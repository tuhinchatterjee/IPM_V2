import assert from "node:assert/strict";
import { test } from "node:test";

import { NAV_ITEMS } from "../navigation.ts";

/**
 * Early Warning is ONE product with ONE way in.
 *
 * The consolidation that removed the second and third Early Warning screens
 * is only worth anything if the navigation cannot quietly grow them back,
 * and a nav list is exactly the kind of file where a second entry is added
 * by someone solving a different problem.
 */

test("there is exactly one way into Early Warning", () => {
  const entries = NAV_ITEMS.filter((item) =>
    item.href === "/early-warning" || item.href.startsWith("/early-warning/"),
  );
  assert.equal(
    entries.length,
    1,
    `expected one Early Warning nav item, found ${entries
      .map((e) => e.href)
      .join(", ")}`,
  );
  assert.equal(entries[0].label, "Early Warning");
});

test("the navigation states the model the engine actually implements", () => {
  // It said 35 classifiers, which is the count of an earlier and wrong
  // reading of the workbook. The engine has 23. A reader who checks the
  // navigation against the methodology screen and finds them disagreeing
  // loses confidence in both, and is right to.
  //
  // The engine-side assertion lives in
  // tests/early_warning/test_money_convention.py; this is the copy a reader
  // sees before they ever open the screen.
  const entry = NAV_ITEMS.find((item) => item.href === "/early-warning");
  assert.ok(entry, "the Early Warning nav item is missing");
  const said = entry.description;
  assert.ok(said.includes("23 classifiers"), said);
  assert.ok(!said.includes("35 classifiers"), said);
  assert.ok(said.includes("123 governed signals"), said);
  assert.ok(said.includes("67 dynamic triggers"), said);
});
