"""Read models for the recruiter cabinet.

Every query is scoped by the principal's subject unless it is HR. The scope is a SQL predicate, not
a post-filter, so a wrong id cannot leak a row that was fetched and then discarded.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    and_,
    case,
    desc,
    func,
    literal_column,
    or_,
    select,
    text,
    tuple_,
)

from onboarding.app.admin.records import (
    DigestRecord,
    EmployeeCursor,
    EmployeeRecord,
    EventRecord,
    IdentityRecord,
    KnowledgeRecord,
    OverviewRecord,
    QuestionCursor,
    QuestionRecord,
    RunCursor,
    RunRecord,
)
from onboarding.app.db.models import (
    AuditRow,
    ChannelIdentityRow,
    DocumentRow,
    EmployeeRow,
    QuestionRow,
    RunRow,
)
from onboarding.app.db.session import Database

__all__ = [
    "AdminQueries",
    "DigestRecord",
    "EmployeeCursor",
    "EmployeeRecord",
    "EventRecord",
    "IdentityRecord",
    "KnowledgeRecord",
    "OverviewRecord",
    "QuestionCursor",
    "QuestionRecord",
    "RunCursor",
    "RunRecord",
]


class AdminQueries:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def runs(
        self, *, recruiter_id: str | None, department: str | None = None, limit: int
    ) -> tuple[RunRecord, ...]:
        records, _ = await self.runs_page(
            recruiter_id=recruiter_id, department=department, limit=limit
        )
        return records

    async def runs_page(
        self,
        *,
        recruiter_id: str | None,
        department: str | None = None,
        limit: int,
        after: RunCursor | None = None,
        active: bool | None = None,
        search: str | None = None,
    ) -> tuple[tuple[RunRecord, ...], bool]:
        """One page of runs, newest activity first, and whether another page exists.

        Keyset, not offset: a run that moves while the recruiter reads page one cannot shift a row
        from page two into a hole. One extra row is fetched to learn that the page is not the last.
        """
        statement = _run_query(recruiter_id, department, active=active, search=search)
        if after is not None:
            statement = statement.where(
                tuple_(RunRow.updated_at, RunRow.id) < tuple_(after.at, _uuid(after.run_id))
            )
        async with self._database.session() as session:
            rows = (await session.execute(statement.limit(limit + 1))).all()
        return tuple(_run_record(*row) for row in rows[:limit]), len(rows) > limit

    async def runs_total(
        self,
        *,
        recruiter_id: str | None,
        department: str | None = None,
        active: bool | None = None,
        search: str | None = None,
    ) -> int:
        statement = select(func.count()).select_from(RunRow).join(
            EmployeeRow, EmployeeRow.id == RunRow.employee_id
        )
        statement = _scope_runs(statement, recruiter_id, department)
        statement = _filter_runs(statement, active=active, search=search)
        async with self._database.session() as session:
            return int(await session.scalar(statement) or 0)

    async def run(
        self, run_id: str, *, recruiter_id: str | None, department: str | None = None
    ) -> RunRecord | None:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    _run_query(recruiter_id, department)
                    .where(RunRow.id == _uuid(run_id))
                    .limit(1)
                )
            ).first()
            return _run_record(*row) if row is not None else None

    async def employees_page(
        self,
        *,
        recruiter_id: str | None,
        department: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        limit: int,
        after: EmployeeCursor | None = None,
    ) -> tuple[tuple[EmployeeRecord, ...], bool]:
        """One page of the directory, newest first, scoped in SQL like every other read.

        ``status_filter`` is ``active``, ``left``, or ``None`` for everybody. The scope predicate
        is the same one the runs and questions use, so the three lists cannot disagree about who
        a caller may see.
        """
        statement = _employee_query(
            recruiter_id, department, status_filter=status_filter, search=search
        )
        if after is not None:
            statement = statement.where(
                tuple_(EmployeeRow.created_at, EmployeeRow.id)
                < tuple_(after.created_at, after.employee_id)
            )
        async with self._database.session() as session:
            rows = (
                await session.scalars(statement.limit(limit + 1))
            ).all()
        return tuple(employee_record(row) for row in rows[:limit]), len(rows) > limit

    async def employees_total(
        self,
        *,
        recruiter_id: str | None,
        department: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> int:
        statement = select(func.count()).select_from(EmployeeRow)
        statement = _scope_runs(statement, recruiter_id, department)
        statement = _filter_employees(statement, status_filter=status_filter, search=search)
        async with self._database.session() as session:
            return int(await session.scalar(statement) or 0)

    async def employee(
        self, employee_id: str, *, recruiter_id: str | None, department: str | None = None
    ) -> EmployeeRecord | None:
        statement = _employee_query(recruiter_id, department).where(
            EmployeeRow.id == employee_id
        )
        async with self._database.session() as session:
            row = await session.scalar(statement)
        return employee_record(row) if row is not None else None

    async def identities(self, employee_id: str) -> tuple[IdentityRecord, ...]:
        async with self._database.session() as session:
            rows = await session.scalars(
                select(ChannelIdentityRow)
                .where(ChannelIdentityRow.employee_id == employee_id)
                .order_by(ChannelIdentityRow.channel, ChannelIdentityRow.external_id)
            )
            return tuple(
                IdentityRecord(
                    channel=row.channel,
                    external_id=row.external_id,
                    linked_at=row.linked_at,
                )
                for row in rows
            )

    async def events(self, employee_id: str, *, limit: int = 50) -> tuple[EventRecord, ...]:
        async with self._database.session() as session:
            rows = await session.scalars(
                select(AuditRow)
                .where(AuditRow.fields["employee_id"].astext == employee_id)
                .order_by(desc(AuditRow.at))
                .limit(limit)
            )
            return tuple(
                EventRecord(name=row.name, at=row.at, fields=row.fields) for row in rows
            )

    async def knowledge(
        self, *, limit: int = 100, include_hr_only: bool
    ) -> tuple[KnowledgeRecord, ...]:
        """Active documents, with ``hr_only`` hidden from everyone who is not HR.

        The predicate is in SQL, like every other scope: a row the caller may not read is never
        fetched, so a later bug in the formatter cannot leak it.
        """
        async with self._database.session() as session:
            statement = select(DocumentRow).where(DocumentRow.status == "active")
            if not include_hr_only:
                statement = statement.where(~DocumentRow.audience.contains(["hr_only"]))
            rows = await session.scalars(
                statement.order_by(desc(DocumentRow.updated_at)).limit(limit)
            )
            return tuple(
                KnowledgeRecord(
                    id=row.id,
                    title=row.title,
                    type=row.type,
                    audience=tuple(row.audience),
                    owner=row.owner,
                    valid_from=row.valid_from,
                    valid_to=row.valid_to,
                    updated_at=row.updated_at,
                )
                for row in rows
            )

    async def knowledge_document(
        self, document_id: str, *, include_hr_only: bool
    ) -> KnowledgeRecord | None:
        """One active document with its source markdown.

        The same SQL scope as the list applies before the row is fetched. An ``hr_only`` document
        therefore looks absent to a recruiter, not merely read-only.
        """
        async with self._database.session() as session:
            statement = select(DocumentRow).where(
                DocumentRow.id == document_id, DocumentRow.status == "active"
            )
            if not include_hr_only:
                statement = statement.where(~DocumentRow.audience.contains(["hr_only"]))
            row = await session.scalar(statement)
            if row is None:
                return None
            return KnowledgeRecord(
                id=row.id,
                title=row.title,
                type=row.type,
                audience=tuple(row.audience),
                owner=row.owner,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                updated_at=row.updated_at,
                body=row.body,
            )

    async def overview(
        self, *, recruiter_id: str | None, department: str | None, since: datetime
    ) -> OverviewRecord:
        async with self._database.session() as session:
            runs = select(func.count()).select_from(RunRow).join(
                EmployeeRow, EmployeeRow.id == RunRow.employee_id
            )
            runs = _scope_runs(runs, recruiter_id, department)
            active = await session.scalar(runs.where(RunRow.status == "active"))
            completed = await session.scalar(runs.where(RunRow.status == "completed"))

            assessments = select(
                AuditRow.fields["level"].astext, func.count()
            ).where(AuditRow.name == "risk_assessed", AuditRow.at >= since)
            if recruiter_id is not None or department is not None:
                assessments = assessments.join(
                    EmployeeRow, EmployeeRow.id == AuditRow.fields["employee_id"].astext
                ).where(*employee_scope_filters(recruiter_id, department))
            level_rows = (
                await session.execute(assessments.group_by(literal_column("1")))
            ).all()
            levels: dict[str, int] = {str(level): int(total) for level, total in level_rows}

            unanswered = await session.scalar(
                select(func.count())
                .select_from(QuestionRow)
                .join(EmployeeRow, EmployeeRow.id == QuestionRow.employee_id)
                .where(
                    QuestionRow.answered.is_(False),
                    *employee_scope_filters(recruiter_id, department),
                )
            )
            resolved = await session.scalar(
                select(func.count())
                .select_from(QuestionRow)
                .join(EmployeeRow, EmployeeRow.id == QuestionRow.employee_id)
                .where(
                    QuestionRow.resolved_at.is_not(None),
                    QuestionRow.resolved_at >= since,
                    *employee_scope_filters(recruiter_id, department),
                )
            )

            tags_statement = text(
                """
                SELECT tag, count(*) AS total
                FROM audit_log, jsonb_array_elements_text(fields -> 'tags') AS tag
                WHERE name = 'risk_assessed' AND at >= :since AND fields -> 'tags' <> '[]'
                GROUP BY tag ORDER BY total DESC, tag LIMIT 5
                """
            )
            tags = tuple(
                (str(tag), int(total))
                for tag, total in (await session.execute(tags_statement, {"since": since})).all()
            )
            return OverviewRecord(
                active_runs=int(active or 0),
                completed_runs=int(completed or 0),
                high_risk=int(levels.get("high", 0)),
                medium_risk=int(levels.get("medium", 0)),
                unanswered_questions=int(unanswered or 0),
                resolved_questions=int(resolved or 0),
                top_tags=tags,
            )

    async def digest(
        self,
        *,
        recruiter_id: str | None,
        department: str | None,
        since: datetime,
        limit: int = 50,
    ) -> tuple[DigestRecord, ...]:
        """Signals that deserve a human this week, newest first, one row per employee and step."""
        async with self._database.session() as session:
            statement = (
                select(AuditRow, EmployeeRow.name, EmployeeRow.department)
                .join(EmployeeRow, EmployeeRow.id == AuditRow.fields["employee_id"].astext)
                .where(
                    AuditRow.name == "risk_assessed",
                    AuditRow.at >= since,
                    *employee_scope_filters(recruiter_id, department),
                )
                .order_by(desc(AuditRow.at), desc(AuditRow.id))
                .limit(500)
            )
            rows = (await session.execute(statement)).all()
        quotes: dict[tuple[str, str], str] = {}
        for event, _, _ in rows:
            key = (
                str(event.fields.get("employee_id", "")),
                str(event.fields.get("step", "")),
            )
            quote = _quote(event.fields.get("evidence"))
            if quote is not None:
                quotes.setdefault(key, quote)
        seen: set[tuple[str, str]] = set()
        items: list[DigestRecord] = []
        for event, name, department_name in rows:
            if event.fields.get("level") not in ("high", "medium"):
                continue
            employee_id = str(event.fields.get("employee_id", ""))
            step_id = str(event.fields.get("step", ""))
            if (employee_id, step_id) in seen:
                continue
            seen.add((employee_id, step_id))
            items.append(
                DigestRecord(
                    employee_id=employee_id,
                    employee_name=name,
                    department=department_name,
                    run_id=str(event.fields.get("run_id", "")),
                    step_id=step_id,
                    step_title=str(event.fields.get("step_title") or step_id),
                    level=str(event.fields.get("level", "")),
                    reasons=_texts(event.fields.get("reasons")),
                    tags=_texts(event.fields.get("tags")),
                    quote=_quote(event.fields.get("evidence"))
                    or quotes.get((employee_id, step_id)),
                    at=event.at,
                )
            )
            if len(items) >= limit:
                break
        return tuple(items)

    async def questions(
        self,
        *,
        recruiter_id: str | None,
        answered: bool | None,
        limit: int,
        department: str | None = None,
        employee_id: str | None = None,
    ) -> tuple[QuestionRecord, ...]:
        records, _ = await self.questions_page(
            recruiter_id=recruiter_id,
            answered=answered,
            limit=limit,
            department=department,
            employee_id=employee_id,
        )
        return records

    async def questions_page(
        self,
        *,
        recruiter_id: str | None,
        answered: bool | None,
        limit: int,
        department: str | None = None,
        employee_id: str | None = None,
        after: QuestionCursor | None = None,
        assignee: str | None = None,
        unassigned: bool = False,
    ) -> tuple[tuple[QuestionRecord, ...], bool]:
        statement = _question_query(
            recruiter_id=recruiter_id,
            department=department,
            answered=answered,
            employee_id=employee_id,
            assignee=assignee,
            unassigned=unassigned,
        )
        if after is not None:
            statement = statement.where(_after_question(after))
        async with self._database.session() as session:
            rows = await session.execute(
                statement.add_columns(EmployeeRow.name)
                .order_by(
                    QuestionRow.answered.asc(),
                    desc(QuestionRow.asked_at),
                    desc(QuestionRow.id),
                )
                .limit(limit + 1)
            )
            all_rows = rows.all()
            records = tuple(
                QuestionRecord(
                    id=question.id,
                    employee_id=question.employee_id or "",
                    employee_name=name,
                    text=question.text,
                    answered=question.answered,
                    reason=question.reason,
                    citations=list(question.citations),
                    asked_at=question.asked_at,
                    resolved_at=question.resolved_at,
                    resolved_by=question.resolved_by,
                    assignee=question.assignee,
                )
                for question, name in all_rows[:limit]
            )
        return records, len(all_rows) > limit

    async def questions_total(
        self,
        *,
        recruiter_id: str | None,
        answered: bool | None,
        department: str | None = None,
        employee_id: str | None = None,
        assignee: str | None = None,
        unassigned: bool = False,
    ) -> int:
        statement = _question_query(
            recruiter_id=recruiter_id,
            department=department,
            answered=answered,
            employee_id=employee_id,
            assignee=assignee,
            unassigned=unassigned,
        )
        counter = select(func.count()).select_from(statement.subquery())
        async with self._database.session() as session:
            return int(await session.scalar(counter) or 0)


def _employee_query(
    recruiter_id: str | None,
    department: str | None,
    *,
    status_filter: str | None = None,
    search: str | None = None,
) -> Any:
    statement = select(EmployeeRow)
    for condition in employee_scope_filters(recruiter_id, department):
        statement = statement.where(condition)
    statement = _filter_employees(statement, status_filter=status_filter, search=search)
    return statement.order_by(desc(EmployeeRow.created_at), desc(EmployeeRow.id))


def _filter_employees(
    statement: Any, *, status_filter: str | None, search: str | None
) -> Any:
    if status_filter is not None:
        statement = statement.where(EmployeeRow.status == status_filter)
    if search:
        pattern = f"%{_escape_like(search.strip())}%"
        statement = statement.where(
            or_(
                EmployeeRow.name.ilike(pattern, escape="\\"),
                EmployeeRow.role.ilike(pattern, escape="\\"),
                EmployeeRow.department.ilike(pattern, escape="\\"),
                EmployeeRow.id.ilike(pattern, escape="\\"),
            )
        )
    return statement


def employee_record(row: EmployeeRow) -> EmployeeRecord:
    return EmployeeRecord(
        employee_id=row.id,
        name=row.name,
        role=row.role,
        department=row.department,
        recruiter_id=row.recruiter_id,
        started_at=row.started_at,
        audience=tuple(row.audience),
        scenario_id=row.scenario_id,
        status=row.status,
        left_at=row.left_at,
        created_at=row.created_at,
    )


def _texts(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _quote(value: object) -> str | None:
    """The employee's own words, so the digest is evidence rather than a label."""
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def employee_scope_filters(recruiter_id: str | None, department: str | None) -> tuple[Any, ...]:
    """SQL predicates that keep an employee row inside the caller's scope."""
    filters: list[Any] = []
    if recruiter_id is not None:
        filters.append(EmployeeRow.recruiter_id == recruiter_id)
    if department is not None:
        filters.append(EmployeeRow.department == department)
    return tuple(filters)


