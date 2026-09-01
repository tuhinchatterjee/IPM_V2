import assert from "node:assert/strict";
import { test } from "node:test";

import { ANSWER_KINDS, answerKindOf } from "../answer-kind.ts";

test("§39 names eight answer kinds and the module knows all of them", () => {
  assert.equal(ANSWER_KINDS.length, 8);
  assert.ok(ANSWER_KINDS.includes("clarification"));
  assert.ok(ANSWER_KINDS.includes("unsupported"));
  assert.ok(ANSWER_KINDS.includes("controlled_failure"));
});

test("a refused plan is a controlled failure, not an unsupported question", () => {
  // Reporting it as unsupported tells the reader we CANNOT do this, when
  // what happened is that we would not.
  assert.equal(
    answerKindOf({ rejected: ["the plan crossed a governed boundary"] }),
    "controlled_failure",
  );
});

test("a clarification outranks unmatched", () => {
  // Stopping to ask is a decision. Grouping it with the questions we could
  // not parse loses the distinction the user is complaining about.
  assert.equal(
    answerKindOf({
      clarification: { question: "which book?" },
      unmatched: true,
    }),
    "clarification",
  );
});

test("an unmatched question is unsupported", () => {
  assert.equal(answerKindOf({ unmatched: true, steps: [] }), "unsupported");
});

test("an agentic run is filed as agentic even when it produced steps", () => {
  assert.equal(
    answerKindOf({ mode: { execution: "agentic" }, steps: [{}, {}] }),
    "agentic",
  );
});

test("an answer with no steps is metadata rather than an empty analysis", () => {
  // A question about which datasets exist computed no portfolio figure, and
  // filing it as an analysis would put it in the accuracy numbers.
  assert.equal(answerKindOf({ steps: [] }), "metadata");
});

test("an ordinary computed answer is an analysis", () => {
  assert.equal(answerKindOf({ status: "succeeded", steps: [{}] }), "analysis");
});

test("a failed status is a controlled failure whatever else is set", () => {
  assert.equal(
    answerKindOf({ status: "failed", steps: [{}] }),
    "controlled_failure",
  );
});

test("an empty run does not throw and lands somewhere real", () => {
  // Defaulting has to be safe: this classifier runs on every answer, and an
  // exception here would take the answer down with it.
  assert.ok(ANSWER_KINDS.includes(answerKindOf({})));
});
