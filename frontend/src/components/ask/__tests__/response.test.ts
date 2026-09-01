import assert from "node:assert/strict";
import { test } from "node:test";

import type { InvestigationResponse } from "../../../lib/api.ts";
import { foundNothing, implications, keyInsight } from "../insight.ts";
import { meaningOf } from "../../../lib/credit-semantics.ts";

/**
 * §61: the response contract, asserted on the functions that decide it.
 *
 * The layout is JSX and is checked in the browser review; what is checked here
 * is every decision the layout DELEGATES — which observation is promoted, what
 * counts as an implication, when an empty result is a conclusion rather than an
 * empty table, and which way a figure is coloured. Those are the parts that can
 * be wrong in a way nobody notices.
 */

/** A response with only what a test cares about set. */
function response(over: Partial<InvestigationResponse> = {}): InvestigationResponse {
  return {
    question: "How has Contracting moved?",
    status: "answered",
    unmatched: false,
    notes: [],
    rejected: [],
    steps: [],
    follow_ups: [],
    plan: { scope: {} },
    analysis_run_id: 1,
    narrative: {
      direct_answer: "Contracting recorded the largest increase in Stage 2 share.",
      summary: "Contracting recorded the largest increase in Stage 2 share.",
      findings: [],
      metrics: [],
      drivers: [],
      caveats: [],
      ...(over.narrative ?? {}),
    },
    ...over,
  } as unknown as InvestigationResponse;
}

/* ------------------------------------------------------------ key insight */

test("the promoted observation is one the backend already wrote", () => {
  // Never composed here: every figure in an answer is quoted from an engine
  // result and checked, and the most prominent box on the screen must not be
  // the one sentence nobody verified.
  const run = response({
    narrative: {
      findings: [
        {
          text: "Contracting moved from 4.1% to 5.9%.",
          tone: "warning",
          evidence: [{ label: "change", value: 1.8, unit: "pp", direction: "up-is-bad" }],
          step: 0,
        },
      ],
    },
  } as unknown as Partial<InvestigationResponse>);

  const insight = keyInsight(run)!;
  assert.equal(insight.text, "Contracting moved from 4.1% to 5.9%.");
  assert.equal(insight.evidence[0].unit, "pp");
});

test("a finding that only restates the headline is not promoted", () => {
  // Repeating the answer in a highlighted box tells the reader the product has
  // one thing to say and has decided to say it twice.
  const answer = "Contracting recorded the largest increase in Stage 2 share.";
  const run = response({
    narrative: {
      direct_answer: answer,
      summary: answer,
      findings: [{ text: answer, tone: "warning", evidence: [], step: 0 }],
    },
  } as unknown as Partial<InvestigationResponse>);
  assert.equal(keyInsight(run), null);
});

test("a finding carrying figures beats a louder one without them", () => {
  // The region's whole job is to be actionable without scrolling, and a
  // statement with its evidence attached is the only kind that is.
  const run = response({
    narrative: {
      findings: [
        { text: "Something is wrong.", tone: "negative", evidence: [], step: 0 },
        {
          text: "Contracting holds 31% of Stage 2 exposure.",
          tone: "neutral",
          evidence: [{ label: "share", value: 31, unit: "%" }],
          step: 1,
        },
      ],
    },
  } as unknown as Partial<InvestigationResponse>);
  assert.match(keyInsight(run)!.text, /^Contracting holds/);
});

test("nothing to promote renders nothing rather than a platitude", () => {
  assert.equal(keyInsight(response()), null);
});

test("the insight says why it was chosen", () => {
  const run = response({
    narrative: {
      findings: [
        { text: "Two facilities breached.", tone: "negative", evidence: [], step: 0 },
      ],
    },
  } as unknown as Partial<InvestigationResponse>);
  assert.equal(keyInsight(run)!.because, "Most material exception");
});

/* ----------------------------------------------------------- implications */

test("a refusal is an implication in the strongest sense", () => {
  const run = response({ rejected: ["No executive-change dataset is governed."] });
  assert.deepEqual(implications(run), ["No executive-change dataset is governed."]);
});

test("named contributors become an implication, in the engine's own order", () => {
  // Re-ranking them here would be a calculation, and this module does not do
  // arithmetic.
  const run = response({
    narrative: {
      drivers: [
        { name: "Contracting", value: 12, unit: "USD mn", measure: "the ECL increase", step: 0 },
        { name: "Retail", value: 4, unit: "USD mn", measure: "the ECL increase", step: 0 },
      ],
    },
  } as unknown as Partial<InvestigationResponse>);
  const [line] = implications(run);
  assert.equal(line, "Contracting and Retail account for most of the ECL increase.");
});

test("implications are capped and deduplicated", () => {
  // A list of nine implications is a list nobody reads.
  const run = response({
    rejected: ["a", "b", "A", "c", "d", "e"],
  });
  assert.equal(implications(run).length, 3);
});

test("nothing to say produces no section", () => {
  assert.deepEqual(implications(response()), []);
});

/* -------------------------------------------------- explicit negative finding */

test("an empty result is a conclusion, not an empty table", () => {
  // §15. An analysis that returned no rows has answered the question; rendering
  // its empty table underneath makes it look as though the product failed to
  // produce one.
  const run = response({
    steps: [
      {
        index: 0,
        role: "primary",
        analysis_id: "dynamic_analysis",
        certification: "dynamic",
        status: "succeeded",
        result: { rows: [], values: {}, units: {}, warnings: [] },
      },
    ],
  } as unknown as Partial<InvestigationResponse>);
  assert.equal(foundNothing(run), true);
});

test("a result with figures but no rows is not a negative finding", () => {
  // A portfolio total is one value and no rows, and it has answered the
  // question perfectly well.
  const run = response({
    steps: [
      {
        index: 0,
        role: "primary",
        analysis_id: "portfolio_summary",
        certification: "certified",
        status: "succeeded",
        result: { rows: [], values: { total_ead: 125259 }, units: {}, warnings: [] },
      },
    ],
  } as unknown as Partial<InvestigationResponse>);
  assert.equal(foundNothing(run), false);
});

test("an answer that ran no analysis has not 'found nothing'", () => {
  // A product-knowledge or catalogue answer carries no rows because it queried
  // nothing. Treating it as an empty result rendered the whole composed answer
  // a second time as one unbroken paragraph, under the structured one.
  const run = response({
    steps: [
      {
        index: 0,
        role: "primary",
        analysis_id: "capability_data_discovery",
        certification: "metadata",
        status: "succeeded",
        result: { rows: [], values: {}, units: {}, warnings: [] },
      },
    ],
  } as unknown as Partial<InvestigationResponse>);
  assert.equal(foundNothing(run), false);
});

test("a step that failed is not reported as having found nothing", () => {
  const run = response({
    steps: [
      {
        index: 0,
        role: "primary",
        analysis_id: "x",
        certification: "dynamic",
        status: "failed",
        result: { rows: [], values: {}, units: {}, warnings: [] },
      },
    ],
  } as unknown as Partial<InvestigationResponse>);
  assert.equal(foundNothing(run), false);
});

/* ------------------------------------------- inline tokens carry risk meaning */

test("an inline token's colour follows the ontology, not the sign", () => {
  // §51. The same +1.8 means opposite things for two measures, and a credit
  // officer reads colour before they read the number.
  assert.equal(meaningOf(1.8, "up-is-bad"), "adverse");
  assert.equal(meaningOf(1.8, "up-is-good"), "favourable");
  assert.equal(meaningOf(1.8, undefined), "neutral");
});
