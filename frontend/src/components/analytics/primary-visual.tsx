"use client";

import * as React from "react";
import { BarChart3, Table2 } from "lucide-react";

import { ResultTable } from "@/components/analytics/primitives";
import type { ColumnSpec } from "@/lib/format";
import type { Row } from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  CategoryBarChart,
  DivergingBarChart,
  StackedBarChart,
  TrendChart,
  type SeriesDef,
} from "./charts";
import { chooseVisualization, type ChartKind, type Choice } from "./registry";

/**
 * The result, drawn the way its shape asks to be drawn.
 *
 * §22: default to a chart where a chart is clearer, always keep a table
 * toggle, and use a table by default where a chart would mislead. The decision
 * itself lives in `registry.ts` and is tested there; this component renders it
 * and gives the reader the switch.
 *
 * Composed analyses used to reach the screen as a table and nothing else. Every
 * certified engine analysis had a bespoke chart and every question a reader
 * actually asked produced twenty-five rows of numbers — which is to say the
 * charts existed exactly where the shape was known in advance and nowhere the
 * product was doing its real work.
 *
 * WHAT IS NOT HERE, AND WHY
 *
 * Nothing in this file computes. The chart reads the same rows the table reads,
 * in the same order, with the same figures. §21: "Every chart uses the
 * structured result. The LLM never invents chart values." Sorting, binning or
 * aggregating here would put a number on screen that no engine produced and no
 * Trace covers.
 */
export function PrimaryVisual({
  rows,
  columns,
  units,
  className,
  maxRows,
}: {
  rows: Row[];
  columns?: ColumnSpec[];
  units?: Record<string, string>;
  className?: string;
  maxRows?: number;
}) {
  const spec = React.useMemo<ColumnSpec[]>(
    () =>
      columns?.length
        ? columns
        : Object.keys(rows[0] ?? {}).map((name) => ({ name, unit: units?.[name] })),
    [columns, rows, units],
  );

  const choice = React.useMemo(
    () => chooseVisualization(spec, rows),
    [spec, rows],
  );

  // The registry's answer is the DEFAULT, not a lock. A reader who wants the
  // figures gets the figures, and a reader who was given a table because there
  // were two hundred rows can still ask for the chart and see for themselves
  // why it was not offered.
  const [showing, setShowing] = React.useState<"chart" | "table">(
    choice.kind === "table" || choice.kind === "kpi" ? "table" : "chart",
  );

  // The registry names the right form; this build draws six of them. When the
  // right form has no renderer here, the next form the shape genuinely
  // supports is drawn instead — silently falling all the way back to a table
  // loses the toggle as well as the chart, and the reader is told neither.
  const { chart, drawn } = React.useMemo(
    () => firstDrawable(choice, rows, spec, units ?? {}),
    [choice, rows, spec, units],
  );

  if (!chart) {
    return (
      <ResultTable
        rows={rows}
        units={units}
        spec={spec}
        maxRows={maxRows}
        className={className}
      />
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] text-text-muted" title="Why this form was chosen">
          {choice.because}
        </p>
        <div className="flex shrink-0 items-center gap-0.5 rounded-md border border-border p-0.5">
          <Toggle
            active={showing === "chart"}
            onClick={() => setShowing("chart")}
            icon={BarChart3}
            label="Chart"
          />
          <Toggle
            active={showing === "table"}
            onClick={() => setShowing("table")}
            icon={Table2}
            label="Table"
          />
        </div>
      </div>

      {showing === "chart" ? (
        <>
          {chart}
          {drawn !== null && drawn !== choice.kind && (
            <p className="text-[11px] text-text-muted">
              Drawn as a {label(drawn)}; this result would read best as a{" "}
              {label(choice.kind)}, which this build does not draw yet.
            </p>
          )}
        </>
      ) : (
        <ResultTable rows={rows} units={units} spec={spec} maxRows={maxRows} />
      )}
    </div>
  );
}

/** A chart kind in the words a reader uses. */
function label(kind: ChartKind): string {
  return kind.replace(/-/g, " ");
}

function Toggle({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof BarChart3;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] transition-colors",
        "outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        active
          ? "bg-surface-interactive text-text-primary"
          : "text-text-muted hover:text-text-secondary",
      )}
    >
      <Icon className="size-3" aria-hidden />
      {label}
    </button>
  );
}

/**
 * The chosen form, or the first alternative this build can actually draw.
 *
 * §21 lists two dozen forms and this build draws six of them well. The registry
 * still records the right answer — adding a renderer later changes nothing
 * else — but a result whose ideal form is a Sankey should not lose its chart
 * toggle entirely when a stacked bar would have shown the same movement
 * honestly. Only the ALTERNATIVES the registry itself listed are tried, so
 * nothing is ever drawn in a form the shape does not support.
 */
function firstDrawable(
  choice: Choice,
  rows: Row[],
  spec: ColumnSpec[],
  units: Record<string, string>,
): { chart: React.ReactNode | null; drawn: ChartKind | null } {
  for (const kind of [choice.kind, ...choice.alternatives]) {
    if (kind === "table") break;
    const chart = renderChart({ ...choice, kind }, rows, spec, units);
    if (chart) return { chart, drawn: kind };
  }
  return { chart: null, drawn: null };
}

/**
 * One form, as a component — or null where this build has no renderer for it.
 */
function renderChart(
  choice: Choice,
  rows: Row[],
  spec: ColumnSpec[],
  units: Record<string, string>,
): React.ReactNode | null {
  const byName = new Map(spec.map((c) => [c.name, c]));
  const data = rows as Record<string, string | number | null>[];
  const series: SeriesDef[] = choice.series.map((key, slot) => ({
    key,
    label: byName.get(key)?.label ?? key,
    slot,
  }));
  const unitMap = { ...units };
  for (const column of spec) {
    if (column.unit) unitMap[column.name] = column.unit;
  }

  if (!choice.x || series.length === 0) return null;

  const kind: ChartKind = choice.kind;
  switch (kind) {
    case "line":
      return <TrendChart data={data} xKey={choice.x} series={series} units={unitMap} />;
    case "area":
    case "stacked-area":
      return (
        <TrendChart data={data} xKey={choice.x} series={series} units={unitMap} area />
      );
    case "bar":
      return (
        <CategoryBarChart
          data={data}
          xKey={choice.x}
          series={series}
          units={unitMap}
          horizontal={false}
        />
      );
    case "horizontal-bar":
      // The height follows the row count. A fixed 260px split fifteen ways
      // gives each bar a hairline, and a chart whose bars cannot be compared
      // by thickness is a table that has lost its numbers.
      return (
        <CategoryBarChart
          data={data}
          xKey={choice.x}
          series={series}
          units={unitMap}
          height={Math.min(560, Math.max(240, data.length * 26 + 40))}
        />
      );
    case "grouped-bar":
      return (
        <CategoryBarChart
          data={data}
          xKey={choice.x}
          series={series}
          units={unitMap}
          horizontal={false}
        />
      );
    case "stacked-bar":
      return (
        <StackedBarChart data={data} xKey={choice.x} series={series} units={unitMap} />
      );
    case "diverging-bar":
    case "waterfall":
      return (
        <DivergingBarChart
          data={data}
          xKey={choice.x}
          valueKey={series[0].key}
          unit={unitMap[series[0].key]}
        />
      );
    default:
      // kpi, table, transition-matrix, sankey, treemap, scatter, bubble,
      // histogram, heatmap, matrix, small-multiples, risk-landscape.
      return null;
  }
}
