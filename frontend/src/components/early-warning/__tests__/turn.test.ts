import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  applyPoll,
  applyPollFailure,
  begin,
  errorFor,
  isReconnecting,
  isSettled,
  MISSES_BEFORE_RECONNECTING,
  MISSES_BEFORE_UNREACHABLE,
  type Poll,
} from "../turn.ts";

const running: Poll = { watching: true, state: "running", elapsed_ms: 1_000 };

describe("a turn's state belongs to the backend", () => {
  it("starts running", () => {
    const turn = begin("t1", "thread-1", "Why has Contracting deteriorated?");
    assert.equal(turn.state, "running");
    assert.equal(turn.answer, null);
    assert.equal(turn.failure, "");
    assert.equal(isSettled(turn), false);
  });

  it("stays running past sixty seconds, and past any other number", () => {
    // The defect, as an assertion. A certified turn takes 40-75 seconds and
    // there is no elapsed time at which the browser may call it dead.
    let turn = begin("t1", "thread-1", "Why?");
    for (const ms of [30_000, 59_000, 60_001, 75_000, 100_000, 300_000]) {
      turn = applyPoll(turn, { ...running, elapsed_ms: ms });
      assert.equal(turn.state, "running", `dead at ${ms}ms`);
      assert.equal(turn.failure, "");
      assert.equal(errorFor(turn, "t1"), "");
    }
    assert.equal(turn.elapsedMs, 300_000);
  });

  it("completes only when the backend says completed", () => {
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPoll(turn, running);
    turn = applyPoll(turn, {
      watching: true,
      state: "completed",
      answer: { answered: true, direct: "Analysed." },
      elapsed_ms: 73_200,
    });
    assert.equal(turn.state, "completed");
    assert.deepEqual(turn.answer, { answered: true, direct: "Analysed." });
    assert.equal(turn.failure, "");
    assert.equal(errorFor(turn, "t1"), "");
    assert.equal(isSettled(turn), true);
  });

  it("never shows an answer and an error at once", () => {
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPoll(turn, {
      watching: true,
      state: "completed",
      answer: { direct: "Analysed in 73.2s" },
    });
    assert.ok(turn.answer);
    assert.equal(turn.failure, "");
    assert.equal(errorFor(turn, "t1"), "");
  });

  it("fails only when the backend says failed", () => {
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPoll(turn, {
      watching: true,
      state: "failed",
      failure: "CreditProbe could not complete this analysis.",
      question: "Why?",
    });
    assert.equal(turn.state, "failed");
    assert.equal(turn.answer, null);
    assert.equal(
      errorFor(turn, "t1"),
      "CreditProbe could not complete this analysis.",
    );
  });

  it("keeps a terminal state whatever arrives afterwards", () => {
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPoll(turn, { watching: true, state: "completed", answer: { a: 1 } });
    turn = applyPoll(turn, { watching: true, state: "failed", failure: "no" });
    assert.equal(turn.state, "completed");
    turn = applyPollFailure(turn);
    assert.equal(turn.state, "completed");
  });
});

describe("a poll that did not arrive is not a failed analysis", () => {
  it("counts a miss and carries on", () => {
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPollFailure(turn);
    assert.equal(turn.state, "running");
    assert.equal(turn.missedPolls, 1);
    assert.equal(errorFor(turn, "t1"), "");
  });

  it("says nothing about one hiccup", () => {
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPollFailure(turn);
    assert.equal(isReconnecting(turn), false);
  });

  it("mentions reconnecting once the silence is material", () => {
    let turn = begin("t1", "thread-1", "Why?");
    for (let i = 0; i < MISSES_BEFORE_RECONNECTING; i += 1) {
      turn = applyPollFailure(turn);
    }
    assert.equal(isReconnecting(turn), true);
    assert.equal(turn.state, "running");
  });

  it("forgets the misses as soon as a poll arrives", () => {
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPollFailure(turn);
    turn = applyPollFailure(turn);
    turn = applyPoll(turn, running);
    assert.equal(turn.missedPolls, 0);
    assert.equal(isReconnecting(turn), false);
  });

  it("gives up only after the network is properly gone", () => {
    let turn = begin("t1", "thread-1", "Why?");
    for (let i = 0; i < MISSES_BEFORE_UNREACHABLE - 1; i += 1) {
      turn = applyPollFailure(turn);
      assert.equal(turn.state, "running");
    }
    turn = applyPollFailure(turn);
    assert.equal(turn.state, "failed");
    assert.match(turn.failure, /could not be reached/);
  });

  it("treats a worker that never saw the turn as no news", () => {
    // The deployment note: behind several workers a poll can land where the
    // turn is unknown. That is "I cannot see it", never "it failed".
    let turn = begin("t1", "thread-1", "Why?");
    turn = applyPoll(turn, { watching: false, state: "" });
    assert.equal(turn.state, "running");
    assert.equal(turn.failure, "");
  });
});

describe("an error belongs to the turn that caused it", () => {
  it("is not shown against a different turn", () => {
    let failed = begin("t1", "thread-1", "Why?");
    failed = applyPoll(failed, {
      watching: true,
      state: "failed",
      failure: "CreditProbe could not complete this analysis.",
    });
    assert.notEqual(errorFor(failed, "t1"), "");
    assert.equal(errorFor(failed, "t2"), "");
  });

  it("is not shown when there is no turn", () => {
    assert.equal(errorFor(null, "t1"), "");
  });

  it("does not survive into the next turn", () => {
    const first = applyPoll(begin("t1", "thread-1", "Why?"), {
      watching: true,
      state: "failed",
      failure: "CreditProbe could not complete this analysis.",
    });
    const second = begin("t2", "thread-1", "And now?");
    // The earlier turn keeps its own error; the later one starts clean.
    assert.notEqual(errorFor(first, "t1"), "");
    assert.equal(errorFor(second, "t2"), "");
    assert.equal(second.failure, "");
  });
});
