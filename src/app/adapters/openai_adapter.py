from .base import LLMAdapter
from typing import Dict, Any
import asyncio
import time

try:
    import openai
except Exception:
    openai = None

class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        start = time.time()
        # If openai package is available and api_key provided, attempt a call
        if openai and self.api_key:
            try:
                openai.api_key = self.api_key

                def _call():
                    # Use Completion fallback if Chat API not configured
                    model = kwargs.get("model") or "gpt-4"
                    if hasattr(openai, "ChatCompletion"):
                        resp = openai.ChatCompletion.create(model=model, messages=[{"role": "user", "content": prompt}])
                        text = resp.choices[0].message.content if resp.choices else str(resp)
                        usage = getattr(resp, "usage", None) or (resp.get("usage") if isinstance(resp, dict) else None)
                        tokens = 0
                        cost = 0.0
                        if usage and isinstance(usage, dict):
                            tokens = usage.get("total_tokens") or usage.get("prompt_tokens") or 0
                        return {"text": text, "tokens": int(tokens), "cost": float(cost)}
                    else:
                        model = kwargs.get("model") or "text-davinci-003"
                        resp = openai.Completion.create(model=model, prompt=prompt, max_tokens=150)
                        text = resp.choices[0].text if resp.choices else str(resp)
                        usage = getattr(resp, "usage", None) or (resp.get("usage") if isinstance(resp, dict) else None)
                        tokens = 0
                        cost = 0.0
                        if usage and isinstance(usage, dict):
                            tokens = usage.get("total_tokens") or usage.get("prompt_tokens") or 0
                        return {"text": text, "tokens": int(tokens), "cost": float(cost)}

                result = await asyncio.to_thread(_call)
                result["latency"] = time.time() - start
                # Record adapter usage in global budget
                try:
                    from ..costs import BUDGET
                    BUDGET.add_adapter_usage("openai", tokens=int(result.get("tokens", 0) or 0), cost=float(result.get("cost", 0.0) or 0.0))
                except Exception:
                    pass
                return result
            except Exception as e:
                return {"text": f"openai adapter error: {e}", "tokens": 0, "cost": 0.0, "latency": time.time() - start}

        # Fallback: estimate tokens from prompt length
        text = "openai placeholder response"
        tokens = max(1, len(text.split()))
        return {"text": text, "tokens": int(tokens), "cost": 0.0, "latency": time.time() - start}
