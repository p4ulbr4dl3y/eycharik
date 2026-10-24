"""Read the knowledge corpus: frontmatter, schema validation, documents.

One invalid file fails the whole batch. A half-indexed corpus produces answers that look right and
are not, which is the failure mode this pipeline exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from onboarding.core.models import DocId, Document

_FRONTMATTER = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)
_META_DIR = "_meta"


class _TextDatesLoader(yaml.SafeLoader):
    """Keep ISO dates as strings so the schema validates the file as written."""


_TextDatesLoader.yaml_implicit_resolvers = {
    first: [item for item in resolvers if item[0] != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class CorpusError(ValueError):
    """The corpus violates the document contract."""


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    document: Document
    doc_type: str
    checksum: str
    status: str
    path: Path
    # The source markdown, frontmatter included. The index only needs the body, but the cabinet
    # edits the whole document, so the raw text is kept alongside the metadata.
    text: str = ""


def load_corpus(directory: Path, schema_path: Path) -> tuple[LoadedDocument, ...]:
    """Load every active document, validating each against ``doc.schema.json``."""
    schema = load_schema(schema_path)
    paths = sorted(
        path
        for path in directory.rglob("*.md")
        if _META_DIR not in path.relative_to(directory).parts
    )
    if not paths:
        raise CorpusError(f"{directory}: no knowledge documents found")

    loaded: list[LoadedDocument] = []
    seen: dict[str, Path] = {}
    for path in paths:
        item = read_document(path, schema)
        if item.status != "active":
            continue
        if item.document.id in seen:
            raise CorpusError(
                f"duplicate document id {item.document.id!r}: {seen[item.document.id]} and {path}"
            )
        seen[item.document.id] = path
        loaded.append(item)

    if not loaded:
        raise CorpusError(f"{directory}: no active knowledge documents")
    return tuple(loaded)


def read_document(path: Path, schema: dict[str, Any]) -> LoadedDocument:
    return parse_document(path.read_text(encoding="utf-8"), schema, source=str(path))


def validate_frontmatter(
    meta: Any, schema: dict[str, Any], *, source: str
) -> dict[str, Any]:
    """Check one metadata mapping against ``doc.schema.json``.

    Shared by the corpus directory, an uploaded markdown document, and the metadata of an uploaded
    file: an upload is validated exactly like a file that was committed.
    """
    if not isinstance(meta, dict):
        raise CorpusError(f"{source}: frontmatter must be a mapping")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(meta),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise CorpusError(f"{source}: {location}: {first.message}")
    return meta


def parse_document(text: str, schema: dict[str, Any], *, source: str) -> LoadedDocument:
    """Validate one document, whether it came from the corpus directory or an upload."""
    match = _FRONTMATTER.match(text)
    if match is None:
        raise CorpusError(f"{source}: missing YAML frontmatter")
    try:
        # SafeLoader subclass with the timestamp resolver removed; no arbitrary objects.
        meta = yaml.load(match.group("meta"), Loader=_TextDatesLoader)  # noqa: S506
    except yaml.YAMLError as error:
        raise CorpusError(f"{source}: invalid frontmatter: {error}") from None
    meta = validate_frontmatter(meta, schema, source=source)

    body = match.group("body").strip()
    if not body:
        raise CorpusError(f"{source}: document body is empty")

    valid_to = meta.get("valid_to")
    document = Document(
        id=DocId(str(meta["id"])),
        title=str(meta["title"]),
        text=body,
        audience=tuple(str(item) for item in meta["audience"]),
        valid_from=date.fromisoformat(str(meta["valid_from"])),
        valid_to=date.fromisoformat(str(valid_to)) if valid_to else None,
        owner=str(meta["owner"]),
    )
    return LoadedDocument(
        document=document,
        doc_type=str(meta["type"]),
        checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        status=str(meta["status"]),
        path=Path(source),
        text=text,
    )


def load_schema(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CorpusError(f"{path}: schema must be an object")
    return raw
