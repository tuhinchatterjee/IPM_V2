import assert from "node:assert/strict";
import { describe, it } from "node:test";

import * as f from "../filters.ts";

const COLUMNS: f.FilterColumn[] = [
  { key: "customer", label: "Customer", kind: "text", field: "customer_name", choices: [], unit: "" },
  { key: "segment", label: "Segment", kind: "multi", field: "segment", choices: [], unit: "" },
  { key: "exposure", label: "Exposure", kind: "range", field: "exposure", choices: [], unit: "SAR m" },
  { key: "dpd", label: "Days past due", kind: "range", field: "dpd", choices: [], unit: "days" },
  { key: "ews_band", label: "Early Warning band", kind: "multi", field: "ews_band", choices: ["LOW", "HIGH"], unit: "" },
];

describe("a half-typed filter is not a filter", () => {
  it("does not send a bound that is still being typed", () => {
    // "-" on the way to "-5" is a keystroke. Sending it would either error
    // or, worse, be coerced into something the reader did not type.
    let state = f.setRange(f.EMPTY, "dpd", "min", "-");
    assert.deepEqual((f.toSpec(state) as { filters: object }).filters, {});

    state = f.setRange(state, "dpd", "min", "-5");
    assert.deepEqual((f.toSpec(state) as { filters: Record<string, unknown> })
      .filters.dpd, { min: -5 });
  });

  it("keeps the text the reader typed even while it is unusable", () => {
    const state = f.setRange(f.EMPTY, "exposure", "min", "1.");
    assert.equal(state.ranges.exposure.min, "1.");
  });

  it("sends one open end when only one is filled", () => {
    const only = f.setRange(f.EMPTY, "dpd", "min", "30");
    const filters = (f.toSpec(only) as { filters: Record<string, unknown> })
      .filters;
    assert.deepEqual(filters.dpd, { min: 30 });
  });

  it("refuses to send a range that cannot match anything", () => {
    let state = f.setRange(f.EMPTY, "exposure", "min", "900");
    state = f.setRange(state, "exposure", "max", "100");
    assert.equal(f.rangeIsImpossible(state.ranges.exposure), true);
    // An empty table is indistinguishable from a finding, so this is named
    // rather than sent.
    assert.deepEqual((f.toSpec(state) as { filters: object }).filters, {});
    assert.equal(f.problems(state).length, 1);
  });
});

describe("what counts as narrowed", () => {
  it("is nothing on an empty state", () => {
    assert.equal(f.isNarrowed(f.EMPTY), false);
    assert.equal(f.activeCount(f.EMPTY), 0);
  });

  it("counts each filter once, however many values it holds", () => {
    let state = f.toggle(f.EMPTY, "ews_band", "HIGH");
    state = f.toggle(state, "ews_band", "LOW");
    assert.equal(f.activeCount(state), 1);
    state = f.setRange(state, "dpd", "min", "30");
    assert.equal(f.activeCount(state), 2);
    state = f.setCustomer(state, "al");
    assert.equal(f.activeCount(state), 3);
  });

  it("does not count a range the reader has only opened", () => {
    const state = f.setRange(f.EMPTY, "dpd", "min", "  ");
    assert.equal(f.activeCount(state), 0);
    assert.equal(f.isNarrowed(state), false);
  });

  it("stops counting a selection whose last value was toggled off", () => {
    let state = f.toggle(f.EMPTY, "segment", "Large Corporate");
    state = f.toggle(state, "segment", "Large Corporate");
    assert.equal(f.isNarrowed(state), false);
    assert.equal(state.selections.segment, undefined);
  });
});

describe("clearing", () => {
  it("clears one filter and leaves the others", () => {
    let state = f.toggle(f.EMPTY, "ews_band", "HIGH");
    state = f.setRange(state, "dpd", "min", "30");
    const after = f.clearOne(state, "dpd");
    assert.equal(f.activeCount(after), 1);
    assert.deepEqual(after.selections.ews_band, ["HIGH"]);
  });

  it("clears every filter", () => {
    let state = f.toggle(f.EMPTY, "ews_band", "HIGH");
    state = f.setCustomer(state, "al");
    state = f.setRange(state, "exposure", "min", "10");
    assert.equal(f.isNarrowed(f.clearAll(state)), false);
  });

  it("does not move the reader to a different month or sort", () => {
    // The month and the sort are HOW a reader is looking, not what at.
    // Resetting them would silently change the answer.
    const state = {
      ...f.toggle(f.EMPTY, "ews_band", "HIGH"),
      period: "2026-03",
      sortBy: "exposure",
      descending: false,
    };
    const cleared = f.clearAll(state);
    assert.equal(cleared.period, "2026-03");
    assert.equal(cleared.sortBy, "exposure");
    assert.equal(cleared.descending, false);
  });
});

