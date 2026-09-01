import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NEUTRAL_ACKNOWLEDGEMENT,
  WANTS_DETAIL,
  figure,
  opensDetail,
  safeAcknowledgement,
  summarise,
} from "../present.ts";

test("only PARTLY and NO open the detail panel", () => {
  assert.equal(opensDetail("PARTLY"), true);
  assert.equal(opensDetail("NO"), true);
  for (const rating of ["YES", "NOT_SURE", "SKIP"]) {
    assert.equal(opensDetail(rating), false, rating);
  }
});

test("a YES never opens a what-went-wrong panel", () => {
  // Asking somebody to justify agreeing is how a positive rating becomes a
  // chore and stops being given.
  assert.equal(opensDetail("YES", ["PARTLY", "NO"]), false);
});

test("the server's list wins where it has one", () => {
  assert.equal(opensDetail("NOT_SURE", ["NOT_SURE"]), true);
  assert.equal(opensDetail("NO", ["NOT_SURE"]), false);
});

test("the fallback list is the two ratings that carry a claim", () => {
  assert.deepEqual([...WANTS_DETAIL], ["PARTLY", "NO"]);
});

test("an acknowledgement that promises learning is not shown", () => {
  for (const said of [
    "Thank you — CreditProbe has learned this.",
    "Got it, I will remember that.",
    "Thanks, the model has been retrained.",
  ]) {
    assert.equal(safeAcknowledgement(said), NEUTRAL_ACKNOWLEDGEMENT, said);
  }
});

test("an honest acknowledgement is shown as written", () => {
  const said =
    "Thank you. This is recorded against the exact run, and goes to review.";
  assert.equal(safeAcknowledgement(said), said);
});

test("an empty acknowledgement stays empty rather than becoming a thank you", () => {
  assert.equal(safeAcknowledgement(""), "");
});

test("a row is summarised by the fields worth scanning", () => {
  const found = summarise({
    rating: "NO",
    question: "What is total ECL?",
    irrelevant: "x",
  });

  assert.match(found, /rating/);
  assert.match(found, /question/);
  assert.doesNotMatch(found, /irrelevant/);
});

test("a row with no known field is shown whole rather than blank", () => {
  // A silent empty row is how a new object type becomes invisible.
  const found = summarise({ something_new: 42 });

  assert.match(found, /something_new/);
  assert.match(found, /42/);
});

test("an empty row still renders something", () => {
  assert.equal(summarise({}).trim(), "{}");
});

test("a metric that was never measured is not shown as zero", () => {
  assert.equal(figure(null), "not measured");
  assert.equal(figure(undefined), "not measured");
  assert.equal(figure(0), "0");
  assert.equal(figure(93.3, "%"), "93.3%");
});
