import type { IncomingMessage, ServerResponse } from "node:http";

import type { Plugin } from "vite";

import * as demo from "./data";

function send(response: ServerResponse, status: number, body: unknown): void {
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  response.end(JSON.stringify(body));
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk as Uint8Array));
  const text = Buffer.concat(chunks).toString("utf8");
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function limitOf(url: URL, fallback: number, max: number): number {
  const parsed = Number(url.searchParams.get("limit") ?? fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(1, Math.trunc(parsed)));
}

/** The demo pages with a plain offset: the real server uses an opaque keyset cursor. */
function paginate<T>(items: T[], url: URL, max: number): { items: T[]; next_cursor: string | null; total: number } {
  const limit = limitOf(url, 50, max);
  const offset = Math.max(0, Math.trunc(Number(url.searchParams.get("cursor") ?? 0)) || 0);
  const slice = items.slice(offset, offset + limit);
  const next = offset + limit < items.length ? String(offset + limit) : null;
  return { items: slice, next_cursor: next, total: items.length };
}

const SESSION_COOKIE = "onboarding_session";

function cookieToken(request: IncomingMessage): string | null {
  const header = request.headers.cookie ?? "";
  for (const part of header.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === SESSION_COOKIE) return decodeURIComponent(rest.join("="));
  }
  return null;
}

