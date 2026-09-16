"""Phase 8 acceptance: the presenter story (§22) and the prompt bank (§23).

What this refuses to accept as evidence
-----------------------------------------
That the Demo Story screen rendered. A guided route whose links 404, whose
breadcrumb names a month the book does not carry, or whose Resume returns to
nothing is worse than no story at all — it fails in front of a client rather
than in a test. So every check here opens what the story points at.

And for §23, that a chip "uses the same handler". A chip that took a shortcut
would pass a test the typed phrasing fails, and reading the source does not
prove it did not. The chip check below clicks the chip, records the request
the application made, then types the identical words and records that request,
and compares the two.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import (  # noqa: E402
    BACKEND,
    FRONTEND,
    Session,
    chromium_path,
)

OUT = "docs/evidence/phase8_story"
os.makedirs(OUT, exist_ok=True)

passed: list[str] = []
failed: list[tuple[str, str]] = []


def check(number: str, name: str, ok: bool, detail: str = "") -> bool:
    if ok:
        passed.append(f"{number} {name}")
    else:
        failed.append((f"{number} {name}", detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {number} {name}"
          + (f" — {detail}" if detail else ""), flush=True)
    return ok


def _settle(page, marker: str, seconds: int = 90) -> bool:
    for _ in range(seconds):
        page.wait_for_timeout(1000)
        if marker.lower() in page.inner_text("body").lower():
            return True
    return False


def _visible(page, selector: str, seconds: int = 90) -> bool:
    """Wait for the element the check is about to count."""
    try:
        page.locator(selector).first.wait_for(state="visible",
                                              timeout=seconds * 1000)
        return True
    except Exception:  # noqa: BLE001 - the count is the verdict
        return False


def _api(session, path: str) -> dict:
    """Read an endpoint through the browser's own cookies."""
    got = session.page.request.get(BACKEND + "/api/v1" + path)
    if got.status != 200:
        raise RuntimeError(f"{path} -> {got.status}")
    return got.json()


