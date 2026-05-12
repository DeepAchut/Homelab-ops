# beszel — System Metrics Dashboard

Lightweight system metrics hub + agents for monitoring host CPU, RAM, disk, and network across all homelab nodes. Complements the Phase 19 Grafana/VictoriaMetrics stack (which covers K8s pod-level metrics).

## Architecture

- **Hub** (`deployment.yaml`) — central server, stores metrics, serves the dashboard UI
- **Agent** (`agent-daemonset.yaml`) — DaemonSet on every K8s node, collects host-level stats and pushes to hub

Non-K8s hosts (LXCs, Proxmox) run the beszel agent binary via systemd.

## Ports

| Port | Purpose |
| ---- | ------- |
| `8090` | Web UI + agent registration |

## Configuration

Beszel hub data is persisted on a local-path PVC (`pvc.yaml`) on the RPi4.

Agent registration: add each host in the hub UI, copy the connection string, run on the target host:

```bash
# On each non-K8s host
curl -sL https://raw.githubusercontent.com/henrygd/beszel/main/supplemental/scripts/install-agent.sh | bash -s -- -p 45876 -k "<hub-public-key>"
```

## Troubleshooting

**Agent not connecting** — Check firewall rules between agent host and hub NodePort. Beszel uses a custom binary protocol, not HTTP.

**No data for WOL nodes** — Expected. Burst nodes (NUC, i9) show as offline when powered down; data resumes automatically when they wake.
