"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { CopilotChat } from "@/components/planner/copilot-chat";
import {
  Empty,
  HealthPill,
  Progress,
  SectionCard,
  Stat,
  StatementLine,
  when,
} from "@/components/planner/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Delivery, in the order somebody actually arrives at it.
 *
 * The old version of this page opened with a table of every project, which is
 * the right thing to show somebody who already knows which project they came
 * for and the wrong thing to show everybody else. §3 reorders it around what
 * a person is doing rather than around what the system stores:
 *
 *   1. say what you want, in words;
 *   2. two things almost everybody is here to do;
 *   3. what needs you today;
 *   4. everything, for when you know what you are looking for.
 *
 * The table did not get worse and it did not go away. It stopped being the
 * first thing, which is a different claim.
 */
export default function DeliveryPortfolioPage() {
  const [search, setSearch] = React.useState("");
  const [health, setHealth] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [query, setQuery] = React.useState("");

  // Typing filters the table on every keystroke, which is a query per
  // keystroke. Debounced rather than searched-on-enter: a filter that needs
  // a keypress to take effect gets used once and then abandoned.
  React.useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const portfolio = useAsync(
    () => api.planner.portfolio({ search: query, health, status }),
    [query, health, status],
  );
  const brief = useAsync(() => api.planner.portfolioBrief(6), []);

  const totals = portfolio.data?.totals;
  const rows = portfolio.data?.projects ?? [];
  const attention = brief.data?.attention ?? [];

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-6">
      <PageHeader
        title="Delivery"
        description="Tell the Copilot what you want to do, or pick up where you left off."
        actions={
          <Button asChild variant="outline" size="sm">
            <a href={api.planner.templateUrl()}>Plan template</a>
          </Button>
        }
      />

      {/* 1 — the conversation. */}
      <CopilotChat
        className="mt-2"
        suggestions={[
          "Start a new project",
          "What is overdue?",
          "Who owes me an update?",
          "What is on the critical path?",
        ]}
      />

      {/* 2 — the two things almost everybody is here to do. */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <QuickAction
          href="/delivery/new"
          title="Start a new project"
          detail="Build the plan in conversation, see the whole thing, then publish it."
        />
        <QuickAction
          href="/delivery/my-work"
          title="What needs me today"
          detail="Your tasks, what is late, and what you have been asked for."
        />
      </div>

      {/* 3 — what needs somebody, before the list of everything. */}
      <div className="mt-4" />
      <SectionCard
        title="Needs attention"
        action={
          brief.data ? <Badge variant="outline">{brief.data.as_of}</Badge> : null
        }
      >
        {brief.loading && <Empty>Working out what needs you…</Empty>}
        {brief.data && attention.length === 0 && (
          <Empty>Nothing in your portfolio is amber or red on the record.</Empty>
        )}
        {attention.length > 0 && (
          <ul className="divide-y divide-border">
            {attention.map((item) => (
              <li key={item.id} className="px-4 py-3">
                <Link href={`/delivery/${item.id}`} className="block">
                  <div className="flex items-center gap-2">
                    <HealthPill health={item.health} />
                    <span className="truncate text-sm text-text-primary">
                      {item.name}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-text-secondary">
                    {item.reason}
                  </p>
                  {item.findings.length > 0 && (
                    <ul className="mt-1.5 space-y-0.5">
                      {item.findings.slice(0, 3).map((finding, index) => (
                        <li key={index} className="text-xs text-text-muted">
                          · {finding.detail}
                        </li>
                      ))}
                    </ul>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {/* 4 — everything, for when you know what you are looking for. */}
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Stat label="Projects" value={totals?.projects ?? 0} />
        <Stat label="Red" value={totals?.by_health.RED ?? 0} tone="negative" />
        <Stat label="Amber" value={totals?.by_health.AMBER ?? 0}
              tone="warning" />
        <Stat label="Overdue tasks" value={totals?.overdue_tasks ?? 0}
              tone={totals?.overdue_tasks ? "negative" : undefined} />
        <Stat label="Blocked" value={totals?.blocked_tasks ?? 0}
              tone={totals?.blocked_tasks ? "warning" : undefined} />
      </div>

      <div className="mt-4 space-y-4">
        <SectionCard
          title="Projects"
          action={
            <div className="flex items-center gap-2">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search name or code"
                className="h-8 w-48 text-xs"
                aria-label="Search projects"
              />
              <select
                value={health}
                onChange={(e) => setHealth(e.target.value)}
                aria-label="Filter by health"
                className="h-8 rounded-md border border-border bg-surface px-2 text-xs text-text-secondary"
              >
                <option value="">All health</option>
                <option value="RED">Red</option>
                <option value="AMBER">Amber</option>
                <option value="GREEN">Green</option>
                <option value="UNKNOWN">Unknown</option>
              </select>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                aria-label="Filter by status"
                className="h-8 rounded-md border border-border bg-surface px-2 text-xs text-text-secondary"
              >
                <option value="">All open</option>
                <option value="DRAFT">Draft</option>
                <option value="ACTIVE">Active</option>
                <option value="ON_HOLD">On hold</option>
                <option value="COMPLETED">Completed</option>
              </select>
            </div>
          }
        >
          {portfolio.loading && <Empty>Reading the portfolio…</Empty>}
          {portfolio.error && (
            <p className="px-4 py-6 text-sm text-negative">{portfolio.error}</p>
          )}
          {!portfolio.loading && !portfolio.error && rows.length === 0 && (
            <Empty>
              {query || health || status
                ? "No project matches that filter."
                : "You are not on any delivery project yet."}
            </Empty>
          )}
          {rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-muted">
                    <th className="px-4 py-2 font-medium">Project</th>
                    <th className="px-3 py-2 font-medium">Health</th>
                    <th className="px-3 py-2 font-medium">Progress</th>
                    <th className="px-3 py-2 font-medium text-right">Overdue</th>
                    <th className="px-3 py-2 font-medium text-right">Blocked</th>
                    <th className="px-3 py-2 font-medium">Next milestone</th>
                    <th className="px-3 py-2 font-medium">Manager</th>
                    <th className="px-4 py-2 font-medium">Recalculated</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}
                        className="border-b border-border last:border-0 hover:bg-surface-hover">
                      <td className="px-4 py-2.5">
                        <Link href={`/delivery/${row.id}`}
                              className="block min-w-0">
                          <span className="font-mono text-[11px] text-text-muted">
                            {row.code}
                          </span>
                          <span className="ml-2 text-text-primary">
                            {row.name}
                          </span>
                        </Link>
                      </td>
                      <td className="px-3 py-2.5">
                        <HealthPill health={row.health}
                                    reason={row.health_reason}
                                    overridden={row.health_overridden} />
                      </td>
                      <td className="px-3 py-2.5">
                        <Progress percent={row.percent_complete} />
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {row.overdue_tasks > 0 ? (
                          <span className="text-negative">{row.overdue_tasks}</span>
                        ) : (
                          <span className="text-text-muted">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {row.blocked_tasks > 0 ? (
                          <span className="text-warning">{row.blocked_tasks}</span>
                        ) : (
                          <span className="text-text-muted">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-text-secondary">
                        {row.next_milestone ? (
                          <>
                            {row.next_milestone}
                            <span className="ml-1 text-text-muted">
                              {row.next_milestone_date}
                            </span>
                          </>
                        ) : (
                          <span className="text-text-muted">None set</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-text-secondary">
                        {row.manager?.name ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-text-muted">
                        {when(row.calculated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Portfolio read">
          {brief.data ? (
            <div className="px-4 py-3">
              <p className="text-sm font-medium text-text-primary">
                {brief.data.headline}
              </p>
              <ul className="mt-2 divide-y divide-border">
                {brief.data.statements.map((statement, index) => (
                  <StatementLine key={index} statement={statement} />
                ))}
              </ul>
              <p className="mt-3 border-t border-border pt-2 text-[11px] text-text-muted">
                {brief.data.grounding}
              </p>
            </div>
          ) : (
            <Empty>{brief.error ?? "Reading the portfolio…"}</Empty>
          )}
        </SectionCard>
      </div>
    </div>
  );
}

/** One of the two things almost everybody opening this page came to do. */
function QuickAction({
  href,
  title,
  detail,
}: {
  href: string;
  title: string;
  detail: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-lg border border-border bg-surface px-4 py-3.5 transition hover:border-accent"
    >
      <p className="text-sm font-semibold text-text-primary">{title}</p>
      <p className="mt-0.5 text-xs text-text-secondary">{detail}</p>
    </Link>
  );
}
