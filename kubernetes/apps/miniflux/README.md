# miniflux — RSS Feed Reader

Minimalist, opinionated RSS/Atom feed reader. Runs on the always-on RPi4 worker so feeds are fetched 24/7 without a WOL node being awake.

## Stack

- **miniflux** — Go binary, single container
- **Postgres** — dedicated instance in the same namespace (separate from mem0 Postgres)

## Ports

| Port | Purpose |
| ---- | ------- |
| `8080` | Web UI |

## Configuration

Credentials are encrypted in `secret.enc.yaml` via SOPS. Key variables:

| Env var | Purpose |
| ------- | ------- |
| `DATABASE_URL` | Postgres connection string |
| `ADMIN_USERNAME` | Initial admin user |
| `ADMIN_PASSWORD` | Initial admin password |

## Troubleshooting

**Feed fetch failures** — Check DNS resolution from within the pod: `kubectl exec -n miniflux deploy/miniflux -- nslookup google.com`. OPNsense DNS overrides can block certain domains.

**Database connection refused** — Verify Postgres pod is running: `kubectl get pods -n miniflux`. Check secret decryption: `kubectl get secret -n miniflux`.
