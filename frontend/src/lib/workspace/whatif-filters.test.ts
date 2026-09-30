import assert from "node:assert/strict";
import test from "node:test";

import { EXPLORER_DIMENSIONS, selectedValues, setFilterValues, toggleFilterValue } from "./whatif-filters.ts";
import type { Filter } from "./objects.ts";

test("WIF01 a chart click adds its value as an `in` filter, a second click removes it", () => {
  const one = toggleFilterValue([], "sector", "Construction");
  assert.deepEqual(one, [{ column: "sector", op: "in", values: ["Construction"] }]);
  const two = toggleFilterValue(one, "sector", "Hospitality");
  assert.deepEqual(selectedValues(two, "sector"), ["Construction", "Hospitality"]);
  const back = toggleFilterValue(two, "sector", "Construction");
  assert.deepEqual(selectedValues(back, "sector"), ["Hospitality"]);
  assert.deepEqual(toggleFilterValue(back, "sector", "Hospitality"), []);
});

test("WIF02 cross-filter keeps every other column's filter untouched", () => {
  const start: Filter[] = [
    { column: "stage", op: "in", values: [2] },
    { column: "pd_pit_12m", op: "gte", value: 0.05 },
  ];
  const next = toggleFilterValue(start, "sector", "Construction");
  assert.equal(next.length, 3);
  assert.deepEqual(next.slice(0, 2), start);
});

test("WIF03 a box/lasso selection replaces that column's values; empty clears it", () => {
  const f = setFilterValues([{ column: "sector", op: "in", values: ["A"] }], "sector", ["B", "C"]);
  assert.deepEqual(f, [{ column: "sector", op: "in", values: ["B", "C"] }]);
  assert.deepEqual(setFilterValues(f, "sector", []), []);
});

test("WIF04 numeric categories (stage) match regardless of string/number form", () => {
  const f = toggleFilterValue([{ column: "stage", op: "in", values: [2] }], "stage", "2");
  assert.deepEqual(f, []);
});

test("WIF05 each book offers its own governed dimensions, never the other's", () => {
  const corp = EXPLORER_DIMENSIONS.corporate.map((d) => d.key);
  const retail = EXPLORER_DIMENSIONS.retail.map((d) => d.key);
  assert.ok(corp.includes("sector") && corp.includes("rating_current") && !corp.includes("product"));
  assert.ok(retail.includes("product") && retail.includes("score_band") && !retail.includes("sector"));
});
