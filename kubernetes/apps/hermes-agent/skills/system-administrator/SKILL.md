---
name: system-administrator
description: Monitor and manage Deep's homelab — Proxmox VE on Peladn + Evo-X2, a Talos K8s cluster, all the LXCs/VMs/containers, observability stack, mem0, n8n, HA. Read-only by default; mutations require explicit user confirmation.
version: 1.0.0
author: deep
license: MIT
tags: [homelab, proxmox, kubernetes, monitoring, system-admin]
---

# System Administrator — Deep's Homelab

You are the system administrator for Deep's homelab. This skill gives you a complete topology map plus helper scripts to monitor and (with confirmation) manage every piece. Use it whenever the user asks about lab status, service health, what's running where, why something is broken, or to restart/check something.

---

## When to Use

Trigger this skill when the user:

- Asks "what's the status of X" / "is X up" / "is X working" — anything about lab health
- Asks "what's running on host Y" / "what pods are in namespace Z" — topology questions
- Asks "restart X" / "why is X slow" / "check logs for X" — troubleshooting
- Asks "how do I reach X" — connection info (IPs, ports, paths)
- Asks "what's using disk/CPU/memory" — resource investigation
- References any of: Peladn, Evo-X2, RPi4, R610, iNUC, i9, OPNsense, PBS, mem0, n8n, observability, Grafana, Loki, VictoriaMetrics, Ollama, Talos, Flux, Hermes itself, miniflux, beszel, HomeAssistant, NPM, Vaultwarden, Gotify, Reolink, UpSnap

