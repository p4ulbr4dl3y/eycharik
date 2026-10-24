export interface RunSummary {
  run_id: string;
  employee_id: string;
  name: string;
  role: string;
  department: string;
  step_id: string;
  step_title: string | null;
  step_number: number;
  steps_total: number;
  entered_at: string;
  updated_at: string;
  status: "active" | "completed";
}

export interface AuditEvent {
  name: string;
  at: string;
  fields: Record<string, unknown>;
}

export interface Question {
  id: number;
  employee_id: string;
  employee_name: string;
  text: string;
  answered: boolean;
  reason: string;
  citations: string[];
  asked_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  /** Who picked the question up. `null` means nobody has. */
  assignee: string | null;
}

export interface AssignedQuestion {
  id: number;
  employee_id: string;
  assignee: string | null;
}

export interface ResolvedQuestion {
  id: number;
  employee_id: string;
  answered: true;
  resolved_at: string;
  resolved_by: string;
}

export interface RunDetail extends RunSummary {
  step_message: string | null;
  scenario: string;
  scenario_version: number;
  tone: "formal" | "informal";
  events: AuditEvent[];
  questions: Question[];
}

export interface ListResponse<T> {
  items: T[];
}

/**
 * One page of a keyset-paged list.
 *
 * `total` counts the whole filtered scope, not the page: it is what a header prints. `next_cursor`
 * is opaque and `null` on the last page.
 */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}


export interface TagCount {
  tag: string;
  count: number;
}

export interface AnalyticsOverview {
  active_runs: number;
  completed_runs: number;
  high_risk: number;
  medium_risk: number;
  unanswered_questions: number;
  resolved_questions: number;
  top_tags: TagCount[];
  since: string;
}

export interface DigestItem {
  employee_id: string;
  employee_name: string;
  department: string;
  run_id: string;
  step_id: string;
  step_title: string;
  level: "high" | "medium";
  reasons: string[];
  tags: string[];
  quote: string | null;
  at: string;
}

export interface DigestResponse {
  items: DigestItem[];
  since: string;
}


export interface KnowledgeDocument {
  id: string;
  title: string;
  type: string;
  audience: string[];
  owner: string;
  valid_from: string | null;
  valid_to: string | null;
  updated_at: string;
}

/** The list shape plus the raw markdown. `text` is null for rows indexed before 0015. */
export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  text: string | null;
}

export type Capability =
  | "runs.read"
  | "questions.read"
  | "questions.resolve"
  | "questions.assign"
  | "knowledge.read"
  | "knowledge.write"
  | "employees.offboard"
  | "analytics.read";

export interface AdminScope {
  recruiter_id: string | null;
  department: string | null;
}

/** `GET /admin/api/me`: what the cabinet is allowed to render for this session. */
export interface AdminIdentity {
  role: "recruiter" | "manager" | "hr_admin";
  subject: string;
  scope: AdminScope;
  capabilities: Capability[];
  expires_at: string | null;
}

export interface KnowledgeFileQueued {
  content_hash: string;
  status: string;
}

/** What extraction decided about one uploaded file. `status` is the extraction's, not the file's. */
export interface KnowledgeExtraction {
  content_hash: string;
  status: "queued" | "running" | "indexed" | "rejected" | string;
  reason: string | null;
  engine: string;
  route: string;
  pages: number;
  min_confidence: number;
  document_id: string | null;
}

export interface OffboardedEmployee {
  employee_id: string;
  questions_deleted: number;
  messages_deleted: number;
  runs_closed: number;
  audit_redacted: number;
}
