#!/bin/bash
# /home/n8n-backup/talos-backup.sh

set -e # Exit on error

DATE=$(date +%Y%m%d_%H%M)
BACKUP_DIR="/mnt/backup-hdd/talos-backups/bundle_$DATE"
mkdir -p "$BACKUP_DIR"

echo "--- Starting Talos Configuration Export ---"
# 1. Export YAMLs from your repo
#cp /mnt/pvedas/Homelab-ops/kubernetes/talos/*.yaml "$BACKUP_DIR/" || true

# 2. Capture etcd Snapshot
# Replace <CP-IP> with your Control Plane IP (e.g., 192.168.4.150 or similar)
/usr/local/bin/talosctl --talosconfig=/home/n8n-backup/.talos/config \
  -n 192.168.4.172 etcd snapshot "$BACKUP_DIR/etcd.db"

# 3. Create the Archive
cd /mnt/backup-hdd/talos-backups
tar -czvf "talos_recovery_$DATE.tar.gz" "bundle_$DATE"

# 4. Cleanup temp folder
rm -rf "$BACKUP_DIR"

# 5. Prune old backups (Keep last 10 days)
echo "--- Pruning backups older than 10 days ---"
find /mnt/backup-hdd/talos-backups/ -name "talos_recovery_*.tar.gz" -mtime +10 -delete

echo "--- Talos Backup Complete: talos_recovery_$DATE.tar.gz ---"
