from .base import LLMAdapter
from typing import Dict, Any
import time
import asyncio
import os
import httpx


def _build_request_headers() -> dict | None:
    """Build optional headers for outgoing LLM wrapper requests from env vars.

    - CLAUDE_CODE_ATTRIBUTION_HEADER: sets X-Code-Attribution header (URL/contact)
    - OLLAMA_NONESSENTIAL_TRAFFIC: if truthy, sets X-Nonessential-Traffic: true
    """
    headers = {}
    attr = os.getenv("CLAUDE_CODE_ATTRIBUTION_HEADER") or os.getenv("CODE_ATTRIBUTION_HEADER")
    if attr:
        headers["X-Code-Attribution"] = attr
    nonessential = os.getenv("OLLAMA_NONESSENTIAL_TRAFFIC", "false").lower()
    if nonessential in ("1", "true", "yes"):
        headers["X-Nonessential-Traffic"] = "true"
    return headers if headers else None


def _wrapper_timeout_seconds(model: str | None = None) -> float:
    default_timeout = 120.0 if (isinstance(model, str) and model.startswith("ollama:")) else 60.0
    try:
        return float(os.getenv("LLM_REQUEST_TIMEOUT", str(default_timeout)))
    except Exception:
        return default_timeout


class LiteLLMAdapter(LLMAdapter):
    def __init__(self):
        # Load litellm.yaml config if present
        self.config = {}
        try:
            import os
            import yaml
            cfg_path = os.path.join(os.getcwd(), "litellm.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
        except Exception:
            # best-effort: if pyyaml not installed or file missing, ignore
            self.config = {}

    async def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Attempt to call `litellm` Python bindings if available.

        This adapter uses a best-effort approach: if `litellm` exposes a simple
        sync `complete` or `Client` API, it will call it inside a thread via
        `asyncio.to_thread`. If `litellm` isn't installed or the API differs,
        the adapter returns a useful placeholder message.
        """
        start = time.time()
        try:
            # Prefer a running LiteLLM wrapper service when available.
            model = kwargs.get("model")
            candidates = []
            env_url = os.getenv("LITELLM_URL")
            if env_url:
                candidates.append(env_url.rstrip('/'))
            candidates.extend([
                "http://localhost:11435",
                "http://127.0.0.1:11435",
                "http://host.docker.internal:11435",
            ])
            seen = set()
            for base in candidates:
                if base in seen:
                    continue
                seen.add(base)
                try:
                    headers = _build_request_headers()
                    async with httpx.AsyncClient(timeout=_wrapper_timeout_seconds(model), headers=headers) as client:
                        resp = await client.post(base + "/api/generate", json={"prompt": prompt, "model": model})
                        if resp.status_code == 200:
                            data = resp.json()
                            # If wrapper returned an error payload, skip this candidate so we can try Ollama directly
                            if isinstance(data, dict):
                                # top-level error fields
                                for k in ("error", "message", "detail", "error_message"):
                                    if k in data and data.get(k):
                                        # treat as non-useful response and try other candidates
                                        raise Exception("wrapper returned error")
                                # nested result may contain error details
                                nested = data.get("result")
                                if isinstance(nested, dict):
                                    for k in ("error", "message", "detail", "error_message"):
                                        if k in nested and nested.get(k):
                                            raise Exception("wrapper returned error in nested result")

                            text = data.get("text") or data.get("result") or data.get("response") or str(data)
                            tokens = max(1, len(str(text).split()))
                            return {"text": text, "tokens": int(tokens), "cost": 0.0, "latency": time.time() - start, "provider": "litellm-wrapper", "meta": data}
                except Exception:
                    continue

            # If the HTTP wrapper didn't provide a useful response, try a local Ollama HTTP adapter
            try:
                from .ollama_adapter import OllamaAdapter

                oll = OllamaAdapter()
                oll_resp = await oll.generate(prompt, model=model)
                # If Ollama returned non-error text, pass it through as the adapter result
                if isinstance(oll_resp, dict) and not str(oll_resp.get("text", "")).startswith("ollama error"):
                    return oll_resp
            except Exception:
                pass

            import litellm

            def _sync_call():
                # Build call kwargs from config and overrides
                call_kwargs = {}
                if isinstance(self.config, dict):
                    if "temperature" in self.config:
                        call_kwargs["temperature"] = self.config["temperature"]
                    if "max_tokens" in self.config:
                        call_kwargs["max_tokens"] = self.config["max_tokens"]
                # kwargs passed to generate override config
                for k in ("temperature", "max_tokens", "model"):
                    if k in kwargs:
                        call_kwargs[k] = kwargs[k]

                # Common possible APIs; adapt as needed for your installed version
                if hasattr(litellm, "complete"):
                    return litellm.complete(prompt, **call_kwargs)
                if hasattr(litellm, "Client"):
                    client = litellm.Client()
                    if hasattr(client, "complete"):
                        return client.complete(prompt, **call_kwargs)
                    # some versions may use `generate`
                    if hasattr(client, "generate"):
                        return client.generate(prompt, **call_kwargs)
                # Fallback to string representation
                return "litellm installed but no known call signature"

            result = await asyncio.to_thread(_sync_call)
            # Normalize result to string if needed and handle error shapes
            if isinstance(result, dict):
                # detect error-like fields
                for k in ("error", "message", "detail", "error_message"):
                    if k in result and result.get(k):
                        text = f"litellm error: {result.get(k)}"
                        break
                else:
                    text = result.get("text") or result.get("result") or str(result)
            else:
                text = result if isinstance(result, str) else str(result)
            # If we returned the generic fallback, treat it as an error so the
            # executor can try other adapters.
            if isinstance(text, str) and ("no known call signature" in text or text.startswith("litellm installed")):
                text = f"litellm error: {text}"
            # litellm may not provide token usage metadata; estimate tokens
            tokens = max(1, len(text.split()))
            cost = 0.0
            # Record adapter usage
            try:
                from ..costs import BUDGET
                BUDGET.add_adapter_usage("litellm", tokens=int(tokens), cost=float(cost))
            except Exception:
                pass
            return {"text": text, "tokens": int(tokens), "cost": float(cost), "latency": time.time() - start}
        except Exception as e:
            return {"text": f"litellm error or not installed: {e}", "tokens": 0, "cost": 0.0, "latency": time.time() - start}