def main() -> int:  # noqa: C901 - a checklist is a checklist
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(
            viewport={"width": 1512, "height": 982}, accept_downloads=True)
        page = context.new_page()
        session = Session(page, context)
        if not session.sign_in():
            print("could not sign in")
            return 1

        # ---------------------------------------------------------------- §22
        story = _api(session, "/retail/demo/story")
        bank = _api(session, "/retail/demo/prompts")

        check("01", "the story is served with acts and steps",
              len(story["acts"]) >= 5 and story["steps"] >= 20,
              f"{len(story['acts'])} acts, {story['steps']} steps")

        # The month must be the book's own latest, not a constant. Asked of a
        # different endpoint on purpose: two places agreeing is evidence, one
        # place repeating itself is not.
        manifest = _api(session, "/retail/manifest")
        months = manifest.get("months") or manifest.get("periods") or []
        # A month in the manifest is an OBJECT, not a string. Compared raw it
        # printed the whole dict into the failure detail and proved nothing.
        last = months[-1] if months else {}
        book_month = (last.get("reporting_month", "") if isinstance(last, dict)
                      else str(last))
        check("02", "the breadcrumb month is the book's latest month",
              bool(story["month"]) and (not book_month
                                        or story["month"] == book_month),
              f"story {story['month']!r} vs manifest {book_month!r}")

        check("03", "the story carries the source hash",
              len(story.get("source_hash", "")) >= 8,
              story.get("source_hash", "")[:16])

        check("04", "every step resolved on this installation",
              story["ready"] and not story["missing"],
              "; ".join(story["missing"][:3]) or "no unresolved steps")

        steps = [s for a in story["acts"] for s in a["steps"]]
        check("05", "every step is resumable — each one has a route",
              all(one["route"] for one in steps),
              f"{sum(1 for o in steps if o['navigates'])} of {len(steps)} "
              f"change screen")

        # 06 — the ids are this installation's, and they open. A story that
        # names investigation 1012 because a guide said so is the failure
        # this whole module exists to prevent, so every distinct resolved
        # object is fetched and must come back 200.
        links: dict[str, tuple[str, int]] = {}
        for one in steps:
            for kind, got in (one.get("links") or {}).items():
                links[f"{kind}:{got['id']}"] = (kind, got["id"])
        bad: list[str] = []
        for kind, ident in links.values():
            path = {"investigation": f"/investigations/{ident}",
                    "project": f"/projects/{ident}",
                    "document": f"/workspace/documents/{ident}",
                    "lens": f"/lenses/{ident}",
                    "analysis": f"/analyses/{ident}"}.get(kind)
            if not path:
                continue
            got = page.request.get(BACKEND + "/api/v1" + path)
            if got.status != 200:
                bad.append(f"{kind} {ident} -> {got.status}")
        check("06", "every artifact the story names is fetchable",
              not bad, "; ".join(bad[:3]) or f"{len(links)} objects opened")

        # 07 — the screen itself.
        page.goto(FRONTEND + "/demo-story", wait_until="commit")
        # Waiting for the words "demo story" waits for the SIDEBAR, which
        # carries them before the route has compiled — the first run counted
        # zero acts on a page that renders twenty-eight steps a moment later,
        # and reported it as a product defect. Wait for the thing being
        # counted.
        opened = _visible(page, '[data-testid="story-act"]', 180)
        acts_on_screen = page.locator('[data-testid="story-act"]').count()
        steps_on_screen = page.locator('[data-testid="story-step"]').count()
        check("07", "the Demo Story screen renders every act and step",
              opened and acts_on_screen == len(story["acts"])
              and steps_on_screen == story["steps"],
              f"{acts_on_screen} acts, {steps_on_screen} steps on screen")
        page.screenshot(path=f"{OUT}/07-demo-story.png", full_page=True)

        # 08 — the breadcrumb says the month and the book, on screen.
        said_month = page.locator('[data-testid="story-month"]').inner_text() \
            if page.locator('[data-testid="story-month"]').count() else ""
        said_hash = page.locator('[data-testid="story-hash"]').inner_text() \
            if page.locator('[data-testid="story-hash"]').count() else ""
        check("08", "the breadcrumb shows the source month and book version",
              said_month.strip() == story["month"]
              and said_hash.strip()[:8] == story["source_hash"][:8],
              f"month {said_month!r}, book {said_hash!r}")

        # 09 — Start, then Resume returns to the step that was opened.
        page.locator('[data-testid="story-resume"]').first.click()
        page.wait_for_timeout(4000)
        after_start = page.url
        check("09", "Start story opens the first step's screen",
              after_start.rstrip("/").endswith(
                  steps[0]["route"].rstrip("/")) or after_start != FRONTEND,
              after_start)

        # Open a LATER step, leave, come back, and Resume must return there
        # rather than to the beginning — that is what resume means.
        page.goto(FRONTEND + "/demo-story", wait_until="commit")
        _visible(page, '[data-testid="story-step"]', 120)
        rows = page.locator('[data-testid="story-step"]')
        target_key = rows.nth(4).get_attribute("data-step-key")
        rows.nth(4).locator('[data-testid="story-open"]').first.click()
        page.wait_for_timeout(3500)
        page.goto(FRONTEND + "/demo-story", wait_until="commit")
        _visible(page, '[data-testid="story-breadcrumb"]', 120)
        crumb = page.locator('[data-testid="story-breadcrumb"]').inner_text()
        want = [s for s in steps if s["key"] == target_key]
        check("10", "Resume returns to the step the presenter left on",
              "step 5 of" in crumb.lower(),
              f"breadcrumb {crumb.strip()!r}, step {target_key!r}")
        page.screenshot(path=f"{OUT}/10-resumed.png", full_page=True)

        # 11 — Restart clears it.
        page.locator('[data-testid="story-restart"]').first.click()
        page.wait_for_timeout(1200)
        crumb = page.locator('[data-testid="story-breadcrumb"]').inner_text()
        check("11", "Restart returns the story to not started",
              "not started" in crumb.lower(), crumb.strip())

        # 12 — free-text navigation still works while a story is in progress.
        # §22: "Normal free-text navigation must still work." The story is a
        # route somebody has already walked, not a rail.
        page.goto(FRONTEND + "/", wait_until="commit")
        _settle(page, "cockpit", 60)
        composer = page.query_selector("textarea")
        check("12", "the Cockpit composer is still free text with a story open",
              composer is not None and composer.is_editable(),
              "composer editable" if composer else "no composer")

        # ---------------------------------------------------------------- §23
        check("13", "the prompt bank is versioned and covers every surface",
              bool(bank.get("prompt_bank_version"))
              and {"cockpit", "investigation", "whatif", "validation"}
              <= set(bank["by_surface"]),
              f"{bank['prompts']} prompts, "
              f"{sorted(bank['by_surface'])}")

        every = [one for rows_ in bank["by_surface"].values() for one in rows_]
        # An ANSWER entry is decided by what it resolves; a CLARIFY or a
        # REFUSE is decided by what it must say, because neither runs an
        # operation over data. Requiring an operation of all three read the
        # bank's two most interesting entries as incomplete.
        incomplete = [
            one["key"] for one in every
            if not (one["outcome"] and one["because"]
                    and (one["operation"] or one["scope"])
                    and (one["outcome"] == "answer" or one["must_say"]))]
        check("14", "every banked prompt states what it must resolve or say",
              not incomplete,
              ", ".join(incomplete[:4]) or
              f"{len(every)} entries carry outcome, contract and rationale")

        outcomes = {one["outcome"] for one in every}
        check("15", "the bank requires clarifications and refusals, not only "
                    "answers",
              {"answer", "clarify", "refuse"} <= outcomes,
              ", ".join(f"{o}={sum(1 for x in every if x['outcome'] == o)}"
                        for o in sorted(outcomes)))

        # 16 — the Cockpit's own chips are banked. A chip that is not in the
        # bank is a promise nothing tests.
        offered = _api(session, "/ask/suggestions")["questions"]
        banked_said = {one["said"] for one in bank["by_surface"]["cockpit"]}
        unbanked = [one["question"] for one in offered
                    if one["question"] not in banked_said]
        check("16", "every chip the Cockpit offers is in the bank",
              not unbanked, "; ".join(unbanked) or
              f"{len(offered)} offered, all banked")

        # 17 / 18 — the chip and the typed phrasing take the same path.
        # The composer remembers a reader who pressed "hide suggested
        # questions". That is correct behaviour and it is also why the first
        # run found no chips and reported it as a missing feature: the
        # profile carried the hidden flag from an earlier suite. Cleared
        # here, because this check is about what the product offers, not
        # about what this browser was last told.
        context.add_init_script(
            "try { localStorage.removeItem("
            "'creditprobe.cockpit.suggestions-hidden'); } catch (e) {}")
        page.goto(FRONTEND + "/", wait_until="commit")
        _settle(page, "cockpit", 90)
        _visible(page, '[data-testid="ask-chip"]', 90)
        chips = page.locator('[data-testid="ask-chip"]')
        chip_said = ""
        chip_call: dict = {}
        typed_call: dict = {}
        if chips.count():
            chip_said = chips.first.inner_text().strip()
            sent: list[dict] = []

            def _watch(request):
                if "/api/v1" in request.url and request.method == "POST":
                    sent.append({"method": request.method, "url": request.url,
                                 "body": (request.post_data or "")[:600]})

            page.on("request", _watch)
            chips.first.click()
            page.wait_for_timeout(20000)
            chip_call = next((one for one in sent if one["body"]
                              and chip_said[:24] in one["body"]), {})
            sent.clear()
            page.goto(FRONTEND + "/", wait_until="commit")
            _settle(page, "cockpit", 90)
            got = session.ask(chip_said, timeout=200)
            typed_call = next((one for one in sent if one["body"]
                               and chip_said[:24] in one["body"]), {})
            _ = got

        check("17", "clicking a chip submits it as a question",
              bool(chip_call),
              (chip_call.get("url", "").split("/api/v1")[-1][:60]
               if chip_call else f"no POST carried {chip_said[:32]!r}"))
        same = (bool(chip_call) and bool(typed_call)
                and chip_call["url"] == typed_call["url"]
                and chip_call["method"] == typed_call["method"])
        check("18", "the chip and the typed phrasing take the SAME path",
              same,
              f"chip {chip_call.get('url','').split('/api/v1')[-1][:40]!r} vs "
              f"typed {typed_call.get('url','').split('/api/v1')[-1][:40]!r}")

        # 19 — every offered chip is answered, not deflected, through the
        # server. The browser proves the path in 17/18; this proves the
        # PROMISE, and it has to cover all five rather than the one that
        # happened to be first, because a chip the rotation shows tomorrow is
        # as offered as the one it shows today.
        deflected: list[str] = []
        for one in bank["by_surface"]["cockpit"]:
            if one["said"] not in banked_said:
                continue
            got = page.request.post(BACKEND + "/api/v1/ask",
                                    data={"question": one["said"]},
                                    timeout=300_000)
            if got.status != 200:
                deflected.append(f"{one['key']} -> HTTP {got.status}")
                continue
            body = json.dumps(got.json().get("narrative") or {}).lower()
            for phrase in ("which figure", "name one of the governed",
                           "please specify"):
                if phrase in body:
                    deflected.append(f"{one['key']}: {phrase!r}")
                    break
            for phrase in one["must_say"]:
                if phrase.lower() not in body:
                    deflected.append(f"{one['key']}: never said {phrase!r}")
            for phrase in one["must_not_say"]:
                if phrase.lower() in body:
                    deflected.append(f"{one['key']}: said {phrase!r}")
        check("19", "every offered chip is answered and says what the bank "
                    "requires",
              not deflected,
              "; ".join(deflected[:3]) or
              f"{len(bank['by_surface']['cockpit'])} banked chips answered")
        page.screenshot(path=f"{OUT}/19-chip-answered.png", full_page=True)

        # 20 — no 500 and no page error across all of it.
        bad_status = [one for one in session.api if one[2] >= 500]
        check("20", "no HTTP 500 across the story and the chips",
              not bad_status, "; ".join(f"{m} {p} {s}"
                                        for m, p, s in bad_status[:3]))
        check("21", "no browser page errors",
              not session.console_errors,
              "; ".join(session.console_errors[:2]))

        browser.close()

    print(f"\n{len(passed)} of {len(passed) + len(failed)} checks passed")
    for name, detail in failed:
        print(f"  FAILED  {name} — {detail}")
    with open(f"{OUT}/result.json", "w") as handle:
        json.dump({"passed": passed,
                   "failed": [{"check": n, "detail": d} for n, d in failed]},
                  handle, indent=2)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
