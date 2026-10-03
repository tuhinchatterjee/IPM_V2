"""Join every inventoried UI control to the runtime record of its execution.

Used by `validation_inventory.py`. Nothing here infers a result from source:
a control is PASS only when a browser journey performed it and recorded what
happened; source analysis decides only WHICH runtime records can belong to
a control (its test-id pattern and the routes that render its file) and
which controls belong to a legacy surface that the enabled configuration
does not render.

Runtime records (written by `tests/guided_workspace/browser/gw.browser.mjs`):

* `exec`: one per click on an element carrying a test id, in every journey:
  the id, the address before and after, the API calls made until the next
  click (writes separated), failed or 4xx/5xx requests, console errors, a
  download, and whether a model-calling endpoint was hit.
* `controls`: one per control a GW-CTL journey exercised deliberately, with
  its prerequisite state, the action, the expected and the observed state
  transition, the result (PASS, FAILED, BLOCKED_WITH_GOVERNED_REASON with
  the reason shown, NOT_APPLICABLE_WITH_PROOF), and for a navigating
  control the in-product Back, browser Back and browser Forward outcome.
* `handoffs`: one per cross-module handoff travelled, with the business
  object at the source and at the destination, whether its identity (id and
  hash) was preserved, the writes the navigation made, and the Back result.
* `na_proofs`: one per legacy route, showing what the enabled configuration
  renders there instead (the governed surface, or the address it hands
  over to) and that the legacy surface is absent.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
APP = SRC / "app"

IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*)["']((?:@/|\.{1,2}/)[^"']+)["']""")

#: Endpoints that call a model (a Cockpit question, an AI Model Lab replay).
MODEL_CALL = re.compile(r"^POST /api/v1/cockpit-v4/(runs($|\?)|workspace/model-lab/replay)")

#: Console lines that are a known, documented benign condition, matched
#: exactly. Nothing else is ignored.
BENIGN_CONSOLE: tuple[tuple[str, re.Pattern], ...] = ()

#: Legacy surfaces. In a V4 runtime with the Guided Workspace on, each page
#: below renders its governed equivalent (or hands over to it) instead of the
#: legacy component; the legacy controls are therefore not reachable. `guard`
#: names the functions that DO render under the enabled configuration (their
#: controls, if any, need their own runtime evidence).
LEGACY_PAGES: dict[str, dict[str, Any]] = {
    "app/page.tsx": {
        "route": "/", "guard": {"CockpitPage"},
        "proof": "app/page.tsx: CockpitPage renders <CockpitV4Home /> when "
                 "cockpitV4Enabled(); the legacy <Cockpit /> otherwise"},
    "app/early-warning/page.tsx": {
        "route": "/early-warning", "guard": {"EarlyWarningPage"},
        "proof": "app/early-warning/page.tsx: EarlyWarningPage returns "
                 "<EarlyWarningV4 /> when cockpitV4Enabled() && guidedEnabled()"},
    "app/lenses/page.tsx": {
        "route": "/lenses", "guard": {"LensesPage"},
        "proof": "app/lenses/page.tsx: LensesPage returns <LegacyLensesPage /> "
                 "only when !guidedEnabled()"},
    "app/lenses/[lensId]/page.tsx": {
        "route": "/lenses/[lensId]", "guard": {"LensPage", "GuidedLens"},
        "proof": "app/lenses/[lensId]/page.tsx: LensPage returns "
                 "<LegacyLensPage /> only when !guidedEnabled()"},
    "app/lenses/cro/page.tsx": {
        "route": "/lenses/cro", "guard": {"CroLensRoute", "RedirectToGovernedLens"},
        "proof": "app/lenses/cro/page.tsx: CroLensRoute redirects to "
                 "/lenses/lens-01 when guidedEnabled()"},
    "app/stress/page.tsx": {
        "route": "/stress", "guard": {"StressRoute", "RedirectToWhatIf"},
        "proof": "app/stress/page.tsx: StressRoute redirects to /what-if when "
                 "guidedEnabled()"},
    "app/trace/page.tsx": {
        "route": "/trace", "guard": {"TraceRoute"},
        "proof": "app/trace/page.tsx: TraceRoute hands over to / when "
                 "legacyRedirectActive() (VAL-DEF-026)"},
    "app/trace/[runId]/page.tsx": {
        "route": "/trace/[runId]", "guard": {"TraceRoute"},
        "proof": "app/trace/[runId]/page.tsx: TraceRoute hands over to "
                 "/cockpit/trace/<run id> when legacyRedirectActive() "
                 "(VAL-DEF-026)"},
    "app/early-warning/lab/page.tsx": {
        "route": "/early-warning/lab", "guard": {"ModelLabRoute"},
        "proof": "app/early-warning/lab/page.tsx: ModelLabRoute hands over to "
                 "/early-warning when legacyRedirectActive() (VAL-DEF-032)"},
    "app/early-warning/signals/page.tsx": {
        "route": "/early-warning/signals", "guard": {"SignalsRoute"},
        "proof": "app/early-warning/signals/page.tsx: SignalsRoute hands over "
                 "to /early-warning when legacyRedirectActive() (VAL-DEF-032)"},
}
#: Routes whose whole page is legacy under the enabled configuration (a
#: component rendered ONLY by these routes is itself legacy).
LEGACY_ONLY_ROUTES = {"/lenses/cro", "/stress", "/trace", "/trace/[runId]",
                      "/early-warning/lab", "/early-warning/signals"}


