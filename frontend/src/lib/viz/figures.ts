/**
 * Pure Plotly figure builders shared by every workspace surface.
 *
 * No DOM, no network: node unit tests pin them. Hover text is pre-formatted by
 * `format.ts` (so a hover and a table say the same thing) and every hover also
 * carries the raw value. `customdata` always holds the governed key of the
 * mark, which is what click-to-filter and View-data act on.
 */

import { bps, byUnit, count, pct, sar, sarDelta, scaleFor, toScale } from "./format.ts";
import { CATEGORICAL, SEMANTIC, STAGE_COLORS, categorical } from "./palette.ts";

export interface Figure {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
}

export interface Point {
  period: string;
  value: number | null;
}

function fmtUnit(value: number | null, unit: string): string {
  if (value === null || value === undefined) return "—";
  if (unit === "SAR_mn") return sar(value);
  if (unit === "fraction") return pct(value);
  if (unit === "count") return count(value);
  return byUnit(value, unit);
}

/** A card sparkline: one trace, no axes, last point emphasised. */
export function sparkline(points: Point[], unit: string, color: string = SEMANTIC.pd): Figure {
  const x = points.map((p) => p.period);
  const y = points.map((p) => p.value);
  return {
    data: [
      {
        type: "scatter",
        mode: "lines+markers",
        x,
        y,
        line: { color, width: 2, shape: "spline" },
        marker: { size: points.map((_, i) => (i === points.length - 1 ? 7 : 3)), color },
        fill: "tozeroy",
        fillcolor: `${color}1A`,
        customdata: points.map((p) => fmtUnit(p.value, unit)),
        hovertemplate: "%{x}: %{customdata}<extra></extra>",
      },
    ],
    layout: {
      margin: { l: 4, r: 4, t: 4, b: 4 },
      xaxis: { visible: false },
      yaxis: { visible: false },
      showlegend: false,
    },
  };
}

/** A governed trend: one or more metric series over periods. */
export function trend(
  series: { name: string; points: Point[]; unit: string; color?: string; dash?: string }[],
  opts: { yTitle?: string } = {},
): Figure {
  const moneyScale = scaleFor(
    series.filter((s) => s.unit === "SAR_mn").flatMap((s) => s.points.map((p) => p.value ?? 0)),
  );
  return {
    data: series.map((s, i) => ({
      type: "scatter",
      mode: "lines+markers",
      name: s.name,
      x: s.points.map((p) => p.period),
      y: s.points.map((p) =>
        p.value === null ? null : s.unit === "SAR_mn" ? toScale(p.value, moneyScale) : s.unit === "fraction" ? p.value * 100 : p.value,
      ),
      line: { color: s.color ?? categorical(i), width: 2.5, dash: s.dash ?? "solid" },
      marker: { size: 6 },
      customdata: s.points.map((p) => [fmtUnit(p.value, s.unit), p.value === null ? "" : String(p.value)]),
      hovertemplate: `<b>${s.name}</b><br>%{x}: %{customdata[0]}<br><span style="font-size:10px">raw %{customdata[1]}</span><extra></extra>`,
    })),
    layout: {
      yaxis: {
        title: {
          text:
            opts.yTitle ??
            (series[0]?.unit === "SAR_mn" ? moneyScale : series[0]?.unit === "fraction" ? "%" : series[0]?.unit ?? ""),
        },
      },
      hovermode: "x unified",
    },
  };
}

/** Horizontal contribution bars: sign-coloured, sign-labelled, clickable. */
export function contributions(
  rows: { label: string; value: number; display?: string }[],
  unit: string,
  opts: { dimension?: string } = {},
): Figure {
  const sorted = [...rows].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, 12).reverse();
  const moneyScale = unit === "SAR_mn" ? scaleFor(sorted.map((r) => r.value)) : null;
  return {
    data: [
      {
        type: "bar",
        orientation: "h",
        y: sorted.map((r) => r.label),
        x: sorted.map((r) =>
          moneyScale ? toScale(r.value, moneyScale) : unit === "fraction" ? r.value * 100 : r.value,
        ),
        marker: {
          color: sorted.map((r) => (r.value >= 0 ? SEMANTIC.increase : SEMANTIC.decrease)),
          line: { width: 0 },
        },
        text: sorted.map((r) => r.display ?? (unit === "SAR_mn" ? sarDelta(r.value) : fmtUnit(r.value, unit))),
        textposition: "outside",
        cliponaxis: false,
        customdata: sorted.map((r) => [r.label, String(r.value)]),
        hovertemplate: `${opts.dimension ?? ""} %{customdata[0]}<br>%{text}<br><span style="font-size:10px">raw %{customdata[1]}</span><extra></extra>`,
      },
    ],
    layout: {
      xaxis: { title: { text: moneyScale ?? (unit === "fraction" ? "%" : unit) }, zeroline: true },
      margin: { l: 150, r: 60, t: 10, b: 40 },
      showlegend: false,
    },
  };
}

/** Stage mix (EAD) as a stacked bar with counts in hover. */
export function stageMix(rows: { stage: number | null; n: number; ead: number; ecl: number }[]): Figure {
  const scale = scaleFor(rows.map((r) => r.ead ?? 0));
  return {
    data: rows.map((r) => ({
      type: "bar",
      name: `Stage ${r.stage ?? "?"}`,
      x: [toScale(r.ead ?? 0, scale)],
      y: ["EAD"],
      orientation: "h",
      marker: { color: STAGE_COLORS[String(r.stage)] ?? SEMANTIC.residual },
      customdata: [[sar(r.ead), count(r.n), sar(r.ecl)]],
      hovertemplate: `Stage ${r.stage}: %{customdata[0]} EAD · %{customdata[1]} exposures · ECL %{customdata[2]}<extra></extra>`,
    })),
    layout: {
      barmode: "stack",
      height: 110,
      margin: { l: 40, r: 10, t: 6, b: 30 },
      xaxis: { title: { text: scale } },
      legend: { orientation: "h", y: -0.6 },
    },
  };
}

/** Category bars (EAD/ECL by a dimension), clickable to filter. */
export function categoryBars(
  rows: { value: string | number | null; n: number; ead_sar_mn?: number; ecl_sar_mn?: number }[],
  measure: "ead_sar_mn" | "ecl_sar_mn",
  opts: { dimension: string; selected?: (string | number)[] } = { dimension: "" },
): Figure {
  const scale = scaleFor(rows.map((r) => r[measure] ?? 0));
  const selected = new Set((opts.selected ?? []).map(String));
  return {
    data: [
      {
        type: "bar",
        x: rows.map((r) => String(r.value ?? "(empty)")),
        y: rows.map((r) => toScale(r[measure] ?? 0, scale)),
        marker: {
          color: rows.map((r, i) =>
            selected.size && !selected.has(String(r.value)) ? SEMANTIC.context : CATEGORICAL[i % CATEGORICAL.length],
          ),
        },
        customdata: rows.map((r) => [String(r.value), sar(r[measure] ?? 0), count(r.n), String(r[measure] ?? 0)]),
        hovertemplate: `${opts.dimension} %{customdata[0]}<br>%{customdata[1]} · %{customdata[2]} exposures<br><span style="font-size:10px">raw %{customdata[3]} SAR million</span><extra></extra>`,
      },
    ],
    layout: {
      yaxis: { title: { text: `${measure === "ead_sar_mn" ? "EAD" : "ECL"} (${scale})` } },
      showlegend: false,
    },
  };
}

export { bps };
