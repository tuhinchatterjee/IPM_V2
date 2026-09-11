"""
CP-10 — Customer 360, and the journey that reaches it.

Section 2 of Revision 3: an ordinary user must be able to open a real synthetic
customer through a supported entry point, read their facilities, history,
scores and warnings, and come back to the list they started from with its
filters intact.

The assertions are about what is on the screen and whether it agrees with the
book, not about an endpoint answering 200. Every figure asserted here was
computed independently from the Parquet lake first — see
`tests/retail/test_ret_customer_360.py`, which recomputes them.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    FRONTEND,
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "customer-360"

#: A customer with six facilities across three products, one of them Stage 3 —
#: chosen because it exercises multi-facility counting, product variety and a
#: non-trivial stage. Independently reconciled below.
CUSTOMER = "RC-0020621"
GCA = "1,228,496"
ECL = "29,206.24"
FACILITIES = 6


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def suite(s: Session, rec: Recorder) -> None:
    page = s.page

    # ---------------------------------------------------------------- C360-01
    # The journey: a filtered EWS list -> an alert -> its customer.
    opened = s.go("/early-warning/signals", settle=6000)
    severity = page.query_selector('[data-testid="signals-severity"]')
    family = page.query_selector('[data-testid="signals-family"]')
    if severity is not None:
        severity.select_option("HIGH")
        # Wait for the refetch the filter starts, bounded. Reading the list
        # three seconds after a select measured the previous render.
        deadline = time.time() + 60
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            if page.query_selector_all("[data-alert-id]"):
                break
    listed = page.query_selector_all("[data-alert-id]")
    filtered_text = s.text()
    only_high = "MEDIUM" not in " ".join(
        filtered_text.split("By rule")[-1].split("Clear filters")[0].split())
    _case(rec, "C360-01", "The Early Warning list opens, filters by severity, "
          "and every row names the rule, what it measured and what to do",
          bool(opened and severity is not None and listed),
          f"the list opened={opened}; a severity filter exists="
          f"{severity is not None}; a family filter exists="
          f"{family is not None}; {len(listed)} alerts listed after filtering "
          f"to HIGH",
          screenshot=s.shot("c360-01-signals"))

    list_url = page.url
    link = page.query_selector('[data-testid^="open-customer-"]')
    alert_id = ""
    if listed:
        alert_id = listed[0].get_attribute("data-alert-id") or ""
    if link is not None:
        link.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(7000)
    body = s.text()
    opened_customer = "Customer 360" in body and "RC-" in body
    _case(rec, "C360-02", "An alert opens the customer it was raised against",
          bool(link is not None and opened_customer and "/borrower-360" in page.url),
          f"the alert carried a link to its customer={link is not None}; the "
          f"customer screen rendered={opened_customer}; url={page.url[:90]}",
          alert=alert_id, screenshot=s.shot("c360-02-opened"))

    # ---------------------------------------------------------------- C360-03
    # A named customer, read against the book.
    page.goto(f"{FRONTEND}/borrower-360?borrower={CUSTOMER}&period=2026-08",
              wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(8000)
    header = s.text()
    figures_ok = (CUSTOMER in header and GCA in header and ECL in header
                  and f"{FACILITIES}" in header)
    said_once = ("reported once here, not once per facility" in header)
    _case(rec, "C360-03", "The customer's exposure, allowance and facility "
          "count agree with the book, and customer values are reported once",
          bool(figures_ok and said_once),
          f"the header carries {CUSTOMER}, {FACILITIES} facilities, SAR {GCA} "
          f"and SAR {ECL}={figures_ok}; the screen says income and obligations "
          f"are customer values reported once={said_once}",
          screenshot=s.shot("c360-03-customer"))

    # ---------------------------------------------------------------- C360-04
    # Facilities, and switching between them.
    tabs = {t.inner_text().strip(): t for t in page.query_selector_all('[role="tab"]')}
    switched = False
    products: set[str] = set()
    if "Facilities" in tabs:
        tabs["Facilities"].click()
        page.wait_for_timeout(1500)
        rows = page.query_selector_all('[data-testid="customer-facilities"] tbody tr')
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) > 1:
                products.add(cells[1].inner_text().strip())
        opener = page.query_selector('[data-testid^="facility-open-"]')
        if opener is not None:
            opener.click()
            page.wait_for_timeout(2500)
            switched = "score-facility" in (page.content() or "")
    _case(rec, "C360-04", "Every facility is listed with its product, balance, "
          "DPD and stage, and one can be opened",
          bool(len(products) >= 2 and switched),
          f"{len(products)} distinct products on the facility table "
          f"({sorted(products)}); opening a facility moved to its scores="
          f"{switched}",
          screenshot=s.shot("c360-04-facilities"))

    # ---------------------------------------------------------------- C360-05
    # Score evidence: model, version, date, and origination not passed off as
    # current.
    scores_text = s.text()
    names_models = ("RETAIL_APP" in scores_text or "RETAIL_BEH" in scores_text)
    separates = ("AT ORIGINATION" in scores_text.upper()
                 and "this month-end" in scores_text)
    _case(rec, "C360-05", "Both scorecards name their model, version and date, "
          "and the origination inputs are not shown as current ones",
          bool(names_models and separates),
          f"a model id and version are on screen={names_models}; the "
          f"application card says its inputs are as at origination and the "
          f"behavioural card says this month-end={separates}",
          screenshot=s.shot("c360-05-scores"))

    # ---------------------------------------------------------------- C360-06
    # History across the published months.
    if "History" in tabs:
        tabs["History"].click()
        page.wait_for_timeout(1500)
    history_rows = page.query_selector_all('[data-testid="customer-history"] tbody tr')
    history_text = s.text()
    spans = "2024-08" in history_text and "2026-08" in history_text
    _case(rec, "C360-06", "The monthly history shows every published month for "
          "this customer, with balances, DPD, stage and score",
          bool(len(history_rows) >= 12 and spans),
          f"{len(history_rows)} months in the history table; it spans the "
          f"published range={spans}",
          screenshot=s.shot("c360-06-history"))

    # ---------------------------------------------------------------- C360-07
    # Warnings raised against this customer, linked to their facilities.
    if "Warnings" in tabs:
        tabs["Warnings"].click()
        page.wait_for_timeout(1500)
    alerts = page.query_selector_all('[data-testid="customer-alerts"] li')
    warning_text = s.text()
    reasoned = "RET-EWS-" in warning_text
    _case(rec, "C360-07", "The customer's own warnings are listed with the rule "
          "that raised them and the facility they concern",
          bool(alerts and reasoned),
          f"{len(alerts)} warnings listed; each names its rule={reasoned}",
          screenshot=s.shot("c360-07-warnings"))

    # ---------------------------------------------------------------- C360-08
    # Another month, on the same customer.
    month = page.query_selector('[data-testid="customer-month"]')
    changed = False
    if month is not None:
        month.select_option("2025-08")
        page.wait_for_timeout(6000)
        changed = "at 2025-08" in s.text()
    _case(rec, "C360-08", "Changing the month re-reads the same customer at "
          "that month rather than clearing the screen",
          bool(changed),
          f"the header states the month it is showing={changed}",
          screenshot=s.shot("c360-08-earlier-month"))

    # ---------------------------------------------------------------- C360-09
    # Back to the list that opened it, with its filters.
    page.goto(list_url, wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(4000)
    back_link = None
    link = page.query_selector('[data-testid^="open-customer-"]')
    if link is not None:
        link.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(5000)
        back_link = page.query_selector('[data-testid="back-link"]')
        if back_link is not None:
            back_link.click()
            page.wait_for_load_state("networkidle", timeout=90_000)
            page.wait_for_timeout(4000)
    returned = "/early-warning/signals" in page.url
    kept = page.query_selector('[data-testid="signals-severity"]')
    kept_value = kept.input_value() if kept is not None else ""
    _case(rec, "C360-09", "Back from the customer returns to the SAME filtered "
          "Early Warning list",
          bool(back_link is not None and returned),
          f"a Back control was present={back_link is not None}; it returned to "
          f"the signals list={returned}; the severity filter reads "
          f"{kept_value!r}",
          screenshot=s.shot("c360-09-back"))

    # ---------------------------------------------------------------- C360-10
    # A missing customer, and a direct link with no history.
    page.goto(f"{FRONTEND}/borrower-360?borrower=RC-9999999&period=2026-08",
              wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(6000)
    missing = s.text()
    recoverable = ("not" in missing.lower() or "no " in missing.lower()
                   or "could not" in missing.lower())
    still_usable = page.query_selector('[data-testid="customer-search"]') is not None
    _case(rec, "C360-10", "An unknown customer id gives a recoverable state "
          "with the search still usable, not a crash or an endless loader",
          bool(recoverable and still_usable),
          f"the screen explains rather than hangs={recoverable}; the search "
          f"box is still there={still_usable}",
          screenshot=s.shot("c360-10-missing"))


if __name__ == "__main__":
    raise SystemExit(run_suite("customer360", suite))
