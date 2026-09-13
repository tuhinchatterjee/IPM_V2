"use client";

/**
 * Charts and tables, drawn from what the server already validated.
 *
 * Nothing in this file computes anything. Every figure arrives twice from the
 * backend -- `canonical`, which is the full-precision value the arithmetic and
 * the ordering ran on, and `display`, which is that same value written by the
 * one display policy that decides money shows no decimals and a share shows
 * two. This component picks the second and lays it out.
 *
 * That division is the whole point. A frontend that rounded for itself would
 * be a second opinion about a number the server had already published, and
 * the first time the two disagreed nobody would be able to say which was the
 * answer.
 *
 * Bars are scaled from the CANONICAL values, never the displayed strings:
 * "SAR 9,000 million" sorts above "SAR 40,599 million" as text, and a bar
 * chart drawn from formatted labels is a bar chart of string lengths.
 *
 * Drawn as plain SVG and a plain table. A charting library would bring its own
 * number formatting, its own locale rules and its own idea of a sensible axis,
 * and every one of those is a place for the published figure to change on its
 * way to the screen.
 */

import * as React from "react";

import type { ChartPoint, RenderedChart, RenderedTable } from "./client";
import { TOP_N, choose, numeric, text } from "./visual-choice";

export { TOP_N, chartIsUseful } from "./visual-choice";

// ---- table --------------------------------------------------------------

