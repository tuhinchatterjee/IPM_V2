/**
 * The macro-sensitivity tornado (MAC07): one horizontal bar pair per
 * (MEV, risk parameter), ranked by swing, from the server's governed rows.
 * Pure: it arranges the server's numbers and never recomputes, rescales or
 * re-signs one. The risk parameter is explicit in every label and colour
 * (PD violet, LGD amber); a SIGN_REVIEW row is marked, never corrected.
 */

import { SEMANTIC } from "./palette.ts";
import type { Figure } from "./figures.ts";

export interface TornadoRow {
  factor_id: string;
  factor_name: string;
  series_id: string | null;
  shock_label: string;
  conversion_up?: string | null;
  parameter: string;
  parameter_label: string;
  family: "pd" | "lgd";
  coefficient: number | null;
  native_derivative: number;
  native_derivative_unit: string;
  sign: "+" | "-";
  parameter_baseline: number | null;
  up_pp: number;
  down_pp: number | null;
  swing_pp: number;
  readiness: string;
  method: string | null;
  lag: number;
  train_start: string | null;
  train_end: string | null;
  training_periods: number | null;
  sign_stability: number | null;
  sign_review: string | null;
  warnings: string[];
}

export const rowLabel = (r: TornadoRow) => `${r.factor_name} → ${r.parameter_label}${r.sign_review ? " ⚠" : ""}`;

const fmt = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`);

/** The hover text of one bar: every governed field the row carries. */
export function hover(r: TornadoRow, side: "down" | "up"): string {
  const pp = side === "up" ? r.up_pp : r.down_pp;
  return [
    `<b>${r.factor_name}</b> (${r.factor_id}${r.series_id ? ` · ${r.series_id}` : ""})`,
    `shock ${side === "up" ? "up" : "down"} ${r.shock_label}${r.conversion_up && side === "up" ? ` (${r.conversion_up})` : ""}`,
    `affects <b>${r.parameter_label}</b>: ${fmt(pp)} pp`,
    `coefficient ${r.coefficient ?? "—"} · slope ${r.native_derivative.toPrecision(4)} ${r.native_derivative_unit}`,
    `sign ${r.sign} (as fitted) · ${r.readiness}${r.sign_stability !== null ? ` · sign stable in ${(r.sign_stability * 100).toFixed(0)}% of resamples` : ""}`,
    `method ${r.method ?? "—"} · lag ${r.lag} · window ${r.train_start ?? "?"}–${r.train_end ?? "?"}${r.training_periods ? ` (${r.training_periods} periods)` : ""}`,
    ...(r.sign_review ? [`⚠ ${r.sign_review}`] : []),
  ].join("<br>");
}

export function tornado(rows: TornadoRow[]): Figure {
  // Plotly draws the first category at the bottom; the largest swing goes on top.
  const ordered = [...rows].reverse();
  const y = ordered.map(rowLabel);
  const colour = (r: TornadoRow) => (r.family === "lgd" ? SEMANTIC.lgd : SEMANTIC.pd);
  const bar = (side: "down" | "up") => ({
    type: "bar",
    orientation: "h",
    name: side === "down" ? "Down shock" : "Up shock",
    y,
    x: ordered.map((r) => (side === "up" ? r.up_pp : (r.down_pp ?? 0))),
    base: 0,
    marker: {
      color: ordered.map(colour),
      opacity: side === "up" ? 0.95 : 0.5,
      line: { color: ordered.map((r) => (r.sign_review ? SEMANTIC.increase : "rgba(0,0,0,0)")), width: 2 },
    },
    customdata: ordered.map((r) => [r.factor_id, r.parameter, hover(r, side)]),
    hovertemplate: "%{customdata[2]}<extra></extra>",
  });
  return {
    data: [bar("down"), bar("up")],
    layout: {
      barmode: "overlay",
      xaxis: { title: { text: "parameter movement (percentage points)" }, zeroline: true, zerolinewidth: 2 },
      yaxis: { automargin: true, type: "category" },
      legend: { orientation: "h", y: -0.15 },
      margin: { l: 220, r: 20, t: 10, b: 60 },
    },
  };
}
