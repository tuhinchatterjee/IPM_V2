"use client";

import * as React from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Copy,
  Download,
  Filter,
  Lock,
  Rows3,
  Search,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type ColumnProfile,
  type DatasetField,
  type DatasetPage,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * The dataset grid.
 *
 * People arriving from Excel and SAS expect a grid to behave: a header that
 * stays put, key columns that do not scroll away, columns you can widen, hide,
 * sort and filter, and a way to get the thing you are looking at out of the
 * product. Anything less and a data steward will export to CSV and work
 * somewhere else, which defeats the point of governing the data here.
 *
 * What it deliberately does NOT do is load the dataset. Fifteen thousand rows
 * in a browser is a hang, not a feature, so every one of those operations is a
 * request: page, sort, filter and search all happen on the server, against the
 * governed catalogue. The grid holds one page at a time and never more.
 *
 * Nor is it a query surface. A filter is `field:operator:value` where the field
 * must be in the data dictionary and the operator is one of nine; the value is
 * compared, never concatenated. The backend refuses anything else and says
 * which part it refused.
 */

const PAGE_SIZES = [50, 100, 250] as const;

/** The comparisons the backend offers, in the order a person reaches for them. */
const OPERATORS: { id: string; label: string; takesValue: boolean }[] = [
  { id: "eq", label: "is", takesValue: true },
  { id: "ne", label: "is not", takesValue: true },
  { id: "contains", label: "contains", takesValue: true },
  { id: "gt", label: "greater than", takesValue: true },
  { id: "gte", label: "at least", takesValue: true },
  { id: "lt", label: "less than", takesValue: true },
  { id: "lte", label: "at most", takesValue: true },
  { id: "blank", label: "is blank", takesValue: false },
  { id: "present", label: "is not blank", takesValue: false },
];

const DEFAULT_WIDTH = 148;
const MIN_WIDTH = 72;

export interface GridState {
  period: string | null;
  offset: number;
  limit: number;
  sort: string | null;
  descending: boolean;
  search: string;
  filters: string[];
  hidden: string[];
  frozen: number;
  dense: boolean;
}

export const INITIAL_GRID: GridState = {
  period: null,
  offset: 0,
  limit: 50,
  sort: null,
  descending: false,
  search: "",
  filters: [],
  hidden: [],
  // The first two columns are usually the key — the account and who it belongs
  // to — and are what you need still on screen when you scroll right.
  frozen: 2,
  dense: false,
};

/**
 * Keyed on the dataset, so choosing a different one starts a fresh grid.
 *
 * Column widths, hidden columns and filters all name fields of one dataset;
 * carrying them across to another would leave a filter on a column that is not
 * there. Remounting is the honest way to say "this is a different thing" — and
 * it beats an effect that resets six pieces of state on every change.
 */
export function DataGrid({ dataset }: { dataset: string }) {
  return <Grid_ key={dataset} dataset={dataset} />;
}

