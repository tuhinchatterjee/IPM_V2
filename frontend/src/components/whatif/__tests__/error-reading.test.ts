import assert from "node:assert/strict";
import { test } from "node:test";

import { readWhatIfError } from "../../../lib/whatif-errors.ts";

/**
 * Four situations, four next actions, said apart.
 *
 * Every What-If failure reached the screen as one red bar carrying whatever
 * sentence the server happened to send. "You are not permitted to run a
 * scenario", "the analytical lake has not been built", "that shock is not one
 * this engine applies" and "the backend is not running" are four different
 * things with four different next actions, and flattening them meant a person
 * could not tell which one they were in — so all four read as "the product is
 * broken".
 *
 * The load-bearing distinction is RETRYABLE. A refusal that invites a retry
 * wastes the reader's time on a request that will be refused identically; a
 * transient failure that does not invite one loses the work they typed.
 */

function fail(status: number, message = "something", code = "") {
  const error = new Error(message) as Error & { status: number; code: string };
  error.status = status;
  error.code = code;
  return error;
}

test("an unreachable backend is not the reader's fault and is worth retrying", () => {
  const read = readWhatIfError(fail(0, "Could not reach the server", "network_error"));
  assert.equal(read.kind, "offline");
  assert.equal(read.retryable, true);
  assert.match(read.next, /Nothing you typed was lost/);
});

test("a permission refusal does not invite a retry", () => {
  const read = readWhatIfError(fail(403, "Not permitted."));
  assert.equal(read.kind, "not_permitted");
  assert.equal(read.retryable, false);
  assert.equal(read.severity, "refusal");
  assert.match(read.next, /administrator/i);
});

test("being signed out is not the same refusal as lacking the role", () => {
  // 401 and 403 used to read identically, so an expired session told the
  // reader to ask an administrator for a permission they already had.
  const read = readWhatIfError(fail(401, "Not authenticated."));
  assert.equal(read.kind, "signed_out");
  assert.equal(read.retryable, false);
  assert.equal(read.severity, "refusal");
  assert.match(read.next, /sign in again/i);
});

test("a refused scenario says the same request will be refused again", () => {
  const read = readWhatIfError(
    fail(422, "'gamma' is not a shock this engine applies."));
  assert.equal(read.kind, "refused");
  assert.equal(read.retryable, false);
  assert.match(read.next, /Change what you asked for/);
});

test("another bank's book is its own kind of refusal", () => {
  const read = readWhatIfError(fail(
    422, "That names a different book. What-If Analysis reads the Corporate "
       + "IFRS 9 domain only."));
  assert.equal(read.kind, "outside_domain");
  assert.equal(read.retryable, false);
  assert.match(read.next, /Corporate IFRS 9/);
});

test("something missing from the installation is not about the scenario", () => {
  const read = readWhatIfError(fail(503, "The analytical lake is not built here."));
  assert.equal(read.kind, "unavailable");
  assert.equal(read.retryable, false);
  assert.match(read.next, /about the installation/i);
});

test("a missing ML model still leaves the reader a way to run the scenario", () => {
  const read = readWhatIfError(fail(503, "The ML methodology cannot run here."));
  assert.equal(read.kind, "model_unavailable");
  assert.equal(read.retryable, false);
  assert.match(read.next, /Delta Model/);
});

test("a server defect says so rather than blaming the reader", () => {
  const read = readWhatIfError(fail(500, "Internal error"));
  assert.equal(read.kind, "defect");
  assert.match(read.next, /defect rather than something you did/);
  assert.match(read.next, /worth reporting/);
});

test("a missing thing is told from a refused one", () => {
  const read = readWhatIfError(fail(404, "No such saved What-If."));
  assert.equal(read.kind, "not_found");
  assert.equal(read.retryable, false);
});

test("every reading carries all four things a reader needs", () => {
  for (const error of [fail(0), fail(403), fail(404), fail(422), fail(500),
                       fail(503), new Error("plain"), "a string"]) {
    const read = readWhatIfError(error);
    assert.ok(read.kind, "a kind");
    assert.ok(read.title, "a title");
    assert.ok(read.message, "what happened");
    assert.ok(read.next, "what to do about it");
    assert.equal(typeof read.retryable, "boolean");
    assert.ok(["refusal", "failure"].includes(read.severity));
  }
});

test("no reading is empty, and nothing is null", () => {
  const read = readWhatIfError(null);
  assert.equal(read.kind, "unknown");
  assert.ok(read.message.length > 0);
});
