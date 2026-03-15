import asyncio


def test_executor_tool_context_persists_embedding(monkeypatch):
    # monkeypatch compute_embedding to return a fixed vector and crud.add_memory to capture calls
    calls = []

    async def fake_add_memory(db, agent_id, memory):
        calls.append((agent_id, memory.content, memory.embedding, memory.metadata))
        return {"id": 1}

    async def fake_compute_embedding(text):
        return [0.0] * 1536

    # patch the symbol imported into the executor module (where it's called)
    monkeypatch.setattr("src.app.agent.executor.add_memory", fake_add_memory)
    # patch the symbol imported into executor module
    monkeypatch.setattr("src.app.agent.executor.compute_embedding", fake_compute_embedding)

    # Dummy DB factory used by AgentExecutor
    class DummyDBCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def DummyDBFactory():
        return DummyDBCtx()

    from src.app.agent.executor import AgentExecutor, AgentTask

    executor = AgentExecutor(DummyDBFactory)

    task = AgentTask(agent_id=42, goal="do test", context={"tool_call": {"tool": "echo", "args": {"text": "hello"}}})

    asyncio.run(executor.run_task(task))

    assert len(calls) >= 1
    agent_id, content, embedding, metadata = calls[0]
    assert agent_id == 42
    assert "Tool" in content or "Tool" in str(content)
    assert isinstance(embedding, list) and len(embedding) == 1536
