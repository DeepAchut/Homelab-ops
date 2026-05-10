import os
import yaml
from mem0 import Memory
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Any
from qdrant_client.models import Distance, VectorParams

config_path = os.getenv("MEM0_CONFIG_PATH", "/app/config/config.yaml")
with open(config_path) as f:
    config = yaml.safe_load(f)

db_url = os.getenv("DATABASE_URL")
if db_url:
    config["history_db_url"] = db_url

memory = Memory.from_config(config)

app = FastAPI(title="mem0 API Server")


class AddRequest(BaseModel):
    messages: List[dict]
    user_id: str = "default"
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[dict] = None


class SearchRequest(BaseModel):
    query: str
    user_id: str = "default"
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    limit: int = 10


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/memories")
def add_memories(req: AddRequest):
    return memory.add(
        req.messages,
        user_id=req.user_id,
        agent_id=req.agent_id,
        run_id=req.run_id,
        metadata=req.metadata,
    )


@app.get("/v1/memories")
def get_memories(
    user_id: str = "default",
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
):
    return memory.get_all(user_id=user_id, agent_id=agent_id, run_id=run_id)


@app.post("/v1/memories/search")
def search_memories(req: SearchRequest):
    return memory.search(
        req.query,
        user_id=req.user_id,
        agent_id=req.agent_id,
        run_id=req.run_id,
        limit=req.limit,
    )


@app.delete("/v1/memories/{memory_id}")
def delete_memory(memory_id: str):
    memory.delete(memory_id)
    return {"message": "Memory deleted", "id": memory_id}


@app.delete("/v1/memories")
def delete_all_memories(user_id: str = "default"):
    memory.delete_all(user_id=user_id)
    return {"message": "All memories deleted for user", "user_id": user_id}
