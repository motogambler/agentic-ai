import os
import asyncio
from typing import List
import json

_redis = None

async def _get_redis():
    global _redis
    if _redis is None:
        try:
            import aioredis
            _redis = await aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        except Exception:
            _redis = None
    return _redis


async def compute_embedding(text: str) -> List[float]:
    """Best-effort embedding: try OpenAI, then litellm. Returns a list of floats.

    Raises RuntimeError if no supported embedding provider is available.
    """
    # Try cache first
    redis = await _get_redis()
    if redis is not None:
        key = "embed:" + (text if len(text) < 1000 else text[:1000])
        try:
            v = await redis.get(key)
            if v:
                return json.loads(v)
        except Exception:
            pass

    # Try OpenAI first if API key present and package available
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            import openai

            openai.api_key = openai_key

            def _sync():
                # model choice left generic; user may change to preferred embedding model
                resp = openai.Embedding.create(input=text, model="text-embedding-3-small")
                return resp

            resp = await asyncio.to_thread(_sync)
            vec = resp["data"][0]["embedding"]
            if redis is not None:
                try:
                    await redis.set(key, json.dumps(vec), ex=60 * 60 * 24)
                except Exception:
                    pass
            return vec
        except Exception:
            # fall through to litellm
            pass

    # Try litellm bindings if available
    try:
        import litellm

        def _sync_litellm():
            # Best-effort: many litellm versions expose `embed` or `Embeddings`
            if hasattr(litellm, "embed"):
                return litellm.embed([text])[0]
            if hasattr(litellm, "Embeddings"):
                emb = litellm.Embeddings()
                if hasattr(emb, "embed"):
                    return emb.embed(text)
                if hasattr(emb, "embed_batch"):
                    return emb.embed_batch([text])[0]
            # Fallback: try Client pattern
            if hasattr(litellm, "Client"):
                client = litellm.Client()
                if hasattr(client, "embed"):
                    return client.embed(text)
            raise RuntimeError("litellm present but no recognized embeddings API")

        vec = await asyncio.to_thread(_sync_litellm)
        vec = list(vec)
        if redis is not None:
            try:
                await redis.set(key, json.dumps(vec), ex=60 * 60 * 24)
            except Exception:
                pass
        return vec
    except Exception as e:
        raise RuntimeError("no embedding provider available (install openai or litellm and set OPENAI_API_KEY)") from e
