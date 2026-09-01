import assert from "node:assert/strict";
import { test } from "node:test";

import {
  borrower360Href,
  borrowerFrom,
  normalisePeriod,
  periodForUrl,
  periodFrom,
} from "../borrower-link.ts";

/**
 * R2 §4: an Early Warning row opens the borrower it names, at the quarter the
 * signal fired in, in the same tab, without a second search.
 */

test("the link carries the borrower and the period", () => {
  assert.equal(
    borrower360Href("CORP-100376", "Q2 2026"),
    "/borrower-360?customer_id=CORP-100376&period=Q2-2026",
  );
});

test("a link with no period does not ask for a quarter called nothing", () => {
  assert.equal(borrower360Href("CORP-1"), "/borrower-360?customer_id=CORP-1");
  assert.equal(borrower360Href("CORP-1", ""), "/borrower-360?customer_id=CORP-1");
  assert.equal(borrower360Href("CORP-1", null), "/borrower-360?customer_id=CORP-1");
});

test("no borrower means the landing table, not a broken query", () => {
  assert.equal(borrower360Href(""), "/borrower-360");
  assert.equal(borrower360Href("   "), "/borrower-360");
});

test("a borrower id that needs escaping is escaped", () => {
  assert.equal(
    borrower360Href("CORP 1/2", "Q1 2025"),
    "/borrower-360?customer_id=CORP+1%2F2&period=Q1-2025",
  );
});

test("the period survives the round trip", () => {
  const href = borrower360Href("CORP-100376", "Q2 2026");
  const params = new URLSearchParams(href.split("?")[1]);
  assert.equal(borrowerFrom(params), "CORP-100376");
  assert.equal(periodFrom(params), "Q2 2026");
});

test("both period spellings are read as the same quarter", () => {
  for (const spelling of ["Q2-2026", "Q2 2026", "Q2_2026", "q2-2026"]) {
    assert.equal(normalisePeriod(spelling), "Q2 2026", spelling);
  }
});

test("a year-first period is understood too", () => {
  assert.equal(normalisePeriod("2026-Q2"), "Q2 2026");
});

test("something that is not a quarter is left alone", () => {
  assert.equal(normalisePeriod("FY2026"), "FY2026");
  assert.equal(normalisePeriod(""), "");
  assert.equal(normalisePeriod(null), "");
});

test("the url spelling has no spaces to be mangled", () => {
  assert.equal(periodForUrl("Q4 2025"), "Q4-2025");
  assert.equal(periodForUrl(""), "");
});

test("the older parameter name still opens the borrower", () => {
  const params = new URLSearchParams("borrower=CORP-9&period=Q1-2024");
  assert.equal(borrowerFrom(params), "CORP-9");
  assert.equal(periodFrom(params), "Q1 2024");
});

test("the mandated name wins where both are present", () => {
  const params = new URLSearchParams("customer_id=CORP-1&borrower=CORP-2");
  assert.equal(borrowerFrom(params), "CORP-1");
});

test("no params at all is a plain visit", () => {
  assert.equal(borrowerFrom(null), "");
  assert.equal(periodFrom(null), "");
  assert.equal(borrowerFrom(new URLSearchParams("")), "");
  assert.equal(periodFrom(new URLSearchParams("")), "");
});
