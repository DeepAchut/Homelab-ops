# Peladn host backup scripts

These scripts run **on the Peladn Proxmox host** (`prop`, 192.168.4.150) and are
invoked by scheduled **n8n workflows** (which SSH in, run the script, and send a
Gotify notification). They are version-controlled here for DR — the live copies
live at `/opt/backup-scripts/` (rpi4 + pbs) and `/home/n8n-backup/` (talos).

> ⚠️ Keep the repo copy and the host copy in sync. After editing here, deploy with:
> `tr -d '\r' < <script> | ssh root@192.168.4.150 "cat > /opt/backup-scripts/<script> && chmod 0755 /opt/backup-scripts/<script>"`

## Scripts

| Script | Run as | n8n workflow | Schedule | Backs up |
|---|---|---|---|---|
| `rpi4-pvc-backup.sh` | `n8n-backup` | rpi4 PVC Dumps (`l8DHMWUaHEoAaQkg`) | Sat 1 AM | Logical dumps of DBs on the **rpi4 Talos node's local-path** (never captured by vzdump): mem0 qdrant + mem0 pg + miniflux pg + **n8n pg** + karakeep pg → `/mnt/pvedas/k8s-backups` |
| `talos-backup.sh` | root | Talos Config and Data Backup (`ggPHd7ROI3GVsLOL`) | Thu 2 AM | Talos etcd snapshot + YAML configs |
| `k8s-export.sh` | root | Talos Config and Data Backup (`ggPHd7ROI3GVsLOL`) | Sun 1 AM | k8s manifest/data export |
| `pbs-config-backup.sh` | root | *(to wire — Sat 3 AM in the PBS workflow)* | weekly | CT 200 (PBS LXC) **config only**: `pct config 200` + `/etc/proxmox-backup/` (datastore.cfg/repos, acl, remote, prune, domains, keys) + host `storage.cfg`. **NOT** the datastore chunk data. → `/mnt/pvedas/pbs-config-backups` |

Everything lands under `/mnt/pvedas` (the DAS), which is swept into the **Friday
DAS PBS backup** (`DAS Backup to External HDD via PBS`, `lZh1YZsfXwzb2PTq`).

## Why each exists / notable design points

- **rpi4-pvc-backup.sh** — the rpi4 is a *physical* Talos node, so its local-path
  PVCs are never in any vzdump. This takes logical dumps instead. **n8n was added
  2026-06-21** after it migrated off SQLite-on-NFS to Postgres-on-local-path (it
  used to ride along in the NFS DAS backup; now nothing else captures it). karakeep
  pg is currently empty (its real data is SQLite on the NFS assets PVC) — dumped
  anyway to catch future use. Uses a shared `dump_pg()` helper.
- **pbs-config-backup.sh** — CT 200 is **not** captured by any vzdump (the Monday
  job only does 201/202/203). This backs up just enough to rebuild PBS and re-point
  it at the existing datastores. Handles CT 200 being **stopped** (its normal
  state) via `pct mount` (mounts the rootfs without starting the container), falls
  back to `pct exec` if running. Captures config only — the actual backup chunks
  stay in the datastores.

## Restore notes

- **n8n pg**: `gunzip -c n8n-postgres-DATE.sql.gz | kubectl exec -i -n n8n n8n-postgres-0 -- psql -U n8n -d n8n`
- **PBS config**: extract the tarball, drop `/etc/proxmox-backup/*` back into a fresh
  CT 200, recreate the datastores from `datastore.cfg` pointing at the existing
  chunk dirs (the data was never deleted), then `proxmox-backup-manager` verify.
