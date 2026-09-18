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
import type { ChartKind } from "./visual-choice";

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

/**
 * A line over an ordered axis. §13: the shape for a time series.
 *
 * FOUR FORMS SHARE THIS GEOMETRY and none of them is the others. A `line`
 * interpolates between readings; a `step_line` holds each value until the
 * next one, which is what a policy rate or a limit actually does; an `area`
 * fills to the baseline, so the eye reads the total rather than the slope;
 * a `scatter` draws the points and NO line, because there is no ordering
 * between them to interpolate along. All four rendered as a plain line,
 * which told the reader three things that were not true.
 */
function LineChart({ chart, variant = "line" }: {
  chart: RenderedChart;
  variant?: "line" | "step_line" | "area" | "scatter";
}) {
  const data = series(chart);
  if (!data || data.points.length < 2) return null;
  const values = data.points.map((p) => p.value);
  const max = Math.max(...values);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const step = 100 / (data.points.length - 1);
  const at = (p: { value: number }, i: number): [number, number] => [
    i * step, 100 - ((p.value - min) / span) * 100];
  const path = data.points
    .map((p, i) => {
      const [x, y] = at(p, i);
      if (i === 0) return `M ${x.toFixed(2)} ${y.toFixed(2)}`;
      if (variant === "step_line") {
        const [, previous] = at(data.points[i - 1], i - 1);
        return `L ${x.toFixed(2)} ${previous.toFixed(2)} L ${x.toFixed(2)} ${
          y.toFixed(2)}`;
      }
      return `L ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <div data-testid={`v4-chart-${variant === "line" ? "line" : variant}`}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none"
           className="h-40 w-full" role="img"
           aria-label={`${chart.title}. ${data.points.length} points.`}>
        {variant === "area" ? (
          <path d={`${path} L 100 100 L 0 100 Z`} fill="currentColor"
                className="text-sky-600/20" stroke="none" />
        ) : null}
        {variant === "scatter" ? null : (
          <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5"
                vectorEffect="non-scaling-stroke" className="text-sky-600" />
        )}
        {variant === "scatter"
          ? data.points.map((p, i) => {
              const [x, y] = at(p, i);
              return (
                <circle key={p.rowId} cx={x} cy={y} r="1.6"
                        vectorEffect="non-scaling-stroke"
                        className="fill-sky-600">
                  <title>{`${p.label}: ${p.display}`}</title>
                </circle>
              );
            })
          : null}
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
/**
 * Segments piled to a total, per category.
 *
 * `normalise` is the difference between the two forms a credit pack uses.
 * A 100% stack answers "what SHARE sits in each bucket" — the delinquency
 * band mix — and every row fills the width. A plain stack keeps the totals
 * comparable, so a book that grew shows a longer bar.
 */
function StackedBarChart({ chart, normalise = true }: {
  chart: RenderedChart;
  normalise?: boolean;
}) {
  const columns = chart.y_columns ?? [];
  const points = chart.points ?? [];
  if (columns.length < 2 || !points.length) return null;
  const tones = ["bg-sky-700", "bg-sky-500", "bg-amber-500", "bg-slate-400",
                 "bg-emerald-600", "bg-rose-500", "bg-violet-500"];
  const widest = Math.max(
    ...points.map((p) =>
      columns.reduce((sum, c) => sum + Math.abs(numeric(p.values?.[c]) ?? 0), 0)),
    0) || 1;
  return (
    <div data-testid={normalise ? "v4-chart-stacked" : "v4-chart-stacked-abs"}
         className="space-y-2">
      <ol className="space-y-1.5">
        {points.map((point) => {
          const parts = columns.map((c) => numeric(point.values?.[c]) ?? 0);
          const sum = parts.reduce((a, b) => a + Math.abs(b), 0) || 1;
          const total = normalise ? sum : widest;
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

/** Bars side by side per category: the comparison is WITHIN a group. */
function GroupedBarChart({ chart }: { chart: RenderedChart }) {
  const columns = chart.y_columns ?? [];
  const points = chart.points ?? [];
  if (columns.length < 2 || !points.length) return null;
  const tones = ["bg-sky-700", "bg-amber-500", "bg-emerald-600",
                 "bg-violet-500", "bg-rose-500"];
  const max = Math.max(
    ...points.flatMap((p) =>
      columns.map((c) => Math.abs(numeric(p.values?.[c]) ?? 0))), 0) || 1;
  return (
    <div data-testid="v4-chart-grouped" className="space-y-2">
      <ol className="space-y-2">
        {points.map((point) => (
          <li key={point.row_id} className="space-y-0.5">
            <span className="truncate text-xs text-slate-700" dir="auto">
              {text(point.label)}
            </span>
            {columns.map((column, index) => {
              const value = numeric(point.values?.[column]) ?? 0;
              return (
                <span key={column} className="flex items-center gap-2">
                  <span className="h-2.5 w-full rounded-sm bg-slate-100">
                    <span className={`block h-2.5 rounded-sm ${
                            tones[index % tones.length]}`}
                          style={{ width: `${(Math.abs(value) / max) * 100}%` }}
                          title={`${column}: ${text(point.display?.[column])}`} />
                  </span>
                  <span className="shrink-0 tabular-nums text-[10px] text-slate-500">
                    {text(point.display?.[column])}
                  </span>
                </span>
              );
            })}
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Volumes as bars, a RATE as a line on its own scale.
 *
 * Exposure in SAR millions and a delinquency rate in percent do not share
 * an axis. Plotted on one, the rate is a flat line along the floor and the
 * chart says nothing — which is why this form exists separately.
 */
function ComboChart({ chart }: { chart: RenderedChart }) {
  const columns = chart.y_columns ?? [];
  const points = chart.points ?? [];
  if (columns.length < 2 || !points.length) return null;
  const [bars, line] = columns;
  const barMax = Math.max(
    ...points.map((p) => Math.abs(numeric(p.values?.[bars]) ?? 0)), 0) || 1;
  const rates = points.map((p) => numeric(p.values?.[line]) ?? 0);
  const top = Math.max(...rates);
  const bottom = Math.min(...rates);
  const span = top - bottom || 1;
  return (
    <div data-testid="v4-chart-combo" className="space-y-2">
      <ol className="space-y-1.5">
        {points.map((point, index) => {
          const value = numeric(point.values?.[bars]) ?? 0;
          const rate = rates[index];
          return (
            <li key={point.row_id}
                className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3">
              <span className="truncate text-xs text-slate-700" dir="auto">
                {text(point.label)}
              </span>
              <span className="relative block h-4 rounded-sm bg-slate-100">
                <span className="block h-4 rounded-sm bg-sky-700"
                      style={{ width: `${(Math.abs(value) / barMax) * 100}%` }}
                      title={`${bars}: ${text(point.display?.[bars])}`} />
                <span data-testid="v4-combo-rate"
                      className="absolute top-0 h-4 w-0.5 bg-amber-500"
                      style={{ left: `${((rate - bottom) / span) * 100}%` }}
                      title={`${line}: ${text(point.display?.[line])}`} />
              </span>
              <span className="shrink-0 tabular-nums text-xs text-amber-700">
                {text(point.display?.[line])}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Shares of one whole. `hole` makes it a donut. */
function SliceChart({ chart, hole }: { chart: RenderedChart; hole: number }) {
  const data = series(chart);
  if (!data) return null;
  const total = data.points.reduce((a, p) => a + Math.abs(p.value), 0);
  if (total <= 0) return null;
  const tones = ["#0f172a", "#0ea5e9", "#b45309", "#15803d", "#7c3aed",
                 "#be123c", "#0891b2", "#a16207"];
  // The running angle is carried in the array rather than in a variable
  // this closure reassigns: a render body that mutates its own scope is a
  // render that can disagree with itself on a re-run.
  const starts = data.points.reduce<number[]>(
    (acc, point) => [...acc,
                     acc[acc.length - 1] + (Math.abs(point.value) / total) * 360],
    [-90]);
  const arcs = data.points.map((point, index) => {
    const sweep = (Math.abs(point.value) / total) * 360;
    const start = starts[index];
    const angle = starts[index + 1];
    const rad = (deg: number) => (deg * Math.PI) / 180;
    const x1 = 60 + 52 * Math.cos(rad(start));
    const y1 = 60 + 52 * Math.sin(rad(start));
    const x2 = 60 + 52 * Math.cos(rad(angle));
    const y2 = 60 + 52 * Math.sin(rad(angle));
    return (
      <path key={point.rowId}
            d={`M 60 60 L ${x1.toFixed(2)} ${y1.toFixed(2)} A 52 52 0 ${
              sweep > 180 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`}
            fill={tones[index % tones.length]}>
        <title>{`${point.label}: ${point.display}`}</title>
      </path>
    );
  });
  return (
    <div data-testid={hole > 0 ? "v4-chart-donut" : "v4-chart-pie"}
         className="flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 120 120" className="h-32 w-32" role="img">
        {arcs}
        {hole > 0 ? (
          <circle cx="60" cy="60" r={52 * hole} fill="#ffffff" />
        ) : null}
      </svg>
      <ul className="space-y-1 text-xs text-slate-600">
        {data.points.map((point, index) => (
          <li key={point.rowId} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm"
                  style={{ backgroundColor: tones[index % tones.length] }} />
            <span className="truncate" dir="auto">{point.label}</span>
            <span className="tabular-nums text-slate-500">{point.display}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Counts per band, drawn touching.
 *
 * The gap between bars is what says "these categories are separate". A DPD
 * distribution has no gaps — 10-19 abuts 20-29 — and drawing one invites a
 * reader to see groups that are not there.
 */
function HistogramChart({ chart }: { chart: RenderedChart }) {
  const data = series(chart);
  if (!data) return null;
  const max = Math.max(...data.points.map((p) => Math.abs(p.value)), 0) || 1;
  return (
    <div data-testid="v4-chart-histogram"
         className="flex h-32 items-end gap-px">
      {data.points.map((point) => (
        <span key={point.rowId} className="flex-1"
              title={`${point.label}: ${point.display}`}>
          <span className="block w-full bg-slate-800"
                style={{ height: `${(Math.abs(point.value) / max) * 112}px` }} />
          <span className="block truncate pt-1 text-center text-[9px] text-slate-500">
            {point.label}
          </span>
        </span>
      ))}
    </div>
  );
}

/**
 * A bridge: each step starts where the last one finished.
 *
 * A waterfall is how a book explains a MOVEMENT — opening balance, new
 * lending, repayments, write-offs, closing balance. Drawn as ordinary bars
 * it becomes five unrelated quantities and the arithmetic that connects
 * them is invisible, which is exactly what `waterfall` did for the months
 * it was legal in the contract and fell through to `_bar_svg`.
 *
 * The last point is treated as a total and drawn from the baseline when it
 * equals the running sum; every other step floats.
 */
function WaterfallChart({ chart }: { chart: RenderedChart }) {
  const data = series(chart);
  if (!data) return null;
  // Running totals in an array, not a reassigned variable: the lint rule
  // that forbids the second one is right that a render body which mutates
  // its own scope can disagree with itself on a re-run.
  const cumulative = data.points.reduce<number[]>(
    (acc, point) => [...acc, acc[acc.length - 1] + point.value], [0]);
  const last = data.points[data.points.length - 1];
  // A LAST STEP THAT EQUALS EVERYTHING BEFORE IT IS THE TOTAL, not another
  // movement: "closing balance" is drawn from the baseline, or the bridge
  // ends with a bar that says the book doubled.
  const before = cumulative[cumulative.length - 2];
  const isTotal = Math.abs(before - last.value)
    <= Math.abs(last.value) * 1e-9;
  const steps = data.points.map((point, index) => (
    isTotal && index === data.points.length - 1
      ? { ...point, from: 0, to: point.value }
      : { ...point, from: cumulative[index], to: cumulative[index + 1] }));
  const floor = Math.min(0, ...steps.map((s) => Math.min(s.from, s.to)));
  const ceiling = Math.max(0, ...steps.map((s) => Math.max(s.from, s.to)));
  const span = ceiling - floor || 1;
  return (
    <ol data-testid="v4-chart-waterfall" className="space-y-1.5">
      {steps.map((step, index) => {
        const low = Math.min(step.from, step.to);
        const high = Math.max(step.from, step.to);
        const total = isTotal && index === steps.length - 1;
        return (
          <li key={step.rowId}
              className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3">
            <span className="truncate text-xs text-slate-700" dir="auto"
                  title={step.label}>{step.label}</span>
            <span className="relative block h-4 rounded-sm bg-slate-100">
              <span
                data-testid="v4-chart-waterfall-step"
                data-value={String(step.value)}
                className={`absolute h-4 rounded-sm ${
                  total ? "bg-slate-700"
                        : step.value >= 0 ? "bg-emerald-600" : "bg-rose-500"}`}
                style={{ left: `${((low - floor) / span) * 100}%`,
                         width: `${Math.max((high - low) / span, 0.004) * 100}%` }}
                title={`${step.label}: ${step.display}`}
              />
            </span>
            <span className="shrink-0 tabular-nums text-xs text-slate-600">
              {step.display}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Two measures and a third in the size of the mark.
 *
 * The form a concentration slide uses: exposure against delinquency rate,
 * with the bubble sized by account count, so a terrible rate over eleven
 * accounts does not read like a terrible rate over eleven thousand. Three
 * numbers per point is the whole reason to draw it, and it was rendering
 * as bars of the first one.
 */
function BubbleChart({ chart }: { chart: RenderedChart }) {
  const columns = chart.y_columns ?? [];
  const points = chart.points ?? [];
  if (columns.length < 2 || !points.length) return null;
  const [xColumn, yColumn, sizeColumn] = columns;
  const read = (column: string | undefined) => (column
    ? points.map((p) => numeric(p.values?.[column]) ?? 0) : []);
  const xs = read(xColumn);
  const ys = read(yColumn);
  const sizes = sizeColumn ? read(sizeColumn) : ys.map(() => 1);
  const place = (values: number[], value: number) => {
    const low = Math.min(...values, 0);
    const high = Math.max(...values, 0);
    return ((value - low) / ((high - low) || 1)) * 100;
  };
  const widest = Math.max(...sizes.map(Math.abs), 0) || 1;
  return (
    <div data-testid="v4-chart-bubble">
      <svg viewBox="0 0 100 100" className="h-48 w-full" role="img"
           aria-label={`${chart.title}. ${points.length} points.`}>
        {points.map((point, index) => (
          <circle key={point.row_id}
                  data-testid="v4-chart-bubble-mark"
                  cx={place(xs, xs[index])}
                  cy={100 - place(ys, ys[index])}
                  r={1.5 + (Math.abs(sizes[index]) / widest) * 7}
                  className="fill-sky-600/50 stroke-sky-700">
            <title>{`${text(point.label)}: ${
              columns.map((c) => text(point.display?.[c])).join(" / ")}`}</title>
          </circle>
        ))}
      </svg>
      <p className="mt-1 text-xs text-slate-500">
        {xColumn} against {yColumn}
        {sizeColumn ? `, sized by ${sizeColumn}` : ""}
      </p>
    </div>
  );
}

/**
 * A from/to result as a grid.
 *
 * NOT `analytics/charts.tsx#MatrixHeatmap`, which looks like the same
 * component and is not: it is hard-coded for row PERCENTAGES
 * (`value.toFixed(1)`, a `%` tooltip), so a migration counted in borrowers
 * renders as "100.0" and claims to be a percentage. It also formats in the
 * browser, which is the one thing the numeric contract forbids; takes a
 * single `categories` axis, so a sector-by-stage grid cannot be drawn; and
 * reads a missing cell as `?? 0`, asserting that nobody made a move the
 * query simply never reported.
 *
 * Every string here is the server's. The only arithmetic is the shade.
 */
function MatrixChart({ chart }: { chart: RenderedChart }) {
  const matrix = chart.matrix;
  if (!matrix?.rows?.length || !matrix.columns?.length) return null;
  const magnitudes = Object.values(matrix.cells ?? {})
    .filter((v): v is number => typeof v === "number")
    .map(Math.abs);
  const max = magnitudes.length ? Math.max(...magnitudes) : 0;

  return (
    <div data-testid="v4-chart-matrix" className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              {matrix.row_axis} \ {matrix.column_axis}
            </th>
            {matrix.columns.map((column) => (
              <th key={column}
                  className="px-1.5 py-1 text-center text-[10px] font-semibold text-slate-500">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row) => (
            <tr key={row}>
              <th className="px-2 py-1 text-left text-[10px] font-semibold text-slate-500">
                {row}
              </th>
              {matrix.columns.map((column) => {
                const key = `${row}|${column}`;
                const value = matrix.cells?.[key];
                const shown = matrix.display?.[key];
                const has = typeof value === "number";
                const weight = has && max > 0 ? Math.abs(value) / max : 0;
                const diagonal = matrix.square && row === column;
                return (
                  <td
                    key={column}
                    data-testid="v4-matrix-cell"
                    data-cell={key}
                    data-empty={has ? undefined : "true"}
                    title={has ? `${row} → ${column}: ${shown}` : undefined}
                    className={[
                      "min-w-12 rounded-[3px] px-1.5 py-1.5 text-center",
                      "tabular-nums",
                      weight > 0.55 ? "text-white" : "text-slate-700",
                      diagonal ? "ring-1 ring-inset ring-sky-500" : "",
                    ].join(" ")}
                    style={{
                      backgroundColor: has
                        ? `rgba(15, 23, 42, ${(0.08 + 0.84 * weight).toFixed(3)})`
                        : "#f8fafc",
                    }}
                  >
                    {/* An empty cell is not a zero. */}
                    {has ? shown : "·"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Min, Q1, median, Q3, max — the five numbers, as computed by the server. */
function BoxChart({ chart }: { chart: RenderedChart }) {
  const boxes = chart.boxes ?? [];
  if (!boxes.length) return null;
  const numbers = boxes
    .flatMap((b) => [Number(b.minimum), Number(b.maximum)])
    .filter((n) => Number.isFinite(n));
  if (!numbers.length) return null;
  const top = Math.max(...numbers);
  const bottom = Math.min(...numbers);
  const span = top - bottom || 1;
  const place = (raw: string) => ((Number(raw) - bottom) / span) * 100;

  return (
    <ol data-testid="v4-chart-boxes" className="space-y-2">
      {boxes.map((box) => {
        const q1 = place(box.q1);
        const q3 = place(box.q3);
        return (
          <li key={box.label || "all"}
              className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3">
            <span className="truncate text-xs text-slate-700" dir="auto"
                  title={box.label}>
              {box.label || "All"}
            </span>
            <span data-testid="v4-box" data-label={box.label}
                  className="relative block h-5">
              <span className="absolute top-1/2 h-px bg-slate-300"
                    style={{
                      left: `${place(box.minimum)}%`,
                      width: `${place(box.maximum) - place(box.minimum)}%`,
                    }} />
              <span className="absolute top-0 h-5 rounded-sm border border-slate-800 bg-slate-800/15"
                    style={{
                      left: `${Math.min(q1, q3)}%`,
                      width: `${Math.max(Math.abs(q3 - q1), 0.5)}%`,
                    }} />
              <span data-testid="v4-box-median"
                    className="absolute top-0 h-5 w-0.5 bg-slate-900"
                    style={{ left: `${place(box.median)}%` }}
                    title={`median ${box.display?.median ?? ""}`} />
            </span>
            <span className="shrink-0 tabular-nums text-xs text-slate-600">
              {box.display?.median}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The form the analyst asked for, drawn as itself.
 *
 * THE KIND DECIDES, not the shape of the payload. This read
 * `y_columns.length > 1` FIRST, so any chart with two measures became a
 * stack whatever it said it was — a combo, a grouped comparison and a
 * bubble all rendered as stacked bars. The count of series is a fallback
 * for a kind nobody recognises, not a rule that outranks the contract.
 */
export const CHART_BODIES: Record<
  ChartKind,
  (chart: RenderedChart) => React.ReactElement | null
> = {
  heatmap: (chart) => <MatrixChart chart={chart} />,
  box: (chart) => <BoxChart chart={chart} />,
  line: (chart) => <LineChart chart={chart} />,
  step_line: (chart) => <LineChart chart={chart} variant="step_line" />,
  area: (chart) => <LineChart chart={chart} variant="area" />,
  scatter: (chart) => <LineChart chart={chart} variant="scatter" />,
  stacked_bar: (chart) => <StackedBarChart chart={chart} normalise={false} />,
  stacked_bar_100: (chart) => <StackedBarChart chart={chart} />,
  grouped_bar: (chart) => <GroupedBarChart chart={chart} />,
  combo: (chart) => <ComboChart chart={chart} />,
  pie: (chart) => <SliceChart chart={chart} hole={0} />,
  donut: (chart) => <SliceChart chart={chart} hole={0.55} />,
  histogram: (chart) => <HistogramChart chart={chart} />,
  bubble: (chart) => <BubbleChart chart={chart} />,
  waterfall: (chart) => <WaterfallChart chart={chart} />,
  bar: (chart) => <BarChart chart={chart} />,
};

export function ResultChart({ chart }: { chart: RenderedChart }) {
  const draw = CHART_BODIES[chart.kind as ChartKind];
  const body = draw
    ? draw(chart)
    : (chart.y_columns ?? []).length > 1
      ? <StackedBarChart chart={chart} />
      : <BarChart chart={chart} />;
  if (!body) return null;
  const unit =
    chart.matrix?.unit ||
    chart.boxes?.[0]?.unit ||
    chart.unit ||
    Object.values(chart.series_units ?? {})[0] ||
    "";
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
  const { usefulCharts, usefulTables } = choose(tables, charts);
  if (!usefulCharts.length && !usefulTables.length) return null;

  // EVERY CHART, ONE AFTER ANOTHER, and the tables below them.
  //
  // This was one chart and one table, mutually exclusive behind a toggle.
  // Two things were wrong with it. An answer that draws a trend per product
  // showed one product, silently — the rest were computed, validated,
  // rendered and dropped a line before the screen. And a reader who wanted
  // the numbers under the picture had to give up the picture to get them,
  // which is not a choice anybody wants to make about their own result.
  return (
    <div data-testid="v4-visuals" className="mt-4 space-y-5">
      {usefulCharts.map((chart, index) => (
        <ResultChart key={`${chart.artifact_id}-${chart.kind}-${index}`}
                     chart={chart} />
      ))}
      {usefulTables.map((table, index) => (
        <ResultTable key={`${table.artifact_id}-${index}`} table={table} />
      ))}
    </div>
  );
}
