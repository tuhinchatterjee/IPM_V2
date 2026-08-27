import assert from "node:assert/strict";
import { test } from "node:test";

import { chooseVisualization, shapeOf, supports } from "../registry.ts";
import type { ColumnSpec } from "../../../lib/format.ts";
import type { Row } from "../../../lib/api.ts";

/**
 * §21 requires the form to come from the RESULT'S SHAPE rather than from prose.
 * These fixtures are shapes, and the assertions are the decision table. A model
 * is never consulted, which is exactly what makes this testable at all.
 */

const col = (name: string, extra: Partial<ColumnSpec> = {}): ColumnSpec => ({
  name,
  ...extra,
});

const rows = (n: number, make: (i: number) => Row): Row[] =>
  Array.from({ length: n }, (_, i) => make(i));

test("one row of figures is a KPI, not a one-bar bar chart", () => {
  const choice = chooseVisualization(
    [col("total_ead", { semantic: "money" }), col("total_ecl", { semantic: "money" })],
    [{ total_ead: 125259, total_ecl: 3120 }],
  );
  assert.equal(choice.kind, "kpi");
  assert.deepEqual(choice.series, ["total_ead", "total_ecl"]);
});

test("a from/to pair with a measure is a transition matrix", () => {
  const choice = chooseVisualization(
    [col("from_stage"), col("to_stage"), col("ead", { semantic: "money" })],
    rows(9, (i) => ({ from_stage: `S${i % 3}`, to_stage: `S${i % 3}`, ead: i })),
  );
  assert.equal(choice.kind, "transition-matrix");
  assert.equal(choice.x, "from_stage");
  assert.equal(supports(choice, "sankey"), true);
});

test("a period column makes it a trend", () => {
  const choice = chooseVisualization(
    [col("period", { semantic: "period" }), col("total_ecl", { semantic: "money" })],
    rows(8, (i) => ({ period: `2024Q${(i % 4) + 1}`, total_ecl: i })),
  );
  assert.equal(choice.kind, "line");
  assert.equal(choice.x, "period");
});

test("a few series over time stay on one axis; many do not", () => {
  const columns = [
    col("period", { semantic: "period" }),
    col("sector", { is_identity: true }),
    col("ecl", { semantic: "money" }),
  ];
  const few = chooseVisualization(
    columns,
    rows(12, (i) => ({ period: `Q${i % 4}`, sector: `S${i % 3}`, ecl: i })),
  );
  assert.equal(few.kind, "line");

  const many = chooseVisualization(
    columns,
    rows(40, (i) => ({ period: `Q${i % 4}`, sector: `S${i % 10}`, ecl: i })),
  );
  assert.equal(many.kind, "small-multiples");
});

test("signed changes get a zero line rather than a plain bar", () => {
  const choice = chooseVisualization(
    [col("sector", { is_identity: true }), col("ecl_change", { semantic: "money" })],
    rows(6, (i) => ({ sector: `S${i}`, ecl_change: i - 3 })),
  );
  assert.equal(choice.kind, "diverging-bar");
  assert.equal(supports(choice, "waterfall"), true);
});

test("two measures per name is a relationship, not a ranking", () => {
  const choice = chooseVisualization(
    [
      col("borrower_name", { is_identity: true }),
      col("pd_pct", { semantic: "percent" }),
      col("lgd_pct", { semantic: "percent" }),
    ],
    rows(20, (i) => ({ borrower_name: `B${i}`, pd_pct: i, lgd_pct: 40 - i })),
  );
  assert.equal(choice.kind, "scatter");
});

test("three measures per name adds size", () => {
  const choice = chooseVisualization(
    [
      col("borrower_name", { is_identity: true }),
      col("pd_pct", { semantic: "percent" }),
      col("lgd_pct", { semantic: "percent" }),
      col("ead", { semantic: "money" }),
    ],
    rows(20, (i) => ({ borrower_name: `B${i}`, pd_pct: i, lgd_pct: i, ead: i })),
  );
  assert.equal(choice.kind, "bubble");
});

test("a handful of groups is a bar; a couple of dozen is a horizontal bar", () => {
  const columns = [col("sector", { is_identity: true }), col("ead", { semantic: "money" })];
  assert.equal(
    chooseVisualization(columns, rows(6, (i) => ({ sector: `S${i}`, ead: i }))).kind,
    "bar",
  );
  assert.equal(
    chooseVisualization(columns, rows(18, (i) => ({ sector: `S${i}`, ead: i }))).kind,
    "horizontal-bar",
  );
});

test("too many categories falls back to the table, and says why", () => {
  // §22: a bar chart of two hundred borrowers is not a picture of anything.
  const choice = chooseVisualization(
    [col("borrower_name", { is_identity: true }), col("ead", { semantic: "money" })],
    rows(200, (i) => ({ borrower_name: `B${i}`, ead: i })),
  );
  assert.equal(choice.kind, "table");
  assert.match(choice.because, /too many/i);
});

test("no measure means no chart, and no crash", () => {
  const choice = chooseVisualization(
    [col("borrower_name", { is_identity: true }), col("sector")],
    rows(5, (i) => ({ borrower_name: `B${i}`, sector: "Contracting" })),
  );
  assert.equal(choice.kind, "table");
});

test("an empty result never claims a chart", () => {
  assert.equal(
    chooseVisualization([col("ead", { semantic: "money" })], []).kind,
    "table",
  );
});

test("hidden lineage columns are not treated as measures", () => {
  // A denominator carried through an aggregate is a real column and not an
  // answer; charting it would draw the plumbing.
  const shape = shapeOf(
    [
      col("sector", { is_identity: true }),
      col("ead", { semantic: "money" }),
      col("_denominator", { semantic: "money", hidden: true }),
    ],
    [{ sector: "A", ead: 1, _denominator: 9 }],
  );
  assert.deepEqual(
    shape.numeric.map((c) => c.name),
    ["ead"],
  );
});

test("every choice explains itself", () => {
  const choice = chooseVisualization(
    [col("sector", { is_identity: true }), col("ead", { semantic: "money" })],
    rows(6, (i) => ({ sector: `S${i}`, ead: i })),
  );
  assert.notEqual(choice.because, "");
});
