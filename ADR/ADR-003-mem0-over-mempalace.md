# ADR-003: mem0 over MemPalace for AI Memory Layer

**Date:** 2026-04  
**Status:** Accepted

## Context

Needed a self-hosted persistent memory layer for AI tools (Claude Code, n8n, Obsidian). Two candidates evaluated: MemPalace and mem0.

## Decision

Chose **mem0 (OSS)**.

## Rationale

MemPalace was the initial choice but was abandoned after discovering a known ChromaDB concurrency issue that caused 88 GB data corruption in reported incidents (GitHub discussion #904). The project's own maintainers described it as "a toy to fiddle with" in the context of production use.

mem0 (53k+ stars, 300+ releases, YC-backed) uses Postgres + Qdrant — both battle-tested concurrent stores — and is actively used in production by CrewAI, LangGraph, and others. Its `user_id` / `agent_id` model is flat and pragmatic: no Wings, rooms, or emotional states to configure.

| Concern | MemPalace | mem0 |
| ------- | --------- | ---- |
| Concurrency safety | ❌ ChromaDB segfaults | ✅ Postgres + Qdrant |
| Production reputation | "Toy" | Large ecosystem |
| LLM flexibility | Limited | Fully pluggable (Ollama, OpenAI) |
| Community | Active but small | Large + funded |

## Consequences

- Requires running Postgres + Qdrant as additional StatefulSets (~160 MB combined RAM)
- mem0ai Python library doesn't pre-create the Qdrant collection — requires a startup workaround in `main.py`
- All vector dimensions must match between collection creation and the embedder model (768 for nomic-embed-text)
