"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
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
 * The delivery portfolio — every project this person can see, in one table.
 *
 * The reader is a senior risk person at nine in the morning. They have four
 * questions and they are in this order: what is in trouble, what is late,
 * what is coming, and everything else. So the Attention panel is above the
 * table, not beside it, and the table's first sortable columns are health and
 * lateness rather than name.
 *
 * Every number here is a count of rows that can be opened. A "3 overdue" that
 * leads nowhere teaches people that the figures on this screen are decoration.
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

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-6">
      <PageHeader
        title="Project Planner"
        description="Every delivery project you are on: what is late, what is blocked, who owes an update, and what is due next."
        actions={
          <div className="flex gap-2">
            <Button asChild variant="outline" size="sm">
              <a href={api.planner.templateUrl()}>Plan template</a>
            </Button>
            <Button asChild size="sm">
              <Link href="/delivery/my-work">My work</Link>
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Stat label="Projects" value={totals?.projects ?? 0} />
        <Stat label="Red" value={totals?.red ?? 0} tone="negative" />
        <Stat label="Amber" value={totals?.amber ?? 0} tone="warning" />
        <Stat label="Overdue tasks" value={totals?.overdue_tasks ?? 0}
              tone={totals?.overdue_tasks ? "negative" : undefined} />
        <Stat label="Blocked" value={totals?.blocked_tasks ?? 0}
              tone={totals?.blocked_tasks ? "warning" : undefined} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_360px]">
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
                    <th className="px-4 py-2 font-medium">Last update</th>
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
                        {when(row.last_update_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>

        <div className="flex flex-col gap-4">
          <SectionCard title="Needs attention">
            {brief.loading && <Empty>Working out what needs you…</Empty>}
            {brief.data && brief.data.attention.length === 0 && (
              <Empty>
                Nothing in your portfolio is amber or red on the record.
              </Empty>
            )}
            {brief.data && brief.data.attention.length > 0 && (
              <ul className="divide-y divide-border">
                {brief.data.attention.map((item) => (
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
                          {item.findings.slice(0, 3).map((f, i) => (
                            <li key={i} className="text-xs text-text-muted">
                              · {f.detail}
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

          <SectionCard
            title="Portfolio read"
            action={
              brief.data ? (
                <Badge variant="outline">{brief.data.as_of}</Badge>
              ) : null
            }
          >
            {brief.data ? (
              <div className="px-4 py-3">
                <p className="text-sm font-medium text-text-primary">
                  {brief.data.headline}
                </p>
                <ul className="mt-2 divide-y divide-border">
                  {brief.data.statements.map((s, i) => (
                    <StatementLine key={i} statement={s} />
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
    </div>
  );
}
