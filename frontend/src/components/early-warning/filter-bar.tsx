"use client";

import * as React from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { EwsFilterChip, EwsFilterColumn } from "@/lib/api";
import * as flt from "@/components/early-warning/filters";

/**
 * Per-column filtering for the Early Warning book.
 *
 * Every control here narrows the PUBLISHED population on the server, not the
 * rows that happen to have been fetched. That distinction is the whole
 * feature: filtering a fetched page to "exposure above five hundred million"
 * answers with the matches among twenty rows and says nothing about the other
 * two hundred and eighty.
 *
 * The chips below the controls are the server's, not the component's. They
 * describe what was actually applied, so a chip cannot claim a filter the
 * backend refused or silently dropped.
 *
 * State lives in `filters.ts`, which is pure and tested. This file draws it.
 */

const CHIP_ORDER = ["customer", "segment", "ews_band", "ta_band",
  "classifier_band", "dominant_driver", "exposure", "dpd", "ews_score",
  "ta_score", "classifier_score"];

function label(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** A multi-select that says how many are chosen without opening. */
function MultiSelect({
  column,
  chosen,
  options,
  onToggle,
}: {
  column: EwsFilterColumn;
  chosen: string[];
  options: string[];
  onToggle: (value: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const box = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`Filter by ${column.label}`}
        data-testid={`ews-filter-${column.key}`}
        className={`flex w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-xs transition ${
          chosen.length > 0
            ? "border-accent bg-accent-muted text-text-primary"
            : "border-border bg-surface text-text-secondary hover:border-border-strong"
        }`}
      >
        <span className="truncate">
          {column.label}
          {chosen.length > 0 && ` · ${chosen.length}`}
        </span>
        <ChevronDown className="size-3.5 shrink-0" aria-hidden />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 max-h-72 w-56 overflow-y-auto rounded-lg border border-border bg-surface py-1 shadow-lg">
          {options.length === 0 && (
            <p className="px-3 py-2 text-xs text-text-muted">
              Nothing to choose from in this month.
            </p>
          )}
          {options.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onToggle(value)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface-hover"
            >
              <span
                className={`flex size-3.5 shrink-0 items-center justify-center rounded border ${
                  chosen.includes(value)
                    ? "border-accent bg-accent text-white"
                    : "border-border"
                }`}
              >
                {chosen.includes(value) && <Check className="size-2.5" aria-hidden />}
              </span>
              <span className="truncate">{label(value)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Two boxes and the unit, so a reader knows what 500 means before typing it. */
function RangeInput({
  column,
  range,
  onChange,
}: {
  column: EwsFilterColumn;
  range: flt.DraftRange | undefined;
  onChange: (edge: "min" | "max", text: string) => void;
}) {
  const impossible = flt.rangeIsImpossible(range);
  const set = flt.rangeIsSet(range);
  return (
    <div
      className={`rounded-md border px-2.5 py-1 ${
        impossible
          ? "border-negative"
          : set
            ? "border-accent bg-accent-muted"
            : "border-border bg-surface"
      }`}
    >
      <div className="flex items-baseline justify-between gap-1">
        <span className="text-[10px] uppercase tracking-wide text-text-muted">
          {column.label}
        </span>
        {column.unit && (
          <span className="text-[10px] text-text-muted">{column.unit}</span>
        )}
      </div>
      <div className="flex items-center gap-1">
        <input
          type="text"
          inputMode="decimal"
          value={range?.min ?? ""}
          onChange={(e) => onChange("min", e.target.value)}
          placeholder="min"
          aria-label={`${column.label} minimum`}
          data-testid={`ews-filter-${column.key}-min`}
          className="w-full min-w-0 bg-transparent text-xs outline-none placeholder:text-text-muted"
        />
        <span className="text-text-muted" aria-hidden>–</span>
        <input
          type="text"
          inputMode="decimal"
          value={range?.max ?? ""}
          onChange={(e) => onChange("max", e.target.value)}
          placeholder="max"
          aria-label={`${column.label} maximum`}
          data-testid={`ews-filter-${column.key}-max`}
          className="w-full min-w-0 bg-transparent text-xs outline-none placeholder:text-text-muted"
        />
      </div>
    </div>
  );
}

export function EwsFilterBar({
  columns,
  facets,
  state,
  chips,
  matched,
  population,
  busy,
  onChange,
  onExport,
  exporting,
  exportError,
}: {
  columns: EwsFilterColumn[];
  facets: Record<string, string[]>;
  state: flt.FilterState;
  /** The chips the SERVER produced, describing what it actually applied. */
  chips: EwsFilterChip[];
  matched: number;
  population: number;
  busy: boolean;
  onChange: (next: flt.FilterState) => void;
  onExport: () => void;
  exporting: boolean;
  exportError: string;
}) {
  const multi = columns.filter((c) => c.kind === "multi");
  const ranges = columns.filter((c) => c.kind === "range");
  const problems = flt.problems(state);
  const ordered = [...chips].sort(
    (a, b) => CHIP_ORDER.indexOf(a.key) - CHIP_ORDER.indexOf(b.key),
  );

  return (
    <div className="space-y-2.5 rounded-lg border border-border bg-surface-subtle p-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-6">
        <div className="col-span-2 flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5">
          <Search className="size-3.5 shrink-0 text-text-muted" aria-hidden />
          <input
            type="search"
            value={state.customer}
            onChange={(e) => onChange(flt.setCustomer(state, e.target.value))}
            placeholder="Customer name"
            aria-label="Filter by customer name"
            data-testid="ews-filter-customer"
            className="w-full min-w-0 bg-transparent text-xs outline-none placeholder:text-text-muted"
          />
        </div>

        {multi.map((column) => (
          <MultiSelect
            key={column.key}
            column={column}
            chosen={state.selections[column.key] ?? []}
            options={
              column.choices.length > 0
                ? column.choices
                : (facets[column.key] ?? [])
            }
            onToggle={(value) => onChange(flt.toggle(state, column.key, value))}
          />
        ))}

        {ranges.map((column) => (
          <RangeInput
            key={column.key}
            column={column}
            range={state.ranges[column.key]}
            onChange={(edge, text) =>
              onChange(flt.setRange(state, column.key, edge, text))
            }
          />
        ))}
      </div>

      {problems.length > 0 && (
        <p className="text-xs text-negative" role="status">
          {problems[0]} Nothing has been filtered on it.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span
          className="text-xs text-text-secondary"
          data-testid="ews-filter-count"
          aria-live="polite"
        >
          {busy ? (
            "Counting…"
          ) : (
            <>
              <strong className="tabular">{matched.toLocaleString()}</strong>
              {" of "}
              <span className="tabular">{population.toLocaleString()}</span>
              {" obligors"}
              {matched !== population && " match"}
            </>
          )}
        </span>

        {ordered.map((chip) => (
          <Badge key={chip.key} variant="info">
            <span className="mr-1 text-text-secondary">{chip.label}:</span>
            {chip.value}
            <button
              type="button"
              onClick={() => onChange(flt.clearOne(state, chip.key))}
              aria-label={`Clear the ${chip.label} filter`}
              className="ml-1 rounded hover:text-negative"
            >
              <X className="size-3" aria-hidden />
            </button>
          </Badge>
        ))}

        {flt.isNarrowed(state) && (
          <button
            type="button"
            onClick={() => onChange(flt.clearAll(state))}
            className="text-xs text-accent underline-offset-2 hover:underline"
          >
            Clear all
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          {exportError && (
            <span className="text-xs text-negative">{exportError}</span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={onExport}
            disabled={exporting}
            data-testid="ews-export"
          >
            {exporting ? "Preparing…" : "Download Excel"}
          </Button>
        </div>
      </div>
    </div>
  );
}
