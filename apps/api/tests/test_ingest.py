from __future__ import annotations

import json
from pathlib import Path

import pytest

from onboarding.app.knowledge.ingest import CorpusError, load_corpus, read_document

ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE = ROOT / "knowledge"
SCHEMA = ROOT / "docs" / "contracts" / "doc.schema.json"


def test_the_repository_corpus_is_valid() -> None:
    loaded = load_corpus(KNOWLEDGE, SCHEMA)

    ids = {item.document.id for item in loaded}
    assert "hr/leave-policy" in ids
    assert "it/access-and-equipment" in ids
    assert all(item.status == "active" for item in loaded)


def test_every_document_has_an_owner_and_audience() -> None:
    for item in load_corpus(KNOWLEDGE, SCHEMA):
        assert item.document.owner
        assert item.document.audience


def test_a_loaded_document_keeps_the_source_markdown() -> None:
    item = load_corpus(KNOWLEDGE, SCHEMA)[0]

    assert item.text.startswith("---\n")
    assert item.document.text in item.text


def test_missing_frontmatter_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Без фронтматтера\n", encoding="utf-8")
    schema = SCHEMA

    with pytest.raises(CorpusError, match="frontmatter"):
        read_document(path, _schema(schema))


def test_invalid_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(
        "---\n"
        "id: hr/bad\n"
        "title: Bad\n"
        "type: knowledge\n"
        "status: active\n"
        "owner: hr-team\n"
        "audience: [everyone]\n"
        "valid_from: 2026-01-01\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="audience"):
        read_document(path, _schema(SCHEMA))


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text(
            "---\n"
            "id: hr/duplicate\n"
            "title: Duplicate\n"
            "type: knowledge\n"
            "status: active\n"
            "owner: hr-team\n"
            "audience: [all]\n"
            "valid_from: 2026-01-01\n"
            "---\n\nbody\n",
            encoding="utf-8",
        )

    with pytest.raises(CorpusError, match="duplicate"):
        load_corpus(tmp_path, SCHEMA)


def test_draft_documents_are_not_indexed(tmp_path: Path) -> None:
    (tmp_path / "draft.md").write_text(
        "---\n"
        "id: hr/draft\n"
        "title: Draft\n"
        "type: knowledge\n"
        "status: draft\n"
        "owner: hr-team\n"
        "audience: [all]\n"
        "valid_from: 2026-01-01\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="no active"):
        load_corpus(tmp_path, SCHEMA)


def _schema(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
