from .base import LLMAdapter
from typing import Dict, Any
import aiohttp
import time
import os


class OllamaAdapter(LLMAdapter):
    def __init__(self, url: str = "http://localhost:11434"):
        self.url = url.rstrip("/")

    async def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Call a local Ollama HTTP endpoint. Returns dict {text, tokens, latency}.

        This implementation attempts a POST to `<url>/api/generate` with JSON `{prompt: ...}`.
        If your Ollama exposes a different route, update `self.url` accordingly.
        """
        start = time.time()
        # include model in payload only when a non-empty model name is provided
        model = kwargs.get("model") if kwargs is not None else None
        if isinstance(model, str) and model.startswith("ollama:"):
            model = model.split(":", 1)[1]
        payload = {"prompt": prompt}
        if model is not None and isinstance(model, str) and model.strip() != "":
            payload["model"] = model.strip()
        payload["stream"] = False
        try:
            # Build optional headers for attribution/privacy signals
            headers = {}
            attr = os.getenv("CLAUDE_CODE_ATTRIBUTION_HEADER") or os.getenv("CODE_ATTRIBUTION_HEADER")
            if attr:
                headers["X-Code-Attribution"] = attr
            nonessential = os.getenv("OLLAMA_NONESSENTIAL_TRAFFIC", "false").lower()
            if nonessential in ("1", "true", "yes"):
                headers["X-Nonessential-Traffic"] = "true"

            async with aiohttp.ClientSession(headers=headers or None) as session:
                async with session.post(f"{self.url}/api/generate", json=payload, timeout=30) as resp:
                        try:
                            data = await resp.json()
                        except Exception:
                            data = {"raw": await resp.text()}

                # Normalize common error shapes from Ollama
                if isinstance(data, dict):
                    # explicit error fields
                    for k in ("error", "message", "detail", "error_message"):
                        if k in data and data.get(k):
                            msg = str(data.get(k))
                            # sanitize common Ollama message that reports empty model names
                            msg = msg.replace("model ''", "model not found")
                            text = f"ollama error: {msg}"
                            break
                    else:
                        # prefer explicit 'text' or 'result' fields
                        text = data.get("text") or data.get("result") or data.get("raw") or str(data)
                        if isinstance(text, str):
                            text = text.replace("model ''", "model not found")
                else:
                    text = str(data).replace("model ''", "model not found")
            # Attempt to extract token usage if Ollama provides it; otherwise estimate
            tokens = None
            cost = 0.0
            if isinstance(data, dict):
                # common fields that might contain token counts
                if data.get("usage") and isinstance(data.get("usage"), dict):
                    tokens = data["usage"].get("total_tokens") or data["usage"].get("tokens")
                # some endpoints may include a 'tokens' field
                if tokens is None:
                    tokens = data.get("tokens")

            if tokens is None:
                # crude estimate: words ~= tokens
                tokens = max(1, len(str(text).split()))

            # Record adapter usage if budget tracker is available
            try:
                from ..costs import BUDGET
                BUDGET.add_adapter_usage("ollama", tokens=int(tokens), cost=float(cost))
            except Exception:
                pass
            return {"text": text, "tokens": int(tokens), "cost": float(cost), "latency": time.time() - start}
        except Exception as e:
            return {"text": f"ollama error: {e}", "tokens": 0, "cost": 0.0, "latency": time.time() - start}
