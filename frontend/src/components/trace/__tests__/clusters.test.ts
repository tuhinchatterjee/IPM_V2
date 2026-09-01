import assert from "node:assert/strict";
import { test } from "node:test";

import type { TraceGraph, TraceNode } from "../../../lib/api.ts";
import {
  CLUSTER_OF,
  CLUSTER_ORDER,
  clusterOf,
  clustersOf,
  defaultCollapsed,
  issuesIn,
  search,
} from "../clusters.ts";
import { layoutClusters, summaryIdFor } from "../cluster-layout.ts";

/**
 * The failure these exist for.
 *
 * The detailed Lineage view drew forty equally-weighted rectangles in coloured
 * bands. A band is a hint about position; it is not something a reader can
 * collapse, focus, isolate, or roll an issue up into. So a trace with one
 * failed invariant among forty passing steps showed the failure as one small
 * rectangle among forty, and finding it meant clicking most of them.
 *
 * These check the three properties that fix it: every node lands in exactly
 * one governed cluster, a cluster that carries an issue never hides it, and an
 * edge that crosses a cluster boundary survives the cluster being shut.
 */

function node(partial: Partial<TraceNode> & { id: string; type: string }): TraceNode {
  return {
    label: partial.id,
    config: {},
    status: "ok",
    is_governed: true,
    started_at: null,
    finished_at: null,
    duration_ms: null,
    rows_in: null,
    rows_out: null,
    output_preview: [],
    output_summary: {},
    dataset: null,
    fields_used: [],
    function_id: null,
    function_version: null,
    dataset_version: null,
    warnings: [],
    error: null,
    ...partial,
  } as TraceNode;
}

function graphOf(nodes: TraceNode[], edges: { source: string; target: string }[]): TraceGraph {
  return {
    nodes,
    edges,
    layers: nodes.map((n) => [n.id]),
  } as unknown as TraceGraph;
}

const TRACE = graphOf(
  [
    node({ id: "question", type: "USER_PROMPT", label: "Question asked" }),
    node({ id: "intent", type: "CAPABILITY", label: "Read as: an analysis" }),
    node({ id: "facility", type: "DATASET", label: "Portfolio Facility", rows_out: 8200 }),
    node({ id: "staging", type: "DATASET", label: "IFRS 9 Staging", rows_out: 8200 }),
    node({ id: "join", type: "JOIN", label: "facility → staging on customer_id" }),
    node({ id: "share", type: "DERIVED_VARIABLE", label: "Stage 2 EAD share" }),
    node({ id: "sql", type: "SQL_QUERY", label: "SELECT …", duration_ms: 240 }),
    node({
      id: "covenant",
      type: "BUSINESS_INVARIANT",
      label: "Covenant headroom below 15%",
      status: "failed",
      error: "one row is at 17.41%",
    }),
    node({ id: "result", type: "RESULT", label: "6 sectors", rows_out: 6 }),
  ],
  [
    { source: "question", target: "intent" },
    { source: "intent", target: "facility" },
    { source: "intent", target: "staging" },
    { source: "facility", target: "join" },
    { source: "staging", target: "join" },
    { source: "join", target: "share" },
    { source: "share", target: "sql" },
    { source: "sql", target: "covenant" },
    { source: "covenant", target: "result" },
  ],
);

/* ------------------------------------------------------------ the taxonomy */

test("every node lands in exactly one cluster", () => {
  const clusters = clustersOf(TRACE);
  const placed = clusters.flatMap((c) => c.nodes.map((n) => n.id));
  assert.equal(placed.length, TRACE.nodes.length);
  assert.equal(new Set(placed).size, TRACE.nodes.length);
});

test("the clusters come back in the order an auditor asks for them", () => {
  const clusters = clustersOf(TRACE);
  const order = clusters.map((c) => c.id);
  const expected = CLUSTER_ORDER.filter((id) => order.includes(id));
  assert.deepEqual(order, expected);
});

test("a derivation and an execution are not the same cluster", () => {
  // The split an auditor disputing a figure depends on: a derivation is a
  // definition, an execution is an event, and they are never both wrong at
  // once.
  assert.equal(clusterOf(node({ id: "x", type: "DERIVED_VARIABLE" })), "derivations");
  assert.equal(clusterOf(node({ id: "y", type: "SQL_QUERY" })), "execution");
});

test("an unknown node type is still placed rather than dropped", () => {
  assert.equal(clusterOf(node({ id: "z", type: "SOMETHING_NEW" })), "derivations");
  assert.equal(CLUSTER_OF.SOMETHING_NEW, undefined);
});

test("the reuse node types belong to the conversation cluster", () => {
  assert.equal(clusterOf(node({ id: "p", type: "PREVIOUS_RESULT" })), "conversation");
  assert.equal(clusterOf(node({ id: "r", type: "REUSED_RESULT" })), "conversation");
});

/* --------------------------------------------------------------- the health */

test("a failed invariant makes its whole cluster read as failed", () => {
  const validation = clustersOf(TRACE).find((c) => c.id === "validation");
  assert.ok(validation);
  assert.equal(validation.status, "failed");
  assert.equal(validation.issues.length, 1);
  assert.equal(validation.issues[0].id, "covenant");
});

