#!/bin/bash
# rpi4 PVC dumps -> /mnt/pvedas/k8s-backups/
# Run on Peladn as the n8n-backup user (invoked by the n8n "rpi4 PVC Dumps" workflow, Sat 1AM).
#
# WHY this script exists: the rpi4 Talos worker is a physical node, NOT a Proxmox
# VM, so its local-path PVCs are never captured by vzdump. This takes logical
# dumps of the databases that live on rpi4 local-path and writes them to the DAS
# (/mnt/pvedas/k8s-backups), which is then swept into the Friday DAS PBS backup.
#
# What it backs up:
#   * mem0 qdrant — every collection (snapshot via API). mem0 stores all its
#     vectors+payloads in qdrant; postgres is configured but unused.
#   * mem0 postgres — logical pg_dump (currently empty; kept to catch future use).
#   * miniflux postgres — logical pg_dump.
#   * n8n postgres — logical pg_dump. ADDED 2026-06-21 after n8n migrated off
#     SQLite-on-NFS to Postgres-on-local-path (it was previously swept in via the
#     NFS DAS backup; now it lives on rpi4 local-path and nothing else captures it).
#   * karakeep postgres — logical pg_dump (currently EMPTY; karakeep's real data is
#     SQLite on the NFS assets PVC, already in the DAS backup. Kept to catch future use).
#   * n8n filesystem extras — the pg dump covers workflows/credentials/executions,
#     but two things live ONLY on n8n's PVCs: the community-node manifest
#     (/home/node/.n8n/nodes/package*.json — tells a restore which nodes to
#     reinstall, e.g. n8n-nodes-proxmox, n8n-nodes-wake-on-lan) and user files
#     under /home/data (e.g. csvs/). Tarred together. Intentionally EXCLUDED:
#     the encryption key (config) — it's in secret.enc.yaml (SOPS/git); the legacy
#     database.sqlite (obsolete post-Postgres migration); nodes/node_modules
#     (reinstallable from the manifest); binaryData (empty / DB-mode).
#
# Retention: keep last 14 per prefix.

set -u  # don't -e; per-section errors handled explicitly
DATE=$(date +%Y%m%d-%H%M%S)
DEST=/mnt/pvedas/k8s-backups
KEEP=14
EXIT=0

