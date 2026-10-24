"""The upload use case decides before anything expensive happens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from onboarding.app.knowledge.ingest import load_schema
from onboarding.app.use_cases.knowledge import (
    KnowledgeRejectedError,
    SubmitKnowledge,
    UnsupportedMediaError,
)
from onboarding.ports import KnowledgeSubmission

DOC = "docs"
FRONTMATTER = """---
id: hr/new-policy
title: Новая политика
type: knowledge
status: active
owner: hr
audience: [all]
valid_from: 2026-10-01
---

## Раздел

Текст документа, достаточно длинный для проверки схемы.
"""


class RecordingSubmitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def submit(self, **kwargs: Any) -> KnowledgeSubmission:
        self.calls.append(kwargs)
        return KnowledgeSubmission(content_hash="abc", queued=True)


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def record(self, name: str, **fields: Any) -> None:
        self.events.append((name, fields))


def service() -> tuple[SubmitKnowledge, RecordingSubmitter, RecordingAudit]:
    submitter = RecordingSubmitter()
    audit = RecordingAudit()
    root = Path(__file__).resolve().parents[3]
    return (
        SubmitKnowledge(
            submitter=submitter,
            schema=load_schema(root / DOC / "contracts" / "doc.schema.json"),
            audit=audit,
        ),
        submitter,
        audit,
    )


async def test_markdown_queues_instead_of_indexing_in_the_request() -> None:
    use_case, submitter, audit = service()

    result = await use_case.markdown(FRONTMATTER, actor="hr@example.com")

    assert result.queued is True
    call = submitter.calls[0]
    assert call["job_kind"] == "index_document"
    assert call["profile_hash"] == "markdown:v1"
    assert call["metadata"]["id"] == "hr/new-policy"
    assert audit.events[0][0] == "knowledge_queued"


async def test_a_document_without_frontmatter_is_refused_before_the_queue() -> None:
    use_case, submitter, _ = service()

    with pytest.raises(KnowledgeRejectedError):
        await use_case.markdown("# just a heading", actor="hr@example.com")
    assert submitter.calls == []


async def test_an_edit_must_keep_the_document_id() -> None:
    use_case, submitter, _ = service()

    with pytest.raises(KnowledgeRejectedError, match="expected"):
        await use_case.markdown(FRONTMATTER, actor="hr@example.com", expected_id="hr/other")
    assert submitter.calls == []


async def test_an_edit_is_audited_as_an_update() -> None:
    use_case, submitter, audit = service()

    await use_case.markdown(FRONTMATTER, actor="hr@example.com", expected_id="hr/new-policy")

    assert submitter.calls[0]["metadata"]["id"] == "hr/new-policy"
    assert audit.events[0][0] == "knowledge_updated"


async def test_a_non_active_document_is_refused() -> None:
    use_case, submitter, _ = service()

    with pytest.raises(KnowledgeRejectedError, match="status"):
        await use_case.markdown(FRONTMATTER.replace("status: active", "status: draft"), actor="hr")
    assert submitter.calls == []


async def test_a_file_format_no_reader_owns_is_refused() -> None:
    use_case, submitter, _ = service()

    with pytest.raises(UnsupportedMediaError):
        await use_case.file(
            content=b"x",
            filename="deck.docx",
            declared_media_type=None,
            raw_metadata=json.dumps(
                {
                    "id": "hr/new-policy",
                    "title": "Новая политика",
                    "type": "knowledge",
                    "status": "active",
                    "owner": "hr",
                    "audience": ["all"],
                    "valid_from": "2026-10-01",
                }
            ),
            actor="hr",
            profile_hash="native",
            max_bytes=100,
        )
    assert submitter.calls == []
