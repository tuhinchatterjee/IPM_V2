import assert from "node:assert/strict";
import { test } from "node:test";

import type { PbChangeItem, PbChangeSet } from "../api.ts";
import {
  decisionSummary,
  dependencyWarnings,
  isOpen,
  openChangeSet,
  withDependencies,
} from "../playbook.ts";

function item(over: Partial<PbChangeItem> & { stable_id: string; number: number }): PbChangeItem {
  return {
    target_section: "A section",
    rationale: "Because.",
    evidence: {},
    depends_on: [],
    status: "proposed",
    ...over,
  };
}

const ITEMS: PbChangeItem[] = [
  item({ stable_id: "a", number: 1, target_section: "3. Staging" }),
  item({ stable_id: "b", number: 2, target_section: "4. Coverage", depends_on: ["a"] }),
  item({ stable_id: "c", number: 3, target_section: "1. Summary" }),
  item({ stable_id: "d", number: 4, target_section: "2. Monitoring", depends_on: ["missing-pack"] }),
  item({ stable_id: "e", number: 5, target_section: "5. Limitations" }),
];

function changeSet(over: Partial<PbChangeSet> = {}): PbChangeSet {
  return { id: 1, status: "proposed", base_version_id: null, items: ITEMS, ...over };
}

test("a proposal with an undecided item is still open", () => {
  assert.equal(isOpen(changeSet()), true);
});

test("a fully decided proposal is closed but not discarded", () => {
  const decided = changeSet({
    items: ITEMS.map((i) => ({ ...i, status: "approved" as const })),
  });
  assert.equal(isOpen(decided), false);
  assert.equal(decided.items.length, 5);
});

test("the open proposal is the most recent one still awaiting a decision", () => {
  const closed = changeSet({
    id: 1,
    items: ITEMS.map((i) => ({ ...i, status: "rejected" as const })),
  });
  const open = changeSet({ id: 2 });
  assert.equal(openChangeSet([closed, open])?.id, 2);
  assert.equal(openChangeSet([closed]), null);
});

test("a dependency inside the proposal is warned about before the request", () => {
  const warnings = dependencyWarnings(ITEMS, ["b", "c"]);
  assert.deepEqual(warnings, [
    { stable_id: "b", number: 2, target_section: "4. Coverage", requires: [1] },
  ]);
});

test("a dependency that is also ticked raises no warning", () => {
  assert.deepEqual(dependencyWarnings(ITEMS, ["a", "b"]), []);
});

test("a dependency on something outside the proposal is not a tick-box problem", () => {
  // Change 4 needs a monitoring pack the user has not supplied. No combination
  // of tick boxes can satisfy that, so the tick boxes do not pretend otherwise.
  assert.deepEqual(dependencyWarnings(ITEMS, ["d"]), []);
});

test("ticking a change ticks what it rests on, in proposal order", () => {
  assert.deepEqual(withDependencies(ITEMS, ["b"]), ["a", "b"]);
  assert.deepEqual(withDependencies(ITEMS, ["e", "b"]), ["a", "b", "e"]);
});

test("pulling in dependencies terminates on a cycle", () => {
  const cyclic = [
    item({ stable_id: "x", number: 1, depends_on: ["y"] }),
    item({ stable_id: "y", number: 2, depends_on: ["x"] }),
  ];
  assert.deepEqual(withDependencies(cyclic, ["x"]), ["x", "y"]);
});

test("the summary names what is applied and what is held", () => {
  assert.equal(
    decisionSummary(ITEMS, ["a", "b", "c", "e"]),
    "Applying changes 1, 2, 3 and 5. Change 4 is held and will not be made.",
  );
});

test("one change reads as one change", () => {
  assert.equal(
    decisionSummary(ITEMS, ["c"]),
    "Applying change 3. Changes 1, 2, 4 and 5 are held and will not be made.",
  );
});

test("approving everything says nothing about exclusions", () => {
  assert.equal(
    decisionSummary(ITEMS, ["a", "b", "c", "d", "e"]),
    "Applying changes 1, 2, 3, 4 and 5.",
  );
});

test("approving nothing says the document is unchanged", () => {
  assert.equal(
    decisionSummary(ITEMS, []),
    "No changes approved. The document is unchanged.",
  );
});
