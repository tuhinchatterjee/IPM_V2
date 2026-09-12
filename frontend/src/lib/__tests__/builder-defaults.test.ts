import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

/**
 * The two "new" builder forms, and the dataset each one opens pre-filled with.
 *
 * Both once named the CORPORATE book: on a retail installation the Add Dataset
 * relationship target defaulted to `portfolio_facility` and the Engine Builder
 * source dataset did the same, so a steward could save a join, or build an
 * analysis, against a dataset this installation does not hold (ON-50).
 *
 * The default now comes from the governed catalogue. It is taken by DERIVING
 * it — the state holds the author's override and falls back to the catalogue —
 * rather than by seeding the state from an effect. An effect seeds one render
 * late, so the select shows blank first and a submit in that window sends an
 * empty dataset; it also fails `react-hooks/set-state-in-effect`.
 */

const root = fileURLToPath(new URL("../../", import.meta.url));
const read = (path: string) => readFileSync(root + path, "utf8");

const forms = {
  "data-builder": read("app/data-builder/new/page.tsx"),
  "engine-builder": read("app/engine-builder/new/page.tsx"),
};

// Comments removed: both files explain in a comment WHICH corporate name they
// used to carry, and a test that cannot tell an explanation from a default
// would forbid recording why the defect existed.
const code = (source: string) =>
  source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

test("neither form hard-codes a dataset name", () => {
  for (const [name, source] of Object.entries(forms)) {
    assert.ok(
      !code(source).includes("portfolio_facility"),
      `${name} names the corporate book`,
    );
  }
});

test("both read their default from the governed catalogue", () => {
  assert.ok(forms["data-builder"].includes("existingDatasets.data?.datasets?.[0]?.name"));
  assert.ok(forms["engine-builder"].includes("catalog.data?.datasets?.[0]?.name"));
});

test("the default is derived, never seeded into state by an effect", () => {
  assert.ok(forms["data-builder"].includes("relToChoice ?? firstExisting"));
  assert.ok(forms["engine-builder"].includes("datasetChoice ?? firstDataset"));
  for (const [name, source] of Object.entries(forms)) {
    assert.ok(
      !/useEffect\(\(\) => \{\s*if \(![A-Za-z]+ && [A-Za-z]+\) set/.test(source),
      `${name} still seeds its default from an effect`,
    );
  }
});

test("what the author picks wins over the catalogue default", () => {
  // The override is what the select writes to, so a chosen value is not
  // overwritten on the next render by the catalogue's first row.
  assert.ok(forms["data-builder"].includes("setRelToChoice(e.target.value)"));
  assert.ok(forms["engine-builder"].includes("setDatasetChoice(e.target.value)"));
});
