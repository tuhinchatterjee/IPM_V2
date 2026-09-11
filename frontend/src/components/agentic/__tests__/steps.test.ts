import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  type ProgressDocument,
  type ProgressStep,
  type StepStatus,
  SUPPORTED_VERSION,
  analyses,
  announcement,
  current,
  details,
  finished,
  pollAfter,
  seconds,
  understands,
} from "../steps.ts";

/**
 * The rules the progress panel follows, tested without rendering it.
 *
 * These are the decisions that would be invisible in a snapshot and wrong in
 * production: which step the reader is told is running, what a screen reader
 * hears and how often, when polling stops, which Details rows appear, and
 * whether a document from a newer server is rendered half-understood.
 */

function step(over: Partial<ProgressStep> = {}): ProgressStep {
  return {
    key: "understanding",
    label: "Understanding your question",
    status: "done" as StepStatus,
    started_ms: 0,
    completed_ms: 2400,
    elapsed_ms: 2400,
    substeps: [],
    detail: {},
    ...over,
  };
}

function document(over: Partial<ProgressDocument> = {}): ProgressDocument {
  return {
    turn_id: "ews-1",
    version: 1,
    sequence: 4,
    steps: [step()],
    summary: {},
    elapsed_ms: 2400,
    active: true,
    outcome: "",
    completion_line: "",
    ...over,
  };
}

describe("the elapsed figure", () => {
  it("reads the way a person would say it", () => {
    assert.equal(seconds(31_800), "31.8s");
    assert.equal(seconds(900), "0.9s");
    assert.equal(seconds(65_000), "1m 5s");
    assert.equal(seconds(120_000), "2m");
  });

  it("says nothing rather than zero", () => {
    // A row that has not started has no duration. "0.0s" would claim it ran
    // instantly, which is a different and untrue statement.
    assert.equal(seconds(0), "");
    assert.equal(seconds(null), "");
    assert.equal(seconds(undefined), "");
    assert.equal(seconds(-5), "");
  });

  it("matches the backend's formatting", () => {
    // Both sides format the same way, so the live figure on the running step
    // does not sit beside finished durations written in another style.
    assert.equal(seconds(5_000), "5.0s");
  });
});

describe("how often the browser asks again", () => {
  it("watches closely while the early stages are quick", () => {
    assert.equal(pollAfter(0), 700);
    assert.equal(pollAfter(4_999), 700);
  });

  it("eases off as the investigation gets long", () => {
    assert.equal(pollAfter(5_000), 1_500);
    assert.equal(pollAfter(29_999), 1_500);
    assert.equal(pollAfter(30_000), 4_000);
  });

  it("never polls faster than twice a second", () => {
    // A minute-long turn polled every 100ms is six hundred requests to watch
    // a list that changes eleven times.
    for (const ms of [0, 1_000, 10_000, 60_000, 600_000]) {
      assert.ok(pollAfter(ms) >= 500, `${ms} polled after ${pollAfter(ms)}`);
    }
  });
});

describe("which step the reader is looking at", () => {
  it("names the one the server says is running", () => {
    const doc = document({
      steps: [
        step({ key: "understanding", status: "done" }),
        step({ key: "analysing", label: "Running Early Warning analysis", status: "active" }),
      ],
    });
    assert.equal(current(doc)?.key, "analysing");
  });

  it("names none when nothing is running", () => {
    assert.equal(current(document({ steps: [step({ status: "done" })] })), null);
    assert.equal(current(null), null);
  });

  it("does not treat a note as the work in progress", () => {
    // "Additional drill-down deferred" is something that happened, not
    // something happening.
    const doc = document({
      steps: [step({ key: "deferred", status: "note" })],
    });
    assert.equal(current(doc), null);
  });
});

describe("the analyses counter", () => {
  const analysing = step({
    key: "analysing",
    status: "active",
    substeps: [
      { key: "population", label: "Establishing the position", status: "done", completed_ms: 100, rows: 25 },
      { key: "movement", label: "Checking movement", status: "done", completed_ms: 200, rows: 4 },
      { key: "concentration", label: "Testing concentration", status: "active", completed_ms: null, rows: 0 },
      { key: "ranking", label: "Ranking the names", status: "waiting", completed_ms: null, rows: 0 },
    ],
  });

  it("counts what has reported against what was planned", () => {
    assert.deepEqual(analyses(analysing), { done: 2, total: 4 });
  });

  it("counts a refused analysis as reported", () => {
    // It is finished with, and leaving it out would make the counter stall
    // on a turn where one step could not run.
    const withNote = step({
      substeps: [
        { key: "grouping", label: "Grouping", status: "note", completed_ms: 10, rows: 0 },
      ],
    });
    assert.deepEqual(analyses(withNote), { done: 1, total: 1 });
  });

  it("is empty for a step that has no analyses under it", () => {
    assert.deepEqual(analyses(step()), { done: 0, total: 0 });
    assert.deepEqual(analyses(null), { done: 0, total: 0 });
  });
});

