import assert from "node:assert/strict";
import { test } from "node:test";

import type { InvestigationResponse } from "../api.ts";
import {
  exportability,
  fromAnswer,
  fromEarlyWarning,
  fromLensPanel,
  fromScorecardValidation,
} from "../playbook-export.ts";

function answer(over: Partial<InvestigationResponse> = {}): InvestigationResponse {
  return {
    question: "How did ECL move between Q1 and Q2 2026?",
    plan: { scope: "portfolio" },
    intent: "movement",
    steps: [
      {
        index: 0,
        analysis_id: "ecl_movement",
        title: "ECL movement",
        rationale: "",
        params: {},
        filters: { sector: "Contracting" },
        period: "Q2 2026",
        status: "succeeded",
        certification: "certified",
        analysis_version: "1.0.0",
        duration_ms: 12,
        result: {
          rows: [{ Scenario: "Base", ECL: "19.20" }],
          values: {},
          units: { ECL: "SAR million" },
          input_row_count: 1,
          warnings: [],
          meta: {},
        },
        error: null,
        analysis_run_id: 4101,
        trace: null,
        node_hashes: {},
        reused: false,
        role: "primary",
      },
    ],
    narrative: {
      direct_answer:
        "Weighted ECL rose to SAR 22.77 million from SAR 20.90 million, an " +
        "increase of 8.95 per cent driven by the downturn scenario.",
      summary: "",
      findings: [],
      interpretation: "The movement sits above the book's own trend.",
      interpretation_points: [],
      metrics: [],
      drivers: [],
      caveats: ["Excludes post-model adjustments."],
      scope: "Whole book",
    },
    clarification: null,
    follow_ups: [],
    notes: [],
    unmatched: false,
    trace: { nodes: [], edges: [] },
    node_hashes: {},
    duration_ms: 20,
    status: "succeeded",
    analysis_run_id: 4101,
    version: 3,
    version_label: "v3",
    rejected: [],
    mode: "governed",
    stages: [],
    ...over,
  } as unknown as InvestigationResponse;
}

// ------------------------------------------------------------ exportability

test("a completed analysis can be exported", () => {
  assert.equal(exportability(answer()).can, true);
});

test("an answer that asked a question is not a completed analysis", () => {
  const state = exportability(
    answer({ clarification: { question: "Which period?", options: [] } } as never),
  );
  assert.equal(state.can, false);
  assert.match(state.reason, /asked a question/);
});

test("an answer that matched nothing cannot be exported", () => {
  const state = exportability(answer({ unmatched: true }));
  assert.equal(state.can, false);
  assert.match(state.reason, /matched no analysis/);
});

test("a failed answer cannot be exported", () => {
  const state = exportability(answer({ status: "failed" }));
  assert.equal(state.can, false);
  assert.match(state.reason, /not a completed analysis/);
});

test("a greeting with no result and no narrative cannot be exported", () => {
  const state = exportability(
    answer({
      steps: [],
      narrative: { summary: "Hello.", findings: [], metrics: [], drivers: [], caveats: [] } as never,
    }),
  );
  assert.equal(state.can, false);
});

test("a substantive narrative with no table is still exportable", () => {
  const state = exportability(answer({ steps: [] }));
  assert.equal(state.can, true);
});

test("nothing at all is not exportable", () => {
  assert.equal(exportability(null).can, false);
});

// ---------------------------------------------------------------- the payload

test("the payload carries the question, the narrative and the table", () => {
  const payload = fromAnswer(answer());
  assert.equal(payload.source_module, "cockpit");
  assert.match(payload.question ?? "", /How did ECL move/);
  assert.match(payload.narrative ?? "", /22.77/);
  assert.equal(payload.tables?.length, 1);
  assert.deepEqual(payload.tables?.[0].columns, ["Scenario", "ECL"]);
  assert.deepEqual(payload.tables?.[0].rows, [["Base", "19.20"]]);
});