export function ResultTable({ table }: { table: RenderedTable }) {
  const rows = table.rows ?? [];
  const [showAll, setShowAll] = React.useState(false);
  const [sort, setSort] = React.useState<{ column: string; desc: boolean }
    | null>(null);

  const ordered = React.useMemo(() => {
    if (!sort) return rows;
    // Sorted on CANONICAL values. Sorting the displayed strings would order
    // a money column alphabetically.
    const copy = [...rows];
    copy.sort((a, b) => {
      const left = numeric(a.canonical[sort.column]);
      const right = numeric(b.canonical[sort.column]);
      if (left !== null && right !== null) return left - right;
      return text(a.canonical[sort.column]).localeCompare(
        text(b.canonical[sort.column]),
      );
    });
    return sort.desc ? copy.reverse() : copy;
  }, [rows, sort]);

  const shown = showAll ? ordered : ordered.slice(0, TOP_N);
  const hidden = ordered.length - shown.length;

  if (!rows.length) {
    return (
      <p data-testid="v4-table-empty" className="text-sm text-slate-600">
        {table.title ? `${table.title}: ` : ""}no rows matched.
      </p>
    );
  }

  return (
    <figure data-testid="v4-result-table" className="min-w-0">
      {table.title ? (
        <figcaption className="mb-2 text-sm font-medium text-slate-800">
          {table.title}
          <span className="ml-2 font-normal text-slate-500">
            {table.row_count ?? rows.length} row
            {(table.row_count ?? rows.length) === 1 ? "" : "s"}
          </span>
        </figcaption>
      ) : null}
      <div className="overflow-x-auto rounded border border-slate-200">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-slate-50 text-left">
            <tr>
              {table.columns.map((column) => (
                <th key={column} scope="col" className="px-3 py-2 font-medium">
                  <button
                    type="button"
                    data-testid={`v4-table-sort-${column}`}
                    className="text-slate-700 hover:underline"
                    onClick={() =>
                      setSort((prev) =>
                        prev && prev.column === column
                          ? { column, desc: !prev.desc }
                          : { column, desc: true },
                      )
                    }
                  >
                    {column}
                    {sort?.column === column ? (sort.desc ? " ▾" : " ▴") : ""}
                  </button>
                  {table.column_units?.[column] ? (
                    <span className="ml-1 font-normal text-xs text-slate-500">
                      {table.column_units[column]}
                    </span>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr
                key={row.row_id}
                data-testid="v4-table-row"
                className="border-t border-slate-100"
              >
                {table.columns.map((column) => (
                  <td
                    key={column}
                    className="px-3 py-2 tabular-nums text-slate-800"
                    dir="auto"
                  >
                    {text(row.display[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hidden > 0 ? (
        <button
          type="button"
          data-testid="v4-table-show-all"
          onClick={() => setShowAll(true)}
          className="mt-2 text-xs font-medium text-sky-700 hover:underline"
        >
          View all {ordered.length} rows ({hidden} more)
        </button>
      ) : null}
      {showAll && ordered.length > TOP_N ? (
        <button
          type="button"
          data-testid="v4-table-show-top"
          onClick={() => setShowAll(false)}
          className="mt-2 text-xs font-medium text-sky-700 hover:underline"
        >
          Show top {TOP_N}
        </button>
      ) : null}
    </figure>
  );
}

// ---- chart --------------------------------------------------------------

/** The series a chart actually plots, with its canonical scale. */
function series(chart: RenderedChart): {
  column: string;
  unit: string;
  points: { label: string; value: number; display: string; rowId: string }[];
} | null {
  const column = chart.y_columns?.[0];
  if (!column) return null;
  const points = (chart.points ?? [])
    .map((p: ChartPoint) => ({
      rowId: p.row_id,
      label: text(p.label),
      value: numeric(p.values?.[column]),
      display: text(p.display?.[column]),
    }))
    .filter((p): p is { rowId: string; label: string; value: number;
                        display: string } => p.value !== null);
  if (!points.length) return null;
  return {
    column,
    unit: chart.series_units?.[column] ?? chart.unit ?? "",
    points,
  };
}

/**
 * A horizontal bar per category. §13: the shape for a ranked comparison,
 * because the labels are words and words read horizontally.
 */
function BarChart({ chart }: { chart: RenderedChart }) {
  const data = series(chart);
  if (!data) return null;
  // Scaled from canonical values, and from zero: a bar chart whose axis
  // starts elsewhere makes a 3% difference look like a threefold one.
  const max = Math.max(...data.points.map((p) => Math.abs(p.value)), 0);
  return (
    <ol data-testid="v4-chart-bars" className="space-y-1.5">
      {data.points.map((point) => {
        const width = max > 0 ? (Math.abs(point.value) / max) * 100 : 0;
        return (
          <li key={point.rowId} className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3">
            <span className="truncate text-xs text-slate-700" dir="auto"
                  title={point.label}>
              {point.label}
            </span>
            <span className="h-4 rounded-sm bg-slate-100">
              <span
                data-testid="v4-chart-bar"
                data-value={String(point.value)}
                className="block h-4 rounded-sm bg-sky-600"
                style={{ width: `${width}%` }}
                title={`${point.label}: ${point.display}`}
              />
            </span>
            <span className="shrink-0 tabular-nums text-xs text-slate-600">
              {point.display}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** A line over an ordered axis. §13: the shape for a time series. */
function LineChart({ chart }: { chart: RenderedChart }) {
  const data = series(chart);
  if (!data || data.points.length < 2) return null;
  const values = data.points.map((p) => p.value);
  const max = Math.max(...values);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const step = 100 / (data.points.length - 1);
  const path = data.points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(2)} ${
      (100 - ((p.value - min) / span) * 100).toFixed(2)}`)
    .join(" ");

  return (
    <div data-testid="v4-chart-line">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none"
           className="h-40 w-full" role="img"
           aria-label={`${chart.title}. ${data.points.length} points.`}>
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5"
              vectorEffect="non-scaling-stroke" className="text-sky-600" />
      </svg>
      <div className="mt-1 flex justify-between text-xs text-slate-500">
        <span dir="auto">{data.points[0].label}</span>
        <span dir="auto">{data.points[data.points.length - 1].label}</span>
      </div>
      <div className="mt-1 flex justify-between text-xs tabular-nums text-slate-600">
        <span>{data.points[0].display}</span>
        <span>{data.points[data.points.length - 1].display}</span>
      </div>
    </div>
  );
}

/** One bar per category, segmented by series. §13: the shape for a mix. */
function StackedBarChart({ chart }: { chart: RenderedChart }) {
  const columns = chart.y_columns ?? [];
  const points = chart.points ?? [];
  if (columns.length < 2 || !points.length) return null;
  const tones = ["bg-sky-700", "bg-sky-500", "bg-amber-500", "bg-slate-400",
                 "bg-emerald-600"];
  return (
    <div data-testid="v4-chart-stacked" className="space-y-2">
      <ol className="space-y-1.5">
        {points.map((point) => {
          const parts = columns.map((c) => numeric(point.values?.[c]) ?? 0);
          const total = parts.reduce((a, b) => a + Math.abs(b), 0) || 1;
          return (
            <li key={point.row_id}
                className="grid grid-cols-[minmax(0,11rem)_1fr] items-center gap-3">
              <span className="truncate text-xs text-slate-700" dir="auto">
                {text(point.label)}
              </span>
              <span className="flex h-4 overflow-hidden rounded-sm bg-slate-100">
                {parts.map((value, index) => (
                  <span
                    key={columns[index]}
                    className={`h-4 ${tones[index % tones.length]}`}
                    style={{ width: `${(Math.abs(value) / total) * 100}%` }}
                    title={`${columns[index]}: ${
                      text(point.display?.[columns[index]])}`}
                  />
                ))}
              </span>
            </li>
          );
        })}
      </ol>
      <ul className="flex flex-wrap gap-3 text-xs text-slate-600">
        {columns.map((column, index) => (
          <li key={column} className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-2 rounded-sm ${
              tones[index % tones.length]}`} />
            {column}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ResultChart({ chart }: { chart: RenderedChart }) {
  const stacked = (chart.y_columns ?? []).length > 1;
  const body = stacked ? (
    <StackedBarChart chart={chart} />
  ) : chart.kind === "line" ? (
    <LineChart chart={chart} />
  ) : (
    <BarChart chart={chart} />
  );
  if (!body) return null;
  const unit = chart.unit || Object.values(chart.series_units ?? {})[0] || "";
  return (
    <figure data-testid="v4-result-chart" data-kind={chart.kind}
            className="min-w-0">
      <figcaption className="mb-2 text-sm font-medium text-slate-800">
        {chart.title}
        {unit ? (
          <span className="ml-2 font-normal text-slate-500">{unit}</span>
        ) : null}
      </figcaption>
      {body}
    </figure>
  );
}

// ---- what to show -------------------------------------------------------

/**
 * Chart and table together, with a toggle only when both say something.
 *
 * §21: a disabled Chart button beside a table that could never be charted is
 * a control that exists to be refused. When only the table is useful, only
 * the table appears.
 */
export function Visuals({
  tables,
  charts,
}: {
  tables: RenderedTable[];
  charts: RenderedChart[];
}) {
  const { chart, table, both } = choose(tables, charts);
  const [view, setView] = React.useState<"chart" | "table">("chart");

  if (!chart && !table) return null;
  const showing = both ? view : chart ? "chart" : "table";

  return (
    <div data-testid="v4-visuals" className="mt-4 space-y-3">
      {both ? (
        <div
          data-testid="v4-visual-toggle"
          role="group"
          aria-label="Chart or table"
          className="inline-flex rounded border border-slate-200 p-0.5 text-xs"
        >
          {(["chart", "table"] as const).map((option) => (
            <button
              key={option}
              type="button"
              data-testid={`v4-visual-${option}`}
              aria-pressed={showing === option}
              onClick={() => setView(option)}
              className={`rounded px-3 py-1 capitalize ${
                showing === option
                  ? "bg-slate-800 text-white"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      ) : null}
      {showing === "chart" && chart ? <ResultChart chart={chart} /> : null}
      {showing === "table" && table ? <ResultTable table={table} /> : null}
    </div>
  );
}
