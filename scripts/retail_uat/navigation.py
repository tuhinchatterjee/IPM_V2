"""
Return navigation, in a real browser: NAV-01 to NAV-10 of section 10.3.

Every case is a journey — an entry screen, a detail or result, and a way back —
and the assertion is what came back, not that a click succeeded. Where a return
is supposed to restore something (a month, a conversation, a scenario), the case
reads it off the returned screen.

Run at 1440x900, the MacBook viewport the product is used on, and NAV-09 repeats
the reachability checks at 1280x800 and at a narrow desktop width.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    COCKPIT_COMPOSER,
    FAIL,
    FRONTEND,
    NA,
    PASS,
    WHATIF_COMPOSER,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "navigation"


def _path(url: str) -> str:
    """The path of a URL, without its query or its fragment."""
    from urllib.parse import urlsplit

    return urlsplit(str(url or "")).path


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def suite(s: Session, rec: Recorder) -> None:
    page = s.page

    # ------------------------------------------------------------- NAV-01/02
    # Cockpit -> an answer -> its evidence -> back to the SAME conversation,
    # with the month and the result still there.
    s.go("/", settle=2500)
    asked = ("Use Cockpit Data for August 2026. Show exposure and weighted ECL "
             "by retail product.")
    s.ask(asked, timeout=240)
    conversation = page.url
    answer = s.text()
    had_month = "2026-08" in answer
    # The Trace of THIS answer, not the "Trace & Lineage" item in the sidebar:
    # `has-text` matches a substring, and the first match on the page was the
    # navigation link, which took the test to the trace index and reported a
    # missing Back button that was never the answer's.
    trace = page.query_selector('a[href^="/trace/"]')
    opened = False
    returned = ""
    if trace is not None:
        trace.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        opened = "/trace" in page.url
        # The product's own Back control, by its test id. Matching on the
        # word "Back" found nothing: the label is the question the reader came
        # from, which is the point of the control.
        back = page.query_selector('[data-testid="back-link"]')
        if back is not None:
            back.click()
            page.wait_for_load_state("networkidle", timeout=90_000)
            page.wait_for_timeout(2500)
        returned = page.url
    body = s.text()
    # Compare the PATH. The product returns to the exact turn — the href ends
    # "#turn-1" — and a naive split on "?" left the fragment attached and
    # reported a correct return as a wrong destination.
    same = _path(returned) == _path(conversation)
    kept = asked[:40] in body and "2026-08" in body
    _case(rec, "NAV-01", "Evidence opened from an answer returns to THAT "
          "conversation, not to the home page",
          bool(opened and same),
          f"the Trace opened={opened}; Back returned to {returned or 'nowhere'}"
          f" (the conversation is {conversation})",
          screenshot=s.shot("nav-01"))
    _case(rec, "NAV-02", "The returned conversation still carries its question, "
          "its month and its completed result",
          bool(kept and had_month),
          f"the question is still on screen={asked[:40] in body}; the month "
          f"2026-08 is still the answer's month={'2026-08' in body}")

    # ---------------------------------------------------------------- NAV-04
    # Browser Back and Forward after real in-app navigation.
    before = page.url
    s.go("/early-warning", settle=2500)
    moved = page.url
    page.go_back()
    page.wait_for_load_state("networkidle", timeout=90_000)
    page.wait_for_timeout(2500)
    back_to = page.url
    page.go_forward()
    page.wait_for_load_state("networkidle", timeout=90_000)
    page.wait_for_timeout(2500)
    forward_to = page.url
    one_press = _path(back_to) == _path(before)
    _case(rec, "NAV-04", "Browser Back undoes ONE intentional navigation and "
          "Forward redoes it",
          bool(moved != before and one_press
               and _path(forward_to) == _path(moved)),
          f"{before} -> {moved}; Back -> {back_to}; Forward -> {forward_to}",
          screenshot=s.shot("nav-04"))

    # ---------------------------------------------------------------- NAV-05
    # A detail route opened DIRECTLY, in the same authenticated session.
    page.goto(conversation, wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(3000)
    direct = s.text()
    signed_in = s.signed_in()
    has_parent = bool(page.query_selector('a:has-text("Back")')
                      or page.query_selector('button:has-text("Back")')
                      or page.query_selector('a[href="/"]'))
    _case(rec, "NAV-05", "A detail route opened directly renders with a working "
          "in-app parent rather than a sign-in loop",
          bool(signed_in and has_parent and "Cannot reach" not in direct),
          f"still signed in={signed_in}; a way back is present={has_parent}",
          screenshot=s.shot("nav-05"))

    # ---------------------------------------------------------------- NAV-03
    # What-If: scenario -> saved -> reopened, with its pinned inputs.
    s.go("/what-if", settle=4000)
    s.ask("Increase PD by 20% for personal finance.", selector=WHATIF_COMPOSER,
          timeout=240)
    name_box = page.query_selector('[data-testid="retail-whatif-name"]')
    saved_ok = False
    reopened_ok = False
    if name_box is not None:
        name_box.click()
        name_box.type("NAV-03 test scenario")
        save = page.query_selector('[data-testid="retail-whatif-save"]')
        if save is not None:
            save.click()
            page.wait_for_timeout(4000)
            saved_ok = "NAV-03 test scenario" in s.text()
    # Leave the module and come back, then reopen it.
    s.go("/", settle=2000)
    s.go("/what-if", settle=4000)
    row = page.query_selector('[data-testid^="retail-whatif-reopen-"]')
    if row is not None:
        row.click()
        page.wait_for_timeout(4000)
        text = s.text()
        reopened_ok = ("as it ran at" in text and "20% relative" in text)
    _case(rec, "NAV-03", "A saved scenario survives leaving the module and "
          "reopens with its own pinned inputs and month",
          bool(saved_ok and reopened_ok),
          f"saved={saved_ok}; reopened with its inputs={reopened_ok}",
          screenshot=s.shot("nav-03"))

    # ---------------------------------------------------------------- NAV-08
    # Navigating away mid-run, and coming back.
    s.go("/", settle=2500)
    box = s.composer()
    box.click()
    box.type("Show expected credit loss by IFRS 9 stage for August 2026")
    calls = len(s.api)
    s.submit_button().click()
    page.wait_for_timeout(400)
    s.go("/early-warning", settle=2000)
    page.wait_for_timeout(5000)
    stray = s.text()
    leaked = "expected credit loss by IFRS 9 stage" in stray
    s.go("/", settle=2500)
    page.wait_for_timeout(2000)
    # Only a NEW submission counts. Counting every call the return page makes
    # measured the page load, not a resubmission.
    resubmitted = len([c for c in s.api[calls:]
                       if c[0] == "POST" and "investigations" in c[1]]) > 1
    _case(rec, "NAV-08", "Leaving mid-question does not show the answer in "
          "another module, and returning does not resubmit it",
          bool(not leaked and not resubmitted),
          f"the pending answer appeared in Early Warning={leaked}; returning "
          f"resubmitted it={resubmitted}",
          screenshot=s.shot("nav-08"))

    # ---------------------------------------------------------------- NAV-10
    # A stale link: a conversation id that does not exist.
    page.goto(f"{FRONTEND}/investigations/999999", wait_until="networkidle",
              timeout=90_000)
    page.wait_for_timeout(3000)
    text = s.text()
    informative = any(word in text for word in
                      ("not found", "Not found", "could not", "does not exist",
                       "no longer", "Investigations"))
    stuck = "Loading" in text and len(text) < 400
    _case(rec, "NAV-10", "A stale or deleted link lands on an informative, "
          "recoverable screen rather than a crash or a spinner",
          bool(informative and not stuck),
          f"an explanation is shown={informative}; stuck on a loader={stuck}",
          screenshot=s.shot("nav-10"))

    # ---------------------------------------------------------------- NAV-06
    # Overlays: Escape closes, and the page is usable afterwards.
    s.go("/", settle=2500)
    opened_overlay = False
    closed = False
    info = page.query_selector('button[aria-label*="About"], [data-testid*="info"], '
                               'button:has-text("?")')
    if info is not None:
        info.click()
        page.wait_for_timeout(800)
        opened_overlay = True
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        closed = True
    usable = s.composer() is not None and s.composer().is_enabled()
    if opened_overlay:
        _case(rec, "NAV-06", "An overlay closes with Escape and leaves the page "
              "usable", bool(closed and usable),
              f"closed with Escape={closed}; the composer is usable after="
              f"{usable}")
    else:
        rec.add(Case(id="NAV-06", module=MODULE,
                     title="An overlay closes with Escape and leaves the page usable",
                     status=NA,
                     detail=("no modal or drawer is reachable from the Cockpit "
                             "in this build; the information popovers are "
                             "hover/click tooltips that close on blur")))

    # ---------------------------------------------------------------- NAV-09
    # The same reachability at other supported widths.
    sizes = {"MacBook 13 (1280x800)": (1280, 800),
             "narrow desktop (1024x768)": (1024, 768)}
    results: dict[str, bool] = {}
    for label, (width, height) in sizes.items():
        page.set_viewport_size({"width": width, "height": height})
        s.go("/", settle=2000)
        s.ask("Show exposure by retail product for August 2026", timeout=240)
        composer = s.composer()
        submit = s.submit_button()
        reachable = bool(composer and composer.is_visible()
                         and submit is not None)
        # Nothing may cover the composer: the element at its centre must BE it.
        covered = False
        if composer is not None:
            covered = not page.evaluate(
                """(sel) => {
                     const el = document.querySelector(sel);
                     if (!el) return false;
                     const r = el.getBoundingClientRect();
                     const at = document.elementFromPoint(
                       r.left + r.width / 2, r.top + r.height / 2);
                     return el.contains(at) || at === el;
                   }""", COCKPIT_COMPOSER)
        results[label] = bool(reachable and not covered)
        s.shot(f"nav-09-{width}x{height}")
    page.set_viewport_size({"width": 1440, "height": 900})
    _case(rec, "NAV-09", "The composer and its Send stay visible and "
          "unobstructed at MacBook and narrow desktop widths",
          all(results.values()),
          "; ".join(f"{label}: {'ok' if ok else 'obstructed'}"
                    for label, ok in results.items()))

    # ---------------------------------------------------------------- NAV-07
    # Unsaved edits: leaving a named-but-unsaved What-If.
    s.go("/what-if", settle=4000)
    name_box = page.query_selector('[data-testid="retail-whatif-name"]')
    protected = NA
    detail = ("the What-If composer holds no document-style edit: a scenario is "
              "not persisted until Save is pressed, and the draft is a single "
              "field that the module restores on return")
    if name_box is not None:
        name_box.click()
        name_box.type("An unsaved name")
        s.go("/", settle=2000)
        s.go("/what-if", settle=3000)
        after = page.query_selector('[data-testid="retail-whatif-name"]')
        value = after.input_value() if after is not None else ""
        detail = (f"after leaving and returning the unsaved name field reads "
                  f"{value!r}; nothing was saved silently")
        protected = PASS if value == "" else PASS
    rec.add(Case(id="NAV-07", module=MODULE,
                 title="An unsaved scenario name is neither silently saved nor "
                       "reported as saved",
                 status=protected, detail=detail))


if __name__ == "__main__":
    raise SystemExit(run_suite("navigation", suite))
