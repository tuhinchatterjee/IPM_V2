import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isRegisteredMethod,
  methodHref,
  runHref,
  stepHref,
} from "../analysis-links.ts";

/**
 * The failure these exist for.
 *
 * Clicking the analysis under a composed answer navigated to Analysis Library
 * / dynamic_analysis and reported "'dynamic_analysis' is not a registered
 * CreditProbe analysis". It is not, and never was — the marker means the plan
 * was composed for one question, so there is nothing in the library to open.
 */

test("a composed analysis has no method page", () => {
  assert.equal(isRegisteredMethod("dynamic_analysis", "dynamic"), false);
  assert.equal(methodHref("dynamic_analysis", "dynamic"), null);
});

test("a composed analysis links to the run that produced it instead", () => {
  assert.equal(stepHref("dynamic_analysis", "dynamic", 412), "/trace/412");
});

test("a registered method still opens its definition", () => {
  assert.equal(isRegisteredMethod("stage_migration", "certified"), true);
  assert.equal(
    methodHref("stage_migration", "certified"),
    "/engine-builder/stage_migration",
  );
  assert.equal(
    stepHref("stage_migration", "certified", 412),
    "/engine-builder/stage_migration",
  );
});

test("a catalogue lookup is neither, and offers no dead link", () => {
  assert.equal(isRegisteredMethod("capability_data_discovery", "metadata"), false);
  assert.equal(stepHref("capability_data_discovery", "metadata", null), null);
});

test("a registered-looking id on an uncertified run is still not a method", () => {
  // Both tests matter: the id catches a composed plan whatever it claims, and
  // the certification catches a plausible id on something never registered.
  assert.equal(isRegisteredMethod("stage_migration", "dynamic"), false);
});

test("a run without an id has nowhere to go, and says so", () => {
  assert.equal(runHref(null), null);
  assert.equal(runHref(0), null);
  assert.equal(stepHref("dynamic_analysis", "dynamic", null), null);
});
