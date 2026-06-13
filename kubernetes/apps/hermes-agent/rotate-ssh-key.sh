#!/usr/bin/env bash
# rotate-ssh-key.sh — full SSH-key rotation for Hermes Agent admin v2.
#
# Generates a fresh ed25519 keypair (or reuses one you point at), updates
# ~/.ssh/authorized_keys on the managed hosts (removing any prior
# hermes-agent@homelab-* entries and adding the new one), then programmatically
# replaces the SSH_PRIVATE_KEY field in the SOPS-encrypted hermes-credentials
# Secret using yaml.safe_dump (no manual paste — no chance of editor mangling).
#
# Verifies end-to-end: key parses, authorized_keys updated, SSH key works,
# YAML round-trip preserves bytes, encrypted file decrypts cleanly.
#
# Does NOT auto-commit. Prints the git commands you should run after.
#
# Usage:
#   ./rotate-ssh-key.sh                          # default: regenerate, hosts=peladn,evox2
#   ./rotate-ssh-key.sh --use-existing <path>    # reuse existing private key file
#   ./rotate-ssh-key.sh --hosts peladn,evox2,ha  # which hosts to update authorized_keys on
#   ./rotate-ssh-key.sh --dry-run                # do everything except modify files / hosts
#
# Requires (on the admin box):
#   ssh-keygen, ssh, sops, python3 + pyyaml, cygpath (Git Bash on Windows)
#
# Run from anywhere — the script auto-finds the Homelab-ops repo root.
set -euo pipefail

# ─── arg parsing ────────────────────────────────────────────────────────────
MODE="regen"          # regen | reuse
KEY_PATH=""           # for --use-existing
HOSTS_CSV="peladn,evox2"
DRY_RUN=false
COMMENT_SUFFIX=""     # auto: -vN based on existing local

while [[ $# -gt 0 ]]; do
  case "$1" in
    --regen)        MODE="regen"; shift;;
    --use-existing) MODE="reuse"; KEY_PATH="$2"; shift 2;;
    --hosts)        HOSTS_CSV="$2"; shift 2;;
    --dry-run)      DRY_RUN=true; shift;;
    -h|--help)      sed -n '/^# /,/^$/p' "$0" | sed 's/^# \?//'; exit 0;;
    *)              echo "unknown arg: $1" >&2; exit 2;;
  esac
done

# ─── locate the repo + the encrypted secret ─────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  echo "error: this script must live inside the Homelab-ops git repo" >&2
  exit 1
fi
SECRET_REL="kubernetes/apps/hermes-agent/secret.enc.yaml"
SECRET_PATH="$REPO_ROOT/$SECRET_REL"
[[ -f "$SECRET_PATH" ]] || { echo "error: $SECRET_PATH not found" >&2; exit 1; }

# Map host aliases → IPs (must match HOSTS dict in ssh_run.py / ssh_exec.py)
declare -A HOST_IPS=(
  [peladn]="192.168.4.150"
  [evox2]="192.168.4.84"
  [ha]="192.168.4.13"
  [pbs]="192.168.4.27"
)

log() { printf '  %s\n' "$*"; }
heading() { printf '\n=== %s ===\n' "$*"; }

# ─── 1. generate or load keypair ────────────────────────────────────────────
heading "1) prepare keypair"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

if [[ "$MODE" == "regen" ]]; then
  DATE_TAG="$(date +%Y-%m-%d)"
  # pick a -vN suffix that doesn't already exist on Peladn's authorized_keys
  N=1
  EXISTING_TAGS="$(ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=5 \
                   "root@${HOST_IPS[peladn]}" \
                   "grep -oE 'hermes-agent@homelab-[0-9-]+-v[0-9]+' ~/.ssh/authorized_keys 2>/dev/null" || true)"
  while echo "$EXISTING_TAGS" | grep -q -- "-v${N}\$"; do N=$((N+1)); done
  COMMENT="hermes-agent@homelab-${DATE_TAG}-v${N}"
  log "generating fresh ed25519 keypair: $COMMENT"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "[dry-run] would: ssh-keygen -t ed25519 -N \"\" -C \"$COMMENT\" -f $WORK_DIR/key"
    # synthesize a dummy keypair so the rest of the script can validate flow
    ssh-keygen -t ed25519 -N "" -C "$COMMENT" -f "$WORK_DIR/key" >/dev/null
  else
    ssh-keygen -t ed25519 -N "" -C "$COMMENT" -f "$WORK_DIR/key" >/dev/null
  fi
  KEY_PATH="$WORK_DIR/key"
