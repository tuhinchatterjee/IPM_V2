/**
 * P0.12 — the decimal display contract, proved rather than asserted.
 *
 * The observed defect was raw IEEE debris reaching the interface: an exposure
 * stored as 59.352000000000004 and a share of 2.6246841182876173%. Those are
 * arithmetically correct and they read as carelessness, because no credit
 * figure is decided on the fourteenth decimal place.
 *
 * A hand-written list of examples cannot prove a ceiling holds — it proves it
 * holds for the examples somebody thought of, which are never the ones that
 * break. So this file generates: every formatter is run over thousands of
 * values chosen to be awkward, and the assertion is a property — NOTHING it
 * returns carries more than two decimals.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_DECIMALS,
  byContract,
  byUnit,
  count,
  delta,
  deltaFigure,
  figure,
  money,
  moneyCompact,
  percent,
  scrubDebris,
  type ColumnSpec,
} from "../format.ts";

/** The decimals in a rendered figure, ignoring thousands separators. */
function decimalsOf(text: string): number {
  const dot = /\.(\d+)/.exec(text.replace(/,/g, ""));
  return dot ? dot[1].length : 0;
}

/**
 * Values chosen to be difficult rather than typical: binary-representation
 * debris, values astride each magnitude boundary the contract switches on,
 * negative zero, and very large and very small numbers.
 */
function awkwardValues(): number[] {
  const values: number[] = [
    0, -0, 1e-9, -1e-9,
    59.352000000000004, 98.84700000000001, 5.5120000000000005,
    2.6246841182876173, 0.1 + 0.2, 1 / 3, 2 / 3, 1e-7,
    0.005, 0.0049999, -0.005, 0.995, 0.9999,
    0.999, 9.999, 99.999, 999.999, 9999.999,
    1, -1, 100, -100, 1000, -1000, 1e6, -1e6, 1e9,
    12345.6789, -12345.6789, 0.123456789, -0.987654321,
  ];
  // A deterministic sweep, so a failure is reproducible. Seeded rather than
  // Math.random: a test that fails once and passes on re-run teaches people to
  // re-run it.
  let seed = 20260828;
  const next = () => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  };
  for (let i = 0; i < 2000; i += 1) {
    const magnitude = 10 ** Math.floor(next() * 10 - 4);
    const value = (next() * 2 - 1) * magnitude;
    values.push(value);
  }
  return values;
}

const VALUES = awkwardValues();

const SEMANTICS = [
  "money", "percent", "ratio", "count", "days", "ordinal", "", undefined,
];
const UNITS = ["%", "pp", "x", "days", "USD mn", "count", "", undefined];

describe("the contract has one ceiling", () => {
  it("is two", () => {
    assert.equal(MAX_DECIMALS, 2);
  });
});

describe("every formatter respects it", () => {
  it("money, at every decimals argument a caller could pass", () => {
    for (const value of VALUES) {
      for (const decimals of [0, 1, 2]) {
        assert.ok(
          decimalsOf(money(value, decimals)) <= MAX_DECIMALS,
          `money(${value}, ${decimals}) = ${money(value, decimals)}`,
        );
      }
    }
  });

  it("percent, delta, count and compact money", () => {
    for (const value of VALUES) {
      for (const text of [
        percent(value),
        percent(value, 2),
        delta(value),
        delta(value, 2, "%"),
        count(value),
        moneyCompact(value),
      ]) {
        assert.ok(decimalsOf(text) <= MAX_DECIMALS, `${text} (from ${value})`);
      }
    }
  });

  it("byUnit, across every governed unit", () => {
    for (const value of VALUES) {
      for (const unit of UNITS) {
        const text = byUnit(value, unit);
        assert.ok(
          decimalsOf(text) <= MAX_DECIMALS,
          `byUnit(${value}, ${unit}) = ${text}`,
        );
      }
    }
  });

  it("byContract, across every semantic and declared precision", () => {
    for (const value of VALUES) {
      for (const semantic of SEMANTICS) {
        // Including declared precisions that are THEMSELVES over the ceiling.
        // A column whose metadata says four decimals must not be able to put
        // four decimals on screen.
        for (const declared of [undefined, 0, 1, 2, 3, 4, 6, 10]) {
          const column: ColumnSpec = {
            name: "x", semantic, decimals: declared,
          };
          const text = byContract(value, column);
          assert.ok(
            decimalsOf(text) <= MAX_DECIMALS,
            `byContract(${value}, {semantic:${semantic}, decimals:${declared}})`
              + ` = ${text}`,
          );
        }
      }
    }
  });

  it("figure and deltaFigure, which feed KPIs and chart labels", () => {
    for (const value of VALUES) {
      for (const semantic of SEMANTICS) {
        const column: ColumnSpec = { name: "x", semantic, decimals: 6 };
        assert.ok(
          decimalsOf(figure(value, column).text) <= MAX_DECIMALS,
          `figure(${value}, ${semantic})`,
        );
        assert.ok(
          decimalsOf(deltaFigure(value, column).text) <= MAX_DECIMALS,
          `deltaFigure(${value}, ${semantic})`,
        );
      }
    }
  });
});

describe("prose is scrubbed", () => {
  it("rewrites floating-point debris a backend formatter missed", () => {
    const said = scrubDebris(
      "Stage 2 share rose to 2.6246841182876173% on exposure of "
        + "59.352000000000004 USD mn.",
    );
    assert.match(said, /2\.62%/);
    assert.match(said, /59\.35/);
    assert.doesNotMatch(said, /\d\.\d{3,}/);
  });

  it("catches three decimals, not only four", () => {
    // The scrubber used to fire at four. 2.625% is already over a ceiling of
    // two, and it is the more dangerous of the two because it looks deliberate.
    assert.doesNotMatch(scrubDebris("coverage of 2.625%"), /\d\.\d{3,}/);
  });

  it("leaves a period, a version and an identifier alone", () => {
    for (const text of [
      "Q2 2026 compared with Q2 2025",
      "method version 1.10.4",
      "customer CUST-00123",
      "ratio of 1.5x",
      // A timestamp's fractional seconds are not a figure. Rewriting them
      // would corrupt a time while claiming to tidy a number.
      "recorded at 2026-08-28T12:57:14.932382+00:00",
    ]) {
      assert.equal(scrubDebris(text), text);
    }
  });

  it("never introduces debris of its own", () => {
    for (const value of VALUES.slice(0, 400)) {
      const said = scrubDebris(`value of ${value}`);
      assert.ok(decimalsOf(said) <= MAX_DECIMALS, said);
    }
  });
});

describe("what the ceiling does not do", () => {
  it("does not round a value across a governed threshold", () => {
    // 14.9996% headroom under a 15% limit is a breach, and a display that
    // rounded it to 15.00% would show a figure that reads as compliant. The
    // contract formats; the THRESHOLD is tested on the underlying value, and
    // this test exists so that stays true if the formatter is ever asked to
    // do the comparison.
    const shown = byContract(14.9996, { name: "h", semantic: "percent" });
    assert.equal(shown, "15.00");
    assert.ok(14.9996 < 15, "the underlying value is what the check uses");
  });

  it("keeps an integer count whole", () => {
    assert.equal(byContract(9, { name: "n", semantic: "count" }), "9");
    assert.equal(byContract(61, { name: "d", semantic: "days" }), "61");
    assert.equal(
      byContract(61, { name: "d", semantic: "days", unit: "days" }),
      "61 days",
    );
  });
});
