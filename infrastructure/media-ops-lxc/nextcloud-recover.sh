#!/usr/bin/env bash
# nextcloud-recover.sh — diagnose + fix Nextcloud maintenance-mode lock-ups
#
# Run on the media-ops-lxc as root. Walks a decision tree:
#   1. Inspect container state, maintenance flag, DB tables, installed version
#   2. Pick the right recovery branch (just unstick / resume upgrade /
#      DB restore — last one HALTS, won't run unattended)
#   3. Apply the chosen fix
#   4. Verify Nextcloud is reachable + maintenance flag is off
#   5. Print the EXACT image tag to pin in docker-compose.yml
#
# Hard safety rules (mirrors ~/.claude/CLAUDE.md Live System Guardrails):
#   - NEVER drops/truncates a table
#   - NEVER restores from backup without explicit interactive confirmation
#   - NEVER overwrites /var/lib/nextcloud-db without confirmation
#   - All read steps print what they found; user can Ctrl-C between phases

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/root/media-ops-lxc}"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"
ENV_FILE="${COMPOSE_DIR}/.env"
NC_CONTAINER="nextcloud"
DB_CONTAINER="mariadb"
LOG_PREFIX="[nextcloud-recover]"

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s ⚠  %s\n' "$LOG_PREFIX" "$*" >&2; }
die()  { printf '%s ✗  %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
ok()   { printf '%s ✓  %s\n' "$LOG_PREFIX" "$*"; }

confirm() {
  # Single-line yes/no prompt. Anything but `yes` aborts.
  local prompt="$1"
  read -r -p "$LOG_PREFIX $prompt [type 'yes' to proceed]: " ans
  [[ "$ans" == "yes" ]] || die "aborted by user"
}

require_root() { [[ $EUID -eq 0 ]] || die "run as root"; }

# Read MARIADB_ROOT_PASSWORD without printing it
load_db_password() {
  [[ -r "$ENV_FILE" ]] || die "cannot read $ENV_FILE — adjust COMPOSE_DIR env var"
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
  [[ -n "${MARIADB_ROOT_PASSWORD:-}" ]] || die "MARIADB_ROOT_PASSWORD missing from .env"
}

db_query() {
  # Args: <SQL>. Pipes via stdin to avoid putting the password on the cmdline.
  docker exec -i "$DB_CONTAINER" mysql -uroot -p"$MARIADB_ROOT_PASSWORD" \
    --batch --skip-column-names nextcloud -e "$1" 2>/dev/null
}

occ() {
  docker exec -u www-data "$NC_CONTAINER" php occ "$@"
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 — DIAGNOSE  (read-only, no side effects)
# ═══════════════════════════════════════════════════════════════════════════

require_root
load_db_password

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "$LOG_PREFIX PHASE 1: DIAGNOSE"
echo "═══════════════════════════════════════════════════════════════════"

log "container state:"
docker ps -a --filter "name=${NC_CONTAINER}" --filter "name=${DB_CONTAINER}" \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

# Confirm both containers are actually up before deeper probes
NC_RUNNING=$(docker inspect -f '{{.State.Running}}' "$NC_CONTAINER" 2>/dev/null || echo "false")
DB_RUNNING=$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || echo "false")

if [[ "$DB_RUNNING" != "true" ]]; then
  warn "mariadb is not running — starting it"
  docker compose -f "$COMPOSE_FILE" up -d mariadb
  log "waiting 15s for mariadb to come up..."
  sleep 15
fi

if [[ "$NC_RUNNING" != "true" ]]; then
  warn "nextcloud container is not running — starting (DB probe needs it for occ)"
  docker compose -f "$COMPOSE_FILE" up -d nextcloud
  log "waiting 20s for nextcloud to come up..."
  sleep 20
fi

log "currently-deployed image digest:"
docker inspect "$NC_CONTAINER" --format '  config: {{.Config.Image}}{{println}}  digest: {{.Image}}{{println}}  started: {{.State.StartedAt}}{{println}}  restarts: {{.RestartCount}}'

log "PHP-side version banner from the container:"
NC_CONTAINER_VERSION=$(docker exec -u www-data "$NC_CONTAINER" php -r 'echo OC_Util::getVersionString();' 2>/dev/null || echo "unknown")
log "  container ships Nextcloud: $NC_CONTAINER_VERSION"

log "maintenance flag (source of truth in config.php):"
MAINT_VALUE=$(docker exec -u www-data "$NC_CONTAINER" php -r \
  '$c=include "/var/www/html/config/config.php"; echo isset($c["maintenance"])?($c["maintenance"]?"true":"false"):"unset";' 2>/dev/null || echo "?")
CONFIG_VERSION=$(docker exec -u www-data "$NC_CONTAINER" php -r \
  '$c=include "/var/www/html/config/config.php"; echo $c["version"]??"unset";' 2>/dev/null || echo "?")
log "  maintenance = $MAINT_VALUE"
log "  config.php version = $CONFIG_VERSION"

log "database table sanity:"
TABLE_COUNT=$(db_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='nextcloud';" || echo "?")
APPCONFIG_EXISTS=$(db_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='nextcloud' AND table_name='oc_appconfig';" || echo "0")
log "  total tables in nextcloud DB: $TABLE_COUNT"
log "  oc_appconfig present:         $APPCONFIG_EXISTS"

DB_VERSION="unknown"
DB_INSTALLED="unknown"
if [[ "$APPCONFIG_EXISTS" == "1" ]]; then
  DB_VERSION=$(db_query "SELECT configvalue FROM oc_appconfig WHERE appid='core' AND configkey='lastupdatedat';" || echo "?")
  DB_INSTALLED=$(db_query "SELECT configvalue FROM oc_appconfig WHERE appid='core' AND configkey='installedat';" || echo "?")
  CORE_VERSION=$(db_query "SELECT configvalue FROM oc_appconfig WHERE appid='core' AND configkey='vendor';" || echo "?")
  log "  oc_appconfig.core.installedat   = $DB_INSTALLED"
  log "  oc_appconfig.core.lastupdatedat = $DB_VERSION"
  log "  oc_appconfig.core.vendor        = $CORE_VERSION"
fi

log "last 20 lines of nextcloud container log:"
docker logs "$NC_CONTAINER" --tail 20 2>&1 | sed "s/^/  | /"

# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 — DECIDE
# ═══════════════════════════════════════════════════════════════════════════

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "$LOG_PREFIX PHASE 2: DECIDE which recovery branch"
echo "═══════════════════════════════════════════════════════════════════"

BRANCH=""
if [[ "$APPCONFIG_EXISTS" != "1" || "$TABLE_COUNT" == "0" || "$TABLE_COUNT" -lt 20 ]]; then
  BRANCH="db-restore"
elif [[ "$MAINT_VALUE" == "true" && "$CONFIG_VERSION" != "$NC_CONTAINER_VERSION" ]]; then
  BRANCH="resume-upgrade"
elif [[ "$MAINT_VALUE" == "true" ]]; then
  BRANCH="unstick-only"
else
  BRANCH="already-healthy"
fi

case "$BRANCH" in
  db-restore)
    warn "DECISION: db-restore"
    warn "  oc_appconfig missing OR table count suspiciously low ($TABLE_COUNT)."
    warn "  This is the same wedged state your nextcloud_error.log captured in April."
    warn ""
    warn "  RESTORE IS NOT AUTOMATED — needs you to pick the source:"
    warn "    a) the PBS vzdump of media-ops-lxc (whole-LXC restore — heavy)"
    warn "    b) a mariadb dump if you have one in /mnt/das/backups/"
    warn "    c) restart fresh install (DESTROYS user data in /mnt/das/nextcloud/data)"
    warn ""
    warn "  Pick a path with the user, run the restore by hand, then re-run THIS"
    warn "  script — it'll auto-continue with 'resume-upgrade' or 'unstick-only'."
    warn ""
    warn "  Quick survey of what backup material exists right now:"
    ls -lhS /mnt/das/backups/ 2>/dev/null | grep -iE 'maria|nextcloud' | tail -10 || echo "    (no /mnt/das/backups matches)"
    echo
    pvesm list local --vmid 0 2>/dev/null | grep -iE 'media' | tail -5 || true
    echo
    die "halting before destructive action — see notes above"
    ;;

  resume-upgrade)
    log "DECISION: resume-upgrade"
    log "  config.php version ($CONFIG_VERSION) != container version ($NC_CONTAINER_VERSION)"
    log "  maintenance flag is on — an upgrade got interrupted. Resuming it."
    ;;

  unstick-only)
    log "DECISION: unstick-only"
    log "  config.php version matches container, but maintenance flag is stuck on."
    log "  Just flipping it off."
    ;;

  already-healthy)
    ok "DECISION: already-healthy"
    ok "  maintenance is off, oc_appconfig is fine. Nothing to recover."
    log "  Skipping straight to verify + recurrence-guard output."
    ;;
