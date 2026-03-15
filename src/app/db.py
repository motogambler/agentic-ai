from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings
from sqlalchemy import text

engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def init_db():
    # Create extension and tables. In production use alembic for migrations.
    try:
        async with engine.begin() as conn:
            # Ensure pgvector extension is available
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception:
                # ignore if running on DB without extension privileges; table creation may still succeed
                pass

            # Create tables
            await conn.run_sync(Base.metadata.create_all)

            # Attempt to create an ANN index for the memories.embedding column (best-effort).
            # This may fail depending on Postgres version or permissions; ignore failures.
            try:
                # Example using ivfflat; adjust parameters for your workload.
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS memories_embedding_idx ON memories USING ivfflat (embedding) WITH (lists = 100)"
                    )
                )
            except Exception:
                try:
                    # Try HNSW as a fallback
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS memories_embedding_idx ON memories USING hnsw (embedding)"
                        )
                    )
                except Exception:
                    # ignore index creation errors
                    pass
    except Exception as e:
        # If DB is not available (e.g., Docker not running), log and continue so the app can start.
        import logging

        logging.warning(f"init_db skipped: could not connect to database: {e}")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
