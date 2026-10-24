"""Knowledge upload use cases: validate cheaply, persist durably, index in the worker.

Validation is intentionally in the request; recognition and embedding are not. A recruiter gets a
fast, honest ``queued`` answer instead of an HTTP request that holds a database transaction open
across a model call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from onboarding.app.jobs import EXTRACT_DOCUMENT, INDEX_DOCUMENT
from onboarding.app.knowledge.extract.media import SUPPORTED, media_type_for
from onboarding.app.knowledge.ingest import (
    CorpusError,
    LoadedDocument,
    parse_document,
    validate_frontmatter,
)
from onboarding.app.knowledge.markdown import MARKDOWN_MEDIA_TYPE, MARKDOWN_PROFILE_HASH
from onboarding.ports import AuditLog, KnowledgeSubmission, KnowledgeSubmitter


class KnowledgeRejectedError(ValueError):
    """The upload is not accepted; the reason is safe to show to the recruiter."""


class UnsupportedMediaError(KnowledgeRejectedError):
    """The upload is not a format a reader owns."""


class UploadTooLargeError(KnowledgeRejectedError):
    """The upload exceeds the configured limit."""


class SubmitKnowledge:
    def __init__(
        self,
        *,
        submitter: KnowledgeSubmitter,
        schema: Mapping[str, Any],
        audit: AuditLog,
    ) -> None:
        self._submitter = submitter
        self._schema = dict(schema)
        self._audit = audit

    async def markdown(
        self,
        text: str,
        *,
        actor: str,
        expected_id: str | None = None,
    ) -> KnowledgeSubmission:
        loaded = self._document(text, source="upload")
        if expected_id is not None and str(loaded.document.id) != expected_id:
            raise KnowledgeRejectedError(
                "upload: frontmatter id is "
                f"{str(loaded.document.id)!r}, expected {expected_id!r}"
            )
        submission = await self._submitter.submit(
            content=text.encode("utf-8"),
            filename=f"{str(loaded.document.id).replace('/', '_')}.md",
            media_type=MARKDOWN_MEDIA_TYPE,
            metadata=_document_metadata(loaded),
            job_kind=INDEX_DOCUMENT,
            profile_hash=MARKDOWN_PROFILE_HASH,
        )
        await self._audit.record(
            "knowledge_updated" if expected_id is not None else "knowledge_queued",
            document=str(loaded.document.id),
            title=loaded.document.title,
            by=actor,
            duplicate=not submission.queued,
        )
        return submission

    async def file(
        self,
        *,
        content: bytes,
        filename: str,
        declared_media_type: str | None,
        raw_metadata: str,
        actor: str,
        profile_hash: str,
        max_bytes: int,
    ) -> KnowledgeSubmission:
        if not content:
            raise KnowledgeRejectedError("empty upload")
        if len(content) > max_bytes:
            raise UploadTooLargeError(f"upload exceeds {max_bytes} bytes")
        media_type = media_type_for(filename, declared_media_type)
        if media_type not in SUPPORTED:
            raise UnsupportedMediaError("supported formats: PDF, PPTX")
        metadata = self._metadata(raw_metadata)

        submission = await self._submitter.submit(
            content=content,
            filename=filename or "upload",
            media_type=media_type,
            metadata=metadata,
            job_kind=EXTRACT_DOCUMENT,
            profile_hash=profile_hash,
        )
        await self._audit.record(
            "knowledge_file_queued",
            blob=submission.content_hash,
            media_type=media_type,
            by=actor,
            duplicate=not submission.queued,
        )
        return submission

    def _document(self, text: str, *, source: str) -> LoadedDocument:
        try:
            loaded = parse_document(text, self._schema, source=source)
        except CorpusError as error:
            raise KnowledgeRejectedError(str(error)) from None
        if loaded.status != "active":
            raise KnowledgeRejectedError(
                f"{source}: document status is {loaded.status!r}, not 'active'"
            )
        return loaded

    def _metadata(self, raw: str) -> dict[str, Any]:
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as error:
            raise KnowledgeRejectedError(f"metadata is not valid JSON: {error}") from None
        try:
            return dict(validate_frontmatter(parsed, self._schema, source="upload"))
        except CorpusError as error:
            raise KnowledgeRejectedError(str(error)) from None


def _document_metadata(loaded: LoadedDocument) -> dict[str, object]:
    document = loaded.document
    return {
        "id": str(document.id),
        "title": document.title,
        "type": loaded.doc_type,
        "status": loaded.status,
        "owner": document.owner,
        "audience": list(document.audience),
        "valid_from": document.valid_from.isoformat(),
        "valid_to": document.valid_to.isoformat() if document.valid_to else None,
    }
