from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
import os
import json
import httpx
import traceback

app = FastAPI(title="litellm-wrapper")

try:
    import litellm
except Exception:
    litellm = None


class GenRequest(BaseModel):
    prompt: str
    model: str | None = None


def _request_timeout_seconds() -> float:
    try:
        return float(os.getenv("OLLAMA_REQUEST_TIMEOUT", os.getenv("LLM_REQUEST_TIMEOUT", "120")))
    except Exception:
        return 120.0


def _candidate_ollama_bases():
    env_url = os.getenv('OLLAMA_URL', None)
    bases = []
    if env_url:
        bases.append(env_url.rstrip('/'))
    for base in [
        'http://host.docker.internal:11434',
        'http://localhost:11434',
        'http://127.0.0.1:11434',
    ]:
        if base not in bases:
            bases.append(base)
    return bases


def _extract_model_ids(payload):
    if payload is None:
        return []
    if isinstance(payload, list):
        out = []
        for item in payload:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                mid = item.get('id') or item.get('name') or item.get('model')
                if mid:
                    out.append(mid)
        return out
    if isinstance(payload, dict):
        if isinstance(payload.get('models'), list):
            return _extract_model_ids(payload.get('models'))
        if isinstance(payload.get('data'), list):
            return _extract_model_ids(payload.get('data'))
        if isinstance(payload.get('result'), list):
            return _extract_model_ids(payload.get('result'))
    return []


def _fetch_ollama_models_sync():
    paths = ["/api/models", "/models", "/api/list_models", "/v1/models"]
    tried = []
    timeout = min(_request_timeout_seconds(), 10.0)
    for base in _candidate_ollama_bases():
        for p in paths:
            url = base + p
            tried.append(url)
            try:
                resp = httpx.get(url, timeout=timeout)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        data = None
                    model_ids = _extract_model_ids(data)
                    if model_ids:
                        return {"available": True, "models": sorted(set(model_ids)), "base": base, "path": p}
            except Exception:
                continue
    return {"available": False, "models": [], "error": f"checked: {tried}"}


@app.get("/health")
async def health():
    return {"status": "ok", "litellm_installed": litellm is not None}


@app.get("/models")
async def list_models():
    if not litellm:
        ollama = _fetch_ollama_models_sync()
        if ollama.get("available") and ollama.get("models"):
            return {"available": True, "models": [f"ollama:{m}" for m in ollama["models"]], "source": "ollama", "base": ollama.get("base"), "path": ollama.get("path")}
        return {"available": False, "reason": "litellm not installed", "models": []}
    try:
        # Try several possible litellm APIs to list available models.
        # Different litellm versions expose different call signatures.
        def _try_client_list():
            try:
                client = litellm.Client()
            except Exception:
                return None
            # try common names
            for attr in ("list_models", "models", "available_models", "availableModels"):
                try:
                    fn = getattr(client, attr, None)
                    if callable(fn):
                        out = fn()
                        return out
                    if fn is not None:
                        return fn
                except Exception:
                    continue
            return None

        # 1) top-level litellm.models (list/dict/callable)
        try:
            lm = getattr(litellm, 'models', None)
            if lm is not None:
                if callable(lm):
                    out = lm()
                    return {"available": True, "models": list(out) if out is not None else []}
                if isinstance(lm, dict):
                    return {"available": True, "models": list(lm.keys())}
                if isinstance(lm, (list, tuple, set)):
                    return {"available": True, "models": list(lm)}
        except Exception:
            pass

        # 2) top-level litellm.available_models
        try:
            am = getattr(litellm, 'available_models', None)
            if am is not None:
                if callable(am):
                    out = am()
                    return {"available": True, "models": list(out) if out is not None else []}
                if isinstance(am, (list, tuple, set)):
                    return {"available": True, "models": list(am)}
        except Exception:
            pass

        # 3) client-based APIs
        try:
            out = _try_client_list()
            if out is not None:
                if isinstance(out, dict):
                    # maybe mapping id -> meta
                    return {"available": True, "models": list(out.keys())}
                if isinstance(out, (list, tuple, set)):
                    return {"available": True, "models": list(out)}
        except Exception:
            pass

        # 4) fallback to Ollama models so LiteLLM wrapper can still surface local models
        ollama = _fetch_ollama_models_sync()
        if ollama.get("available") and ollama.get("models"):
            return {"available": True, "models": [f"ollama:{m}" for m in ollama["models"]], "source": "ollama", "base": ollama.get("base"), "path": ollama.get("path")}
        return {"available": True, "models": []}
    except Exception as e:
        ollama = _fetch_ollama_models_sync()
        if ollama.get("available") and ollama.get("models"):
            return {"available": True, "models": [f"ollama:{m}" for m in ollama["models"]], "source": "ollama", "base": ollama.get("base"), "path": ollama.get("path"), "litellm_error": str(e)}
        return {"available": True, "models": [], "error": str(e)}



@app.get('/ollama/models')
async def ollama_models():
    """Proxy to Ollama's model list. Uses OLLAMA_URL env var or host.docker.internal."""
    # try a list of candidate base URLs so wrapper works from different Docker/host setups
    candidates = _candidate_ollama_bases()
    paths = ["/api/models", "/models", "/api/list_models", "/v1/models"]
    tried = []
    for base in candidates:
        for p in paths:
            url = base + p
            tried.append(url)
            try:
                resp = httpx.get(url, timeout=min(_request_timeout_seconds(), 10.0))
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        data = resp.text
                    return {"available": True, "models": _extract_model_ids(data), "raw": data, "base": base, "path": p}
            except Exception:
                continue
    return {"available": False, "error": f"checked: {tried}"}


