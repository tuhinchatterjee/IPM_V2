/**
 * Unit tests for the UI reducer. No network, no backend.
 *
 * These cover the fencing rules, which are the ones that go wrong in
 * practice: a replayed event after a reconnect, and a late event from a run
 * the user has already moved on from.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { RunEvent, RunStatus } from "./client.ts";
import { collapsedSummary, failedStage, initial, reduce } from "./reducer.ts";

function event(over: Partial<RunEvent> = {}): RunEvent {
  return {
    schema_version: "v4.1",
    event_id: "ev-1",
    run_id: "run-a",
    seq: 1,
    event_type: "model.requested",
    stage: "understanding",
    operation: "generate",
    status: "started",
    occurred_at: "2026-09-10T00:00:00.000Z",
    elapsed_ms: 100,
    attempt: 1,
    submission: 0,
    round: 0,
    public_message: "Understanding the request",
    detail_ref: "",
    error_id: "",
    trace_id: "tr-1",
    span_id: "sp-1",
    parent_span_id: "",
    ...over,
  };
}

test("future steps are prospective, never complete", () => {
  const view = initial("run-a");
  assert.ok(view.steps.every((s) => s.state === "prospective"));
  assert.ok(!view.steps.some((s) => s.stage === "executing"),
    "a stage that may never run is not drawn before it happens");
});

test("an event from another run is ignored", () => {
  const view = reduce(initial("run-a"), {
    type: "event",
    event: event({ run_id: "run-b", seq: 5 }),
  });
  assert.equal(view.lastSeq, 0);
});

test("a replayed event does not duplicate a step", () => {
  let view = reduce(initial("run-a"), { type: "event", event: event() });
  const before = view.steps.find((s) => s.stage === "understanding");
  view = reduce(view, { type: "event", event: event() });
  const after = view.steps.find((s) => s.stage === "understanding");
  assert.equal(after?.substeps.length, before?.substeps.length);
  assert.equal(view.lastSeq, 1);
});

test("a failed event marks the step and exposes its error id", () => {
  let view = initial("run-a");
  view = reduce(view, { type: "event", event: event() });
  view = reduce(view, {
    type: "event",
    event: event({
      seq: 2,
      stage: "executing",
      status: "failed",
      event_type: "tool.failed",
      error_id: "err-abc123456789",
      public_message: "Executing query failed at the bind check.",
    }),
  });
  assert.equal(failedStage(view), "executing");
  assert.equal(view.errorId, "err-abc123456789");
});

test("a settled status closes any step still marked running", () => {
  let view = reduce(initial("run-a"), { type: "event", event: event() });
  const status = {
    run_id: "run-a",
    state: "COMPLETED",
    error_code: "",
    error_id: "",
    final_response: null,
  } as unknown as RunStatus;
  view = reduce(view, { type: "settled", status });
  assert.ok(!view.steps.some((s) => s.state === "running"));
  assert.equal(view.terminal, true);
});

test("a stop is summarised as a stop, not as an answer", () => {
  let view = initial("run-a");
  view = reduce(view, {
    type: "settled",
    status: {
      run_id: "run-a",
      state: "FAILED",
      error_code: "COST_LIMIT",
      error_id: "",
      final_response: null,
    } as unknown as RunStatus,
  });
  assert.match(collapsedSummary(view), /Stopped: COST_LIMIT/);
});

test("V4-AT-082: connection loss is a client state, not a server failure", () => {
  let view = reduce(initial("run-a"), { type: "event", event: event() });
  view = reduce(view, { type: "connection", state: "lost" });
  assert.equal(view.connection, "lost");
  assert.equal(view.terminal, false,
    "losing the stream must not mark the run finished");
  assert.equal(view.state, "ACCEPTED",
    "the client does not know the server failed, and must not say it did");
});

test("V4-AT-068: the failed step is identifiable for auto-expansion", () => {
  let view = reduce(initial("run-a"), { type: "event", event: event() });
  assert.equal(failedStage(view), "", "nothing has failed yet");
  view = reduce(view, {
    type: "event",
    event: event({
      seq: 2,
      stage: "executing",
      status: "failed",
      event_type: "tool.failed",
      public_message: "Executing query failed at the bind check.",
    }),
  });
  assert.equal(failedStage(view), "executing");
  const step = view.steps.find((s) => s.stage === "executing");
  assert.equal(step?.state, "failed");
  assert.match(step?.detail ?? "", /bind check/,
    "the panel can show WHICH substep failed, not just that one did");
});

test("V4-AT-069: substeps keep their operation and detail reference", () => {
  const view = reduce(initial("run-a"), {
    type: "event",
    event: event({
      status: "failed",
      event_type: "model.response_received",
      operation: "generate",
      detail_ref: "dt-abc123",
      error_id: "err-abc123456789",
    }),
  });
  const sub = view.steps.find((s) => s.stage === "understanding")?.substeps[0];
  assert.equal(sub?.operation, "generate");
  assert.equal(sub?.detailRef, "dt-abc123");
  assert.equal(sub?.errorId, "err-abc123456789");
});
