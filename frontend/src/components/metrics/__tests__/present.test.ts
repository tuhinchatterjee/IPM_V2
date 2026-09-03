/**
 * How a metric is allowed to read on screen.
 *
 * Two things can be broken by presentation alone, with the backend correct:
 * a number formatted as if it were something else, and a period rule shown as
 * the raw token nobody outside this codebase can parse. Both are one line
 * away, and both are tested here.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { coerce, formatMetric, readablePeriodRule } from "../present.ts";

describe("a metric's own unit decides how it reads", () => {
  it("shows a percentage as a percentage", () => {
    assert.equal(formatMetric(6.183704, "percent", 2), "6.18%");
    assert.equal(formatMetric(100, "percent", 2), "100.00%");
  });

  it("shows a ratio to the decimals the metric declares", () => {
    assert.equal(formatMetric(0.4369014, "ratio", 4), "0.4369");
    assert.equal(formatMetric(0.4369014, "ratio", 2), "0.44");
  });

  it("shows a count as a whole number", () => {
    assert.equal(formatMetric(475000, "count"), "475,000");
  });

  it("does not put decimals on a large currency figure", () => {
    // A committee reading exposures in millions does not need fils.
    assert.equal(formatMetric(127247.897, "currency", 2), "127,248");
  });

  it("keeps decimals on a small currency figure", () => {
    assert.notEqual(formatMetric(12.5, "currency", 2), "13");
  });
});

describe("a missing number is a dash, never a zero", () => {
  it("never renders null or undefined as 0", () => {
    for (const value of [null, undefined, Number.NaN]) {
      const shown = formatMetric(value, "percent", 2);
      assert.equal(shown, "—");
      assert.notEqual(shown, "0.00%");
    }
  });

  it("still shows a real zero", () => {
    assert.equal(formatMetric(0, "percent", 2), "0.00%");
  });
});

describe("the period rule is said in words", () => {
  it("explains the rule that would otherwise mislead", () => {
    // "latest_matured" is the one a reader would get wrong: it is not the
    // latest month, and a Gini for the latest month does not exist.
    const shown = readablePeriodRule("latest_matured");
    assert.match(shown, /performance window/i);
    assert.doesNotMatch(shown, /latest_matured/);
  });

  it("never shows a raw token", () => {
    for (const rule of [
      "latest_available",
      "latest_matured",
      "rolling_window",
      "as_selected",
      "something_new",
    ]) {
      assert.doesNotMatch(readablePeriodRule(rule), /_/);
    }
  });
});

describe("a value typed into a filter keeps the type it was written as", () => {
  it("reads a whole number as a number", () => {
    // `stage = 2` against an integer column has to compare numerically. As
    // the string "2" it either errors in the compiler or matches nothing,
    // and a filter that quietly matches nothing is the dangerous one.
    assert.equal(coerce("2"), 2);
    assert.equal(coerce(" 2 "), 2);
  });

  it("reads a decimal and a negative as numbers", () => {
    assert.equal(coerce("0.05"), 0.05);
    assert.equal(coerce("-30"), -30);
  });

  it("reads the two boolean words as booleans", () => {
    assert.equal(coerce("true"), true);
    assert.equal(coerce("TRUE"), true);
    assert.equal(coerce("false"), false);
    assert.equal(coerce("False"), false);
  });

  it("leaves everything else a string", () => {
    // Including things that look almost numeric. Guessing harder than this
    // is how a filter starts meaning something nobody wrote.
    assert.equal(coerce("Riyadh"), "Riyadh");
    assert.equal(coerce("2025-01"), "2025-01");
    assert.equal(coerce("30+"), "30+");
    assert.equal(coerce("1,000"), "1,000");
    assert.equal(coerce("1e5"), "1e5");
  });

  it("gives an empty box back as an empty string, not zero", () => {
    assert.equal(coerce(""), "");
    assert.equal(coerce("   "), "");
  });
});
