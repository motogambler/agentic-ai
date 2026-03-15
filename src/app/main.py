from fastapi import FastAPI
from .routers import agents
from .routers import memories
from .routers import embeddings
from .routers import metrics
from .routers import admin
from .routers import ui
from .routers import events
from .config import settings
from .db import init_db
from .agent.queue import get_queue
from .agent.executor import AgentExecutor, AgentTask
from .db import AsyncSessionLocal
import asyncio
import logging
from .costs import get_budget_snapshot
from . import crud

app = FastAPI(title="Agentic AI")

app.include_router(agents.router, prefix="/agents")
app.include_router(memories.router, prefix="/agents")
app.include_router(embeddings.router)
app.include_router(metrics.router, prefix="/metrics")
app.include_router(admin.router, prefix="/admin")
app.include_router(ui.router, prefix="/ui")
app.include_router(events.router, prefix="/events")


@app.on_event("startup")
async def on_startup():
    # Initialize DB tables (simple; use alembic for migrations)
    await init_db()
    # Log whether an OpenAI key is configured (masked) so operators can verify .env loading
    try:
        from .config import settings as _settings
        _key = getattr(_settings, 'openai_api_key', None)
        if _key:
            masked = _key[:4] + '...' + _key[-4:]
            logging.getLogger('uvicorn').info(f'OpenAI API key loaded (masked): {masked}')
        else:
            logging.getLogger('uvicorn').info('No OpenAI API key configured in settings')
    except Exception:
        pass
    # Start background worker for agent tasks
    try:
        executor = AgentExecutor(AsyncSessionLocal)
        queue = get_queue()
        loop = asyncio.get_event_loop()
        loop.create_task(executor.worker_loop(queue))
        logging.getLogger("agent.executor").info("Agent worker started")
        # Start background metrics persister
        async def _metrics_persister():
            while True:
                try:
                    snap = get_budget_snapshot()
                    tokens = snap.get("tokens", 0)
                    cost = snap.get("cost", 0.0)
                    adapters = snap.get("adapters", None)
                    async with AsyncSessionLocal() as db:
                        await crud.add_metrics_snapshot(db, tokens=tokens, cost=cost, adapters=adapters)
                except Exception:
                    logging.exception("metrics persister error")
                await asyncio.sleep(10)

        app.state.metrics_task = loop.create_task(_metrics_persister())
    except Exception:
        logging.exception("Failed to start agent worker")


@app.on_event("shutdown")
async def on_shutdown():
    # cancel metrics persister if running
    try:
        t = getattr(app.state, "metrics_task", None)
        if t:
            t.cancel()
            await t
    except Exception:
        pass


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8000, reload=True)