function Grid_({ dataset }: { dataset: string }) {
  const [state, setState] = React.useState<GridState>(INITIAL_GRID);
  const [draftSearch, setDraftSearch] = React.useState("");
  const [profiling, setProfiling] = React.useState<string | null>(null);
  const [widths, setWidths] = React.useState<Record<string, number>>({});
  const [panel, setPanel] = React.useState<"columns" | "filters" | null>(null);

  const page = useAsync(
    () =>
      api.datasetRows(dataset, {
        period: state.period ?? undefined,
        offset: state.offset,
        limit: state.limit,
        sort: state.sort ?? undefined,
        descending: state.descending,
        search: state.search || undefined,
        filters: state.filters,
      }),
    [
      dataset,
      state.period,
      state.offset,
      state.limit,
      state.sort,
      state.descending,
      state.search,
      state.filters,
    ],
  );

  const update = React.useCallback(
    (patch: Partial<GridState>, keepOffset = false) =>
      setState((s) => ({ ...s, ...patch, offset: keepOffset ? s.offset : 0 })),
    [],
  );

  if (page.loading && !page.data) return <Skeleton className="h-[32rem] w-full" />;
  if (page.error && !page.data) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {page.error}
      </Card>
    );
  }
  if (!page.data) return null;

  const data = page.data;
  const shown = data.fields.filter((f) => !state.hidden.includes(f.name));

  return (
    <div className="space-y-3">
      <Toolbar
        data={data}
        state={state}
        draftSearch={draftSearch}
        onDraftSearch={setDraftSearch}
        onUpdate={update}
        panel={panel}
        onPanel={setPanel}
        shownCount={shown.length}
      />

      {panel === "columns" && (
        <ColumnPanel
          fields={data.fields}
          hidden={state.hidden}
          frozen={state.frozen}
          onToggle={(name) =>
            update(
              {
                hidden: state.hidden.includes(name)
                  ? state.hidden.filter((h) => h !== name)
                  : [...state.hidden, name],
              },
              true,
            )
          }
          onFrozen={(frozen) => update({ frozen }, true)}
          onProfile={setProfiling}
        />
      )}

      {panel === "filters" && (
        <FilterPanel
          fields={data.fields}
          filters={state.filters}
          onChange={(filters) => update({ filters })}
        />
      )}

      <Grid
        data={data}
        shown={shown}
        state={state}
        widths={widths}
        onWidth={(name, width) =>
          setWidths((w) => ({ ...w, [name]: Math.max(MIN_WIDTH, width) }))
        }
        onSort={(column) =>
          update(
            state.sort === column
              ? { descending: !state.descending }
              : { sort: column, descending: false },
          )
        }
        onProfile={setProfiling}
        busy={page.loading}
      />

      <Footer data={data} state={state} onUpdate={update} />

      {profiling && (
        <ColumnDrawer
          dataset={dataset}
          field={profiling}
          period={data.period}
          onClose={() => setProfiling(null)}
          onFilter={(filter) => {
            update({ filters: [...state.filters, filter] });
            setProfiling(null);
          }}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ toolbar */

function Toolbar({
  data,
  state,
  draftSearch,
  onDraftSearch,
  onUpdate,
  panel,
  onPanel,
  shownCount,
}: {
  data: DatasetPage;
  state: GridState;
  draftSearch: string;
  onDraftSearch: (value: string) => void;
  onUpdate: (patch: Partial<GridState>, keepOffset?: boolean) => void;
  panel: "columns" | "filters" | null;
  onPanel: (panel: "columns" | "filters" | null) => void;
  shownCount: number;
}) {
  const exportHref = api.datasetExportUrl(data.dataset, {
    period: state.period ?? undefined,
    sort: state.sort ?? undefined,
    descending: state.descending,
    search: state.search || undefined,
    filters: state.filters,
  });

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <label className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-muted"
          aria-hidden
        />
        <input
          value={draftSearch}
          onChange={(e) => onDraftSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onUpdate({ search: draftSearch });
            if (e.key === "Escape") {
              onDraftSearch("");
              onUpdate({ search: "" });
            }
          }}
          onBlur={() => onUpdate({ search: draftSearch })}
          placeholder="Search these rows"
          aria-label="Search the rows shown"
          className="w-56 rounded-md border border-border bg-surface py-1.5 pl-8 pr-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
      </label>

      <Button
        variant={panel === "filters" ? "outline" : "ghost"}
        size="sm"
        onClick={() => onPanel(panel === "filters" ? null : "filters")}
      >
        <Filter aria-hidden />
        Filters{state.filters.length > 0 && ` (${state.filters.length})`}
      </Button>

      <Button
        variant={panel === "columns" ? "outline" : "ghost"}
        size="sm"
        onClick={() => onPanel(panel === "columns" ? null : "columns")}
      >
        <Columns3 aria-hidden />
        Columns ({shownCount}/{data.fields.length})
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => onUpdate({ dense: !state.dense }, true)}
        title={state.dense ? "More room per row" : "Fit more rows on screen"}
      >
        <Rows3 aria-hidden />
        {state.dense ? "Comfortable" : "Compact"}
      </Button>

      <div className="ml-auto flex items-center gap-1.5">
        {data.periods.length > 0 && (
          <select
            value={state.period ?? data.period ?? ""}
            onChange={(e) => onUpdate({ period: e.target.value })}
            aria-label="Reporting period"
            className="rounded-md border border-border bg-surface px-2 py-1.5 text-[13px] text-text-primary focus:border-accent focus:outline-none"
          >
            {data.periods.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        )}
        <Button variant="ghost" size="sm" asChild title="Download what is on screen">
          <a href={exportHref} download>
            <Download aria-hidden />
            Export
          </a>
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ column picker */

function ColumnPanel({
  fields,
  hidden,
  frozen,
  onToggle,
  onFrozen,
  onProfile,
}: {
  fields: DatasetField[];
  hidden: string[];
  frozen: number;
  onToggle: (name: string) => void;
  onFrozen: (frozen: number) => void;
  onProfile: (field: string) => void;
}) {
  return (
    <Card className="p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="meta text-text-muted">Columns</p>
        <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
          Keep
          <select
            value={frozen}
            onChange={(e) => onFrozen(Number(e.target.value))}
            className="rounded border border-border bg-surface px-1 py-0.5 text-[11px]"
            aria-label="Columns to keep on screen while scrolling"
          >
            {[0, 1, 2, 3].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          on screen while scrolling
        </label>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {fields.map((field) => {
          const on = !hidden.includes(field.name);
          return (
            <span
              key={field.name}
              className={cn(
                "flex items-center rounded-full border text-[11px] transition-colors",
                on
                  ? "border-accent/40 bg-accent-muted text-accent"
                  : "border-border bg-surface text-text-muted",
              )}
            >
              <button
                type="button"
                onClick={() => onToggle(field.name)}
                className="py-1 pl-2.5 pr-1"
                title={field.definition || field.name}
              >
                {field.business_name || field.name}
              </button>
              <button
                type="button"
                onClick={() => onProfile(field.name)}
                className="py-1 pl-0.5 pr-2 opacity-60 hover:opacity-100"
                title={`What is in ${field.business_name || field.name}?`}
              >
                <ChevronDown className="size-3" aria-hidden />
              </button>
            </span>
          );
        })}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------ filter panel */

function FilterPanel({
  fields,
  filters,
  onChange,
}: {
  fields: DatasetField[];
  filters: string[];
  onChange: (filters: string[]) => void;
}) {
  const [field, setField] = React.useState(fields[0]?.name ?? "");
  const [op, setOp] = React.useState("eq");
  const [value, setValue] = React.useState("");

  const takesValue = OPERATORS.find((o) => o.id === op)?.takesValue ?? true;

  function add() {
    if (!field) return;
    if (takesValue && !value.trim()) return;
    onChange([...filters, `${field}:${op}:${takesValue ? value.trim() : ""}`]);
    setValue("");
  }

  return (
    <Card className="space-y-2.5 p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <select
          value={field}
          onChange={(e) => setField(e.target.value)}
          aria-label="Column to filter on"
          className="rounded-md border border-border bg-surface px-2 py-1.5 text-[13px] text-text-primary focus:border-accent focus:outline-none"
        >
          {fields.map((f) => (
            <option key={f.name} value={f.name}>
              {f.business_name || f.name}
            </option>
          ))}
        </select>
        <select
          value={op}
          onChange={(e) => setOp(e.target.value)}
          aria-label="Comparison"
          className="rounded-md border border-border bg-surface px-2 py-1.5 text-[13px] text-text-primary focus:border-accent focus:outline-none"
        >
          {OPERATORS.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
        {takesValue && (
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="Value"
            aria-label="Value to compare against"
            className="w-40 rounded-md border border-border bg-surface px-2 py-1.5 text-[13px] text-text-primary focus:border-accent focus:outline-none"
          />
        )}
        <Button size="sm" variant="outline" onClick={add}>
          Add filter
        </Button>
      </div>

      {filters.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {filters.map((filter) => (
            <span
              key={filter}
              className="mono flex items-center gap-1 rounded-full border border-border bg-surface-sunken py-0.5 pl-2.5 pr-1 text-[11px] text-text-secondary"
            >
              {readable(filter, fields)}
              <button
                type="button"
                onClick={() => onChange(filters.filter((f) => f !== filter))}
                aria-label={`Remove filter ${filter}`}
                className="rounded-full p-0.5 hover:text-negative"
              >
                <X className="size-3" aria-hidden />
              </button>
            </span>
          ))}
          <button
            type="button"
            onClick={() => onChange([])}
            className="text-[11px] text-text-muted underline-offset-2 hover:text-accent hover:underline"
          >
            Clear all
          </button>
        </div>
      )}

      <p className="text-[11px] text-text-muted">
        Filters run on the server, against the governed dictionary. A column that
        is not in the dictionary, or a comparison that is not on this list, is
        refused — the grid is a viewer, not a query surface.
      </p>
    </Card>
  );
}

function readable(filter: string, fields: DatasetField[]): string {
  const [field, op, ...rest] = filter.split(":");
  const label =
    fields.find((f) => f.name === field)?.business_name || field || filter;
  const operator = OPERATORS.find((o) => o.id === op);
  if (!operator) return filter;
  return operator.takesValue
    ? `${label} ${operator.label} ${rest.join(":")}`
    : `${label} ${operator.label}`;
}

/* --------------------------------------------------------------- the table */

function Grid({
  data,
  shown,
  state,
  widths,
  onWidth,
  onSort,
  onProfile,
  busy,
}: {
  data: DatasetPage;
  shown: DatasetField[];
  state: GridState;
  widths: Record<string, number>;
  onWidth: (name: string, width: number) => void;
  onSort: (column: string) => void;
  onProfile: (field: string) => void;
  busy: boolean;
}) {
  const widthOf = (name: string) => widths[name] ?? DEFAULT_WIDTH;

  // A frozen column's left offset is the sum of the widths before it, which is
  // why widths live in state rather than being left to the browser.
  const offsets: number[] = [];
  let running = 0;
  for (const field of shown) {
    offsets.push(running);
    running += widthOf(field.name);
  }

  const rowPadding = state.dense ? "py-0.5" : "py-1.5";

  return (
    <Card className={cn("overflow-hidden", busy && "opacity-60")}>
      <div className="max-h-[62vh] overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-xs">
          <thead>
            <tr>
              {shown.map((field, index) => {
                const frozen = index < state.frozen;
                return (
                  <th
                    key={field.name}
                    style={{
                      width: widthOf(field.name),
                      minWidth: widthOf(field.name),
                      left: frozen ? offsets[index] : undefined,
                    }}
                    className={cn(
                      "sticky top-0 z-20 border-b border-r border-border bg-surface-sunken px-2.5 py-1.5 text-left align-bottom",
                      frozen && "z-30",
                    )}
                  >
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => onSort(field.name)}
                        title={
                          field.definition
                            ? `${field.definition}${field.unit ? ` (${field.unit})` : ""}`
                            : field.name
                        }
                        className={cn(
                          "flex min-w-0 flex-1 items-center gap-1 truncate text-left font-medium transition-colors hover:text-accent",
                          state.sort === field.name
                            ? "text-accent"
                            : "text-text-secondary",
                        )}
                      >
                        <span className="truncate">
                          {field.business_name || field.name}
                        </span>
                        {field.sensitivity === "confidential" && (
                          <Lock className="size-2.5 shrink-0" aria-hidden />
                        )}
                        {state.sort === field.name && (
                          <span aria-hidden>{state.descending ? "↓" : "↑"}</span>
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => onProfile(field.name)}
                        aria-label={`Profile ${field.business_name || field.name}`}
                        className="shrink-0 text-text-muted hover:text-accent"
                      >
                        <ChevronDown className="size-3" aria-hidden />
                      </button>
                    </div>
                    <p className="mono mt-0.5 truncate text-[9px] font-normal uppercase tracking-wider text-text-muted">
                      {field.data_type}
                      {field.unit ? ` · ${field.unit}` : ""}
                    </p>
                    <ResizeHandle
                      onResize={(delta) =>
                        onWidth(field.name, widthOf(field.name) + delta)
                      }
                    />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, i) => (
              <tr key={i} className="group">
                {shown.map((field, index) => {
                  const value = row[field.name];
                  const missing = value === null || value === undefined;
                  const frozen = index < state.frozen;
                  return (
                    <td
                      key={field.name}
                      onDoubleClick={() =>
                        void navigator.clipboard?.writeText(
                          missing ? "" : String(value),
                        )
                      }
                      title={missing ? "No value recorded" : String(value)}
                      style={{
                        width: widthOf(field.name),
                        minWidth: widthOf(field.name),
                        left: frozen ? offsets[index] : undefined,
                      }}
                      className={cn(
                        "truncate border-b border-r border-border px-2.5 group-hover:bg-surface-hover",
                        rowPadding,
                        frozen && "sticky z-10 bg-surface group-hover:bg-surface-hover",
                        typeof value === "number"
                          ? "mono text-right text-text-primary"
                          : "text-text-secondary",
                        missing && "text-text-muted",
                      )}
                    >
                      {missing ? "—" : String(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
            {data.rows.length === 0 && (
              <tr>
                <td
                  colSpan={shown.length}
                  className="px-4 py-10 text-center text-sm text-text-muted"
                >
                  Nothing matches. {data.filtered && "Try removing a filter."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="flex items-center gap-1.5 border-t border-border bg-surface-sunken px-3 py-1.5 text-[11px] text-text-muted">
        <Copy className="size-3" aria-hidden />
        Double-click a cell to copy it.
      </p>
    </Card>
  );
}

/** Drag the right edge of a header to widen or narrow the column. */
function ResizeHandle({ onResize }: { onResize: (delta: number) => void }) {
  const start = React.useRef<number | null>(null);

  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize column"
      onPointerDown={(e) => {
        start.current = e.clientX;
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (start.current === null) return;
        const delta = e.clientX - start.current;
        if (Math.abs(delta) < 4) return;
        start.current = e.clientX;
        onResize(delta);
      }}
      onPointerUp={() => {
        start.current = null;
      }}
      className="absolute inset-y-0 right-0 w-1.5 cursor-col-resize touch-none hover:bg-accent/40"
    />
  );
}

/* ------------------------------------------------------------------ footer */

function Footer({
  data,
  state,
  onUpdate,
}: {
  data: DatasetPage;
  state: GridState;
  onUpdate: (patch: Partial<GridState>, keepOffset?: boolean) => void;
}) {
  const from = data.total_rows === 0 ? 0 : data.offset + 1;
  const to = data.offset + data.returned;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-xs text-text-muted">
        {from.toLocaleString()}–{to.toLocaleString()} of{" "}
        <span className="text-text-secondary">
          {data.total_rows.toLocaleString()}
        </span>{" "}
        {data.filtered
          ? `matching rows, from ${data.total_in_period.toLocaleString()} in ${data.period ?? "the dataset"}`
          : `rows in ${data.period ?? "the dataset"}`}
      </p>
      <div className="flex items-center gap-1.5">
        <select
          value={state.limit}
          onChange={(e) => onUpdate({ limit: Number(e.target.value) })}
          aria-label="Rows per page"
          className="rounded-md border border-border bg-surface px-2 py-1 text-[12px] text-text-muted focus:border-accent focus:outline-none"
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n} rows
            </option>
          ))}
        </select>
        <Button
          variant="outline"
          size="sm"
          disabled={data.offset === 0}
          onClick={() =>
            onUpdate({ offset: Math.max(0, data.offset - state.limit) }, true)
          }
        >
          <ChevronLeft aria-hidden />
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={to >= data.total_rows}
          onClick={() => onUpdate({ offset: data.offset + state.limit }, true)}
        >
          Next
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- column profile */

/**
 * What is actually in a column.
 *
 * The dictionary says what a field is meant to hold; this says what it holds —
 * how much is missing, what values it takes, where the mass of it sits. It is
 * the question a steward asks before trusting a field in a calculation, and
 * every value here can be turned straight into a filter.
 */
function ColumnDrawer({
  dataset,
  field,
  period,
  onClose,
  onFilter,
}: {
  dataset: string;
  field: string;
  period: string | null;
  onClose: () => void;
  onFilter: (filter: string) => void;
}) {
  const profile = useAsync(
    () => api.datasetColumn(dataset, field, period ?? undefined),
    [dataset, field, period],
  );

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border bg-surface shadow-2xl">
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="min-w-0">
          <p className="meta text-text-muted">Column</p>
          <h2 className="truncate text-[15px] font-semibold text-text-primary">
            {profile.data?.business_name || field}
          </h2>
          <p className="mono truncate text-[11px] text-text-muted">{field}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
          <X aria-hidden />
        </Button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {profile.loading && <Skeleton className="h-64 w-full" />}
        {profile.error && <p className="text-sm text-negative">{profile.error}</p>}
        {profile.data && <ProfileBody profile={profile.data} onFilter={onFilter} />}
      </div>
    </div>
  );
}

function ProfileBody({
  profile,
  onFilter,
}: {
  profile: ColumnProfile;
  onFilter: (filter: string) => void;
}) {
  return (
    <>
      {profile.definition && (
        <p className="prose-ai text-[13px] text-text-secondary">
          {profile.definition}
        </p>
      )}

      <div className="grid grid-cols-3 gap-2">
        <Stat label="Rows" value={profile.rows.toLocaleString()} />
        <Stat label="Distinct" value={profile.distinct.toLocaleString()} />
        <Stat
          label="Missing"
          value={`${profile.missing_pct}%`}
          tone={profile.missing_pct > 0 ? "warning" : undefined}
        />
      </div>

      {profile.statistics && (
        <div>
          <p className="meta mb-1.5 text-text-muted">Distribution</p>
          <Card className="divide-y divide-border">
            {(
              [
                ["Minimum", profile.statistics.min],
                ["25th percentile", profile.statistics.p25],
                ["Median", profile.statistics.median],
                ["75th percentile", profile.statistics.p75],
                ["Maximum", profile.statistics.max],
                ["Mean", profile.statistics.mean],
                ["Total", profile.statistics.sum],
              ] as const
            ).map(([label, value]) => (
              <div
                key={label}
                className="flex items-baseline justify-between gap-3 px-3 py-1.5"
              >
                <span className="text-xs text-text-muted">{label}</span>
                <span className="mono text-xs text-text-primary">
                  {value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  {profile.unit ? ` ${profile.unit}` : ""}
                </span>
              </div>
            ))}
          </Card>
        </div>
      )}

      {profile.top_values.length > 0 && (
        <div>
          <p className="meta mb-1.5 text-text-muted">
            Most common values — click one to filter
          </p>
          <Card className="divide-y divide-border">
            {profile.top_values.map((entry) => (
              <button
                key={entry.value}
                type="button"
                onClick={() => onFilter(`${profile.field}:eq:${entry.value}`)}
                className="flex w-full items-center gap-3 px-3 py-1.5 text-left hover:bg-surface-hover"
              >
                <span className="min-w-0 flex-1 truncate text-xs text-text-primary">
                  {entry.value}
                </span>
                <span
                  className="h-1 shrink-0 rounded-full bg-accent"
                  style={{ width: `${Math.max(2, entry.share_pct)}%` }}
                  aria-hidden
                />
                <span className="mono w-24 shrink-0 text-right text-[11px] text-text-muted">
                  {entry.count.toLocaleString()} · {entry.share_pct}%
                </span>
              </button>
            ))}
          </Card>
        </div>
      )}

      {profile.missing > 0 && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onFilter(`${profile.field}:blank:`)}
        >
          Show the {profile.missing.toLocaleString()} rows where this is blank
        </Button>
      )}
    </>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "warning";
}) {
  return (
    <Card className="px-3 py-2">
      <p className="meta text-text-muted">{label}</p>
      <p
        className={cn(
          "display-num mt-0.5 text-sm font-semibold",
          tone === "warning" ? "text-warning" : "text-text-primary",
        )}
      >
        {value}
      </p>
    </Card>
  );
}
