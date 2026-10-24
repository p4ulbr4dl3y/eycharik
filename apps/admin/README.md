# Recruiter cabinet (web)

The human side of the MAX onboarding assistant. React 18 + TypeScript + Vite + TanStack Query.
The cabinet reads the admin API, shows where each newcomer is, which answers need a person, and lets
HR index a knowledge document. It never talks to MAX and it never sends chat messages.

## Run

```bash
npm install
npm run dev          # :5173, proxies /admin/api to http://localhost:8000
npm run preview:demo # :5173, dev-only API with the documented cohort, no database
npm run typecheck    # tsc -b --noEmit
npm run build        # tsc -b + vite build
npm run lint         # eslint, including jsx-a11y
npm run test         # vitest, jsdom
npm run e2e          # playwright against preview:demo, plus axe on every screen
```

`npm run dev` is the real frontend: it needs the API and its PostgreSQL. `npm run preview:demo` is a
design/review tool; see [Preview mode](#preview-mode). For the full Docker Compose flow (empty
database, `demo-data`, `demo-data-del`), see [`../../README.md`](../../README.md).

## Routes

The URL hash is the router; there is no router dependency.

| Hash | Screen | Purpose |
|---|---|---|
| `#/overview` | Overview | Seven-day snapshot, risks, queue, topics, new hires |
| `#/runs` | Employees | Active and completed runs, search, filters |
| `#/run/<run_id>` | Employee detail | Step, facts, questions, audit timeline |
| `#/questions` | Questions | Queue by status and by owner (`&owner=me`, `&owner=unassigned`), reasons, citations, claim |
| `#/risk` | Risks | Counters, weekly digest, risk topics |
| `#/knowledge` | Knowledge | Upload, list, open and edit indexed documents |

The default route is `#/overview`. The gate is shown before any route when the session cookie is
missing or expired. Filters live in the query string (`#/questions?status=answered`), so a screen is
a link someone can send.

An address that names no section renders the not-found screen (`#/nonsense`), never the overview: a
stale bookmark must not look like a working link. A section the role cannot read says so instead of
rendering an empty main. Every navigation sets `document.title` and moves focus to `main`, because a
hash change does not reload the page and a screen reader would otherwise stay on the old link.

## Release and the open tab

`index.html` and `/version.json` are served `no-store`; `/assets/*` is content-addressed and cached
for a year. A deploy therefore never breaks an open tab, but the tab keeps running the old code.

- `vite.config.ts` bakes `VITE_BUILD_ID` (default: `git rev-parse --short HEAD`) into the bundle as
  `__BUILD_ID__` and emits `version.json` with the same value.
- The shell polls `/version.json` every five minutes while the tab is focused and shows a banner
  when the server reports a different build; the banner only offers a reload.
- The build id is printed in the sidebar footer, so an incident report names the code that produced
  it. `/version.json` is HTML-free JSON and inherits the same security headers as `index.html`.
- A lost network shows a banner instead of a frozen screen; queries refetch on reconnect and on
  focus.

There is no client-side error telemetry: a 5xx shows a Russian sentence and the crash boundary keeps
the shell alive, but nothing leaves the browser. Wiring that up needs an endpoint in the admin API
contract first.

## Authentication and tokens

The gate posts the token once and gets an HttpOnly cookie back
([`docs/decisions/0018`](../../docs/decisions/0018-session-cookie-for-the-cabinet.md)); script cannot
read the token afterwards and every later request carries the cookie:

```http
POST /admin/api/session   {"token": "…"}   → 204 Set-Cookie: onboarding_session=…
GET  /admin/api/runs                        → cookie, no header
```

A bearer header is still accepted, so `curl` and the tests keep working. The token is opaque: what a
role may do is read from `GET /admin/api/me`, which returns `capabilities`, and the cabinet hides
what it may not use.

The server maps tokens to `(role, subject)` from `ADMIN_TOKENS`, a comma-separated list of
`token:role:subject` entries:

