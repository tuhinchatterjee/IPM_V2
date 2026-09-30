import assert from "node:assert/strict";
import test from "node:test";

import {
  blankComponent,
  componentMatrix,
  derivedRows,
  kindsFor,
  pendingOverlaps,
  readinessTone,
  resolutionsFrom,
  scopeBandFigure,
} from "./scenario-figures.ts";
import type { Overlap, Preview } from "./scenarios.ts";

const overlap = (over: Partial<Overlap>): Overlap => ({
  a: "A.c1",
  b: "B.c1",
  a_label: "PD +20%",
  b_label: "GDP -1.5 pp",
  shared_entities: 248,
  variables: ["pd"],
  status: "NEEDS_POLICY",
  overlap_id: "A.c1|B.c1|pd",
  variable: "pd",
  allowed: ["compound", "max", "min", "priority"],
  ...over,
});

test("SCN01 only overlaps still needing a decision are pending", () => {
  const pending = pendingOverlaps({
    overlaps: [overlap({}), overlap({ status: "RESOLVED", overlap_id: "x" }), overlap({ status: "INVALID_POLICY", overlap_id: "y" })],
  });
  assert.deepEqual(pending.map((o) => o.overlap_id), ["A.c1|B.c1|pd", "y"]);
});

test("SCN02 a blank choice is never defaulted into a resolution", () => {
  const out = resolutionsFrom([overlap({}), overlap({ overlap_id: "second" })], { "A.c1|B.c1|pd": "max" });
  assert.deepEqual(Object.keys(out), ["A.c1|B.c1|pd"]);
  assert.equal(out["A.c1|B.c1|pd"].policy, "max");
  assert.deepEqual(out["A.c1|B.c1|pd"].order, ["A.c1", "B.c1"]);
});

test("SCN03 readiness tones never show a blocked scenario as ready", () => {
  assert.equal(readinessTone("BLOCKED"), "negative");
  assert.equal(readinessTone("READY_FOR_CONFIRMATION"), "positive");
  assert.equal(readinessTone("READY_WITH_USER_DEFINED_INPUTS"), "warning");
});

test("SCN04 the component matrix names each carried component's source", () => {
  const rows = componentMatrix(
    {
      components: [
        {
          component_id: "A.c1",
          kind: "parameter",
          label: "PD +20%",
          status: "DIRECT",
          families: ["pd"],
          population: { entities: 248, owners: 100, ead: 1, ecl: 1, mean_pd: 0.02, mean_lgd_pct: 30 },
          methods: { delta: "COMPATIBLE", ml: "COMPATIBLE", user_defined: "COMPATIBLE" },
          translation: null,
        },
      ],
    },
    {
      components: [
        {
          component_id: "A.c1",
          kind: "parameter",
          operation: "relative_pct",
          value: "20",
          source: { object_id: "scn-1", version: 3, component_id: "c1", scenario: "Construction" },
        },
      ],
    },
  );
  assert.equal(rows[0].source, "Construction v3 · c1");
  assert.equal(rows[0].variables, "pd");
});

test("SCN05 derived macro rows keep the sign and the governed slope", () => {
  const rows = derivedRows({
    derived: [
      { field: "pd_pit_12m", value: "0.304396", parameter_baseline: 0.0214, parameter_scenario: 0.0245, native_derivative: 0.3044, native_derivative_unit: "pp per pp", lag: 1 },
      { field: "lgd_pct", value: "-0.126054", parameter_baseline: 0.29, parameter_scenario: 0.2897, native_derivative: 0.084, native_derivative_unit: "pp per pp", lag: 1 },
    ],
  });
  assert.equal(rows[0].change, "+0.304 pp");
  assert.equal(rows[1].change, "-0.126 pp");
  assert.equal(rows[0].slope, 0.3044);
});

test("SCN06 the band figure plots the server's band mix, one bar per band", () => {
  const fig = scopeBandFigure({
    scope: {
      type: "whole_book",
      summary: {
        entities: 3,
        owners: 3,
        ead: 30,
        ecl: 1,
        stage_mix: [],
        band_dimension: "rating_current",
        band_mix: [
          { band: "BB", n: 2, ead: 20 },
          { band: "B", n: 1, ead: 10 },
        ],
        period: "2026Q2",
      },
      share_of_book_ead: 1,
      share_of_book_ecl: 1,
      book: { entities: 3, ead: 30, ecl: 1 },
    },
  } as Pick<Preview, "scope">);
  assert.deepEqual((fig.data[0] as { x: string[] }).x, ["BB", "B"]);
});

test("SCN07 builder offers ratings only to Corporate and scores only to Retail", () => {
  assert.ok(kindsFor("corporate").includes("rating") && !kindsFor("corporate").includes("score"));
  assert.ok(kindsFor("retail").includes("score") && !kindsFor("retail").includes("rating"));
  assert.equal(blankComponent("macro", "retail").operation, "basis_points");
  assert.equal(blankComponent("collateral", "retail").asset, "residential_property");
});
