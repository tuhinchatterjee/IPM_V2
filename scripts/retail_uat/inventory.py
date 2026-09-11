"""
Every reachable screen and every control on it, discovered in the browser.

Section 10.2 asks for a real inventory rather than a reading of the route
files, so this signs in, walks the navigation the product actually renders, and
records what is on each screen: buttons and what they say, links and where they
go, text boxes and what they are labelled, selects and their options, tabs, and
the state the screen was in when it was read.

It discovers. It does not assert: the exercising is in the suites beside it, and
docs/RETAIL_FUNCTIONALITY_MATRIX.csv is built from both.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    EVIDENCE,
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "inventory"

#: Read off the rendered sidebar rather than listed here, so a module added or
#: retired changes the inventory without anybody editing this file.
NAV_SELECTOR = 'nav a[href^="/"], aside a[href^="/"]'

_CONTROLS_JS = """() => {
  const text = (el) =>
    (el.getAttribute('aria-label')
     || el.getAttribute('title')
     || (el.innerText || '').trim()
     || el.getAttribute('placeholder')
     || '').replace(/\\s+/g, ' ').slice(0, 80);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
           && s.display !== 'none';
  };
  const pick = (sel) => [...document.querySelectorAll(sel)].filter(visible);
  const body = (document.body.innerText || '');
  return {
    heading: ((document.querySelector('h1') || {}).innerText || '').trim(),
    buttons: pick('button').map((b) => ({
      label: text(b), disabled: b.disabled,
      testid: b.getAttribute('data-testid') || '' })),
    links: pick('a[href]').map((a) => ({
      label: text(a), href: a.getAttribute('href') })),
    inputs: pick('input, textarea').map((i) => ({
      label: text(i), type: i.getAttribute('type') || i.tagName.toLowerCase(),
      testid: i.getAttribute('data-testid') || '', disabled: i.disabled })),
    selects: pick('select').map((s) => ({
      label: text(s), options: [...s.options].map((o) => o.value).slice(0, 30),
      testid: s.getAttribute('data-testid') || '' })),
    tabs: pick('[role="tab"], [data-tab]').map(text),
    details: pick('details').map((d) => text(d.querySelector('summary') || d)),
    tables: pick('table').length,
    empty_state: /Nothing yet|No .* yet|None yet|no results/i.test(body),
    refused: /could not|cannot|unavailable|not configured/i.test(body),
    characters: body.length,
  };
}"""


def suite(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/", settle=2500)
    routes: list[str] = []
    for link in page.query_selector_all(NAV_SELECTOR):
        href = link.get_attribute("href") or ""
        if href.startswith("/") and href not in routes:
            routes.append(href)

    found: dict[str, Any] = {}
    for index, route in enumerate(routes, start=1):
        opened = s.go(route, settle=3000)
        if not opened:
            found[route] = {"opened": False}
            rec.add(Case(id=f"RUI-{index:03d}", module=MODULE,
                         title=f"{route} opens from the navigation",
                         status=FAIL,
                         detail="no navigation link led to this route"))
            continue
        page.wait_for_timeout(700)
        record: dict[str, Any] = page.evaluate(_CONTROLS_JS)
        record["opened"] = True
        record["url"] = page.url
        record["console_errors"] = list(s.console_errors[-3:])
        record["screenshot"] = s.shot(f"route{route.replace('/', '-') or '-home'}")
        found[route] = record
        rec.add(Case(
            id=f"RUI-{index:03d}", module=MODULE,
            title=f"{route} renders with its controls",
            status=PASS if record["characters"] > 400 else FAIL,
            detail=(f"{len(record['buttons'])} buttons, "
                    f"{len(record['links'])} links, "
                    f"{len(record['inputs'])} inputs, "
                    f"{len(record['selects'])} selects, "
                    f"{len(record['tabs'])} tabs, "
                    f"{record['tables']} tables"
                    + (" — the screen reports something unavailable"
                       if record["refused"] else "")),
            evidence={"route": route, "heading": record["heading"],
                      "screenshot": record["screenshot"]}))

    # Not "inventory.json": the recorder writes one file per SUITE, and this
    # suite is called inventory — the crawl overwrote its own results.
    path = EVIDENCE / "inventory_controls.json"
    path.write_text(json.dumps({"routes": found}, indent=2, default=str))
    print(f"  inventory {path.name}: {len(found)} routes")


if __name__ == "__main__":
    raise SystemExit(run_suite("inventory", suite))
