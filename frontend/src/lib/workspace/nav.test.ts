import { test } from "node:test";
import assert from "node:assert/strict";

import { backLabel, safeBack, withBack } from "./nav.ts";

test("NAV01 safeBack keeps same-origin paths only", () => {
  assert.equal(safeBack("/issues/iss-1?driver=Hotels"), "/issues/iss-1?driver=Hotels");
  for (const bad of ["https://evil.example/x", "//evil.example", "javascript:alert(1)", "issues/x", "/\\evil", "", null, undefined]) {
    assert.equal(safeBack(bad as string), "", String(bad));
  }
  assert.equal(safeBack(`/${"a".repeat(7000)}`), "");
  assert.equal(safeBack(`/x?back=${"a".repeat(3000)}`).length, 3008, "a nested chain of origins is kept");
});

test("NAV02 withBack appends an encoded origin and never an unsafe one", () => {
  assert.equal(withBack("/what-if?cohort=coh-1", "/issues/iss-1?driver=A B"), "/what-if?cohort=coh-1&back=%2Fissues%2Fiss-1%3Fdriver%3DA%20B");
  assert.equal(withBack("/scenarios", "/x"), "/scenarios?back=%2Fx");
  assert.equal(withBack("/scenarios", "https://evil"), "/scenarios");
});

test("NAV03 backLabel names the origin module", () => {
  assert.equal(backLabel("/"), "Cockpit");
  assert.equal(backLabel("/issues/iss-1"), "the issue");
  assert.equal(backLabel("/what-if?cohort=x"), "What-If");
  assert.equal(backLabel("/what-if/result/res-1"), "the result");
  assert.equal(backLabel("/scenarios?domain=retail"), "the Scenario Library");
  assert.equal(backLabel("/lenses/lens-02?x=1"), "the Lens");
  assert.equal(backLabel("/monitoring?alert=a"), "the Monitoring Centre");
});
