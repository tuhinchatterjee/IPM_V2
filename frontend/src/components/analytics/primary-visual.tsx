"use client";

import * as React from "react";

import { InteractiveChart } from "@/components/analytics/chart-frame";
import { PeriodPlayback } from "@/components/analytics/period-playback";
import { ResultTable } from "@/components/analytics/primitives";
import {
  readPresentation,
  showingFor,
  subscribePresentation,
  writePresentation,
} from "@/lib/presentation";
import type { ColumnSpec } from "@/lib/format";
import type { Row } from "@/lib/api";

import {
  BubbleChart,
  CategoryBarChart,
  DivergingBarChart,
  ScatterPlot,
  StackedBarChart,
  TrendChart,
  type SeriesDef,
} from "./charts";
import * as playback from "./playback";
import { chooseVisualization, type ChartKind, type Choice } from "./registry";
import * as selection from "./selection";

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
  runId,
  onAsk,
}: {
  rows: Row[];
  columns?: ColumnSpec[];
  units?: Record<string, string>;
  className?: string;
  maxRows?: number;
  /**
   * The analysis this result belongs to. Presentation is remembered against
   * it — §47 — so a reader who switched THIS breakdown to a table finds it as
   * a table next time, and the next question they ask still starts from the
   * registry's judgement.
   */
  runId?: number | null;
  /** Carries "Ask about this" back to the composer, with the reader's view. */
  onAsk?: (question: string) => void;
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

  // ------------------------------------------------------------- playback
  //
  // Eligible only where the result actually carries several periods. A play
  // button over a single quarter is a control that does nothing, so it is not
  // offered rather than offered and disabled.
  const periodKey = React.useMemo(() => periodColumn(spec), [spec]);
  const periods = React.useMemo(
    () => (periodKey ? playback.periodsIn(rows, periodKey) : []),
    [rows, periodKey],
  );
  const [film, step] = React.useReducer(
    playback.reduce,
    periods,
    playback.start,
  );
  // The result changed under a playing cursor — a re-run, or a new answer in
  // the thread. Re-seeding from the new periods is a synchronisation with data
  // that arrived from outside, which is what an effect is for.
  React.useEffect(() => {
    step({ type: "reset" });
  }, [periodKey, periods.length]);

  const playing = playback.isEligible(periods) && periodKey !== "";
  const shownRows = React.useMemo(
    () => (playing ? playback.rowsFor(rows, periodKey, film) : rows),
    [playing, rows, periodKey, film],
  );

  // ------------------------------------------- what the reader chose, kept
  const registryDefault: "chart" | "table" =
    choice.kind === "table" || choice.kind === "kpi" ? "table" : "chart";
  const remembered = React.useSyncExternalStore(
    subscribePresentation,
    () => (runId ? JSON.stringify(readPresentation(runId)) : "{}"),
    () => "{}",
  );
  const [override, setOverride] = React.useState<"chart" | "table" | null>(null);
  const showing =
    override ??
    showingFor(registryDefault, runId ? JSON.parse(remembered) : {});

  const chooseShowing = React.useCallback(
    (next: "chart" | "table") => {
      setOverride(next);
      if (runId) writePresentation(runId, { showing: next });
    },
    [runId],
  );

  // The registry names the right form; this build draws six of them. When the
  // right form has no renderer here, the next form the shape genuinely
  // supports is drawn instead — silently falling all the way back to a table
  // loses the toggle as well as the chart, and the reader is told neither.
  const { series, x } = React.useMemo(
    () => seriesOf(choice, spec),
    [choice, spec],
  );

  const unitMap = React.useMemo(() => {
    const merged = { ...(units ?? {}) };
    for (const column of spec) {
      if (column.unit) merged[column.name] = column.unit;
    }
    return merged;
  }, [units, spec]);

  const table = (
    <ResultTable rows={shownRows} units={units} spec={spec} maxRows={maxRows} />
  );

  // A shape with no drawable form is a table and only a table. Wrapping it in
  // the interaction frame would offer a legend for series nobody can see and a
  // brush over rows nothing is drawing.
  const drawable = React.useMemo(
    () => firstDrawable(choice, shownRows, spec, unitMap).drawn,
    [choice, shownRows, spec, unitMap],
  );
  if (!drawable || !x || series.length === 0) {
    return (
      <ResultTable
        rows={shownRows}
        units={units}
        spec={spec}
        maxRows={maxRows}
        className={className}
      />
    );
  }

  return (
    <InteractiveChart
      className={className}
      series={series}
      rows={shownRows as Record<string, string | number | null>[]}
      xKey={x}
      because={choice.because}
      showing={showing}
      onShowing={chooseShowing}
      table={table}
      onAsk={onAsk}
      toolbar={
        playing ? <PeriodPlayback state={film} dispatch={step} /> : undefined
      }
      footer={
        drawable !== choice.kind ? (
          <p className="text-[11px] text-text-muted">
            Drawn as a {label(drawable)}; this result would read best as a{" "}
            {label(choice.kind)}, which this build does not draw yet.
          </p>
        ) : undefined
      }
    >
      {(view) =>
        renderChart(
          { ...choice, kind: drawable, series: view.series.map((s) => s.key) },
          view.rows as Row[],
          spec,
          unitMap,
          view.state,
          view.onCategory,
        )
      }
    </InteractiveChart>
  );
}

