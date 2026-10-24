"""Recruiter cabinet API.

Recruiters see their own employees. HR sees everyone. A run outside the caller's scope answers 404,
the same as a run that does not exist: the existence of other employees is not the caller's
business.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from onboarding.api.auth import (
    SESSION_COOKIE,
    SESSION_PATH,
    SESSION_TTL,
    AdminPrincipal,
    authenticate,
    current_admin,
)
from onboarding.api.cursor import CursorError, decode, encode
from onboarding.api.schemas import (
    AdminIdentity,
    AdminScope,
    AnalyticsOverview,
    AssignedQuestion,
    AssignQuestion,
    AuditEvent,
    DigestItem,
    DigestList,
    Employee,
    EmployeeBulkResult,
    EmployeeChannel,
    EmployeeCreate,
    EmployeeList,
    EmployeesBulk,
    EmployeeUpdate,
    KnowledgeDocument,
    KnowledgeDocumentDetail,
    KnowledgeExtraction,
    KnowledgeFileQueued,
    KnowledgeList,
    KnowledgeUpload,
    LinkIdentity,
    OffboardedEmployee,
    Question,
    QuestionList,
    ResolvedQuestion,
    ResolveQuestion,
    RunDetail,
    RunList,
    RunSummary,
    SessionRequest,
    TagCount,
)
from onboarding.app.admin.actions import EmployeeFields, EmployeeNotFoundError
from onboarding.app.admin.records import (
    EmployeeCursor,
    EmployeeRecord,
    IdentityRecord,
    QuestionCursor,
    QuestionRecord,
    RunCursor,
    RunRecord,
)
from onboarding.app.scenarios import ScenarioCatalog, ScenarioCatalogError

# The cabinet talks to a versioned surface. The unversioned prefix keeps answering for a client
# that has not shipped the new path yet, and is not part of the published schema (ADR 0024).
API_PREFIX = "/admin/api/v1"
LEGACY_PREFIX = "/admin/api"

router = APIRouter(tags=["admin"])

log = logging.getLogger("onboarding.api.admin")

Admin = Annotated[AdminPrincipal, Depends(current_admin)]


def _scope(principal: AdminPrincipal) -> str | None:
    """The recruiter id predicate; HR is unscoped and a manager is scoped by department."""
    return principal.subject if principal.role == "recruiter" else None


def _department(principal: AdminPrincipal) -> str | None:
    return principal.subject if principal.is_manager else None


@router.get("/me", response_model=AdminIdentity)
async def whoami(principal: Admin) -> AdminIdentity:
    """Who the caller is and what the cabinet may offer them.

    The cabinet renders buttons from ``capabilities`` instead of guessing from an opaque token, and
    a capability the server does not grant never becomes a button that fails with 403.
    """
    return AdminIdentity(
        role=principal.role,
        subject=principal.subject,
        scope=AdminScope(
            recruiter_id=_scope(principal),
            department=_department(principal),
        ),
        capabilities=list(principal.capabilities),
        expires_at=principal.expires_at,
    )


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
async def open_session(request: Request, body: SessionRequest, response: Response) -> None:
    """Trade a token for an HttpOnly session cookie.

    The token is never stored by the page: it arrives once in a JSON body and leaves as a cookie the
    script cannot read. A wrong token is throttled here exactly like a wrong bearer header.
    """
    principal = await authenticate(request, body.token)
    container = request.app.state.container
    response.set_cookie(
        SESSION_COOKIE,
        body.token,
        max_age=int(SESSION_TTL.total_seconds()),
        path=SESSION_PATH,
        httponly=True,
        samesite="strict",
        secure=container.settings.environment != "local",
    )
    log.info(
        json.dumps(
            {"event": "admin_session_opened", "role": principal.role, "subject": principal.subject},
            ensure_ascii=False,
        )
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def close_session(request: Request, response: Response) -> None:
    """Clear the cookie.

    Open by design: signing out must work even for a token that just expired.
    """
    response.delete_cookie(SESSION_COOKIE, path=SESSION_PATH)
    log.info(json.dumps({"event": "admin_session_closed"}, ensure_ascii=False))


@router.get("/runs", response_model=RunList)
async def list_runs(  # noqa: PLR0917 - the query parameters are the endpoint's interface

    request: Request,
    principal: Admin,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    status_filter: Annotated[
        Literal["active", "completed", "all"], Query(alias="status")
    ] = "all",
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> RunList:
    catalog = request.app.state.container.catalog
    admin = request.app.state.container.admin
    recruiter_id = _scope(principal)
    department = _department(principal)
    active = {"active": True, "completed": False, "all": None}[status_filter]
    records, has_more = await admin.runs_page(
        recruiter_id=recruiter_id,
        department=department,
        limit=limit,
        after=_run_cursor(cursor),
        active=active,
        search=q,
    )
    return RunList(
        items=[_summary(record, catalog) for record in records],
        next_cursor=_next_run_cursor(records, has_more),
        total=await admin.runs_total(
            recruiter_id=recruiter_id, department=department, active=active, search=q
        ),
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def run_detail(request: Request, principal: Admin, run_id: str) -> RunDetail:
    admin = request.app.state.container.admin
    record = await admin.run(
        run_id, recruiter_id=_scope(principal), department=_department(principal)
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")

    catalog: ScenarioCatalog = request.app.state.container.catalog
    summary = _summary(record, catalog)
    try:
        step = catalog.get(record.scenario_id, record.scenario_version).step(record.step_id)
    except ScenarioCatalogError:
        step_message = None
    else:
        step_message = step.message

    events = await admin.events(record.employee_id)
    questions = await admin.questions(
        recruiter_id=_scope(principal),
        department=_department(principal),
        answered=None,
        limit=20,
        employee_id=record.employee_id,
    )
    return RunDetail(
        **summary.model_dump(),
        step_message=step_message,
        scenario=record.scenario_id,
        scenario_version=record.scenario_version,
        tone=record.tone,
        events=[
            AuditEvent(name=event.name, at=event.at, fields=event.fields) for event in events
        ],
        questions=[_question(question) for question in questions],
    )


@router.get("/employees", response_model=EmployeeList)
async def list_employees(  # noqa: PLR0917 - the query parameters are the endpoint's interface
    request: Request,
    principal: Admin,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    status_filter: Annotated[
        Literal["active", "left", "all"], Query(alias="status")
    ] = "all",
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> EmployeeList:
    """The directory, newest first, scoped like every other list.

    ``q`` searches the id, name, role and department: an HR system keys a person by an id, and a
    recruiter remembers a name.
    """
    admin = request.app.state.container.admin
    recruiter_id = _scope(principal)
    department = _department(principal)
    status_value = None if status_filter == "all" else status_filter
    records, has_more = await admin.employees_page(
        recruiter_id=recruiter_id,
        department=department,
        status_filter=status_value,
        search=q,
        limit=limit,
        after=_employee_cursor(cursor),
    )
    return EmployeeList(
        items=[_employee(record, ()) for record in records],
        next_cursor=_next_employee_cursor(records, has_more),
        total=await admin.employees_total(
            recruiter_id=recruiter_id,
            department=department,
            status_filter=status_value,
            search=q,
        ),
    )


@router.get("/employees/{employee_id}", response_model=Employee)
async def employee_detail(
    request: Request, principal: Admin, employee_id: str
) -> Employee:
    admin = request.app.state.container.admin
    record = await admin.employee(
        employee_id, recruiter_id=_scope(principal), department=_department(principal)
    )
    if record is None:
        raise EmployeeNotFoundError(employee_id)
    return _employee(record, await admin.identities(employee_id))


@router.post(
    "/employees",
    response_model=Employee,
    status_code=status.HTTP_201_CREATED,
)
async def create_employee(
    request: Request, principal: Admin, body: EmployeeCreate
) -> Employee:
    """Add a hire. The id is the one the company already uses, so a retry is a 409, not a twin."""
    _require_hr(principal, "create an employee")
    record = await request.app.state.container.admin.create_employee(
        _fields(body), actor=principal.subject
    )
    return _employee(record, ())


@router.patch("/employees/{employee_id}", response_model=Employee)
async def update_employee(
    request: Request, principal: Admin, employee_id: str, body: EmployeeUpdate
) -> Employee:
    """Correct a directory row. Only ``status: "active"`` touches the lifecycle, and it restores.

    Leaving stays on ``DELETE``: it must close the run and purge the transcript in one transaction.
    """
    _require_hr(principal, "change an employee")
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)
    admin = request.app.state.container.admin
    record = await admin.update_employee(employee_id, changes, actor=principal.subject)
    return _employee(record, await admin.identities(employee_id))


@router.post("/employees/bulk", response_model=EmployeeBulkResult)
async def sync_employees(
    request: Request, principal: Admin, body: EmployeesBulk
) -> EmployeeBulkResult:
    """Upsert a batch from an HRIS. Rows are keyed by ``employee_id``; leaving is never implied."""
    _require_hr(principal, "sync employees")
    created, updated = await request.app.state.container.admin.sync_employees(
        [_fields(employee) for employee in body.employees], actor=principal.subject
    )
    return EmployeeBulkResult(created=created, updated=updated)


@router.get("/questions", response_model=QuestionList)
async def list_questions(  # noqa: PLR0917 - the query parameters are the endpoint's interface

    request: Request,
    principal: Admin,
    status: Annotated[Literal["unanswered", "answered", "all"], Query()] = "unanswered",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    assignee: Annotated[Literal["me", "unassigned", "any"], Query()] = "any",
) -> QuestionList:
    answered = {"unanswered": False, "answered": True, "all": None}[status]
    admin = request.app.state.container.admin
    recruiter_id = _scope(principal)
    department = _department(principal)
    mine = principal.subject if assignee == "me" else None
    unassigned = assignee == "unassigned"
    records, has_more = await admin.questions_page(
        recruiter_id=recruiter_id,
        department=department,
        answered=answered,
        limit=limit,
        after=_question_cursor(cursor),
        assignee=mine,
        unassigned=unassigned,
    )
    return QuestionList(
        items=[_question(record) for record in records],
        next_cursor=_next_question_cursor(records, has_more),
        total=await admin.questions_total(
            recruiter_id=recruiter_id,
            department=department,
            answered=answered,
            assignee=mine,
            unassigned=unassigned,
        ),
    )


@router.post(
    "/questions/{question_id}/resolve",
    response_model=ResolvedQuestion,
)
async def resolve_question(
    request: Request,
    principal: Admin,
    question_id: int,
    body: ResolveQuestion,
) -> ResolvedQuestion:
    """Close one escalated question and queue the recruiter's reply in the outbox."""
    resolution = await request.app.state.container.admin.resolve_question(
        question_id,
        text=body.text,
        actor=principal.subject,
        recruiter_id=_scope(principal),
        department=_department(principal),
    )
    return ResolvedQuestion(
        id=resolution.question_id,
        employee_id=resolution.employee_id,
        answered=True,
        resolved_at=resolution.resolved_at,
        resolved_by=resolution.resolved_by,
    )


