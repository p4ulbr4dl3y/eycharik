"""Protocols between the pure core and the outside world.

Implementations live in ``onboarding.app``. The core imports this module only for typing; nothing
here performs I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable

from onboarding.core.models import (
    AcceptancePolicy,
    Address,
    Channel,
    Chunk,
    DocId,
    Document,
    DocumentSniff,
    EmployeeId,
    EmployeeProfile,
    Event,
    ExtractedDocument,
    ExtractedPage,
    Keyboard,
    QualityPolicy,
    ReminderPlan,
    RiskSignal,
    RunId,
    ScoredChunk,
    StepState,
)


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time in UTC. The only source of time in the application."""
        ...


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """One call. ``None`` means "the model profile decides"; a value is an explicit override."""

    messages: tuple[Message, ...]
    temperature: float | None = None
    max_tokens: int | None = None
    prompt_name: str = "answer"
    prompt_version: int = 1
    response_format: str = "json_object"
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    # Prefix tokens the provider served from its cache. Some providers bill these at a lower rate,
    # so a cost that ignores them is wrong in the expensive direction.
    cached_input_tokens: int = 0
    model: str = ""
    latency_ms: int = 0
    cost_rub: float = 0.0


@dataclass(frozen=True, slots=True)
class AnswerProfile:
    """What one answer model needs: wire dialect, capabilities, envelope, and prices.

    Profiles are data (``apps/api/model-profiles/answer/<name>.yaml``), validated against
    ``docs/contracts/model-profile.schema.json``. The gateway reads a profile; it never branches on
    a model name, so a new model is a file plus an eval run, not a code change.
    """

    name: str
    model: str
    family: Literal["openai-chat", "gigachat"] = "openai-chat"
    json_mode: bool = True
    max_tokens_field: str = "max_tokens"
    reasoning_effort: str | None = None
    temperature: float = 0.2
    max_tokens: int = 700
    timeout_s: float = 8.0
    max_retries: int = 1
    retry_empty_completion: bool = True
    price_input_rub_per_1k: float = 0.0
    price_output_rub_per_1k: float = 0.0
    price_cache_read_rub_per_1k: float = 0.0


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    """One embedding model. ``dim`` is part of the contract: a different width is a migration."""

    name: str
    model: str
    family: Literal["openai-chat", "gigachat", "local"] = "openai-chat"
    dim: int = 1024
    # Matryoshka models answer any prefix width; asking for a shorter one avoids a migration.
    dimensions_param: bool = False
    timeout_s: float = 10.0


@dataclass(frozen=True, slots=True)
class RerankProfile:
    """One reranker. An outage keeps the hybrid order, so this profile is never fatal."""

    name: str
    model: str
    family: Literal["cohere-rerank"] = "cohere-rerank"
    timeout_s: float = 3.0
    deadline_s: float = 6.0
    """The whole stage, retries included. A free endpoint answers 429 in bursts, and three spaced
    attempts at an 8 s timeout reach 32 s, which turns a ranking improvement into a latency
    incident. The budget stops the retrying, not the answering: a failure keeps the hybrid order."""


@dataclass(frozen=True, slots=True)
class ClassifyProfile:
    """One classifier model: its rubric, its envelope, and its input price.

    Classifiers answer typed probabilities, not chat completions, so they have no temperature,
    token budget, or output price. ``rubric`` is a ``<name>@<version>`` selector for the versioned
    file in ``docs/prompts/``; the classifier never knows a file path.
    """

    name: str
    model: str
    rubric: str = ""
    family: Literal["typesafe-jev"] = "typesafe-jev"
    timeout_s: float = 8.0
    max_retries: int = 2
    price_input_rub_per_1k: float = 0.0


@runtime_checkable
class LLM(Protocol):
    async def complete(self, request: CompletionRequest) -> Completion:
        """One completion. Raises :class:`LLMUnavailableError` when no provider answered."""
        ...


class LLMUnavailableError(RuntimeError):
    """Every configured provider failed or the circuit breaker is open."""


