import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { componentTable, identities, kpis, methodComparison, plotted, sharedScale, stageBeforeAfter, waterfall, type Decomposition } from "./decomposition.ts";
import { DRIVERS, driverColor } from "./palette.ts";

// A real engine decomposition (CORP-18, Delta), not a hand-made one.
const fixture = JSON.parse(readFileSync(new URL("./decomposition.fixture.json", import.meta.url), "utf8")) as { decomposition: Decomposition };
const d = fixture.decomposition;

test("DEC01 both scopes list every taxonomy component in the one order", () => {
  const order = DRIVERS.map((x) => x.id);
  assert.deepEqual(plotted(d.scopes.selected).map((c) => c.id), order);
  assert.deepEqual(plotted(d.scopes.total).map((c) => c.id), order);
});

test("DEC02 a component has the same colour and label in both scope charts", () => {
  const scale = sharedScale(d);
  const sel = waterfall(d.scopes.selected, { scale }).data[0] as { x: string[]; marker: { color: string[] } };
  const tot = waterfall(d.scopes.total, { scale }).data[0] as { x: string[]; marker: { color: string[] } };
  assert.deepEqual(sel.x, tot.x);
  assert.deepEqual(sel.marker.color, tot.marker.color);
  assert.equal(new Set(sel.marker.color).size, sel.marker.color.length, "varied colours, one per component");
});

test("DEC03 the waterfall walks opening + movements to closing", () => {
  const scale = "SAR m" as const;
  const fig = waterfall(d.scopes.selected, { scale, compact: true }).data[0] as { y: number[]; base: number[]; customdata: string[][] };
  const ids = fig.customdata.map((c) => c[0]);
  const last = ids.indexOf("closing");
  const opening = fig.y[0];
  let running = opening;
  for (let i = 1; i < last; i++) {
    const v = Number(fig.customdata[i][2] || 0);
    running += v;
    const top = fig.base[i] + fig.y[i];
    assert.ok(Math.abs((v >= 0 ? top : fig.base[i]) - running) < 1e-6, `${ids[i]} ends at the running total`);
  }
  assert.ok(Math.abs(running - fig.y[last]) < 1e-6, "closing equals opening plus every movement");
});

test("DEC04 the table beneath carries every plotted component, by id", () => {
  const table = componentTable(d);
  const tableIds = new Set(table.map((r) => r.id));
  for (const compact of [false, true]) {
    for (const c of plotted(d.scopes.selected, compact)) assert.ok(tableIds.has(c.id), c.id);
  }
  for (const r of table) assert.equal(r.colour, driverColor(r.id));
});

test("DEC05 N/A components are shown as N/A, never dropped or redefined", () => {
  const na = d.scopes.selected.components.filter((c) => c.status === "N/A");
  assert.ok(na.length > 0);
  const fig = waterfall(d.scopes.selected).data[0] as { text: string[]; customdata: string[][] };
  for (const c of na) {
    const i = fig.customdata.findIndex((x) => x[0] === c.id);
    assert.equal(fig.text[i], "N/A");
    assert.ok(c.reason.length > 0, `${c.id} carries its reason`);
  }
  assert.equal(plotted(d.scopes.selected, true).filter((c) => c.status === "N/A").length, 0);
});

test("DEC06 both identities hold on the published strings", () => {
  assert.deepEqual(identities(d), { selected: true, total: true, cross: true });
  const broken = structuredClone(d);
  broken.cross_scope.rest_of_book_delta = "5";
  assert.equal(identities(broken).cross, false);
});

test("DEC07 KPIs, method comparison and stage figures read the server's values", () => {
  const k = kpis(d.scopes.selected);
  assert.equal(k[0].raw, d.scopes.selected.opening);
  assert.equal(k[2].raw, d.scopes.selected.change);
  const mc = methodComparison({
    delta: { method: "delta", label: "Delta", status: "OK", ran: true, baseline: "10", scenario: "12", change: "2", change_pct: "20", reason: "", limitations: [] },
    ml: { method: "ml", label: "ML emulator", status: "UNAVAILABLE", ran: false, baseline: "10", scenario: null, change: null, change_pct: null, reason: "G4", limitations: [] },
  }).data[0] as { x: string[] };
  assert.deepEqual(mc.x, ["Delta"], "an unavailable method is never drawn as a zero");
  const st = stageBeforeAfter([{ stage: "1", exposures: 3, ead: "1", ecl_before: "1", ecl_after: "1.2", change: "0.2" }]);
  assert.equal(st.data.length, 2);
});

test("DEC08 a small movement on a large book cuts the axis and says so", () => {
  const scale = sharedScale(d);
  const total = waterfall(d.scopes.total, { scale, compact: true });
  const layout = total.layout as { yaxis: { range?: number[] }; annotations: { text: string }[] };
  assert.ok(layout.yaxis.range && layout.yaxis.range[0] > 0, "axis cut above zero");
  assert.equal(layout.annotations[0].text, "Axis does not start at zero");
  const selected = waterfall(d.scopes.selected, { scale, compact: true }).layout as { annotations: unknown[] };
  assert.ok(Array.isArray(selected.annotations));
});
