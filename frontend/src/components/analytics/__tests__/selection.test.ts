import assert from "node:assert/strict";
import { test } from "node:test";

import * as s from "../selection.ts";

/**
 * The selection reducer.
 *
 * These are the combinations that produce a wrong screen rather than an error:
 * a Reset that leaves one thing on, a legend that can hide every series, an
 * isolation that survives being contradicted.
 */

const SERIES = [
  { key: "ead", label: "EAD", slot: 0 },
  { key: "ecl", label: "ECL", slot: 1 },
  { key: "pd", label: "PD", slot: 2 },
];

function after(actions: s.Action[]): s.Selection {
  return actions.reduce(s.reduce, s.EMPTY);
}

test("hiding a series removes it from what is drawn", () => {
  const state = after([{ type: "toggle-series", key: "ecl" }]);
  assert.deepEqual(
    s.visibleSeries(SERIES, state).map((x) => x.key),
    ["ead", "pd"],
  );
});

test("hiding the same series twice brings it back", () => {
  const state = after([
    { type: "toggle-series", key: "ecl" },
    { type: "toggle-series", key: "ecl" },
  ]);
  assert.equal(s.visibleSeries(SERIES, state).length, 3);
  assert.equal(s.isTouched(state), false);
});

test("hiding every series still draws the chart", () => {
  // Reachable by clicking through a legend. An empty chart is not an answer.
  const state = after([
    { type: "toggle-series", key: "ead" },
    { type: "toggle-series", key: "ecl" },
    { type: "toggle-series", key: "pd" },
  ]);
  assert.equal(s.visibleSeries(SERIES, state).length, 3);
});

test("isolating a series shows it alone", () => {
  const state = after([{ type: "isolate-series", key: "ecl" }]);
  assert.deepEqual(
    s.visibleSeries(SERIES, state).map((x) => x.key),
    ["ecl"],
  );
});

test("isolating the same series again shows them all", () => {
  const state = after([
    { type: "isolate-series", key: "ecl" },
    { type: "isolate-series", key: "ecl" },
  ]);
  assert.equal(s.visibleSeries(SERIES, state).length, 3);
});

test("isolation ends when the reader asks for a second series", () => {
  const state = after([
    { type: "isolate-series", key: "ecl" },
    { type: "toggle-series", key: "ead" },
  ]);
  assert.equal(state.isolated, null);
});

test("an isolated series that is no longer in the result does not blank the chart", () => {
  // The analysis was re-run with different measures while a series was isolated.
  const state = after([{ type: "isolate-series", key: "leverage" }]);
  assert.equal(s.visibleSeries(SERIES, state).length, 3);
});

test("a brushed range narrows what is drawn, not what was calculated", () => {
  const rows = [1, 2, 3, 4, 5, 6, 7, 8];
  const state = after([{ type: "set-range", range: { from: 2, to: 4 } }]);
  assert.deepEqual(s.visibleRows(rows, state), [3, 4, 5]);
  // The result itself is untouched.
  assert.equal(rows.length, 8);
});

test("a range beyond the rows is clamped rather than producing nothing", () => {
  const rows = [1, 2, 3];
  const state = after([{ type: "set-range", range: { from: 1, to: 99 } }]);
  assert.deepEqual(s.visibleRows(rows, state), [2, 3]);
});

test("picking a category emphasises it without dropping the others", () => {
  const rows = ["a", "b", "c"];
  const state = after([{ type: "toggle-category", value: "b" }]);
  assert.equal(s.visibleRows(rows, state).length, 3);
  assert.equal(s.emphasis(state, "b"), 1);
  assert.ok(s.emphasis(state, "a") < 1);
});

test("with nothing picked every row is drawn at full strength", () => {
  assert.equal(s.emphasis(s.EMPTY, "a"), 1);
});

test("reset undoes everything, not most of it", () => {
  const state = after([
    { type: "toggle-series", key: "ecl" },
    { type: "toggle-category", value: "Contracting" },
    { type: "set-range", range: { from: 1, to: 4 } },
    { type: "focus", index: 3 },
    { type: "reset" },
  ]);
  assert.deepEqual(state, s.EMPTY);
  assert.equal(s.isTouched(state), false);
});

test("arrow keys walk the categories and wrap", () => {
  let state = s.EMPTY;
  state = s.reduce(state, { type: "move-focus", delta: 1, count: 3 });
  assert.equal(state.focused, 0, "the first press starts at the beginning");
  state = s.reduce(state, { type: "move-focus", delta: 1, count: 3 });
  state = s.reduce(state, { type: "move-focus", delta: 1, count: 3 });
  assert.equal(state.focused, 2);
  state = s.reduce(state, { type: "move-focus", delta: 1, count: 3 });
  assert.equal(state.focused, 0, "past the end wraps to the start");
  state = s.reduce(state, { type: "move-focus", delta: -1, count: 3 });
  assert.equal(state.focused, 2);
});

test("moving focus in an empty result focuses nothing", () => {
  const state = s.reduce(s.EMPTY, { type: "move-focus", delta: 1, count: 0 });
  assert.equal(state.focused, -1);
});

test("the reducer never mutates the state it was given", () => {
  const before = { ...s.EMPTY, hidden: ["ecl"] };
  const copy = JSON.parse(JSON.stringify(before));
  s.reduce(before, { type: "toggle-series", key: "ead" });
  assert.deepEqual(before, copy);
});

test("the description says what the reader chose, in their words", () => {
  const state = after([
    { type: "toggle-series", key: "ecl" },
    { type: "toggle-category", value: "Contracting" },
  ]);
  const said = s.describe(state, { ecl: "ECL" });
  assert.match(said, /ECL/);
  assert.match(said, /Contracting/);
});

test("an untouched selection describes itself as nothing", () => {
  assert.equal(s.describe(s.EMPTY), "");
});