# ---- source analysis ------------------------------------------------------------------

def _resolve(spec: str, here: Path) -> Path | None:
    base = SRC / spec[2:] if spec.startswith("@/") else (here.parent / spec)
    for cand in (base.with_suffix(".tsx"), base.with_suffix(".ts"),
                 base / "index.tsx", base / "index.ts", base):
        if cand.is_file():
            return cand.resolve()
    return None


def import_graph() -> dict[Path, set[Path]]:
    graph: dict[Path, set[Path]] = {}
    for f in list(SRC.rglob("*.tsx")) + list(SRC.rglob("*.ts")):
        if "node_modules" in f.parts or f.name.endswith((".test.tsx",
                                                         ".test.ts")):
            continue
        deps = set()
        for m in IMPORT.finditer(f.read_text(encoding="utf-8")):
            t = _resolve(m.group(1), f)
            if t is not None:
                deps.add(t)
        graph[f.resolve()] = deps
    return graph


def page_routes() -> dict[str, Path]:
    out = {}
    for page in APP.rglob("page.tsx"):
        rel = page.relative_to(APP).parent.as_posix()
        out["/" + ("" if rel == "." else rel)] = page.resolve()
    return out


def route_regex(route: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\[[^\]]+\]", "[^/]+", route) + "/?$")


def rendering_routes() -> dict[str, set[str]]:
    """file (repo-relative) -> the page routes whose import closure holds it."""
    graph = import_graph()
    out: dict[str, set[str]] = defaultdict(set)
    for route, page in page_routes().items():
        seen, todo = set(), [page]
        while todo:
            f = todo.pop()
            if f in seen:
                continue
            seen.add(f)
            todo.extend(graph.get(f, ()))
        for f in seen:
            out[f.relative_to(ROOT).as_posix()].add(route)
    return out


def applicability(row: dict[str, str], routes: set[str]) -> tuple[str, str, str]:
    """('REACHABLE' | 'LEGACY' | 'NOT_RENDERED', the legacy route, proof)."""
    rel = row["file"].replace("frontend/src/", "")
    rule = LEGACY_PAGES.get(rel)
    if rule and row.get("component") not in rule["guard"]:
        return "LEGACY", rule["route"], rule["proof"]
    if not routes:
        return "NOT_RENDERED", "", "no page route imports this file"
    if routes <= LEGACY_ONLY_ROUTES:
        r = sorted(routes)
        return ("LEGACY", r[0], f"rendered only by {', '.join(r)}, which "
                f"{'hands' if len(r) == 1 else 'hand'} over to the governed "
                f"route under the enabled configuration (import graph)")
    return "REACHABLE", "", ""


def _block_end(text: str, start: int) -> int:
    """End index of the `{...}` body that opens at or after `start`."""
    i = text.find("{", start)
    depth = 0
    while 0 <= i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


FN_DECL = re.compile(r"(?:async\s+)?function\s+([a-z]\w*)\s*\(|"
                     r"const\s+([a-z]\w*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{")


