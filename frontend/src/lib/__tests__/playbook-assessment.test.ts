import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assessmentLines,
  duration,
  hasAssessment,
  type PbAssessmentCard,
} from "../playbook-assessment.ts";

const CARD: PbAssessmentCard = {
  available: true,
  version: 1,
  title: "Auto Loan Development Report",
  sections: {
    total: 3,
    written: 2,
    thin: [],
    gaps: ["3. Out-of-time testing"],
  },
  files: { delivered: ["docx", "pdf"], failed: {} },
  evidence: {
    sources: [
      {
        filename: "results.xlsx",
        complete: false,
        cited: 4,
        skipped: [{ what: "Working", why: "hidden sheet" }],
      },
    ],
    omissions: [{ what: "results.xlsx: Working", why: "hidden sheet" }],
  },
  untraceable: [{ section: "2. Results", figures: ["71.4"] }],
  review: { label: "Draft", open_items: 2 },
  time: { authoring_ms: 240000, render_ms: 3000, total_ms: 243000 },
  verdict: "Both files were produced.",
  verdict_state: "written",
};

function find(card: PbAssessmentCard, key: string) {
  return assessmentLines(card).find((l) => l.key === key);
}

test("a workspace with no document shows no card at all", () => {
  assert.equal(hasAssessment({ available: false, reason: "none yet" }), false);
  assert.deepEqual(assessmentLines({ available: false }), []);
});

test("the files it delivered are named", () => {
  assert.equal(find(CARD, "files")?.value, "DOCX, PDF");
});

test("a format that could not be produced says why", () => {
  const line = find(
    { ...CARD, files: { delivered: ["docx"], failed: { pdf: "no reader" } } },
    "failed",
  );
  assert.equal(line?.value, "PDF — no reader");
  assert.equal(line?.tone, "attention");
});

test("sections are counted, never scored", () => {
  const line = find(CARD, "sections");
  assert.equal(line?.value, "2 of 3 sections written in full");
  // No percentage anywhere: the document never declared how many sections it
  // would have, so a share of it is a number nobody measured.
  for (const rendered of assessmentLines(CARD)) {
    assert.ok(!rendered.value.includes("%"), rendered.value);
  }
});

test("a section that states a gap is named, not summarised away", () => {
  assert.equal(find(CARD, "gaps")?.value, "3. Out-of-time testing");
});

test("a figure with no source carries the section it is in", () => {
  assert.equal(find(CARD, "untraceable")?.value, "71.4 (2. Results)");
});

test("a source read in part says so", () => {
  const line = find(CARD, "source:results.xlsx");
  assert.equal(line?.value, "read in part, 4 passages used");
  assert.equal(line?.tone, "attention");
});

test("a source nothing was taken from is not reported as used", () => {
  const card = {
    ...CARD,
    evidence: {
      sources: [{ filename: "notes.docx", complete: true, cited: 0 }],
      omissions: [],
    },
  };
  assert.equal(
    find(card, "source:notes.docx")?.value,
    "read in full, nothing from it was used",
  );
});

test("a draft is never described as checked", () => {
  assert.equal(find(CARD, "review")?.value, "nobody yet — this is a draft");
  assert.equal(
    find({ ...CARD, review: { label: "Reviewed", open_items: 0 } }, "review")
      ?.value,
    "Reviewed",
  );
});

test("the time is split between the writing and the building", () => {
  assert.equal(
    find(CARD, "time")?.value,
    "4m 3s — 4m 0s writing, 3s building the files",
  );
});

test("durations read as durations", () => {
  assert.equal(duration(0), "0s");
  assert.equal(duration(8400), "8s");
  assert.equal(duration(252000), "4m 12s");
});
