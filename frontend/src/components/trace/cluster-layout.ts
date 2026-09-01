import type { TraceGraph, TraceNode } from "@/lib/api";

import {
  CLUSTER_ORDER,
  type Cluster,
  type ClusterId,
  clusterOf,
  clustersOf,
} from "./clusters.ts";
import { statusOf } from "./status.ts";

/**
 * Laying the Lineage graph out as real subgraphs.
 *
 * Everything here is pure. Given the same graph and the same set of collapsed
 * clusters it produces the same coordinates every time — which matters more
 * than it sounds, because a map that rearranges itself between two visits
 * cannot be pointed at in a meeting. The backend records the dependency layers,
 * so a node's depth is a fact rather than a simulation, and this file only
 * decides how far apart to put things.
 *
 * The one rule that shapes the rest
 * ---------------------------------
 * **Expanding a cluster must not move the others.** A layout that reflows the
 * whole canvas every time somebody opens a box makes the reader re-find their
 * place on every click, which is worse than the wall of nodes it replaced. So
 * clusters stack vertically in a fixed order and each one grows downward from
 * its own top edge: opening the fourth pushes the fifth down and leaves the
 * first three exactly where they were.
 */

export const NODE_WIDTH = 208;
export const NODE_HEIGHT = 74;
export const NODE_GAP_X = 28;
export const NODE_GAP_Y = 14;

/** The strip a cluster's name and summary live in. */
export const HEADER_HEIGHT = 34;
export const CLUSTER_PADDING = 14;
export const CLUSTER_GAP = 22;

/** The collapsed card is wider than a node: it carries a sentence. */
export const SUMMARY_WIDTH = 420;
export const SUMMARY_HEIGHT = 78;

/**
 * How many nodes sit side by side inside one cluster before it wraps.
 *
 * Six is about what stays legible at the zoom the whole map fits in. Without a
 * wrap a governed-data cluster reading nine datasets is nine columns wide on
 * its own, and every other cluster is then drawn at that scale.
 */
export const MAX_COLUMNS = 6;

export interface PlacedNode {
  id: string;
  node: TraceNode;
  cluster: ClusterId;
  /** Position RELATIVE to the cluster group that owns it. */
  x: number;
  y: number;
}

export interface PlacedCluster {
  cluster: Cluster;
  /** Absolute position of the group box. */
  x: number;
  y: number;
  width: number;
  height: number;
  collapsed: boolean;
  /** The id of the stand-in node when collapsed; empty when expanded. */
  summaryId: string;
}

/** What one dependency between two steps IS, in a word. */
export type EdgeKind =
  | "reads"
  | "joins"
  | "derives"
  | "computes"
  | "checks"
  | "reuses"
  | "feeds";

export interface PlacedEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  /** True when the dependency itself recorded a problem. */
  warning: boolean;
  /** How many real edges this one stands for, once clusters are collapsed. */
  weight: number;
  crossesClusters: boolean;
}

export interface ClusterLayout {
  clusters: PlacedCluster[];
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  width: number;
  height: number;
}

const KIND_OF: Record<string, EdgeKind> = {
  DATASET: "reads",
  DATA_DOMAIN: "reads",
  DATASET_FAMILY: "reads",
  VARIABLE: "reads",
  FILTER: "reads",
  GOVERNED_METADATA: "reads",
  RELATIONSHIP: "joins",
  JOIN: "joins",
  DERIVED_VARIABLE: "derives",
  TRANSFORMATION: "derives",
  AGGREGATION: "derives",
  WINDOW: "derives",
  CALCULATION: "derives",
  MATHEMATICAL_QUERY: "derives",
  SQL_QUERY: "computes",
  ENGINE_FUNCTION: "computes",
  CERTIFIED_METHOD: "computes",
  KERNEL: "computes",
  BUSINESS_INVARIANT: "checks",
  PRESENTATION_GATE: "checks",
  RECONCILIATION: "checks",
  FINGERPRINT: "checks",
  PREVIOUS_RESULT: "reuses",
  REUSED_RESULT: "reuses",
};

