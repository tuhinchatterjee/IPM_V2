import assert from "node:assert/strict";
import { test } from "node:test";

import type { RelatedParty, RelationshipNetwork } from "../api.ts";
import {
  BAND_ORDER,
  NODE_HEIGHT,
  directOnly,
  layout,
  money,
  stake,
} from "../relationship-layout.ts";

/**
 * The group structure's layout rules. R2 §2.
 *
 * The picture makes one claim — upstream is above, downstream is below — and
 * these tests are what hold it. A layout that put a parent underneath a
 * subsidiary would be worse than no picture, because it would be read.
 */

function party(over: Partial<RelatedParty> = {}): RelatedParty {
  return {
    node_id: "X",
    label: "X",
    node_type: "Corporate",
    detail: "",
    direction: "UPSTREAM",
    depth: 1,
    relationship: "Shareholder",
    edge_type: "OWNS",
    ownership_pct: null,
    voting_pct: null,
    amount: null,
    instrument: "",
    source: "",
    confidence: null,
    via: [],
    is_borrower: false,
    exposure: null,
    controls: false,
    significant: false,
    ...over,
  };
}

function network(parties: RelatedParty[]): RelationshipNetwork {
  const of = (direction: RelatedParty["direction"]) =>
    parties.filter((p) => p.direction === direction);
  return {
    version: "1.0.0",
    centre: "CENTRE",
    centre_label: "The Borrower",
    period: "Q2 2026",
    as_of: "2026-06-30",
    view: "group",
    depth: 2,
    party_count: parties.length,
    groups: BAND_ORDER.map((direction) => ({
      direction,
      label: direction,
      question: "?",
      count: of(direction).length,
      parties: of(direction),
    })),
    edges: [],
    group_exposure: 0,
    centre_exposure: null,
    group_borrowers: 0,
    exposure_is_floor: false,
    truncated: false,
    truncation_note: "",
  };
}

test("a parent is drawn above the borrower", () => {
  const parent = party({ node_id: "P", direction: "UPSTREAM" });
  const { placed } = layout(network([parent]));
  const centre = placed.find((s) => s.centre);
  const above = placed.find((s) => s.party?.node_id === "P");
  assert.ok(centre && above);
  assert.ok(above.y < centre.y, "the parent is not above the borrower");
});

test("a subsidiary is drawn below the borrower", () => {
  const child = party({ node_id: "C", direction: "DOWNSTREAM" });
  const { placed } = layout(network([child]));
  const centre = placed.find((s) => s.centre);
  const below = placed.find((s) => s.party?.node_id === "C");
  assert.ok(centre && below);
  assert.ok(below.y > centre.y, "the subsidiary is not below the borrower");
});

test("a sister is drawn level with the borrower, not above or below", () => {
  const sister = party({ node_id: "S", direction: "LATERAL", depth: 2 });
  const { placed } = layout(network([sister]));
  const centre = placed.find((s) => s.centre);
  const beside = placed.find((s) => s.party?.node_id === "S");
  assert.ok(centre && beside);
  assert.ok(
    Math.abs(beside.y - centre.y) <= NODE_HEIGHT,
    "the sister is not level with the borrower",
  );
});

test("every party is placed exactly once, and so is the centre", () => {
  const { placed } = layout(
    network([
      party({ node_id: "P", direction: "UPSTREAM" }),
      party({ node_id: "C", direction: "DOWNSTREAM" }),
      party({ node_id: "S", direction: "LATERAL" }),
    ]),
  );
  assert.equal(placed.length, 4);
  assert.equal(placed.filter((s) => s.centre).length, 1);
});

test("an empty network still places the borrower", () => {
  const { placed } = layout(network([]));
  assert.equal(placed.length, 1);
  assert.equal(placed[0].centre, true);
});

test("parties in the same band do not overlap", () => {
  const { placed } = layout(
    network([
      party({ node_id: "A", direction: "UPSTREAM" }),
      party({ node_id: "B", direction: "UPSTREAM" }),
      party({ node_id: "C", direction: "UPSTREAM" }),
    ]),
  );
  const xs = placed
    .filter((s) => s.party)
    .map((s) => s.x)
    .sort((a, b) => a - b);
  for (let i = 1; i < xs.length; i += 1) {
    assert.ok(xs[i] - xs[i - 1] >= 168, "two parties are drawn on top of each other");
  }
});

test("direct-only keeps the parents and drops the sisters", () => {
  const shown = directOnly(
    network([
      party({ node_id: "P", direction: "UPSTREAM", depth: 1 }),
      party({ node_id: "S", direction: "LATERAL", depth: 2 }),
    ]),
  );
  const ids = shown.groups.flatMap((g) => g.parties.map((p) => p.node_id));
  assert.deepEqual(ids, ["P"]);
  assert.equal(shown.party_count, 1);
});

test("direct-only keeps every band present, even the emptied ones", () => {
  // A screen that has to branch on whether a band exists is one that shows
  // "beside" only when something is beside it, and the reader cannot tell an
  // empty band from an unbuilt one.
  const shown = directOnly(network([party({ node_id: "S", direction: "LATERAL", depth: 2 })]));
  assert.deepEqual(
    shown.groups.map((g) => g.direction),
    BAND_ORDER,
  );
});

test("money never prints a bare number", () => {
  assert.equal(money(75.4), "SAR 75.4m");
  assert.equal(money(1234), "SAR 1.23bn");
  assert.equal(money(0), "SAR 0.0m");
});

test("money says nothing rather than zero when there is no figure", () => {
  assert.equal(money(null), "");
  assert.equal(money(undefined), "");
  assert.equal(money(Number.NaN), "");
});

test("the stake shows voting rights only when they differ from ownership", () => {
  assert.equal(stake(party({ ownership_pct: 80, voting_pct: 80 })), "80.0% owned");
  assert.equal(
    stake(party({ ownership_pct: 90, voting_pct: 10 })),
    "90.0% owned · 10.0% votes",
  );
});

test("a guarantee shows its amount and claims no ownership", () => {
  assert.equal(stake(party({ amount: 250, edge_type: "PROVIDES" })), "SAR 250.0m");
});

test("an edge with nothing on it says nothing rather than 0%", () => {
  assert.equal(stake(party()), "");
});
