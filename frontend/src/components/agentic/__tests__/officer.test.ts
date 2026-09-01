/**
 * §6–§11 — what the officer indicator says.
 *
 * The rules the brief is strictest about are rules about wording and about
 * stopping, not about pixels, so they are tested here rather than left to a
 * screenshot: the pulse stops when the work does, one specialist is not
 * "coordinating", and nothing on screen is a fabricated percentage.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import * as officer from "../officer.ts";
import type { Live, Stage } from "../officer.ts";

function live(overrides: Partial<Live> = {}): Live {
  return { stage: "CALCULATING", officer_level: 2, ...overrides };
}

describe("the stage vocabulary", () => {
  it("is §7's eleven states, in order", () => {
    assert.deepEqual(officer.SEQUENCE, [
      "QUEUED",
      "UNDERSTANDING",
      "SCOPING",
      "SELECTING_DATA",
      "COORDINATING",
      "CALCULATING",
      "VALIDATING",
      "INTERPRETING",
      "COMPLETE",
    ]);
  });

  it("gives every stage a caption and a short label", () => {
    const all: Stage[] = [...officer.SEQUENCE, ...officer.TERMINAL];
    for (const stage of all) {
      assert.ok(officer.SHORT[stage], `${stage} has no label`);
      assert.ok(officer.CAPTIONS[stage], `${stage} has no caption`);
    }
  });

  it("says nothing about how the model is thinking", () => {
    // §7: "Do not show hidden chain-of-thought." Every caption describes the
    // WORK, not the reasoning behind it.
    for (const caption of Object.values(officer.CAPTIONS)) {
      assert.doesNotMatch(caption, /thinking|reasoning|considering|pondering/i);
    }
  });
});

describe("when the indicator is on screen", () => {
  it("is working while a stage is not terminal", () => {
    assert.equal(officer.isWorking(live({ stage: "SCOPING" })), true);
  });

  it("stops completely when the work is done", () => {
    // §10. A pulse that keeps beating after the answer arrived teaches the
    // reader that the pulse means nothing.
    for (const stage of officer.TERMINAL) {
      assert.equal(officer.isWorking(live({ stage })), false, stage);
    }
  });

  it("shows nothing at all when there is no run", () => {
    assert.equal(officer.isWorking(null), false);
    assert.equal(officer.statusLine(null), "");
    assert.equal(officer.caption(null), "");
    assert.deepEqual(officer.completed(null), []);
  });
});

describe("the status line", () => {
  it("names the officer working, in §4's words", () => {
    assert.equal(
      officer.statusLine(live({ officer_level: 1 })),
      "Credit Analyst is working",
    );
    assert.equal(
      officer.statusLine(live({ officer_level: 4 })),
      "Chief Orchestrator is working",
    );
  });

  it("prefers the title the run recorded over the one the level implies", () => {
    assert.equal(
      officer.statusLine(live({ officer_level: 1, officer_title: "Portfolio Risk Lead" })),
      "Portfolio Risk Lead is working",
    );
  });

  it("says nobody is working once the run has finished", () => {
    assert.equal(officer.statusLine(live({ stage: "COMPLETE" })), "");
  });
});

describe("the caption", () => {
  it("prefers the run's own detail — §8's 'Validating 6 calculations'", () => {
    assert.equal(
      officer.caption(live({ stage: "VALIDATING", detail: "Validating 6 calculations" })),
      "Validating 6 calculations",
    );
  });

  it("falls back to the API's caption before the local copy", () => {
    assert.equal(
      officer.caption(live({ caption: "Reading the published book." })),
      "Reading the published book.",
    );
  });

  it("ignores a detail that is only whitespace", () => {
    assert.equal(
      officer.caption(live({ stage: "SCOPING", detail: "   " })),
      officer.CAPTIONS.SCOPING,
    );
  });
});

describe("the specialist line", () => {
  it("lists the specialists in §8's form", () => {
    assert.equal(
      officer.specialistLine(live({ specialists: ["Ratings", "IFRS 9", "DPD", "Covenants"] })),
      "Ratings · IFRS 9 · DPD · Covenants",
    );
  });

  it("says nothing for one specialist", () => {
    // "Coordinating 1 specialist" is a sentence about nothing, and showing it
    // on every ordinary question would make coordination look like the norm.
    assert.equal(officer.specialistLine(live({ specialists: ["IFRS 9"] })), "");
    assert.equal(officer.specialistCount(live({ specialists: ["IFRS 9"] })), "");
    assert.equal(officer.specialistLine(live({ specialists: [] })), "");
  });

  it("counts only when there is genuinely coordination", () => {
    assert.equal(
      officer.specialistCount(live({ specialists: ["Ratings", "IFRS 9", "DPD"] })),
      "Coordinating 3 specialists",
    );
  });
});

describe("elapsed time", () => {
  it("is seconds, then minutes — never milliseconds", () => {
    assert.equal(officer.elapsed(4_200), "4s");
    assert.equal(officer.elapsed(59_000), "59s");
    assert.equal(officer.elapsed(60_000), "1m");
    assert.equal(officer.elapsed(95_000), "1m 35s");
  });

  it("shows nothing before the first second", () => {
    // A number changing ten times a second is not information.
    assert.equal(officer.elapsed(300), "");
    assert.equal(officer.elapsed(0), "");
    assert.equal(officer.elapsed(undefined), "");
    assert.equal(officer.elapsed(-5), "");
  });
});

describe("what has already happened", () => {
  it("is the stages before this one", () => {
    assert.deepEqual(officer.completed(live({ stage: "CALCULATING" })), [
      "QUEUED",
      "UNDERSTANDING",
      "SCOPING",
      "SELECTING_DATA",
      "COORDINATING",
    ]);
  });

  it("prefers the list the run actually recorded", () => {
    assert.deepEqual(
      officer.completed(live({ stage: "CALCULATING", completed: ["QUEUED", "SCOPING"] })),
      ["QUEUED", "SCOPING"],
    );
  });

  it("has nothing to show for a stage outside the sequence", () => {
    assert.deepEqual(officer.completed(live({ stage: "FAILED" })), []);
  });
});

describe("escalation", () => {
  it("is shown only when a run actually escalated — §9", () => {
    assert.equal(officer.escalation(live()), null);
    assert.equal(officer.escalation(live({ escalation_line: "   " })), null);
  });

  it("carries the reason beside the line, never a bare heading", () => {
    const found = officer.escalation(
      live({
        escalation_line: "Escalated to Portfolio Risk Lead",
        selection_reason: "Three sectors moved together.",
      }),
    );
    assert.deepEqual(found, {
      line: "Escalated to Portfolio Risk Lead",
      reason: "Three sectors moved together.",
    });
  });

  it("does not leave a dangling reason when there is none", () => {
    assert.equal(officer.escalation(live({ escalation_line: "Escalated" }))?.reason, "");
  });
});

describe("the screen-reader announcement", () => {
  it("says in words what the pulse says visually — §10", () => {
    const said = officer.announcement(
      live({ stage: "CALCULATING", officer_level: 3, specialists: ["Ratings", "IFRS 9"] }),
    );
    assert.match(said, /Portfolio Risk Lead is working/);
    assert.match(said, /Running governed calculations/);
    assert.match(said, /Specialists: Ratings · IFRS 9/);
  });

  it("is the same words that are on screen, not a separate description", () => {
    const now = live({ stage: "VALIDATING", detail: "Validating 6 calculations" });
    assert.ok(officer.announcement(now).includes(officer.caption(now)));
  });

  it("is empty when nothing is running", () => {
    assert.equal(officer.announcement(null), "");
  });
});

describe("polling", () => {
  it("is fast early and slow later", () => {
    // §6 forbids a fake percentage bar, so the caption IS the progress. A
    // stale caption reads as nothing happening.
    assert.ok(officer.pollAfter(1_000) < officer.pollAfter(20_000));
    assert.ok(officer.pollAfter(20_000) < officer.pollAfter(120_000));
  });

  it("never polls fast enough to be a request per frame", () => {
    assert.ok(officer.pollAfter(0) >= 500);
  });
});
