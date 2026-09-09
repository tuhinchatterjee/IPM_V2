import assert from "node:assert/strict";
import { test } from "node:test";

import {
  analysisAnchor,
  asSourceType,
  facilityAnchor,
  fromBorrower,
  fromCockpit,
  fromDataset,
  fromInvestigation,
  fromLens,
  fromProject,
  fromSavedAnalysis,
  fromTraceNode,
  INDEX_OF,
  linkBack,
  readReturn,
  turnAnchor,
} from "../return-context.ts";

/**
 * §5 lists ten navigation paths and calls broken Back behaviour release
 * blocking. Each of them is one source builder and one read-back, and both
 * halves are asserted here rather than by clicking around the running product —
 * a Back button that returns you to the wrong screen is exactly the kind of
 * defect that survives a demo and is found by a user.
 */

/* ------------------------------------------------------------- the sources */

test("an investigation carries the exact turn as its anchor", () => {
  const from = fromInvestigation(7, "Contracting deterioration", 4);
  assert.equal(from.href, "/investigations/7#turn-4");
  assert.equal(from.label, "Contracting deterioration");
  assert.equal(from.type, "investigation");
});

test("turn zero is an anchor, not a missing one", () => {
  // The first turn in a thread has sequence 0, and `if (!sequence)` would drop
  // it — returning a reader to the top of the thread they were already at the
  // top of, which looks like nothing happened.
  assert.equal(fromInvestigation(7, "x", 0).href, "/investigations/7#turn-0");
});

test("an investigation without a turn returns to the thread itself", () => {
  assert.equal(fromInvestigation(7, "x").href, "/investigations/7");
  assert.equal(fromInvestigation(7, "x", null).href, "/investigations/7");
});

test("an untitled investigation still names something in the Back control", () => {
  assert.equal(fromInvestigation(7, "").label, "this investigation");
});

test("a project carries the tab that was open", () => {
  assert.equal(
    fromProject(4, "Contracting review", "analyses").href,
    "/projects/4?tab=analyses",
  );
  assert.equal(fromProject(4, "Contracting review").href, "/projects/4");
});

test("a saved analysis returns to its row in the list", () => {
  // There is no per-saved-analysis page: the row IS where the reader was.
  const from = fromSavedAnalysis(91, "Stage 2 by sector");
  assert.equal(from.href, `/analyses#${analysisAnchor(91)}`);
  assert.equal(from.type, "analysis");
});

test("the built-in CRO lens keeps its own route", () => {
  assert.equal(fromLens("cro", "CRO Lens").href, "/lenses/cro");
  assert.equal(fromLens("12", "Watchlist").href, "/lenses/12");
});

test("a borrower carries both the selection and the anchor", () => {
  const from = fromBorrower("ACC-100482", "Al Rajhi Contracting");
  assert.equal(
    from.href,
    "/early-warning?facility=ACC-100482#facility-ACC-100482",
  );
  assert.equal(from.label, "Al Rajhi Contracting");
  assert.equal(from.type, "borrower");
});

test("a dataset carries the period being read", () => {
  assert.equal(
    fromDataset("ecl_facility", "2025Q2").href,
    "/data-builder/dataset/ecl_facility?period=2025Q2",
  );
  assert.equal(fromDataset("ecl_facility").href, "/data-builder/dataset/ecl_facility");
});

test("a trace node carries the mode and the selected step", () => {
  assert.equal(
    fromTraceNode(57, "lineage", "join_1").href,
    "/trace/57?mode=lineage&node=join_1",
  );
  assert.equal(fromTraceNode(57).href, "/trace/57");
  assert.equal(fromTraceNode(57, "audit").href, "/trace/57?mode=audit");
});

test("every source type has an index to fall back to", () => {
  for (const [type, index] of Object.entries(INDEX_OF)) {
    assert.equal(index.href.startsWith("/"), true, type);
    assert.notEqual(index.label, "", type);
  }
});

/* ---------------------------------------------------------------- the link */

test("a link carries where it came from, what it says and what kind it is", () => {
  const href = linkBack("/trace/57", fromInvestigation(7, "Contracting", 4));
  const params = new URL(href, "https://example.test").searchParams;
  assert.equal(params.get("returnTo"), "/investigations/7#turn-4");
  assert.equal(params.get("returnLabel"), "Contracting");
  assert.equal(params.get("returnType"), "investigation");
});

test("a link that already has a query string keeps it", () => {
  const href = linkBack("/trace/57?version=3", fromCockpit());
  assert.match(href, /^\/trace\/57\?version=3&returnTo=/);
});

test("a source href with its own query and anchor survives the round trip", () => {
  const from = fromBorrower("ACC-1", "Borrower & Co");
  const href = linkBack("/investigations/9", from);
  const params = new URL(href, "https://example.test").searchParams;
  assert.equal(params.get("returnTo"), from.href);
  assert.equal(params.get("returnLabel"), "Borrower & Co");
});

/* ----------------------------------------------------------- the read-back */

test("a carried context is honoured", () => {
  const back = readReturn("/projects/4?tab=analyses", "Contracting review", "project", {
    href: "/investigations",
    label: "Investigations",
  });
  assert.equal(back.href, "/projects/4?tab=analyses");
  assert.equal(back.label, "Contracting review");
  assert.equal(back.type, "project");
});

test("nothing carried falls back to the caller's own default", () => {
  const back = readReturn(null, null, null, {
    href: "/investigations",
    label: "Investigations",
  });
  assert.equal(back.href, "/investigations");
  assert.equal(back.label, "Investigations");
});

test("an off-site return is refused, not followed", () => {
  // `returnTo` arrives in a query string, so trusting it would let any link
  // anywhere turn a Back button into an off-site redirect.
  for (const hostile of [
    "//evil.example/steal",
    "https://evil.example",
    "javascript:alert(1)",
  ]) {
    const back = readReturn(hostile, "Back", "project", {
      href: "/trace",
      label: "Trace & Lineage",
    });
    assert.equal(back.href, "/trace", hostile);
  }
});

test("a carried context with no label still says something", () => {
  assert.equal(
    readReturn("/projects/4", "", null, { href: "/", label: "Cockpit" }).label,
    "Back",
  );
});

test("an unknown source type is recorded as unknown rather than trusted", () => {
  assert.equal(asSourceType("investigation"), "investigation");
  assert.equal(asSourceType("../../etc/passwd"), "unknown");
  assert.equal(asSourceType(null), "unknown");
});

/* ------------------------------------------------------------- the anchors */

test("anchors are stable and unique per object", () => {
  assert.equal(turnAnchor(4), "turn-4");
  assert.equal(analysisAnchor(91), "analysis-91");
  assert.equal(facilityAnchor("ACC-1"), "facility-ACC-1");
  assert.notEqual(turnAnchor(4), analysisAnchor(4));
});

test("the Cockpit is the return context a global investigation starts from", () => {
  assert.equal(fromCockpit().type, "cockpit");
  assert.equal(fromCockpit().href, "/");
});
