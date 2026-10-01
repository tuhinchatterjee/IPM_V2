import assert from "node:assert/strict";
import test from "node:test";

import { METHOD_LABEL, methodLabel } from "./method-labels.ts";

test("MLB01 every method is shown by its governed name", () => {
  assert.equal(methodLabel("delta"), "Method 1 — Delta");
  assert.equal(methodLabel("ml"), "Method 2 — ML emulator");
  assert.equal(methodLabel("user_defined"), "Method 3 — User-defined");
  assert.equal(Object.keys(METHOD_LABEL).length, 3);
  assert.equal(methodLabel("other"), "other");
});
