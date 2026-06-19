#!/usr/bin/env bash
# das-mount-watchdog.sh — auto-heal a stale LXC bind mount after a DAS USB flap.
#
# Runs on the Peladn Proxmox host (prop) on a 2-minute systemd timer.
#
# THE CONDITION IT FIXES:
#   When the USB DAS drive flaps off the bus and re-enumerates, the host
#   re-mounts it at /mnt/pvedas (healthy), but LXC 202's bind mount
#   (mp0: /mnt/pvedas -> /mnt/das) is left pointing at the dead mount instance.
#   Result: host reads the data fine, but the LXC + every container under it get
#   "Input/output error" -> Nextcloud/Immich serve HTTP 500 until someone
#   notices and reboots the LXC. This watchdog notices in <=2 min and reboots
#   LXC 202 automatically, turning a multi-hour outage into a ~90s blip.
#
# IT IS DELIBERATELY CONSERVATIVE — it only acts on the EXACT stale-mount
# signature and rate-limits itself:
#   - host CAN read .ncdata           (host mount healthy)  AND
#   - LXC CANNOT read .ncdata (EIO)   (LXC bind stale)
#   => recover by `pct reboot 202`, at most once per RATE_LIMIT_S.
#
#   If the HOST itself can't read .ncdata, the drive is fully gone — rebooting
#   the LXC won't help, so it only logs + notifies (a human/replug is needed).
#   If both host and LXC are healthy, it does nothing.

set -uo pipefail

LXC_ID="${LXC_ID:-202}"
HOST_NCDATA="${HOST_NCDATA:-/mnt/pvedas/nextcloud/data/.ncdata}"
LXC_NCDATA="${LXC_NCDATA:-/mnt/das/nextcloud/data/.ncdata}"
RATE_LIMIT_S="${RATE_LIMIT_S:-900}"          # don't reboot more than once per 15 min
STAMP="/run/das-mount-watchdog.last"
GOTIFY_URL="${GOTIFY_URL:-http://192.168.4.13:8800}"
GOTIFY_TOKEN_FILE="${GOTIFY_TOKEN_FILE:-/etc/das-watchdog-gotify.token}"

log(){ logger -t das-watchdog "$*"; echo "das-watchdog: $*"; }

notify(){
  # Best-effort Gotify push. No-op if the token file is absent.
  local title="$1" msg="$2" prio="${3:-7}"
  [ -r "$GOTIFY_TOKEN_FILE" ] || return 0
  local tok; tok="$(cat "$GOTIFY_TOKEN_FILE")"
  curl -fsS -m 8 -X POST "$GOTIFY_URL/message?token=$tok" \
    -F "title=$title" -F "message=$msg" -F "priority=$prio" >/dev/null 2>&1 || true
}

# --- health checks -----------------------------------------------------------
host_ok="no"; lxc_ok="no"
head -c 8 "$HOST_NCDATA" >/dev/null 2>&1 && host_ok="yes"
pct exec "$LXC_ID" -- head -c 8 "$LXC_NCDATA" >/dev/null 2>&1 && lxc_ok="yes"

# Case 1: everything healthy — nothing to do (quiet; no log spam)
if [ "$host_ok" = "yes" ] && [ "$lxc_ok" = "yes" ]; then
  exit 0
fi

# Case 2: host mount itself is down — LXC reboot won't help. Alert only.
if [ "$host_ok" != "yes" ]; then
  log "HOST mount unhealthy ($HOST_NCDATA unreadable) — DAS fully dropped. Manual intervention / replug needed; NOT rebooting LXC."
  notify "DAS DOWN on Peladn" "Host cannot read $HOST_NCDATA — the USB DAS dropped and did not re-mount. Nextcloud/Immich are down until the drive is back. Check 'dmesg', re-seat the enclosure." 9
  exit 1
fi

# Case 3: host healthy but LXC stale — THE recoverable signature.
log "stale LXC bind detected (host OK, LXC EIO on $LXC_NCDATA)"

# Rate limit
now="$(date +%s)"
if [ -f "$STAMP" ]; then
  last="$(cat "$STAMP" 2>/dev/null || echo 0)"
  if [ $(( now - last )) -lt "$RATE_LIMIT_S" ]; then
    log "within rate-limit window ($RATE_LIMIT_S s) since last recovery — skipping reboot this tick"
    exit 0
  fi
fi
echo "$now" > "$STAMP"

log "recovering: pct reboot $LXC_ID"
notify "DAS auto-recover on Peladn" "USB DAS flapped; LXC $LXC_ID bind mount went stale. Auto-rebooting LXC $LXC_ID to restore Nextcloud/Immich." 7
pct reboot "$LXC_ID"

# Verify within ~120s
for i in $(seq 1 24); do
  sleep 5
  if pct exec "$LXC_ID" -- head -c 8 "$LXC_NCDATA" >/dev/null 2>&1; then
    log "recovered after ~$(( i * 5 ))s — LXC can read the DAS again"
    notify "DAS recovered on Peladn" "LXC $LXC_ID rebooted; data mount is healthy again." 5
    exit 0
  fi
done

log "ERROR: LXC $LXC_ID still cannot read the DAS 120s after reboot — needs a human"
notify "DAS recovery FAILED on Peladn" "Rebooted LXC $LXC_ID but it still can't read $LXC_NCDATA after 120s. Investigate." 10
exit 1
