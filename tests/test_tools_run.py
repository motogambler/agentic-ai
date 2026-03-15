#!/usr/bin/env python3
import asyncio
import sys
import os

# Ensure repo root is on sys.path for direct script execution
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.app.tools.basic import echo, calc, run_cmd, read_file


async def main():
    r1 = await echo('hello')
    assert r1['result'] == 'hello', r1

    r2 = await calc('1+2*3')
    assert r2.get('result') == 7, r2

    r3 = await run_cmd('python -c "print(\'ok\')"', timeout=5)
    assert ('ok' in r3.get('stdout', '') or r3.get('returncode') == 0), r3

    print('TOOLS OK')


if __name__ == '__main__':
    asyncio.run(main())
