#!/bin/bash
# /home/n8n-backup/k8s-export.sh

set -euo pipefail

DATE=$(date +%Y%m%d)
EXPORT_DIR="/mnt/pvedas/k8s-app-exports/$DATE"
mkdir -p "$EXPORT_DIR"

# --- Beszel ---
# henrygd/beszel is a minimal image with no tar in PATH.
# PocketBase stores its data as SQLite files — stream them directly with cat.
#echo "--- Exporting Beszel Data ---"
#BESZEL_POD=$(kubectl get pods -n beszel -l app=beszel -o jsonpath='{.items[0].metadata.name}')
# Stream each SQLite file individually (no tar needed inside the container)
#kubectl exec -n beszel "$BESZEL_POD" -- cat /beszel_data/data.db \
#  > "$EXPORT_DIR/beszel_data.db"
# Capture logs db if present (may not exist)
#kubectl exec -n beszel "$BESZEL_POD" -- cat /beszel_data/logs.db \
#  > "$EXPORT_DIR/beszel_logs.db" 2>/dev/null || true
# Compress on the host side
#gzip -f "$EXPORT_DIR/beszel_data.db" "$EXPORT_DIR/beszel_logs.db" 2>/dev/null || true

# --- Miniflux Database ---
# NEVER tar a live postgres data directory — it produces a corrupt backup.
# Use pg_dump for a consistent logical dump. postgres:16-alpine has pg_dump.
echo "--- Exporting Miniflux Database ---"
MINIFLUX_DB_POD=$(kubectl get pods -n miniflux -l app=miniflux-db -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n miniflux "$MINIFLUX_DB_POD" \
  -- pg_dump -U miniflux miniflux \
  | gzip > "$EXPORT_DIR/miniflux_db.sql.gz"

# Prune exports older than 14 days to maintain exactly 2 weekly copies
echo "--- Pruning backups older than 14 days ---"
find /mnt/pvedas/k8s-app-exports/ -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +

echo "--- Export Complete: $EXPORT_DIR ---"
