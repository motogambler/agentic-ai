import os
import asyncio
from typing import Optional
from pathlib import Path

from ..crud import add_event, add_memory
from .. import schemas
from ..db import AsyncSessionLocal
from ..utils.embeddings import compute_embedding

# Configuration
_ENABLED = os.getenv("ENABLE_REPO_TOOL", "false").lower() in ("1", "true", "yes")
_ALLOWED_DIRS = os.getenv("REPO_TOOL_ALLOWED_DIRS", "agents,scripts,docs,workspace").split(",")
_MAX_BYTES = int(os.getenv("REPO_TOOL_MAX_BYTES", "200000"))


def _project_root() -> str:
    return os.getcwd()


def _resolve_and_check(path: str) -> Optional[Path]:
    root = Path(_project_root()).resolve()
    raw = Path(path) if path else root
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        # Allow the project root itself so callers can inspect the repository root.
        if candidate == root:
            return candidate

        # Allow root-level files like README.md when the user selected the repo root.
        if candidate.parent == root:
            return candidate

        # Ensure candidate is under one of the allow-list directories.
        for d in _ALLOWED_DIRS:
            allowed = (root / d).resolve()
            try:
                candidate.relative_to(allowed)
                return candidate
            except Exception:
                continue
    except Exception:
        return None
    return None


async def repo_list(path: str = "") -> dict:
    p = _resolve_and_check(path or "")
    if p is None:
        return {"error": "path not allowed"}
    try:
        loop = asyncio.get_running_loop()

        def _ls():
            out = []
            if p.is_dir():
                for entry in sorted(p.iterdir()):
                    out.append({"name": entry.name, "is_dir": entry.is_dir()})
            else:
                out.append({"name": p.name, "is_dir": False})
            return out

        items = await loop.run_in_executor(None, _ls)
        # record an audit event (no agent by default)
        async with AsyncSessionLocal() as db:
            await add_event(db, None, "repo_list", {"path": str(p)})
        return {"result": items}
    except Exception as e:
        return {"error": str(e)}


async def repo_read(path: str, max_bytes: int | None = None) -> dict:
    # Reading files has been intentionally disabled for security/privacy.
    # The repo tool is limited to listing and writing new files only.
    return {"error": "repo_read disabled: reading repository files is not allowed"}


async def repo_mkdir(path: str) -> dict:
    if not _ENABLED:
        return {"error": "repo tool disabled"}
    p = _resolve_and_check(path)
    if p is None:
        return {"error": "path not allowed"}
    try:
        loop = asyncio.get_running_loop()

        def _mk():
            p.mkdir(parents=True, exist_ok=True)
            return True

        await loop.run_in_executor(None, _mk)
        async with AsyncSessionLocal() as db:
            await add_event(db, None, "repo_mkdir", {"path": str(p)})
        return {"result": "ok", "path": str(p)}
    except Exception as e:
        return {"error": str(e)}


async def repo_write(path: str, content: str, agent_id: int | None = None, persist_memory: bool = True) -> dict:
    if not _ENABLED:
        return {"error": "repo tool disabled"}
    p = _resolve_and_check(path)
    if p is None:
        return {"error": "path not allowed"}
    if len(content.encode("utf-8")) > _MAX_BYTES:
        return {"error": "content too large"}
    try:
        loop = asyncio.get_running_loop()

        def _write():
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return True

        await loop.run_in_executor(None, _write)
        # record audit event and optionally persist as memory
        async with AsyncSessionLocal() as db:
            await add_event(db, agent_id, "repo_write", {"path": str(p), "size": len(content)})
            if persist_memory and agent_id is not None:
                try:
                    emb = await compute_embedding(content)
                except Exception:
                    emb = None
                mem = schemas.MemoryCreate(content=content, embedding=emb, metadata={"source": "repo_tool", "path": str(p)})
                try:
                    await add_memory(db, agent_id, mem)
                except Exception:
                    pass
        return {"result": "ok", "path": str(p)}
    except Exception as e:
        return {"error": str(e)}