class KnowledgeUnavailableError(RuntimeError):
    """Retrieval could not run: the embedder or the database is down."""


class RerankUnavailableError(RuntimeError):
    """The reranker did not answer; retrieval keeps its own order."""


class RunAlreadyActiveError(RuntimeError):
    """An employee already has an active run; the database enforced it."""


@runtime_checkable
class SentimentAnalysis(Protocol):
    """Turn one free-text survey answer into a risk signal."""

    async def classify(self, text: str, *, source: str) -> RiskSignal: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """One vector per input text, in the same order."""
        ...


class Contextualizer(Protocol):
    """Adds back the sentence a chunk lost when the document was split (ADR 0016).

    The result is prepended to the chunk for embedding and for the lexical indexes only; citations
    keep quoting the chunk text itself.
    """

    async def context_for(self, document: Document, chunk: Chunk) -> str: ...


@runtime_checkable
class Reranker(Protocol):
    async def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> tuple[int, ...]:
        """Indices of the best documents, best first. Never invents an index."""
        ...


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    audience: tuple[str, ...]
    on_date: date
    limit: int = 30


@runtime_checkable
class KnowledgeBase(Protocol):
    async def search(self, query: SearchQuery) -> tuple[ScoredChunk, ...]:
        """Active, audience-permitted chunks ranked by relevance. No filtering after the fact."""
        ...


class ChannelUnavailableError(RuntimeError):
    """The messenger did not answer, or answered 5xx: the same send may work later."""


class ChannelRejectedError(RuntimeError):
    """The messenger refused the request: a retry repeats the refusal."""


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """One rendered domain message. The adapter turns it into a wire payload."""

    address: Address
    text: str
    image: str | None = None
    keyboard: Keyboard = ()
    reply_to: str | None = None


@runtime_checkable
class Sender(Protocol):
    """Anything a domain decision may send through: the outbox, in practice."""

    async def send(self, message: OutboundMessage) -> str:
        """Queue or send one message; return its identifier."""
        ...

    async def edit(
        self, address: Address, message_id: str, text: str, keyboard: Keyboard = ()
    ) -> None:
        """Replace the text of a previously sent message."""
        ...


@runtime_checkable
class Messaging(Sender, Protocol):
    """One messenger's send path. ``channel`` is how the composition root routes a message."""

    channel: Channel


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """One delivery, already typed. The adapter namespaces ``dedupe_key`` with its channel."""

    dedupe_key: str
    address: Address
    sender: str
    event: Event
    starts_run: bool = False


@runtime_checkable
class Ingress(Protocol):
    """One messenger's inbound path: authenticate, handshake, parse. Never touches the database."""

    channel: Channel

    @property
    def configured(self) -> bool:
        """False when the transport has no secret yet; the route then answers 503, not 401."""
        ...

    def verify(self, headers: Mapping[str, str], body: bytes) -> bool:
        """True when this delivery comes from the messenger. Compare secrets in constant time."""
        ...

    def handshake(self, body: bytes) -> str | None:
        """The plain-text answer a messenger needs before it delivers events, else ``None``."""
        ...

    def parse(self, body: bytes, *, received_at: datetime) -> InboundMessage | None:
        """A typed inbound message, or ``None`` when this delivery is not ours to handle."""
        ...


@runtime_checkable
class Directory(Protocol):
    async def profile(self, employee_id: EmployeeId) -> EmployeeProfile | None:
        """Employee facts needed for the assistant context. ``None`` when unknown."""
        ...

    async def resolve(self, channel: Channel, external_id: str) -> EmployeeId | None:
        """The employee behind one messenger account, or ``None`` when the account is unlinked."""
        ...

    async def link(self, channel: Channel, external_id: str, employee_id: EmployeeId) -> bool:
        """Bind a messenger account to an employee. Idempotent; ``False`` for an unknown person."""
        ...


@runtime_checkable
class EventDeduper(Protocol):
    async def claim(self, event_id: str) -> bool:
        """True when this delivery is new. Claims atomically; a repeat answers False."""
        ...


