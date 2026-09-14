"use client";

/**
 * The pictures a What-If result is read through.
 *
 * A scenario answers "how much" with one number and "why" with about eight,
 * and the second question is the one a reader came with. Tables carry the
 * second answer honestly and slowly: the shape of a distribution, the fact
 * that a movement is concentrated in one band, the order the mechanism ran in,
 * are all present in a table and none of them are visible in it.
 *
 * Three rules hold across everything here.
 *
 * **Colour means something.** Deterioration is drawn in the negative token and
 * improvement in the positive one, everywhere, so a reader never has to check
 * which way up a chart is. Categorical series use the palette slots the rest
 * of the application uses, so a chart in a What-If thread and a chart on a
 * Lens are the same chart.
 *
 * **Nothing is drawn that was not measured.** A waterfall step exists because
 * the engine re-ran the scenario and reported the difference; a distribution
 * bar exists because a cut of the book was counted. There is no interpolation
 * and no smoothing anywhere in this file.
 *
 * **An empty chart says why it is empty.** A scenario with no delinquency
 * migration has no delinquency chart, and the reader is told that rather than
 * shown an axis with nothing on it.
 */

import * as React from "react";

import {
  CategoryBarChart,
  StackedBarChart,
  slotColor,
} from "@/components/analytics/charts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const NEGATIVE = "var(--ipm-negative)";
const POSITIVE = "var(--ipm-positive)";
const NEUTRAL = "var(--ipm-accent)";

export function money(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const size = Math.abs(n);
  if (size >= 1e9) return `${sign}SAR ${(size / 1e9).toFixed(2)}bn`;
  if (size >= 1e6) return `${sign}SAR ${(size / 1e6).toFixed(1)}mn`;
  if (size >= 1e3) return `${sign}SAR ${Math.round(size / 1e3)}k`;
  return `${sign}SAR ${size.toFixed(0)}`;
}

export function count(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString() : "—";
}