/**
 * The period column, where the result carries one.
 *
 * From the presentation contract's own semantic marking rather than from a
 * column called "period": a movement analysis labels its axis "Quarter", and
 * matching on the word would miss it.
 */
function periodColumn(spec: ColumnSpec[]): string {
  const semantic = spec.find((c) => String(c.semantic ?? "") === "period");
  if (semantic) return semantic.name;
  const named = spec.find((c) => /^(period|quarter|month|reporting_period)$/i.test(c.name));
  return named?.name ?? "";
}

/** The series and the x column, named once so the frame and the chart agree. */
function seriesOf(
  choice: Choice,
  spec: ColumnSpec[],
): { series: SeriesDef[]; x: string } {
  const byName = new Map(spec.map((c) => [c.name, c]));
  return {
    series: choice.series.map((key, slot) => ({
      key,
      label: byName.get(key)?.label ?? key,
      slot,
    })),
    x: choice.x ?? "",
  };
}

/** A chart kind in the words a reader uses. */
function label(kind: ChartKind): string {
  return kind.replace(/-/g, " ");
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
  state: selection.Selection = selection.EMPTY,
  onCategory?: (value: string) => void,
): React.ReactNode | null {
  const emphasise = (value: string) => selection.emphasis(state, value);
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
    // §54's Risk Landscape: two positions, a size and a governed band.
    case "risk-landscape":
    case "bubble":
      if (series.length < 2) return null;
      return (
        <BubbleChart
          data={data}
          xKey={choice.x}
          yKey={series[0].key}
          sizeKey={series[1]?.key ?? series[0].key}
          bandKey={bandColumn(spec)}
          labelKey={identityColumn(spec) || choice.x}
          units={unitMap}
          onPick={onCategory}
          emphasis={emphasise}
        />
      );
    case "scatter":
      return (
        <ScatterPlot
          data={data}
          xKey={choice.x}
          yKey={series[0].key}
          labelKey={identityColumn(spec) || choice.x}
          units={unitMap}
          onPick={onCategory}
          emphasis={emphasise}
        />
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
      // kpi, table, transition-matrix, sankey, treemap, histogram, heatmap,
      // matrix, small-multiples.
      return null;
  }
}

/**
 * The governed band that colours a landscape — a stage, a rating band.
 *
 * Chosen from the presentation contract rather than guessed: a column the
 * result declares categorical and that has few enough values to be a legend is
 * a band; a free-text column with two hundred values is not.
 */
function bandColumn(spec: ColumnSpec[]): string | undefined {
  const found = spec.find(
    (c) =>
      !c.hidden &&
      !c.is_identity &&
      (c.semantic === "text" || c.semantic === "ordinal") &&
      /stage|band|bucket|grade|rating|segment|tier/i.test(c.name),
  );
  return found?.name;
}

/** The column naming each point, so a tooltip can say which borrower it is. */
function identityColumn(spec: ColumnSpec[]): string {
  const declared = spec.find((c) => !c.hidden && c.is_identity);
  if (declared) return declared.name;
  const named = spec.find(
    (c) => !c.hidden && /name|borrower|customer|obligor|account/i.test(c.name),
  );
  return named?.name ?? "";
}
