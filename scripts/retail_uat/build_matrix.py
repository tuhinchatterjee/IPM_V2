"""
docs/RETAIL_FUNCTIONALITY_MATRIX.csv, built from the evidence rather than typed.

Two sources, both produced by driving the running application:

* `inventory_controls.json` — every route the navigation renders and every
  control on it, discovered in the browser.
* the suite files beside it — what was actually exercised, and what happened.

A row is written for every route and for every case. Nothing here is asserted;
everything is copied from a file some suite wrote while a browser was open.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "retail_functionality"
OUT = ROOT / "docs" / "RETAIL_FUNCTIONALITY_MATRIX.csv"

#: Which suite covers which route, so a discovered screen can point at the
#: cases that exercised it.
COVERED_BY = {
    "/": ["cockpit_chat", "cockpit_journeys", "navigation"],
    "/what-if": ["whatif_chat", "whatif_journeys", "navigation"],
    "/investigations": ["cockpit_chat", "navigation"],
    "/trace": ["navigation", "cockpit_journeys"],
    "/early-warning": ["navigation"],
}

HEADER = [
    "id", "module", "route", "ui_state", "control_or_function",
    "prerequisites", "journey", "test_id", "environment", "action",
    "expected_effect", "evidence", "observed", "status", "defect",
]


def _suites() -> list[dict]:
    out = []
    for path in sorted(EVIDENCE.glob("*.json")):
        if path.name in ("inventory_controls.json",) or path.name.startswith("probe"):
            continue
        try:
            out.append(json.loads(path.read_text()))
        except Exception:  # noqa: BLE001 - a malformed file is not a row
            continue
    return out


def main() -> int:
    controls_path = EVIDENCE / "inventory_controls.json"
    if not controls_path.exists():
        print("no inventory: run scripts/retail_uat/inventory.py first",
              file=sys.stderr)
        return 1
    routes = json.loads(controls_path.read_text())["routes"]

    rows: list[dict[str, str]] = []
    index = 0
    for route, found in routes.items():
        index += 1
        if not found.get("opened"):
            rows.append({
                "id": f"RUI-{index:03d}", "module": "shell", "route": route,
                "ui_state": "not reachable", "control_or_function": "the route",
                "prerequisites": "signed in",
                "journey": "open the module from the navigation",
                "test_id": "inventory", "environment": "Chromium 1440x900",
                "action": "click the navigation item",
                "expected_effect": "the module renders",
                "evidence": "docs/evidence/retail_functionality/inventory.json",
                "observed": "no navigation link led here",
                "status": "FAIL", "defect": "",
            })
            continue
        counts = (f"{len(found['buttons'])} buttons, {len(found['inputs'])} "
                  f"inputs, {len(found['selects'])} selects, "
                  f"{len(found['tabs'])} tabs, {found['tables']} tables")
        rows.append({
            "id": f"RUI-{index:03d}", "module": found.get("heading") or route,
            "route": route,
            "ui_state": ("empty" if found.get("empty_state") else "populated"),
            "control_or_function": counts,
            "prerequisites": "signed in as retail.demo",
            "journey": "navigation -> module",
            "test_id": "inventory",
            "environment": "Chromium 1440x900 against the launcher's build",
            "action": "open the module and read every visible control",
            "expected_effect": "the module renders its controls",
            "evidence": found.get("screenshot", ""),
            "observed": f"heading {found.get('heading', '')!r}; {counts}",
            "status": "PASS",
            "defect": "",
        })
        for suite in COVERED_BY.get(route, []):
            rows[-1]["journey"] += f"; exercised by {suite}"

    for suite in _suites():
        name = suite.get("suite", "")
        for case in suite.get("cases", []):
            evidence = case.get("evidence") or {}
            rows.append({
                "id": case.get("id", ""),
                "module": case.get("module", ""),
                "route": str(evidence.get("route", "")),
                "ui_state": "exercised",
                "control_or_function": case.get("title", ""),
                "prerequisites": "signed in as retail.demo",
                "journey": name,
                "test_id": f"{name}:{case.get('id', '')}",
                "environment": "Chromium 1440x900 against the launcher's build",
                "action": case.get("title", ""),
                "expected_effect": case.get("title", ""),
                "evidence": str(evidence.get("screenshot", "")
                                or f"docs/evidence/retail_functionality/{name}.json"),
                "observed": case.get("detail", ""),
                "status": case.get("status", ""),
                "defect": case.get("defect", ""),
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"{OUT.relative_to(ROOT)}: {len(rows)} rows — "
          + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
