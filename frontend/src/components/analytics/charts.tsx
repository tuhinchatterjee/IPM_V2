"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import { byUnit, humanise } from "@/lib/format";
import {
  CHART_SLOTS as SLOTS,
  ChartFrame,
  PaletteControl,
} from "@/components/analytics/chart-palette";
import { cn } from "@/lib/utils";

/**
 * Chart primitives.
 *
 * Rules applied throughout, rather than per chart:
 *
 *  - **Colour is assigned in fixed slot order and never cycled.** A series keeps
 *    its colour when a filter changes how many series are on screen.
 *  - **One axis, always.** Two measures on different scales get two charts, never
 *    two y-scales on one.
 *  - **Thin marks, recessive grid.** 2px lines, horizontal gridlines only, no
 *    axis lines competing with the data.
 *  - **A hover layer by default.** Every chart carries a tooltip; a static chart
 *    in a browser wastes the medium.
 *  - **A legend whenever there are two or more series**, so identity never rests
 *    on colour alone. One series needs none — the title names it.
 *  - **A 2px surface gap between stacked segments**, so adjacent bands read as
 *    separate quantities rather than one blurred mass.
 *
 * Colours are read from the theme's CSS custom properties at render time, so a
 * theme switch repaints every chart with no chart-level code involved.
 */

export { CHART_SLOTS } from "@/components/analytics/chart-palette";

/**
 * Every chart is wrapped so it carries its own palette and its own control.
 *
 * The control belongs to the chart, not to whatever is rendering it. Putting it
 * in the result view covered analyses and missed the ten charts on the CRO
 * Lens, which is exactly the kind of gap that makes a control feel unreliable.
 *
 * It is invisible until the chart is hovered or focused. Ten visible palette
 * rows on one page is clutter in a product whose first principle is that
 * decoration comes last; ten that appear under your cursor are a tool.
 */
function Framed({
  children,
  className,
  height,
}: {
  children: React.ReactNode;
  className?: string;
  height: number;
}) {
  return (
    <ChartFrame className={cn("group/chart", className)} showControl={false}>
      <div className="w-full" style={{ height }}>
        {children}
      </div>
      <div
        className={cn(
          "opacity-0 transition-opacity duration-[--duration-quick]",
          "group-hover/chart:opacity-100 focus-within:opacity-100",
        )}
      >
        <PaletteControl />
      </div>
    </ChartFrame>
  );
}

/** Fixed-order slot colour. Never call this with an index derived from rank. */
export function slotColor(index: number): string {
  return `var(--ipm-chart-${(index % SLOTS) + 1})`;
}

const AXIS = { fill: "var(--ipm-text-muted)", fontSize: 11 };
const GRID = "var(--ipm-border)";

