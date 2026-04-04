#!/bin/bash
# One-time migration script: CasaOS (192.168.4.55) → Peladn Proxmox LXCs
# Run from a machine that has SSH access to both source and destination

# --- CONFIGURATION ---
SOURCE_USER="deep"
SOURCE_IP="192.168.4.55"

# Destination IPs (Update these to your new LXC IPs)
STORAGE_LXC_IP="192.168.4.11"
MEDIA_AI_LXC_IP="192.168.4.12"
HOME_OPS_LXC_IP="192.168.4.13"

LOG_FILE="./migration_split_$(date +%F).log"
DRY_RUN=true # Set to false when you are ready for the real move!

# --- MAPPING SCHEMA ---
# "Source_Path | Destination_IP | Destination_Path"
MAPPINGS=(
    # --- STORAGE LXC TARGETS ---
    # "/DATA/AppData/jellyfin/config/ | $STORAGE_LXC_IP | /mnt/das/jellyfin/config/"
    # "/mnt/wd-hdd-500/frigate/config/ | $STORAGE_LXC_IP | /mnt/das/frigate/config/"
    # "/mnt/wd-hdd-500/frigate/media/ | $STORAGE_LXC_IP | /mnt/das/frigate/media/"
    # "/mnt/sandisk-ssd-raid/Immich/ | $STORAGE_LXC_IP | /mnt/das/immich/upload/"
    # "/mnt/tforce-ssd-raid/SSD-Raid/NextCloud/Data/ | $STORAGE_LXC_IP | /mnt/das/nextcloud/data/"
    # "/mnt/tforce-ssd-raid/SSD-Raid/vaultwarden/data/ | $STORAGE_LXC_IP | /mnt/das/vaultwarden/data/"
    
    # --- MEDIA & AI LXC TARGETS (Databases & High-IO) ---
    # "/mnt/tforce-ssd-raid/SSD-Raid/nextcloud_db/config/ | $MEDIA_AI_LXC_IP | /var/lib/nextcloud-db/"
    # "/mnt/sandisk-ssd-raid/Immich/pgdata/ | $MEDIA_AI_LXC_IP | /var/lib/immich-db/"
    # "/mnt/tforce-ssd-raid/SSD-Raid/NextCloud/WWW/ | $MEDIA_AI_LXC_IP | /var/www/nextcloud/"
    "/mnt/tforce-ssd-raid/SSD-Raid/NextCloud/Data/deep/files/Notes/ObsidianNotes/ObsidianLiveSync/data/couchdb/ | $HOME_OPS_LXC_IP | /var/lib/obsidianLiveSync/couchdb/"
    # "/mnt/tforce-ssd-raid/SSD-Raid/NextCloud/Configs/ | $MEDIA_AI_LXC_IP | /var/www/nextcloud/config/"
    # "/mnt/tforce-ssd-raid/SSD-Raid/NextCloud/Apps/ | $MEDIA_AI_LXC_IP | /var/www/nextcloud/custom_apps/"

    #--- Home/Monitoring Ops LXCs in Storage LXC ---
    # "/DATA/AppData/Wake-on-lan/data/ | $STORAGE_LXC_IP | /mnt/das/upsnap/data/"
    # "/DATA/AppData/big-bear-gotify/data/ | $STORAGE_LXC_IP | /mnt/das/gotify/data/"
    # "/DATA/AppData/uptimekuma/app/data/ | $STORAGE_LXC_IP | /mnt/das/uptimekuma/data/"
    "/DATA/AppData/nginxproxymanager/ | $STORAGE_LXC_IP | /mnt/das/nginxproxymanager/"
    # "/mnt/wd-hdd-500/selkies/ | $STORAGE_LXC_IP | /mnt/das/selkies/"
    # "/mnt/wd-hdd-500/mosquitto/ | $STORAGE_LXC_IP | /mnt/das/mosquitto/"
    # # "/mnt/tforce-ssd-raid/SSD-Raid/vaultwarden/data/ | $STORAGE_LXC_IP | /mnt/das/vaultwarden/data/"
    # "/DATA/AppData/Beszel/data/ | $STORAGE_LXC_IP | /mnt/das/beszel/data/"
    # "/mnt/sandisk-ssd-raid/homeassistant/ | $STORAGE_LXC_IP | /mnt/das/homeassistant/"
    # "/mnt/tforce-ssd-raid/SSD-Raid/OpenWebUI/data/ | $STORAGE_LXC_IP | /mnt/das/openwebui/data/"
    # "/DATA/AppData/big-bear-myspeed/data/ | $STORAGE_LXC_IP | /mnt/das/myspeed/data/"

    # #--- External locations for Nextcloud Migration ---
    # "/mnt/HDD_1/SG-NR-old/HDD-NR-1/ | $STORAGE_LXC_IP | /mnt/das/nextcloud/external_locaions/Non-Raid-1/"
    # "/mnt/tforce-ssd-raid/HDD-Raid/shared | $STORAGE_LXC_IP | /mnt/das/nextcloud/external_locaions/Raid-Shared/"
    # "/mnt/tforce-ssd-raid/SSD-Raid/NextCloud/tmpfs | $STORAGE_LXC_IP | /mnt/das/nextcloud/external_locaions/tmpfs/"
    # "/mnt/HDD_1/WD-NR-old/ | $STORAGE_LXC_IP | /mnt/das/nextcloud/external_locaions/Non-Raid-2/"
)

# --- EXECUTION ---
echo "Starting Split-Tier Migration at $(date)" | tee -a "$LOG_FILE"

for MAP in "${MAPPINGS[@]}"; do
    SRC=$(echo "$MAP" | cut -d'|' -f1 | xargs)
    DEST_IP=$(echo "$MAP" | cut -d'|' -f2 | xargs)
    DEST_PATH=$(echo "$MAP" | cut -d'|' -f3 | xargs)

    echo "---------------------------------------------------" | tee -a "$LOG_FILE"
    echo "SYNCING: $SRC" | tee -a "$LOG_FILE"
    echo "TO:      $DEST_IP:$DEST_PATH" | tee -a "$LOG_FILE"
    
    # Create the destination directory remotely
    ssh root@"$DEST_IP" "mkdir -p $DEST_PATH"

    # Rsync Flags:
    # -aHX: Archive, Hardlinks, Extended Attributes
    # --numeric-ids: Keeps UIDs mapped correctly for LXC containers
    RSYNC_OPTS="-aHX --numeric-ids --info=progress2 --delete"
    if [ "$DRY_RUN" = true ]; then 
        RSYNC_OPTS="$RSYNC_OPTS --dry-run"
        echo "[!] DRY RUN ENABLED" | tee -a "$LOG_FILE"
    fi

    # Execute the transfer FROM the i9 Server directly to the LXC
    ssh "$SOURCE_USER"@"$SOURCE_IP" "sudo rsync $RSYNC_OPTS -e 'ssh -o StrictHostKeyChecking=no' '$SRC' root@$DEST_IP:'$DEST_PATH'" 2>&1 | tee -a "$LOG_FILE"
done

echo "Migration Complete at $(date)" | tee -a "$LOG_FILE"