Do **not** trigger this skill for: pure conversation, code help unrelated to the lab, generic questions about Linux/Docker/K8s (only when those tie to the user's specific homelab).

---

## Lab Topology (ground truth — 2026-05-27)

### Hosts (physical / always-on tier)

| Host | IP | OS | Role | Notes |
|---|---|---|---|---|
| **Peladn** | `192.168.4.150` | Proxmox VE (PVE 9.x) | Standalone PVE node, K8s control plane (via VM 201), 24×7 always-on | AMD Ryzen 7 8845HS + Radeon 780M iGPU. Has DAS (11 TB Toshiba) + 2 USB externals (2 TB Seagate sda, 2 TB WD sdb). SSH: `~/.ssh/id_ed25519` → `root@192.168.4.150`. |
| **Evo-X2** | `192.168.4.84` | Proxmox VE (PVE 9.2.2) | Standalone PVE node, hosts AI + observability + PBS + new K8s worker, 24×7 always-on | AMD Ryzen AI Max+ 395 + Radeon 8060S (gfx1151, RDNA 3.5). 96 GB RAM split 48 UMA / 48 host. 1 × 26 TB Seagate Expansion external + 1 TB NVMe. SSH: `root@192.168.4.84`. |
| **RPi4** | `192.168.4.141` | Talos Linux | K8s worker (ARM64, the only ARM node), 24×7 always-on | Hostname in cluster: `ira-rpi4-talos-worker`. Labels: `tier=always-on arch=arm64`. Talos API on `:50000`. Hosts most K8s apps (mem0, n8n, miniflux, beszel, nut, monitoring, open-webui). |
| **R610** | (LAN, WOL) | Talos Linux | K8s worker (amd64), WOL-off | Hostname: `ira-dellr610-talos-worker`. Static IP `192.168.4.65`. Labels: `tier=on-demand arch=amd64`. Currently `NotReady, SchedulingDisabled` — woken via UpSnap when needed. |
| **iNUC** | (LAN, WOL) | Talos Linux | K8s worker (amd64), WOL-off | Hostname: `ira-inuc-talos-worker`. Static IP `192.168.4.215`. Labels: `tier=on-demand arch=amd64`. Currently `NotReady, SchedulingDisabled`. |
| **i9 server** | `192.168.4.110` | Linux + Docker | WOL burst node for heavy GPU bursts | RTX 5070 + Ollama (when on). NOT always-on. UpSnap wakes it. |

### LXCs / VMs on Peladn (PVE node `prop`)

| ID | Type | Name | IP | Role | Privilege |
|---|---|---|---|---|---|
| 200 | LXC | (old PBS shell — stopped) | — | Rollback target only | privileged (frozen) |
| 201 | VM | `hl-talos-control-node` | `192.168.4.172` | Talos K8s **control plane** (the cluster's CP) | OVMF, q35, `BC:24:11:C1:FB:D7` |
| 202 | LXC | `hl-media-ai-ops-lxc` | `192.168.4.12` | Docker host for **Immich, Jellyfin, Nextcloud, Ollama (gfx1103)**. Mem0's LLM calls this Ollama. | unprivileged, bind-mounts /mnt/pvedas, sg-ext-hdd, wd-ext-hdd |
| 203 | LXC | `hl-home-ops-lxc` | `192.168.4.13` | Docker host for **NPM (nginx-proxy-manager), Home Assistant, Vaultwarden, miniflux extras, other "home ops" services** | unprivileged |

### LXCs / VMs on Evo-X2 (PVE node `pve`)

| ID | Type | Name | IP | Role | Privilege |
|---|---|---|---|---|---|
| 200 | LXC | `hl-pbs-backup` | `192.168.4.27` | **PBS** — Proxmox Backup Server. Datastores: `backup-26tb` (the 26 TB external), `external-hdds`, `evox2-image`. Token: `root@pam!n8n-das-backup` (DatastoreBackup role). | **privileged** (restore privileged or chunk store breaks) |
| 401 | LXC | `hl-ai-ollama-lxc` | DHCP | **Currently inactive** — built for Ollama in Phase 22a but Strix Halo + LXC + Ollama is broken upstream. Has ROCm 7.2.3 installed inside. Kept for future re-use (Open WebUI etc.). | privileged |
| 402 | VM | `hl-evox2-talos-worker` | `192.168.4.71` | **Talos K8s worker** (joined cluster 2026-05-27). Labels: `tier=ai-worker arch=amd64 gpu=false`. Hosts Hermes Agent (us). | OVMF (non-secboot), `BC:24:11:82:E3:87` |
| 405 | LXC | `hl-observability-lxc` | `192.168.4.66` | **Observability stack**: VictoriaMetrics:8428, Loki:3100, Grafana:3000, node-exporter:9100, Grafana Alloy (Docker log shipper + OPNsense syslog receiver:1514). 5 containers from `/root/Homelab-ops/infrastructure/observability-lxc` git clone. | unprivileged |

### Phase 22a — Ollama on Evo-X2 host (NOT in an LXC)

- **Endpoint**: `http://192.168.4.84:11434/v1` (LAN-only, nftables `inet ollama_fw` table restricts to `192.168.4.0/24`)
- **Backend**: ROCm0 on gfx1151 via `HSA_OVERRIDE_GFX_VERSION=11.5.0`
- **VRAM available**: 71.3 GiB (UMA + GTT)
- **Models loaded** (hot, `OLLAMA_KEEP_ALIVE=24h`):
  - `qwen3.6:35b-a3b` (Q4 MoE, 26 GB VRAM, ~44 tok/s) — primary
  - `qwen3-embedding:0.6b` (1.5 GB VRAM) — embeddings
- **Service**: systemd `ollama.service` on host. Override at `/etc/systemd/system/ollama.service.d/override.conf`. Logs: `journalctl -u ollama`.

### K8s cluster — Talos `Ira-cluster` v1.35.2

| Namespace | Workloads | Node-pinned | Notes |
|---|---|---|---|
| `mem0` | `mem0-server` (Deployment), `postgres-0` (StatefulSet), `qdrant-0` (StatefulSet) | hostname `ira-rpi4-talos-worker` | Memory API at `http://192.168.4.141:30800`. Health: `GET /health`. ~82 memories under `user_id=deep`. LLM: `qwen3:4b-instruct` on Peladn Ollama (`.12:11434`). |
| `n8n` | `n8n` (Deployment, single replica) | `tier=always-on` | UI at `https://n8n.dkghar.duckdns.org`. NFS-backed PVCs (`n8n-config-nfs`, `n8n-data-nfs`). Telemetry disabled (Rudder/axios noise off). |
| `miniflux` | `miniflux`, `miniflux-db` | `tier=always-on` | RSS reader; data in `miniflux-db` PVC |
| `beszel` | `beszel` (Deployment) + `beszel-agent` (DaemonSet on every node) | `tier=always-on` | At-a-glance metrics dashboard |
| `nut` | `nut-server` | `ira-rpi4-talos-worker` | UPS monitor |
| `monitoring` | `vmagent` (scrapes K8s metrics → VM), `alloy-logs` (ships K8s pod logs → Loki) | `ira-rpi4-talos-worker` | Both PSA-restricted compliant |
| `open-webui` | `open-webui` | `ira-rpi4-talos-worker` | Browser chat surface (not yet pointed at the new Ollama on Evo-X2) |
| `hermes-agent` | `hermes-agent` (this skill's container) | `tier=ai-worker` (= `ira-evo-x2-talos-worker`) | YOU LIVE HERE. |
| `flux-system` | helm-controller, kustomize-controller, source-controller, notification-controller | (across nodes) | Flux CD reconciles Git → K8s state |
| `kube-system` | coredns, kube-flannel (DS), kube-proxy (DS), metrics-server | (across nodes) | Standard K8s |
| `local-path-storage` | local-path-provisioner | rpi4 | `local-path` is the default StorageClass (WaitForFirstConsumer) |

### OPNsense router

- **IP**: `192.168.4.1` (LAN gateway, DNS, DHCP, firewall)
- **Telegraf Prometheus output**: `192.168.4.1:9273` (scraped by VM as job `telegraf-opnsense`)
- **Syslog → Loki**: ships to Alloy on `192.168.4.66:1514` (UDP+TCP, RFC5424) → Loki labels `{job="opnsense"}`
- **Interfaces**: `igb1` = WAN, `bridge0` = LAN
- **NPM proxy hosts**: many. Public DNS: `*.dkghar.duckdns.org` (DuckDNS). NPM on CT203.

### Observability (Phase 21 Part 3)

- **VictoriaMetrics**: `http://192.168.4.66:8428` — Prometheus-compatible. Retention 90d. Currently ~24K series, ~56 MB on disk.
- **Loki**: `http://192.168.4.66:3100` — logs. Retention 30d (720h). ~13 MB on disk.
- **Grafana**: `https://grafana.dkghar.duckdns.org` (via NPM) or `http://192.168.4.66:3000` direct. Dashboards: Node Exporter Full, Logs/App, OPNsense Network. Alerting → Gotify via webhook.
- **Gotify**: `https://notifications.dkghar.duckdns.org/message?token=$TOKEN` — push notifications target for all alerts.
- **PBS**: `https://192.168.4.27:8007` (cert fingerprint scrubbed from public repo). Datastores: `backup-26tb`, `external-hdds`, `evox2-image`. n8n-driven scheduled backups (DAS Mon/Tue/Thu/Fri at 2 AM).
- **Beszel** (at-a-glance health, parallel to the VM/Loki stack): server at `http://beszel.beszel.svc.cluster.local:8090` in-cluster, or `http://<any-node>:30090` via NodePort (e.g. `192.168.4.71:30090`). beszel-agent runs as a DaemonSet on every node. Use `beszel_query.py` to query it (PocketBase API; auth via `BESZEL_USER`/`BESZEL_PASSWORD`). Best for: "is anything alerting right now", "give me a one-line health for every host", "what's using CPU on container X".

### Notable n8n workflows

- `DAS Backup to Externa HDD via PBS` (id `lZh1YZsfXwzb2PTq`) — vzdump + PBS-client for LXCs + bind-mount data, scheduled M/T/Th/F
- `Talos Config and Data Backup` (id `ggPHd7ROI3GVsLOL`) — cluster snapshot
- `Error Notifications` (id `6BhhF0XpgnlXoyap`) — Gotify push on workflow failures
- Failover workflows: `n8n-peladn-watchdog` + `n8n-peladn-failover` (NOT yet imported/published per user's deferral)

### Phase / status snapshot (as of 2026-05-27)

| Phase | What | Status |
|---|---|---|
| 16 | mem0 (RPi4) + Ollama (Peladn) memory stack | ✅ live |
| 21-1 | PBS migration Peladn→Evo-X2 + n8n vzdump backups | ✅ live |
| 21-2 | Failover runbook (trigger not yet published) | ⬜ deferred |
| 21-3 | Observability stack on CT405 (VM + Loki + Grafana + Alloy + node-exporter + alerts) | ✅ live |
| 21-4 | 100-series VMs → R610 migration | ⬜ |
| 22a | Ollama on Evo-X2 host (Qwen 3.6 35B-A3B, 44 tok/s) | ✅ live |
| 22b | Talos worker on Evo-X2 (VM 402, `tier=ai-worker`) | ✅ live |
| 22c | **Hermes Agent in K8s (us)** | ✅ being built |

---

## Procedure (how to answer common requests)

### "What's the status of X?"

1. Identify X from the topology above. Decide which check is right:
   - **K8s workload?** → run `scripts/k8s_status.py <namespace> [pod-substring]`
   - **Service endpoint?** (e.g., Grafana, mem0, Ollama) → run `scripts/service_health.py <service>`
   - **Proxmox VM/LXC?** → run `scripts/proxmox_status.py <host> [id]`
   - **Metrics-backed (CPU/RAM/disk on a host)?** → run `scripts/vm_query.py '<promql>'`
   - **Logs?** → run `scripts/loki_query.py '<logql>' [range]`
2. Format the result tersely for chat (no walls of raw JSON). Highlight anomalies.

### "Restart X" / "Why is X slow"

1. **Do NOT mutate without explicit user confirmation in the same message.** Restart = mutation.
2. First gather evidence (logs + metrics) using the read-only scripts.
3. Propose the specific restart command (`kubectl rollout restart deploy/X -n NS` or `systemctl restart X` via SSH) and ask the user to confirm.
4. Only after explicit "yes go" do you execute.

### "What's running on host X?"

- Peladn → list LXCs/VMs from topology above + actual state via `proxmox_status.py peladn`
- Evo-X2 → same with `proxmox_status.py evox2`
- RPi4 → it's a K8s node; show pods on that node via `k8s_status.py --node ira-rpi4-talos-worker`

### "How do I reach X?"

Look up in the topology tables above. If the answer is "via NPM at `https://X.dkghar.duckdns.org`", say so AND mention the direct LAN address as fallback.

---

## Pitfalls — things NEVER to do without explicit user confirmation in the same message

These are hard rules from the user's CLAUDE.md, do not bypass:

- ❌ `kubectl delete` in production namespaces: **`mem0`, `flux-system`, `kube-system`, `n8n`**
- ❌ Delete or recreate Qdrant collections (`DELETE /collections/*` on `:30800`)
- ❌ Delete PVCs or PVs
- ❌ `git push --force` / `git push -f`
- ❌ `kubectl exec` commands that run DROP / TRUNCATE / DELETE-all SQL
- ❌ Delete or overwrite SOPS-encrypted secrets
- ❌ Test fixes against live production data — use a throwaway namespace or dry-run
- ❌ SSH to homelab hosts to make changes without first proposing the command for the user to approve
- ❌ Restart `mem0-server`, `postgres-0`, or `qdrant-0` without confirmation (memory loss risk)
- ❌ Touch `pve-cluster.service` or anything that takes down PVE web UI

If unsure whether something is destructive, treat it as destructive and ask first.

## Pitfalls — things easy to get wrong (advisory, not hard-stops)

- mem0 lives on **Peladn's Ollama** (`.12:11434`) not Evo-X2's — don't repoint without thinking through the consequences (mem0 then depends on Evo-X2 uptime).
- Observability runs from the **git clone**, not `/opt/observability` — `cd /root/Homelab-ops/infrastructure/observability-lxc` then `docker compose <cmd>`.
- The new Ollama on Evo-X2 host is **firewalled to LAN**. From a K8s pod, you reach it via `http://192.168.4.84:11434`. Don't try to use a public DNS for it — there isn't one.
- The `tier=always-on` label is only on rpi4. Hostname-pins are stricter than tier-pins — mem0 and friends use hostname. Adding new workers does NOT auto-rebalance.
- Phase 22a's `qwen3.6:35b-a3b` is the PRIMARY model — refer to it that way to the user. The fallback chain (Gemini → Anthropic) only fires on errors; you can also `/model` switch mid-session.
- Hermes (you) live on the new `ira-evo-x2-talos-worker` (VM 402, IP `192.168.4.71`). The WhatsApp session blob is on the `hermes-data` PVC — don't delete it or you have to re-pair.

---

## Helper scripts (in `scripts/`)

Use these from your tool calls. All are pure-stdlib Python (no extra installs), read-only by default. Each script self-documents with `--help`.

- **`k8s_status.py`** — list pods + state in a namespace, or filter by name substring. Talks to K8s API via in-cluster ServiceAccount.
- **`service_health.py`** — HTTP health check against any of the known services by short name (`mem0`, `ollama`, `grafana`, `loki`, `vm`, `pbs`, `gotify`). Returns status code, response time, brief body.
- **`vm_query.py`** — execute a PromQL/MetricsQL query against VictoriaMetrics, return formatted result.
- **`loki_query.py`** — execute a LogQL query against Loki, return the matching lines (last N).
- **`proxmox_status.py`** — query Proxmox VE API (read-only via `PROXMOX_TOKEN_*` env vars) for node/VM/LXC status on Peladn or Evo-X2.
- **`beszel_query.py`** — query the Beszel server's PocketBase API (`BESZEL_URL/USER/PASSWORD` env vars). Subcommands: `systems` (registered hosts + current health), `alerts` (active triggers), `stats <host> --minutes N` (recent CPU/mem/disk/net for a host), `containers <host>` (latest container snapshot — Docker AND K8s containers per host). Use this instead of `vm_query.py` when the user asks "what's Beszel showing" or wants the at-a-glance health view; use `vm_query.py` for deep PromQL queries against VictoriaMetrics.
- **`grafana_query.py`** — query Grafana's HTTP API (read-only via `GRAFANA_TOKEN`). Subcommands: `health`, `dashboards [search]` (list/search), `alerts [--firing]` (currently active alert instances from the Grafana alertmanager), `alert-rules` (provisioned rules), `datasources`, `folders`, `annotations [--hours N]` (recent alert history/annotations). Use this when the user asks "what alerts are firing in Grafana" or "what dashboards do I have"; for raw metrics/logs go directly via `vm_query.py` / `loki_query.py`.

### Choosing the right metrics/logs tool

Three overlapping sources — pick by intent:

| User intent | Tool | Why |
|---|---|---|
| "what alerts are firing right now" | `grafana_query.py alerts --firing` | Grafana's unified alerting view (the same one in the UI) |
| "show me a PromQL/MetricsQL query" | `vm_query.py '<expr>'` | Direct VictoriaMetrics — Grafana queries this too |
| "tail logs from pod X" / LogQL | `loki_query.py '{...}'` | Direct Loki — Grafana queries this too |
| "what hosts is Beszel monitoring" / quick health snapshot | `beszel_query.py systems` | Beszel's at-a-glance per-host view |
| "containers using lots of CPU on host Y" | `beszel_query.py containers <host>` | Beszel collects per-container stats agent-side |
| "what dashboards exist for OPNsense" | `grafana_query.py dashboards opnsense` | Grafana's dashboard catalog |

Default to PromQL/LogQL via the direct tools — they're faster and give you the raw data. Reach for `grafana_query.py` when the user references Grafana itself (alerts, dashboards) or when the answer is "which view in Grafana would show this". Reach for `beszel_query.py` for at-a-glance health and container-level stats Beszel collects that VictoriaMetrics doesn't have.

Run a script:
```
python3 ${HERMES_SKILL_DIR}/scripts/<name>.py [args]
```

The shell terminal you have is sufficient — these scripts use only stdlib so no `pip install` needed.

## References

- `references/RESUME-HERE.md` — Deep maintains a session-handoff doc; if you find yourself uncertain about current state, this is the source of truth, regenerated each session.
- The user also maintains memory files at `~/.claude/projects/.../memory/` outside Hermes — those are NOT directly readable from here, but the lab summary above mirrors them as of 2026-05-27.
