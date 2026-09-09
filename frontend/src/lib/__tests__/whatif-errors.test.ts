/**
 * Every failure a What-If can reach the screen with, and the one sentence that
 * is only allowed to appear for one of them.
 *
 * The UAT defect these exist to prevent: a page said "The CreditProbe backend
 * did not answer" while the backend was answering. It was a client-side
 * timeout, reported as an outage, and every check the tester made — including
 * a 200 from /health — agreed the backend was fine.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { readWhatIfError } from "../whatif-errors.ts";

/** An error shaped the way `ApiError` shapes one. */
function apiError(message: string, status: number, code = "http_error") {
  const error = new Error(message) as Error & { status: number; code: string };
  error.status = status;
  error.code = code;
  return error;
}

const NEVER_SAY = /backend did not answer/i;

test("only a request that reached nothing says the backend did not answer", () => {
  const offline = readWhatIfError(
    apiError("Cannot reach the CreditProbe backend.", 0, "network_error"));
  assert.equal(offline.kind, "offline");
  assert.match(offline.title, NEVER_SAY);
});

test("a client timeout is not an unreachable backend", () => {
  const reading = readWhatIfError(
    apiError("The backend did not respond within 190 seconds.", 0, "timeout"));
  assert.equal(reading.kind, "timeout");
  assert.doesNotMatch(reading.title, NEVER_SAY);
  assert.match(reading.next, /backend is running/i);
  assert.equal(reading.retryable, true);
});

test("401 says you are signed out, not that your role is wrong", () => {
  const reading = readWhatIfError(apiError("Not authenticated.", 401));
  assert.equal(reading.kind, "signed_out");
  assert.match(reading.title, /signed out/i);
  assert.match(reading.next, /sign in again/i);
  assert.doesNotMatch(reading.title, NEVER_SAY);
});

test("403 is about the role and says so", () => {
  const reading = readWhatIfError(
    apiError("You do not have permission to do this.", 403));
  assert.equal(reading.kind, "not_permitted");
  assert.match(reading.next, /Analyst permission/);
  assert.equal(reading.retryable, false);
});

test("a methodology refusal names the methodology", () => {
  const reading = readWhatIfError(apiError(
    "'quantum' is not an ECL methodology. The choices are Delta Model "
    + "(delta), ML Model — XGBoost (ml).", 422));
  assert.equal(reading.kind, "methodology");
  assert.match(reading.title, /methodology/i);
  assert.match(reading.message, /Delta Model/);
  assert.doesNotMatch(reading.title, NEVER_SAY);
});

test("a workbook failure says the workbook could not be generated", () => {
  const reading = readWhatIfError(apiError(
    "The detailed workbook could not be generated because the saved scenario "
    + "state is incomplete.", 422));
  assert.equal(reading.kind, "workbook");
  assert.match(reading.title, /workbook/i);
});

test("a period refusal names the period", () => {
  const reading = readWhatIfError(apiError(
    "Corporate IFRS 9 does not publish the period 'Q9 2031'.", 400));
  assert.equal(reading.kind, "period");
  assert.match(reading.title, /period/i);
});

test("a missing ML model is separated from a missing installation", () => {
  const model = readWhatIfError(apiError(
    "This scenario is valid, but no active ML model could be loaded.", 503));
  assert.equal(model.kind, "model_unavailable");
  assert.match(model.next, /Delta Model/);
  const other = readWhatIfError(apiError(
    "The analytical lake has not been built here.", 503));
  assert.equal(other.kind, "unavailable");
});

test("404, 409 and 429 each read as themselves", () => {
  assert.equal(readWhatIfError(apiError("No such saved What-If.", 404)).kind,
               "not_found");
  assert.equal(readWhatIfError(apiError("It changed underneath you.", 409)).kind,
               "conflict");
  assert.equal(readWhatIfError(apiError("Too many scenarios.", 429)).kind,
               "limit");
});

test("none of the statuses a server answers with claims the backend was silent", () => {
  for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
    const reading = readWhatIfError(apiError("something", status));
    assert.doesNotMatch(reading.title, NEVER_SAY,
      `HTTP ${status} must not read as an unreachable backend`);
    assert.doesNotMatch(reading.next, NEVER_SAY);
  }
});

test("a refusal never invites a pointless retry and a failure never loses work", () => {
  for (const status of [400, 401, 403, 404, 409, 422, 429]) {
    assert.equal(readWhatIfError(apiError("x", status)).retryable, false,
      `HTTP ${status} will be refused identically on a retry`);
  }
  assert.equal(readWhatIfError(apiError("x", 0, "timeout")).retryable, true);
  assert.equal(readWhatIfError(apiError("x", 0, "network_error")).retryable, true);
});
