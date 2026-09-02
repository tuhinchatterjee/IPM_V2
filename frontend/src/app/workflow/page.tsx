"use client";

import Link from "next/link";
import * as React from "react";
import { AlertTriangle, Mail, Share2, Users } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { useRole } from "@/components/system/role-switcher";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type WorkflowUserRow,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * Workflow — administrative oversight.
 *
 * What this page is
 * -----------------
 * The operational answer to "how is the workflow actually running". Who is
 * active, who is drowning in unread work, whose review requests have gone past
 * their date, who has not signed in for a month. Counts, per user, across the
 * whole institution.
 *
 * What this page is NOT
 * ---------------------
 * A mailbox. Messages live in Messages, whatever they carry: a message with an
 * analysis attached is still a message, and a review request that moves from
 * Open to Responded is still the same conversation in the same inbox. Nothing
 * is relocated here because of what it contains or what state it is in.
 *
 * And not surveillance. There is no subject line and no message body anywhere
 * on this page, because there is no route that would return one to an
 * administrator: reading somebody's mail requires being in the conversation,
 * and administering an account is not being in it. Where governance genuinely
 * needs to know who sent what to whom, the audit log answers that by act.
 *
 * Non-administrators do not see this in the sidebar and the two routes behind
 * it refuse them, so the notice below is the honest thing to show rather than
 * a blank page.
 */
export default function WorkflowPage() {
  const { role } = useRole();
  const [q, setQ] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [selected, setSelected] = React.useState<number | null>(null);

  const page = useAsync(
    () => api.workflowOverview({ q: search, limit: 200 }),
    [search],
  );

  if (role && role !== "ADMIN") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Workflow"
          description="Administrative oversight of message and review activity."
          status="live"
        />
        <Card className="p-6">
          <p className="text-sm text-text-primary">
            This is an administrator&rsquo;s view of how the workflow is running
            across every account. It is not your mailbox.
          </p>
          <p className="mt-2 text-sm text-text-secondary">
            Your own messages are in{" "}
            <Link href="/messages" className="text-accent hover:underline">
              Messages
            </Link>
            , and what has been sent to you for review is in{" "}
            <Link href="/reviews" className="text-accent hover:underline">
              My reviews
            </Link>
            .
          </p>
        </Card>
      </div>
    );
  }

  const totals = page.data?.totals;
  const users = page.data?.users ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow"
        description="How message and review activity is running across every account: who has unread work, whose requests are overdue, who has stopped signing in. Counts and status only — never the contents of anybody's mail."
        status="live"
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={Users} label="Active accounts"
              value={totals ? `${totals.active}` : "—"}
              note={totals ? `${totals.suspended} suspended` : ""} />
        <Tile icon={Mail} label="Messages sent"
              value={totals ? totals.messages_sent.toLocaleString() : "—"}
              note={totals ? `${totals.unread.toLocaleString()} unread across all inboxes` : ""} />
        <Tile icon={AlertTriangle} label="Open requests"
              value={totals ? `${totals.action_required}` : "—"}
              note={totals ? `${totals.overdue} past their date` : ""}
              alert={Boolean(totals && totals.overdue > 0)} />
        <Tile icon={Share2} label="Objects shared"
              value={totals ? `${totals.shares}` : "—"}
              note="Live grants, not revoked" />
      </div>

      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(q.trim());
        }}
      >
        <input
          id="workflow-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Find a person by name, job title, team or role"
          aria-label="Find a person"
          className="w-80 rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        <Link href="/users"
              className="ml-auto text-xs font-medium text-accent hover:underline">
          Manage users →
        </Link>
      </form>

      {page.loading && <Skeleton className="h-64 w-full" />}
      {page.error && (
        <p className="py-8 text-center text-sm text-negative">{page.error}</p>
      )}

      {page.data && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full min-w-[52rem] text-left text-xs">
            <thead className="border-b border-border text-[11px] uppercase tracking-wide text-text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Person</th>
                <th scope="col" className="px-3 py-2 font-medium">Role &amp; team</th>
                <th scope="col" className="px-3 py-2 font-medium">Status</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Unread</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Received</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Sent</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Action required</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Overdue</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Shared</th>
                <th scope="col" className="px-3 py-2 font-medium">Last active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((u) => (
                <Row key={u.id} user={u}
                     open={selected === u.id}
                     onToggle={() => setSelected(selected === u.id ? null : u.id)} />
              ))}
            </tbody>
          </table>
          {users.length === 0 && (
            <p className="px-3 py-8 text-center text-xs text-text-muted">
              Nobody matched that.
            </p>
          )}
        </div>
      )}

      {page.data && page.data.total > users.length && (
        <p className="text-center text-xs text-text-muted">
          Showing {users.length} of {page.data.total.toLocaleString()} accounts.
        </p>
      )}
    </div>
  );
}

