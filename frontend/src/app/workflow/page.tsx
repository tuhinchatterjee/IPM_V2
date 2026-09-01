"use client";

import Link from "next/link";
import * as React from "react";
import {
  AtSign,
  CheckCircle2,
  Clock,
  CornerDownRight,
  Inbox,
  Send,
  Users,
} from "lucide-react";

import { WorkflowStateBadge } from "@/components/collaboration/share";
import { PageHeader } from "@/components/layout/page-header";
import { ReadOnlyNotice, useCanRunAnalysis } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import {
  api,
  type Directory,
  type WorkflowDetail,
  type WorkflowItemRow,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { linkBack } from "@/lib/return-to";
import { cn } from "@/lib/utils";

/**
 * The Workflow Inbox. §46.
 *
 * Five lists, and the split is the whole idea:
 *
 *   ASSIGNED TO ME  what I have to do, including work sent to a team I am in
 *   SENT BY ME      what I am waiting on
 *   MENTIONS        where somebody named me. Being asked a question is not the
 *                   same as being given the work, and an inbox that cannot tell
 *                   them apart is one people stop reading
 *   DUE SOON        assigned to me, with a date inside a week
 *   COMPLETED       closed, however it closed
 *
 * Opening a row shows what §46 asks for: the object it is about with a link
 * that opens it, the message thread, the actions the state machine actually
 * permits, and the append-only audit history.
 *
 * Every row is a real workflow item from PostgreSQL. Approving something writes
 * an immutable event and notifies the person who asked; nothing on this page is
 * a mock-up of a process.
 */

const PRIORITY_CLASS: Record<string, string> = {
  urgent: "text-negative",
  high: "text-warning",
  normal: "text-text-muted",
  low: "text-text-muted",
};

type View =
  | "assigned_to_me"
  | "sent_by_me"
  | "mentions"
  | "due_soon"
  | "completed";

export default function WorkflowPage() {
  const [tab, setTab] = React.useState<View>("assigned_to_me");
  const [selected, setSelected] = React.useState<number | null>(null);
  const [nonce, setNonce] = React.useState(0);

  const inbox = useAsync(() => api.workflowInbox(), [nonce]);
  const directory = useAsync(() => api.directory(), []);
  // A Viewer may read a decision history and reply to a thread, but may not
  // make a decision. The backend refuses it; the buttons are hidden so nobody
  // discovers that by being refused.
  const canDecide = useCanRunAnalysis();

  const lists = inbox.data;
  const rows: WorkflowItemRow[] = lists?.[tab] ?? [];

  const count = (view: View) => lists?.[view]?.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow"
        description="Send a Project, an Investigation or an Analysis to somebody for review, approval, sign-off or comment. Every decision is written to an append-only history with who made it and when, and the conversation stays against the object rather than in email."
        status="live"
      />

      {!canDecide && <ReadOnlyNotice action="approve or reject a review" />}

      {inbox.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{inbox.error}</Card>
      )}

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Assigned to me" value={count("assigned_to_me")} icon={Inbox} />
        <Stat label="Sent by me" value={count("sent_by_me")} icon={Send} />
        <Stat label="Due soon" value={count("due_soon")} icon={Clock} />
        <Stat label="Completed" value={count("completed")} icon={CheckCircle2} />
      </div>

      <Tabs
        active={tab}
        onChange={(id) => {
          setTab(id as View);
          setSelected(null);
        }}
        tabs={[
          { id: "assigned_to_me", label: "Assigned to me", count: count("assigned_to_me") },
          { id: "sent_by_me", label: "Sent by me", count: count("sent_by_me") },
          { id: "mentions", label: "Mentions", count: count("mentions") },
          { id: "due_soon", label: "Due soon", count: count("due_soon") },
          { id: "completed", label: "Completed", count: count("completed") },
        ]}
      />

      {inbox.loading && <Skeleton className="h-48 w-full" />}

      {!inbox.loading && rows.length === 0 && (
        <Card className="px-5 py-10 text-center">
          <p className="text-sm text-text-secondary">{EMPTY[tab]}</p>
          <p className="mt-1 text-xs text-text-muted">
            Send is under every answer, every project and every saved analysis.
          </p>
        </Card>
      )}

      {rows.length > 0 && (
        <Card className="divide-y divide-border">
          {rows.map((item) => (
            <div key={item.id}>
              <button
                type="button"
                onClick={() => setSelected(selected === item.id ? null : item.id)}
                className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-surface-hover"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-text-primary">
                    {item.title}
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs text-text-muted">
                    <span>{nameOf(directory.data, item.requested_by)}</span>
                    <span>·</span>
                    <span>{item.object_type_label ?? item.object_type}</span>
                    {item.object_version && <span>v{item.object_version}</span>}
                    {item.action_label && (
                      <>
                        <span>·</span>
                        <span className="text-text-secondary">{item.action_label}</span>
                      </>
                    )}
                    {item.due_at && (
                      <>
                        <span>·</span>
                        <span className={cn(PRIORITY_CLASS[item.priority ?? "normal"])}>
                          due {when(item.due_at)}
                        </span>
                      </>
                    )}
                    {(item.messages ?? 0) > 0 && (
                      <>
                        <span>·</span>
                        <span>
                          {item.messages}{" "}
                          {item.messages === 1 ? "message" : "messages"}
                        </span>
                      </>
                    )}
                    <span>·</span>
                    <span>{when(item.updated_at)}</span>
                  </p>
                </div>
                {item.priority && item.priority !== "normal" && (
                  <Badge variant="outline" className={PRIORITY_CLASS[item.priority]}>
                    {item.priority}
                  </Badge>
                )}
                <WorkflowStateBadge state={item.state} label={item.state_label} />
              </button>
              {selected === item.id && (
                <ItemDetail
                  itemId={item.id}
                  canDecide={canDecide}
                  directory={directory.data ?? null}
                  onChanged={() => setNonce((n) => n + 1)}
                />
              )}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

const EMPTY: Record<View, string> = {
  assigned_to_me: "Nothing is waiting on you.",
  sent_by_me: "You have not sent anything.",
  mentions: "Nobody has named you.",
  due_soon: "Nothing is due in the next week.",
  completed: "Nothing has been through review yet.",
};

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: typeof Inbox;
}) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </p>
      <p className="mt-1.5 text-2xl font-semibold tabular text-text-primary">{value}</p>
    </Card>
  );
}

/**
 * One item, opened: what it is about, what was said, what can be done, and
 * everything that has happened to it.
 *
 * The decision buttons are exactly the transitions the backend's state machine
 * permits from the current state. Offering one that would be refused is a worse
 * failure than offering none.
 */
function ItemDetail({
  itemId,
  canDecide,
  directory,
  onChanged,
}: {
  itemId: number;
  canDecide: boolean;
  directory: Directory | null;
  onChanged: () => void;
}) {
  const [detail, setDetail] = React.useState<WorkflowDetail | null>(null);
  const [comment, setComment] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [replyTo, setReplyTo] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Opening it IS the OPENED status. Recorded here rather than claimed by the
  // list, because the list renders every row and opening one row is not
  // opening all of them.
  React.useEffect(() => {
    let live = true;
    api
      .openWorkflow(itemId)
      .then((d) => live && setDetail(d))
      .catch(() =>
        api
          .workflowItem(itemId)
          .then((d) => live && setDetail(d))
          .catch((e) => live && setError(String(e))),
      );
    return () => {
      live = false;
    };
  }, [itemId]);

  const move = async (state: string) => {
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.moveWorkflow(itemId, state, comment));
      setComment("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That decision was refused.");
    } finally {
      setBusy(false);
    }
  };

  const say = async () => {
    if (!message.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.sayOnWorkflow(itemId, { body: message, parentId: replyTo });
      setMessage("");
      setReplyTo(null);
      setDetail(await api.workflowItem(itemId));
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That message was not sent.");
    } finally {
      setBusy(false);
    }
  };

  if (error && !detail) {
    return <p className="border-t border-border px-5 py-3 text-xs text-negative">{error}</p>;
  }
  if (!detail) {
    return (
      <div className="px-5 py-3">
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  const target = objectHref(detail);

  return (
    <div className="space-y-5 border-t border-border bg-surface-sunken px-5 py-4">
      {/* ------------------------------------------------- object preview */}
      <section>
        <p className="meta mb-1.5 text-text-muted">
          {detail.action_label ?? "Review"} requested
        </p>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-sm text-text-primary">{detail.title}</span>
          <span className="text-xs text-text-muted">
            {detail.object_type_label ?? detail.object_type}
            {detail.object_version ? ` · version ${detail.object_version}` : ""}
          </span>
          {target && (
            <Link href={target} className="text-xs font-medium text-accent hover:underline">
              Open it
            </Link>
          )}
        </div>
        {detail.message && (
          <p className="prose-ai mt-2 max-w-[68ch] border-l-2 border-border pl-3 text-xs leading-relaxed text-text-secondary">
            {detail.message}
          </p>
        )}
        {detail.recipients.length > 0 && (
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-text-muted">
            <Users className="size-3" aria-hidden />
            {detail.recipients.map((r) => (
              <span key={r.id}>
                {r.team_id !== null
                  ? teamOf(directory, r.team_id)
                  : nameOf(directory, r.user_id)}
                {r.opened_at ? " (opened)" : ""}
              </span>
            ))}
          </p>
        )}
      </section>

      {/* --------------------------------------------------- message thread */}
      <section>
        <p className="meta mb-2 text-text-muted">Conversation</p>
        {detail.thread.length === 0 ? (
          <p className="text-xs text-text-muted">Nothing said yet.</p>
        ) : (
          <ul className="space-y-2.5">
            {detail.thread.map((entry) => (
              <li
                key={entry.id}
                className={cn(
                  "text-xs",
                  entry.parent_id !== null && "ml-5 border-l border-border pl-3",
                )}
              >
                <p className="flex flex-wrap items-baseline gap-x-2 text-text-muted">
                  <span className="font-medium text-text-secondary">
                    {nameOf(directory, entry.author_id)}
                  </span>
                  <span>{when(entry.created_at)}</span>
                  {entry.resolved && <Badge variant="outline">resolved</Badge>}
                </p>
                <p className="prose-ai mt-0.5 max-w-[68ch] text-text-primary">
                  {entry.body}
                </p>
                {entry.attachments.length > 0 && (
                  <p className="mt-1 flex flex-wrap gap-2">
                    {entry.attachments.map((a) => (
                      <span key={`${a.type}-${a.id}`} className="text-[11px] text-text-muted">
                        {a.label ?? `${a.type} ${a.id}`}
                      </span>
                    ))}
                  </p>
                )}
                <div className="mt-1 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setReplyTo(entry.id)}
                    className="inline-flex items-center gap-1 text-[11px] text-text-muted hover:text-accent"
                  >
                    <CornerDownRight className="size-3" aria-hidden />
                    Reply
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      await api.resolveWorkflowMessage(entry.id, !entry.resolved);
                      setDetail(await api.workflowItem(itemId));
                    }}
                    className="text-[11px] text-text-muted hover:text-accent"
                  >
                    {entry.resolved ? "Reopen" : "Mark resolved"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 space-y-1.5">
          {replyTo !== null && (
            <p className="flex items-center gap-1.5 text-[11px] text-text-muted">
              <AtSign className="size-3" aria-hidden />
              Replying
              <button
                type="button"
                onClick={() => setReplyTo(null)}
                className="text-accent hover:underline"
              >
                cancel
              </button>
            </p>
          )}
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={2}
            placeholder="Say something about this"
            className="w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <Button size="sm" variant="outline" disabled={busy || !message.trim()} onClick={() => void say()}>
            Send message
          </Button>
        </div>
      </section>

      {/* ----------------------------------------------------- the decision */}
      {detail.next_states.length > 0 && canDecide ? (
        <section>
          <p className="meta mb-2 text-text-muted">Decision</p>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="Add a note with your decision"
            className="w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {detail.next_states.map((state) => (
              <Button
                key={state}
                size="sm"
                variant={state === "approved" ? "default" : "outline"}
                disabled={busy}
                onClick={() => void move(state)}
              >
                {detail.next_state_labels[state] ?? state}
              </Button>
            ))}
          </div>
        </section>
      ) : (
        <p className="text-xs text-text-muted">
          {detail.next_states.length === 0
            ? "This is closed. Wanting another look means sending it again, which leaves this decision standing."
            : "Your acting role can read this and reply to it, but cannot decide it."}
        </p>
      )}

      {error && <p className="text-xs text-negative">{error}</p>}

      {/* ------------------------------------------------------ audit trail */}
      <section>
        <p className="meta mb-2 text-text-muted">History</p>
        <ol className="space-y-1.5">
          {detail.events.map((event, i) => (
            <li key={i} className="flex items-start gap-2 text-xs">
              <Clock className="mt-0.5 size-3 shrink-0 text-text-muted" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="text-text-primary">{event.to_state_label}</span>
                <span className="ml-1.5 text-text-muted">
                  {nameOf(directory, event.actor_id)} · {when(event.created_at)}
                </span>
                {event.comment && (
                  <span className="block text-text-secondary">{event.comment}</span>
                )}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

/**
 * Where the object being reviewed lives.
 *
 * Carrying the Workflow inbox as the return context: somebody who opens an
 * investigation from a review is coming back to the review.
 */
function objectHref(detail: WorkflowDetail): string | null {
  const from = { href: "/workflow", label: "Workflow", type: "workflow" as const };
  switch (detail.object_type) {
    case "investigation":
      return linkBack(`/investigations/${detail.object_id}`, from);
    case "project":
      return linkBack(`/projects/${detail.object_id}`, from);
    case "analysis":
      return linkBack(`/engine-builder/${detail.object_id}`, from);
    case "dataset":
      return linkBack(
        `/data-builder/dataset/${encodeURIComponent(detail.object_id)}`,
        from,
      );
    case "scenario":
      return "/stress";
    case "document":
      return `/documents/${detail.object_id}`;
    default:
      return null;
  }
}

/** A person's name, or an honest placeholder — never a fabricated one. */
function nameOf(directory: Directory | null, id: number | null | undefined): string {
  if (id === null || id === undefined) return "CreditProbe";
  const person = directory?.people.find((p) => p.id === id);
  return person?.name ?? `User ${id}`;
}

function teamOf(directory: Directory | null, id: number): string {
  return directory?.teams.find((t) => t.id === id)?.name ?? `Team ${id}`;
}

function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
