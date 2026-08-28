import assert from "node:assert/strict";
import { test } from "node:test";

import { showingFor } from "../presentation.ts";

/**
 * The precedence between the registry's judgement and the reader's.
 *
 * The storage functions themselves need a browser; this is the decision they
 * exist to serve, and it is the part that can be wrong.
 */

test("with nothing remembered the registry decides", () => {
  assert.equal(showingFor("chart", {}), "chart");
  assert.equal(showingFor("table", {}), "table");
});

test("the reader's choice wins over the registry", () => {
  assert.equal(showingFor("chart", { showing: "table" }), "table");
  assert.equal(showingFor("table", { showing: "chart" }), "chart");
});

test("an unrelated remembered preference does not change the default", () => {
  assert.equal(showingFor("chart", { kind: "line" }), "chart");
});
