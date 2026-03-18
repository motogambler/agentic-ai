import os
import asyncio
import json
from typing import Optional

_redis = None
_queue_name = os.environ.get("AGENT_QUEUE_KEY", "agent_queue")

# ensure a module-level adapter reference exists
_adapter = None

async def _get_redis():
    global _redis
    if _redis is None:
        try:
            import aioredis
            _redis = await aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        except Exception:
            _redis = None
    return _redis


def get_queue():
    """Return a queue-like adapter with async `get()` and `put()` methods and async `qsize()`.

    This provides compatibility with existing code which awaits `queue.get()` and
    `await queue.put(item)`. `qsize()` is awaitable when Redis is used.
    """
    global _adapter
    if _adapter is None:
        # create a single shared adapter instance
        _adapter = QueueAdapter()
    return _adapter


class QueueAdapter:
    def __init__(self):
        # local in-memory queue used as a reliable fallback
        try:
            self._local_q = asyncio.Queue()
        except Exception:
            self._local_q = None

    async def put(self, item: dict):
        # prefer Redis when available, otherwise use the adapter-local queue
        redis = await _get_redis()
        # normalize item for JSON storage when using Redis
        if isinstance(item, dict):
            payload_obj = item
        else:
            try:
                from dataclasses import asdict

                payload_obj = asdict(item)
            except Exception:
                payload_obj = getattr(item, "__dict__", str(item))
        payload = json.dumps(payload_obj)
        if redis is not None:
            try:
                await redis.rpush(_queue_name, payload)
                return
            except Exception:
                pass
        if self._local_q is None:
            self._local_q = asyncio.Queue()
        await self._local_q.put(item)

    async def get(self):
        # prefer Redis when available; if Redis is present but empty, retry
        # BLPOP instead of falling back to the in-memory queue (which would
        # otherwise block indefinitely if it's empty).
        while True:
            redis = await _get_redis()
            if redis is not None:
                try:
                    # wait up to a few seconds for an item; if none, loop and retry
                    res = await redis.blpop(_queue_name, timeout=5)
                    if res:
                        payload = res[1]
                        try:
                            obj = json.loads(payload)
                        except Exception:
                            return payload
                        if isinstance(obj, dict):
                            try:
                                from .executor import AgentTask

                                return AgentTask(**obj)
                            except Exception:
                                return obj
                        return obj
                    # no result within timeout, retry BLPOP
                    continue
                except Exception:
                    # Redis appears to have failed; fall through to local queue fallback
                    pass

            # Redis not available or failed: use local in-memory queue as a fallback
            if self._local_q is None:
                self._local_q = asyncio.Queue()
            return await self._local_q.get()

    async def qsize(self):
        # If Redis is available, return list length; otherwise use in-memory queue size
        redis = await _get_redis()
        if redis is not None:
            try:
                return await redis.llen(_queue_name)
            except Exception:
                return 0
        # prefer our internal local queue if present
        if self._local_q is not None:
            return self._local_q.qsize()
        # otherwise try event-loop attached queue
        loop = asyncio.get_event_loop()
        q = getattr(loop, '_agent_queue', None)
        if q is None:
            return 0
        return q.qsize()


async def enqueue(task: dict):
    """Push task into Redis list (rpush) or in-memory queue if Redis unavailable."""
    redis = await _get_redis()
    payload = json.dumps(task)
    if redis is not None:
        try:
            await redis.rpush(_queue_name, payload)
            return
        except Exception:
            pass
    # fallback to in-memory queue
    loop = asyncio.get_event_loop()
    q = getattr(loop, '_agent_queue', None)
    if q is None:
        # attach a persistent in-memory queue to the event loop
        q = getattr(loop, '_agent_queue', None)
        if q is None:
            q = asyncio.Queue()
            setattr(loop, '_agent_queue', q)
    await q.put(task)


# Note: older code exposed a top-level `dequeue` helper; it was unused
# and is intentionally removed to reduce dead code. Use `get_queue()`
# and call `await queue.get()` on the returned adapter instead.
