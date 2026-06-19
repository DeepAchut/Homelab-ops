#!/usr/bin/env bash
# nextcloud-das-recover.sh — recover Nextcloud after the DAS USB drive flaps
#
# RUN ON THE PELADN PROXMOX HOST (prop, 192.168.4.150), as root — NOT inside
# the LXC. It uses `pct`.
#
# THE FAILURE MODE THIS FIXES (observed 2026-06-19):
#   The Nextcloud data lives on a USB-attached DAS drive (Realtek USB-SATA
#   bridge enclosure — known flaky, flagged for replacement). When that drive
#   briefly drops off the USB bus:
#     1. kernel logs `usb X-Y: USB disconnect` + `I/O error, dev sdX` +
#        `XFS (sdX): log I/O error -19`
#     2. the drive re-enumerates under a NEW letter (e.g. sdc → sdd) and the
#        host re-mounts it at /mnt/pvedas (it has x-systemd.automount)
#     3. BUT the LXC 202 bind mount (mp0: /mnt/pvedas -> /mnt/das) still points
#        at the DEAD mount instance — it's stale. The host is healthy; the LXC
#        and every Docker container under it see "Input/output error" on
#        /mnt/das. Nextcloud then reports "data directory invalid / .ncdata
#        missing" and serves HTTP 500.
#
#   Your DATA is NOT lost in this scenario — it's intact on the healthy drive.
#   The DB is on the LXC rootfs (separate disk) and is also unaffected. The
#   ONLY broken thing is the stale bind mount. The reliable fix is to restart
#   the LXC, which re-establishes mp0/mp1/mp2 against the now-healthy host
#   mount. Restarting just the Docker container does NOT work — it re-binds the
#   same stale LXC mount.
#
# WHAT THIS SCRIPT DOES (safe, read-mostly, one disruptive step gated):
#   1. Confirm the host's /mnt/pvedas is healthy (reads .ncdata)
#   2. Confirm the DAS drive SMART is PASSED (don't reboot onto a dying disk)
#   3. Confirm the LXC actually has the stale-mount symptom (I/O error)
#   4. `pct reboot 202` (the only disruptive step — restarts ALL services in
#      that LXC: Immich, Jellyfin, Webtop, Nextcloud, Alloy). Gated behind a
#      yes/no prompt unless you pass --yes.
#   5. Wait for the stack to come back, verify the container sees .ncdata and
#      `occ status` is clean.
#
# USAGE:
#   bash nextcloud-das-recover.sh           # interactive (prompts before reboot)
#   bash nextcloud-das-recover.sh --yes     # non-interactive (CI / cron)

set -euo pipefail

LXC_ID="${LXC_ID:-202}"
HOST_DAS="${HOST_DAS:-/mnt/pvedas}"            # where the host mounts the DAS
NC_DATA_REL="${NC_DATA_REL:-nextcloud/data}"  # data dir under the DAS root
DAS_DEV="${DAS_DEV:-/dev/sdd}"                 # current letter — may change after a flap
AUTO_YES="no"
[[ "${1:-}" == "--yes" ]] && AUTO_YES="yes"

