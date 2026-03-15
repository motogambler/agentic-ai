import asyncio
from src.app.agent.queue import QueueAdapter
from src.app.agent.executor import AgentTask


def test_queue_adapter_local():
    async def _run():
        q = QueueAdapter()
        task = AgentTask(agent_id=123, goal="test-queue", context=None)
        await q.put(task)
        size = await q.qsize()
        assert size == 1
        got = await q.get()
        assert (hasattr(got, "agent_id") and got.agent_id == 123) or (isinstance(got, dict) and got.get("agent_id") == 123)
        size2 = await q.qsize()
        assert size2 == 0

    asyncio.run(_run())
