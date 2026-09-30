/**
 * Pure helpers for the Metric Catalogue: format a governed value by its unit
 * and draw its breakdown / trend. No fetch; node tests pin them.
 */

import { categorical, SEMANTIC } from "../viz/palette.ts";
import { count, pct, sar } from "../viz/format.ts";
import type { Figure } from "../viz/figures.ts";

export function formatValue(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (unit) {
    case "SAR_mn":
      return sar(value);
    case "fraction":
      return pct(value);
    case "pct_points":
      return `${value.toFixed(2)}%`;
    case "count":
      return count(value);
    case "hours":
      return `${value.toFixed(1)} h`;
    case "notches":
      return `${value >= 0 ? "+" : ""}${value.toFixed(2)} notches`;
    default:
      return value.toFixed(4);
  }
}

/** Plot scale: fractions as %, money in SAR million, everything else raw. */
export function plotValue(value: number | null | undefined, unit: string): number | null {
  if (value === null || value === undefined) return null;
  return unit === "fraction" ? value * 100 : value;
}

export function axisTitle(unit: string): string {
  return unit === "fraction" ? "%" : unit === "SAR_mn" ? "SAR million" : unit;
}

/** Breakdown bars: one bar per dimension value, clickable (customdata[0] is the value). */
export function breakdownBars(groups: { dimension: string; value: number | null; rows?: number }[], unit: string, dimension: string): Figure {
  const sorted = [...groups].filter((g) => g.value !== null).sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  return {
    data: [
      {
        type: "bar",
        x: sorted.map((g) => String(g.dimension)),
        y: sorted.map((g) => plotValue(g.value, unit)),
        marker: { color: sorted.map((_, i) => categorical(i)) },
        customdata: sorted.map((g) => [String(g.dimension), formatValue(g.value, unit), String(g.rows ?? ""), String(g.value)]),
        hovertemplate: `${dimension} %{customdata[0]}<br>%{customdata[1]} · %{customdata[2]} rows<br><span style="font-size:10px">raw %{customdata[3]}</span><extra></extra>`,
      },
    ],
    layout: { yaxis: { title: { text: axisTitle(unit) } }, xaxis: { automargin: true, tickangle: -30 }, showlegend: false },
  };
}

/** Trend per book: one line per book, same metric id/version. */
export function metricTrend(series: { name: string; points: { period: string; value: number | null }[] }[], unit: string): Figure {
  return {
    data: series.map((s, i) => ({
      type: "scatter",
      mode: "lines+markers",
      name: s.name,
      x: s.points.map((p) => p.period),
      y: s.points.map((p) => plotValue(p.value, unit)),
      line: { color: i === 0 ? SEMANTIC.pd : SEMANTIC.macro, width: 2.5 },
      customdata: s.points.map((p) => [formatValue(p.value, unit), String(p.value)]),
      hovertemplate: `<b>${s.name}</b> %{x}: %{customdata[0]}<br><span style="font-size:10px">raw %{customdata[1]}</span><extra></extra>`,
    })),
    layout: { yaxis: { title: { text: axisTitle(unit) } }, hovermode: "x unified" },
  };
}

/** A dimension the grid can filter on (drill-to-rows), vs a non-grid one. */
export function gridDimension(dim: string, domain: string): string | null {
  if (dim === "sector|product") return domain === "corporate" ? "sector" : "product";
  const nonGrid = ["scenario", "method", "baseline", "result", "factor", "parameter", "segment", "field", "dataset", "component", "lens", "rule", "metric", "severity"];
  return nonGrid.includes(dim) ? null : dim;
}
