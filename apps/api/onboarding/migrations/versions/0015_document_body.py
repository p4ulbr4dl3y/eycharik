"""The cabinet can read and edit the markdown it indexed.

Until now a document existed only as metadata plus chunks: enough to answer, not enough to show or
edit. ``kb_documents.body`` keeps the exact source markdown, frontmatter included, so an HR admin
opens the same document they uploaded and saves a new version.

The column is nullable on purpose. Rows indexed before this revision have no copy of their source;
a re-index fills it, and the cabinet reports "unavailable" rather than inventing text from chunks.
The baseline is derived from ``Base.metadata``, so a fresh database already has the column and this
upgrade is idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_document_body"
down_revision: str | None = "0014_channel_address"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {str(column["name"]) for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "body" not in _columns("kb_documents"):
        op.add_column("kb_documents", sa.Column("body", sa.Text(), nullable=True))


def downgrade() -> None:
    if "body" in _columns("kb_documents"):
        op.drop_column("kb_documents", "body")
