import asyncio
import logging
import json
from ..config import settings
from dataclasses import dataclass
from typing import Any

from ..crud import add_memory
from ..adapters.ollama_adapter import OllamaAdapter
from ..adapters.litellm_adapter import LiteLLMAdapter
from ..adapters.openai_adapter import OpenAIAdapter
from ..utils.embeddings import compute_embedding
from ..costs import BUDGET
import asyncio
import os

logger = logging.getLogger("agent.executor")

VALID_TOOLS = {"echo", "http_get", "calc", "run_cmd", "read_file", "repo_list", "repo_read", "repo_write", "repo_mkdir"}


def _model_timeout_seconds(model: str | None, default: int = 20) -> int:
    if isinstance(model, str) and model.startswith("ollama:"):
        # Larger local models can take materially longer on first-token latency.
        if any(tag in model for tag in (":8b", ":14b", ":latest")):
            return 120
        return 90
    return default


def _extract_json_payload(text: str):
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _normalize_tool_call(parsed: dict | None):
    if not isinstance(parsed, dict):
        return None
    if "tool_call" in parsed and isinstance(parsed.get("tool_call"), dict):
        tc = dict(parsed["tool_call"])
    elif isinstance(parsed.get("output"), dict) and isinstance(parsed["output"].get("value"), dict):
        inner = parsed["output"]["value"]
        if isinstance(inner.get("tool_call"), dict):
            tc = dict(inner["tool_call"])
        else:
            return None
    else:
        return None

    tool = tc.get("tool")
    args = tc.get("args", {}) or {}
    if not isinstance(args, dict):
        args = {}

    if tool == "calc":
        if "expr" not in args and "expression" in args:
            args["expr"] = args.pop("expression")
        if "expr" not in args and "text" in args:
            args["expr"] = args.pop("text")

    if tool not in VALID_TOOLS:
        return None

    return {"tool": tool, "args": args}


def _clean_response_text(text: str) -> str:
    if not isinstance(text, str):
        return str(text)
    parsed = _extract_json_payload(text)
    if parsed is not None:
        return json.dumps(parsed)
    return text.strip()


@dataclass
class AgentTask:
    agent_id: int
    goal: str
    context: dict | None = None


