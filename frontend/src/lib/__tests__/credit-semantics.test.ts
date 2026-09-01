import assert from "node:assert/strict";
import { test } from "node:test";

import { describeMeaning, meaningOf } from "../credit-semantics.ts";

test("a rising risk measure is adverse and a falling one is favourable", () => {
  assert.equal(meaningOf(12.4, "up-is-bad"), "adverse");
  assert.equal(meaningOf(-12.4, "up-is-bad"), "favourable");
});

test("a rising performance measure is favourable", () => {
  // Cure rate, recovery rate, collateral coverage: up is the good direction.
  assert.equal(meaningOf(3.1, "up-is-good"), "favourable");
  assert.equal(meaningOf(-3.1, "up-is-good"), "adverse");
});

test("the sign alone never decides", () => {
  // The whole point: the same +1.8 means opposite things for two measures.
  assert.notEqual(meaningOf(1.8, "up-is-bad"), meaningOf(1.8, "up-is-good"));
});

test("nothing moved is neutral, whatever the measure", () => {
  assert.equal(meaningOf(0, "up-is-bad"), "neutral");
  assert.equal(meaningOf(0, "up-is-good"), "neutral");
});

test("an ungoverned measure is not coloured", () => {
  // A miscoloured risk figure tells a credit officer the opposite of the
  // truth. Not colouring is the safe failure, so there is no name-guessing.
  assert.equal(meaningOf(12.4, "neutral"), "neutral");
  assert.equal(meaningOf(12.4, undefined), "neutral");
});

test("a missing or unusable change is neutral rather than an error", () => {
  assert.equal(meaningOf(null, "up-is-bad"), "neutral");
  assert.equal(meaningOf(undefined, "up-is-bad"), "neutral");
  assert.equal(meaningOf(Number.NaN, "up-is-bad"), "neutral");
});

test("assistive text carries what the colour carries", () => {
  assert.equal(
    describeMeaning("Contracting ECL", "+12.4%", "adverse"),
    "Contracting ECL +12.4% — adverse for credit risk",
  );
  assert.equal(describeMeaning("Total EAD", "125,259", "neutral"), "Total EAD 125,259");
});
