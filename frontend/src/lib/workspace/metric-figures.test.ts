import assert from "node:assert/strict";
import test from "node:test";

import { breakdownBars, formatValue, gridDimension, metricTrend, plotValue } from "./metric-figures.ts";

test("MET01 values render by their governed unit", () => {
  assert.equal(formatValue(0.1234, "fraction"), "12.34%");
  assert.equal(formatValue(null, "SAR_mn"), "—");
  assert.equal(formatValue(1234, "count"), "1,234");
  assert.equal(plotValue(0.5, "fraction"), 50);
});

test("MET02 breakdown bars sort, keep the raw value and drop nulls", () => {
  const fig = breakdownBars(
    [
      { dimension: "A", value: 0.1, rows: 3 },
      { dimension: "B", value: 0.3, rows: 4 },
      { dimension: "C", value: null },
    ],
    "fraction",
    "sector",
  );
  const t = fig.data[0] as { x: string[]; y: number[]; customdata: string[][] };
  assert.deepEqual(t.x, ["B", "A"]);
  assert.deepEqual(t.y, [30, 10]);
  assert.equal(t.customdata[0][3], "0.3");
});

test("MET03 a trend draws one line per book", () => {
  const fig = metricTrend([{ name: "Corporate", points: [{ period: "2026Q1", value: 1 }] }, { name: "Retail", points: [{ period: "2026-08", value: 2 }] }], "SAR_mn");
  assert.equal(fig.data.length, 2);
});

test("MET04 only grid columns drill to rows", () => {
  assert.equal(gridDimension("sector|product", "retail"), "product");
  assert.equal(gridDimension("scenario", "corporate"), null);
  assert.equal(gridDimension("rating_current", "corporate"), "rating_current");
});
