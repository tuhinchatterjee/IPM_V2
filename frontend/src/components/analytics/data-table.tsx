"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Columns3, Check } from "lucide-react";

import { MetadataLabel } from "@/components/typography";
import { columnUnit, figure, humanise, type ColumnSpec } from "@/lib/format";
import type { Row } from "@/lib/api";
import { cn } from "@/lib/utils";

import { isPointedAt, useHighlight } from "./highlight";

/**
 * The analytical table.
 *
 * What a credit officer does with one of these is scan a column for magnitude,
 * find the two rows that are wrong, and check them against the heading. Every
 * decision here follows from that and from nothing else.
 *
 * The unit belongs in the header
 * ------------------------------
 * A column that prints "USD mn" on all twenty-five rows has repeated the one
 * fact that does not vary twenty-four times, in the same visual weight as the
 * figures that do. Worse, it pushes the digits apart so the column can no
 * longer be scanned. The unit is lifted into the header — but only when every
 * row agrees on it. A money column straddling the billion boundary would show
 * "12.3" beside "840.0" under one header meaning two different things, so
 * there the unit stays on the rows and the header says nothing.
 *
 * Sorting is client-side and says so
 * ----------------------------------
 * It reorders the rows the engine returned. It does NOT re-run the analysis, so
 * sorting a truncated result sorts the part you can see — which is why the
 * count under the table says how many rows there are in total.
 *
 * What it deliberately is not
 * ---------------------------
 * A spreadsheet. There is no editing, no formulae, no cell selection. Every
 * figure here is the output of a governed analysis and the way to change one is
 * to change the question.
 */

const IDENTITY_HINT = /^(customer|borrower|account|facility|obligor|sector|region|segment|name|id)/i;

/** The values in a row that name what it is about, for highlight matching. */
function identityValues(row: Row, keys: string[]): (string | number | null)[] {
  return keys.map((key) => {
    const value = row[key];
    return typeof value === "string" || typeof value === "number" ? value : null;
  });
}

export interface DataTableProps {
  rows: Row[];
  /** The backend's presentation contract. Without it, formatting is guesswork. */
  spec?: ColumnSpec[];
  /** Restrict and order the columns. Defaults to the keys of the first row. */
  columns?: string[];
  /** Rows shown before the table says how many more there are. */
  maxRows?: number;
  /** Stick the header while the body scrolls. Needs a bounded height. */
  stickyHeader?: boolean;
  /** Cap the body height, in px, and scroll inside it. */
  maxHeight?: number;
  className?: string;
  emptyMessage?: string;
  /** Let a caller draw one cell itself — a status pill, a link. */
  renderCell?: (column: string, value: unknown, row: Row) => React.ReactNode | undefined;
}

type SortState = { key: string; direction: "asc" | "desc" } | null;

