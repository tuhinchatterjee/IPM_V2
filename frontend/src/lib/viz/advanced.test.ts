import assert from "node:assert/strict";
import test from "node:test";

import { distribution, heatmap, pareto, reconcile, stageSankey, type Cell } from "./advanced.ts";

const cells: Cell[] = [
  { x: 1, y: 1, n: 90, ead_sar_mn: 900, ecl_sar_mn: 9 },
  { x: 1, y: 2, n: 8, ead_sar_mn: 80, ecl_sar_mn: 4 },
  { x: 2, y: 3, n: 2, ead_sar_mn: 20, ecl_sar_mn: 10 },
  { x: null, y: 1, n: 5, ead_sar_mn: 50, ecl_sar_mn: 1 },
];

test("VIZ08 the stage Sankey reconciles counts and EAD to the book", () => {
  const fig = stageSankey(cells);
  const link = (fig.data[0] as { link: { value: number[]; source: number[]; target: number[] } }).link;
  assert.equal(link.value.reduce((a, b) => a + b, 0), 1050);
  assert.equal(link.source.length, 4);
  assert.ok(reconcile(cells, { n: 105, ead_sar_mn: 1050 }).ok);
  assert.equal(reconcile(cells, { n: 104, ead_sar_mn: 1050 }).ok, false);
  const nodes = (fig.data[0] as { node: { label: string[] } }).node.label;
  assert.ok(nodes.includes("Prior — new"), "entities new to the book are their own source, not dropped");
});

test("VIZ12 the heatmap places every cell and leaves absent cells empty (not zero)", () => {
  const fig = heatmap(cells, "ead_sar_mn", { x: "prior", y: "stage" });
  const z = (fig.data[0] as { z: (number | null)[][] }).z;
  assert.equal(z.flat().filter((v) => v !== null).length, 4);
  assert.ok(z.flat().some((v) => v === null));
});

test("VIZ10 the Pareto ends at 100% cumulative", () => {
  const fig = pareto([
    { group: "A", change: "30", cumulative_share: "0.75" },
    { group: "B", change: "10", cumulative_share: "1.0000" },
  ]);
  const line = fig.data[1] as { y: number[] };
  assert.equal(line.y.at(-1), 100);
});

test("VIZ11 the distribution plots moved exposures and leaves the unmoved out of the bars", () => {
  const fig = distribution([
    { label: "0% to 5%", lo: 0, n: 10, ead: "100" },
    { label: "not moved by the scenario", lo: null, n: 3, ead: "30" },
  ]);
  assert.deepEqual((fig.data[0] as { x: string[] }).x, ["0% to 5%"]);
});
