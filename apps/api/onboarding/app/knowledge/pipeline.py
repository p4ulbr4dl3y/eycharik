"""Indexing: corpus files in, embedded chunks out.

The pipeline is idempotent per document: replacing a document deletes its old chunks in the same
transaction, so a re-run after an edit never leaves two versions retrievable at once.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from onboarding.app.knowledge.ingest import (
    LoadedDocument,
    load_corpus,
    load_schema,
    parse_document,
)
from onboarding.core.chunking import split_document
from onboarding.core.models import Chunk, Document
from onboarding.ports import (
    Contextualizer,
    Embedder,
    KnowledgeDocumentRecord,
    KnowledgeWriter,
)


@dataclass(frozen=True, slots=True)
class IngestReport:
    documents: int
    chunks: int
    contextualized: int = 0


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    id: str
    title: str
    chunks: int


async def ingest(
    *,
    directory: Path,
    schema_path: Path,
    writer: KnowledgeWriter,
    embedder: Embedder,
    max_chars: int = 1200,
    overlap_chars: int = 200,
    contextualizer: Contextualizer | None = None,
) -> IngestReport:
    loaded = load_corpus(directory, schema_path)
    chunks = 0
    contextualized = 0
    for item in loaded:
        pieces = split_document(item.document, max_chars=max_chars, overlap_chars=overlap_chars)
        if not pieces:
            raise ValueError(f"{item.path}: document produced no chunks")
        if contextualizer is not None:
            pieces = await _with_context(contextualizer, item.document, pieces)
            contextualized += len(pieces)
        embeddings = await embedder.embed([piece.embedding_text for piece in pieces])
        if len(embeddings) != len(pieces):
            raise ValueError(f"{item.path}: embedder returned a wrong number of vectors")
        await writer.replace_document(
            KnowledgeDocumentRecord(
                id=item.document.id,
                title=item.document.title,
                doc_type=item.doc_type,
                status=item.status,
                audience=item.document.audience,
                valid_from=item.document.valid_from,
                valid_to=item.document.valid_to,
                owner=item.document.owner,
                checksum=item.checksum,
                body=item.text,
            ),
            pieces,
            embeddings,
        )
        chunks += len(pieces)
    return IngestReport(documents=len(loaded), chunks=chunks, contextualized=contextualized)


async def ingest_document(
    *,
    text: str,
    source: str,
    schema_path: Path,
    writer: KnowledgeWriter,
    embedder: Embedder,
    max_chars: int = 1200,
    overlap_chars: int = 200,
    contextualizer: Contextualizer | None = None,
) -> IndexedDocument:
    """Index one uploaded document. Raises ``CorpusError`` when its frontmatter is invalid."""
    loaded = parse_document(text, load_schema(schema_path), source=source)
    if loaded.status != "active":
        raise ValueError(f"{source}: document status is {loaded.status!r}, not 'active'")
    chunks = await _chunks(
        loaded,
        writer=writer,
        embedder=embedder,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        contextualizer=contextualizer,
    )
    return IndexedDocument(id=str(loaded.document.id), title=loaded.document.title, chunks=chunks)


async def _chunks(
    loaded: LoadedDocument,
    *,
    writer: KnowledgeWriter,
    embedder: Embedder,
    max_chars: int,
    overlap_chars: int,
    contextualizer: Contextualizer | None = None,
) -> int:
    pieces = split_document(loaded.document, max_chars=max_chars, overlap_chars=overlap_chars)
    if not pieces:
        raise ValueError(f"{loaded.path}: document produced no chunks")
    if contextualizer is not None:
        pieces = await _with_context(contextualizer, loaded.document, pieces)
    embeddings = await embedder.embed([piece.embedding_text for piece in pieces])
    if len(embeddings) != len(pieces):
        raise ValueError(f"{loaded.path}: embedder returned a wrong number of vectors")
    await writer.replace_document(
        KnowledgeDocumentRecord(
            id=loaded.document.id,
            title=loaded.document.title,
            doc_type=loaded.doc_type,
            status=loaded.status,
            audience=loaded.document.audience,
            valid_from=loaded.document.valid_from,
            valid_to=loaded.document.valid_to,
            owner=loaded.document.owner,
            checksum=loaded.checksum,
            body=loaded.text,
        ),
        pieces,
        embeddings,
    )
    return len(pieces)


async def _with_context(
    contextualizer: Contextualizer, document: Document, pieces: tuple[Chunk, ...]
) -> tuple[Chunk, ...]:
    """One model call per chunk. Sequential on purpose: an ingest is not a latency race."""
    out: list[Chunk] = []
    for piece in pieces:
        context = await contextualizer.context_for(document, piece)
        out.append(replace(piece, context=context))
    return tuple(out)
