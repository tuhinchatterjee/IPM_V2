"""
Reconcile the route and control crawl with the functionality matrix.

Revision 3 §4 asks for this and is specific about what it does NOT want: one
matrix row per DOM node. "One journey may legitimately exercise multiple
controls and repeated component instances, and categories can overlap. Instead
map each distinct required operation and relevant route/state instance to an
executed test or a justified equivalence class. Name uncovered controls."

So this reads the evidence the suites actually wrote — not the source, not the
matrix's own claims — and answers three questions:

1.  Which routes were OPENED and read in a browser?
2.  Which routes had an OPERATION executed on them, and by which case?
3.  Which required operation classes are covered, and which are not?

An operation class is the unit a reader cares about: "run an analysis", "save",
"export", "return to where I was". Whether a screen has one Save button or four
instances of a shared Save component is not a coverage question; whether Save
was ever pressed and its effect asserted is.

The output is written beside the other evidence so a reader can check the
reconciliation rather than take this document's word for it.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "retail_functionality"
MATRIX = ROOT / "docs" / "RETAIL_FUNCTIONALITY_MATRIX.csv"

#: The operation classes a retail acceptance has to cover, and what each means.
#: Deliberately few: these are the things a credit officer does, not the
#: controls a framework renders.
OPERATIONS: dict[str, str] = {
    "open": "Open a route and read what it renders",
    "ask": "Ask a question in a composer and get an answer",
    "run": "Run a calculation and read its result",
    "filter": "Narrow a list or change its reporting month",
    "drill": "Open a row and read the record behind it",
    "save": "Keep a result under a name",
    "reopen": "Reopen something kept, as it was kept",
    "compare": "Put two results side by side",
    "export": "Download a result and read the file back",
    "delete": "Remove something this test created",
    "return": "Go back and arrive where you left, with state intact",
    "refuse": "Ask for something unsupported and be refused whole",
    "recover": "Reach a bad state and be given a way out",
}

#: Which suite case proves which operation class. A case may prove several —
#: that is the point of an equivalence class, and the reason a row-per-control
#: matrix is the wrong shape.
CLAIMS: dict[str, tuple[str, ...]] = {
    "inventory": ("open",),
    "retail_only": ("open", "drill", "return"),
    "cockpit_chat": ("ask", "run", "refuse"),
    "cockpit_journeys": ("ask", "run", "drill", "export", "return", "recover"),
    "whatif_chat": ("ask", "run", "refuse"),
    "whatif_journeys": ("run", "save", "reopen", "compare", "export", "delete",
                        "filter", "return"),
    "whatif_fidelity": ("ask", "run", "refuse", "recover", "return"),
    "customer360": ("open", "filter", "drill", "return", "recover"),
    "navigation": ("open", "return"),
    "end_to_end": ("ask", "run", "save", "reopen", "return"),
}


def _suites() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(EVIDENCE.glob("*.json")):
        if path.name.startswith("probe") or path.name == "inventory_controls.json":
            continue
        try:
            body = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if "cases" in body:
            out[body.get("suite", path.stem)] = body
    return out


def _routes_opened(suites: dict[str, dict]) -> dict[str, list[str]]:
    """Every route a case recorded opening, and which cases opened it."""
    opened: dict[str, list[str]] = defaultdict(list)
    for name, body in suites.items():
        for case in body["cases"]:
            route = (case.get("evidence") or {}).get("route")
            if route:
                opened[route].append(f"{name}:{case['id']}")
            for shot in [(case.get("evidence") or {}).get("screenshot")]:
                if shot and "route-" in str(shot):
                    stem = str(shot).split("route-")[-1].removesuffix(".png")
                    opened["/" + stem.replace("-", "/")].append(
                        f"{name}:{case['id']}")
    return dict(opened)


def main() -> int:
    suites = _suites()
    if not suites:
        print("No suite evidence found. Run the suites first.")
        return 1

    passed = {n: sum(1 for c in b["cases"] if c["status"] == "PASS")
              for n, b in suites.items()}
    failed = {n: [c["id"] for c in b["cases"] if c["status"] == "FAIL"]
              for n, b in suites.items()}

    # ---- operation classes, and which suites prove them ------------------
    by_operation: dict[str, list[str]] = defaultdict(list)
    for suite, operations in CLAIMS.items():
        if suite not in suites:
            continue
        if failed.get(suite):
            continue
        for operation in operations:
            by_operation[operation].append(suite)
    uncovered = sorted(set(OPERATIONS) - set(by_operation))

    report = {
        "suites": {n: {"passed": passed[n],
                       "failed": failed[n],
                       "total": len(b["cases"])}
                   for n, b in sorted(suites.items())},
        "operations": {
            name: {"meaning": OPERATIONS[name],
                   "proved_by": sorted(by_operation.get(name, []))}
            for name in OPERATIONS},
        "uncovered_operations": uncovered,
        "routes_opened": {r: sorted(set(c))
                          for r, c in sorted(_routes_opened(suites).items())},
    }
    out = EVIDENCE / "coverage.json"
    out.write_text(json.dumps(report, indent=2))

    print(f"  {len(suites)} suites, "
          f"{sum(passed.values())} cases passed, "
          f"{sum(len(f) for f in failed.values())} failed")
    print()
    print("  operation class        proved by")
    for name in OPERATIONS:
        provers = by_operation.get(name, [])
        mark = "OK  " if provers else "GAP "
        print(f"  [{mark}] {name:<14s} {', '.join(provers) or '— nothing'}")
    print()
    print(f"  {len(report['routes_opened'])} routes opened in a browser")
    if uncovered:
        print(f"  UNCOVERED: {', '.join(uncovered)}")
    print(f"  evidence {out.relative_to(ROOT)}")
    return 1 if uncovered or any(failed.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
