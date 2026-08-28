"use client";

import * as React from "react";
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Maximize2,
  MessageSquareText,
  Minimize2,
  RotateCcw,
  Table2,
  X,
} from "lucide-react";

import {
  PaletteControl,
  paletteStyle,
  useChartPalette,
} from "@/components/analytics/chart-palette";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { SeriesDef } from "./charts";
import * as selection from "./selection";

/**
 * The controls around a chart, and the state they change.
 *
 * §47 asks for a long list — legend filtering, series isolation, category
 * selection, a range brush, reset, full screen, a chart/table toggle, a
 * palette selector, "Ask about this", keyboard and touch. What makes that a
 * feature rather than a pile of buttons is that they all read and write ONE
 * structured selection (`selection.ts`), so Reset genuinely resets and two
 * controls can never disagree about what is on screen.
 *
 * The frame owns the controls and the state. It does not own the chart: the
 * caller passes a render function and receives the series and rows that
 * survived the reader's choices. That is what keeps the eight chart forms free
 * of interaction code, and what lets a new form inherit all of this by being
 * drawn inside the frame.
 *
 * Nothing here computes an analytical figure. Hiding a series changes what is
 * drawn; the result, the table and the export are untouched.
 */

export interface InteractiveChartProps {
  /** The series the result carries, before the reader hides any. */
  series: SeriesDef[];
  /** The rows, in the result's own order. */
  rows: Record<string, string | number | null>[];
  /** The column along the bottom, for category selection and the brush. */
  xKey?: string;
  /** Why the registry chose this form. Shown, so the choice is inspectable. */
  because?: string;
  /** Chart or table, and the switch. */
  showing: "chart" | "table";
  onShowing: (next: "chart" | "table") => void;
  /** The table, rendered by the caller so the frame owns no formatting. */
  table: React.ReactNode;
  /** Draw the chart from what survived the reader's choices. */
  children: (view: {
    series: SeriesDef[];
    rows: Record<string, string | number | null>[];
    state: selection.Selection;
    onCategory: (value: string) => void;
  }) => React.ReactNode;
  /** Carry the reader's view into a follow-up question. */
  onAsk?: (question: string) => void;
  /** Extra controls — period playback goes here. */
  toolbar?: React.ReactNode;
  /** Shown under the chart, beneath the toolbar. */
  footer?: React.ReactNode;
  className?: string;
}

