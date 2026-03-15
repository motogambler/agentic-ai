from fastapi import APIRouter, HTTPException, Depends
from typing import List
import os
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from .. import crud, schemas
import asyncio
import httpx

from ..agent import queue as agent_queue

router = APIRouter()


def _extract_model_ids(payload) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        out = []
        for item in payload:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name") or item.get("model")
                if model_id:
                    out.append(model_id)
        return out
    if isinstance(payload, dict):
        if isinstance(payload.get("models"), list):
            return _extract_model_ids(payload.get("models"))
        if isinstance(payload.get("data"), list):
            return _extract_model_ids(payload.get("data"))
        if isinstance(payload.get("result"), list):
            return _extract_model_ids(payload.get("result"))
    return []


def _parse_frontmatter(text: str) -> dict:
    """Very small frontmatter parser for YAML-like key: value pairs.

    This intentionally does not require external deps and supports simple
    values (strings, numbers, booleans).
    """
    out = {}
    lines = text.splitlines()
    if not lines:
        return out
    if lines[0].strip() != "---":
        return out
    # find closing ---
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return out
    for line in lines[1:end]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        # simple type inference
        if v.lower() in ("true", "false"):
            val = v.lower() == "true"
        else:
            try:
                if "." in v:
                    val = float(v)
                else:
                    val = int(v)
            except Exception:
                # strip surrounding quotes if present
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    val = v[1:-1]
                else:
                    val = v
        out[k] = val
    return out


