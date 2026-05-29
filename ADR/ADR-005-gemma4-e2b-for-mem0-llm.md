# ADR-005: qwen3:4b-instruct for mem0 LLM (with qwen3-embedding:0.6b)

**Date:** 2026-05 (settled)
**Status:** Accepted
**Supersedes:** an earlier interim choice of `gemma4:e2b` that was never durably deployed.

## Context

mem0 runs an LLM to extract structured facts from conversations before storing them as memories, plus an embedder to vectorise those facts into Qdrant. Both run on the Peladn-side Ollama at `http://192.168.4.12:11434` (`media-ai-ops-lxc`), backed by the AMD 780M iGPU via ROCm.

The 780M is an integrated GPU sharing system RAM (Peladn has 32 GB total). It is the *always-on* tier — by design, mem0 inference must run there, not on the bigger Evo-X2 host, so memory writes don't depend on Evo-X2 availability. That constraint caps model size hard: anything that pushes VRAM+KV cache much past ~3 GB causes the Ollama model runner to OOM and return 500s to the mem0 server.

Three candidates were trialled in May 2026:

1. `qwen2.5:7b` (Q4_K_M, ~4.7 GB loaded) — high extraction quality, but **OOM-crashed under any concurrency** with the embedder.
2. `gemma4:e2b` (~1.5 GB loaded) — stable, low-overhead, but **JSON-extraction quality was inconsistent** even with a careful system prompt; the small parameter count showed at the structured-output boundary.
3. **`qwen3:4b-instruct`** (Q4_K_M, ~2.5 GB loaded) — stable on the 780M with headroom for the concurrent embedder, and extraction quality matches the larger 7B baseline for mem0's use case.

For the embedder, `qwen3-embedding:0.6b` (0.6 GB, **1024-dim output**) replaces the previously-considered `nomic-embed-text`. The 1024-dim matches the Qdrant collection schema (`embedding_model_dims: 1024`); changing this requires migrating the existing 82-memory collection, so the dim choice has weight.

## Decision

| Slot | Model | Notes |
| --- | --- | --- |
| **LLM (fact extraction)** | `qwen3:4b-instruct` | Stock Ollama tag, no custom Modelfile wrapper |
| **Embedder** | `qwen3-embedding:0.6b` | 1024-dim, matches Qdrant collection |
| **Backend** | Ollama on Peladn `media-ai-ops-lxc` (`192.168.4.12:11434`) | Always-on tier |
| **Vector store** | Qdrant `mem0` collection, 1024-dim cosine | On the rpi4 Talos worker |

mem0's `kubernetes/apps/mem0/server/configmap.yaml` references both models by their **stock Ollama tags directly** — there is no longer a custom `gemma4-mem0` / `qwen2.5-mem0` wrapper. System-prompt customisation, if needed in the future, would happen via mem0's own prompt config, not via a Modelfile.

## Rationale

| Model | Loaded | 780M stability under concurrency | JSON-extraction quality | Verdict |
| ----- | ------ | -------------------------------- | ----------------------- | ------- |
| `qwen2.5:7b` | ~4.7 GB | ❌ OOM crashes with embedder loaded | High | Too big for 780M |
| `gemma4:e2b` | ~1.5 GB | ✅ Stable | ⚠ inconsistent on structured-output edges | Worked but extraction quality drifted |
| **`qwen3:4b-instruct`** | ~2.5 GB | ✅ Stable | ✅ Matches 7B baseline for mem0 use case | **Chosen** |

Live verification (2026-05): one full search round-trip ≈ 1.2 s, one full write round-trip ≈ 3.1 s (cold-load), both at HTTP 200. Both models hot-loaded together consume ~4.7 GB iGPU memory — within budget. `mem0-server-config` configmap reflects this stable end state.

## Consequences

- **No custom Ollama wrapper.** mem0 talks to stock `qwen3:4b-instruct` directly. `docker/mem0-server/Modelfile`, `Modelfile.template`, and `push-modelfile.py` are now **legacy from the gemma4-mem0 / qwen2.5-mem0 era** — they are not on any active code path. They can be removed in a future cleanup PR; leaving them in place documents the prior approach and costs nothing.
- **Vector dim is load-bearing.** The Qdrant `mem0` collection is configured for 1024-dim cosine. Switching the embedder requires either matching that dim or re-creating the collection (which would require re-ingesting all 82 existing memories). Don't swap the embedder lightly.
- **Provisioning:** both models must be pulled to the Peladn Ollama before deploying mem0: `ollama pull qwen3:4b-instruct && ollama pull qwen3-embedding:0.6b`. The mem0 deployment will return 500s until both are present.
- **Concurrent-load policy:** `OLLAMA_MAX_LOADED_MODELS=2` and `OLLAMA_KEEP_ALIVE=24h` keep both hot. Lower keep-alive causes the 1.5–2 s cold-load tax on the first request after idle.
- **Trade-off accepted:** mem0 quality is bounded by what a 4B model can extract. If we later move mem0 inference to a larger host (e.g., the Evo-X2 host's `qwen3.6:35b-a3b`), this ADR becomes revisitable — but doing so introduces a hard dependency on Evo-X2 availability for memory *writes*, which violates the "mem0 stays on the always-on tier" design principle. Phase 22 considered this and chose to **keep mem0 on Peladn**.

## Related

- [ADR-001: Talos over k3s](ADR-001-talos-over-k3s.md) — same "always-on tier" reasoning that constrains mem0 placement
- [ADR-003: mem0 over MemPalace](ADR-003-mem0-over-mempalace.md) — establishes mem0 as the memory layer
- Phase 22 research: kept mem0 on Peladn even after deploying Ollama on Evo-X2 host — see [Phase-22-Part-1 - hermes-agent-design-research.md](../../Phase-22-Part-1%20-%20hermes-agent-design-research.md) and the mem0 health check in this session's [Implementation-Summary-2026-05-28.md](../../Implementation-Summary-2026-05-28.md)
