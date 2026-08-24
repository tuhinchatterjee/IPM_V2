import assert from "node:assert/strict";
import { test } from "node:test";

import { isInternalPath, withReturnTo } from "../links.ts";

test("return context survives a link that already has a query string", () => {
  const href = withReturnTo("/trace/12?version=3", "/investigations/7#turn-4", "Stage 2 review");
  assert.match(href, /^\/trace\/12\?version=3&returnTo=/);
  const params = new URL(href, "https://example.test").searchParams;
  assert.equal(params.get("returnTo"), "/investigations/7#turn-4");
  assert.equal(params.get("returnLabel"), "Stage 2 review");
});

test("the anchor identifying one turn is carried intact", () => {
  const href = withReturnTo("/engine-builder/ecl_movement", "/investigations/7#turn-4", "x");
  const params = new URL(href, "https://example.test").searchParams;
  assert.equal(params.get("returnTo"), "/investigations/7#turn-4");
});

test("a label with an ampersand does not break the query string", () => {
  const href = withReturnTo("/trace/1", "/projects/3", "Trace & Lineage");
  const params = new URL(href, "https://example.test").searchParams;
  assert.equal(params.get("returnLabel"), "Trace & Lineage");
  assert.equal(params.get("returnTo"), "/projects/3");
});

test("only same-origin paths are accepted as a destination", () => {
  assert.equal(isInternalPath("/investigations/7"), true);
  assert.equal(isInternalPath("/investigations/7#turn-2"), true);
  assert.equal(isInternalPath("//evil.example/steal"), false);
  assert.equal(isInternalPath("https://evil.example"), false);
  assert.equal(isInternalPath("javascript:alert(1)"), false);
  assert.equal(isInternalPath("investigations/7"), false);
  assert.equal(isInternalPath(""), false);
});
