from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from . import models, schemas
from sqlalchemy import delete as sa_delete

# Default embedding dimension used by pgvector column in models.Memory
EMBEDDING_DIM = 1536


async def get_agents(db: AsyncSession, limit: int = 100):
    result = await db.execute(select(models.Agent).limit(limit))
    return result.scalars().all()


async def create_agent(db: AsyncSession, agent_in: schemas.AgentCreate):
    obj = models.Agent(name=agent_in.name, config=agent_in.config)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def get_agent(db: AsyncSession, agent_id: int):
    from sqlalchemy import select

    result = await db.execute(select(models.Agent).where(models.Agent.id == agent_id))
    return result.scalars().first()


async def delete_agent(db: AsyncSession, agent_id: int) -> bool:
    agent = await get_agent(db, agent_id)
    if not agent:
        return False

    # Be explicit about cleanup so DB-level cascade settings don't matter.
    await db.execute(sa_delete(models.Memory).where(models.Memory.agent_id == agent_id))
    await db.execute(sa_delete(models.Agent).where(models.Agent.id == agent_id))
    await db.commit()
    return True


async def add_event(db: AsyncSession, agent_id: int | None, event_type: str, payload: dict | None = None):
    obj = models.Event(agent_id=agent_id, event_type=event_type, payload=payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def get_events(db: AsyncSession, agent_id: int | None = None, limit: int = 100):
    from sqlalchemy import select

    stmt = select(models.Event).order_by(models.Event.created_at.desc()).limit(limit)
    if agent_id is not None:
        stmt = select(models.Event).where(models.Event.agent_id == agent_id).order_by(models.Event.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def add_memory(db: AsyncSession, agent_id: int, memory_in: schemas.MemoryCreate):
    obj = models.Memory(
        agent_id=agent_id,
        content=memory_in.content,
        embedding=memory_in.embedding,
        meta=memory_in.metadata,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def search_memories(db: AsyncSession, agent_id: int, query_embedding: list[float], limit: int = 5):
    from sqlalchemy import bindparam

    # Use pgvector operator `<->` for nearest-neighbor distance ordering
    # Normalize/query vector length to EMBEDDING_DIM to avoid pgvector dimension errors
    if query_embedding is None:
        raise ValueError("query_embedding required")
    qlen = len(query_embedding)
    if qlen != EMBEDDING_DIM:
        if qlen < EMBEDDING_DIM:
            query_embedding = list(query_embedding) + [0.0] * (EMBEDDING_DIM - qlen)
        else:
            query_embedding = list(query_embedding)[:EMBEDDING_DIM]

    distance_expr = models.Memory.embedding.op("<->")(bindparam("qvec"))
    # Exclude memories without embeddings to avoid operator errors
    stmt = (
        select(models.Memory, distance_expr.label("distance"))
        .where(models.Memory.agent_id == agent_id)
        .where(models.Memory.embedding != None)
        .order_by(distance_expr)
        .limit(limit)
    )
    result = await db.execute(stmt, {"qvec": query_embedding})
    rows = result.all()
    # Each row is (Memory, distance)
    out = []
    for mem, dist in rows:
        out.append({
            "id": mem.id,
            "agent_id": mem.agent_id,
            "content": mem.content,
            "embedding": mem.embedding,
            "metadata": getattr(mem, "meta", None),
            "created_at": mem.created_at.isoformat() if mem.created_at is not None else None,
            "distance": float(dist) if dist is not None else None,
        })
    return out


async def add_metrics_snapshot(db: AsyncSession, tokens: int, cost: float, adapters: dict | None = None):
    obj = models.MetricsSnapshot(tokens=int(tokens or 0), cost=float(cost or 0.0), adapters=adapters)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def get_metrics_snapshots(db: AsyncSession, limit: int = 100):
    from sqlalchemy import select

    stmt = select(models.MetricsSnapshot).order_by(models.MetricsSnapshot.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return rows
