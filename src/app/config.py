from pydantic_settings import BaseSettings
from pydantic import ConfigDict
import os


class Settings(BaseSettings):
    # Load from .env and ignore any extra env vars to avoid validation errors
    model_config = ConfigDict(env_file='.env', extra='ignore')

    # Primary: allow user to set `DATABASE_URL` directly. Secondary: build from
    # POSTGRES_* env vars to support docker-compose service names or localhost mapping.
    database_url: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None
    postgres_port: int | None = None

    def __init__(self, **values):
        super().__init__(**values)
        if not self.database_url:
            user = self.postgres_user or os.getenv('POSTGRES_USER') or 'agent'
            pwd = self.postgres_password or os.getenv('POSTGRES_PASSWORD') or 'agentpass'
            db = self.postgres_db or os.getenv('POSTGRES_DB') or 'agentdb'
            port = self.postgres_port or int(os.getenv('POSTGRES_PORT') or 5432)
            host = os.getenv('POSTGRES_HOST') or os.getenv('DB_HOST') or os.getenv('HOST') or 'localhost'
            # default host 'localhost' works when docker compose maps port 5432 to host
            self.database_url = f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{db}"

    # Optional OpenAI API key (loaded from .env if present)
    openai_api_key: str | None = None


settings = Settings()
