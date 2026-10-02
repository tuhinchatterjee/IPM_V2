"use client";

/**
 * The governed latest-period data grid.
 *
 * Server-side everything: filters, sort and paging are sent to
 * `/workspace/grid/query`, which answers one page plus the COMPLETE filtered
 * population's counts, EAD, ECL and stage mix. The browser never holds the
 * book. Every visible column has a filter control fitted to its kind
 * (text / category / range / boolean / empty-or-not).
 *
 * Selection is explicit about what it means:
 *   * rows     -- the exact exposures ticked (any page);
 *   * filtered -- "select all N filtered": the whole filtered population,
 *                 carried as the FILTERS, not as the rows on screen (GRID17).
 */

import * as React from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Filter as FilterIcon, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { count, moneyColumn, pct, pctPoints, sar } from "@/lib/viz/format";
import {
  downloadGridCsv,
  gridValues,
  queryGrid,
  readGridSchema,
  type GridColumn,
  type GridPage,
  type GridSchema,
} from "@/lib/workspace/guided";
import type { DomainId, Filter } from "@/lib/workspace/objects";
import { cn } from "@/lib/utils";

export interface GridSelection {
  mode: "none" | "rows" | "filtered";
  ids: string[];
  filters: Filter[];
  count: number;
  owner?: string;
  key?: string;
}

export function selectionFilters(selection: GridSelection): Filter[] {
  if (selection.mode === "filtered") return selection.filters;
  if (selection.mode === "rows" && selection.key) {
    return [{ column: selection.key, op: "in", values: selection.ids }];
  }
  return [];
}

function unitSuffix(col: GridColumn): string {
  switch (col.unit) {
    case "SAR_mn":
      return "";
    case "fraction":
    case "pct_points":
      return " (%)";
    case "days":
      return " (days)";
    case "months":
      return " (months)";
    default:
      return "";
  }
}

function formatCell(col: GridColumn, value: unknown, money?: (v: number) => string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value !== "number") return String(value);
  switch (col.unit) {
    case "SAR_mn":
      return money ? money(value) : sar(value);
    case "fraction":
      return pct(value);
    case "pct_points":
      return pctPoints(value, 1);
    case "count":
    case "days":
    case "months":
      return col.type === "flag" ? (value ? "Yes" : "No") : count(value);
    default:
      return Number.isInteger(value) ? count(value) : value.toFixed(2);
  }
}

function describeFilter(f: Filter, cols: GridColumn[]): string {
  const label = cols.find((c) => c.key === f.column)?.label ?? f.column;
  switch (f.op) {
    case "in":
      return `${label}: ${(f.values ?? []).slice(0, 3).join(", ")}${(f.values ?? []).length > 3 ? ` +${(f.values ?? []).length - 3}` : ""}`;
    case "between":
      return `${label}: ${f.values?.[0] ?? "…"} – ${f.values?.[1] ?? "…"}`;
    case "contains":
      return `${label} contains “${f.value}”`;
    case "is_null":
      return `${label} is empty`;
    case "not_null":
      return `${label} is not empty`;
    case "is_true":
      return `${label}: yes`;
    case "is_false":
      return `${label}: no`;
    default:
      return `${label} ${f.op} ${f.value}`;
  }
}

/** Range inputs for a fraction column are typed in percent and sent as a fraction. */
function toServer(col: GridColumn, raw: string): number | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  return col.unit === "fraction" ? n / 100 : n;
}

