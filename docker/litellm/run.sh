#!/bin/sh
set -e

# Start optional preload in background
if [ -n "$PRELOAD_MODELS" ] || [ -z "$(echo "$PRELOAD_MODELS")" ]; then
  echo "[entrypoint] starting preload_models.py (background)"
  python /app/preload_models.py &
else
  echo "[entrypoint] PRELOAD_MODELS not set; skipping preload"
fi

echo "[entrypoint] launching uvicorn"
exec uvicorn run_litellm:app --host 0.0.0.0 --port 11435
