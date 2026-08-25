import type { TraceGraph, TraceNode } from "@/lib/api";

/**
 * Turning a stored Trace into something that can be drawn.
 *
 * All of this is pure: given the same graph it produces the same coordinates,
 * every time. That matters more than it sounds — a reasoning map that rearranges
 * itself between two visits cannot be discussed in a meeting, and force-directed
 * layouts do exactly that. The backend already computes dependency layers, so
 * the depth of a node is a fact rather than a simulation, and this file only
 * decides how far apart to place things.
 */

export interface Placed {
  id: string;
  node: TraceNode;
  x: number;
  y: number;
  /** Which analysis step this belongs to; null for the interpretive frame. */
  step: number | null;
  stepTitle: string;
  /** A collapsed stand-in for a whole step, rather than one recorded node. */
  collapsed: boolean;
  containedIds: string[];
}

export interface PlacedEdge {
  id: string;
  source: string;
  target: string;
}

export interface Layout {
  nodes: Placed[];
  edges: PlacedEdge[];
  width: number;
  height: number;
}

export const COLUMN_WIDTH = 240;
export const ROW_HEIGHT = 104;
//: Bands need more room than step lanes: a band holds a row of cards and its
//: name, and cards that nearly touch read as one block.
export const SWIMLANE_HEIGHT = 132;
export const NODE_WIDTH = 208;
export const NODE_HEIGHT = 74;

/**
 * Which horizontal band each kind of step belongs in.
 *
 * The order is the order an analysis actually happens in, which is also the
 * order a reader checks it: what was asked, how it was read, what data was
 * used, how it was joined, what was derived from it, what ran, what came back,
 * and what CreditProbe made of that.
 */
export const LAYER_LANE: Record<string, number> = {
  USER_PROMPT: 0,
  LLM_INTENT: 0,
  CAPABILITY: 0,
  PLAN: 0,

  DATA_DOMAIN: 1,
  DATASET_FAMILY: 1,
  DATASET: 1,
  GOVERNED_METADATA: 1,
  VARIABLE: 1,

  RELATIONSHIP: 2,
  JOIN: 2,
  FILTER: 2,

  DERIVED_VARIABLE: 3,
  TRANSFORMATION: 3,
  AGGREGATION: 3,
  WINDOW: 3,
  CALCULATION: 3,

  SQL_QUERY: 4,
  KERNEL: 4,
  ENGINE_FUNCTION: 4,
  CERTIFIED_METHOD: 4,
  MATHEMATICAL_QUERY: 4,

  RECONCILIATION: 5,
  FINGERPRINT: 5,
  RESULT: 5,

  LLM_EXPLANATION: 6,
  VISUALIZATION: 6,
};

export const LAYER_COUNT = 7;

/** What each band is called, for the legend down the side of the canvas. */
export const LAYER_LABELS: string[] = [
  "Request",
  "Governed data",
  "Relationships",
  "Derivations",
  "Execution",
  "Result",
  "Interpretation",
];

export function stepOf(node: TraceNode): number | null {
  const value = (node.config as Record<string, unknown>)?._step;
  return typeof value === "number" ? value : null;
}

export function stepTitleOf(node: TraceNode): string {
  const value = (node.config as Record<string, unknown>)?._step_title;
  return typeof value === "string" ? value : "";
}

/** Every distinct analysis step present in the graph, in order. */
export function stepsIn(graph: TraceGraph): { step: number; title: string; nodes: number }[] {
  const seen = new Map<number, { step: number; title: string; nodes: number }>();
  for (const node of graph.nodes) {
    const step = stepOf(node);
    if (step === null) continue;
    const entry = seen.get(step);
    if (entry) entry.nodes += 1;
    else seen.set(step, { step, title: stepTitleOf(node) || `Step ${step}`, nodes: 1 });
  }
  return [...seen.values()].sort((a, b) => a.step - b.step);
}

