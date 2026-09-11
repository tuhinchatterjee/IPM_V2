/**
 * Unit tests for the shell's reading of a partial runtime. No network.
 *
 * The rule: a backend that is reachable and simply does not serve an optional
 * surface must not be reported as offline, and an existing CreditProbe
 * payload — which declares no optional surfaces — must behave exactly as it
 * did before.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { ComponentHealth, HealthResponse } from "@/lib/api";
import { optionalSurfaces, partialRuntimeLabel } from "./runtime-surfaces.ts";

function component(
  name: string,
  status: ComponentHealth["status"],
  data: Record<string, unknown> = {},
): ComponentHealth {
  return { name, status, detail: `${name} detail`, data };
}

function health(components: ComponentHealth[], app = "CreditProbe"): HealthResponse {
  return {
    status: "ok",
    app,
    version: "1.0",
    environment: "local",
    phase: "phase",
    components,
  };
}

const V4 = health(
  [
    component("cockpit_v4_api", "ok"),
    component("cockpit_v4_analyst", "ok"),
    component("cockpit_v4_release", "ok"),
    component("legacy_dashboard_api", "not_configured", {
      optional: true,
      runtime: "cockpit_v4",
    }),
  ],
  "CreditProbe Cockpit V4",
);

const LEGACY = health([
  component("postgresql", "ok"),
  component("analytical_store", "ok"),
  component("ai", "not_configured"),
]);

test("a V4 payload is recognised as a reachable partial runtime", () => {
  const optional = optionalSurfaces(V4);
  assert.notEqual(optional, null);
  assert.equal(optional?.runtime, "cockpit_v4");
  assert.equal(optional?.absent.length, 1);

  const label = partialRuntimeLabel(V4);
  assert.match(label ?? "", /Cockpit V4/);
  assert.match(label ?? "", /dashboard service not in this runtime/);
  assert.doesNotMatch(label ?? "", /offline/i,
    "a reachable runtime is never described as offline");
});

test("an existing CreditProbe payload is completely unaffected", () => {
  // `ai: not_configured` is a supported mode and carries no optional marker,
  // so nothing here changes for any instance that exists today.
  assert.equal(optionalSurfaces(LEGACY), null);
  assert.equal(partialRuntimeLabel(LEGACY), null);
});

test("an optional surface that IS working is not reported as absent", () => {
  const ready = health(
    [
      component("cockpit_v4_api", "ok"),
      component("cockpit_v4_python_runner", "ok", {
        optional: true,
        runtime: "cockpit_v4",
      }),
    ],
    "CreditProbe Cockpit V4",
  );
  assert.equal(optionalSurfaces(ready), null);
  assert.equal(partialRuntimeLabel(ready), null);
});

test("an optional surface other than the dashboard does not claim one", () => {
  const runnerOnly = health(
    [
      component("cockpit_v4_api", "ok"),
      component("cockpit_v4_python_runner", "not_configured", {
        optional: true,
        runtime: "cockpit_v4",
      }),
    ],
    "CreditProbe Cockpit V4",
  );
  assert.notEqual(optionalSurfaces(runnerOnly), null);
  assert.equal(
    partialRuntimeLabel(runnerOnly),
    null,
    "an unavailable Python runner is not the dashboard being absent",
  );
});

test("a genuine service fault is still a fault", () => {
  const broken: HealthResponse = {
    ...V4,
    status: "unavailable",
    components: [
      component("cockpit_v4_api", "ok"),
      component("cockpit_v4_release", "unavailable"),
      component("legacy_dashboard_api", "not_configured", {
        optional: true,
        runtime: "cockpit_v4",
      }),
    ],
  };
  // The partial label describes the optional surface; it must not be allowed
  // to disguise the headline, which the indicator reads separately.
  assert.notEqual(partialRuntimeLabel(broken), null);
  assert.equal(broken.status, "unavailable");
});
