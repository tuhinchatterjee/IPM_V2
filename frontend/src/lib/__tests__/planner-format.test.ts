import assert from "node:assert/strict";
import { test } from "node:test";

import {
  claimLabel,
  dueLabel,
  healthTone,
  progressWidth,
  when,
} from "../planner-format.ts";

/**
 * The presentation rules of the Project Planner.
 *
 * Each of these is a decision somebody could reasonably make the other way,
 * which is exactly why it needs pinning: the next person to touch the due
 * column will otherwise "tidy up" the lateness rule and quietly make every
 * overdue task look like every other task.
 */

test("lateness beats every other reading of a due date", () => {
  // A task both overdue AND with a days_until must read as overdue: the
  // backend can send both when a date has just passed, and "In 0 days" for
  // something six days late is worse than useless.
  assert.equal(dueLabel("2026-08-28", 6, -6).text, "6 days overdue");
  assert.equal(dueLabel("2026-08-28", 6, -6).tone, "negative");
});

test("one day is singular", () => {
  assert.equal(dueLabel("2026-09-02", 1).text, "1 day overdue");
  assert.equal(dueLabel("2026-09-04", 0, 1).text, "In 1 day");
});

test("today is named, not counted", () => {
  const today = dueLabel("2026-09-03", 0, 0);
  assert.equal(today.text, "Due today");
  assert.equal(today.tone, "warning");
});

test("a date far out is just the date", () => {
  assert.equal(dueLabel("2026-12-18", 0, 90).text, "2026-12-18");
});

test("no date says so rather than showing an empty cell", () => {
  // An empty cell reads as a rendering bug. "No date" is a fact about the
  // plan, and it is one somebody should act on.
  assert.equal(dueLabel(null).text, "No date");
  assert.equal(dueLabel(null).tone, "muted");
});

test("health tone never invents a colour for an unknown", () => {
  assert.equal(healthTone("RED"), "negative");
  assert.equal(healthTone("AMBER"), "warning");
  assert.equal(healthTone("GREEN"), "positive");
  assert.equal(healthTone("UNKNOWN"), "default");
});

test("relative time gives up after a fortnight", () => {
  const now = Date.parse("2026-09-03T12:00:00Z");
  assert.equal(when("2026-09-03T09:00:00Z", now), "today");
  assert.equal(when("2026-09-02T09:00:00Z", now), "yesterday");
  assert.equal(when("2026-08-31T09:00:00Z", now), "3 days ago");
  assert.equal(when("2026-08-01T09:00:00Z", now), "2026-08-01");
});

test("a missing or unreadable timestamp is a dash, not Invalid Date", () => {
  assert.equal(when(null), "—");
  assert.equal(when(""), "—");
  assert.equal(when("not a date"), "—");
});

test("a future timestamp falls back to the date", () => {
  // Clock skew between a server and a browser is real, and "-1 days ago" is
  // the kind of thing that ends up in a screenshot.
  const now = Date.parse("2026-09-03T12:00:00Z");
  assert.equal(when("2026-09-05T09:00:00Z", now), "2026-09-05");
});

test("claim labels are the words a person would use", () => {
  assert.equal(claimLabel("FACT"), "Fact");
  assert.equal(claimLabel("INFERENCE"), "Reading");
  assert.equal(claimLabel("RECOMMENDATION"), "Suggested");
  assert.equal(claimLabel("NOT RECORDED"), "Not recorded");
});

test("an unknown claim kind is shown, not swallowed", () => {
  // If the backend adds a kind, a blank badge hides it. Showing the raw value
  // is ugly and visible, which is the right way round.
  assert.equal(claimLabel("SPECULATION"), "SPECULATION");
});

test("a progress bar cannot overflow its track", () => {
  assert.equal(progressWidth(-5), 0);
  assert.equal(progressWidth(140), 100);
  assert.equal(progressWidth(33.4), 33);
  assert.equal(progressWidth(Number.NaN), 0);
});
