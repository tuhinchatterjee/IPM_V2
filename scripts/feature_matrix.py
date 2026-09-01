#!/usr/bin/env python
"""The full-system feature verification matrix. §3.

    python scripts/feature_matrix.py --write
    python scripts/feature_matrix.py --check

Generated, not typed. A matrix written by hand records what somebody
remembered being there; this one enumerates what is actually there - every
page under `frontend/src/app`, every endpoint in the live OpenAPI spec, every
navigation item with the roles that can see it - and joins that against the
route crawl and the test suite.

The difference matters for the column §3 cares most about. "No visible
broken/empty/dead action may remain unreported" is a claim about what EXISTS,
so the inventory has to come from the filesystem and the router rather than
from a list someone maintained. A route added last week and forgotten appears
here whether or not anyone remembered it.

Three columns cannot be generated and are curated in `_JUDGEMENTS` below:
expected behaviour, known defect, and remaining limitation. Each one is a
statement somebody is accountable for, and deriving them from code would
produce a matrix that agrees with the code by construction and therefore
proves nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "FINAL_FEATURE_VERIFICATION_MATRIX.md"

OK = "OK"
PARTIAL = "PARTIAL"
API_ONLY = "API ONLY"
HIDDEN = "HIDDEN"
NOT_BUILT = "NOT BUILT"


@dataclass
class Judgement:
    """What a human says about a surface. Not derivable from the code."""

    expected: str
    status: str = OK
    defect: str = ""
    limitation: str = ""
    fix_commit: str = ""
    #: Roles that can reach it. "" means every signed-in role.
    role: str = ""


#: Curated per route. A route absent from here is reported as UNREVIEWED,
#: which is the honest state for a page nobody has made a claim about.
_JUDGEMENTS: dict[str, Judgement] = {
    "/": Judgement(
        "The Cockpit: ask a question, see recent investigations, and see what "
        "requires attention. Counts reflect what actually moved this period.",
        limitation="Requires Attention shows Portfolio and Data as empty at "
                   "Q2 2026 because nothing moved at those levels. Nothing "
                   "is invented to fill a filter."),
    "/analyses": Judgement(
        "Every saved Analysis, filterable, each opening its definition."),
    "/analysis/[analysisId]": Judgement(
        "One analysis definition: inputs, method, governed datasets, and a "
        "run history.",
        status=PARTIAL,
        defect="Opening the page directly logs a console 404: it requests an "
               "Assurance record, and Assurance records belong to "
               "Investigations rather than to a bare engine run. The page "
               "renders correctly.",
        limitation="Reached through Analyses or Trace, this does not arise."),
    "/investigations": Judgement(
        "Global Investigations, newest first, with their status."),
    "/investigations/[id]": Judgement(
        "One Investigation: its thread, its analyses, its Trace, its "
        "assurance record and How CreditProbe Performed."),
    "/investigations/saved/[id]": Judgement(
        "A saved Investigation at a chosen version, refreshable against a "
        "new period."),
    "/projects": Judgement("Credit Projects the signed-in user can reach."),
    "/projects/[id]": Judgement(
        "One Project: its Investigations, its people, its workflow and its "
        "Risk Cases. Project-scoped work stays inside it until published.",
        limitation="A Project holds context, threads, analyses and people "
                   "but not a structured operating plan; the governed "
                   "Project Plan is not built."),
    "/trace": Judgement("Recent analysis runs, each opening its Trace."),
    "/trace/[runId]": Judgement(
        "The Trace for one run: Story, Lineage, Landscape and Audit, with "
        "governed and interpretive steps drawn differently."),
    "/data-builder": Judgement(
        "The governed catalogue: domains, datasets, families and authority.",
        role="Administrator, Analyst"),
    "/data-builder/browse": Judgement("Every governed dataset, searchable.",
                                      role="Administrator, Analyst"),
    "/data-builder/dataset/[name]": Judgement(
        "One dataset: its grain, its fields, its authority and a real data "
        "grid.", role="Administrator, Analyst"),
    "/data-builder/domain/[...domain]": Judgement(
        "One domain and the datasets under it.",
        role="Administrator, Analyst"),
    "/data-builder/inbox": Judgement(
        "Incoming data, its drift against the contract, and what to do "
        "about it.", role="Administrator"),
    "/data-builder/new": Judgement("Register a new dataset.",
                                   role="Administrator"),
    "/data-builder/relationships": Judgement(
        "The governed relationship graph, its cardinalities and its "
        "proposals.", role="Administrator, Analyst"),
    "/studio": Judgement(
        "Analysis Studio: the certified method library.",
        role="Administrator, Analyst"),
    "/studio/[methodId]": Judgement(
        "One method: its definition, its validation and its certification.",
        role="Administrator, Analyst"),
    "/studio/new": Judgement("Define a new method for validation.",
                             role="Administrator, Analyst"),
    "/engine-builder": Judgement("Registered engine analyses.",
                                 role="Administrator, Analyst"),
    "/engine-builder/[analysisId]": Judgement("One registered analysis.",
                                              role="Administrator, Analyst"),
    "/engine-builder/new": Judgement("Register a new engine analysis.",
                                     role="Administrator"),
    "/ai-studio": Judgement(
        "AI Intelligence Studio: the six Intelligence Dimensions, the "
        "current release, evaluations and health.",
        role="Administrator",
        limitation="All 18 tabs the final brief names. Three of them — "
                   "Continuous Learning, Brain Center and Regulatory "
                   "Learning — open onto areas with their own tab bars "
                   "rather than rendering a panel, because eleven tabs "
                   "nested inside one tab produce a bar nobody reads."),
    "/ai-studio/feedback-learning": Judgement(
        "Feedback and the governed learning queue: observations, candidates, "
        "review and releases.", role="Administrator"),
    "/ai-studio/continuous-learning": Judgement(
        "Continuous Learning: what was captured since a chosen baseline and "
        "\u2014 separately \u2014 what measurably changed, the six "
        "dimensions on development against validation, the measurement "
        "timeline, the three evaluation sets and the thresholds behind "
        "every figure.",
        role="Administrator, Data Steward or Analyst",
        limitation="Reads NO BASELINE on a fresh installation and NOT "
                   "MEASURED IN THIS WINDOW once a baseline exists but no "
                   "evaluation has run inside the selected window. Those "
                   "are different states and are worded differently, "
                   "because 'nothing to compare against' and 'nobody "
                   "looked' read identically as a zero. No sealed-holdout "
                   "question or gold answer appears here, by \u00a758."),
    "/borrower-360": Judgement(
        "Borrower 360: one corporate borrower and everything the bank knows "
        "about it, across thirteen tabs, with eleven views of its "
        "relationship network, the six ways of grouping it shown side by "
        "side rather than reconciled, its hidden-relationship candidates, "
        "the graph data-quality register, and a seventeen-sheet export.",
        role="Every role can open it; the relationship graph is "
             "Administrator, Data Steward or Analyst; the named natural "
             "persons behind a borrower are Administrator or Data Steward; "
             "the export is separate again.",
        limitation="Every figure is computed over synthetic demonstration "
                   "data marked SYNTHETIC_DEMO, which describes no real "
                   "company and no real ownership structure. The connected "
                   "counterparty groups are CANDIDATES for assessment, not "
                   "determinations - graph connectivity is not regulatory "
                   "connectedness. The Network Risk Score is a relative "
                   "ranking within this population and is not a "
                   "probability, a rating, an IFRS 9 stage or an expected "
                   "credit loss. The group and single-name limit thresholds "
                   "are UNVERIFIED REGULATORY PARAMETERS. A quarter the "
                   "derivation has not been run for reads NOT COMPUTED "
                   "rather than showing a blank."),
    "/scorecard-validation": Judgement(
        "Retail Scorecard Validation: the application and behavioural "
        "scorecards, twelve tabs covering discrimination, calibration, "
        "stability, variable diagnostics, implementation replication, the "
        "model registry with its exact equations, the two agentic "
        "diagnostics, trends, findings and the validation policy.",
        role="Administrator, Data Steward or Analyst",
        limitation="Every figure is computed over synthetic demonstration "
                   "data marked SYNTHETIC_DEMO, which describes no real "
                   "customer. A month whose twelve-month performance window "
                   "has not closed shows stability only, and says when the "
                   "window closes rather than showing a zero. Metrics with "
                   "no approved limit read NO APPROVED LIMIT, which is not "
                   "a pass and is not the same as NOT MEASURED. The "
                   "validation opinion is derived by governed policy and is "
                   "not regulatory certification."),
    "/ai-studio/brain-center": Judgement(
        "The Brain Center: what Brain is running, the Learning Ledger, the "
        "three export formats, quarantined imports, the Lift Lab, the Merge "
        "Lab, installation history, rollbacks, compatibility and security.",
        role="Administrator",
        limitation="Imports, Lift Lab, Merge Lab, Installations and "
                   "Rollbacks read empty on a fresh installation, because "
                   "nothing has been imported. That is the honest state, not "
                   "a missing screen: the pipeline, the resolution set and "
                   "the enforced security rules render regardless so a "
                   "reviewer can see what would happen before it does."),
    "/studio/regulatory-intelligence": Judgement(
        "Regulatory Intelligence: the document library, the sixteen-stage "
        "processing pipeline, extracted requirements with their citations "
        "and confidence, one-by-one review, contradictions and their "
        "governed resolutions, draft method candidates and the audit trail.",
        role="Administrator or Data Steward",
        limitation="Reads empty on a fresh installation until a regulatory "
                   "document has been processed. The pipeline, the fifteen "
                   "requirement types, the twelve contradiction classes and "
                   "the ten resolutions render regardless, so a reviewer "
                   "can see what would happen before it does. Extraction "
                   "produces proposed requirements only \u2014 nothing here "
                   "changes a method, a policy or the ontology."),
    "/agent-operations": Judgement(
        "Agent Operations: runs, workers, schedules, budgets and approvals.",
        role="Administrator"),
    "/workflow": Judgement("Assigned work, comments and notifications."),
    "/users": Judgement("Users, roles and teams.", role="Administrator"),
    "/settings": Judgement("Theme, display preferences and session."),
    "/lenses": Judgement(
        "Saved dashboards of governed analyses.",
        status=PARTIAL,
        defect="A Viewer sees the Lenses link and gets a dashboard of "
               "refusals: every tile runs an analysis and running one "
               "requires an Analyst.",
        limitation="The permission is deliberate; the invitation is the "
                   "rough edge. Sign in as Analyst or Administrator."),
    "/lenses/[lensId]": Judgement("One Lens and its panels.",
                                  role="Administrator, Analyst"),
    "/lenses/cro": Judgement("The CRO Lens: the executive story.",
                             role="Administrator, Analyst"),
    "/early-warning": Judgement(
        "The Forward Risk Signal: which facilities are deteriorating and "
        "what is driving each score.", role="Administrator, Analyst"),
    "/early-warning/signals": Judgement(
        "The governed early-warning taxonomy, borrower by borrower: which "
        "named conditions fire, in which families, with the threshold each "
        "crossed and who owns it. Deliberately carries no score, and names "
        "both what could not be tested and what this deployment cannot watch "
        "for at all.", role="Administrator, Analyst"),
    "/early-warning/lab": Judgement(
        "The signal's specification, weights and out-of-time backtest. "
        "Model internals are labelled technical.",
        role="Administrator"),
    "/stress": Judgement("Scenario definitions and their impact.",
                         role="Administrator, Analyst"),
    "/playbooks": Judgement(
        "Saved sequences of governed analyses.",
        status=PARTIAL,
        limitation="Manual and on-publication triggers run; scheduled "
                   "triggers are not wired to a scheduler."),
    "/documents": Judgement(
        "Document authoring.",
        status=HIDDEN,
        limitation="A placeholder. Hidden in Demo Mode rather than shown as "
                   "though it worked."),
    "/documents/[id]": Judgement(
        "One document.", status=HIDDEN,
        limitation="Same placeholder as /documents."),
}

#: Capabilities with no page at all. §3 wants these reported, not omitted -
#: a capability that exists only at the API is a capability a demonstration
#: cannot show, and that is a fact about the build.
_HEADLESS: tuple[tuple[str, str, str, str], ...] = (
    ("Regulatory circular knowledge",
     "/api/v1/regulatory/*",
     "Ingestion in six formats, SME review, releases, as-of retrieval, "
     "citations and five critical Assurance gates.",
     "Reachable at the API and tested. No screen; the Regulatory "
     "Intelligence UI is being added in this phase."),
    ("Teaching corpus import",
     "/api/v1/teaching-corpus/*",
     "Template, four-outcome preview and import of 500+ human Q&A.",
     "Works at the API. No screen."),
    ("Governed XLSX exports",
     "/api/v1/analysis-runs/{id}/export",
     "Results Workbook and the 20-sheet Calculation Pack, from every "
     "surface that shows a result.",
     "Download buttons exist on every result surface; the export itself "
     "has no page of its own, by design."),
    ("Live AI verification",
     "scripts/verify-live-ai.ps1",
     "DryRun, Quick, Critical, Feedback and Regulatory modes against the "
     "real provider, run from Windows.",
     "A script, not a screen. Deliberately: it spends API credit and must "
     "be run deliberately."),
)


@dataclass
class Route:
    path: str
    file: str
    judgement: Judgement | None = None
    crawl: str = ""
    tests: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)


def _routes() -> list[Route]:
    """Every page that exists, from the filesystem."""
    out: list[Route] = []
    base = ROOT / "frontend" / "src" / "app"
    for page in sorted(base.rglob("page.tsx")):
        relative = page.parent.relative_to(base).as_posix()
        path = "/" if relative == "." else f"/{relative}"
        path = re.sub(r"/\(.*?\)", "", path) or "/"
        out.append(Route(path=path,
                         file=page.relative_to(ROOT).as_posix(),
                         judgement=_JUDGEMENTS.get(path)))
    return out


def _endpoints() -> dict[str, list[str]]:
    """Every live endpoint, from the OpenAPI spec, grouped by area."""
    from backend.api.main import create_app

    spec = create_app().openapi()
    grouped: dict[str, list[str]] = {}
    for path, operations in spec.get("paths", {}).items():
        parts = [p for p in path.split("/") if p]
        area = parts[2] if len(parts) > 2 and parts[0] == "api" else (
            parts[0] if parts else "/")
        for method in operations:
            if method.upper() in ("HEAD", "OPTIONS"):
                continue
            grouped.setdefault(area, []).append(f"{method.upper()} {path}")
    return grouped


def _pattern_for(route: str) -> re.Pattern[str]:
    """A dynamic route as a matcher for the concrete URLs a crawl visits.

    `/analysis/[analysisId]` is never visited literally; the crawl visits
    `/analysis/approaching_sicr_threshold`. Matching on the literal string
    would report every parameterised page as never crawled, which is a
    reassuring falsehood in the wrong direction.

    Built segment by segment rather than by escaping and then un-escaping a
    whole path, which is how the first version managed to produce a pattern
    the regex engine would not compile.
    """
    parts: list[str] = []
    for segment in route.strip("/").split("/"):
        if not segment:
            continue
        if segment.startswith("[...") and segment.endswith("]"):
            parts.append(".+")          # a catch-all matches any depth
        elif segment.startswith("[") and segment.endswith("]"):
            parts.append("[^/]+")
        else:
            parts.append(re.escape(segment))
    body = "/".join(parts)
    return re.compile(rf"^/{body}/?$" if body else r"^/$")


def _crawl() -> dict[str, str]:
    """What the browser crawl actually saw, if it has been run."""
    report = ROOT / "docs" / "route_crawl.json"
    if not report.exists():
        return {}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    seen: dict[str, list[str]] = {}
    for visit in data.get("visits", []):
        path = str(visit.get("path") or "")
        if not path:
            continue
        role = str(visit.get("role") or "").strip()
        if visit.get("ok"):
            mark = "pass"
        elif visit.get("refused_as_intended"):
            mark = "refused as intended"
        else:
            mark = "FAIL"
        seen.setdefault(path, []).append(f"{role} {mark}".strip())
    return {path: ", ".join(sorted(set(marks)))
            for path, marks in seen.items()}


def _crawl_for(route: str, crawl: dict[str, str]) -> str:
    """The crawl result for a route, matching dynamic segments."""
    if route in crawl:
        return crawl[route]
    pattern = _pattern_for(route)
    hits = [f"`{path}` {mark}" for path, mark in sorted(crawl.items())
            if pattern.match(path)]
    return "; ".join(hits[:2]) if hits else "-"


def _test_index() -> dict[str, list[str]]:
    """Which test files mention which route. Coarse and honest.

    A grep, not a coverage measurement: it says a route is exercised
    somewhere, not that it is well tested. Claiming more would be the kind of
    number this matrix exists to stop.
    """
    index: dict[str, list[str]] = {}
    for area in ("tests", "frontend/src"):
        base = ROOT / area
        if not base.exists():
            continue
        for file in base.rglob("*"):
            if not file.is_file() or file.suffix not in (".py", ".ts",
                                                         ".tsx"):
                continue
            name = file.name
            if not (name.startswith("test_") or ".test." in name
                    or "route_crawl" in name):
                continue
            try:
                body = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            index.setdefault("__files__", []).append(
                (file.relative_to(ROOT).as_posix(), body))
    return index


def _tests_for(route: str, index: dict[str, list]) -> list[str]:
    """Test files that name this route, or the concrete URLs it stands for.

    A substring search rather than a quoted-literal one: tests build URLs by
    interpolation as often as they write them out, and a matcher that only
    saw the quoted form would report a well-exercised route as untested.
    """
    stem = re.sub(r"/\[.*", "", route) or "/"
    if stem == "/":
        needles = ('"/"', "'/'")
    else:
        needles = (stem,)
    out: list[str] = []
    for name, body in index.get("__files__", []):
        if any(needle in body for needle in needles):
            out.append(name)
    return out


#: A page's first URL segment is usually its API area and sometimes is not.
#: Written out rather than guessed, because a "-" in the API column would
#: read as "this page calls no backend", which for the Cockpit is false.
_API_ALIAS: dict[str, str] = {
    "cockpit": "ask",
    "analysis": "analyses",
    "investigations": "investigations",
    "projects": "workspace",
    "ai-studio": "intelligence",
    "agent-operations": "agentic",
    "workflow": "workspace",
    "settings": "users",
    "data-builder": "data-builder",
    "engine-builder": "engine",
    "early-warning": "early-warning",
    "scorecard-validation": "scorecard",
}


def _area_for(path: str) -> str:
    first = [p for p in path.split("/") if p]
    return first[0] if first else "cockpit"


def _api_area(path: str) -> str:
    area = _area_for(path)
    return _API_ALIAS.get(area, area)


def build() -> str:
    routes = _routes()
    endpoints = _endpoints()
    crawl = _crawl()
    tests = _test_index()
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True, cwd=ROOT,
                         check=False).stdout.strip()

    reviewed = [r for r in routes if r.judgement]
    unreviewed = [r for r in routes if not r.judgement]
    defects = [r for r in reviewed if r.judgement and r.judgement.defect]
    partial = [r for r in reviewed
               if r.judgement and r.judgement.status != OK]

    lines: list[str] = [
        "# Full-system feature verification matrix",
        "",
        f"Generated from the build at `{sha}` by "
        "`scripts/feature_matrix.py`.",
        "",
        "This inventory is enumerated, not remembered. Every row comes from "
        "a page that exists on disk or an endpoint in the live OpenAPI "
        "spec, so a route added and forgotten appears here anyway. Three "
        "columns cannot be generated and are curated by hand - expected "
        "behaviour, defect and remaining limitation - because each is a "
        "claim somebody is accountable for, and deriving them from the code "
        "would produce a document that agrees with the code by construction "
        "and therefore establishes nothing.",
        "",
        "## Summary",
        "",
        "| | |",
        "|---|---|",
        f"| Pages | {len(routes)} |",
        f"| Reviewed | {len(reviewed)} |",
        f"| Not yet reviewed | {len(unreviewed)} |",
        f"| Carrying a known defect | {len(defects)} |",
        f"| Not fully OK | {len(partial)} |",
        f"| API endpoints | "
        f"{sum(len(v) for v in endpoints.values())} across "
        f"{len(endpoints)} areas |",
        f"| Browser-crawled routes | {len(crawl)} |",
        "",
    ]

    if unreviewed:
        lines += [
            "> **UNREVIEWED pages.** These exist and nobody has written down "
            "what they are supposed to do. That is a gap in this document, "
            "not evidence the page works:",
            "",
        ]
        lines += [f"> * `{r.path}`" for r in unreviewed]
        lines += [""]

    lines += ["## Pages", ""]
    by_area: dict[str, list[Route]] = {}
    for route in routes:
        by_area.setdefault(_area_for(route.path), []).append(route)

    for area in sorted(by_area):
        lines += [f"### {area}", "",
                  "| Route | Role | Expected behaviour | API area | Test | "
                  "Browser | Status | Defect | Remaining limitation |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for route in by_area[area]:
            judged = route.judgement
            expected = judged.expected if judged else "NOT REVIEWED"
            status = judged.status if judged else "UNREVIEWED"
            role = (judged.role if judged and judged.role
                    else "any signed-in role")
            defect = (judged.defect if judged else "") or "-"
            limitation = (judged.limitation if judged else "") or "-"
            api = _api_area(route.path)
            api_cell = (f"`{api}` ({len(endpoints[api])})"
                        if api in endpoints else "none")
            hits = _tests_for(route.path, tests)
            test_cell = f"{len(hits)} file(s)" if hits else "-"
            browser = _crawl_for(route.path, crawl)
            lines.append(
                f"| `{route.path}` | {role} | {expected} | {api_cell} | "
                f"{test_cell} | {browser} | {status} | {defect} | "
                f"{limitation} |")
        lines += [""]

    lines += [
        "## Capabilities with no page",
        "",
        "Reported rather than omitted: a capability that exists only at the "
        "API is one a demonstration cannot show, and that is a fact about "
        "this build.",
        "",
        "| Capability | Reachable at | What works | Why there is no screen |",
        "|---|---|---|---|",
    ]
    for name, where, works, why in _HEADLESS:
        lines.append(f"| {name} | `{where}` | {works} | {why} |")

    lines += ["", "## API surface", "",
              "| Area | Endpoints |", "|---|---|"]
    for area in sorted(endpoints):
        lines.append(f"| `{area}` | {len(endpoints[area])} |")

    lines += [
        "", "## What this document does not claim", "",
        "* The **Test** column is a grep, not a coverage measurement. It "
        "says a route is named in a test file somewhere; it does not say "
        "the route is well tested, and reading it as coverage would be "
        "exactly the false comfort this matrix exists to prevent.",
        "* The **Browser** column reflects the most recent recorded crawl. "
        "Where it reads `-`, the route was not visited in that run.",
        "* A row marked OK means no defect is known, not that none exists.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="fail if any page has no curated judgement")
    args = parser.parse_args()

    text = build()
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")

    unreviewed = [r.path for r in _routes() if not r.judgement]
    if unreviewed:
        print(f"\n{len(unreviewed)} page(s) with no curated judgement:")
        for path in unreviewed:
            print(f"  {path}")
        if args.check:
            return 1
    else:
        print("every page carries a curated expected behaviour")
    if not args.write and not args.check:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
