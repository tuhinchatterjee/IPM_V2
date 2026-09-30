/**
 * Pure figure builders for Trace > LLM Exchange (no DOM, no network), so the
 * node unit tests can pin them.
 */

import { SEMANTIC, categorical } from "../viz/palette.ts";
import type { ExchangeCall, GrowthRow } from "./llm-exchange.ts";

// ---- pure figure builders (unit-tested) --------------------------------

export function growthFigure(rows: GrowthRow[]): { data: Record<string, unknown>[]; layout: Record<string, unknown> } {
  const x = rows.map((r) => `Call ${r.seq}`);
  return {
    data: [
      {
        type: "bar",
        name: "Request size (KB, measured)",
        x,
        y: rows.map((r) => r.total_bytes / 1024),
        marker: { color: SEMANTIC.ccf },
        hovertemplate: "%{x}<br>%{y:.1f} KB measured<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines+markers",
        name: "Input tokens (provider-reported)",
        x,
        y: rows.map((r) => r.input_tokens_exact),
        yaxis: "y2",
        line: { color: SEMANTIC.pd, width: 2 },
        hovertemplate: "%{x}<br>%{y:,} input tokens (exact)<extra></extra>",
      },
    ],
    layout: {
      yaxis: { title: { text: "Request size (KB)" } },
      yaxis2: { title: { text: "Input tokens" }, overlaying: "y", side: "right", showgrid: false },
      barmode: "group",
    },
  };
}

export const COMPONENT_ORDER = [
  "system",
  "tool_schema",
  "user_text",
  "assistant_text",
  "tool_call",
  "tool_result",
  "tool_choice",
  "output_config",
];

export function compositionFigure(calls: ExchangeCall[]): {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
} {
  const components = Array.from(
    new Set(calls.flatMap((c) => Object.keys(c.context_composition?.totals_bytes ?? {}))),
  ).sort((a, b) => {
    const ia = COMPONENT_ORDER.indexOf(a);
    const ib = COMPONENT_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return {
    data: components.map((component, i) => ({
      type: "bar",
      name: component.replace(/_/g, " "),
      x: calls.map((c) => `Call ${c.seq}`),
      y: calls.map((c) => (c.context_composition?.totals_bytes?.[component] ?? 0) / 1024),
      marker: { color: categorical(i) },
      hovertemplate: `%{x}<br>${component}: %{y:.1f} KB (measured)<extra></extra>`,
    })),
    layout: { barmode: "stack", yaxis: { title: { text: "KB (measured bytes)" } } },
  };
}
