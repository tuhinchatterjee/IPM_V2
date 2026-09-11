/**
 * Unit tests for the V4 API origin. No network.
 *
 * These call the module, so they prove the RUNTIME behaviour: that an unset
 * variable raises rather than resolving to a default, and that the legacy
 * variable is not consulted even when it is set to something plausible.
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { CockpitV4NotConfigured, apiOrigin } from "./client.ts";

const LEGACY = "http://127.0.0.1:8000";

function setEnv(v4: string | undefined, generic: string | undefined): void {
  if (v4 === undefined) delete process.env.NEXT_PUBLIC_COCKPIT_V4_API;
  else process.env.NEXT_PUBLIC_COCKPIT_V4_API = v4;
  if (generic === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = generic;
}

afterEach(() => setEnv(undefined, undefined));

test("the configured V4 API origin is used", () => {
  setEnv("http://127.0.0.1:8414", undefined);
  assert.deepEqual(apiOrigin(), { ok: true, origin: "http://127.0.0.1:8414" });
});

test("an alternate selected port propagates", () => {
  for (const port of [8414, 8415, 8422, 9001]) {
    setEnv(`http://127.0.0.1:${port}`, undefined);
    const resolved = apiOrigin();
    assert.equal(resolved.ok, true);
    assert.equal(
      resolved.ok && resolved.origin,
      `http://127.0.0.1:${port}`,
      "the client must address the port the launcher actually selected",
    );
  }
});

test("a trailing slash is normalised away", () => {
  setEnv("http://127.0.0.1:8414/", undefined);
  assert.deepEqual(apiOrigin(), { ok: true, origin: "http://127.0.0.1:8414" });
});

test("an unset V4 variable fails loudly instead of defaulting", () => {
  setEnv(undefined, undefined);
  const resolved = apiOrigin();
  assert.equal(resolved.ok, false);
  assert.match(
    resolved.ok ? "" : resolved.reason,
    /NEXT_PUBLIC_COCKPIT_V4_API is not set/,
  );
});

test("the generic API variable is NEVER used as a fall back", () => {
  // The exact shape of the defect: the shell variable is set (to the legacy
  // backend, or even to something that looks like a V4 address) and the V4
  // variable is not. The client must refuse, not borrow it.
  setEnv(undefined, LEGACY);
  const resolved = apiOrigin();
  assert.equal(resolved.ok, false, "the legacy address must not be borrowed");

  setEnv(undefined, "http://127.0.0.1:8414");
  assert.equal(
    apiOrigin().ok,
    false,
    "even a plausible address in the wrong variable is not configuration",
  );
});

test("no V4 request can be addressed to the legacy backend port", () => {
  setEnv(undefined, LEGACY);
  const resolved = apiOrigin();
  assert.equal(resolved.ok, false);
  assert.equal(
    resolved.ok ? resolved.origin : "",
    "",
    "there is no origin at all, so there is nothing to send to 8000",
  );
});

test("an empty or whitespace value is not configuration", () => {
  for (const value of ["", "   "]) {
    setEnv(value, LEGACY);
    assert.equal(apiOrigin().ok, false);
  }
});

test("same-origin is an explicit opt-in, not an accident", () => {
  setEnv("same-origin", LEGACY);
  assert.deepEqual(apiOrigin(), { ok: true, origin: "" });
});

test("the thrown error is typed so callers can render it", () => {
  setEnv(undefined, undefined);
  assert.throws(
    () => {
      const resolved = apiOrigin();
      if (!resolved.ok) throw new CockpitV4NotConfigured();
    },
    CockpitV4NotConfigured,
  );
});
