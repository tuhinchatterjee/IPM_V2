/**
 * Money published in whole currency units, formatted as whole currency units.
 *
 * The observed defect: the retail book publishes gross carrying amount in SAR,
 * and the formatter assumed every money column was already in millions. A
 * product holding 463,168,890 SAR was rendered "463,169" under a column header
 * reading "SAR bn". Every figure in the answer was a million times too large,
 * the ranking that followed disagreed with the table beside it, and nothing on
 * screen looked wrong.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { figure, scaleMoney, type ColumnSpec } from "../format.ts";

const SAR: ColumnSpec = {
  name: "gross_carrying_amount",
  label: "Gross carrying amount",
  semantic: "money",
  unit: "SAR",
  currency: "SAR",
  scale: "",
};

const SAR_MILLIONS: ColumnSpec = { ...SAR, unit: "SAR mn", scale: "mn" };

describe("money scale", () => {
  it("reads a whole-SAR column as whole SAR", () => {
    const f = figure(463_168_889.69, SAR);
    assert.equal(f.unit, "SAR mn");
    assert.equal(f.text, "463.2");
  });

  it("keeps a billion-scale total in billions", () => {
    const f = figure(2_082_852_855.82, SAR);
    assert.equal(f.unit, "SAR bn");
    assert.equal(f.text, "2.08");
  });

  it("leaves a single facility in plain SAR", () => {
    const f = figure(48_250, SAR);
    assert.equal(f.unit, "SAR");
    assert.equal(f.text, "48,250");
  });

  it("still reads a book kept in millions as millions", () => {
    const f = figure(12_261, SAR_MILLIONS);
    assert.equal(f.unit, "SAR bn");
    assert.equal(f.text, "12.3");
    assert.equal(figure(840, SAR_MILLIONS).unit, "SAR mn");
  });

  it("orders the same way the figures do", () => {
    // The defect that reached a user: the largest product in the table was not
    // the product the answer named as largest.
    const rows = [
      { label: "Personal Finance", value: 463_168_889.69 },
      { label: "Home Finance", value: 1_330_366_000.0 },
    ];
    const largest = [...rows].sort((a, b) => b.value - a.value)[0];
    const shown = rows.map((r) => ({ ...r, f: figure(r.value, SAR) }));
    const biggestShown = shown.find((r) => r.f.unit === "SAR bn");
    assert.equal(largest.label, biggestShown?.label);
  });

  it("treats an unscaled call the same as an unscaled column", () => {
    assert.deepEqual(scaleMoney(2_082_852_855.82, "SAR", ""),
                     figure(2_082_852_855.82, SAR));
  });
});
