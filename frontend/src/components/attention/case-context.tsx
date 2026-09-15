"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";

import { TrendChart } from "@/components/analytics/charts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * What the reader was looking at when they pressed Investigate.
 *
 * An investigation opened from a Risk Case used to begin with a title and an
 * empty conversation. The reader had just spent a minute on a drawer holding
 * the finding, its figures and its trend — and then pressed the one button on
 * it, and the screen replaced all of that with a question box. Everything they
 * were about to ask about was now behind a Back button.
 *
 * So the case comes with them: the sentence it concluded, the figures behind
 * it, and the same chart, drawn from the same numbers the case carried. It is
 * a reading surface and nothing on it is recomputed — this is the case as it
 * was raised, not a fresh look at the book that might say something slightly
 * different by the time the thread is reopened.
 *
 * It is deliberately compact and it sits above the first turn rather than
 * beside it, because the conversation is the work and this is the thing the
 * conversation is about.
 */
export function CaseContext({
  context,
  className,
}: {
  context: Record<string, unknown> | undefined;
  className?: string;
}) {
  const found = (context?.risk_case ?? null) as CaseSeed | null;
  const [open, setOpen] = React.useState(true);
  if (!found?.title) return null;

  const chart = found.chart ?? null;
  const rows = chart?.rows ?? [];
  const focus = chart?.focus?.length ? chart.focus : (chart?.series ?? []);
  const metrics = (found.metrics ?? []).filter(
    (m) => m && m.label && m.value !== undefined && m.value !== null,
  );

  return (
    <Card className={cn("overflow-hidden", className)} data-testid="case-context">
      <div className="flex items-start gap-3 px-4 py-3">
        <TriangleAlert
          className="mt-0.5 size-4 shrink-0 text-negative"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <h2 className="text-sm font-medium text-text-primary">
              {found.title}
            </h2>
            {found.period && (
              <span className="mono text-[11px] text-text-muted">
                {found.prior_period
                  ? `${found.prior_period} → ${found.period}`
                  : found.period}
              </span>
            )}
          </div>
          {found.conclusion && (
            <p className="mt-1 text-xs leading-relaxed text-text-secondary">
              {found.conclusion}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen((now) => !now)}
          aria-expanded={open}
          className="shrink-0 text-[11px] text-accent hover:underline"
        >
          {open ? "Hide" : "Show"} the figures
        </button>
      </div>

      {open && (metrics.length > 0 || rows.length > 0) && (
        <div className="border-t border-border px-4 py-3">
          {metrics.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-4">
              {metrics.slice(0, 8).map((metric, index) => (
                <div key={index} className="min-w-0">
                  <dt className="truncate text-[10px] uppercase tracking-[0.08em] text-text-muted">
                    {metric.label}
                  </dt>
                  <dd className="mono tabular text-text-secondary">
                    {formatValue(metric.value)}
                    {metric.unit ? (
                      <span className="ml-0.5 text-[11px] text-text-muted">
                        {metric.unit}
                      </span>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>
          )}

          {rows.length > 0 && focus.length > 0 && (
            <>
              <TrendChart
                className={metrics.length > 0 ? "mt-3" : undefined}
                data={rows}
                xKey="Month"
                series={focus.map((name, index) => ({
                  key: name,
                  label: name,
                  slot: index,
                }))}
                units={Object.fromEntries(
                  focus.map((name) => [name, chart?.unit ?? "%"]),
                )}
                height={180}
              />
              <p className="mt-1 text-[11px] text-text-muted">
                {chart?.title}
                {chart?.unit ? `, ${chart.unit}` : ""}.
                {chart?.note ? ` ${chart.note}` : ""}
              </p>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

/** A figure is shown as it was recorded, grouped for readability and no more. */
function formatValue(value: number | string): string {
  if (typeof value !== "number") return String(value);
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
}

interface CaseSeed {
  id?: number;
  key?: string;
  title?: string;
  about?: string;
  entity?: string;
  severity?: string;
  period?: string;
  prior_period?: string;
  conclusion?: string;
  signals?: string[];
  metrics?: { label: string; value: number | string; unit?: string }[];
  chart?: {
    title?: string;
    unit?: string;
    note?: string;
    series?: string[];
    focus?: string[];
    rows?: Record<string, number | string>[];
  };
}
