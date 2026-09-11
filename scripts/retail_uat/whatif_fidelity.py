"""
What-If fidelity WF-01 to WF-22, in a real browser.

Revision 3 §3 asks one question: did wiring a retail What-If screen quietly
reduce the product? This suite answers the half that cannot be answered by
reading code — whether a person sitting at the route the launcher serves can
actually REACH what the screen says it implements.

The screen prints twelve methodologies under "What this engine implements",
generated from the engine's own contract. That list is always complete and
proves nothing: the composer is the only way in, and until this suite existed
one of the twelve could not be reached by typing a sentence at all. "Replay an
application cutoff of 620" matched no pattern, was read as a scenario with no
shocks, and came back as the published book — a baseline, under the reader's
own question, indistinguishable on the page from an answer.

So every case here types a sentence into the real composer and asserts the
screen came back with something that is NOT the untouched book.

The retired corporate routes are checked too. `/what-if/thread` and the two
model-configuration pages are not in this installation's navigation, which is
not the same as unreachable: a bookmark still opened a corporate screen naming
rating notches over a book that does not exist here.

Nothing destructive runs outside the records this suite creates itself.
"""

from __future__ import annotations

import re
import sys
import time
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

MODULE = "what-if-fidelity"
STAMP = time.strftime("%H%M%S")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


#: Each advertised methodology, the sentence that reaches it, and the words the
#: answer must contain to prove the sentence was READ rather than approximated.
METHODOLOGIES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("WF-04", "pd_relative",
     "Increase PD by 20% relative for personal finance",
     ("PD +20% relative",)),
    ("WF-05", "pd_absolute_pp",
     "Increase PD by 2 percentage points for personal finance",
     ("PD +2 percentage points",)),
    ("WF-06", "lgd_relative",
     "Increase LGD by 10% for personal finance",
     ("LGD +10% relative",)),
    ("WF-07", "collateral_value_pct",
     "Reduce mortgage collateral values by 10%",
     ("collateral values -10% relative",)),
    ("WF-08", "recovery_delay_months",
     "Delay recovery by 6 months for mortgages",
     ("recovery delayed 6 months",)),
    ("WF-09", "utilisation_pp",
     "Increase card utilisation by 15 percentage points",
     ("card utilisation +15 percentage points",)),
    ("WF-10", "ccf_absolute",
     "Set the CCF to 60% for credit cards",
     ("credit conversion factor set to 0.60",)),
    ("WF-11", "income_pct",
     "Reduce verified salary by 15% for salary-transfer customers",
     ("verified income -15% relative",)),
    ("WF-12", "behavioural_score_points",
     "Reduce the behavioural score by 30 points for personal finance",
     ("behavioural score -30 points",)),
    ("WF-13", "scenario_weights",
     "Change scenario weights to base 50%, upturn 10%, downturn 40%",
     ("weights base/upturn/downturn",)),
    ("WF-14", "staging_mode",
     "Increase PD by 20% relative for personal finance and re-evaluate staging",
     ("staging re-evaluated",)),
    ("WF-15", "cutoff_replay",
     "Replay an application cutoff of 620 on personal finance",
     ("replay an application-score cutoff of 620",)),
]

#: Wording that would mean a corporate screen is showing.
CORPORATE = ("rating notch", "master scale", "Downgrade", "sector stress",
             "XGBoost", "Corporate IFRS 9", "BBB", "EBITDA", "covenant")


def _clear(s: Session) -> None:
    button = s.page.query_selector('[data-testid="retail-whatif-clear"]')
    if button:
        button.click()
        s.page.wait_for_timeout(600)


def _money(text: str) -> list[float]:
    return [float(t.replace(",", ""))
            for t in re.findall(r"SAR\s+([\d,]+(?:\.\d+)?)", text)]


