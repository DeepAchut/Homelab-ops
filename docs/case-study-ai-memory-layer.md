# Case Study: Self-Hosted AI Memory Layer with mem0

**Problem:** AI assistants (Claude, Gemini, local LLMs) have no persistent memory between sessions. Each conversation starts cold — re-explaining context wastes time and produces worse results.

**Solution:** Deploy mem0 as a self-hosted REST API on K8s. Every AI tool in the homelab writes facts to it and reads context from it at session start. Memory persists across sessions, tools, and devices.

---

## Why Self-Host?

| Concern | Cloud mem0 | This implementation |
| ------- | ---------- | ------------------- |
| Data privacy | Facts leave your network | Stays on-prem |
| Cost at scale | Per-API-call pricing | Fixed hardware cost |
| Latency | Network round-trip | LAN speed |
| Model choice | OpenAI-tied | Any Ollama model |
| Vendor lock-in | High | None |

---

## Architecture

```text
                    ┌─────────────────────────────────┐
                    │  mem0 namespace (Talos K8s)      │
                    │                                 │
 Claude Code ──────▶│  mem0-server (FastAPI)          │
 n8n workflows ────▶│  NodePort :30800                │
 Obsidian ─────────▶│         │                       │
                    │    ┌────┴──────┐  ┌──────────┐  │
                    │    │ Postgres  │  │ Qdrant   │  │
                    │    │ (history) │  │ (vectors)│  │
                    │    └───────────┘  └──────────┘  │
                    └─────────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────────┐
                    │  media-ai-ops-lxc (Peladn)    │
                    │  Ollama — AMD 780M ROCm        │
                    │  ├── gemma4-mem0 (LLM)         │
                    │  └── nomic-embed-text (768d)   │
                    └───────────────────────────────┘
```

---

## Key Implementation Decisions

### 1. Ollama on AMD 780M instead of cloud LLM

The Peladn base station has an AMD Ryzen AI 9 HX 8845HS with integrated Radeon 780M (RDNA3). By installing Ollama with ROCm 6.4 support inside an LXC (`/dev/kfd` passthrough via cgroup2), all LLM inference runs locally at zero marginal cost.

**Critical fix:** Ollama's bundled libraries include CUDA and Vulkan runners but not the AMD ROCm runner. You must install via the official script (`curl -fsSL https://ollama.com/install.sh | sh`) which detects `/dev/kfd` and downloads the ROCm runner.

### 2. Qdrant for vectors, Postgres for history

mem0 needs two stores: a vector DB (semantic search over memories) and a relational DB (conversation history, metadata). Qdrant and Postgres each run as StatefulSets with local-path PVCs on the RPi4.

**Why local-path over NFS:** Postgres and Qdrant use WAL and internal locking that NFS can silently corrupt under network flap. Primary data stays on local disk; backups push to NFS via CronJob.

### 3. Custom LLM model (`gemma4-mem0`)

A vanilla LLM extracts generic JSON. A context-aware model extracts *relevant* facts. The `gemma4-mem0` model is built on `gemma4:e2b` with a system prompt containing:

- Your homelab topology (nodes, IPs, services)
- Your role, tools, and preferences
- Instructions to ignore transient content (one-shot commands, build output)
- Instructions to never extract secrets

This dramatically reduces noise in the memory store.

### 4. Startup collection pre-creation

mem0ai (`pip install mem0ai`) does not create the Qdrant collection at startup — it only creates it on the first write, by first searching (which 404s on a missing collection). The fix in `docker/mem0-server/main.py`:

```python
_vs = memory.vector_store
_existing = {c.name for c in _vs.client.get_collections().collections}
if _vs.collection_name not in _existing:
    _vs.client.create_collection(
        collection_name=_vs.collection_name,
        vectors_config=VectorParams(size=_embed_dims, distance=Distance.COSINE),
    )
```

### 5. Claude Code integration via Stop hook

A Python Stop hook (`~/.claude/mem0-sync.py`) fires at the end of every Claude Code session, reads the session transcript, and pushes the last 20 messages to mem0. Each new session starts by querying mem0 for relevant context — configured in `~/.claude/CLAUDE.md`.

---

## Deployment Steps

### Prerequisites

- Talos K8s cluster with local-path-provisioner on a worker node
- Ollama running on an always-on host with `nomic-embed-text` and your LLM pulled
- Flux CD + SOPS configured (see [GitOps case study](case-study-gitops-talos-flux.md))

### 1. Deploy the stack

```bash
# Add mem0 to your apps kustomization
echo "  - ./mem0" >> kubernetes/apps/kustomization.yaml

# Encrypt the Postgres secret
sops --encrypt kubernetes/apps/mem0/postgres/secret.yaml \
  > kubernetes/apps/mem0/postgres/secret.enc.yaml

git add kubernetes/apps/mem0/ && git push
# Flux reconciles within 1-10 min
```

### 2. Verify

```bash
kubectl get pods -n mem0
# mem0-server, postgres-0, qdrant-0 all Running

curl http://<node-ip>:30800/health
# {"status": "ok"}
```

### 3. Deploy the custom LLM model

```bash
cp docker/mem0-server/personal-context.txt.example \
   docker/mem0-server/personal-context.txt
# Edit personal-context.txt with your homelab and personal context
python3 docker/mem0-server/push-modelfile.py
# OK: success
```

### 4. Wire up Claude Code

```bash
# Add to ~/.claude/CLAUDE.md:
# "Query mem0 at session start: POST /v1/memories/search"

# Add Stop hook to ~/.claude/settings.json:
# {"Stop": [{"hooks": [{"type": "command", "command": "python mem0-sync.py"}]}]}
```

---

## Lessons Learned

- **Dimension mismatch kills writes silently** — if you ever change embedding models, delete and recreate the Qdrant collection. Old 1536-dim vectors are incompatible with 768-dim nomic-embed-text.
- **Never test destructive fixes against the production Qdrant collection** — use a throwaway collection name.
- **Lighter LLM = better reliability** — `qwen2.5:7b` OOMed the 780M iGPU under concurrent requests. `gemma4:e2b` (2B params) runs stably with room for embedding inference in parallel.
- **The system prompt is the product** — a generic "extract JSON" prompt produces noise. The personal context model produces signal.
