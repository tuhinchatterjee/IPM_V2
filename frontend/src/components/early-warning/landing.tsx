"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { EarlyWarningDashboard, DashboardMeasure } from "@/lib/api";
import * as ew from "@/lib/early-warning-format";
import { cn } from "@/lib/utils";

/**
 * The Early Warning landing page, in business terms. R2 §10.
 *
 * The screen opened on signal counts — "412 utilisation_high, 389
 * leverage_rose" — which describes how the RULE BOOK is behaving and says
 * nothing about the book. A credit officer arrives wanting to know how many
 * names need them today, how much money is behind those names, and what
 * changed since last quarter.
 *
 * So the counts move to DIAGNOSTICS, below the fold and collapsed, where the
 * person tuning a threshold can still find them.
 */

export const PRIORITY_TONE: Record<string, string> = {
  ACT_NOW: "border-negative/40 bg-negative-muted text-negative",
  REVIEW: "border-warning/40 bg-warning-muted text-warning",
  MONITOR: "border-border-subtle text-text-secondary",
  ROUTINE: "border-border-subtle text-text-muted",
};

export function PriorityBadge({
  priority,
  label,
}: {
  priority: string;
  label?: string;
}) {
  return (
    <span
      className={cn(
        "rounded border px-1.5 py-0.5 text-[11px] font-medium",
        PRIORITY_TONE[priority] ?? PRIORITY_TONE.MONITOR,
      )}
    >
      {label || priority}
    </span>
  );
}

function shown(measure: DashboardMeasure): string {
  if (!measure.available) return "—";
  return ew.showValue(measure.value, measure.unit, measure.currency || "SAR");
}

export function Measures({ measures }: { measures: DashboardMeasure[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {measures.map((measure) => (
        <Card key={measure.key} className="p-4">
          <p className="text-xs text-text-muted">{measure.label}</p>
          <p
            className={cn(
              "mt-1 text-xl font-medium tabular-nums",
              measure.available ? "" : "text-text-muted",
            )}
          >
            {shown(measure)}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
            {measure.available ? measure.means : measure.unavailable}
          </p>
        </Card>
      ))}
    </div>
  );
}

export function Hotspots({
  rows,
  currency,
}: {
  rows: EarlyWarningDashboard["hotspots"];
  currency: string;
}) {
  if (!rows.length) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-medium uppercase tracking-wide text-text-muted">
        Where it is concentrated
      </h2>
      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[32rem] text-left text-xs">
          <thead className="text-text-muted">
            <tr className="border-b border-border-subtle">
              <th className="px-3 py-2 font-medium">Sector</th>
              <th className="px-3 py-2 text-right font-medium">Act now</th>
              <th className="px-3 py-2 text-right font-medium">Review</th>
              <th className="px-3 py-2 text-right font-medium">Exposure</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.sector} className="border-b border-border-subtle">
                <td className="px-3 py-2">{row.sector}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {row.act_now}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {row.review}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {ew.money(row.exposure, currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </section>
  );
}

export function Changes({
  rows,
  currency,
}: {
  rows: EarlyWarningDashboard["changes"];
  currency: string;
}) {
  if (!rows.length) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-medium uppercase tracking-wide text-text-muted">
        What changed this quarter
      </h2>
      <Card className="divide-y divide-border-subtle p-0">
        {rows.map((row) => (
          <div key={row.borrower_id} className="space-y-1 px-4 py-3">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-sm font-medium">
                {row.borrower_name || row.borrower_id}
              </span>
              <span className="text-xs text-text-muted">{row.sector}</span>
              <PriorityBadge
                priority={row.priority}
                label={row.priority_label}
              />
              {row.exposure !== null ? (
                <span className="text-xs tabular-nums text-text-secondary">
                  {ew.money(row.exposure, currency)}
                </span>
              ) : null}
            </div>
            <p className="text-xs leading-relaxed text-text-secondary">
              {row.what_changed}
            </p>
            {row.because.map((said) => (
              <p key={said} className="text-[11px] leading-relaxed text-text-muted">
                {said}
              </p>
            ))}
          </div>
        ))}
      </Card>
    </section>
  );
}

export function Diagnostics({
  rows,
}: {
  rows: EarlyWarningDashboard["diagnostics"];
}) {
  const [open, setOpen] = React.useState(false);
  if (!rows.length) return null;
  return (
    <section className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        className="text-xs font-medium uppercase tracking-wide text-text-muted hover:text-text-secondary"
      >
        {open ? "Hide" : "Show"} rule-book diagnostics
      </button>
      {open ? (
        <Card className="overflow-x-auto p-0">
          <p className="px-3 pt-3 text-[11px] leading-relaxed text-text-muted">
            How often each governed condition fires across the book. This is
            about the RULE BOOK, not about any borrower — it is here for the
            person tuning a threshold.
          </p>
          <table className="mt-2 w-full min-w-[30rem] text-left text-xs">
            <thead className="text-text-muted">
              <tr className="border-b border-border-subtle">
                <th className="px-3 py-2 font-medium">Condition</th>
                <th className="px-3 py-2 text-right font-medium">Borrowers</th>
                <th className="px-3 py-2 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.signal} className="border-b border-border-subtle">
                  <td className="px-3 py-2">{row.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.borrowers}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.share_of_book_pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}
    </section>
  );
}

export function Landing({ book }: { book: EarlyWarningDashboard }) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-sm text-text-secondary">
          <span className="tabular-nums">{book.evaluated.toLocaleString()}</span>{" "}
          borrowers evaluated at {book.period}
          {book.previous_period ? `, against ${book.previous_period}` : ""}.
        </p>
        <Badge variant="outline">
          Priority policy v{book.priority_policy.version} ·{" "}
          {book.priority_policy.owner}
        </Badge>
      </div>
      <Measures measures={book.measures} />
      <Hotspots rows={book.hotspots} currency={book.currency} />
      <Changes rows={book.changes} currency={book.currency} />
      <Diagnostics rows={book.diagnostics} />
    </div>
  );
}
