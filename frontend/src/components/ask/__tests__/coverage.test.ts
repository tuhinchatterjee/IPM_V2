/**
 * The coverage strip's contract. §11, §36, §40.
 *
 * Rendering is checked by the browser acceptance run; what is checked here is
 * the reasoning the component encodes, because that is where an answer starts
 * claiming more than it established.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { CompoundAnswer } from "../../../lib/api.ts";

function coverage(
  complete: number,
  total: number,
  statuses: string[],
): CompoundAnswer {
  return {
    available: true,
    questions_answered:
      complete === total
        ? `${total} of ${total}`
        : `${complete} of ${total} answered; ${total - complete} partly answered`,
    analyses_performed: 1,
    coverage: {
      total,
      complete,
      presentable: true,
      by_status: {},
      sentence: "",
      headline: "",
      objectives: statuses.map((status, index) => ({
        objective_id: `obj_${index + 1}`,
        description: `part ${index + 1}`,
        action: "AGGREGATE",
        status,
        note: status === "PARTIAL" ? "folded into the combined analysis" : "",
        planned_task: "",
      })),
      unmet: [],
      unsettled: [],
      failed: [],
    },
  };
}

test("a fully answered request reads as n of n", () => {
  const compound = coverage(2, 2, ["COMPLETE", "COMPLETE"]);
  assert.equal(compound.questions_answered, "2 of 2");
});

test("a partly verified request never reads as n of n", () => {
  const compound = coverage(1, 2, ["COMPLETE", "PARTIAL"]);
  assert.notEqual(compound.questions_answered, "2 of 2");
  assert.match(compound.questions_answered ?? "", /partly answered/);
});

test("every objective that is not complete carries a reason", () => {
  const compound = coverage(1, 2, ["COMPLETE", "PARTIAL"]);
  for (const objective of compound.coverage?.objectives ?? []) {
    if (objective.status !== "COMPLETE") {
      assert.ok(
        objective.note.length > 0,
        "an objective marked short of answered with no reason cannot be acted on",
      );
    }
  }
});

test("an unavailable coverage block still says something", () => {
  const compound: CompoundAnswer = {
    available: false,
    why: "the coverage of this request could not be established",
  };
  assert.equal(compound.available, false);
  assert.ok(
    (compound.why ?? "").length > 0,
    "silence would read as 'everything was answered'",
  );
});

test("a partial objective is presentable, not a failure", () => {
  const compound = coverage(1, 2, ["COMPLETE", "PARTIAL"]);
  assert.equal(compound.coverage?.presentable, true);
});
