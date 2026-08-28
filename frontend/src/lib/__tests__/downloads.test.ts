import assert from "node:assert/strict";
import { test } from "node:test";

import { captionFor, filenameFrom } from "../downloads.ts";

/**
 * The two download decisions that are not rendering.
 *
 * Both have the same failure mode: they are invisible until the file reaches
 * somebody's laptop, and by then the wrong name is on it.
 */

const FALLBACK = "CreditProbe_analysis_7_results.xlsx";

test("the server's own filename is used", () => {
  assert.equal(
    filenameFrom(
      'attachment; filename="CreditProbe_ead_by_rating_q2_2026_01bd86_results.xlsx"',
      FALLBACK,
    ),
    "CreditProbe_ead_by_rating_q2_2026_01bd86_results.xlsx",
  );
});

test("the quoted name wins over the percent-encoded one", () => {
  // Both forms are sent for old and new clients. The quoted one is already
  // decoded; preferring the other would show %20 in a downloads folder.
  assert.equal(
    filenameFrom(
      "attachment; filename=\"Q2 2026 pack.xlsx\"; filename*=UTF-8''Q2%202026%20pack.xlsx",
      FALLBACK,
    ),
    "Q2 2026 pack.xlsx",
  );
});

test("the extended form is decoded when it is the only one", () => {
  assert.equal(
    filenameFrom("attachment; filename*=UTF-8''Q2%202026%20pack.xlsx", FALLBACK),
    "Q2 2026 pack.xlsx",
  );
});

test("a malformed encoding falls back to the raw value rather than throwing", () => {
  assert.equal(
    filenameFrom("attachment; filename*=UTF-8''broken%zz.xlsx", FALLBACK),
    "broken%zz.xlsx",
  );
});

test("a missing header falls back to a name that still identifies the run", () => {
  assert.equal(filenameFrom(null, FALLBACK), FALLBACK);
  assert.equal(filenameFrom("attachment", FALLBACK), FALLBACK);
});

test("the button says what it is doing, not only which icon it shows", () => {
  assert.equal(captionFor("idle", "DOWNLOAD RESULTS"), "DOWNLOAD RESULTS");
  assert.equal(captionFor("working", "DOWNLOAD RESULTS"), "Preparing workbook…");
  assert.equal(captionFor("done", "DOWNLOAD RESULTS"), "Workbook ready");
});

test("a failed download returns to its label rather than lying about success", () => {
  assert.equal(
    captionFor("failed", "DOWNLOAD FULL CALCULATION"),
    "DOWNLOAD FULL CALCULATION",
  );
});
