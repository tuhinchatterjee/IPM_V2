import assert from "node:assert/strict";
import { test } from "node:test";

import type { PlaybookFigure } from "../api.ts";
import {
  availabilityLabel,
  availabilityTone,
  daysUntil,
  figureReading,
  formatDay,
  isLocked,
  isOpen,
  movementReading,
  nextStatuses,
  packStatusTone,
  severityTone,
  stateTone,
} from "../playbook-format.ts";

/**
 * The presentation rules of the Playbook.
 *
 * Every one of these is a decision somebody could reasonably make the other
 * way, which is exactly why it is pinned here. The first group is the most
 * important thing in the area: an absent figure must never reach a committee
 * looking like a number.
 */

function figure(overrides: Partial<PlaybookFigure> = {}): PlaybookFigure {
  return {
    metric_id: "retail.default_rate",
    metric_name: "Retail default rate",
    metric_version: "1",
    formula_hash: "abc123",
    period: "2025-01",
    comparison_period: "2024-12",
    filters: {},
    value: 6.88,
    comparison_value: 6.24,
    display_value: "6.88%",
    comparison_display: "6.24%",
    unit: "percent",
    decimals: 2,
    higher_is_better: false,
    numerator: 688,
    denominator: 10000,
    rows_considered: 10000,
    series: [],
    availability: "OK",
    unavailable_reason: "",
    dataset: "retail.loans",
    dataset_version: "v3",
    source_fields: [],
    run_id: "run-1",
    warnings: [],
    verification_state: "",
    governed: true,
    available: true,
    ...overrides,
  };
}

// ================================================== the rule the area rests on

test("an immature cohort is never rendered as a number", () => {
  const reading = figureReading(
    figure({
      availability: "NOT_MATURED",
      value: null,
      display_value: "—",
      unavailable_reason:
        "The 12-month window for this cohort has not closed yet.",
    }),
  );
  assert.equal(reading.kind, "unavailable");
  if (reading.kind !== "unavailable") return;
  assert.equal(reading.label, "Not yet matured");
  // The point of the whole exercise: not a zero, and not a bare dash.
  assert.notEqual(reading.label, "0.0%");
  assert.notEqual(reading.label, "—");
  assert.match(reading.reason, /has not closed/);
});

test("the five ways of having no number stay five different facts", () => {
  const said = [
    "NO_DATA",
    "NOT_MATURED",
    "CALCULATION_FAILED",
    "NOT_AUTHORISED",
    "PERIOD_MISSING",
  ].map(availabilityLabel);
  assert.equal(new Set(said).size, said.length, said.join(" / "));
  // And none of them is silence.
  for (const label of said) assert.ok(label.length > 0);
});

test("a failed calculation reads as a fault; an immature one does not", () => {
  // Different afternoons. A calculation that broke is somebody's problem
  // now; a cohort that has not matured is nobody's problem at all.
  assert.equal(availabilityTone("CALCULATION_FAILED"), "negative");
  assert.equal(availabilityTone("NOT_MATURED"), "info");
  assert.equal(availabilityTone("NO_DATA"), "info");
  assert.equal(availabilityTone("NOT_AUTHORISED"), "warning");
});

test("a figure with a value renders the string the backend rounded", () => {
  const reading = figureReading(figure({ display_value: "6.88%" }));
  assert.deepEqual(reading, { kind: "value", text: "6.88%" });
});

test("the screen never re-rounds the value itself", () => {
  // 6.876 rounds to 6.88 on the backend. If the screen formatted `value` it
  // would be free to say 6.9%, and the PDF sent the same morning would say
  // 6.88% — which is the discrepancy the display string exists to prevent.
  const reading = figureReading(
    figure({ value: 6.876123, display_value: "6.88%" }),
  );
  assert.equal(reading.kind === "value" && reading.text, "6.88%");
});

test("a block laid out but never generated says so", () => {
  const reading = figureReading(null);
  assert.equal(reading.kind, "uncalculated");
  assert.equal(reading.kind === "uncalculated" && reading.text,
               "Not yet calculated");
});

// =========================================================== movement reading

test("a rising default rate is bad and a rising coverage ratio is good", () => {
  const worse = movementReading(
    figure({ value: 6.88, comparison_value: 6.24, higher_is_better: false }),
  );
  assert.equal(worse.kind, "moved");
  assert.equal(worse.kind === "moved" && worse.up, true);
  assert.equal(worse.kind === "moved" && worse.good, false);

  const better = movementReading(
    figure({
      metric_id: "ifrs9.coverage_ratio",
      value: 4.1,
      comparison_value: 3.8,
      higher_is_better: true,
    }),
  );
  assert.equal(better.kind === "moved" && better.up, true);
  assert.equal(better.kind === "moved" && better.good, true);
});

test("a falling default rate is good", () => {
  const reading = movementReading(
    figure({ value: 6.0, comparison_value: 6.5, higher_is_better: false }),
  );
  assert.equal(reading.kind === "moved" && reading.up, false);
  assert.equal(reading.kind === "moved" && reading.good, true);
});

test("no comparison means no movement, not a movement of zero", () => {
  const reading = movementReading(figure({ comparison_value: null }));
  assert.equal(reading.kind, "none");
  assert.match(reading.text, /No comparable prior figure/);
});

