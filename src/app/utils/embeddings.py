import os
import asyncio
from typing import List
import json
import time
from collections import OrderedDict

_redis = None

# In-process LRU cache to reduce Redis round-trips for hot texts
# Entries are (timestamp_seconds, vector)
_local_cache = OrderedDict()
_local_cache_lock = asyncio.Lock()
_local_cache_max = int(os.getenv("EMBEDDING_LRU_SIZE", "1024"))
# TTL for both Redis and local cache (seconds)
_cache_ttl = int(os.getenv("EMBEDDING_CACHE_TTL", str(60 * 60)))  # default 1 hour

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
    # 1) Try local in-process LRU cache
    now_ts = time.time()
    async with _local_cache_lock:
        entry = _local_cache.get(text)
        if entry is not None:
            ts, vec = entry
            if now_ts - ts < _cache_ttl:
                # move to end as recently used
                _local_cache.move_to_end(text)
                return vec
            else:
                # expired
                try:
                    del _local_cache[text]
                except Exception:
                    pass

    # 2) Try Redis cache next
    redis = await _get_redis()
    key = "embed:" + (text if len(text) < 1000 else text[:1000])
    if redis is not None:
        try:
            v = await redis.get(key)
            if v:
                vec = json.loads(v)
                # populate local cache
                async with _local_cache_lock:
                    _local_cache[text] = (now_ts, vec)
                    while len(_local_cache) > _local_cache_max:
                        _local_cache.popitem(last=False)
                return vec
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
                    await redis.set(key, json.dumps(vec), ex=_cache_ttl)
                except Exception:
                    pass
            # populate local cache
            async with _local_cache_lock:
                _local_cache[text] = (time.time(), vec)
                while len(_local_cache) > _local_cache_max:
                    _local_cache.popitem(last=False)
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
                await redis.set(key, json.dumps(vec), ex=_cache_ttl)
            except Exception:
                pass
        # populate local cache
        async with _local_cache_lock:
            _local_cache[text] = (time.time(), vec)
            while len(_local_cache) > _local_cache_max:
                _local_cache.popitem(last=False)
        return vec
    except Exception as e:
        raise RuntimeError("no embedding provider available (install openai or litellm and set OPENAI_API_KEY)") from e
