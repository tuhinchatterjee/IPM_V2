import type { TraceGraph, TraceNode } from "@/lib/api";

import { STATUS, statusOf, worst, type TraceStatus } from "./status";

/**
 * A Trace, as six stages a person can read in seconds.
 *
 * The failure this fixes
 * ----------------------
 * The Trace opened on a graph of forty equally-weighted rectangles. Everything
 * a reader needed was in it and none of it was legible without clicking almost
 * every node. "How was this produced?" is a question with a four-sentence
 * answer, and the product was replying with a diagram.
 *
 * The six stages are the four sentences, plus the two that only a bank asks:
 *
 *   UNDERSTOOD   what the question was taken to mean
 *   DATA         which governed sources were read, and over what window
 *   CONNECTED    how they were joined, and on what declared relationship
 *   CALCULATED   the arithmetic, in the terms the question used
 *   VALIDATED    what was checked before the answer was allowed on screen
 *   ANSWERED     what came out, and how it was expressed
 *
 * Every node lands in exactly one of them. A stage with no nodes does not
 * appear — a single-dataset analysis joined nothing, and showing an empty
 * CONNECTED stage would invite a reader to wonder what went wrong.
 */

export type StageId =
  | "understood"
  | "data"
  | "connected"
  | "calculated"
  | "validated"
  | "answered";

export interface Stage {
  id: StageId;
  title: string;
  /** One sentence, built from the nodes rather than written. */
  summary: string;
  status: TraceStatus;
  /** The number a reader cares about for this stage: sources, joins, checks. */
  count: number;
  /** What `count` counts, in words. */
  counts: string;
  /** How many nodes in this stage are not passing. */
  issues: number;
  nodes: TraceNode[];
}

/** Which stage each node type belongs to. Every type appears exactly once. */
const STAGE_OF: Record<string, StageId> = {
  USER_PROMPT: "understood",
  LLM_INTENT: "understood",
  CAPABILITY: "understood",
  PRIOR_CONTEXT: "understood",
  PLAN_CHANGE: "understood",
  MODEL_ROUTING: "understood",
  PLAN: "understood",

  // A reused result IS where this answer's figures came from. Putting it in
  // "calculated" — which is where an unmapped type lands — hid the whole
  // claim: Story reported "the arithmetic behind the answer" for a turn whose
  // point was that no governed data was read at all.
  PREVIOUS_RESULT: "data",
  REUSED_RESULT: "data",

  DATA_DOMAIN: "data",
  DATASET_FAMILY: "data",
  DATASET: "data",
  VARIABLE: "data",
  FILTER: "data",
  GOVERNED_METADATA: "data",

  JOIN: "connected",
  RELATIONSHIP: "connected",
  RECONCILIATION: "connected",

  MATHEMATICAL_QUERY: "calculated",
  DERIVED_VARIABLE: "calculated",
  TRANSFORMATION: "calculated",
  AGGREGATION: "calculated",
  WINDOW: "calculated",
  ENGINE_FUNCTION: "calculated",
  CERTIFIED_METHOD: "calculated",
  SQL_QUERY: "calculated",
  KERNEL: "calculated",
  CALCULATION: "calculated",

  BUSINESS_INVARIANT: "validated",
  FINGERPRINT: "validated",

  RESULT: "answered",
  LLM_EXPLANATION: "answered",
  VISUALIZATION: "answered",
};

const ORDER: StageId[] = [
  "understood",
  "data",
  "connected",
  "calculated",
  "validated",
  "answered",
];

const TITLES: Record<StageId, string> = {
  understood: "Understood",
  data: "Data",
  connected: "Connected",
  calculated: "Calculated",
  validated: "Validated",
  answered: "Answered",
};

/** A node whose stage is not in the table lands where the reader expects it. */
function stageOf(node: TraceNode): StageId {
  return STAGE_OF[node.type] ?? "calculated";
}

export function stagesOf(graph: TraceGraph): Stage[] {
  const grouped = new Map<StageId, TraceNode[]>();
  for (const node of graph.nodes) {
    const id = stageOf(node);
    const found = grouped.get(id);
    if (found) found.push(node);
    else grouped.set(id, [node]);
  }

  return ORDER.filter((id) => (grouped.get(id)?.length ?? 0) > 0).map((id) => {
    const nodes = grouped.get(id) ?? [];
    const statuses = nodes.map(statusOf);
    const { count, counts } = countFor(id, nodes);
    return {
      id,
      title: TITLES[id],
      summary: summaryFor(id, nodes),
      status: worst(statuses),
      count,
      counts,
      issues: statuses.filter((s) => STATUS[s].attention).length,
      nodes,
    };
  });
}

/* ------------------------------------------------------------- the numbers */

/**
 * The one number that matters for each stage.
 *
 * A step count is the number a graph knows and the number nobody wants. What a
 * reader asks is how many SOURCES were read, how many JOINS were made, how
 * many CHECKS ran — and those are different counts over different nodes.
 */
function countFor(id: StageId, nodes: TraceNode[]): { count: number; counts: string } {
  const of = (type: string) => nodes.filter((n) => n.type === type).length;

  if (id === "data") {
    const reused = nodes.find((n) => n.type === "REUSED_RESULT");
    if (reused && typeof reused.rows_out === "number") {
      return { count: reused.rows_out,
               counts: reused.rows_out === 1 ? "row reused" : "rows reused" };
    }
    const datasets = of("DATASET");
    if (datasets) return { count: datasets, counts: datasets === 1 ? "source" : "sources" };
    return { count: nodes.length, counts: nodes.length === 1 ? "entry" : "entries" };
  }
  if (id === "connected") {
    const joins = of("JOIN") + of("RELATIONSHIP");
    return { count: joins, counts: joins === 1 ? "join" : "joins" };
  }
  if (id === "validated") {
    const checks = checkCounts(nodes);
    if (checks.total) return { count: checks.total, counts: checks.total === 1 ? "check" : "checks" };
  }
  if (id === "answered") {
    const rows = nodes.find((n) => n.type === "RESULT")?.rows_out;
    if (typeof rows === "number") return { count: rows, counts: rows === 1 ? "row" : "rows" };
  }
  return { count: nodes.length, counts: nodes.length === 1 ? "step" : "steps" };
}

