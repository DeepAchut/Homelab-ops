#!/bin/bash
# Decrypt SOPS-encrypted .env files using Age key
# Run on LXC after cloning the repo
# Usage: ./decrypt-secrets.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Enter your Age private key (starts with AGE-SECRET-KEY-):"
read -r AGE_KEY
export SOPS_AGE_KEY="$AGE_KEY"

decrypt_env() {
    local enc_file="$1"
    local out_file="${enc_file%.enc.yaml}"

    if [ ! -f "$enc_file" ]; then
        echo "  [SKIP] $enc_file not found"
        return
    fi

    sops --decrypt --input-type yaml --output-type dotenv "$enc_file" > "$out_file"
    sed -i 's/\r$//' "$out_file"
    echo "  [OK] $out_file"
}

echo ""
echo "Decrypting secrets..."
decrypt_env "$SCRIPT_DIR/media-ops-lxc/.env.enc.yaml"
decrypt_env "$SCRIPT_DIR/home-ops-lxc/.env.enc.yaml"

unset SOPS_AGE_KEY
echo ""
echo "Done. Decrypted .env files are ready."
