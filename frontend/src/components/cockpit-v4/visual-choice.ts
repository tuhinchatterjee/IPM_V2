/**
 * What is worth showing, and how to read a value safely.
 *
 * Separate from the drawing because it is the part with rules in it. A chart
 * earns its place or it does not appear, and deciding that is logic a test
 * can hold; turning numbers into rectangles is not.
 */

import type { RenderedChart, RenderedTable } from "./client.ts";

/** How many rows a table shows before a reader asks for the rest. §14, §41. */
export const TOP_N = 10;

/**
 * A number, or nothing.
 *
 * A null is NOT zero, and `Number(null)` is 0 -- which would plot a cell
 * nobody computed as a bar of height zero, indistinguishable from a real
 * one. An empty string and a boolean convert just as cheerfully, and none of
 * the three is a measurement.
 */
export function numeric(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * Whether a chart is worth drawing at all.
 *
 * §13 and §42: one point is a number and a chart of it is decoration; no
 * points is an empty frame, which reads as missing data rather than as no
 * data. §40 is the same rule from the other side -- an analysis that
 * returned nothing says so in words.
 */
export function chartIsUseful(chart: RenderedChart | undefined): boolean {
  if (!chart) return false;
  const columns = chart.y_columns ?? [];
  if (!columns.length) return false;
  const points = chart.points ?? [];
  if (points.length < 2) return false;
  return points.some((p) => numeric(p.values?.[columns[0]]) !== null);
}

/** Whether a table has anything in it. An empty one is said in words. */
export function tableIsUseful(table: RenderedTable | undefined): boolean {
  return Boolean(table && (table.rows ?? []).length > 0);
}

/**
 * What to show, and whether a toggle is worth offering.
 *
 * §21: a disabled Chart button beside a table that could never be charted is
 * a control that exists to be refused.
 */
export function choose(
  tables: RenderedTable[],
  charts: RenderedChart[],
): { chart?: RenderedChart; table?: RenderedTable; both: boolean } {
  const chart = charts.find((c) => chartIsUseful(c));
  const table = tables.find((t) => tableIsUseful(t));
  return { chart, table, both: Boolean(chart && table) };
}
