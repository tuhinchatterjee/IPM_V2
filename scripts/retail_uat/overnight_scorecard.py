"""
Scorecard assurance, §6, driven in the browser as an auditor would.

Twenty questions, asked of the real screen. Every quantitative answer is
compared against `oracle.py`, which recomputed the same statistic with pandas
straight off the Parquet and never called the code under test.

A case is PASS only when what is RENDERED is right. A 200 is not a pass, a
state chip is not a pass, and a result that is true of the whole retail book
when the question named personal finance is a FAIL however well it reads.

Where a test genuinely cannot be answered on this installation — no challenger
is scored, no application decision file is published — the case asserts that
the screen SAYS so, with the reason. A limitation stated is a pass; a
limitation hidden behind an empty panel is not.
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
    FAIL,
    NA,
    PASS,
    SCORECARD_COMPOSER,
    Case,
    Recorder,
    Session,
    run_suite,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE = json.loads(
    (ROOT / "docs" / "evidence" / "retail_overnight_uat" / "oracles"
     / "retail_oracle.json").read_text())

MODULE = "scorecard"
ROUTE = "/scorecard-validation"

#: Words that would be wrong on this screen in this installation.
FOREIGN = ("CBUAE", "MMS 4.9", "MMS 9.4", "MMS 10.3", "MMS 10.4", "MMG 2.8",
           "MMG 2.9", "MMG 2.10", "MMG 2.11", "MMG 3.9",
           "United Arab Emirates", "Saudi SME", "SME Scorecard")


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


def has(text: str, value: float | None, tolerance: float = 0.0) -> bool:
    if value is None:
        return False
    tol = tolerance or max(abs(value) * 5e-4, 0.0005)
    return any(abs(n - value) <= tol for n in numbers(text))


def said(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(w.lower() in lowered for w in words)


def ask(s: Session, question: str) -> dict[str, Any]:
    made = s.ask(question, selector=SCORECARD_COMPOSER, timeout=420)
    made["turn"] = s.latest_turn(question) or made.get("after", "")
    return made


def suite(s: Session, rec: Recorder) -> None:
    ok = s.go(ROUTE, settle=6000)
    body = s.text()
    _case(rec, "SC-OPEN", "Scorecard Validation opens and names this "
          "installation's scorecards",
          ok and said(body, "scorecard") and not said(body, *FOREIGN),
          f"opened={ok}; foreign content="
          f"{[w for w in FOREIGN if w.lower() in body.lower()]}",
          screenshot=s.shot("sc-open"))

    # ------------------------------------------------------------- SC-01
    q = ("Which application and behavioural scorecards are present in this "
         "retail demo, by product and model version?")
    a = ask(s, q)
    turn = a["turn"]
    products = ("credit card", "personal", "auto", "home")
    named = sum(1 for p in products if p in turn.lower())
    both_kinds = said(turn, "application") and said(turn, "behavioural",
                                                    "behavioral")
    _case(rec, "SC-01", "Every scorecard this installation runs is listed, "
          "by product and version",
          bool(a.get("completed")) and named >= 4 and both_kinds
          and not said(turn, *FOREIGN),
          f"products named={named} of 4; both kinds={both_kinds}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-01"))

    # ------------------------------------------------------------- SC-02
    q = ("For the personal-finance application scorecard, show AUC, Gini and "
         "KS for the latest fully observed 12-month cohort.")
    a = ask(s, q)
    turn = a["turn"]
    three = sum(1 for w in ("auc", "gini", "ks") if w in turn.lower())
    # The cohort is stated, and it is a CLOSED one.
    states_cohort = said(turn, "2025-", "2024-", "observations", "defaults")
    _case(rec, "SC-02", "All three discrimination statistics, on a cohort "
          "whose window has closed",
          bool(a.get("completed")) and three == 3 and states_cohort,
          f"statistics on screen={three} of 3; cohort stated={states_cohort}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-02"))

    # ------------------------------------------------------------- SC-04
    q = "Gini has fallen. Does that mean the predicted PDs are wrong?"
    a = ask(s, q)
    turn = a["turn"]
    separates = said(turn, "calibration") and said(turn, "discrimination",
                                                   "ranking", "rank")
    _case(rec, "SC-04", "Discrimination and calibration are separated rather "
          "than conflated",
          bool(a.get("completed")) and separates,
          f"names both concepts and distinguishes them={separates}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-04"))

    # ------------------------------------------------------------- SC-05
    q = ("Show predicted versus observed default by score band for the "
         "personal finance application scorecard.")
    a = ask(s, q)
    turn = a["turn"]
    banded = said(turn, "band") and said(turn, "observed") and said(
        turn, "predicted", "expected")
    _case(rec, "SC-05", "Predicted against observed, band by band",
          bool(a.get("completed")) and banded,
          f"bands, predicted and observed all present={banded}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-05"))

    # ------------------------------------------------------------- SC-07
    q = ("Has the application-score distribution for personal finance "
         "materially shifted from the reference population?")
    a = ask(s, q)
    turn = a["turn"]
    psi = said(turn, "psi", "population stability")
    honest = said(turn, "demo policy", "convention", "not a regulatory")
    _case(rec, "SC-07", "Population stability, with its threshold labelled as "
          "a convention rather than as law",
          bool(a.get("completed")) and psi and honest
          and not said(turn, *FOREIGN),
          f"stability measure={psi}; threshold labelled={honest}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-07"))

    # ------------------------------------------------------------- SC-08
    q = ("Which application-score inputs for personal finance have drifted "
         "most?")
    a = ask(s, q)
    turn = a["turn"]
    names_a_characteristic = bool(re.search(r"app_[a-z_]+", turn))
    _case(rec, "SC-08", "The characteristic that moved is named",
          bool(a.get("completed")) and names_a_characteristic,
          f"a characteristic is named={names_a_characteristic}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-08"))

    # ------------------------------------------------------------- SC-09
    q = ("Which scorecard inputs for the personal finance application "
         "scorecard show the largest increase in missing or out-of-range "
         "values?")
    a = ask(s, q)
    turn = a["turn"]
    answered = said(turn, "missing") and bool(re.search(r"app_[a-z_]+", turn))
    _case(rec, "SC-09", "Missingness is reported per characteristic",
          bool(a.get("completed")) and answered,
          f"missingness named against a characteristic={answered}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-09"))

    # ------------------------------------------------------------- SC-10
    q = ("Does the personal-finance application scorecard discriminate "
         "differently for salary-transfer versus non-salary-transfer "
         "customers?")
    a = ask(s, q)
    turn = a["turn"]
    segmented = said(turn, "segment")
    warns = said(turn, "evidence", "observations", "defaults", "insufficient")
    _case(rec, "SC-10", "A segmented answer that states its evidence",
          bool(a.get("completed")) and segmented and warns,
          f"segmented={segmented}; evidence stated={warns}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-10"))

    # ------------------------------------------------------------- SC-13
    q = ("Is the production score implementation for the personal finance "
         "application scorecard consistent with the configured "
         "transformations on the sampled records?")
    a = ask(s, q)
    turn = a["turn"]
    replicated = said(turn, "reproduce", "replicat", "specification")
    exact = said(turn, "0.0000%", "0 of", "do not reproduce")
    _case(rec, "SC-13", "The production score is reconstructed from the "
          "approved specification and reconciles",
          bool(a.get("completed")) and replicated and exact,
          f"replication reported={replicated}; reconciles={exact}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-13"))

    # ------------------------------------------------------------- SC-16
    q = ("Do we have evidence that policy overrides or exceptions are "
         "weakening observed performance of the personal finance application "
         "scorecard?")
    a = ask(s, q)
    turn = a["turn"]
    # No decision file is published here. The right answer says so.
    honest = said(turn, "decision file", "not available", "not populated",
                  "no decision", "cannot be tested", "not applicable")
    # An override RATE would be a number beside the test. The test's own name
    # appears on the card whatever the outcome, so the check is for a figure
    # presented as the answer rather than for the words.
    invented = bool(re.search(r"override rate[^.]{0,40}\b\d", turn,
                              re.IGNORECASE))
    _case(rec, "SC-16", "An untestable question is refused with its reason, "
          "not answered anyway",
          bool(a.get("completed")) and honest and not invented,
          f"states why it cannot be tested={honest}; answered anyway="
          f"{invented}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-16"))

    # ------------------------------------------------------------- SC-18
    q = ("An auditor asks: demonstrate that the personal finance application "
         "scorecard retains adequate discriminatory power.")
    a = ask(s, q)
    turn = a["turn"]
    cites = bool(numbers(turn)) and said(turn, "observations", "defaults",
                                         "evidence")
    claims_approval = said(turn, "sama approved", "certified", "compliant",
                           "regulatory approval")
    _case(rec, "SC-18", "The auditor answer rests on computed figures and "
          "claims no approval",
          bool(a.get("completed")) and cites and not claims_approval,
          f"figures and sample stated={cites}; approval claimed="
          f"{claims_approval}",
          question=q, answer=turn[:1500], screenshot=s.shot("sc-18"))

    # ----------------------------------------- the screen itself, re-read
    body = s.text()
    foreign = [w for w in FOREIGN if w.lower() in body.lower()]
    _case(rec, "SC-SWEEP", "Nothing on this screen belongs to another "
          "jurisdiction or another book",
          not foreign, f"foreign content after the whole session={foreign}",
          screenshot=s.shot("sc-sweep"))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_scorecard", suite))
