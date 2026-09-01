"use client";

import * as React from "react";
import { Clock, TriangleAlert } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type RiskCase, type RiskCaseList } from "@/lib/api";
import { cn } from "@/lib/utils";

import { CaseDrawer } from "./case-drawer";
import {
  FILTERS,
  FILTER_LABEL,
  FILTER_LEVEL,
  type Filter,
  LEVEL_LABEL,
  SEVERITY_LABEL,
  SEVERITY_TONE,
  countFor,
  dueLabel,
  isUrgent,
  sorted,
  subtitle,
} from "./severity";

/**
 * Requires Attention. §40–§47.
 *
 * The Cockpit stays calm
 * ----------------------
 * §40: "The Cockpit should remain calm. Do not add Portfolio Pulse or a
 * dashboard wall." §63 asks that at 1440×900 the greeting, the composer, three
 * suggestions and this section all fit above the fold.
 *
 * So: one row of small filter chips with counts, and up to five one-line case
 * rows. Everything else — the signals, the timeline, the evidence, the
 * actions — is in the drawer, one click away. The section is a *list of what
 * needs looking at*, not a place to look at it.
 *
 * §45's sentence is not decoration
 * ---------------------------------
 * "CreditProbe reviewed Q2 2026 and identified 2 portfolio issues, 3 segment
 * issues and 11 borrower cases requiring review." It comes from the backend,
 * built from the same grouped count the badges use, so it can never state a
 * number that is not backed by current Risk Cases — which is exactly what §45
 * forbids.
 *
 * Ordering
 * --------
 * §46: never by model prose. The backend stores a `priority` integer computed
 * from the severity arithmetic; `sorted` reads it and nothing else.
 */
export function RequiresAttention({
  period,
  onInvestigate,
  className,
}: {
  period?: string;
  /** Opening an Investigation is the parent's navigation to perform. */
  onInvestigate?: (investigationId: number) => void;
  className?: string;
}) {
  const [filter, setFilter] = React.useState<Filter>("ALL");
  const [open, setOpen] = React.useState<number | null>(null);
  const [loaded, setLoaded] = React.useState<{
    key: string;
    data: RiskCaseList | null;
    error: string;
  } | null>(null);

  // A counter rather than a refetch function: acting on a case in the drawer
  // has to reload the list, and a `useCallback` the effect also depends on is
  // how one fetch becomes two on every filter change.
  const [reload, setReload] = React.useState(0);
  const key = `${filter}|${period ?? ""}|${reload}`;

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = await api.riskCases({ level: filter, period, limit: 40 });
        if (live) setLoaded({ key, data: found, error: "" });
      } catch (error) {
        if (live)
          setLoaded({
            key,
            data: null,
            error:
              error instanceof Error
                ? error.message
                : "Requires Attention could not be loaded.",
          });
      }
    })();
    return () => {
      live = false;
    };
  }, [filter, period, key]);

  // The state carries the key it was loaded for, so a filter change shows a
  // skeleton rather than the previous filter's rows under the new tab.
  const settled = loaded && loaded.key === key ? loaded : null;
  const found = settled?.data ?? null;
  const cases = found ? sorted(found.cases) : [];

  return (
    <div className={cn("min-w-0", className)} data-testid="requires-attention">
      {/* §45 — one grounded sentence, above the filters. */}
      {found?.summary && (
        <p className="mb-2 text-sm text-text-secondary" data-testid="attention-summary">
          {found.summary}
        </p>
      )}

      <Filters
        filter={filter}
        counts={found?.counts}
        onPick={setFilter}
        className="mb-2"
      />

      <Card className="overflow-hidden">
        {settled === null && <Skeleton className="h-40 w-full" />}

        {settled?.error && (
          <p className="px-4 py-4 text-sm text-negative">{settled.error}</p>
        )}

        {settled && !settled.error && cases.length === 0 && (
          <Empty filter={filter} period={period} />
        )}

        {cases.length > 0 && (
          <ul className="divide-y divide-border">
            {cases.slice(0, 5).map((found_) => (
              <li key={found_.id}>
                <CaseRow
                  found={found_}
                  onOpen={() => setOpen(found_.id)}
                  showLevel={filter === "ALL"}
                />
              </li>
            ))}
          </ul>
        )}

        {cases.length > 5 && (
          <p className="border-t border-border bg-surface-sunken px-4 py-2 text-xs text-text-muted">
            {cases.length - 5} more {cases.length - 5 === 1 ? "case" : "cases"}{" "}
            below this list. Filter to narrow it.
          </p>
        )}
      </Card>

      {open !== null && (
        <CaseDrawer
          caseId={open}
          onClose={() => setOpen(null)}
          onChanged={() => setReload((n) => n + 1)}
          onInvestigate={onInvestigate}
        />
      )}
    </div>
  );
}

