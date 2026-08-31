/**
 * §25, §28, §29 — how the Early Warning screens present the governed signal.
 *
 * The rule the whole module exists to keep: there is no score, and the
 * presentation layer must not quietly reintroduce one. The backend went to
 * some trouble to rank borrowers by counts a reader can reproduce; a
 * weighted sum in a client-side comparator would undo that at the last step,
 * where nobody is looking for it.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { SignalObservation, SignalStanding } from "@/lib/api";
import * as view from "../signal-view.ts";

function observation(
  overrides: Partial<SignalObservation> = {},
): SignalObservation {
  return {
    signal: "revenue_fell",
    family: "FINANCIAL",
    family_label: "Financial performance",
    label: "Revenue fell",
    fired: true,
    lifecycle: "NEW",
    lifecycle_means: "Not present at the previous reporting date.",
    severity: "CONCERN",
    value: 12,
    previous: 18,
    movement: -0.33,
    threshold: 0,
    threshold_version: "1.0.0",
    threshold_owner: "Credit Risk Analytics",
    dataset: "corporate_borrower_360",
    field: "revenue_growth_yoy_pct",
    test: "below",
    period: "Q2 2026",
    previous_period: "Q1 2026",
    booked_accounting: false,
    unavailable: "",
    means: "Turnover is below where it was a year ago.",
    available: true,
    ...overrides,
  };
}

function standing(overrides: Partial<SignalStanding> = {}): SignalStanding {
  const fired = overrides.fired ?? [observation()];
  return {
    version: "1.0.0",
    borrower_id: "CB-0001",
    period: "Q2 2026",
    sentence: "A sentence composed by the backend.",
    breadth: new Set(fired.map((o) => o.family)).size,
    severity: "CONCERN",
    persistence: 0,
    worsening: 0,
    improving: 0,
    agreement: [...new Set(fired.map((o) => o.family))].sort(),
    conflict: [],
    booked_accounting_signals: [],
    fired,
    cured: [],
    untested: [],
    families: {},
    ...overrides,
  };
}

describe("ordering conditions inside one borrower", () => {
  it("puts what got worse in front of what merely persists", () => {
    const rows = [
      observation({ label: "Quiet", lifecycle: "PERSISTING" }),
      observation({ label: "Worse", lifecycle: "WORSENING" }),
      observation({ label: "Fresh", lifecycle: "NEW" }),
    ].sort(view.byUrgency);
    assert.deepEqual(
      rows.map((r) => r.label),
      ["Worse", "Fresh", "Quiet"],
    );
  });

  it("breaks a lifecycle tie by severity, worst first", () => {
    const rows = [
      observation({ label: "Watch it", severity: "WATCH" }),
      observation({ label: "Serious", severity: "SEVERE" }),
      observation({ label: "Concerning", severity: "CONCERN" }),
    ].sort(view.byUrgency);
    assert.deepEqual(
      rows.map((r) => r.label),
      ["Serious", "Concerning", "Watch it"],
    );
  });

  it("is total, so the same evidence always renders the same way", () => {
    const rows = [
      observation({ label: "B" }),
      observation({ label: "A" }),
      observation({ label: "C" }),
    ];
    const forwards = [...rows].sort(view.byUrgency).map((r) => r.label);
    const backwards = [...rows].reverse().sort(view.byUrgency).map(
      (r) => r.label,
    );
    assert.deepEqual(forwards, backwards);
  });
});

describe("grouping by family", () => {
  it("tells one fact once rather than five times", () => {
    // The exact inflation §25 counts families to avoid: five liquidity
    // conditions off one utilisation number.
    const groups = view.byFamily(
      standing({
        fired: [
          observation({ family: "LIQUIDITY", label: "Utilisation high" }),
          observation({ family: "LIQUIDITY", label: "Utilisation rose" }),
          observation({ family: "LIQUIDITY", label: "Undrawn thin" }),
          observation({ family: "LEVERAGE", label: "Leverage rose" }),
        ],
      }),
    );
    assert.equal(groups.length, 2);
    assert.equal(groups.find((g) => g.family === "LIQUIDITY")?.fired.length, 3);
  });

  it("leads with the family carrying the worst condition", () => {
    const groups = view.byFamily(
      standing({
        fired: [
          observation({ family: "FINANCIAL", severity: "WATCH" }),
          observation({ family: "FINANCIAL", severity: "WATCH" }),
          observation({ family: "IFRS9", severity: "SEVERE" }),
        ],
      }),
    );
    assert.equal(groups[0].family, "IFRS9");
  });

  it("takes the family's severity from its worst condition", () => {
    const groups = view.byFamily(
      standing({
        fired: [
          observation({ family: "COLLATERAL", severity: "WATCH" }),
          observation({ family: "COLLATERAL", severity: "SEVERE" }),
        ],
      }),
    );
    assert.equal(groups[0].severity, "SEVERE");
  });
});

describe("the wording a row leads with", () => {
  it("counts conditions and families, never a score", () => {
    const said = view.summary(
      standing({
        fired: [
          observation({ family: "FINANCIAL" }),
          observation({ family: "LIQUIDITY" }),
        ],
      }),
    );
    assert.equal(said, "2 conditions across 2 families");
    assert.ok(!/\d\.\d/.test(said), "no decimal may appear: that is a score");
  });

  it("says so plainly when nothing fires", () => {
    assert.equal(
      view.summary(standing({ fired: [], breadth: 0 })),
      "No governed condition fires.",
    );
  });

  it("stays silent about movement when nothing moved", () => {
    // A column that says "no change" every quarter is a column people stop
    // reading, and then miss the quarter it changes.
    assert.equal(view.movement(standing({ fired: [] })), "");
  });

  it("names what moved, worst first", () => {
    const said = view.movement(
      standing({
        fired: [
          observation({ lifecycle: "WORSENING" }),
          observation({ lifecycle: "NEW" }),
        ],
        worsening: 1,
        improving: 1,
        cured: [observation({ lifecycle: "CURED" })],
      }),
    );
    assert.equal(said, "1 worse, 1 new, 1 better, 1 cured");
  });
});

describe("what could not be tested", () => {
  it("never lets a thin standing present as a clean one", () => {
    // §7. "Nothing fires" and "nothing could be tested" are different
    // answers and only one of them is reassuring.
    const said = view.notTested(
      standing({
        fired: [],
        untested: [
          observation({ available: false, unavailable: "No column." }),
          observation({ available: false, unavailable: "No column." }),
        ],
      }),
    );
    assert.match(said, /2 governed conditions could not be tested/);
  });

  it("says nothing when everything was testable", () => {
    assert.equal(view.notTested(standing()), "");
  });
});

describe("the booked accounting position", () => {
  it("stays separable from the prediction", () => {
    // §20: an early-warning signal is never described as a stage
    // classification. Keeping them apart here is how a caption stays honest.
    const booked = view.booked(
      standing({
        fired: [
          observation({ signal: "stage_2", booked_accounting: true }),
          observation({ signal: "revenue_fell" }),
        ],
      }),
    );
    assert.deepEqual(
      booked.map((o) => o.signal),
      ["stage_2"],
    );
  });
});

describe("evidence pointing the other way", () => {
  it("is named rather than dropped", () => {
    const said = view.conflicting(
      standing({
        fired: [observation({ family: "COVENANT", family_label: "Covenants" })],
        conflict: ["COVENANT"],
      }),
    );
    assert.equal(said, "Evidence points the other way in covenants.");
  });

  it("is empty when the evidence all points one way", () => {
    assert.equal(view.conflicting(standing()), "");
  });
});

describe("ordering borrowers on the overview", () => {
  it("ranks by breadth first, as the backend does", () => {
    const rows = [
      standing({ borrower_id: "A", breadth: 1 }),
      standing({ borrower_id: "B", breadth: 4 }),
      standing({ borrower_id: "C", breadth: 2 }),
    ].sort(view.byEvidence);
    assert.deepEqual(
      rows.map((r) => r.borrower_id),
      ["B", "C", "A"],
    );
  });

  it("falls through severity, persistence and worsening in that order", () => {
    const base = { breadth: 2 };
    const rows = [
      standing({ ...base, borrower_id: "A", severity: "CONCERN",
                 persistence: 1 }),
      standing({ ...base, borrower_id: "B", severity: "SEVERE" }),
      standing({ ...base, borrower_id: "C", severity: "CONCERN",
                 persistence: 1, worsening: 2 }),
    ].sort(view.byEvidence);
    assert.deepEqual(
      rows.map((r) => r.borrower_id),
      ["B", "C", "A"],
    );
  });

  it("is total, so two loads of the same book render the same order", () => {
    const rows = [
      standing({ borrower_id: "CB-3" }),
      standing({ borrower_id: "CB-1" }),
      standing({ borrower_id: "CB-2" }),
    ];
    assert.deepEqual(
      [...rows].sort(view.byEvidence).map((r) => r.borrower_id),
      [...rows].reverse().sort(view.byEvidence).map((r) => r.borrower_id),
    );
  });
});

describe("the lenses the overview offers", () => {
  it("offers questions rather than score bands", () => {
    for (const lens of view.LENSES) {
      assert.ok(lens.means.length > 20, `${lens.id} must explain itself`);
      assert.ok(
        !/score|band|rating of/i.test(lens.means),
        `${lens.id} must not describe a score`,
      );
    }
  });

  it("matches new, worsening, persisting, severe and breadth correctly", () => {
    const fresh = standing({ fired: [observation({ lifecycle: "NEW" })] });
    const worse = standing({
      fired: [observation({ lifecycle: "WORSENING" })],
      worsening: 1,
    });
    const stuck = standing({
      fired: [observation({ lifecycle: "PERSISTING" })],
      persistence: 2,
    });
    const bad = standing({ severity: "SEVERE" });
    const broad = standing({ breadth: 3 });

    assert.equal(view.matches(fresh, "new"), true);
    assert.equal(view.matches(worse, "new"), false);
    assert.equal(view.matches(worse, "worsening"), true);
    assert.equal(view.matches(stuck, "persisting"), true);
    assert.equal(view.matches(bad, "severe"), true);
    assert.equal(view.matches(broad, "multi"), true);
    assert.equal(view.matches(standing({ breadth: 2 }), "multi"), false);
  });

  it("lets everything through the default lens", () => {
    assert.equal(view.matches(standing({ fired: [] }), "all"), true);
  });
});

describe("severity presentation", () => {
  it("gives each of the three levels its own weight", () => {
    assert.equal(view.tone("SEVERE"), "danger");
    assert.equal(view.tone("CONCERN"), "warning");
    assert.equal(view.tone("WATCH"), "muted");
  });

  it("treats an unknown severity as the quietest, never the loudest", () => {
    // Failing loud on a value nobody defined turns a data problem into an
    // alarm, and an alarm nobody can explain is one people learn to ignore.
    assert.equal(view.tone("WHATEVER"), "muted");
  });
});

describe("joining a list into a sentence", () => {
  it("reads like English", () => {
    assert.equal(view.andList(["one"]), "one");
    assert.equal(view.andList(["one", "two"]), "one and two");
    assert.equal(view.andList(["one", "two", "three"]), "one, two and three");
    assert.equal(view.andList([]), "");
  });
});
