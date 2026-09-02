"use client";

import * as React from "react";

import {
  AttachmentCard,
  Body,
  REQUEST_LABEL,
  STATUS_LABEL,
  Sender,
  SystemActions,
  when,
} from "@/components/messages/parts";
import { Button } from "@/components/ui/button";
import { api, type Message, type RequestStatus } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * One conversation, and the composer that continues it.
 *
 * Opening it marks it read — for this reader only. The messages below it are
 * the whole thread, oldest first, each with what it carried: a reply does not
 * quote the message above it, because the message above it is right there.
 *
 * A request carries its own panel. The reader sees where it has got to, the
 * moves they may make from here (the ones the state machine permits, and no
 * others), and every move anybody has already made with the note they left.
 */
export function ThreadView({ threadId }: { threadId: number }) {
  const [reload, setReload] = React.useState(0);
  const thread = useAsync(() => api.messageThread(threadId), [threadId, reload]);

  // Marked read once, on arrival. A thread that re-marks itself on every
  // re-render writes a row for every keystroke in the reply box.
  const marked = React.useRef(false);
  React.useEffect(() => {
    if (!thread.data || marked.current) return;
    marked.current = true;
    void api.markThreadRead(threadId, true).catch(() => {});
  }, [thread.data, threadId]);

  if (thread.loading) {
    return <p className="py-10 text-center text-sm text-text-muted">Loading…</p>;
  }
  if (thread.error || !thread.data) {
    return (
      <div className="rounded-lg border border-dashed border-border py-12 text-center">
        <p className="text-sm text-text-secondary">
          {/* A thread you are not in and a thread that does not exist give the
              same answer, so this sentence has to be true of both. */}
          That conversation is not available to you.
        </p>
      </div>
    );
  }

  const data = thread.data;
  const request = [...data.messages]
    .reverse()
    .find((m) => m.request_type !== "fyi" && m.request_status);

  return (
    <div className="space-y-5">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold text-text-primary">
          {data.subject}
        </h1>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
          <span>
            {data.participants.map((p) => p.name).filter(Boolean).join(", ")}
          </span>
          <span className="text-text-muted">
            · {data.messages.length}{" "}
            {data.messages.length === 1 ? "message" : "messages"}
          </span>
        </p>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              await api.archiveMessageThread(threadId, !data.archived);
              setReload((n) => n + 1);
            }}
          >
            {data.archived ? "Restore to inbox" : "Archive"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              await api.markThreadRead(threadId, false);
              setReload((n) => n + 1);
            }}
          >
            Mark unread
          </Button>
        </div>
      </header>

      {request && (
        <RequestPanel
          message={request}
          onChanged={() => setReload((n) => n + 1)}
        />
      )}

      <ol className="space-y-4">
        {data.messages
          .filter((m) => m.status === "sent")
          .map((m) => (
            <li
              key={m.id}
              className={cn(
                "rounded-lg border bg-surface p-4",
                m.sender.type === "SYSTEM"
                  ? "border-accent/30"
                  : "border-border",
              )}
            >
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <Sender sender={m.sender} className="text-sm" />
                <span className="text-xs text-text-muted">
                  {when(m.sent_at)}
                </span>
              </div>
              <Body text={m.body} />
              {m.attachments.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-text-muted">
                    Attachments
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {m.attachments.map((a) => (
                      <AttachmentCard key={a.id} attachment={a} />
                    ))}
                  </div>
                </div>
              )}
              <SystemActions actions={m.actions} />
            </li>
          ))}
      </ol>

      <ReplyBox threadId={threadId} onSent={() => setReload((n) => n + 1)} />
    </div>
  );
}

/** What the state machine allows from here. Nothing else is offered. */
const NEXT: Record<RequestStatus, RequestStatus[]> = {
  open: ["in_review", "responded", "closed"],
  in_review: ["responded", "closed"],
  responded: ["closed", "in_review"],
  closed: [],
};

function RequestPanel({ message, onChanged }: {
  message: Message;
  onChanged: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const history = useAsync(() => api.requestHistory(message.id), [message.id,
                                                                 message.request_status]);
  const status = (message.request_status ?? "open") as RequestStatus;

  async function move(to: RequestStatus) {
    setBusy(true);
    setError(null);
    try {
      await api.changeRequestStatus(message.id, to);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the status.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-surface-sunken p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-muted">
            {REQUEST_LABEL[message.request_type]}
          </p>
          <p className="mt-0.5 text-sm font-medium text-text-primary">
            Status: {STATUS_LABEL[status]}
            {message.due_at && (
              <span className="ml-2 font-normal text-text-secondary">
                · due {when(message.due_at)}
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {NEXT[status].map((next) => (
            <Button
              key={next}
              size="sm"
              variant={next === "closed" ? "ghost" : "default"}
              disabled={busy}
              onClick={() => move(next)}
            >
              {next === "in_review"
                ? "Start review"
                : next === "responded"
                  ? "Mark responded"
                  : "Close"}
            </Button>
          ))}
        </div>
      </div>
      {error && <p className="mt-2 text-xs text-negative">{error}</p>}
      {history.data && history.data.events.length > 0 && (
        <ol className="mt-3 space-y-1 border-t border-border pt-3">
          {history.data.events.map((e, i) => (
            <li key={i} className="text-xs text-text-secondary">
              <span className="text-text-primary">
                {STATUS_LABEL[e.to_status]}
              </span>
              {e.actor && <> · {e.actor}</>}
              {e.at && <> · {when(e.at)}</>}
              {e.note && <> — {e.note}</>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ReplyBox({ threadId, onSent }: {
  threadId: number;
  onSent: () => void;
}) {
  const [body, setBody] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.replyToThread(threadId, { body });
      setBody("");
      onSent();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the reply.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <label htmlFor="reply-body" className="sr-only">
        Reply
      </label>
      <textarea
        id="reply-body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={3}
        placeholder="Reply…"
        className="w-full resize-y rounded-md border-0 bg-transparent px-1 py-1 text-sm leading-[1.6] text-text-primary placeholder:text-text-muted focus:outline-none"
      />
      {error && <p className="px-1 pb-1 text-xs text-negative">{error}</p>}
      <div className="flex justify-end">
        <Button size="sm" onClick={send} disabled={busy || !body.trim()}>
          Reply
        </Button>
      </div>
    </div>
  );
}
