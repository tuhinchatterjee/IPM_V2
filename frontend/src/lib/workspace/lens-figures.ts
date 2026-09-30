/**
 * Pure figure builders for Lenses: every chart is a governed metric value
 * the server rendered. No fetch; node tests pin them.
 */

import { SEMANTIC, STAGE_COLORS, categorical } from "../viz/palette.ts";
import { count, sar } from "../viz/format.ts";
import type { Figure } from "../viz/figures.ts";
import { axisTitle, breakdownBars, formatValue, plotValue } from "./metric-figures.ts";
import type { RenderedVisual } from "./lenses.ts";

export interface Kpi {
  title: string;
  value: string;
  raw: string;
  delta: string;
  tone: "good" | "bad" | "neutral";
  metric: string;
  note?: string;
}

/** A KPI tile: value, movement against the prior period, and whether the
 * movement is good or bad by the metric's governed direction (colour AND a
 * signed label, never colour alone). */
export function kpiTile(v: RenderedVisual): Kpi {
  const unit = v.unit ?? "";
  let delta = "";
  let tone: Kpi["tone"] = "neutral";
  if (v.value != null && v.prior != null) {
    const move = v.value - v.prior;
    delta = unit === "fraction" ? `${move >= 0 ? "+" : "−"}${Math.abs(move * 100).toFixed(2)} pp` : `${move >= 0 ? "+" : "−"}${formatValue(Math.abs(move), unit)}`;
    if (v.direction === "lower_is_better") tone = move > 0 ? "bad" : move < 0 ? "good" : "neutral";
    else if (v.direction === "higher_is_better") tone = move < 0 ? "bad" : move > 0 ? "good" : "neutral";
    delta = `${delta} vs ${v.prior_period ?? "prior"}`;
  }
  return {
    title: v.title,
    value: v.value == null ? "—" : formatValue(v.value, unit),
    raw: v.value == null ? "" : String(v.value),
    delta,
    tone,
    metric: `${v.metric_id} v${v.metric_version}`,
    note: v.note,
  };
}

export function sparkFigure(v: RenderedVisual): Figure | null {
  const pts = v.spark ?? [];
  if (pts.length < 2) return null;
  return {
    data: [{ type: "scatter", mode: "lines", x: pts.map((p) => p.period), y: pts.map((p) => plotValue(p.value, v.unit ?? "")), line: { color: SEMANTIC.pd, width: 2 }, hoverinfo: "x+y" }],
    layout: { margin: { l: 2, r: 2, t: 2, b: 2 }, xaxis: { visible: false }, yaxis: { visible: false }, showlegend: false, height: 40 },
  };
}

/** Trend: click a point to move the Lens to that period. */
export function trendFigure(v: RenderedVisual): Figure {
  const series = v.series ?? [];
  const unit = series[0]?.unit ?? "";
  return {
    data: series.map((s, i) => ({
      type: "scatter",
      mode: "lines+markers",
      name: `${s.name} (${s.metric_id})`,
      x: s.points.map((p) => p.period),
      y: s.points.map((p) => plotValue(p.value, s.unit)),
      line: { color: categorical(i), width: 2.5 },
      customdata: s.points.map((p) => [p.period, formatValue(p.value, s.unit), String(p.value)]),
      hovertemplate: `<b>${s.name}</b> %{customdata[0]}: %{customdata[1]}<br><span style="font-size:10px">raw %{customdata[2]} · click to move the Lens here</span><extra></extra>`,
    })),
    layout: { yaxis: { title: { text: axisTitle(unit) } }, xaxis: { type: "category" }, legend: { orientation: "h", y: -0.25 }, hovermode: "closest" },
  };
}

/** Breakdown / stage mix: click or box-select categories to cross-filter. */
export function breakdownFigure(v: RenderedVisual): Figure {
  const groups = v.groups ?? [];
  if (v.type === "stage_mix") {
    const sorted = [...groups].sort((a, b) => String(a.dimension).localeCompare(String(b.dimension)));
    return {
      data: [
        {
          type: "bar",
          x: sorted.map((g) => `Stage ${g.dimension}`),
          y: sorted.map((g) => plotValue(g.value, v.unit ?? "")),
          marker: { color: sorted.map((g) => STAGE_COLORS[String(g.dimension)] ?? SEMANTIC.residual) },
          customdata: sorted.map((g) => [String(g.dimension), formatValue(g.value, v.unit ?? ""), String(g.rows ?? "")]),
          hovertemplate: "Stage %{customdata[0]}: %{customdata[1]} · %{customdata[2]} rows<extra></extra>",
        },
      ],
      layout: { yaxis: { title: { text: axisTitle(v.unit ?? "") } }, showlegend: false },
    };
  }
  return breakdownBars(groups, v.unit ?? "", v.group_by ?? "");
}

export function topOwnersFigure(v: RenderedVisual): Figure {
  const rows = [...(v.rows ?? [])].reverse() as { owner: string; name: string; ead: number; ecl: number; n: number }[];
  const total = v.total_ead ?? 0;
  return {
    data: [
      {
        type: "bar",
        orientation: "h",
        y: rows.map((r) => String(r.name ?? r.owner)),
        x: rows.map((r) => r.ead),
        marker: { color: rows.map((_, i) => categorical(i)) },
        text: rows.map((r) => (total ? `${((r.ead / total) * 100).toFixed(2)}%` : "")),
        textposition: "outside",
        cliponaxis: false,
        customdata: rows.map((r) => [String(r.owner), sar(r.ead), sar(r.ecl), count(r.n)]),
        hovertemplate: "%{y}<br>EAD %{customdata[1]} · ECL %{customdata[2]} · %{customdata[3]} exposures<br><span style='font-size:10px'>click to investigate %{customdata[0]}</span><extra></extra>",
      },
    ],
    layout: { xaxis: { title: { text: "EAD (SAR million)" } }, margin: { l: 170, r: 60, t: 10, b: 40 }, showlegend: false },
  };
}

/** Results / alerts / sensitivities: one bar per governed group. */
export function groupsFigure(v: RenderedVisual): Figure {
  const groups = (v.groups ?? []).filter((g) => g.value != null).slice(0, 15);
  return {
    data: [
      {
        type: "bar",
        orientation: "h",
        y: groups.map((g) => String(g.dimension).slice(0, 48)),
        x: groups.map((g) => plotValue(g.value, v.unit ?? "")),
        marker: { color: groups.map((g) => ((g.value ?? 0) >= 0 ? SEMANTIC.increase : SEMANTIC.decrease)) },
        customdata: groups.map((g) => [String(g.object_id ?? ""), formatValue(g.value, v.unit ?? "")]),
        hovertemplate: "%{y}: %{customdata[1]}<extra></extra>",
      },
    ],
    layout: { xaxis: { title: { text: axisTitle(v.unit ?? "") }, zeroline: true }, margin: { l: 260, r: 30, t: 10, b: 40 }, showlegend: false },
  };
}

/** The cross-filter a click on this visual produces, or null. */
export function clickFilter(v: RenderedVisual, customdata: unknown): { column: string; op: "in"; values: (string | number)[]; domain: string } | null {
  if (!Array.isArray(customdata)) return null;
  const value = customdata[0];
  if (v.type === "breakdown" && v.group_by) return { column: v.group_by, op: "in", values: [String(value)], domain: v.domain };
  if (v.type === "stage_mix") return { column: "stage", op: "in", values: [Number(value)], domain: v.domain };
  return null;
}