@router.post(
    "/identities",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def link_identity(
    request: Request,
    principal: Admin,
    body: LinkIdentity,
) -> Response:
    """Link a messenger account to an employee, which is what unblocks their first message."""
    if not principal.is_hr:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only hr_admin may link a messenger account",
        )
    linked = await request.app.state.container.admin.link_identity(
        body.channel, body.external_id, body.employee_id
    )
    if not linked:
        raise EmployeeNotFoundError(body.employee_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/questions/{question_id}/assignee",
    response_model=AssignedQuestion,
)
async def assign_question(
    request: Request,
    principal: Admin,
    question_id: int,
    body: AssignQuestion,
) -> AssignedQuestion:
    """Name an owner for an open question, or clear one with `{"assignee": null}`.

    Any role that may answer a question may also claim it: the queue is shared, and picking a card
    up is not a privilege. HR keeps the ability to reassign somebody else's card, which is what
    "the recruiter is on holiday" needs.
    """
    assignment = await request.app.state.container.admin.assign_question(
        question_id,
        assignee=body.assignee or None,
        actor=principal.subject,
        recruiter_id=_scope(principal),
        department=_department(principal),
    )
    return AssignedQuestion(
        id=assignment.question_id,
        employee_id=assignment.employee_id,
        assignee=assignment.assignee,
    )


