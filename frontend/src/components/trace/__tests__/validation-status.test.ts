import assert from "node:assert/strict";
import { test } from "node:test";

import type { TraceGraph, TraceNode } from "../../../lib/api.ts";
import { clustersOf } from "../clusters.ts";
import { stagesOf } from "../stages.ts";

/**
 * §9. The contradiction an acceptance run photographed.
 *
 * The Trace showed, in one row:
 *
 *     VALIDATED — Failed · 4 checks · "4 of 4 checks passed"
 *
 * with a red "Not shown" beneath it. Every part of that was individually
 * true. The four business invariants had all held, which is what the count
 * said; the presentation gate had blocked the written answer, which is what
 * the red text said; and the stage word was the worst status of everything in
 * the stage, which is what made them look like one statement. A reader could
 * not tell whether the calculation was wrong.
 *
 * The two are different questions with different owners and they are shown
 * separately now. These tests hold that apart: a presentation failure must
 * not fail the calculation validation, and a real invariant failure must
 * still fail it.
 */

function node(partial: Partial<TraceNode> & { id: string; type: string }): TraceNode {
  return {
    label: partial.id,
    config: {},
    status: "ok",
    is_governed: true,
    started_at: null,
    finished_at: null,
    duration_ms: null,
    rows_in: null,
    rows_out: null,
    output_preview: [],
    output_summary: {},
    dataset: null,
    fields_used: [],
    function_id: null,
    function_version: null,
    dataset_version: null,
    warnings: [],
    error: null,
    ...partial,
  } as TraceNode;
}

function graphOf(nodes: TraceNode[]): TraceGraph {
  return { nodes, edges: [], layers: nodes.map((n) => [n.id]) } as unknown as TraceGraph;
}

/** Four invariants, all held. */
const HELD = node({
  id: "invariants",
  type: "BUSINESS_INVARIANT",
  label: "4 of 4 checks held",
  config: { checked: ["a", "b", "c", "d"], failed: [] },
});

/** One invariant genuinely failed. */
const BROKEN = node({
  id: "invariants",
  type: "BUSINESS_INVARIANT",
  label: "3 of 4 checks held",
  status: "failed",
  config: { checked: ["a", "b", "c", "d"], failed: [{ claim: "d" }] },
});

/** The presentation gate blocked the prose. */
const BLOCKED = node({
  id: "presentability",
  type: "PRESENTATION_GATE",
  label: "Not shown. A figure in the summary has no fact behind it.",
  status: "failed",
  error: "GROUNDING",
});

const RESULT = node({ id: "result", type: "RESULT", label: "10 borrowers", rows_out: 10 });

test("a blocked presentation does not fail the calculation validation", () => {
  const stages = stagesOf(graphOf([HELD, BLOCKED, RESULT]));
  const validated = stages.find((s) => s.id === "validated");
  assert.ok(validated, "there is no validated stage");
  assert.equal(validated.status, "passed");
  assert.match(validated.summary, /4 of 4 checks passed/);
});

test("the blocked presentation is still shown, in its own stage", () => {
  const stages = stagesOf(graphOf([HELD, BLOCKED, RESULT]));
  const presented = stages.find((s) => s.id === "presented");
  assert.ok(presented, "the presentation gate vanished instead of moving");
  assert.equal(presented.status, "failed");
  assert.match(presented.summary, /Not shown/);
});

test("a genuinely failed invariant still fails the validation stage", () => {
  const stages = stagesOf(graphOf([BROKEN, RESULT]));
  const validated = stages.find((s) => s.id === "validated");
  assert.ok(validated);
  assert.equal(validated.status, "failed");
  assert.match(validated.summary, /3 of 4 checks passed/);
});

test("no stage ever prints FAILED beside its own all-passed count", () => {
  // The invariant itself, over every combination that produced the defect.
  for (const nodes of [
    [HELD, BLOCKED, RESULT],
    [HELD, RESULT],
    [BROKEN, BLOCKED, RESULT],
    [BROKEN, RESULT],
  ]) {
    for (const stage of stagesOf(graphOf(nodes))) {
      const all = /^(\d+) of \1 checks passed\.$/.exec(stage.summary);
      if (all) {
        assert.notEqual(
          stage.status,
          "failed",
          `${stage.title} says "${stage.summary}" and "Failed" at the same time`,
        );
      }
    }
  }
});

test("the same holds for the detailed cluster view", () => {
  const clusters = clustersOf(graphOf([HELD, BLOCKED, RESULT]));
  const validation = clusters.find((c) => c.id === "validation");
  assert.ok(validation);
  assert.equal(validation.status, "passed");
  assert.match(validation.summary, /4 of 4 checks passed/);

  const presentation = clusters.find((c) => c.id === "presentation");
  assert.ok(presentation, "the gate did not reach its own cluster");
  assert.equal(presentation.status, "failed");
});