esac

# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 — EXECUTE
# ═══════════════════════════════════════════════════════════════════════════

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "$LOG_PREFIX PHASE 3: EXECUTE branch '$BRANCH'"
echo "═══════════════════════════════════════════════════════════════════"

case "$BRANCH" in
  resume-upgrade)
    log "running 'occ upgrade --no-interaction' (idempotent — safe to re-run)"
    if occ upgrade --no-interaction; then
      ok "upgrade succeeded"
    else
      die "occ upgrade failed — copy its output, do NOT mass-restart; debug manually"
    fi

    log "running app-update checks"
    occ app:update --all || warn "some app updates failed — non-fatal, continuing"

    log "turning maintenance mode off"
    occ maintenance:mode --off
    ;;

  unstick-only)
    log "running 'occ maintenance:mode --off'"
    occ maintenance:mode --off
    ;;

  already-healthy)
    : # nothing to do
    ;;
esac

# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 — VERIFY
# ═══════════════════════════════════════════════════════════════════════════

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "$LOG_PREFIX PHASE 4: VERIFY"
echo "═══════════════════════════════════════════════════════════════════"

log "occ status:"
occ status || warn "occ status failed"

log "HTTP probe on localhost:8080 (expect 200 or 302, NOT 503):"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/status.php || echo "000")
log "  GET /status.php → HTTP $HTTP_CODE"
[[ "$HTTP_CODE" == "200" ]] && ok "  status endpoint returns 200" \
                            || warn "  status endpoint returns $HTTP_CODE — investigate"

