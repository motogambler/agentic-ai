import aiohttp
import json
import ast
import asyncio
import sys
from typing import Any


async def echo(text: str, **kwargs) -> dict:
    return {"result": text}


async def http_get(url: str, **kwargs) -> dict:
    """Async HTTP GET with timeout and basic error handling."""
    timeout = kwargs.get("timeout", 10)
    headers = kwargs.get("headers")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout, headers=headers) as resp:
                text = await resp.text()
                return {"status": resp.status, "result": text}
    except asyncio.TimeoutError:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)}


def _safe_eval_expr(expr: str) -> Any:
    # Allow only simple arithmetic expressions using ast
    node = ast.parse(expr, mode='eval')

    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Num,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.Load,
    )

    for n in ast.walk(node):
        if not isinstance(n, allowed):
            raise ValueError("unsafe expression")

    return eval(compile(node, '<string>', 'eval'), {})


async def calc(expr: str, **kwargs) -> dict:
    try:
        val = _safe_eval_expr(expr)
        return {"result": val}
    except Exception as e:
        return {"error": str(e)}


async def run_cmd(cmd: str, timeout: int = 10) -> dict:
    """Run a shell command asynchronously with a timeout. Returns stdout/stderr."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": "timeout"}

        return {"returncode": proc.returncode, "stdout": out.decode(errors='ignore'), "stderr": err.decode(errors='ignore')}
    except Exception as e:
        return {"error": str(e)}


async def read_file(path: str, max_bytes: int = 100_000) -> dict:
    """Read a local file asynchronously (non-blocking wrapper)."""
    try:
        loop = asyncio.get_running_loop()
        def _read():
            with open(path, 'rb') as f:
                return f.read(max_bytes)

        data = await loop.run_in_executor(None, _read)
        return {"result": data.decode(errors='ignore')}
    except Exception as e:
        return {"error": str(e)}
