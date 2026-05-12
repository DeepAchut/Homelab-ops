# mem0 — Self-Hosted AI Memory Layer

Stateful, multi-agent memory for LLM applications. Stores facts extracted from conversations in a vector + relational database, enabling AI tools to recall context across sessions.

## Architecture

```text
Claude Code / n8n / Obsidian
         │  REST  │  MCP
         ▼        ▼
    mem0-server (FastAPI)
         │
    ┌────┴─────────────┐
    │                  │
 Postgres           Qdrant
 (history DB)    (vector store)
         │
    Ollama (LLM + embedder)
    gemma4-mem0 + nomic-embed-text
```

## Components

| Resource | Kind | Notes |
| -------- | ---- | ----- |
| `postgres/` | StatefulSet | pgvector-enabled Postgres, local-path PVC |
| `qdrant/` | StatefulSet | Vector store, local-path PVC, 768-dim collection |
| `server/` | Deployment | Custom FastAPI image, NodePort 30800 |
| `mcp/` | Deployment | MCP bridge for Claude Code integration |

## Configuration

Environment-specific values (see [`cluster.env.example`](../../../../cluster.env.example)):

| Variable | Used in | Default |
| -------- | ------- | ------- |
| `OLLAMA_ALWAYS_ON_URL` | `server/configmap.yaml` | `http://192.168.4.12:11434` |
| `MEM0_LLM_MODEL` | `server/configmap.yaml` | `gemma4-mem0` |
| `MEM0_EMBED_MODEL` | `server/configmap.yaml` | `nomic-embed-text` |
| `MEM0_EMBED_DIMS` | `server/configmap.yaml` | `768` |
| `NFS_SERVER_IP` | `postgres/backup-cronjob.yaml` | `192.168.4.150` |

## API

```bash
# Health
curl http://<node-ip>:30800/health

# Add memory
curl -X POST http://<node-ip>:30800/v1/memories \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "fact"}], "user_id": "you"}'

# Search
curl -X POST http://<node-ip>:30800/v1/memories/search \
  -H "Content-Type: application/json" \
  -d '{"query": "what do I prefer?", "user_id": "you", "limit": 5}'
```

## Custom LLM Model

The mem0 server uses a custom Ollama model (`gemma4-mem0`) tuned for memory extraction. To deploy or update it:

```bash
# Fill in your personal context first
cp docker/mem0-server/personal-context.txt.example docker/mem0-server/personal-context.txt
# Edit personal-context.txt, then:
python3 docker/mem0-server/push-modelfile.py
```

## Troubleshooting

**500 errors on `/v1/memories`** — Ollama model runner crashed (memory pressure). Switch to a lighter model or reduce concurrent requests. Check: `kubectl logs -n mem0 deploy/mem0-server`.

**Qdrant 404 on first write** — Collection not pre-created. The `main.py` startup block handles this automatically; check it ran: `kubectl logs -n mem0 deploy/mem0-server | grep -i qdrant`.

**Dimension mismatch error** — Collection was created with wrong dims. Delete and recreate: port-forward Qdrant `:6333`, `DELETE /collections/mem0`, restart mem0-server pod.

## Solution Guide

See [`docs/case-study-ai-memory-layer.md`](../../../../docs/case-study-ai-memory-layer.md) for a full deployment walkthrough.
