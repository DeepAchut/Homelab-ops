# nut — UPS Monitoring

Network UPS Tools (NUT) client deployment. Connects to a NUT server running on the Proxmox host (which has USB access to the UPS) and exposes UPS status to the K8s cluster.

## Architecture

```text
UPS (USB) ── Proxmox host (nut-server) ── K8s nut pod (nut-client)
                                                    │
                                              Alerts via Gotify / n8n
```

The Proxmox host runs `nut-server` (USB-attached UPS). This K8s deployment runs `nut-client` / `upsmon` watching the server over the network.

## Configuration

UPS server IP and credentials are in `secret.enc.yaml` (SOPS-encrypted).

| Setting | Notes |
| ------- | ----- |
| `UPSD_HOST` | Proxmox host IP running nut-server |
| `UPSD_USER` | NUT monitor username |
| `UPSD_PASSWORD` | NUT monitor password |

## Troubleshooting

**upsmon: can't connect to server** — Check that nut-server on the Proxmox host allows connections from the K8s pod CIDR. Edit `/etc/nut/upsd.conf` `LISTEN` directive on the host.

**UPS status unknown** — Run `kubectl exec -n nut deploy/nut -- upsc <ups-name>@localhost` to check the client-side view.
