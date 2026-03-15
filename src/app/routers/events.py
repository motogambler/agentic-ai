from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from .. import crud
from ..agent.queue import enqueue
from typing import List

router = APIRouter()


@router.post("/", summary="Create an event")
async def create_event(payload: dict, db: AsyncSession = Depends(get_db)):
    agent_id = payload.get("agent_id")
    event_type = payload.get("event_type")
    data = payload.get("payload")
    if not event_type:
        raise HTTPException(status_code=400, detail="event_type required")
    obj = await crud.add_event(db, agent_id=agent_id, event_type=event_type, payload=data)
    return obj


@router.get("/", summary="List events")
async def list_events(agent_id: int | None = None, limit: int = 100, db: AsyncSession = Depends(get_db)):
    events = await crud.get_events(db, agent_id=agent_id, limit=limit)
    return events


@router.post("/{event_id}/replay", summary="Replay an event (re-enqueue)")
async def replay_event(event_id: int, db: AsyncSession = Depends(get_db)):
    events = await crud.get_events(db, limit=500)
    ev = next((e for e in events if e.id == event_id), None)
    if not ev:
        raise HTTPException(status_code=404, detail="event not found")
    # Re-enqueue the event payload for processing by the agent executor
    task = {"agent_id": ev.agent_id, "goal": f"replay:{ev.event_type}", "context": {"event": ev.payload}}
    await enqueue(task)
    return {"status": "enqueued", "event_id": event_id}