function checkCounts(nodes: TraceNode[]): { passed: number; total: number } {
  let passed = 0;
  let total = 0;
  for (const node of nodes) {
    if (node.type !== "BUSINESS_INVARIANT") continue;
    const config = node.config ?? {};
    const checked = config.checked;
    const failed = config.failed;
    if (Array.isArray(checked)) total += checked.length;
    if (Array.isArray(failed)) passed += (Array.isArray(checked) ? checked.length : 0) - failed.length;
    else if (typeof config.passed === "number") passed += config.passed;
  }
  return { passed: Math.max(0, passed), total };
}

/* ----------------------------------------------------------- the sentences */

/**
 * One sentence per stage, assembled from what the nodes recorded.
 *
 * Never written by a model and never generic. "Six governed steps" is what a
 * program says; "IFRS 9 Staging · 2 periods · EAD, stage, sector" is what a
 * reader needed, and every part of it was already stamped on a node.
 */
function summaryFor(id: StageId, nodes: TraceNode[]): string {
  switch (id) {
    case "understood":
      return understood(nodes);
    case "data":
      return data(nodes);
    case "connected":
      return connected(nodes);
    case "calculated":
      return calculated(nodes);
    case "validated":
      return validated(nodes);
    case "answered":
      return answered(nodes);
  }
}

function labelOf(nodes: TraceNode[], type: string): string {
  return nodes.find((n) => n.type === type)?.label?.trim() ?? "";
}

function understood(nodes: TraceNode[]): string {
  const intent = labelOf(nodes, "LLM_INTENT") || labelOf(nodes, "CAPABILITY");
  const prompt = labelOf(nodes, "USER_PROMPT");
  const carried = nodes.find((n) => n.type === "PRIOR_CONTEXT");
  const base = intent || prompt || "The request, as CreditProbe read it.";
  return carried ? `${trimStop(base)}, continuing the previous population.` : base;
}

function data(nodes: TraceNode[]): string {
  // Said first, because it is the whole finding for this kind of turn.
  const reused = nodes.find((n) => n.type === "REUSED_RESULT");
  if (reused) {
    const previous = nodes.find((n) => n.type === "PREVIOUS_RESULT");
    return previous ? `${trimStop(reused.label)} · ${previous.label}` : reused.label;
  }

  const datasets = nodes.filter((n) => n.type === "DATASET").map((n) => n.label);
  const fields = unique(nodes.flatMap((n) => n.fields_used ?? []));
  const filters = nodes.filter((n) => n.type === "FILTER").map((n) => n.label);

  if (datasets.length === 0) {
    return labelOf(nodes, "GOVERNED_METADATA") || "Read from the governed catalogue.";
  }
  const parts = [datasets.slice(0, 3).join(", ")];
  if (datasets.length > 3) parts[0] += ` and ${datasets.length - 3} more`;
  if (fields.length) parts.push(fields.slice(0, 5).join(", "));
  if (filters.length) parts.push(filters.slice(0, 2).join("; "));
  return parts.join(" · ");
}

function connected(nodes: TraceNode[]): string {
  const joins = nodes.filter((n) => n.type === "JOIN" || n.type === "RELATIONSHIP");
  if (joins.length === 0) return "Nothing needed joining.";
  return joins.map((n) => n.label).slice(0, 3).join(" → ");
}

function calculated(nodes: TraceNode[]): string {
  const query = nodes.find((n) => n.type === "MATHEMATICAL_QUERY");
  const formula = query && typeof query.config?.formula === "string" ? query.config.formula : "";
  if (formula) return formula;

  const derived = nodes
    .filter((n) => n.type === "DERIVED_VARIABLE" || n.type === "AGGREGATION")
    .map((n) => n.label);
  if (derived.length) return derived.slice(0, 3).join("; ");
  return labelOf(nodes, "CERTIFIED_METHOD") || labelOf(nodes, "ENGINE_FUNCTION") ||
    "The arithmetic behind the answer.";
}

function validated(nodes: TraceNode[]): string {
  const { passed, total } = checkCounts(nodes);
  if (total) {
    return passed === total
      ? `${passed} of ${total} checks passed.`
      : `${passed} of ${total} checks passed — ${total - passed} did not.`;
  }
  return labelOf(nodes, "FINGERPRINT") || "Recorded so this run can be reproduced.";
}

function answered(nodes: TraceNode[]): string {
  const result = nodes.find((n) => n.type === "RESULT");
  const explained = labelOf(nodes, "LLM_EXPLANATION");
  if (result?.label) {
    return explained ? `${trimStop(result.label)} — ${lower(explained)}` : result.label;
  }
  return explained || "The answer as it was shown.";
}

/* -------------------------------------------------------------- small bits */

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function trimStop(text: string): string {
  return text.replace(/[.·\s]+$/, "");
}

function lower(text: string): string {
  const first = text.trim().split(" ")[0] ?? "";
  // An acronym keeps its capitals, and so does a name with a capital inside
  // it: lowering the C of CreditProbe produced "creditProbe interpretation",
  // which is the product misspelling its own name in its own audit trail.
  if (first.length > 1 && (first === first.toUpperCase() || /[a-z][A-Z]/.test(first))) {
    return text;
  }
  return text.charAt(0).toLowerCase() + text.slice(1);
}
