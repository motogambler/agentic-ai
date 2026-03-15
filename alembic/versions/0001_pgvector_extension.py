"""create pgvector extension and ANN index

Revision ID: 0001
Revises: 
Create Date: 2026-03-13 00:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Ensure the vector extension is available. Requires superuser privileges in many setups.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Create an IVFFlat index for the memories.embedding column. Adjust method/params for your workload.
    # Note: Creating ivfflat index requires the table to be populated and an appropriate operator class.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'idx_memories_embedding') THEN
                EXECUTE 'CREATE INDEX idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists=100)';
            END IF;
        END$$;
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_memories_embedding;")
    op.execute("DROP EXTENSION IF EXISTS vector;")
