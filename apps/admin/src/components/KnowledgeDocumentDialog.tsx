import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { fetchExtraction, fetchKnowledgeDocument, updateKnowledge } from "../api";
import { REFRESH } from "../config";
import { formatDateTime } from "../format";
import { useUnauthorized } from "../useUnauthorized";
import { ErrorNote } from "./States";

const TERMINAL = new Set(["indexed", "rejected"]);

/** The readable part of a source document: frontmatter is already shown as metadata cards. */
function bodyOf(text: string): string {
  const frontmatter = /^---\s*\n[\s\S]*?\n---\s*\n?/.exec(text);
  return (frontmatter ? text.slice(frontmatter[0].length) : text).trimStart();
}

/**
 * One active document: read the exact markdown the index was built from, and, for HR, replace it.
 *
 * The dialog is keyed by document id in the page, so opening another row never carries a draft
 * from the previous document.
 */
export function KnowledgeDocumentDialog({
  documentId,
  canWrite,
  onClose,
  onUnauthorized,
}: {
  documentId: string;
  canWrite: boolean;
  onClose: () => void;
  onUnauthorized: () => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [hash, setHash] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["knowledge", documentId],
    queryFn: () => fetchKnowledgeDocument(documentId),
  });

  const update = useMutation({
    mutationFn: (text: string) => updateKnowledge(documentId, text),
    onSuccess: (queued) => {
      setEditing(false);
      setHash(queued.content_hash);
    },
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

  const done = extraction.data ? TERMINAL.has(extraction.data.status) : false;
  const unavailable = detail.data?.text == null;

  // The raw text is the source of truth until the user starts editing. A background refetch while
  // a draft is open must not overwrite what they are typing.
  useEffect(() => {
    if (!editing && detail.data) setDraft(detail.data.text ?? "");
  }, [detail.data, editing]);

  // The new version is only in the index when the worker says so. Refresh both the list and this
  // document then, once.
  useEffect(() => {
    if (!done) return;
    void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
  }, [done, queryClient, documentId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !editing && !update.isPending) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editing, onClose, update.isPending]);

  useUnauthorized(detail.error ?? update.error ?? extraction.error, onUnauthorized);

  return (
    <div
      className="knowledge-modal"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !update.isPending) onClose();
      }}
    >
      <div
        className="knowledge-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="knowledge-dialog-title"
      >
        <header className="knowledge-dialog-head">
          <div className="knowledge-dialog-title">
            <p className="eyebrow">Активный документ</p>
            <h2 id="knowledge-dialog-title">{detail.data?.title ?? documentId}</h2>
            <p className="document-id">
              <code>{documentId}</code>
            </p>
          </div>
          <button
            type="button"
            className="button button-quiet knowledge-dialog-close"
            onClick={onClose}
            aria-label="Закрыть документ"
          >
            Закрыть
          </button>
        </header>

        <div className="knowledge-dialog-body">
          {detail.isPending ? <p className="empty-inline">Открываем документ…</p> : null}
          {detail.isError ? (
            <ErrorNote error={detail.error} onRetry={() => void detail.refetch()} />
          ) : null}
          {detail.data ? (
            <>
              <dl className="document-meta">
                <div>
                  <dt>Тип</dt>
                  <dd>{detail.data.type}</dd>
                </div>
                <div>
                  <dt>Аудитория</dt>
                  <dd>{detail.data.audience.join(", ") || "—"}</dd>
                </div>
                <div>
                  <dt>Владелец</dt>
                  <dd>{detail.data.owner}</dd>
                </div>
                <div>
                  <dt>Обновлён</dt>
                  <dd>{formatDateTime(detail.data.updated_at)}</dd>
                </div>
              </dl>

              {editing ? (
                <label className="document-editor-label" htmlFor="knowledge-document-text">
                  Markdown с frontmatter
                  <textarea
                    id="knowledge-document-text"
                    className="upload-area document-editor"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    rows={16}
                    spellCheck={false}
                  />
                </label>
              ) : unavailable ? (
                <p className="note">
                  Исходный текст этого документа не сохранён: он проиндексирован до появления
                  редактора. Переиндексируйте документ, чтобы открыть его здесь.
                </p>
              ) : (
                <pre className="document-text">{bodyOf(detail.data.text ?? "")}</pre>
              )}

              {hash ? (
                <p
                  className={
                    extraction.data?.status === "rejected"
                      ? "note note-error"
                      : done
                        ? "note note-ok"
                        : "note"
                  }
                  role="status"
                >
                  {extraction.isPending
                    ? "Сохраняем: ставим документ в очередь на переиндексацию…"
                    : extraction.data
                      ? extraction.data.status === "indexed"
                        ? "Документ обновлён и переиндексирован."
                        : extraction.data.status === "rejected"
                          ? `Переиндексация отклонена: ${extraction.data.reason ?? "причина не указана"}.`
                          : "Воркер переиндексирует документ…"
                      : "Документ в очереди на переиндексацию."}
                </p>
              ) : null}

              {extraction.isError ? <ErrorNote error={extraction.error} /> : null}
              {update.isError ? <ErrorNote error={update.error} /> : null}
            </>
          ) : null}
        </div>

        <footer className="knowledge-dialog-foot">
          {!editing && !unavailable && detail.data ? (
            canWrite ? (
              <button
                type="button"
                className="button button-primary"
                onClick={() => {
                  setDraft(detail.data.text ?? "");
                  setEditing(true);
                  setHash(null);
                  update.reset();
                }}
                disabled={update.isPending}
              >
                Редактировать
              </button>
            ) : (
              <p className="muted">Изменять документы может только HR-администратор.</p>
            )
          ) : null}

          {editing ? (
            <>
              <button
                type="button"
                className="button button-quiet"
                onClick={() => {
                  setEditing(false);
                  setDraft(detail.data?.text ?? "");
                  update.reset();
                }}
                disabled={update.isPending}
              >
                Отмена
              </button>
              <button
                type="button"
                className="button button-primary"
                onClick={() => update.mutate(draft)}
                disabled={update.isPending || draft.trim().length < 20}
              >
                {update.isPending ? "Сохраняем…" : "Сохранить и переиндексировать"}
              </button>
            </>
          ) : null}
        </footer>
      </div>
    </div>
  );
}
