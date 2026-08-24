import assert from "node:assert/strict";
import { test } from "node:test";

import { domainHref, isInternalPath, withReturnTo } from "../links.ts";

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

test("a domain name containing a slash round-trips through its URL", () => {
  const name = "Core Portfolio / Facility";
  const href = domainHref(name);
  assert.equal(href, "/data-builder/domain/Core%20Portfolio%20/%20Facility");

  // What the page does with the segments it is handed.
  const segments = href.replace("/data-builder/domain/", "").split("/");
  assert.equal(segments.map(decodeURIComponent).join("/"), name);
});

test("a domain name with no slash still produces one segment", () => {
  assert.equal(domainHref("Macroeconomic"), "/data-builder/domain/Macroeconomic");
});
