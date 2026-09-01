import assert from "node:assert/strict";
import { test } from "node:test";

import {
  money,
  NOTHING,
  showMovement,
  showValue,
} from "../early-warning-format.ts";

/**
 * R2 §3. "Value 75.4" is four characters and no information. Every one of
 * these asserts what a credit officer would read off the screen.
 */

test("money is riyals, in millions, never bare", () => {
  assert.equal(showValue(75.4, "money"), "SAR 75.4m");
  assert.equal(showValue(150, "money"), "SAR 150.0m");
});

test("money becomes billions when the millions stop reading", () => {
  assert.equal(showValue(1200, "money"), "SAR 1.2bn");
  assert.equal(showValue(48600, "money"), "SAR 48.6bn");
});

test("a negative amount keeps its sign", () => {
  assert.equal(showValue(-75.4, "money"), "SAR -75.4m");
});

test("a very small amount does not round to nothing", () => {
  assert.equal(money(0.04), "SAR 0.04m");
});

test("another deployment's currency is not renamed to riyals", () => {
  assert.equal(showValue(75.4, "money", "USD"), "USD 75.4m");
});

test("a percentage is a percentage", () => {
  assert.equal(showValue(12.42, "percent"), "12.4%");
  assert.equal(showValue(-5, "percent"), "-5.0%");
});

test("a multiple is a multiple, not a percentage", () => {
  // A covenant written as "minimum DSCR 1.25x" is not "minimum DSCR 125%".
  assert.equal(showValue(1.25, "ratio"), "1.25x");
  assert.equal(showValue(4, "ratio"), "4.00x");
});

test("days are counted, and one day is singular", () => {
  assert.equal(showValue(45, "days"), "45 days");
  assert.equal(showValue(1, "days"), "1 day");
  assert.equal(showValue(90.4, "days"), "90 days");
});

test("notches are counted the same way", () => {
  assert.equal(showValue(2, "notches"), "2 notches");
  assert.equal(showValue(1, "notches"), "1 notch");
});

test("a stage is named, not left as a number", () => {
  assert.equal(showValue(2, "stage"), "Stage 2");
});

test("a flag is yes or no", () => {
  assert.equal(showValue(true, "flag"), "Yes");
  assert.equal(showValue(false, "flag"), "No");
  assert.equal(showValue("true", "flag"), "Yes");
});

test("nothing is nothing, and zero is not nothing", () => {
  assert.equal(showValue(null, "money"), NOTHING);
  assert.equal(showValue(undefined, "percent"), NOTHING);
  assert.equal(showValue("", "days"), NOTHING);
  assert.equal(showValue(0, "money"), "SAR 0.0m");
  assert.equal(showValue(0, "percent"), "0.0%");
});

test("an unknown unit is a plain number, not a guessed currency", () => {
  assert.equal(showValue(12.5, "board_meetings"), "12.5");
  assert.equal(showValue(12.5, null), "12.5");
});

test("a value that is not a number survives as itself", () => {
  assert.equal(showValue("Watchlist", "count"), "Watchlist");
});

test("a movement is signed", () => {
  assert.equal(showMovement(8.2, "percent"), "+8.2 points");
  assert.equal(showMovement(-8.2, "percent"), "−8.2 points");
});

test("a movement in a percentage is in POINTS", () => {
  // "utilisation rose 8%" and "utilisation rose 8 points" are different
  // claims, and only one of them is what the signal measured.
  assert.equal(showMovement(8, "percent"), "+8.0 points");
});

test("a movement in money is money", () => {
  assert.equal(showMovement(-12.5, "money"), "−SAR 12.5m");
});

test("a movement in days or notches is counted", () => {
  assert.equal(showMovement(15, "days"), "+15 days");
  assert.equal(showMovement(-1, "notches"), "−1 notch");
});

test("a flag and a stage do not have a movement", () => {
  assert.equal(showMovement(1, "flag"), NOTHING);
  assert.equal(showMovement(1, "stage"), NOTHING);
});

test("no movement is not a movement of zero", () => {
  assert.equal(showMovement(null, "percent"), NOTHING);
  assert.equal(showMovement(undefined, "money"), NOTHING);
});
