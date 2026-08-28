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

/* ------------------------------------------- §62: representative result shapes */

test("a sector ranking is a bar chart", () => {
  const choice = chooseVisualization(
    [col("sector", { is_identity: true }), col("ead", { semantic: "money" })],
    rows(7, (i) => ({ sector: `Sector ${i}`, ead: 100 - i })),
  );
  assert.equal(choice.kind, "bar");
  assert.equal(choice.x, "sector");
});

test("a time series is a line", () => {
  const choice = chooseVisualization(
    [col("as_of_quarter", { semantic: "period" }), col("total_ecl", { semantic: "money" })],
    rows(8, (i) => ({ as_of_quarter: `2024Q${(i % 4) + 1}`, total_ecl: i })),
  );
  assert.equal(choice.kind, "line");
});

test("an ECL movement offers a waterfall", () => {
  // Signed contributions to a change: the zero line is the point, and a plain
  // bar chart hides it.
  const choice = chooseVisualization(
    [col("sector", { is_identity: true }), col("ecl_movement", { semantic: "money" })],
    rows(5, (i) => ({ sector: `S${i}`, ecl_movement: i - 2 })),
  );
  assert.equal(choice.kind, "diverging-bar");
  assert.equal(supports(choice, "waterfall"), true);
});

test("a stage migration is a matrix and offers a Sankey", () => {
  const choice = chooseVisualization(
    [col("from_stage"), col("to_stage"), col("ead", { semantic: "money" })],
    rows(9, (i) => ({ from_stage: `S${i % 3}`, to_stage: `S${(i + 1) % 3}`, ead: i })),
  );
  assert.equal(choice.kind, "transition-matrix");
  assert.equal(supports(choice, "sankey"), true);
  assert.equal(supports(choice, "heatmap"), true);
});

test("a concentration offers a treemap", () => {
  const choice = chooseVisualization(
    [col("borrower_name", { is_identity: true }), col("ead", { semantic: "money" })],
    rows(10, (i) => ({ borrower_name: `B${i}`, ead: 100 - i })),
  );
  assert.equal(supports(choice, "treemap"), true);
});

test("a multidimensional borrower result is a scatter or a bubble", () => {
  const two = chooseVisualization(
    [
      col("borrower_name", { is_identity: true }),
      col("pd_pct", { semantic: "percent" }),
      col("coverage_pct", { semantic: "percent" }),
    ],
    rows(30, (i) => ({ borrower_name: `B${i}`, pd_pct: i, coverage_pct: 60 - i })),
  );
  assert.equal(two.kind, "scatter");
  assert.equal(supports(two, "risk-landscape"), true);
});

test("a dense heterogeneous result is a table, and says why", () => {
  // §22: precision over pattern, and the reader is told which rule applied
  // rather than being left to wonder why there is no chart.
  const choice = chooseVisualization(
    [
      col("account_id", { is_identity: true }),
      col("borrower_name", { is_identity: true }),
      col("stage", { semantic: "ordinal" }),
      col("ead", { semantic: "money" }),
      col("dpd", { semantic: "days" }),
    ],
    rows(120, (i) => ({
      account_id: `A${i}`, borrower_name: `B${i}`, stage: 1, ead: i, dpd: i,
    })),
  );
  assert.equal(choice.kind, "table");
  assert.notEqual(choice.because, "");
});

test("the registry never names a series the result does not have", () => {
  // §21: "The LLM never invents chart values." Nothing here invents a column
  // either — every series is a column that was passed in.
  const columns = [
    col("sector", { is_identity: true }),
    col("ead", { semantic: "money" }),
    col("ecl", { semantic: "money" }),
  ];
  const names = new Set(columns.map((c) => c.name));
  const choice = chooseVisualization(
    columns,
    rows(6, (i) => ({ sector: `S${i}`, ead: i, ecl: i })),
  );
  for (const key of choice.series) assert.equal(names.has(key), true, key);
  if (choice.x) assert.equal(names.has(choice.x), true, choice.x);
});

test("the chosen form is always one the result supports", () => {
  const choice = chooseVisualization(
    [col("sector", { is_identity: true }), col("ead", { semantic: "money" })],
    rows(6, (i) => ({ sector: `S${i}`, ead: i })),
  );
  assert.equal(supports(choice, choice.kind), true);
  assert.equal(supports(choice, "sankey"), false);
});

test("a table is offered as an alternative wherever a chart is chosen", () => {
  // §22: "Always retain a TABLE toggle."
  for (const [columns, data] of [
    [
      [col("sector", { is_identity: true }), col("ead", { semantic: "money" })],
      rows(6, (i) => ({ sector: `S${i}`, ead: i })),
    ],
    [
      [col("period", { semantic: "period" }), col("ecl", { semantic: "money" })],
      rows(6, (i) => ({ period: `Q${i}`, ecl: i })),
    ],
  ] as const) {
    const choice = chooseVisualization([...columns], [...data]);
    assert.equal(
      choice.kind === "table" || choice.alternatives.includes("table"),
      true,
      choice.kind,
    );
  }
});

