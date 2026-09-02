"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  AttachmentChips,
  RequestBadge,
  Sender,
  Stat,
  when,
} from "@/components/messages/parts";
import { Button } from "@/components/ui/button";
import {
  api,
  type AttachmentSpec,
  type DraftSummary,
  type Mailbox,
  type MessageSummary,
  type Person,
  type RequestType,
  type SentSummary,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * The messaging centre.
 *
 * Five views over the same rows rather than five folders a message is moved
 * between: archiving is a fact about ONE PERSON's copy, so filing a thread away
 * leaves it in everybody else's inbox. Action Required is a filter, not a
 * queue — a request lives in the inbox and is also listed here while it is
 * open, which is what stops it being two things that can disagree.
 *
 * Every list is paginated and carries no bodies beyond a preview and no
 * attachment payloads at all. The counts and the kinds come from the list
 * endpoint; the content arrives when a thread is opened.
 */

const BOXES: { key: Mailbox; label: string }[] = [
  { key: "inbox", label: "Inbox" },
  { key: "action", label: "Action required" },
  { key: "sent", label: "Sent" },
  { key: "drafts", label: "Drafts" },
  { key: "archived", label: "Archived" },
];

export function MessageCentre() {
  const router = useRouter();
  const params = useSearchParams();
  const initial = (params.get("box") as Mailbox) ?? "inbox";

  const [box, setBox] = React.useState<Mailbox>(
    BOXES.some((b) => b.key === initial) ? initial : "inbox",
  );
  const [query, setQuery] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [unreadOnly, setUnreadOnly] = React.useState(false);
  const [composing, setComposing] = React.useState(false);
  const [reload, setReload] = React.useState(0);

  const counts = useAsync(() => api.messageCounts(), [reload]);
  const page = useAsync(
    () => api.mailbox(box, { q: search, unread: unreadOnly, limit: 50 }),
    [box, search, unreadOnly, reload],
  );

  // The filter only applies where it means something. "Unread" in Sent asks a
  // question about somebody else's reading, which this product does not track
  // and should not pretend to.
  const canFilterUnread = box === "inbox" || box === "archived";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid grid-cols-3 gap-2 sm:max-w-md">
          <Stat label="Unread" value={counts.data?.unread ?? 0} />
          <Stat label="Action required" value={counts.data?.action_required ?? 0} />
          <Stat label="Shared with me" value={counts.data?.shared_with_me ?? 0} />
        </div>
        <Button onClick={() => setComposing(true)}>New message</Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-2">
        {BOXES.map((b) => (
          <button
            key={b.key}
            type="button"
            onClick={() => setBox(b.key)}
            aria-current={box === b.key ? "page" : undefined}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              box === b.key
                ? "bg-accent/10 text-accent"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {b.label}
            {b.key === "inbox" && (counts.data?.unread ?? 0) > 0 && (
              <span className="ml-1.5 tabular-nums">
                {counts.data?.unread}
              </span>
            )}
            {b.key === "action" && (counts.data?.action_required ?? 0) > 0 && (
              <span className="ml-1.5 tabular-nums">
                {counts.data?.action_required}
              </span>
            )}
          </button>
        ))}
        <form
          className="ml-auto flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(query.trim());
          }}
        >
          <input
            id="message-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search subject, message or attachment"
            aria-label="Search messages"
            className="w-64 rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          {canFilterUnread && (
            <label className="flex items-center gap-1.5 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(e) => setUnreadOnly(e.target.checked)}
              />
              Unread
            </label>
          )}
        </form>
      </div>

      {page.loading && (
        <p className="py-10 text-center text-sm text-text-muted">Loading…</p>
      )}
      {page.error && (
        <p className="py-10 text-center text-sm text-negative">{page.error}</p>
      )}
      {!page.loading && page.data && page.data.items.length === 0 && (
        <EmptyBox box={box} searching={Boolean(search)} />
      )}
      {page.data && page.data.items.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {page.data.items.map((item) =>
            box === "sent" ? (
              <SentRow key={(item as SentSummary).message_id}
                       item={item as SentSummary} />
            ) : box === "drafts" ? (
              <DraftRow key={(item as DraftSummary).message_id}
                        item={item as DraftSummary} />
            ) : (
              <InboxRow key={(item as MessageSummary).thread_id}
                        item={item as MessageSummary} />
            ),
          )}
        </ul>
      )}
      {page.data && page.data.total > page.data.items.length && (
        <p className="text-center text-xs text-text-muted">
          Showing {page.data.items.length} of {page.data.total.toLocaleString()}.
        </p>
      )}

      {composing && (
        <Compose
          onClose={() => setComposing(false)}
          onSent={(threadId) => {
            setComposing(false);
            setReload((n) => n + 1);
            router.push(`/messages/${threadId}`);
          }}
        />
      )}
    </div>
  );
}