P="[nc-das-recover]"
log(){ printf '%s %s\n' "$P" "$*"; }
ok(){  printf '%s ✓ %s\n' "$P" "$*"; }
warn(){ printf '%s ⚠ %s\n' "$P" "$*" >&2; }
die(){ printf '%s ✗ %s\n' "$P" "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root on the Proxmox host"
command -v pct >/dev/null || die "pct not found — run this on the Proxmox host, not the LXC"

echo "═══════════════════════════════════════════════════════════"
echo "$P PHASE 1 — is the host's DAS mount healthy?"
echo "═══════════════════════════════════════════════════════════"

NCDATA="${HOST_DAS}/${NC_DATA_REL}/.ncdata"
if head -c 32 "$NCDATA" >/dev/null 2>&1; then
  ok "host reads ${NCDATA}:"
  sed 's/^/    /' "$NCDATA"
else
  warn "host CANNOT read ${NCDATA}"
  warn "  The DAS mount itself is down on the HOST. This script only fixes a"
  warn "  stale LXC bind over a HEALTHY host mount. First get the host mount"
  warn "  back: check 'dmesg | tail', 'lsblk', re-seat/replace the USB enclosure,"
  warn "  then 'mount ${HOST_DAS}' (it has x-systemd.automount, so an 'ls ${HOST_DAS}'"
  warn "  may trigger it). Re-run this script once the host can read .ncdata."
  die "host DAS mount not healthy — halting before any reboot"
fi

echo
echo "═══════════════════════════════════════════════════════════"
echo "$P PHASE 2 — is the DAS drive actually healthy (SMART)?"
echo "═══════════════════════════════════════════════════════════"
# Seagate USB externals hide SMART behind -d sat (see reference_drives memory).
SMART=$(smartctl -d sat -H "$DAS_DEV" 2>/dev/null | grep -iE 'overall-health|result' || true)
if echo "$SMART" | grep -qi passed; then
  ok "SMART: $SMART"
else
  warn "SMART check inconclusive or FAILED for $DAS_DEV:"
  warn "  ${SMART:-<no output — wrong device letter? check lsblk>}"
  warn "  If the drive is genuinely failing, DO NOT reboot onto it — restore"
  warn "  from backup instead. If it just flapped (SMART actually fine but the"
  warn "  letter changed), set DAS_DEV=/dev/sdX and re-run."
  if [[ "$AUTO_YES" != "yes" ]]; then
    read -r -p "$P SMART not confirmed PASSED. Continue to reboot anyway? [type 'yes']: " a
    [[ "$a" == "yes" ]] || die "aborted — verify the drive first"
  fi
fi

echo
echo "═══════════════════════════════════════════════════════════"
echo "$P PHASE 3 — does the LXC actually have the stale-mount symptom?"
echo "═══════════════════════════════════════════════════════════"
if pct exec "$LXC_ID" -- ls "/mnt/das/${NC_DATA_REL}/.ncdata" >/dev/null 2>&1; then
  ok "LXC ${LXC_ID} can already read /mnt/das — mount is NOT stale."
  warn "  Nothing to fix at the mount layer. If Nextcloud is still unhappy,"
  warn "  the issue is elsewhere (check 'docker logs nextcloud')."
  exit 0
else
  warn "LXC ${LXC_ID} gets I/O error on /mnt/das — confirmed stale bind mount."
fi

echo
echo "═══════════════════════════════════════════════════════════"
echo "$P PHASE 4 — refresh the bind mount via LXC reboot"
echo "═══════════════════════════════════════════════════════════"
warn "pct reboot ${LXC_ID} restarts ALL services in this LXC (Immich, Jellyfin,"
warn "Webtop, Nextcloud, Alloy). ~1-2 min. Graceful; touches no data."
if [[ "$AUTO_YES" != "yes" ]]; then
  read -r -p "$P proceed with 'pct reboot ${LXC_ID}'? [type 'yes']: " a
  [[ "$a" == "yes" ]] || die "aborted by user"
fi
log "rebooting LXC ${LXC_ID}..."
pct reboot "$LXC_ID"

echo
echo "═══════════════════════════════════════════════════════════"
echo "$P PHASE 5 — wait + verify"
echo "═══════════════════════════════════════════════════════════"
log "waiting for the stack to come back..."
for i in $(seq 1 24); do
  sleep 5
  if pct exec "$LXC_ID" -- docker exec nextcloud ls "/var/www/html/data/.ncdata" >/dev/null 2>&1; then
    ok "container sees .ncdata after ~$((i*5))s"
    break
  fi
  [[ $i -eq 24 ]] && die "timed out after 120s — check 'pct status ${LXC_ID}' and 'docker logs nextcloud'"
done

log "occ status:"
pct exec "$LXC_ID" -- docker exec -u www-data nextcloud php occ status 2>&1 | sed 's/^/    /'

MAINT=$(pct exec "$LXC_ID" -- docker exec -u www-data nextcloud php occ maintenance:mode 2>&1 || true)
log "maintenance: $MAINT"
case "$MAINT" in
  *disabled*) ok "maintenance mode is OFF" ;;
  *) warn "maintenance still on — turning it off"
     pct exec "$LXC_ID" -- docker exec -u www-data nextcloud php occ maintenance:mode --off ;;
esac

HTTP=$(pct exec "$LXC_ID" -- docker exec nextcloud curl -s -o /dev/null -w '%{http_code}' http://localhost/status.php 2>&1 || echo "000")
log "HTTP status.php → $HTTP"
[[ "$HTTP" == "200" ]] && ok "Nextcloud is serving (HTTP 200)" || warn "status.php returned $HTTP — investigate"

ok "done"
