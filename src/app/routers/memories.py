from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..db import get_db
from .. import crud, schemas
from ..utils.embeddings import compute_embedding

router = APIRouter()


@router.post("/{agent_id}/memories", response_model=schemas.MemoryRead)
async def create_memory(agent_id: int, payload: schemas.MemoryCreate, db: AsyncSession = Depends(get_db)):
    agent = await crud.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    mem = await crud.add_memory(db, agent_id, payload)
    return mem


@router.post("/{agent_id}/memories/search")
async def search_memory(agent_id: int, query: dict, db: AsyncSession = Depends(get_db)) -> List[dict]:
    # Accept either an explicit embedding or a text query to compute the embedding
    embedding = query.get("embedding")
    text = query.get("text")
    limit = int(query.get("limit", 5))

    if not embedding and not text:
        raise HTTPException(status_code=400, detail="provide either `embedding` (list) or `text` (string)")

    if text and not embedding:
        try:
            embedding = await compute_embedding(text)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"embedding error: {e}")

    results = await crud.search_memories(db, agent_id, embedding, limit=limit)
    return results


@router.post("/{agent_id}/memories/ingest", response_model=schemas.MemoryRead)
async def ingest_memory(agent_id: int, payload: schemas.MemoryCreate, db: AsyncSession = Depends(get_db)):
    """Compute embedding for `payload.content` and store as a memory linked to `agent_id`.

    If `payload.embedding` is provided it will be used instead of computing.
    """
    agent = await crud.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")

    embedding = payload.embedding
    if not embedding:
        try:
            embedding = await compute_embedding(payload.content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"embedding error: {e}")

    mem_in = schemas.MemoryCreate(content=payload.content, embedding=embedding, metadata=payload.metadata)
    mem = await crud.add_memory(db, agent_id, mem_in)
    return mem