@router.get("/agents")
async def list_agent_descriptions() -> List[dict]:
    base = os.path.join(os.getcwd(), "agents")
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(base, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
            fm = _parse_frontmatter(txt)
            # also include first paragraph or title as summary
            body = txt.split("---")[-1].strip() if "---" in txt else txt
            summary = None
            for line in body.splitlines():
                if line.strip():
                    summary = line.strip()
                    break
            out.append({"file": name, "frontmatter": fm, "summary": summary})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return out


@router.post("/import")
async def import_agents(db: AsyncSession = Depends(get_db)):
    """Import agent markdown files from ./agents into the DB as Agent rows.

    For each `agents/*.md`, parse frontmatter and create an Agent with
    `name` (frontmatter `name` or filename) and `config` containing the
    frontmatter mapping. Skips agents that already exist.
    """
    base = os.path.join(os.getcwd(), "agents")
    if not os.path.isdir(base):
        return {"created": [], "skipped": [], "errors": ["agents directory not found"]}

    created = []
    skipped = []
    errors = []

    # existing agent names
    try:
        existing = await crud.get_agents(db)
        existing_names = {a.name for a in existing}
    except Exception:
        existing_names = set()

    # walk directories recursively so team subfolders are included
    for root, _, files in os.walk(base):
        for name in sorted(files):
            if not name.endswith('.md'):
                continue
            path = os.path.join(root, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                txt = f.read()
            fm = _parse_frontmatter(txt) or {}
            # prefer explicit frontmatter `name`; otherwise use the file's
            # path relative to the agents base so names are unique across
            # subfolders (e.g. "engineer_team/engineer-frontend").
            rel = os.path.relpath(path, base)
            rel_no_ext = os.path.splitext(rel)[0]
            agent_name = fm.get('name') or rel_no_ext.replace(os.sep, '/')
            if agent_name in existing_names:
                skipped.append(agent_name)
                continue
            payload = schemas.AgentCreate(name=agent_name, config=fm)
            try:
                obj = await crud.create_agent(db, payload)
                created.append(agent_name)
                existing_names.add(agent_name)
            except Exception as e:
                errors.append({"file": name, "error": str(e)})
        except Exception as e:
            errors.append({"file": name, "error": str(e)})

    return {"created": created, "skipped": skipped, "errors": errors}


@router.get('/queue')
async def inspect_queue():
    """Debug endpoint: list current queue entries from Redis or in-memory queue."""
    try:
        redis = await agent_queue._get_redis()
    except Exception:
        redis = None

    out = {"backend": None, "queue_name": getattr(agent_queue, '_queue_name', 'agent_queue'), "items": []}
    if redis is not None:
        try:
            raw = await redis.lrange(out['queue_name'], 0, -1)
            items = []
            for v in raw:
                try:
                    s = v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
                    import json

                    items.append(json.loads(s))
                except Exception:
                    items.append(s)
            out['backend'] = 'redis'
            out['items'] = items
            return out
        except Exception as e:
            out['error'] = str(e)

    # Redis not available: try to inspect in-memory queue attached to event loop
    loop = asyncio.get_event_loop()
    q = getattr(loop, '_agent_queue', None)
    # also check adapter-local queue if present
    try:
        adapter = agent_queue.get_queue()
        if getattr(adapter, '_local_q', None) is not None:
            q = getattr(adapter, '_local_q')
    except Exception:
        pass

    if q is None:
        out['backend'] = 'none'
        out['items'] = []
        return out

    # inspect private deque for debug purposes
    try:
        internal = getattr(q, '_queue', None)
        if internal is not None:
            entries = list(internal)
            out['backend'] = 'in-memory'
            out['items'] = [getattr(e, '__dict__', str(e)) for e in entries]
            return out
    except Exception as e:
        out['error'] = str(e)

    out['backend'] = 'in-memory'
    out['items'] = []
    return out


@router.get('/litellm/models')
async def list_litellm_models():
    """Return available Litellm models if litellm is installed and exposes them.

    This is best-effort: different litellm versions expose different APIs.
    """
    # First, try probing a local litellm wrapper service (dockerized) if available.
    import httpx
    litellm_url = os.getenv('LITELLM_URL', None)
    candidates = []
    if litellm_url:
        candidates.append(litellm_url.rstrip('/'))
    candidates.extend([
        'http://localhost:11435',
        'http://127.0.0.1:11435',
        'http://host.docker.internal:11435',
    ])
    for base in candidates:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                for p in ['/models', '/api/models', '/ollama/models', '/health']:
                    try:
                        resp = await client.get(base + p)
                        if resp.status_code == 200:
                            try:
                                data = resp.json()
                                if isinstance(data, dict) and 'models' in data:
                                    models = _extract_model_ids(data.get('models'))
                                    if models:
                                        return {"available": True, "models": models, "source": data.get("source") or "wrapper", "base": base, "path": p}
                                # or may return raw list
                                if isinstance(data, list):
                                    models = _extract_model_ids(data)
                                    if models:
                                        return {"available": True, "models": models, "source": "wrapper", "base": base, "path": p}
                            except Exception:
                                # non-json; ignore
                                pass
                    except Exception:
                        continue
        except Exception:
            continue

    try:
        import asyncio
        import inspect
        import litellm
    except Exception as e:
        return {"available": False, "reason": f"litellm import failed: {e}", "models": []}

    models = []
    # common attributes
    if hasattr(litellm, 'models') and isinstance(litellm.models, (list, dict)):
        try:
            if isinstance(litellm.models, dict):
                models = list(litellm.models.keys())
            else:
                models = list(litellm.models)
            return {"available": True, "models": models}
        except Exception:
            pass

    if hasattr(litellm, 'available_models'):
        try:
            am = litellm.available_models
            models = list(am) if isinstance(am, (list, tuple)) else am
            return {"available": True, "models": list(models)}
        except Exception:
            pass

    # try client-based listing in a thread
    try:
        if hasattr(litellm, 'Client'):
            def _sync():
                try:
                    client = litellm.Client()
                    if hasattr(client, 'models') and callable(client.models):
                        return client.models()
                    if hasattr(client, 'list_models') and callable(client.list_models):
                        return client.list_models()
                    # fallback: inspect attributes
                    return []
                except Exception:
                    return []

            out = await asyncio.to_thread(_sync)
            try:
                models = list(out) if out is not None else []
            except Exception:
                models = []
            return {"available": True, "models": models}
    except Exception:
        pass

    # Final fallback: use Ollama-discovered models and expose them with the same prefix
    env_url = os.getenv('OLLAMA_URL', None)
    ollama_candidates = []
    if env_url:
        ollama_candidates.append(env_url.rstrip('/'))
    ollama_candidates.extend([
        'http://localhost:11434',
        'http://127.0.0.1:11434',
        'http://host.docker.internal:11434',
    ])
    for base in ollama_candidates:
        for p in ['/api/models', '/models', '/api/list_models', '/v1/models']:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(base + p)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = _extract_model_ids(data)
                        if models:
                            return {"available": True, "models": [f"ollama:{m}" for m in models], "source": "ollama-fallback", "base": base, "path": p}
            except Exception:
                continue

    return {"available": True, "models": [], "note": "litellm installed but no model list exposed"}



@router.get('/ollama_models')
async def proxy_ollama_models():
    """Proxy to a local Ollama instance to list models. Uses OLLAMA_URL env var or defaults to http://localhost:11434"""
    # try a list of candidate base URLs so this works whether Ollama is on the host
    # or accessible via Docker host forwarding. Env var overrides.
    env_url = os.getenv('OLLAMA_URL', None)
    candidates = []
    if env_url:
        candidates.append(env_url.rstrip('/'))
    candidates.extend([
        'http://localhost:11434',
        'http://127.0.0.1:11434',
        'http://host.docker.internal:11434',
    ])
    paths = ['/api/models', '/models', '/api/list_models', '/v1/models']
    tried = []
    for base in candidates:
        for p in paths:
            url = base + p
            tried.append(url)
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                        except Exception:
                            data = resp.text
                        return {"available": True, "models": data, "base": base, "path": p}
            except Exception:
                continue
    return {"available": False, "error": f"checked: {tried}"}
