/**
 * Dev-only fixtures for reviewing the cabinet without a database.
 *
 * The rows mirror the demo cohort described in docs/product/demo-script.md. The production build
 * never imports this module: it is wired into Vite only under `--mode preview`.
 */

export type Role = "recruiter" | "hr_admin";

export const TOKENS: Record<string, Role> = {
  "dev-recruiter-token": "recruiter",
  "dev-hr-token": "hr_admin",
};

/**
 * Mirrors `CAPABILITIES` in `apps/api/onboarding/api/auth.py`.
 *
 * The copy is deliberate — the preview has no server — and `src/preview.test.ts` fails when the two
 * lists stop agreeing, so the demo cannot promise a button the API would refuse.
 */
export const CAPABILITIES: Record<Role, readonly string[]> = {
  recruiter: [
    "runs.read",
    "questions.read",
    "questions.resolve",
    "questions.assign",
    "knowledge.read",
    "employees.read",
    "analytics.read",
  ],
  hr_admin: [
    "runs.read",
    "questions.read",
    "questions.resolve",
    "questions.assign",
    "knowledge.read",
    "knowledge.write",
    "employees.read",
    "employees.write",
    "employees.offboard",
    "analytics.read",
  ],
};

export function identity(role: Role): {
  role: Role;
  subject: string;
  scope: { recruiter_id: string | null; department: string | null };
  capabilities: readonly string[];
  expires_at: string | null;
} {
  return {
    role,
    subject: role === "recruiter" ? "rec-1" : "hr-1",
    scope: { recruiter_id: role === "recruiter" ? "rec-1" : null, department: null },
    capabilities: CAPABILITIES[role],
    expires_at: null,
  };
}

const DAY = 86_400_000;

function ago(days: number, hours = 0): string {
  return new Date(Date.now() - days * DAY - hours * 3_600_000).toISOString();
}

interface RunFixture {
  run_id: string;
  employee_id: string;
  recruiter_id: string;
  name: string;
  role: string;
  department: string;
  scenario: string;
  scenario_version: number;
  tone: "formal" | "informal";
  step_id: string;
  step_title: string;
  step_number: number;
  steps_total: number;
  entered_days: number;
  status: "active" | "completed";
  step_message: string;
}

const SURVEY_MESSAGE =
  "Девять коротких оценок от 1 до 10. Если оценка ниже 8, я спрошу, что можно улучшить.";

const RUNS: RunFixture[] = [
  {
    run_id: "0f0a6f4e-1b1c-4a58-9d1e-7d6f2a1f9b3c",
    employee_id: "1001",
    recruiter_id: "rec-1",
    name: "Анна Смирнова",
    role: "Инженер-технолог",
    department: "Производство",
    scenario: "onboarding_plant",
    scenario_version: 1,
    tone: "informal",
    step_id: "week_two_survey",
    step_title: "Опрос двух недель",
    step_number: 15,
    steps_total: 20,
    entered_days: 18,
    status: "active",
    step_message: SURVEY_MESSAGE,
  },
  {
    run_id: "4a1d2c3b-5e6f-4a71-8b92-0c1d2e3f4a5b",
    employee_id: "1002",
    recruiter_id: "rec-1",
    name: "Пётр Кузнецов",
    role: "Системный администратор",
    department: "ИТ",
    scenario: "onboarding_default",
    scenario_version: 2,
    tone: "formal",
    step_id: "week_two_survey",
    step_title: "Опрос двух недель",
    step_number: 15,
    steps_total: 20,
    entered_days: 17,
    status: "active",
    step_message: SURVEY_MESSAGE,
  },
  {
    run_id: "9c8b7a65-4321-4f0e-9d8c-7b6a5f4e3d2c",
    employee_id: "1003",
    recruiter_id: "rec-2",
    name: "Мария Волкова",
    role: "HR-специалист",
    department: "Дирекция по персоналу",
    scenario: "onboarding_default",
    scenario_version: 2,
    tone: "formal",
    step_id: "territory_map",
    step_title: "Территория",
    step_number: 7,
    steps_total: 20,
    entered_days: 4,
    status: "active",
    step_message: "Покажу схему территории и подскажу, где находятся нужные кабинеты.",
  },
];