@router.delete(
    "/employees/{employee_id}",
    response_model=OffboardedEmployee,
)
async def offboard_employee(
    request: Request,
    principal: Admin,
    employee_id: str,
) -> OffboardedEmployee:
    """HR offboards an employee: the run stops and the transcript is deleted immediately."""
    if not principal.is_hr:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only hr_admin may offboard an employee",
        )
    result = await request.app.state.container.admin.offboard(
        employee_id, actor=principal.subject
    )
    return OffboardedEmployee(
        employee_id=result.employee_id,
        questions_deleted=result.questions_deleted,
        messages_deleted=result.messages_deleted,
        runs_closed=result.runs_closed,
        audit_redacted=result.audit_redacted,
    )


def _summary(record: RunRecord, catalog: ScenarioCatalog) -> RunSummary:
    step_title: str | None = None
    try:
        scenario = catalog.get(record.scenario_id, record.scenario_version)
    except ScenarioCatalogError:
        number, total = 0, 0
    else:
        ordered = list(scenario.steps)
        number = ordered.index(record.step_id) + 1 if record.step_id in ordered else 0
        total = len(ordered)
        if record.step_id in ordered:
            step_title = scenario.step(record.step_id).title
    return RunSummary(
        run_id=record.run_id,
        employee_id=record.employee_id,
        name=record.name,
        role=record.role,
        department=record.department,
        step_id=record.step_id,
        step_title=step_title,
        step_number=number,
        steps_total=total,
        entered_at=record.entered_at,
        updated_at=record.updated_at,
        status="active" if record.active else "completed",
    )


