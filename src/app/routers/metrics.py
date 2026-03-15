from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..costs import get_budget_snapshot, reset_budget
from ..db import get_db
from .. import crud

router = APIRouter()


@router.get("/budget")
async def budget():
    """Return current in-memory budget snapshot: tokens and cost."""
    return get_budget_snapshot()


@router.post("/budget/reset")
async def budget_reset():
    """Reset the in-memory budget counters."""
    return reset_budget()


@router.get("/usage-by-adapter")
async def usage_by_adapter():
    """Return per-adapter token/cost/calls breakdown."""
    snap = get_budget_snapshot()
    return snap.get("adapters", {})


@router.get("/ui", response_class=HTMLResponse)
async def metrics_ui():
    """Simple HTML dashboard showing budget and per-adapter usage.

    This is intentionally tiny and dependency-free (vanilla JS fetch polling).
    """
    html = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Agentic AI - Budget</title>
      <style>
        body { font-family: system-ui, Arial, sans-serif; margin: 20px; }
        .card { border: 1px solid #ddd; padding: 12px; border-radius: 6px; margin-bottom: 12px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #eee; }
      </style>
    </head>
    <body>
      <h2>Budget Snapshot</h2>
      <div id="budget" class="card">Loading...</div>

      <h3>Usage by Adapter</h3>
      <div id="adapters" class="card">Loading...</div>

      <script>
        async function fetchBudget() {
          try {
            const b = await fetch('/metrics/budget');
            const jb = await b.json();
            document.getElementById('budget').innerText = `Tokens: ${jb.tokens} — Cost: ${jb.cost}`;
            const a = await fetch('/metrics/usage-by-adapter');
            const ja = await a.json();
            const keys = Object.keys(ja || {});
            if (!keys.length) {
              document.getElementById('adapters').innerText = 'No adapter usage recorded yet.';
              return;
            }
            let html = '<table><thead><tr><th>Adapter</th><th>Tokens</th><th>Cost</th><th>Calls</th></tr></thead><tbody>';
            for (const k of keys) {
              const s = ja[k];
              html += `<tr><td>${k}</td><td>${s.tokens}</td><td>${s.cost}</td><td>${s.calls}</td></tr>`;
            }
            html += '</tbody></table>';
            document.getElementById('adapters').innerHTML = html;
          } catch (e) {
            document.getElementById('budget').innerText = 'error fetching metrics';
            document.getElementById('adapters').innerText = '';
          }
        }

        fetchBudget();
        setInterval(fetchBudget, 3000);
      </script>
    </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/prometheus")
async def prometheus_metrics():
    """Expose a tiny Prometheus-style exporter for current in-memory metrics.

    Produces plain-text exposition format with a few metrics:
      - agentic_budget_tokens_total
      - agentic_budget_cost_total
      - agentic_adapter_tokens_total{adapter="..."}
      - agentic_adapter_cost_total{adapter="..."}
      - agentic_adapter_calls_total{adapter="..."}
    """
    snap = get_budget_snapshot()
    lines = []
    lines.append('# HELP agentic_budget_tokens_total Total tokens tracked')
    lines.append('# TYPE agentic_budget_tokens_total counter')
    lines.append(f'agentic_budget_tokens_total {snap.get("tokens", 0)}')
    lines.append('# HELP agentic_budget_cost_total Total estimated cost')
    lines.append('# TYPE agentic_budget_cost_total gauge')
    lines.append(f'agentic_budget_cost_total {snap.get("cost", 0.0)}')

    adapters = snap.get('adapters', {}) or {}
    for name, stat in adapters.items():
        safe = str(name).replace('"', '\\"')
        lines.append(f'# HELP agentic_adapter_tokens_total Tokens per adapter')
        lines.append(f'# TYPE agentic_adapter_tokens_total counter')
        lines.append(f'agentic_adapter_tokens_total{{adapter="{safe}"}} {stat.get("tokens", 0)}')
        lines.append(f'# HELP agentic_adapter_cost_total Cost per adapter')
        lines.append(f'# TYPE agentic_adapter_cost_total gauge')
        lines.append(f'agentic_adapter_cost_total{{adapter="{safe}"}} {stat.get("cost", 0.0)}')
        lines.append(f'# HELP agentic_adapter_calls_total Calls per adapter')
        lines.append(f'# TYPE agentic_adapter_calls_total counter')
        lines.append(f'agentic_adapter_calls_total{{adapter="{safe}"}} {stat.get("calls", 0)}')

    text = '\n'.join(lines) + '\n'
    return PlainTextResponse(content=text, media_type='text/plain; version=0.0.4')


@router.get("/snapshots")
async def snapshots(limit: int = Query(100, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    """Return recent persisted metrics snapshots (most recent first)."""
    try:
        rows = await crud.get_metrics_snapshots(db, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "tokens": r.tokens,
            "cost": float(r.cost or 0.0),
            "adapters": r.adapters,
            "created_at": r.created_at.isoformat() if r.created_at is not None else None,
        })
    return out
