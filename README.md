# Homelab-ops

Production-grade homelab platform built on **Talos Linux**, **Flux CD GitOps**, and **Proxmox** — engineered as a reference implementation for platform engineering, self-hosted AI infrastructure, and data resilience.

> This repo is a live, working system — not a template. See [`cluster.env.example`](cluster.env.example) for the environment-specific values you would need to adapt it to your own setup.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│  Tier 1 — Always-On (24/7)                                      │
│  Peladn 8845HS · 32 GB · AMD 780M                               │
│  ├── Talos K8s Control Plane VM                                 │
│  ├── home-ops-lxc  · HA · NPM · Vaultwarden · ESPHome          │
│  └── media-ai-ops-lxc · Nextcloud · Immich · Ollama (ROCm)     │
│                                                                 │
│  RPi4 · 4 GB · ARM64                                            │
│  └── Talos K8s Worker · mem0 · n8n · miniflux · beszel         │
├─────────────────────────────────────────────────────────────────┤
│  Tier 2 — On-Demand WOL                                         │
│  Intel NUC  · Talos K8s Worker · general burst                 │
│  Dell R610  · Talos K8s Worker · heavy compute                 │
│  i9-14900K  · RTX 5070 · Talos Worker + Ollama CUDA            │
└─────────────────────────────────────────────────────────────────┘
                  │ GitOps (Flux CD)
          ┌───────┴────────────────┐
          │  OPNsense (perimeter)  │
          └────────────────────────┘
```

**Key design decisions:** See [`ADR/`](ADR/) for full rationale.

---

## Stack

| Layer | Technology | Notes |
| ----- | ---------- | ----- |
| OS | [Talos Linux](https://www.talos.dev/) | Immutable, API-driven K8s OS |
| Orchestration | Kubernetes (K8s) | 5-node mixed-arch cluster |
| GitOps | [Flux CD v2](https://fluxcd.io/) | Push-based, native SOPS support |
| Secrets | [SOPS](https://github.com/getsops/sops) + Age | Encrypted secrets safe to commit |
| Hypervisor | [Proxmox VE](https://www.proxmox.com/) | LXC containers + VMs |
| Backup | Proxmox Backup Server (PBS) | 3-2-1, GFS retention, verify jobs |
| Networking | OPNsense | Perimeter firewall, DNS, DHCP, VPN |
| AI Memory | [mem0](https://github.com/mem0ai/mem0) | Self-hosted, Ollama + Qdrant + Postgres |
| Observability | Grafana + Loki + VictoriaMetrics | Phase 19 — in progress |

---

## Repository Structure

```text
Homelab-ops/
├── kubernetes/
│   ├── apps/                    # All K8s application manifests (Kustomize)
│   │   ├── beszel/              # System metrics dashboard
│   │   ├── mem0/                # AI memory layer (Postgres + Qdrant + server)
│   │   ├── miniflux/            # RSS feed reader
│   │   ├── n8n/                 # Workflow automation
│   │   ├── nut/                 # UPS monitoring
│   │   └── open-webui/          # LLM chat interface (scaled to 0, moving to i9)
│   └── clusters/
│       └── homelab/             # Flux CD cluster bootstrap + sync config
├── infrastructure/
│   ├── home-ops-lxc/            # Docker Compose for home-ops LXC
│   └── media-ops-lxc/           # Docker Compose for media-ai LXC
├── docker/
│   └── mem0-server/             # Custom mem0 FastAPI server image
├── docs/                        # Solution guides and case studies
├── ADR/                         # Architectural Decision Records
└── cluster.env.example          # All environment-specific values documented
```

---

## Services

| Service | Namespace | Purpose | Docs |
| ------- | --------- | ------- | ---- |
| mem0 | `mem0` | Stateful AI memory layer — Postgres + Qdrant + REST API | [README](kubernetes/apps/mem0/README.md) |
| n8n | `n8n` | Workflow automation, WOL triggers, AI pipelines | [README](kubernetes/apps/n8n/README.md) |
| miniflux | `miniflux` | Lightweight RSS reader | [README](kubernetes/apps/miniflux/README.md) |
| beszel | `beszel` | Host + container system metrics | [README](kubernetes/apps/beszel/README.md) |
| nut | `nut` | UPS power monitoring | [README](kubernetes/apps/nut/README.md) |
| open-webui | `open-webui` | LLM chat UI (paused — migrating to i9 LXC) | [README](kubernetes/apps/open-webui/README.md) |

---

## Key Patterns

### Secrets Management

All secrets are encrypted with SOPS + Age before committing. The Age public key is stored in `.sops.yaml`. Private key lives in Vaultwarden only.

```bash
# Encrypt a secret
sops --encrypt secret.yaml > secret.enc.yaml

# Flux decrypts automatically via the sops-age K8s secret
```

### Adding a New Application

1. Create `kubernetes/apps/<name>/` with `namespace.yaml`, manifests, `kustomization.yaml`
2. Add to `kubernetes/apps/kustomization.yaml`
3. Encrypt any secrets: `sops --encrypt secret.yaml > secret.enc.yaml`
4. Push — Flux reconciles within 1–10 minutes

### WOL (Wake-on-LAN) Automation

Burst nodes (NUC, i9) are powered off when idle. n8n workflows trigger WOL via UpSnap when RPi4 RAM exceeds 75% or GPU workloads are requested. See [Phase 21 worker management plan](../Phase-21%20-%20worker-management-plan.md).

---

## Docs & Case Studies

- [Self-hosted AI Memory Layer with mem0](docs/case-study-ai-memory-layer.md)
- [GitOps on Talos with Flux CD and SOPS](docs/case-study-gitops-talos-flux.md)

---

## Licence

MIT — fork, adapt, and deploy freely. Attribution appreciated but not required.