```dotenv
ADMIN_TOKENS=dev-recruiter-token:recruiter:rec-1,dev-hr-token:hr_admin:hr-1
```

| Role | Subject | Scope |
|---|---|---|
| `recruiter` | recruiter id, e.g. `rec-1` | Employees whose `recruiter_id` equals the subject |
| `hr_admin` | HR identity, e.g. `hr-1` | Every employee, every question, every knowledge document |

`Settings.admin_principals` accepts all three. A `manager` token's subject is a department name
(`ADMIN_TOKENS=dev-manager-token:manager:Производство`); the cabinet filters every list by that
department in SQL.

Status codes the frontend relies on:

| Code | Meaning | Frontend behaviour |
|---|---|---|
| `401` | Missing or unknown token | Clear `onboarding.admin.token`, show the gate |
| `403` | Role may not perform the mutation | Say "недостаточно прав"; the UI should not have offered it |
| `404` | Run does not exist **or** is outside the caller's scope | Show the detail; never guess that another recruiter's employee exists |

A run outside the scope is deliberately `404`, not `403`.

### Why the preview has two tokens

They are not two factors for one HR. They are two different scopes:

- `dev-recruiter-token` — role `recruiter`, subject `rec-1`: sees only Anna and Peter.
- `dev-hr-token` — role `hr_admin`: sees Maria as well, plus the `hr_only` document.

The second token exists to prove that scoping happens in SQL, not in the UI: sign in as the
recruiter and Maria disappears. For ordinary HR work one token is enough.

### Production tokens

Issue one token per person, not one shared token per role. A recruiter's subject must match
`employees.recruiter_id`; an HR token is unscoped. Use long random values, rotate them with a
deploy, and keep them in the server environment. Example generation:

```bash
openssl rand -hex 32
```

The token is never stored in the page: it exists for the length of one form submit. The cookie is
`HttpOnly`, `SameSite=Strict`, `Secure` outside local development, and scoped to `/admin/api`. A
`401` (an expired token, a restarted server) drops the cabinet back to the gate.

### Token vs MAX bot token

Do not confuse the two:

| Variable | Who uses it | Where it lives |
|---|---|---|
| `ADMIN_TOKENS` | recruiters and HR reading this cabinet | server env and the user's browser |
| `MAX_BOT_TOKEN` | the API/worker sending messages to MAX | server env only, never the browser |
| `MAX_WEBHOOK_SECRET` | MAX proving a webhook call | server env only |

The frontend has no MAX credentials at all.

## API surface

The contract of record is [`docs/contracts/admin-api.md`](../../docs/contracts/admin-api.md). If a
screen needs a field the contract does not have, change the contract and the server first; never
guess a shape in the client.

| Method and path | Returns |
|---|---|
| `GET /admin/api/runs?limit=50` | `{ items: RunSummary[] }`, newest activity first |
| `GET /admin/api/runs/{run_id}` | `RunDetail`: summary + scenario, tone, step message, events, questions |
| `GET /admin/api/questions?status=unanswered&limit=50&assignee=any` | `{ items: Question[], total, next_cursor }`; status is `unanswered`, `answered`, `all`; assignee is `any`, `me`, `unassigned` |
| `PATCH /admin/api/questions/{id}/assignee` | `{ assignee }`: claim, hand over, or clear with `null` |
| `GET /admin/api/analytics/overview` | Seven-day counters and `top_tags` |
| `GET /admin/api/digest/weekly?days=7` | `{ items: DigestItem[], since }` |
| `GET /admin/api/v1/knowledge` | `{ items: KnowledgeDocument[] }` |
| `GET /admin/api/v1/knowledge/{document_id}` | `KnowledgeDocumentDetail`: metadata plus source `text`; `hr_only` is a `404` for non-HR |
| `POST /admin/api/v1/knowledge` | `202 { content_hash, status }`; `hr_admin` only |
| `PUT /admin/api/v1/knowledge/{document_id}` | `202 { content_hash, status }`; `hr_admin` only, frontmatter `id` must match |
| `POST /admin/api/v1/knowledge/files` | `202 { content_hash, status }`; PDF/PPTX, `hr_admin` only |
| `GET /admin/api/v1/knowledge/files/{content_hash}` | extraction status, refusal reason included |
| `GET /healthz`, `/readyz` | Liveness/readiness, no auth |

