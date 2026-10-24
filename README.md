# MAX onboarding assistant

AI assistant for employee onboarding in the MAX messenger: onboarding scenarios for newcomers,
a recruiter cockpit, and a retrieval-grounded assistant over the company knowledge base.

Built for the "AI assistant in MAX" case (ООО «Группа ПОЛИПЛАСТИК»).

## Map

| Path | What | Mutable |
|---|---|---|
| `docs/` | architecture, contracts, decisions, runbooks, evals | yes |
| `knowledge/` | non-public company corpus served to the assistant | yes, with owner review |
| `apps/api/` | the service: webhook API, scenario engine, RAG, admin API | yes |
| `apps/admin/` | recruiter cockpit | yes |
| `docs/evals/` | golden set and its runner contract | yes |
| `infra/demo/` | demo employees for `make seed` | yes |

## Start here

| Question | File |
|---|---|
| What are we building and why? | `docs/architecture.md` |
| How do I work in this repository? | `AGENTS.md` |
| Where does a fact live? | `docs/README.md` |
| What is the bot allowed to answer? | `docs/product/answer-policy.md` |

## Docker Compose: empty, demo, empty again

`docker compose up -d --build` starts PostgreSQL, migrations, the API, the worker, and the static
cabinet. It deliberately seeds nothing: the database is empty, so after login the cabinet shows
zero counts and empty lists.

Open <http://localhost:3000> and sign in with `dev-hr-token` (or `dev-recruiter-token` for the
scoped recruiter view).

The compose defaults are the local offline profile (extractive answers, hashing embeddings) and the
demo admin tokens. No `.env` is required for this empty/demo flow. For real models and MAX, copy
`.env.example` to `.env` and set the keys.

### Fill with demo data

From the repository root:

```bash
make demo-data
```

If `make` is not installed (common on Windows), use the wrapper:

```powershell
.\demo-data.cmd
```

Both run `ingest` and the demo seed inside the API image, so they need Docker Compose but not a
local Python environment. The seed creates three employees, their runs and risks, three questions,
and indexes `knowledge/`.

### Remove demo data

```bash
make demo-data-del
```

On Windows without `make`:

```powershell
.\demo-data-del.cmd
```

Both truncate the runtime tables, delete the demo employees `1001`–`1003`, and clear the indexed
knowledge (the SQL lives in `scripts/demo-data-del.sql`). The cabinet returns to the empty state.
This is a local/demo reset: it also removes knowledge documents and runtime rows, so do not run it
against data you care about.

### Full reset

```bash
docker compose down -v
docker compose up -d --build
```

`-v` drops the PostgreSQL volume; the next start is empty again. Migrations run automatically.

If `make` is not installed, the fill command is:

```bash
docker compose run --rm api python -m onboarding.cli ingest
docker compose run --rm api python -m onboarding.cli demo --reset --yes
```

## Quick commands

```bash
make install       # create the virtual environment
make check         # ruff, mypy, import contracts, unit tests, docs links, admin
make eval          # golden-set retrieval, generation, escalation
make ingest        # index knowledge/ into pgvector
make demo-data     # docker compose: ingest + three employees, risks, three questions
make demo-data-del # docker compose: return the cabinet to empty
make run           # api with reload on :8000
make worker        # job loop, outbox dispatcher, reminder tick
make cron          # one scheduler pass for reminders and the outbox (crontab-friendly)
make admin-install # cabinet dependencies
make admin-dev     # recruiter cabinet on :5173
make up            # postgres + migrate + api + worker + cabinet, no demo seed
make prod-config   # validate docker-compose.prod.yml with .env.prod
make smoke         # public health, webhook, cabinet headers, metrics exposure
make backup        # verified Postgres dump; BACKUP_S3_URI enables offsite upload
```

Offline demo in five minutes: [docs/product/demo-script.md](docs/product/demo-script.md).

Defense script for organizers: [docs/product/defense.md](docs/product/defense.md).

## Status

Working end to end against a local Postgres with pgvector and a hosted model through OpenRouter:

- **MAX webhook**: secret check, `events` dedupe, durable job enqueue, `200` in milliseconds.
- **Scenario engine**: versioned YAML pinned per run, buttons, reminders, surveys with 10-point
  scales, escalation on timeout. Twenty steps from the welcome message to the end of probation.
  The employee row picks the branch, so the plant variant (`onboarding_plant`) is live, not dead
  content: its own transport copy and no remote-work question. The welcome asks «ты» or «вы»; the
  choice is stored on the run and switches the copy of later steps.
- **Retrieval**: frontmatter/JSON Schema corpus, deterministic chunking, pgvector HNSW + Russian
  `tsvector`, RRF, hosted rerank, audience and validity as SQL predicates. Every answer carries a
  citation from the retrieved set or escalates.
- **Answering**: one model call, JSON contract, prompt version `v4`; personal questions
  ("кто мой наставник", salary, contract) escalate instead of being answered with generic policy.
- **Risk radar**: after every survey the answer is classified (hosted model with a deterministic
  keyword fallback), rules turn signals into a level, tags, and Russian reasons, and the audit log
  records `risk_assessed` / `risk_escalated`. The cabinet shows a seven-day overview and a weekly
  digest of the signals that need a human.
- **Recruiter cabinet**: runs, per-employee detail with the audit timeline, question queue scoped by
  recruiter, manager (by department), or HR; a reply closes the question and leaves through the
  outbox; HR can offboard an employee; HR can upload, open, and edit a knowledge document with
  frontmatter validation.
- **Retention**: expired questions, uploads, outbox messages, and personal audit fields are purged
  hourly by the worker; `DATA_RETENTION_DAYS` is the policy knob; offboarding is immediate and
  audited. A claimed outbox row holds a lease, so a crashed worker loses no message.
- **Scheduler**: a cron entrypoint that shares the worker's building blocks, so reminders and the
  outbox are drained even when only a periodic job is running.

![Risk radar](docs/assets/cabinet-risk.png)

| Measurement | Result | Where |
|---|---|---|
| Golden set, 16 cases, real model | recall@5 1.00, MRR 1.00, citation 1.00, escalation 1.00, p95 2 237 ms, 0.077 ₽/answer | `docs/measurements/2026-10-23-eval-full-case-corpus.md` |
| Retrieval with rerank, 12 cases | recall@5 1.00, MRR 1.00 | `docs/measurements/2026-10-23-eval-full-answer-v3-gpt-4.1-mini.md` |
| Tests | unit and integration suites; `core/` purity and API boundaries are enforced by tests | `apps/api/tests/` |

![Run detail](docs/assets/cabinet-run.png)

![Run list](docs/assets/cabinet-runs.png)

![Knowledge upload](docs/assets/cabinet-knowledge.png)

Known gaps, stated so nobody assumes otherwise:

- A real MAX bot token and the "MAX для бизнеса" verification are external dependencies. The
  adapter and the webhook are tested against the documented payloads and a local sender.
- File upload to MAX is not implemented; the scenario describes documents, the bot does not yet
  attach them.
- The retention window is a placeholder until the company's data protection policy confirms it.
  The mechanism is tested; the legal number is not ours.
- One worker replica: the MAX pacing state is in-process. More replicas need a shared limiter.
- The production model vendor must satisfy 152-ФЗ. The architecture keeps the provider behind a
  port; `docs/decisions/0010-one-model-vendor.md` records the current choice and what changes for
  an on-prem deployment.
- No production deployment has happened. Nothing here claims one.
