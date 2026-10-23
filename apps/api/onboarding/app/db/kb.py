"""Postgres knowledge base: vector search, lexical search, reciprocal rank fusion.

ACL and validity are SQL predicates in both branches, so a forbidden chunk can never reach the
ranker or the prompt.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, Text, cast, delete, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from onboarding.app.db.models import EMBEDDING_DIM, ChunkRow, DocumentRow
from onboarding.app.db.session import Database
from onboarding.core.models import Chunk, ChunkId, DocId, ScoredChunk
from onboarding.core.ranking import reciprocal_rank_fusion
from onboarding.ports import (
    Embedder,
    KnowledgeDocumentRecord,
    KnowledgeUnavailableError,
    SearchQuery,
)

OVERFETCH = 40


class PostgresKnowledgeBase:
    def __init__(
        self,
        database: Database,
        embedder: Embedder,
        *,
        overfetch: int = OVERFETCH,
    ) -> None:
        self._database = database
        self._embedder = embedder
        self._overfetch = overfetch
        self._bm25: bool | None = None

    async def search(self, query: SearchQuery) -> tuple[ScoredChunk, ...]:
        if not query.text.strip():
            return ()
        try:
            vector = list((await self._embedder.embed((query.text,)))[0])
        except Exception as error:
            raise KnowledgeUnavailableError(f"embedding failed: {error}") from error
        async with self._database.session() as session:
            if self._bm25 is None:
                self._bm25 = await _has_bm25(session)
            semantic = await _semantic_ids(session, query, vector, self._overfetch)
            lexical = await _lexical_ids(session, query, self._overfetch)
            rankings = [semantic, lexical]
            if self._bm25:
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


class PostgresKnowledgeWriter:
    def __init__(self, database: Database) -> None:
        self._database = database

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
                    },
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
                        embedding=list(embedding),
                        ts=func.to_tsvector("russian", chunk.text),
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
    """ParadeDB is optional; the plain-Postgres deployment keeps the two-list fusion."""
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
    )


def assert_embedding_width(dim: int) -> None:
    if dim != EMBEDDING_DIM:
        raise ValueError(
            f"EMBED_DIM is {dim}, but the kb_chunks.embedding column is vector({EMBEDDING_DIM}); "
            "changing it requires a migration"
        )
