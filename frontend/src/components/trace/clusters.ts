import type { TraceGraph, TraceNode } from "@/lib/api";

import { STATUS, statusOf, worst, type TraceStatus } from "./status.ts";

/**
 * The detailed Lineage view, as eight governed clusters rather than forty
 * equally-weighted rectangles.
 *
 * What the Story view could not do
 * --------------------------------
 * Story answers "how was this produced?" in six sentences, and that is the
 * right default. But a reviewer who then opens Lineage is asking a different
 * question — *show me the actual dependency graph* — and the graph was still a
 * wall. Grouping it in Story did not group it here, because Story is a list of
 * rows and the DAG is a DAG: the nodes were laid out in bands, but a band is a
 * hint about position, not a thing you can collapse, focus, isolate or roll an
 * issue up into.
 *
 * A cluster here is a real subgraph. It has a boundary, a summary you can read
 * without opening it, a health that its members roll up into, and inter-cluster
 * edges that survive when its internals are hidden.
 *
 * Why these eight
 * ---------------
 * They are the eight questions an auditor asks, in the order they ask them:
 *
 *   1 REQUEST & UNDERSTANDING   what was asked, and what it was taken to mean
 *   2 CONVERSATION & SCOPE      what was inherited from the turns before it
 *   3 GOVERNED DATA             which sources were read, and over what window
 *   4 RELATIONSHIPS & ALIGNMENT how they were joined, on what declared link
 *   5 DERIVATIONS & CALCULATION what was computed FROM the data
 *   6 EXECUTION                 what actually ran
 *   7 VALIDATION & EVIDENCE     what was checked before it was allowed on screen
 *   8 ANSWER & INTERPRETATION   what came out, and what was said about it
 *
 * The split between 5 and 6 is the one worth defending: a derivation is a
 * DEFINITION (ECL coverage is ECL over EAD) and an execution is an EVENT (this
 * statement ran, against these files, in 240ms). An auditor disputing a figure
 * disputes one or the other, never both at once, and a Trace that mixes them
 * makes them read every node to find out which kind they are looking at.
 */

export type ClusterId =
  | "request"
  | "conversation"
  | "data"
  | "relationships"
  | "derivations"
  | "execution"
  | "validation"
  | "answer";

export const CLUSTER_ORDER: ClusterId[] = [
  "request",
  "conversation",
  "data",
  "relationships",
  "derivations",
  "execution",
  "validation",
  "answer",
];

export const CLUSTER_TITLES: Record<ClusterId, string> = {
  request: "Request & understanding",
  conversation: "Conversation & scope",
  data: "Governed data",
  relationships: "Relationships & alignment",
  derivations: "Derivations & calculation",
  execution: "Execution",
  validation: "Validation & evidence",
  answer: "Answer & interpretation",
};

/** What each cluster is FOR, shown when it is collapsed and on hover. */
export const CLUSTER_PURPOSE: Record<ClusterId, string> = {
  request: "What was asked, and what CreditProbe took it to mean.",
  conversation: "What this turn inherited from the ones before it.",
  data: "The governed sources that were read, and the window they were read over.",
  relationships: "How those sources were aligned, on which declared relationship.",
  derivations: "What was computed from the data, and by which definition.",
  execution: "What actually ran, and what it ran against.",
  validation: "What was checked before the answer was allowed on screen.",
  answer: "What came out, and what was said about it.",
};

/**
 * Which cluster each node type belongs to. Every type appears exactly once.
 *
 * A type missing from this table lands in `derivations`, which is the middle of
 * the graph — visible, and obviously in the wrong place, rather than silently
 * absent.
 */
export const CLUSTER_OF: Record<string, ClusterId> = {
  USER_PROMPT: "request",
  LLM_INTENT: "request",
  CAPABILITY: "request",
  PLAN: "request",
  MODEL_ROUTING: "request",

  PRIOR_CONTEXT: "conversation",
  PLAN_CHANGE: "conversation",
  PREVIOUS_RESULT: "conversation",
  REUSED_RESULT: "conversation",

  DATA_DOMAIN: "data",
  DATASET_FAMILY: "data",
  DATASET: "data",
  VARIABLE: "data",
  FILTER: "data",
  GOVERNED_METADATA: "data",

  RELATIONSHIP: "relationships",
  JOIN: "relationships",

  DERIVED_VARIABLE: "derivations",
  TRANSFORMATION: "derivations",
  AGGREGATION: "derivations",
  WINDOW: "derivations",
  CALCULATION: "derivations",
  MATHEMATICAL_QUERY: "derivations",

  SQL_QUERY: "execution",
  KERNEL: "execution",
  ENGINE_FUNCTION: "execution",
  CERTIFIED_METHOD: "execution",

  BUSINESS_INVARIANT: "validation",
  RECONCILIATION: "validation",
  FINGERPRINT: "validation",

  RESULT: "answer",
  LLM_EXPLANATION: "answer",
  VISUALIZATION: "answer",
};