TMP=$(mktemp -d -t rpi4-pvc.XXXXXX)
PF_PID=""
cleanup() {
  if [[ -n "$PF_PID" ]]; then kill "$PF_PID" 2>/dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Logical pg_dump of a postgres pod that exposes POSTGRES_USER/POSTGRES_DB in its env.
# Args: <namespace> <pod> <output-prefix> [min-size-bytes]
dump_pg() {
  local ns="$1" pod="$2" prefix="$3" minsize="${4:-0}"
  local out="$DEST/${prefix}-$DATE.sql.gz"
  log "dumping ${prefix} (${ns}/${pod})..."
  if kubectl exec -n "$ns" "$pod" -- \
       bash -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
       2>"$TMP/${prefix}.err" | gzip > "$out"; then
    local size; size=$(stat -c%s "$out")
    if [[ "$size" -lt "$minsize" ]]; then
      log "  X ${prefix} dump suspiciously small ($size bytes)"
      cat "$TMP/${prefix}.err"
      EXIT=1
    else
      log "  OK ${prefix}: $size bytes"
    fi
  else
    log "  X ${prefix} dump failed"
    cat "$TMP/${prefix}.err"
    EXIT=1
  fi
}

mkdir -p "$DEST"
cd "$TMP" || exit 1

# ---------- 1. mem0 postgres (logical, even if empty) ----------
dump_pg mem0 postgres-0 mem0-postgres 0

# ---------- 2. mem0 qdrant snapshot — via port-forward ----------
log "snapshotting mem0 qdrant..."
LPORT=16333
kubectl port-forward -n mem0 svc/qdrant ${LPORT}:6333 >"$TMP/pf.log" 2>&1 &
PF_PID=$!
# Wait for the port-forward to be ready (poll, max ~5s)
for i in $(seq 1 10); do
  if curl -sfm 1 "http://127.0.0.1:${LPORT}/" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
if ! curl -sfm 2 "http://127.0.0.1:${LPORT}/" >/dev/null 2>&1; then
  log "  X qdrant port-forward never came up"
  cat "$TMP/pf.log"
  EXIT=1
else
  log "  port-forward up on 127.0.0.1:${LPORT}"
  COLLECTIONS=$(curl -sfm 10 "http://127.0.0.1:${LPORT}/collections" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ".join(c["name"] for c in d["result"]["collections"]))')
  if [[ -z "$COLLECTIONS" ]]; then
    log "  ! qdrant has no collections — skipping"
  else
    log "  collections: $COLLECTIONS"
    for COL in $COLLECTIONS; do
      SNAP_JSON=$(curl -sfm 120 -X POST "http://127.0.0.1:${LPORT}/collections/$COL/snapshots")
      SNAP_NAME=$(echo "$SNAP_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["result"]["name"])' 2>/dev/null || true)
      if [[ -z "$SNAP_NAME" ]]; then
        log "  X qdrant $COL snapshot create returned no name: $SNAP_JSON"
        EXIT=1
        continue
      fi
      log "  snapshot created in pod: $SNAP_NAME"
      OUT="$DEST/mem0-qdrant-${COL}-$DATE.snapshot"
      if curl -sfm 300 -o "$OUT" "http://127.0.0.1:${LPORT}/collections/$COL/snapshots/$SNAP_NAME"; then
        Q_SIZE=$(stat -c%s "$OUT")
        log "  OK qdrant $COL: $Q_SIZE bytes -> $OUT"
        # delete the in-pod snapshot to free disk
        curl -sfm 30 -X DELETE "http://127.0.0.1:${LPORT}/collections/$COL/snapshots/$SNAP_NAME" >/dev/null || true
      else
        log "  X qdrant $COL snapshot download failed"
        EXIT=1
      fi
    done
  fi
fi

# Tear down port-forward early (the trap will also catch it, but be tidy)
if [[ -n "$PF_PID" ]]; then kill "$PF_PID" 2>/dev/null || true; PF_PID=""; fi

# ---------- 3. miniflux postgres ----------
log "dumping miniflux postgres..."
MF_POD=$(kubectl -n miniflux get pod -l app=miniflux-db -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -z "$MF_POD" ]]; then
  MF_POD=$(kubectl -n miniflux get pods -o name | grep -m1 miniflux-db | sed 's|pod/||')
fi
if [[ -z "$MF_POD" ]]; then
  log "  X could not find miniflux-db pod"
  EXIT=1
else
  dump_pg miniflux "$MF_POD" miniflux-postgres 1000
fi

# ---------- 4. n8n postgres (the workflow DB — local-path on rpi4, nothing else backs it up) ----------
dump_pg n8n n8n-postgres-0 n8n-postgres 1000

# ---------- 4b. n8n filesystem extras (NOT in the pg dump): community-node manifest + /home/data ----------
log "archiving n8n filesystem extras (community-node manifest + /home/data)..."
N8N_FILES_OUT="$DEST/n8n-files-$DATE.tar.gz"
# -C / + relative paths so the archive restores cleanly with `tar xzf - -C /`.
if kubectl exec -n n8n deploy/n8n -- tar czf - -C / \
     home/data \
     home/node/.n8n/nodes/package.json \
     home/node/.n8n/nodes/package-lock.json \
     2>"$TMP/n8n-files.err" > "$N8N_FILES_OUT"; then
  NF_SIZE=$(stat -c%s "$N8N_FILES_OUT")
  if [[ "$NF_SIZE" -lt 200 ]]; then
    log "  X n8n-files archive suspiciously small ($NF_SIZE bytes)"
    cat "$TMP/n8n-files.err"
    EXIT=1
  else
    log "  OK n8n-files: $NF_SIZE bytes"
  fi
else
  log "  X n8n-files archive failed"
  cat "$TMP/n8n-files.err"
  EXIT=1
fi

# ---------- 5. karakeep postgres (currently empty; real data is SQLite on NFS assets PVC) ----------
dump_pg karakeep postgres-0 karakeep-postgres 0

# ---------- 6. retention ----------
log "applying retention (keep last $KEEP per prefix)..."
for PREFIX in mem0-postgres mem0-qdrant-mem0 miniflux-postgres n8n-postgres n8n-files karakeep-postgres; do
  ls -1t "$DEST"/${PREFIX}-* 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r OLD; do
    log "  removing old: $(basename "$OLD")"
    rm -f "$OLD"
  done
done

# ---------- 7. summary ----------
log "summary (this run's files):"
ls -lh "$DEST"/*-$DATE.* 2>/dev/null | sed 's/^/  /'
log "free space:"
df -h "$DEST" | sed 's/^/  /'

exit $EXIT