interface QuestionFixture {
  id: number;
  employee_id: string;
  text: string;
  answered: boolean;
  reason: string;
  citations: string[];
  asked_days: number;
  assignee: string | null;
}

const QUESTIONS: QuestionFixture[] = [
  {
    id: 1,
    employee_id: "1001",
    text: "Сколько дней отпуска в первый год?",
    answered: true,
    reason: "answered",
    citations: ["hr/leave-policy#0"],
    asked_days: 2,
    assignee: null,
  },
  {
    id: 2,
    employee_id: "1001",
    text: "Сколько дней больничного оплачивает компания?",
    answered: false,
    reason: "restricted",
    citations: [],
    asked_days: 1,
    assignee: null,
  },
  {
    id: 3,
    employee_id: "1002",
    text: "Как получить доступ к корпоративному порталу?",
    answered: true,
    reason: "answered",
    citations: ["it/access-and-equipment#0"],
    asked_days: 3,
    assignee: null,
  },
  {
    id: 4,
    employee_id: "1003",
    text: "Когда выплачивают аванс?",
    answered: false,
    reason: "no_sources",
    citations: [],
    asked_days: 1,
    assignee: "hr-1",
  },
];

interface DigestFixture {
  employee_id: string;
  step_id: string;
  level: "high" | "medium";
  reasons: string[];
  tags: string[];
  quote: string | null;
  at_days: number;
}

const DIGEST: DigestFixture[] = [
  {
    employee_id: "1002",
    step_id: "week_two_survey",
    level: "high",
    reasons: ["конфликт с руководителем", "нет доступа к порталу"],
    tags: ["manager", "access", "it"],
    quote: "Руководитель не отвечает третий день, доступ к порталу так и не дали.",
    at_days: 1,
  },
  {
    employee_id: "1001",
    step_id: "week_two_survey",
    level: "medium",
    reasons: ["оценка 6 из 10 ниже порога 8"],
    tags: ["clarity", "workload"],
    quote: "Задач много, но не всегда понятно, что в приоритете.",
    at_days: 3,
  },
];

interface KnowledgeFixture {
  id: string;
  title: string;
  audience: string[];
  owner: string;
  updated_days: number;
  text?: string;
}

/** A demo source document for a fixture that has not been edited in this browser session. */
function sourceText(item: KnowledgeFixture): string {
  return `---
id: ${item.id}
title: ${item.title}
type: knowledge
status: active
owner: ${item.owner}
audience: [${item.audience.join(", ")}]
valid_from: 2026-01-01
---

## ${item.title}

Демонстрационный документ. В реальном кабинете здесь лежит markdown, по которому
ассистент отвечает сотрудникам.`;
}

const KNOWLEDGE: KnowledgeFixture[] = [
  {
    id: "hr/leave-policy",
    title: "Отпуска и отгулы",
    audience: ["all"],
    owner: "hr",
    updated_days: 2,
  },
  {
    id: "hr/benefits-dms",
    title: "ДМС и льготы",
    audience: ["all"],
    owner: "hr",
    updated_days: 5,
  },
  {
    id: "it/access-and-equipment",
    title: "Доступы и оборудование",
    audience: ["all"],
    owner: "it",
    updated_days: 9,
  },
  {
    id: "hr/sick-leave",
    title: "Больничные: внутренняя инструкция для HR",
    audience: ["hr_only"],
    owner: "hr",
    updated_days: 12,
  },
];

function scopedRuns(role: Role): RunFixture[] {
  return role === "hr_admin" ? RUNS : RUNS.filter((run) => run.recruiter_id === "rec-1");
}

function employeeName(employeeId: string): string {
  return RUNS.find((run) => run.employee_id === employeeId)?.name ?? "Сотрудник";
}

export function summary(run: RunFixture) {
  return {
    run_id: run.run_id,
    employee_id: run.employee_id,
    name: run.name,
    role: run.role,
    department: run.department,
    step_id: run.step_id,
    step_title: run.step_title,
    step_number: run.step_number,
    steps_total: run.steps_total,
    entered_at: ago(run.entered_days),
    status: run.status,
  };
}

export function runs(role: Role) {
  return scopedRuns(role).map(summary);
}