function TooltipBox({
  active,
  payload,
  label,
  units,
}: {
  active?: boolean;
  payload?: { name?: string; dataKey?: string; value?: number; color?: string }[];
  label?: string | number;
  units?: Record<string, string>;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2 shadow-lg">
      {label !== undefined && (
        <p className="mb-1 text-xs font-medium text-text-primary">{String(label)}</p>
      )}
      <div className="space-y-0.5">
        {payload.map((entry, i) => {
          const key = String(entry.dataKey ?? entry.name ?? i);
          return (
            <div key={key} className="flex items-center gap-2 text-xs">
              <span
                className="size-2 shrink-0 rounded-[2px]"
                style={{ backgroundColor: entry.color }}
                aria-hidden
              />
              <span className="text-text-secondary">{entry.name ?? humanise(key)}</span>
              <span className="ml-auto font-medium text-text-primary tabular">
                {byUnit(entry.value, units?.[key])}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChartLegend() {
  return (
    <Legend
      verticalAlign="bottom"
      height={28}
      iconType="square"
      iconSize={8}
      wrapperStyle={{ fontSize: 11, color: "var(--ipm-text-secondary)", paddingTop: 8 }}
    />
  );
}

export interface SeriesDef {
  key: string;
  label: string;
  /** Fixed slot index. Assign once per series and never recompute from order. */
  slot: number;
}

interface BaseProps {
  data: Record<string, string | number | null>[];
  xKey: string;
  series: SeriesDef[];
  units?: Record<string, string>;
  height?: number;
  className?: string;
}

/** Change over time. */
export function TrendChart({
  data,
  xKey,
  series,
  units,
  height = 240,
  className,
  area = false,
}: BaseProps & { area?: boolean }) {
  const Chart = area ? AreaChart : LineChart;
  return (
    <Framed className={className} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="0" vertical={false} />
          <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} />
          <Tooltip
            content={<TooltipBox units={units} />}
            cursor={{ stroke: "var(--ipm-border-strong)", strokeWidth: 1 }}
          />
          {series.length > 1 && ChartLegend()}
          {series.map((s) =>
            area ? (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={slotColor(s.slot)}
                fill={slotColor(s.slot)}
                fillOpacity={0.12}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--ipm-surface)" }}
              />
            ) : (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={slotColor(s.slot)}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--ipm-surface)" }}
              />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </Framed>
  );
}

/** Magnitude by category. Horizontal when the labels are words. */
export function CategoryBarChart({
  data,
  xKey,
  series,
  units,
  height = 260,
  className,
  horizontal = true,
}: BaseProps & { horizontal?: boolean }) {
  return (
    <Framed className={className} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout={horizontal ? "vertical" : "horizontal"}
          margin={{ top: 4, right: 16, bottom: 0, left: horizontal ? 8 : -8 }}
          barCategoryGap={horizontal ? 6 : "22%"}
        >
          <CartesianGrid stroke={GRID} horizontal={!horizontal} vertical={horizontal} />
          {horizontal ? (
            <>
              <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} />
              <YAxis
                type="category"
                dataKey={xKey}
                tick={AXIS}
                tickLine={false}
                axisLine={false}
                width={112}
              />
            </>
          ) : (
            <>
              <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} />
            </>
          )}
          <Tooltip
            content={<TooltipBox units={units} />}
            cursor={{ fill: "var(--ipm-surface-hover)" }}
          />
          {series.length > 1 && ChartLegend()}
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={slotColor(s.slot)}
              // Rounded data-end only, anchored to the baseline.
              radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
              maxBarSize={horizontal ? 18 : 44}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </Framed>
  );
}

/** Composition — parts of one whole. */
export function StackedBarChart({
  data,
  xKey,
  series,
  units,
  height = 260,
  className,
  horizontal = false,
}: BaseProps & { horizontal?: boolean }) {
  return (
    <Framed className={className} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout={horizontal ? "vertical" : "horizontal"}
          margin={{ top: 4, right: 16, bottom: 0, left: horizontal ? 8 : -8 }}
        >
          <CartesianGrid stroke={GRID} horizontal={!horizontal} vertical={horizontal} />
          {horizontal ? (
            <>
              <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey={xKey} tick={AXIS} tickLine={false}
                     axisLine={false} width={96} />
            </>
          ) : (
            <>
              <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} />
            </>
          )}
          <Tooltip content={<TooltipBox units={units} />}
                   cursor={{ fill: "var(--ipm-surface-hover)" }} />
          {series.length > 1 && ChartLegend()}
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId="stack"
              fill={slotColor(s.slot)}
              // A 2px surface-coloured edge separates adjacent bands, so a
              // stack reads as distinct quantities rather than one mass.
              stroke="var(--ipm-surface)"
              strokeWidth={2}
              maxBarSize={horizontal ? 26 : 52}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </Framed>
  );
}

/** Signed contributions — a movement broken into its drivers. */
export function DivergingBarChart({
  data,
  xKey,
  valueKey,
  unit,
  height = 260,
  className,
}: {
  data: Record<string, string | number | null>[];
  xKey: string;
  valueKey: string;
  unit?: string;
  height?: number;
  className?: string;
}) {
  return (
    <Framed className={className} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 8 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey={xKey} tick={AXIS} tickLine={false}
                 axisLine={false} width={148} />
          <Tooltip content={<TooltipBox units={{ [valueKey]: unit ?? "" }} />}
                   cursor={{ fill: "var(--ipm-surface-hover)" }} />
          <Bar dataKey={valueKey} radius={[0, 4, 4, 0]} maxBarSize={18}>
            {/* Polarity, not identity: an increase in loss is negative news, a
                decrease is positive. Status colours, never categorical ones. */}
            {data.map((row, i) => (
              <Cell
                key={i}
                fill={
                  Number(row[valueKey]) >= 0 ? "var(--ipm-negative)" : "var(--ipm-positive)"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Framed>
  );
}

/**
 * Transition matrix.
 *
 * A sequential single-hue ramp: one colour, light to dark, encoding magnitude.
 * The diagonal is outlined rather than coloured differently — "stayed put" is a
 * position on the grid, not a different kind of quantity.
 */
export function MatrixHeatmap({
  categories,
  cells,
  className,
  diagonalHint = true,
}: {
  categories: string[];
  /** Row percentages keyed `${from}|${to}`. */
  cells: Record<string, number>;
  className?: string;
  diagonalHint?: boolean;
}) {
  const max = Math.max(1, ...Object.values(cells));

  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-surface px-2 py-1 text-left text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              From \ To
            </th>
            {categories.map((c) => (
              <th
                key={c}
                className="px-1.5 py-1 text-center text-[10px] font-semibold text-text-muted"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {categories.map((from) => (
            <tr key={from}>
              <th className="sticky left-0 z-10 bg-surface px-2 py-1 text-left text-[10px] font-semibold text-text-muted">
                {from}
              </th>
              {categories.map((to) => {
                const value = cells[`${from}|${to}`] ?? 0;
                const intensity = value / max;
                const isDiagonal = from === to;
                return (
                  <td
                    key={to}
                    title={`${from} → ${to}: ${value.toFixed(2)}%`}
                    className={cn(
                      "min-w-11 rounded-[3px] px-1.5 py-1.5 text-center tabular transition-colors",
                      intensity > 0.55 ? "text-white" : "text-text-secondary",
                      diagonalHint && isDiagonal && "ring-1 ring-inset ring-border-strong",
                    )}
                    style={{
                      backgroundColor:
                        value > 0
                          ? `color-mix(in oklab, var(--ipm-chart-1) ${Math.round(
                              12 + intensity * 88,
                            )}%, var(--ipm-surface-sunken))`
                          : "var(--ipm-surface-sunken)",
                    }}
                  >
                    {value > 0 ? value.toFixed(1) : "·"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


/* ------------------------------------------------------- relationships */

/**
 * Two measures against each other, one point per named thing.
 *
 * The form the registry chooses when a result is a RELATIONSHIP rather than a
 * ranking: EAD against coverage, leverage against DSCR. Until now the registry
 * named it and this module could not draw it, so those results silently fell
 * back to a table and the reader was told nothing about why.
 *
 * A point is a row of the result and nothing else. No regression line is drawn
 * and no correlation is quoted: a trend line through a scatter is a claim, and
 * a claim belongs to the analysis, not to the picture of it.
 */
export function ScatterPlot({
  data,
  xKey,
  yKey,
  labelKey,
  units,
  height = 320,
  className,
  onPick,
  emphasis,
}: {
  data: Record<string, string | number | null>[];
  xKey: string;
  yKey: string;
  /** The column naming each point, shown in the tooltip. */
  labelKey?: string;
  units?: Record<string, string>;
  height?: number;
  className?: string;
  /** Clicking a point picks it out. */
  onPick?: (value: string) => void;
  /** How strongly to draw each point, by its label. */
  emphasis?: (value: string) => number;
}) {
  return (
    <Framed className={className} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 8, left: -4 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="0" />
          <XAxis
            type="number"
            dataKey={xKey}
            name={humanise(xKey)}
            tick={AXIS}
            tickLine={false}
            axisLine={{ stroke: GRID }}
          />
          <YAxis
            type="number"
            dataKey={yKey}
            name={humanise(yKey)}
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            width={64}
          />
          <Tooltip
            content={<PointTooltip units={units} labelKey={labelKey} />}
            cursor={{ strokeDasharray: "3 3", stroke: "var(--ipm-border-strong)" }}
          />
          <Scatter
            data={data}
            fill={slotColor(0)}
            onClick={(point) => onPick?.(named(point, labelKey ?? xKey))}
          >
            {data.map((row, index) => (
              <Cell
                key={index}
                fill={slotColor(0)}
                fillOpacity={
                  emphasis?.(String(row[labelKey ?? xKey] ?? "")) ?? 0.75
                }
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </Framed>
  );
}

/**
 * The Risk Landscape: three measures at once, and a governed band as colour.
 *
 * §54's first renderer. Position carries two measures, the point's AREA carries
 * a third, and colour carries a category — a stage, a rating band — so four
 * dimensions are readable at a glance without a rotating cube nobody can read
 * a value off.
 *
 * Area rather than radius, deliberately. Doubling a radius quadruples the ink,
 * and a reader comparing two bubbles reads the ink. Recharts's ZAxis maps the
 * value to area, which is the honest encoding.
 */
export function BubbleChart({
  data,
  xKey,
  yKey,
  sizeKey,
  bandKey,
  labelKey,
  units,
  height = 380,
  className,
  onPick,
  emphasis,
}: {
  data: Record<string, string | number | null>[];
  xKey: string;
  yKey: string;
  sizeKey: string;
  /** The governed category that colours each point — Stage, rating band. */
  bandKey?: string;
  labelKey?: string;
  units?: Record<string, string>;
  height?: number;
  className?: string;
  onPick?: (value: string) => void;
  emphasis?: (value: string) => number;
}) {
  // One colour per band, assigned in the order the bands first appear so a
  // band keeps its colour when a filter changes how many are on screen.
  const bands = React.useMemo(() => {
    if (!bandKey) return [];
    const seen: string[] = [];
    for (const row of data) {
      const value = String(row[bandKey] ?? "");
      if (value && !seen.includes(value)) seen.push(value);
    }
    return seen;
  }, [data, bandKey]);

  return (
    <Framed className={className} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 8, left: -4 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="0" />
          <XAxis
            type="number"
            dataKey={xKey}
            name={humanise(xKey)}
            tick={AXIS}
            tickLine={false}
            axisLine={{ stroke: GRID }}
          />
          <YAxis
            type="number"
            dataKey={yKey}
            name={humanise(yKey)}
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            width={64}
          />
          <ZAxis type="number" dataKey={sizeKey} range={[40, 720]} name={humanise(sizeKey)} />
          <Tooltip
            content={<PointTooltip units={units} labelKey={labelKey} bandKey={bandKey} />}
            cursor={{ strokeDasharray: "3 3", stroke: "var(--ipm-border-strong)" }}
          />
          {bands.length > 1 && ChartLegend()}
          {bands.length > 0 ? (
            bands.map((band, slot) => (
              <Scatter
                key={band}
                name={band}
                data={data.filter((row) => String(row[bandKey as string] ?? "") === band)}
                fill={slotColor(slot)}
                fillOpacity={0.7}
                onClick={(point) => onPick?.(named(point, labelKey ?? xKey))}
              />
            ))
          ) : (
            <Scatter
              data={data}
              fill={slotColor(0)}
              fillOpacity={0.7}
              onClick={(point) => onPick?.(named(point, labelKey ?? xKey))}
            >
              {data.map((row, index) => (
                <Cell
                  key={index}
                  fill={slotColor(0)}
                  fillOpacity={
                    emphasis?.(String(row[labelKey ?? xKey] ?? "")) ?? 0.7
                  }
                />
              ))}
            </Scatter>
          )}
        </ScatterChart>
      </ResponsiveContainer>
    </Framed>
  );
}

/**
 * What a clicked point is called.
 *
 * Recharts hands the click a point descriptor whose shape it does not promise
 * to keep, and whose type has no index signature. Reading it in one guarded
 * place keeps that fact from spreading through three chart components.
 */
function named(point: unknown, key: string): string {
  const record = point as Record<string, unknown> | null;
  const payload = record?.payload as Record<string, unknown> | undefined;
  return String(payload?.[key] ?? record?.[key] ?? "");
}

/**
 * A tooltip for a point, which needs the thing's NAME as well as its figures.
 *
 * The category tooltip labels a point by its x value, which for a scatter is a
 * number — "18.4" tells a reader nothing about which borrower they are hovering.
 */
function PointTooltip({
  active,
  payload,
  units,
  labelKey,
  bandKey,
}: {
  active?: boolean;
  payload?: { payload?: Record<string, unknown>; name?: string; dataKey?: string;
              value?: number; color?: string }[];
  units?: Record<string, string>;
  labelKey?: string;
  bandKey?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload ?? {};
  const name = labelKey ? String(row[labelKey] ?? "") : "";
  const band = bandKey ? String(row[bandKey] ?? "") : "";

  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2 shadow-lg">
      {name && (
        <p className="mb-1 text-xs font-medium text-text-primary">{name}</p>
      )}
      {band && <p className="mb-1 text-[11px] text-text-muted">{band}</p>}
      <div className="space-y-0.5">
        {payload.map((entry, i) => {
          const key = String(entry.dataKey ?? entry.name ?? i);
          return (
            <div key={key} className="flex items-center gap-2 text-xs">
              <span className="text-text-secondary">
                {humanise(String(entry.name ?? key))}
              </span>
              <span className="ml-auto font-medium text-text-primary tabular">
                {byUnit(entry.value, units?.[key])}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