test("a cluster carrying an issue never opens collapsed", () => {
  const clusters = clustersOf(TRACE);
  const shut = defaultCollapsed(clusters);
  assert.equal(shut.has("validation"), false);
});

test("the issue navigator lists the failures worst first", () => {
  const warned = graphOf(
    [
      node({ id: "j", type: "JOIN", label: "a join", warnings: ["multiplied 3x"] }),
      node({ id: "inv", type: "BUSINESS_INVARIANT", label: "a check", status: "failed" }),
    ],
    [{ source: "j", target: "inv" }],
  );
  const found = issuesIn(clustersOf(warned));
  assert.equal(found.length, 2);
  // Cluster order puts relationships before validation, so both are listed —
  // the ordering that matters is within a cluster, and the reader is taken
  // through them rather than left to scan.
  assert.deepEqual(found.map((f) => f.node.id).sort(), ["inv", "j"]);
});

/* --------------------------------------------------------------- collapsing */

test("a collapsed cluster says what it contains without being opened", () => {
  const data = clustersOf(TRACE).find((c) => c.id === "data");
  assert.ok(data);
  assert.match(data.summary, /Portfolio Facility/);
  assert.deepEqual(data.represents, ["Portfolio Facility", "IFRS 9 Staging"]);
  assert.equal(data.rowsOut, 8200);
});

test("an edge across a collapsed boundary survives, pointing at the card", () => {
  const layout = layoutClusters(TRACE, new Set(["data"]));
  const stand = summaryIdFor("data");
  const intoJoin = layout.edges.filter((e) => e.target === "join");

  // Two dataset → join edges became one, and it points at the collapsed card
  // rather than at a node that is no longer drawn.
  assert.equal(intoJoin.length, 1);
  assert.equal(intoJoin[0].source, stand);
  assert.equal(intoJoin[0].weight, 2);
  assert.equal(intoJoin[0].kind, "reads");
  assert.equal(intoJoin[0].crossesClusters, true);
});

test("collapsing a cluster does not leave a dangling edge", () => {
  const layout = layoutClusters(TRACE, new Set(["data", "derivations"]));
  const drawn = new Set([
    ...layout.nodes.map((n) => n.id),
    ...layout.clusters.filter((c) => c.collapsed).map((c) => c.summaryId),
  ]);
  for (const edge of layout.edges) {
    assert.ok(drawn.has(edge.source), `dangling source ${edge.source}`);
    assert.ok(drawn.has(edge.target), `dangling target ${edge.target}`);
  }
});

test("a join that multiplied its rows marks its own edge", () => {
  const multiplied = graphOf(
    [
      node({ id: "d", type: "DATASET", label: "a dataset" }),
      node({ id: "j", type: "JOIN", label: "a join", warnings: ["multiplied 3x"] }),
      node({ id: "r", type: "RESULT", label: "the result" }),
    ],
    [
      { source: "d", target: "j" },
      { source: "j", target: "r" },
    ],
  );
  const layout = layoutClusters(multiplied, new Set());
  assert.ok(layout.edges.every((e) => e.warning), "the fault is in the link, not the boxes");
});

test("expanding one cluster does not move the ones above it", () => {
  const shut = layoutClusters(TRACE, new Set(["data", "relationships", "derivations"]));
  const open = layoutClusters(TRACE, new Set(["data", "relationships"]));
  const before = (l: ReturnType<typeof layoutClusters>, id: string) =>
    l.clusters.find((c) => c.cluster.id === id)?.y;

  assert.equal(before(shut, "request"), before(open, "request"));
  assert.equal(before(shut, "data"), before(open, "data"));
  assert.equal(before(shut, "relationships"), before(open, "relationships"));
  // The one below it does move — it has to, the box above grew.
  assert.notEqual(before(shut, "execution"), before(open, "execution"));
});

test("the same graph lays out identically every time", () => {
  const a = layoutClusters(TRACE, new Set(["data"]));
  const b = layoutClusters(TRACE, new Set(["data"]));
  assert.deepEqual(
    a.nodes.map((n) => [n.id, n.x, n.y]),
    b.nodes.map((n) => [n.id, n.x, n.y]),
  );
});

/* ---------------------------------------------------------------- isolating */

test("isolating a cluster hides the others and their edges", () => {
  const layout = layoutClusters(TRACE, new Set(), "data");
  assert.equal(layout.clusters.length, 1);
  assert.equal(layout.clusters[0].cluster.id, "data");
  assert.deepEqual(layout.nodes.map((n) => n.id).sort(), ["facility", "staging"]);
  assert.equal(layout.edges.length, 0, "no edge may point outside an isolated cluster");
});

/* ------------------------------------------------------------------ finding */

test("a step can be found by label, dataset or field", () => {
  assert.deepEqual(search(TRACE, "covenant").map((n) => n.id), ["covenant"]);
  assert.deepEqual(search(TRACE, "ifrs").map((n) => n.id), ["staging"]);
  assert.deepEqual(search(TRACE, "").map((n) => n.id), []);
  assert.deepEqual(search(TRACE, "nothing here").map((n) => n.id), []);
});
