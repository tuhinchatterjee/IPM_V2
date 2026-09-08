import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { EMPTY, isAStep, merge, read, write } from "../selection.ts";

describe("what the Early Warning screen is looking at", () => {
  it("reads an empty query string as no selection", () => {
    assert.deepEqual(read(""), EMPTY);
  });

  it("reads each selection back out of the URL", () => {
    const found = read("?band=HIGH&segment=Large+Corporate&customer=CORP-1&level=internal_rating");
    assert.equal(found.band, "HIGH");
    assert.equal(found.segment, "Large Corporate");
    assert.equal(found.customer, "CORP-1");
    assert.equal(found.level, "internal_rating");
  });

  it("writes no key for a selection that is not made", () => {
    // `?band=&segment=&customer=` is three keys saying nothing, and it makes
    // a shared link look like a filtered view when it is not.
    assert.equal(write(EMPTY), "");
    assert.equal(write(merge(EMPTY, { band: "HIGH" })), "band=HIGH");
  });

  it("survives a round trip", () => {
    const selection = merge(EMPTY, { band: "VERY_HIGH", customer: "CORP-9" });
    assert.deepEqual(read(`?${write(selection)}`), selection);
  });
});

describe("which changes belong in the browser's history", () => {
  it("counts opening a borrower as a step", () => {
    // The readiness run found Back leaving the Early Warning page on the
    // first press, because three selections had been written with
    // replaceState and left no trace to walk.
    const before = merge(EMPTY, { band: "HIGH" });
    assert.equal(isAStep(before, merge(before, { customer: "CORP-1" })), true);
  });

  it("counts closing one as a step too", () => {
    // A reader who closes a borrower and wants it back presses Back.
    const before = merge(EMPTY, { customer: "CORP-1" });
    assert.equal(isAStep(before, merge(before, { customer: null })), true);
  });

  it("does not count re-selecting what is already selected", () => {
    // Otherwise Back has to be pressed twice to undo one click.
    const before = merge(EMPTY, { band: "HIGH" });
    assert.equal(isAStep(before, merge(before, { band: "HIGH" })), false);
    assert.equal(isAStep(before, before), false);
  });

  it("does not care which order the keys were set in", () => {
    const a = merge(merge(EMPTY, { band: "HIGH" }), { customer: "CORP-1" });
    const b = merge(merge(EMPTY, { customer: "CORP-1" }), { band: "HIGH" });
    assert.equal(isAStep(a, b), false);
  });
});
