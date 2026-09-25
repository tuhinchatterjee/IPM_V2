import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatMetric,
  formatRate,
  statusLabel,
  statusTone,
} from "./format.ts";

test("an unknown metric is shown as unknown with its reason, never 0", () => {
  const text = formatMetric({
    value: null,
    unit: "ms",
    status: "UNAVAILABLE",
    source: "",
    missing_reason: "non-streaming route",
    definition: "",
  });
  assert.equal(text, "unknown — non-streaming route");
  assert.ok(!text.includes("0"));
});

test("a measured metric carries its status", () => {
  assert.equal(
    formatMetric({
      value: 412.4,
      unit: "ms",
      status: "MEASURED",
      source: "x",
      missing_reason: "",
      definition: "",
    }),
    "412 ms (measured)",
  );
});

test("a rate with no denominator is N/A, not 0%", () => {
  assert.equal(formatRate({ numerator: 0, denominator: 0 }), "N/A (nothing assessed)");
  assert.equal(formatRate({ numerator: 1, denominator: 4 }), "1/4 (25%)");
});

test("every status has a text label; colour is never the only signal", () => {
  for (const s of ["PASS", "FAIL", "NOT_OBSERVED", "NOT_REACHED", "UNSUPPORTED"]) {
    assert.ok(statusLabel(s).length > 2);
  }
  assert.equal(statusTone("NOT_OBSERVED"), "muted");
  assert.equal(statusTone("PASS"), "positive");
});
