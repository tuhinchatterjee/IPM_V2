import assert from "node:assert/strict";
import { test } from "node:test";

import type { PbArtifact, PbCapabilities, PbSource } from "../api.ts";
import {
  HOME_SECTIONS,
  composerState,
  formatBytes,
  hasEvidenceGaps,
  homeOrder,
  homePrompts,
  matching,
  moduleLabel,
  nextSteps,
  QUICK_PROMPTS,
  sourceStatus,
} from "../playbook.ts";

function source(over: Partial<PbSource> = {}): PbSource {
  return {
    id: 1,
    filename: "prior.docx",
    role: "previous_report",
    status: "parsed",
    size_bytes: 2048,
    manifest: { read: ["12 paragraphs"], skipped: [], warnings: [], complete: true },
    failure_reason: "",
    ...over,
  };
}

function artifact(over: Partial<PbArtifact> = {}): PbArtifact {
  return {
    id: 1,
    kind: "report",
    title: "IFRS 9 committee report",
    current_version_id: 10,
    derived_from_artifact_id: null,
    derived_from_version_id: null,
    versions: [
      { id: 10, version: 1, change_summary: "", origin: "assistant_live",
        created_at: "", files: [] },
    ],
    ...over,
  };
}

// ------------------------------------------------------------- the home order

test("the home screen order is composer, prompts, playbooks, then analyses", () => {
  assert.deepEqual(homeOrder(), [
    "composer",
    "quick-prompts",
    "recent-playbooks",
    "recent-exported-analyses",
  ]);
});

test("recent playbooks come before recent exported analyses", () => {
  const order = homeOrder();
  assert.ok(
    order.indexOf("recent-playbooks") < order.indexOf("recent-exported-analyses"),
  );
});

test("the order constant and the function cannot drift apart", () => {
  assert.deepEqual(homeOrder(), [...HOME_SECTIONS]);
});

// ------------------------------------------------------------- quick prompts

test("every quick prompt has text to put in the composer", () => {
  assert.ok(QUICK_PROMPTS.length >= 8);
  for (const p of QUICK_PROMPTS) {
    assert.ok(p.prompt.length > 20, `${p.id} has no usable prompt`);
    assert.ok(p.label.length > 0);
  }
});

test("the eight starters §3 names are all present", () => {
  const ids = QUICK_PROMPTS.map((p) => p.id);
  for (const expected of [
    "ifrs9-committee",
    "ifrs9-corporate-pack",
    "application-development",
    "behavioural-validation",
    "update-previous",
    "methodology-coverage",
    "sharpen-summary",
    "to-presentation",
  ]) {
    assert.ok(ids.includes(expected), `${expected} is missing`);
  }
});

test("the home screen shows a subset rather than all of them", () => {
  assert.ok(homePrompts().length < QUICK_PROMPTS.length);
});

// ------------------------------------------------------------ source honesty

test("a partly read source is neither ready nor failed", () => {
  const state = sourceStatus(
    source({
      status: "partial",
      manifest: {
        read: ["sheet 'ECL'"],
        skipped: [{ what: "sheet 'Working'", why: "hidden" }],
        warnings: [],
        complete: false,
      },
    }),
  );
  assert.equal(state.tone, "warning");
  assert.equal(state.label, "Partly read");
  assert.ok(state.detail.includes("Working"));
});

test("a failed source shows why", () => {
  const state = sourceStatus(
    source({ status: "failed", failure_reason: "It appears to be a scan." }),
  );
  assert.equal(state.tone, "negative");
  assert.ok(state.detail.includes("scan"));
});

test("evidence gaps are detected from partial and failed sources", () => {
  assert.equal(hasEvidenceGaps([source()]), false);
  assert.equal(hasEvidenceGaps([source({ status: "partial" })]), true);
  assert.equal(hasEvidenceGaps([source({ status: "failed" })]), true);
});

// -------------------------------------------------------------- next actions

test("nothing about the report is suggested before one exists", () => {
  const steps = nextSteps({ artifacts: [], sources: [source()] });
  assert.equal(steps.some((s) => s.id === "sharpen"), false);
  assert.equal(steps.some((s) => s.id === "present"), false);
  assert.equal(steps[0].id, "draft");
});

test("with no report and no sources there is nothing honest to suggest", () => {
  assert.deepEqual(nextSteps({ artifacts: [], sources: [] }), []);
});

test("a presentation is offered when the report has one and it is stale", () => {
  const report = artifact();
  const staleDeck = artifact({
    id: 2,
    kind: "presentation",
    derived_from_artifact_id: 1,
    derived_from_version_id: 9,
  });
  const steps = nextSteps({ artifacts: [report, staleDeck], sources: [] });
  const present = steps.find((s) => s.id === "present");
  assert.ok(present);
  assert.ok(present.label.includes("Update"));
});

test("a presentation already current at this version is not offered again", () => {
  const report = artifact();
  const currentDeck = artifact({
    id: 2,
    kind: "presentation",
    derived_from_artifact_id: 1,
    derived_from_version_id: 10,
  });
  const steps = nextSteps({ artifacts: [report, currentDeck], sources: [] });
  assert.equal(steps.some((s) => s.id === "present"), false);
});

test("reviewing unread sources is offered only when something was unread", () => {
  const clean = nextSteps({ artifacts: [artifact()], sources: [source()] });
  assert.equal(clean.some((s) => s.id === "gaps"), false);

  const gappy = nextSteps({
    artifacts: [artifact()],
    sources: [source({ status: "partial" })],
  });
  assert.equal(gappy.some((s) => s.id === "gaps"), true);
});

// ------------------------------------------------------------ provider state

test("with no provider the composer says so and does not offer to generate", () => {
  const caps: PbCapabilities = {
    formats: [],
    provider: {
      configured: false,
      reason: "ANTHROPIC_API_KEY is not set.",
      provider: "anthropic",
      model: "",
      model_inherited: true,
    },
  };
  const state = composerState(caps);
  assert.equal(state.canGenerate, false);
  assert.ok(state.note.includes("ANTHROPIC_API_KEY"));
});

test("with a provider configured generation is offered without a note", () => {
  const caps: PbCapabilities = {
    formats: [],
    provider: {
      configured: true,
      reason: "",
      provider: "anthropic",
      model: "",
      model_inherited: true,
    },
  };
  assert.deepEqual(composerState(caps), { canGenerate: true, note: "" });
});

// ---------------------------------------------------------------- selection

test("filtering keeps entries that are already selected", () => {
  const entries = [
    { revision_id: 1, title: "Stage migration" },
    { revision_id: 2, title: "Coverage ratio movement" },
  ];
  const filtered = matching(entries, "coverage", [1]);
  assert.equal(filtered.length, 2, "a selected entry must not vanish while typing");
});

test("filtering without a selection narrows normally", () => {
  const entries = [
    { revision_id: 1, title: "Stage migration" },
    { revision_id: 2, title: "Coverage ratio movement" },
  ];
  assert.equal(matching(entries, "coverage", []).length, 1);
});

// -------------------------------------------------------------------- labels

test("module labels are readable and unknown ones pass through", () => {
  assert.equal(moduleLabel("early_warning"), "Early Warning");
  assert.equal(moduleLabel("scorecard_validation"), "Scorecard Validation");
  assert.equal(moduleLabel("something_new"), "something_new");
});

test("byte sizes are readable", () => {
  assert.equal(formatBytes(0), "0 KB");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(2048), "2 KB");
  assert.equal(formatBytes(3 * 1024 * 1024), "3.0 MB");
});
