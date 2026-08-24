"use client";

import Link from "next/link";
import * as React from "react";
import { Bell, CheckCircle2, Clock, Inbox, Send } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { ReadOnlyNotice, useCanRunAnalysis } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { api, type WorkflowDetail, type WorkflowItemRow } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * The Workflow Inbox.
 *
 * Three lists, and the split is the whole idea: what I have to do, what I am
 * waiting on, and what is finished. A single undifferentiated queue makes a
 * reviewer read every row to find the two that are theirs.
 *
 * Every row here is a real workflow item from PostgreSQL with its full decision
 * history. Approving something writes an immutable event and notifies the person
 * who asked — nothing on this page is a mock-up of a process.
 */

const STATE_TONE: Record<string, string> = {
  submitted: "warning",
  in_review: "accent",
  approved: "positive",
  rejected: "negative",
  withdrawn: "default",
};

export default function WorkflowPage() {
  const [tab, setTab] = React.useState("my_work");
  const [selected, setSelected] = React.useState<number | null>(null);
  const [nonce, setNonce] = React.useState(0);

  const inbox = useAsync(() => api.workflowInbox(), [nonce]);
  const notifications = useAsync(() => api.notifications(), [nonce]);
  // A Viewer can read a decision history but cannot make a decision. The backend
  // refuses it; the buttons are hidden so nobody discovers that by being refused.
  const canDecide = useCanRunAnalysis();

  const lists = inbox.data;
  const rows: WorkflowItemRow[] =
    tab === "my_work" ? lists?.my_work ?? []
    : tab === "sent_by_me" ? lists?.sent_by_me ?? []
    : lists?.completed ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow"
        description="Review and approval of things that carry institutional weight: an investigation, a certified analysis, a published dataset, a scenario, a paper. Every decision is written to an append-only history with who made it and when."
        status="live"
        actions={
          notifications.data && notifications.data.unread > 0 ? (
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                await api.markNotificationsRead();
                setNonce((n) => n + 1);
              }}
            >
              <Bell aria-hidden />
              {notifications.data.unread} unread
            </Button>
          ) : undefined
        }
      />

      {!canDecide && <ReadOnlyNotice action="approve, reject or comment on a review" />}

      {inbox.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{inbox.error}</Card>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="My work" value={lists?.my_work.length} icon={Inbox} />
        <Stat label="Sent by me" value={lists?.sent_by_me.length} icon={Send} />
        <Stat label="Completed" value={lists?.completed.length} icon={CheckCircle2} />
      </div>

      <Tabs
        active={tab}
        onChange={(id) => {
          setTab(id);
          setSelected(null);
        }}
        tabs={[
          { id: "my_work", label: "My work", count: lists?.my_work.length ?? 0 },
          { id: "sent_by_me", label: "Sent by me", count: lists?.sent_by_me.length ?? 0 },
          { id: "completed", label: "Completed", count: lists?.completed.length ?? 0 },
        ]}
      />

      {inbox.loading && <Skeleton className="h-48 w-full" />}

      {!inbox.loading && rows.length === 0 && (
        <Card className="px-5 py-10 text-center">
          <p className="text-sm text-text-secondary">
            {tab === "my_work"
              ? "Nothing is waiting on you."
              : tab === "sent_by_me"
                ? "You have not sent anything for review."
                : "Nothing has been through review yet."}
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Send an investigation for review from the answer itself.
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
                  <p className="truncate text-sm font-medium text-text-primary">{item.title}</p>
                  <p className="mt-0.5 text-xs text-text-muted">
                    {item.object_type_label ?? item.object_type} · updated{" "}
                    {item.updated_at ? new Date(item.updated_at).toLocaleString() : "—"}
                  </p>
                </div>
                <Badge
                  variant={
                    (STATE_TONE[item.state] ?? "default") as
                      | "warning" | "accent" | "positive" | "negative" | "default"
                  }
                >
                  {item.state_label}
                </Badge>
              </button>
              {selected === item.id && (
                <ReviewDetail
                  itemId={item.id}
                  canDecide={canDecide}
                  onChanged={() => setNonce((n) => n + 1)}
                />
              )}
            </div>
          ))}
        </Card>
      )}

      {notifications.data && notifications.data.notifications.length > 0 && (
        <section>
          <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
            Recent activity
          </h2>
          <Card className="divide-y divide-border">
            {notifications.data.notifications.slice(0, 8).map((n) => (
              <div key={n.id} className="flex items-start gap-3 px-5 py-2.5">
                <span
                  className={cn(
                    "mt-1.5 size-1.5 shrink-0 rounded-full",
                    n.read ? "bg-border-strong" : "bg-accent",
                  )}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-text-primary">{n.title}</p>
                  {n.body && (
                    <p className="mt-0.5 line-clamp-1 text-xs text-text-muted">{n.body}</p>
                  )}
                </div>
                <span className="shrink-0 text-[11px] text-text-muted">
                  {n.created_at ? new Date(n.created_at).toLocaleDateString() : ""}
                </span>
              </div>
            ))}
          </Card>
        </section>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number | undefined;
  icon: typeof Inbox;
}) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </p>
      <p className="mt-1.5 text-2xl font-semibold text-text-primary tabular">
        {value ?? "—"}
      </p>
    </Card>
  );
}

/**
 * One review, expanded: its history, and the decisions available from here.
 *
 * The buttons are exactly the transitions the backend's state machine permits
 * from the current state. Offering a button that would be refused is a worse
 * failure than offering none.
 */
function ReviewDetail({
  itemId,
  canDecide,
  onChanged,
}: {
  itemId: number;
  canDecide: boolean;
  onChanged: () => void;
}) {
  const [detail, setDetail] = React.useState<WorkflowDetail | null>(null);
  const [comment, setComment] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let live = true;
    api
      .workflowItem(itemId)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError(String(e)));
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

  if (error) {
    return <p className="border-t border-border px-5 py-3 text-xs text-negative">{error}</p>;
  }
  if (!detail) {
    return <div className="px-5 py-3"><Skeleton className="h-20 w-full" /></div>;
  }

  return (
    <div className="border-t border-border bg-surface-sunken px-5 py-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
        Decision history
      </p>
      <ol className="mt-2 space-y-1.5">
        {detail.events.map((event, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            <Clock className="mt-0.5 size-3 shrink-0 text-text-muted" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="text-text-primary">{event.to_state_label}</span>
              {event.comment && <span className="text-text-secondary"> — {event.comment}</span>}
              <span className="ml-1.5 text-text-muted">
                {event.created_at ? new Date(event.created_at).toLocaleString() : ""}
              </span>
            </span>
          </li>
        ))}
      </ol>

      {detail.object_type === "investigation" && (
        <Link
          href={`/investigations/saved/${detail.object_id}`}
          className="mt-3 inline-block text-xs font-medium text-accent hover:underline"
        >
          Open the investigation
        </Link>
      )}

      {detail.next_states.length > 0 && canDecide ? (
        <div className="mt-4 space-y-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="Add a note with your decision"
            className="w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <div className="flex flex-wrap gap-1.5">
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
        </div>
      ) : (
        <p className="mt-3 text-xs text-text-muted">
          {detail.next_states.length === 0
            ? "This review is closed. Wanting another look means submitting again, which leaves this decision standing."
            : "Your acting role can read this history but cannot make a decision on it."}
        </p>
      )}
    </div>
  );
}
