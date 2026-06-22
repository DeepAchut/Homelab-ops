#!/bin/bash
# PBS (CT 200 "hl-pbs-backup") config backup -> /mnt/pvedas/pbs-config-backups/
# Run on the Peladn host as ROOT (needs pct + access to /etc/pve).
#
# WHY: CT 200 is the Peladn PBS LXC. It is NOT captured by any vzdump (the Monday
# job only does 201/202/203), so if its rootfs is lost there's no way to rebuild
# it. This backs up ONLY the configuration needed to recreate PBS and re-point it
# at the EXISTING datastores — NOT the actual backup chunk data (that lives in the
# datastores on /mnt/backup-hdd etc. and is itself the backup).
#
# Captures:
#   * pct config 200                  — the LXC definition (mounts, net, rootfs)
#   * CT 200:/etc/proxmox-backup/      — PBS config: datastore.cfg (the repos),
#                                        remote.cfg, acl.cfg, prune.cfg, verify.cfg,
#                                        sync.cfg, user.cfg, domains.cfg, node.cfg,
#                                        and PBS keys/certs (authkey, proxy.pem)
#   * Peladn host /etc/pve/storage.cfg — how PVE connects to PBS (the pbs-* storages)
#
# Handles CT 200 being stopped (the normal state) via `pct mount`, which mounts
# the rootfs without starting the container. Falls back to `pct exec` if running.
#
# Retention: keep last 14.

set -u
CTID=200
DATE=$(date +%Y%m%d-%H%M%S)
DEST=/mnt/pvedas/pbs-config-backups
KEEP=14
EXIT=0

TMP=$(mktemp -d -t pbs-cfg.XXXXXX)
MOUNTED=0
cleanup() {
  if [[ "$MOUNTED" == "1" ]]; then pct unmount "$CTID" 2>/dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

log() { echo "[$(date +%H:%M:%S)] $*"; }

mkdir -p "$DEST" "$TMP/bundle"

# 1. LXC config
log "capturing pct config $CTID..."
if pct config "$CTID" > "$TMP/bundle/lxc-${CTID}.conf" 2>"$TMP/cfg.err"; then
  log "  OK lxc config"
else
  log "  X pct config failed"; cat "$TMP/cfg.err"; EXIT=1
fi

# 2. Host storage.cfg (PVE -> PBS storage definitions)
if cp /etc/pve/storage.cfg "$TMP/bundle/host-storage.cfg" 2>/dev/null; then
  log "  OK host storage.cfg"
else
  log "  ! /etc/pve/storage.cfg not copied (non-fatal)"
fi

# 3. CT 200 PBS config (/etc/proxmox-backup) — config only, no datastore data
STATUS=$(pct status "$CTID" 2>/dev/null | awk '{print $2}')
log "CT $CTID status: ${STATUS:-unknown}"
PBS_SRC=""
if [[ "$STATUS" == "running" ]]; then
  log "  running -> copying via pct exec"
  if pct exec "$CTID" -- tar -C /etc -cf - proxmox-backup > "$TMP/pbs.tar" 2>"$TMP/pbs.err"; then
    tar -C "$TMP/bundle" -xf "$TMP/pbs.tar" 2>/dev/null && PBS_SRC="ok"
  fi
else
  log "  stopped -> mounting rootfs read-only via pct mount"
  if pct mount "$CTID" >"$TMP/mount.log" 2>&1; then
    MOUNTED=1
    ROOTFS="/var/lib/lxc/${CTID}/rootfs"
    if [[ -d "$ROOTFS/etc/proxmox-backup" ]]; then
      cp -a "$ROOTFS/etc/proxmox-backup" "$TMP/bundle/proxmox-backup" && PBS_SRC="ok"
    else
      log "  X $ROOTFS/etc/proxmox-backup not found"
    fi
    pct unmount "$CTID" 2>/dev/null && MOUNTED=0
  else
    log "  X pct mount failed"; cat "$TMP/mount.log"
  fi
fi

if [[ -z "$PBS_SRC" ]]; then
  log "  X could not capture /etc/proxmox-backup"; EXIT=1
else
  # Drop lock files (zero-byte .lck) from the captured config — noise only.
  find "$TMP/bundle/proxmox-backup" -name '*.lck' -delete 2>/dev/null || true
  log "  OK PBS config captured ($(find "$TMP/bundle/proxmox-backup" -type f 2>/dev/null | wc -l) files)"
fi

# 4. Bundle it up
OUT="$DEST/pbs-ct${CTID}-config-$DATE.tar.gz"
if tar -C "$TMP/bundle" -czf "$OUT" . 2>/dev/null; then
  SIZE=$(stat -c%s "$OUT")
  log "OK bundle: $SIZE bytes -> $OUT"
else
  log "X bundle tar failed"; EXIT=1
fi

# 5. retention
log "applying retention (keep last $KEEP)..."
ls -1t "$DEST"/pbs-ct${CTID}-config-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r OLD; do
  log "  removing old: $(basename "$OLD")"
  rm -f "$OLD"
done

log "summary:"
ls -lh "$OUT" 2>/dev/null | sed 's/^/  /'

exit $EXIT