elif [[ "$MODE" == "reuse" ]]; then
  [[ -f "$KEY_PATH" ]] || { echo "error: --use-existing $KEY_PATH does not exist" >&2; exit 1; }
  [[ -f "${KEY_PATH}.pub" ]] || { echo "error: ${KEY_PATH}.pub missing" >&2; exit 1; }
  log "reusing keypair at: $KEY_PATH"
fi

# verify parses
PUB="$(ssh-keygen -y -f "$KEY_PATH" 2>/dev/null)" || {
  echo "error: $KEY_PATH does not parse as a valid private key" >&2; exit 1; }
PUB_LINE="$(cat "${KEY_PATH}.pub")"
log "public key: $PUB_LINE"
log "round-trip from private: $PUB"

# ─── 2. update authorized_keys on each host ─────────────────────────────────
heading "2) update authorized_keys"
IFS=',' read -ra HOSTS_ARR <<< "$HOSTS_CSV"
for h in "${HOSTS_ARR[@]}"; do
  ip="${HOST_IPS[$h]:-}"
  [[ -z "$ip" ]] && { echo "error: unknown host alias '$h'" >&2; exit 1; }
  log "$h ($ip):"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "[dry-run] would: sed -i '/hermes-agent@homelab/d' + append new key on $h"
    continue
  fi
  ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 "root@$ip" \
    "sed -i '/hermes-agent@homelab/d' ~/.ssh/authorized_keys && \
     echo \"$PUB_LINE\" >> ~/.ssh/authorized_keys && \
     chmod 600 ~/.ssh/authorized_keys && \
     grep hermes-agent ~/.ssh/authorized_keys | tail -1"
done

# ─── 3. sanity: SSH to each host with the NEW key ───────────────────────────
heading "3) verify SSH works with the new key"
for h in "${HOSTS_ARR[@]}"; do
  ip="${HOST_IPS[$h]}"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "[dry-run] would: ssh -i $KEY_PATH root@$ip hostname"
    continue
  fi
  result="$(ssh -i "$KEY_PATH" \
              -o StrictHostKeyChecking=accept-new \
              -o UserKnownHostsFile="$WORK_DIR/known_hosts" \
              -o BatchMode=yes -o ConnectTimeout=10 \
              "root@$ip" "hostname && date" 2>&1)" || {
    echo "error: SSH to $h ($ip) with new key FAILED:" >&2
    echo "$result" >&2
    echo "  rotation aborted; old key may already be removed from authorized_keys — review manually" >&2
    exit 1
  }
  log "$h: $(echo "$result" | tr '\n' ' | ')"
done

# ─── 4. decrypt the secret ──────────────────────────────────────────────────
heading "4) decrypt + update SSH_PRIVATE_KEY in the SOPS Secret"
PLAIN="$WORK_DIR/secret.plain.yaml"
if [[ "$DRY_RUN" == "true" ]]; then
  log "[dry-run] would: sops --decrypt $SECRET_REL > $PLAIN"
else
  sops --decrypt "$SECRET_PATH" > "$PLAIN"
fi

# ─── 5. update SSH_PRIVATE_KEY programmatically ─────────────────────────────
# Use cygpath when on Git Bash so Python sees Windows paths
PY_PLAIN="$PLAIN"
PY_KEY="$KEY_PATH"
if command -v cygpath >/dev/null 2>&1; then
  PY_PLAIN="$(cygpath -w "$PLAIN")"
  PY_KEY="$(cygpath -w "$KEY_PATH")"
fi

if [[ "$DRY_RUN" == "true" ]]; then
  log "[dry-run] would: python3 ... safe_dump SSH_PRIVATE_KEY into $PLAIN"
else
  python3 - "$PY_PLAIN" "$PY_KEY" <<'PYEOF'
import sys, yaml, os, subprocess, tempfile
from pathlib import Path
plain_path = Path(sys.argv[1])
new_key = Path(sys.argv[2]).read_text(encoding="utf-8")
d = yaml.safe_load(plain_path.read_text(encoding="utf-8"))

