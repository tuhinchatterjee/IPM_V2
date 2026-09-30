import assert from "node:assert/strict";
import test from "node:test";

import { categoryBars, contributions, sparkline, stageMix, trend } from "./figures.ts";
import { SEMANTIC, STAGE_COLORS } from "./palette.ts";

type Trace = Record<string, unknown> & { customdata: unknown[]; x: unknown[]; y: unknown[] };

test("FIG01 sparkline emphasises the last point and formats hover in the metric's unit", () => {
  const fig = sparkline(
    [
      { period: "2026Q1", value: 1200 },
      { period: "2026Q2", value: 1940 },
    ],
    "SAR_mn",
  );
  const t = fig.data[0] as Trace & { marker: { size: number[] } };
  assert.deepEqual(t.x, ["2026Q1", "2026Q2"]);
  assert.deepEqual(t.marker.size, [3, 7]);
  assert.equal(t.customdata[1], "SAR 1.94bn");
  assert.equal((fig.layout.xaxis as { visible: boolean }).visible, false);
});

test("FIG02 trend scales money series to ONE shared unit and keeps the raw value in hover", () => {
  const fig = trend([
    { name: "ECL", unit: "SAR_mn", points: [{ period: "a", value: 1200 }, { period: "b", value: 3000 }] },
    { name: "ECL (peer)", unit: "SAR_mn", points: [{ period: "a", value: 800 }, { period: "b", value: null }] },
  ]);
  const [a, b] = fig.data as Trace[];
  assert.deepEqual(a.y, [1.2, 3]);
  assert.deepEqual(b.y, [0.8, null], "a missing value stays missing, never zero");
  assert.match((a.customdata[0] as string[])[0], /^SAR 1\.2/);
  assert.equal((a.customdata[0] as string[])[1], "1200");
  assert.equal(((fig.layout.yaxis as { title: { text: string } }).title.text), "SAR bn");
});

test("FIG03 trend shows a fraction metric as percent on the axis", () => {
  const fig = trend([{ name: "Stage 2 share", unit: "fraction", points: [{ period: "a", value: 0.125 }] }]);
  assert.deepEqual((fig.data[0] as Trace).y, [12.5]);
  assert.equal(((fig.layout.yaxis as { title: { text: string } }).title.text), "%");
});

test("FIG04 contributions: sorted by magnitude, sign-coloured, label carried in customdata for drill", () => {
  const fig = contributions(
    [
      { label: "Hospitality", value: 4.2 },
      { label: "Construction", value: -12.5 },
      { label: "Real Estate", value: 20 },
    ],
    "SAR_mn",
    { dimension: "sector" },
  );
  const t = fig.data[0] as Trace & { marker: { color: string[] }; text: string[] };
  // Plotly draws horizontal bars bottom-up, so the largest is LAST.
  assert.deepEqual(t.y, ["Hospitality", "Construction", "Real Estate"]);
  assert.deepEqual(t.marker.color, [SEMANTIC.increase, SEMANTIC.decrease, SEMANTIC.increase]);
  assert.equal(t.text[1], "−SAR 12.5m");
  assert.deepEqual(t.customdata.map((c) => (c as string[])[0]), ["Hospitality", "Construction", "Real Estate"]);
});

test("FIG05 contributions never show more than twelve bars", () => {
  const rows = Array.from({ length: 20 }, (_, i) => ({ label: `s${i}`, value: i + 1 }));
  const t = contributions(rows, "count").data[0] as Trace;
  assert.equal(t.y.length, 12);
  assert.ok(t.y.includes("s19") && !t.y.includes("s0"), "the twelve largest are kept");
});

test("FIG06 stage mix uses the governed stage colours and stacks", () => {
  const fig = stageMix([
    { stage: 1, n: 10, ead: 900, ecl: 5 },
    { stage: 2, n: 3, ead: 80, ecl: 6 },
    { stage: 3, n: 1, ead: 20, ecl: 9 },
  ]);
  assert.equal(fig.layout.barmode, "stack");
  assert.deepEqual(
    fig.data.map((d) => (d.marker as { color: string }).color),
    [STAGE_COLORS["1"], STAGE_COLORS["2"], STAGE_COLORS["3"]],
  );
});

test("FIG07 category bars grey out what is not selected (cross-filter context)", () => {
  const fig = categoryBars(
    [
      { value: "Auto Finance", n: 10, ecl_sar_mn: 1.2 },
      { value: "BNPL", n: 4, ecl_sar_mn: 0.4 },
    ],
    "ecl_sar_mn",
    { dimension: "product", selected: ["BNPL"] },
  );
  const colors = (fig.data[0].marker as { color: string[] }).color;
  assert.equal(colors[0], SEMANTIC.context);
  assert.notEqual(colors[1], SEMANTIC.context);
  assert.match(String((fig.layout.yaxis as { title: { text: string } }).title.text), /^ECL \(SAR /);
});
