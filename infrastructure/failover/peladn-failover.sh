#!/usr/bin/env bash
# ============================================================================
# Peladn -> Evo-X2 failover restore.
# GitOps source of truth:
#   https://github.com/DeepAchut/Homelab-ops/blob/main/infrastructure/failover/peladn-failover.sh
#
# Triggered by the n8n "peladn-failover" workflow (manual / confirmed) so that
# triggering + notification are managed in one place. n8n pulls THIS file from
# the repo at run time (curl raw) and executes it on the Evo-X2 host.
#
# Restores guests from the LOCAL PBS (storage `pbs-local` -> CT200 on Evo-X2).
# The vzdump rootfs already contains the critical data (vaultwarden, HA config,
# npm, immich-db, nextcloud-db); bulk media is rehydrated on demand
# (see Phase-21-Part-2 §5). Run ON the Evo-X2 PVE host.
# ============================================================================
set -euo pipefail

PBS=pbs-local
TARGET=local-lvm
PELADN_API="https://192.168.4.150:8006/api2/json/version"
LOG=/var/log/peladn-failover.log

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
latest(){ pvesm list "$PBS" | awk -v t="$1" -v id="$2" '$1 ~ "backup/"t"/"id"/" {print $1}' | sort | tail -1; }

# --- split-brain guard: refuse if Peladn is still alive (override with FORCE=1) ---
if [ "${FORCE:-0}" != "1" ] && curl -ksf --max-time 8 "$PELADN_API" >/dev/null 2>&1; then
  log "ABORT: Peladn API still reachable -> refusing failover (would duplicate IPs .12/.13/.172)."
  log "       Set FORCE=1 only if you are certain Peladn's guests are stopped."
  exit 3
fi

mkdir -p /mnt/das /mnt/sg-ext-hdd /mnt/wd-ext-hdd   # bind-mount stubs so CTs can start

log "=== Peladn failover START ==="

# Tier 1 — Talos CP + home-ops (rootfs already holds vault/HA/npm + their data)
V=$(latest vm 201);  log "restore VM 201 <= $V";  qmrestore "$V" 201 --storage "$TARGET" --force 1
qm set 201 --cpu x86-64-v2-AES
C3=$(latest ct 203); log "restore CT203 <= $C3"; pct restore 203 "$C3" --storage "$TARGET" --force 1
qm start 201; pct start 203
log "Tier-1 up: Talos CP + home-ops (.13) — vault/HA/npm + DBs are in the restored rootfs"

# Tier 2 — media-ai (DBs in rootfs; bulk media via on-demand pxar restore, Part 2 §5)
C2=$(latest ct 202); log "restore CT202 <= $C2"; pct restore 202 "$C2" --storage "$TARGET" --force 1
pct start 202

log "=== core failover COMPLETE — verify: kubectl get nodes ; bulk media via Part 2 §5 ==="