export function InteractiveChart({
  series,
  rows,
  xKey,
  because,
  showing,
  onShowing,
  table,
  children,
  onAsk,
  toolbar,
  footer,
  className,
}: InteractiveChartProps) {
  const [state, dispatch] = React.useReducer(selection.reduce, selection.EMPTY);
  const [full, setFull] = React.useState(false);
  const [palette] = useChartPalette();

  const labels = React.useMemo(
    () => Object.fromEntries(series.map((s) => [s.key, s.label])),
    [series],
  );
  const shown = React.useMemo(
    () => selection.visibleSeries(series, state),
    [series, state],
  );
  const windowed = React.useMemo(
    () => selection.visibleRows(rows, state),
    [rows, state],
  );

  const categories = React.useMemo(
    () => (xKey ? windowed.map((r) => String(r[xKey] ?? "")) : []),
    [windowed, xKey],
  );

  // Escape leaves full screen. Registered on the window rather than on the
  // panel because the reader's focus is usually inside the chart, where a
  // key handler on a div would never see it.
  React.useEffect(() => {
    if (!full) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFull(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);

  const onKeyDown = React.useCallback(
    (event: React.KeyboardEvent) => {
      if (showing !== "chart" || categories.length === 0) return;
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        dispatch({
          type: "move-focus",
          delta: event.key === "ArrowRight" ? 1 : -1,
          count: categories.length,
        });
        return;
      }
      if ((event.key === "Enter" || event.key === " ") && state.focused >= 0) {
        event.preventDefault();
        dispatch({ type: "toggle-category", value: categories[state.focused] });
        return;
      }
      if (event.key === "Escape" && selection.isTouched(state)) {
        event.preventDefault();
        dispatch({ type: "reset" });
      }
    },
    [showing, categories, state],
  );

  const summary = selection.describe(state, labels);
  const touched = selection.isTouched(state);

  const ask = React.useCallback(() => {
    if (!onAsk) return;
    // The question carries what the reader was looking at. A follow-up asked
    // from a chart filtered to two sectors that arrived as "tell me more"
    // would be answered about the whole book.
    const about = summary ? ` (looking at ${summary})` : "";
    onAsk(`What should I take from this${about}?`);
  }, [onAsk, summary]);

  const focused =
    state.focused >= 0 && state.focused < categories.length
      ? categories[state.focused]
      : "";

  const body = (
    <div
      className={cn("space-y-2", full && "flex h-full flex-col")}
      onKeyDown={onKeyDown}
    >
      {/* ------------------------------------------------------- the toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <p className="min-w-0 text-[11px] text-text-muted" title="Why this form was chosen">
          {because}
        </p>

        <div className="flex shrink-0 flex-wrap items-center gap-1">
          {toolbar}

          {touched && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => dispatch({ type: "reset" })}
              title="Show every series and every row again"
            >
              <RotateCcw aria-hidden />
              Reset
            </Button>
          )}

          {onAsk && (
            <Button
              variant="ghost"
              size="sm"
              onClick={ask}
              title="Ask CreditProbe about what is on screen"
            >
              <MessageSquareText aria-hidden />
              Ask about this
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setFull((f) => !f)}
            title={full ? "Leave full screen (Esc)" : "Full screen"}
            aria-label={full ? "Leave full screen" : "Full screen"}
          >
            {full ? <Minimize2 aria-hidden /> : <Maximize2 aria-hidden />}
          </Button>

          <div className="flex items-center gap-0.5 rounded-md border border-border p-0.5">
            <Toggle
              active={showing === "chart"}
              onClick={() => onShowing("chart")}
              icon={BarChart3}
              label="Chart"
            />
            <Toggle
              active={showing === "table"}
              onClick={() => onShowing("table")}
              icon={Table2}
              label="Table"
            />
          </div>
        </div>
      </div>

      {/* ---------------------------------------------------------- the legend */}
      {showing === "chart" && series.length > 1 && (
        <Legend
          series={series}
          state={state}
          onToggle={(key) => dispatch({ type: "toggle-series", key })}
          onIsolate={(key) => dispatch({ type: "isolate-series", key })}
        />
      )}

      {/* ------------------------------------------------------------ the chart */}
      <div
        className={cn("outline-none", full && "min-h-0 flex-1")}
        tabIndex={showing === "chart" ? 0 : -1}
        role={showing === "chart" ? "application" : undefined}
        aria-label={
          showing === "chart"
            ? "Chart. Use the left and right arrows to move between categories, " +
              "Enter to pick one out, and Escape to reset."
            : undefined
        }
        data-testid="chart-surface"
      >
        <div style={paletteStyle(palette)}>
          {showing === "chart"
            ? children({
                series: shown,
                rows: windowed,
                state,
                onCategory: (value) => dispatch({ type: "toggle-category", value }),
              })
            : table}
        </div>
      </div>

      {/* ------------------------------------------------------- what is chosen */}
      {showing === "chart" && (summary || focused) && (
        <p className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted"
           role="status">
          {focused && <span className="mono">{focused}</span>}
          {summary && <span>{summary}</span>}
        </p>
      )}

      {/* ------------------------------------------------------------- the brush */}
      {showing === "chart" && rows.length > 6 && (
        <RangeBrush
          count={rows.length}
          range={state.range}
          onChange={(range) => dispatch({ type: "set-range", range })}
        />
      )}

      {showing === "chart" && <PaletteControl />}

      {footer}
    </div>
  );

  if (!full) return <div className={className}>{body}</div>;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col gap-3 bg-surface p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Chart, full screen"
    >
      <div className="flex items-center justify-end">
        <Button variant="ghost" size="sm" onClick={() => setFull(false)}>
          <Minimize2 aria-hidden />
          Close
        </Button>
      </div>
      <div className="min-h-0 flex-1">{body}</div>
    </div>
  );
}

/* --------------------------------------------------------------- the legend */

