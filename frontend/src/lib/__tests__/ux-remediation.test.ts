import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

/**
 * The UX remediation brief's three visual tasks, checked against the source.
 *
 * These three were left open in the tracker long after the work that would
 * satisfy them landed under other headings, and "probably superseded" is not
 * a state a checklist should stay in. Rather than close them on somebody's
 * reading of the diff, each claim the tasks make is asserted here against
 * the file that would have to contain it.
 *
 * A structural test, deliberately. These are claims about what the interface
 * is made of — a nav that remembers, a header with no explanatory paragraph
 * under it, an answer whose interpretation comes before its numbers — and
 * the honest way to hold them is to fail when somebody removes the thing.
 *
 * What this does NOT claim: that any of it looks good. A test cannot see
 * that. It can see that the pieces the brief asked for are present and
 * wired, which is the part that silently rots.
 */

const root = fileURLToPath(new URL("../../", import.meta.url));
const read = (path: string) => readFileSync(root + path, "utf8");

// ------------------------------------------------------- §15-§19 (task 112)

test("the answer puts the interpretation before the numbers, unboxed", () => {
  const answer = read("components/ask/answer.tsx");

  // The interpretation exists as its own labelled section rather than as a
  // paragraph inside the result card.
  assert.ok(answer.includes("CreditProbe interpretation"));

  // And it is rendered above the analysis. Position, not presence: an
  // interpretation printed under the table is the defect the brief names.
  const interpretation = answer.indexOf("CreditProbe interpretation");
  const supporting = answer.indexOf("Supporting analysis");
  assert.ok(interpretation > 0 && supporting > 0);
  assert.ok(
    interpretation < supporting,
    "the interpretation must be rendered before the supporting analysis",
  );
});

test("supporting analysis is collapsed and follow-ups come last", () => {
  const answer = read("components/ask/answer.tsx");
  assert.ok(
    answer.includes("Supporting analysis ("),
    "supporting analysis is a collapsed summary with a count",
  );
  assert.ok(answer.includes("follow_ups"));

  const supporting = answer.indexOf("Supporting analysis");
  const followUps = answer.lastIndexOf("follow_ups");
  assert.ok(
    supporting < followUps,
    "follow-ups belong after the answer, not inside it",
  );
});

test("an analysis header can carry a certification mark", () => {
  const mark = read("components/ui/certified-mark.tsx");
  assert.ok(mark.length > 0);
  const method = read("components/ask/data-and-method.tsx");
  assert.ok(
    /certif/i.test(method),
    "the data-and-method header shows whether the method is certified",
  );
});

// ------------------------------------------------------- §41-§43 (task 116)

test("the navigation collapses and remembers the choice", () => {
  const state = read("components/layout/nav-state.tsx");
  assert.ok(state.includes("collapsed"));
  assert.ok(
    state.includes("creditprobe.nav.collapsed"),
    "the preference is persisted under a stable key",
  );

  const header = read("components/layout/header.tsx");
  // A control that changes state must say which state it is in, or a
  // screen reader user cannot tell whether it collapsed.
  assert.ok(header.includes("aria-expanded"));
  assert.ok(header.includes("Collapse navigation"));
  assert.ok(header.includes("Expand navigation"));
});

test("the page header is eyebrow, title and actions — and no paragraph", () => {
  const header = read("components/layout/page-header.tsx");
  for (const part of ["eyebrow", "title", "actions"]) {
    assert.ok(header.includes(part), `the header takes an ${part}`);
  }
  // §43's actual instruction: the standing explanatory paragraph goes
  // behind an info control. The header importing the popover is what makes
  // that true rather than aspirational.
  assert.ok(
    header.includes("info-popover") || header.includes("InfoPopover"),
    "the explanation lives behind the info control, not under the title",
  );
});

// ------------------------------------------------------- §44-§46 (task 117)

test("data builder shows domains as tiles with a summary strip", () => {
  const page = read("app/data-builder/page.tsx");
  assert.ok(page.includes("SummaryTile"));
  assert.ok(page.includes("DomainCard"));
  // Tiles, meaning a responsive grid rather than a list.
  assert.ok(/grid gap-\d+ md:grid-cols-2/.test(page));
});

test("the data grid is period-aware", () => {
  const grid = read("components/data-builder/data-grid.tsx");
  assert.ok(grid.includes("period"));
  assert.ok(
    grid.includes("period={"),
    "the period reaches the grid rather than only its request",
  );
});

test("the relationship map has a layout, a canvas and an inspector", () => {
  for (const file of [
    "components/data-builder/relationship-layout.ts",
    "components/data-builder/relationship-canvas.tsx",
    "components/data-builder/relationship-inspector.tsx",
  ]) {
    assert.ok(read(file).length > 0, `${file} is present`);
  }
});

test("the method library is a compact grid, not a wall of prose", () => {
  const studio = read("app/studio/page.tsx");
  assert.ok(/grid gap-\d+ sm:grid-cols-\d/.test(studio));
});
