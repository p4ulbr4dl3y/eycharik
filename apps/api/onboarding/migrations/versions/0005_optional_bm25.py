"""Add a BM25 index when ParadeDB is available.

The base image is plain Postgres, so the extension is optional: migrations stay runnable there.
On a ParadeDB image the index is created and the knowledge base adds BM25 as a third ranking list.
The Russian stemmer keeps the index aligned with the tsvector branch instead of comparing raw
word forms.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_optional_bm25"
down_revision: str | None = "0004_run_tone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _available() -> bool:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_search'")
    )
    return exists.scalar() is not None


def upgrade() -> None:
    if not _available():
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
    op.execute(
        "CREATE INDEX kb_chunks_bm25_idx ON kb_chunks "
        "USING paradedb (id, (text::pdb.simple('stemmer=russian'))) "
        "WITH (key_field='id')"
    )


def downgrade() -> None:
    if not _available():
        return
    op.execute("DROP INDEX IF EXISTS kb_chunks_bm25_idx")
