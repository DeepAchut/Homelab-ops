#!/usr/bin/env bash
# claude-sessions-backup.sh — back up Claude Code session data to the homelab DAS.
#
# RUNS ON THE WINDOWS ADMIN BOX (Git Bash), via a daily Windows Scheduled Task.
# Live copy: C:\Users\Administrator\.claude\claude-sessions-backup.sh
#
# WHY: Claude Code session transcripts (.jsonl) + the auto-memory files live only
# on this laptop at ~/.claude/projects/. They were never backed up — the DAS dir
# /mnt/pvedas/mem0-backups/claude-sessions/ was an empty placeholder. This makes a
# dated tar.gz of the whole projects tree and ships it to the DAS (which is swept
# into the Friday DAS->PBS backup). Surfaces on the mem0 Grafana dashboard via
# homelab_backup_age_seconds{name="mem0-daily-claude-sessions"}.
#
# Captures: ~/.claude/projects/ = every project's .jsonl transcripts AND the
#           memory/ files (MEMORY.md + project_*.md). Excludes settings.json
#           (kept out — it holds secrets and isn't under projects/).
#
# Retention: keep last 14 on the DAS.

set -uo pipefail

SRC_PARENT="/c/Users/Administrator/.claude"
SRC_NAME="projects"
DEST_HOST="root@192.168.4.150"
DEST_DIR="/mnt/pvedas/mem0-backups/claude-sessions"
KEEP=14
DATE="$(date +%Y%m%d-%H%M%S)"
NOW_EPOCH="$(date +%s)"
WINDOW_SECONDS="${CLAUDE_BACKUP_WINDOW:-14400}"   # min seconds between backups (default 4h)
MARKER="$SRC_PARENT/.claude-sessions-backup.last" # stores epoch of last successful backup
LOG="$SRC_PARENT/claude-sessions-backup.log"

log() { echo "$(date +%Y-%m-%dT%H:%M:%S)  $*" | tee -a "$LOG"; }

# Time-window gate. This runs from the Claude Code Stop hook (fires every turn),
# so without a gate it would tar+scp 26 MB on every turn. Instead it backs up at
# most once per WINDOW_SECONDS of ACTIVE use — i.e. each usage burst on this
# non-24h laptop gets its own snapshot, but rapid turns don't thrash it.
# `--force` bypasses the gate for manual runs.
if [[ "${1:-}" != "--force" && -f "$MARKER" ]]; then
  LAST="$(cat "$MARKER" 2>/dev/null || echo 0)"
  if [[ "$LAST" =~ ^[0-9]+$ ]] && (( NOW_EPOCH - LAST < WINDOW_SECONDS )); then
    exit 0
  fi
fi

if [[ ! -d "$SRC_PARENT/$SRC_NAME" ]]; then
  log "FAIL  source $SRC_PARENT/$SRC_NAME not found"; exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ARCHIVE="$TMP/claude-sessions-$DATE.tar.gz"

log "creating archive of $SRC_NAME ..."
# tar from the parent so the archive contains projects/... ; exclude noisy caches
if tar -czf "$ARCHIVE" -C "$SRC_PARENT" \
      --exclude='*/shell-snapshots' --exclude='*/.tmp' \
      "$SRC_NAME" 2>>"$LOG"; then
  SZ=$(stat -c%s "$ARCHIVE" 2>/dev/null || echo 0)
  log "  archive: $SZ bytes"
else
  log "FAIL  tar failed"; exit 1
fi

log "shipping to $DEST_HOST:$DEST_DIR ..."
if scp -o ConnectTimeout=20 -o BatchMode=yes "$ARCHIVE" "$DEST_HOST:$DEST_DIR/" 2>>"$LOG"; then
  log "  OK uploaded $(basename "$ARCHIVE")"
else
  log "FAIL  scp failed (is the DAS host reachable / SSH key present?)"; exit 1
fi

# Prune old archives on the DAS (keep newest $KEEP).
ssh -o ConnectTimeout=20 -o BatchMode=yes "$DEST_HOST" \
  "ls -1t $DEST_DIR/claude-sessions-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f" \
  2>>"$LOG" && log "  retention applied (keep $KEEP)"

# Record the backup time only after a successful upload (so a failed run retries
# on the next turn instead of waiting out the whole window).
echo "$NOW_EPOCH" > "$MARKER"
log "done"