def _question_query(
    *,
    recruiter_id: str | None,
    department: str | None,
    answered: bool | None,
    employee_id: str | None,
    assignee: str | None = None,
    unassigned: bool = False,
) -> Any:
    statement = select(QuestionRow).join(
        EmployeeRow, EmployeeRow.id == QuestionRow.employee_id
    )
    for condition in employee_scope_filters(recruiter_id, department):
        statement = statement.where(condition)
    if answered is not None:
        statement = statement.where(QuestionRow.answered == answered)
    if employee_id is not None:
        statement = statement.where(QuestionRow.employee_id == employee_id)
    if assignee is not None:
        statement = statement.where(QuestionRow.assignee == assignee)
    if unassigned:
        statement = statement.where(QuestionRow.assignee.is_(None))
    return statement


def _after_question(cursor: QuestionCursor) -> Any:
    """Rows that sort after the cursor: unanswered first, then newest asked, then highest id.

    Postgres compares row values in one direction only, and this order mixes directions, so the
    predicate is spelled out instead of using a row-value comparison. ``answered`` is a boolean
    column, and SQLAlchemy refuses an ordering comparison against a Python ``bool``, so the order
    is spelled as a rank: unanswered is 0, answered is 1.
    """
    rank = case((QuestionRow.answered.is_(False), 0), else_=1)
    position = 0 if not cursor.answered else 1
    return or_(
        rank > position,
        and_(
            rank == position,
            or_(
                QuestionRow.asked_at < cursor.asked_at,
                and_(
                    QuestionRow.asked_at == cursor.asked_at,
                    QuestionRow.id < cursor.id,
                ),
            ),
        ),
    )


