"use client";

import { useSearchParams } from "next/navigation";
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
  type ShareableObject,
} from "@/lib/api";
import { useAttention } from "@/lib/attention";
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
  const [notice, setNotice] = React.useState("");

  // Not a fetch of its own: the tiles, the tabs and the header badge all read
  // the same store, so a number that moves moves everywhere at once.
  const { safe: counts, refresh: refreshCounts } = useAttention();
  React.useEffect(() => {
    void refreshCounts();
  }, [reload, refreshCounts]);

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
          <Stat label="Unread" value={counts.unread} />
          <Stat label="Action required" value={counts.action_required} />
          <Stat label="Shared with me" value={counts.shared_with_me} />
        </div>
        <Button onClick={() => setComposing(true)}>New message</Button>
      </div>

      {notice && (
        <div
          role="status"
          className="flex items-center justify-between rounded-md border border-positive/30 bg-positive/5 px-3 py-2 text-xs text-text-primary"
        >
          <span>{notice}</span>
          <button type="button" aria-label="Dismiss"
                  className="text-text-muted hover:text-text-primary"
                  onClick={() => setNotice("")}>
            ×
          </button>
        </div>
      )}

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
            {b.key === "inbox" && counts.unread > 0 && (
              <span className="ml-1.5 tabular-nums" data-testid="tab-unread">
                {counts.unread}
              </span>
            )}
            {b.key === "action" && counts.action_required > 0 && (
              <span className="ml-1.5 tabular-nums">
                {counts.action_required}
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
          {/*
            The row shape follows the DATA, not the tab. `page.data.box` is
            what the backend actually returned; `box` is what the reader has
            most recently clicked. Between the click and the response arriving
            they disagree for one render, and choosing by the tab drew Sent
            rows over Inbox items — a crash, because an inbox row has no
            recipient list to draw.
          */}
          {page.data.items.map((item, _i, _all, shown = page.data!.box) =>
            shown === "sent" ? (
              <SentRow key={(item as SentSummary).message_id}
                       item={item as SentSummary} />
            ) : shown === "drafts" ? (
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
          onSent={(sent) => {
            // Close, confirm, and land in Sent — where the thing that just
            // happened is visible. Opening the thread instead would mark it
            // read on arrival, and a self-addressed message would clear its own
            // unread badge before the sender ever saw it appear.
            setComposing(false);
            setNotice(
              sent.recipients > 1
                ? `Message sent to ${sent.recipients} people.`
                : "Message sent.",
            );
            setBox("sent");
            setReload((n) => n + 1);
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
 * Two things here were wrong and are the reason this component was rewritten.
 *
 * The recipient list rendered only once something had been typed, so a sender
 * who clicked into the To field saw an empty box and concluded there were no
 * colleagues configured. A directory people have to guess their way into is not
 * a directory. It now loads on focus and shows who is there; typing narrows it
 * across name, username, email, job title, department, team and role.
 *
 * And attaching a governed object meant knowing its id. Now "Share from
 * CreditProbe" lists the analyses and investigations THIS sender can actually
 * read, as cards — the backend access-checks every one before offering it, so
 * a card that appears can be attached and the send cannot fail for a reason the
 * picker already knew about.
 */
function Compose({ onClose, onSent }: {
  onClose: () => void;
  onSent: (sent: { threadId: number; recipients: number }) => void;
}) {
  const [to, setTo] = React.useState<Person[]>([]);
  const [find, setFind] = React.useState("");
  const [picking, setPicking] = React.useState(false);
  const [subject, setSubject] = React.useState("");
  const [body, setBody] = React.useState("");
  const [requestType, setRequestType] = React.useState<RequestType>("fyi");
  const [attachments, setAttachments] = React.useState<AttachmentSpec[]>([]);
  const [attachLabels, setAttachLabels] = React.useState<string[]>([]);
  const [sharing, setSharing] = React.useState<"analysis" | "investigation" | null>(
    null,
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // One token per send attempt, minted on the first press of Send and kept for
  // any retry of it. Pressing Send twice — or a request the browser retried
  // after a timeout it never saw the answer to — carries the same token, and
  // the backend answers with the message it already created rather than
  // putting a second copy in somebody's inbox.
  //
  // Minted in the handler rather than during render: a value drawn from the
  // clock or the random source while rendering is not a pure render, and a
  // re-render would silently change the identity of the send in flight.
  const token = React.useRef("");

  // Empty query included: the point is that focusing the field shows people.
  const directory = useAsync(() => api.messageDirectory(find, 50), [find]);
  const chosen = new Set(to.map((p) => p.id));
  const offered = (directory.data?.users ?? []).filter((p) => !chosen.has(p.id));

  async function send() {
    if (!token.current) token.current = crypto.randomUUID();
    setBusy(true);
    setError(null);
    try {
      const sent = await api.sendMessage({
        to: to.map((p) => p.id),
        subject,
        body,
        attachments,
        request_type: requestType,
        client_token: token.current,
      });
      onSent({ threadId: sent.thread_id, recipients: to.length });
    } catch (e) {
      // A send that failed says so and leaves the composer open with
      // everything still in it. Closing on failure would look exactly like
      // success and lose what was written.
      setError(e instanceof Error ? e.message : "Could not send.");
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

  function attachObject(item: ShareableObject) {
    setAttachments((a) => [
      ...a,
      { type: item.object_type as AttachmentSpec["type"],
        object_id: item.object_id, label: item.label },
    ]);
    setAttachLabels((l) => [...l, item.label || `${item.object_type} ${item.object_id}`]);
    setSharing(null);
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
            {to.length > 0 && (
              <ul className="mb-1.5 flex flex-wrap gap-1.5">
                {to.map((p) => (
                  <li key={p.id}
                      data-testid="recipient-chip"
                      className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-1 text-xs text-accent">
                    {p.name}
                    <button type="button"
                            aria-label={`Remove ${p.name}`}
                            onClick={() => setTo((c) => c.filter((x) => x.id !== p.id))}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <input
              id="compose-to"
              value={find}
              onFocus={() => setPicking(true)}
              onChange={(e) => {
                setFind(e.target.value);
                setPicking(true);
              }}
              autoComplete="off"
              placeholder="Search by name, job title, team or role"
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
            {picking && (
              <div className="mt-1 rounded-md border border-border">
                {directory.loading && (
                  <p className="px-3 py-2 text-xs text-text-muted">
                    Loading the directory…
                  </p>
                )}
                {directory.error && (
                  <p className="px-3 py-2 text-xs text-negative">
                    {directory.error}
                  </p>
                )}
                {!directory.loading && !directory.error && offered.length === 0 && (
                  <p className="px-3 py-2 text-xs text-text-muted">
                    {find
                      ? "Nobody matched that."
                      : "No other active accounts are configured."}
                  </p>
                )}
                {offered.length > 0 && (
                  <ul data-testid="recipient-options"
                      className="max-h-56 overflow-y-auto">
                    {offered.map((p) => (
                      <li key={p.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setTo((c) => [...c, p]);
                            setFind("");
                          }}
                          className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-xs hover:bg-surface-sunken"
                        >
                          <span className="font-medium text-text-primary">
                            {p.name}
                          </span>
                          <span className="text-text-muted">
                            {[p.job_title, p.team, p.role]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="border-t border-border px-3 py-1.5 text-right">
                  <button type="button"
                          className="text-[11px] text-text-muted hover:text-text-primary"
                          onClick={() => setPicking(false)}>
                    Done
                  </button>
                </div>
              </div>
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

          <div className="rounded-md border border-border bg-surface-sunken/40 px-3 py-2.5">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
              Share from CreditProbe
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button"
                      onClick={() => setSharing(
                        sharing === "analysis" ? null : "analysis")}
                      className="rounded-md border border-border px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary">
                + Analysis
              </button>
              <button type="button"
                      onClick={() => setSharing(
                        sharing === "investigation" ? null : "investigation")}
                      className="rounded-md border border-border px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary">
                + Investigation
              </button>
              <label className="cursor-pointer rounded-md border border-border px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary">
                + File
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
              <span className="text-[11px] text-text-muted">
                Workbooks and reports attach as files.
              </span>
            </div>
            {sharing && (
              <ObjectPicker kind={sharing} onPick={attachObject} />
            )}
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
          </div>

          {attachLabels.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {attachLabels.map((name, i) => (
                <li key={`${name}-${i}`}
                    data-testid="attachment-chip"
                    className="inline-flex items-center gap-1.5 rounded border border-border bg-surface-sunken px-2 py-1 text-xs text-text-secondary">
                  {name}
                  <button type="button"
                          aria-label={`Remove ${name}`}
                          onClick={() => {
                            setAttachments((a) => a.filter((_, j) => j !== i));
                            setAttachLabels((l) => l.filter((_, j) => j !== i));
                          }}>
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}

          {error && <p role="alert" className="text-xs text-negative">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="ghost" onClick={saveDraft} disabled={busy}>
            Save draft
          </Button>
          <Button
            onClick={send}
            disabled={busy || to.length === 0 || !subject.trim()}
          >
            {busy ? "Sending…" : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * The list behind "+ Analysis" and "+ Investigation".
 *
 * Cards, not identifiers. Each row is something the signed-in person can
 * already open, described the way the attachment will describe it in the
 * recipient's inbox — so what the sender picked and what the reader receives
 * are visibly the same object.
 */
function ObjectPicker({ kind, onPick }: {
  kind: "analysis" | "investigation";
  onPick: (item: ShareableObject) => void;
}) {
  const [q, setQ] = React.useState("");
  const list = useAsync(() => api.shareableObjects(kind, q, 20), [kind, q]);

  return (
    <div className="mt-2.5 rounded-md border border-border bg-surface">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label={`Search ${kind === "analysis" ? "analyses" : "investigations"}`}
        placeholder={`Search your ${kind === "analysis" ? "analyses" : "investigations"}`}
        className="w-full rounded-t-md border-b border-border bg-surface px-3 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none"
      />
      {list.loading && (
        <p className="px-3 py-2 text-xs text-text-muted">Loading…</p>
      )}
      {list.error && (
        <p className="px-3 py-2 text-xs text-negative">{list.error}</p>
      )}
      {!list.loading && list.data && list.data.items.length === 0 && (
        <p className="px-3 py-2 text-xs text-text-muted">
          Nothing here you can share yet.
        </p>
      )}
      {list.data && list.data.items.length > 0 && (
        <ul data-testid="shareable-list" className="max-h-56 overflow-y-auto">
          {list.data.items.map((item) => (
            <li key={`${item.object_type}-${item.object_id}`}>
              <button
                type="button"
                onClick={() => onPick(item)}
                className="flex w-full flex-col gap-0.5 border-b border-border px-3 py-2 text-left last:border-b-0 hover:bg-surface-sunken"
              >
                <span className="text-xs font-medium text-text-primary">
                  {item.label || "Untitled"}
                </span>
                <span className="text-[11px] text-text-muted">
                  {[
                    String(item.meta.period ?? ""),
                    String(item.meta.scope ?? item.meta.domain ?? ""),
                    String(item.meta.certification ?? item.meta.status ?? ""),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
