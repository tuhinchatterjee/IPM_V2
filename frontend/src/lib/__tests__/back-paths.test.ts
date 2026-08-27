import assert from "node:assert/strict";
import { test } from "node:test";

import { stepHref } from "../analysis-links.ts";
import {
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
} from "../return-context.ts";

/**
 * §58: every Back path in §5, walked end to end.
 *
 * Each test follows a real journey: build the link the way the screen builds
 * it, read the context back the way the destination reads it, and assert the
 * reader lands where they came from. The unit behaviour of each builder is
 * asserted in return-context.test.ts; what is asserted here is the JOURNEY,
 * because that is what §5 calls release blocking and what a unit test of one
 * function cannot catch.
 */

/** Read the return context out of a built link, as the destination does. */
function back(href: string) {
  const params = new URL(href, "https://x.test").searchParams;
  return readReturn(
    params.get("returnTo"),
    params.get("returnLabel"),
    params.get("returnType"),
    { href: "/", label: "Cockpit" },
  );
}

test("Cockpit → Investigation → Trace → back to the exact turn", () => {
  const thread = linkBack("/investigations/7", fromCockpit());
  assert.equal(back(thread).href, "/");

  const trace = linkBack("/trace/412", fromInvestigation(7, "Contracting", 4));
  assert.equal(back(trace).href, "/investigations/7#turn-4");
  assert.equal(back(trace).label, "Contracting");
});

test("Cockpit → Investigation → Method → back to the exact turn", () => {
  const method = stepHref("stage_migration", "certified", 412);
  assert.equal(method, "/engine-builder/stage_migration");
  const link = linkBack(method!, fromInvestigation(7, "Contracting", 4));
  assert.equal(back(link).href, "/investigations/7#turn-4");
});

test("Project → Project Investigation → Trace → back to that investigation, then to the project", () => {
  const thread = linkBack(
    "/investigations/12",
    fromProject(4, "Contracting review", "investigations"),
  );
  assert.equal(back(thread).href, "/projects/4?tab=investigations");

  const trace = linkBack("/trace/91", fromInvestigation(12, "Q2 deterioration", 2));
  assert.equal(back(trace).href, "/investigations/12#turn-2");
});

test("Saved Analysis → Trace → back to the saved analysis", () => {
  const trace = linkBack("/trace/55", fromSavedAnalysis(91, "Stage 2 by sector"));
  assert.equal(back(trace).href, "/analyses#analysis-91");
  assert.equal(back(trace).type, "analysis");
});

test("Lens → Analysis → Trace → back to the lens", () => {
  const trace = linkBack("/trace/77", fromLens("12", "Watchlist"));
  assert.equal(back(trace).href, "/lenses/12");
  assert.equal(back(trace).label, "Watchlist");
});

test("Early Warning → Borrower → Investigation → back to that borrower", () => {
  // A signal score is a fitted model rather than a governed engine run, so the
  // route to a Trace is through the investigation the borrower opens.
  const ask = linkBack(
    "/?focus=ask&q=What%20changed",
    fromBorrower("ACC-1", "Al Rajhi Contracting"),
  );
  const context = back(ask);
  assert.equal(context.href, "/early-warning?facility=ACC-1#facility-ACC-1");
  assert.equal(context.label, "Al Rajhi Contracting");
});

test("Data Builder → Dataset → Relationship map → back to the dataset and period", () => {
  const map = linkBack(
    "/data-builder/relationships",
    fromDataset("ecl_facility", "2025Q2"),
  );
  assert.equal(
    back(map).href,
    "/data-builder/dataset/ecl_facility?period=2025Q2",
  );
});

test("Trace → Open dataset in Data Builder → back to the same node in the same mode", () => {
  const dataset = linkBack(
    "/data-builder/dataset/ecl_facility",
    fromTraceNode(57, "lineage", "join_1"),
  );
  assert.equal(back(dataset).href, "/trace/57?mode=lineage&node=join_1");
});

test("a dynamic Analysis Run links to its run, not to a Method page that does not exist", () => {
  // §59: "dynamic run never opens Method route".
  const target = stepHref("dynamic_analysis", "dynamic", 412);
  const link = linkBack(target!, fromInvestigation(7, "Contracting", 4));
  assert.match(link, /^\/trace\/412\?/);
  assert.equal(back(link).href, "/investigations/7#turn-4");
});

test("a source that no longer exists falls back rather than stranding the reader", () => {
  // §58: "deleted/missing source fallback". A Back with nothing usable in it
  // lands on the caller's own index, which is always a real screen.
  const stranded = readReturn(null, null, "project", INDEX_OF.investigation);
  assert.equal(stranded.href, "/investigations");
  assert.equal(stranded.label, "Investigations");

  // And a hostile one is refused the same way rather than followed.
  const hostile = readReturn("https://evil.example", "Back", "project",
                             INDEX_OF.project);
  assert.equal(hostile.href, "/projects");
});

test("every source type's fallback index is a real in-product path", () => {
  for (const [type, index] of Object.entries(INDEX_OF)) {
    assert.equal(index.href.startsWith("/"), true, type);
    assert.equal(index.href.includes(":"), false, type);
  }
});

test("a return context survives being carried through two hops", () => {
  // Cockpit → Investigation → Trace: the middle hop must not eat the context
  // it was given, and the last hop must carry its own.
  const thread = linkBack("/investigations/7", fromCockpit());
  assert.equal(back(thread).type, "cockpit");
  const trace = linkBack("/trace/1", fromInvestigation(7, "Thread", 0));
  assert.equal(back(trace).href, "/investigations/7#turn-0");
});
