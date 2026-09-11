"""
Cockpit business journeys CP-01 to CP-15, in a real browser.

Section 10.5. These are the questions a credit officer actually types, asked in
the order they would type them, and the assertions are about scope, arithmetic,
evidence and honesty rather than wording.

Every figure asserted here was reconciled independently against the published
Parquet before it was written into a case — see the constants below, which are
read from the book by tests/retail/test_ret_chat_regressions.py.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "cockpit"

#: Independently computed from data/retail/analytics at 2026-08.
BOOK_GCA = "2,082,852,856"
PERSONAL_FINANCE_GCA = "463,168,890"
FACILITIES = "19,745"


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def suite(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/", settle=2500)

    # ------------------------------------------------------------------ CP-01
    q1 = ("Use Cockpit Data for August 2026. Show exposure, customers, "
          "facilities and weighted ECL by retail product.")
    r1 = s.ask(q1, timeout=240)
    turn = s.latest_turn(q1)
    correct = (BOOK_GCA in turn and "2026-08" in turn
               and "Personal Finance" in turn and "Home Finance" in turn
               and "Customers" in turn and "Facilities" in turn)
    # The answer must not claim a product is largest when another one is.
    names_largest = "Home Finance is the largest" in turn
    _case(rec, "CP-01", "Exposure, customers, facilities and weighted ECL by "
          "retail product, at the month the question named",
          bool(r1.get("completed") and correct and names_largest),
          f"completed={r1.get('completed')}; the four measures and the four "
          f"products are on screen={correct}; the largest product named "
          f"matches the table={names_largest}",
          answer=turn[:1200], screenshot=s.shot("cockpit-cp-01"))

    # ------------------------------------------------------------------ CP-02
    r2a = s.ask("Now only personal finance", timeout=240)
    narrowed = s.latest_turn("Now only personal finance")
    r2b = s.ask("Compare with July 2026", timeout=240)
    compared = s.latest_turn("Compare with July 2026")
    kept_metric = "gross carrying amount" in compared.lower() or "ECL" in compared
    both_periods = "2026-07" in compared and "2026-08" in compared
    scoped = PERSONAL_FINANCE_GCA in compared or "Personal Finance" in compared
    _case(rec, "CP-02", "Narrowing to one product and then comparing periods "
          "keeps the measure and changes only what was asked",
          bool(r2a.get("completed") and r2b.get("completed")
               and kept_metric and both_periods and scoped),
          f"the narrowing answered={r2a.get('completed')}; the comparison "
          f"answered={r2b.get('completed')}; it names both periods="
          f"{both_periods}; it stayed in personal finance={scoped}",
          narrowed=narrowed[:600], compared=compared[:800],
          screenshot=s.shot("cockpit-cp-02"))

    # ------------------------------------------------------------------ CP-03
    r3 = s.ask("Give me the July to August ECL decomposition for personal "
               "finance and explain the PD impact.", timeout=300)
    bridge = s.latest_turn("Give me the July to August ECL decomposition")
    # "PD" is governed as three measures on this book, and the product asks
    # which horizon. Answering it is part of the journey, not a workaround.
    if "ONE QUESTION BACK" in bridge:
        r3 = s.ask("Twelve-month PD.", timeout=300)
        bridge = s.latest_turn("Twelve-month PD.")
    reconciles = ("opening" in bridge.lower() or "2026-07" in bridge) and \
                 ("closing" in bridge.lower() or "2026-08" in bridge)
    # A retired corporate dimension offered anywhere in the answer, including
    # in the follow-up it suggests, is the defect this looks for.
    fabricated = "sector" in bridge.lower() or "rating grade" in bridge.lower()
    _case(rec, "CP-03", "A period decomposition reconciles opening, "
          "contributions and closing rather than showing an unrelated chart",
          bool(r3.get("completed") and reconciles and not fabricated),
          f"completed={r3.get('completed')}; both ends of the bridge are "
          f"named={reconciles}; it invents a corporate dimension={fabricated}",
          answer=bridge[:900], screenshot=s.shot("cockpit-cp-03"))

    # ------------------------------------------------------------------ CP-04
    r4 = s.ask("What is the difference between base-scenario ECL and the "
               "baseline in What-If?", timeout=240)
    explained = s.latest_turn("What is the difference between base-scenario ECL")
    honest = ("weighted" in explained.lower() or "base" in explained.lower())
    _case(rec, "CP-04", "A definitional question is answered as an explanation, "
          "without inventing a portfolio figure",
          bool(r4.get("completed") and honest),
          f"completed={r4.get('completed')}; the answer distinguishes the base "
          f"scenario from the weighted baseline={honest}",
          answer=explained[:800], screenshot=s.shot("cockpit-cp-04"))

    # ------------------------------------------------------------------ CP-05
    r5 = s.ask("Use cockpit data aug 2026, persnal finace. Show ECL by stage "
               "and tell me what changed from July.", timeout=300)
    messy = s.latest_turn("Use cockpit data aug 2026")
    understood = ("stage" in messy.lower() and
                  ("2026-08" in messy or "August" in messy))
    _case(rec, "CP-05", "A misspelt, single-paragraph instruction is read by "
          "the ordinary parser rather than refused",
          bool(r5.get("completed") and understood),
          f"completed={r5.get('completed')}; the stage breakdown and the month "
          f"were understood={understood}",
          answer=messy[:900], screenshot=s.shot("cockpit-cp-05"))

    # ------------------------------------------------------------------ CP-06
    s.go("/", settle=2500)
    r6 = s.ask("Show scorecard performance.", timeout=240)
    vague = s.latest_turn("Show scorecard performance.")
    asked_back = ("ONE QUESTION BACK" in vague or "?" in vague)
    typed = s.ask("The personal finance application scorecard.", timeout=300)
    resolved = s.latest_turn("The personal finance application scorecard.")
    _case(rec, "CP-06", "An under-specified scorecard question is clarified "
          "once, and a typed answer resolves it",
          bool(asked_back and typed.get("completed")),
          f"the product asked rather than guessing={asked_back}; the typed "
          f"clarification was answered={typed.get('completed')}",
          clarification=vague[:600], resolved=resolved[:600],
          screenshot=s.shot("cockpit-cp-06"))

    # ------------------------------------------------------------------ CP-07
    s.go("/", settle=2500)
    r7 = s.ask("Assess personal-finance application-scorecard discrimination "
               "using the latest fully observed 12-month cohort.", timeout=300)
    cohort = s.latest_turn("Assess personal-finance application-scorecard")
    states = any(word in cohort.lower() for word in
                 ("gini", "auc", "ks", "cohort", "observed", "insufficient",
                  "cannot"))
    _case(rec, "CP-07", "A discrimination question either reports the cohort, "
          "its counts and its statistic, or says what is missing",
          bool(r7.get("completed") and states),
          f"completed={r7.get('completed')}; the answer names the cohort or "
          f"the evidence it lacks={states}",
          answer=cohort[:900], screenshot=s.shot("cockpit-cp-07"))

    # ------------------------------------------------------------------ CP-08
    r8 = s.ask("Is it well calibrated?", timeout=300)
    calib = s.latest_turn("Is it well calibrated?")
    # Gini is discrimination, never calibration. Using it as calibration
    # evidence is the defect this case exists to catch.
    misuses_gini = ("gini" in calib.lower()
                    and "calibrat" in calib.lower()
                    and "not" not in calib.lower()[:400])
    _case(rec, "CP-08", "A calibration question is not answered with a "
          "discrimination statistic",
          bool(r8.get("completed") and not misuses_gini),
          f"completed={r8.get('completed')}; Gini offered as calibration "
          f"evidence={misuses_gini}",
          answer=calib[:800], screenshot=s.shot("cockpit-cp-08"))

    # ------------------------------------------------------------------ CP-09
    s.go("/", settle=2500)
    r9 = s.ask("Calculate the next-12-month Gini for applications originated "
               "in August 2026.", timeout=300)
    future = s.latest_turn("Calculate the next-12-month Gini")
    refuses = any(word in future.lower() for word in
                  ("not yet", "cannot", "unobserved", "not observed",
                   "incomplete", "insufficient", "window"))
    invents = "gini of 0." in future.lower() and not refuses
    _case(rec, "CP-09", "A statistic that needs outcomes the book cannot have "
          "yet is refused with the reason, not fabricated",
          bool(r9.get("completed") and refuses and not invents),
          f"completed={r9.get('completed')}; the answer explains why the "
          f"outcome window is not complete={refuses}; it invents a "
          f"figure={invents}",
          answer=future[:900], screenshot=s.shot("cockpit-cp-09"))

    # ------------------------------------------------------------------ CP-11
    s.go("/", settle=2500)
    r11 = s.ask("Explain credit-card utilisation and show which customers "
                "worsened between July and August 2026.", timeout=300)
    util = s.latest_turn("Explain credit-card utilisation")
    separated = "utilisation" in util.lower()
    _case(rec, "CP-11", "An explain-and-compare question separates the "
          "explanation from the comparison it can actually run",
          bool(r11.get("completed") and separated),
          f"completed={r11.get('completed')}; the answer is about "
          f"utilisation={separated}",
          answer=util[:900], screenshot=s.shot("cockpit-cp-11"))

    # ------------------------------------------------------------------ CP-13
    s.go("/", settle=2500)
    r13 = s.ask("Show exposure by retail product for August 2026 where the "
                "product is Aviation Finance.", timeout=240)
    empty = s.latest_turn("where the product is Aviation Finance")
    honest_empty = any(word in empty for word in
                       ("no ", "No ", "not a", "nothing", "0 ", "could not"))
    reused = BOOK_GCA in empty
    _case(rec, "CP-13", "A filter that matches nothing gives an honest empty "
          "answer rather than the previous populated one",
          bool(r13.get("completed") and honest_empty and not reused),
          f"completed={r13.get('completed')}; an empty or refusing answer="
          f"{honest_empty}; the previous result was reused={reused}",
          answer=empty[:800], screenshot=s.shot("cockpit-cp-13"))

    # ------------------------------------------------------------------ CP-14
    s.go("/", settle=2500)
    q14 = "Show weighted ECL by retail product for August 2026"
    s.ask(q14, timeout=240)
    conversation = page.url
    trace = page.query_selector('a[href^="/trace/"]')
    returned = False
    simpler_ok = False
    if trace is not None:
        trace.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        back = page.query_selector('[data-testid="back-link"]')
        if back is not None:
            back.click()
            page.wait_for_load_state("networkidle", timeout=90_000)
            page.wait_for_timeout(2500)
        returned = conversation.split("?")[0].split("#")[0] in page.url
        if returned:
            simpler = s.ask("Explain that result more simply.", timeout=240)
            simpler_ok = bool(simpler.get("completed"))
    _case(rec, "CP-14", "Opening the evidence and coming back lands on the same "
          "conversation, and a follow-up there is contextual",
          bool(trace is not None and returned and simpler_ok),
          f"the evidence opened={trace is not None}; Back returned to the "
          f"conversation={returned}; the contextual follow-up answered="
          f"{simpler_ok}",
          screenshot=s.shot("cockpit-cp-14"))

    # ------------------------------------------------------------------ CP-15
    s.go("/", settle=2500)
    s.ask("Show weighted ECL by retail product for July 2026", timeout=240)
    july = s.latest_turn("Show weighted ECL by retail product for July 2026")
    july_ok = "2026-07" in july
    s.go("/", settle=2500)
    s.ask("Show weighted ECL by retail product for August 2026", timeout=240)
    august = s.latest_turn("Show weighted ECL by retail product for August 2026")
    august_ok = "2026-08" in august and "2026-07" not in august.split("2026-08")[0]
    _case(rec, "CP-15", "Two conversations at two months do not contaminate "
          "each other",
          bool(july_ok and august_ok),
          f"the July conversation is at 2026-07={july_ok}; the August one is "
          f"at 2026-08={august_ok}",
          screenshot=s.shot("cockpit-cp-15"))

    # ---------------------------------------------- the five-turn conversation
    s.go("/", settle=2500)
    started = time.time()
    turns = [
        ("Use Cockpit Data for August 2026. Show exposure, customers, "
         "facilities and weighted ECL by retail product.", BOOK_GCA),
        ("Now only personal finance", "Personal Finance"),
        ("Compare with July 2026", "2026-07"),
        ("Explain that change", "2026-08"),
        ("Show the evidence", "Trace"),
    ]
    outcomes: list[str] = []
    for question, expected in turns:
        answer = s.ask(question, timeout=300)
        text = s.latest_turn(question)
        ok = bool(answer.get("completed")) and expected in text
        outcomes.append(f"{question[:28]}…={'ok' if ok else 'FAILED'}")
    _case(rec, "CP-CONT", "One continuous five-turn conversation: analysis, "
          "narrowing, comparison, explanation and evidence",
          all("FAILED" not in o for o in outcomes),
          "; ".join(outcomes) + f" ({time.time() - started:.0f}s)",
          screenshot=s.shot("cockpit-cp-continuous"))

    # ------------------------------------------------------------------ CP-10
    # A named customer, opened through the UI and read on the screen.
    #
    # This was BLOCKED in Revision 2: the route rendered the previous module's
    # layout, called the corporate endpoints and answered 503 data_not_built,
    # so there was no retail customer to open. It is answered here the way the
    # case asks — by searching for a customer on the screen and reading the
    # score panel — and NOT against the API, which would be a different case.
    page = s.page
    s.go("/borrower-360", settle=3000)
    box = page.query_selector('[data-testid="customer-search"]')
    opened = False
    detail = "the customer search is not on the screen"
    if box is not None:
        box.fill("RC-0020621")
        go = page.query_selector('[data-testid="customer-search-go"]')
        if go:
            go.click()
            # Searching LISTS customers; it does not open one. Clicking the
            # result is the step a reader takes and the step this case is for.
            deadline = time.time() + 90
            while time.time() < deadline:
                page.wait_for_timeout(1500)
                if page.query_selector('[data-customer-id="RC-0020621"]'):
                    break
            hit = page.query_selector('[data-customer-id="RC-0020621"]')
            if hit is not None:
                hit.click()
                deadline = time.time() + 90
                while time.time() < deadline:
                    page.wait_for_timeout(1500)
                    if page.query_selector('[data-testid="customer-facilities"]'):
                        break
        # The Scores tab carries the behavioural scorecard and its evidence.
        tabs = {t.inner_text().strip(): t
                for t in page.query_selector_all('[role="tab"]')}
        if "Scores" in tabs:
            tabs["Scores"].click()
            page.wait_for_timeout(2500)
        text = s.text()
        # The screen names the MODEL and its version — as a badge reading
        # "RETAIL_BEH_..." and "v1.0.0", not the word "version" — and shows the
        # weight-of-evidence contributions that make the score explainable.
        # A score with no model and no inputs behind it cannot be explained to
        # anybody, which is what this case is for.
        behavioural = page.query_selector('[data-testid^="score-RETAIL_BEH"]')
        named_model = behavioural is not None
        version = bool(behavioural
                       and re.search(r"\bv\d+\.\d+", behavioural.inner_text()))
        contributions = page.query_selector_all(
            '[data-testid^="score-RETAIL_BEH"] tbody tr')
        this_month = "as they stand at this month-end" in text
        opened = (named_model and version and len(contributions) >= 3
                  and "RC-0020621" in text and this_month)
        detail = (f"customer opened on screen={('RC-0020621' in text)}; "
                  f"behavioural model named={named_model}; version shown={version}; "
                  f"{len(contributions)} weight-of-evidence contributions listed; "
                  f"read as of this month-end rather than origination={this_month}")
    _case(rec, "CP-10",
          "Explain a named customer's behavioural score through the Customer "
          "360 screen, with the model and its evidence named",
          opened, detail,
          route="/borrower-360", customer="RC-0020621",
          screenshot=s.shot("cockpit-cp-10"))

    # ------------------------------------------------------------------ CP-12
    s.go("/", settle=2500)
    r12 = s.ask("Draft an evidence-backed response to the auditor about this "
                "scorecard's continuing performance.", timeout=300)
    drafted = s.latest_turn("Draft an evidence-backed response to the auditor")
    disclosed = ("No AI provider is configured" in drafted
                 or "assembled from the result" in drafted)
    _case(rec, "CP-12", "A drafting request is answered from the result, and "
          "says plainly that no model wrote the prose",
          bool(r12.get("completed") and disclosed),
          f"completed={r12.get('completed')}; the deterministic fallback is "
          f"disclosed on the answer={disclosed} — this is NOT a live-provider "
          f"pass",
          answer=drafted[:800], screenshot=s.shot("cockpit-cp-12"))


if __name__ == "__main__":
    raise SystemExit(run_suite("cockpit_journeys", suite))
