# ADR-005: gemma4:e2b over qwen2.5:7b for mem0 LLM

**Date:** 2026-05  
**Status:** Accepted

## Context

mem0 uses an LLM to extract structured facts from conversations before storing them as memories. The initial model was `qwen2.5:7b` (a custom Ollama model `qwen2.5-mem0`), running on the AMD 780M iGPU via ROCm in `media-ai-ops-lxc`.

The 780M is an integrated GPU sharing system RAM (Peladn 32 GB). Under concurrent mem0 requests, `qwen2.5:7b` (4.7 GB loaded) caused the Ollama model runner to OOM and crash, returning 500 errors to the mem0 server.

## Decision

Switch to **`gemma4:e2b`** (Google Gemma 4, Efficient 2B variant) as the base model, wrapped in a custom `gemma4-mem0` Ollama model.

## Rationale

| Model | Size loaded | 780M stability | Quality for extraction |
| ----- | ----------- | -------------- | ---------------------- |
| `qwen2.5:7b` | ~4.7 GB | ❌ OOM crashes | High |
| `gemma4:e2b` | ~1.5 GB | ✅ Stable | Sufficient |
| `qwen2.5:0.5b` | ~0.4 GB | ✅ Stable | Lower |

`gemma4:e2b` hits the sweet spot: recent architecture (Gemma 4 family, 2026), stable on the 780M with headroom for concurrent nomic-embed-text inference, and produces quality JSON extraction with the right system prompt.

The system prompt in `gemma4-mem0` provides full homelab context so the model extracts relevant, durable facts rather than generic JSON — effectively making the system prompt the primary quality lever, not model size.

## Consequences

- `gemma4:e2b` must be pulled to the Ollama instance before deploying: `ollama pull gemma4:e2b`
- The custom `gemma4-mem0` model is re-created by running `docker/mem0-server/push-modelfile.py` after any system prompt changes
- `personal-context.txt` (gitignored) holds the personal context injected at model creation time
- If upgrading to a more powerful always-on host with dedicated VRAM, revisit this decision — a 7B model with the right system prompt would produce higher-quality extractions
