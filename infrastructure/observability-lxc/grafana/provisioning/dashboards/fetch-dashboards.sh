#!/usr/bin/env bash
# Fetch community Grafana dashboards into the provisioning json/ dir, pinning the
# datasource UIDs to ours (victoriametrics / loki). Run inside CT405:
#   bash grafana/provisioning/dashboards/fetch-dashboards.sh && docker compose restart grafana
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)/json"
mkdir -p "$DIR"

fetch(){ # $1=gnetId  $2=outfile
  curl -fsSL "https://grafana.com/api/dashboards/$1/revisions/latest/download" \
    | sed 's/${DS_PROMETHEUS}/victoriametrics/g; s/${DS_VICTORIAMETRICS}/victoriametrics/g; s/${DS_LOKI}/loki/g' \
    > "$DIR/$2"
  echo "  fetched $2 (gnet $1)"
}

echo "fetching dashboards -> $DIR"
fetch 1860  node-exporter-full.json     # host/LXC metrics
fetch 13639 loki-logs.json              # Loki log explorer
echo done
