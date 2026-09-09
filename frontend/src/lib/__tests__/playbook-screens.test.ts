import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

/**
 * The Playbook screens, checked against the source.
 *
 * A structural test, deliberately, and paired with `playbook-format.test.ts`
 * rather than replacing it: that file holds the RULES as pure functions with
 * real assertions; this one holds the claim that the screens actually use
 * them and have not grown a second, quieter implementation.
 *
 * What this cannot claim: that any of it looks good. It can see that the
 * pieces this area depends on are present and wired, which is the part that
 * silently rots.
 */

const root = fileURLToPath(new URL("../../", import.meta.url));
const read = (path: string) => readFileSync(`${root}${path}`, "utf8");

/**
 * The same source with runs of whitespace collapsed.
 *
 * Prose in JSX is wrapped by the formatter, so a sentence a test looks for is
 * routinely split across two lines. Asserting on the raw text makes these
 * checks fail whenever somebody reformats the file, which teaches people to
 * delete them.
 */
const prose = (path: string) => read(path).replace(/\s+/g, " ");

const PARTS = "components/playbook/parts.tsx";
const PACK_PAGE = "app/playbook/packs/[packId]/page.tsx";
const PACK_CONTENT = "components/playbook/pack-content.tsx";
const FINDINGS = "components/playbook/findings-panel.tsx";
const GOVERNANCE = "components/playbook/governance-panel.tsx";
const HISTORY = "components/playbook/history-panel.tsx";
const LANDING = "app/playbook/page.tsx";

// ================================================ figures come from one place

test("no Playbook screen formats a figure itself", () => {
  // The display string is decided once, on the backend, and stored on the
  // snapshot. A screen calling toFixed on `value` is a screen that will one
  // day disagree with the PDF sent to the same committee that morning.
  for (const file of [PARTS, PACK_CONTENT, FINDINGS, GOVERNANCE, HISTORY,
                      LANDING]) {
    const source = read(file);
    assert.ok(
      !source.includes("toFixed("),
      `${file} formats a number itself instead of rendering display_value`,
    );
  }
});

test("the figure component renders the reading rather than deciding it", () => {
  const source = read(PARTS);
  assert.ok(source.includes("figureReading("));
  assert.ok(source.includes("movementReading("));
  // And it does not carry its own copy of the availability vocabulary.
  assert.ok(
    !source.includes("NOT_MATURED:"),
    "parts.tsx has grown a second availability table",
  );
});

test("the working behind a figure is reachable from the pack", () => {
  const source = read(PACK_CONTENT);
  // The pack OFFERS the working and the recalculation; the working itself is
  // rendered by `parts.tsx`, so that one component decides what "the working"
  // consists of for every screen in the area.
  for (const control of ["Working", "Recalculate"]) {
    assert.ok(source.includes(control), `the pack offers ${control}`);
  }
  const parts = read(PARTS);
  // The fields that make a committee figure defensible rather than asserted.
  for (const field of ["formula_hash", "dataset_version", "run_id",
                       "numerator", "denominator"]) {
    assert.ok(parts.includes(field), `the working shows ${field}`);
  }
});

// ================================================= what is AI and what is not

test("an unaccepted AI draft is labelled on the pack", () => {
  const source = read(PACK_CONTENT);
  assert.ok(source.includes("ai_accepted"));
  assert.ok(
    source.includes("AI draft"),
    "a draft nobody has read must say so on the page",
  );
  assert.ok(
    source.includes("Accept"),
    "and accepting it must be a deliberate act",
  );
});

test("imported content is labelled as theirs, not as CreditProbe's", () => {
  const source = read(PACK_CONTENT);
  assert.ok(source.includes("import_class"));
  assert.ok(source.includes("UNMAPPED_TABLE"));
  assert.ok(
    prose(PACK_CONTENT).includes("CreditProbe did not calculate them"),
    "the screen says whose numbers these are",
  );
});

test("the history distinguishes the door a change came through", () => {
  const source = read(HISTORY);
  assert.ok(source.includes("event.source"));
  for (const door of ["AI", "IMPORT"]) {
    assert.ok(source.includes(`"${door}"`), `${door} is distinguished`);
  }
});

// ============================================== findings carry their evidence