export function clusterOf(node: TraceNode): ClusterId {
  return CLUSTER_OF[node.type] ?? "derivations";
}

/** Above this many nodes a cluster opens collapsed. */
export const COLLAPSE_ABOVE = 4;

export interface Cluster {
  id: ClusterId;
  title: string;
  purpose: string;
  /** One sentence built from the nodes, never written by a model. */
  summary: string;
  nodes: TraceNode[];
  /** Datasets or operations this cluster represents, for the collapsed card. */
  represents: string[];
  status: TraceStatus;
  /** Nodes in this cluster whose status wants attention. */
  issues: TraceNode[];
  /** Milliseconds, summed over the nodes that recorded one. Null when none did. */
  durationMs: number | null;
  rowsIn: number | null;
  rowsOut: number | null;
}

export function clustersOf(graph: TraceGraph): Cluster[] {
  const grouped = new Map<ClusterId, TraceNode[]>();
  for (const node of graph.nodes ?? []) {
    const id = clusterOf(node);
    const found = grouped.get(id);
    if (found) found.push(node);
    else grouped.set(id, [node]);
  }

  return CLUSTER_ORDER.filter((id) => (grouped.get(id)?.length ?? 0) > 0).map((id) => {
    const nodes = grouped.get(id) ?? [];
    const statuses = nodes.map(statusOf);
    const durations = nodes
      .map((n) => n.duration_ms)
      .filter((d): d is number => typeof d === "number");
    return {
      id,
      title: CLUSTER_TITLES[id],
      purpose: CLUSTER_PURPOSE[id],
      summary: summaryFor(id, nodes),
      nodes,
      represents: representsFor(id, nodes),
      status: worst(statuses),
      issues: nodes.filter((n) => STATUS[statusOf(n)].attention),
      durationMs: durations.length ? durations.reduce((a, b) => a + b, 0) : null,
      rowsIn: firstNumber(nodes.map((n) => n.rows_in)),
      rowsOut: lastNumber(nodes.map((n) => n.rows_out)),
    };
  });
}

/**
 * Which clusters open collapsed.
 *
 * Big ones do; a cluster carrying an issue never does, whatever its size. The
 * whole point of rolling issues up is that a reader is taken TO the problem,
 * and a collapsed box saying "1 failed" that they then have to open is one
 * click closer than before rather than an answer.
 */
export function defaultCollapsed(clusters: Cluster[]): Set<ClusterId> {
  return new Set(
    clusters
      .filter((c) => c.issues.length === 0 && c.nodes.length > COLLAPSE_ABOVE)
      .map((c) => c.id),
  );
}

/**
 * Every node worth a reader's attention, in the order a reader should meet
 * them: cluster order, and within a cluster the worst first.
 */
export function issuesIn(clusters: Cluster[]): { node: TraceNode; cluster: ClusterId }[] {
  const rank: Record<TraceStatus, number> = {
    failed: 0,
    repaired: 1,
    warning: 2,
    stale: 3,
    skipped: 4,
    passed: 5,
  };
  return clusters.flatMap((cluster) =>
    [...cluster.issues]
      .sort((a, b) => rank[statusOf(a)] - rank[statusOf(b)])
      .map((node) => ({ node, cluster: cluster.id })),
  );
}

