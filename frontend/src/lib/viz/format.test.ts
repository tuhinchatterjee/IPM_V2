import assert from "node:assert/strict";
import test from "node:test";

import { bps, count, moneyColumn, multiplier, pct, pctChange, raw, sar, sarDelta, scaleFor } from "./format.ts";

test("FMT02 narrative money is compact finance notation, never 'SAR million'", () => {
  assert.equal(sar(171), "SAR 171m");
  assert.equal(sar(2.6), "SAR 2.60m");
  assert.equal(sar(23300), "SAR 23.3bn");
  assert.equal(sar(0.845), "SAR 845k");
  for (const v of [171, 2.6, 23300, 0.845, 1e-5]) assert.ok(!sar(v).includes("million"));
});

test("FMT01 a table column carries its scale once in the header, plain numbers in cells", () => {
  const col = moneyColumn([23275, 171, 2.6]);
  assert.equal(col.header, "(SAR m)");
  assert.deepEqual(col.cells, ["23,275.00", "171.00", "2.60"]);
  const big = moneyColumn([23275, 18400, 9100]);
  assert.equal(big.header, "(SAR bn)");
  assert.deepEqual(big.cells, ["23.28", "18.40", "9.10"]);
  const small = moneyColumn([1.6929, 2.0315, 0.3386]);
  assert.equal(small.header, "(SAR m)");
  assert.deepEqual(small.cells, ["1.69", "2.03", "0.34"]);
  for (const c of [...col.cells, ...small.cells]) assert.ok(!/SAR|million/.test(c));
});

test("FMT05 PD is a percentage, never 0.02x", () => {
  assert.equal(pct(0.02), "2.00%");
  assert.equal(pct(0.2857), "28.57%");
  assert.ok(!pct(0.02).includes("x"));
});

test("FMT06 the multiplier notation is reserved for scenario multipliers", () => {
  assert.equal(multiplier(1.2), "×1.20");
});

test("FMT07 small Retail money changes remain visible and do not round to zero", () => {
  const col = moneyColumn([0.0004, 0.0012]);
  assert.ok(col.cells.every((c) => Number(c.replace(/,/g, "")) !== 0), JSON.stringify(col));
  assert.notEqual(sarDelta(0.34), "SAR 0");
  assert.equal(sarDelta(0.34), "+SAR 340k");
  assert.equal(sarDelta(-31), "−SAR 31.0m");
});

test("FMT04/FMT08 the raw value is never altered by display", () => {
  const v = 5231.577413502459;
  assert.equal(raw(v), "5231.577413502459 SAR million (raw)");
  sar(v);
  assert.equal(v, 5231.577413502459);
});

test("counts, basis points and changes", () => {
  assert.equal(count(14203.4), "14,203");
  assert.equal(bps(0.0014), "+14 bps");
  assert.equal(pctChange(0.182), "+18.2%");
  assert.equal(scaleFor([]), "SAR m");
});

test("FMT10 a money column states its scale once, cells carry no unit, the CSV keeps raw SAR million", async () => {
  const { moneyCol } = await import("./format.ts");
  const rows = [{ ead: "1250.5" }, { ead: "3400" }, { ead: "980.25" }, { ead: null }];
  const col = moneyCol("ead", "EAD", rows);
  assert.equal(col.label, "EAD (SAR bn)");
  assert.equal(col.csvLabel, "EAD (SAR million, raw)");
  assert.equal(col.format("3400"), "3.40");
  assert.equal(col.format(null), "—");
  assert.ok(!col.format("1250.5").includes("SAR"));
  const small = moneyCol("ecl", "ECL", [{ ecl: 12.5 }, { ecl: 40.25 }]);
  assert.equal(small.label, "ECL (SAR m)");
  assert.equal(small.format(40.25), "40.3");
});