/** The label a summarised inter-cluster edge carries. */
export const KIND_LABEL: Record<EdgeKind, string> = {
  reads: "reads",
  joins: "joins",
  derives: "derives",
  computes: "computes",
  checks: "checks",
  reuses: "reuses",
  feeds: "feeds",
};

export function summaryIdFor(cluster: ClusterId): string {
  return `cluster__${cluster}`;
}

export function groupIdFor(cluster: ClusterId): string {
  return `group__${cluster}`;
}

/**
 * A node that recorded a problem WITH THE DEPENDENCY rather than with itself.
 *
 * A join that multiplied its left side, or a relationship that could not be
 * resolved, is a fault in the edge and not in either box it connects — and
 * marking only the boxes is how a reader ends up staring at two healthy-looking
 * datasets wondering why the row count trebled.
 */
function edgeWarns(node: TraceNode | undefined): boolean {
  if (!node) return false;
  if (node.type !== "JOIN" && node.type !== "RELATIONSHIP" && node.type !== "RECONCILIATION") {
    return false;
  }
  return Boolean(node.warnings?.length) || statusOf(node) === "failed";
}

export function layoutClusters(
  graph: TraceGraph,
  collapsed: Set<ClusterId>,
  isolated: ClusterId | null = null,
): ClusterLayout {
  const all = clustersOf(graph);
  const shown = isolated ? all.filter((c) => c.id === isolated) : all;

  const depth = new Map<string, number>();
  (graph.layers ?? []).forEach((layer, index) => {
    for (const id of layer) depth.set(id, index);
  });
  for (const node of graph.nodes ?? []) if (!depth.has(node.id)) depth.set(node.id, 0);

  const byId = new Map((graph.nodes ?? []).map((n) => [n.id, n]));
  const visibleClusters = new Set(shown.map((c) => c.id));

  // --- place the nodes inside each cluster --------------------------------
  const placedClusters: PlacedCluster[] = [];
  const placedNodes: PlacedNode[] = [];
  /** Real node id → the id actually drawn for it (itself, or a stand-in). */
  const drawnAs = new Map<string, string>();

  let cursorY = 0;
  let widest = SUMMARY_WIDTH + CLUSTER_PADDING * 2;

  for (const id of CLUSTER_ORDER) {
    const cluster = shown.find((c) => c.id === id);
    if (!cluster) continue;

    const isCollapsed = collapsed.has(id);
    if (isCollapsed) {
      const summaryId = summaryIdFor(id);
      for (const node of cluster.nodes) drawnAs.set(node.id, summaryId);
      const width = SUMMARY_WIDTH + CLUSTER_PADDING * 2;
      const height = HEADER_HEIGHT + SUMMARY_HEIGHT + CLUSTER_PADDING;
      placedClusters.push({
        cluster, x: 0, y: cursorY, width, height,
        collapsed: true, summaryId,
      });
      cursorY += height + CLUSTER_GAP;
      widest = Math.max(widest, width);
      continue;
    }

    // Expanded: pack left to right in the order the steps depend on each
    // other, wrapping so one wide cluster does not set the scale for all of
    // them.
    const ordered = [...cluster.nodes].sort((a, b) => {
      const da = depth.get(a.id) ?? 0;
      const db = depth.get(b.id) ?? 0;
      return da - db || a.id.localeCompare(b.id);
    });

    ordered.forEach((node, index) => {
      drawnAs.set(node.id, node.id);
      const column = index % MAX_COLUMNS;
      const row = Math.floor(index / MAX_COLUMNS);
      placedNodes.push({
        id: node.id,
        node,
        cluster: id,
        x: CLUSTER_PADDING + column * (NODE_WIDTH + NODE_GAP_X),
        y: HEADER_HEIGHT + row * (NODE_HEIGHT + NODE_GAP_Y),
      });
    });

    const columns = Math.min(ordered.length, MAX_COLUMNS);
    const rows = Math.ceil(ordered.length / MAX_COLUMNS);
    const width = Math.max(
      SUMMARY_WIDTH,
      columns * NODE_WIDTH + Math.max(0, columns - 1) * NODE_GAP_X,
    ) + CLUSTER_PADDING * 2;
    const height =
      HEADER_HEIGHT + rows * NODE_HEIGHT + Math.max(0, rows - 1) * NODE_GAP_Y + CLUSTER_PADDING;

    placedClusters.push({
      cluster, x: 0, y: cursorY, width, height, collapsed: false, summaryId: "",
    });
    cursorY += height + CLUSTER_GAP;
    widest = Math.max(widest, width);
  }

  // --- rewrite the edges through whatever is actually drawn ---------------
  //
  // An edge whose ends both fall inside one collapsed cluster disappears with
  // its internals. An edge that crosses a boundary survives, pointing at the
  // collapsed card — which is the property that makes collapsing safe: the
  // shape of the dependency is never lost, only its detail.
  const merged = new Map<string, PlacedEdge>();
  for (const edge of graph.edges ?? []) {
    const sourceNode = byId.get(edge.source);
    const targetNode = byId.get(edge.target);
    if (!sourceNode || !targetNode) continue;
    const sourceCluster = clusterOf(sourceNode);
    const targetCluster = clusterOf(targetNode);
    if (!visibleClusters.has(sourceCluster) || !visibleClusters.has(targetCluster)) {
      continue;
    }

    const source = drawnAs.get(edge.source) ?? edge.source;
    const target = drawnAs.get(edge.target) ?? edge.target;
    if (source === target) continue;

    const key = `${source}->${target}`;
    const kind = KIND_OF[sourceNode.type] ?? "feeds";
    const warning = edgeWarns(sourceNode) || edgeWarns(targetNode);
    const existing = merged.get(key);
    if (existing) {
      existing.weight += 1;
      existing.warning = existing.warning || warning;
      continue;
    }
    merged.set(key, {
      id: key,
      source,
      target,
      kind,
      warning,
      weight: 1,
      crossesClusters: sourceCluster !== targetCluster,
    });
  }

  return {
    clusters: placedClusters,
    nodes: placedNodes,
    edges: [...merged.values()],
    width: widest,
    height: Math.max(cursorY - CLUSTER_GAP, 0),
  };
}

