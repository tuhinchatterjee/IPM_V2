import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

/**
 * The Scorecard Validation Intelligence cockpit, checked against its source.
 *
 * Structural, like its sibling, and for the same reason: every claim below is
 * a claim about what the screen REFUSES to do, and a refusal rots silently.
 * Nobody files a bug when a NO APPROVED LIMIT chip quietly becomes a green
 * tick — the screen looks better afterwards, and the model looks sounder than
 * the evidence says it is.
 *
 * A structural test cannot see that the cockpit looks good. It can see that
 * the pieces encoding the governance are present, distinct, and have not been
 * collapsed into each other.
 */

const root = fileURLToPath(new URL("../../", import.meta.url));
const read = (path: string) => readFileSync(root + path, "utf8");
const page = () => read("app/scorecard-validation/page.tsx");
const card = () => read("components/scorecard-validation/result-card.tsx");
const chart = () => read("components/scorecard-validation/validation-chart.tsx");

test("all ten result states have their own colour", () => {
  const source = card();
  for (const state of [
    "PASS",
    "WARNING",
    "FAIL",
    "NO_LIMIT",
    "CALCULATION_ERROR",
    "UNAVAILABLE",
    "INSUFFICIENT_SAMPLE",
    "NOT_MATURED",
    "NOT_AUTHORISED",
    "NOT_APPLICABLE",
  ]) {
    assert.ok(source.includes(`${state}:`), `${state} has a tone entry`);
  }
});

test("NO_LIMIT is not painted as a pass", () => {
  const source = card();
  const noLimit = source.match(/NO_LIMIT: "([^"]+)"/);
  const pass = source.match(/PASS: "([^"]+)"/);
  assert.ok(noLimit && pass, "both states carry a tone");
  assert.notEqual(noLimit![1], pass![1],
    "a measurement with no governed limit must not look like a verdict");
  assert.ok(!noLimit![1].includes("positive"),
    "NO_LIMIT must not borrow the positive colour");
});

test("the six refusals are not one grey chip", () => {
  const source = card();
  // They may share a tone — they are all absences — but the LABEL is the
  // result's own state_label, so the reader can tell wait from cannot.
  assert.ok(source.includes("result.state_label"),
    "the chip renders the state's own label, not a generic word");
});

test("a value is rendered only when the result says it was measured", () => {
  const source = card();
  assert.ok(source.includes("if (!result.measured || result.value === null)"),
    "the figure is gated on measured AND on a non-null value");
});

test("a chart is drawn only for a measured result", () => {
  const source = chart();
  assert.ok(source.includes("if (!result.measured || !chart || !chart.kind)"),
    "the chart is gated on the same flag as the figure");
});

test("the chart dispatcher draws with the shared primitives, not its own", () => {
  const source = chart();
  assert.ok(source.includes('from "@/components/analytics/charts"'),
    "charts come from the one chart engine");
  for (const forbidden of ["from \"recharts\"", "<svg", "<canvas"]) {
    assert.ok(!source.includes(forbidden),
      `the dispatcher must not draw ${forbidden} itself`);
  }
});

test("every chart kind the registry declares has a renderer", () => {
  const source = chart();
  // The kinds the backend registry attaches. A kind with no entry renders
  // nothing, which is safe — but it is also a silently missing chart, so the
  // list is pinned here rather than discovered at runtime.
  for (const kind of [
    "waterfall", "distribution", "heatmap", "roc", "cap", "ks",
    "band_rate", "lift", "gains", "trend", "calibration", "psi_trend",
    "ranking", "woe", "matrix", "tornado",
  ]) {
    assert.ok(source.includes(`  ${kind}:`), `${kind} has a renderer`);
  }
});

test("the cockpit shows coverage beside the results", () => {
  const source = page();
  assert.ok(source.includes("run.measured") && source.includes("run.returned"),
    "how many tests produced a number, against how many were returned");
  assert.ok(source.includes("run.coverage_means"),
    "and the backend's own sentence explaining what that counts");
});

test("nothing is reported as passing before anything has run", () => {
  const source = page();
  assert.ok(source.includes("Nothing has been run yet, and nothing is shown"),
    "the empty state says so rather than showing an encouraging green");
});

test("an empty findings list is not reported as a clean model", () => {
  const source = page();
  assert.ok(source.includes("read the coverage figure above before treating"),
    "no breach among the tests that ran is not a clean bill of health");
});

test("the generated report is called a draft", () => {
  const source = page();
  assert.ok(source.includes("Draft report"), "the button says draft");
  assert.ok(source.includes("does not issue validation opinions"),
    "and the page says who does");
});

test("there is no single score for the model as a whole", () => {
  const source = page();
  for (const invented of [
    "overallScore", "healthScore", "validationScore", "percentComplete",
  ]) {
    assert.ok(!source.includes(invented),
      `${invented} would be a number no validator would sign`);
  }
});

test("switching scorecard clears the results", () => {
  const source = page();
  assert.ok(source.includes("function chooseModel"),
    "the switch is an act, not an effect reacting to one");
  const body = source.slice(source.indexOf("function chooseModel"));
  const end = body.indexOf("\n  }");
  assert.ok(body.slice(0, end).includes("setRun(null)"),
    "and it clears the previous model's results in the same act");
});

test("the three scorecards are named as the whole scope", () => {
  const source = page();
  assert.ok(source.includes("Three, and only three"),
    "the restriction is stated on the screen, not only in the backend");
});
