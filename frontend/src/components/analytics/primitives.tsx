"use client";

import * as React from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";

import { DataTable } from "@/components/analytics/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { byUnit, unitSuffix, toneFor } from "@/lib/format";
import type { ColumnSpec, Direction } from "@/lib/format";
import type { Row } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * A headline figure.
 *
 * A stat tile, not a chart: when the job is "what is this number", a chart of
 * one value is decoration. The movement carries the tone, and which direction
 * counts as good is declared by the caller — in credit risk a rising number is
 * usually bad news, which is the opposite of most dashboards' default.
 */
export function KpiTile({
  label,
  value,
  unit,
  change,
  changeUnit,
  direction = "up-is-bad",
  hint,
  loading,
  className,
  emphasis = false,
}: {
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  change?: number | null;
  changeUnit?: string;
  direction?: Direction;
  hint?: string;
  loading?: boolean;
  className?: string;
  emphasis?: boolean;
}) {
  if (loading) {
    return (
      <div className={cn("rounded-lg border border-border bg-surface p-4", className)}>
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-7 w-32" />
        <Skeleton className="mt-2 h-3 w-20" />
      </div>
    );
  }

  const tone = change !== null && change !== undefined ? toneFor(change, direction) : "muted";
  const ChangeIcon =
    change === null || change === undefined || change === 0
      ? ArrowRight
      : change > 0
        ? ArrowUpRight
        : ArrowDownRight;

  return (
    <div className={cn("rounded-lg border border-border bg-surface p-4", className)}>
      <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">{label}</p>
      <p
        className={cn(
          "display-num mt-2 flex items-baseline gap-1.5 font-semibold text-text-primary tabular",
          emphasis ? "text-3xl" : "text-2xl",
        )}
      >
        <span>{typeof value === "number" ? byUnit(value, unit) : (value ?? "—")}</span>
        {unitSuffix(unit) && (
          <span className="text-xs font-normal text-text-muted">{unitSuffix(unit)}</span>
        )}
      </p>
      <div className="mt-1.5 flex items-center gap-1.5 text-xs">
        {change !== null && change !== undefined ? (
          <>
            <ChangeIcon
              className={cn(
                "size-3.5 shrink-0",
                tone === "positive" && "text-positive",
                tone === "negative" && "text-negative",
                tone === "muted" && "text-text-muted",
              )}
              aria-hidden
            />
            <span
              className={cn(
                "font-medium tabular",
                tone === "positive" && "text-positive",
                tone === "negative" && "text-negative",
                tone === "muted" && "text-text-muted",
              )}
            >
              {byUnit(Math.abs(change), changeUnit ?? unit)}
            </span>
            {hint && <span className="text-text-muted">{hint}</span>}
          </>
        ) : (
          <span className="text-text-muted">{hint ?? " "}</span>
        )}
      </div>
    </div>
  );
}

/**
 * A table of engine result rows.
 *
 * Kept as the name every analysis renderer already calls, and now a thin
 * adapter over `DataTable`. The two things it still has to do are translate
 * the older `units` map into the column contract `DataTable` expects, and
 * decide when a table is long enough to be worth sticking its header to.
 */
export function ResultTable({
  rows,
  units = {},
  columns,
  spec,
  maxRows,
  className,
  emptyMessage = "No rows returned.",
  renderCell,
}: {
  rows: Row[];
  /** The older per-column unit map, from analyses with no presentation contract. */
  units?: Record<string, string>;
  /** Restrict and order the columns. Defaults to every key on the first row. */
  columns?: string[];
  /**
   * What each column IS, from the backend's presentation contract: its label,
   * its unit, how many decimals it should carry, whether it identifies the
   * row. Falls back to the unit map, and then to guessing from the name.
   */
  spec?: ColumnSpec[];
  maxRows?: number;
  className?: string;
  emptyMessage?: string;
  renderCell?: (column: string, value: unknown, row: Row) => React.ReactNode | undefined;
}) {
  // A contract entry per column, whichever source described it, IN THE ORDER
  // THE CONTRACT GIVES.
  //
  // The order used to come from the row object's keys, which is the order the
  // compiler emitted them — so "for each rating grade, show average ECL
  // coverage, leverage and DSCR" put the grade fourth, because that is where
  // the GROUP happened to produce it. The backend ranks the columns by what
  // the question made them; discarding that here made the ranking invisible.
  //
  // An explicit `columns` list still wins: a caller naming five columns means
  // those five, in that order. And any key the contract does not mention is
  // appended rather than dropped — a figure that vanished from a table is one
  // the reader cannot see and cannot ask about.
  const contract = React.useMemo<ColumnSpec[]>(() => {
    const present = new Set(rows.length ? Object.keys(rows[0]) : []);
    const declared = new Map((spec ?? []).map((c) => [c.name, c]));

    if (columns) {
      return columns.map((name) => declared.get(name) ?? { name, unit: units[name] });
    }

    const ordered = (spec ?? []).filter((c) => present.has(c.name));
    const extra = [...present]
      .filter((name) => !declared.has(name))
      .map((name) => ({ name, unit: units[name] }) as ColumnSpec);
    if (ordered.length || extra.length) return [...ordered, ...extra];

    return [...present].map((name) => ({ name, unit: units[name] }) as ColumnSpec);
  }, [spec, units, columns, rows]);

  return (
    <DataTable
      rows={rows}
      spec={contract}
      columns={columns}
      maxRows={maxRows}
      // Long enough that the header would scroll off before the reader is
      // done with it. Shorter tables get no scroll container at all, which
      // keeps a five-row answer sitting naturally in the page.
      stickyHeader={rows.length > 12}
      maxHeight={rows.length > 12 ? 460 : undefined}
      className={className}
      emptyMessage={emptyMessage}
      renderCell={renderCell}
    />
  );
}

/** A labelled definition row — used by every detail panel. */
export function DefinitionRow({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-[minmax(140px,180px)_1fr] gap-4 py-2", className)}>
      <dt className="text-xs font-medium text-text-muted">{label}</dt>
      <dd className="min-w-0 text-sm text-text-secondary">{children}</dd>
    </div>
  );
}

/** A small labelled figure, for dense summary strips inside a card. */
export function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "positive" | "negative" | "muted";
}) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-text-muted">{label}</p>
      <p
        className={cn(
          "display-num mt-0.5 text-base font-semibold tabular",
          tone === "positive" && "text-positive",
          tone === "negative" && "text-negative",
          !tone && "text-text-primary",
          tone === "muted" && "text-text-muted",
        )}
      >
        {value}
      </p>
    </div>
  );
}
