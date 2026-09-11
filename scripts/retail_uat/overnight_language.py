"""
§24 — the same question, typed twelve different ways.

The test is not whether each sentence gets an answer. It is whether the
CONTEXT is modified correctly rather than discarded: a narrowing turn keeps
the measure, a broadening turn drops the filter it names, a correction
replaces one measure with another rather than adding it, and a pronoun points
at what the reader means by it.

An answer that quietly reverts to the whole book, or quietly keeps a filter
the reader has just widened out of, is a wrong answer under a heading that
does not say so — which is the class of defect this whole night is about.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    COCKPIT_COMPOSER,
    FAIL,
    PASS,
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

MODULE = "language"
BOOK_ECL = ORACLE["book"]["ecl_final_sar"]
BOOK_GCA = ORACLE["book"]["gross_carrying_amount_sar"]
PERSONAL_ECL = sum(r["ecl_final_sar"]
                   for r in ORACLE["by_stage_personal_finance"]["rows"])
#: Personal finance one month earlier, and the salary-transfer book. Read from
#: the Parquet by the oracle builder, never from the product.
PERSONAL_ECL_JULY = 8_012_418.68
SALARY_ECL = 12_717_680.53
SALARY_GCA = 1_611_005_576.58


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
    tol = tolerance or max(abs(value) * 5e-4, 0.5)
    return any(abs(n - value) <= tol for n in numbers(text))


def said(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(w.lower() in lowered for w in words)


def ask(s: Session, question: str, selector: str = COCKPIT_COMPOSER) -> str:
    made = s.ask(question, selector=selector, timeout=300)
    turn = s.latest_turn(question) or made.get("after", "")
    return turn if made.get("completed") else ""


def suite(s: Session, rec: Recorder) -> None:
    # ---------------------------------------------- one question, six ways
    s.go("/", settle=5000)
    shapes = [
        ("NL-01", "clean and formal",
         "Please show the expected credit loss by IFRS 9 stage for "
         "August 2026."),
        ("NL-02", "shorthand", "ecl by stage aug 26"),
        ("NL-03", "typo-heavy", "expcted creditt loss by stge for augst 2026"),
        ("NL-04", "all lowercase", "show me ecl by ifrs 9 stage at 2026-08"),
    ]
    stage3 = next(r for r in ORACLE["by_stage"]["rows"] if r["stage"] == 3)
    for cid, shape, question in shapes:
        turn = ask(s, question)
        right = has(turn, stage3["ecl_final_sar"], tolerance=50.0) or has(
            turn, BOOK_ECL, tolerance=BOOK_ECL * 0.001)
        _case(rec, cid, f"The same question, {shape}", bool(turn) and right,
              f"answered={bool(turn)}; a governed stage figure is on screen="
              f"{right}",
              question=question, answer=turn[:900],
              screenshot=s.shot(cid.lower()))

    # ------------------------------------------ filter and analysis at once
    turn = ask(s, "For personal finance only, show expected credit loss by "
                  "IFRS 9 stage at August 2026.")
    scoped = said(turn, "personal") and has(turn, PERSONAL_ECL,
                                            tolerance=PERSONAL_ECL * 0.002)
    _case(rec, "NL-05", "A filter and an analysis in one sentence are both "
          "applied", scoped,
          f"scoped to personal finance and reconciling with the oracle="
          f"{scoped}; oracle {PERSONAL_ECL:,.0f}",
          answer=turn[:900], expected=f"{PERSONAL_ECL:,.0f}",
          screenshot=s.shot("nl-05"))

    # ------------------------------------------------------ pronoun follow-up
    #
    # The sentence names no measure, no population and no breakdown. All three
    # come from the turn before it, and the answer has to SAY so: a movement
    # in Personal Finance captioned only "3 stages carried from the previous
    # answer" is a figure with no book named over it.
    turn = ask(s, "How did that move since July 2026?")
    moved = (said(turn, "2026-07") and said(turn, "personal")
             and has(turn, PERSONAL_ECL, tolerance=PERSONAL_ECL * 0.002)
             and has(turn, PERSONAL_ECL_JULY,
                     tolerance=PERSONAL_ECL_JULY * 0.002))
    _case(rec, "NL-06", "A pronoun follow-up keeps the population it points at",
          bool(turn) and moved,
          f"the comparison month, the personal-finance scope and both "
          f"totals survived={moved}; oracle {PERSONAL_ECL_JULY:,.0f} -> "
          f"{PERSONAL_ECL:,.0f}",
          answer=turn[:900], screenshot=s.shot("nl-06"))

    # ------------------------------------------------------------ narrowing
    turn = ask(s, "Only salary transfer customers.")
    narrowed = said(turn, "salary") and said(turn, "personal")
    _case(rec, "NL-07", "A narrowing turn adds a condition and keeps the rest",
          bool(turn) and narrowed,
          f"the new condition is applied and the product survived={narrowed}",
          answer=turn[:900], screenshot=s.shot("nl-07"))

    # ----------------------------------------------------------- broadening
    #
    # "All products" drops the PRODUCT restriction and keeps the salary
    # transfer condition the reader added one turn earlier — widening out of
    # one filter is not a reset, and answering it with the whole book would
    # silently discard what they had just asked for. So the right answer is
    # every product among salary-transfer customers, and the caption has to
    # say that is the population.
    turn = ask(s, "Now show all products.")
    products = sum(1 for p in ("Personal Finance", "Credit Card",
                               "Home Finance", "Auto Finance")
                   if p.lower() in turn.lower())
    widened = (products == 4
               and has(turn, SALARY_ECL, tolerance=SALARY_ECL * 0.002)
               and said(turn, "salary"))
    _case(rec, "NL-08", "A broadening turn drops the filter it widens out of "
          "and keeps the one it does not",
          bool(turn) and widened,
          f"{products} of 4 products on screen; the salary-transfer total and "
          f"the population are stated={widened}; oracle {SALARY_ECL:,.0f}",
          answer=turn[:900], expected=f"{SALARY_ECL:,.0f}",
          screenshot=s.shot("nl-08"))

    # ----------------------------------------------------------- correction
    #
    # The population is still salary-transfer customers across all products,
    # because a correction changes the MEASURE and nothing else. What must not
    # survive is the figure being corrected: an answer carrying both columns
    # has answered the question and the one it replaced.
    turn = ask(s, "No, I meant gross carrying amount, not expected credit "
                  "loss.")
    corrected = (has(turn, SALARY_GCA, tolerance=SALARY_GCA * 0.002)
                 and not has(turn, SALARY_ECL, tolerance=SALARY_ECL * 0.002))
    _case(rec, "NL-09", "A correction REPLACES the measure rather than adding "
          "it", bool(turn) and corrected,
          f"gross carrying amount replaced ECL={corrected}; oracle "
          f"{SALARY_GCA:,.0f}, and {SALARY_ECL:,.0f} must be gone",
          answer=turn[:900], expected=f"{SALARY_GCA:,.0f}",
          screenshot=s.shot("nl-09"))

    # ------------------------------------------- a paragraph with three parts
    turn = ask(s, "I want to understand the retail book this month. Show me "
                  "expected credit loss by product, tell me which product "
                  "carries the most, and say whether that has changed since "
                  "July.")
    parts = sum(1 for w in ("product", "largest", "2026-07") if w in turn.lower())
    _case(rec, "NL-10", "A three-part paragraph is answered as three parts, "
          "or says which part it could not take",
          bool(turn) and (parts >= 2 or said(turn, "answered", "outstanding",
                                             "partly")),
          f"{parts} of 3 parts visible in the answer",
          answer=turn[:1200], screenshot=s.shot("nl-10"))

    # ------------------------------------- free text instead of clicking a chip
    s.go("/what-if", settle=5000)
    turn = ask(s, "Increase PD by 2.", selector=WHATIF_COMPOSER)
    asked_back = said(turn, "percentage point", "percent of the current",
                      "will not guess")
    _case(rec, "NL-11", "An ambiguous unit is asked about rather than guessed",
          bool(turn) and asked_back,
          f"the two readings are offered={asked_back}",
          answer=turn[:900], screenshot=s.shot("nl-11"))

    turn = ask(s, "I meant 2 percentage points.", selector=WHATIF_COMPOSER)
    answered_in_words = said(turn, "percentage point") and not said(
        turn, "will not guess")
    _case(rec, "NL-12", "The clarification can be answered in free text rather "
          "than by clicking", bool(turn) and answered_in_words,
          f"the typed answer resolved the ambiguity={answered_in_words}",
          answer=turn[:900], screenshot=s.shot("nl-12"))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_language", suite))
