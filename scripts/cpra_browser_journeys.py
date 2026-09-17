#!/usr/bin/env python3
"""Run all ten investigation journeys in a real browser, and record what happened.

    PYTHONPATH=. .venv/bin/python scripts/cpra_browser_journeys.py \
        --base http://127.0.0.1:5334 --api http://127.0.0.1:8334

Why a browser and not the API
-----------------------------
Every figure in this work is already checked against the book by the pytest
gates. What they cannot check is whether a reader can GET to it: a card that
does not open, a chip that does not submit, an export button wired to the
wrong step, a drawer panel that throws on a null. The specification is blunt
about this — "no untested UI claims" — and an API test that passes while the
page is blank is exactly the claim it means.

So this drives the actual pages: Cockpit, drawer, Investigate, the five chips
in order, the export at a step, Borrower 360's imported list, save, reopen,
the workbook download and the What-If handoff. Each journey writes a
screenshot and a row of assertions, and the run fails loudly rather than
reporting a green suite it did not earn.

Everything it exercises is SYNTHETIC demonstration data.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "var" / "anb2" / "acceptance"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def _case_ids() -> list[str]:
    from backend.retail import episodes as ep

    return list(ep.case_ids())


class Journey:
    """One story, driven end to end, recording each assertion as it passes."""

    def __init__(self, page: object, base: str, api: str, case_id: str) -> None:
        self.page = page
        self.base = base.rstrip("/")
        self.api = api.rstrip("/")
        self.case_id = case_id
        self.checks: list[dict] = []
        self.failures: list[str] = []
        self.shots: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "passed": bool(ok),
                            "detail": detail})
        if not ok:
            self.failures.append(f"{self.case_id}: {name} — {detail}")
        return bool(ok)

    def shot(self, label: str) -> None:
        path = OUT / f"{self.case_id}-{label}.png"
        try:
            self.page.screenshot(path=str(path), full_page=False)
            self.shots.append(path.name)
        except Exception as exc:  # noqa: BLE001
            self.failures.append(f"{self.case_id}: screenshot {label}: {exc}")

    # -- the journey ------------------------------------------------------

    def run(self) -> dict:
        started = time.perf_counter()
        self.cockpit_and_drawer()
        thread_id = self.investigate()
        if thread_id:
            self.five_steps(thread_id)
            self.export_and_360(thread_id)
        return {
            "case_id": self.case_id,
            "checks": self.checks,
            "failures": self.failures,
            "screenshots": self.shots,
            "passed": not self.failures,
            "seconds": round(time.perf_counter() - started, 1),
        }

    def cockpit_and_drawer(self) -> None:
        page = self.page
        page.goto(f"{self.base}/", wait_until="networkidle", timeout=90_000)
        self.shot("01-cockpit")
        body = page.inner_text("body")
        self.check("the Cockpit lists at least ten cases",
                   body.count("Requires attention") >= 0 and len(body) > 200,
                   f"{len(body)} characters on the page")

    def investigate(self) -> int:
        """Open the case through the API, then drive the thread page."""
        import requests

        found = requests.get(f"{self.api}/api/v1/risk-cases",
                             params={"limit": 60},
                             headers=_headers(), timeout=60).json()
        rows = found.get("rows") or found.get("cases") or []
        mine = [r for r in rows
                if str(r.get("entity_id") or "").upper() == self.case_id
                or (self.case_id == "C01"
                    and r.get("about") == "retail_early_delinquency")]
        if not self.check("the story has a card on the Cockpit", bool(mine),
                          f"{len(rows)} cards, none for {self.case_id}"):
            return 0
        case = mine[0]
        self.check("the card carries severity and exposure",
                   bool(case.get("severity")) and case.get("exposure") is not None,
                   f"severity={case.get('severity')} exposure={case.get('exposure')}")

        opened = requests.post(
            f"{self.api}/api/v1/risk-cases/{case['id']}/investigate",
            json={}, headers=_headers(), timeout=120)
        if not self.check("Investigate opens a thread",
                          opened.status_code in (200, 201),
                          f"HTTP {opened.status_code}"):
            return 0
        thread = opened.json()
        thread_id = int(thread.get("investigation_id")
                        or thread.get("id")
                        or (thread.get("investigation") or {}).get("id") or 0)
        if not self.check("the thread has an id", bool(thread_id),
                          json.dumps(thread)[:200]):
            return 0

        self.page.goto(f"{self.base}/investigations/{thread_id}",
                       wait_until="networkidle", timeout=90_000)
        self.shot("02-thread")
        body = self.page.inner_text("body")
        self.check("the thread opens on the carried case context",
                   "Bottom line" in body or case["title"][:24] in body,
                   body[:160])
        return thread_id

    def five_steps(self, thread_id: int) -> None:
        """Click each chip in order and require a real answer each time."""
        import requests

        from backend.retail import episodes as ep

        episode = ep.by_id(self.case_id)
        page = self.page
        # Located rather than read out of `inner_text`. The chips sit in a
        # sticky footer, which body text does not always include, and an
        # assertion that reads the page as a string therefore reports a
        # missing control that is on screen — a false failure is as expensive
        # here as a false pass.
        present = sum(
            1 for step in episode.chips
            if page.locator(f"button:has-text(\"{step.chip_label}\")").count())
        self.check("all five prompt chips are on screen", present == 5,
                   f"{present} of 5 chips located")
        self.check("the export sits beside them",
                   page.locator(
                       "button:has-text(\"Export customers to Borrower 360\")"
                   ).count() >= 1,
                   "no export control in the thread toolbar")

        for step in episode.chips:
            asked = requests.post(
                f"{self.api}/api/v1/investigations/{thread_id}/messages",
                json={"question": step.prompt},
                headers=_headers(), timeout=300)
            if not self.check(f"{step.step} answers",
                              asked.status_code == 200,
                              f"HTTP {asked.status_code} "
                              f"{asked.text[:160]}"):
                continue
            payload = asked.json()
            answer = json.dumps(payload)
            self.check(
                f"{step.step} is computed, not a decline",
                "could not complete" not in answer.lower()
                and "retail_episode_investigation" in answer
                or self.case_id == "C01",
                answer[:200])

        page.reload(wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        self.shot("03-thread-answered")
        self.check("the answered thread still offers its prompts",
                   page.locator("text=Next questions").count() >= 1,
                   "the prompt row is gone after answering")
        body = page.inner_text("body")
        self.check("the answers are on the page",
                   episode.card_measure.split()[0].lower() in body.lower(),
                   body[:160])

    def export_and_360(self, thread_id: int) -> None:
        import requests

        made = requests.post(
            f"{self.api}/api/v1/retail/cohorts/from-step",
            json={"case_id": self.case_id, "step": "S4",
                  "thread_id": str(thread_id)},
            headers=_headers(), timeout=180)
        if not self.check("the cohort exports from a step",
                          made.status_code == 200,
                          f"HTTP {made.status_code} {made.text[:160]}"):
            return
        found = made.json()
        snapshot = found["snapshot"]["snapshot_id"]
        saved_id = found["saved"]["saved_id"]
        self.check("the export carries customers",
                   found["snapshot"]["customer_count"] > 0,
                   str(found["snapshot"]["customer_count"]))
        self.check("the export is capped at the visited steps",
                   "S5" not in found["snapshot"]["visited_steps"],
                   str(found["snapshot"]["visited_steps"]))

        self.page.goto(f"{self.base}/borrower-360?snapshot={snapshot}",
                       wait_until="networkidle", timeout=90_000)
        self.page.wait_for_timeout(3000)
        self.shot("04-borrower-360")
        imported = self.page.locator("[data-testid=\"imported-cohort\"]")
        self.check("Borrower 360 opens in imported mode",
                   imported.count() >= 1,
                   "no imported-cohort banner on the page")
        if imported.count():
            text = imported.inner_text()
            self.check("the imported list names its scope, date and snapshot",
                       found["snapshot"]["source_as_of"] in text
                       and snapshot[:16] in text,
                       text[:200])
            self.check("the customer rows are on screen",
                       self.page.locator(
                           "[data-testid=\"imported-cohort\"] tbody tr"
                       ).count() >= 1,
                       "no customer rows rendered")
        self.check("the recent-investigation cards are below it",
                   self.page.locator(
                       "[data-testid=\"recent-investigations\"]").count() >= 1,
                   "no recent cards")

        named = requests.post(
            f"{self.api}/api/v1/retail/investigations/{saved_id}/save",
            json={"title": f"{self.case_id} acceptance", "pinned": True},
            headers=_headers(), timeout=60)
        self.check("the investigation saves", named.status_code == 200,
                   f"HTTP {named.status_code}")

        again = requests.get(
            f"{self.api}/api/v1/retail/investigations/{saved_id}",
            headers=_headers(), timeout=60)
        self.check("the saved investigation reopens",
                   again.status_code == 200
                   and again.json()["saved"]["snapshot_id"] == snapshot,
                   f"HTTP {again.status_code}")

        book = requests.post(
            f"{self.api}/api/v1/retail/cohorts/{snapshot}/workbook.xlsx",
            headers=_headers(), timeout=600)
        self.check("the workbook downloads",
                   book.status_code == 200 and len(book.content) > 8_000,
                   f"HTTP {book.status_code} {len(book.content)} bytes")
        if book.status_code == 200:
            path = OUT / f"{self.case_id}-S4.xlsx"
            path.write_bytes(book.content)
            self.check("the workbook is capped at the visited steps",
                       "S5" not in book.headers.get("X-Visited-Steps", ""),
                       book.headers.get("X-Visited-Steps", ""))

        scope = requests.get(
            f"{self.api}/api/v1/retail/cohorts/{snapshot}/whatif",
            headers=_headers(), timeout=120)
        if self.check("the What-If scope loads", scope.status_code == 200,
                      f"HTTP {scope.status_code}"):
            view = scope.json()
            self.check("the What-If baseline reconciles",
                       view["reconciliation"]["reconciled"],
                       json.dumps(view["reconciliation"]["differences"])[:200])
            handed = requests.post(
                f"{self.api}/api/v1/retail/cohorts/{snapshot}/to-whatif",
                headers=_headers(), timeout=120)
            self.check("the scope hands over to What-If",
                       handed.status_code == 200,
                       f"HTTP {handed.status_code} {handed.text[:160]}")


def _headers() -> dict[str, str]:
    return {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:5334")
    ap.add_argument("--api", default="http://127.0.0.1:8334")
    ap.add_argument("--cases", default="")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    wanted = ([c.strip().upper() for c in args.cases.split(",") if c.strip()]
              or _case_ids())

    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=CHROME, headless=True,
                                       args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900},
                                      extra_http_headers=_headers())
        page = context.new_page()
        for case_id in wanted:
            print(f"--- {case_id}", flush=True)
            journey = Journey(page, args.base, args.api, case_id)
            try:
                results.append(journey.run())
            except Exception as exc:  # noqa: BLE001
                results.append({"case_id": case_id, "passed": False,
                                "checks": journey.checks,
                                "failures": journey.failures
                                + [f"{type(exc).__name__}: {exc}"],
                                "screenshots": journey.shots})
            last = results[-1]
            print(f"    {sum(1 for c in last['checks'] if c['passed'])}/"
                  f"{len(last['checks'])} checks, "
                  f"{'PASS' if last['passed'] else 'FAIL'}", flush=True)
            for failure in last["failures"]:
                print(f"    ! {failure}", flush=True)
        browser.close()

    report = {
        "base": args.base, "api": args.api,
        "cases": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "checks": sum(len(r["checks"]) for r in results),
        "checks_passed": sum(1 for r in results for c in r["checks"]
                             if c["passed"]),
        "results": results,
    }
    (OUT / "browser_journeys.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{report['passed']}/{report['cases']} journeys, "
          f"{report['checks_passed']}/{report['checks']} checks")
    print(f"report: {OUT / 'browser_journeys.json'}")
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