`limit` is bounded to `1..200`. There is no cursor pagination: the cabinet asks for the newest 50
and the cohort is one hire batch. Add a cursor before raising the cap.

Timestamps are UTC ISO 8601 strings. `src/format.ts` formats them for the reader; the client never
recomputes them.

## Knowledge documents

HR uploads markdown with YAML frontmatter or a PDF/deck; the API validates the metadata and queues
indexing in the worker. Clicking an active document in the cabinet opens the exact source markdown
the index was built from. HR can edit it in place; saving validates the frontmatter, requires the
same `id`, and queues a re-index. A re-index replaces the document's chunks atomically, so the old
and new versions are never retrievable at the same time.

### Frontmatter

The schema is [`docs/contracts/doc.schema.json`](../../docs/contracts/doc.schema.json). Unknown
fields are rejected (`additionalProperties: false`).

| Field | Required | Type | Values |
|---|---|---|---|
| `id` | yes | string | `^[a-z0-9][a-z0-9/_-]*$`, e.g. `hr/leave-policy` |
| `title` | yes | string | Human title, minimum one character |
| `type` | yes | string | Always `knowledge` |
| `status` | yes | string | `draft`, `active`, `deprecated` |
| `owner` | yes | string | `^[a-z][a-z0-9_-]*$`, e.g. `hr`, `it`; a team slug, not a person |
| `audience` | yes | string[] | Non-empty, unique; each item is `all`, `hr_only`, or `dept:<slug>` |
| `valid_from` | yes | date | `YYYY-MM-DD`; the first day the document applies |
| `valid_to` | no | date or null | Last day the document applies; `null` means no end date |
| `source_of_truth` | no | string | Link or reference to the canonical document |
| `related` | no | string[] | Related document ids |

### What the values mean

`audience` is enforced twice: in the retrieval SQL and in the admin query. The bot must never see a
document outside the employee's audience.

| Audience | Who receives it |
|---|---|
| `all` | Every employee |
| `dept:<slug>` | Employees whose directory audience contains the same department slug |
| `hr_only` | HR only; the bot must never use it in an answer |

Use the directory's audience slug, not the Russian display name, in `dept:` values. Check the
employee's `audience` in the directory before inventing one.

`status` controls indexing:

- `active` — loaded from `knowledge/`, indexed by upload, and eligible for retrieval.
- `draft` and `deprecated` — valid in the schema, skipped by corpus loading, and rejected by the
  upload endpoint (it requires `active`). Use them in the corpus for documents that are not ready.

Validity is a retrieval predicate: `valid_from <= today` and (`valid_to is null` or
`valid_to >= today`). A future `valid_from` is indexed but not used yet.

### Upload contract

```http
POST /admin/api/knowledge
Content-Type: application/json
Authorization: Bearer <hr_admin token>

{"text": "---\nid: hr/sport-compensation\ntitle: Компенсация спорта\ntype: knowledge\nstatus: active\nowner: hr\naudience: [all]\nvalid_from: 2026-10-01\n---\n\n## Спорт\n\nКомпания компенсирует часть абонемента."}
```

```json
{"id": "hr/sport-compensation", "title": "Компенсация спорта", "chunks": 1}
```

- `201` means the document is indexed; the next answer can cite it as `hr/sport-compensation#0`.
- `422` returns the exact failing field, e.g.
  `upload: owner: 'HR' does not match '^[a-z][a-z0-9_-]*$'`.
- `403` means the caller is not `hr_admin`; the cabinet keeps the session and shows the detail.
- A success is audited as `knowledge_ingested` with the document id, chunk count, and subject.
- Chunking is deterministic and server-side; the response reports the number of chunks.

### Preview knowledge values

The preview fixtures mirror the documented cohort and use four documents:

| `id` | `audience` | `owner` | Visible to recruiter |
|---|---|---|---|
| `hr/leave-policy` | `all` | `hr` | yes |
| `hr/benefits-dms` | `all` | `hr` | yes |
| `it/access-and-equipment` | `all` | `it` | yes |
| `hr/sick-leave` | `hr_only` | `hr` | no |

The real corpus lives in `knowledge/` and includes company policies, HR policies, and IT access
instructions. Every file there also carries this frontmatter.

### Role scoping

`GET /knowledge` and `GET /knowledge/{document_id}` apply the `hr_only` predicate in SQL. A
recruiter opening an `hr_only` document gets a `404`, not a read-only view. Editing requires
`knowledge.write`, which only `hr_admin` holds; the server re-checks the role on every `PUT`.

## Preview mode

`npm run preview:demo` starts Vite with a dev-only API on `/admin/api/*`, so the cabinet can be
reviewed without PostgreSQL or a model provider.

- The plugin is [`preview/plugin.ts`](preview/plugin.ts); the fixtures are
  [`preview/data.ts`](preview/data.ts); the short note is [`preview/README.md`](preview/README.md).
- The fixtures mirror the cohort in `docs/product/demo-script.md`, not production data.
- Tokens: `dev-recruiter-token` (recruiter `rec-1`) and `dev-hr-token` (HR, unscoped).
- Upload in preview changes the in-memory document list only. It does not reindex a vector store and
  the bot cannot answer from it. In the real API the upload is indexed in the request.
- The plugin uses `apply: "serve"` and is imported only by `vite.config.ts`; `npm run build` never
  ships it.
- This mode is for design and interaction review. It is not evidence of retrieval quality, model
  quality, or production readiness.

`npm run dev` is the production-shaped setup: Vite proxies `/admin/api` to
`VITE_PROXY_TARGET` (default `http://localhost:8000`). The Docker image serves the built `dist/`
through nginx, which proxies `/admin/api` to the `api` service.

## UI system

The cabinet has no component library and no chart library. `src/styles.css` owns the tokens and the
few primitives; icons are inline SVG in `src/components/Icons.tsx`.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#FAF7F2` | Page background |
| `--surface` | `#FFFFFF` | Cards, sidebar, controls |
| `--accent` | `#C56A43` | Accent fills, active indicators, primary button |
| `--accent-deep` | `#9D4F2E` | Text-safe accent, gate panel |
| `--accent-soft` | `#F5E4D9` | Highlight, active nav, high-risk card |
| `--ink` | `#292524` | Primary text |
| `--ink-2` | `#57534E` | Secondary text |
| `--muted` | `#857C74` | Metadata |
| `--line` | `#EEE7DF` | Borders |

Rules of the system:

- Cards are white on cream, with one subtle border and a very light shadow. No gradients or
  decorative glass; the sticky topbar uses a light blur only for legibility.
- Numbers are tabular. Headings use tighter letter spacing; body text stays at 1.5 line height.
- Charts are CSS bars and a segmented progress rail; no canvas, no chart dependency.
- The shell is viewport-height on desktop. The content column is the only scroll container; the page
  itself never scrolls, so the sidebar and the rounded top and bottom corners stay in place.
- The sidebar is 248 px; below 1024 px it becomes an icon rail; below 760 px it becomes a fixed
  bottom navigation with the same five sections.
- On mobile, long rows (name + reason pill + time) reflow to a two-line grid, and the body clips
  horizontal overflow. This keeps the layout viewport at the device width and the fixed navigation
  on screen.
- Main lists have three distinct states: loading skeleton, explicit empty state, and an error with
  a retry. "Nothing" and "failed" never look the same.
- The gate is the only full-screen screen; the token is never prefilled.
- The topbar has one refresh action, plus a logout icon on narrow screens. There is no "live data"
  label and no footer with environment notes; the cabinet should look the same in demo and
  production.

Accessibility is part of the definition of done: a skip link, real buttons and labels, `aria-current`
on navigation, `aria-live` on counts, visible focus rings, and `prefers-reduced-motion` support.