class AgentExecutor:
    """Very small executor that runs simple tasks.

    Current behavior: calls local LLM adapters (Ollama, LiteLLM) and a
    placeholder OpenAI adapter, then writes the LLM output as a memory.
    """

    def __init__(self, db_session_factory):
        # db_session_factory should be an async session maker or a callable that
        # returns an AsyncSession via `async with db_session_factory() as s`.
        self.db_factory = db_session_factory
        # Initialize adapters
        self.ollama = OllamaAdapter()
        self.litellm = LiteLLMAdapter()
        # Read OpenAI API key from configured settings (pydantic Settings loads .env)
        openai_key = getattr(settings, 'openai_api_key', None)
        self.openai = OpenAIAdapter(api_key=openai_key)
        # Track whether OpenAI is configured so we only try it when useful
        self._openai_configured = bool(openai_key)
        # Global budget tracker is available via `BUDGET` in the module when needed

    async def run_task(self, task: AgentTask):
        logger.info("Running agent task: %s", task.goal)

        # helper to call adapters with a small retry/backoff
        async def _call_adapter_with_retries(adapter, prompt, model=None, timeout=15, retries=2):
            last_exc = None
            for attempt in range(max(1, retries)):
                try:
                    if model is not None and model != '':
                        return await asyncio.wait_for(adapter.generate(prompt, model=model), timeout=timeout)
                    else:
                        return await asyncio.wait_for(adapter.generate(prompt), timeout=timeout)
                except Exception as e:
                    last_exc = e
                    await asyncio.sleep(0.1 * (attempt + 1))
            if last_exc is None:
                err_text = "adapter error: unknown"
            else:
                err_text = f"adapter error: {type(last_exc).__name__}: {last_exc}".rstrip()
            return {"text": err_text, "tokens": 0, "cost": 0.0}

        # Compose prompt early so follow-up branches can reference it safely
        # If a persona was provided in the task context, prepend it to specialize the agent's voice
        persona_prefix = ""
        try:
            if task.context and isinstance(task.context, dict):
                p = task.context.get('persona')
                if p and isinstance(p, str):
                    persona_prefix = p.strip() + "\n\n"
        except Exception:
            persona_prefix = ""

        repo_context = ""
        try:
            if task.context and isinstance(task.context, dict):
                repo_base = task.context.get("repo_base")
                repo_snapshot = task.context.get("repo_snapshot")
                if repo_base:
                    repo_context += f"Repository base available: {repo_base}\n"
                if isinstance(repo_snapshot, dict):
                    snap_path = repo_snapshot.get("path")
                    snap_content = str(repo_snapshot.get("content") or "")[:4000]
                    repo_context += (
                        "Repository snapshot is already provided below. Use it directly before asking for more input.\n"
                        f"Snapshot path: {snap_path}\n"
                        f"Snapshot content:\n{snap_content}\n"
                    )
                if repo_context:
                    repo_context += (
                        "If you need more repository context, use repo_list(path), repo_read(path), "
                        "repo_write(path, content), or repo_mkdir(path). Do not ask the user to paste files "
                        "if repo context or repo tools are available.\n"
                    )
        except Exception:
            repo_context = ""

        prompt = (
            f"{persona_prefix}Agent {task.agent_id} goal: {task.goal}\n"
            f"{repo_context}"
            "Available tools: echo(text), http_get(url), calc(expr), run_cmd(cmd), read_file(path), "
            "repo_list(path), repo_read(path), repo_write(path, content), repo_mkdir(path).\n"
            "If a tool is needed, respond with ONLY valid JSON in this exact shape: "
            "{\"tool_call\": {\"tool\": \"calc\", \"args\": {\"expr\": \"1+1\"}}}.\n"
            "If no tool is needed, respond with a concise plain-text answer only."
        )

        # Keep a stable base prompt so follow-up generations don't depend on
        # a variable that might be shadowed or unassigned in some runtime paths.
        base_prompt = prompt

        # If a tool_call was provided in the task context, run it directly and persist
        if task.context and isinstance(task.context, dict) and task.context.get("tool_call"):
            from ..tools import run_tool

            tc = task.context.get("tool_call")
            tool = tc.get("tool")
            if tool not in VALID_TOOLS:
                logger.warning("Ignoring unsupported tool in task context: %s", tool)
                return
            args = tc.get("args", {})
            tool_result = await run_tool(tool, args)

            result_text = f"Tool {tool} result: {tool_result}"
            memory = type("_", (), {})()
            memory.content = result_text
            try:
                memory.embedding = await compute_embedding(memory.content)
            except Exception:
                memory.embedding = None
            memory.metadata = {"source": "executor", "tool": tool, "tool_result": tool_result}

            async with self.db_factory() as db:
                await add_memory(db, task.agent_id, memory)
            logger.info("Tool task complete for agent %s", task.agent_id)
            return


        # Optionally persist the composed prompt for debugging so we can verify persona inclusion
        try:
            dbg_flag = os.getenv('DEBUG_PERSIST_PROMPT', '0') == '1'
            if task.context and isinstance(task.context, dict):
                dbg_flag = dbg_flag or bool(task.context.get('debug_persist_prompt'))
            if dbg_flag:
                pmem = type("_", (), {})()
                pmem.content = f"PROMPT: {prompt}"
                try:
                    pmem.embedding = await compute_embedding(pmem.content)
                except Exception:
                    pmem.embedding = None
                pmem.metadata = {"source": "executor", "note": "persisted_prompt"}
                async with self.db_factory() as db:
                    await add_memory(db, task.agent_id, pmem)
                # also persist the merged task context so callers can verify what
                # agent config keys (skills, persona, etc.) were propagated
                try:
                    import json

                    cmem = type("_", (), {})()
                    cmem.content = f"CONTEXT: {json.dumps(task.context, ensure_ascii=False)}"
                    try:
                        cmem.embedding = await compute_embedding(cmem.content)
                    except Exception:
                        cmem.embedding = None
                    cmem.metadata = {"source": "executor", "note": "persisted_context"}
                    async with self.db_factory() as db:
                        await add_memory(db, task.agent_id, cmem)
                except Exception:
                    pass
        except Exception:
            pass

        # Call adapters in preferred order: LiteLLM -> OpenAI -> Ollama
        # allow tasks to hint a preferred model via task.context.model
        preferred_model = None
        try:
            if task.context and isinstance(task.context, dict):
                preferred_model = task.context.get('model')
        except Exception:
            preferred_model = None

        primary_timeout = _model_timeout_seconds(preferred_model, default=20)
        resp = await _call_adapter_with_retries(self.litellm, prompt, model=preferred_model, timeout=primary_timeout, retries=2)
        text = resp.get("text", "")
        # normalize non-string adapter responses
        if not isinstance(text, str):
            try:
                import json

                text = json.dumps(text)
            except Exception:
                text = str(text)
        # If litellm produced an error-like text, try OpenAI next if configured, otherwise try Ollama
        if isinstance(text, str) and text.startswith("litellm error"):
            if self._openai_configured:
                resp = await _call_adapter_with_retries(self.openai, prompt, model=preferred_model, timeout=30, retries=2)
                text = resp.get("text", "")
                if isinstance(text, str) and text.startswith("openai adapter error"):
                    # finally try Ollama
                    resp = await _call_adapter_with_retries(self.ollama, prompt, model=preferred_model, timeout=primary_timeout, retries=2)
                    text = resp.get("text", "")
            else:
                # skip OpenAI fallback (not configured) and try Ollama directly
                resp = await _call_adapter_with_retries(self.ollama, prompt, model=preferred_model, timeout=primary_timeout, retries=2)
                text = resp.get("text", "")

        cleaned_text = _clean_response_text(text)

        # Persist initial LLM output as a memory (with embedding if available)
        result_text = f"LLM result: {cleaned_text}"
        memory = type("_", (), {})()
        memory.content = result_text
        try:
            memory.embedding = await compute_embedding(memory.content)
        except Exception:
            memory.embedding = None
        memory.metadata = {"source": "executor", "llm_meta": resp}

        async with self.db_factory() as db:
            await add_memory(db, task.agent_id, memory)

        # Attempt to parse LLM output as JSON to detect a tool call
        parsed = _extract_json_payload(text) if isinstance(text, str) else None
        tool_call = _normalize_tool_call(parsed)

        if tool_call:
            from ..tools import run_tool

            tool = tool_call.get("tool")
            args = tool_call.get("args", {})
            tool_result = await run_tool(tool, args)

            # Persist tool result with embedding
            tmem = type("_", (), {})()
            tmem.content = f"Tool {tool} executed: {tool_result}"
            try:
                tmem.embedding = await compute_embedding(tmem.content)
            except Exception:
                tmem.embedding = None
            tmem.metadata = {"source": "executor", "tool": tool}
            async with self.db_factory() as db:
                await add_memory(db, task.agent_id, tmem)

            # Optionally call LLM again with the tool result to produce a final summary
            try:
                followup_prompt = (
                    f"{base_prompt}\n"
                    f"Tool {tool} returned: {tool_result}\n"
                    "Respond with a final concise plain-text summary only. Do not return JSON."
                )
            except Exception:
                # fallback to a minimal prompt if something unexpected happens
                followup_prompt = (
                    f"Agent {task.agent_id} goal: {task.goal}\n"
                    f"Tool {tool} returned: {tool_result}\n"
                    "Respond with a final concise plain-text summary only. Do not return JSON."
                )
            # Reuse the same adapter preference order so prefixed models like
            # `ollama:<name>` continue to route through the LiteLLM wrapper.
            fresp = await _call_adapter_with_retries(self.litellm, followup_prompt, model=preferred_model, timeout=primary_timeout, retries=2)
            ftext = fresp.get("text", "")
            if isinstance(ftext, str) and ftext.startswith("litellm error"):
                fresp = await _call_adapter_with_retries(self.openai, followup_prompt, model=preferred_model, timeout=30, retries=2)
                ftext = fresp.get("text", "")
                if isinstance(ftext, str) and ftext.startswith("openai adapter error"):
                    fresp = await _call_adapter_with_retries(self.ollama, followup_prompt, model=preferred_model, timeout=primary_timeout, retries=2)
            ftext = fresp.get("text", "")
            fmemory = type("_", (), {})()
            fmemory.content = f"LLM final: {_clean_response_text(ftext)}"
            try:
                fmemory.embedding = await compute_embedding(fmemory.content)
            except Exception:
                fmemory.embedding = None
            fmemory.metadata = {"source": "executor", "llm_meta": fresp}
            async with self.db_factory() as db:
                await add_memory(db, task.agent_id, fmemory)

        logger.info("Task complete for agent %s", task.agent_id)

    async def worker_loop(self, queue):
        while True:
            try:
                task = await queue.get()
                await self.run_task(task)
            except Exception:
                logger.exception("Error running agent task")
            finally:
                await asyncio.sleep(0.01)
