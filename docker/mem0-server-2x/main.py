"""mem0 API server — mem0ai 2.x.

Ported from the 0.1.x server (docker/mem0-server/main.py). Same REST surface so
existing clients (CLAUDE.md curl, the ~/.claude/mem0-mcp.py bridge, Hermes) work
unchanged. Breaking changes handled vs 0.1.x:
  - Memory.search(): `limit` -> `top_k`; user_id/agent_id/run_id -> `filters={}`
  - Memory.get_all(): user_id/etc -> `filters={}`; `top_k` defaults to 20, so we
    pass a high value to keep "return all for this user" behaviour.
  - add/delete/delete_all signatures unchanged.
The critical qwen3 `think=False` patch is retained (2.x's Ollama LLM still calls
ollama.Client.chat). Telemetry (PostHog) disabled before importing mem0.
"""
import inspect
import logging
import os

# Disable mem0's PostHog telemetry BEFORE importing mem0 (noisy + phones home).
os.environ.setdefault("MEM0_TELEMETRY", "false")
os.environ.setdefault("MEM0_TELEMETRY_ENABLED", "false")

from contextlib import asynccontextmanager
from typing import List, Optional

import ollama
import yaml
from fastapi import FastAPI, HTTPException
from mem0 import Memory
from pydantic import BaseModel
from qdrant_client.models import Distance, VectorParams

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mem0-server")

# qwen3 enables thinking by default; with format=json the answer lands in the
# response's `thinking` field and `content` is empty, so mem0's json.loads()
# fails and extracts zero facts. Forcing think=False on ollama.Client.chat is the
# only reliable disable (Modelfile PARAMETER and /no_think do not work). mem0 2.x
# still routes LLM calls through ollama.Client.chat; embeddings use a different
# method, so this only affects the extraction LLM.
if "think" in inspect.signature(ollama.Client.chat).parameters:
    _orig_chat = ollama.Client.chat

    def _chat_no_think(self, *args, **kwargs):
        kwargs.setdefault("think", False)
        return _orig_chat(self, *args, **kwargs)

    ollama.Client.chat = _chat_no_think
    logger.info("patched ollama.Client.chat with think=False")
else:
    logger.warning("ollama.Client.chat has no 'think' param — extraction may break")

_state: dict = {"memory": None}


def _filters(user_id, agent_id=None, run_id=None) -> dict:
    """Build the mem0 2.x filters dict (only non-None keys)."""
    f = {"user_id": user_id}
    if agent_id:
        f["agent_id"] = agent_id
    if run_id:
        f["run_id"] = run_id
    return f


def _build_memory() -> Memory:
    config_path = os.getenv("MEM0_CONFIG_PATH", "/app/config/config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        config["history_db_url"] = db_url

    memory = Memory.from_config(config)

    # mem0 doesn't create the Qdrant collection at init — only on first write,
    # which searches before inserting and 404s on a fresh/deleted collection.
    vs = memory.vector_store
    existing = {c.name for c in vs.client.get_collections().collections}
    if vs.collection_name not in existing:
        dims = (
            config.get("vector_store", {}).get("config", {}).get("embedding_model_dims", 768)
        )
        vs.client.create_collection(
            collection_name=vs.collection_name,
            vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
        )
        logger.info("created Qdrant collection '%s' (dims=%s)", vs.collection_name, dims)

    return memory


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("initializing mem0 Memory (mem0ai 2.x)...")
    _state["memory"] = _build_memory()
    logger.info("mem0 Memory ready")
    yield
    _state["memory"] = None


app = FastAPI(title="mem0 API Server (2.x)", lifespan=lifespan)


def get_memory() -> Memory:
    memory = _state["memory"]
    if memory is None:
        raise HTTPException(status_code=503, detail="memory not initialized")
    return memory


class AddRequest(BaseModel):
    messages: List[dict]
    user_id: str = "default"
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[dict] = None
    infer: bool = True


class SearchRequest(BaseModel):
    query: str
    user_id: str = "default"
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    limit: int = 10


@app.get("/health")
def health():
    return {"status": "ok", "memory_ready": _state["memory"] is not None}


@app.post("/v1/memories")
def add_memories(req: AddRequest):
    memory = get_memory()
    try:
        return memory.add(
            req.messages,
            user_id=req.user_id,
            agent_id=req.agent_id,
            run_id=req.run_id,
            metadata=req.metadata,
            infer=req.infer,
        )
    except Exception as e:
        logger.exception("add_memories failed")
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")


@app.get("/v1/memories")
def get_memories(
    user_id: str = "default",
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 2000,
):
    memory = get_memory()
    try:
        # 2.x: user_id/etc via filters; top_k default is 20, so pass a high value.
        return memory.get_all(filters=_filters(user_id, agent_id, run_id), top_k=limit)
    except Exception as e:
        logger.exception("get_memories failed")
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")


@app.post("/v1/memories/search")
def search_memories(req: SearchRequest):
    memory = get_memory()
    try:
        # 2.x: `limit` -> `top_k`; user_id/etc via filters.
        return memory.search(
            req.query,
            top_k=req.limit,
            filters=_filters(req.user_id, req.agent_id, req.run_id),
        )
    except Exception as e:
        logger.exception("search_memories failed")
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")


@app.delete("/v1/memories/{memory_id}")
def delete_memory(memory_id: str):
    memory = get_memory()
    try:
        memory.delete(memory_id)
        return {"message": "Memory deleted", "id": memory_id}
    except Exception as e:
        logger.exception("delete_memory failed")
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")


@app.delete("/v1/memories")
def delete_all_memories(user_id: str = "default"):
    memory = get_memory()
    try:
        memory.delete_all(user_id=user_id)
        return {"message": "All memories deleted for user", "user_id": user_id}
    except Exception as e:
        logger.exception("delete_all_memories failed")
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")
