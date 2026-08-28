import assert from "node:assert/strict";
import { test } from "node:test";

import { compare, summarise, type ComparableVersion } from "../compare.ts";

/**
 * §49's version comparison.
 *
 * A diff is easy to get subtly wrong and easy to assert, which is exactly why
 * it lives outside the component.
 */

function version(
  n: number,
  nodes: ComparableVersion["nodes"],
  extra: Partial<ComparableVersion> = {},
): ComparableVersion {
  return { version: n, nodes, ...extra };
}

test("a step that appeared is reported as added", () => {
  const found = compare(
    version(1, [{ id: "source", status: "ok" }]),
    version(2, [
      { id: "source", status: "ok" },
      { id: "scoped", status: "ok", label: "Restrict to Contracting" },
    ]),
  );
  const added = found.changes.filter((c) => c.kind === "added");
  assert.equal(added.length, 1);
  assert.equal(added[0].id, "scoped");
  assert.equal(added[0].label, "Restrict to Contracting");
});

test("a step that disappeared is reported as removed", () => {
  const found = compare(
    version(1, [
      { id: "source", status: "ok" },
      { id: "scoped", status: "ok" },
    ]),
    version(2, [{ id: "source", status: "ok" }]),
  );
  assert.deepEqual(
    found.changes.filter((c) => c.kind === "removed").map((c) => c.id),
    ["scoped"],
  );
});

test("a row count that moved is reported with both numbers", () => {
  const found = compare(
    version(1, [{ id: "scoped", rows_out: 16346 }]),
    version(2, [{ id: "scoped", rows_out: 2189 }]),
  );
  const moved = found.changes.find((c) => c.kind === "rows");
  assert.ok(moved);
  assert.equal(moved.before, "16,346");
  assert.equal(moved.after, "2,189");
});

test("a step whose status changed is reported", () => {
  const found = compare(
    version(1, [{ id: "join", status: "ok" }]),
    version(2, [{ id: "join", status: "warning" }]),
  );
  const change = found.changes.find((c) => c.kind === "status");
  assert.ok(change);
  assert.equal(change.before, "ok");
  assert.equal(change.after, "warning");
});

test("a relabelled step is a change a reviewer needs to see", () => {
  // Somebody who approved the old wording did not approve the new one.
  const found = compare(
    version(1, [{ id: "grouped", label: "Total by sector" }]),
    version(2, [{ id: "grouped", label: "Average by sector" }]),
  );
  const change = found.changes.find((c) => c.kind === "label");
  assert.ok(change);
  assert.equal(change.before, "Total by sector");
  assert.equal(change.after, "Average by sector");
});

test("an unchanged step produces no noise", () => {
  const found = compare(
    version(1, [{ id: "source", status: "ok", rows_out: 10, label: "Read" }]),
    version(2, [{ id: "source", status: "ok", rows_out: 10, label: "Read" }]),
  );
  assert.deepEqual(found.changes, []);
});

test("the arguments are not silently swapped", () => {
  // Sorting them here would reverse every before and after in the panel.
  const found = compare(
    version(3, [{ id: "a", rows_out: 5 }]),
    version(2, [{ id: "a", rows_out: 9 }]),
  );
  assert.equal(found.from, 3);
  assert.equal(found.to, 2);
  assert.equal(found.changes[0].before, "5");
});

test("two versions that computed the same thing say so", () => {
  const found = compare(
    version(1, [{ id: "a", status: "ok" }], { answer: "EAD is 125,259 USD mn." }),
    version(2, [{ id: "a", status: "ok" }], { answer: "EAD is 125,259 USD mn." }),
  );
  assert.equal(found.sameAnswer, true);
  assert.match(summarise(found), /same answer/);
});

test("the same steps with a different answer is called out", () => {
  const found = compare(
    version(1, [{ id: "a", status: "ok" }], { answer: "125,259" }),
    version(2, [{ id: "a", status: "ok" }], { answer: "18,475" }),
  );
  assert.equal(found.sameAnswer, false);
  assert.match(summarise(found), /the answer differs/);
});

test("the summary counts what changed", () => {
  const found = compare(
    version(1, [{ id: "a", rows_out: 10 }, { id: "b" }]),
    version(2, [{ id: "a", rows_out: 4 }, { id: "c" }]),
  );
  const said = summarise(found);
  assert.match(said, /1 step added/);
  assert.match(said, /1 step removed/);
  assert.match(said, /1 row count changed/);
});

test("a missing row count is not read as zero", () => {
  const found = compare(
    version(1, [{ id: "a", rows_out: null }]),
    version(2, [{ id: "a", rows_out: null }]),
  );
  assert.deepEqual(found.changes, []);
});
