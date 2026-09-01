/**
 * §211 and §212 — how the assurance surfaces are allowed to present a record.
 *
 * The four impossibilities that live in the front end
 * ----------------------------------------------------
 * §212's rules are enforced in the backend for the payloads it builds, but
 * four of them can be broken by presentation alone, without the backend ever
 * knowing: rendering an unmeasured dimension as a pass, calling the figure
 * accuracy, showing a zero where there is no score, and letting a stale
 * record read as current. Each is one line away, and each is tested here.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { AssuranceReview, DimensionCell, ReviewRow } from "@/lib/api";
import * as present from "../present.ts";

function cell(overrides: Partial<DimensionCell> = {}): DimensionCell {
  return {
    dimension: "COMPUTATION_AND_EVIDENCE",
    short: "CE",
    state: "PASSED",
    score: 90,
    coverage_pct: 95,
    ...overrides,
  };
}

function row(overrides: Partial<ReviewRow> = {}): ReviewRow {
  return {
    assurance_record_id: "ar-1",
    investigation_id: "inv-1",
    title: "What moved in Contracting?",
    user_id: 7,
    project_id: "",
    at: "2026-08-01T09:00:00+00:00",
    scope: "corporate",
    language: "en",
    turn_index: 0,
    officer_level: 2,
    model_route: "ROUTINE",
    case_family: "SINGLE_DOMAIN_AGGREGATION",
    overall_status: "VALIDATED",
    status_now: "VALIDATED",
    operational_assurance: 88,
    operational_assurance_label: "Operational assurance",
    coverage_pct: 91,
    reference_match: {
      available: false,
      value_pct: null,
      source: "",
      why: "This is a live Investigation with no independent reference answer.",
    },
    dimensions: [cell()],
    critical_failures: 0,
    warnings: 0,
    good_feedback: 0,
    bad_feedback: 0,
    teaching_release_id: "tr-1",
    release_current: true,
    stale_reasons: [],
    superseded_by: "",
    rerun_of: "",
    open_review: false,
    ...overrides,
  };
}

describe("dimension cells", () => {
  it("never reads an unmeasured dimension as a pass", () => {
    assert.equal(present.cellWord(cell({ state: "UNMEASURED" })), "not measured");
    assert.equal(present.cellWord(cell({ state: "PASSED" })), "passed");
  });

  it("distinguishes a warning from a failure", () => {
    assert.equal(present.cellWord(cell({ state: "WARNING" })), "warning");
    assert.equal(present.cellWord(cell({ state: "FAILED" })), "failed");
  });
});

describe("the score", () => {
  it("shows the status in words rather than a zero when nothing was scored", () => {
    const text = present.scoreText(null, "Operational assurance", "UNVERIFIED");

    assert.equal(text, "unverified");
    assert.ok(!text.includes("0"));
  });

  it("uses the label the payload supplied, never the word accuracy", () => {
    const text = present.scoreText(88, "Operational assurance", "VALIDATED");

    assert.equal(text, "88 / 100 operational assurance");
    assert.ok(!text.includes("accuracy"));
  });

  it("leaves no dangling space where the surrounding label names it", () => {
    assert.equal(present.scoreText(88, "", "VALIDATED"), "88 / 100");
  });
});

describe("reference match", () => {
  it("explains the absence rather than rendering a blank", () => {
    const review = {
      header: {
        reference_match: {
          available: false,
          value_pct: null,
          source: "",
          why: "no independent reference answer exists",
        },
      },
    } as unknown as AssuranceReview;

    assert.equal(
      present.referenceText(review),
      "no independent reference answer exists",
    );
  });

  it("reports the figure where an approved reference exists", () => {
    const review = {
      header: {
        reference_match: {
          available: true,
          value_pct: 96,
          source: "benchmark-2026Q1",
          why: "",
        },
      },
    } as unknown as AssuranceReview;

    assert.equal(present.referenceText(review), "96% against benchmark-2026Q1");
  });
});

describe("staleness", () => {
  it("never presents a stale record as current validation", () => {
    const stale = row({
      overall_status: "HIGH_ASSURANCE",
      stale_reasons: ["a newer Teaching Release is in force"],
    });

    assert.equal(present.displayStatus(stale), "STALE");
  });

  it("leaves a current record alone", () => {
    assert.equal(present.displayStatus(row()), "VALIDATED");
  });
});

describe("what needs attention", () => {
  it("flags a critical failure", () => {
    assert.equal(present.needsAttention(row({ critical_failures: 1 })), true);
  });

  it("flags a record where somebody pressed Bad", () => {
    assert.equal(present.needsAttention(row({ bad_feedback: 2 })), true);
  });

  it("leaves a clean record alone", () => {
    assert.equal(present.needsAttention(row()), false);
  });
});

describe("review order", () => {
  it("puts what needs attention first, not what scored lowest", () => {
    const ordered = present.reviewOrder([
      row({ assurance_record_id: "clean" }),
      row({ assurance_record_id: "critical", critical_failures: 1 }),
      row({ assurance_record_id: "review", overall_status: "NEEDS_REVIEW" }),
    ]);

    assert.deepEqual(
      ordered.map((r) => r.assurance_record_id),
      ["critical", "review", "clean"],
    );
  });

  it("does not sort unscored records to an end by their missing score", () => {
    const ordered = present.reviewOrder([
      row({ assurance_record_id: "old", at: "2026-01-01T00:00:00+00:00" }),
      row({
        assurance_record_id: "unscored",
        operational_assurance: null,
        overall_status: "UNVERIFIED",
        at: "2026-08-01T00:00:00+00:00",
      }),
    ]);

    // Newest first among rows that need no attention. The null score plays
    // no part, because sorting by it would bury or promote every record the
    // gates refused to vouch for.
    assert.equal(ordered[0].assurance_record_id, "unscored");
  });

  it("does not mutate the array it was given", () => {
    const rows = [row({ assurance_record_id: "a" }),
                  row({ assurance_record_id: "b", critical_failures: 1 })];
    present.reviewOrder(rows);

    assert.equal(rows[0].assurance_record_id, "a");
  });
});
