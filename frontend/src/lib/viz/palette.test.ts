import assert from "node:assert/strict";
import test from "node:test";

import { DRIVERS, SEMANTIC, driverColor, driverOrder, luminance } from "./palette.ts";

test("VIZ14 the §10.2 semantic tokens are exactly the specification's", () => {
  assert.equal(SEMANTIC.baseline, "#64748B");
  assert.equal(SEMANTIC.pd, "#7C3AED");
  assert.equal(SEMANTIC.lgd, "#F59E0B");
  assert.equal(SEMANTIC.ccf, "#0EA5E9");
  assert.equal(SEMANTIC.stage, "#EC4899");
  assert.equal(SEMANTIC.macro, "#14B8A6");
  assert.equal(SEMANTIC.userDefined, "#6366F1");
  assert.equal(SEMANTIC.increase, "#EF4444");
  assert.equal(SEMANTIC.decrease, "#10B981");
  assert.equal(SEMANTIC.residual, "#94A3B8");
});

test("driver identity is stable: unique ids, fixed order, colour by id", () => {
  const ids = DRIVERS.map((d) => d.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(driverOrder("pd"), 0);
  assert.ok(driverOrder("residual") === ids.length - 1);
  assert.equal(driverColor("pd"), SEMANTIC.pd);
  assert.equal(driverColor("unknown"), SEMANTIC.residual);
});

test("increase and decrease are separable without hue (luminance differs)", () => {
  const diff = Math.abs(luminance(SEMANTIC.increase) - luminance(SEMANTIC.decrease));
  assert.ok(diff > 0.05, `luminance difference ${diff}`);
});
