import assert from "node:assert/strict";
import test from "node:test";

import { breakdownFigure, clickFilter, groupsFigure, kpiTile, trendFigure } from "./lens-figures.ts";
import type { RenderedVisual } from "./lenses.ts";

const base: RenderedVisual = { visual_id: "v1", type: "kpi", title: "Stage 2 EAD share", domain: "corporate", status: "OK", unit: "fraction", direction: "lower_is_better", metric_id: "M005", metric_version: 1, prior_period: "2026Q1" };

test("LENS01 a worse move by the metric's own direction is 'bad', with a signed label", () => {
  const k = kpiTile({ ...base, value: 0.004, prior: 0.003 });
  assert.equal(k.tone, "bad");
  assert.match(k.delta, /^\+0\.10 pp vs 2026Q1$/);
  assert.equal(k.metric, "M005 v1");
  assert.equal(kpiTile({ ...base, direction: "higher_is_better", value: 0.004, prior: 0.003 }).tone, "good");
  assert.equal(kpiTile({ ...base, value: null, note: "none yet" }).value, "—");
});

test("LENS02 a category click becomes a cross-filter on that dimension and book", () => {
  const v: RenderedVisual = { ...base, type: "breakdown", group_by: "sector", groups: [{ dimension: "Construction", value: 0.1, rows: 3 }] };
  assert.deepEqual(clickFilter(v, ["Construction"]), { column: "sector", op: "in", values: ["Construction"], domain: "corporate" });
  assert.deepEqual(clickFilter({ ...v, type: "stage_mix" }, ["2"]), { column: "stage", op: "in", values: [2], domain: "corporate" });
  assert.equal(clickFilter({ ...v, type: "kpi" }, ["x"]), null);
  assert.equal((breakdownFigure(v).data[0] as { x: string[] }).x[0], "Construction");
});

test("LENS03 trends keep periods as categories (quarters and months never reinterpreted)", () => {
  const fig = trendFigure({ ...base, type: "trend", series: [{ metric_id: "M001", metric_version: 1, name: "Booked ECL", unit: "SAR_mn", points: [{ period: "2026Q1", value: 1 }, { period: "2026Q2", value: 2 }] }] });
  assert.equal((fig.layout.xaxis as { type: string }).type, "category");
});

test("LENS04 group charts drop nulls and sign-colour the rest", () => {
  const fig = groupsFigure({ ...base, type: "scenario_results", unit: "SAR_mn", groups: [{ dimension: "A", value: 5 }, { dimension: "B", value: null }, { dimension: "C", value: -1 }] });
  assert.equal((fig.data[0] as { y: string[] }).y.length, 2);
});
