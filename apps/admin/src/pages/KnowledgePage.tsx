import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  fetchExtraction,
  fetchKnowledge,
  uploadKnowledge,
  uploadKnowledgeFile,
  type FileMetadata,
} from "../api";
import { ErrorNote } from "../components/States";
import { KnowledgeDocumentDialog } from "../components/KnowledgeDocumentDialog";
import { useUnauthorized } from "../useUnauthorized";
import { useSession } from "../session";
import { countLabel, formatDateTime } from "../format";
import { REFRESH } from "../config";

const TEMPLATE = `---
id: hr/new-policy
title: Название документа
type: knowledge
status: active
owner: hr
audience: [all]
valid_from: 2026-10-01
---

## Раздел

Текст, из которого ассистент сможет отвечать.`;

export function KnowledgePage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const queryClient = useQueryClient();
  const { can } = useSession();
  const canWrite = can("knowledge.write");
  const [text, setText] = useState("");
  const [hash, setHash] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["knowledge"],
    queryFn: fetchKnowledge,
    refetchInterval: REFRESH.knowledge,
  });
  const upload = useMutation({
    mutationFn: uploadKnowledge,
    onSuccess: (queued) => {
      setText("");
      setHash(queued.content_hash);
    },
  });
  const extraction = useQuery({
    queryKey: ["extraction", hash],
    queryFn: () => fetchExtraction(hash as string),
    enabled: hash !== null,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && TERMINAL.has(status) ? false : REFRESH.extraction;
    },
  });
  const done = extraction.data ? TERMINAL.has(extraction.data.status) : false;

  useEffect(() => {
    if (done) void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
  }, [done, queryClient]);

  useUnauthorized(query.error ?? upload.error ?? extraction.error, onUnauthorized);

  return (
    <section className="page">
      <header className="page-head">
        <div className="page-head-text">
          <p className="eyebrow">Документы</p>
          <h1>База знаний</h1>
          <p className="muted">
            HR загружает документ с frontmatter, ассистент сразу отвечает по нему со ссылкой.
            Нажмите на документ, чтобы прочитать его; HR может изменить текст. Изменения
            фиксируются в аудите.
          </p>
        </div>
        <div className="page-count" aria-live="polite">
          {query.isSuccess
            ? countLabel(query.data.items.length, "документ", "документа", "документов")
            : "…"}
        </div>
      </header>

      <div className={canWrite ? "knowledge-layout" : "knowledge-layout knowledge-layout-read"}>
        {canWrite ? (
        <section className="card">
          <div className="card-head">
            <h2>Новый документ</h2>
            <span className="card-note">Индексирует воркер</span>
          </div>
          <form
            className="upload"
            onSubmit={(event) => {
              event.preventDefault();
              upload.mutate(text);
            }}
          >
            <label className="upload-label" htmlFor="knowledge-text">
              Markdown с frontmatter
            </label>
            <p className="upload-hint">
              Поля id, title, type, status, owner, audience и valid_from проверяются по схеме до
              записи. Загружать может только HR-администратор.
            </p>
            <textarea
              id="knowledge-text"
              className="upload-area"
              value={text}
              placeholder="Вставьте markdown с frontmatter. Поля проверяются по схеме doc.schema.json. Или нажмите «Вставить шаблон»."
              onChange={(event) => setText(event.target.value)}
              rows={14}
              spellCheck={false}
            />
            <div className="upload-actions">
              <button
                type="button"
                className="button button-quiet"
                onClick={() => setText(TEMPLATE)}
              >
                Вставить шаблон
              </button>
              <button
                type="submit"
                className="button button-primary"
                disabled={upload.isPending || text.length < 20}
              >
                {upload.isPending ? "Ставим в очередь…" : "Загрузить и проиндексировать"}
              </button>
            </div>
            {upload.isError ? <ErrorNote error={upload.error} /> : null}
            {upload.isSuccess ? (
              <p className={done ? "note note-ok" : "note"} role="status">
                {done
                  ? extraction.data?.status === "indexed"
                    ? <>Документ проиндексирован, id <code>{extraction.data.document_id}</code>.</>
                    : <>Документ отклонён: {extraction.data?.reason ?? "неизвестная причина"}.</>
                  : "Документ в очереди: воркер проверит frontmatter и построит индекс."}
              </p>
            ) : null}
          </form>
        </section>
        ) : null}

        {canWrite ? <FileUpload onUnauthorized={onUnauthorized} /> : null}

        <section className="card">
          <div className="card-head">
            <h2>{canWrite ? "Активные документы" : "Что ассистент знает"}</h2>
            <span className="card-note">
              {query.isSuccess ? `${query.data.items.length} в индексе` : "…"}
            </span>
          </div>
          {query.isPending ? <p className="empty-inline">Загружаем документы…</p> : null}
          {query.isError ? (
            <ErrorNote error={query.error} onRetry={() => void query.refetch()} />
          ) : null}
          {query.isSuccess && query.data.items.length === 0 ? (
            <p className="empty-inline">
              База пуста. Загрузите первый документ или выполните make ingest.
            </p>
          ) : null}
          {query.isSuccess && query.data.items.length > 0 ? (
            <ul className="knowledge">
              {query.data.items.map((item) => (
                <li key={item.id} className="knowledge-row">
                  <button
                    type="button"
                    className="knowledge-open"
                    onClick={() => setSelectedId(item.id)}
                    aria-label={`Открыть документ ${item.title}`}
                  >
                    <span className="knowledge-main">
                      <strong>{item.title}</strong>
                      <span className="digest-meta">
                        <code>{item.id}</code>
                        <span aria-hidden="true">·</span>
                        <span>{item.audience.join(", ")}</span>
                        <span aria-hidden="true">·</span>
                        <span>owner {item.owner}</span>
                      </span>
                    </span>
                    <span className="digest-meta">{formatDateTime(item.updated_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>

      {selectedId ? (
        <KnowledgeDocumentDialog
          key={selectedId}
          documentId={selectedId}
          canWrite={canWrite}
          onClose={() => setSelectedId(null)}
          onUnauthorized={onUnauthorized}
        />
      ) : null}
    </section>
  );
}

const UPLOAD_ACCEPT = ".pdf,.pptx,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation";

const TERMINAL = new Set(["indexed", "rejected"]);

/**
 * A PDF or a deck: recognition takes seconds per page, so the server answers 202 and the cabinet
 * polls. Showing a spinner without a state is a lie — every poll prints what the worker is doing.
 */
function FileUpload({ onUnauthorized }: { onUnauthorized: () => void }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [metadata, setMetadata] = useState<FileMetadata>({
    id: "",
    title: "",
    owner: "hr",
    audience: ["all"],
    valid_from: new Date().toISOString().slice(0, 10),
  });
  const [hash, setHash] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => uploadKnowledgeFile(file as File, metadata),
    onSuccess: (queued) => setHash(queued.content_hash),
  });

  const extraction = useQuery({
    queryKey: ["extraction", hash],
    queryFn: () => fetchExtraction(hash as string),
    enabled: hash !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : REFRESH.extraction;
    },
  });

  useUnauthorized(upload.error ?? extraction.error, onUnauthorized);

  const done = extraction.data ? TERMINAL.has(extraction.data.status) : false;

  // The new document is only in the index once the worker says so: refresh the list then, once.
  useEffect(() => {
    if (done) void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
  }, [done, queryClient]);

  function reset() {
    setFile(null);
    setHash(null);
    setMetadata((current) => ({ ...current, id: "", title: "" }));
    upload.reset();
    queryClient.removeQueries({ queryKey: ["extraction", hash] });
  }

  const field = <K extends keyof FileMetadata>(key: K) => ({
    value: key === "audience" ? metadata.audience.join(", ") : String(metadata[key]),
    onChange: (event: { target: { value: string } }) =>
      setMetadata((current) => ({
        ...current,
        [key]:
          key === "audience"
            ? event.target.value
                .split(",")
                .map((part) => part.trim())
                .filter(Boolean)
            : event.target.value,
      })),
  });

  return (
    <section className="card">
      <div className="card-head">
        <h2>PDF или презентация</h2>
        <span className="card-note">Распознаётся в фоне</span>
      </div>
      <p className="upload-hint">
        Файл сохраняется по хешу, страницы распознаются воркером и попадают в тот же индекс, что и
        markdown. Прогресс виден здесь; закрывать вкладку не обязательно.
      </p>

      <form
        className="upload"
        onSubmit={(event) => {
          event.preventDefault();
          upload.mutate();
        }}
      >
        <label className="upload-label" htmlFor="knowledge-file">
          Файл
        </label>
        <input
          id="knowledge-file"
          type="file"
          accept={UPLOAD_ACCEPT}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          disabled={upload.isPending || hash !== null}
        />

        <div className="upload-fields">
          <label>
            id
            <input type="text" required placeholder="hr/onboarding-guide" {...field("id")} />
          </label>
          <label>
            Название
            <input type="text" required placeholder="Гид по онбордингу" {...field("title")} />
          </label>
          <label>
            owner
            <input type="text" required {...field("owner")} />
          </label>
          <label>
            audience
            <input type="text" {...field("audience")} />
          </label>
          <label>
            valid_from
            <input type="date" required {...field("valid_from")} />
          </label>
        </div>

        <div className="upload-actions">
          <button
            type="submit"
            className="button button-primary"
            disabled={!file || !metadata.id || !metadata.title || upload.isPending || hash !== null}
          >
            {upload.isPending ? "Отправляем…" : "Загрузить файл"}
          </button>
        </div>

        {upload.isError ? <ErrorNote error={upload.error} /> : null}

        {hash ? (
          <div className="note" role="status">
            {extraction.isPending ? <p>В очереди на распознавание…</p> : null}
            {extraction.data ? (
              <p>
                {extraction.data.status === "indexed"
                  ? `Готово: ${countLabel(extraction.data.pages, "страница", "страницы", "страниц")}, движок ${extraction.data.engine}.`
                  : extraction.data.status === "rejected"
                    ? `Распознавание отказано: ${extraction.data.reason ?? "причина не указана"}.`
                    : "Распознаём страницы…"}
              </p>
            ) : null}
            {extraction.isError ? <ErrorNote error={extraction.error} /> : null}
            {done ? (
              <button type="button" className="button button-quiet" onClick={reset}>
                Загрузить ещё
              </button>
            ) : null}
          </div>
        ) : null}
      </form>
    </section>
  );
}