/** Nodes whose label or type matches a search term, for the node finder. */
export function search(graph: TraceGraph, term: string): TraceNode[] {
  const needle = term.trim().toLowerCase();
  if (!needle) return [];
  return (graph.nodes ?? []).filter((node) => {
    const haystack = [
      node.label,
      node.type.replace(/_/g, " "),
      node.dataset ?? "",
      ...(node.fields_used ?? []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(needle);
  });
}

/* -------------------------------------------------------------- the numbers */

function firstNumber(values: (number | null)[]): number | null {
  for (const value of values) if (typeof value === "number") return value;
  return null;
}

function lastNumber(values: (number | null)[]): number | null {
  for (let i = values.length - 1; i >= 0; i -= 1) {
    const value = values[i];
    if (typeof value === "number") return value;
  }
  return null;
}

function labelsOf(nodes: TraceNode[], type: string): string[] {
  return nodes.filter((n) => n.type === type).map((n) => n.label.trim()).filter(Boolean);
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

/**
 * What a collapsed cluster says it contains.
 *
 * Datasets for the data cluster, relationships for the join cluster, the
 * operations themselves elsewhere. "6 steps" is what a program knows; "IFRS 9
 * Staging, Portfolio Facility, Customer Ratings" is what the reader came for.
 */
function representsFor(id: ClusterId, nodes: TraceNode[]): string[] {
  if (id === "data") {
    const datasets = unique([
      ...labelsOf(nodes, "DATASET"),
      ...nodes.map((n) => n.dataset ?? ""),
    ]);
    return datasets.length ? datasets : unique(labelsOf(nodes, "GOVERNED_METADATA"));
  }
  if (id === "relationships") {
    return unique([...labelsOf(nodes, "RELATIONSHIP"), ...labelsOf(nodes, "JOIN")]);
  }
  if (id === "validation") {
    return unique(nodes.map((n) => n.label.trim()));
  }
  return unique(nodes.map((n) => n.type.replace(/_/g, " ").toLowerCase()));
}

/* ------------------------------------------------------------ the sentences */

function summaryFor(id: ClusterId, nodes: TraceNode[]): string {
  switch (id) {
    case "request":
      return (
        labelsOf(nodes, "LLM_INTENT")[0] ??
        labelsOf(nodes, "CAPABILITY")[0] ??
        labelsOf(nodes, "USER_PROMPT")[0] ??
        CLUSTER_PURPOSE.request
      );
    case "conversation": {
      const reused = nodes.find((n) => n.type === "REUSED_RESULT");
      if (reused) return reused.label;
      const carried = labelsOf(nodes, "PRIOR_CONTEXT")[0];
      const changed = labelsOf(nodes, "PLAN_CHANGE")[0];
      return [carried, changed].filter(Boolean).join(" · ") || CLUSTER_PURPOSE.conversation;
    }
    case "data": {
      const datasets = unique(labelsOf(nodes, "DATASET"));
      const fields = unique(nodes.flatMap((n) => n.fields_used ?? []));
      const filters = labelsOf(nodes, "FILTER");
      if (!datasets.length) {
        return labelsOf(nodes, "GOVERNED_METADATA")[0] ?? "Read from the governed catalogue.";
      }
      const parts = [
        datasets.slice(0, 3).join(", ") +
          (datasets.length > 3 ? ` and ${datasets.length - 3} more` : ""),
      ];
      if (fields.length) parts.push(`${fields.length} fields`);
      if (filters.length) parts.push(filters.slice(0, 2).join("; "));
      return parts.join(" · ");
    }
    case "relationships": {
      const joins = unique([...labelsOf(nodes, "RELATIONSHIP"), ...labelsOf(nodes, "JOIN")]);
      return joins.length ? joins.slice(0, 3).join(" → ") : "Nothing needed joining.";
    }
    case "derivations": {
      const formula = nodes
        .map((n) => (typeof n.config?.formula === "string" ? n.config.formula : ""))
        .find(Boolean);
      if (formula) return formula;
      const derived = unique([
        ...labelsOf(nodes, "DERIVED_VARIABLE"),
        ...labelsOf(nodes, "AGGREGATION"),
      ]);
      return derived.length ? derived.slice(0, 3).join("; ") : CLUSTER_PURPOSE.derivations;
    }
    case "execution": {
      const kernels = labelsOf(nodes, "KERNEL");
      const engine = labelsOf(nodes, "ENGINE_FUNCTION")[0] ?? labelsOf(nodes, "CERTIFIED_METHOD")[0];
      const sql = nodes.find((n) => n.type === "SQL_QUERY");
      const parts = [engine, sql ? sql.label : "", ...kernels].filter(Boolean);
      return parts.length ? parts.slice(0, 3).join(" · ") : CLUSTER_PURPOSE.execution;
    }
    case "validation": {
      const { passed, total } = checkCounts(nodes);
      if (total) {
        return passed === total
          ? `${passed} of ${total} checks passed.`
          : `${passed} of ${total} checks passed — ${total - passed} did not.`;
      }
      return labelsOf(nodes, "FINGERPRINT")[0] ?? "Recorded so this run can be reproduced.";
    }
    case "answer": {
      const result = labelsOf(nodes, "RESULT")[0];
      const explained = labelsOf(nodes, "LLM_EXPLANATION")[0];
      return result || explained || CLUSTER_PURPOSE.answer;
    }
  }
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
