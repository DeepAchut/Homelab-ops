# open-webui — LLM Chat Interface

> **Status: Scaled to 0 (paused).** Migrating to a dedicated LXC on the i9 GPU server. See [Phase 21 worker management plan](../../../../Phase-21%20-%20worker-management-plan.md).

Web-based chat UI for Ollama. Was running in K8s targeting the i9 Ollama endpoint (WOL burst, RTX 5070). Consumed 755 Mi on the RPi4 while the i9 was powered off — moved out of the always-on K8s worker to run closer to its GPU.

## Migration Target

New home: `ai-webui-lxc` (CT 301) on the i9 Proxmox host — starts and stops with the i9.

```text
i9 Proxmox host (192.168.4.110)
└── ai-webui-lxc (CT 301, Docker Compose)
    ├── open-webui  :3000
    └── OLLAMA_BASE_URL → http://192.168.4.110:11434 (ollama-lxc same host)
```

## Re-enabling in K8s (not recommended)

If you want to run this in K8s, scale up and ensure `OLLAMA_BASE_URL` points to an always-on Ollama endpoint:

```bash
kubectl scale deployment open-webui -n open-webui --replicas=1
```

Add a `nodeAffinity` to `deployment.yaml` pinning it to a WOL burst node with GPU access so it doesn't consume always-on worker RAM.
