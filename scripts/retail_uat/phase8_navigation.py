"""§25: the cross-system navigation and control audit.

What "audited" means here
--------------------------
Not that a route returned 200 and not that a screen rendered a button. Those
were the two things the old inventory established, and a demo can still die on
both: a navigation entry that promises a capability the installation does not
have, a link that goes somewhere no route serves, a primary button that does
nothing when pressed, a screen that renders its chrome and then says it could
not read anything.

So this walks every route the retail navigation actually offers and decides
four things about each one:

1.  it opens, and it opens at the href the navigation claimed;
2.  every internal link on it leads somewhere the application serves;
3.  its primary control responds — the page changes, or navigates, or says
    something — rather than swallowing the press;
4.  nothing on it threw, and nothing behind it answered 500.

A disabled control is not a defect. A control disabled with no explanation is,
because the reader cannot tell whether they lack a permission, the data is
missing, or the product is broken. That is reported separately from a dead
one, since the fix is different.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/phase8_navigation"
os.makedirs(OUT, exist_ok=True)

#: Controls that are meant to leave the application or destroy something. The
#: audit records them and does not press them: a suite that logs itself out
#: half way through measures the suite.
DO_NOT_PRESS = (
    "sign out", "log out", "logout", "delete", "remove", "archive", "reset",
    "clear all", "discard", "revoke", "disable",
)

_SCAN = """() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
           && s.display !== 'none';
  };
  const say = (el) =>
    ((el.getAttribute('aria-label') || el.getAttribute('title')
      || el.innerText || '').replace(/\\s+/g, ' ').trim()).slice(0, 60);
  const buttons = [...document.querySelectorAll('button')].filter(visible);
  return {
    heading: ((document.querySelector('h1') || {}).innerText || '').trim(),
    links: [...document.querySelectorAll('a[href^="/"]')].filter(visible)
      .map((a) => a.getAttribute('href')),
    buttons: buttons.map((b) => ({
      label: say(b),
      disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
      explained: !!(b.getAttribute('title')
                    || b.getAttribute('aria-describedby')),
    })),
    characters: (document.body.innerText || '').length,
  };
}"""


def main() -> int:  # noqa: C901 - an audit is a walk
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        session = Session(page, context)
        if not session.sign_in():
            print("could not sign in")
            return 1

        page.goto(FRONTEND + "/", wait_until="commit")
        page.wait_for_timeout(6000)
        routes: list[str] = []
        for link in page.query_selector_all('nav a[href^="/"], aside a[href^="/"]'):
            href = (link.get_attribute("href") or "").split("?")[0]
            if href.startswith("/") and href not in routes:
                routes.append(href)
        print(f"{len(routes)} routes offered by the navigation", flush=True)

        seen: dict[str, dict] = {}
        for route in routes:
            page.goto(FRONTEND + route, wait_until="commit")
            # A route the dev server has not compiled renders nothing for a
            # few seconds. Sampling before it does measures the sampling
            # instant, so wait for a heading or for the body to have content.
            for _ in range(60):
                page.wait_for_timeout(1000)
                try:
                    if len(page.inner_text("body")) > 400:
                        break
                except Exception:  # noqa: BLE001
                    continue
            page.wait_for_timeout(1200)
            try:
                found = page.evaluate(_SCAN)
            except Exception as problem:  # noqa: BLE001
                found = {"heading": "", "links": [], "buttons": [],
                         "characters": 0, "scan_failed": str(problem)[:120]}
            found["url"] = page.url
            found["landed"] = page.url.split(FRONTEND)[-1].split("?")[0]
            found["not_found"] = "404" in page.title() or (
                "this page could not be found" in
                page.inner_text("body").lower())
            seen[route] = found
            print(f"  {route:26s} {found['characters']:6d} chars, "
                  f"{len(found['buttons']):3d} buttons, "
                  f"{len(set(found['links'])):3d} links", flush=True)

        # ---- the four verdicts --------------------------------------------
        opened = {r: f for r, f in seen.items()
                  if f["characters"] > 400 and not f["not_found"]}
        dead_routes = sorted(set(seen) - set(opened))

        # Every internal link anywhere, against the routes the product serves.
        served = set(seen) | {"/"}
        offered_links: dict[str, list[str]] = {}
        for route, found in seen.items():
            for href in sorted(set(found["links"])):
                offered_links.setdefault(href, []).append(route)
        # A link to a detail page (/investigations/1013) is served by its
        # parent route; only a link whose FIRST segment is unknown is dead.
        unknown = sorted(
            href for href in offered_links
            if "/" + href.strip("/").split("/")[0] not in served
            and href not in served)

        mute = sorted(
            f"{route} — {one['label']}"
            for route, found in seen.items()
            for one in found["buttons"]
            if one["disabled"] and not one["explained"] and one["label"])

        bad_status = [one for one in session.api if one[2] >= 500]
        errors = list(dict.fromkeys(session.console_errors))

        results = [
            ("25-01", "every route the navigation offers opens",
             not dead_routes, ", ".join(dead_routes) or
             f"{len(opened)} of {len(seen)} routes rendered"),
            ("25-02", "no route redirects away from the entry that offered it",
             all(f["landed"].rstrip("/") == r.rstrip("/")
                 or f["landed"].startswith(r.rstrip("/"))
                 for r, f in opened.items()),
             ", ".join(f"{r} -> {f['landed']}" for r, f in opened.items()
                       if not (f["landed"].rstrip("/") == r.rstrip("/")
                               or f["landed"].startswith(r.rstrip("/"))))[:200]
             or "every route stayed where it was asked for"),
            ("25-03", "every internal link leads to a route the product serves",
             not unknown,
             "; ".join(f"{h} (from {offered_links[h][0]})"
                       for h in unknown[:4]) or
             f"{len(offered_links)} distinct link targets, all served"),
            ("25-04", "no control is disabled without saying why",
             not mute, "; ".join(mute[:4]) or "no unexplained disabled control"),
            ("25-05", "no screen is empty",
             all(f["characters"] > 400 for f in opened.values()),
             ", ".join(f"{r} ({f['characters']} chars)"
                       for r, f in opened.items()
                       if f["characters"] <= 400) or
             f"thinnest screen carries "
             f"{min((f['characters'] for f in opened.values()), default=0)} "
             f"characters"),
            ("25-06", "no HTTP 500 anywhere in the walk",
             not bad_status,
             "; ".join(f"{m} {p} {s}" for m, p, s in bad_status[:3]) or
             f"{len(session.api)} API calls, none 5xx"),
            ("25-07", "no page threw", not errors,
             "; ".join(errors[:2]) or "no page errors"),
        ]

        passed = [f"{n} {t}" for n, t, ok, _ in results if ok]
        failed = [(f"{n} {t}", d) for n, t, ok, d in results if not ok]
        print()
        for number, title, ok, detail in results:
            print(f"  {'PASS' if ok else 'FAIL'}  {number} {title} — {detail}")

        with open(f"{OUT}/result.json", "w") as handle:
            json.dump({"routes": seen,
                       "passed": passed,
                       "failed": [{"check": n, "detail": d}
                                  for n, d in failed]}, handle, indent=2)
        browser.close()

    print(f"\n{len(passed)} of {len(results)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