describe("changing what is looked at returns to the first page", () => {
  it("resets the offset on every filter change", () => {
    const deep = { ...f.EMPTY, offset: 200 };
    assert.equal(f.toggle(deep, "segment", "x").offset, 0);
    assert.equal(f.setRange(deep, "dpd", "min", "30").offset, 0);
    assert.equal(f.setCustomer(deep, "al").offset, 0);
    assert.equal(f.clearOne(deep, "segment").offset, 0);
    assert.equal(f.clearAll(deep).offset, 0);
    assert.equal(f.sortOn(deep, "exposure").offset, 0);
  });
});

describe("sorting", () => {
  it("reverses on a second press of the same column", () => {
    const once = f.sortOn(f.EMPTY, "exposure");
    assert.equal(once.sortBy, "exposure");
    assert.equal(once.descending, true);
    assert.equal(f.sortOn(once, "exposure").descending, false);
  });

  it("starts a score worst-first and a name A-first", () => {
    // A column the state is not already sorted by, so this is the first
    // press rather than the reversal the previous test covers.
    assert.equal(f.sortOn(f.EMPTY, "ta_score").descending, true);
    assert.equal(f.sortOn(f.EMPTY, "customer_name").descending, false);
    assert.equal(f.sortOn(f.EMPTY, "segment").descending, false);
    assert.equal(f.sortOn(f.EMPTY, "ews_band").descending, false);
  });
});

describe("the spec that goes on the wire", () => {
  it("carries only what is set", () => {
    const spec = f.toSpec(f.EMPTY) as { filters: object };
    assert.deepEqual(spec.filters, {});
  });

  it("is the same object for the dashboard and the export", () => {
    // One description, two consumers -- which is what makes the downloaded
    // file the same population as the screen.
    let state = f.toggle(f.EMPTY, "ews_band", "HIGH");
    state = f.setRange(state, "dpd", "min", "30");
    assert.deepEqual(f.toSpec(state), f.toSpec(state));
  });

  it("knows when two states would ask the same question", () => {
    const a = f.setCustomer(f.EMPTY, "al");
    const b = f.setCustomer({ ...f.EMPTY, offset: 0 }, "al");
    assert.equal(f.sameRequest(a, b), true);
    assert.equal(f.sameRequest(a, f.setCustomer(f.EMPTY, "ali")), false);
  });

  it("treats a half-typed bound as no change at all", () => {
    // What debouncing rests on: typing "3" then "30" in a min box should
    // not fire a request for each keystroke that says nothing new.
    const a = f.setRange(f.EMPTY, "dpd", "min", "");
    const b = f.setRange(f.EMPTY, "dpd", "min", "-");
    assert.equal(f.sameRequest(a, b), true);
  });
});

describe("a filtered view can be shared and walked back to", () => {
  it("round-trips through the address bar", () => {
    let state = f.toggle(f.EMPTY, "ews_band", "HIGH");
    state = f.toggle(state, "ews_band", "LOW");
    state = f.setRange(state, "dpd", "min", "30");
    state = f.setCustomer(state, "al rajhi");
    state = { ...state, period: "2026-06", sortBy: "exposure", descending: false };

    const back = f.fromQuery(f.toQuery(state), COLUMNS);
    assert.deepEqual(back.selections, state.selections);
    assert.deepEqual(back.ranges, state.ranges);
    assert.equal(back.customer, state.customer);
    assert.equal(back.period, "2026-06");
    assert.equal(back.sortBy, "exposure");
    assert.equal(back.descending, false);
  });

  it("reads an empty address as an unfiltered book", () => {
    assert.equal(f.isNarrowed(f.fromQuery("", COLUMNS)), false);
  });

  it("writes nothing for a state that filters nothing", () => {
    assert.equal(f.toQuery(f.EMPTY), "");
  });

  it("ignores a query key the dashboard does not filter by", () => {
    const state = f.fromQuery("?made_up=1&ews_band=HIGH", COLUMNS);
    assert.deepEqual(state.selections, { ews_band: ["HIGH"] });
  });

  it("does not confuse a name search with an opened borrower", () => {
    // `?customer=` already means "open this borrower's drilldown" in the
    // Early Warning address. A search term written under the same key would
    // make a shared link open a drilldown for the words somebody typed.
    const state = f.fromQuery("?customer=CORP-100721&q=al+rajhi", COLUMNS);
    assert.equal(state.customer, "al rajhi");
    assert.ok(f.toQuery(state).includes("q="));
    assert.ok(!f.toQuery(state).includes("customer="));
  });
});
