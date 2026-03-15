# Justfile for common developer tasks (prefer running from WSL/Git-Bash)
# Install Just: https://github.com/casey/just

# --- Configuration (override by passing env vars or editing file) ---
POSTGRES_USER := agent
POSTGRES_PASSWORD := agentpass
POSTGRES_DB := agentdb
POSTGRES_PORT := 5432
REDIS_URL := redis://localhost:6379
OLLAMA_URL := http://host.docker.internal:11434
LITELLM_URL := http://localhost:11435

# Convenience derived variables
DATABASE_URL := postgres://{{POSTGRES_USER}}:{{POSTGRES_PASSWORD}}@localhost:{{POSTGRES_PORT}}/{{POSTGRES_DB}}

# Write a local .env file with the current values
envfile:
    @echo "Writing .env with local defaults"
    @printf "POSTGRES_USER=%s\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=%s\nPOSTGRES_PORT=%s\nREDIS_URL=%s\nOLLAMA_URL=%s\nLITELLM_URL=%s\n" \
        "{{POSTGRES_USER}}" "{{POSTGRES_PASSWORD}}" "{{POSTGRES_DB}}" "{{POSTGRES_PORT}}" "{{REDIS_URL}}" "{{OLLAMA_URL}}" "{{LITELLM_URL}}" > .env

# Best-effort Ollama install (platform-specific). This tries the official script
# but may require manual steps on your OS. Run this in WSL/Git-Bash for best results.
install-ollama:
    @echo "Attempting a best-effort Ollama install (may require sudo)."
    @echo "If this fails, please follow https://ollama.ai/docs/install"
    @bash -lc "curl -sSfL https://ollama.ai/install | sh || true"

# Build and start Docker services (postgres, redis, litellm, etc.)
docker-up:
    @echo "Starting Docker services via docker compose..."
    docker compose up -d postgres redis litellm

docker-down:
    @echo "Stopping Docker services"
    docker compose down

build-litellm:
    @echo "Building LiteLLM wrapper image"
    docker compose build litellm

# Run Alembic migrations (assumes your venv/pyenv is active so `alembic` is on PATH)
migrate:
    @echo "Running Alembic migrations (ensure venv active or `alembic` available)`"
    alembic upgrade head

# Start the FastAPI server (Unix / WSL / macOS)
start-api:
    @echo "Starting FastAPI (Unix). Use Ctrl-C to stop."
    . venv/bin/activate 2>/dev/null || true
    uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000

# Start the FastAPI server (Windows PowerShell/Command Prompt)
start-api-windows:
    @echo "Starting FastAPI (Windows). Uses venv/Scripts/python.exe"
    venv\\Scripts\\python.exe -m uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000

# Start everything: docker, migrate, then start API in background (for dev)
start-all:
    @echo "Start docker, run migrations, then start API (Unix/WSL)"
    docker compose up -d postgres redis litellm
    alembic upgrade head || true
    . venv/bin/activate 2>/dev/null || true
    uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000 &
    @echo "Started services and API (check logs with docker compose ps)"

# Run unit tests
test:
    @echo "Running unit tests"
    . venv/bin/activate 2>/dev/null || true
    python -m pytest tests/unit -q

# Integration persistence check helper invocation
persistence-check:
    @echo "Run the integration persistence helper (manual restart required)"
    python tests/integration/check_persistence.py