def _run_cursor(raw: str | None) -> RunCursor | None:
    if raw is None:
        return None
    payload = _payload(raw)
    try:
        return RunCursor(
            at=datetime.fromisoformat(str(payload["at"])),
            run_id=str(payload["run_id"]),
        )
    except (KeyError, ValueError) as error:
        raise _bad_cursor() from error


def _employee_cursor(raw: str | None) -> EmployeeCursor | None:
    if raw is None:
        return None
    payload = _payload(raw)
    try:
        return EmployeeCursor(
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            employee_id=str(payload["employee_id"]),
        )
    except (KeyError, ValueError) as error:
        raise _bad_cursor() from error


def _question_cursor(raw: str | None) -> QuestionCursor | None:
    if raw is None:
        return None
    payload = _payload(raw)
    try:
        return QuestionCursor(
            answered=bool(payload["answered"]),
            asked_at=datetime.fromisoformat(str(payload["asked_at"])),
            id=int(str(payload["id"])),
        )
    except (KeyError, ValueError) as error:
        raise _bad_cursor() from error


def _payload(raw: str) -> dict[str, Any]:
    try:
        return decode(raw)
    except CursorError as error:
        raise _bad_cursor() from error


def _bad_cursor() -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, "cursor is not valid")


def _next_run_cursor(records: tuple[RunRecord, ...], has_more: bool) -> str | None:
    if not has_more or not records:
        return None
    last = records[-1]
    return encode({"at": last.updated_at.isoformat(), "run_id": last.run_id})


def _next_question_cursor(records: tuple[QuestionRecord, ...], has_more: bool) -> str | None:
    if not has_more or not records:
        return None
    last = records[-1]
    return encode(
        {"answered": last.answered, "asked_at": last.asked_at.isoformat(), "id": last.id}
    )


