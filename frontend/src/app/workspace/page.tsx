"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import {
  AttachmentChips,
  RequestBadge,
  Sender,
  Stat,
  when,
} from "@/components/messages/parts";
import { api, type MessageSummary } from "@/lib/api";
import { useAttention } from "@/lib/attention";
import { useAsync } from "@/lib/hooks";

/**
 * My Workspace — one person's own working state.
 *
 * Not a second executive dashboard. The Cockpit answers "what is happening in
 * the book"; this answers "what is waiting on me", which is a different
 * question with different rows and a different reader — the same reader, an
 * hour earlier in their day.
 *
 * Every number here is a count of real rows the reader can click through to.
 * A tile that says 3 and opens onto nothing is worse than no tile: it teaches
 * people that the numbers on this screen are decorative.
 */
export default function WorkspacePage() {
  // The same store the header badge and the mailbox tabs read, so this
  // card cannot show a number the rest of the product disagrees with.
  const { safe: counts } = useAttention();
  const unread = useAsync(
    () => api.mailbox("inbox", { unread: true, limit: 5 }),
    [],
  );
  const action = useAsync(() => api.mailbox("action", { limit: 5 }), []);
  const shared = useAsync(() => api.sharedWithMe(6), []);
  const recent = useAsync(() => api.recentInvestigations(5), []);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-6">
      <PageHeader
        title="My workspace"
        description="What is waiting on you, what colleagues have shared, and what CreditProbe has told you."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Unread messages" value={counts.unread}
              href="/messages?box=inbox" />
        <Stat label="Awaiting my review"
              value={counts.action_required}
              href="/messages?box=action" />
        <Stat label="Shared with me" value={counts.shared_with_me}
              href="/messages?box=inbox" />
        <Stat label="Recent investigations"
              value={recent.data?.investigations.length ?? 0}
              href="/investigations" />
      </div>

      <Section title="Awaiting my review"
               empty="Nothing is waiting on you."
               href="/messages?box=action"
               loading={action.loading}>
        {(action.data?.items as MessageSummary[] | undefined)?.map((m) => (
          <MessageRow key={m.thread_id} item={m} />
        ))}
      </Section>

      <Section title="Unread"
               empty="Your inbox is clear."
               href="/messages?box=inbox"
               loading={unread.loading}>
        {(unread.data?.items as MessageSummary[] | undefined)?.map((m) => (
          <MessageRow key={m.thread_id} item={m} />
        ))}
      </Section>

      <Section title="Shared with me"
               empty="Nobody has shared an investigation or analysis with you yet."
               loading={shared.loading}>
        {shared.data?.items.map((s) => (
          <li key={`${s.object_type}-${s.object_id}`}>
            <Link
              href={
                s.object_type === "investigation"
                  ? `/investigations/${s.object_id}`
                  : `/analyses/${s.object_id}`
              }
              className="flex items-start justify-between gap-3 px-4 py-3 transition-colors hover:bg-surface-sunken"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm text-text-primary">
                  {s.label || `${s.object_type} ${s.object_id}`}
                </span>
                <span className="mt-0.5 block text-xs text-text-secondary">
                  {s.object_type === "investigation" ? "Investigation" : "Analysis"}
                  {s.shared_by && <> · shared by {s.shared_by}</>}
                  {typeof s.meta?.period === "string" && s.meta.period
                    ? ` · ${s.meta.period}`
                    : ""}
                </span>
              </span>
              <span className="shrink-0 text-xs text-text-muted">
                {when(s.shared_at)}
              </span>
            </Link>
          </li>
        ))}
      </Section>

      <Section title="My recent work"
               empty="You have not opened an investigation yet."
               href="/investigations"
               loading={recent.loading}>
        {recent.data?.investigations.map((i) => (
          <li key={i.analysis_run_id}>
            <Link
              href={`/analysis/${i.analysis_run_id}`}
              className="flex items-start justify-between gap-3 px-4 py-3 transition-colors hover:bg-surface-sunken"
            >
              <span className="min-w-0 truncate text-sm text-text-primary">
                {i.question}
              </span>
              <span className="shrink-0 text-xs text-text-muted">
                {when(i.created_at)}
              </span>
            </Link>
          </li>
        ))}
      </Section>
    </div>
  );
}

function Section({ title, empty, href, loading, children }: {
  title: string;
  empty: string;
  href?: string;
  loading: boolean;
  children?: React.ReactNode;
}) {
  const rows = React.Children.toArray(children).filter(Boolean);
  return (
    <section className="mt-6">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
          {title}
        </h2>
        {href && rows.length > 0 && (
          <Link href={href} className="text-xs text-accent hover:underline">
            See all
          </Link>
        )}
      </div>
      {loading ? (
        <p className="rounded-lg border border-border py-6 text-center text-sm text-text-muted">
          Loading…
        </p>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border py-6 text-center text-sm text-text-secondary">
          {empty}
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {rows}
        </ul>
      )}
    </section>
  );
}

function MessageRow({ item }: { item: MessageSummary }) {
  return (
    <li>
      <Link
        href={`/messages/${item.thread_id}`}
        className="flex items-start justify-between gap-3 px-4 py-3 transition-colors hover:bg-surface-sunken"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm text-text-primary">
            {item.subject}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
            <Sender sender={item.sender} />
            <AttachmentChips types={item.attachment_types} />
          </span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-xs text-text-muted">
            {when(item.last_message_at)}
          </span>
          <RequestBadge type={item.request_type} status={item.request_status} />
        </span>
      </Link>
    </li>
  );
}
