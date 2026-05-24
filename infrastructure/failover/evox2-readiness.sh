#!/usr/bin/env bash
# ============================================================================
# Evo-X2 failover readiness (idempotent). Run ON the Evo-X2 PVE host.
# Prepares everything peladn-failover.sh needs:
#   1) pbs-local storage  -> the local CT200 PBS (for pct/qmrestore)
#   2) bind-mount stub dirs (so restored CTs can start)
#   3) installs peladn-failover.sh from this repo dir
#
# Env (./.env, gitignored — see .env.example): PBS_SERVER, PBS_FINGERPRINT, PBS_TOKEN_SECRET.
#   Only needed when ADDING pbs-local on a fresh host (keeps infra details out of the public repo).
#   If you keep an encrypted .env.enc.yaml, decrypt first:  sops -d .env.enc.yaml > .env
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$HERE/.env" ] && . "$HERE/.env"

# Non-sensitive defaults (override in ./.env if needed). Server/fingerprint/secret come from ./.env.
PBS_DATASTORE="${PBS_DATASTORE:-backup-26tb}"
PBS_TOKENID="${PBS_TOKENID:-root@pam!n8n-das-backup}"

echo "[1/3] pbs-local restore storage"
if pvesm status --storage pbs-local >/dev/null 2>&1; then
  echo "  exists — skipping"
else
  : "${PBS_SERVER:?set PBS_SERVER in ./.env (PBS host IP)}"
  : "${PBS_FINGERPRINT:?set PBS_FINGERPRINT in ./.env (PBS cert SHA-256)}"
  : "${PBS_TOKEN_SECRET:?set PBS_TOKEN_SECRET in ./.env (API token secret)}"
  pvesm add pbs pbs-local --server "$PBS_SERVER" --datastore "$PBS_DATASTORE" \
    --username "$PBS_TOKENID" --password "$PBS_TOKEN_SECRET" \
    --fingerprint "$PBS_FINGERPRINT" --content backup
  echo "  added"
fi

echo "[2/3] bind-mount stub dirs"
mkdir -p /mnt/das /mnt/sg-ext-hdd /mnt/wd-ext-hdd

echo "[3/3] install peladn-failover.sh"
install -m 0755 "$HERE/peladn-failover.sh" /usr/local/bin/peladn-failover.sh

echo "Done. Verify: pvesm list pbs-local"
