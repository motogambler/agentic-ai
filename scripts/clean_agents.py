import asyncio
import sys
from pathlib import Path
from sqlalchemy import delete

# ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app.db import AsyncSessionLocal
from src.app import models

PATTERNS = [
    "e2e-test-agent%",
    "search-test-%",
    "search-test%",
]
EXACT = ["tool-agent"]

async def main():
    async with AsyncSessionLocal() as session:
        # delete by patterns
        for p in PATTERNS:
            stmt = delete(models.Agent).where(models.Agent.name.ilike(p))
            await session.execute(stmt)
        for name in EXACT:
            stmt = delete(models.Agent).where(models.Agent.name == name)
            await session.execute(stmt)
        await session.commit()
        print('deleted test agents matching patterns')

if __name__ == '__main__':
    asyncio.run(main())
