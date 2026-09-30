/**
 * The remaining governed chart types (§27, VIZ08/10/11/12): stage-migration
 * Sankey, two-dimension heatmap, top-contributor Pareto and the per-exposure
 * change distribution. Pure; the server aggregates (never the whole book in
 * the browser) and these only arrange its cells.
 */

import { count, sar, sarDelta, scaleFor, toScale } from "./format.ts";
import { SEMANTIC, STAGE_COLORS, categorical } from "./palette.ts";
import type { Figure } from "./figures.ts";

export interface Cell {
  x: string | number | null;
  y: string | number | null;
  n: number;
  ead_sar_mn: number | null;
  ecl_sar_mn: number | null;
}

const label = (v: string | number | null) => (v === null || v === undefined ? "(none)" : String(v));

/** Stage migration prior → current as a Sankey. Link values are the chosen
 * measure; every link's customdata carries (prior, current) for click-to-
 * filter, and `reconcile` proves the links sum to the book totals. */
export function stageSankey(cells: Cell[], measure: "n" | "ead_sar_mn" = "ead_sar_mn"): Figure {
  const priors = [...new Set(cells.map((c) => label(c.x)))].sort();
  const currents = [...new Set(cells.map((c) => label(c.y)))].sort();
  const nodes = [...priors.map((p) => `Prior ${p === "(none)" ? "— new" : `Stage ${p}`}`), ...currents.map((c) => `Now Stage ${c}`)];
  const stageColor = (s: string) => STAGE_COLORS[s] ?? SEMANTIC.residual;
  return {
    data: [
      {
        type: "sankey",
        arrangement: "snap",
        node: {
          label: nodes,
          color: [...priors.map(stageColor), ...currents.map(stageColor)],
          pad: 18,
          thickness: 16,
        },
        link: {
          source: cells.map((c) => priors.indexOf(label(c.x))),
          target: cells.map((c) => priors.length + currents.indexOf(label(c.y))),
          value: cells.map((c) => (measure === "n" ? c.n : c.ead_sar_mn ?? 0)),
          color: cells.map((c) => `${stageColor(label(c.y))}66`),
          customdata: cells.map((c) => [label(c.x), label(c.y), count(c.n), sar(c.ead_sar_mn ?? 0)]),
          hovertemplate: "Stage %{customdata[0]} → %{customdata[1]}<br>%{customdata[2]} exposures · EAD %{customdata[3]}<extra></extra>",
        },
      },
    ],
    layout: { margin: { l: 10, r: 10, t: 10, b: 10 } },
  };
}

export function reconcile(cells: Cell[], total: { n: number; ead_sar_mn: number | null }) {
  const n = cells.reduce((a, c) => a + c.n, 0);
  const ead = cells.reduce((a, c) => a + (c.ead_sar_mn ?? 0), 0);
  return { n, ead, ok: n === total.n && Math.abs(ead - (total.ead_sar_mn ?? 0)) <= 1e-6 * Math.max(1, Math.abs(ead)) };
}

/** A two-dimension heatmap (sector × rating, product × score band). */
export function heatmap(cells: Cell[], measure: "ead_sar_mn" | "ecl_sar_mn", opts: { x: string; y: string }): Figure {
  const xs = [...new Set(cells.map((c) => label(c.x)))];
  const ys = [...new Set(cells.map((c) => label(c.y)))].sort();
  const scale = scaleFor(cells.map((c) => c[measure] ?? 0));
  const z = ys.map((y) => xs.map((x) => {
    const c = cells.find((k) => label(k.x) === x && label(k.y) === y);
    return c ? toScale(c[measure] ?? 0, scale) : null;
  }));
  const custom = ys.map((y) => xs.map((x) => {
    const c = cells.find((k) => label(k.x) === x && label(k.y) === y);
    return [x, y, c ? sar(c[measure] ?? 0) : "—", c ? count(c.n) : "0"];
  }));
  return {
    data: [
      {
        type: "heatmap",
        x: xs,
        y: ys,
        z,
        customdata: custom,
        colorscale: [
          [0, "#F8FAFC"],
          [0.5, SEMANTIC.lgd],
          [1, SEMANTIC.increase],
        ],
        colorbar: { title: { text: scale } },
        hoverongaps: false,
        hovertemplate: `${opts.x} %{customdata[0]} · ${opts.y} %{customdata[1]}<br>%{customdata[2]} · %{customdata[3]} exposures<extra></extra>`,
      },
    ],
    layout: { xaxis: { tickangle: -30, automargin: true }, yaxis: { automargin: true, type: "category" }, margin: { l: 80, r: 20, t: 10, b: 110 } },
  };
}

/** Pareto: change by segment (bars, sign-coloured) + cumulative share (line). */
export function pareto(rows: { group: string; change: string; cumulative_share: string | null }[]): Figure {
  const scale = scaleFor(rows.map((r) => Number(r.change)));
  return {
    data: [
      {
        type: "bar",
        name: "ECL change",
        x: rows.map((r) => r.group),
        y: rows.map((r) => toScale(Number(r.change), scale)),
        marker: { color: rows.map((r) => (Number(r.change) >= 0 ? SEMANTIC.increase : SEMANTIC.decrease)) },
        text: rows.map((r) => sarDelta(Number(r.change))),
        textposition: "outside",
        cliponaxis: false,
        customdata: rows.map((r) => [r.group, r.change]),
        hovertemplate: "%{x}: %{text}<br><span style='font-size:10px'>raw %{customdata[1]}</span><extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines+markers",
        name: "Cumulative share",
        x: rows.map((r) => r.group),
        y: rows.map((r) => (r.cumulative_share === null ? null : Number(r.cumulative_share) * 100)),
        yaxis: "y2",
        line: { color: SEMANTIC.baseline, width: 2 },
        hovertemplate: "cumulative %{y:.1f}%<extra></extra>",
      },
    ],
    layout: {
      yaxis: { title: { text: `ECL change (${scale})` } },
      yaxis2: { title: { text: "cumulative %" }, overlaying: "y", side: "right", range: [0, 105] },
      xaxis: { tickangle: -30, automargin: true },
      legend: { orientation: "h", y: -0.35 },
    },
  };
}

/** How the per-exposure change is distributed (count, EAD in hover). */
export function distribution(bins: { label: string; lo: number | null; n: number; ead: string }[]): Figure {
  const moved = bins.filter((b) => b.lo !== null);
  return {
    data: [
      {
        type: "bar",
        x: moved.map((b) => b.label),
        y: moved.map((b) => b.n),
        marker: { color: moved.map((b, i) => ((b.lo ?? 0) < 0 ? SEMANTIC.decrease : categorical(i + 3))) },
        customdata: moved.map((b) => [count(b.n), sar(Number(b.ead))]),
        hovertemplate: "%{x}: %{customdata[0]} exposures · EAD %{customdata[1]}<extra></extra>",
      },
    ],
    layout: { xaxis: { title: { text: "change in the exposure's own ECL" }, tickangle: -30, automargin: true }, yaxis: { title: { text: "exposures" } }, showlegend: false },
  };
}