export function runDetail(role: Role, runId: string) {
  const run = scopedRuns(role).find((item) => item.run_id === runId);
  if (!run) return null;
  const risk = DIGEST.find((item) => item.employee_id === run.employee_id);
  const events = [
    {
      name: "run_started",
      at: ago(run.entered_days),
      fields: { step: "welcome", employee_id: run.employee_id },
    },
    {
      name: "step_transition",
      at: ago(run.entered_days - 2),
      fields: {
        previous_step: "day_three_survey",
        step: "week_two_plan",
        accepted: true,
      },
    },
    {
      name: "step_transition",
      at: ago(run.entered_days - 4),
      fields: { previous_step: "week_two_plan", step: run.step_id, accepted: true },
    },
    ...(risk
      ? [
          {
            name: "risk_assessed",
            at: ago(risk.at_days),
            fields: {
              step: risk.step_id,
              step_title: run.step_title,
              level: risk.level,
              tags: risk.tags,
              reasons: risk.reasons,
            },
          },
        ]
      : []),
    {
      name: "answer_completed",
      at: ago(2, 3),
      fields: { reason: "answered", citations: ["hr/leave-policy#0"] },
    },
  ].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  return {
    ...summary(run),
    scenario: run.scenario,
    scenario_version: run.scenario_version,
    tone: run.tone,
    step_message: run.step_message,
    events,
    questions: questions(role, "all", "any", 20).items.filter(
      (question) => question.employee_id === run.employee_id,
    ),
  };
}

/** `owner` mirrors the API's `assignee` parameter: `any`, `me` or `unassigned`. */
export function questions(role: Role, status: string, owner: string, limit: number) {
  const visible = new Set(scopedRuns(role).map((run) => run.employee_id));
  const me = identity(role).subject;
  const items = QUESTIONS.filter((question) => visible.has(question.employee_id))
    .filter((question) => {
      if (status === "unanswered") return !question.answered;
      if (status === "answered") return question.answered;
      return true;
    })
    .filter((question) => {
      if (owner === "me") return question.assignee === me;
      if (owner === "unassigned") return question.assignee === null;
      return true;
    })
    .sort((a, b) => a.asked_days - b.asked_days)
    .slice(0, limit)
    .map((question) => ({
      id: question.id,
      employee_id: question.employee_id,
      employee_name: employeeName(question.employee_id),
      text: question.text,
      answered: question.answered,
      reason: question.reason,
      citations: question.citations,
      asked_at: ago(question.asked_days),
      resolved_at: question.answered ? ago(question.asked_days, 1) : null,
      resolved_by: question.answered ? identity(role).subject : null,
      assignee: question.assignee,
    }));
  return { items };
}

/** The demo keeps a claim in memory, so the queue behaves like the real one until a reload. */
export function assignQuestion(id: number, assignee: string | null) {
  const question = QUESTIONS.find((item) => item.id === id);
  if (question) question.assignee = assignee;
  return { id, employee_id: question?.employee_id ?? "", assignee };
}

export function digest(role: Role) {
  const visible = new Map(scopedRuns(role).map((run) => [run.employee_id, run]));
  return {
    items: DIGEST.filter((item) => visible.has(item.employee_id)).map((item) => {
      const run = visible.get(item.employee_id);
      return {
        employee_id: item.employee_id,
        employee_name: run?.name ?? "Сотрудник",
        department: run?.department ?? "",
        run_id: run?.run_id ?? "",
        step_id: item.step_id,
        step_title: run?.step_title ?? item.step_id,
        level: item.level,
        reasons: item.reasons,
        tags: item.tags,
        quote: item.quote,
        at: ago(item.at_days),
      };
    }),
    since: ago(7),
  };
}

export function overview(role: Role) {
  const cohort = scopedRuns(role);
  const signals = digest(role).items;
  const tagCounts = new Map<string, number>();
  for (const signal of signals) {
    for (const tag of signal.tags) tagCounts.set(tag, (tagCounts.get(tag) ?? 0) + 1);
  }
  return {
    active_runs: cohort.filter((run) => run.status === "active").length,
    completed_runs: cohort.filter((run) => run.status === "completed").length,
    high_risk: signals.filter((item) => item.level === "high").length,
    medium_risk: signals.filter((item) => item.level === "medium").length,
    unanswered_questions: questions(role, "unanswered", "any", 200).items.length,
    top_tags: [...tagCounts.entries()]
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
      .slice(0, 5),
    since: ago(7),
  };
}

