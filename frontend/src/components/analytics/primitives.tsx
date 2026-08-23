"use client";

import * as React from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { byUnit, humanise, type Direction, toneFor } from "@/lib/format";
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
          "mt-2 font-semibold tracking-tight text-text-primary tabular",
          emphasis ? "text-3xl" : "text-2xl",
        )}
      >
        {typeof value === "number" ? byUnit(value, unit) : (value ?? "—")}
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
 * Columns are derived from the data and formatted by the unit the engine
 * declared, so nothing here decides what a number means — it only decides how
 * many decimals to show.
 */
export function ResultTable({
  rows,
  units = {},
  columns,
  maxRows,
  className,
  emptyMessage = "No rows returned.",
  renderCell,
}: {
  rows: Row[];
  units?: Record<string, string>;
  /** Restrict and order the columns. Defaults to every key on the first row. */
  columns?: string[];
  maxRows?: number;
  className?: string;
  emptyMessage?: string;
  renderCell?: (column: string, value: unknown, row: Row) => React.ReactNode | undefined;
}) {
  if (!rows.length) {
    return <p className="py-6 text-center text-sm text-text-muted">{emptyMessage}</p>;
  }

  const keys = columns ?? Object.keys(rows[0]);
  const shown = maxRows ? rows.slice(0, maxRows) : rows;
  const isNumeric = (key: string) =>
    shown.some((r) => typeof r[key] === "number");

  return (
    <div className={className}>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {keys.map((key) => (
              <TableHead key={key} numeric={isNumeric(key)}>
                {humanise(key)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((row, i) => (
            <TableRow key={i}>
              {keys.map((key) => {
                const custom = renderCell?.(key, row[key], row);
                return (
                  <TableCell key={key} numeric={isNumeric(key)}>
                    {custom !== undefined ? custom : byUnit(row[key], units[key])}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {maxRows && rows.length > maxRows && (
        <p className="px-3 pt-2 text-xs text-text-muted">
          Showing {maxRows} of {rows.length} rows.
        </p>
      )}
    </div>
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
          "mt-0.5 text-base font-semibold tabular",
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
