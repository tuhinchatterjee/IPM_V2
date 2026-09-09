import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { chartFor, showsChart, worthDrawing } from "../chart-rules.ts";

describe("when an Early Warning answer earns a chart", () => {
  it("draws the answers that are about shape", () => {
    assert.equal(chartFor("portfolio"), "trend");
    assert.equal(chartFor("movement"), "movement");
    assert.equal(chartFor("level"), "comparison");
    assert.equal(chartFor("group"), "distribution");
    assert.equal(chartFor("diagnosis"), "distribution");
  });

  it("withholds one from a methodology explanation", () => {
    // A bar chart beside an explanation of the notch model invites the
    // reader to look for a pattern in something that has none.
    assert.equal(showsChart("methodology"), false);
  });

  it("withholds one from an evidence request", () => {
    // One signal's reading is a single point. Drawing it says nothing.
    assert.equal(showsChart("evidence"), false);
  });

  it("withholds one from a recommendation", () => {
    // A chart beside an action competes with the action for attention.
    assert.equal(showsChart("action"), false);
  });

  it("withholds one from an escalation decision", () => {
    assert.equal(showsChart("escalation"), false);
  });

  it("withholds one from a refusal and from nothing at all", () => {
    assert.equal(showsChart("refusal"), false);
    assert.equal(showsChart(""), false);
  });

  it("does not draw a trend across two points", () => {
    // Two months is a pair of numbers; drawing it implies a shape the data
    // cannot support.
    assert.equal(worthDrawing("trend", 2), false);
    assert.equal(worthDrawing("trend", 3), true);
  });

  it("needs at least two groups to compare", () => {
    assert.equal(worthDrawing("comparison", 1), false);
    assert.equal(worthDrawing("comparison", 2), true);
  });

  it("never draws when no kind was chosen", () => {
    assert.equal(worthDrawing(null, 100), false);
  });
});
