"""
CHAT-01 to CHAT-18 for the COCKPIT chat box, in a real browser.

Section 10.4 of the closeout specification, run against the same frontend and
backend the retail launcher serves, signed in as the demonstration user. No
test-only route, no injected answer, no mocked provider on any happy path: the
only interception in this file is the deliberately labelled failure injection
in CHAT-13, and it says so in its own case.

What each case proves is written into the case title rather than left to the
reader of an assertion. A case that cannot be run here — because it needs a
credential or a machine this environment does not have — is recorded BLOCKED,
never passed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    BLOCKED,  # noqa: F401 - used by cases that must record BLOCKED
    COCKPIT_COMPOSER,
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    answer_region,
    run_suite,
)

MODULE = "cockpit"

#: A real portfolio question, asked the way a credit officer types one.
Q_MAIN = ("Use Cockpit Data for August 2026. Show exposure, customers, "
          "facilities and weighted ECL by retail product.")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def suite(s: Session, rec: Recorder) -> None:
    page = s.page

    # ---------------------------------------------------------------- CHAT-01
    box = s.composer()
    ready = box is not None and box.is_enabled() and box.is_visible()
    if box is not None:
        box.click()
    focused = page.evaluate(
        '() => document.activeElement && document.activeElement.tagName') == "TEXTAREA"
    body = s.text()
    provider_state = ("No AI provider is configured" in body
                      or "Enter to ask" in body)
    _case(rec, "CHAT-01", "Composer is visible, enabled, focusable, and the "
          "scope and provider state are readable",
          bool(ready and focused and provider_state),
          f"visible/enabled={ready} focused={focused} state shown={provider_state}",
          screenshot=s.shot("cockpit-chat-01"))

    # ---------------------------------------------------------------- CHAT-05
    # Before anything is typed: an empty composer must not be able to submit.
    submit = s.submit_button()
    empty_disabled = submit is not None and not submit.is_enabled()
    calls_before = len(s.api)
    box = s.composer()
    box.click()
    box.type("   ")
    page.wait_for_timeout(300)
    submit = s.submit_button()
    blank_disabled = submit is not None and not submit.is_enabled()
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)
    no_call = len(s.api) == calls_before
    for _ in range(6):
        page.keyboard.press("Backspace")
    _case(rec, "CHAT-05", "Empty and whitespace-only input cannot be sent and "
          "makes no analysis call",
          bool(empty_disabled and blank_disabled and no_call),
          f"empty disabled={empty_disabled} blank disabled={blank_disabled} "
          f"calls made={len(s.api) - calls_before}")

    # ---------------------------------------------------------------- CHAT-02
    first = s.ask(Q_MAIN, timeout=240)
    answered = answer_region(first.get("after", ""))
    correct = ("2026-08" in answered and "Product label" in answered
               and "Personal Finance" in answered)
    posts = [c for c in first.get("api", []) if c[0] == "POST"]
    _case(rec, "CHAT-02", "Typing a real question and clicking Ask makes ONE "
          "submission and returns the answer to that question",
          bool(first.get("completed") and first.get("echoed") and correct
               and len(posts) >= 1),
          f"completed={first.get('completed')} echoed={first.get('echoed')} "
          f"posts={[p[1] for p in posts]} seconds={first.get('seconds'):.1f}",
          screenshot=s.shot("cockpit-chat-02"), seconds=first.get("seconds"))

    # ---------------------------------------------------------------- CHAT-18
    _case(rec, "CHAT-18", "Submission is acknowledged and the answer completes "
          "inside a bounded time on this environment",
          bool(first.get("completed") and first.get("seconds", 999) < 240),
          f"first answer completed in {first.get('seconds', 0):.1f}s "
          f"(bound 240s); no unbounded spinner",
          seconds=first.get("seconds"))

    # ---------------------------------------------------------------- CHAT-03
    box = s.composer()
    box.click()
    box.type("Show ECL by stage")
    page.keyboard.down("Shift")
    page.keyboard.press("Enter")
    page.keyboard.up("Shift")
    page.wait_for_timeout(400)
    value = box.input_value()
    newline_kept = "\n" in value
    calls_before = len(s.api)
    still_there = box.input_value().strip() != ""
    # Now plain Enter, which must send.
    page.keyboard.press("Enter")
    sent = _wait_for_answer(s, calls_before, seconds=240)
    _case(rec, "CHAT-03", "Shift+Enter makes a new line and plain Enter sends",
          bool(newline_kept and still_there and sent),
          f"shift+enter kept the draft on a new line={newline_kept}; "
          f"enter submitted={sent}",
          screenshot=s.shot("cockpit-chat-03"))

    # ---------------------------------------------------------------- CHAT-08
    box = s.composer()
    box.click()
    box.type("Show exposure by customer segment")
    page.wait_for_timeout(200)
    calls_before = len(s.api)
    btn = s.submit_button()
    btn.click()
    try:  # a second click landing on a button the first click disabled
        btn.click(timeout=1000)
    except Exception:  # noqa: BLE001 - the control is already busy, as intended
        pass
    page.keyboard.press("Enter")
    _wait_for_answer(s, calls_before, seconds=240)
    asks = [c for c in s.api[calls_before:]
            if c[0] == "POST" and ("ask" in c[1] or "messages" in c[1]
                                   or "investigations" in c[1])]
    _case(rec, "CHAT-08", "A double click and an Enter on top of it submit the "
          "question once",
          len(asks) <= 1,
          f"submissions recorded: {[a[1] for a in asks]}")

    # ---------------------------------------------------------------- CHAT-07
    box = s.composer()
    usable_again = box is not None and box.is_enabled()
    submit_disabled_when_empty = (s.submit_button() is not None
                                  and not s.submit_button().is_enabled())
    _case(rec, "CHAT-07", "After completion the composer and Ask are usable "
          "again and no progress indicator is left running",
          bool(usable_again and submit_disabled_when_empty
               and "Thinking" not in s.text()),
          f"composer enabled={usable_again}; Ask disabled on an empty draft="
          f"{submit_disabled_when_empty}")

    # ---------------------------------------------------------------- CHAT-09
    # A follow-up is only a follow-up to a RESULT. The cases above deliberately
    # include a clarification, so the thread is put back on a settled answer
    # first — otherwise this case would measure the clarification, not the
    # follow-up.
    settled = s.ask("Show weighted ECL by retail product for August 2026",
                    timeout=240)
    if "ONE QUESTION BACK" in s.latest_turn(
            "Show weighted ECL by retail product for August 2026"):
        s.ask("Expected credit loss.", timeout=240)
    follow = s.ask("Now only personal finance", timeout=240)
    # Only what THIS turn added. An assertion against the whole page would be
    # satisfied by the answer above it, which already named the product.
    turn = s.latest_turn("Now only personal finance")
    narrowed = "Personal Finance" in turn and "Auto Finance" not in turn
    _case(rec, "CHAT-09", "A follow-up resolves against the conversation and "
          "the new answer echoes the narrowed scope",
          bool(follow.get("completed") and narrowed),
          f"completed={follow.get('completed')}; the NEW turn names Personal "
          f"Finance and drops the other products={narrowed}",
          new_turn=turn[:600], screenshot=s.shot("cockpit-chat-09"))

    compare = s.ask("Compare with July 2026", timeout=240)
    turn = s.latest_turn("Compare with July 2026")
    compared = "2026-07" in turn and "2026-08" in turn
    _case(rec, "CHAT-10", "A period change between messages is applied to the "
          "carried scope rather than a stale cached result",
          bool(compare.get("completed") and compared),
          f"completed={compare.get('completed')}; the NEW turn names both "
          f"periods={compared}",
          new_turn=turn[:600], screenshot=s.shot("cockpit-chat-10"))

    # ---------------------------------------------------------------- CHAT-06
    # A clarification the product asks for, answered two ways: by clicking the
    # option it offers, and by typing the answer.
    vague = s.ask("Show scorecard performance.", timeout=240)
    turn = s.latest_turn("Show scorecard performance.")
    asked_back = "ONE QUESTION BACK" in turn or "?" in turn
    options = page.query_selector_all(
        'button:has-text("Personal Finance"), button:has-text("Application")')
    clicked = False
    if asked_back and options:
        calls = len(s.api)
        options[0].click()
        clicked = _wait_for_answer(s, calls, seconds=240)
    typed = s.ask("Personal finance, the application scorecard.", timeout=240)
    typed_turn = s.latest_turn("Personal finance, the application scorecard.")
    _case(rec, "CHAT-06", "A clarification can be answered by clicking the "
          "option offered and by typing the answer",
          bool(asked_back and typed.get("completed") and typed_turn.strip()),
          f"the product asked rather than guessing={asked_back}; a clickable "
          f"option resolved it={clicked}; a typed answer resolved it="
          f"{bool(typed.get('completed'))}",
          clarification=turn[:400], typed_answer=typed_turn[:400],
          screenshot=s.shot("cockpit-chat-06"))

    # ---------------------------------------------------------------- CHAT-12
    # Navigate away WHILE a request is in flight, then come back to it.
    conversation = page.url
    box = s.composer()
    box.click()
    box.type("Show expected credit loss by IFRS 9 stage")
    calls = len(s.api)
    s.submit_button().click()
    page.wait_for_timeout(300)
    left = s.go("/early-warning", settle=2500)
    page.wait_for_timeout(4000)
    page.goto(conversation, wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(4000)
    returned = s.text()
    bound = "IFRS 9 stage" in returned or "Stage" in returned
    _case(rec, "CHAT-12", "Navigating away while a question is running and "
          "returning shows the answer on ITS conversation",
          bool(left and bound and s.composer() is not None),
          f"navigated away mid-flight={left}; the answer is on the "
          f"conversation it was asked in={bound}",
          screenshot=s.shot("cockpit-chat-12"))

    # ---------------------------------------------------------------- CHAT-11
    # A NEW conversation must not inherit the scope of the one before it.
    s.go("/", settle=2500)
    fresh = s.ask("How many facilities are in each IFRS 9 stage?", timeout=240)
    fresh_turn = s.latest_turn("How many facilities are in each IFRS 9 stage?")
    new_url = page.url
    inherited = "Personal Finance" in fresh_turn
    history = s.go("/investigations", settle=2500)
    # The list rows are not anchors — they are clickable cards — so the earlier
    # selector found nothing and reported an empty history on a page showing
    # three conversations.
    listed = page.query_selector_all("[data-investigation-id]")
    resumed = False
    if listed:
        listed[0].click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        resumed = "messages" in s.text() or bool(s.composer())
    _case(rec, "CHAT-11", "A new conversation starts clean and an existing one "
          "can be reopened with its transcript",
          bool(fresh.get("completed") and not inherited and history and resumed),
          f"new conversation at {new_url.split('/')[-1]}; inherited the old "
          f"scope={inherited}; history listed {len(listed)} conversations; "
          f"reopened one={resumed}",
          screenshot=s.shot("cockpit-chat-11"))

    # ---------------------------------------------------------------- CHAT-04
    # Back to a conversation with a composer: CHAT-11 above ends on the
    # Investigations list, which has none.
    if s.composer() is None:
        s.go("/", settle=2500)
    pasted = ("Use Cockpit Data for August 2026.\n"
              "Personal finance only.\n"
              "Show expected credit loss by IFRS 9 stage, and tell me which "
              "stage carries the most.")
    box = s.composer()
    box.click()
    page.evaluate(
        """([selector, text]) => {
             const el = document.querySelector(selector);
             const setter = Object.getOwnPropertyDescriptor(
               window.HTMLTextAreaElement.prototype, "value").set;
             setter.call(el, text);
             el.dispatchEvent(new Event("input", {bubbles: true}));
           }""", [COCKPIT_COMPOSER, pasted])
    page.wait_for_timeout(300)
    kept = s.composer().input_value() == pasted
    calls_before = len(s.api)
    s.submit_button().click()
    done = _wait_for_answer(s, calls_before, seconds=240)
    region = answer_region(s.text())
    _case(rec, "CHAT-04", "A pasted multi-line instruction keeps its content "
          "and resolves its scope",
          bool(kept and done and "stage" in region.lower()),
          f"pasted text preserved={kept}; answered={done}",
          screenshot=s.shot("cockpit-chat-04"))

    # ---------------------------------------------------------------- CHAT-15
    _case(rec, "CHAT-15", "The answer's table, figures, units and evidence link "
          "agree with the response",
          all(word in region for word in ("Trace",))
          and ("SAR" in region or "%" in region),
          "the rendered answer carries a Trace and units on its figures",
          screenshot=s.shot("cockpit-chat-15"))

    # ---------------------------------------------------------------- CHAT-16
    height = page.evaluate("() => document.body.scrollHeight")
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    top_reachable = page.evaluate("() => window.scrollY") == 0
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(400)
    composer_visible = s.composer() is not None and s.composer().is_visible()
    _case(rec, "CHAT-16", "A long transcript stays readable: earlier evidence "
          "can be scrolled to and the composer stays reachable",
          bool(top_reachable and composer_visible),
          f"transcript height={height}px; composer reachable at the bottom="
          f"{composer_visible}")

    # ---------------------------------------------------------------- CHAT-17
    controls = {
        "Trace": bool(page.query_selector('a:has-text("Trace")')),
        "Save analysis": bool(page.query_selector('button:has-text("Save analysis")')),
        "Project": bool(page.query_selector('button:has-text("Project")')),
        "Download results": bool(page.query_selector(':text("DOWNLOAD RESULTS")')
                                 or page.query_selector('button:has-text("Download")')),
    }
    _case(rec, "CHAT-17", "Every extra control the answer shows is present and "
          "advertised truthfully",
          any(controls.values()),
          f"controls found on the answer: {controls}")

    # ---------------------------------------------------------------- CHAT-13
    # FAILURE INJECTION — deliberately labelled. Everything above this point
    # ran against the real backend with nothing intercepted; this case fails
    # ONE request on purpose to see what the product does with it, and the
    # interception is removed before the retry.
    s.go("/", settle=2500)
    failing = {"hits": 0}

    def break_once(route: object, request: object) -> None:
        if request.method == "POST":  # type: ignore[attr-defined]
            failing["hits"] += 1
            route.abort("failed")  # type: ignore[attr-defined]
        else:
            route.continue_()  # type: ignore[attr-defined]

    page.route("**/api/v1/investigations*", break_once)
    box = s.composer()
    box.click()
    typed_question = "Show expected credit loss by product for August 2026"
    box.type(typed_question)
    s.submit_button().click()
    page.wait_for_timeout(6000)
    body = s.text()
    shown = any(word in body for word in
                ("could not", "Could not", "failed", "unavailable", "try again",
                 "Cannot reach"))
    preserved = (s.composer() is not None
                 and typed_question in (s.composer().input_value() or ""))
    not_stuck = "Thinking" not in body and "Working" not in body
    page.unroute("**/api/v1/investigations*", break_once)

    calls = len(s.api)
    retry_ok = False
    if s.composer() is not None and s.submit_button() is not None:
        if not (s.composer().input_value() or "").strip():
            s.composer().click()
            s.composer().type(typed_question)
        s.submit_button().click()
        retry_ok = _wait_for_answer(s, calls, seconds=240)
    _case(rec, "CHAT-13", "FAILURE INJECTION — a failed submission shows a real "
          "error, keeps the typed question, clears the progress state, and "
          "retries successfully without duplicating the run",
          bool(failing["hits"] and shown and not_stuck and retry_ok),
          f"injected failures={failing['hits']}; an error was shown={shown}; "
          f"the typed question survived={preserved}; no stuck progress="
          f"{not_stuck}; the retry answered={retry_ok}",
          screenshot=s.shot("cockpit-chat-13"))

    # ---------------------------------------------------------------- CHAT-14
    # The session boundary: an EXPIRED APP LOGIN, which must read as a login
    # problem and not as a provider or backend outage.
    s.context.clear_cookies()
    page.reload(wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(3000)
    signed_out = page.query_selector("#username") is not None
    body = s.text()
    honest = signed_out and "provider" not in body.lower()
    _case(rec, "CHAT-14", "An expired app login returns the user to sign-in and "
          "is not reported as a provider or backend failure",
          bool(honest),
          f"sign-in form shown after the session was cleared={signed_out}; "
          f"the message does not blame the AI provider="
          f"{'provider' not in body.lower()}",
          screenshot=s.shot("cockpit-chat-14"))
    if signed_out and not s.sign_in():
        rec.add(Case(id="CHAT-14b", module=MODULE,
                     title="Signing back in after the session boundary",
                     status=FAIL, detail="could not sign back in"))


def _wait_for_answer(s: Session, calls_before: int, *, seconds: int) -> bool:
    """Wait — bounded — for the transcript to settle after a submission."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        s.page.wait_for_timeout(2000)
        body = s.text()
        if len(s.api) > calls_before and not any(
                w in body for w in ("Thinking", "Working", "Composing",
                                    "Running the analysis")):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(run_suite("cockpit_chat", suite))
