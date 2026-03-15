# Agentic AI (local-first)

Local-first agentic AI runtime (FastAPI + Postgres + pgvector + Redis).

Summary
- Purpose: lightweight local-first agent runtime that runs agent personas, stores memories in Postgres/pgvector, uses local LLMs (Ollama, LiteLLM) with an OpenAI fallback, and processes tasks via a Redis-backed queue with an in-memory fallback.

Key components
- `FastAPI` server (src/app/main.py)
- Agents: markdown-driven agent personas under `agents/` imported via `POST /admin/import`
- Storage: Postgres with `pgvector` (memories vectorized with 1536-dim embeddings)
- Queue: `QueueAdapter` (Redis rpush/blpop with in-memory `asyncio.Queue` fallback) in `src/app/agent/queue.py`
- Executor: `AgentExecutor` worker processes tasks, calls LLM adapters, persists memories
- Adapters: `OllamaAdapter`, `LiteLLMAdapter`, `OpenAIAdapter` in `src/app/adapters/`

Quickstart (dev)
Prerequisites:
- Python 3.10+ (project tested on 3.11/3.12)
- Optional: Docker & docker-compose to run Postgres+Redis locally

1) Create and activate virtualenv
```bash
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Tip: edit project files with `vi` (or `nvim`) e.g. `vi src/app/routers/agents.py`.

2) Option A — run with docker-compose (recommended for DB + Redis)
```bash
docker compose up -d
# then run server in venv
uvicorn src.app.main:app --reload
```

2) Option B — run services manually and start server
```powershell
# ensure Postgres + Redis running and env vars configured
uvicorn src.app.main:app --reload
```

API docs & OpenAPI
- A generated OpenAPI specification is included at `docs/openapi.yaml` (OpenAPI 3.0.3). Use it to import into tools like Postman or Swagger UI.

Agent management endpoints
- `DELETE /agents/{agent_id}`: remove an agent and all its memories (returns `204` on success). This endpoint is useful for test cleanup and housekeeping; the included e2e script `tests/e2e_test.py` now calls it after creating a temporary agent.

If you want to regenerate the OpenAPI JSON from a running server, fetch the live schema with `curl`:

```bash
curl -sS http://127.0.0.1:8000/openapi.json -o docs/openapi.json
# optionally pretty-print with `jq`:
# jq . docs/openapi.json > docs/openapi.pretty.json
```

Using `vi` on Windows
---------------------
If `vi`/`vim` isn't available on your Windows machine, recommended options:

- Use WSL (Ubuntu/other) and run `vi`/`nvim` there. Install WSL from the Microsoft Store and then:

```bash
# inside WSL
sudo apt update && sudo apt install -y vim
```

- Install Vim via Chocolatey:

```powershell
choco install vim -y
```

- Use Git Bash (bundled with Git for Windows) which includes `vim`/`vi`, or install Neovim for a modern experience.

After installing, ensure the editor executable is on your `PATH` so calling `vi` from your preferred shell opens the editor.


Developer notes
- Tests: unit tests are under `tests/unit/`, e2e under `tests/e2e/`.
	- Run unit tests: `python -m pytest tests/unit -q`
	- Run all tests: `python -m pytest -q`
- Scripts: `scripts/sync_agents.py` and `scripts/clean_agents.py` to manage agent markdown imports.
- Key files: `src/app/agent/queue.py`, `src/app/agent/executor.py`, `src/app/adapters/`.

Docs
- OpenAPI: `docs/openapi.yaml`
- Architecture diagram (PlantUML): `docs/architecture.puml` — render with PlantUML or use an online viewer.

Next steps / TODOs
- Add CI to run `tests/unit` (recommended)
- Add an optional metrics UI (in-progress)

Contact
- For development help or to run e2e flows, see the project maintainer notes in the repo.

**Architecture & State**

- **Stateful (persisted)**
	- **Postgres (Agents & Memories):** Agents and memories are persisted in Postgres tables (`agents`, `memories`) and survive FastAPI restarts when the DB is persistent. See `src/app/models.py` and `src/app/crud.py`.
	- **Redis (optional):** When `REDIS_URL` is configured, the `QueueAdapter` prefers Redis for queue storage so tasks can survive server restarts and be shared across processes. See `src/app/agent/queue.py`.
	- **Disk/Volumes:** Agent markdown under `agents/` and model artifacts (Ollama/LiteLLM) persist on disk or container volumes.

- **Stateless / Ephemeral**
	- **In-memory queue fallback:** If Redis is not available, the runtime uses an in-process `asyncio.Queue` which is lost on process restart.
	- **App state & background tasks:** `app.state.*` tasks (metrics persister, executor loop) are ephemeral and restart with the process.

**Options for carrying historical events & state**

- Keep using Postgres as the primary durable store (already present). For richer event history consider adding an `events` table with `event_type`, `payload`, `created_at` for append-only auditing and replay.
- Use Redis (persistent instance) for queue durability; alternatively Redis Streams, Kafka, or RabbitMQ if ordering, replay, and retention policies are required.
- Offload large transcripts/artifacts to object storage (S3/GCS) and reference them from DB rows.
- Add migrations (Alembic) and automated backups (pg_dump, WAL) to protect schema and data.

**Are memories kept between restarts?**

Yes — memories are stored in Postgres. They persist across FastAPI restarts provided your Postgres instance is persistent (for example a container with a Docker volume, or a managed DB). If Postgres runs in a disposable container without a volume, data will be lost when the container is removed.

**Persistence verification (quick steps)**

1. Create an agent and ingest a memory (use `curl`):

```bash
# create an agent
curl -sS -X POST http://127.0.0.1:8000/agents -H "Content-Type: application/json" -d '{"name":"tmp-test","description":"tmp"}' | jq .

# ingest a memory
curl -sS -X POST http://127.0.0.1:8000/agents/<AGENT_ID>/memories/ingest -H "Content-Type: application/json" -d '{"content":"persist-test","metadata":{"case":"persistence"}}' | jq .

# check status
curl -sS http://127.0.0.1:8000/agents/<AGENT_ID>/status | jq .
```

2. Restart the FastAPI process (or container), then re-run the `status` call — the memory should still appear.

3. To verify queue durability, enable `REDIS_URL` and confirm that `QueueAdapter` uses Redis (check logs or call `GET /metrics/usage-by-adapter` if instrumented) and that queued tasks are present after restarts.

**Recommendations**

- Ensure Postgres runs with a persistent volume or use a managed DB service.
- Enable Redis for durable queues if you rely on task persistence across restarts.
- Add an `events` table or extend `memories` with `event_type`/`raw_payload` for audit/replay requirements.
- Add Alembic migrations and scheduled DB backups to prevent accidental data loss.
- Add an automated integration test that creates a memory, restarts the server, and verifies persistence (useful as a CI guard).
  
Alembic & migrations
- Initialize Alembic in the repo (one-time):

```bash
# from repo root
alembic init alembic
```

- Configure `alembic.ini` or environment to use your `DATABASE_URL` (the repo includes a starter `alembic/env.py` that reads `src.app.config.settings.database_url`).

- Create an initial migration after models are stable:

```bash
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

Backups
- Quick manual DB dump:

```bash
pg_dump -Fc --file=backups/agentdb-$(date +%F).dump $DATABASE_URL
```

Integration persistence check
- There is a small helper script at `tests/integration/check_persistence.py` that creates an agent and memory, and helps verify persistence after a manual restart. Use it for manual verification or wrap it in CI with appropriate service restart steps.