def _calls(name: str) -> re.Pattern:
    return re.compile(rf"\b{name}\s*\(|={{{name}}}|\b{name}\b\)?\s*[}}\]]")


def owning_controls(file_text: str, line: int, rows: list[dict[str, Any]],
                    tags: list[tuple[int, int, str]] = ()
                    ) -> list[dict[str, Any]]:
    """The controls that trigger the navigation written at `line`:

    1. the control whose tag contains it;
    2. the controls inside the component instance whose callback prop
       (`onRun={...}`) contains it, i.e. the controls that call that prop;
    3. a `const href = ...` line: the controls whose tag uses `href`;
    4. the controls whose handler calls the innermost named function that
       contains it, directly or through a callback prop of a child.
    """
    here = [r for r in rows if r["line"] <= line <= r.get("end_line", r["line"])]
    if here:
        return [max(here, key=lambda r: r["line"])]
    for start, end, tag in sorted(tags, key=lambda t: t[0], reverse=True):
        if start <= line <= end:
            props = re.findall(r"\b(on[A-Z]\w*)=\{", tag)
            owners = [r for r in rows if any(_calls(p).search(r.get("tag", ""))
                                             for p in props)]
            if owners:
                return owners
    text_line = file_text.split("\n")[line - 1]
    const = re.match(r"\s*const\s+(\w+)\s*=", text_line)
    if const:
        used = re.compile(rf"\{{{const.group(1)}\}}")
        owners = [r for r in rows if used.search(r.get("tag", ""))]
        if owners:
            return owners
    pos = sum(len(x) + 1 for x in file_text.split("\n")[:line - 1])
    best = None
    for m in FN_DECL.finditer(file_text, 0, pos):
        end = _block_end(file_text, m.end() - 1)
        if end >= pos:
            best = m.group(1) or m.group(2)
    if not best:
        return []
    owners = [r for r in rows if _calls(best).search(r.get("tag", ""))]
    if owners:
        return owners
    # Through a child's callback prop: `<IssueCard onInvestigate={(q) =>
    # investigate(issue, q)} />`, then the controls calling `onInvestigate`.
    props = {m.group(1) for _, _, tag in tags
             for m in re.finditer(r"\b(on[A-Z]\w*)=\{[^}]*\b" + best +
                                  r"\b", tag)}
    return [r for r in rows if any(_calls(p).search(r.get("tag", ""))
                                   for p in props)]


def target_regex(target: str) -> re.Pattern:
    """`/what-if?cohort=${x}&from=issue` -> a pattern over a destination
    address whose `back=` parameter has been removed."""
    pat = re.escape(target)
    pat = re.sub(r"\\\$\\\{(?:[^{}]|\\\{[^{}]*\\\})*?\\\}", "[^&/]*", pat)
    return re.compile("^" + pat + "$")


def strip_back(url: str) -> str:
    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k != "back"]
    return parts.path + (f"?{urlencode(q, safe='/:${}')}" if q else "")


# ---- the join ------------------------------------------------------------------------

def _path(url: str) -> str:
    return urlsplit(url or "").path or "/"


def _clean(e: dict[str, Any]) -> list[str]:
    problems = [c for c in e.get("console", [])
                if not any(rx.search(c) for _, rx in BENIGN_CONSOLE)]
    return problems + list(e.get("failed", []))


def _summ_calls(e: dict[str, Any]) -> str:
    calls = e.get("api", [])
    return "; ".join(calls[:6]) + (f" (+{len(calls) - 6})" if len(calls) > 6
                                   else "")


def _expected(row: dict[str, str]) -> str:
    k = row["kind"]
    if k == "navigation":
        return f"navigates to {row['target'] or 'its destination'}"
    if k == "mutation":
        return "a governed write through the workspace API"
    if k == "export":
        return "a file is produced (download)"
    if k == "chart click/selection":
        return "the chart's app-owned click/selection changes the page state"
    if k == "analysis":
        return "an analysis starts on the governed objects shown"
    return "the page state changes as labelled; no unintended write"


