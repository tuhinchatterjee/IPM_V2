/**
 * The universal ECL decomposition, drawn. Pure: no React, no fetch.
 *
 * Every decomposition figure in the product is built here from the server's
 * published contract (`gw-decomposition-1.0.0`): the same component id,
 * label, order and colour in the selected scope, the total book, every
 * method, a reopened or shared result, and the CSV. Values are the server's
 * strings; the figure only arranges them. A component the decomposition
 * could not measure stays in the list as N/A with its reason, never dropped
 * or redefined -- the compact view hides it from the chart and says how many
 * it hid, and the table beneath always lists every component.
 */

import { count, pctChange, sar, sarDelta, scaleFor, toScale } from "./format.ts";
import { DRIVERS, SEMANTIC, STAGE_COLORS, driverColor, driverLabel } from "./palette.ts";
import type { Figure } from "./figures.ts";

export type ComponentStatus = "MEASURED" | "ZERO" | "N/A";

export interface DecompositionComponent {
  id: string;
  label: string;
  kind: "total" | "flow" | "driver";
  definition: string;
  order: number;
  value: string | null;
  status: ComponentStatus;
  reason: string;
  detail: Record<string, unknown>[] | Record<string, unknown>;
}

export interface DecompositionScope {
  scope: "selected" | "total";
  label: string;
  opening: string;
  closing: string;
  change: string;
  change_pct: string | null;
  residual: string;
  reconciles: boolean;
  identity: string;
  kpis: {
    opening: string;
    closing: string;
    change: string;
    change_pct: string | null;
    largest_driver: string | null;
    largest_driver_value: string | null;
    stage_2_3_ead_share_pct: string | null;
    exposures: number;
  };
  components: DecompositionComponent[];
}

export interface Decomposition {
  contract_version: string;
  method: string;
  scopes: { selected: DecompositionScope; total: DecompositionScope };
  cross_scope: {
    selected_delta: string;
    rest_of_book_delta: string;
    total_delta: string;
    reconciles: boolean;
    selected_share_of_total_change_pct: string | null;
    rest_of_book_reason: string;
    tolerance: string;
  };
}

const num = (v: string | null | undefined): number => (v === null || v === undefined || v === "" ? 0 : Number(v));

/** The components a chart plots: all of them, or all but N/A (compact). */
export function plotted(scope: DecompositionScope, compact = false): DecompositionComponent[] {
  const ordered = [...scope.components].sort((a, b) => a.order - b.order);
  return compact ? ordered.filter((c) => c.status !== "N/A") : ordered;
}

/**
 * A waterfall with ONE colour per component (Plotly's own waterfall trace
 * colours only by direction, so this is a floating bar: `base` is the
 * running total). Opening and closing are anchored at zero. Every bar is
 * labelled with its signed value; N/A bars are zero-height and say "N/A".
 */
