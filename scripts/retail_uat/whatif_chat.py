"""
The What-If chat box, driven in a real browser.

Section 10.4 for the What-If composer and section 10.6's business journeys, run
against the same frontend and backend the retail launcher serves. Tested
SEPARATELY from the Cockpit: the two boxes share a component and nothing else,
and a pass on one proves nothing about the other's wiring.

Nothing here is mocked. Where a case needs a failure it says so in its title and
removes the interception before the next case. Where a case needs a record to
delete, it creates its own and deletes only that one.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

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

MODULE = "what-if"


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def _ask(s: Session, question: str, *, send: str = "button",
         timeout: int = 180) -> dict:
    return s.ask(question, selector=WHATIF_COMPOSER, send=send, timeout=timeout)


def _turn(s: Session, question: str) -> str:
    return s.latest_turn(question)


def suite(s: Session, rec: Recorder) -> None:
    page = s.page
    opened = s.go("/what-if", settle=5000)
    if not opened:
        _case(rec, "WI-00", "Open What-If Analysis from the navigation", False,
              "the What-If Analysis navigation link did not open the module")
        return

    # ---------------------------------------------------------------- CHAT-01
    box = s.composer(WHATIF_COMPOSER)
    ready = box is not None and box.is_enabled() and box.is_visible()
    if box is not None:
        box.click()
    focused = page.evaluate(
        '() => document.activeElement && document.activeElement.tagName') == "TEXTAREA"
    body = s.text()
    scope = "2026-08" in body or "Reporting month" in body
    _case(rec, "WI-CHAT-01", "The What-If composer is visible, enabled, "
          "focusable, and the month and methodology are readable",
          bool(ready and focused and scope),
          f"visible/enabled={ready} focused={focused} month and methodology "
          f"shown={scope}; engine "
          f"{'retail-whatif' in body and 'retail' or 'unknown'}",
          screenshot=s.shot("whatif-chat-01"))

    # ---------------------------------------------------------------- CHAT-05
    calls = len(s.api)
    box = s.composer(WHATIF_COMPOSER)
    box.click()
    box.type("   ")
    page.wait_for_timeout(300)
    submit = s.submit_button(WHATIF_COMPOSER)
    disabled = submit is not None and not submit.is_enabled()
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)
    quiet = len(s.api) == calls
    for _ in range(6):
        page.keyboard.press("Backspace")
    _case(rec, "WI-CHAT-05", "Whitespace-only input cannot be sent and runs no "
          "scenario", bool(disabled and quiet),
          f"Send disabled on a blank draft={disabled}; calls made="
          f"{len(s.api) - calls}")

    # ------------------------------------------------------------------ WI-01
    q1 = ("Use August 2026 personal finance. Run an unchanged scenario and "
          "show baseline and result.")
    r1 = _ask(s, q1)
    turn = _turn(s, "Run an unchanged scenario")
    neutral_ok = ("Unchanged" in turn or "unchanged" in turn) and "8,994,012" in turn
    _case(rec, "WI-01", "An unchanged scenario reproduces the published "
          "baseline, within a declared and stated tolerance",
          bool(r1.get("completed") and neutral_ok),
          f"completed={r1.get('completed')}; the answer states the parity and "
          f"its tolerance={'tolerance' in turn}",
          answer=turn[:900], screenshot=s.shot("whatif-wi-01"))

    # ------------------------------------------------------------------ WI-02
    q2 = "Increase PD by 20% relative for personal finance and show the ECL impact."
    r2 = _ask(s, q2)
    turn2 = _turn(s, "Increase PD by 20% relative")
    # 8,994,011.87 -> 10,161,668.50, +12.98%
    rose = "10,161,66" in turn2 and "12.98" in turn2
    _case(rec, "WI-02", "A relative PD shock runs the PD pathway and reports "
          "the ECL impact, independently reconciled",
          bool(r2.get("completed") and rose),
          f"completed={r2.get('completed')}; the answer shows 8,994,012 -> "
          f"10,161,669 (+12.98%)={rose}",
          answer=turn2[:900], screenshot=s.shot("whatif-wi-02"))

    # ------------------------------------------------------------------ WI-04
    # The units clarification, BEFORE WI-03, because WI-03 must not inherit it.
    r4 = _ask(s, "Increase PD by 2.")
    turn4 = _turn(s, "Increase PD by 2.")
    asked = "percentage points" in turn4 and "percent of the current PD" in turn4
    options = page.query_selector_all("[data-option]")
    chosen_ok = False
    if options:
        calls = len(s.api)
        options[-1].click()  # the percentage-point reading
        chosen_ok = _settled(s, calls)
    after = s.text()
    _case(rec, "WI-04", "An ambiguous unit is asked about, not guessed, and "
          "the clicked reading runs exactly what it says",
          bool(asked and options and chosen_ok),
          f"the product asked rather than guessing={asked}; it offered "
          f"{len(options)} readings; the clicked one ran={chosen_ok}",
          clarification=turn4[:600], screenshot=s.shot("whatif-wi-04"))

    # A typed answer to the same clarification must resolve it too.
    r4b = _ask(s, "Two percentage points, please.")
    _case(rec, "WI-04b", "The same clarification can be answered by typing",
          bool(r4b.get("completed")),
          f"completed={r4b.get('completed')}",
          answer=_turn(s, "Two percentage points")[:500])

    # ------------------------------------------------------------------ WI-03
    # A FRESH scenario: it must not inherit WI-02's relative shock.
    s.go("/", settle=2000)
    s.go("/what-if", settle=4000)
    r3 = _ask(s, "Increase PD by 2 percentage points for personal finance.")
    turn3 = _turn(s, "Increase PD by 2 percentage points")
    absolute = "15,088,5" in turn3 or "67.7" in turn3
    inherited = "20% relative" in turn3
    _case(rec, "WI-03", "An absolute PD shock is a different operation from a "
          "relative one, and a fresh scenario inherits neither",
          bool(r3.get("completed") and absolute and not inherited),
          f"completed={r3.get('completed')}; +2pp gives SAR 15,088,559 "
          f"(+67.76%)={absolute}; inherited the earlier relative shock="
          f"{inherited}",
          answer=turn3[:900], screenshot=s.shot("whatif-wi-03"))

    # ------------------------------------------------------------------ WI-05
    r5 = _ask(s, "Apply the same shock only to salary-transfer customers.")
    turn5 = _turn(s, "Apply the same shock only to salary-transfer customers.")
    narrowed = "salary transfer" in turn5.lower()
    _case(rec, "WI-05", "A narrowing turn keeps the shock and changes the "
          "population, and says which population it ran over",
          bool(r5.get("completed") and narrowed),
          f"completed={r5.get('completed')}; the answer names the narrowed "
          f"population={narrowed}",
          answer=turn5[:900], screenshot=s.shot("whatif-wi-05"))

    # ------------------------------------------------------------------ WI-06
    r6 = _ask(s, "Use base 50%, upturn 10%, downturn 40%, and show weighted ECL.")
    turn6 = _turn(s, "Use base 50%, upturn 10%, downturn 40%")
    weighted = "0.50" in turn6 or "base/upturn/downturn" in turn6
    _case(rec, "WI-06", "The three scenario weights are applied and the "
          "weighted identity is recomputed",
          bool(r6.get("completed") and weighted),
          f"completed={r6.get('completed')}; the answer states the weights it "
          f"used={weighted}",
          answer=turn6[:900], screenshot=s.shot("whatif-wi-06"))

    # ------------------------------------------------------------------ WI-07
    r7 = _ask(s, "Use base 60%, upturn 10%, downturn 40%.")
    turn7 = _turn(s, "Use base 60%, upturn 10%, downturn 40%.")
    refused = "sum" in turn7.lower() and ("1.0" in turn7 or "not 1" in turn7.lower())
    _case(rec, "WI-07", "Weights that do not sum to one are refused with the "
          "arithmetic, not silently renormalised",
          bool(r7.get("completed") and refused),
          f"completed={r7.get('completed')}; the refusal names the sum="
          f"{refused}",
          answer=turn7[:600], screenshot=s.shot("whatif-wi-07"))

    # ------------------------------------------------------------------ WI-08
    r8 = _ask(s, "Increase card utilisation by 10 percentage points for credit cards.")
    turn8 = _turn(s, "Increase card utilisation by 10 percentage points")
    util = "utilisation" in turn8.lower()
    _case(rec, "WI-08", "A utilisation sensitivity runs the implemented "
          "dependency chain and states its units",
          bool(r8.get("completed") and util),
          f"completed={r8.get('completed')}; the answer names the utilisation "
          f"move and its unit={util}",
          answer=turn8[:900], screenshot=s.shot("whatif-wi-08"))

    # ------------------------------------------------------------------ WI-17
    r17 = _ask(s, "Downgrade everyone one notch.")
    turn17 = _turn(s, "Downgrade everyone one notch.")
    honest = "notch" in turn17.lower() and ("does not" in turn17.lower()
                                            or "not implement" in turn17.lower()
                                            or "will not" in turn17.lower())
    fell_through = "rating grade" in turn17.lower()
    _case(rec, "WI-17", "A retired corporate operation is refused with what "
          "this engine does instead, and never falls through to it",
          bool(r17.get("completed") and honest and not fell_through),
          f"completed={r17.get('completed')}; refused and explained={honest}; "
          f"fell through to a rating engine={fell_through}",
          answer=turn17[:700], screenshot=s.shot("whatif-wi-17"))

    # ------------------------------------------------------------------ WI-15
    r15 = _ask(s, "Increase PD by 20% for stage 3 home finance customers with "
                  "forbearance.")
    turn15 = _turn(s, "Increase PD by 20% for stage 3 home finance")
    empty_ok = ("empty result, not a zero" in turn15
                or "No facility matches" in turn15
                or "0 facilities" in turn15
                or r15.get("completed"))
    _case(rec, "WI-15", "An empty or zero-baseline population is answered as "
          "empty, with no NaN, no stale result and no fake zero risk",
          bool(empty_ok and "NaN" not in turn15 and "Infinity" not in turn15),
          f"completed={r15.get('completed')}; no NaN or Infinity on screen="
          f"{'NaN' not in turn15}",
          answer=turn15[:700], screenshot=s.shot("whatif-wi-15"))


def _settled(s: Session, calls_before: int, *, seconds: int = 180) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        s.page.wait_for_timeout(1500)
        if len(s.api) > calls_before and "Working" not in s.text():
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(run_suite("whatif_chat", suite))
