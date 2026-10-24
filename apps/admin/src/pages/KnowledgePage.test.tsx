import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchExtraction,
  fetchKnowledge,
  fetchKnowledgeDocument,
  updateKnowledge,
  uploadKnowledge,
  uploadKnowledgeFile,
} from "../api";
import type { Capability } from "../types";
import { SessionProvider, sessionFor } from "../session";
import { KnowledgePage } from "./KnowledgePage";

vi.mock("../api", () => ({
  fetchKnowledge: vi.fn(),
  fetchKnowledgeDocument: vi.fn(),
  updateKnowledge: vi.fn(),
  uploadKnowledge: vi.fn(),
  uploadKnowledgeFile: vi.fn(),
  fetchExtraction: vi.fn(),
}));

function renderPage(capabilities: Capability[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SessionProvider
        value={sessionFor({
          role: capabilities.includes("knowledge.write") ? "hr_admin" : "recruiter",
          subject: "rec-1",
          scope: { recruiter_id: "rec-1", department: null },
          capabilities,
          expires_at: null,
        })}
      >
        <KnowledgePage onUnauthorized={() => undefined} />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

describe("KnowledgePage", () => {
  beforeEach(() => {
    vi.mocked(fetchKnowledge).mockResolvedValue({ items: [] });
    vi.mocked(fetchKnowledgeDocument).mockReset();
    vi.mocked(updateKnowledge).mockReset();
    vi.mocked(uploadKnowledgeFile).mockReset();
    vi.mocked(fetchExtraction).mockReset();
    vi.mocked(uploadKnowledge).mockReset();
  });

  it("opens an active document and lets HR edit it", async () => {
    const source = "---\nid: hr/leave-policy\ntitle: Отпуска\n---\n\n## Отпуск\n\nДвадцать восемь дней.";
    vi.mocked(fetchKnowledge).mockResolvedValue({
      items: [
        {
          id: "hr/leave-policy",
          title: "Отпуска и отгулы",
          type: "knowledge",
          audience: ["all"],
          owner: "hr",
          valid_from: "2026-01-01",
          valid_to: null,
          updated_at: "2026-10-23T08:00:00Z",
        },
      ],
    });
    vi.mocked(fetchKnowledgeDocument).mockResolvedValue({
      id: "hr/leave-policy",
      title: "Отпуска и отгулы",
      type: "knowledge",
      audience: ["all"],
      owner: "hr",
      valid_from: "2026-01-01",
      valid_to: null,
      updated_at: "2026-10-23T08:00:00Z",
      text: source,
    });
    vi.mocked(updateKnowledge).mockResolvedValue({ content_hash: "hash-edit", status: "queued" });
    vi.mocked(fetchExtraction).mockResolvedValue({
      content_hash: "hash-edit",
      status: "indexed",
      reason: null,
      engine: "markdown",
      route: "text",
      pages: 0,
      min_confidence: 1,
      document_id: "hr/leave-policy",
    });

    renderPage(["knowledge.read", "knowledge.write"]);
    await userEvent.click(
      await screen.findByRole("button", { name: "Открыть документ Отпуска и отгулы" }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("hr/leave-policy")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    const editor = within(dialog).getByLabelText("Markdown с frontmatter");
    expect(editor).toHaveValue(source);

    await userEvent.clear(editor);
    await userEvent.type(editor, `${source}\n\nИзменённый текст.`);
    await userEvent.click(screen.getByRole("button", { name: "Сохранить и переиндексировать" }));

    expect(await screen.findByText("Документ обновлён и переиндексирован.")).toBeInTheDocument();
    expect(updateKnowledge).toHaveBeenCalledWith(
      "hr/leave-policy",
      expect.stringContaining("Изменённый текст."),
    );
  });

  it("hides both write forms from a role that may only read", async () => {
    renderPage(["knowledge.read"]);

    await screen.findByText("База пуста. Загрузите первый документ или выполните make ingest.");
    expect(screen.queryByLabelText("Файл")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Загрузить файл" })).not.toBeInTheDocument();
  });

  it("uploads a file and follows the extraction until it is indexed", async () => {
    vi.mocked(uploadKnowledgeFile).mockResolvedValue({
      content_hash: "hash-1",
      status: "queued",
    });
    vi.mocked(fetchExtraction).mockResolvedValue({
      content_hash: "hash-1",
      status: "indexed",
      reason: null,
      engine: "pdf-text",
      route: "text",
      pages: 3,
      min_confidence: 0.9,
      document_id: "hr/guide",
    });

    renderPage(["knowledge.read", "knowledge.write"]);
    await userEvent.upload(
      screen.getByLabelText("Файл"),
      new File(["%PDF-1.7"], "guide.pdf", { type: "application/pdf" }),
    );
    await userEvent.type(screen.getByLabelText("id"), "hr/guide");
    await userEvent.type(screen.getByLabelText("Название"), "Гид");
    await userEvent.click(screen.getByRole("button", { name: "Загрузить файл" }));

    expect(await screen.findByText(/Готово: 3 страницы, движок pdf-text/)).toBeInTheDocument();
    expect(uploadKnowledgeFile).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({ id: "hr/guide", title: "Гид", audience: ["all"] }),
    );
    expect(screen.getByRole("button", { name: "Загрузить ещё" })).toBeInTheDocument();
  });

  it("queues markdown and reports the worker's verdict", async () => {
    vi.mocked(uploadKnowledge).mockResolvedValue({
      content_hash: "hash-md",
      status: "queued",
    });
    vi.mocked(fetchExtraction).mockResolvedValue({
      content_hash: "hash-md",
      status: "indexed",
      reason: null,
      engine: "markdown",
      route: "text",
      pages: 0,
      min_confidence: 1,
      document_id: "hr/new-policy",
    });

    renderPage(["knowledge.read", "knowledge.write"]);
    await userEvent.type(
      screen.getByLabelText("Markdown с frontmatter"),
      "---\nid: hr/new-policy\ntitle: Политика\n---\n\nТекст документа.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Загрузить и проиндексировать" }));

    expect(await screen.findByText(/Документ проиндексирован/)).toBeInTheDocument();
    expect(fetchExtraction).toHaveBeenCalledWith("hash-md");
  });

  it("keeps the submit disabled until the file and the id are there", async () => {
    renderPage(["knowledge.read", "knowledge.write"]);

    const submit = screen.getByRole("button", { name: "Загрузить файл" });
    expect(submit).toBeDisabled();

    await userEvent.upload(
      screen.getByLabelText("Файл"),
      new File(["%PDF-1.7"], "guide.pdf", { type: "application/pdf" }),
    );

    expect(submit).toBeDisabled();
  });
});