async function handle(
  request: IncomingMessage,
  response: ServerResponse,
  next: () => void,
): Promise<void> {
  const url = new URL(request.url ?? "/", "http://localhost");
  // The cabinet talks to `/admin/api/v1`; this demo server keeps one set of handlers.
  const path = url.pathname.replace(/^\/admin\/api\/v1(?=\/|$)/, "/admin/api");

  if (path === "/healthz" || path === "/readyz") {
    send(response, 200, { status: "ok" });
    return;
  }
  if (!path.startsWith("/admin/api/")) {
    next();
    return;
  }

  // The cabinet signs in with a cookie; `Authorization` stays for curl and the existing tests.
  const presented =
    (request.headers.authorization ?? "").replace(/^Bearer\s+/i, "") || cookieToken(request) || "";

  if (request.method === "POST" && path === "/admin/api/session") {
    const body = (await readJson(request)) as { token?: unknown } | null;
    const candidate = typeof body?.token === "string" ? body.token.trim() : "";
    if (!demo.TOKENS[candidate]) {
      send(response, 401, { detail: "unknown token", code: "token_unknown" });
      return;
    }
    response.statusCode = 204;
    response.setHeader(
      "Set-Cookie",
      `${SESSION_COOKIE}=${encodeURIComponent(candidate)}; HttpOnly; SameSite=Strict; Path=/admin/api; Max-Age=43200`,
    );
    response.end();
    return;
  }

  if (request.method === "DELETE" && path === "/admin/api/session") {
    response.statusCode = 204;
    response.setHeader(
      "Set-Cookie",
      `${SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/admin/api; Max-Age=0`,
    );
    response.end();
    return;
  }

  const role = demo.TOKENS[presented];
  if (!role) {
    send(response, 401, { detail: "unauthorized", code: "unauthorized" });
    return;
  }

  if (request.method === "GET" && path === "/admin/api/me") {
    send(response, 200, demo.identity(role));
    return;
  }

  if (request.method === "GET" && path === "/admin/api/runs") {
    const status = url.searchParams.get("status") ?? "all";
    const term = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    const filtered = demo.runs(role).filter((run) => {
      const byStatus = status === "all" || run.status === status;
      const haystack = [run.name, run.role, run.department, run.employee_id].join(" ").toLowerCase();
      return byStatus && (!term || haystack.includes(term));
    });
    send(response, 200, paginate(filtered, url, 200));
    return;
  }

  const runMatch = /^\/admin\/api\/runs\/([^/]+)$/.exec(path);
  if (request.method === "GET" && runMatch?.[1]) {
    const detail = demo.runDetail(role, decodeURIComponent(runMatch[1]));
    if (!detail) {
      send(response, 404, { detail: "run not found", code: "not_found" });
      return;
    }
    send(response, 200, detail);
    return;
  }

  if (request.method === "GET" && path === "/admin/api/questions") {
    const status = url.searchParams.get("status") ?? "unanswered";
    if (!["unanswered", "answered", "all"].includes(status)) {
      send(response, 422, { detail: "status must be unanswered, answered or all", code: "validation_failed" });
      return;
    }
    const owner = url.searchParams.get("assignee") ?? "any";
    send(response, 200, paginate(demo.questions(role, status, owner, 500).items, url, 200));
    return;
  }

  const assignMatch = /^\/admin\/api\/questions\/([^/]+)\/assignee$/.exec(path);
  if (request.method === "PATCH" && assignMatch?.[1]) {
    const body = (await readJson(request)) as { assignee?: unknown } | null;
    const owner = typeof body?.assignee === "string" ? body.assignee : null;
    send(response, 200, demo.assignQuestion(Number(assignMatch[1]), owner));
    return;
  }

  if (request.method === "GET" && path === "/admin/api/analytics/overview") {
    send(response, 200, demo.overview(role));
    return;
  }

  if (request.method === "GET" && path === "/admin/api/digest/weekly") {
    send(response, 200, demo.digest(role));
    return;
  }

  if (request.method === "GET" && path === "/admin/api/knowledge") {
    send(response, 200, demo.knowledge(role));
    return;
  }

  if (request.method === "DELETE" && path.startsWith("/admin/api/employees/")) {
    if (role !== "hr_admin") {
      send(response, 403, { detail: "only hr_admin may offboard an employee", code: "forbidden" });
      return;
    }
    send(response, 200, {
      employee_id: decodeURIComponent(path.slice("/admin/api/employees/".length)),
      questions_deleted: 2,
      messages_deleted: 14,
      runs_closed: 1,
      audit_redacted: 6,
    });
    return;
  }

  if (request.method === "POST" && path === "/admin/api/knowledge/files") {
    if (role !== "hr_admin") {
      send(response, 403, { detail: "only hr_admin may change the knowledge base", code: "forbidden" });
      return;
    }
    polls.clear();
    send(response, 202, { content_hash: "demo-file", status: "queued" });
    return;
  }

  if (request.method === "GET" && path.startsWith("/admin/api/knowledge/files/")) {
    const hash = path.slice("/admin/api/knowledge/files/".length);
    const seen = (polls.get(hash) ?? 0) + 1;
    polls.set(hash, seen);
    const indexed = seen > 1;
    send(response, 200, {
      content_hash: hash,
      status: indexed ? "indexed" : "running",
      reason: null,
      engine: "pdf-text",
      route: "text",
      pages: 4,
      min_confidence: 0.93,
      document_id: indexed ? "hr/demo-guide" : null,
    });
    return;
  }

  if (request.method === "GET" && path.startsWith("/admin/api/knowledge/")) {
    const id = decodeURIComponent(path.slice("/admin/api/knowledge/".length));
    const document = demo.knowledgeDocument(id, role);
    if (!document) {
      send(response, 404, { detail: "document not found", code: "not_found" });
      return;
    }
    send(response, 200, document);
    return;
  }

  if (
    request.method === "PUT" &&
    path.startsWith("/admin/api/knowledge/") &&
    !path.startsWith("/admin/api/knowledge/files/")
  ) {
    if (role !== "hr_admin") {
      send(response, 403, { detail: "only hr_admin may change the knowledge base", code: "forbidden" });
      return;
    }
    const id = decodeURIComponent(path.slice("/admin/api/knowledge/".length));
    const body = (await readJson(request)) as { text?: unknown } | null;
    const text = typeof body?.text === "string" ? body.text : "";
    if (text.length < 20) {
      send(response, 422, { detail: "upload: text is required", code: "knowledge_rejected" });
      return;
    }
    const result = demo.updateDocument(id, text);
    send(response, result.status, result.body);
    return;
  }

  if (request.method === "POST" && path === "/admin/api/knowledge") {
    if (role !== "hr_admin") {
      send(response, 403, { detail: "only hr_admin may change the knowledge base", code: "forbidden" });
      return;
    }
    const body = (await readJson(request)) as { text?: unknown } | null;
    const text = typeof body?.text === "string" ? body.text : "";
    if (text.length < 20) {
      send(response, 422, { detail: "upload: text is required", code: "knowledge_rejected" });
      return;
    }
    const result = demo.upload(text);
    send(response, result.status, result.body);
    return;
  }

  send(response, 405, { detail: "method not allowed", code: "method_not_allowed" });
}

/** How many times the demo has polled each hash, so a fake extraction can finish. */
const polls = new Map<string, number>();

/**
 * Serves the documented demo cohort on `/admin/api/*` during `vite --mode preview`.
 * It is never part of a production build: `apply: "serve"` keeps it out of `vite build`.
 */

export function previewApi(): Plugin {
  return {
    name: "onboarding-demo-api",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        void handle(request, response, next);
      });
    },
  };
}