export function waterfall(scope: DecompositionScope, opts: { compact?: boolean; highlight?: string; scale?: ReturnType<typeof scaleFor> } = {}): Figure {
  const rows = plotted(scope, opts.compact);
  const scale = opts.scale ?? scaleFor([num(scope.opening), num(scope.closing)]);
  let running = 0;
  const x: string[] = [];
  const y: number[] = [];
  const base: number[] = [];
  const colors: string[] = [];
  const text: string[] = [];
  const custom: string[][] = [];
  const lines: number[] = [];
  for (const c of rows) {
    const v = num(c.value);
    x.push(driverLabel(c.id));
    if (c.kind === "total") {
      base.push(0);
      y.push(toScale(v, scale));
      running = v;
      text.push(sar(v));
    } else {
      base.push(toScale(v >= 0 ? running : running + v, scale));
      y.push(toScale(Math.abs(v), scale));
      running += v;
      text.push(c.status === "N/A" ? "N/A" : sarDelta(v));
    }
    colors.push(driverColor(c.id));
    lines.push(opts.highlight === c.id ? 3 : 0);
    custom.push([c.id, c.status, c.value ?? "", c.reason || c.definition]);
  }
  // A bridge whose movement is small against its level is unreadable on a
  // zero-based axis (51m on 1.9bn is a hairline). The axis is then cut, and
  // the chart SAYS so -- the anchored opening/closing bars run off its foot.
  const levels = base.map((b, i) => [b, b + y[i]]).flat().filter((_, i) => rows[Math.floor(i / 2)]?.kind !== "total");
  const ends = [y[0] ?? 0, y[y.length - 1] ?? 0];
  const all = [...levels, ...ends];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo;
  const cut = hi > 0 && span > 0 && lo / hi > 0.6;
  const range = cut ? [Math.max(0, lo - span * 1.5), hi + span * 0.6] : undefined;
  return {
    data: [
      {
        type: "bar",
        x,
        y,
        base,
        marker: { color: colors, line: { color: "#0F172A", width: lines } },
        text,
        textposition: "outside",
        cliponaxis: false,
        customdata: custom,
        hovertemplate: "<b>%{x}</b><br>%{text} · %{customdata[1]}<br><span style='font-size:10px'>raw %{customdata[2]}</span><br><span style='font-size:10px'>%{customdata[3]}</span><extra></extra>",
      },
    ],
    layout: {
      showlegend: false,
      yaxis: cut ? { title: { text: `ECL (${scale})` }, range } : { title: { text: `ECL (${scale})` }, rangemode: "tozero" },
      xaxis: { tickangle: -35, automargin: true },
      margin: { l: 60, r: 20, t: cut ? 34 : 20, b: 120 },
      annotations: cut
        ? [{ text: "Axis does not start at zero", xref: "paper", yref: "paper", x: 0, y: 1.08, showarrow: false, font: { size: 10, color: SEMANTIC.baseline }, xanchor: "left" }]
        : [],
    },
  };
}

/** One scale for both scopes, so a bar's height means the same in each. */
export function sharedScale(d: Decomposition) {
  return scaleFor([num(d.scopes.total.opening), num(d.scopes.total.closing), num(d.scopes.selected.closing)]);
}

export interface ComponentRow {
  id: string;
  label: string;
  colour: string;
  selected: string;
  selected_status: ComponentStatus;
  total: string;
  total_status: ComponentStatus;
  definition: string;
  reason: string;
}

/**
 * The table beneath: every taxonomy component, both scopes, in the one
 * order. What the chart plots is a subset of these rows by id.
 */
export function componentTable(d: Decomposition): ComponentRow[] {
  const total = new Map(d.scopes.total.components.map((c) => [c.id, c]));
  return plotted(d.scopes.selected).map((c) => {
    const t = total.get(c.id);
    return {
      id: c.id,
      label: driverLabel(c.id),
      colour: driverColor(c.id),
      selected: c.value ?? "",
      selected_status: c.status,
      total: t?.value ?? "",
      total_status: t?.status ?? "N/A",
      definition: c.definition,
      reason: c.reason || t?.reason || "",
    };
  });
}

/** Both identities, re-checked from the published strings. */
export function identities(d: Decomposition, tolerance = 1e-6) {
  const scope = (s: DecompositionScope) => {
    const moved = s.components.filter((c) => c.kind !== "total").reduce((a, c) => a + num(c.value), 0);
    return Math.abs(num(s.opening) + moved - num(s.closing)) <= tolerance * Math.max(1, Math.abs(num(s.closing)));
  };
  const cross =
    Math.abs(num(d.cross_scope.selected_delta) + num(d.cross_scope.rest_of_book_delta) - num(d.cross_scope.total_delta)) <=
    tolerance * Math.max(1, Math.abs(num(d.cross_scope.total_delta)));
  return { selected: scope(d.scopes.selected), total: scope(d.scopes.total), cross };
}

export interface Kpi {
  label: string;
  value: string;
  raw: string;
}

