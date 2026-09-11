"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Empty, HealthPill, Progress, SectionCard, when }
  from "@/components/planner/parts";
import { shortDate } from "@/lib/planner-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  api,
  type DraftRow,
  type PlannerAttentionRow,
  type PlannerProjectRow,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * The Project Planner, in the order §2 asks for it.
 *
 *   Create new project · Import project · View my tasks
 *   Needs attention
 *   Current projects
 *   Draft projects
 *   Closed and completed projects
 *
 * The page this replaces opened with a chat box and a suggestion to "start a
 * new project" by describing it in conversation. UAT found that confusing,
 * and it was: the product's primary action was a text field that might or
 * might not understand the sentence typed into it. There is no chat here now.
 * Creating a project is a form, and the form is one click away.
 *
 * Drafts are listed apart from projects, never mixed in. A draft is not a
 * project — nothing is scheduled off it and nobody is chased about it — and a
 * list that showed both would be a list where "we have 14 projects" is false.
 */
export default function DeliveryPortfolioPage() {
  const [search, setSearch] = React.useState("");
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const open = useAsync(
    () => api.planner.portfolio({ search: query, limit: 200 }), [query]);
  const closed = useAsync(
    () => api.planner.portfolio({ status: "COMPLETED", limit: 200 }), []);
  const attention = useAsync(() => api.planner.needsAttention(25), []);
  const drafts = useAsync(() => api.planner.plan.drafts("DRAFTING"), []);

  const current = (open.data?.projects ?? []).filter(
    (row) => row.status !== "COMPLETED" && row.status !== "CANCELLED");
  const done = closed.data?.projects ?? [];
  const issues = attention.data?.items ?? [];

  return (
    <div className="mx-auto w-full max-w-7xl px-6 py-6">
      <PageHeader
        title="Project Planner"
        description="Your projects, what needs somebody today, and what the Agentic AI is chasing."
        actions={
          <Button asChild variant="outline" size="sm">
            <a href={api.planner.templateUrl()}>Plan template</a>
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <Button asChild>
          <Link href="/delivery/new">Create new project</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/delivery/new?import=1">Import project</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/delivery/my-work">View my tasks</Link>
        </Button>
      </div>

      <SectionCard
        title="Needs attention"
        action={
          attention.data ? (
            <Badge variant="outline">
              {attention.data.count} across {attention.data.projects}{" "}
              {attention.data.projects === 1 ? "project" : "projects"}
            </Badge>
          ) : null
        }
      >
        {attention.loading && <Empty>Working out what needs you…</Empty>}
        {attention.error && (
          <p className="px-4 py-6 text-sm text-negative">{attention.error}</p>
        )}
        {attention.data && issues.length === 0 && (
          <Empty>
            Nothing is overdue, blocked, stale or about to slip on any project
            you can see.
          </Empty>
        )}
        {issues.length > 0 && (
          <ul className="divide-y divide-border">
            {issues.map((issue, index) => (
              <AttentionRow key={index} issue={issue} />
            ))}
          </ul>
        )}
      </SectionCard>

      <div className="mt-4">
        <SectionCard
          title="Current projects"
          action={
            <div className="flex items-center gap-2">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search name or code"
                className="h-8 w-48 text-xs"
                aria-label="Search projects"
              />
              <Badge variant="outline">{current.length}</Badge>
            </div>
          }
        >
          {open.loading && <Empty>Reading the portfolio…</Empty>}
          {open.error && (
            <p className="px-4 py-6 text-sm text-negative">{open.error}</p>
          )}
          {!open.loading && !open.error && current.length === 0 && (
            <Empty>
              {query
                ? "No open project matches that filter."
                : "No open projects yet. Create one to get started."}
            </Empty>
          )}
          {current.length > 0 && <ProjectTable rows={current} />}
        </SectionCard>
      </div>

      <div className="mt-4">
        <SectionCard
          title="Draft projects"
          action={
            <Badge variant="outline">{drafts.data?.drafts.length ?? 0}</Badge>
          }
        >
          {drafts.loading && <Empty>Looking for unfinished plans…</Empty>}
          {drafts.data && drafts.data.drafts.length === 0 && (
            <Empty>
              No drafts. A project you start but do not publish waits here.
            </Empty>
          )}
          {(drafts.data?.drafts.length ?? 0) > 0 && (
            <ul className="divide-y divide-border">
              {drafts.data?.drafts.map((draft) => (
                <DraftLine key={draft.key} draft={draft}
                           onGone={() => drafts.reload()} />
              ))}
            </ul>
          )}
        </SectionCard>
      </div>

      <div className="mt-4">
        <SectionCard
          title="Closed and completed projects"
          action={<Badge variant="outline">{done.length}</Badge>}
        >
          {closed.loading && <Empty>Reading closed projects…</Empty>}
          {!closed.loading && done.length === 0 && (
            <Empty>Nothing has been completed yet.</Empty>
          )}
          {done.length > 0 && <ProjectTable rows={done} />}
        </SectionCard>
      </div>
    </div>
  );
}

/**
 * §2. Every column a person reads before deciding to open a project.
 *
 * Thirteen columns did not fit a laptop: the project names wrapped onto four
 * lines and "Last updated" hung off the right edge half-drawn, which reads
 * as broken rather than as scrollable. Nothing was dropped — the same facts
 * are here, paired the way somebody reads them: the code belongs to the
 * name, the two dates are one span, and "2 overdue · 1 blocked" is one
 * thought rather than two numeric columns to line up by eye.
 */
function ProjectTable({ rows }: { rows: PlannerProjectRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-muted">
            <th className="px-4 py-2 font-medium">Project</th>
            <th className="px-3 py-2 font-medium">Sponsor</th>
            <th className="px-3 py-2 font-medium">Project manager</th>
            <th className="px-3 py-2 font-medium">Health</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Progress</th>
            <th className="px-3 py-2 font-medium">Dates</th>
            <th className="px-3 py-2 font-medium">Next milestone</th>
            <th className="px-3 py-2 font-medium">Needs attention</th>
            <th className="px-4 py-2 font-medium">Last updated</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}
                className="border-b border-border last:border-0 hover:bg-surface-hover">
              <td className="px-4 py-2.5">
                <Link href={`/delivery/${row.id}`}
                      className="text-text-primary hover:text-accent">
                  {row.name}
                </Link>
                <div className="font-mono text-[11px] text-text-muted">
                  {row.code}
                </div>
              </td>
              <td className="px-3 py-2.5 text-xs text-text-secondary">
                {row.sponsor?.name ?? "—"}
              </td>
              <td className="px-3 py-2.5 text-xs text-text-secondary">
                {row.manager?.name ?? "—"}
              </td>
              <td className="px-3 py-2.5">
                <HealthPill health={row.health} reason={row.health_reason}
                            overridden={row.health_overridden} />
              </td>
              <td className="px-3 py-2.5 text-xs text-text-secondary">
                {row.status}
              </td>
              <td className="px-3 py-2.5">
                <Progress percent={row.percent_complete} />
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap text-xs text-text-muted">
                {shortDate(row.start_date)}
                <span className="mx-1">→</span>
                {shortDate(row.target_end_date)}
              </td>
              <td className="px-3 py-2.5 text-xs text-text-secondary">
                {row.next_milestone ? (
                  <>
                    <div>{row.next_milestone}</div>
                    <div className="text-text-muted">
                      {shortDate(row.next_milestone_date)}
                    </div>
                  </>
                ) : (
                  <span className="text-text-muted">None set</span>
                )}
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap text-xs tabular-nums">
                {row.overdue_tasks === 0 && row.blocked_tasks === 0 ? (
                  <span className="text-text-muted">Nothing</span>
                ) : (
                  <>
                    {row.overdue_tasks > 0 && (
                      <span className="text-negative">
                        {row.overdue_tasks} overdue
                      </span>
                    )}
                    {row.overdue_tasks > 0 && row.blocked_tasks > 0 && (
                      <span className="text-text-muted"> · </span>
                    )}
                    {row.blocked_tasks > 0 && (
                      <span className="text-warning">
                        {row.blocked_tasks} blocked
                      </span>
                    )}
                  </>
                )}
              </td>
              <td className="px-4 py-2.5 text-xs text-text-muted">
                {when(row.updated_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * §17. One issue, with everything needed to act on it.
 *
 * Including how far the agent has already chased it — a list that showed the
 * same overdue task for a week without saying "the sponsor was told on
 * Tuesday" is a list people learn to scroll past.
 */
function AttentionRow({ issue }: { issue: PlannerAttentionRow }) {
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={cn(
          "rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
          issue.severity === "critical"
            ? "bg-negative/15 text-negative"
            : "bg-warning/15 text-warning",
        )}>
          {issue.severity === "critical" ? "Critical" : "Warning"}
        </span>
        <Link href={`/delivery/${issue.project.id}`}
              className="text-sm text-text-primary hover:text-accent">
          {issue.project.name}
        </Link>
        <span className="font-mono text-[11px] text-text-muted">
          {issue.entity_code}
        </span>
        <span className="text-sm text-text-secondary">{issue.title}</span>
      </div>
      <p className="mt-1 text-xs text-text-secondary">{issue.reason}</p>
      <p className="mt-1 text-xs text-text-muted">
        Owner {issue.owner?.name ?? "not named"}
        {" · due "}{issue.due_date ?? "no date"}
        {" · "}{issue.escalation.said}
      </p>
      <p className="mt-1 text-xs text-text-primary">
        Next: {issue.next_action}
      </p>
    </li>
  );
}

/** §14. A draft, and the three things you can do with one. */
function DraftLine({
  draft,
  onGone,
}: {
  draft: DraftRow;
  onGone: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const milestones = draft.plan?.milestones?.length ?? 0;
  const tasks = draft.plan?.tasks?.length ?? 0;
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm text-text-primary">
          {draft.name || "Unnamed plan"}
          {draft.code && (
            <span className="ml-2 font-mono text-[11px] text-text-muted">
              {draft.code}
            </span>
          )}
        </p>
        <p className="mt-0.5 text-xs text-text-muted">
          {milestones} {milestones === 1 ? "milestone" : "milestones"},{" "}
          {tasks} {tasks === 1 ? "task" : "tasks"} · last saved{" "}
          {when(draft.updated_at)} · not published, so nobody is being chased
          about it.
        </p>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button asChild size="sm" variant="outline">
          <Link href={`/delivery/new?draft=${draft.key}`}>Continue editing</Link>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api.planner.plan.discard(draft.key);
              onGone();
            } finally {
              setBusy(false);
            }
          }}
        >
          Discard
        </Button>
      </div>
    </li>
  );
}
