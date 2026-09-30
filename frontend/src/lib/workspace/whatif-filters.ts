/**
 * The What-If explorer's cross-filter rules, pure (no React, no fetch): a
 * chart click or box/lasso selection becomes a governed grid filter, and the
 * grid's filters are what the charts are drawn from. One state, two views.
 */

import type { DomainId, Filter } from "./objects.ts";

/** Dimensions the explorer can break the book down by, per book. */
export const EXPLORER_DIMENSIONS: Record<DomainId, { key: string; label: string }[]> = {
  corporate: [
    { key: "sector", label: "Sector" },
    { key: "rating_current", label: "Rating" },
    { key: "stage", label: "Stage" },
    { key: "region", label: "Region" },
    { key: "product_type", label: "Product" },
    { key: "ews_band", label: "EWS band" },
  ],
  retail: [
    { key: "product", label: "Product" },
    { key: "score_band", label: "Score band" },
    { key: "delinquency_bucket", label: "Delinquency" },
    { key: "region", label: "Region" },
    { key: "employment_type", label: "Employment" },
    { key: "ews_band", label: "EWS band" },
  ],
};

/**
 * A chart click becomes a governed filter: toggling a value in an `in`
 * filter on that column, and removing the filter when it empties. Pure, so
 * the cross-filter rule is unit-tested rather than inferred from a click.
 */
export function toggleFilterValue(filters: Filter[], column: string, value: string | number): Filter[] {
  const current = filters.find((f) => f.column === column && f.op === "in");
  const others = filters.filter((f) => !(f.column === column && f.op === "in"));
  const values = (current?.values ?? []) as (string | number)[];
  const has = values.some((v) => String(v) === String(value));
  const next = has ? values.filter((v) => String(v) !== String(value)) : [...values, value];
  return next.length ? [...others, { column, op: "in", values: next }] : others;
}

/** Replace a column's values from a box/lasso selection. */
export function setFilterValues(filters: Filter[], column: string, values: (string | number)[]): Filter[] {
  const others = filters.filter((f) => !(f.column === column && f.op === "in"));
  return values.length ? [...others, { column, op: "in", values }] : others;
}

/** The values a column is currently filtered to (for chart highlighting). */
export function selectedValues(filters: Filter[], column: string): (string | number)[] {
  const f = filters.find((x) => x.column === column && x.op === "in");
  return (f?.values ?? []) as (string | number)[];
}

/** The two-dimension views per book: a heatmap and a stage-migration flow. */
export const EXPLORER_MATRICES: Record<DomainId, { x: string; xLabel: string; y: string; yLabel: string }> = {
  corporate: { x: "sector", xLabel: "Sector", y: "rating_current", yLabel: "Rating" },
  retail: { x: "product", xLabel: "Product", y: "score_band", yLabel: "Score band" },
};

const NUMERIC_COLUMNS = new Set(["stage", "prior_stage"]);

/**
 * A heatmap cell or a flow link narrows to BOTH of its coordinates; the same
 * click again (already narrowed to exactly that cell) clears them. A
 * "(none)" coordinate -- a new exposure with no prior stage -- is not a
 * filterable value and leaves that column alone.
 */
export function cellFilter(
  filters: Filter[],
  cell: { column: string; value: string | number | null }[],
): Filter[] {
  const coords = cell
    .filter((c) => c.value !== null && c.value !== undefined && c.value !== "(none)")
    .map((c) => ({ column: c.column, value: NUMERIC_COLUMNS.has(c.column) ? Number(c.value) : String(c.value) }));
  const already = coords.length > 0 && coords.every((c) => {
    const v = selectedValues(filters, c.column);
    return v.length === 1 && String(v[0]) === String(c.value);
  });
  return coords.reduce((acc, c) => setFilterValues(acc, c.column, already ? [] : [c.value]), filters);
}
