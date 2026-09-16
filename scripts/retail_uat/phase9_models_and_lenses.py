"""§10.2's model page and §20's lenses, opened rather than asserted.

Two things this refuses to accept.

That a lens EXISTS. §20 asks for eight dashboards including one per product,
and a row in a table proves none of it: the question is whether opening one
renders its tiles from the book, says which month it is reading, and applies
a filter to the KPI, the chart, the table and the interpretation together
rather than to whichever of them happens to be wired up.

That the challenger model page RENDERS. §10.2 asks for six tabs, a persisted
artifact and save/load parity. A page with six tab labels and nothing behind
four of them satisfies the word and not the sentence, so each tab is opened
and its content is read.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import (  # noqa: E402
    BACKEND,
    FRONTEND,
    Session,
    chromium_path,
)

OUT = "docs/evidence/phase9_models_and_lenses"
os.makedirs(OUT, exist_ok=True)

results: list[tuple[str, str, bool, str]] = []


def check(number: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append((number, name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {number} {name}"
          + (f" — {detail}" if detail else ""), flush=True)
    return ok


def _visible(page, selector: str, seconds: int = 120) -> bool:
    try:
        page.locator(selector).first.wait_for(state="visible",
                                              timeout=seconds * 1000)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> int:  # noqa: C901
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        session = Session(page, context)
        if not session.sign_in():
            print("could not sign in")
            return 1

        def api(path: str) -> dict:
            got = page.request.get(BACKEND + "/api/v1" + path, timeout=300_000)
            if got.status != 200:
                raise RuntimeError(f"{path} -> {got.status}")
            return got.json()

        # ------------------------------------------------ §10.2 model page
        page.goto(FRONTEND + "/what-if/models/ml", wait_until="commit")
        opened = _visible(page, '[data-testid="challenger-page"]', 180)
        check("10-01", "the XGBoost page opens in a retail installation",
              opened, "" if opened else "no challenger page rendered")
        page.screenshot(path=f"{OUT}/10-01-challenger.png", full_page=True)

        state = ""
        if page.locator('[data-testid="challenger-artifact-state"]').count():
            state = page.locator(
                '[data-testid="challenger-artifact-state"]').inner_text()
        check("10-02", "it says an artifact is stored",
              "stored" in state.lower() and "no artifact" not in state.lower(),
              state.strip())

        wanted = ["Model card", "Features", "Performance", "Artifact",
                  "Worked example", "Rebuild"]
        body = page.inner_text("body")
        missing = [one for one in wanted if one not in body]
        check("10-03", "all six tabs §10.2 names are present",
              not missing, ", ".join(missing) or ", ".join(wanted))

        # Each tab OPENED, and something read out of it.
        empty: list[str] = []
        for label, marker in (
                ("Features", '[data-testid="challenger-features"]'),
                ("Performance", "WAPE (held back)"),
                ("Artifact", '[data-testid="challenger-parity"]'),
                ("Worked example", '[data-testid="challenger-example"]')):
            # The tab, by its role. `get_by_text` matched the first node
            # carrying the word anywhere on the page — on the Performance
            # tab that was the prose in the limitation banner, so the click
            # landed on a paragraph and the tab never changed.
            page.locator(f'[role="tab"]:text-is("{label}")').first.click()
            page.wait_for_timeout(3000)
            if marker.startswith("["):
                if not _visible(page, marker, 180):
                    empty.append(label)
            # Case-insensitively: these labels are CSS-uppercased, so
            # `inner_text` returns "WAPE (HELD BACK)" and a literal compare
            # reported an empty tab on a page that had rendered the figure.
            elif marker.lower() not in page.inner_text("body").lower():
                empty.append(label)
        check("10-04", "every tab has content behind it, not just a label",
              not empty, ", ".join(empty) or "four data tabs read")
        page.screenshot(path=f"{OUT}/10-04-tabs.png", full_page=True)

        parity = api("/retail/whatif/models/challenger/parity")
        check("10-05", "the stored artifact scores as the fitted model did",
              parity["identical"], parity["says"])

        card = api("/retail/whatif/models/challenger")
        held = card.get("card") or {}
        check("10-06", "the artifact names the book it was fitted from",
              len(held.get("source_hash", "")) >= 16 and not card["stale"],
              f"{held.get('source_hash','')[:16]} · "
              f"{'current' if not card['stale'] else 'STALE'}")

        worked = api("/retail/whatif/models/challenger/example?rows=5")
        check("10-07", "the worked example scores real facilities from the "
                       "book, against their recorded ECL",
              len(worked["rows"]) == 5
              and all(one["facility_id"] and one["recorded_ecl_sar"] is not None
                      for one in worked["rows"]),
              f"{len(worked['rows'])} facilities at {worked['month']}")

        # ------------------------------------------------ §20 lenses
        lenses = api("/lenses")
        rows = lenses if isinstance(lenses, list) else (
            lenses.get("lenses") or lenses.get("items") or [])
        check("20-01", "at least eight lenses are published",
              len(rows) >= 8, f"{len(rows)} lenses")

        products = ("credit card", "personal", "auto", "home")
        titles = " | ".join(str(one.get("name") or one.get("title") or "")
                            for one in rows).lower()
        absent = [one for one in products if one not in titles]
        check("20-02", "there is a dashboard for each of the four products",
              not absent, ", ".join(absent) or "all four present")

        # 20-03 / 20-04 — one RENDERS, through the render endpoint, with the
        # month and the freshness it was computed against.
        seeded = [one for one in rows
                  if str(one.get("slug") or "").startswith("retail-")]
        target = seeded[0] if seeded else (rows[0] if rows else {})
        rendered: dict = {}
        if target:
            rendered = api(f"/lenses/{target['id']}/render")
        panels = rendered.get("panels") or rendered.get("tiles") or []
        # A panel's figure is in its `result`, not on the panel. The first
        # version of this check looked on the panel, found nothing, and
        # reported eighteen correctly-rendered tiles as empty.
        def _carries(one: dict) -> bool:
            body = one.get("result") or {}
            return bool(one.get("status") == "succeeded" and (
                body.get("value") is not None or body.get("rows")
                or body.get("series") or body.get("table")))

        carrying = [one for one in panels if _carries(one)]
        check("20-03", "every tile on a seeded lens renders from the book",
              bool(panels) and len(carrying) == len(panels),
              f"{target.get('slug','?')} — {len(carrying)} of {len(panels)} "
              f"tiles carry a figure; "
              f"{rendered.get('note') or 'no failures reported'}")

        # The ENVELOPE, not the tiles: the screen carries one badge for the
        # lens, so a null period there leaves it with nothing to show while
        # every tile underneath knows exactly which month it read.
        check("20-04", "the render envelope says which month and which book "
                       "it read",
              bool(rendered.get("month")) and bool(rendered.get("source_hash")),
              f"month {rendered.get('month') or '—'}, book "
              f"{str(rendered.get('source_hash') or '')[:12] or '—'}, "
              f"{'LIVE' if rendered.get('is_latest') else 'stale'}")

        # 20-05 — on screen, with the badge.
        if target:
            page.goto(FRONTEND + f"/lenses/{target['id']}", wait_until="commit")
            for _ in range(90):
                page.wait_for_timeout(1000)
                if len(page.inner_text("body")) > 600:
                    break
            page.wait_for_timeout(2500)
            _visible(page, '[data-testid="lens-freshness"]', 120)
            shown = page.inner_text("body")
            badge = (page.locator('[data-testid="lens-freshness"]').inner_text()
                     if page.locator('[data-testid="lens-freshness"]').count()
                     else "")
            check("20-05", "the lens screen shows the month, the book and "
                           "whether it is the latest",
                  str(rendered.get("month", "")) in shown and bool(badge)
                  and str(rendered.get("source_hash", ""))[:12] in shown,
                  f"month {rendered.get('month','?')}, badge "
                  f"{badge.strip().lower() or 'absent'}")
            page.screenshot(path=f"{OUT}/20-05-lens.png", full_page=True)
        else:
            check("20-05", "the lens screen shows the month it is reading",
                  False, "no lens to open")

        bad = [one for one in session.api if one[2] >= 500]
        check("99-01", "no HTTP 500 across the model page and the lenses",
              not bad, "; ".join(f"{m} {p} {s}" for m, p, s in bad[:3]))
        check("99-02", "no page errors", not session.console_errors,
              "; ".join(session.console_errors[:2]))

        browser.close()

    passed = [one for one in results if one[2]]
    print(f"\n{len(passed)} of {len(results)} checks passed")
    for number, name, ok, detail in results:
        if not ok:
            print(f"  FAILED  {number} {name} — {detail}")
    with open(f"{OUT}/result.json", "w") as handle:
        json.dump({"passed": [f"{n} {t}" for n, t, ok, _ in results if ok],
                   "failed": [{"check": f"{n} {t}", "detail": d}
                              for n, t, ok, d in results if not ok]},
                  handle, indent=2)
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
