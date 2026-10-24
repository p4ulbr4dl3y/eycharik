"""Response models. The wire format is pinned by ``docs/contracts/admin-api.md``."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from onboarding.core.models import Channel


class SessionRequest(BaseModel):
    """The one place a raw token travels in a body instead of a header."""

    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class AdminScope(BaseModel):
    """The rows the caller may see. ``None`` means "not narrowed by this dimension"."""

    model_config = ConfigDict(frozen=True)

    recruiter_id: str | None
    department: str | None


class AdminIdentity(BaseModel):
    """Who the caller is and what the cabinet may offer them."""

    model_config = ConfigDict(frozen=True)

    role: str
    subject: str
    scope: AdminScope
    capabilities: list[str]
    expires_at: datetime | None


# A person id comes from an HR system, so it is an opaque token, not a display name.
EmployeeIdText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:@-]+$"
    ),
]
_PERSON = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# An audience entry is one of the three shapes the retrieval ACL understands. A free-form string
# would look accepted and then match no document.
_AUDIENCE = Annotated[
    str,
    StringConstraints(min_length=1, max_length=80, pattern=r"^(all|hr_only|dept:[\w.-]{1,64})$"),
]
# An inline ``Literal["active"]`` confuses the quote-removal lint under postponed evaluation.
RestoreStatus = Literal["active"]
_SCENARIO_ID = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=1, max_length=64),
]


class EmployeeChannel(BaseModel):
    """One messenger account linked to the person. The link is the access gate (ADR 0019)."""

    model_config = ConfigDict(frozen=True)

    channel: str
    external_id: str
    linked_at: datetime


class Employee(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    name: str
    role: str
    department: str
    recruiter_id: str | None
    started_at: date
    audience: list[str]
    scenario_id: str
    status: str
    left_at: datetime | None
    created_at: datetime
    channels: list[EmployeeChannel] = Field(default_factory=list)


class EmployeeCreate(BaseModel):
    """A new hire. ``employee_id`` is the id the company already uses, not one the server mints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    employee_id: EmployeeIdText
    name: _PERSON
    role: _PERSON
    department: _PERSON
    recruiter_id: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=64)
    ] | None = None
    started_at: date
    audience: list[_AUDIENCE] = Field(default_factory=lambda: ["all"], min_length=1, max_length=32)
    scenario_id: _SCENARIO_ID = "onboarding_default"

    @field_validator("audience")
    @classmethod
    def _unique_audience(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("audience entries must be unique")
        return value


class EmployeeUpdate(BaseModel):
    """A correction to the directory. ``status: "active"`` restores a person who has left.

    Leaving is not an update: it is ``DELETE /employees/{id}``, which stops the run and purges the
    transcript. Restoring keeps that purge; the person comes back with no history and no links.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: _PERSON | None = None
    role: _PERSON | None = None
    department: _PERSON | None = None
    recruiter_id: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=64)
    ] | None = None
    started_at: date | None = None
    audience: list[_AUDIENCE] | None = Field(default=None, min_length=1, max_length=32)
    scenario_id: _SCENARIO_ID | None = None
    status: RestoreStatus | None = None

    @field_validator("audience")
    @classmethod
    def _unique_audience(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("audience entries must be unique")
        return value


class EmployeesBulk(BaseModel):
    """An HRIS batch: the same body repeated is the same batch, because every row is keyed by id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    employees: list[EmployeeCreate] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _unique_ids(self) -> EmployeesBulk:
        ids = [employee.employee_id for employee in self.employees]
        if len(set(ids)) != len(ids):
            raise ValueError("employees must not repeat an employee_id inside one batch")
        return self


class EmployeeBulkResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: int
    updated: int


class EmployeeList(BaseModel):
    items: list[Employee]
    next_cursor: str | None = None
    total: int


class RunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    employee_id: str
    name: str
    role: str
    department: str
    step_id: str
    step_title: str | None
    step_number: int
    steps_total: int
    entered_at: datetime
    updated_at: datetime
    status: str


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    at: datetime
    fields: dict[str, object]


class Question(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    employee_id: str
    employee_name: str
    text: str
    answered: bool
    reason: str
    citations: list[str]
    asked_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    assignee: str | None = None


class AssignQuestion(BaseModel):
    """`null` clears the owner; a name must be an admin the server can authenticate."""

    assignee: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class AssignedQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    employee_id: str
    assignee: str | None


class ResolveQuestion(BaseModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


class ResolvedQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    employee_id: str
    answered: bool
    resolved_at: datetime
    resolved_by: str


class LinkIdentity(BaseModel):
    """HR links one messenger account to an employee: without a link there is no run (ADR 0019)."""

    model_config = ConfigDict(frozen=True)

    channel: Channel
    external_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    employee_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]


class OffboardedEmployee(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    questions_deleted: int
    messages_deleted: int
    runs_closed: int
    audit_redacted: int


class RunList(BaseModel):
    """One page of runs. `next_cursor` is null on the last page; `total` counts the whole scope."""

    items: list[RunSummary]
    next_cursor: str | None = None
    total: int


class RunDetail(RunSummary):
    step_message: str | None
    scenario: str
    scenario_version: int
    tone: str
    events: list[AuditEvent]
    questions: list[Question]


class QuestionList(BaseModel):
    items: list[Question]
    next_cursor: str | None = None
    total: int


class TagCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    tag: str
    count: int


class AnalyticsOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    active_runs: int
    completed_runs: int
    high_risk: int
    medium_risk: int
    unanswered_questions: int
    resolved_questions: int
    top_tags: list[TagCount]
    since: datetime


class DigestItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    employee_name: str
    department: str
    run_id: str
    step_id: str
    step_title: str
    level: str
    reasons: list[str]
    tags: list[str]
    quote: str | None
    at: datetime


class DigestList(BaseModel):
    items: list[DigestItem]
    since: datetime


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    type: str
    audience: list[str]
    owner: str
    valid_from: date | None
    valid_to: date | None
    updated_at: datetime


class KnowledgeDocumentDetail(KnowledgeDocument):
    """The list shape plus the raw markdown the cabinet can show and edit."""

    text: str | None


class KnowledgeList(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[KnowledgeDocument]


class KnowledgeUpload(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=20, max_length=200_000)


class KnowledgeFileQueued(BaseModel):
    """A file accepted for extraction. It is not in the corpus yet, and the cabinet says so."""

    model_config = ConfigDict(frozen=True)

    content_hash: str
    status: str


class KnowledgeExtraction(BaseModel):
    """What happened to one uploaded file under the active extraction profile."""

    model_config = ConfigDict(frozen=True)

    content_hash: str
    status: str
    reason: str | None = None
    engine: str
    route: str
    pages: int
    min_confidence: float
    document_id: str | None = None
