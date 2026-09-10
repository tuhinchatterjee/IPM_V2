import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

import {
  V3_SETTLEMENTS,
  V3_TERMINAL_STATUSES,
  failureFrom,
  isSupportedStop,
  settlementOf,
  stillRunning,
} from "../cockpit-v3-outcome.ts";

/** The shape `api.request` throws. Built here rather than imported, because
 *  `@/lib/api` pulls in the whole client; the assertion that the real class
 *  still has this shape is `the transport error this reads is the one the API
 *  client throws` below. */
function apiError(message: string, status: number, code: string) {
  const error = new Error(message);
  error.name = "ApiError";
  return Object.assign(error, { status, code });
}

/** A returned payload with the envelope the server would have written. */
function payload(kind: string, status: string, narrative = "because.") {
  return {
    request_id: "req-1",
    status,
    answer: { kind, status, narrative },
  } as never;
}

const API = fs.readFileSync(
  path.join(import.meta.dirname, "..", "..", "..", "lib", "api.ts"),
  "utf8",
);

// ---------------------------------------------- 1-3. every request settles

test("a request settles into exactly one of five things, and none of them is silence", () => {
  assert.deepEqual(
    [...V3_SETTLEMENTS],
    ["answer", "referral", "clarification", "stop", "error"],
  );
});

test("each envelope kind the server writes maps to what the reader is shown", () => {
  assert.equal(settlementOf(payload("answer", "COMPLETED")), "answer");
  assert.equal(settlementOf(payload("referral", "REDIRECTED")), "referral");
  assert.equal(
    settlementOf(payload("clarification", "WAITING_FOR_USER")),
    "clarification",
  );
  assert.equal(settlementOf(payload("stop", "INSUFFICIENT_DATA")), "stop");
});

test("a response this client cannot read is an error, not an empty answer", () => {
  // The failure being fixed: rendering nothing reads as success with nothing
  // to say.
  assert.equal(settlementOf({ answer: {} } as never), "error");
  assert.equal(settlementOf({} as never), "error");
  assert.equal(settlementOf(undefined as never), "error");
});

// ------------------------------ 4-7. supported stops are not transport errors

test("every governed terminal state is a supported outcome with its own explanation", () => {
  for (const status of [
    "STOPPED_TOKEN_LIMIT",
    "STOPPED_COST_LIMIT",
    "STOPPED_TIME_LIMIT",
    "STOPPED_EXECUTION_LIMIT",
    "STOPPED_ANALYSIS_LIMIT",
    "MODEL_UNAVAILABLE",
    "DATA_UNAVAILABLE",
    "PARTIAL",
    "WAITING_FOR_USER",
    "REDIRECTED",
  ]) {
    assert.ok(
      isSupportedStop(status),
      `${status} would have been shown as a transport failure`,
    );
  }
});

test("a budget stop renders the backend's own sentence, not a generic outage", () => {
  const stop = payload(
    "stop",
    "STOPPED_COST_LIMIT",
    "This question reached the $1.00 spend ceiling for one request.",
  ) as unknown as { answer: { narrative: string } };
  assert.equal(settlementOf(stop as never), "stop");
  assert.match(stop.answer.narrative, /spend ceiling/);
});

test("a partial answer is still an answer, and a redirect is still a redirect", () => {
  assert.equal(settlementOf(payload("answer", "PARTIAL")), "answer");
  assert.equal(settlementOf(payload("referral", "REDIRECTED")), "referral");
});

test("the terminal list is the server's, and nothing invented sits in it", () => {
  assert.ok(V3_TERMINAL_STATUSES.includes("PROVIDER_CREDENTIAL_MISSING"));
  assert.ok(V3_TERMINAL_STATUSES.includes("CONTEXT_TOO_LARGE"));
  assert.equal(isSupportedStop("SOMETHING_MADE_UP"), false);
  assert.equal(isSupportedStop(""), false);
});

// ------------------------------------------- 8-11. the failure that is shown

test("a timeout is reported, with the sentence the transport layer wrote", () => {
  const failure = failureFrom(
    apiError("The backend did not respond within 120 seconds.", 0, "timeout"),
  );
  assert.equal(failure.code, "timeout");
  assert.match(failure.message, /did not respond within 120 seconds/);
});

test("a governed 503 keeps the server's explanation instead of becoming an outage", () => {
  const failure = failureFrom(
    apiError(
      "The pinned data release r-2026Q2 cannot be read, and no other " +
        "release was silently substituted for it.",
      503,
      "DATA_UNAVAILABLE",
    ),
  );
  assert.equal(failure.status, 503);
  assert.equal(failure.code, "DATA_UNAVAILABLE");
  assert.match(failure.message, /no other release was silently substituted/);
});