function FilterEditor({
  col,
  domain,
  current,
  onApply,
  onClose,
}: {
  col: GridColumn;
  domain: DomainId;
  current?: Filter;
  onApply: (f: Filter | null) => void;
  onClose: () => void;
}) {
  const [text, setText] = React.useState(current?.op === "contains" ? String(current.value ?? "") : "");
  const [picked, setPicked] = React.useState<string[]>(
    current?.op === "in" ? (current.values ?? []).map(String) : [],
  );
  const [values, setValues] = React.useState<{ value: string | number | null; count: number }[]>([]);
  const [search, setSearch] = React.useState("");
  const [low, setLow] = React.useState("");
  const [high, setHigh] = React.useState("");
  const [bool, setBool] = React.useState<"any" | "yes" | "no">("any");
  const [nulls, setNulls] = React.useState<"any" | "empty" | "not_empty">("any");

  React.useEffect(() => {
    if (col.filter !== "category") return;
    const t = setTimeout(() => {
      gridValues(domain, col.key, search)
        .then((r) => setValues(r.values))
        .catch(() => setValues([]));
    }, 200);
    return () => clearTimeout(t);
  }, [col, domain, search]);

  function apply() {
    if (nulls !== "any") return onApply({ column: col.key, op: nulls === "empty" ? "is_null" : "not_null" });
    if (col.filter === "text") return onApply(text.trim() ? { column: col.key, op: "contains", value: text.trim() } : null);
    if (col.filter === "category") {
      if (!picked.length) return onApply(null);
      const typed = picked.map((p) => {
        const match = values.find((v) => String(v.value) === p);
        return typeof match?.value === "number" ? match.value : p;
      });
      return onApply({ column: col.key, op: "in", values: typed });
    }
    if (col.filter === "boolean") {
      if (bool === "any") return onApply(null);
      return onApply({ column: col.key, op: "eq", value: bool === "yes" ? 1 : 0 });
    }
    const lo = toServer(col, low);
    const hi = toServer(col, high);
    if (lo === null && hi === null) return onApply(null);
    return onApply({ column: col.key, op: "between", values: [lo, hi] });
  }

  return (
    <div
      role="dialog"
      aria-label={`Filter ${col.label}`}
      className="absolute left-0 top-full z-30 mt-1 w-64 rounded-md border border-border bg-surface-raised p-3 text-xs shadow-lg"
      data-testid={`grid-filter-editor-${col.key}`}
    >
      <p className="mb-2 font-medium text-text-primary">{col.label}</p>
      <p className="mb-2 text-text-muted">{col.description}</p>
      {col.filter === "text" && (
        <input
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="contains…"
          aria-label={`${col.label} contains`}
          className="w-full rounded border border-border bg-surface px-2 py-1"
          onKeyDown={(e) => e.key === "Enter" && apply()}
        />
      )}
      {col.filter === "category" && (
        <div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="search values"
            aria-label={`Search ${col.label} values`}
            className="mb-2 w-full rounded border border-border bg-surface px-2 py-1"
          />
          <div className="max-h-48 space-y-0.5 overflow-auto">
            {values.map((v) => {
              const key = String(v.value);
              return (
                <label key={key} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={picked.includes(key)}
                    onChange={(e) =>
                      setPicked((prev) => (e.target.checked ? [...prev, key] : prev.filter((p) => p !== key)))
                    }
                  />
                  <span className="flex-1 truncate">{v.value === null ? "(empty)" : key}</span>
                  <span className="text-text-muted tabular">{count(v.count)}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}
      {col.filter === "range" && (
        <div className="flex items-center gap-2">
          <input
            value={low}
            onChange={(e) => setLow(e.target.value)}
            placeholder={col.unit === "fraction" ? "min %" : "min"}
            aria-label={`${col.label} minimum`}
            className="w-full rounded border border-border bg-surface px-2 py-1"
            inputMode="decimal"
          />
          <span>–</span>
          <input
            value={high}
            onChange={(e) => setHigh(e.target.value)}
            placeholder={col.unit === "fraction" ? "max %" : "max"}
            aria-label={`${col.label} maximum`}
            className="w-full rounded border border-border bg-surface px-2 py-1"
            inputMode="decimal"
          />
        </div>
      )}
      {col.filter === "boolean" && (
        <select
          value={bool}
          onChange={(e) => setBool(e.target.value as "any" | "yes" | "no")}
          aria-label={`${col.label} value`}
          className="w-full rounded border border-border bg-surface px-2 py-1"
        >
          <option value="any">any</option>
          <option value="yes">yes</option>
          <option value="no">no</option>
        </select>
      )}
      <label className="mt-2 flex items-center gap-2 text-text-muted">
        Empty values
        <select
          value={nulls}
          onChange={(e) => setNulls(e.target.value as "any" | "empty" | "not_empty")}
          aria-label={`${col.label} empty values`}
          className="rounded border border-border bg-surface px-1 py-0.5"
        >
          <option value="any">any</option>
          <option value="empty">only empty</option>
          <option value="not_empty">not empty</option>
        </select>
      </label>
      <div className="mt-3 flex justify-end gap-2">
        <button type="button" onClick={() => onApply(null)} className="rounded border border-border px-2 py-1">
          Clear
        </button>
        <button type="button" onClick={onClose} className="rounded border border-border px-2 py-1">
          Cancel
        </button>
        <button
          type="button"
          onClick={apply}
          className="rounded bg-accent px-2 py-1 font-medium text-accent-contrast"
          data-testid={`grid-filter-apply-${col.key}`}
        >
          Apply
        </button>
      </div>
    </div>
  );
}

export interface DataGridProps {
  domain: DomainId;
  initialFilters?: Filter[];
  /** Filters the reader cannot remove (e.g. an issue's population). */
  lockedFilters?: Filter[];
  selectable?: boolean;
  onSelection?: (selection: GridSelection, page: GridPage | null) => void;
  onFiltersChange?: (filters: Filter[]) => void;
  pageSize?: number;
  testId?: string;
  compact?: boolean;
  /** Bump to force a re-query (e.g. after clearing selection upstream). */
  refreshKey?: number;
  /** Bump to clear the selection from outside (the page's Clear button). */
  selectionResetKey?: number;
}

export function DataGrid({
  domain,
  initialFilters = [],
  lockedFilters = [],
  selectable = false,
  onSelection,
  onFiltersChange,
  pageSize = 50,
  testId = "data-grid",
  compact = false,
  refreshKey = 0,
  selectionResetKey = 0,
}: DataGridProps) {
  const [schema, setSchema] = React.useState<GridSchema | null>(null);
  const [filters, setFilters] = React.useState<Filter[]>(initialFilters);
  const [sort, setSort] = React.useState("ecl_sar_mn");
  const [desc, setDesc] = React.useState(true);
  const [offset, setOffset] = React.useState(0);
  const [page, setPage] = React.useState<GridPage | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [editing, setEditing] = React.useState<string>("");
  const [hidden, setHidden] = React.useState<Set<string>>(new Set());
  const [selection, setSelection] = React.useState<GridSelection>({ mode: "none", ids: [], filters: [], count: 0 });

  // A new book or a new drill resets the grid DURING render (React's
  // "adjusting state when a prop changes"), not in an effect that would paint
  // one stale frame first.
  const filterKey = JSON.stringify(initialFilters);
  const [shownFor, setShownFor] = React.useState({ domain, filterKey });
  const [resetFor, setResetFor] = React.useState(selectionResetKey);
  if (resetFor !== selectionResetKey) {
    setResetFor(selectionResetKey);
    setSelection({ mode: "none", ids: [], filters: [], count: 0 });
  }
  if (shownFor.domain !== domain || shownFor.filterKey !== filterKey) {
    if (shownFor.domain !== domain) {
      // The other book's rows must not render against a missing schema:
      // that keyed every row "undefined" (VAL-DEF-005) and let select-page
      // act on wrong ids.
      setSchema(null);
      setPage(null);
      setSelection({ mode: "none", ids: [], filters: [], count: 0 });
    }
    setShownFor({ domain, filterKey });
    setFilters(initialFilters);
    setOffset(0);
  }

  React.useEffect(() => {
    readGridSchema(domain)
      .then((s) => {
        setSchema(s);
        setHidden(new Set(s.columns.filter((c) => !c.visible).map((c) => c.key)));
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [domain]);

  // Keyed by CONTENT: a parent that re-renders with an equal (but new) locked
  // filter array must not restart -- and abort -- the page query.
  const lockedKey = JSON.stringify(lockedFilters);
  const effective = React.useMemo(
    () => [...(JSON.parse(lockedKey) as Filter[]), ...filters],
    [lockedKey, filters],
  );

  React.useEffect(() => {
    if (!schema) return;
    const controller = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      queryGrid({ domain, filters: effective, sort, desc, offset, limit: pageSize }, controller.signal)
        .then((p) => {
          setPage(p);
          setError("");
        })
        .catch((e: unknown) => {
          if ((e as { name?: string })?.name !== "AbortError") setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => setLoading(false));
    }, 180);
    return () => {
      clearTimeout(t);
      controller.abort();
    };
  }, [schema, domain, effective, sort, desc, offset, pageSize, refreshKey]);

  React.useEffect(() => {
    onFiltersChange?.(effective);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(effective)]);

  React.useEffect(() => {
    onSelection?.(selection, page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, page?.total]);

  const columns = (schema?.columns ?? []).filter((c) => !hidden.has(c.key));
  const moneyFormats = React.useMemo(() => {
    const out: Record<string, { header: string; cells: string[] }> = {};
    if (!page) return out;
    for (const c of columns) {
      if (c.unit !== "SAR_mn") continue;
      const col = moneyColumn(page.rows.map((r) => (typeof r[c.key] === "number" ? (r[c.key] as number) : null)));
      out[c.key] = { header: col.header, cells: col.cells };
    }
    return out;
  }, [page, columns]);

  function setFilter(col: string, f: Filter | null) {
    setFilters((prev) => [...prev.filter((p) => p.column !== col), ...(f ? [f] : [])]);
    setOffset(0);
    setEditing("");
    if (selection.mode === "filtered") setSelection({ mode: "none", ids: [], filters: [], count: 0 });
  }

  const key = schema?.key ?? "";
  // Rows are shown only with the schema that names their key.
  const rows = schema && page ? page.rows : [];
  const pageIds = rows.map((r) => String(r[key]));
  const allPageSelected = selection.mode === "rows" && pageIds.every((id) => selection.ids.includes(id)) && pageIds.length > 0;

  function toggleRow(id: string) {
    setSelection((prev) => {
      const base = prev.mode === "rows" ? prev.ids : [];
      const ids = base.includes(id) ? base.filter((x) => x !== id) : [...base, id].slice(0, 500);
      return ids.length
        ? { mode: "rows", ids, filters: [], count: ids.length, key, owner: schema?.owner }
        : { mode: "none", ids: [], filters: [], count: 0 };
    });
  }

  function togglePage() {
    setSelection((prev) => {
      const base = prev.mode === "rows" ? prev.ids : [];
      const ids = allPageSelected ? base.filter((x) => !pageIds.includes(x)) : Array.from(new Set([...base, ...pageIds])).slice(0, 500);
      return ids.length
        ? { mode: "rows", ids, filters: [], count: ids.length, key, owner: schema?.owner }
        : { mode: "none", ids: [], filters: [], count: 0 };
    });
  }

  function selectAllFiltered() {
    if (!page) return;
    setSelection({ mode: "filtered", ids: [], filters: effective, count: page.total, key, owner: schema?.owner });
  }

  if (error && !schema) {
    return (
      <p role="alert" className="text-sm text-negative" data-testid={`${testId}-error`}>
        {error}
      </p>
    );
  }

  const totalPages = page ? Math.max(1, Math.ceil(page.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;

  return (
    <div className="space-y-2" data-testid={testId} data-total={page?.total ?? ""}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {lockedFilters.map((f) => (
          <Badge key={`lock-${f.column}`} variant="info">
            {describeFilter(f, schema?.columns ?? [])} (locked)
          </Badge>
        ))}
        {filters.map((f) => (
          <span key={f.column} className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-sunken px-2 py-0.5" data-testid="grid-filter-chip">
            {describeFilter(f, schema?.columns ?? [])}
            <button type="button" aria-label={`Remove filter on ${f.column}`} onClick={() => setFilter(f.column, null)}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {filters.length > 0 && (
          <button type="button" onClick={() => setFilters([])} className="text-accent underline">
            Clear all filters
          </button>
        )}
        <span className="ml-auto text-text-muted">
          {page ? `${count(page.total)} ${schema?.grain_plural ?? "rows"} · ${page.period} · ${page.server_ms} ms` : "…"}
        </span>
        <details className="relative">
          <summary className="cursor-pointer rounded border border-border px-2 py-0.5">Columns</summary>
          <div className="absolute right-0 z-30 mt-1 max-h-72 w-56 overflow-auto rounded-md border border-border bg-surface-raised p-2 shadow-lg">
            {(schema?.columns ?? []).map((c) => (
              <label key={c.key} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={!hidden.has(c.key)}
                  onChange={() =>
                    setHidden((prev) => {
                      const next = new Set(prev);
                      if (next.has(c.key)) next.delete(c.key);
                      else next.add(c.key);
                      return next;
                    })
                  }
                />
                {c.label}
              </label>
            ))}
          </div>
        </details>
        <button
          type="button"
          onClick={() => void downloadGridCsv(domain, effective).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5"
          data-testid={`${testId}-export`}
        >
          <Download className="h-3 w-3" /> Export filtered
        </button>
      </div>
      {selectable && page && (
        <div className="flex flex-wrap items-center gap-2 text-xs" data-testid={`${testId}-selection-bar`}>
          <button type="button" onClick={selectAllFiltered} className="rounded border border-border px-2 py-0.5" data-testid={`${testId}-select-all-filtered`}>
            Select all {count(page.total)} filtered
          </button>
          {selection.mode !== "none" && (
            <>
              <Badge variant="accent" data-testid={`${testId}-selection-count`}>
                {selection.mode === "filtered"
                  ? `All ${count(selection.count)} filtered ${schema?.grain_plural ?? "rows"} selected`
                  : `${count(selection.count)} selected`}
              </Badge>
              <button
                type="button"
                onClick={() => setSelection({ mode: "none", ids: [], filters: [], count: 0 })}
                className="text-accent underline"
                data-testid={`${testId}-clear-selection`}
              >
                Clear selection
              </button>
            </>
          )}
        </div>
      )}
      <div className={cn("overflow-auto rounded-md border border-border", compact ? "max-h-80" : "max-h-[34rem]")}>
        <table className="w-full min-w-max text-xs">
          <thead className="sticky top-0 z-20 bg-surface-sunken">
            <tr>
              {selectable && (
                <th className="px-2 py-1.5">
                  <input type="checkbox" aria-label="Select this page" checked={allPageSelected} onChange={togglePage} data-testid={`${testId}-select-page`} />
                </th>
              )}
              {columns.map((c) => {
                const active = filters.find((f) => f.column === c.key) || lockedFilters.find((f) => f.column === c.key);
                const money = moneyFormats[c.key]?.header ?? "";
                return (
                  <th key={c.key} className="relative whitespace-nowrap px-2 py-1.5 text-left font-medium text-text-secondary" title={`${c.description}${c.unit === "SAR_mn" ? " Values in SAR million (raw on export)." : ""}`}>
                    <span className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          if (sort === c.key) setDesc((d) => !d);
                          else {
                            setSort(c.key);
                            setDesc(true);
                          }
                        }}
                        className="hover:text-text-primary"
                        aria-label={`Sort by ${c.label}`}
                        data-testid={`grid-sort-${c.key}`}
                      >
                        {c.label}
                        {c.unit === "SAR_mn" ? ` ${money || "(SAR m)"}` : unitSuffix(c)}
                      </button>
                      {sort === c.key && (desc ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
                      <button
                        type="button"
                        aria-label={`Filter ${c.label}`}
                        onClick={() => setEditing(editing === c.key ? "" : c.key)}
                        className={cn("rounded p-0.5", active ? "text-accent" : "text-text-muted hover:text-text-primary")}
                        data-testid={`grid-filter-${c.key}`}
                      >
                        <FilterIcon className="h-3 w-3" />
                      </button>
                    </span>
                    {editing === c.key && (
                      <FilterEditor
                        col={c}
                        domain={domain}
                        current={filters.find((f) => f.column === c.key)}
                        onApply={(f) => setFilter(c.key, f)}
                        onClose={() => setEditing("")}
                      />
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className={cn(loading && "opacity-60")}>
            {rows.map((row, i) => {
              const id = row[key] != null ? String(row[key]) : `row-${offset + i}`;
              const checked = selection.mode === "filtered" || (selection.mode === "rows" && selection.ids.includes(id));
              return (
                <tr key={id} className={cn("border-t border-border", checked && "bg-accent-muted")} data-testid="grid-row" data-row-id={id}>
                  {selectable && (
                    <td className="px-2 py-1">
                      <input
                        type="checkbox"
                        aria-label={`Select ${id}`}
                        checked={checked}
                        disabled={selection.mode === "filtered"}
                        onChange={() => toggleRow(id)}
                      />
                    </td>
                  )}
                  {columns.map((c) => (
                    <td key={c.key} className={cn("whitespace-nowrap px-2 py-1", c.type !== "string" ? "text-right tabular" : "")} title={typeof row[c.key] === "number" ? String(row[c.key]) : undefined}>
                      {c.unit === "SAR_mn" && moneyFormats[c.key]
                        ? moneyFormats[c.key].cells[i]
                        : formatCell(c, row[c.key])}
                    </td>
                  ))}
                </tr>
              );
            })}
            {page && page.rows.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="p-4 text-center text-text-muted" data-testid={`${testId}-empty-by-filter`}>
                  No {schema?.grain_plural ?? "rows"} match these filters (EMPTY_BY_FILTER). Clear a filter to widen.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>
          Page {currentPage} of {totalPages} · {pageSize} per page · sorted by {sort} {desc ? "↓" : "↑"}
        </span>
        <span className="flex gap-1">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))} className="rounded border border-border p-1 disabled:opacity-40" aria-label="Previous page" data-testid={`${testId}-prev`}>
            <ChevronLeft className="h-3 w-3" />
          </button>
          <button type="button" disabled={currentPage >= totalPages} onClick={() => setOffset(offset + pageSize)} className="rounded border border-border p-1 disabled:opacity-40" aria-label="Next page" data-testid={`${testId}-next`}>
            <ChevronRight className="h-3 w-3" />
          </button>
        </span>
      </div>
      {error && schema && (
        <p role="alert" className="text-xs text-negative">
          {error}
        </p>
      )}
    </div>
  );
}