def _filter_runs(
    statement: Any, *, active: bool | None, search: str | None
) -> Any:
    """The employee list's own filters, applied in SQL so a page is a page of matches.

    Filtering a fetched page in the browser silently truncates the list: the fifty-first employee
    never appears. Both filters therefore travel to the database with the keyset predicate.
    """
    if active is not None:
        statement = statement.where(RunRow.status == ("active" if active else "completed"))
    if search:
        pattern = f"%{_escape_like(search.strip())}%"
        statement = statement.where(
            or_(
                EmployeeRow.name.ilike(pattern, escape="\\"),
                EmployeeRow.role.ilike(pattern, escape="\\"),
                EmployeeRow.department.ilike(pattern, escape="\\"),
                EmployeeRow.id.ilike(pattern, escape="\\"),
            )
        )
    return statement


def _escape_like(value: str) -> str:
    """A recruiter typing ``%`` searches for a percent sign, not for everything."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _scope_runs(statement: Any, recruiter_id: str | None, department: str | None) -> Any:
    for condition in employee_scope_filters(recruiter_id, department):
        statement = statement.where(condition)
    return statement


def _run_query(
    recruiter_id: str | None,
    department: str | None = None,
    *,
    active: bool | None = None,
    search: str | None = None,
) -> Any:
    statement = select(
        RunRow,
        EmployeeRow.name,
        EmployeeRow.role,
        EmployeeRow.department,
    ).join(EmployeeRow, EmployeeRow.id == RunRow.employee_id)
    for condition in employee_scope_filters(recruiter_id, department):
        statement = statement.where(condition)
    statement = _filter_runs(statement, active=active, search=search)
    # The id breaks ties: two runs saved in the same millisecond must still have one stable order.
    return statement.order_by(desc(RunRow.updated_at), desc(RunRow.id))


def _run_record(
    run: RunRow, name: str, role: str, department: str
) -> RunRecord:
    return RunRecord(
        run_id=str(run.id),
        employee_id=run.employee_id,
        name=name,
        role=role,
        department=department,
        scenario_id=run.scenario_id,
        scenario_version=run.scenario_version,
        tone=run.tone,
        step_id=run.step_id,
        entered_at=run.entered_at,
        updated_at=run.updated_at,
        active=run.status == "active",
    )


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.UUID(int=0)