describe("what a screen reader is told", () => {
  it("names the running step rather than re-reading the list", () => {
    // §29: no rapid noisy announcements. Eleven rows re-announced every
    // second is worse than no live region at all.
    const doc = document({
      steps: [
        step({ key: "understanding", status: "done" }),
        step({ key: "scoping", label: "Resolving scope and intent", status: "done" }),
        step({ key: "planning", label: "Planning the investigation", status: "active" }),
      ],
    });
    assert.equal(announcement(doc), "Planning the investigation");
  });

  it("says how far the investigation has got", () => {
    const doc = document({
      steps: [
        step({
          key: "analysing",
          label: "Running Early Warning analysis",
          status: "active",
          substeps: [
            { key: "population", label: "a", status: "done", completed_ms: 1, rows: 0 },
            { key: "movement", label: "b", status: "active", completed_ms: null, rows: 0 },
            { key: "ranking", label: "c", status: "waiting", completed_ms: null, rows: 0 },
          ],
        }),
      ],
    });
    assert.equal(
      announcement(doc),
      "Running Early Warning analysis. 1 of 3 analyses complete.",
    );
  });

  it("reads the completion line once the work stops", () => {
    const doc = document({
      active: false,
      completion_line: "Analysed in 31.8s · 6 analyses · evidence checked",
      steps: [step({ status: "done" })],
    });
    assert.equal(
      announcement(doc),
      "Analysed in 31.8s · 6 analyses · evidence checked",
    );
  });

  it("falls back to a plain word rather than to silence", () => {
    assert.equal(announcement(document({ steps: [step({ status: "done" })] })), "Working.");
    assert.equal(announcement(null), "");
  });
});

describe("whether the work has stopped", () => {
  it("follows the server, not the step statuses", () => {
    assert.equal(finished(document({ active: true })), false);
    assert.equal(finished(document({ active: false })), true);
    assert.equal(finished(null), false);
  });
});

describe("the Details table", () => {
  it("orders the rows the same way every time", () => {
    const doc = document({
      active: false,
      elapsed_ms: 31_800,
      summary: {
        evidence_check: "Passed",
        mode: "Standard",
        analyses: 6,
        functionality: "Early Warning",
      },
    });
    assert.deepEqual(
      details(doc).map((r) => r.label),
      ["Mode", "Functionality", "Analyses completed", "Evidence check", "Elapsed"],
    );
  });

  it("leaves out what the server did not send", () => {
    // A row reading "Scope —" tells the reader nothing except that somebody
    // wrote a row.
    const rows = details(document({ summary: { mode: "Deep" } }));
    assert.ok(!rows.some((r) => r.label === "Scope"));
    assert.deepEqual(rows[0], { label: "Mode", value: "Deep" });
  });

  it("shows a deferred drill-down without the arithmetic behind it", () => {
    const rows = details(document({ summary: { deferred: 1 } }));
    const row = rows.find((r) => r.label === "Additional analysis deferred");
    assert.equal(row?.value, "1");
    assert.ok(!JSON.stringify(rows).toLowerCase().includes("budget"));
  });

  it("never offers a row for something the reader cannot act on", () => {
    // §18: no tokens, no call counters, no model names — even if a future
    // server started sending them.
    const rows = details(
      document({
        summary: {
          mode: "Standard",
          model_calls: 7,
          tokens: 4200,
          provider: "anthropic",
        },
      }),
    );
    assert.deepEqual(rows.map((r) => r.label), ["Mode", "Elapsed"]);
    const written = JSON.stringify(rows).toLowerCase();
    for (const forbidden of ["model", "token", "provider", "anthropic"]) {
      assert.ok(!written.includes(forbidden), `${forbidden} reached Details`);
    }
  });
});

describe("a document from a server this client does not understand", () => {
  it("accepts the version it was built for", () => {
    assert.equal(understands({ version: SUPPORTED_VERSION }), true);
    assert.equal(understands({ version: 1 }), true);
  });

  it("refuses a newer one rather than rendering it half-understood", () => {
    assert.equal(understands({ version: SUPPORTED_VERSION + 1 }), false);
  });

  it("refuses nothing at all", () => {
    assert.equal(understands(null), false);
    assert.equal(understands(undefined), false);
    assert.equal(understands({}), false);
  });
});
