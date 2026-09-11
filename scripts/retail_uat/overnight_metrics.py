"""
Metrics, Lenses and Playbook, opened and read in a real browser.

RFD-37 was closed in code: 46 retail metrics, two lenses, three committee packs,
every tile computing. That proves the arithmetic. It does not prove that a Head
of Retail Risk who opens the Lenses screen sees a number — a tile can compute
and still render a dash, a lens can install and still not appear, and a pack can
hold thirty-four figures and show none of them.

So this opens the screens, reads what is rendered, and compares it against the
independent oracle rather than against the API that drew it.
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

MODULE = "metrics-lenses-playbook"

#: What an empty tile looks like on screen. A lens that renders these is the
#: defect RFD-37 was about, and it is invisible to any test that asks the API.
EMPTY_MARKS = ("—", "–", "N/A", "n/a", "Not available", "No value",
               "Unavailable", "--")

CORPORATE = ("wholesale book", "rating notch", "master scale", "sector stress",
             "largest obligor", "Corporate IFRS 9", "Corporate Credit",
             "XGBoost", "BBB", "EBITDA", "covenant")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def _numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in re.findall(r"-?[\d,]+\.?\d*", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def main_text(s: Session) -> str:
    """What is rendered in the content region, without the navigation shell.

    `s.text()` returns the whole body, and on every screen that is mostly the
    sidebar: thirty navigation labels and a version number. A check for "is
    there a number on this page" run against the body passes on the empty page
    because the sidebar has numbers in it.
    """
    el = s.page.query_selector("main") or s.page.query_selector('[role="main"]')
    return el.inner_text() if el else ""


def _settle(s: Session, wait: int = 200) -> str:
    """Wait for the content region to have SOMETHING in it, then for it to stop.

    The bug this replaces: the loop exited when "Loading" was absent from the
    text — and on a page that has not rendered yet the text is empty, so
    "Loading" is absent, so it exited instantly and read a blank screen. Every
    lens in the first run was measured before it had drawn anything.
    """
    deadline = time.time() + wait
    last = ""
    stable = 0
    while time.time() < deadline:
        s.page.wait_for_timeout(1500)
        now = main_text(s)
        if now.strip() and "Loading" not in now and "Calculating" not in now:
            stable = stable + 1 if now == last else 0
            if stable >= 1:
                return now
        last = now
    return main_text(s)


def _open_and_settle(s: Session, route: str, wait: int = 200,
                     until: str = "") -> str:
    if not s.go(route, settle=2500):
        page = s.page
        origin = page.url.split("/")[0] + "//" + page.url.split("/")[2]
        page.goto(f"{origin}{route}", wait_until="networkidle", timeout=90_000)
    if until:
        deadline = time.time() + wait
        while time.time() < deadline:
            if s.page.query_selector(until):
                break
            s.page.wait_for_timeout(1500)
    return _settle(s, wait)


def suite(s: Session, rec: Recorder) -> None:
    page = s.page

    # ------------------------------------------------------------- MET-01
    body = _open_and_settle(s, "/lenses")
    cards = page.query_selector_all('a[href^="/lenses/"]')
    hrefs = sorted({c.get_attribute("href") for c in cards if c.get_attribute("href")})
    _case(rec, "MET-01", "The Lenses index offers the retail lenses and nothing "
          "corporate",
          len(hrefs) >= 2 and not [w for w in CORPORATE if w.lower() in body.lower()],
          f"lenses offered: {hrefs}; corporate wording: "
          f"{[w for w in CORPORATE if w.lower() in body.lower()]}",
          screenshot=s.shot("met-01-lenses-index"))

    # ------------------------------------------------- MET-02..03 each lens
    lens_results: list[dict[str, Any]] = []
    for index, href in enumerate(hrefs[:2], start=2):
        link = page.query_selector(f'a[href="{href}"]')
        if link is None:
            _open_and_settle(s, "/lenses")
            link = page.query_selector(f'a[href="{href}"]')
        if link is None:
            _case(rec, f"MET-{index:02d}", f"{href} opens and shows values",
                  False, "the card vanished between listing and clicking")
            continue
        link.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        text = _settle(s)

        # Every tile, read off the rendered card rather than from the payload.
        tiles = page.query_selector_all(
            '[data-metric-id], [data-testid^="lens-tile"], article, .lens-tile')
        values = [t.inner_text() for t in tiles] if tiles else []
        dashes = [v for v in values
                  if any(v.strip() == mark or f"\n{mark}" in v
                         for mark in EMPTY_MARKS)]
        corporate = [w for w in CORPORATE if w.lower() in text.lower()]
        numbers = _numbers(text)
        ok = bool(numbers) and not dashes and not corporate
        lens_results.append({"href": href, "tiles": len(values),
                             "empty": len(dashes), "numbers": len(numbers)})
        _case(rec, f"MET-{index:02d}",
              f"{href} renders its tiles with real values, none empty",
              ok,
              f"{len(values)} tile elements; {len(dashes)} showing an empty "
              f"mark; {len(numbers)} numbers on the page; corporate wording "
              f"{corporate}",
              href=href, screenshot=s.shot(f"met-{index:02d}-lens"))
        _open_and_settle(s, "/lenses")

    # ------------------------------------------- MET-04 a figure reconciles
    book = ORACLE["book"]
    # The index links by id, not by slug. Looking for the slug found nothing
    # and measured an empty page.
    _open_and_settle(s, "/lenses")
    link = None
    for href in hrefs:
        candidate = page.query_selector(f'a[href="{href}"]')
        if candidate and "Retail Credit Risk" in (candidate.inner_text() or ""):
            link = candidate
            break
    link = link or (page.query_selector(f'a[href="{hrefs[0]}"]') if hrefs else None)
    on_screen: list[float] = []
    if link:
        link.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        on_screen = _numbers(_settle(s))
    # The book's own figures, in the units a screen shows them in.
    wanted = {
        "facilities": book["facilities"],
        "customers": book["customers"],
    }
    found = {name: any(abs(v - target) < 1 for v in on_screen)
             for name, target in wanted.items()}
    _case(rec, "MET-04",
          "A figure on the Retail Credit Risk lens reconciles with the "
          "independent oracle",
          all(found.values()),
          f"looking for {wanted} among the rendered numbers; found {found}",
          screenshot=s.shot("met-04-reconcile"))

    # ------------------------------------------------------------- MET-05
    _open_and_settle(s, "/metrics")
    # The catalogue opens on a search prompt; "Show the whole catalogue" is the
    # control a reader uses to browse it.
    for button in page.query_selector_all("button"):
        if "whole catalogue" in (button.inner_text() or "").lower():
            button.click()
            break
    body = _settle(s, 120)
    corporate = [w for w in CORPORATE if w.lower() in body.lower()]
    listed = [name for name in ("Retail Gross Carrying Amount",
                                "Retail Expected Credit Loss",
                                "Application Scorecard Gini")
              if name in body]
    _case(rec, "MET-05",
          "The Metric Catalogue lists the retail metrics and nothing corporate",
          len(listed) >= 2 and not corporate,
          f"found on screen: {listed}; corporate wording: {corporate}",
          screenshot=s.shot("met-05-metrics"))

    # ------------------------------------------------------------- MET-06
    body = _open_and_settle(s, "/playbook")
    committees = [w for w in ("Retail Credit Risk Committee",
                              "Retail IFRS 9 Committee",
                              "Retail Model Risk Committee") if w in body]
    corporate = [w for w in CORPORATE if w.lower() in body.lower()]
    _case(rec, "MET-06",
          "The Playbook offers three retail committees and nothing corporate",
          len(committees) == 3 and not corporate,
          f"committees on screen: {committees}; corporate wording: {corporate}",
          screenshot=s.shot("met-06-playbook"))

    # ------------------------------------------------------------- MET-07
    # Open a pack and read its figures.
    opened = False
    # The link to a PACK, not the "Committees" navigation link beside it. The
    # first run clicked `/playbook/committees` and measured the committee
    # admin screen, which is a different page with no Back control.
    for selector in ('table a[href^="/playbook/"]',
                     'a[href*="-committee-20"]',
                     'tbody a'):
        card = page.query_selector(selector)
        if card is not None and "new" not in (card.get_attribute("href") or ""):
            card.click()
            page.wait_for_load_state("networkidle", timeout=90_000)
            opened = True
            break
    text = _settle(s) if opened else ""
    numbers = _numbers(text)
    corporate = [w for w in CORPORATE if w.lower() in text.lower()]
    _case(rec, "MET-07",
          "A committee pack opens and shows figures rather than placeholders",
          opened and len(numbers) >= 5 and not corporate,
          f"opened={opened}; {len(numbers)} numbers rendered; corporate "
          f"wording {corporate}",
          screenshot=s.shot("met-07-pack"))

    # ------------------------------------------------------------- MET-08
    back = page.query_selector('[data-testid="back-link"]')
    returned = False
    if back:
        back.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        returned = "/playbook" in page.url
    _case(rec, "MET-08", "Back from a pack returns to the Playbook",
          bool(back) and returned,
          f"back control present={bool(back)}; returned to {page.url}",
          screenshot=s.shot("met-08-back"))


    # ------------------------------------------------------------- MET-09
    # A tile asking for a trend must draw one. Every tile became a metric
    # panel whatever its visual, so a `line` rendered as a second copy of the
    # same KPI: the Retail Credit Risk lens showed "Retail Expected Credit
    # Loss 15,952,109" twice, with no chart between them.
    _open_and_settle(s, "/lenses")
    link = page.query_selector(f'a[href="{hrefs[0]}"]') if hrefs else None
    charts = 0
    svgs = 0
    if link:
        link.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        _settle(s)
        charts = len(page.query_selector_all(
            '[data-testid^="chart"], .recharts-wrapper, svg.recharts-surface'))
        svgs = len(page.query_selector_all("main svg"))
    _case(rec, "MET-09",
          "A lens tile declared as a trend draws a chart rather than repeating "
          "the KPI beside it",
          charts > 0,
          f"{charts} chart elements and {svgs} svg elements in the content "
          f"region",
          screenshot=s.shot("met-09-charts"))

    # ------------------------------------------------------------- MET-10
    # Units. "ECL Coverage 0.77" is unreadable: 0.77% or 77%?
    text = main_text(s)
    percents = text.count("%")
    _case(rec, "MET-10",
          "Percentage tiles carry their unit on screen",
          percents >= 5,
          f"{percents} percent signs in the content region; the lens carries "
          f"eleven percentage metrics",
          screenshot=s.shot("met-10-units"))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_metrics", suite))