def join(controls: list[dict[str, Any]], runs: list[dict[str, Any]]
         ) -> list[dict[str, Any]]:
    """Set `status` and the execution-matrix fields on every control row."""
    scope = rendering_routes()
    exec_recs, explicit, handoffs, na = [], [], [], {}
    for j in runs:
        ok = j.get("status") == "PASS"
        for e in j.get("exec", []):
            exec_recs.append({**e, "journey": j["journey"], "journey_ok": ok})
        for c in j.get("controls", []):
            explicit.append({**c, "journey": j["journey"], "journey_ok": ok})
        for h in j.get("handoffs", []):
            handoffs.append({**h, "journey": j["journey"], "journey_ok": ok})
        for p in j.get("na_proofs", []):
            if p.get("status") == "PASS" and ok:
                na.setdefault(p["route"], {**p, "journey": j["journey"]})
            else:
                na.setdefault(p["route"] + "#failed", {**p,
                                                       "journey": j["journey"]})
    for row in controls:
        routes = scope.get(row["file"], set())
        row["routes"] = ";".join(sorted(routes))
        kind, legacy_route, proof = applicability(row, routes)
        row["applicability"] = kind
        base = {"prerequisite": "", "action": "", "expected": _expected(row),
                "observed": "", "api_calls": "", "persistence": "",
                "model_call": "", "console": "", "route_after": "",
                "back": "", "evidence": ""}
        row.update(base)
        if kind == "LEGACY":
            p = na.get(legacy_route)
            row.update({
                "prerequisite": "V4 runtime, NEXT_PUBLIC_GUIDED_WORKSPACE=1",
                "action": f"open {legacy_route}",
                "expected": "the legacy surface is not rendered; the governed "
                            "equivalent is",
                "observed": (f"landed on {p['landed']}; governed "
                             f"'{p['governed_marker']}' present; legacy "
                             f"surface absent" if p else
                             "no runtime proof recorded"),
                "route_after": p["landed"] if p else "",
                "evidence": f"{p['journey']} · {proof}" if p else proof,
                "status": ("NOT_APPLICABLE_WITH_PROOF" if p else
                           "NOT_EXERCISED")})
            continue
        if kind == "NOT_RENDERED":
            row.update({"status": "NOT_EXERCISED", "evidence": proof})
            continue
        rx = re.compile(row["match"]) if row.get("match") else None
        rregs = [route_regex(r) for r in routes]

        def mine(rec: dict[str, Any], key: str = "id", rx=rx,
                 rregs=rregs) -> bool:
            ids = [rec.get(key, ""), rec.get("control", "")] if key == "id" \
                else [rec.get(key, "")]
            return bool(rx) and any(i and rx.match(i) for i in ids) and \
                any(r.match(_path(rec.get("url") or rec.get("from_url", "")))
                    for r in rregs)
        ex = [c for c in explicit if mine(c)]
        au = [e for e in exec_recs if mine(e)]
        hs = [h for h in handoffs if mine(h, "control")]
        row["_handoff_records"] = hs
        navigates = any(_path(e.get("url_after", "")) != _path(e.get("url", ""))
                        and e.get("url_after") for e in au + ex)
        status, pick = "NOT_EXERCISED", None
        failed_ex = [c for c in ex if c.get("result") == "FAILED"
                     or not c.get("journey_ok")]
        good_ex = [c for c in ex if c.get("journey_ok") and c.get("result") in (
            "PASS", "BLOCKED_WITH_GOVERNED_REASON",
            "NOT_APPLICABLE_WITH_PROOF")]
        good_au = [e for e in au if e["journey_ok"] and not _clean(e)]
        bad_au = [e for e in au if e["journey_ok"] and _clean(e)]
        if failed_ex:
            status, pick = "FAILED", failed_ex[0]
        elif good_ex:
            pick = next((c for c in good_ex if c["result"] == "PASS"),
                        good_ex[0])
            status = pick["result"]
        elif bad_au and not good_au:
            status, pick = "FAILED", bad_au[0]
        elif good_au:
            status, pick = "PASS", good_au[0]
        elif au:
            status, pick = "FAILED", au[0]
        back = ""
        if navigates:
            trips = [c.get("back") for c in ex if c.get("back")] + \
                [h.get("back") for h in hs if h.get("back")]
            okt = [t for t in trips if t.get("ok")]
            back = (f"in-product Back: {okt[0].get('in_app', 'n/a')}; "
                    f"browser Back: {okt[0].get('browser_back')}; "
                    f"browser Forward: {okt[0].get('browser_forward')}"
                    if okt else ("FAILED: " + str(trips[0]))[:300]
                    if trips else "no Back/Forward record")
            if status == "PASS" and not okt:
                status = "FAILED" if trips else "NOT_EXERCISED"
        if pick:
            row.update({
                "prerequisite": pick.get("prereq", "") or
                f"journey {pick['journey']}",
                "action": pick.get("action", "click"),
                "expected": pick.get("expected") or row["expected"],
                "observed": pick.get("observed") or
                (f"{_path(pick.get('url', ''))} → "
                 f"{_path(pick.get('url_after', '') or pick.get('url', ''))}"
                 + (f"; download {pick['download']}" if pick.get("download")
                    else "")),
                "api_calls": _summ_calls(pick),
                "persistence": "; ".join(pick.get("writes", [])[:4]) or "none",
                "model_call": "yes" if any(MODEL_CALL.match(a) for a in
                                           pick.get("api", [])) else "no",
                "console": "; ".join(_clean(pick)[:3]) or "clean",
                "route_after": pick.get("url_after", "") or pick.get("url", ""),
                "back": back if navigates else "does not navigate",
                "evidence": ";".join(sorted({c["journey"] for c in ex + au}))
                [:300]})
            if pick.get("reason"):
                row["observed"] = f"{row['observed']} · reason shown: " \
                                  f"{pick['reason']}"
        seen = sorted({c["result"] for c in ex if c.get("result")} |
                      ({"PASS"} if good_au else set()))
        row["results_seen"] = ";".join(seen)
        if len(seen) > 1 and pick:
            others = [c for c in ex if c.get("result") != status]
            if others:
                o = others[0]
                row["observed"] = f"{row['observed']} · also {o['result']}: " \
                    f"{o.get('prereq', '')} — {o.get('observed', '')}" \
                    f"{(' · reason shown: ' + o['reason']) if o.get('reason') else ''}"[:900]
        row["status"] = status
    return controls