export function ratioPct(value: unknown, places = 2): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(places)}%` : "—";
}

/** A titled box with a sentence under the title, or a reason it is empty. */
export function Panel({ title, note, empty, children, testId, className }: {
  title: string;
  note?: string;
  empty?: string;
  children?: React.ReactNode;
  testId?: string;
  className?: string;
}) {
  return (
    <Card className={cn("p-4", className)} data-testid={testId}>
      <p className="text-sm font-semibold text-text-primary">{title}</p>
      {note ? (
        <p className="mt-0.5 text-[11px] leading-relaxed text-text-secondary">
          {note}
        </p>
      ) : null}
      {empty ? (
        <p className="mt-3 text-[12px] italic text-text-muted">{empty}</p>
      ) : (
        <div className="mt-3">{children}</div>
      )}
    </Card>
  );
}

export interface WaterfallStep {
  key: string;
  label: string;
  from_sar: number;
  to_sar: number;
  change_sar: number;
  change_pct?: number | null;
  facilities_moved?: number | null;
}

/**
 * The mechanism, drawn.
 *
 * Each bar floats between where the number was and where the step left it, so
 * the eye follows one line from the baseline to the final figure. The first
 * and last bars sit on the floor because they are levels, not changes — a
 * waterfall that drew them floating would be showing a movement that has no
 * before.
 *
 * Drawn here rather than with the shared bar chart because a waterfall needs
 * an invisible base per bar, which is a property of this chart and not of bar
 * charts.
 */
export function WaterfallChart({ steps, baseline, final, height = 260 }: {
  steps: WaterfallStep[];
  baseline: number;
  final: number;
  height?: number;
}) {
  if (!steps.length) return null;

  const bars = [
    { label: "Baseline", base: 0, size: baseline, value: baseline,
      kind: "level" as const },
    ...steps.map((one) => ({
      label: one.label,
      base: Math.min(one.from_sar, one.to_sar),
      size: Math.abs(one.change_sar),
      value: one.change_sar,
      kind: (one.change_sar >= 0 ? "up" : "down") as "up" | "down",
    })),
    { label: "After", base: 0, size: final, value: final,
      kind: "level" as const },
  ];

  const top = Math.max(...bars.map((one) => one.base + one.size), 1);
  const colour = (kind: string) =>
    kind === "level" ? NEUTRAL : kind === "up" ? NEGATIVE : POSITIVE;

  return (
    <div data-testid="whatif-waterfall-chart">
      <div className="flex items-end gap-1.5 overflow-x-auto pb-1"
           style={{ height }}>
        {bars.map((one, index) => {
          const plot = height - 46;
          const bottom = (one.base / top) * plot;
          const size = Math.max((one.size / top) * plot, 2);
          return (
            <div key={`${one.label}-${index}`}
                 className="flex min-w-[58px] flex-1 flex-col items-center">
              <span className="mb-0.5 whitespace-nowrap text-[9px] tabular-nums
                               text-text-secondary">
                {one.kind === "level" ? money(one.value)
                  : `${one.value >= 0 ? "+" : ""}${money(one.value)}`}
              </span>
              <div className="relative w-full" style={{ height: plot }}>
                <div className="absolute w-full rounded-sm"
                     style={{ bottom, height: size,
                              background: colour(one.kind),
                              opacity: one.kind === "level" ? 0.85 : 0.75 }} />
              </div>
              <span className="mt-1 line-clamp-2 text-center text-[9px]
                               leading-tight text-text-muted">
                {one.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Two bars per measure: what it was, and what the scenario left it at. */
export function BeforeAfterChart({ rows, height = 240 }: {
  rows: { measure: string; before: number; after: number }[];
  height?: number;
}) {
  if (!rows.length) return null;
  return (
    <CategoryBarChart
      data={rows.map((one) => ({
        measure: one.measure, Before: one.before, After: one.after }))}
      xKey="measure"
      series={[{ key: "Before", label: "Before", slot: 0 },
               { key: "After", label: "After", slot: 3 }]}
      height={height}
      horizontal
    />
  );
}

/** One cut of the cohort, as bars. */
export function DistributionChart({ rows, valueKey, valueLabel, height = 230 }: {
  rows: { label: string; [key: string]: unknown }[];
  valueKey: string;
  valueLabel: string;
  height?: number;
}) {
  if (!rows.length) return null;
  return (
    <CategoryBarChart
      data={rows.map((one) => ({
        band: String(one.label), [valueLabel]: Number(one[valueKey] ?? 0) }))}
      xKey="band"
      series={[{ key: valueLabel, label: valueLabel, slot: 1 }]}
      height={height}
      horizontal
    />
  );
}

/** A cut drawn twice over: how many, and how much money. */
export function CutChart({ cut, height = 230 }: {
  cut: { label: string; rows: { label: string; accounts: number;
                                exposure_sar: number }[] };
  height?: number;
}) {
  const rows = (cut.rows || []).map((one) => ({
    band: String(one.label),
    Accounts: Number(one.accounts ?? 0),
    "Exposure (SAR mn)": Number(one.exposure_sar ?? 0) / 1e6,
  }));
  if (!rows.length) return null;
  return (
    <StackedBarChart
      data={rows}
      xKey="band"
      series={[{ key: "Accounts", label: "Accounts", slot: 0 }]}
      height={height}
    />
  );
}

/**
 * Where the movement landed, worst first.
 *
 * Drawn as a diverging bar so an improvement and a deterioration sit on
 * opposite sides of zero rather than both reading as "a big bar".
 */
export function ContributionChart({ rows, height = 240 }: {
  rows: { label: string; change_sar: number }[];
  height?: number;
}) {
  if (!rows.length) return null;
  const widest = Math.max(...rows.map((one) => Math.abs(one.change_sar)), 1);
  return (
    <div className="space-y-1" data-testid="whatif-contribution-chart"
         style={{ minHeight: Math.min(height, rows.length * 26) }}>
      {rows.map((one) => {
        const share = Math.abs(one.change_sar) / widest;
        const up = one.change_sar >= 0;
        return (
          <div key={one.label} className="flex items-center gap-2 text-[11px]">
            <span className="w-40 shrink-0 truncate text-text-secondary">
              {one.label}
            </span>
            <div className="relative h-4 flex-1">
              <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
              <div className="absolute inset-y-0.5 rounded-sm"
                   style={{
                     background: up ? NEGATIVE : POSITIVE,
                     opacity: 0.75,
                     left: up ? "50%" : `${50 - share * 50}%`,
                     width: `${share * 50}%`,
                   }} />
            </div>
            <span className="w-24 shrink-0 text-right tabular-nums
                             text-text-primary">
              {up ? "+" : ""}{money(one.change_sar)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** The same movement, seen from five widths. */
export function LevelsChart({ rows, height = 200 }: {
  rows: { label: string; pct: number }[];
  height?: number;
}) {
  if (!rows.length) return null;
  const widest = Math.max(...rows.map((one) => Math.abs(one.pct)), 0.0001);
  return (
    <div className="space-y-1.5" data-testid="whatif-levels-chart"
         style={{ minHeight: Math.min(height, rows.length * 30) }}>
      {rows.map((one) => (
        <div key={one.label} className="flex items-center gap-2 text-[11px]">
          <span className="w-48 shrink-0 truncate text-text-secondary">
            {one.label}
          </span>
          <div className="h-4 flex-1 rounded-sm bg-surface-muted">
            <div className="h-full rounded-sm"
                 style={{ width: `${(Math.abs(one.pct) / widest) * 100}%`,
                          background: one.pct >= 0 ? NEGATIVE : POSITIVE,
                          opacity: 0.75 }} />
          </div>
          <span className="w-20 shrink-0 text-right tabular-nums
                           text-text-primary">
            {one.pct >= 0 ? "+" : ""}{(one.pct * 100).toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}

/** A legend a reader can check the colours against, once per thread. */
export function ColourKey() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-[10px] text-text-muted"
         data-testid="whatif-colour-key">
      {[["Deterioration", NEGATIVE], ["Improvement", POSITIVE],
        ["Level", NEUTRAL], ["Category", slotColor(1)]].map(([label, tone]) => (
        <span key={label} className="flex items-center gap-1">
          <span className="size-2.5 rounded-sm"
                style={{ background: tone, opacity: 0.8 }} />
          {label}
        </span>
      ))}
    </div>
  );
}
