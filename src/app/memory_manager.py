import asyncio
import os
import math
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, delete
from .models import Memory, Agent

# Simple word lists for a tiny heuristic sentiment fallback when no sentiment provided.
POSITIVE = {"good", "great", "happy", "love", "like", "excellent", "awesome", "nice", "positive"}
NEGATIVE = {"bad", "sad", "angry", "hate", "dislike", "terrible", "awful", "negative", "problem"}


def _heuristic_sentiment_score(text: str) -> float:
    if not text:
        return 0.0
    t = text.lower()
    score = 0
    for w in POSITIVE:
        if w in t:
            score += 1
    for w in NEGATIVE:
        if w in t:
            score -= 1
    # clamp and normalize to [-1,1]
    if score == 0:
        return 0.0
    return max(-1.0, min(1.0, score / 5.0))


def _time_decay(created_at: datetime, now: datetime, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    # Normalize naive vs aware datetimes: convert both to aware UTC for safe subtraction
    if created_at is None:
        return 1.0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_days = (now - created_at).total_seconds() / 86400.0
    # exponential decay with given half-life
    lam = math.log(2) / half_life_days
    return math.exp(-lam * age_days)


async def _score_memory(mem, now, half_life_days: float, sentiment_weight: float):
    # base score from recency
    created = mem.created_at or now
    recency = _time_decay(created, now, half_life_days)
    meta = mem.meta or {}
    importance = float(meta.get("importance") or 0.0)
    # sentiment: prefer meta['sentiment_score'] or heuristic
    if isinstance(meta.get("sentiment_score"), (int, float)):
        s = float(meta.get("sentiment_score"))
    else:
        s = _heuristic_sentiment_score(mem.content)
    # final score: recency * (1 + importance) * (1 + sentiment_weight * sentiment)
    return recency * (1.0 + importance) * (1.0 + sentiment_weight * s)


async def prune_loop(async_session_maker):
    """Background task: periodically prune memories per-agent using a sentiment-weighted score.

    Environment variables:
    - MEMORY_MAX_PER_AGENT (int, default 200)
    - MEMORY_PRUNE_INTERVAL (seconds, default 60)
    - MEMORY_HALF_LIFE_DAYS (float, default 30)
    - MEMORY_SENTIMENT_WEIGHT (float, default 0.5)
    - MEMORY_TTL_DAYS (float, default 365)
    """
    max_per_agent = int(os.getenv("MEMORY_MAX_PER_AGENT", "200"))
    interval = int(os.getenv("MEMORY_PRUNE_INTERVAL", "60"))
    half_life_days = float(os.getenv("MEMORY_HALF_LIFE_DAYS", "30"))
    sentiment_weight = float(os.getenv("MEMORY_SENTIMENT_WEIGHT", "0.5"))
    ttl_days = float(os.getenv("MEMORY_TTL_DAYS", "365"))

    while True:
        try:
            now = datetime.now(timezone.utc)
            async with async_session_maker() as db:
                # iterate agents
                stmt = select(Agent)
                res = await db.execute(stmt)
                agents = res.scalars().all()
                for agent in agents:
                    # fetch all memories for agent
                    mstmt = select(Memory).where(Memory.agent_id == agent.id)
                    mres = await db.execute(mstmt)
                    mems = mres.scalars().all()
                    if not mems:
                        continue
                    # compute scores
                    scored = []
                    for m in mems:
                        score = await _score_memory(m, now, half_life_days, sentiment_weight)
                        scored.append((m, score))
                    # sort ascending by score (low first)
                    scored.sort(key=lambda x: x[1])

                    # 1) remove very old memories beyond TTL regardless of score unless importance high
                    ttl_cutoff = now - timedelta(days=ttl_days)
                    to_delete_ids = []
                    for m, sc in scored:
                        meta = m.meta or {}
                        importance = float(meta.get("importance") or 0.0)
                        if (m.created_at is not None and m.created_at < ttl_cutoff) and importance <= 0.0:
                            to_delete_ids.append(m.id)

                    # 2) if per-agent count exceeds max_per_agent, delete lowest-scoring until within limit
                    remaining = [m for m, s in scored if m.id not in to_delete_ids]
                    if len(remaining) > max_per_agent:
                        excess = len(remaining) - max_per_agent
                        # pick lowest-scoring among remaining
                        rem_scored = [(m, s) for m, s in scored if m.id not in to_delete_ids]
                        rem_scored.sort(key=lambda x: x[1])
                        for m, s in rem_scored[:excess]:
                            # skip deleting if importance high
                            meta = m.meta or {}
                            if float(meta.get("importance") or 0.0) > 0.5:
                                continue
                            to_delete_ids.append(m.id)

                    if to_delete_ids:
                        del_stmt = delete(Memory).where(Memory.id.in_(to_delete_ids))
                        await db.execute(del_stmt)
                        await db.commit()

        except Exception:
            # avoid crashing the loop; log if available
            try:
                import logging

                logging.exception("memory prune error")
            except Exception:
                pass
        await asyncio.sleep(interval)