export function kpis(s: DecompositionScope): Kpi[] {
  return [
    { label: "Opening ECL", value: sar(num(s.opening)), raw: s.opening },
    { label: "Closing ECL", value: sar(num(s.closing)), raw: s.closing },
    { label: "Change", value: sarDelta(num(s.change)), raw: s.change },
    { label: "Change %", value: s.change_pct === null ? "—" : pctChange(num(s.change_pct) / 100), raw: s.change_pct ?? "" },
    { label: "Largest driver", value: s.kpis.largest_driver ?? "—", raw: s.kpis.largest_driver_value ?? "" },
    { label: "Exposures", value: count(s.kpis.exposures), raw: String(s.kpis.exposures) },
  ];
}

export interface MethodResult {
  method: string;
  label: string;
  status: string;
  ran: boolean;
  baseline: string;
  scenario: string | null;
  change: string | null;
  change_pct: string | null;
  reason: string;
  limitations: string[];
}

const METHOD_COLOURS: Record<string, string> = { delta: SEMANTIC.pd, ml: SEMANTIC.macro, user_defined: SEMANTIC.userDefined };

/** Method comparison: one bar per method that ran, its change on one contract. */
export function methodComparison(results: Record<string, MethodResult>): Figure {
  const ran = Object.values(results).filter((r) => r.ran && r.change !== null);
  const scale = scaleFor(ran.map((r) => num(r.change)));
  return {
    data: [
      {
        type: "bar",
        x: ran.map((r) => r.label),
        y: ran.map((r) => toScale(num(r.change), scale)),
        marker: { color: ran.map((r) => METHOD_COLOURS[r.method] ?? SEMANTIC.residual) },
        text: ran.map((r) => sarDelta(num(r.change))),
        textposition: "outside",
        cliponaxis: false,
        customdata: ran.map((r) => [r.method, r.baseline, r.scenario ?? "", r.change ?? ""]),
        hovertemplate: "<b>%{x}</b><br>change %{text}<br>baseline %{customdata[1]} → scenario %{customdata[2]}<extra></extra>",
      },
    ],
    layout: { showlegend: false, yaxis: { title: { text: `ECL change (${scale})` }, zeroline: true } },
  };
}

export interface StageRow {
  stage: string;
  exposures: number;
  ead: string;
  ecl_before: string;
  ecl_after: string;
  change: string;
}

/** Stage ECL before vs after. Stages are frozen unless a rule moved them. */
export function stageBeforeAfter(stages: StageRow[]): Figure {
  const scale = scaleFor(stages.flatMap((s) => [num(s.ecl_before), num(s.ecl_after)]));
  const x = stages.map((s) => `Stage ${s.stage}`);
  return {
    data: [
      {
        type: "bar",
        name: "Before",
        x,
        y: stages.map((s) => toScale(num(s.ecl_before), scale)),
        marker: { color: stages.map((s) => `${STAGE_COLORS[s.stage] ?? SEMANTIC.residual}80`) },
        customdata: stages.map((s) => [sar(num(s.ecl_before)), count(s.exposures)]),
        hovertemplate: "%{x} before: %{customdata[0]} · %{customdata[1]} exposures<extra></extra>",
      },
      {
        type: "bar",
        name: "After",
        x,
        y: stages.map((s) => toScale(num(s.ecl_after), scale)),
        marker: { color: stages.map((s) => STAGE_COLORS[s.stage] ?? SEMANTIC.residual) },
        text: stages.map((s) => sarDelta(num(s.change))),
        textposition: "outside",
        customdata: stages.map((s) => [sar(num(s.ecl_after)), count(s.exposures)]),
        hovertemplate: "%{x} after: %{customdata[0]} · %{text}<extra></extra>",
      },
    ],
    layout: { barmode: "group", yaxis: { title: { text: `ECL (${scale})` } }, legend: { orientation: "h" } },
  };
}

/** The taxonomy ids in the one order (pinned against the server's). */
export const TAXONOMY_ORDER = DRIVERS.map((d) => d.id);