export function DataTable({
  rows,
  spec,
  columns,
  maxRows,
  stickyHeader = false,
  maxHeight,
  className,
  emptyMessage = "No rows returned.",
  renderCell,
}: DataTableProps) {
  const byName = React.useMemo(
    () => new Map((spec ?? []).map((c) => [c.name, c])),
    [spec],
  );

  const allKeys = React.useMemo(
    () => columns ?? spec?.map((c) => c.name)
      ?? (rows.length ? Object.keys(rows[0]) : []),
    [columns, spec, rows],
  );

  // Lineage starts hidden. An as-of stamp, a denominator, a key carried
  // through an aggregate so a filter could be applied — each is a real column
  // and none of them is an answer, and a borrower name beside a sector total
  // invites a reader to conclude the total belongs to that borrower. Hidden,
  // never removed: the column picker turns every one of them back on.
  const [hidden, setHidden] = React.useState<Set<string>>(
    () => new Set((spec ?? []).filter((c) => c.hidden).map((c) => c.name)),
  );
  const [sort, setSort] = React.useState<SortState>(null);
  const { active } = useHighlight();

  // Which columns name the thing each row is about. Only these are matched
  // against a token's label: a highlight that fired on a numeric cell would
  // point at whichever row happened to hold that value.
  const identityKeys = React.useMemo(
    () =>
      (spec ?? [])
        .filter((c) => c.is_identity)
        .map((c) => c.name)
        .concat(
          (columns ?? spec?.map((c) => c.name) ?? []).filter((k) =>
            IDENTITY_HINT.test(k),
          ),
        ),
    [spec, columns],
  );

  const keys = React.useMemo(
    () => allKeys.filter((k) => !hidden.has(k)),
    [allKeys, hidden],
  );

  const isNumeric = React.useCallback(
    (key: string) => {
      const declared = byName.get(key);
      if (declared?.align) return declared.align === "right";
      if (declared?.is_identity) return false;
      if (IDENTITY_HINT.test(key)) return false;
      return rows.some((r) => typeof r[key] === "number");
    },
    [byName, rows],
  );

  /** The unit every row in this column agrees on, for the header. */
  const headerUnit = React.useCallback(
    (key: string) => columnUnit(rows.map((r) => r[key]), byName.get(key)),
    [byName, rows],
  );

  const sorted = React.useMemo(() => {
    if (!sort) return rows;
    const { key, direction } = sort;
    const factor = direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = a[key];
      const y = b[key];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * factor;
      return String(x).localeCompare(String(y)) * factor;
    });
  }, [rows, sort]);

  const shown = maxRows ? sorted.slice(0, maxRows) : sorted;

  if (!rows.length) {
    return (
      <p className="py-8 text-center text-body text-text-muted">{emptyMessage}</p>
    );
  }

  const toggleSort = (key: string) =>
    setSort((current) =>
      current?.key !== key
        ? { key, direction: isNumeric(key) ? "desc" : "asc" }
        : current.direction === "desc"
          ? { key, direction: "asc" }
          : null,
    );

  return (
    <div className={cn("min-w-0", className)}>
      <div
        className={cn("w-full overflow-auto", stickyHeader && "relative")}
        style={maxHeight ? { maxHeight } : undefined}
      >
        <table className="w-full border-collapse text-body">
          <thead
            className={cn(
              stickyHeader && "sticky top-0 z-10",
              "bg-surface",
            )}
          >
            <tr className="border-b border-border-strong">
              {keys.map((key) => {
                const column = byName.get(key);
                const unit = headerUnit(key);
                const numeric = isNumeric(key);
                const active = sort?.key === key;
                return (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={
                      active
                        ? sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                    className={cn(
                      "h-8 max-w-[16rem] px-3 align-bottom",
                      numeric ? "text-right" : "text-left",
                    )}
                  >
                    {/* Label, then unit, then the sort arrow — in that order
                        whichever way the column is aligned. `flex-row-reverse`
                        put the unit in front of the name, which reads as
                        "usd mn Exposure at default". The alignment is done by
                        justifying the row instead. */}
                    <button
                      type="button"
                      onClick={() => toggleSort(key)}
                      title={column?.role ?? `Sort by ${column?.label ?? humanise(key)}`}
                      className={cn(
                        "group flex w-full min-w-0 items-baseline gap-1 rounded-sm",
                        "outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                        numeric ? "justify-end" : "justify-start",
                      )}
                    >
                      {/* Sentence case, not the uppercase mono used elsewhere
                          for technical labels. "EXPOSURE AT DEFAULT — POPULATION
                          TOTAL" set in letterspaced capitals is half a table
                          wide and the reader is here for the figures. */}
                      <span
                        className={cn(
                          "truncate text-[0.6875rem] font-semibold leading-tight transition-colors",
                          active ? "text-text-secondary" : "text-text-muted group-hover:text-text-secondary",
                        )}
                      >
                        {column?.label ?? humanise(key)}
                      </span>
                      {unit && (
                        <span className="shrink-0 font-mono text-[0.625rem] font-normal lowercase text-text-muted/70">
                          {unit}
                        </span>
                      )}
                      {active &&
                        (sort.direction === "asc" ? (
                          <ArrowUp className="size-3 shrink-0 text-accent" aria-hidden />
                        ) : (
                          <ArrowDown className="size-3 shrink-0 text-accent" aria-hidden />
                        ))}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => (
              <tr
                key={index}
                className={cn(
                  "border-b border-border/60 last:border-0",
                  "transition-colors duration-100 hover:bg-surface-interactive",
                  // §51: clicking an evidence token in the prose points at the
                  // row it came from. The reader used to reconstruct that by
                  // scanning twenty-eight rows for the sector the sentence
                  // named.
                  isPointedAt(active, identityValues(row, identityKeys)) &&
                    "bg-accent-muted/40 ring-1 ring-inset ring-accent/30",
                )}
              >
                {keys.map((key) => {
                  const column = byName.get(key);
                  const numeric = isNumeric(key);
                  const custom = renderCell?.(key, row[key], row);
                  const value = figure(row[key], column);
                  const unitShown = headerUnit(key);
                  return (
                    <td
                      key={key}
                      className={cn(
                        "whitespace-nowrap px-3 py-1.5 align-middle",
                        numeric
                          ? "text-right font-mono text-[0.8125rem] tabular-nums text-text-primary"
                          : "text-left text-text-secondary",
                      )}
                    >
                      {custom ?? (
                        <>
                          {value.text}
                          {/* Only when the header could not take it — a column
                              whose rows disagree about their unit. */}
                          {!unitShown && value.unit && (
                            <span className="ml-1 text-[0.6875rem] text-text-muted">
                              {value.unit}
                            </span>
                          )}
                        </>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <TableFooter
        shown={shown.length}
        total={rows.length}
        allKeys={allKeys}
        hidden={hidden}
        setHidden={setHidden}
        byName={byName}
      />
    </div>
  );
}

/**
 * What is on screen, and what is not.
 *
 * A table that silently shows the first twenty-five of four thousand rows is
 * a table somebody will read as the whole answer.
 */
function TableFooter({
  shown,
  total,
  allKeys,
  hidden,
  setHidden,
  byName,
}: {
  shown: number;
  total: number;
  allKeys: string[];
  hidden: Set<string>;
  setHidden: (next: Set<string>) => void;
  byName: Map<string, ColumnSpec>;
}) {
  const [open, setOpen] = React.useState(false);
  const container = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!container.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  if (total <= shown && hidden.size === 0 && allKeys.length < 4) return null;

  return (
    <div className="mt-2 flex items-center justify-between gap-3 px-3">
      <MetadataLabel>
        {shown === total
          ? `${total.toLocaleString("en-US")} ${total === 1 ? "row" : "rows"}`
          : `${shown.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} rows`}
      </MetadataLabel>

      {allKeys.length >= 4 && (
        <div className="relative" ref={container}>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2 py-1",
              "text-[0.6875rem] text-text-muted transition-colors",
              "hover:bg-surface-hover hover:text-text-secondary",
            )}
            aria-expanded={open}
          >
            <Columns3 className="size-3.5" aria-hidden />
            {hidden.size > 0 ? `${allKeys.length - hidden.size} of ${allKeys.length} columns` : "Columns"}
          </button>

          {open && (
            <div
              className={cn(
                "absolute bottom-full right-0 z-20 mb-1 w-56 overflow-hidden rounded-lg",
                "border border-border bg-surface-elevated shadow-overlay",
              )}
              role="group"
              aria-label="Show or hide columns"
            >
              {allKeys.map((key) => {
                const visible = !hidden.has(key);
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      const next = new Set(hidden);
                      // The last visible column cannot be hidden: an empty
                      // table is not a view anybody asked for.
                      if (visible && allKeys.length - next.size <= 1) return;
                      if (visible) next.add(key);
                      else next.delete(key);
                      setHidden(next);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-body",
                      "transition-colors hover:bg-surface-hover",
                      visible ? "text-text-primary" : "text-text-muted",
                    )}
                  >
                    <Check
                      className={cn("size-3.5 shrink-0", visible ? "opacity-100 text-accent" : "opacity-0")}
                      aria-hidden
                    />
                    <span className="truncate">
                      {byName.get(key)?.label ?? humanise(key)}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