class LiteralDumper(yaml.SafeDumper): pass
def repr_str(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)
LiteralDumper.add_representer(str, repr_str)

d["stringData"]["SSH_PRIVATE_KEY"] = new_key
with plain_path.open("w", encoding="utf-8", newline="\n") as f:
    yaml.dump(d, f, Dumper=LiteralDumper, default_flow_style=False, sort_keys=False, width=4096)

# Round-trip verify byte-exact preservation
reloaded = yaml.safe_load(plain_path.read_text(encoding="utf-8"))
roundtrip = reloaded["stringData"]["SSH_PRIVATE_KEY"]
assert roundtrip == new_key, f"BYTE MISMATCH after YAML round-trip ({len(new_key)} vs {len(roundtrip)})"

# Extract + ssh-keygen verify that the key in the YAML actually parses
with tempfile.NamedTemporaryFile(mode="w", suffix="", delete=False, newline="\n") as tf:
    tf.write(roundtrip)
    test = tf.name
os.chmod(test, 0o600)
r = subprocess.run(["ssh-keygen", "-y", "-f", test], capture_output=True, text=True)
os.unlink(test)
if r.returncode != 0:
    print(f"  [FAIL] extracted key from YAML does not parse: {r.stderr.strip()}", file=sys.stderr)
    sys.exit(1)
print(f"  [OK] YAML round-trip preserves key, ssh-keygen accepts: {r.stdout.strip()}")
PYEOF
fi

# ─── 6. encrypt back in place ───────────────────────────────────────────────
heading "5) encrypt back into $SECRET_REL"
if [[ "$DRY_RUN" == "true" ]]; then
  log "[dry-run] would: cp $PLAIN $SECRET_PATH && sops --encrypt --in-place $SECRET_PATH"
else
  cp "$PLAIN" "$SECRET_PATH"
  sops --encrypt --in-place "$SECRET_PATH"
  log "encrypted"
fi

# ─── 7. round-trip verify the encrypted file ────────────────────────────────
heading "6) round-trip verify the encrypted file"
if [[ "$DRY_RUN" == "true" ]]; then
  log "[dry-run] would: sops --decrypt | python verify key matches"
else
  sops --decrypt "$SECRET_PATH" | python3 -c "
import sys, yaml, os, subprocess, tempfile
d = yaml.safe_load(sys.stdin)
k = d['stringData']['SSH_PRIVATE_KEY']
with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False, newline='\n') as tf:
    tf.write(k); test=tf.name
os.chmod(test, 0o600)
r = subprocess.run(['ssh-keygen','-y','-f',test], capture_output=True, text=True)
os.unlink(test)
if r.returncode == 0:
    print(f'  [OK] encrypted file round-trips cleanly. pub: {r.stdout.strip()}')
else:
    print(f'  [FAIL] {r.stderr.strip()}'); sys.exit(1)
"
fi

# ─── 8. print git + rollout instructions ────────────────────────────────────
heading "7) next steps (NOT executed by this script — your call)"
cat <<EOF

  cd "$REPO_ROOT"
  git add "$SECRET_REL"
  git diff --cached --stat
  git commit -m "hermes: rotate SSH key (\${PWD##*/})"
  git push
  kubectl -n flux-system annotate kustomization/apps reconcile.fluxcd.io/requestedAt="\$(date +%s)" --overwrite
  kubectl -n hermes-agent rollout restart deploy/hermes-agent
  kubectl -n hermes-agent rollout status deploy/hermes-agent --timeout=180s

  # then smoke-test SSH from inside the pod:
  ssh root@192.168.4.150 'su - n8n-backup -c "kubectl -n hermes-agent exec deploy/hermes-agent -- \
    ssh -i /opt/data/.ssh/id_ed25519 \
      -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile=/opt/data/.ssh/known_hosts \
      -o BatchMode=yes -o ConnectTimeout=5 \
      root@192.168.4.150 \"hostname && date && echo HERMES_SSH_ROTATED_OK\""'
EOF

heading "DONE"
log "rotation complete."
log "  hosts updated:    $HOSTS_CSV"
log "  Secret updated:   $SECRET_REL"
log "  uncommitted:      yes (run the git commands above)"
[[ "$DRY_RUN" == "true" ]] && log "  mode: DRY-RUN — no real changes made"
