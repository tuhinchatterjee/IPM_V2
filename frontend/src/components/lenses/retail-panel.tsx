"use client";

/**
 * A retail lens tile, drawn from the measure engine's own result. §20.
 *
 * What this replaced
 * -------------------
 * Nothing, and that was the defect. A retail tile's result is what
 * `backend/retail/measures.py` returns — a measure, a cut, or a month-by-month
 * trend, each carrying its unit, its meaning, the month it read and the book
 * hash it read from. The lens screen handed that to the corporate
 * `ResultView`, which expects an analysis run with columns and rows, and it
 * threw "Cannot convert undefined or null to object" — taking the whole page
 * down to an error boundary.
 *
 * Nobody saw it, because a second defect was hiding it: the renderer marked
 * these panels `"ok"` where the screen gates on `"succeeded"`, so every tile
 * rendered as "could not be produced" and the code that throws was never
 * reached. Fixing the status is what surfaced this.
 *
 * Why the unit decides the formatting
 * -------------------------------------
 * The measure engine already says whether a number is money, a rate, a count
 * or a ratio. Formatting from that rather than from the column name means a
 * new measure is formatted correctly the day it is added, and means the
 * dashboard and the analysis that share a measure cannot disagree about
 * whether 0.0868 is 8.68% or 0.09.
 */

import * as React from "react";

import { CategoryBarChart, TrendChart } from "@/components/analytics/charts";
import type { RenderedPanel } from "@/lib/api";

type Unit = "money" | "rate" | "count" | "ratio" | "years" | string;

const MONEY = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const COUNT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const RATIO = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

/** One number, said the way its unit means it. */
export function say(value: number | null | undefined, unit: Unit): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (unit) {
    case "money":
      return `${MONEY.format(value)} SAR`;
    case "rate":
      return `${(value * 100).toFixed(2)}%`;
    case "count":
      return COUNT.format(value);
    case "years":
      return `${RATIO.format(value)} yr`;
    default:
      return RATIO.format(value);
  }
}

interface MeasureSpec {
  measure: string;
  label: string;
  unit: Unit;
  meaning?: string;
}

interface ValueResult {
  measure: string; label: string; unit: Unit; meaning?: string;
  value: number | null; facilities?: number;
}

interface TableResult {
  cut: string; cut_label: string; measures: MeasureSpec[];
  rows: Record<string, string | number | null>[];
  not_applicable?: { measure: string; because: string }[];
}

interface TrendResult {
  measures: MeasureSpec[];
  rows: Record<string, string | number | null>[];
}

function Meaning({ said }: { said?: string }) {
  if (!said) return null;
  return (
    <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">{said}</p>
  );
}

function ValueTile({ result }: { result: ValueResult }) {
  return (
    <div data-testid="retail-tile-value">
      <p className="text-[26px] font-semibold leading-none tabular-nums text-text-primary">
        {say(result.value, result.unit)}
      </p>
      <p className="mt-1.5 text-[11px] text-text-muted">{result.label}</p>
      <Meaning said={result.meaning} />
    </div>
  );
}

function TableTile({ result, visual }: { result: TableResult; visual: string }) {
  const rows = result.rows ?? [];
  const measures = result.measures ?? [];
  if (!rows.length || !measures.length) {
    return (
      <p className="text-[12px] text-text-muted">
        Nothing to show: the population carries no rows for this breakdown.
      </p>
    );
  }
  // A chart where the tile asked for one AND one measure carries the
  // comparison. Several measures in different units on one axis is a chart
  // that cannot be read, so those stay a table.
  const chartable = visual === "bar" && measures.length > 0;
  const lead = measures[0];
  const units = Object.fromEntries(measures.map((m) => [m.measure, m.unit]));

  return (
    <div className="space-y-3" data-testid="retail-tile-table">
      {chartable && (
        <CategoryBarChart
          data={rows as Record<string, string | number | null>[]}
          xKey={result.cut}
          series={[{ key: lead.measure, label: lead.label, slot: 0 }]}
          units={units}
          height={Math.max(160, Math.min(320, rows.length * 34 + 40))}
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-border text-left text-[10px] uppercase tracking-[0.12em] text-text-muted">
              <th className="py-1.5 pr-3">{result.cut_label || result.cut}</th>
              {measures.map((one) => (
                <th key={one.measure} className="py-1.5 pl-3 text-right"
                    title={one.meaning}>
                  {one.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={String(row[result.cut] ?? index)}
                  className="border-b border-border/50">
                <td className="py-1.5 pr-3 text-text">
                  {String(row[result.cut] ?? "—")}
                </td>
                {measures.map((one) => (
                  <td key={one.measure}
                      className="py-1.5 pl-3 text-right tabular-nums text-text">
                    {say(row[one.measure] as number | null, one.unit)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(result.not_applicable ?? []).map((one) => (
        <p key={one.measure} className="text-[11px] text-text-muted">
          {one.because}
        </p>
      ))}
    </div>
  );
}

function TrendTile({ result }: { result: TrendResult }) {
  const rows = result.rows ?? [];
  const measures = result.measures ?? [];
  if (!rows.length || !measures.length) {
    return (
      <p className="text-[12px] text-text-muted">
        Nothing to show: the book holds no months for this population.
      </p>
    );
  }
  const units = Object.fromEntries(measures.map((m) => [m.measure, m.unit]));
  return (
    <div className="space-y-2" data-testid="retail-tile-trend">
      <TrendChart
        data={rows as Record<string, string | number | null>[]}
        xKey="month"
        series={measures.map((one, index) => ({
          key: one.measure, label: one.label, slot: index,
        }))}
        units={units}
        height={240}
      />
      <p className="text-[11px] text-text-muted">
        {rows.length} months, {rows[0].month} to {rows[rows.length - 1].month}.
        {" "}
        {measures.map((one) => one.label).join(" · ")}
      </p>
    </div>
  );
}

/** Whether this panel is one the measure engine produced. */
export function isRetailPanel(panel: RenderedPanel): boolean {
  return panel.kind === "retail";
}

export function RetailPanelView({ panel }: { panel: RenderedPanel }) {
  const shape = String(
    ((panel.params ?? {}) as { shape?: string }).shape ?? "table");
  const result = panel.result as unknown;
  if (!result) {
    return (
      <p className="text-[12px] text-text-muted">
        This tile produced no result.
      </p>
    );
  }
  if (shape === "value") return <ValueTile result={result as ValueResult} />;
  if (shape === "trend") return <TrendTile result={result as TrendResult} />;
  return (
    <TableTile result={result as TableResult}
               visual={String(panel.visual ?? "")} />
  );
}