test("a share of the measure is not a second measure", () => {
  // Found in the browser review: "exposure at default by sector, with each
  // sector's share" was read as two measures and drawn as a scatter — a
  // quantity plotted against its own proportion, which is a straight line
  // presented as a finding. It is a bar chart of one measure.
  const choice = chooseVisualization(
    [
      col("sector", { is_identity: true }),
      col("exposure_at_default", { semantic: "money" }),
      col("exposure_at_default_share_pct", { semantic: "percent" }),
    ],
    rows(15, (i) => ({
      sector: `Sector ${i}`,
      exposure_at_default: 100 - i,
      exposure_at_default_share_pct: (100 - i) / 15,
    })),
  );
  assert.equal(choice.kind, "horizontal-bar");
  assert.deepEqual(choice.series, ["exposure_at_default"]);
});

test("a genuine second measure still makes it a relationship", () => {
  // The rule above must not swallow real pairs: PD against LGD is two things
  // that were measured, not one thing and its proportion.
  const choice = chooseVisualization(
    [
      col("borrower_name", { is_identity: true }),
      col("pd_pct", { semantic: "percent" }),
      col("lgd_pct", { semantic: "percent" }),
    ],
    rows(15, (i) => ({ borrower_name: `B${i}`, pd_pct: i, lgd_pct: 40 - i })),
  );
  assert.equal(choice.kind, "scatter");
});

/* ------------------------------------------------------------ the two fixes */

test("a governed code column is a dimension, not a measure", () => {
  // An internal rating grade arrives as semantic "text" carrying 1 to 10.
  // Reading its VALUES made it a measure, which left the breakdown with no
  // dimension and sent every "for each rating grade…" question to a table.
  const choice = chooseVisualization(
    [
      { name: "internal_grade", semantic: "text" },
      { name: "ecl_coverage_pct", semantic: "percent" },
      { name: "dscr", semantic: "ratio" },
    ],
    Array.from({ length: 10 }, (_, i) => ({
      internal_grade: i + 1,
      ecl_coverage_pct: 5 + i,
      dscr: 1.5,
    })),
  );
  assert.equal(choice.kind, "grouped-bar");
  assert.equal(choice.x, "internal_grade");
  assert.deepEqual(choice.series, ["ecl_coverage_pct", "dscr"]);
});

test("a column with no declared semantic is still read from its data", () => {
  const choice = chooseVisualization(
    [{ name: "sector" }, { name: "ead" }],
    [
      { sector: "Contracting", ead: 100 },
      { sector: "Real Estate", ead: 80 },
    ],
  );
  assert.notEqual(choice.kind, "table");
  assert.equal(choice.x, "sector");
});

test("two measures across a small governed scale is a comparison, not a scatter", () => {
  // Scattering ten rating grades throws away the ordering, which is the one
  // property of a rating scale that carries meaning.
  const choice = chooseVisualization(
    [
      { name: "rating_bucket", semantic: "text" },
      { name: "ead", semantic: "money" },
      { name: "total_ecl", semantic: "money" },
    ],
    Array.from({ length: 8 }, (_, i) => ({
      rating_bucket: `CP-${i + 1}`,
      ead: 100 - i,
      total_ecl: 5 + i,
    })),
  );
  assert.equal(choice.kind, "grouped-bar");
});

test("two measures per named thing is still a scatter", () => {
  const choice = chooseVisualization(
    [
      { name: "customer_id", semantic: "identity", is_identity: true },
      { name: "ead", semantic: "money" },
      { name: "ecl_coverage_pct", semantic: "percent" },
    ],
    Array.from({ length: 20 }, (_, i) => ({
      customer_id: `SA-${i}`,
      ead: 10 + i,
      ecl_coverage_pct: 2 + i,
    })),
  );
  assert.equal(choice.kind, "scatter");
});

test("three measures per named thing is a bubble", () => {
  const choice = chooseVisualization(
    [
      { name: "customer_id", semantic: "identity", is_identity: true },
      { name: "ead", semantic: "money" },
      { name: "ecl_coverage_pct", semantic: "percent" },
      { name: "dscr", semantic: "ratio" },
    ],
    Array.from({ length: 20 }, (_, i) => ({
      customer_id: `SA-${i}`,
      ead: 10 + i,
      ecl_coverage_pct: 2 + i,
      dscr: 1 + i / 10,
    })),
  );
  assert.equal(choice.kind, "bubble");
});