/**
 * §40's compact level filters with counts and severity.
 *
 * Chips rather than tabs: tabs imply five separate pages of content, and this
 * is one list being narrowed. A count of zero is shown greyed rather than
 * hidden — "no borrower cases this period" is information, and a tab that
 * disappears makes the reader wonder whether it was ever there.
 */
function Filters({
  filter,
  counts,
  onPick,
  className,
}: {
  filter: Filter;
  counts: Record<string, number> | undefined;
  onPick: (filter: Filter) => void;
  className?: string;
}) {
  return (
    <div
      className={cn("flex flex-wrap items-center gap-1", className)}
      role="tablist"
      aria-label="Filter cases by level"
    >
      {FILTERS.map((one) => {
        const count = countFor(one, counts);
        const active = filter === one;
        return (
          <button
            key={one}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onPick(one)}
            data-testid={`attention-filter-${one}`}
            className={cn(
              "rounded px-2 py-1 text-xs transition-colors",
              active
                ? "bg-accent text-accent-contrast"
                : "text-text-secondary hover:bg-surface-hover",
              !active && count === 0 && "text-text-muted",
            )}
          >
            {FILTER_LABEL[one]}
            <span
              className={cn(
                "mono ml-1.5 tabular",
                active ? "opacity-80" : "text-text-muted",
              )}
            >
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * One case, on one line.
 *
 * Severity word, title, and a subtitle carrying what the level is about. §41's
 * fuller list — evidence, validation, owner, actions — is the drawer's job:
 * putting it here would make five cases into a wall, which is the dashboard
 * §40 asks us not to build.
 */
function CaseRow({
  found,
  onOpen,
  showLevel,
}: {
  found: RiskCase;
  onOpen: () => void;
  showLevel: boolean;
}) {
  const due = dueLabel(found);
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="attention-case"
      data-severity={found.severity}
      data-level={found.level}
      className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-hover"
    >
      {isUrgent(found) ? (
        <TriangleAlert
          className="mt-0.5 size-3.5 shrink-0 text-negative"
          aria-hidden
        />
      ) : (
        <span
          className={cn(
            "mt-1 size-2 shrink-0 rounded-full",
            found.severity === "medium" ? "bg-warning" : "bg-text-muted/40",
          )}
          aria-hidden
        />
      )}

      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-3">
          <span className="truncate text-sm font-medium text-text-primary">
            {found.title}
          </span>
          <span
            className={cn(
              "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
              SEVERITY_TONE[found.severity] ?? "",
            )}
          >
            {SEVERITY_LABEL[found.severity] ?? found.severity}
          </span>
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-text-muted">
          {showLevel && (
            <span className="text-text-secondary">
              {LEVEL_LABEL[found.level] ?? found.level}
            </span>
          )}
          <span className="truncate">{subtitle(found)}</span>
          {due && (
            <span
              className={cn(
                "inline-flex items-center gap-1",
                found.overdue && "text-negative",
              )}
            >
              <Clock className="size-3" aria-hidden />
              {due}
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

/**
 * Nothing to attend to is a finding, and it is said.
 *
 * An empty grey rectangle under a heading is what a generic admin dashboard
 * looks like and tells the reader nothing — the same reasoning that produced
 * the original Cockpit's empty state, kept.
 */
function Empty({ filter, period }: { filter: Filter; period?: string }) {
  const level = FILTER_LEVEL[filter];
  const what =
    filter === "ALL"
      ? "Nothing requires attention"
      : `No ${FILTER_LABEL[filter].toLowerCase()} cases`;
  return (
    <p className="px-4 py-6 text-center text-sm text-text-secondary">
      {what}
      {period ? ` in ${period}` : ""}.
      <span className="mt-1 block text-xs text-text-muted">
        {level
          ? "Cases appear here when a governed review finds something at this level."
          : "CreditProbe reviews each published period and raises a case when a governed threshold is crossed."}
      </span>
    </p>
  );
}
