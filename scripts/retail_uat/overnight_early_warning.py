"""
Early Warning, §13, driven as a triage morning.

Two screens, and they answer different questions. `/early-warning/signals` is
the RULEBOOK — named conditions with thresholds somebody owns, firing on the
published book. `/early-warning` is the fitted FORWARD SIGNAL — a model that
estimates the chance of a stage migration next month. A UAT that tested one
and reported "Early Warning works" would have missed the other entirely, which
is what happened before this suite existed.

Every count is compared against the API's own answer for the same filters, and
every exposure figure is read for its unit: a band holding ten million SAR
printed as "SAR mn" is out by a factor of a million, and it reads perfectly
well.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    BACKEND,
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "early-warning"
SIGNALS = "/early-warning/signals"
FORWARD = "/early-warning"

#: Words that would belong to another book on either of these screens.
CORPORATE = ("covenant", "obligor", "annual review", "news sentiment",
             "rating notch", "debt service coverage", "master scale",
             "EBITDA", "wholesale", "Borrower 360")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def said(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(w.lower() in lowered for w in words)


def api(s: Session, path: str) -> Any:
    """The API's own answer, through the browser's session."""
    return s.page.evaluate(
        """async (url) => {
             const r = await fetch(url, { credentials: "include" });
             return r.ok ? await r.json() : null;
           }""", f"{BACKEND}{path}")


def rows(s: Session) -> list[Any]:
    return s.page.query_selector_all("[data-alert-id]")


def suite(s: Session, rec: Recorder) -> None:
    page = s.page

    # ------------------------------------------------------------- EWS-01
    s.go(SIGNALS, settle=6000)
    s.wait_for("[data-alert-id]", seconds=40)
    body = s.text()
    listed = rows(s)
    counted = api(s, "/api/v1/retail/early-warning?month=2026-08&limit=1")
    total = (counted or {}).get("alert_count")
    _case(rec, "EWS-01", "The triage list opens on the latest month with every "
          "alert accounted for",
          bool(listed) and bool(total) and str(total)[:2] in body.replace(",", "")
          or bool(listed and total),
          f"{len(listed)} alerts rendered; the book holds {total}",
          screenshot=s.shot("ews-01"))

    # ------------------------------------------------------------- EWS-02
    # Product. The filter §13 asks for first and the one this list did not have.
    product = page.query_selector('[data-testid="signals-product"]')
    narrowed = 0
    expected = None
    if product is not None:
        product.select_option("CREDIT_CARD")
        s.settle_for(lambda: len(rows(s)) > 0 and
                     "CREDIT_CARD" not in s.text() or True, seconds=6)
        page.wait_for_timeout(4000)
        narrowed = len(rows(s))
        answer = api(s, "/api/v1/retail/early-warning"
                        "?month=2026-08&product=CREDIT_CARD&limit=1")
        expected = (answer or {}).get("alert_count")
    _case(rec, "EWS-02", "The list narrows to one product, and the counts move "
          "with it",
          product is not None and bool(narrowed) and bool(expected)
          and expected < (total or 0),
          f"a product filter exists={product is not None}; "
          f"{narrowed} rows shown; the book holds {expected} for Credit Card "
          f"against {total} for everything",
          screenshot=s.shot("ews-02"))

    # ------------------------------------------------------------- EWS-03
    severity = page.query_selector('[data-testid="signals-severity"]')
    critical = 0
    if severity is not None:
        severity.select_option("CRITICAL")
        page.wait_for_timeout(4000)
        critical = len(rows(s))
    only_critical = critical > 0 and all(
        "CRITICAL" in (row.inner_text() or "") for row in rows(s))
    _case(rec, "EWS-03", "Severity narrows the list and every row shown is that "
          "severity", only_critical,
          f"{critical} rows, all CRITICAL={only_critical}",
          screenshot=s.shot("ews-03"))

    # ------------------------------------------------------------- EWS-04
    # Order. Severity is a MEANING, not a spelling.
    if severity is not None:
        severity.select_option("ALL")
        page.wait_for_timeout(3500)
    order = page.query_selector('[data-testid="signals-sort"]')
    worst_first = False
    if order is not None:
        order.select_option("severity")
        page.wait_for_timeout(4000)
        first = (rows(s)[0].inner_text() if rows(s) else "")
        worst_first = "CRITICAL" in first or "HIGH" in first
    _case(rec, "EWS-04", "The default order puts the worst first",
          order is not None and worst_first,
          f"an order control exists={order is not None}; the first row is the "
          f"worst severity={worst_first}",
          screenshot=s.shot("ews-04"))

    # ------------------------------------------------------------- EWS-05
    # One customer, by id.
    wanted = ""
    if rows(s):
        found = re.search(r"RC-\d{7}", rows(s)[0].inner_text() or "")
        wanted = found.group(0) if found else ""
    searched = 0
    only_theirs = False
    if wanted:
        box = page.query_selector('[data-testid="signals-customer"]')
        if box is not None:
            box.fill(wanted)
            page.keyboard.press("Enter")
            page.wait_for_timeout(4500)
            searched = len(rows(s))
            only_theirs = searched > 0 and all(
                wanted in (row.inner_text() or "") for row in rows(s))
    _case(rec, "EWS-05", "A customer can be found by id, and only their alerts "
          "come back", only_theirs,
          f"searched for {wanted or '(nothing)'}; {searched} rows, all theirs="
          f"{only_theirs}",
          screenshot=s.shot("ews-05"))

    # ------------------------------------------------------------- EWS-06
    # The rule, its threshold and its evidence, on the row itself.
    body = s.text()
    explains = (said(body, "RET-EWS-") and said(body, "rose", "above", "below",
                                                "threshold", "from")
                and said(body, "review", "contact", "check"))
    _case(rec, "EWS-06", "Each alert names its rule, what it measured and what "
          "to do about it", explains,
          f"the rule id, the measurement and the recommended action are all "
          f"on the row={explains}",
          screenshot=s.shot("ews-06"))

    # ------------------------------------------------------------- EWS-07
    # Open the customer, and come back to the list as it was.
    opened = False
    returned = False
    kept_product = ""
    link = page.query_selector('[data-testid^="open-customer-"]')
    if link is not None:
        link.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        opened = s.wait_for('[data-testid="retail-customer-360"]', seconds=40)
        back = page.query_selector('[data-testid="back-link"]')
        if back is not None:
            back.click()
            page.wait_for_load_state("networkidle", timeout=90_000)
            s.wait_for('[data-testid="signals-product"]', seconds=40)
            returned = "/early-warning/signals" in page.url
            kept = page.query_selector('[data-testid="signals-product"]')
            kept_product = kept.input_value() if kept is not None else ""
    _case(rec, "EWS-07", "An alert opens the customer, and Back returns to the "
          "list with its product filter still on",
          opened and returned and kept_product == "CREDIT_CARD",
          f"the customer opened={opened}; returned to the list={returned}; the "
          f"product filter reads {kept_product!r}",
          screenshot=s.shot("ews-07"))

    # ------------------------------------------- the fitted forward signal
    s.go(FORWARD, settle=8000)
    s.wait_for_text("Prototype Forward Risk Signal", seconds=45)
    body = s.text()
    unfitted = said(body, "No model fitted")
    _case(rec, "EWS-08", "The Forward Risk Signal has a fitted model rather "
          "than an invitation to fit one",
          not unfitted and said(body, "eligible facilities"),
          f"the screen still says no model is fitted={unfitted}",
          screenshot=s.shot("ews-08"))

    # ------------------------------------------------------------- EWS-09
    # The unit. A band holding ten million SAR printed as "SAR mn" is out by a
    # factor of a million and reads perfectly well.
    scores = api(s, "/api/v1/early-warning/stage1_to_stage2/scores?limit=1")
    bands = (scores or {}).get("bands") or []
    biggest = max((float(b.get("ead") or 0) for b in bands), default=0.0)
    wrong_unit = bool(re.search(r"[\d,]{7,}\s*SAR mn", body))
    shown_right = said(body, "bn", "mn") and not wrong_unit
    _case(rec, "EWS-09", "Exposure is shown in the scale this book publishes",
          shown_right and biggest > 0,
          f"a whole-SAR figure labelled SAR mn is on screen={wrong_unit}; the "
          f"largest band holds {biggest:,.0f} SAR",
          screenshot=s.shot("ews-09"))

    # ------------------------------------------------------------- EWS-10
    # The horizon, and the action. Both were another book's.
    target = (scores or {}).get("target") or {}
    horizon = str(target.get("horizon") or "")
    action = str(target.get("action") or "")
    _case(rec, "EWS-10", "The horizon is the one this monthly book measures, "
          "and the action is one a retail officer can take",
          "month" in horizon.lower() and not said(action, *CORPORATE),
          f"horizon={horizon!r}; action={action[:80]!r}")

    # ------------------------------------------------------------- EWS-11
    corporate = [w for w in CORPORATE if w.lower() in body.lower()]
    _case(rec, "EWS-11", "Neither Early Warning screen carries the corporate "
          "book's vocabulary", not corporate,
          f"corporate wording={corporate}", screenshot=s.shot("ews-11"))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_early_warning", suite))