/**
 * A legend that filters.
 *
 * Click hides a series; a second click brings it back. The isolate control
 * beside each entry answers the other question a reader has — "show me only
 * this one" — which clicking away five other series is a poor way to ask.
 */
function Legend({
  series,
  state,
  onToggle,
  onIsolate,
}: {
  series: SeriesDef[];
  state: selection.Selection;
  onToggle: (key: string) => void;
  onIsolate: (key: string) => void;
}) {
  return (
    <ul className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {series.map((s) => {
        const off =
          state.isolated !== null
            ? state.isolated !== s.key
            : state.hidden.includes(s.key);
        return (
          <li key={s.key} className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onToggle(s.key)}
              onDoubleClick={() => onIsolate(s.key)}
              aria-pressed={!off}
              title={
                off
                  ? `Show ${s.label}. Double-click to show it alone.`
                  : `Hide ${s.label}. Double-click to show it alone.`
              }
              className={cn(
                "flex items-center gap-1.5 rounded px-1 py-0.5 text-[11px] transition-opacity",
                "hover:bg-surface-hover",
                off ? "opacity-40" : "opacity-100",
              )}
            >
              <span
                aria-hidden
                className="size-2.5 shrink-0 rounded-[2px]"
                style={{ background: `var(--ipm-chart-${s.slot + 1})` }}
              />
              <span className={cn(off && "line-through")}>{s.label}</span>
            </button>
          </li>
        );
      })}
      {state.isolated !== null && (
        <li>
          <button
            type="button"
            onClick={() => onIsolate(state.isolated as string)}
            className="flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-text-muted hover:bg-surface-hover"
          >
            <X className="size-3" aria-hidden />
            Show all
          </button>
        </li>
      )}
    </ul>
  );
}

/* ---------------------------------------------------------------- the brush */

/**
 * A range over the rows.
 *
 * Two number inputs rather than a dragged overlay: a drag is pleasant with a
 * mouse and unusable with a trackpad on a laptop in a meeting, and it cannot
 * be operated from the keyboard at all. These are exact, they are reachable by
 * Tab, and they say which rows they mean.
 */
function RangeBrush({
  count,
  range,
  onChange,
}: {
  count: number;
  range: selection.Range | null;
  onChange: (range: selection.Range | null) => void;
}) {
  const from = range?.from ?? 0;
  const to = range?.to ?? count - 1;

  const set = (next: Partial<selection.Range>) => {
    const start = Math.max(0, Math.min(next.from ?? from, count - 1));
    const end = Math.max(start, Math.min(next.to ?? to, count - 1));
    onChange(start === 0 && end === count - 1 ? null : { from: start, to: end });
  };

  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
      <span>Rows</span>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => set({ from: from - 1, to: to - 1 })}
        disabled={from <= 0}
        aria-label="Earlier rows"
      >
        <ChevronLeft aria-hidden />
      </Button>
      <input
        type="range"
        min={0}
        max={count - 1}
        value={from}
        onChange={(e) => set({ from: Number(e.target.value) })}
        aria-label="First row shown"
        className="h-1 w-28 accent-[var(--ipm-accent)]"
      />
      <span className="mono">
        {from + 1}–{to + 1} of {count}
      </span>
      <input
        type="range"
        min={0}
        max={count - 1}
        value={to}
        onChange={(e) => set({ to: Number(e.target.value) })}
        aria-label="Last row shown"
        className="h-1 w-28 accent-[var(--ipm-accent)]"
      />
      <Button
        variant="ghost"
        size="sm"
        onClick={() => set({ from: from + 1, to: to + 1 })}
        disabled={to >= count - 1}
        aria-label="Later rows"
      >
        <ChevronRight aria-hidden />
      </Button>
      {range && (
        <Button variant="ghost" size="sm" onClick={() => onChange(null)}>
          All rows
        </Button>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- the toggle */

function Toggle({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={`Show as a ${label.toLowerCase()}`}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-1 text-[11px] transition-colors",
        active
          ? "bg-surface-sunken text-text-primary"
          : "text-text-muted hover:text-text-primary",
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {label}
    </button>
  );
}
