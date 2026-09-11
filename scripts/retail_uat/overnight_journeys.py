"""
§23 — the four journeys a Head of Retail Risk actually walks, end to end.

Not four screens visited in turn. Each journey starts with a question, follows
what the answer says, drills into the evidence, comes back, and ends with
something a person would do with it: an investigation, a share, a message, an
export. A module that works on its own and loses the thread when you arrive
from another one is the failure this section exists to catch.

Everything destructive uses records this suite creates. The disposable
recipients are the `uat.` accounts, never a seeded user and never an external
address.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    BACKEND,
    COCKPIT_COMPOSER,
    FAIL,
    PASS,
    SCORECARD_COMPOSER,
    WHATIF_COMPOSER,
    Case,
    Recorder,
    Session,
    run_suite,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE = json.loads(
    (ROOT / "docs" / "evidence" / "retail_overnight_uat" / "oracles"
     / "retail_oracle.json").read_text())

MODULE = "journeys"
BOOK_ECL = ORACLE["book"]["ecl_final_sar"]
CORPORATE = ("rating notch", "obligor", "covenant", "EBITDA", "wholesale",
             "corporate book", "master scale", "annual review")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def said(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(w.lower() in lowered for w in words)


def numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def has(text: str, value: float, tolerance: float = 0.0) -> bool:
    tol = tolerance or max(abs(value) * 5e-4, 0.5)
    return any(abs(n - value) <= tol for n in numbers(text))


def api(s: Session, method: str, path: str, body: Any = None) -> tuple:
    return tuple(s.page.evaluate(
        """async ([method, url, body]) => {
             const res = await fetch(url, {
               method,
               headers: { "Content-Type": "application/json" },
               credentials: "include",
               body: body === null ? undefined : JSON.stringify(body),
             });
             let payload = null;
             try { payload = await res.json(); } catch (e) { payload = null; }
             return [res.status, payload];
           }""", [method, f"{BACKEND}{path}", body]))


# ------------------------------------------------- A: portfolio to action


def journey_a(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/", settle=5000)
    steps = [
        "What needs my attention in the retail portfolio this month?",
        "Why is that happening?",
        "Show me the evidence.",
    ]
    answers: list[str] = []
    for index, question in enumerate(steps, start=1):
        made = s.ask(question, selector=COCKPIT_COMPOSER, timeout=300)
        turn = s.latest_turn(question) or ""
        answers.append(turn)
        _case(rec, f"JA-0{index}", f"Step {index}: {question[:44]}",
              bool(made.get("completed")) and len(turn.strip()) > 80
              and not said(turn, *CORPORATE),
              f"answered={bool(made.get('completed'))}; "
              f"{len(turn)} characters; corporate wording="
              f"{[w for w in CORPORATE if w.lower() in turn.lower()]}",
              question=question, answer=turn[:1200],
              screenshot=s.shot(f"ja-0{index}"))

    # The evidence answer has to point at something governed.
    evidence = answers[-1] if answers else ""
    _case(rec, "JA-04", "The evidence step names a dataset, a column or a "
          "calculation rather than restating the finding",
          said(evidence, "retail_facility_month", "column", "dataset",
               "calculation", "trace", "governed"),
          "the evidence answer names its source",
          answer=evidence[:800])

    # This conversation IS an investigation. It has to be listed as one.
    conversation = page.url
    s.go("/investigations", settle=5000)
    s.wait_for("[data-investigation-id]", seconds=40)
    listed = page.query_selector_all("[data-investigation-id]")
    _case(rec, "JA-05", "The conversation became an investigation that "
          "Investigations lists", bool(listed),
          f"{len(listed)} investigations listed; the thread was "
          f"{conversation}")

    # And reopening it keeps the conversation rather than the title alone.
    reopened = ""
    if listed:
        listed[0].click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        s.wait_for_text("retail", seconds=40)
        reopened = s.text()
    _case(rec, "JA-06", "Reopening carries the whole conversation",
          len(reopened) > 800,
          f"the reopened thread renders {len(reopened)} characters",
          screenshot=s.shot("ja-06"))


# ------------------------------------------- B: the auditor's challenge


def journey_b(s: Session, rec: Recorder) -> None:
    s.go("/scorecard-validation", settle=6000)
    steps = [
        ("JB-01", "Assess the personal-finance application scorecard using "
                  "the latest fully observed cohort.",
         ("gini", "auc", "ks", "observations")),
        ("JB-02", "How is calibration for the personal finance application "
                  "scorecard?", ("observed", "expected", "o/e", "predicted")),
        ("JB-03", "Has the population for the personal finance application "
                  "scorecard drifted?", ("psi", "stability", "reference")),
        ("JB-04", "Which segment is weakest for the personal finance "
                  "application scorecard?", ("segment",)),
        ("JB-05", "Gini has fallen. Does that mean the predicted PDs are "
                  "wrong?", ("calibration", "discrimination")),
    ]
    for cid, question, wanted in steps:
        made = s.ask(question, selector=SCORECARD_COMPOSER, timeout=420)
        turn = s.latest_turn(question) or ""
        answered = any(w in turn.lower() for w in wanted)
        _case(rec, cid, f"{question[:52]}",
              bool(made.get("completed")) and answered
              and not said(turn, "CBUAE", "United Arab Emirates", "Saudi SME"),
              f"the answer speaks to what was asked={answered}",
              question=question, answer=turn[:1200],
              screenshot=s.shot(cid.lower()))


# ------------------------------------------- C: the management decision


def journey_c(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/what-if", settle=6000)
    opening = s.text()
    _case(rec, "JC-01", "The opening book is on screen before anything is run",
          said(opening, "facilit") and said(opening, "customer"),
          "facilities and customers are stated before the first scenario",
          screenshot=s.shot("jc-01"))

    for cid, question in (
            ("JC-02", "Increase personal-finance PD by 20% relative."),
            ("JC-03", "Only salary-transfer customers."),
            ("JC-04", "Explain the ECL impact.")):
        made = s.ask(question, selector=WHATIF_COMPOSER, timeout=300)
        turn = s.latest_turn(question) or ""
        _case(rec, cid, question[:52],
              bool(made.get("completed")) and len(turn.strip()) > 60,
              f"answered={bool(made.get('completed'))}",
              question=question, answer=turn[:1000],
              screenshot=s.shot(cid.lower()))

    # Save, leave, and reopen from Recent Runs.
    name = f"UAT journey {time.strftime('%H%M%S')}"
    saved = False
    box = page.query_selector('[data-testid="retail-whatif-name"]')
    if box is not None:
        box.click()
        box.fill(name)
        button = page.query_selector('[data-testid="retail-whatif-save"]')
        if button is not None:
            button.click()
            saved = s.wait_for_text(name, seconds=30)
    _case(rec, "JC-05", "The scenario saves under a name this suite owns",
          saved, f"saved as {name!r}={saved}", screenshot=s.shot("jc-05"))

    s.go("/metrics", settle=3000)
    s.go("/what-if", settle=6000)
    s.wait_for('[data-testid^="retail-whatif-reopen-"]', seconds=40)
    reopened = False
    for row in page.query_selector_all('[data-testid^="retail-whatif-reopen-"]'):
        if name in (row.evaluate("e => e.closest('li')?.innerText || ''") or ""):
            row.click()
            reopened = s.wait_for_text("as it ran at", seconds=40)
            break
    _case(rec, "JC-06", "Leaving the module and reopening from Recent Runs "
          "brings back the scenario as it ran", reopened,
          f"reopened {name!r}={reopened}", screenshot=s.shot("jc-06"))

    # The export a reader would take to a meeting.
    body = s.text()
    _case(rec, "JC-07", "A saved scenario offers an export beside it",
          said(body, "CSV") and said(body, "JSON"),
          "CSV and JSON are offered on the saved run")


# ------------------------------------------- D: early warning to customer


def journey_d(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/early-warning/signals", settle=6000)
    s.wait_for("[data-alert-id]", seconds=40)

    product = page.query_selector('[data-testid="signals-product"]')
    if product is not None:
        product.select_option("PERSONAL_LOAN")
        page.wait_for_timeout(4000)
    severity = page.query_selector('[data-testid="signals-severity"]')
    if severity is not None:
        severity.select_option("HIGH")
        page.wait_for_timeout(4000)
    narrowed = len(page.query_selector_all("[data-alert-id]"))
    _case(rec, "JD-01", "The list narrows to one product at one severity",
          narrowed > 0,
          f"{narrowed} alerts after filtering to personal finance, HIGH",
          screenshot=s.shot("jd-01"))

    opened = False
    link = page.query_selector('[data-testid^="open-customer-"]')
    if link is not None:
        link.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        opened = s.wait_for('[data-testid="retail-customer-360"]', seconds=40)
    _case(rec, "JD-02", "The alert opens the customer it was raised against",
          opened, f"Customer 360 rendered={opened}",
          screenshot=s.shot("jd-02"))

    # History and both scores, on the customer. They sit behind tabs, so the
    # tabs are opened — a reader clicks them, and a check that reads only the
    # landing tab reports the product as missing what it is showing.
    # Read ACROSS the tabs, not from whichever one happens to be last. A
    # reader opens History, then Scores, then Warnings; a check that keeps
    # only the final tab's text reports the two before it as missing.
    s.wait_for('[data-testid="customer-header"]', seconds=40)
    seen: list[str] = [s.text()]
    for label in ("History", "Scores", "Warnings"):
        for tab in page.query_selector_all("button, [role='tab']"):
            if (tab.inner_text() or "").strip() == label:
                tab.click()
                page.wait_for_timeout(2500)
                seen.append(s.text())
                break
    body = "\n".join(seen)
    _case(rec, "JD-03", "The customer's history and both scorecards are there",
          said(body, "history", "month") and said(body, "behavioural")
          and said(body, "application"),
          f"history={said(body, 'history', 'month')}; "
          f"behavioural={said(body, 'behavioural')}; "
          f"application={said(body, 'application')}",
          screenshot=s.shot("jd-03"))

    returned = False
    kept = ""
    back = page.query_selector('[data-testid="back-link"]')
    if back is not None:
        back.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        s.wait_for('[data-testid="signals-product"]', seconds=40)
        returned = "/early-warning/signals" in page.url
        control = page.query_selector('[data-testid="signals-product"]')
        kept = control.input_value() if control is not None else ""
    _case(rec, "JD-04", "Back returns to the EXACT filtered list",
          returned and kept == "PERSONAL_LOAN",
          f"returned={returned}; the product filter reads {kept!r}",
          screenshot=s.shot("jd-04"))


def suite(s: Session, rec: Recorder) -> None:
    journey_a(s, rec)
    journey_b(s, rec)
    journey_c(s, rec)
    journey_d(s, rec)


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_journeys", suite))