function Tile({ icon: Icon, label, value, note, alert }: {
  icon: typeof Users;
  label: string;
  value: string;
  note?: string;
  alert?: boolean;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-text-muted">
        <Icon className="size-[13px]" aria-hidden />
        <span className="text-[11px] uppercase tracking-wide">{label}</span>
      </div>
      <p className={cn("mt-1.5 text-2xl font-semibold tabular-nums",
                       alert ? "text-warning" : "text-text-primary")}>
        {value}
      </p>
      {note && <p className="mt-0.5 text-[11px] text-text-muted">{note}</p>}
    </Card>
  );
}

/** How long ago, in the coarsest unit that is still informative. */
function ago(iso: string | null): string {
  if (!iso) return "Never signed in";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return months === 1 ? "A month ago" : `${months} months ago`;
}

function Row({ user, open, onToggle }: {
  user: WorkflowUserRow;
  open: boolean;
  onToggle: () => void;
}) {
  const a = user.activity;
  const profile = useAsync(
    () => (open ? api.workflowUserProfile(user.id) : Promise.resolve(null)),
    [open, user.id],
  );

  return (
    <>
      <tr
        onClick={onToggle}
        className="cursor-pointer align-middle hover:bg-surface-sunken/60"
      >
        <td className="px-3 py-2">
          <span className="block font-medium text-text-primary">{user.name}</span>
          <span className="block text-[11px] text-text-muted">
            {user.job_title || user.username}
          </span>
        </td>
        <td className="px-3 py-2 text-text-secondary">
          {[user.role, user.team].filter(Boolean).join(" · ") || "—"}
        </td>
        <td className="px-3 py-2">
          <span className={cn(
            "rounded-full px-2 py-0.5 text-[11px]",
            user.status === "active"
              ? "bg-positive/10 text-positive"
              : "bg-surface-sunken text-text-muted",
          )}>
            {user.status === "active" ? "Active" : "Suspended"}
          </span>
        </td>
        <td className={cn("px-3 py-2 text-right tabular-nums",
                          a.unread > 0 ? "font-semibold text-text-primary"
                                       : "text-text-muted")}>
          {a.unread}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
          {a.received}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
          {a.sent}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
          {a.action_required}
        </td>
        <td className={cn("px-3 py-2 text-right tabular-nums",
                          a.overdue > 0 ? "font-semibold text-warning"
                                        : "text-text-muted")}>
          {a.overdue}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
          {a.shared_with_them}
        </td>
        <td className="px-3 py-2 text-text-muted">{ago(user.last_active)}</td>
      </tr>

      {open && (
        <tr>
          <td colSpan={10} className="bg-surface-sunken/40 px-3 py-4">
            <div className="grid gap-5 md:grid-cols-2">
              <div>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                  Operational profile
                </h3>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                  <Fact label="Email" value={user.email || "—"} />
                  <Fact label="Department" value={user.department || "—"} />
                  <Fact label="Read conversations" value={String(a.read)} />
                  <Fact label="Unsent drafts" value={String(a.drafts)} />
                  <Fact label="Waiting on others" value={String(a.awaiting_others)} />
                  <Fact label="Objects they have shared"
                        value={String(a.shared_by_them)} />
                </dl>
                <Link
                  href={`/users?user=${user.id}`}
                  className="mt-3 inline-block text-xs font-medium text-accent hover:underline"
                >
                  Manage user →
                </Link>
              </div>
              <div>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                  Recent activity
                </h3>
                {profile.loading && <Skeleton className="h-20 w-full" />}
                {profile.data && profile.data.recent_activity.length === 0 && (
                  <p className="text-xs text-text-muted">
                    Nothing recorded yet.
                  </p>
                )}
                {profile.data && profile.data.recent_activity.length > 0 && (
                  <ul className="space-y-1 text-xs text-text-secondary">
                    {profile.data.recent_activity.slice(0, 8).map((e, i) => (
                      <li key={`${e.action}-${i}`} className="flex gap-2">
                        <span className="text-text-muted">
                          {e.at ? new Date(e.at).toLocaleDateString() : "—"}
                        </span>
                        <span>{ACTION_LABEL[e.action] ?? e.action}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-3 text-[11px] leading-[1.5] text-text-muted">
                  Acts, not contents. No subject line or message body is
                  available here, to an administrator or to anybody else who is
                  not in the conversation.
                </p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-text-muted">{label}</dt>
      <dd className="text-text-primary">{value}</dd>
    </>
  );
}

/** The audit vocabulary, said in English. */
const ACTION_LABEL: Record<string, string> = {
  message_sent: "Sent a message",
  message_replied: "Replied in a conversation",
  message_read: "Read a conversation",
  message_archived: "Archived a conversation",
  object_shared: "Shared a governed object",
  file_downloaded: "Downloaded an attachment",
  workflow_status_changed: "Moved a request along",
  user_created: "Created a user",
  user_updated: "Updated a user",
  user_deactivated: "Suspended a user",
  user_reactivated: "Restored a user",
};