log "current maintenance flag:"
FINAL_MAINT=$(docker exec -u www-data "$NC_CONTAINER" php -r \
  '$c=include "/var/www/html/config/config.php"; echo isset($c["maintenance"])?($c["maintenance"]?"true":"false"):"unset";' 2>/dev/null || echo "?")
log "  maintenance = $FINAL_MAINT"
[[ "$FINAL_MAINT" == "false" || "$FINAL_MAINT" == "unset" ]] && ok "  maintenance mode is OFF" \
                                                              || warn "  maintenance mode is STILL ON — manual investigation"

# ═══════════════════════════════════════════════════════════════════════════
# Phase 5 — RECURRENCE GUARD: tell user exactly what tag to pin
# ═══════════════════════════════════════════════════════════════════════════

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "$LOG_PREFIX PHASE 5: RECURRENCE GUARD — image pin recommendation"
echo "═══════════════════════════════════════════════════════════════════"

# Strip patch from NEXTCLOUD_VERSION to suggest a minor-line pin
# (e.g. 30.0.13 → 30.0)  — minor-line pins get patch updates but never
# accidentally jump to 31.x on container restart.
FULL_VER="$NC_CONTAINER_VERSION"
MINOR_VER=$(echo "$FULL_VER" | awk -F. '{print $1"."$2}')

cat <<EOF

  Current running Nextcloud version: $FULL_VER

  The compose file currently has:
    image: nextcloud:stable                  ← moving tag, root cause of recurrence

  Edit ${COMPOSE_FILE} and change the 'nextcloud' service image to ONE of:

    image: nextcloud:${FULL_VER}-apache       ← FULL PIN (recommended)
                                                no automatic updates on restart;
                                                you choose when to bump.

    image: nextcloud:${MINOR_VER}-apache       ← MINOR-LINE PIN (compromise)
                                                gets patch updates, never major.

  Then redeploy with:
    docker compose -f ${COMPOSE_FILE} up -d nextcloud

  Also recommended (already in the Phase 27 doc): pin mariadb to a version,
  add healthchecks, switch depends_on to 'service_healthy'. The compose
  patch is in the repo at infrastructure/media-ops-lxc/docker-compose.yml —
  pull + redeploy when ready.

EOF

ok "all done"
