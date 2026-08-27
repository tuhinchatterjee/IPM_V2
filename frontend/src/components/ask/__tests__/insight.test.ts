import assert from "node:assert/strict";
import { test } from "node:test";

import { sentences } from "../insight.ts";

/**
 * The selection functions take a full `InvestigationResponse`, which is a large
 * type to build by hand; they are exercised through the sentence splitter and
 * through the response-UI tests. The splitter is asserted directly because its
 * failure mode — cutting a figure in half — is the one §52 must not produce.
 */

test("an ordinary paragraph splits into its sentences", () => {
  assert.deepEqual(
    sentences("Contracting rose most. Manufacturing was flat. Retail fell."),
    ["Contracting rose most.", "Manufacturing was flat.", "Retail fell."],
  );
});

test("a decimal is never a sentence boundary", () => {
  // "rose 12.4% over" must not become "rose 12." + "4% over": a highlight that
  // ends mid-figure draws the eye to half a number.
  assert.deepEqual(sentences("ECL rose 12.4% over the year."), [
    "ECL rose 12.4% over the year.",
  ]);
});

test("an abbreviation followed by a lowercase word does not split", () => {
  assert.deepEqual(sentences("Compared with Q1 2025 vs. the prior year."), [
    "Compared with Q1 2025 vs. the prior year.",
  ]);
});

test("a quoted sentence opening is a boundary", () => {
  assert.equal(sentences('It fell. "Contracting" is the exception.').length, 2);
});

test("empty and blank input produce nothing rather than an empty sentence", () => {
  assert.deepEqual(sentences(""), []);
  assert.deepEqual(sentences("   "), []);
});
