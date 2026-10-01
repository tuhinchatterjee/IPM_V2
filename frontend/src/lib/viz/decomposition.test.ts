import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { comparisonBars, componentTable, identities, kpis, methodComparison, plotted, scopeEquivalence, sharedScale, stageBeforeAfter, waterfall, type Decomposition } from "./decomposition.ts";
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

test("DEC09 a comparison plots every compared result, component by component, from the published values", () => {
  const comp = {
    domain_id: "corporate",
    period: "2026Q2",
    method: "delta",
    items: [
      { result_id: "res-a", version: 1, scenario_name: "A", baseline_mode: "SOURCE_BASELINE", chain: [], cohort: "", entities: 1, methods_ran: ["delta"] },
      { result_id: "res-b", version: 1, scenario_name: "B", baseline_mode: "SOURCE_BASELINE", chain: [], cohort: "", entities: 1, methods_ran: ["delta"] },
    ],
    kpis: [],
    components: d.scopes.selected.components.map((c) => ({
      id: c.id,
      label: c.label,
      kind: c.kind,
      values: { "res-a": { selected: { value: c.value, status: c.status } }, "res-b": { selected: { value: c.value, status: c.status } } },
    })),
    note: "",
  };
  const fig = comparisonBars(comp, "selected");
  assert.equal(fig.data.length, 2);
  const x = (fig.data[0] as { x: string[] }).x;
  assert.ok(!x.includes("Opening ECL") && !x.includes("New originations"), "totals and all-N/A components are not bars");
  assert.ok(x.includes("PD"));
});

/** The same population as both scopes, as the server publishes it (DECOMP21). */
function wholeBook(): Decomposition {
  const copy = JSON.parse(JSON.stringify(d)) as Decomposition;
  copy.selected_equals_total = true;
  copy.scopes.total = { ...JSON.parse(JSON.stringify(copy.scopes.selected)), scope: "total", label: "Total active book" };
  copy.cross_scope = {
    ...copy.cross_scope,
    selected_delta: copy.scopes.selected.change,
    rest_of_book_delta: "0",
    total_delta: copy.scopes.selected.change,
    scope_equivalence: "Selected scope = Total book",
  };
  return copy;
}

test("DEC10 selected scope = total book is proven component by component", () => {
  const eq = scopeEquivalence(wholeBook());
  assert.equal(eq.equal, true);
  assert.equal(eq.proven, true);
  assert.equal(eq.identical, eq.components);
  assert.ok(eq.components >= 20);
  assert.equal(eq.restOfBookZero, true);
  assert.equal(eq.deltasEqual, true);
  assert.deepEqual(eq.mismatches, []);
});

test("DEC11 one differing component, a non-zero rest of book, or no flag: not proven", () => {
  const one = wholeBook();
  const c = one.scopes.total.components.find((x) => x.status === "MEASURED") ?? one.scopes.total.components[1];
  c.value = String(Number(c.value ?? 0) + 1);
  const r = scopeEquivalence(one);
  assert.equal(r.proven, false);
  assert.deepEqual(r.mismatches, [c.id]);
  const rest = wholeBook();
  rest.cross_scope.rest_of_book_delta = "0.5";
  assert.equal(scopeEquivalence(rest).proven, false);
  assert.equal(scopeEquivalence(d).equal, false);
  assert.equal(scopeEquivalence(d).proven, false);
});