/** The node that best represents a whole step when it is collapsed. */
function representative(nodes: TraceNode[]): TraceNode {
  return (
    nodes.find((n) => n.type === "ENGINE_FUNCTION") ??
    nodes.find((n) => n.type === "RESULT") ??
    nodes[nodes.length - 1] ??
    nodes[0]
  );
}

/**
 * Place every node.
 *
 * Depth comes from the dependency layers the executor recorded. The vertical
 * position is by analysis step, so a four-step investigation reads as four
 * parallel lanes between the plan and the findings rather than as one tangle.
 */
export function layoutGraph(graph: TraceGraph, collapsed: Set<number>): Layout {
  const depth = new Map<string, number>();
  graph.layers.forEach((layer, index) => {
    for (const id of layer) depth.set(id, index);
  });
  // A node the layers did not mention (only possible on a malformed graph) is
  // still drawn rather than silently dropped.
  for (const node of graph.nodes) if (!depth.has(node.id)) depth.set(node.id, 0);

  // --- collapse -----------------------------------------------------------
  const hidden = new Set<string>();
  const standIn = new Map<string, string>(); // real id -> collapsed node id
  const collapsedNodes: Placed[] = [];

  for (const step of collapsed) {
    const members = graph.nodes.filter((n) => stepOf(n) === step);
    if (members.length === 0) continue;
    const id = `step-${step}`;
    for (const member of members) {
      hidden.add(member.id);
      standIn.set(member.id, id);
    }
    const rep = representative(members);
    const rows = members.reduce<number | null>(
      (best, n) => (n.rows_out !== null && (best === null || n.rows_out > best) ? n.rows_out : best),
      null,
    );
    collapsedNodes.push({
      id,
      node: {
        ...rep,
        id,
        label: stepTitleOf(rep) || rep.label,
        rows_out: rows,
        warnings: members.flatMap((m) => m.warnings),
        error: members.find((m) => m.error)?.error ?? null,
      },
      x: 0,
      y: 0,
      step,
      stepTitle: stepTitleOf(rep),
      collapsed: true,
      containedIds: members.map((m) => m.id),
    });
  }

  // --- edges, rewritten through the collapsed stand-ins --------------------
  const edgeKeys = new Set<string>();
  const edges: PlacedEdge[] = [];
  for (const edge of graph.edges) {
    const source = standIn.get(edge.source) ?? edge.source;
    const target = standIn.get(edge.target) ?? edge.target;
    if (source === target) continue;
    const key = `${source}->${target}`;
    if (edgeKeys.has(key)) continue;
    edgeKeys.add(key);
    edges.push({ id: key, source, target });
  }

  // --- depth for the collapsed stand-ins ----------------------------------
  // The earliest depth inside the step, not the average: a collapsed analysis
  // begins where its first read began. Using the average would scatter the four
  // steps of one investigation across four columns and widen the map for no
  // reason, which is exactly what makes a collapsed view worth having.
  for (const placed of collapsedNodes) {
    const depths = placed.containedIds.map((id) => depth.get(id) ?? 0);
    depth.set(placed.id, Math.min(...depths));
  }

  const visible: Placed[] = [
    ...graph.nodes
      .filter((n) => !hidden.has(n.id))
      .map((node) => ({
        id: node.id,
        node,
        x: 0,
        y: 0,
        step: stepOf(node),
        stepTitle: stepTitleOf(node),
        collapsed: false,
        containedIds: [node.id],
      })),
    ...collapsedNodes,
  ];

  // --- lanes ---------------------------------------------------------------
  //
  // Two layouts, because two kinds of trace exist.
  //
  // A multi-step investigation lanes by STEP: each registered analysis gets a
  // row, and the interpretive frame sits between them.
  //
  // A composed analysis has one step and thirty-odd nodes, so laning by step
  // puts every one of them on a single line — which is what made a rich trace
  // render as an unreadable ribbon. It lanes by GOVERNANCE LAYER instead: the
  // question and its reading, then the data, then the joins, then the
  // derivations, then the query, then the result and its reading. The picture
  // then shows what kind of thing each step is as well as what fed it.
  const stepNumbers = [...new Set(visible.map((p) => p.step).filter((s): s is number => s !== null))]
    .sort((a, b) => a - b);
  const byStep = stepNumbers.length > 1;

  const laneOf = new Map<number, number>();
  stepNumbers.forEach((step, index) => laneOf.set(step, index));
  const laneCount = Math.max(byStep ? stepNumbers.length : LAYER_COUNT, 1);
  const centreLane = (laneCount - 1) / 2;

  const laneFor = (placed: (typeof visible)[number]): number => {
    if (byStep) {
      return placed.step !== null ? (laneOf.get(placed.step) ?? 0) : centreLane;
    }
    return LAYER_LANE[placed.node.type] ?? centreLane;
  };

  // Re-index depths so there are no empty columns after a collapse.
  const usedDepths = [...new Set(visible.map((p) => depth.get(p.id) ?? 0))].sort((a, b) => a - b);
  const column = new Map(usedDepths.map((d, i) => [d, i]));

  const ordered = visible.sort((a, b) => {
    const da = column.get(depth.get(a.id) ?? 0) ?? 0;
    const db = column.get(depth.get(b.id) ?? 0) ?? 0;
    if (da !== db) return da - db;
    return (a.step ?? -1) - (b.step ?? -1) || a.id.localeCompare(b.id);
  });

  if (byStep) {
    // Step lanes: the column IS the dependency depth, because a reader
    // following a multi-analysis investigation is following the order things
    // ran in across all of them.
    const occupied = new Map<string, number>();
    for (const placed of ordered) {
      const col = column.get(depth.get(placed.id) ?? 0) ?? 0;
      const lane = laneFor(placed);
      const key = `${col}:${lane}`;
      const stack = occupied.get(key) ?? 0;
      occupied.set(key, stack + 1);
      placed.x = col * COLUMN_WIDTH;
      placed.y = lane * ROW_HEIGHT + stack * (NODE_HEIGHT + 12);
    }
  } else {
    // Swimlanes: each band packs left to right in its own dependency order.
    //
    // A composed analysis is a chain twenty-odd steps long, and laying it out
    // by global depth makes a picture twenty-odd columns wide — legible only
    // at a zoom where the labels are decoration. Packing within the band turns
    // the same graph into six short rows, which is the shape it actually has:
    // read some data, join it, derive from it, run it, report it.
    const nextColumn = new Map<number, number>();
    for (const placed of ordered) {
      const lane = laneFor(placed);
      const col = nextColumn.get(lane) ?? 0;
      nextColumn.set(lane, col + 1);
      placed.x = col * COLUMN_WIDTH;
      placed.y = lane * SWIMLANE_HEIGHT;
    }
  }

  const width = (Math.max(...visible.map((p) => p.x), 0) + NODE_WIDTH) || NODE_WIDTH;
  const height = (Math.max(...visible.map((p) => p.y), 0) + NODE_HEIGHT) || NODE_HEIGHT;
  return { nodes: visible, edges, width, height };
}

/** Everything upstream of a node — what it depends on. */
export function ancestorsOf(edges: PlacedEdge[], id: string): Set<string> {
  const parents = new Map<string, string[]>();
  for (const e of edges) parents.set(e.target, [...(parents.get(e.target) ?? []), e.source]);
  const seen = new Set<string>();
  const stack = [...(parents.get(id) ?? [])];
  while (stack.length) {
    const current = stack.pop()!;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(parents.get(current) ?? []));
  }
  return seen;
}

/** Everything downstream — what a change to this node would invalidate. */
export function descendantsOf(edges: PlacedEdge[], id: string): Set<string> {
  const children = new Map<string, string[]>();
  for (const e of edges) children.set(e.source, [...(children.get(e.source) ?? []), e.target]);
  const seen = new Set<string>();
  const stack = [...(children.get(id) ?? [])];
  while (stack.length) {
    const current = stack.pop()!;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(children.get(current) ?? []));
  }
  return seen;
}

export function nodeById(graph: TraceGraph, id: string): TraceNode | undefined {
  return graph.nodes.find((n) => n.id === id);
}