/**
 * An empty state that says what this box is FOR.
 *
 * "No messages" is true of every empty list in every product. What a reader
 * needs is whether they are looking at the right place.
 */
function EmptyBox({ box, searching }: { box: Mailbox; searching: boolean }) {
  const said = searching
    ? "Nothing matched that search."
    : box === "action"
      ? "Nothing is waiting on you."
      : box === "drafts"
        ? "No unsent messages."
        : box === "sent"
          ? "You have not sent anything yet."
          : box === "archived"
            ? "Nothing filed away."
            : "Your inbox is empty.";
  return (
    <div className="rounded-lg border border-dashed border-border py-12 text-center">
      <p className="text-sm text-text-secondary">{said}</p>
    </div>
  );
}

function InboxRow({ item }: { item: MessageSummary }) {
  return (
    <li>
      <a
        href={`/messages/${item.thread_id}`}
        className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-sunken"
      >
        <span
          aria-hidden
          className={cn(
            "mt-1.5 size-2 shrink-0 rounded-full",
            item.unread ? "bg-accent" : "bg-transparent",
          )}
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span
              className={cn(
                "truncate text-sm",
                item.unread
                  ? "font-semibold text-text-primary"
                  : "text-text-primary",
              )}
            >
              {item.subject}
            </span>
            {item.message_count > 1 && (
              <span className="shrink-0 text-xs text-text-muted">
                {item.message_count}
              </span>
            )}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
            <Sender sender={item.sender} />
            <AttachmentChips types={item.attachment_types} />
          </span>
          {item.preview && (
            <span className="mt-1 block truncate text-xs text-text-muted">
              {item.preview}
            </span>
          )}
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-xs text-text-muted">
            {when(item.last_message_at)}
          </span>
          <RequestBadge type={item.request_type} status={item.request_status} />
        </span>
      </a>
    </li>
  );
}

function SentRow({ item }: { item: SentSummary }) {
  const to = item.recipients.map((r) => r.name).filter(Boolean).join(", ");
  return (
    <li>
      <a
        href={`/messages/${item.thread_id}`}
        className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-sunken"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-text-primary">
            {item.subject}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
            <span className="truncate">To {to || "—"}</span>
            <AttachmentChips types={item.attachment_types} />
          </span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-xs text-text-muted">{when(item.sent_at)}</span>
          <RequestBadge type={item.request_type} status={item.request_status} />
        </span>
      </a>
    </li>
  );
}

function DraftRow({ item }: { item: DraftSummary }) {
  return (
    <li>
      <a
        href={`/messages/${item.thread_id}`}
        className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-sunken"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-text-primary">
            {item.subject || "(no subject)"}
          </span>
          <span className="mt-0.5 block truncate text-xs text-text-muted">
            {item.preview || "Nothing written yet."}
          </span>
        </span>
        <span className="shrink-0 text-xs text-text-muted">
          {when(item.created_at)}
        </span>
      </a>
    </li>
  );
}

/**
 * Compose.
 *
 * The recipient picker searches the governed directory, which excludes anybody
 * whose account has been suspended: offering somebody who cannot sign in
 * produces a message that is delivered and never read, and that looks exactly
 * like a message that was ignored.
 */
