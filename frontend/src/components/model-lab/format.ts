/**
 * Pure formatting for the lab. No React, so `node --test` covers it.
 *
 * The one rule: an unknown value is shown as unknown, with its reason. It is
 * never rendered as 0, and a missing check is never a green badge.
 */

import type { Metric } from "./client";

export const STAGES = ["S1", "S2", "S3", "S4"] as const;

export const STAGE_NAMES: Record<string, string> = {
  S1: "Understand & ground",
  S2: "Plan, author & submit",
  S3: "Review, repair & continue",
  S4: "Interpret & present",
};

/** Text labels, so colour is never the only carrier of meaning. */
export function statusLabel(status: string | null | undefined): string {
  const s = String(status ?? "UNKNOWN");
  const map: Record<string, string> = {
    PASS: "Pass",
    FAIL: "Fail",
    PARTIAL: "Partial",
    NOT_OBSERVED: "Not observed",
    NOT_REACHED: "Not reached",
    UNKNOWN: "Unknown",
    NOT_SEPARATELY_OBSERVABLE: "Shared span (not separable)",
    SUPPORTED: "Supported",
    CONTRADICTED: "Contradicted",
    UNSUPPORTED: "Unsupported",
    UNVERIFIABLE: "Needs review",
    EVIDENCE_INCOMPLETE: "Evidence incomplete",
    FROM_FROZEN_RECORD: "From frozen record",
    "NOT_FACTUAL/QUALIFIED": "Qualified / not factual",
  };
  return map[s] ?? s.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
}

/** A semantic tone for a status; the label always accompanies it. */
export function statusTone(
  status: string | null | undefined,
): "positive" | "negative" | "warning" | "muted" {
  const s = String(status ?? "");
  if (["PASS", "SUPPORTED", "COMPLETED", "READY_E2E", "READY", "COMPLETE"].includes(s))
    return "positive";
  if (["FAIL", "CONTRADICTED", "FAILED", "INCOMPATIBLE_PROTOCOL"].includes(s))
    return "negative";
  if (
    [
      "PARTIAL",
      "UNSUPPORTED",
      "WAITING_USER",
      "NEEDS_APPROVAL",
      "BLOCKED",
      "BLOCKED_RESOURCE",
      "INTERRUPTED",
    ].includes(s)
  )
    return "warning";
  return "muted";
}

export function isMetric(x: unknown): x is Metric {
  return Boolean(x && typeof x === "object" && "status" in (x as object) && "unit" in (x as object));
}

/** "412 ms (measured)" or "unknown — non-streaming route". Never "0". */
export function formatMetric(m: Metric | undefined | null): string {
  if (!m) return "unknown";
  if (m.value === null || m.value === undefined) {
    return `unknown${m.missing_reason ? ` — ${m.missing_reason}` : ""}`;
  }
  const v =
    typeof m.value === "number"
      ? m.unit === "ms"
        ? m.value >= 10000
          ? `${(m.value / 1000).toFixed(1)} s`
          : `${Math.round(m.value)} ms`
        : m.unit === "USD"
          ? `$${m.value.toFixed(4)}`
          : Number.isInteger(m.value)
            ? m.value.toLocaleString("en-US")
            : m.value.toFixed(2)
      : String(m.value);
  const unit = m.unit === "ms" || m.unit === "USD" ? "" : ` ${m.unit}`;
  return `${v}${unit} (${m.status.toLowerCase()})`;
}

/** Tooltip text: definition, units, source, status. */
export function metricHelp(m: Metric | undefined | null): string {
  if (!m) return "No measurement.";
  const parts = [
    m.definition && `Definition: ${m.definition}.`,
    `Unit: ${m.unit}.`,
    `Status: ${m.status}.`,
    m.source && `Source: ${m.source}.`,
    m.missing_reason && `Missing because: ${m.missing_reason}.`,
  ];
  return parts.filter(Boolean).join(" ");
}

/** A rate with its denominator, or N/A when nothing was assessed. */
export function formatRate(
  r: { numerator: number; denominator: number } | undefined,
): string {
  if (!r || !r.denominator) return "N/A (nothing assessed)";
  return `${r.numerator}/${r.denominator} (${Math.round((100 * r.numerator) / r.denominator)}%)`;
}

/** Blind labels for review: stable per comparison, reveal-on-demand. */
export function blindLabel(index: number): string {
  return `Model ${String.fromCharCode(65 + (index % 26))}`;
}

export function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 14)}…` : id;
}

/** Terminal states for polling. */
export const SETTLED = new Set(["COMPLETE", "PARTIAL", "CANCELLED", "BLOCKED"]);
