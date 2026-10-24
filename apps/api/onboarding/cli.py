"""Operator commands: index the corpus, seed employees, inspect settings.

Run as ``uv run python -m onboarding.cli <command>``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from onboarding.app.channels.max.client import MaxClient, Subscription
from onboarding.app.channels.telegram.client import TelegramClient
from onboarding.app.clock import SystemClock
from onboarding.app.container import Container, build_container
from onboarding.app.db.directory import SqlDirectory
from onboarding.app.db.kb import PostgresKnowledgeWriter
from onboarding.app.db.models import ChannelIdentityRow, EmployeeRow
from onboarding.app.db.repos import DatabaseQuestionLog, DatabaseRunRepository
from onboarding.app.knowledge.contextual import LlmContextualizer
from onboarding.app.knowledge.extract.media import media_type_for
from onboarding.app.knowledge.extract.ocr import build_ocr
from onboarding.app.knowledge.extract.pdf import PdfReader
from onboarding.app.knowledge.extract.pptx import PptxReader
from onboarding.app.knowledge.extract.profiles import ExtractionProfileLibrary
from onboarding.app.knowledge.extract.router import RoutingExtraction
from onboarding.app.knowledge.pipeline import ingest
from onboarding.app.settings import Settings
from onboarding.app.worker.actions import ActionExecutor
from onboarding.app.worker.answerer import AnswerOutcome
from onboarding.app.worker.service import OnboardingService
from onboarding.core.extraction import accept
from onboarding.core.models import (
    Accepted,
    Address,
    Channel,
    ChatId,
    EmployeeId,
    EmployeeProfile,
    Event,
    EventKind,
    Expects,
    Keyboard,
    QuestionKind,
    StepKind,
)
from onboarding.ports import (
    DocumentRef,
    ExtractionUnavailableError,
    OutboundMessage,
    Sender,
)

ROOT = Path(__file__).resolve().parents[3]
# The demo walks the scenario through the MAX adapter's address: seeded employees are MAX users.
DEMO_CHANNEL = Channel.MAX


def _address(chat_id: ChatId) -> Address:
    return Address(channel=DEMO_CHANNEL, chat_id=chat_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onboarding")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="index the knowledge corpus")
    ingest_parser.add_argument("--dir", type=Path, default=None)
    ingest_parser.add_argument("--max-chars", type=int, default=1200)
    ingest_parser.add_argument("--overlap-chars", type=int, default=200)

    seed_parser = sub.add_parser("seed", help="load employees from a JSON file")
    seed_parser.add_argument("--file", type=Path, required=True)

    demo_parser = sub.add_parser("demo", help="populate the cabinet with demo runs")
    demo_parser.add_argument(
        "--reset",
        action="store_true",
        help="clear runs, questions, events, jobs and audit rows first (local only)",
    )
    demo_parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the destructive --reset without a prompt",
    )

    subscribe_parser = sub.add_parser("subscribe", help="register the MAX webhook subscription")
    subscribe_parser.add_argument("--url", required=True, help="public HTTPS webhook URL")
    subscribe_parser.add_argument(
        "--types",
        default="message_created,bot_started",
        help="comma-separated MAX update types",
    )

    webhook_parser = sub.add_parser(
        "webhook", help="point a messenger at this deployment's inbound route"
    )
    webhook_parser.add_argument("--channel", required=True, choices=["telegram", "vk"])
    webhook_parser.add_argument(
        "--url", required=True, help="public HTTPS URL, e.g. https://host/webhook/telegram"
    )

    extract_parser = sub.add_parser(
        "extract", help="read one file and report what the pipeline would do with it"
    )
    extract_parser.add_argument("--file", type=Path, required=True)
    extract_parser.add_argument(
        "--profile", default=None, help="extraction profile name; defaults to EXTRACTION_PROFILE"
    )

    sub.add_parser("check", help="validate settings, scenarios, and the extraction profile")

    args = parser.parse_args(argv)
    settings = Settings()
    commands = {
        "ingest": lambda: asyncio.run(_ingest(settings, args)),
        "seed": lambda: asyncio.run(_seed(settings, args.file)),
        "subscribe": lambda: asyncio.run(_subscribe(settings, args)),
        "webhook": lambda: asyncio.run(_webhook(settings, args)),
        "demo": lambda: asyncio.run(_demo(settings, reset=args.reset, assume_yes=args.yes)),
        "extract": lambda: asyncio.run(_extract(settings, args)),
    }
    command = commands.get(args.command)
    return _check(settings) if command is None else command()


async def _ingest(settings: Settings, args: argparse.Namespace) -> int:
    container = build_container(settings)
    contextualizer = None
    if settings.contextual_retrieval:
        contextualizer = LlmContextualizer(
            llm=container.llm,
            prompts=container.prompts,
            prompt_version=settings.contextual_prompt_version,
            max_context_chars=settings.contextual_context_max_chars,
        )
    try:
        report = await ingest(
            directory=args.dir or settings.knowledge_dir,
            schema_path=settings.contracts_dir / "doc.schema.json",
            writer=PostgresKnowledgeWriter(container.database, container.embedder),
            embedder=container.embedder,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
            contextualizer=contextualizer,
        )
    finally:
        await container.aclose()
    suffix = f", {report.contextualized} contextualized" if report.contextualized else ""
    print(f"indexed {report.documents} documents, {report.chunks} chunks{suffix}")
    return 0


async def _subscribe(settings: Settings, args: argparse.Namespace) -> int:
    container = build_container(settings)
    try:
        sender = container.senders.get(Channel.MAX)
        if not isinstance(sender, MaxClient):
            raise SystemExit("the MAX channel is not configured")
        secret = settings.max_webhook_secret
        if secret is None:
            raise SystemExit("MAX_WEBHOOK_SECRET is not set")
        await sender.subscribe(
            Subscription(
                url=args.url,
                update_types=tuple(part.strip() for part in args.types.split(",") if part),
                secret=secret,
            )
        )
    finally:
        await container.aclose()
    print(f"subscribed {args.url}")
    return 0


async def _webhook(settings: Settings, args: argparse.Namespace) -> int:
    """Register the inbound route. Telegram can do it over the API; VK asks the operator."""
    channel = Channel(args.channel)
    if channel not in settings.channels:
        raise SystemExit(f"{channel.value} is not enabled: add it to CHANNELS")
    if channel is Channel.VK:
        print(f"Set the callback URL to {args.url} in the community settings.")
        print("It must equal VK_CONFIRMATION_CODE, and VK_WEBHOOK_SECRET must match too.")
        return 0
    container = build_container(settings)
    try:
        sender = container.senders.get(Channel.TELEGRAM)
        if not isinstance(sender, TelegramClient):
            raise SystemExit("the Telegram channel is not configured")
        secret = settings.telegram_webhook_secret
        if not secret.get_secret_value():
            raise SystemExit("TELEGRAM_WEBHOOK_SECRET is not set")
        await sender.set_webhook(args.url, secret)
    finally:
        await container.aclose()
    print(f"webhook registered: {args.url}")
    return 0


async def _demo(settings: Settings, *, reset: bool, assume_yes: bool) -> int:
    if settings.environment != "local":
        raise SystemExit("demo data is only allowed with ENVIRONMENT=local")
    if reset and not assume_yes:
        raise SystemExit("--reset is destructive: re-run with --reset --yes")
    path = ROOT / "infra" / "demo" / "employees.json"
    await _seed(settings, path)
    container = build_container(settings)
    try:
        if reset:
            db_target = make_url(settings.database_url).render_as_string(hide_password=True)
            print(f"resetting runtime tables in {db_target}")
            async with container.database.session() as session:
                await session.execute(
                    text(
                        "TRUNCATE messages, jobs, events, questions, audit_log, runs "
                        "RESTART IDENTITY CASCADE"
                    )
                )
        service = _demo_service(container)
        questions = DatabaseQuestionLog(container.database)
        directory = SqlDirectory(container.database)
        now = SystemClock().now()

        for employee_id, name, chat_id, target in (
            ("1001", "Анна Смирнова", ChatId(1001), "day_three_survey"),
            ("1002", "Пётр Кузнецов", ChatId(1002), "day_three_survey"),
            ("1003", "Мария Волкова", ChatId(1003), "documents_checklist"),
        ):
            employee = EmployeeId(employee_id)
            if await DatabaseRunRepository(container.database).find_active_by_employee(employee):
                print(f"skip {name}: already has an active run")
                continue
            if not (await service.start(employee, _address(chat_id))).handled:
                continue
            await _drive(container, service, employee, _address(chat_id), target=target, now=now)
            if target is not None and target.endswith("_survey"):
                await _answer_survey(
                    container,
                    service,
                    employee,
                    _address(chat_id),
                    score=3 if employee_id == "1002" else 6,
                    free_text=(
                        "руководитель не отвечает третий день, нет доступа к 1С"
                        if employee_id == "1002"
                        else "много задач сразу, не хватает времени на обучение"
                    ),
                    now=now,
                )

        await _demo_question(
            container,
            questions,
            directory=directory,
            employee_id=EmployeeId("1001"),
            chat_id=ChatId(1001),
            text="Сколько дней отпуска в первый год?",
            now=now,
            require_citation=True,
            expect_reason="answered",
            expect_doc="hr/leave-policy#0",
        )
        await _demo_question(
            container,
            questions,
            directory=directory,
            employee_id=EmployeeId("1001"),
            chat_id=ChatId(1001),
            text="Кто мой наставник?",
            now=now,
            expect_escalated=True,
        )
        await _demo_question(
            container,
            questions,
            directory=directory,
            employee_id=EmployeeId("1003"),
            chat_id=ChatId(1003),
            text="Какая у меня будет зарплата после испытательного срока?",
            now=now,
            expect_reason="restricted",
        )
    finally:
        await container.aclose()
    print("demo data is ready: 3 employees, three questions in the queue, two risk signals")
    print("open the cabinet and the risk page: #/risk")
    return 0


async def _demo_question(
    container: Container,
    questions: DatabaseQuestionLog,
    *,
    directory: SqlDirectory,
    employee_id: EmployeeId,
    chat_id: ChatId,
    text: str,
    now: datetime,
    require_citation: bool = False,
    expect_reason: str | None = None,
    expect_escalated: bool = False,
    expect_doc: str | None = None,
) -> None:
    """Ask the real pipeline so the cabinet shows observed citations, not fixtures."""
    profile = await directory.profile(employee_id)
    if profile is None:
        raise SystemExit(f"demo employee {employee_id} is not seeded")
    outcome = await _demo_answer(container, text, profile, now)
    if require_citation and not outcome.citations:
        raise SystemExit(
            "no citation: run `make ingest` before `make demo` "
            f"(reason={outcome.reason}, retrieved={len(outcome.retrieved)})"
        )
    if expect_escalated and not outcome.escalated:
        raise SystemExit(
            f"demo question {text!r}: expected a refusal, got {outcome.reason} "
            f"with citations {outcome.citations}"
        )
    if expect_reason is not None and outcome.reason != expect_reason:
        raise SystemExit(
            f"demo question {text!r}: expected {expect_reason}, got {outcome.reason} "
            f"(retrieved={len(outcome.retrieved)})"
        )
    citations = {str(citation) for citation in outcome.citations}
    if expect_doc is not None and expect_doc not in citations:
        raise SystemExit(f"demo question {text!r}: expected citation {expect_doc}, got {citations}")
    await questions.record_question(
        employee_id=employee_id,
        address=_address(chat_id),
        text=text,
        answered=not outcome.escalated,
        reason=outcome.reason,
        citations=[str(citation) for citation in outcome.citations],
        latency_ms=outcome.completion.latency_ms if outcome.completion else None,
    )


async def _demo_answer(
    container: Container,
    text: str,
    profile: EmployeeProfile,
    now: datetime,
    attempts: int = 3,
) -> AnswerOutcome:
    """A demo must survive a provider hiccup: retry an unavailable answer, never fake it."""
    outcome: AnswerOutcome | None = None
    for attempt in range(attempts):
        outcome = await container.answerer.answer(text, profile, now.date())
        if outcome.reason != "unavailable":
            return outcome
        if attempt + 1 < attempts:
            await asyncio.sleep(1.5 * (attempt + 1))
    assert outcome is not None
    return outcome


async def _answer_survey(
    container: Container,
    service: OnboardingService,
    employee: EmployeeId,
    address: Address,
    *,
    score: int,
    free_text: str,
    now: datetime,
) -> None:
    """Answer the survey the way a real employee would: buttons, a score, a reason."""
    runs = DatabaseRunRepository(container.database)
    survey_id: str | None = None
    for _ in range(12):
        stored = await runs.find_active_by_employee(employee)
        if stored is None:
            return
        scenario = container.catalog.get(
            stored.state.scenario_id, stored.state.scenario_version
        )
        step = scenario.step(stored.state.step_id)
        if step.kind is not StepKind.SURVEY or not step.questions:
            return
        if survey_id is None:
            survey_id = step.id
        elif step.id != survey_id:
            return
        if stored.state.pending_reason:
            event = Event(kind=EventKind.MESSAGE_RECEIVED, at=now, text=free_text)
        else:
            question = step.questions[min(stored.state.question_index, len(step.questions) - 1)]
            if question.kind is QuestionKind.CHOICE and question.options:
                option = next(
                    (candidate for candidate in question.options if candidate.id in {"no", "bad"}),
                    question.options[-1],
                )
                event = Event(
                    kind=EventKind.BUTTON_PRESSED,
                    at=now,
                    button_id=f"q_{question.id}_{option.id}",
                )
            elif question.kind is QuestionKind.SCALE:
                event = Event(kind=EventKind.MESSAGE_RECEIVED, at=now, text=str(score))
            else:
                event = Event(kind=EventKind.MESSAGE_RECEIVED, at=now, text=free_text)
        await service.handle(employee, address, event)


async def _drive(
    container: Container,
    service: OnboardingService,
    employee: EmployeeId,
    address: Address,
    *,
    target: str | None,
    now: datetime,
) -> None:
    """Walk the scenario with synthetic replies until ``target`` or the terminal step."""

    runs = DatabaseRunRepository(container.database)
    for _ in range(12):
        stored = await runs.find_active_by_employee(employee)
        if stored is None:
            if target is not None:
                raise SystemExit(f"demo run for {employee} ended before {target}")
            return
        if stored.state.step_id == target:
            return
        scenario = container.catalog.get(stored.state.scenario_id, stored.state.scenario_version)
        step = scenario.step(stored.state.step_id)
        if step.expects is Expects.FILE:
            event = Event(kind=EventKind.FILE_RECEIVED, at=now, file_id="demo-file")
        elif step.expects is Expects.BUTTON:
            if not step.keyboard:
                raise SystemExit(f"demo step {step.id} expects a button but offers none")
            event = Event(
                kind=EventKind.BUTTON_PRESSED, at=now, button_id=step.keyboard[0][0].id
            )
        else:
            event = Event(kind=EventKind.MESSAGE_RECEIVED, at=now, text="готово")
        await service.handle(employee, address, event)
    raise SystemExit(f"demo run for {employee} did not reach {target or 'the terminal step'}")


def _demo_service(container: Container) -> OnboardingService:
    return OnboardingService(
        runs=DatabaseRunRepository(container.database),
        catalog=container.catalog,
        executor=ActionExecutor(
            messaging=_Discard(),
            answerer=container.answerer,
            copy=container.copy,
            audit=container.audit,
            questions=DatabaseQuestionLog(container.database),
        ),
        clock=SystemClock(),
        directory=SqlDirectory(container.database),
        audit=container.audit,
    )


class _Discard(Sender):
    """The demo writes state, not chat history: nothing leaves the process."""

    async def send(self, message: OutboundMessage) -> str:
        del message
        return "demo"

    async def edit(
        self, address: Address, message_id: str, text: str, keyboard: Keyboard = ()
    ) -> None:
        del address, message_id, text, keyboard


async def _seed(settings: Settings, path: Path) -> int:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"{path}: expected a list of employees")
    rows = [_employee_row(item) for item in raw]
    container = build_container(settings)
    try:
        statement = insert(EmployeeRow).values(rows)
        async with container.database.session() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[EmployeeRow.id],
                    set_={
                        "name": statement.excluded.name,
                        "role": statement.excluded.role,
                        "department": statement.excluded.department,
                        "recruiter_id": statement.excluded.recruiter_id,
                        "started_at": statement.excluded.started_at,
                        "audience": statement.excluded.audience,
                        "scenario_id": statement.excluded.scenario_id,
                    },
                )
            )
            # A seeded employee talks through one MAX account whose id is the employee id, which is
            # the rule the migration backfills (ADR 0019).
            await session.execute(
                insert(ChannelIdentityRow)
                .values(
                    [
                        {
                            "channel": DEMO_CHANNEL.value,
                            "external_id": str(row["id"]),
                            "employee_id": str(row["id"]),
                        }
                        for row in rows
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[ChannelIdentityRow.channel, ChannelIdentityRow.external_id]
                )
            )
    finally:
        await container.aclose()
    print(f"seeded {len(rows)} employees")
    return 0


def _employee_row(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise SystemExit("each employee must be an object")
    return {
        "id": str(item["id"]),
        "name": str(item["name"]),
        "role": str(item["role"]),
        "department": str(item["department"]),
        "recruiter_id": str(item["recruiter_id"]),
        "started_at": date.fromisoformat(str(item["started_at"])),
        "audience": [str(value) for value in item["audience"]],
        "scenario_id": str(item.get("scenario_id", "onboarding_default")),
    }


async def _extract(settings: Settings, args: argparse.Namespace) -> int:
    """Dry run: no database, no upload. Useful before HR commits a scanned regulation."""
    library = ExtractionProfileLibrary(
        settings.extraction_profiles_dir,
        settings.contracts_dir / "extraction-profile.schema.json",
    )
    profile = library.load(args.profile or settings.extraction_profile)
    path: Path = args.file
    content = path.read_bytes()
    extraction = RoutingExtraction(
        readers=(PdfReader(), PptxReader()),
        ocr=build_ocr(profile.family),
        max_pages=settings.extraction_max_pages,
    )
    try:
        document = await extraction.extract(
            content,
            DocumentRef(
                blob_id="local",
                filename=path.name,
                media_type=media_type_for(path.name),
            ),
            profile,
        )
    except ExtractionUnavailableError as error:
        print(f"extraction profile {profile.name!r} cannot read this file: {error}")
        return 2
    outcome = accept(document, profile.acceptance)
    summary = {
        "file": str(path),
        "profile": profile.name,
        "route": document.route.value,
        "engine": document.engine,
        "pages": len(document.pages),
        "accepted": isinstance(outcome, Accepted),
        "reason": None if isinstance(outcome, Accepted) else outcome.reason.value,
        "characters": len(outcome.text) if isinstance(outcome, Accepted) else 0,
        "min_confidence": round(outcome.min_confidence, 4)
        if isinstance(outcome, Accepted)
        else 0.0,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if isinstance(outcome, Accepted) else 1


def _check(settings: Settings) -> int:

    container = build_container(settings)
    try:
        print(f"scenarios: {', '.join(container.catalog.ids())}")
        print(f"prompts: {settings.prompts_dir}")
        print(f"knowledge: {settings.knowledge_dir}")
        print(
            "extraction: "
            f"{container.extractor.profile.name} "
            f"(family {container.extractor.profile.family})"
        )
    finally:
        asyncio.run(container.aclose())
    return 0


if __name__ == "__main__":
    sys.exit(main())
