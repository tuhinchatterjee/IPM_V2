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