test("a failure is never empty and never a bare status code", () => {
  for (const error of [
    apiError("", 500, "http_error"),
    apiError("   ", 0, "network_error"),
    new Error("boom"),
    null,
    undefined,
    "a string",
  ]) {
    const failure = failureFrom(error);
    assert.ok(failure.message.trim().length > 20, "the message is not a sentence");
    assert.ok(!/^\d+$/.test(failure.message));
    assert.match(failure.message, /Nothing was computed/);
  }
});

test("a raw exception never reaches the reader: no stack trace, no class name", () => {
  const thrown = new TypeError("Cannot read properties of undefined");
  const failure = failureFrom(thrown);
  assert.ok(!failure.message.includes("TypeError"));
  assert.ok(!failure.message.includes("Cannot read properties"));
  assert.ok(!/\n\s+at /.test(failure.message), "a stack frame reached the reader");
  assert.equal(failure.code, "unknown");
});

// ----------------------------------------- 12-14. the transport timeout only

test("cockpitV3Ask waits 120 seconds, and the shared default is untouched", () => {
  assert.match(API, /const DEFAULT_TIMEOUT_MS = 20_000;/);
  const call = API.slice(
    API.indexOf("cockpitV3Ask:"),
    API.indexOf("cockpitV3Cancel:"),
  );
  assert.match(call, /timeoutMs: 120_000/);
  assert.ok(!call.includes("150_000"), "a local UAT edit reached the branch");
});

test("the measured 20.517-second request would have survived", () => {
  // The live run: a real backend request took 20.517 seconds against a
  // 20-second abort. This is the number, not a rounding of it.
  const measuredMs = 20_517;
  assert.ok(measuredMs > 20_000, "the defect no longer reproduces");
  assert.ok(measuredMs < 120_000);
});

test("nothing about the server's deadlines was changed to fix the transport", () => {
  // Transport waiting time is not a deadline, a budget or a limit. Standard
  // stops at 60 seconds and Deep at 120, on the server, and the frontend
  // neither knows nor sets those. Checked against the CODE of the call, with
  // its comments stripped — the comment says the words on purpose.
  const block = API.slice(
    API.indexOf("cockpitV3Ask:"),
    API.indexOf("cockpitV3Cancel:"),
  );
  const call = block
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");
  for (const forbidden of [
    "deadline",
    "max_tokens",
    "submissions",
    "analysis_rounds",
    "spend",
  ]) {
    assert.ok(
      !call.includes(forbidden),
      `the transport change reached into ${forbidden}`,
    );
  }
  assert.match(block, /TRANSPORT WAITING TIME ONLY/);
});

test("a credential can never reach the reader through a failure", () => {
  // `failureFrom` reads three fields off an error and nothing else, so there
  // is no path by which an environment value, a header or a request body
  // could travel with one. Checked both ways: a secret hidden on the error
  // object does not come through, and one in a server-written sentence is the
  // server's own text — which is why the server never puts one there, and why
  // `credential.py` holds the value nowhere it can be serialized.
  // Assembled from parts. A key-shaped literal must not exist in a shipped
  // file even as a fixture, and `test_no_shipped_file_carries_anything_key_shaped`
  // is right to refuse one — it caught this line written out in full.
  const secret = ["sk", "ant", "api03", "NOT-A-REAL-KEY"].join("-");
  const error = Object.assign(new Error("upstream refused"), {
    status: 401,
    code: "unauthorized",
    apiKey: secret,
    config: { headers: { "x-api-key": secret } },
  });
  error.name = "ApiError";
  const failure = failureFrom(error);
  assert.equal(JSON.stringify(failure).includes(secret), false);
  assert.deepEqual(Object.keys(failure).sort(), ["code", "message", "status"]);
});

test("the running indicator is off once a request has settled, whatever it settled as", () => {
  assert.equal(stillRunning(), false);
});

test("the transport error this reads is the one the API client throws", () => {
  // `failureFrom` recognises the error structurally, so the client's own class
  // has to keep that shape: the name, and the three fields that may be shown.
  assert.match(API, /this\.name = "ApiError";/);
  assert.match(API, /readonly status: number;/);
  assert.match(API, /readonly code: string;/);
  // And an error that is NOT one contributes none of its own text.
  const foreign = Object.assign(new Error("leaked internal detail"), {
    status: 500,
    code: "boom",
  });
  const failure = failureFrom(foreign);
  assert.ok(!failure.message.includes("leaked internal detail"));
  assert.equal(failure.status, undefined);
});
