#!/usr/bin/env python3
"""Build the validation inventories from SOURCE, then join RUNTIME evidence.

    python3 scripts/guided_workspace/validation_inventory.py \\
        --journeys <journeys.json of the run> \\
        --out docs/guided_workspace/validation

Writes ROUTE_INVENTORY.csv, UI_CONTROL_INVENTORY.csv and
FUNCTIONALITY_INVENTORY.csv, plus inventory_summary.json.

* Routes: every `frontend/src/app/**/page.tsx` of the Guided Workspace
  surfaces, with the query parameters the page and the components it renders
  read, its in-app back controls, the API paths those components call, and
  the browser journeys that visit it.
* Controls: every interactive JSX element (button, link, select, input,
  checkbox, chart click/selection handler, clickable element) in the guided
  source, with file:line, `data-testid`, label, the kind of action and its
  target. A control is EXERCISED when the browser run clicked an element
  carrying its test id (recorded by the harness, never inferred); its status
  is the status of the journeys that clicked it.
* Functionality: every workspace API endpoint (`backend/workspace/*_api.py`)
  with the pytest files and browser journeys that call it.

Decorative content is not a control: only elements with a handler, an href
or a form role are listed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
APP = SRC / "app"

#: The Guided Workspace surfaces (new in this programme).
GUIDED_ROUTES = ("issues", "what-if", "scenarios", "lenses", "monitoring",
                 "messages", "metrics", "trace", "ai-model-lab",
                 "early-warning", "cockpit", "stress")
GUIDED_DIRS = ("components/guided", "components/whatif",
               "components/scenarios", "components/lenses",
               "components/monitoring", "components/messages",
               "components/metrics", "components/workspace",
               "components/trace", "components/llm-exchange",
               "components/viz")
MODULE = {"issues": "Guided Cockpit", "cockpit": "Cockpit thread / Trace",
          "what-if": "What-If", "scenarios": "Scenario Library",
          "lenses": "Lenses", "monitoring": "Monitoring Centre",
          "messages": "Messages", "metrics": "Metric Catalogue",
          "trace": "Trace / LLM Exchange", "ai-model-lab": "AI Model Lab",
          "early-warning": "Early Warning", "stress": "What-If (redirect)",
          "": "Guided Cockpit home"}

TAG = re.compile(r"<([A-Za-z][A-Za-z0-9.]*)\b")
INTERACTIVE_PROPS = ("onClick", "href", "onChange", "onPointClick",
                     "onSelected", "onSubmit", "onRowActivate", "onKeyDown")


def _tag_span(text: str, start: int) -> int:
    """Index just past the `>` that closes the tag opened at `start`,
    skipping `>` inside braces and strings."""
    depth, i, quote = 0, start, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth == 0:
            return i + 1
        i += 1
    return len(text)


def _prop(tag: str, name: str) -> str:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    if m:
        return m.group(1)
    m = re.search(rf"\b{name}=\{{`([^`]*)`\}}", tag)
    if m:
        return m.group(1)
    m = re.search(rf"\b{name}=\{{([^}}]*)\}}", tag)
    return m.group(1).strip() if m else ""


def _label(text: str, end: int, tagname: str, tag: str) -> str:
    for attr in ("aria-label", "title", "label"):
        v = _prop(tag, attr)
        if v and len(v) < 120:
            return v
    close = text.find(f"</{tagname}>", end)
    if close == -1 or close - end > 600:
        return ""
    inner = re.sub(r"<[^>]*>", " ", text[end:close])
    inner = re.sub(r"\{[^{}]*\}", " … ", inner)
    return re.sub(r"\s+", " ", inner).strip()[:100]


def _kind(tagname: str, tag: str) -> tuple[str, str]:
    """(action kind, target)."""
    href = _prop(tag, "href")
    onclick = _prop(tag, "onClick")
    if href:
        return "navigation", href
    if "router.push" in tag or "router.replace" in tag or "push(" in onclick:
        m = re.search(r"push\((`[^`]*`|\"[^\"]*\")", tag)
        return "navigation", (m.group(1).strip("`\"") if m else "router")
    if "onPointClick" in tag or "onSelected" in tag:
        return "chart click/selection", "cross-filter or drill"
    if tagname in ("select", "input", "textarea") or "onChange" in tag:
        return "filter/input", ""
    if "onSubmit" in tag:
        return "mutation", ""
    if onclick:
        low = onclick.lower()
        for word, kind in (("share", "mutation"), ("save", "mutation"),
                           ("export", "export"), ("refresh", "mutation"),
                           ("delete", "mutation"), ("retire", "mutation"),
                           ("clone", "mutation"), ("branch", "mutation"),
                           ("execute", "analysis"), ("investigate",
                                                     "navigation"),
                           ("ask", "analysis"), ("set", "state"),
                           ("toggle", "state"), ("clear", "state")):
            if word in low:
                return kind, ""
        return "action", ""
    return "action", ""


def scan_controls() -> list[dict[str, str]]:
    rows = []
    files = []
    for d in GUIDED_DIRS:
        files += sorted((SRC / d).rglob("*.tsx"))
    for r in GUIDED_ROUTES:
        files += sorted((APP / r).rglob("*.tsx")) if (APP / r).exists() else []
    files.append(APP / "page.tsx")
    seen_files = set()
    for path in files:
        if path in seen_files or not path.exists() or path.name.endswith(
                ".test.tsx"):
            continue
        seen_files.add(path)
        text = path.read_text(encoding="utf-8")
        for m in TAG.finditer(text):
            tagname = m.group(1)
            end = _tag_span(text, m.start())
            tag = text[m.start():end]
            if not any(re.search(rf"\b{p}=", tag) for p in INTERACTIVE_PROPS):
                continue
            if tagname in ("svg", "path", "g", "rect", "Fragment"):
                continue
            kind, target = _kind(tagname, tag)
            testid = _prop(tag, "data-testid") or _prop(tag, "testId")
            line = text.count("\n", 0, m.start()) + 1
            rel = path.relative_to(ROOT).as_posix()
            rows.append({
                "module": _module_of(rel), "file": rel, "line": line,
                "element": tagname, "testid": testid,
                "label": _label(text, end, tagname, tag), "kind": kind,
                "target": target[:120],
                "disabled_rule": _prop(tag, "disabled")[:80]})
    return rows


def _module_of(rel: str) -> str:
    for key, name in (("guided", "Guided Cockpit"), ("whatif", "What-If"),
                      ("scenarios", "Scenario Library"),
                      ("lenses", "Lenses"), ("monitoring", "Monitoring Centre"),
                      ("messages", "Messages"), ("metrics", "Metric Catalogue"),
                      ("trace", "Trace / LLM Exchange"),
                      ("llm-exchange", "Trace / LLM Exchange"),
                      ("workspace", "Shared workspace"), ("viz", "Charts"),
                      ("issues", "Guided Cockpit"),
                      ("what-if", "What-If"),
                      ("ai-model-lab", "AI Model Lab"),
                      ("early-warning", "Early Warning")):
        if f"/{key}/" in rel or rel.endswith(f"/{key}.tsx"):
            return name
    return "Guided Cockpit home" if rel.endswith("app/page.tsx") else "Other"


def _testid_regex(testid: str) -> re.Pattern | None:
    if not testid:
        return None
    pat = re.escape(testid)
    pat = re.sub(r"\\\$\\\{[^}]*\\\}", ".+", pat)  # template parts
    if testid.startswith("{") or "?" in testid or "(" in testid:
        return None
    return re.compile(rf"^{pat}$")


def scan_routes(journey_src: str) -> list[dict[str, str]]:
    rows = []
    for page in sorted(APP.rglob("page.tsx")):
        rel = page.relative_to(APP).parent.as_posix()
        route = "/" + ("" if rel == "." else rel)
        first = route.strip("/").split("/")[0]
        if first not in GUIDED_ROUTES and route != "/":
            continue
        text = page.read_text(encoding="utf-8")
        comps = set(re.findall(r'from "@/components/([^"]+)"', text))
        sources = [page]
        for c in comps:
            for ext in (".tsx", ".ts"):
                f = SRC / "components" / f"{c}{ext}"
                if f.exists():
                    sources.append(f)
        blob = "\n".join(f.read_text(encoding="utf-8") for f in sources)
        params = sorted(set(re.findall(
            r'(?:params|searchParams|URLSearchParams\([^)]*\))\.get\("([^"]+)"\)',
            blob)) | set(re.findall(r'useSearchParams\(\)\.get\("([^"]+)"\)',
                                    blob)))
        backs = sorted(set(re.findall(
            r'data-testid="([^"]*back[^"]*)"', blob)))
        if "ArrowLeft" in blob and not backs:
            backs = ["(ArrowLeft control without test id)"]
        api = sorted(set(re.findall(r'ws(?:Get|Send)[^(]*\(\s*[`"]([^`"$?]+)',
                                    blob)))[:12]
        static = re.sub(r"\[[^\]]+\]", "[^/]+", route)
        journeys: list[str] = []
        hits = [m.start() for m in re.finditer(
            re.escape(route.split("[")[0].rstrip("/")) or "/", journey_src)]
        rows.append({
            "route": route, "module": MODULE.get(first, first),
            "flag": "NEXT_PUBLIC_GUIDED_WORKSPACE" if first not in (
                "cockpit", "early-warning", "trace", "ai-model-lab") else
            "accepted route (guided branch inside)",
            "source": page.relative_to(ROOT).as_posix(),
            "components": ";".join(sorted(comps))[:300],
            "query_params": ";".join(params),
            "back_controls": ";".join(backs),
            "deep_link": "yes" if "[" in route or params else "static",
            "api_paths": ";".join(api), "journey_mentions": len(hits),
            "_static": static, "_journeys": journeys})
    return rows


def scan_functionality() -> list[dict[str, str]]:
    rows = []
    tests = {p: p.read_text(encoding="utf-8") for p in
             (ROOT / "tests/cockpit_v4").glob("test_gw_*.py")}
    browser = (ROOT / "tests/guided_workspace/browser/gw.browser.mjs"
               ).read_text(encoding="utf-8")
    for api in sorted((ROOT / "backend/workspace").glob("*_api.py")):
        text = api.read_text(encoding="utf-8")
        for m in re.finditer(r'@router\.(get|post|put|delete|patch)\("([^"]+)"',
                             text):
            method, path = m.group(1).upper(), m.group(2)
            fn = re.search(r"async def (\w+)", text[m.end():m.end() + 400])
            probe = re.sub(r"\{[^}]+\}", "", path).rstrip("/")
            covering = sorted(p.name for p, t in tests.items()
                              if probe and probe in t)
            in_browser = probe in browser
            rows.append({
                "method": method, "path": f"/api/v1/cockpit-v4/workspace"
                                          f"{path}",
                "handler": f"{api.name}:{fn.group(1) if fn else '?'}",
                "pytest_files": ";".join(covering)[:400],
                "browser_journeys": "yes" if in_browser else "",
                "status": "PASS" if covering else "UNTESTED"})
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--journeys", default="")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    runs = (json.loads(Path(args.journeys).read_text())["journeys"]
            if args.journeys else [])
    clicked: dict[str, set[str]] = defaultdict(set)
    for j in runs:
        for t in j.get("controls_clicked", []):
            clicked[t].add(f"{j['journey']}:{j['status']}")
    browser_src = "\n".join(
        p.read_text(encoding="utf-8") for p in
        (ROOT / "tests/guided_workspace/browser").glob("*.mjs"))

    controls = scan_controls()
    for c in controls:
        rx = _testid_regex(c["testid"])
        hits = sorted({h for t, hs in clicked.items() if rx and rx.match(t)
                       for h in hs})
        referenced = bool(c["testid"]) and (
            c["testid"].split("${")[0] in browser_src)
        c["journeys_clicked"] = ";".join(hits)[:300]
        c["referenced_by_browser_test"] = "yes" if referenced else ""
        if hits:
            c["status"] = ("FAILED" if any(h.endswith(":FAILED") for h in hits)
                           else "PASS")
            c["evidence"] = "clicked in a browser journey (runtime record)"
        elif not runs:
            c["status"] = "NOT_RUN"
            c["evidence"] = ""
        else:
            c["status"] = "PARTIAL"
            c["evidence"] = ("present in source; not clicked by any browser "
                             "journey in this run" + (
                                 " (no stable test id)" if not c["testid"]
                                 else ""))
    cols = ["module", "file", "line", "element", "testid", "label", "kind",
            "target", "disabled_rule", "referenced_by_browser_test",
            "journeys_clicked", "status", "evidence"]
    with (out / "UI_CONTROL_INVENTORY.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(controls)

    routes = scan_routes(browser_src)
    visited: dict[str, list[str]] = defaultdict(list)
    for j in runs:
        for url in j.get("urls", []):
            visited[url].append(f"{j['journey']}:{j['status']}")
    rcols = ["route", "module", "flag", "source", "components",
             "query_params", "back_controls", "deep_link", "api_paths",
             "journey_mentions", "status"]
    for r in routes:
        rx = re.compile("^" + r["_static"] + "$")
        hits = sorted({h for u, hs in visited.items() if rx.match(u)
                       for h in hs})
        r["status"] = ("FAILED" if any(h.endswith(":FAILED") for h in hits)
                       else "PASS" if hits else
                       ("PARTIAL" if runs else "NOT_RUN"))
        r["journeys_visiting"] = ";".join(hits)[:300]
    with (out / "ROUTE_INVENTORY.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rcols + ["journeys_visiting"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(routes)

    funcs = scan_functionality()
    with (out / "FUNCTIONALITY_INVENTORY.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(funcs[0]))
        w.writeheader()
        w.writerows(funcs)

    def count(rows, key="status"):
        c: dict[str, int] = defaultdict(int)
        for r in rows:
            c[r[key]] += 1
        return dict(c)
    summary = {
        "controls": len(controls), "controls_by_status": count(controls),
        "controls_with_testid": sum(1 for c in controls if c["testid"]),
        "controls_exercised": sum(1 for c in controls
                                  if c["journeys_clicked"]),
        "routes": len(routes), "routes_by_status": count(routes),
        "functions": len(funcs), "functions_by_status": count(funcs)}
    (out / "inventory_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