/* ------------------------------------------------------------- the lineage */

/** Everything upstream of a drawn node — what it depends on. */
export function ancestorsOf(edges: PlacedEdge[], id: string): Set<string> {
  return walk(edges, id, "up");
}

/** Everything downstream — what a change to this node would invalidate. */
export function descendantsOf(edges: PlacedEdge[], id: string): Set<string> {
  return walk(edges, id, "down");
}

function walk(edges: PlacedEdge[], id: string, direction: "up" | "down"): Set<string> {
  const next = new Map<string, string[]>();
  for (const edge of edges) {
    const from = direction === "up" ? edge.target : edge.source;
    const to = direction === "up" ? edge.source : edge.target;
    next.set(from, [...(next.get(from) ?? []), to]);
  }
  const seen = new Set<string>();
  const stack = [...(next.get(id) ?? [])];
  while (stack.length) {
    const current = stack.pop();
    if (current === undefined || seen.has(current)) continue;
    seen.add(current);
    stack.push(...(next.get(current) ?? []));
  }
  return seen;
}

/**
 * The chain from a node back to the datasets it rests on.
 *
 * What "trace this figure" means in practice: a reader points at a number and
 * asks which fields, in which datasets, joined on which relationship, produced
 * it. That is the upstream walk filtered to the steps that answer it, in the
 * order they happened.
 */
export function provenanceChain(graph: TraceGraph, edges: PlacedEdge[], id: string): TraceNode[] {
  const up = ancestorsOf(edges, id);
  const byId = new Map((graph.nodes ?? []).map((n) => [n.id, n]));
  const order = new Map<string, number>();
  (graph.layers ?? []).forEach((layer, index) => {
    for (const nodeId of layer) order.set(nodeId, index);
  });
  return [...up]
    .map((nodeId) => byId.get(nodeId))
    .filter((node): node is TraceNode => Boolean(node))
    .sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
}
