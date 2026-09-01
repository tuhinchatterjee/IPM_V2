import assert from "node:assert/strict";
import { test } from "node:test";

import { openingView, showingFor } from "../presentation.ts";

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

/**
 * §11 — DATA FIRST, GRAPH OPTIONAL.
 *
 * The screen used to derive this from the result's column shape: a label
 * column and a number column meant a bar chart, whatever had been asked. That
 * geometry is identical for "show the distribution of DPD" and "list the
 * twenty borrowers with the highest PD", so half the answers in the product
 * opened as pictures of lists.
 */

test("with no governed decision the table opens", () => {
  assert.equal(openingView(undefined), "table");
  assert.equal(openingView(null), "table");
});

test("a chart opens only when the gate said so", () => {
  assert.equal(openingView(true), "chart");
  assert.equal(openingView(false), "table");
});

test("the reader still overrides the opening view", () => {
  assert.equal(showingFor(openingView(true), { showing: "table" }), "table");
  assert.equal(showingFor(openingView(false), { showing: "chart" }), "chart");
});