@dataclass(frozen=True, slots=True)
class StoredRun:
    state: StepState
    reminder: ReminderPlan
    address: Address
    active: bool = True


@runtime_checkable
class RunRepository(Protocol):
    async def create(self, run: StoredRun) -> None: ...

    async def load(self, run_id: RunId) -> StoredRun | None: ...

    async def save(self, run: StoredRun) -> None: ...

    async def find_active_by_employee(self, employee_id: EmployeeId) -> StoredRun | None: ...

    async def list_active(
        self, *, recruiter_id: str | None, limit: int
    ) -> tuple[StoredRun, ...]: ...


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentRecord:
    id: DocId
    title: str
    doc_type: str
    status: str
    audience: tuple[str, ...]
    valid_from: date
    valid_to: date | None
    owner: str
    checksum: str
    # Raw markdown with frontmatter. Optional so older callers and rows stay valid; the ingestion
    # pipeline always supplies it when it has the source text.
    body: str | None = None


@runtime_checkable
class KnowledgeWriter(Protocol):
    async def replace_document(
        self,
        record: KnowledgeDocumentRecord,
        chunks: tuple[Chunk, ...],
        embeddings: tuple[tuple[float, ...], ...],
    ) -> None:
        """Replace all chunks of one document atomically."""
        ...


@runtime_checkable
class QuestionLog(Protocol):
    async def record_question(
        self,
        *,
        employee_id: EmployeeId | None,
        address: Address,
        text: str,
        answered: bool,
        reason: str,
        citations: Sequence[str],
        latency_ms: int | None,
    ) -> None:
        """Append one asked question. The recruiter dashboard reads this table."""
        ...


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: int
    kind: str
    payload: dict[str, object]
    attempts: int


@runtime_checkable
class JobSink(Protocol):
    async def claim(self) -> tuple[ClaimedJob, ...]: ...

    async def complete(self, job: ClaimedJob) -> None: ...

    async def fail(self, job: ClaimedJob, error: Exception) -> None: ...


@runtime_checkable
class InboundSink(Protocol):
    """Durably accept one inbound event and the job that will process it.

    One transaction: a duplicate delivery is rejected by the dedupe key and never enqueues a
    second job. The transport never writes either row itself.
    """

    async def accept(
        self, *, dedupe_key: str, job_kind: str, payload: Mapping[str, object]
    ) -> bool:
        """True when the event is new and the job was queued; False for a duplicate."""
        ...


@dataclass(frozen=True, slots=True)
class KnowledgeSubmission:
    """One upload accepted for background indexing."""

    content_hash: str
    queued: bool


@runtime_checkable
class KnowledgeSubmitter(Protocol):
    """Store an upload and its indexing job in one transaction.

    The payload carries the bytes, the metadata, and the job kind. The returned flag is ``False``
    when the same content is already indexed or already queued, so a repeated upload is free.
    """

    async def submit(
        self,
        *,
        content: bytes,
        filename: str,
        media_type: str,
        metadata: Mapping[str, object],
        job_kind: str,
        profile_hash: str | None = None,
    ) -> KnowledgeSubmission:
        ...


@runtime_checkable
class HealthCheck(Protocol):
    """Readiness for the process, not for a dependency graph."""

    async def ping(self) -> bool: ...


@runtime_checkable
class AuditLog(Protocol):
    async def record(self, name: str, **fields: object) -> None:
        """Append-only record. Fields must not contain secrets or raw personal data."""
        ...


# --- Document extraction ---------------------------------------------------
#
# A file becomes text in two steps that fail for different reasons, so they are two ports:
# a reader knows container formats, an engine knows pixels. The composite that joins them is one
# adapter; the decisions it makes are pure and live in ``core/extraction.py``.
#
# Recognizers are the only part of this system that may be a large optional dependency, so they sit
# behind a profile and a lazy import. A profile with ``family="none"`` reads digital documents and
# refuses scans instead of pretending.


@dataclass(frozen=True, slots=True)
class DocumentRef:
    """Where a file came from. The transport is not part of the contract."""

    blob_id: str
    filename: str
    media_type: str


