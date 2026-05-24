# Observability LXC (CT405, Evo-X2)

Tier-1 monitoring stack for the homelab, running on **CT405 `hl-observability-lxc`** on the
Evo-X2 (Debian 13, Docker Compose). Part of Phase 21 Part 3.

- **VictoriaMetrics** (`:8428`) — metrics store; scrapes node_exporters and receives
  `remote_write` from the K8s **vmagent** (`kubernetes/apps/monitoring`).
- **Loki** (`:3100`) — log store (+ Grafana Alloy shipper).
- **Grafana** (`:3000`) — dashboards; VictoriaMetrics + Loki datasources auto-provisioned.
- **node-exporter** (`:9100`) — this LXC's OS metrics.

**Beszel stays** as the lightweight at-a-glance view; this stack adds history, logs,
dashboards, and real alerting (alerting/SMART/speedtest come in Tier 2).

## Host

- CT405 on Evo-X2, DHCP (reserve MAC `BC:24:11:56:BC:A2` in OPNsense for a stable IP).
- 4 cores / 4 GB / 40 GB, unprivileged, `nesting=1`.

## Deploy

```bash
# inside CT405
git clone https://github.com/DeepAchut/Homelab-ops.git
cd Homelab-ops/infrastructure/observability-lxc
cp .env.example .env            # optionally set GRAFANA_ADMIN_PASSWORD (else admin/admin, change on first login)
docker compose up -d
docker compose ps
```

> Data lives in Docker named volumes inside the LXC rootfs (captured by the CT405 vzdump backup). Metrics retention 90d, logs 30d.

## Scrape targets

node_exporter on: this LXC, Evo-X2 host, Peladn host, CT202, CT203 (see `scrape.yaml`).
K8s pod/node metrics arrive via the vmagent `remote_write`.

## Access

Put Grafana behind NPM (e.g. `grafana.dkghar.duckdns.org` → `192.168.4.66:3000`).
VictoriaMetrics/Loki stay internal-only.

## Secrets

No secrets committed. `GRAFANA_ADMIN_PASSWORD` lives in a gitignored `.env` (or SOPS
`.env.enc.yaml`). Everything else is non-sensitive config.

## Next (Tier 2)

smartctl_exporter (drive temps incl. the 26 TB/2 TB externals, `-d sat,16`),
vmalert → Gotify (temp/host alerts), speedtest-exporter. Tier 3: n8n LAN-device watcher.
