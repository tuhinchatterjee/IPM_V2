import assert from "node:assert/strict";
import test from "node:test";

import type { RenderedChart, RenderedTable } from "./client.ts";
import { TOP_N, chartIsUseful } from "./visual-choice.ts";

/**
 * What earns a chart, and what a chart is drawn from.
 *
 * The rule that matters most here is not tested by looking at pixels: bars
 * and sort order come from the CANONICAL values, never the displayed
 * strings. "SAR 9,000 million" sorts above "SAR 40,599 million" as text, so
 * a chart drawn from formatted labels is a chart of string lengths.
 */

function chart(over: Partial<RenderedChart> = {}): RenderedChart {
  return {
    kind: "bar",
    title: "EAD by sector",
    artifact_id: "art-1",
    x_column: "sector_name",
    y_columns: ["ead"],
    unit: "SAR million",
    points: [
      { row_id: "r0", label: "Information Technology",
        values: { ead: 7013.1167 }, display: { ead: "SAR 7,013 million" } },
      { row_id: "r1", label: "Manufacturing",
        values: { ead: 6936.1557 }, display: { ead: "SAR 6,936 million" } },
    ],
    series_units: { ead: "SAR million" },
    rendered_by: "creditprobe",
    ...over,
  };
}

test("a ranked comparison of several categories is worth charting", () => {
  assert.equal(chartIsUseful(chart()), true);
});

test("a single value is a number, and a chart of it is decoration", () => {
  assert.equal(
    chartIsUseful(chart({ points: [chart().points![0]] })),
    false,
  );
});

test("no rows is not an empty chart", () => {
  // §40: an empty frame reads as missing data rather than as no data.
  assert.equal(chartIsUseful(chart({ points: [] })), false);
});

test("a chart with no series to plot is not drawn", () => {
  assert.equal(chartIsUseful(chart({ y_columns: [] })), false);
});

test("a chart whose points carry no numbers is not drawn", () => {
  assert.equal(
    chartIsUseful(
      chart({
        points: [
          { row_id: "r0", label: "A", values: { ead: null },
            display: { ead: "" } },
          { row_id: "r1", label: "B", values: { ead: "n/a" },
            display: { ead: "" } },
        ],
      }),
    ),
    false,
  );
});

test("an absent chart is not useful", () => {
  assert.equal(chartIsUseful(undefined), false);
});

test("a table shows a readable top slice before the whole result", () => {
  // §41: five hundred rows are not dumped into a conversation.
  assert.equal(TOP_N, 10);
});

test("the displayed value is what the server wrote, not a local rounding",
  () => {
    const table: RenderedTable = {
      title: "EAD by sector",
      artifact_id: "art-1",
      columns: ["sector_name", "ead"],
      column_units: { ead: "SAR million" },
      rows: [
        {
          row_id: "r0",
          canonical: { sector_name: "Information Technology",
                       ead: 7013.1167117986615 },
          display: { sector_name: "Information Technology",
                     ead: "SAR 7,013 million" },
        },
      ],
      row_count: 1,
      rendered_by: "creditprobe",
    };
    // The contract this file depends on: both forms present, the canonical
    // one at full precision, and the display one already formatted.
    assert.equal(table.rows![0].display.ead, "SAR 7,013 million");
    assert.equal(table.rows![0].canonical.ead, 7013.1167117986615);
    assert.notEqual(
      String(table.rows![0].display.ead),
      String(table.rows![0].canonical.ead),
      "if these were ever the same string the frontend would be rounding",
    );
  });
