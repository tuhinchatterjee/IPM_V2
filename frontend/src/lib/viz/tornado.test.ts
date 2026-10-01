import assert from "node:assert/strict";
import test from "node:test";

import { hover, rowLabel, tornado, type TornadoRow } from "./tornado.ts";

const row = (o: Partial<TornadoRow>): TornadoRow => ({
  factor_id: "MEV03", factor_name: "Unemployment rate", series_id: "corp.MEV03", shock_label: "±1 pp", conversion_up: "+1 percentage points",
  parameter: "pd_pit_12m", parameter_label: "PD 12m", family: "pd", coefficient: 0.155, native_derivative: 0.38, native_derivative_unit: "pp of PD per pp",
  sign: "+", parameter_baseline: 0.021, up_pp: 0.38, down_pp: -0.38, swing_pp: 0.38, readiness: "SUPPORTED_ESTIMATE", method: "ridge-logit-difference-1.0",
  lag: 1, train_start: "2021Q3", train_end: "2025Q4", training_periods: 18, sign_stability: 0.97, sign_review: null, warnings: [], ...o,
});

const ROWS = [
  row({ swing_pp: 1.26, up_pp: -1.26, down_pp: 1.26, factor_name: "Equity market index", factor_id: "MEV11", sign: "-", coefficient: -0.02, parameter: "pd_lifetime", parameter_label: "PD lifetime" }),
  row({}),
  row({ factor_id: "MEV10", factor_name: "Commercial property price index", parameter: "lgd_pct", parameter_label: "LGD", family: "lgd", coefficient: 0.005, up_pp: 0.51, down_pp: -0.51, swing_pp: 0.51, sign_review: "SIGN_REVIEW: the governed slope moves LGD DOWN (-0.513 pp) when collateral values fall." }),
];

test("TOR01 a Plotly tornado: two horizontal bar traces from zero, largest swing on top", () => {
  const f = tornado(ROWS);
  assert.equal(f.data.length, 2);
  for (const t of f.data) {
    assert.equal(t.type, "bar");
    assert.equal(t.orientation, "h");
    assert.equal(t.base, 0);
  }
  const y = f.data[0].y as string[];
  assert.equal(y[y.length - 1], "Equity market index → PD lifetime");
  assert.equal(y[0], "Commercial property price index → LGD ⚠");
});

test("TOR02 values are the server's, signs as fitted (a negative slope is drawn negative)", () => {
  const f = tornado(ROWS);
  const up = f.data[1].x as number[];
  const down = f.data[0].x as number[];
  assert.equal(up[2], -1.26); // equity: up shock lowers PD, kept negative
  assert.equal(down[2], 1.26);
  assert.equal(up[0], 0.51); // LGD rises with the price index: shown, not corrected
});

test("TOR03 PD and LGD are distinct in label and colour", () => {
  const f = tornado(ROWS);
  const colours = (f.data[1].marker as { color: string[] }).color;
  assert.notEqual(colours[0], colours[1]);
  assert.match(rowLabel(ROWS[2]), /→ LGD/);
  assert.match(rowLabel(ROWS[1]), /→ PD 12m/);
});

test("TOR04 hover carries MEV, series, shock, coefficient, parameter, movement, sign, status, method, window and the sign review", () => {
  const h = hover(ROWS[2], "down");
  for (const s of ["Commercial property price index", "corp.MEV03", "±1 pp", "coefficient 0.005", "LGD", "-0.510 pp", "sign +", "SUPPORTED_ESTIMATE", "ridge-logit", "2021Q3–2025Q4", "SIGN_REVIEW"]) {
    assert.ok(h.includes(s), s);
  }
  assert.ok(!hover(ROWS[1], "up").includes("SIGN_REVIEW"));
});
