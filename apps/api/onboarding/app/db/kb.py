"""Postgres knowledge base: vector search, lexical search, reciprocal rank fusion.

ACL and validity are SQL predicates in both branches, so a forbidden chunk can never reach the
ranker or the prompt.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, Text, cast, delete, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from onboarding.app.db.models import EMBEDDING_DIM, ChunkRow, DocumentRow, IndexStateRow
from onboarding.app.db.session import Database
from onboarding.core.models import Chunk, ChunkId, DocId, ScoredChunk
from onboarding.core.ranking import reciprocal_rank_fusion
from onboarding.ports import (
    Embedder,
    KnowledgeDocumentRecord,
    KnowledgeUnavailableError,
    SearchQuery,
)

log = logging.getLogger(__name__)

OVERFETCH = 40


class PostgresKnowledgeBase:
    def __init__(
        self,
        database: Database,
        embedder: Embedder,
        *,
        overfetch: int = OVERFETCH,
        bm25: bool = False,
    ) -> None:
        self._database = database
        self._embedder = embedder
        self._overfetch = overfetch
        # An experiment switch, not a feature flag: ADR 0012 keeps BM25 out of the request path
        # until a measurement on a larger corpus says otherwise.
        self._bm25_enabled = bm25
        self._bm25_available: bool | None = None
        self._index_checked = False

    async def search(self, query: SearchQuery) -> tuple[ScoredChunk, ...]:
        if not query.text.strip():
            return ()
        try:
            vector = list((await self._embedder.embed((query.text,)))[0])
        except Exception as error:
            raise KnowledgeUnavailableError(f"embedding failed: {error}") from error
        async with self._database.session() as session:
            await self._check_index(session)
            if self._bm25_enabled and self._bm25_available is None:
                self._bm25_available = await _has_bm25(session)
                if not self._bm25_available:
                    # Enabled but unavailable is a configuration mistake, not a runtime failure:
                    # the two-list fusion is still correct, so the turn must not fail.
                    log.warning("bm25_enabled_but_pg_search_is_missing")
            semantic = await _semantic_ids(session, query, vector, self._overfetch)
            lexical = await _lexical_ids(session, query, self._overfetch)
            rankings = [semantic, lexical]
            if self._bm25_enabled and self._bm25_available:
                rankings.append(await _bm25_ids(session, query, self._overfetch))
            fused = reciprocal_rank_fusion(rankings, limit=query.limit)
            if not fused:
                return ()
            rows = {
                row.id: row
                for row in await session.scalars(
                    select(ChunkRow).where(ChunkRow.id.in_([cid for cid, _ in fused]))
                )
            }
        return tuple(
            ScoredChunk(chunk=_chunk(rows[chunk_id]), score=score)
            for chunk_id, score in fused
            if chunk_id in rows
        )


    async def _check_index(self, session: AsyncSession) -> None:
        """Refuse to search vectors that another model produced.

        The first search pays for one row read; later searches on the same instance are free. A
        table without a row is a pre-0012 index and is accepted as-is, because failing there would
        break every existing deployment on upgrade.
        """
        if self._index_checked:
            return
        self._index_checked = True
        state = await session.get(IndexStateRow, "active")
        if state is None:
            return
        current = getattr(self._embedder, "fingerprint", "")
        if current and state.embedder != current:
            raise KnowledgeUnavailableError(
                f"knowledge index was built with {state.embedder!r}, this process embeds with "
                f"{current!r}; reindex before serving answers"
            )


class PostgresKnowledgeWriter:
    def __init__(self, database: Database, embedder: object | None = None) -> None:
        self._database = database
        self._fingerprint = getattr(embedder, "fingerprint", "")
        self._dim = getattr(embedder, "dim", 0)

    async def replace_document(
        self,
        record: KnowledgeDocumentRecord,
        chunks: tuple[Chunk, ...],
        embeddings: tuple[tuple[float, ...], ...],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        async with self._database.session() as session:
            await session.execute(
                insert(DocumentRow)
                .values(
                    id=str(record.id),
                    title=record.title,
                    type=record.doc_type,
                    status=record.status,
                    owner=record.owner,
                    audience=list(record.audience),
                    valid_from=record.valid_from,
                    valid_to=record.valid_to,
                    checksum=record.checksum,
                    body=record.body,
                    updated_at=func.now(),
                )
                .on_conflict_do_update(
                    index_elements=[DocumentRow.id],
                    set_={
                        "title": record.title,
                        "type": record.doc_type,
                        "status": record.status,
                        "owner": record.owner,
                        "audience": list(record.audience),
                        "valid_from": record.valid_from,
                        "valid_to": record.valid_to,
                        "checksum": record.checksum,
                        "body": record.body,
                        "updated_at": func.now(),
                    },
                )
            )
            if self._fingerprint:
                await session.execute(
                    insert(IndexStateRow)
                    .values(id="active", embedder=self._fingerprint, dim=self._dim, chunks=0)
                    .on_conflict_do_update(
                        index_elements=[IndexStateRow.id],
                        set_={"embedder": self._fingerprint, "dim": self._dim},
                    )
                )
            await session.execute(delete(ChunkRow).where(ChunkRow.doc_id == str(record.id)))
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                await session.execute(
                    insert(ChunkRow).values(
                        id=str(chunk.id),
                        doc_id=str(chunk.doc_id),
                        index=chunk.index,
                        text=chunk.text,
                        context=chunk.context,
                        embedding=list(embedding),
                        ts=func.to_tsvector("russian", chunk.embedding_text),
                    )
                )


async def _semantic_ids(
    session: AsyncSession,
    query: SearchQuery,
    vector: Sequence[float],
    limit: int,
) -> tuple[ChunkId, ...]:
    rows = await session.scalars(
        _filtered(query)
        .with_only_columns(ChunkRow.id)
        .order_by(ChunkRow.embedding.cosine_distance(list(vector)))
        .limit(limit)
    )
    return tuple(ChunkId(row) for row in rows)


async def _has_bm25(session: AsyncSession) -> bool:
    """ParadeDB is optional; a plain-Postgres deployment keeps the two-list fusion."""
    found = await session.scalar(
        text("SELECT count(*) FROM pg_extension WHERE extname = 'pg_search'")
    )
    return bool(found)


async def _bm25_ids(
    session: AsyncSession, query: SearchQuery, limit: int
) -> tuple[ChunkId, ...]:
    score = func.pdb.score(ChunkRow.id).label("score")
    rows = await session.execute(
        _filtered(query)
        .with_only_columns(ChunkRow.id, score)
        .where(ChunkRow.text.op("@@@")(query.text))
        .order_by(score.desc())
        .limit(limit)
    )
    return tuple(ChunkId(row.id) for row in rows)


async def _lexical_ids(
    session: AsyncSession, query: SearchQuery, limit: int
) -> tuple[ChunkId, ...]:
    ts_query = func.plainto_tsquery("russian", query.text)
    rank = func.ts_rank_cd(ChunkRow.ts, ts_query)
    rows = await session.scalars(
        _filtered(query)
        .with_only_columns(ChunkRow.id)
        .where(ChunkRow.ts.op("@@")(ts_query))
        .order_by(rank.desc())
        .limit(limit)
    )
    return tuple(ChunkId(row) for row in rows)


def _filters(query: SearchQuery) -> tuple[ColumnElement[bool], ...]:
    return (
        DocumentRow.status == "active",
        DocumentRow.audience.op("?|")(cast(list(query.audience), ARRAY(Text))),
        (DocumentRow.valid_from.is_(None)) | (DocumentRow.valid_from <= query.on_date),
        (DocumentRow.valid_to.is_(None)) | (DocumentRow.valid_to >= query.on_date),
    )


def _filtered(query: SearchQuery) -> Select[ChunkRow]:
    return (
        select(ChunkRow)
        .join(DocumentRow, DocumentRow.id == ChunkRow.doc_id)
        .where(*_filters(query))
    )


def _chunk(row: ChunkRow) -> Chunk:
    return Chunk(
        id=ChunkId(row.id),
        doc_id=DocId(row.doc_id),
        index=row.index,
        text=row.text,
        context=row.context or "",
    )


def assert_embedding_width(dim: int) -> None:
    if dim != EMBEDDING_DIM:
        raise ValueError(
            f"EMBED_DIM is {dim}, but the kb_chunks.embedding column is vector({EMBEDDING_DIM}); "
            "changing it requires a migration"
        )
