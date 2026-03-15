import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncio
from sqlalchemy import select, update
from src.app.db import AsyncSessionLocal
from src.app import models

BASE = Path(ROOT) / "agents"


def parse_frontmatter(text: str) -> dict:
    lines = text.splitlines()
    out = {}
    if not lines or lines[0].strip() != "---":
        return out
    # find closing ---
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return out
    fm_lines = lines[1:end]
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if ":" not in line:
            i += 1
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        # block scalar
        if v == "|":
            i += 1
            parts = []
            while i < len(fm_lines) and (fm_lines[i].startswith("  ") or fm_lines[i].startswith("\t") or fm_lines[i].strip() == ""):
                parts.append(fm_lines[i].lstrip())
                i += 1
            out[k] = "\n".join(parts).strip()
            continue
        # list following key (next lines start with '-')
        if v == "":
            j = i + 1
            items = []
            while j < len(fm_lines) and fm_lines[j].strip().startswith("-"):
                items.append(fm_lines[j].strip().lstrip("-").strip())
                j += 1
            if items:
                out[k] = items
                i = j
                continue
        # simple scalar
        val = v
        if val.lower() in ("true", "false"):
            out[k] = val.lower() == "true"
        else:
            try:
                if "." in val:
                    out[k] = float(val)
                else:
                    out[k] = int(val)
            except Exception:
                out[k] = val.strip('"').strip("'")
        i += 1
    return out


async def sync():
    created = []
    updated = []
    async with AsyncSessionLocal() as session:
        for path in sorted(BASE.rglob("*.md")):
            try:
                txt = path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"skip {path}: read error {e}")
                continue
            fm = parse_frontmatter(txt) or {}
            rel = path.relative_to(BASE)
            rel_no_ext = str(rel.with_suffix("")).replace("\\", "/")
            agent_name = fm.get("name") or rel_no_ext

            # load existing
            stmt = select(models.Agent).where(models.Agent.name == agent_name)
            res = await session.execute(stmt)
            existing = res.scalars().first()
            if existing:
                # update config
                await session.execute(
                    update(models.Agent).where(models.Agent.id == existing.id).values(config=fm)
                )
                updated.append(agent_name)
            else:
                # create
                obj = models.Agent(name=agent_name, config=fm)
                session.add(obj)
                created.append(agent_name)
        await session.commit()
    print("created:", created)
    print("updated:", updated)


if __name__ == "__main__":
    asyncio.run(sync())