@dataclass(frozen=True, slots=True)
class ExtractionProfile:
    """How to read a file: thresholds, language, engine family.

    Profiles are data (``apps/api/model-profiles/extract/<name>.yaml``), validated against
    ``docs/contracts/extraction-profile.schema.json``. No code branches on ``family``: the
    composition root picks the adapter once, exactly like a model profile picks a gateway.
    """

    name: str
    family: Literal["none", "paddle", "rapid", "tesseract"] = "none"
    model: str = ""
    lang: str = "ru"
    dpi: int = 300
    min_text_chars: int = 40
    quality: QualityPolicy = field(default_factory=QualityPolicy)
    acceptance: AcceptancePolicy = field(default_factory=AcceptancePolicy)

    def fingerprint(self) -> str:
        """Identity of this reader configuration. Changes invalidate the extraction cache."""
        payload = {
            "family": self.family,
            "model": self.model,
            "lang": self.lang,
            "dpi": self.dpi,
            "min_text_chars": self.min_text_chars,
            "quality": {
                "min_dpi": self.quality.min_dpi,
                "min_edge_energy": self.quality.min_edge_energy,
            },
            "acceptance": {
                "min_confidence": self.acceptance.min_confidence,
                "min_chars": self.acceptance.min_chars,
            },
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class ExtractionUnavailableError(RuntimeError):
    """No recognizer is configured, or its dependency is missing.

    The job is retried, then parked with the reason; the corpus is untouched.
    """


@runtime_checkable
class DocumentReader(Protocol):
    """One container format: PDF, PPTX, and whatever comes next.

    ``inspect`` is cheap and decides the route; ``rasterize`` is only called when recognition is
    actually needed, so a digital document never pays for page rendering.
    """

    engine: str

    def supports(self, media_type: str) -> bool:
        """True when this reader owns the media type."""
        ...

    def inspect(self, content: bytes) -> DocumentSniff:
        """Pages, any existing text layer, and cheap quality metrics."""
        ...

    def rasterize(self, content: bytes, *, dpi: int) -> tuple[bytes, ...]:
        """One encoded image per page, in reading order. Empty when the format has no raster."""
        ...


@runtime_checkable
class Ocr(Protocol):
    """Pixels to text. Never decides whether the result is good enough to keep."""

    engine: str

    def recognize(
        self, images: Sequence[bytes], *, lang: str, model: str
    ) -> tuple[ExtractedPage, ...]:
        """One page per image, in the same order. Confidence is calibrated 0..1."""
        ...


@runtime_checkable
class Extraction(Protocol):
    """Bytes to pages, with the routing and the quality gate applied."""

    async def extract(
        self, content: bytes, ref: DocumentRef, profile: ExtractionProfile
    ) -> ExtractedDocument:
        """Never writes and never indexes. A refusal is a result, not an exception."""
        ...


@runtime_checkable
class BlobStore(Protocol):
    """Uploaded bytes, addressable by content hash so a repeat upload is free."""

    async def put(self, content: bytes, *, filename: str, media_type: str) -> str:
        """Store and return the content hash. Storing the same bytes twice is a no-op."""
        ...

    async def read(self, blob_id: str) -> bytes | None:
        """Exact bytes back, or ``None`` when the blob is gone."""
        ...


@dataclass(frozen=True, slots=True)
class ExtractionRecord:
    """The cached outcome of one (file, profile) pair, refusals included."""

    content_hash: str
    profile_hash: str
    status: str
    reason: str | None
    engine: str
    route: str
    pages: int
    min_confidence: float
    markdown: str | None = None
    document_id: str | None = None


@runtime_checkable
class ExtractionCache(Protocol):
    """Extraction is expensive and deterministic per profile, so it is cached by hash pair."""

    async def load(self, content_hash: str, profile_hash: str) -> ExtractionRecord | None: ...

    async def load_latest(self, content_hash: str) -> ExtractionRecord | None:
        """The newest record for a blob, whichever profile produced it. The cabinet reads this."""
        ...

    async def save(self, record: ExtractionRecord) -> None:
        """Insert or replace one record."""
        ...
