from .basic import echo, http_get, calc, run_cmd, read_file

_TOOLS = {
    "echo": echo,
    "http_get": http_get,
    "calc": calc,
    "run_cmd": run_cmd,
    "read_file": read_file,
}


async def run_tool(name: str, args: dict | None = None):
    func = _TOOLS.get(name)
    if not func:
        return {"error": f"unknown tool: {name}"}
    if args is None:
        args = {}

    # Special reserved keys in args: `_timeout` and `_retries` control execution
    timeout = args.pop("_timeout", None)
    retries = int(args.pop("_retries", 1)) if args.get("_retries", None) is not None else 1

    last_exc = None
    for attempt in range(max(1, retries)):
        try:
            if timeout:
                import asyncio

                return await asyncio.wait_for(func(**args), timeout=timeout)
            else:
                return await func(**args)
        except Exception as e:
            last_exc = e
            # simple backoff
            import asyncio

            await asyncio.sleep(0.1 * (attempt + 1))
    return {"error": f"tool failed after {retries} attempts: {last_exc}"}