test("a finding shows the rule that raised it and the numbers it fired on", () => {
  const source = read(FINDINGS);
  for (const field of ["rule_key", "factual_basis"]) {
    assert.ok(source.includes(field), `a finding shows its ${field}`);
  }
});

test("dismissing a finding requires a written reason on the screen too", () => {
  const source = read(FINDINGS);
  assert.ok(source.includes("DISMISSED"));
  // The button is disabled without a reason, so the API's refusal is a
  // backstop rather than the first thing a person meets.
  assert.ok(
    source.includes("!reason.trim()"),
    "the dismiss button is disabled until a reason is written",
  );
  assert.ok(source.includes("takes this off the committee"));
});

test("dismissal is gated on reviewer access in the screen as well", () => {
  const source = read(FINDINGS);
  assert.ok(source.includes("canDismiss"));
  assert.ok(source.includes("REVIEWER"));
});

// ================================== the Planner is the source of truth on work

test("an action reads its progress from the Planner rather than storing it", () => {
  const source = read(GOVERNANCE);
  assert.ok(source.includes("action.planner"));
  assert.ok(
    source.includes("percent_complete"),
    "progress comes off the Planner payload",
  );
  assert.ok(
    source.includes("was_linked"),
    "a Planner task that was deleted is reported, not silently unlinked",
  );
});

test("closing an action requires evidence", () => {
  const source = read(GOVERNANCE);
  assert.ok(source.includes("closure_evidence") || source.includes("evidence"));
  assert.ok(source.includes("!evidence.trim()"));
});

test("recording a decision is gated on approver access", () => {
  const source = read(GOVERNANCE);
  assert.ok(source.includes("canDecide"));
  assert.ok(source.includes("APPROVER"));
});

// ========================================================== the pack lifecycle

test("the pack's transitions come from the shared table, not a local copy", () => {
  const source = read(PACK_PAGE);
  assert.ok(source.includes("nextStatuses("));
  assert.ok(
    !source.includes("READY_FOR_APPROVAL:"),
    "the pack page has grown its own transition table",
  );
});

test("an approved pack offers an amendment rather than an edit", () => {
  const source = read(PACK_PAGE);
  assert.ok(source.includes("Raise an amendment"));
  assert.ok(source.includes("supersedes this one"));
  assert.ok(
    source.includes("historical record that can be edited is not a record"),
    "the screen says why an approved pack is read-only",
  );
});

test("readiness is shown with the moment it was worked out", () => {
  const parts = read(PARTS);
  assert.ok(parts.includes("computed_at"));
  assert.ok(parts.includes("Worked out"));
  assert.ok(
    parts.includes("not_assessed"),
    "a check that could not be run says so rather than scoring zero",
  );
});

// =========================================================== refusals and 403s

test("panels use Unavailable, which tells a refusal apart from a fault", () => {
  for (const file of [LANDING, FINDINGS, GOVERNANCE, HISTORY]) {
    assert.ok(
      read(file).includes("<Unavailable"),
      `${file} distinguishes "you may not see this" from "this is broken"`,
    );
  }
});

test("the chase screen says it sends nothing", () => {
  const source = read(LANDING);
  assert.ok(source.includes("sends nothing"));
});

// ============================================================== the downloads

test("every format is offered by the backend rather than hard-coded", () => {
  const source = read(PACK_PAGE);
  assert.ok(source.includes("api.playbook.formats()"));
  assert.ok(source.includes("api.playbook.exportUrl("));
  // A real link the browser follows: the file has to be saved, and the
  // response carries the filename and the checksum in its headers.
  assert.ok(source.includes("<a\n                href="));
  for (const guess of ['"pdf"', '"docx"', '"pptx"', '"xlsx"']) {
    assert.ok(
      !source.includes(guess),
      `the page hard-codes ${guess} instead of asking which formats exist`,
    );
  }
});

// ============================================================= navigation

test("Playbook is in the capability map, under Govern", () => {
  const nav = read("lib/navigation.ts");
  assert.ok(nav.includes('href: "/playbook"'));
  assert.ok(nav.includes('label: "Playbook"'));
  const entry = nav.slice(nav.indexOf('href: "/playbook"'));
  assert.match(entry.slice(0, 1400), /group: "Govern"/);
  assert.ok(
    !nav.includes('href: "/playbooks"'),
    "the earlier Playbooks feature is gone, not shadowing this one",
  );
});
