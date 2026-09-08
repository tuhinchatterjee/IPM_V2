/**
 * When an Early Warning answer earns a chart, and when it does not.
 *
 * A chart attached to every answer stops meaning anything. Worse, it is
 * actively misleading on the answers that are not about shape: a bar chart
 * beside an explanation of the notch model invites the reader to look for a
 * pattern in something that has none, and a chart beside a recommendation
 * competes with the recommendation for attention.
 *
 * So a chart is shown when the answer is genuinely about shape — a trend, a
 * distribution, a comparison, a concentration or a movement — and withheld
 * when the answer is a methodology explanation, an evidence request, a
 * recommendation, a simple factual lookup or an escalation decision.
 *
 * Pure so it can be tested under the repo's `node --test` convention.
 */

/** The scopes the Early Warning answerer returns. */
export type EwsScope =
  | "portfolio"
  | "level"
  | "group"
  | "borrower"
  | "layer"
  | "evidence"
  | "movement"
  | "comparison"
  | "diagnosis"
  | "action"
  | "escalation"
  | "methodology"
  | "refusal"
  | "";

/** What a chart would be showing, when one is warranted. */
export type ChartKind = "trend" | "distribution" | "comparison" | "movement";

/**
 * Scopes whose answers are about shape. Everything absent from this map is
 * answered in words, and adding a chart to it would be decoration.
 */
const CHART_FOR: Partial<Record<EwsScope, ChartKind>> = {
  portfolio: "trend", // a score over fifteen months
  movement: "movement", // period on period, by layer
  level: "comparison", // groups ranked against each other
  comparison: "comparison", // two groups side by side
  group: "distribution", // the population inside one group
  diagnosis: "distribution", // how the population partitions
  borrower: "trend", // this obligor's own score history
};

/**
 * Scopes that must never carry a chart, stated rather than implied by
 * absence — these are the ones somebody would otherwise be tempted to
 * decorate.
 */
const NEVER: EwsScope[] = [
  "methodology", // explaining the matrix is not a data shape
  "evidence", // one signal's reading; a chart of one point says nothing
  "action", // a recommendation competes with its own chart
  "escalation", // a routing decision is a sentence, not a picture
  "layer", // a handful of node scores reads better as a list
  "refusal",
  "",
];

export function chartFor(scope: EwsScope): ChartKind | null {
  if (NEVER.includes(scope)) return null;
  return CHART_FOR[scope] ?? null;
}

export function showsChart(scope: EwsScope): boolean {
  return chartFor(scope) !== null;
}

/**
 * Whether a set of rows is worth drawing at all.
 *
 * Even a scope that warrants a chart does not warrant one over two points:
 * a "trend" of two months is a pair of numbers, and drawing it implies a
 * shape the data cannot support.
 */
export function worthDrawing(kind: ChartKind | null, rowCount: number): boolean {
  if (kind === null) return false;
  if (kind === "trend") return rowCount >= 3;
  return rowCount >= 2;
}
