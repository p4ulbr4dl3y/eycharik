"""Tables.

State, queue, outbox, audit and knowledge live in one Postgres so a single transaction can keep
them consistent. Knowledge tables are declared here too: their migrations are part of the same
schema.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Frozen on purpose: the column type and the HNSW index need a fixed width. Changing the
# embedding model means a migration, not a config flip.
EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


class EmployeeRow(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(200))
    recruiter_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[date] = mapped_column(Date)
    audience: Mapped[list[str]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    scenario_id: Mapped[str] = mapped_column(
        String(64), server_default=sql_text("'onboarding_default'")
    )
    status: Mapped[str] = mapped_column(String(16), server_default=sql_text("'active'"))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("employees_recruiter_idx", "recruiter_id"),
        Index("employees_status_idx", "status"),
    )


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    scenario_id: Mapped[str] = mapped_column(String(64))
    scenario_version: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String(64))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_action: Mapped[str | None] = mapped_column(String(16))
    answers: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    question_index: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    pending_reason: Mapped[str | None] = mapped_column(String(64))
    tone: Mapped[str] = mapped_column(String(16), server_default=sql_text("'formal'"))
    channel: Mapped[str] = mapped_column(String(16), server_default=sql_text("'max'"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), server_default=sql_text("'active'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "runs_employee_active_idx",
            "employee_id",
            unique=True,
            postgresql_where=sql_text("status = 'active'"),
        ),
        Index("runs_reminder_idx", "reminder_at", postgresql_where=sql_text("status = 'active'")),
        Index("runs_status_idx", "status"),
    )


class ChannelIdentityRow(Base):
    """One sender on one messenger, linked to one employee.

    The link is the access gate: an unlinked sender gets no run. It is also what makes a person one
    employee across several messengers instead of one per app (ADR 0019).
    """

    __tablename__ = "channel_identities"

    channel: Mapped[str] = mapped_column(String(16), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("channel_identities_employee_idx", "employee_id"),)


class EventRow(Base):
    """Webhook deduplication: the primary key is the guarantee, not the application code."""

    __tablename__ = "events"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default=sql_text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("jobs_claim_idx", "status", "available_at"),)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(16), server_default=sql_text("'max'"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    image: Mapped[str | None] = mapped_column(String(80))
    keyboard: Mapped[list[list[dict[str, str]]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), server_default=sql_text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    external_id: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("messages_dispatch_idx", "status", "available_at"),)


class QuestionRow(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    employee_id: Mapped[str | None] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16), server_default=sql_text("'max'"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    answered: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(32))
    citations: Mapped[list[str]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(200))
    resolution: Mapped[str | None] = mapped_column(Text)
    # Who picked this up. Null means nobody has; the queue is shared, the work is not.
    assignee: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        Index("questions_asked_idx", "asked_at"),
        Index("questions_answered_idx", "answered", "asked_at"),
        Index("questions_assignee_idx", "assignee", "answered", "asked_at"),
    )


class AuditRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    fields: Mapped[dict[str, object]] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("audit_name_at_idx", "name", "at"),)


class IndexStateRow(Base):
    """Which embedder built the vector index. One row, id ``active``.

    A model swap without a reindex is silent corruption: the vectors are still 1024 wide, so every
    query succeeds and every answer is wrong. Recording the identity turns that into a startup-time
    failure with a sentence a human can act on.
    """

    __tablename__ = "kb_index_state"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    embedder: Mapped[str] = mapped_column(String(120))
    dim: Mapped[int] = mapped_column(Integer)
    chunks: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentRow(Base):
    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    owner: Mapped[str] = mapped_column(String(200))
    audience: Mapped[list[str]] = mapped_column(JSONB)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    checksum: Mapped[str] = mapped_column(String(64))
    # The exact markdown the index was built from, frontmatter included. It is nullable because
    # rows indexed before 0015 have no copy; a re-index fills it, and the cabinet says "unavailable"
    # instead of pretending an editable document exists.
    body: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChunkRow(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[str] = mapped_column(String(220), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # Generated at ingest by the contextual-retrieval pass (ADR 0016). Empty on a corpus indexed
    # without it, which keeps the column additive and the migration cheap.
    context: Mapped[str] = mapped_column(Text, server_default=sql_text("''"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    ts: Mapped[str | None] = mapped_column(TSVECTOR)

    __table_args__ = (
        UniqueConstraint("doc_id", "index"),
        Index("kb_chunks_doc_idx", "doc_id"),
        Index("kb_chunks_ts_idx", "ts", postgresql_using="gin"),
        Index(
            "kb_chunks_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class FileRow(Base):
    """An uploaded file, addressed by the hash of its bytes.

    Content addressing is the idempotency rule of the whole ingestion path: the same bytes uploaded
    twice occupy one row, produce one job, and cost one recognition.
    """

    __tablename__ = "kb_files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    media_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExtractionRow(Base):
    """The cached outcome of one (file, extraction profile) pair.

    Recognising a scan is seconds of CPU, and the result is deterministic for a given profile, so it
    is cached by the pair of hashes. A new profile re-reads the file instead of trusting a result
    produced by a different one. Refusals are cached too: a recruiter must be able to read why.
    """

    __tablename__ = "kb_extractions"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(32))
    engine: Mapped[str] = mapped_column(String(32))
    route: Mapped[str] = mapped_column(String(16))
    pages: Mapped[int] = mapped_column(Integer)
    min_confidence: Mapped[float] = mapped_column(Float)
    markdown: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