test("an unavailable figure has no movement at all", () => {
  const reading = movementReading(
    figure({ availability: "NO_DATA", value: null }),
  );
  assert.equal(reading.kind, "none");
  assert.equal(reading.text, "");
});

test("floating-point noise is not a movement", () => {
  const reading = movementReading(
    figure({ value: 6.88, comparison_value: 6.88 + 1e-15 }),
  );
  assert.equal(reading.kind, "flat");
  assert.match(reading.text, /Unchanged/);
});

test("the movement quotes the prior figure as the backend formatted it", () => {
  const reading = movementReading(
    figure({ comparison_display: "6.24%", comparison_period: "2024-12" }),
  );
  assert.equal(reading.kind, "moved");
  assert.match(reading.kind === "moved" ? reading.text : "", /6\.24%/);
  assert.match(reading.kind === "moved" ? reading.text : "", /2024-12/);
});

test("a metric with no agreed direction is not guessed at", () => {
  // A count has no "better". Colouring it green because it went up would be
  // the screen inventing a view the metric definition does not hold.
  const reading = movementReading(
    figure({ higher_is_better: null, value: 12, comparison_value: 10 }),
  );
  assert.equal(reading.kind === "moved" && reading.good, false);
});

// =============================================================== the lifecycle

test("an approved pack is locked, and a draft is not", () => {
  assert.equal(isLocked("APPROVED"), true);
  assert.equal(isLocked("PUBLISHED"), true);
  assert.equal(isLocked("SUPERSEDED"), true);
  assert.equal(isLocked("DRAFT"), false);
  assert.equal(isLocked("REVIEW"), false);
  assert.equal(isOpen("DRAFT"), true);
  assert.equal(isOpen("APPROVED"), false);
});

test("approval is only offered from ready-for-approval", () => {
  const offered = (status: string) =>
    nextStatuses(status).map((next) => next.status);
  assert.ok(offered("READY_FOR_APPROVAL").includes("APPROVED"));
  assert.ok(!offered("DRAFT").includes("APPROVED"));
  assert.ok(!offered("REVIEW").includes("APPROVED"));
  assert.ok(!offered("CONTRIBUTOR_REVIEW").includes("APPROVED"));
});

test("an approved pack offers publication and nothing that edits it", () => {
  const offered = nextStatuses("APPROVED").map((next) => next.status);
  assert.deepEqual(offered, ["PUBLISHED"]);
});

test("a published pack offers nothing — it is finished", () => {
  assert.deepEqual(nextStatuses("PUBLISHED"), []);
  assert.deepEqual(nextStatuses("SUPERSEDED"), []);
});

test("approving carries a warning about what it means", () => {
  const approve = nextStatuses("READY_FOR_APPROVAL").find(
    (next) => next.status === "APPROVED");
  assert.ok(approve);
  assert.match(approve.hint, /name/);
  assert.match(approve.hint, /read-only/);
});

// ==================================================================== tones

test("a critical finding and a low one do not look the same", () => {
  assert.equal(severityTone("CRITICAL"), "negative");
  assert.equal(severityTone("HIGH"), "negative");
  assert.equal(severityTone("MEDIUM"), "warning");
  assert.equal(severityTone("LOW"), "info");
  assert.notEqual(severityTone("CRITICAL"), severityTone("LOW"));
});

test("an unknown severity is not silently treated as serious", () => {
  assert.equal(severityTone("SOMETHING_NEW"), "default");
});

test("approved and published read as done; changes-requested does not", () => {
  assert.equal(packStatusTone("APPROVED"), "positive");
  assert.equal(packStatusTone("PUBLISHED"), "positive");
  assert.equal(packStatusTone("CHANGES_REQUESTED"), "warning");
  assert.equal(packStatusTone("DRAFT"), "default");
});

test("an unknown readiness state is treated as red, not green", () => {
  assert.equal(stateTone("GREEN"), "positive");
  assert.equal(stateTone("RED"), "negative");
  // The safe reading of a value outside the vocabulary is the pessimistic
  // one. A pack reading green because its state was mistyped is the failure
  // that actually costs something.
  assert.equal(stateTone("PURPLE"), "negative");
});

// ===================================================================== dates

test("a missing meeting date says so rather than showing an epoch", () => {
  assert.equal(formatDay(null), "no date set");
  assert.equal(formatDay(""), "no date set");
  assert.equal(daysUntil(null), "no date set");
});

test("an unparseable date is shown as sent rather than as Invalid Date", () => {
  assert.equal(formatDay("not a date"), "not a date");
  assert.equal(daysUntil("not a date"), "not a date");
});

test("days are counted against a passed-in now, so a list cannot straddle midnight", () => {
  const now = Date.parse("2026-09-04T12:00:00Z");
  assert.equal(daysUntil("2026-09-04T18:00:00Z", now), "today");
  assert.equal(daysUntil("2026-09-05T12:00:00Z", now), "tomorrow");
  assert.equal(daysUntil("2026-09-03T12:00:00Z", now), "yesterday");
  assert.equal(daysUntil("2026-09-11T12:00:00Z", now), "in 7 days");
  assert.equal(daysUntil("2026-08-28T12:00:00Z", now), "7 days ago");
});
