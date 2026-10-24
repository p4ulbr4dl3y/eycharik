# Documentation index

The single entry point. Every document in `docs/` is listed here; CI fails when a file is missing
from this table. If a question is not answered here, the answer does not exist yet — add the row.

## By question

| Question | File |
|---|---|
| What is the system made of, and how does a message travel through it? | [architecture.md](architecture.md) |
| What did the client actually ask for? | [case/poliplastic-2026.md](case/poliplastic-2026.md) |
| What do the words mean? | [glossary.md](glossary.md) |
| How do we write code, tests, and commits? | [conventions.md](conventions.md) |
| What exactly does the MAX API give us? | [contracts/max-api.md](contracts/max-api.md) |
| How does one core serve several messengers? | [contracts/channel.md](contracts/channel.md), [decisions/0019-a-channel-is-an-address.md](decisions/0019-a-channel-is-an-address.md) |
| What does Telegram give us? | [contracts/telegram-api.md](contracts/telegram-api.md) |
| What does VK give us? | [contracts/vk-api.md](contracts/vk-api.md) |
| What can one messenger carry, and where is that written? | [contracts/channel-profile.schema.json](contracts/channel-profile.schema.json), profiles in `apps/api/channel-profiles/` |
| What does the recruiter cabinet call, and with what rights? | [contracts/admin-api.md](contracts/admin-api.md) |
| What exactly does the model see? | [prompts/answer/v7.md](prompts/answer/v7.md) (current), [v6](prompts/answer/v6.md), [v5](prompts/answer/v5.md), [v4](prompts/answer/v4.md), [v3](prompts/answer/v3.md), [v2](prompts/answer/v2.md), [v1](prompts/answer/v1.md) (superseded) |
| How is a survey answer scored? | [prompts/sentiment/v1.md](prompts/sentiment/v1.md), [product/risk-radar.md](product/risk-radar.md) |
| What is the Jev classifier pilot? | [decisions/0011-jev-sentiment-pilot.md](decisions/0011-jev-sentiment-pilot.md), rubric [prompts/sentiment-jev/v1.yaml](prompts/sentiment-jev/v1.yaml) |
| How is a chunk given context before embedding? | [prompts/context/v1.md](prompts/context/v1.md) |
| What does the assistant answer, and what does it refuse? | [product/answer-policy.md](product/answer-policy.md) |
| How does sentiment become risk, escalation, and a digest? | [product/risk-radar.md](product/risk-radar.md) |
| What does the sentiment layer return? | [contracts/sentiment.schema.json](contracts/sentiment.schema.json) |
| What may a Jev rubric contain? | [contracts/jev-rubric.schema.json](contracts/jev-rubric.schema.json), rubric [prompts/sentiment-jev/v1.yaml](prompts/sentiment-jev/v1.yaml) |
| Which model runs, and what does it allow? | [contracts/model-profile.schema.json](contracts/model-profile.schema.json), profiles in `apps/api/model-profiles/` |
| What are the onboarding scenarios? | [product/scenarios.md](product/scenarios.md) |
| Which mascot image belongs to which step? | [product/scenario-images.md](product/scenario-images.md) |
| How do I demo this in five minutes? | [product/demo-script.md](product/demo-script.md) |
| How do we defend the project to organizers? | [product/defense.md](product/defense.md) |
| Who may see what? | [product/roles.md](product/roles.md) |
| Why is the code split into core and app? | [decisions/0001-functional-core.md](decisions/0001-functional-core.md) |
| Why does the webhook answer before doing work? | [decisions/0002-async-webhook.md](decisions/0002-async-webhook.md) |
| Why hybrid retrieval instead of pure vectors? | [decisions/0003-hybrid-retrieval.md](decisions/0003-hybrid-retrieval.md) |
| Why are prompts files with versions? | [decisions/0004-prompts-as-data.md](decisions/0004-prompts-as-data.md) |
| Why does one Postgres hold state, vectors, and the outbox? | [decisions/0005-single-postgres.md](decisions/0005-single-postgres.md) |
| Why refuse instead of guessing? | [decisions/0006-refuse-over-guess.md](decisions/0006-refuse-over-guess.md) |
| Why is there an offline provider? | [decisions/0007-extractive-demo-provider.md](decisions/0007-extractive-demo-provider.md) |
| Why a hosted reranker? | [decisions/0008-hosted-rerank.md](decisions/0008-hosted-rerank.md) |
| Why is the latency gate 8 s? | [decisions/0009-latency-budget.md](decisions/0009-latency-budget.md) |
| Why one vendor for answers, embeddings, and rerank? | [decisions/0010-one-model-vendor.md](decisions/0010-one-model-vendor.md) |
| Why is Jev behind a flag? | [decisions/0011-jev-sentiment-pilot.md](decisions/0011-jev-sentiment-pilot.md) |
| Why not BM25 / ParadeDB? | [decisions/0012-no-bm25-in-request-path.md](decisions/0012-no-bm25-in-request-path.md) |
| Why is a model a profile file? | [decisions/0013-model-profiles.md](decisions/0013-model-profiles.md) |
| Why does the cabinet write through the outbox, and what does leaving delete? | [decisions/0014-cabinet-writes-through-the-outbox.md](decisions/0014-cabinet-writes-through-the-outbox.md) |
| Why is extraction an adapter, and how does an uploaded PDF become a document? | [decisions/0015-extraction-is-an-adapter.md](decisions/0015-extraction-is-an-adapter.md) |
| Why is contextual retrieval written but switched off? | [decisions/0016-contextual-retrieval.md](decisions/0016-contextual-retrieval.md) |
| How is the sentiment eval measured, and why does it abort on an outage? | [decisions/0017-sentiment-eval-v2.md](decisions/0017-sentiment-eval-v2.md) |
| Why does the cabinet hold a cookie instead of a token? | [decisions/0018-session-cookie-for-the-cabinet.md](decisions/0018-session-cookie-for-the-cabinet.md) |
| Why is Jev a profile and not a special case? | [decisions/0020-jev-as-a-classifier-profile.md](decisions/0020-jev-as-a-classifier-profile.md) |
| Why does a model have no environment fallback? | [decisions/0021-model-identity-has-one-home.md](decisions/0021-model-identity-has-one-home.md) |
| Why is a markdown upload queued instead of indexed? | [decisions/0022-knowledge-upload-is-async.md](decisions/0022-knowledge-upload-is-async.md) |
| Can the same sentence arrive twice, and what happens then? | [decisions/0023-a-delivery-is-deduped-not-a-sentence.md](decisions/0023-a-delivery-is-deduped-not-a-sentence.md) |
| Why does every cabinet route carry `/v1`? | [decisions/0024-a-versioned-cabinet-api.md](decisions/0024-a-versioned-cabinet-api.md) |
| Which models does the demo deploy, and why two vendors? | [decisions/0025-demo-models-on-opencode-and-openrouter.md](decisions/0025-demo-models-on-opencode-and-openrouter.md) |
| How good and how expensive is the Jev classifier? | [measurements/2026-10-23-sentiment-jev-expanded-v2.md](measurements/2026-10-23-sentiment-jev-expanded-v2.md) |
| Does a run really follow a person from one messenger to another? | [measurements/2026-10-24-cross-channel-move.md](measurements/2026-10-24-cross-channel-move.md) |
| What does the demo host have? | [measurements/2026-10-23-demo-vps-capacity.md](measurements/2026-10-23-demo-vps-capacity.md) |
| How does the assistant read an uploaded PDF or scan? | [contracts/extraction-profile.schema.json](contracts/extraction-profile.schema.json), profiles in `apps/api/model-profiles/extract/` |
| An uploaded file did not reach the corpus — what now? | [runbooks/extraction.md](runbooks/extraction.md) |
| How is OCR quality measured? | [evals/ocr.yaml](evals/ocr.yaml), `make eval-ocr` |
| How do I deploy? | [runbooks/deploy.md](runbooks/deploy.md) |
| How do I back up and restore? | [runbooks/backup.md](runbooks/backup.md) |
| How do I migrate the database? | [runbooks/migrate.md](runbooks/migrate.md) |
| How do proactive reminders run on a schedule? | [runbooks/cron.md](runbooks/cron.md) |
| What is deleted, when, and how do I offboard someone? | [runbooks/retention.md](runbooks/retention.md) |
| What metrics exist and what should alert? | [runbooks/observability.md](runbooks/observability.md) |
| The model provider is down — what now? | [runbooks/llm-outage.md](runbooks/llm-outage.md) |
| The provider is blocked from this network — how do I still measure? | [runbooks/provider-tunnel.md](runbooks/provider-tunnel.md) |
| Webhooks return 401 — what now? | [runbooks/webhook-auth.md](runbooks/webhook-auth.md) |
| How do I turn on Telegram or VK? | [runbooks/channels.md](runbooks/channels.md) |
| How is answer quality measured? | [evals/README.md](evals/README.md), case contract [contracts/golden.schema.json](contracts/golden.schema.json) |
| How is the risk radar scored, and what does a label mean? | [evals/sentiment-guide.md](evals/sentiment-guide.md) |
| How is the retrieval corpus built, and what can it prove? | [evals/corpus-design.md](evals/corpus-design.md) |
| Where do measured numbers live? | [measurements/TEMPLATE.md](measurements/TEMPLATE.md) |
| Where does a postmortem live? | [incidents/TEMPLATE.md](incidents/TEMPLATE.md) |

## Document classes

| Class | Purpose | Change rule |
|---|---|---|
| `architecture.md`, `glossary.md`, `conventions.md` | normative description of the system | edit in place, keep the anchor headings stable |
| `contracts/` | schemas and API surfaces that code is generated from or validated against | schema first, code second |
| `decisions/` | immutable records of why | never edit an accepted ADR; add a new one |
| `runbooks/` | steps under stress | keep short, imperative, tested in staging |
| `product/` | rules the bot and the cockpit obey | edit with a matching test or eval case |
| `case/` | transcript of the client brief | append corrections with a date; never reword the quotes |
| `evals/` | the quality gate | every new failure mode becomes a case |
| `measurements/`, `incidents/` | evidence | one file per event, never rewritten |

## Frontmatter

Every document under `knowledge/` carries YAML frontmatter validated by
[contracts/doc.schema.json](contracts/doc.schema.json). Documents under `docs/` do not need
frontmatter; the index above is their identifier.