test("units survive the export, because a column of numbers without them is ambiguous", () => {
  const payload = fromAnswer(answer());
  assert.equal(payload.tables?.[0].units?.ECL, "SAR million");
});

test("period, filters and provenance are carried", () => {
  const payload = fromAnswer(answer(), { threadId: 77 });
  assert.equal(payload.reporting_period, "Q2 2026");
  assert.equal((payload.scope as Record<string, unknown>).analysis_id, "ecl_movement");
  assert.equal((payload.source_ref as Record<string, unknown>).run_id, 4101);
  assert.equal((payload.source_ref as Record<string, unknown>).thread_id, 77);
});

test("caveats are carried rather than dropped", () => {
  assert.deepEqual(fromAnswer(answer()).caveats, ["Excludes post-model adjustments."]);
});

test("the interpretation travels with the answer but stays in the narrative", () => {
  const payload = fromAnswer(answer());
  assert.match(payload.narrative ?? "", /above the book's own trend/);
});

// ------------------------------------------------------------- other modules

test("a lens export names the lens, its revision, and links to it", () => {
  const payload = fromLensPanel(
    {
      analysis_id: "obligor_concentration",
      title: "Obligor concentration",
      analysis_run_id: 55,
      result: { rows: [{ Obligor: "A", Share: "12.0" }], units: { Share: "%" } },
    },
    { id: 9, name: "CRO portfolio", revision: 4 },
  );
  assert.equal(payload.source_module, "lenses");
  assert.match(payload.title, /CRO portfolio/);
  assert.equal((payload.source_ref as Record<string, unknown>).lens_id, 9);
  assert.equal(payload.source_revision, "4");
  assert.deepEqual(payload.tables?.[0].columns, ["Obligor", "Share"]);
  assert.equal(payload.tables?.[0].units?.Share, "%");
});

test("an early warning export carries the prototype caveat by default", () => {
  const payload = fromEarlyWarning({
    borrowerId: "C-1",
    borrowerName: "Contracting Co",
    period: "Q2 2026",
    narrative: "The signal rose sharply. Utilisation is the largest factor.",
    columns: ["Factor", "Contribution"],
    rows: [["Utilisation", "0.14"]],
  });
  assert.equal(payload.source_module, "early_warning");
  assert.match(payload.caveats?.[0] ?? "", /prototype/);
  assert.equal(payload.tables?.length, 1);
});

test("a scorecard validation export names the model and the month", () => {
  const payload = fromScorecardValidation({
    reportId: "r-1",
    modelKind: "behavioural",
    month: "2026-06",
    title: "Discrimination",
    narrative: "Gini was 0.58 against a limit of 0.45.",
    columns: ["Metric", "Value"],
    rows: [["Gini", "0.58"]],
  });
  assert.equal(payload.source_module, "scorecard_validation");
  assert.equal(payload.reporting_period, "2026-06");
  assert.equal((payload.scope as Record<string, unknown>).model_kind, "behavioural");
});

test("every builder produces a module the backend contract accepts", () => {
  const accepted = new Set([
    "cockpit",
    "early_warning",
    "what_if",
    "scorecard_validation",
    "lenses",
  ]);
  const payloads = [
    fromAnswer(answer()),
    fromLensPanel({ analysis_id: "a" }, { id: 1, name: "L" }),
    fromEarlyWarning({
      borrowerId: "b", borrowerName: "B", period: "Q2 2026",
      narrative: "x", columns: [], rows: [],
    }),
    fromScorecardValidation({
      reportId: "r", modelKind: "application", month: "2026-06",
      title: "t", narrative: "n", columns: [], rows: [],
    }),
  ];
  for (const p of payloads) {
    assert.ok(accepted.has(p.source_module), `${p.source_module} is not in scope`);
    assert.ok(p.title.length > 0);
  }
});

test("no builder produces a Project Planner export", () => {
  const payloads = [fromAnswer(answer()), fromLensPanel({ analysis_id: "a" }, { id: 1, name: "L" })];
  for (const p of payloads) {
    assert.notEqual(p.source_module, "project_planner");
  }
});
