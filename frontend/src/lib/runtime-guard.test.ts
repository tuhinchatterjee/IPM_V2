/**
 * Unit tests for the runtime guard in the generic API client. No network.
 *
 * The rule: in a Cockpit V4 runtime, a path the V4 API does not serve is not
 * requested at all. Not translated into a V4 call, not caught after a 404 —
 * never sent.
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { cockpitV4Runtime, servedByCurrentRuntime } from "./runtime.ts";

const LEGACY_PATHS = [
  "/investigations",
  "/investigations/12",
  "/agentic/officer",
  "/ask/mode",
  "/ask/briefing",
  "/ask/suggestions",
  "/ask/cockpit-v2/diagnostics",
  "/cockpit/diagnostics",
  "/demo",
  "/auth/me",
  "/ai/status",
  "/workspace/notifications",
];

function v4Mode(on: boolean): void {
  if (on) process.env.NEXT_PUBLIC_COCKPIT_V4_API = "http://127.0.0.1:8414";
  else delete process.env.NEXT_PUBLIC_COCKPIT_V4_API;
}

afterEach(() => v4Mode(false));

test("outside a V4 runtime every path is served as before", () => {
  v4Mode(false);
  for (const path of LEGACY_PATHS) {
    assert.equal(
      servedByCurrentRuntime(path),
      true,
      `${path} must be unaffected in a normal CreditProbe instance`,
    );
  }
});

test("inside a V4 runtime the legacy paths are not requested", () => {
  v4Mode(true);
  for (const path of LEGACY_PATHS) {
    assert.equal(
      servedByCurrentRuntime(path),
      false,
      `${path} would 404 against the V4 API; it must not be sent`,
    );
  }
});

test("inside a V4 runtime the V4 paths are served", () => {
  v4Mode(true);
  for (const path of [
    "/health",
    "/cockpit-v4/runs",
    "/cockpit-v4/runs/run-abc/events",
    "/cockpit-v4/diagnostics",
  ]) {
    assert.equal(servedByCurrentRuntime(path), true, `${path} is a V4 path`);
  }
});

test("the runtime flag reads only the Cockpit variable", () => {
  v4Mode(false);
  process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:8414";
  assert.equal(cockpitV4Runtime(), false,
    "pointing the shell at a V4 API does not make this a V4 build");
  delete process.env.NEXT_PUBLIC_API_URL;
  v4Mode(true);
  assert.equal(cockpitV4Runtime(), true);
});

test("the guard decides on the path, never on a response", () => {
  // Stated as a test because the distinction is the requirement: catching a
  // 404 afterwards still makes the request, still fills the API log, and
  // still shows the widget an error.
  v4Mode(true);
  assert.equal(servedByCurrentRuntime("/investigations"), false);
  assert.equal(servedByCurrentRuntime("/cockpit-v4/runs"), true);
});
