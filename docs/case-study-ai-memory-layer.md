# Case Study: Self-Hosted AI Memory Layer — from mem0 to Hindsight

**Problem:** AI assistants (Claude, Gemini, local LLMs) have no persistent memory between sessions. Each conversation starts cold — re-explaining context wastes time and produces worse results.

**Solution:** Run a self-hosted memory service on the K8s cluster. Every AI tool in the homelab writes facts to it and reads context from it at session start, over a native MCP endpoint. Memory persists across sessions, tools, and devices — and never leaves the network.

This layer was first built on **mem0**, then migrated to **[Hindsight](https://github.com/vectorize-io/hindsight)** once real-world use exposed mem0's limits. The migration itself — evaluate, back up, test, cut over — is part of the case study.

---

## Why migrate off mem0?

mem0 (self-hosted, `mem0-server` FastAPI wrapper + Qdrant + Postgres) worked, but daily use surfaced three friction points:

| Limitation | Impact |
| ---------- | ------ |
| No native MCP server | Needed a custom stdio bridge to connect Claude Code — extra moving part |
| Lossy LLM extraction | Facts were silently dropped/merged; required hand-feeding atomic one-idea notes |
| No visualization | Memories were an opaque vector blob; no way to browse or audit them |

Three replacements were evaluated against the actual use case (self-hosted, central, MCP-native, good recall):

- **OpenMemory** — rejected: it *is* mem0 underneath (same engine), so it fixes nothing.
- **Squish** — interesting (local-first, no-LLM), but immature, local-first (fights a central multi-client model), and auto-decays old memories.
- **Hindsight** — chosen: MIT, one-command self-host, **native MCP**, a built-in web UI, and best-in-class retrieval (94.6% on LongMemEval, independently reproduced) using four parallel strategies + a cross-encoder reranker.

---

## Why Self-Host?

| Concern | Cloud memory SaaS | This implementation |
| ------- | ----------------- | ------------------- |
| Data privacy | Facts leave your network | Stays on-prem |
| Cost at scale | Per-API-call pricing | Fixed hardware cost |
| Latency | Network round-trip | LAN speed |
| Model choice | Vendor-tied | Any Ollama model |
| Vendor lock-in | High | None (MIT, portable export) |

---

## Architecture

```text
                    ┌──────────────────────────────────────┐
                    │  hindsight namespace (Talos K8s)      │
 Claude Code ─MCP──▶│  evo-x2 ai-worker node (amd64)        │
 Cline ──────MCP──▶ │                                       │
 REST clients ────▶ │  hindsight (all-in-one pod)           │
                    │   ├── API + MCP   :8888 (NodePort 30888)
                    │   ├── Web UI      :9999 (NodePort 30999)
                    │   ├── Postgres + pgvector (embedded)  │
                    │   ├── embeddings  bge-small-en (384d) │  ← local, in-pod
                    │   └── reranker    ms-marco-MiniLM     │  ← local, in-pod
                    └──────────────────┬───────────────────┘
                                       │ retain-time extraction only
                    ┌──────────────────▼───────────────────┐
                    │  Evo-X2 host — Ollama (always-on)     │
                    │  qwen3:4b-instruct (JSON fact extract)│
                    └───────────────────────────────────────┘
```

Retrieval (semantic + BM25 keyword + knowledge-graph + temporal, merged by a cross-encoder reranker) runs entirely **local to the pod**. Only retain-time fact extraction calls out to Ollama.

---

## Key Implementation Decisions

### 1. Node selection: reranker weight, not just CPU arch

Hindsight ships a multi-arch image, so it *runs* on the arm64 Raspberry Pi 4 that previously hosted mem0. But it was placed on the **evo-x2 ai-worker (amd64, 8 GB)** instead, because — unlike mem0, which offloaded all inference to Ollama — Hindsight's **cross-encoder reranker runs locally in-pod**. On the 4 GB Pi (already hosting n8n, homepage, monitoring) that would risk OOM-evicting existing services. Right-sizing means matching the workload's *local* footprint, not just the CPU architecture.

### 2. A non-thinking extraction LLM (the JSON trap)

`retain` uses an LLM to extract facts and build the knowledge graph, and it expects strict JSON back. The first choice, a strong 35B "thinking" model, **broke extraction**: its reasoning tokens polluted the output (`JSONDecodeError: Extra data`), and each call took ~35 s — 4.5 hours just to import the back catalog.

Switching to **`qwen3:4b-instruct`** (a non-thinking instruct model) fixed both: clean JSON in every response-format mode, at ~1 s per call. Reasoning models and structured extraction don't mix — the small instruct model is the correct tool, and Hindsight's local four-strategy retrieval + reranker carry recall quality regardless of extractor size. `HINDSIGHT_API_LLM_STRICT_SCHEMA=true` and a low temperature make extraction deterministic.

### 3. Local embeddings + reranker (no embedding service to manage)

Embeddings (`bge-small-en-v1.5`, 384-d) and the reranker (`ms-marco-MiniLM-L-6-v2`) run in-process and are cached to the PVC via `HF_HOME`. That removes an entire external dependency (mem0 needed a separate Ollama embedding model + a Qdrant collection dimensioned to match it) and eliminates the dimension-mismatch class of bugs.

### 4. Stateful pod hygiene on Kubernetes

- **Non-root data dir:** the image runs as user `hindsight`, but a local-path PVC mounts root-owned. An `initContainer` (reusing the same image so it can resolve the user by name) `chown`s `/home/hindsight/.pg0` before the embedded Postgres starts.
- **Stable worker id:** a Deployment pod's hostname changes on recreate, which can orphan in-flight consolidation tasks. `HINDSIGHT_API_WORKER_ID=hindsight-0` pins it (single replica, `Recreate` strategy on one RWO volume).

### 5. Native MCP — no bridge

Hindsight exposes MCP directly at `:8888/mcp/{bank}/` (streamable HTTP). Claude Code connects with a one-liner (`claude mcp add --transport http --scope user hindsight …/mcp/deep/`) — the custom Python stdio bridge that mem0 required is gone. Memories are organized into **banks** (namespaces): `deep` (primary), `family` (secondary).

### 6. Test-first migration

Nothing was deleted until the data was safe: all 465 mem0 memories were exported straight from the Qdrant collection to a versioned JSON file (plus a fresh Qdrant snapshot + Postgres dump on NFS). Only then was mem0 pruned via GitOps and Hindsight brought up. The export was re-imported with a batched, per-item-fallback loader so a single malformed record couldn't sink the run.

---

## Deployment (GitOps)

```bash
# Manifests: kubernetes/apps/hindsight/  (namespace, pvc, deployment, service)
# Pinned to the ai-worker; LLM -> .84 Ollama; embeddings + reranker local.
echo "  - hindsight" >> kubernetes/apps/kustomization.yaml
git add kubernetes/apps/hindsight/ && git push     # Flux reconciles

kubectl -n hindsight get pods           # hindsight-… Running
curl http://<node>:30888/health         # 200
```

Retain / recall over REST (also available as MCP tools):

```bash
# save
curl -X POST http://<node>:30888/v1/default/banks/deep/memories \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"content":"Backups run nightly to the DAS over USB3."}]}'

# search
curl -X POST http://<node>:30888/v1/default/banks/deep/memories/recall \
  -H 'Content-Type: application/json' -d '{"query":"how are backups done"}'
```

---

## Results

- **465 memories** migrated from mem0 into Hindsight with zero data loss (versioned export retained as the source of truth during cutover).
- Retain latency dropped from ~35 s (thinking model) to **~1–5 s** with `qwen3:4b-instruct`.
- One integrated stack (API + MCP + UI + DB) replaced four components (mem0-server + Qdrant + Postgres + a bolt-on viewer) — *fewer* moving parts, plus a native MCP and a UI.

---

## Lessons Learned

- **Reasoning models break structured extraction.** Thinking-token output is not valid JSON. Use a non-thinking instruct model for any extract-to-schema step (this bit both mem0 and Hindsight).
- **Right-size by the *local* footprint.** An arm64-compatible image still doesn't belong on a 4 GB Pi if it runs a reranker in-process. Know which parts offload and which don't.
- **Migrate data-first.** Export and verify a portable copy before deleting anything; keep the old system's backups until the new one is proven.
- **Prefer the fewest components that meet the need.** The best replacement folded storage, retrieval, MCP, and UI into one deployable — and deleted a bespoke bridge in the process.
