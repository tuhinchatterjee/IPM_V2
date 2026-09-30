import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

/**
 * P11 inventory lock. The chart inventory (docs/guided_workspace/
 * CHART_INVENTORY.md) is only true while the code agrees with it: these
 * tests fail when a chart renderer appears that the inventory does not
 * account for, so a new non-Plotly chart -- or a Plotly chart that skips
 * the governed frame -- cannot land silently.
 */

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const DOC = path.resolve(SRC, "../../docs/guided_workspace/CHART_INVENTORY.md");

function files(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "node_modules" ? [] : files(p);
    return /\.(tsx?|mjs)$/.test(e.name) && !/\.test\.ts$/.test(e.name) ? [p] : [];
  });
}

const ALL = files(SRC).map((f) => ({ rel: path.relative(SRC, f), text: fs.readFileSync(f, "utf8") }));
const using = (re: RegExp) => ALL.filter((f) => re.test(f.text)).map((f) => f.rel).sort();

/** Legacy Recharts: reachable only with the guided flag off (or redirected). */
const RECHARTS_LEGACY = [
  "app/lenses/cro/page.tsx",
  "app/stress/page.tsx",
  "components/analytics/chart-frame.tsx",
  "components/analytics/primary-visual.tsx",
  "components/analytics/result-view.tsx",
];

/** Direct PlotlyChart use outside the governed ChartCard: sparklines only. */
const PLOTLY_DIRECT = ["components/guided/requires-attention.tsx", "components/lenses/lens-view.tsx", "components/viz/chart-card.tsx"];

test("INV01 recharts is imported in exactly one legacy module", () => {
  assert.deepEqual(using(/from ["']recharts["']/), ["components/analytics/charts.tsx"]);
});

test("INV02 only the documented legacy pages consume the Recharts building blocks", () => {
  assert.deepEqual(using(/from ["'](@\/components\/analytics\/charts|\.\/charts)["']/), RECHARTS_LEGACY);
});

test("INV03 no other chart library, and Plotly is loaded only through the one wrapper", () => {
  for (const lib of ["chart.js", "d3", "vega", "@nivo", "@visx", "echarts", "highcharts"]) {
    assert.deepEqual(using(new RegExp(`from ["']${lib.replace(/[.@/]/g, "\\$&")}["'/]`)), [], lib);
  }
  assert.deepEqual(using(/import\(["']plotly\.js-dist-min["']\)|from ["']plotly\.js-dist-min["']/), ["components/viz/plotly-chart.tsx"]);
});

test("INV04 a Plotly chart outside ChartCard is a documented sparkline", () => {
  assert.deepEqual(using(/<PlotlyChart\b/), PLOTLY_DIRECT);
});

test("INV05 every file drawing a chart is named in CHART_INVENTORY.md", () => {
  const doc = fs.readFileSync(DOC, "utf8");
  const drawing = [...new Set([...using(/<ChartCard\b/), ...using(/<PlotlyChart\b/), ...RECHARTS_LEGACY, "components/analytics/charts.tsx"])];
  const missing = drawing.filter((f) => !doc.includes(f));
  assert.deepEqual(missing, [], `undocumented chart files: ${missing.join(", ")}`);
});

test("INV06 legacy Recharts pages are gated: the guided flag redirects or swaps them", () => {
  for (const page of ["app/stress/page.tsx", "app/lenses/cro/page.tsx"]) {
    const text = ALL.find((f) => f.rel === page)?.text ?? "";
    assert.match(text, /guidedEnabled\(\)\s*\?\s*<Redirect/, page);
  }
  const lensDetail = ALL.find((f) => f.rel === "app/lenses/[lensId]/page.tsx")?.text ?? "";
  assert.match(lensDetail, /if \(!guidedEnabled\(\)\) return <LegacyLensPage/);
});