def evidence_by_id(runs: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Concrete test id -> the results recorded for it (explicit records,
    and clean clicks in passing journeys)."""
    out: dict[str, set[str]] = defaultdict(set)
    for j in runs:
        ok = j.get("status") == "PASS"
        for c in j.get("controls", []):
            out[c.get("id", "")].add(c.get("result", ""))
        for e in j.get("exec", []):
            if ok and not _clean(e):
                out[e.get("id", "")].add("PASS")
                if e.get("control"):
                    out[e["control"]].add("PASS")
    return out


#: The app-owned interaction contract of every interactive chart: each
#: interaction names the control ids whose runtime record proves it (any
#: one suffices). Plotly's own toolbar (zoom, pan, autoscale, PNG) is not
#: part of the contract; no app logic depends on a legend click.
CHART_CONTRACTS: dict[str, dict[str, list[str]]] = {
    "issue-drivers": {"click → drill the grid": ["issue-drivers"], "underlying data": ["issue-drivers-view-data"], "row activation → drill": ["issue-drivers-table-row"], "reset": ["issue-detail-clear-drill"], "hover payload": ["hover:issue-drivers"]},
    "issue-stage-mix": {"click → drill the grid": ["issue-stage-mix"], "reset": ["issue-detail-clear-drill"], "hover payload": ["hover:issue-stage-mix"]},
    "ew-reasons": {"click → cross-filter the page": ["ew-reasons"], "reset": ["ew-reason-clear"], "cohort creation on the filtered population": ["ew-seg-save", "ew-save-cohort"], "What-If handoff": ["ew-seg-whatif", "ew-whatif"], "hover payload": ["hover:ew-reasons"]},
    "whatif-chart-dimension": {"click → filter the grid": ["whatif-chart-dimension"], "underlying data": ["whatif-chart-dimension-view-data"], "reset": ["grid-clear-filters"], "hover payload": ["hover:whatif-chart-dimension"]},
    "whatif-chart-stage": {"click → filter the grid": ["whatif-chart-stage"], "hover payload": ["hover:whatif-chart-stage"]},
    "whatif-chart-heatmap": {"click / row activation → filter the grid": ["whatif-chart-heatmap", "whatif-chart-heatmap-table-row"], "reset": ["grid-clear-filters"], "measure switch": ["whatif-heatmap-measure"]},
    "whatif-chart-sankey": {"flow / row activation → filter the grid": ["whatif-chart-sankey", "whatif-chart-sankey-table-row"], "reset": ["grid-clear-filters"]},
    "whatif-waterfall-selected": {"click → highlight the component": ["whatif-waterfall-selected"], "compact view": ["whatif-decomp-compact"], "hover payload": ["hover:whatif-waterfall-selected"]},
    "lens-chart-trend": {"click → re-evaluate at that period": ["lens-chart-trend"], "reset": ["lens-reset"], "hover payload": ["hover:lens-chart-trend"]},
    "lens-chart-breakdown": {"click → cross-filter": ["lens-chart-breakdown"], "box select → cohort": ["lens-selection-save"], "Investigate handoff": ["lens-selection-investigate"], "What-If handoff": ["lens-selection-whatif"], "remove filter": ["lens-cross-remove"], "underlying data": ["lens-visual-.+-view-data"], "hover payload": ["hover:lens-chart-breakdown"]},
    "lens-chart-top-owners": {"click → investigate the owner": ["lens-chart-top-owners"]},
    "lens-chart-groups": {"click → open the alert / result": ["lens-chart-groups"]},
    "monitoring-by-severity": {"click → filter by severity": ["monitoring-by-severity"]},
    "monitoring-by-lens": {"click → filter by Lens": ["monitoring-by-lens"]},
    "metric-breakdown": {"click → rows behind the bar": ["metric-breakdown"], "underlying data": ["metric-breakdown-view-data"], "hover payload": ["hover:metric-breakdown"]},
}


def plotly_contracts(runs: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen = evidence_by_id(runs)
    for j in runs:
        for h in j.get("hovers", []):
            if h.get("text"):
                seen[f"hover:{h.get('chart', '')}"].add("PASS")
                if h.get("control"):
                    seen[f"hover:{h['control']}"].add("PASS")
    rows = []
    for chart, contract in CHART_CONTRACTS.items():
        for interaction, ids in contract.items():
            hits = sorted({r for pat in ids for k, rs in seen.items()
                           if re.fullmatch(pat, k) for r in rs})
            status = ("FAILED" if "FAILED" in hits else "PASS" if "PASS" in hits
                      else "NOT_EXERCISED")
            rows.append({"row_type": "interaction contract", "testid": chart,
                         "interaction": interaction,
                         "evidence_controls": ";".join(ids),
                         "results": ";".join(hits), "status": status})
    return rows


def _tags(text: str) -> list[tuple[int, int, str]]:
    import validation_inventory as vi  # the same tag scanner as the controls

    out = []
    for m in vi.TAG.finditer(text):
        end = vi._tag_span(text, m.start())
        first = text.count("\n", 0, m.start()) + 1
        out.append((first, first + text.count("\n", m.start(), end),
                    text[m.start():end]))
    return out


def join_handoffs(handoffs: list[dict[str, Any]],
                  controls: list[dict[str, Any]]) -> None:
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in controls:
        by_file[c["file"].replace("frontend/src/", "")].append(c)
    for h in handoffs:
        text = (SRC / h["file"]).read_text(encoding="utf-8")
        owners = owning_controls(text, int(h["line"]), by_file[h["file"]],
                                 _tags(text))
        h["controls"] = ";".join(o["testid"] or f"line {o['line']}"
                                 for o in owners)
        rx = target_regex(h["target_full"])
        recs = [r for o in owners for r in o.get("_handoff_records", [])
                if rx.match(strip_back(r.get("to_url", "")))]
        good = [r for r in recs if r.get("status") == "PASS" and
                r.get("journey_ok")]
        bad = [r for r in recs if r not in good]
        pick = good[0] if good else (bad[0] if bad else None)
        h["source_object"] = pick.get("source", "") if pick else ""
        h["destination_object"] = pick.get("destination", "") if pick else ""
        h["identity"] = pick.get("identity", "") if pick else ""
        h["writes_on_handoff"] = "; ".join(pick.get("writes", [])) \
            if pick else ""
        h["back"] = str(pick.get("back", ""))[:300] if pick else ""
        h["journeys"] = ";".join(sorted({r["journey"] for r in recs}))[:300]
        h["status"] = ("FAILED" if h["route_exists"] != "yes" or (bad and not
                                                                   good)
                       else "PASS" if good else "NOT_EXERCISED")