## File map

| Path | Responsibility |
|---|---|
| `src/App.tsx` | Shell, session bootstrap, capability-filtered navigation, global refresh |
| `src/route.ts` | Hash router: parse, build, and the URL as screen state; unknown paths become `notFound` |
| `src/version.ts` | Build id, `/version.json` check, stale-build banner state |
| `src/useOnline.ts` | Browser online/offline signal for the banner |
| `src/session.ts` | Session context and `can(capability)` |
| `src/errors.ts` | Status codes to Russian, conflict detection |
| `src/config.ts` | Tenant name, scenario labels, refresh intervals |
| `src/api.ts` | Fetch wrapper, session cookie, `Unauthorized`, typed endpoints |
| `src/types.ts` | API response types; mirrors the contract |
| `src/format.ts` | Dates, Russian plurals, reason/event/step/tag labels, initials |
| `src/styles.css` | `@import`s the files below in cascade order |
| `src/styles/base.css` | Tokens, reset, focus, shell, sidebar, top bar, tab-level banner |
| `src/styles/gate.css` | The token gate |
| `src/styles/layout.css` | Page scaffolding, controls, cards |
| `src/styles/dashboard.css` | KPI, cohort charts, digest, pills |
| `src/styles/screens.css` | Runs, detail, risk, questions, knowledge, states |
| `src/styles/responsive.css` | Breakpoints, reduced motion, print — always last |
| `src/components/Icons.tsx` | Inline SVG icon set and logo mark |
| `src/components/KnowledgeDocumentDialog.tsx` | Read and edit one active knowledge document |
| `src/components/TokenGate.tsx` | Login by token |
| `src/components/Boundary.tsx` | Keeps a crashed screen from becoming a white page; remounted per route so the shell survives |
| `src/components/UpdateBanner.tsx` | Offline and stale-build strip above the shell |
| `src/components/Pills.tsx` | Status, answer, reason pills |
| `src/components/Progress.tsx` | Step progress |
| `src/components/States.tsx` | Empty, error, skeleton |
| `src/pages/OverviewPage.tsx` | Dashboard |
| `src/pages/RunsPage.tsx` | Employee list and filters |
| `src/pages/RunDetailPage.tsx` | Employee card and audit timeline |
| `src/pages/QuestionsPage.tsx` | Question queue |
| `src/pages/RiskPage.tsx` | Risk counters and weekly digest |
| `src/pages/KnowledgePage.tsx` | Knowledge upload, list, document viewer/editor |
| `src/pages/NotFoundPage.tsx` | An address the cabinet cannot read |
| `preview/` | Dev-only API and fixtures; never in a production build |

## Limits and next mutations

- Writes: resolve a question, publish a markdown document, upload a PDF or a deck (queued, then
  polled), offboard an employee. Manual messages to an employee are still not implemented.
- Escalation resolution and assignment are not implemented; the human action happens in MAX and
  the decision is tracked outside the cabinet.
- Lists are keyset-paged: a screen asks for the next page with the cursor the server returned, and
  the header prints `shown of total`. `limit` is capped at 200.
- The knowledge list hides `hr_only` documents from non-HR callers, but a recruiter still sees the
  titles of the rest: the corpus is shared, the audience is not a secret.
- No in-app notifications, exports, saved views, or assignment. Those are product decisions that
  need a contract change first.
- UI copy is Russian. Documentation is English, per the workspace rules.

## When changing the frontend

1. Read `docs/contracts/admin-api.md` and the relevant product doc before changing a screen.
2. If a field is missing, change the contract and the server first; do not invent a shape in `types.ts`.
3. Run `npm run lint`, `npm run typecheck` and `npm run test`; `make check` does all of it.
4. Keep the three list states and the accessibility rules.
5. If the change is a product claim or a measured number, add the command, environment, and commit
   to `docs/measurements/`; the preview is not a measurement.
6. Never add a MAX bot token, provider key, or real admin token to this app.
