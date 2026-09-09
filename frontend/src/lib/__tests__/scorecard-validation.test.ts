import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

/**
 * The Retail Scorecard Validation module, checked against its source.
 *
 * These are claims about what the screen refuses to do, and a refusal is
 * exactly the kind of thing that rots silently: nobody notices when a grey
 * "no approved limit" chip quietly becomes a green tick, because the screen
 * looks better afterwards.
 *
 * A structural test, deliberately. It cannot see that the module looks good.
 * It can see that the pieces which encode the governance are present and
 * distinct from each other.
 */

const root = fileURLToPath(new URL("../../", import.meta.url));
const read = (path: string) => readFileSync(root + path, "utf8");
// The retail monitoring surface moved to its own route when
// /scorecard-validation became the Intelligence Cockpit. Same file, same
// refusals — the tests below are about what it will not draw, and that is
// unchanged by where it is mounted.
const page = () => read("app/scorecard-validation/monitoring/page.tsx");

test("the module has the twelve tabs the brief names", () => {
  const source = page();
  for (const tab of [
    "cockpit",
    "dashboard",
    "discrimination",
    "calibration",
    "stability",
    "variables",
    "models",
    "diagnostics",
    "trends",
    "findings",
    "governance",
    "data",
  ]) {
    assert.ok(source.includes(`"${tab}"`), `tab ${tab} is present`);
  }
});

test("no approved limit is styled apart from pass and from not measured", () => {
  const source = page();
  // §50. Three distinct entries: a metric nobody set a limit for has not
  // passed, and is also not the same as one that was never measured.
  assert.ok(source.includes('"NO APPROVED LIMIT":'));
  assert.ok(source.includes('"NOT MEASURED":'));

  const noLimit = source.match(/"NO APPROVED LIMIT": "([^"]+)"/)?.[1];
  const notMeasured = source.match(/"NOT MEASURED": "([^"]+)"/)?.[1];
  const pass = source.match(/PASS: "([^"]+)"/)?.[1];
  assert.ok(noLimit && notMeasured && pass);
  assert.notEqual(noLimit, pass, "no-limit must not be the pass colour");
  assert.notEqual(noLimit, notMeasured, "the two absences differ");
  assert.ok(
    !noLimit.includes("positive"),
    "no-limit must not use the positive token",
  );
});

test("the limits table carries a source column", () => {
  // §81: Metric, Observed, Limit, Status, Source. Without the source a
  // reader cannot tell a demonstration default from a regulator's number.
  const source = page();
  const table = source.slice(source.indexOf("function Limits("));
  for (const heading of ["Metric", "Observed", "Limit", "Status", "Source"]) {
    assert.ok(table.includes(`>${heading}<`), heading);
  }
});

test("an unavailable section renders its reason rather than a zero", () => {
  const source = page();
  assert.ok(source.includes("function Unavailable("));
  // Every outcome-dependent panel checks for it before reading a number.
  for (const panel of ["Discrimination", "Calibration"]) {
    const start = source.indexOf(`function ${panel}(`);
    const body = source.slice(start, start + 400);
    assert.ok(
      body.includes("available === false"),
      `${panel} checks availability first`,
    );
  }
});

test("validation statistics and business figures use different formatters", () => {
  const source = page();
  assert.ok(source.includes("function stat("));
  assert.ok(source.includes("function percent("));
  // Four decimals for unit-interval statistics, two for percentages.
  assert.ok(/places = 4/.test(source));
  assert.ok(/toFixed\(2\)\}%/.test(source));
});

test("the three month notions are shown separately", () => {
  // §7. Latest data month, latest matured performance month, and horizon.
  const source = page();
  assert.ok(source.includes("Latest data month"));
  assert.ok(source.includes("Latest matured performance month"));
  assert.ok(source.includes("Performance horizon"));
});

test("an immature month is labelled in the month picker", () => {
  const source = page();
  assert.ok(source.includes("stability only"));
});

test("the opinion is shown with its reasoning and its disclaimer", () => {
  const source = page();
  assert.ok(source.includes("Overall validation opinion"));
  assert.ok(source.includes("how_this_was_decided"));
  assert.ok(source.includes("not_a_certification"));
});

test("the diagnostics panel shows the restated question and claim strength", () => {
  // §28. The restatement is the honest version of the question, and the
  // claim strength is what says whether an ablation actually ran.
  const source = page();
  assert.ok(source.includes("question_as_asked"));
  assert.ok(source.includes("question_as_analysed"));
  assert.ok(source.includes("why_restated"));
  assert.ok(source.includes("Claim strength"));
  assert.ok(source.includes("limitations"));
});

test("the module is reachable from the navigation", () => {
  // A finished page at a real route with nothing linking to it is
  // indistinguishable from a page nobody built.
  const nav = read("lib/navigation.ts");
  assert.ok(nav.includes('href: "/scorecard-validation"'));
  assert.ok(nav.includes('label: "Scorecard Validation"'));
});

test("the api client sends no rows and asks for summaries", () => {
  // §76. Every scorecard call returns aggregates; the browser never sees
  // the 12,000-19,000 rows a month holds.
  const client = read("lib/api.ts");
  assert.ok(client.includes("scorecardDashboard:"));
  assert.ok(client.includes("scorecardOdrTrend:"));
  assert.ok(client.includes("scorecardLowDiscrimination:"));
  assert.ok(client.includes("scorecardRescore:"));
  // The candidate flow is typed as never activating.
  assert.ok(client.includes("activated: boolean"));
});

test("the reports tab offers both downloads and a way to record one", () => {
  // §51/§83. Two files, and generation kept separate from download: a
  // single button that did both would leave no record of a report somebody
  // looked at and did not save.
  const source = page();
  assert.ok(source.includes('"reports"'));
  assert.ok(source.includes("Download validation report (DOCX)"));
  assert.ok(source.includes("Download validation evidence (XLSX)"));
  assert.ok(source.includes("Generate validation report"));
  assert.ok(source.includes("scorecardGenerateReport"));
});

test("the report panel shows coverage and refuses to claim certification", () => {
  // §89's coverage is shown before the report reaches a committee, and §0's
  // disclaimer travels with it rather than living only in the file.
  const source = page();
  assert.ok(source.includes("built.coverage.complete"));
  assert.ok(source.includes("required topics are addressed"));
  assert.ok(source.includes("built.disclaimer"));
  assert.ok(source.includes("built.not_client_data"));
  assert.ok(source.includes("does not provide regulatory certification"));
});

test("a section that was not reported shows its reason in the section list", () => {
  // §7. A blank cell in that column would read as "nothing to say".
  const source = page();
  assert.ok(source.includes("section.unavailable ? section.unavailable"));
});

test("the download link is a navigation, not a fetch-and-rename", () => {
  // §51 names the filename. Fetching the bytes and naming the file in the
  // browser would put that decision in two places.
  const client = read("lib/api.ts");
  assert.ok(client.includes("scorecardReportDownloadUrl:"));
  const page_source = page();
  assert.ok(page_source.includes("href={api.scorecardReportDownloadUrl("));
});
