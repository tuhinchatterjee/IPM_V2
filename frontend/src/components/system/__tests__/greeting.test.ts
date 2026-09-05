import assert from "node:assert/strict";
import { test } from "node:test";

/**
 * The greeting's two halves, tested where they are decidable.
 *
 * The time-of-day half is a pure function of the clock and belongs here. The
 * name half is a stored preference and belongs in the API suite, which proves
 * it persists and — the part that matters — that it changes nothing about the
 * account it belongs to.
 */

/** The same rule the control previews with and the Cockpit prints. */
function timeOfDay(hour: number): string {
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

test("the morning runs to noon", () => {
  assert.equal(timeOfDay(0), "Good morning");
  assert.equal(timeOfDay(8), "Good morning");
  assert.equal(timeOfDay(11), "Good morning");
});

test("noon starts the afternoon", () => {
  // Twelve is afternoon, not morning: "Good morning" at 12:01 is the kind of
  // small wrongness a reader notices every single day.
  assert.equal(timeOfDay(12), "Good afternoon");
  assert.equal(timeOfDay(17), "Good afternoon");
});

test("six starts the evening", () => {
  assert.equal(timeOfDay(18), "Good evening");
  assert.equal(timeOfDay(23), "Good evening");
});

test("every hour of the day has a greeting", () => {
  const said = new Set<string>();
  for (let hour = 0; hour < 24; hour += 1) {
    const greeting = timeOfDay(hour);
    assert.ok(greeting.startsWith("Good "), `hour ${hour} has no greeting`);
    said.add(greeting);
  }
  assert.deepEqual(
    [...said].sort(),
    ["Good afternoon", "Good evening", "Good morning"],
  );
});
