import sys
import types
import pytest

from src.app.adapters.ollama_adapter import OllamaAdapter
from src.app.adapters.litellm_adapter import LiteLLMAdapter


class DummyResp:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data

    async def text(self):
        return str(self._data)


class FakeClientSession:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, *a, **kw):
        class CM:
            def __init__(self, resp):
                self._resp = resp

            async def __aenter__(self):
                return self._resp

            async def __aexit__(self, *a):
                return False

        return CM(self._resp)


def test_ollama_error_normalization(monkeypatch):
    # simulate an Ollama response that contains an error field
    data = {"error": "model '' not found"}
    resp = DummyResp(data)
    monkeypatch.setattr("src.app.adapters.ollama_adapter.aiohttp.ClientSession", lambda: FakeClientSession(resp))

    adapter = OllamaAdapter(url="http://example")
    out = __import__("asyncio").run(adapter.generate("hello"))
    assert isinstance(out, dict)
    assert isinstance(out.get("text"), str)
    assert out["text"].lower().startswith("ollama error")


def test_litellm_error_normalization(monkeypatch):
    # Force wrapper HTTP calls to fail so this unit test covers the Python `litellm` bindings path
    # even if a local wrapper is running on the developer machine.
    class FailingAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise RuntimeError("disable wrapper for unit test")

    monkeypatch.setattr("src.app.adapters.litellm_adapter.httpx.AsyncClient", FailingAsyncClient)

    # create a fake litellm module with a Client.generate that returns an error dict
    fake = types.SimpleNamespace()

    class Client:
        def generate(self, prompt, **kwargs):
            return {"error": "no model available"}

    fake.Client = Client
    sys.modules["litellm"] = fake

    adapter = LiteLLMAdapter()
    out = __import__("asyncio").run(adapter.generate("hello"))
    assert isinstance(out, dict)
    assert isinstance(out.get("text"), str)
    assert out["text"].lower().startswith("litellm error")
