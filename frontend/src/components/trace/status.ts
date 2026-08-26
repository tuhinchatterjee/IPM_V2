import type { TraceNode } from "@/lib/api";

/**
 * What a Trace node's status means, and how a reader is told.
 *
 * Never colour alone
 * ------------------
 * A CRO reviewing a Trace has to be able to find the one step that went wrong.
 * Roughly one man in twelve cannot reliably separate the amber from the red, so
 * every status carries three signals: a **word**, a **mark**, and a colour.
 * Remove the colour and the map still reads.
 *
 * Six statuses, and why REPAIRED is one of them
 * ---------------------------------------------
 * The orchestrator is allowed one repair attempt when a plan fails validation.
 * A step that was repaired PASSED — but it did not pass first time, and an
 * auditor asking "did anything have to be corrected to produce this number?"
 * deserves an answer that is not buried. Folding it into PASSED would be true
 * and would hide the interesting thing.
 */

export type TraceStatus =
  | "passed"
  | "warning"
  | "failed"
  | "repaired"
  | "skipped"
  | "stale";

export interface StatusPresentation {
  /** The word. This is what a screen reader announces. */
  label: string;
  /** A single character, so status survives at any zoom and in monochrome. */
  mark: string;
  /** Tailwind text colour token. */
  text: string;
  /** Tailwind background token for a chip or a node edge. */
  surface: string;
  /** Border token. */
  border: string;
  /** Whether this status is worth a reader's attention first. */
  attention: boolean;
}

export const STATUS: Record<TraceStatus, StatusPresentation> = {
  passed: {
    label: "Passed",
    mark: "✓",
    text: "text-positive",
    surface: "bg-positive-muted",
    border: "border-positive/30",
    attention: false,
  },
  warning: {
    label: "Warning",
    mark: "!",
    text: "text-warning",
    surface: "bg-surface-warning",
    border: "border-warning/40",
    attention: true,
  },
  failed: {
    label: "Failed",
    mark: "✕",
    text: "text-negative",
    surface: "bg-surface-critical",
    border: "border-negative/50",
    attention: true,
  },
  repaired: {
    label: "Repaired",
    mark: "↻",
    text: "text-ai",
    surface: "bg-ai-muted",
    border: "border-ai-edge",
    attention: true,
  },
  skipped: {
    label: "Skipped",
    mark: "–",
    text: "text-text-muted",
    surface: "bg-surface-sunken",
    border: "border-border",
    attention: false,
  },
  stale: {
    label: "Stale",
    mark: "◷",
    text: "text-warning",
    surface: "bg-surface-warning",
    border: "border-warning/30",
    attention: true,
  },
};

/**
 * The status of one node, read from what execution actually stamped.
 *
 * Deliberately derived rather than trusted: the backend records a status string
 * for the node's own execution, and separately records warnings and an error.
 * A node that "succeeded" while recording three warnings is not something a
 * reader should have to notice for themselves.
 */
export function statusOf(node: TraceNode): TraceStatus {
  const raw = String(node.status ?? "").toLowerCase();
  if (node.error) return "failed";
  if (raw.includes("fail") || raw.includes("error")) return "failed";
  if (raw.includes("repair")) return "repaired";
  if (raw.includes("skip") || raw.includes("not_run")) return "skipped";
  if (raw.includes("stale")) return "stale";
  if (node.warnings?.length) return "warning";
  return "passed";
}

/** The worst status in a set, for a lane summary or the health map. */
export function worst(statuses: TraceStatus[]): TraceStatus {
  const order: TraceStatus[] = [
    "failed",
    "repaired",
    "warning",
    "stale",
    "skipped",
    "passed",
  ];
  for (const candidate of order) {
    if (statuses.includes(candidate)) return candidate;
  }
  return "passed";
}