export function knowledge(role: Role) {
  return {
    items: KNOWLEDGE.filter((item) => role === "hr_admin" || !item.audience.includes("hr_only"))
      .map((item) => ({
        id: item.id,
        title: item.title,
        type: "knowledge",
        audience: item.audience,
        owner: item.owner,
        valid_from: "2026-01-01",
        valid_to: null,
        updated_at: ago(item.updated_days),
      }))
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)),
  };
}

export function knowledgeDocument(id: string, role: Role) {
  const item = KNOWLEDGE.find((candidate) => candidate.id === id);
  if (!item) return null;
  if (role !== "hr_admin" && item.audience.includes("hr_only")) return null;
  return {
    id: item.id,
    title: item.title,
    type: "knowledge",
    audience: item.audience,
    owner: item.owner,
    valid_from: "2026-01-01",
    valid_to: null,
    updated_at: ago(item.updated_days),
    text: item.text ?? sourceText(item),
  };
}

export function updateDocument(id: string, text: string) {
  const item = KNOWLEDGE.find((candidate) => candidate.id === id);
  if (!item) return { status: 404, body: { detail: "document not found", code: "not_found" } };
  const declared = /^---\s*\n[\s\S]*?^id:\s*(.+)$/m.exec(text)?.[1]?.trim();
  if (declared !== id) {
    return {
      status: 422,
      body: { detail: `upload: frontmatter id is '${declared ?? ""}', expected '${id}'`, code: "knowledge_rejected" },
    };
  }
  item.text = text;
  item.updated_days = 0;
  return { status: 202, body: { content_hash: `demo-edit-${Date.now()}`, status: "queued" } };
}

function frontmatter(text: string, name: string): string | undefined {
  return new RegExp(`^${name}:\\s*(.+)$`, "m").exec(text)?.[1]?.trim();
}

export function upload(text: string): { status: number; body: unknown } {
  const id = frontmatter(text, "id");
  const title = frontmatter(text, "title");
  const owner = frontmatter(text, "owner");
  const status = frontmatter(text, "status");
  const type = frontmatter(text, "type");
  const validFrom = frontmatter(text, "valid_from");
  const audienceRaw = frontmatter(text, "audience");
  const audience = audienceRaw
    ?.replace(/^\[|\]$/g, "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (!id || !/^[a-z0-9][a-z0-9/_-]*$/.test(id)) {
    return { status: 422, body: { detail: "upload: id is missing or invalid" } };
  }
  if (!title) {
    return { status: 422, body: { detail: "upload: title is required" } };
  }
  if (type !== "knowledge") {
    return { status: 422, body: { detail: "upload: type must be 'knowledge'" } };
  }
  if (!status || !["draft", "active", "deprecated"].includes(status)) {
    return { status: 422, body: { detail: "upload: status must be draft, active or deprecated" } };
  }
  if (status !== "active") {
    return {
      status: 422,
      body: { detail: `upload: document status is '${status}', not 'active'` },
    };
  }
  if (!owner || !/^[a-z][a-z0-9_-]*$/.test(owner)) {
    return { status: 422, body: { detail: "upload: owner is missing or invalid" } };
  }
  if (!audience?.length || audience.some((item) => !/^(all|hr_only|dept:[a-z0-9_-]+)$/.test(item))) {
    return {
      status: 422,
      body: { detail: "upload: audience must contain all, hr_only or dept:<slug>" },
    };
  }
  if (!validFrom || !/^\d{4}-\d{2}-\d{2}$/.test(validFrom)) {
    return { status: 422, body: { detail: "upload: valid_from must be YYYY-MM-DD" } };
  }

  const existing = KNOWLEDGE.find((item) => item.id === id);
  const chunks = Math.max(1, Math.ceil(text.length / 1200));
  if (existing) {
    existing.title = title;
    existing.audience = audience;
    existing.owner = owner;
    existing.updated_days = 0;
  } else {
    KNOWLEDGE.push({ id, title, audience, owner, updated_days: 0 });
  }
  return { status: 201, body: { id, title, chunks } };
}
