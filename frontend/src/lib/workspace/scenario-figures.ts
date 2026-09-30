/**
 * Pure helpers for the Scenario Library screens: no React, no fetch, so the
 * node test runner exercises them directly. Every number shown comes from the
 * server's preview; these helpers only arrange it.
 */

import { categoryBars, stageMix, type Figure } from "../viz/figures.ts";
import type { AssessedComponent, Component, Overlap, Preview, Resolution } from "./scenarios.ts";

export type Tone = "positive" | "warning" | "negative" | "info" | "default";

export function readinessTone(readiness: string): Tone {
  if (readiness === "READY_FOR_CONFIRMATION") return "positive";
  if (readiness === "READY_WITH_USER_DEFINED_INPUTS") return "warning";
  if (readiness === "BLOCKED") return "negative";
  return "default";
}

export function readinessText(readiness: string): string {
  return (
    {
      READY_FOR_CONFIRMATION: "Ready for confirmation",
      READY_WITH_USER_DEFINED_INPUTS: "Needs user-defined inputs",
      BLOCKED: "Blocked",
    }[readiness] ?? readiness
  );
}

export function statusTone(status: string): Tone {
  if (status === "DIRECT" || status === "TRANSLATED" || status === "RESOLVED" || status === "RESOLVED_BY_GOVERNED_RULE" || status === "NO_CONFLICT")
    return "positive";
  if (status === "UNSUPPORTED" || status === "NEEDS_POLICY" || status === "INVALID_POLICY") return "negative";
  if (status === "NEEDS_USER_MAPPING" || status === "TRANSLATION_ONLY" || status === "USER_DEFINED") return "warning";
  return "default";
}

export function methodTone(status: string): Tone {
  if (status === "AVAILABLE") return "positive";
  if (status === "UNAVAILABLE" || status === "NOT_COMPATIBLE") return "negative";
  if (status === "PARTIAL" || status === "NEEDS_ASSUMPTION") return "warning";
  return "default";
}

export const SEVERITY_TONE: Record<string, Tone> = {
  upside: "positive",
  mild: "info",
  moderate: "warning",
  severe: "negative",
};

/** Overlaps a person still has to decide. */
export function pendingOverlaps(preview: Pick<Preview, "overlaps">): Overlap[] {
  return preview.overlaps.filter((o) => o.status === "NEEDS_POLICY" || o.status === "INVALID_POLICY");
}

/**
 * The resolutions to send: only overlaps with an explicit choice. An
 * overlap left blank is left out, never defaulted -- the server keeps it
 * blocking.
 */
export function resolutionsFrom(
  overlaps: Overlap[],
  choices: Record<string, string>,
  orders: Record<string, string[]> = {},
): Record<string, Resolution> {
  const out: Record<string, Resolution> = {};
  for (const o of overlaps) {
    if (!o.overlap_id) continue;
    const policy = choices[o.overlap_id];
    if (!policy) continue;
    out[o.overlap_id] = { policy, order: orders[o.overlap_id] ?? [o.a, o.b], chosen_by: "user" };
  }
  return out;
}

export interface MatrixRow {
  component_id: string;
  label: string;
  kind: string;
  status: string;
  variables: string;
  entities: number;
  delta: string;
  ml: string;
  user_defined: string;
  source: string;
  reason: string;
}

/** The component matrix (§30.3): one row per component. */
export function componentMatrix(preview: Pick<Preview, "components">, definition?: { components: Component[] }): MatrixRow[] {
  const byId = new Map((definition?.components ?? []).map((c) => [c.component_id, c]));
  return preview.components.map((c: AssessedComponent) => {
    const src = byId.get(c.component_id)?.source;
    return {
      component_id: c.component_id,
      label: c.label,
      kind: c.kind,
      status: c.status,
      variables: c.families.join(", ") || "—",
      entities: c.population.entities,
      delta: c.methods.delta,
      ml: c.methods.ml,
      user_defined: c.methods.user_defined,
      source: src ? `${src.scenario} v${src.version} · ${src.component_id}` : "",
      reason: c.reason ?? "",
    };
  });
}

export interface DerivedRow {
  field: string;
  change: string;
  from: number | null;
  to: number | null;
  slope: number | null;
  slope_unit: string;
  lag: number | null;
}

/** A macro/collateral translation's derived parameter moves, one row each. */
export function derivedRows(translation: Record<string, unknown> | null): DerivedRow[] {
  const derived = (translation?.derived as Record<string, unknown>[] | undefined) ?? [];
  return derived
    .filter((d) => typeof d.parameter_baseline === "number")
    .map((d) => ({
      field: String(d.field),
      change: `${Number(d.value) >= 0 ? "+" : ""}${Number(d.value).toFixed(3)} pp`,
      from: d.parameter_baseline as number,
      to: d.parameter_scenario as number,
      slope: (d.native_derivative as number) ?? null,
      slope_unit: String(d.native_derivative_unit ?? ""),
      lag: (d.lag as number) ?? null,
    }));
}

/** Stage mix of the scope, as the shared Plotly figure. */
export function scopeStageFigure(preview: Pick<Preview, "scope">): Figure {
  return stageMix(
    preview.scope.summary.stage_mix.map((s) => ({ stage: s.stage, n: s.n, ead: s.ead ?? 0, ecl: s.ecl ?? 0 })),
  );
}

/** Rating (Corporate) or score band (Retail) mix of the scope, EAD. */
export function scopeBandFigure(preview: Pick<Preview, "scope">): Figure {
  const s = preview.scope.summary;
  return categoryBars(
    s.band_mix.map((b) => ({ value: b.band, n: b.n, ead_sar_mn: b.ead })),
    "ead_sar_mn",
    { dimension: s.band_dimension.replace(/_/g, " ") },
  );
}

/** A new component of a kind, with the fields that kind needs. */
export function blankComponent(kind: Component["kind"], domain: "corporate" | "retail"): Component {
  switch (kind) {
    case "parameter":
      return { kind, field: "pd_pit_12m", operation: "relative_pct", value: "20" };
    case "utilisation":
      return { kind, operation: "relative_pct", value: "10" };
    case "rating":
      return { kind, operation: "notches", value: "1" };
    case "score":
      return { kind, score_type: "BEHAVIOURAL", operation: "points", value: "-30" };
    case "delinquency":
      return { kind, operation: "bands", value: "1" };
    case "macro":
      return { kind, factor_id: "MEV03", operation: "basis_points", value: "100" };
    case "collateral":
      return { kind, asset: domain === "corporate" ? "commercial_property" : "residential_property", operation: "relative_pct", value: "-15" };
    case "overlay":
      return { kind, operation: "relative_pct", value: "5" };
  }
}

/** Which component kinds make sense on a book. */
export function kindsFor(domain: "corporate" | "retail"): Component["kind"][] {
  return domain === "corporate"
    ? ["parameter", "utilisation", "rating", "macro", "collateral", "overlay"]
    : ["parameter", "utilisation", "score", "delinquency", "macro", "collateral", "overlay"];
}