def _next_employee_cursor(records: tuple[EmployeeRecord, ...], has_more: bool) -> str | None:
    if not has_more or not records:
        return None
    last = records[-1]
    return encode(
        {"created_at": last.created_at.isoformat(), "employee_id": last.employee_id}
    )


def _fields(body: EmployeeCreate) -> EmployeeFields:
    return EmployeeFields(
        employee_id=body.employee_id,
        name=body.name,
        role=body.role,
        department=body.department,
        recruiter_id=body.recruiter_id,
        started_at=body.started_at,
        audience=tuple(body.audience),
        scenario_id=body.scenario_id,
    )


def _employee(record: EmployeeRecord, channels: tuple[IdentityRecord, ...]) -> Employee:
    return Employee(
        employee_id=record.employee_id,
        name=record.name,
        role=record.role,
        department=record.department,
        recruiter_id=record.recruiter_id,
        started_at=record.started_at,
        audience=list(record.audience),
        scenario_id=record.scenario_id,
        status=record.status,
        left_at=record.left_at,
        created_at=record.created_at,
        channels=[
            EmployeeChannel(
                channel=channel.channel,
                external_id=channel.external_id,
                linked_at=channel.linked_at,
            )
            for channel in channels
        ],
    )


def _require_hr(principal: AdminPrincipal, action: str) -> None:
    if not principal.is_hr:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"only hr_admin may {action}",
        )


def _question(record: QuestionRecord) -> Question:
    return Question(
        id=record.id,
        employee_id=record.employee_id,
        employee_name=record.employee_name,
        text=record.text,
        answered=record.answered,
        reason=record.reason,
        citations=record.citations,
        asked_at=record.asked_at,
        resolved_at=record.resolved_at,
        resolved_by=record.resolved_by,
        assignee=record.assignee,
    )


@router.get("/analytics/overview", response_model=AnalyticsOverview)
async def analytics_overview(request: Request, principal: Admin) -> AnalyticsOverview:
    since = request.app.state.container.clock.now() - timedelta(days=7)
    record = await request.app.state.container.admin.overview(
        recruiter_id=_scope(principal), department=_department(principal), since=since
    )
    return AnalyticsOverview(
        active_runs=record.active_runs,
        completed_runs=record.completed_runs,
        high_risk=record.high_risk,
        medium_risk=record.medium_risk,
        unanswered_questions=record.unanswered_questions,
        resolved_questions=record.resolved_questions,
        top_tags=[TagCount(tag=tag, count=count) for tag, count in record.top_tags],
        since=since,
    )


@router.get("/digest/weekly", response_model=DigestList)
async def weekly_digest(
    request: Request,
    principal: Admin,
    days: Annotated[int, Query(ge=1, le=31)] = 7,
) -> DigestList:
    since = request.app.state.container.clock.now() - timedelta(days=days)
    records = await request.app.state.container.admin.digest(
        recruiter_id=_scope(principal), department=_department(principal), since=since
    )
    return DigestList(
        items=[
            DigestItem(
                employee_id=record.employee_id,
                employee_name=record.employee_name,
                department=record.department,
                run_id=record.run_id,
                step_id=record.step_id,
                step_title=record.step_title,
                level=record.level,
                reasons=list(record.reasons),
                tags=list(record.tags),
                quote=record.quote,
                at=record.at,
            )
            for record in records
        ],
        since=since,
    )


