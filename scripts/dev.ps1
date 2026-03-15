param(
    [string]$Action = "help"
)

# Simple Windows-native dev helper for common project tasks.
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Action envfile

function Write-EnvFile {
    $envfile = Join-Path -Path (Get-Location) -ChildPath ".env"
    Write-Host "Writing .env to $envfile"
    $content = @()
    $content += "POSTGRES_USER=agent"
    $content += "POSTGRES_PASSWORD=agentpass"
    $content += "POSTGRES_DB=agentdb"
    $content += "POSTGRES_PORT=5432"
    $content += "REDIS_URL=redis://localhost:6379"
    $content += "OLLAMA_URL=http://host.docker.internal:11434"
    $content += "LITELLM_URL=http://localhost:11435"
    $content | Out-File -FilePath $envfile -Encoding UTF8 -Force
}

function Install-Ollama {
    Write-Host "Attempting to install Ollama (may require manual steps)"
    try {
        iex ((New-Object System.Net.WebClient).DownloadString('https://ollama.ai/install'))
    } catch {
        Write-Warning "Automatic install failed; please follow https://ollama.ai/docs/install"
    }
}

function Docker-Up {
    Write-Host "Bringing up Docker services: postgres, redis, litellm"
    docker compose up -d postgres redis litellm
}

function Docker-Down {
    Write-Host "Stopping Docker services"
    docker compose down
}

function Build-LiteLLM {
    Write-Host "Building LiteLLM wrapper image"
    docker compose build litellm
}

function Migrate {
    Write-Host "Running Alembic migrations (ensure venv active)"
    .\venv\Scripts\python.exe -m alembic upgrade head
}

function Start-API {
    Write-Host "Starting FastAPI via venv python"
    .\venv\Scripts\python.exe -m uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000
}

function Start-All {
    Docker-Up
    Migrate
    Start-API
}

function Test-Unit {
    .\venv\Scripts\python.exe -m pytest tests/unit -q
}

function Persistence-Check {
    .\venv\Scripts\python.exe tests\integration\check_persistence.py
}

switch ($Action.ToLower()) {
    'envfile' { Write-EnvFile }
    'install-ollama' { Install-Ollama }
    'docker-up' { Docker-Up }
    'docker-down' { Docker-Down }
    'build-litellm' { Build-LiteLLM }
    'migrate' { Migrate }
    'start-api' { Start-API }
    'start-all' { Start-All }
    'test' { Test-Unit }
    'persistence-check' { Persistence-Check }
    default {
        Write-Host "Usage: dev.ps1 -Action <envfile|install-ollama|docker-up|docker-down|build-litellm|migrate|start-api|start-all|test|persistence-check>"
    }
}
