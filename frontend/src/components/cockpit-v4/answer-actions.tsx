/**
 * What you can do with an answer once you have read it.
 *
 * Four actions, all of them on a finished run: save it, put it in an
 * investigation, comment on it, share it with a colleague.
 *
 * The delivery line is the rule this component exists to hold. It renders
 * whatever `deliveryWording` returns and nothing else, so the only sentence
 * on this screen that says "Sent" is one the server reached by handing the
 * message to a named transport that accepted it. A build with no transport
 * -- which is every build nobody has configured one for -- shows "Recorded,
 * not sent" and says why.
 */

"use client";

import { useCallback, useState } from "react";

import {
  addComment,
  createInvestigation,
  deliveryWording,
  saveAnalysis,
  shareItem,
  type Notification,
  type SavedAnalysis,
} from "./client";

type Panel = "" | "save" | "investigate" | "comment" | "share";

function Button({
  id,
  label,
  active,
  onClick,
  disabled,
}: {
  id: string;
  label: string;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      data-testid={`v4-action-${id}`}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={
        "rounded border px-2.5 py-1 text-xs font-medium transition " +
        (active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-slate-300 text-slate-700 hover:border-slate-400") +
        (disabled ? " cursor-not-allowed opacity-50" : "")
      }
    >
      {label}
    </button>
  );
}

export function AnswerActions({
  runId,
  question,
  threadId,
}: {
  runId: string;
  question: string;
  threadId?: string;
}) {
  const [panel, setPanel] = useState<Panel>("");
  const [saved, setSaved] = useState<SavedAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [notification, setNotification] = useState<Notification | null>(null);
  const [notified, setNotified] = useState(false);

  const [title, setTitle] = useState(question.slice(0, 120));
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const [audience, setAudience] = useState("");
  const [email, setEmail] = useState("");

  const ensureSaved = useCallback(async (): Promise<SavedAnalysis> => {
    if (saved) return saved;
    const record = await saveAnalysis({ run_id: runId, title, note });
    setSaved(record);
    return record;
  }, [saved, runId, title, note]);

  const guard = useCallback(
    async (work: () => Promise<string>) => {
      setBusy(true);
      setStatus("");
      try {
        setStatus(await work());
      } catch (error) {
        setStatus(
          error instanceof Error
            ? `That did not go through: ${error.message}`
            : "That did not go through.",
        );
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return (
    <div
      className="mt-4 border-t border-slate-200 pt-3"
      data-testid="v4-answer-actions"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wide text-slate-400">
          Do something with this
        </span>
        <Button
          id="save"
          label={saved ? "Saved" : "Save"}
          active={panel === "save"}
          onClick={() => setPanel(panel === "save" ? "" : "save")}
        />
        <Button
          id="investigate"
          label="Add to investigation"
          active={panel === "investigate"}
          onClick={() => setPanel(panel === "investigate" ? "" : "investigate")}
        />
        <Button
          id="comment"
          label="Comment"
          active={panel === "comment"}
          onClick={() => setPanel(panel === "comment" ? "" : "comment")}
        />
        <Button
          id="share"
          label="Share"
          active={panel === "share"}
          onClick={() => setPanel(panel === "share" ? "" : "share")}
        />
      </div>

      {panel === "save" ? (
        <div className="mt-3 space-y-2" data-testid="v4-panel-save">
          <label className="block text-xs text-slate-600">
            Title
            <input
              data-testid="v4-save-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="block text-xs text-slate-600">
            Why you are keeping it
            <input
              data-testid="v4-save-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            data-testid="v4-save-submit"
            disabled={busy}
            onClick={() =>
              void guard(async () => {
                const record = await ensureSaved();
                return `Saved as “${record.title}”.`;
              })
            }
            className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            Save this analysis
          </button>
        </div>
      ) : null}

      {panel === "investigate" ? (
        <div className="mt-3 space-y-2" data-testid="v4-panel-investigate">
          <label className="block text-xs text-slate-600">
            Investigation title
            <input
              data-testid="v4-investigation-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            data-testid="v4-investigation-submit"
            disabled={busy}
            onClick={() =>
              void guard(async () => {
                const record = await ensureSaved();
                const investigation = await createInvestigation({
                  title,
                  summary: note,
                  origin: "answer",
                  thread_id: threadId ?? "",
                  saved_ids: [record.saved_id],
                });
                return `Opened “${investigation.title}” with this analysis in it.`;
              })
            }
            className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            Open an investigation
          </button>
        </div>
      ) : null}

      {panel === "comment" ? (
        <div className="mt-3 space-y-2" data-testid="v4-panel-comment">
          <textarea
            data-testid="v4-comment-body"
            value={comment}
            rows={3}
            onChange={(event) => setComment(event.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            placeholder="What should a reviewer check?"
          />
          <button
            type="button"
            data-testid="v4-comment-submit"
            disabled={busy || !comment.trim()}
            onClick={() =>
              void guard(async () => {
                const record = await ensureSaved();
                await addComment({
                  subject_kind: "saved_analysis",
                  subject_id: record.saved_id,
                  body: comment.trim(),
                });
                setComment("");
                return "Comment added.";
              })
            }
            className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            Add comment
          </button>
        </div>
      ) : null}

      {panel === "share" ? (
        <div className="mt-3 space-y-2" data-testid="v4-panel-share">
          <label className="block text-xs text-slate-600">
            Colleague or group inside the bank
            <input
              data-testid="v4-share-audience"
              value={audience}
              onChange={(event) => setAudience(event.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="block text-xs text-slate-600">
            Notify by email (optional)
            <input
              data-testid="v4-share-email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            data-testid="v4-share-submit"
            disabled={busy || !audience.trim()}
            onClick={() =>
              void guard(async () => {
                const record = await ensureSaved();
                const result = await shareItem({
                  subject_kind: "saved_analysis",
                  subject_id: record.saved_id,
                  audience_id: audience.trim(),
                  message: note,
                  notify_email: email.trim(),
                });
                setNotification(result.notification);
                setNotified(true);
                return `Shared with ${result.share.audience_id}.`;
              })
            }
            className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            Share
          </button>
          {notified ? (
            <p
              data-testid="v4-share-delivery"
              className={
                "text-xs " +
                (notification?.delivered ? "text-emerald-700" : "text-amber-700")
              }
            >
              {deliveryWording(notification)}
            </p>
          ) : null}
        </div>
      ) : null}

      {status ? (
        <p className="mt-2 text-xs text-slate-600" data-testid="v4-action-status">
          {status}
        </p>
      ) : null}
    </div>
  );
}