@app.post("/api/generate")
async def generate(req: GenRequest):
    if not litellm:
        raise HTTPException(status_code=500, detail="litellm not installed in container")
    try:
        # If the requested model is an Ollama-backed model, proxy to Ollama HTTP API.
        model_name = None
        if req.model and isinstance(req.model, str) and req.model.startswith('ollama:'):
            model_name = req.model.split(':', 1)[1]
        elif req.model and isinstance(req.model, str):
            ollama = _fetch_ollama_models_sync()
            known = set(ollama.get('models') or [])
            if req.model in known:
                model_name = req.model

        if model_name:
            payload = {"prompt": req.prompt, "stream": False}
            if model_name:
                payload['model'] = model_name
            bases = _candidate_ollama_bases()
            # include paths that embed the model id (some Ollama deployments expose model-specific generate endpoints)
            gen_paths = ["/api/generate", "/generate", "/api/completions", "/api/chat/completions", "/v1/generate"]
            # add model-specific candidate paths
            gen_paths.extend([
                f"/v1/models/{model_name}/generate",
                f"/v1/models/{model_name}/predict",
                f"/v1/models/{model_name}/completions",
            ])
            errors = []
            with httpx.Client(timeout=_request_timeout_seconds()) as client:
                for base in bases:
                    for p in gen_paths:
                        url = base + p
                        try:
                            r = client.post(url, json=payload)
                            if r.status_code == 200:
                                try:
                                    data = r.json()
                                    if isinstance(data, dict):
                                        text = data.get('response') or data.get('text') or data.get('output') or data.get('content') or data
                                    else:
                                        text = data
                                    return {"text": text, "base": base, "path": p, "provider": "ollama"}
                                except Exception:
                                    return {"text": r.text, "base": base, "path": p, "provider": "ollama"}
                            else:
                                errors.append((base + p, r.status_code, r.text))
                        except Exception as e:
                            errors.append((base + p, str(e)))
            raise HTTPException(status_code=500, detail=f"ollama proxy error, tried: {errors}")

        def _sync():
            # try common call patterns
            if hasattr(litellm, "complete"):
                return litellm.complete(req.prompt, model=req.model) if req.model else litellm.complete(req.prompt)
            if hasattr(litellm, "Client"):
                client = litellm.Client()
                if hasattr(client, "complete"):
                    return client.complete(req.prompt, model=req.model) if req.model else client.complete(req.prompt)
                if hasattr(client, "generate"):
                    return client.generate(req.prompt, model=req.model) if req.model else client.generate(req.prompt)
            return {"error": "no known call signature for litellm in this package"}

        result = await asyncio.to_thread(_sync)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/debug')
async def debug_litellm():
    """Debug endpoint to introspect the installed litellm package and Client.

    Returns top-level attributes, whether litellm is present, and attempts to
    instantiate a client and call common model-listing methods capturing
    exceptions so we can see why /models may be empty.
    """
    out = {"litellm_installed": litellm is not None, "top_level": [], "client_info": {}, "attempts": {}}
    try:
        if litellm is None:
            return out
        # top-level attrs (filter long/private)
        attrs = [a for a in dir(litellm) if not a.startswith('__')]
        out['top_level'] = sorted(attrs)
        # try top-level models/available_models
        for name in ('models', 'available_models', 'list_models'):
            try:
                val = getattr(litellm, name, None)
                if callable(val):
                    try:
                        res = val()
                        out['attempts'][name] = {"callable": True, "result_type": type(res).__name__}
                    except Exception as e:
                        out['attempts'][name] = {"callable": True, "error": traceback.format_exc()}
                else:
                    out['attempts'][name] = {"callable": False, "value_type": type(val).__name__}
            except Exception:
                out['attempts'][name] = {"error": traceback.format_exc()}

        # try client
        client_info = {}
        if hasattr(litellm, 'Client'):
            try:
                Client = litellm.Client
                client_info['client_type'] = repr(Client)
                try:
                    client = Client()
                    client_info['instantiated'] = True
                    # list first-level callables on client
                    cattrs = [a for a in dir(client) if not a.startswith('__')]
                    client_info['attrs'] = sorted(cattrs)
                    # attempt common methods
                    for m in ('list_models','models','available_models','listModels','generate','complete'):
                        if hasattr(client, m):
                            try:
                                fn = getattr(client, m)
                                if callable(fn):
                                    try:
                                        res = fn()
                                        client_info[f'{m}_result_type'] = type(res).__name__
                                    except Exception:
                                        client_info[f'{m}_error'] = traceback.format_exc()
                                else:
                                    client_info[f'{m}_value_type'] = type(fn).__name__
                            except Exception:
                                client_info[f'{m}_error'] = traceback.format_exc()
                except Exception:
                    client_info['instantiated'] = False
                    client_info['inst_error'] = traceback.format_exc()
            except Exception:
                client_info['client_error'] = traceback.format_exc()
        out['client_info'] = client_info
    except Exception:
        out['error'] = traceback.format_exc()
    return out
