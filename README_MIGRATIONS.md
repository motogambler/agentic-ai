Alembic migration notes

- The migration in `alembic/versions/0001_pgvector_extension.py` enables the `vector` extension
  and creates an IVFFlat index for the `memories.embedding` column.
- Creating the `vector` extension and some index types typically requires superuser privileges.

How to run:

1. Ensure `DATABASE_URL` env var points to your Postgres instance (example below):

   DATABASE_URL=postgresql+asyncpg://agent:agentpass@localhost:5432/agentdb

2. From the repo root, run Alembic (you may need to install alembic in your venv):

   pip install alembic
   alembic -c alembic.ini upgrade head

If you cannot run the migration as a DB superuser, run the SQL statements manually as an admin:

   CREATE EXTENSION IF NOT EXISTS vector;
   -- then create the preferred index after loading data
