from fastapi import APIRouter, Depends, HTTPException, Response
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from .. import crud, schemas
from ..agent.queue import enqueue, get_queue
import inspect
from ..agent.executor import AgentTask
import asyncio
import os

# optionally import the admin frontmatter parser to auto-load agent configs
try:
    from ..routers.admin import _parse_frontmatter
except Exception:
    _parse_frontmatter = None

router = APIRouter()

VALID_TOOLS = {"echo", "http_get", "calc", "run_cmd", "read_file", "repo_list", "repo_read", "repo_write", "repo_mkdir"}


@router.get("/", response_model=List[schemas.AgentRead])
async def list_agents(db: AsyncSession = Depends(get_db)):
    agents = await crud.get_agents(db)
    return agents


@router.post("/", response_model=schemas.AgentRead)
async def create_agent(payload: schemas.AgentCreate, db: AsyncSession = Depends(get_db)):
    # naive uniqueness check handled by DB unique constraint; return 400 on failure
    try:
        # If an agent markdown exists under ./agents/<name>.md, load its frontmatter into the agent `config`.
        if _parse_frontmatter:
            cfg_path = os.path.join(os.getcwd(), "agents", f"{payload.name}.md")
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        fm = _parse_frontmatter(f.read())
                    if fm:
                        payload.config = fm
                except Exception:
                    pass
        obj = await crud.create_agent(db, payload)
        return obj
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{agent_id}", status_code=204, summary="Delete an agent and its memories", tags=["agents"], responses={404: {"description": "Agent not found"}})
async def delete_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an agent and all associated memories.

    Returns HTTP 204 on success. If the agent does not exist, returns 404.
    """
    ok = await crud.delete_agent(db, agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="agent not found")
    return Response(status_code=204)


from sqlalchemy import select
from .. import models

@router.post("/{agent_id}/run")
async def run_agent(agent_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    """Enqueue a simple agent goal to be executed by the background worker.

    Expects JSON: {"goal": "do something"}
    """
    agent = await crud.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")

    goal = body.get("goal")
    if not goal:
        raise HTTPException(status_code=400, detail="goal is required")
    # If the request includes a tool_call, run it immediately and persist the result
    tool_call = body.get("tool_call")
    if tool_call:
        from ..tools import run_tool

        tool = tool_call.get("tool")
        if tool not in VALID_TOOLS:
            raise HTTPException(status_code=400, detail=f"unsupported tool: {tool}")
        args = tool_call.get("args", {})
        res = await run_tool(tool, args)

        # persist the tool result as a memory
        mem = type("_", (), {})()
        mem.content = f"Tool {tool} executed: {res}"
        mem.embedding = None
        mem.metadata = {"source": "executor", "tool": tool}
        try:
            obj = await crud.add_memory(db, agent_id, mem)
        except Exception:
            raise HTTPException(status_code=500, detail="failed to persist tool result")
        return {"status": "ok", "tool": tool, "result": res, "memory": obj}

    context = body.get("context") if isinstance(body, dict) else None
    # Merge agent `config` (persona, skills, etc.) into task context so the executor
    # receives the full agent configuration when running the task. Do not overwrite
    # any keys explicitly provided by the request body.
    try:
        if context is None or not isinstance(context, dict):
            context = {}
        if getattr(agent, 'config', None) and isinstance(agent.config, dict):
            for k, v in agent.config.items():
                if k not in context:
                    context[k] = v
    except Exception:
        # best-effort: if merging fails, continue with existing context
        context = context
    # accept optional model hint (e.g., from UI) and include it in the task context
    model = body.get("model") if isinstance(body, dict) else None
    if model:
        if context is None or not isinstance(context, dict):
            context = {}
        context["model"] = model
    task = AgentTask(agent_id=agent_id, goal=goal, context=context)
    q = get_queue()
    await q.put(task)
    return {"status": "enqueued", "agent_id": agent_id, "goal": goal}


@router.get("/{agent_id}/status")
async def agent_status(agent_id: int, db: AsyncSession = Depends(get_db)):
    agent = await crud.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")

    q = get_queue()
    queue_size = 0
    if hasattr(q, "qsize"):
        maybe = q.qsize()
        if inspect.isawaitable(maybe):
            queue_size = await maybe
        else:
            queue_size = maybe

    # recent memories
    stmt = select(models.Memory).where(models.Memory.agent_id == agent_id).order_by(models.Memory.created_at.desc()).limit(10)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    recent = []
    for mem in rows:
        recent.append({
            "id": mem.id,
            "content": mem.content,
            "metadata": getattr(mem, "meta", None),
            "created_at": mem.created_at.isoformat() if mem.created_at is not None else None,
        })

    return {"queue_size": queue_size, "recent_memories": recent}
