import assert from "node:assert/strict";
import { test } from "node:test";

import { NODE_WIDTH, layoutRelationships } from "../relationship-layout.ts";
import type { RelationshipEdge, RelationshipNode } from "../../../lib/api.ts";

function node(name: string): RelationshipNode {
  return {
    name,
    domain: "credit",
    grain: `one row per ${name}`,
    field_count: 4,
    is_synthetic: true,
    in_catalogue: true,
    degree: 0,
  };
}

function edge(id: number, from: string, to: string): RelationshipEdge {
  return {
    id,
    name: `${from}_${to}`,
    from_dataset: from,
    from_field: "customer_id",
    to_dataset: to,
    to_field: "customer_id",
    cardinality: "many_to_one",
    kind: "key",
    description: "",
    semantic: "",
    lifecycle: "active",
    lifecycle_label: "Active",
    version: 1,
    is_preferred: false,
    confidence: 1,
    join_policy: "inner",
    temporal_rule: "same_period",
    temporal_label: "",
    match_rate: 1,
    orphan_rate: 0,
    duplicate_rate: 0,
    validated_at: "",
    validation: {},
    is_runnable: true,
  };
}

/** A hub with three spokes, one of which carries a spoke of its own. */
const NODES = ["facility", "customer", "ratings", "memos", "sector"].map(node);
const EDGES = [
  edge(1, "customer", "facility"),
  edge(2, "ratings", "facility"),
  edge(3, "memos", "facility"),
  edge(4, "sector", "customer"),
];

test("the busiest dataset is the centre of the map", () => {
  const { placed } = layoutRelationships(NODES, EDGES);
  const centre = placed.find((p) => p.ring === 0);
  assert.equal(centre?.name, "facility");
  assert.deepEqual({ x: centre?.x, y: centre?.y }, { x: 0, y: 0 });
});

test("a ring is how many joins it takes to reach the centre", () => {
  const { placed } = layoutRelationships(NODES, EDGES);
  const ring = new Map(placed.map((p) => [p.name, p.ring]));
  assert.equal(ring.get("customer"), 1);
  assert.equal(ring.get("ratings"), 1);
  assert.equal(ring.get("memos"), 1);
  // sector only reaches the facility position through the customer.
  assert.equal(ring.get("sector"), 2);
});

test("the same model always draws the same picture", () => {
  const first = layoutRelationships(NODES, EDGES);
  const shuffled = layoutRelationships([...NODES].reverse(), [...EDGES].reverse());
  assert.deepEqual(
    first.placed.map((p) => [p.name, Math.round(p.x), Math.round(p.y)]),
    shuffled.placed.map((p) => [p.name, Math.round(p.x), Math.round(p.y)]),
  );
});

test("boxes in a ring never overlap", () => {
  // Twelve datasets all hanging off one hub: the ring has to grow to hold them.
  const many = ["hub", ...Array.from({ length: 12 }, (_, i) => `spoke_${i}`)].map(node);
  const spokes = Array.from({ length: 12 }, (_, i) => edge(i + 1, `spoke_${i}`, "hub"));
  const { placed } = layoutRelationships(many, spokes);
  const ring = placed.filter((p) => p.ring === 1);
  assert.equal(ring.length, 12);
  for (const a of ring) {
    for (const b of ring) {
      if (a.name === b.name) continue;
      const apart = Math.hypot(a.x - b.x, a.y - b.y);
      assert.ok(apart > NODE_WIDTH * 0.5, `${a.name} and ${b.name} sit on top of each other`);
    }
  }
});

test("a dataset the centre cannot reach is still placed", () => {
  const isolated = [...NODES, node("macro"), node("macro_other")];
  const detached = [...EDGES, edge(9, "macro", "macro_other")];
  const { placed } = layoutRelationships(isolated, detached);
  const names = placed.map((p) => p.name);
  assert.ok(names.includes("macro"));
  assert.ok(names.includes("macro_other"));
});

test("nothing declared draws nothing rather than throwing", () => {
  const { placed, rings } = layoutRelationships(NODES, []);
  assert.deepEqual(placed, []);
  assert.equal(rings, 0);
});