def suite(s: Session, rec: Recorder) -> None:
    page = s.page

    # ---------------------------------------------------------------- WF-01
    opened = s.go("/what-if")
    screen = page.query_selector('[data-testid="retail-whatif"]')
    body = s.text()
    _case(rec, "WF-01",
          "The navigation link serves the RETAIL What-If, not the corporate one",
          bool(opened and screen),
          f"opened={opened} retail screen present={bool(screen)}",
          screenshot=s.shot("wf-01-landing"))

    # ---------------------------------------------------------------- WF-02
    advertised = [name for name in (
        "pd_relative", "pd_absolute_pp", "lgd_relative", "collateral_value_pct",
        "recovery_delay_months", "utilisation_pp", "ccf_absolute",
        "scenario_weights", "income_pct", "behavioural_score_points",
        "staging_mode", "cutoff_replay") if name in body]
    _case(rec, "WF-02",
          "The screen names every methodology the engine implements, and both "
          "staging modes",
          len(advertised) == 12 and "frozen_stage" in body
          and "reevaluate_stage" in body,
          f"{len(advertised)} of 12 advertised on screen; "
          f"missing={sorted(set(m for _, m, _, _ in METHODOLOGIES) - set(advertised))}",
          advertised=advertised)

    # ---------------------------------------------------------------- WF-03
    found = [w for w in CORPORATE if w.lower() in body.lower()]
    _case(rec, "WF-03",
          "No corporate rating or sector vocabulary is reachable on the screen",
          not found, f"corporate wording found: {found}" if found else "none found",
          corporate_wording=found)

    # ---------------------------------- WF-04 .. WF-15, one per methodology
    baseline_figures: dict[str, list[float]] = {}
    for cid, name, sentence, must_say in METHODOLOGIES:
        _clear(s)
        asked = s.ask(sentence, selector=WHATIF_COMPOSER, timeout=300)
        turn = s.latest_turn(sentence)
        said = [phrase for phrase in must_say if phrase.lower() in turn.lower()]
        neutral = ("An unchanged scenario over the whole retail book" in turn
                   or "Nothing was shocked" in turn)
        # A cutoff replay is a count, not a revaluation: it is proved by its own
        # card rather than by a movement in ECL.
        if name == "cutoff_replay":
            card = page.query_selector('[data-testid="retail-whatif-cutoff"]')
            moved = bool(card) and "booked originations only" in turn.lower()
            detail = (f"cutoff card present={bool(card)}, "
                      f"booked-only stated={'booked originations only' in turn.lower()}")
        else:
            figures = _money(turn)
            baseline_figures[name] = figures
            # Baseline and What-If must be DIFFERENT numbers on the page.
            moved = len(figures) >= 2 and figures[0] != figures[1]
            detail = f"baseline={figures[:1]} whatif={figures[1:2]}"
        ok = bool(asked.get("completed")) and bool(said) and not neutral and moved
        _case(rec, cid,
              f"'{name}' is reachable by typing a sentence, and is read as "
              f"itself rather than as an unchanged book",
              ok,
              f"read_as matched {said}; neutral={neutral}; {detail}; "
              f"{asked.get('seconds', 0):.0f}s",
              sentence=sentence, methodology=name,
              screenshot=s.shot(f"{cid.lower()}-{name.replace('_', '-')}"))

    # ------------------------------------------- WF-16 the §6.3 conversation
    _clear(s)
    first = "Increase PD by 20% relative for personal finance"
    s.ask(first, selector=WHATIF_COMPOSER, timeout=300)
    one = _money(s.latest_turn(first))

    second = "Apply the same shock only to salary-transfer customers"
    s.ask(second, selector=WHATIF_COMPOSER, timeout=300)
    two_turn = s.latest_turn(second)
    two = _money(two_turn)
    narrowed_kept_the_shock = (
        len(two) >= 2 and two[0] != two[1]
        and "salary transfer flag = True" in two_turn
        and "carrying forward" in two_turn.lower())
    _case(rec, "WF-16",
          "A narrowing follow-up keeps the shock it narrows instead of "
          "answering with the published book",
          narrowed_kept_the_shock,
          f"first run {one[:2]}; narrowed run {two[:2]}; "
          f"population stated={'salary transfer flag = True' in two_turn}; "
          f"carry stated={'carrying forward' in two_turn.lower()}",
          screenshot=s.shot("wf-16-narrowed"))

    # ------------------------------------------- WF-17 replacement, not stack
    third = "Instead increase PD by 2 percentage points"
    s.ask(third, selector=WHATIF_COMPOSER, timeout=300)
    three_turn = s.latest_turn(third)
    three = _money(three_turn)
    replaced = ("PD +2 percentage points" in three_turn
                and "+20% relative" not in three_turn
                and len(three) >= 2 and three[1] != two[1] if len(two) >= 2 else False)
    _case(rec, "WF-17",
          "A replacement replaces the earlier shock rather than compounding on "
          "top of it",
          bool(replaced),
          f"narrowed what-if={two[1:2]}; replaced what-if={three[1:2]}; "
          f"relative shock still shown={'+20% relative' in three_turn}",
          screenshot=s.shot("wf-17-replaced"))

    # ------------------------------------------- WF-18 the same figures fresh
    _clear(s)
    fresh = ("Increase PD by 2 percentage points for personal finance "
             "salary-transfer customers")
    s.ask(fresh, selector=WHATIF_COMPOSER, timeout=300)
    fresh_figures = _money(s.latest_turn(fresh))
    same = (len(fresh_figures) >= 2 and len(three) >= 2
            and fresh_figures[0] == three[0] and fresh_figures[1] == three[1])
    _case(rec, "WF-18",
          "The replaced run and the same scenario asked from scratch reach the "
          "SAME figures — replacement is not almost-replacement",
          same,
          f"after replacement={three[:2]}; from scratch={fresh_figures[:2]}",
          screenshot=s.shot("wf-18-fresh"))

    # ------------------------------------------- WF-19 the units clarification
    _clear(s)
    ambiguous = "Increase PD by 2 for personal finance"
    s.ask(ambiguous, selector=WHATIF_COMPOSER, timeout=300)
    asked_back = page.query_selector('[data-turn="clarification"]')
    options = page.query_selector_all('[data-turn="clarification"] [data-option]')
    _case(rec, "WF-19",
          "An ambiguous unit is answered with a question offering both "
          "readings, not with a guess",
          bool(asked_back) and len(options) == 2,
          f"clarification shown={bool(asked_back)}; options={len(options)}",
          screenshot=s.shot("wf-19-clarification"))

    if options:
        options[1].click()
        page.wait_for_timeout(1500)
        deadline = time.time() + 300
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            if page.query_selector('[data-turn="result"]'):
                break
        chosen_turn = s.text()
        ran_what_it_said = ("PD +2 percentage points" in chosen_turn
                            and "+2% relative" not in chosen_turn)
        _case(rec, "WF-20",
              "Clicking a reading runs EXACTLY that reading, with nothing "
              "carried underneath it",
              ran_what_it_said,
              f"percentage-point reading on screen="
              f"{'PD +2 percentage points' in chosen_turn}; "
              f"relative reading also present={'+2% relative' in chosen_turn}",
              screenshot=s.shot("wf-20-chosen"))
    else:
        _case(rec, "WF-20", "Clicking a reading runs EXACTLY that reading",
              False, "no options were offered to click")

    # ------------------------------------------- WF-21 a retired instruction
    _clear(s)
    retired = "Downgrade every borrower two rating notches"
    s.ask(retired, selector=WHATIF_COMPOSER, timeout=300)
    refusal = page.query_selector('[data-turn="refusal"]')
    refusal_text = s.latest_turn(retired)
    _case(rec, "WF-21",
          "A retired corporate operation is refused WHOLE, with the list of "
          "what this engine does implement",
          bool(refusal) and "retail book with scorecards" in refusal_text
          and "Supported:" in refusal_text,
          f"refusal card={bool(refusal)}; reason stated="
          f"{'retail book with scorecards' in refusal_text}; "
          f"supported list shown={'Supported:' in refusal_text}",
          screenshot=s.shot("wf-21-refusal"))

    # ------------------------------- WF-22 the retired corporate What-If routes
    retired_routes = []
    for route, expect in (("/what-if/thread", "What-If thread"),
                          ("/what-if/models/delta", "Delta Model configuration"),
                          ("/what-if/models/ml", "ML Model configuration")):
        page.goto(f"{page.url.split('/what-if')[0]}{route}",
                  wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        text = s.text()
        fallback = page.query_selector('[data-testid="retired-screen"]')
        instead = page.query_selector('[data-testid="retired-instead"]')
        corporate = [w for w in CORPORATE if w.lower() in text.lower()
                     and w.lower() not in expect.lower()]
        # "Corporate IFRS 9" naming the book that is NOT served is the
        # explanation, not a corporate surface: the test is that no corporate
        # DATA screen rendered.
        rendered_corporate = bool(page.query_selector('[data-testid="whatif-result"]')
                                  or page.query_selector('[data-model="ml"]'))
        retired_routes.append({
            "route": route, "fallback": bool(fallback),
            "link_back": bool(instead), "heading_matched": expect in text,
            "corporate_screen_rendered": rendered_corporate,
            "screenshot": s.shot(f"wf-22{route.replace('/', '-')}"),
        })
    ok = all(r["fallback"] and r["link_back"] and r["heading_matched"]
             and not r["corporate_screen_rendered"] for r in retired_routes)
    _case(rec, "WF-22",
          "A direct link to a retired corporate What-If route lands on a "
          "meaningful in-app fallback, not on a corporate screen over a book "
          "that is not served",
          ok,
          "; ".join(f"{r['route']}: fallback={r['fallback']} "
                    f"link={r['link_back']} corporate={r['corporate_screen_rendered']}"
                    for r in retired_routes),
          routes=retired_routes)


if __name__ == "__main__":
    raise SystemExit(run_suite("whatif_fidelity", suite))
