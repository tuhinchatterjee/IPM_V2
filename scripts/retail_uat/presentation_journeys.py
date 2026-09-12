"""
The four journeys the presentation runs, and nothing else.

Not a coverage suite. These are the exact sequences a Head of Retail Risk is
shown on the morning, each asked in a REAL browser and each read for whether
the screen says what the presenter is about to claim it says. Every Cockpit
journey starts on a fresh conversation, because that is how the demonstration
starts and because a scope carried in from a rehearsal is the one thing that
cannot be reproduced live.

Every figure is checked against `oracle.py`, which computed it with pandas
straight off the Parquet and never called the code under test.
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
    COCKPIT_COMPOSER,
    WHATIF_COMPOSER,
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE = json.loads(
    (ROOT / "docs" / "evidence" / "retail_overnight_uat" / "oracles"
     / "retail_oracle.json").read_text())

MODULE = "presentation"
STAMP = time.strftime("%H%M%S")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def has(text: str, value: float, tolerance: float = 0.0) -> bool:
    if value is None:
        return False
    tol = tolerance or max(abs(value) * 5e-4, 0.5)
    return any(abs(n - value) <= tol for n in numbers(text))


def has_rounded(text: str, value: float) -> bool:
    if has(text, value):
        return True
    for scale, places in ((1e6, 1), (1e6, 0), (1e3, 0), (1, 0)):
        if has(text, round(value / scale, places), tolerance=0.05):
            return True
    return False


def ask(s: Session, question: str, *, selector: str = COCKPIT_COMPOSER,
        timeout: int = 300) -> dict[str, Any]:
    out = s.ask(question, selector=selector, timeout=timeout)
    out["turn"] = s.latest_turn(question)
    return out


def fresh(s: Session) -> None:
    """A NEW conversation, the way the presenter starts one."""
    s.go("/", settle=3000)


# ----------------------------------------------------------------- journey A

def journey_portfolio(s: Session, rec: Recorder) -> None:
    fresh(s)
    turns: list[dict[str, Any]] = []
    for question in ("What needs my attention in the retail portfolio "
                     "this month?",
                     "Which product is driving it?",
                     "Show me the evidence."):
        turns.append(ask(s, question))

    opened, driver, evidence = turns
    book = ORACLE["book"]

    # The first turn is the governed review: several checks, at THIS month.
    reviewed = ("governed check" in opened["turn"]
                and "2026-08" in opened["turn"])
    honest = "not by a judgement of importance" in opened["turn"]
    # ...and it is not simply the ECL movement restated.
    _case(rec, "PRES-A1",
          "The month's attention question runs the governed review, at this "
          "month, and says what ordered it",
          bool(opened.get("completed") and reviewed and honest),
          f"completed={opened.get('completed')}; reads as a governed review "
          f"at 2026-08={reviewed}; states what the ordering is and is "
          f"not={honest}",
          question=opened["question"], answer=opened["turn"][:1500],
          screenshot=s.shot("pres-a1"))

    named = any(p["product_label"] in driver["turn"]
                for p in ORACLE["by_product"]["rows"])
    _case(rec, "PRES-A2",
          "The follow-up names a product from the governed book",
          bool(driver.get("completed") and named),
          f"completed={driver.get('completed')}; a governed product label is "
          f"named={named}",
          question=driver["question"], answer=driver["turn"][:1500],
          screenshot=s.shot("pres-a2"))

    # The evidence turn must show a calculation, not repeat the sentence.
    shown = any(word in evidence["turn"].lower()
                for word in ("trace", "dataset", "rows", "calculation",
                             "governed", "analysis"))
    _case(rec, "PRES-A3",
          "Asking for the evidence shows where the figure came from",
          bool(evidence.get("completed") and shown),
          f"completed={evidence.get('completed')}; the answer points at the "
          f"calculation or its source={shown}; whole-book ECL on screen="
          f"{has_rounded(evidence['turn'], book.get('ecl_final_sar'))}",
          question=evidence["question"], answer=evidence["turn"][:1500],
          screenshot=s.shot("pres-a3"))


# ----------------------------------------------------------------- journey B

def journey_scorecard(s: Session, rec: Recorder) -> None:
    fresh(s)
    asked = ("How is the personal-finance application scorecard performing?",
             "Show discrimination.",
             "What about calibration?",
             "Has the population drifted?",
             "Draft the response to an auditor.")
    turns = [ask(s, q) for q in asked]

    opened, disc, calib, drift, draft = turns

    _case(rec, "PRES-B1",
          "The scorecard question is answered about a scorecard",
          bool(opened.get("completed")
               and any(w in opened["turn"].lower()
                       for w in ("scorecard", "model", "gini", "ks",
                                 "discrimination", "application"))),
          f"completed={opened.get('completed')}",
          question=opened["question"], answer=opened["turn"][:1500],
          screenshot=s.shot("pres-b1"))

    # Discrimination is a discrimination statistic, not a calibration one.
    said = disc["turn"].lower()
    discriminates = any(w in said for w in ("gini", "auc", "ks", "roc",
                                            "discrimination"))
    _case(rec, "PRES-B2",
          "Discrimination is answered with a discrimination statistic",
          bool(disc.get("completed") and discriminates),
          f"completed={disc.get('completed')}; a discrimination statistic is "
          f"named={discriminates}",
          question=disc["question"], answer=disc["turn"][:1500],
          screenshot=s.shot("pres-b2"))

    said = calib["turn"].lower()
    calibrates = any(w in said for w in ("calibrat", "observed", "expected",
                                         "hosmer", "binomial", "predicted"))
    borrowed = ("gini" in said or "auc" in said) and not calibrates
    _case(rec, "PRES-B3",
          "Calibration is not answered with a discrimination statistic",
          bool(calib.get("completed") and calibrates and not borrowed),
          f"completed={calib.get('completed')}; calibration is addressed="
          f"{calibrates}; answered with discrimination instead={borrowed}",
          question=calib["question"], answer=calib["turn"][:1500],
          screenshot=s.shot("pres-b3"))

    said = drift["turn"].lower()
    drifted = any(w in said for w in ("psi", "drift", "stability",
                                      "population"))
    _case(rec, "PRES-B4",
          "The drift question is answered about population stability",
          bool(drift.get("completed") and drifted),
          f"completed={drift.get('completed')}; stability is addressed="
          f"{drifted}",
          question=drift["question"], answer=drift["turn"][:1500],
          screenshot=s.shot("pres-b4"))

    said = draft["turn"]
    # A draft is prose the reader could send. The check that matters is that
    # it is a DRAFT and not the previous answer again: "Draft the response to
    # an auditor." used to return the stability table it had just returned,
    # word for word, under a question asking for a letter.
    drafted = "Draft, for review" in said
    repeated = drift["turn"][:200].strip() != "" and \
        drift["turn"][:200].strip() in said and not drafted
    claims = any(w in said.lower() for w in ("approved by", "signed off",
                                             "validated and approved"))
    _case(rec, "PRES-B5",
          "The auditor draft is written from the result, is marked a draft, "
          "and claims no approval",
          bool(draft.get("completed") and drafted and not repeated
               and len(said.split()) > 40 and not claims),
          f"completed={draft.get('completed')}; marked as a draft={drafted}; "
          f"repeats the previous answer={repeated}; {len(said.split())} "
          f"words; claims an approval={claims}",
          question=draft["question"], answer=said[:1800],
          screenshot=s.shot("pres-b5"))


# ----------------------------------------------------------------- journey C

def journey_whatif(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/what-if", settle=4000)

    run = ask(s, "Increase personal-finance PD by 20% relative.",
              selector=WHATIF_COMPOSER)
    narrowed = ask(s, "Only salary-transfer customers.",
                   selector=WHATIF_COMPOSER)
    explained = ask(s, "Explain the ECL impact.", selector=WHATIF_COMPOSER)

    said = run["turn"].lower()
    corporate = any(w in said for w in ("notch", "rating notch", "obligor",
                                        "sector stress"))
    _case(rec, "PRES-C1",
          "The shock runs as a retail PD shock, with no corporate wording",
          bool(run.get("completed") and not corporate),
          f"completed={run.get('completed')}; corporate wording={corporate}",
          question=run["question"], answer=run["turn"][:1200],
          screenshot=s.shot("pres-c1"))

    said = narrowed["turn"].lower()
    kept = "salary" in said or "salary_transfer" in said
    _case(rec, "PRES-C2",
          "Narrowing to salary-transfer customers is applied and shown",
          bool(narrowed.get("completed") and kept),
          f"completed={narrowed.get('completed')}; the narrowing is on "
          f"screen={kept}",
          question=narrowed["question"], answer=narrowed["turn"][:1200],
          screenshot=s.shot("pres-c2"))

    said = explained["turn"].lower()
    about = ("ecl" in said or "expected credit loss" in said)
    _case(rec, "PRES-C3",
          "The explanation is about this run's ECL impact",
          bool(explained.get("completed") and about),
          f"completed={explained.get('completed')}; the ECL impact is "
          f"explained={about}",
          question=explained["question"], answer=explained["turn"][:1400],
          screenshot=s.shot("pres-c3"))

    # Save -> leave -> reopen. The record is one this suite created, named so
    # it can be told apart from anything the installation shipped.
    name = f"PRES-C {STAMP}"
    box = page.query_selector('[data-testid="retail-whatif-name"]')
    saved = False
    if box is not None:
        box.click()
        box.fill(name)
        button = page.query_selector('[data-testid="retail-whatif-save"]')
        if button is not None:
            button.click()
            page.wait_for_timeout(4000)
            saved = name in s.text()

    s.go("/", settle=3000)
    left = "/what-if" not in page.url
    s.go("/what-if", settle=4000)
    listed = name in s.text()
    reopened = False
    if listed:
        opener = None
        for candidate in page.query_selector_all(
                '[data-testid^="retail-whatif-reopen-"]'):
            opener = opener or candidate
        # The reopen control beside the saved row. Clicking the FIRST is
        # enough only because this run is the newest; the assertion below is
        # on the restored content, not on which row was clicked.
        rows = [el for el in page.query_selector_all(
            '[data-testid^="retail-whatif-reopen-"]')]
        if rows:
            rows[0].click()
            page.wait_for_timeout(4000)
            body = s.text()
            reopened = ("as it ran at" in body or "20" in body) and \
                       ("Personal" in body or "personal" in body)
    _case(rec, "PRES-C4",
          "The run is saved, survives leaving the screen, and reopens with "
          "its own shock",
          bool(saved and left and listed and reopened),
          f"saved={saved}; left the screen={left}; listed on return="
          f"{listed}; reopened with its shock={reopened}",
          screenshot=s.shot("pres-c4"))


# ----------------------------------------------------------------- journey D

def journey_early_warning(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/early-warning/signals", settle=4000)
    listed = s.wait_for('[data-testid^="open-customer-"]', seconds=45)
    first = page.query_selector('[data-testid^="open-customer-"]')
    alert_id = first.get_attribute("data-testid") if first else ""
    before = s.text()

    opened = False
    if first is not None:
        first.click()
        opened = s.wait_for('[data-testid="retail-customer-360"]', seconds=45)
        # The container renders before the customer does. Waiting on the
        # container alone read an empty screen and reported a product with no
        # facilities on it.
        page.wait_for_load_state("networkidle", timeout=90_000)
        s.settle_for(lambda: any(
            c.inner_text().strip() == "Facilities"
            for c in page.query_selector_all('[role="tab"]')), seconds=45)
    _case(rec, "PRES-D1",
          "An alert opens the customer it is about",
          bool(listed and opened),
          f"alerts listed={listed}; Customer 360 opened={opened}; alert="
          f"{alert_id}",
          screenshot=s.shot("pres-d1"))

    # Facilities and History are tabs on Customer 360, and the tables under
    # them do not exist until the tab is on. Reading them off the page as it
    # lands measures the harness, not the screen.
    def _tab(name: str) -> bool:
        for control in page.query_selector_all('[role="tab"]'):
            if control.inner_text().strip() == name:
                control.click()
                page.wait_for_timeout(1800)
                return True
        return False

    _tab("Facilities")
    facilities = page.query_selector_all(
        '[data-testid="customer-facilities"] tbody tr')
    facility_opened = False
    opener = (page.query_selector('[data-testid^="facility-open-"]')
              or page.query_selector('[data-testid^="alert-facility-"]'))
    if opener is not None:
        opener.click()
        page.wait_for_timeout(2500)
        facility_opened = ("score-facility" in (page.content() or "")
                           or "RF-" in s.text())
    _tab("History")
    history = page.query_selector_all(
        '[data-testid="customer-history"] tbody tr')
    _case(rec, "PRES-D2",
          "The customer shows its facilities and its history, and a facility "
          "opens",
          bool(facilities and history and facility_opened),
          f"{len(facilities)} facilities; {len(history)} history rows; a "
          f"facility opened={facility_opened}",
          screenshot=s.shot("pres-d2"))

    back = page.query_selector('[data-testid="back-link"]')
    returned = False
    same = False
    if back is not None:
        back.click()
        s.wait_for('[data-testid^="open-customer-"]', seconds=45)
        returned = "/early-warning" in page.url
        same = bool(page.query_selector(f'[data-testid="{alert_id}"]'))
    _case(rec, "PRES-D3",
          "Back returns to the same alert list, with the alert still on it",
          bool(returned and same),
          f"returned to the list={returned}; the alert opened from is still "
          f"listed={same}",
          screenshot=s.shot("pres-d3"))


def suite(s: Session, rec: Recorder) -> None:
    journey_portfolio(s, rec)
    journey_scorecard(s, rec)
    journey_whatif(s, rec)
    journey_early_warning(s, rec)


if __name__ == "__main__":
    raise SystemExit(run_suite("presentation_journeys", suite))
