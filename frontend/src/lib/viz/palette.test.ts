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
  assert.equal(driverOrder("opening"), 0);
  assert.equal(driverOrder("closing"), ids.length - 1);
  assert.ok(driverOrder("pd") < driverOrder("lgd") && driverOrder("lgd") < driverOrder("residual"));
  assert.equal(driverColor("pd"), SEMANTIC.pd);
  assert.equal(driverColor("unknown"), SEMANTIC.residual);
});

test("increase and decrease are separable without hue (luminance differs)", () => {
  const diff = Math.abs(luminance(SEMANTIC.increase) - luminance(SEMANTIC.decrease));
  assert.ok(diff > 0.05, `luminance difference ${diff}`);
});

test("decomposition colours are varied: no two components share a colour", () => {
  const colours = DRIVERS.map((d) => d.color.toLowerCase());
  assert.equal(new Set(colours).size, colours.length);
  const blues = colours.filter((c) => ["#2563eb", "#0ea5e9", "#0891b2"].includes(c));
  assert.ok(blues.length <= 3, "not a wall of blue");
});