function Compose({ onClose, onSent }: {
  onClose: () => void;
  onSent: (threadId: number) => void;
}) {
  const [to, setTo] = React.useState<Person[]>([]);
  const [find, setFind] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [body, setBody] = React.useState("");
  const [requestType, setRequestType] = React.useState<RequestType>("fyi");
  const [attachments, setAttachments] = React.useState<AttachmentSpec[]>([]);
  const [attachLabels, setAttachLabels] = React.useState<string[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const directory = useAsync(() => api.messageDirectory(find, 20), [find]);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const sent = await api.sendMessage({
        to: to.map((p) => p.id),
        subject,
        body,
        attachments,
        request_type: requestType,
      });
      onSent(sent.thread_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    setBusy(true);
    setError(null);
    try {
      const draft = await api.createDraft({ subject, body });
      if (attachments.length) {
        await api.updateDraft(draft.message_id, { attachments });
      }
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setError(null);
    try {
      const stored = await api.uploadAttachment(file);
      setAttachments((a) => [...a, { type: "file",
                                     artifact_id: stored.artifact_id }]);
      setAttachLabels((l) => [...l, stored.filename]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not attach that file.");
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="New message"
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4 sm:p-8"
    >
      <div className="w-full max-w-2xl rounded-xl border border-border bg-surface shadow-lg">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold text-text-primary">New message</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-text-muted hover:text-text-primary"
          >
            ×
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div>
            <label htmlFor="compose-to"
                   className="mb-1 block text-xs font-medium text-text-secondary">
              To
            </label>
            <div className="mb-1.5 flex flex-wrap gap-1.5">
              {to.map((p) => (
                <span key={p.id}
                      className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-1 text-xs text-accent">
                  {p.name}
                  <button type="button"
                          aria-label={`Remove ${p.name}`}
                          onClick={() => setTo((c) => c.filter((x) => x.id !== p.id))}>
                    ×
                  </button>
                </span>
              ))}
            </div>
            <input
              id="compose-to"
              value={find}
              onChange={(e) => setFind(e.target.value)}
              placeholder="Search by name, job title, team or role"
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
            {find && directory.data && (
              <ul className="mt-1 max-h-44 overflow-y-auto rounded-md border border-border">
                {directory.data.users
                  .filter((p) => !to.some((x) => x.id === p.id))
                  .map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setTo((c) => [...c, p]);
                          setFind("");
                        }}
                        className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-xs hover:bg-surface-sunken"
                      >
                        <span className="font-medium text-text-primary">
                          {p.name}
                        </span>
                        <span className="text-text-muted">
                          {[p.job_title, p.team].filter(Boolean).join(" · ")}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            )}
          </div>

          <div>
            <label htmlFor="compose-subject"
                   className="mb-1 block text-xs font-medium text-text-secondary">
              Subject
            </label>
            <input
              id="compose-subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
            />
          </div>

          <div>
            <label htmlFor="compose-body"
                   className="mb-1 block text-xs font-medium text-text-secondary">
              Message
            </label>
            <textarea
              id="compose-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={6}
              className="w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm leading-[1.6] text-text-primary focus:border-accent focus:outline-none"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs font-medium text-text-secondary">
              This message is
              <select
                value={requestType}
                onChange={(e) => setRequestType(e.target.value as RequestType)}
                aria-label="What this message is asking for"
                className="ml-2 rounded-md border border-border bg-surface px-2 py-1 text-xs text-text-primary"
              >
                <option value="fyi">for information</option>
                <option value="review">a review request</option>
                <option value="action">an action request</option>
              </select>
            </label>
            <label className="cursor-pointer text-xs font-medium text-accent">
              Attach a file
              <input
                type="file"
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void upload(file);
                  e.target.value = "";
                }}
              />
            </label>
          </div>

          {attachLabels.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {attachLabels.map((name, i) => (
                <li key={`${name}-${i}`}
                    className="rounded border border-border bg-surface-sunken px-2 py-1 text-xs text-text-secondary">
                  {name}
                </li>
              ))}
            </ul>
          )}

          {error && <p className="text-xs text-negative">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="ghost" onClick={saveDraft} disabled={busy}>
            Save draft
          </Button>
          <Button
            onClick={send}
            disabled={busy || to.length === 0 || !subject.trim()}
          >
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}
