import assert from "node:assert/strict";
import { test } from "node:test";

import * as p from "../playback.ts";

/**
 * The period playback machine.
 *
 * What matters here is what a sequence of presses MEANS at the edges: Play at
 * the end, Next on the last period, comparing a period with itself.
 */

const PERIODS = ["Q1 2026", "Q2 2026", "Q3 2026", "Q4 2026"];

function after(actions: p.Action[], periods = PERIODS): p.Playback {
  return actions.reduce(p.reduce, p.start(periods));
}

test("nothing plays until somebody presses Play", () => {
  assert.equal(p.start(PERIODS).playing, false);
  assert.equal(p.start(PERIODS).index, 0);
});

test("play then tick advances one period at a time", () => {
  const state = after([{ type: "play" }, { type: "tick" }, { type: "tick" }]);
  assert.equal(p.current(state), "Q3 2026");
  assert.equal(state.playing, true);
});

test("playback stops at the last period rather than looping", () => {
  const state = after([
    { type: "play" },
    { type: "tick" },
    { type: "tick" },
    { type: "tick" },
    { type: "tick" },
  ]);
  assert.equal(p.current(state), "Q4 2026");
  assert.equal(state.playing, false);
});

test("pressing Play at the end restarts", () => {
  const state = after([
    { type: "seek", index: 3 },
    { type: "play" },
  ]);
  assert.equal(state.index, 0);
  assert.equal(state.playing, true);
});

test("a tick while paused changes nothing", () => {
  const state = after([{ type: "tick" }]);
  assert.equal(state.index, 0);
});

test("scrubbing takes over from playback", () => {
  const state = after([{ type: "play" }, { type: "seek", index: 2 }]);
  assert.equal(state.playing, false);
  assert.equal(p.current(state), "Q3 2026");
});

test("Next on the last period does not run off the end", () => {
  const state = after([{ type: "seek", index: 3 }, { type: "step", delta: 1 }]);
  assert.equal(state.index, 3);
});

test("Previous on the first period does not run off the start", () => {
  const state = after([{ type: "step", delta: -1 }]);
  assert.equal(state.index, 0);
});

test("speed changes how long a period is held", () => {
  const fast = after([{ type: "speed", speed: 4 }]);
  const slow = after([{ type: "speed", speed: 0.5 }]);
  assert.ok(p.stepMs(fast) < p.stepMs(slow));
});

test("comparing a period with itself turns comparison off", () => {
  const state = after([{ type: "compare", index: 0 }]);
  assert.equal(state.compare, null);
});

test("comparing shows both periods together, in period order", () => {
  const rows = [
    { period: "Q1 2026", ead: 1 },
    { period: "Q2 2026", ead: 2 },
    { period: "Q3 2026", ead: 3 },
  ];
  const state = after([{ type: "seek", index: 2 }, { type: "compare", index: 0 }]);
  assert.deepEqual(
    p.rowsFor(rows, "period", state).map((r) => r.period),
    ["Q1 2026", "Q3 2026"],
  );
});

test("without a comparison only the current period is drawn", () => {
  const rows = [
    { period: "Q1 2026", ead: 1 },
    { period: "Q2 2026", ead: 2 },
  ];
  const state = after([{ type: "seek", index: 1 }]);
  assert.deepEqual(
    p.rowsFor(rows, "period", state).map((r) => r.period),
    ["Q2 2026"],
  );
});

test("reset returns to the first period, paused, at normal speed", () => {
  const state = after([
    { type: "seek", index: 3 },
    { type: "speed", speed: 4 },
    { type: "compare", index: 0 },
    { type: "reset" },
  ]);
  assert.deepEqual(state, p.start(PERIODS));
});

test("one period is not eligible for playback", () => {
  assert.equal(p.isEligible(["Q2 2026"]), false);
  assert.equal(p.isEligible([]), false);
  assert.equal(p.isEligible(["Q1 2026", "Q2 2026"]), true);
});

test("play does nothing where there is nothing to play", () => {
  const state = after([{ type: "play" }], ["Q2 2026"]);
  assert.equal(state.playing, false);
});

test("periods keep the result's own order, never an alphabetical one", () => {
  // "Q1 2026" sorts before "Q4 2025", which would run a trend backwards.
  const rows = [
    { period: "Q4 2025" },
    { period: "Q1 2026" },
    { period: "Q4 2025" },
  ];
  assert.deepEqual(p.periodsIn(rows, "period"), ["Q4 2025", "Q1 2026"]);
});

test("the caption says where the cursor is and what it is compared with", () => {
  const state = after([{ type: "seek", index: 1 }, { type: "compare", index: 0 }]);
  assert.equal(p.caption(state), "Q2 2026 · 2 of 4 · compared with Q1 2026");
});
