from abc import ABC, abstractmethod
from typing import Any, Dict

class LLMAdapter(ABC):
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate a response and return metadata {text, tokens, latency} """
        raise NotImplementedError()
