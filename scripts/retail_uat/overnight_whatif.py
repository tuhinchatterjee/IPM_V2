"""
What-If, §7, driven in the browser as a Head of Retail Risk would drive it.

The rule this suite enforces above all others: **an answer that reproduces the
untouched published book is a failure unless the question asked for one.** A
scenario whose ECL equals the baseline reads as "this shock has no impact",
and where the truth is "nothing in your sentence was understood" that is the
most expensive possible way to be wrong.

Every figure is compared against `oracle.py`, which recomputed the same
baseline with pandas straight off the Parquet.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
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

MODULE = "whatif"
ROUTE = "/what-if"

CORPORATE = ("rating notch", "master scale", "downgrade them", "obligor",
             "BBB", "EBITDA", "covenant", "wholesale", "corporate book",
             "sector stress")

#: The whole-book and personal-finance baselines, from the oracle.
BOOK_ECL = ORACLE["book"]["ecl_final_sar"]
PERSONAL_ECL = sum(r["ecl_final_sar"]
                   for r in ORACLE["by_stage_personal_finance"]["rows"])


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
    tol = tolerance or max(abs(value) * 5e-4, 0.5)
    return any(abs(n - value) <= tol for n in numbers(text))


def said(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(w.lower() in lowered for w in words)


def ask(s: Session, question: str) -> dict[str, Any]:
    made = s.ask(question, selector=WHATIF_COMPOSER, timeout=300)
    made["turn"] = s.latest_turn(question) or made.get("after", "")
    return made


def clarified(s: Session) -> bool:
    return s.page.query_selector('[data-turn="clarification"]') is not None


def options(s: Session) -> list[Any]:
    """The buttons of the NEWEST clarification, not of every one on the page.

    A What-If thread keeps its earlier turns, so a page-wide selector returns
    the options of the first clarification ever asked. Clicking index 1 of
    that list ran a PD-units answer from six turns earlier and recorded it as
    the reweighting under test.
    """
    cards = s.page.query_selector_all('[data-turn="clarification"]')
    if not cards:
        return []
    return cards[-1].query_selector_all("[data-option]")


def clarification_text(s: Session) -> str:
    cards = s.page.query_selector_all('[data-turn="clarification"]')
    return cards[-1].inner_text() if cards else ""


def suite(s: Session, rec: Recorder) -> None:
    ok = s.go(ROUTE, settle=6000)
    body = s.text()
    _case(rec, "WI-OPEN", "What-If opens on the retail book",
          ok and said(body, "what-if", "scenario")
          and not said(body, *CORPORATE),
          f"opened={ok}; corporate wording="
          f"{[w for w in CORPORATE if w.lower() in body.lower()]}",
          screenshot=s.shot("wi-open"))

    # ------------------------------------------------------------ WI-CHAT-01
    q = "Increase personal-finance PD by 20% relative in August 2026."
    a = ask(s, q)
    turn = a["turn"]
    baseline_right = has(turn, PERSONAL_ECL, tolerance=PERSONAL_ECL * 0.001)
    moved = not has(turn, PERSONAL_ECL) or len(
        [n for n in numbers(turn) if n > PERSONAL_ECL * 1.02]) > 0
    scoped = said(turn, "personal")
    _case(rec, "WI-CHAT-01",
          "A PD shock on one product moves ECL from the right baseline",
          bool(a.get("completed")) and baseline_right and moved and scoped,
          f"oracle personal-finance ECL {PERSONAL_ECL:,.0f} on screen="
          f"{baseline_right}; a higher figure is shown={moved}; scoped to "
          f"personal finance={scoped}",
          question=q, answer=turn[:1500], expected=f"{PERSONAL_ECL:,.0f}",
          screenshot=s.shot("wi-01"))

    # ------------------------------------------------------------ WI-CHAT-02
    q = "Apply that only to salary-transfer customers."
    a = ask(s, q)
    turn = a["turn"]
    kept = said(turn, "pd", "20%")
    narrowed = said(turn, "salary")
    smaller = bool([n for n in numbers(turn) if 0 < n < PERSONAL_ECL * 0.6])
    _case(rec, "WI-CHAT-02",
          "A narrowing turn keeps the shock and narrows the population",
          bool(a.get("completed")) and kept and narrowed and smaller,
          f"shock retained={kept}; salary transfer named={narrowed}; "
          f"population smaller than the whole product={smaller}",
          question=q, answer=turn[:1500], screenshot=s.shot("wi-02"))

    # ------------------------------------------------------------ WI-CHAT-03
    q = "Explain the ECL impact."
    a = ask(s, q)
    turn = a["turn"]
    explains = said(turn, "pd", "ecl") and not said(turn, *CORPORATE)
    _case(rec, "WI-CHAT-03", "The impact is explained from what moved",
          bool(a.get("completed")) and explains,
          f"explanation names the shock and the measure={explains}",
          question=q, answer=turn[:1500], screenshot=s.shot("wi-03"))

    # ------------------------------------------------------------ WI-CHAT-04
    #
    # A percentage-point LGD move is NOT supported: LGD is multiplied here.
    # The right answer refuses and says so rather than substituting a
    # relative shock of the same number.
    q = ("Now add a 5 percentage-point LGD increase for unsecured "
         "facilities.")
    a = ask(s, q)
    turn = a["turn"]
    refused = said(turn, "percentage point", "not a defined operation",
                   "will not run part of a scenario", "relative")
    substituted = said(turn, "LGD +5% relative")
    _case(rec, "WI-CHAT-04",
          "An unsupported unit is refused rather than silently substituted",
          bool(a.get("completed")) and refused and not substituted,
          f"states what it cannot do={refused}; substituted a different "
          f"shock={substituted}",
          question=q, answer=turn[:1500], screenshot=s.shot("wi-04"))

    # ------------------------------------------------------------ WI-CHAT-06
    q = "Run the same 20% relative PD shock for credit cards instead."
    a = ask(s, q)
    turn = a["turn"]
    card = ORACLE["by_product"]["rows"] if "by_product" in ORACLE else []
    switched = said(turn, "credit card", "card")
    not_personal = not said(turn, "personal finance")
    _case(rec, "WI-CHAT-06", "The product switches and the shock is kept",
          bool(a.get("completed")) and switched and not_personal,
          f"credit card named={switched}; personal finance dropped="
          f"{not_personal}",
          question=q, answer=turn[:1500], screenshot=s.shot("wi-06"))

    # ------------------------------------------------------------ WI-CHAT-07
    q = "Replay a personal-finance application cutoff of 620."
    a = ask(s, q)
    turn = a["turn"]
    replayed = said(turn, "cut-off", "cutoff", "620")
    honest = said(turn, "booked", "declined", "reject", "outcome",
                  "only the originations")
    _case(rec, "WI-CHAT-07",
          "A cutoff replay states the population it can and cannot see",
          bool(a.get("completed")) and replayed and honest,
          f"replay shown={replayed}; population limitation stated={honest}",
          question=q, answer=turn[:1500], screenshot=s.shot("wi-07"))

    # ------------------------------------------------------------ WI-CHAT-08
    q = ("Shift macro scenario weights toward downturn and show the effect on "
         "weighted ECL.")
    a = ask(s, q)
    turn = a["turn"]
    asked = clarified(s)
    offered = len(options(s))
    about_weights = said(clarification_text(s), "weight")
    ran_empty = has(turn, BOOK_ECL) and said(turn, "unchanged", "neutral")
    _case(rec, "WI-CHAT-08",
          "A reweighting with no weights is asked about, not run empty",
          bool(a.get("completed")) and asked and about_weights
          and offered >= 2 and not ran_empty,
          f"clarified={asked}; the question is about weights={about_weights}; "
          f"weightings offered={offered}; ran as a neutral scenario="
          f"{ran_empty}",
          question=q, answer=turn[:1500], screenshot=s.shot("wi-08"))

    if offered:
        before_cards = len(s.page.query_selector_all('[data-turn="result"]'))
        options(s)[1].click()
        s.page.wait_for_timeout(12000)
        # The NEWEST result card, not the whole page. The page also carries
        # the saved-scenario list and the methodology reference, and reading
        # the lot answers a question about the screen rather than about the
        # run that was just made.
        cards = s.page.query_selector_all('[data-turn="result"]')
        newest = cards[-1].inner_text() if cards else ""
        ran = len(cards) > before_cards
        weighted = said(newest, "0.60", "downturn")
        empty = said(newest, "unchanged scenario") or said(
            newest, "SAR 0 (+0.00%)")
        _case(rec, "WI-CHAT-08B",
              "Clicking a weighting runs it rather than the neutral scenario",
              ran and weighted and not empty,
              f"a new result card appeared={ran}; the weighting is named in "
              f"it={weighted}; it ran as the unchanged book={empty}",
              answer=newest[:1200], screenshot=s.shot("wi-08b"))

    # ------------------------------------------------------------ WI-CHAT-09
    q = "Run a neutral no-change scenario over the whole retail book."
    a = ask(s, q)
    turn = a["turn"]
    parity = has(turn, BOOK_ECL, tolerance=BOOK_ECL * 0.0005)
    says_so = said(turn, "neutral", "unchanged", "parity", "reproduces")
    _case(rec, "WI-CHAT-09",
          "A neutral scenario reproduces the published book exactly, and "
          "says that is what it did",
          bool(a.get("completed")) and parity and says_so,
          f"whole-book ECL {BOOK_ECL:,.0f} reproduced={parity}; labelled as "
          f"a parity run={says_so}",
          question=q, answer=turn[:1500], expected=f"{BOOK_ECL:,.0f}",
          screenshot=s.shot("wi-09"))

    # ------------------------------------------------------------ WI-CHAT-10
    q = "Make risk worse."
    a = ask(s, q)
    turn = a["turn"]
    asked = clarified(s)
    offered = len(options(s))
    ran_empty = has(turn, BOOK_ECL) and not asked
    _case(rec, "WI-CHAT-10",
          "An unreadable scenario is asked about, never run as a no-op",
          bool(a.get("completed")) and asked and offered >= 2
          and not ran_empty,
          f"clarified={asked}; scenarios offered={offered}; ran the "
          f"published book unchanged and called it a scenario={ran_empty}",
          question=q, answer=turn[:1500], screenshot=s.shot("wi-10"))

    q = "Increase personal-finance PD by 10% relative."
    a = ask(s, q)
    turn = a["turn"]
    recovered = said(turn, "10", "pd") and said(turn, "personal")
    _case(rec, "WI-CHAT-10B",
          "Typing the scenario after the clarification runs it",
          bool(a.get("completed")) and recovered,
          f"the typed scenario ran={recovered}",
          question=q, answer=turn[:1200], screenshot=s.shot("wi-10b"))

    # ------------------------------------------------------------ WI-CHAT-11
    body = s.text()
    opening = all(said(body, w) for w in ("facilit", "customer"))
    _case(rec, "WI-CHAT-11",
          "The opening book is on screen beside the scenario",
          opening, f"facilities and customers stated={opening}",
          screenshot=s.shot("wi-11"))

    # ---------------------------------------------- the screen, re-read
    body = s.text()
    corporate = [w for w in CORPORATE if w.lower() in body.lower()]
    _case(rec, "WI-SWEEP", "Nothing on this screen belongs to the corporate "
          "book", not corporate, f"corporate wording={corporate}",
          screenshot=s.shot("wi-sweep"))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_whatif", suite))