@router.get("/knowledge", response_model=KnowledgeList)
async def knowledge_documents(
    request: Request,
    principal: Admin,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> KnowledgeList:
    """Active documents. An ``hr_only`` document is not fetched for a non-HR caller at all."""
    records = await request.app.state.container.admin.knowledge(
        limit=limit, include_hr_only=principal.is_hr
    )
    return KnowledgeList(
        items=[
            KnowledgeDocument(
                id=record.id,
                title=record.title,
                type=record.type,
                audience=list(record.audience),
                owner=record.owner,
                valid_from=record.valid_from,
                valid_to=record.valid_to,
                updated_at=record.updated_at,
            )
            for record in records
        ]
    )


@router.post(
    "/knowledge",
    response_model=KnowledgeFileQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_knowledge(
    request: Request,
    principal: Admin,
    body: KnowledgeUpload,
) -> KnowledgeFileQueued:
    """HR uploads one markdown document; the worker indexes it and the cabinet polls."""
    if not principal.is_hr:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only hr_admin may change the knowledge base",
        )
    submission = await request.app.state.container.admin.submit_markdown(
        body.text, actor=principal.subject
    )
    return KnowledgeFileQueued(content_hash=submission.content_hash, status="queued")


@router.post(
    "/knowledge/files",
    response_model=KnowledgeFileQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_knowledge_file(
    request: Request,
    principal: Admin,
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form()],
) -> KnowledgeFileQueued:
    """Accept a PDF or a deck, store it by hash, and queue extraction.

    The request does no heavy work: recognition takes seconds per page, so it happens in the worker
    and the cabinet polls ``/knowledge/files/{content_hash}``. The metadata is validated here,
    against the same contract a committed document obeys, so a bad upload fails fast.
    """
    if not principal.is_hr:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only hr_admin may change the knowledge base",
        )
    container = request.app.state.container
    limit = container.settings.extraction_max_upload_bytes
    content = await file.read(limit + 1)
    submission = await container.admin.submit_file(
        content=content,
        filename=file.filename or "upload",
        declared_media_type=file.content_type,
        raw_metadata=metadata,
        actor=principal.subject,
        max_bytes=limit,
    )
    return KnowledgeFileQueued(content_hash=submission.content_hash, status="queued")


@router.get("/knowledge/files/{content_hash}", response_model=KnowledgeExtraction)
async def extraction_status(
    request: Request, principal: Admin, content_hash: str
) -> KnowledgeExtraction:
    record = await request.app.state.container.admin.extraction(content_hash)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no extraction for this file"
        )
    return KnowledgeExtraction(
        content_hash=record.content_hash,
        status=record.status,
        reason=record.reason,
        engine=record.engine,
        route=record.route,
        pages=record.pages,
        min_confidence=record.min_confidence,
        document_id=record.document_id,
    )


@router.get("/knowledge/{document_id:path}", response_model=KnowledgeDocumentDetail)
async def knowledge_document(
    request: Request, principal: Admin, document_id: str
) -> KnowledgeDocumentDetail:
    """One active document, including the raw markdown the cabinet may edit.

    The route uses a path converter because document ids are namespaced (``hr/leave-policy``).
    An ``hr_only`` document is a 404 for a non-HR caller, exactly like a missing one.
    """
    record = await request.app.state.container.admin.knowledge_document(
        document_id, include_hr_only=principal.is_hr
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return KnowledgeDocumentDetail(
        id=record.id,
        title=record.title,
        type=record.type,
        audience=list(record.audience),
        owner=record.owner,
        valid_from=record.valid_from,
        valid_to=record.valid_to,
        updated_at=record.updated_at,
        text=record.body,
    )


@router.put(
    "/knowledge/{document_id:path}",
    response_model=KnowledgeFileQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_knowledge(
    request: Request,
    principal: Admin,
    document_id: str,
    body: KnowledgeUpload,
) -> KnowledgeFileQueued:
    """Replace one document's markdown and queue re-indexing.

    The frontmatter is validated by the same use case as an upload, and its ``id`` must stay equal
    to the path id: an edit changes a document, it does not create a second one under a new key.
    """
    if not principal.is_hr:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only hr_admin may change the knowledge base",
        )
    container = request.app.state.container
    existing = await container.admin.knowledge_document(document_id, include_hr_only=True)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    submission = await container.admin.submit_markdown(
        body.text, actor=principal.subject, expected_id=document_id
    )
    return KnowledgeFileQueued(content_hash=submission.content_hash, status="queued")
