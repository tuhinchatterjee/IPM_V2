/**
 * §39–§47 — how Requires Attention presents a Risk Case.
 *
 * The rule this file exists for is §46: the order must never depend on model
 * prose. That is a property of a comparator, so it is tested as one — a case
 * with alarming words in its conclusion and a low stored priority must sort
 * below a quiet one with a high priority.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { RiskCase } from "@/lib/api";
import * as severity from "../severity.ts";

function riskCase(overrides: Partial<RiskCase> = {}): RiskCase {
  return {
    id: 1,
    case_key: "rc_test",
    title: "Contracting Stage 2 share rose",
    level: "SEGMENT",
    level_label: "Segment",
    entity: "Contracting",
    entity_id: "contracting",
    entity_kind: "sector",
    period: "Q2 2026",
    prior_period: "Q1 2026",
    severity: "high",
    severity_score: 0.62,
    severity_version: "1.0",
    priority: 60,
    evidence_coverage: 1,
    exposure: 812,
    exposure_unit: "SAR mn",
    metrics: [],
    signals: [],
    conclusion: "Stage 2 share rose from 4.1% to 6.4%.",
    why: "",
    evidence: {},
    analyses: [],
    status: "NEW",
    status_label: "New",
    open: true,
    overdue: false,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    next_actions: [],
    ...overrides,
  } as RiskCase;
}

describe("ordering — §46", () => {
  it("is the stored priority, and nothing else", () => {
    const quiet = riskCase({ id: 1, priority: 90, conclusion: "Slight drift." });
    const loud = riskCase({
      id: 2,
      priority: 10,
      conclusion: "URGENT: catastrophic deterioration, immediate action required.",
    });
    assert.deepEqual(
      severity.sorted([loud, quiet]).map((c) => c.id),
      [1, 2],
    );
  });

  it("breaks a tie on the severity arithmetic, then on age", () => {
    const older = riskCase({ id: 1, priority: 50, severity_score: 0.5, created_at: "2026-01-01T00:00:00Z" });
    const newer = riskCase({ id: 2, priority: 50, severity_score: 0.5, created_at: "2026-06-01T00:00:00Z" });
    const bigger = riskCase({ id: 3, priority: 50, severity_score: 0.9 });
    assert.deepEqual(
      severity.sorted([older, newer, bigger]).map((c) => c.id),
      [3, 2, 1],
    );
  });

  it("does not mutate the list it was given", () => {
    const list = [riskCase({ id: 1, priority: 10 }), riskCase({ id: 2, priority: 90 })];
    severity.sorted(list);
    assert.deepEqual(list.map((c) => c.id), [1, 2]);
  });
});

describe("the filter tabs — §40", () => {
  it("are the five the brief names, in order", () => {
    assert.deepEqual([...severity.FILTERS], ["ALL", "PORTFOLIO", "SEGMENTS", "BORROWERS", "DATA"]);
  });

  it("each map to a case level, and ALL to none", () => {
    assert.equal(severity.FILTER_LEVEL.ALL, "");
    assert.equal(severity.FILTER_LEVEL.SEGMENTS, "SEGMENT");
    assert.equal(severity.FILTER_LEVEL.DATA, "DATA_QUALITY");
  });

  it("take their counts from the backend's grouped query", () => {
    // §47: "Do not state a number that is not backed by current Risk Cases."
    const counts = { ALL: 7, PORTFOLIO: 1, SEGMENT: 2, BORROWER: 3, DATA_QUALITY: 1 };
    assert.equal(severity.countFor("ALL", counts), 7);
    assert.equal(severity.countFor("BORROWERS", counts), 3);
    assert.equal(severity.countFor("DATA", counts), 1);
  });

  it("show zero rather than a guess when no counts have arrived", () => {
    assert.equal(severity.countFor("ALL", undefined), 0);
    assert.equal(severity.countFor("SEGMENTS", {}), 0);
  });
});

describe("the severity band", () => {
  it("carries a word for every band, not colour alone — §10", () => {
    for (const band of severity.SEVERITIES) {
      assert.ok(severity.SEVERITY_LABEL[band], band);
      assert.ok(severity.SEVERITY_TONE[band], band);
    }
  });

  it("uses tokens rather than a literal colour", () => {
    // §11: "No literal hard-coded green in components." The same rule, applied
    // to every band: a hex value here cannot follow the theme.
    for (const tone of Object.values(severity.SEVERITY_TONE)) {
      assert.doesNotMatch(tone, /#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i);
    }
  });
});

describe("urgency", () => {
  it("is narrow enough to mean something", () => {
    assert.equal(severity.isUrgent(riskCase({ severity: "critical" })), true);
    assert.equal(severity.isUrgent(riskCase({ overdue: true })), true);
    assert.equal(severity.isUrgent(riskCase({ severity: "high" })), false);
    assert.equal(severity.isUrgent(riskCase({ severity: "medium" })), false);
  });

  it("never marks a closed case", () => {
    assert.equal(
      severity.isUrgent(riskCase({ severity: "critical", open: false, overdue: true })),
      false,
    );
  });
});

describe("the due date", () => {
  it("counts in days, in the reader's terms", () => {
    const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString();
    assert.equal(severity.dueLabel(riskCase({ due_at: inDays(0.4) })), "due today");
    assert.equal(severity.dueLabel(riskCase({ due_at: inDays(1) })), "due tomorrow");
    assert.equal(severity.dueLabel(riskCase({ due_at: inDays(4) })), "due in 4d");
    assert.match(severity.dueLabel(riskCase({ due_at: inDays(-3) })), /3d overdue/);
  });

  it("says nothing for a closed case or a missing date", () => {
    assert.equal(severity.dueLabel(riskCase({ due_at: undefined })), "");
    assert.equal(
      severity.dueLabel(riskCase({ due_at: new Date().toISOString(), open: false })),
      "",
    );
  });

  it("does not fall over on a date it cannot read", () => {
    assert.equal(severity.dueLabel(riskCase({ due_at: "not a date" })), "");
  });
});

describe("evidence coverage — §54", () => {
  it("is words, not a percentage", () => {
    // A percentage invites a reader to treat 0.8 as "80% true", which it is
    // not: it is "four of the five things we expected are attached".
    assert.equal(severity.coverage(riskCase({ evidence_coverage: 1 })), "Fully evidenced");
    assert.equal(severity.coverage(riskCase({ evidence_coverage: 0.8 })), "Mostly evidenced");
    assert.equal(severity.coverage(riskCase({ evidence_coverage: 0.2 })), "Partly evidenced");
    assert.equal(
      severity.coverage(riskCase({ evidence_coverage: 0 })),
      "Evidence not yet attached",
    );
  });

  it("never renders a number", () => {
    for (const value of [0, 0.33, 0.7, 1]) {
      assert.doesNotMatch(severity.coverage(riskCase({ evidence_coverage: value })), /\d/);
    }
  });
});

describe("the row subtitle", () => {
  it("shows a segment's share of the book — §42", () => {
    const found = riskCase({
      level: "SEGMENT",
      evidence: { segment: { share_of_book: 0.114 } },
    });
    assert.match(severity.subtitle(found), /11\.4% of the book/);
    assert.match(severity.subtitle(found), /Q2 2026/);
  });

  it("shows a borrower's exposure and position — §43", () => {
    const found = riskCase({
      level: "BORROWER",
      entity_kind: "customer",
      exposure: 41.2,
      signals: ["Stage 2 → Stage 3", "DPD 61"],
    });
    assert.match(severity.subtitle(found), /41\.2 SAR mn/);
    assert.match(severity.subtitle(found), /Stage 2 → Stage 3/);
  });

  it("names the dataset for a data case rather than an exposure", () => {
    const found = riskCase({
      level: "DATA_QUALITY",
      entity: "customer_ratings",
      exposure: 812,
    });
    const line = severity.subtitle(found);
    assert.match(line, /customer_ratings/);
    assert.doesNotMatch(line, /SAR mn/);
  });

  it("degrades to the period alone rather than to an empty row", () => {
    assert.equal(
      severity.subtitle(riskCase({ level: "PORTFOLIO", exposure: undefined })),
      "Q2 2026",
    );
  });
});

describe("number formatting", () => {
  it("drops precision nobody reads as the figure grows", () => {
    assert.equal(severity.format(4.17), "4.17");
    assert.equal(severity.format(41.23), "41.2");
    assert.equal(severity.format(4123.7), "4,124");
  });

  it("treats a negative figure the same way", () => {
    assert.equal(severity.format(-4123.7), "-4,124");
  });
});
