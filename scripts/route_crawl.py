"""Authenticated route and link crawl. §31.

    "No 404/500. No console error. No stranded user. No wrong object type."

`browser_acceptance.py` proves that twelve screens RENDER at three viewports.
This proves something different and, for a demonstration, more dangerous to
get wrong: that every link a presenter might click actually goes somewhere.

The difference matters. A screen can render perfectly and carry a button to a
route that throws. Nobody finds that in a unit test, and the person who finds
it first is the one clicking in front of a client.

How it works
------------
1. Real object ids are read from the API — the seeded Project, Investigation,
   saved Analysis, Risk Case, workflow item, Trace run, Studio method and
   dataset. Detail routes are crawled with REAL ids, because `/projects/1` on
   an empty database proves nothing about `/projects/{a real one}`.
2. Every route is visited for each demo role. Console errors and page errors
   are captured for the whole visit.
3. Every internal `href` on every page is collected, de-duplicated, and then
   visited in turn.
4. A page counts as broken if it returns >= 400, renders the not-found or
   error boundary, throws in the console, or offers no way to leave.

Running it

    .venv/bin/python scripts/route_crawl.py --start
    .venv/bin/python scripts/route_crawl.py --out docs/route_crawl.json

If Chromium will not launch it EXITS 2 and reports that the crawl did not
run. It never reports a pass for a crawl that did not happen.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = "http://127.0.0.1:3000"
BACKEND = "http://127.0.0.1:8000"

#: The roles a demonstration is given under. Each sees a different sidebar,
#: and a link that 403s for a Viewer is a finding, not a feature.
ROLES: tuple[tuple[str, str], ...] = (
    ("ADMIN", "1"),
    ("ANALYST", "3"),
    ("VIEWER", "4"),
)

#: Routes that exist without needing an id. Crawled for every role.
STATIC_ROUTES: tuple[str, ...] = (
    "/", "/projects", "/investigations", "/analyses", "/documents",
    "/lenses", "/lenses/cro", "/early-warning", "/playbooks", "/stress",
    "/studio", "/data-builder", "/data-builder/browse",
    "/data-builder/relationships", "/data-builder/inbox",
    "/trace", "/workflow", "/settings", "/users",
    "/agent-operations", "/ai-studio", "/ai-studio/feedback-learning",
    # Named rather than left to link discovery: the route is permitted to
    # Administrator, Data Steward AND Analyst, and a crawl that only reached
    # it through one role's navigation would report one role's experience as
    # the route's.
    "/scorecard-validation",
)

#: Text a broken page renders. Matched case-insensitively against the body.
BROKEN_MARKERS: tuple[tuple[str, str], ...] = (
    ("that address does not exist", "not-found boundary"),
    ("this page could not be loaded", "error boundary"),
    ("application error", "unhandled client exception"),
)

#: How many DISCOVERED links to follow, at most.
#:
#: Bounded because the first run against a seeded workspace did not finish.
#: Analysis Studio lists 324 methods, Data Builder 20 datasets, and following
#: every one of them at 45 seconds of patience each is an afternoon, not a
#: release gate. The cap is applied to a SORTED list so the sample is the same
#: every run - a crawl that checked a different random 60 links each time
#: could not be compared with the last one.
#:
#: The number of links found is reported whether or not they were all
#: followed, so "60 of 412" is visible rather than looking like 60 of 60.
MAX_DISCOVERED = 60

#: Per-visit patience. Lower than the browser-acceptance harness on purpose:
#: this crawl visits hundreds of pages and a slow page is itself a finding.
VISIT_TIMEOUT_MS = 20_000
SELECTOR_TIMEOUT_MS = 10_000

#: Routes a role is EXPECTED to be refused, and why.
#:
#: A 403 here is the product working. `/users` is ADMIN-only in the sidebar,
#: `/ai-studio` is ADMIN and DATA_STEWARD, and a Viewer is read-only so
#: executing an analysis is refused wherever they type the address. None of
#: these is reachable by a link for that role - the crawl types the URL, which
#: is exactly what a permission check is for.
#:
#: Kept as an explicit table rather than "any 403 is fine", because a 403 on a
#: route a role SHOULD reach is a real defect and would be silently swallowed
#: by the looser rule. Mirrors `frontend/src/lib/navigation.ts`.
EXPECTED_REFUSALS: dict[tuple[str, str], str] = {
    ("ANALYST", "/users"): "Users & Teams is ADMIN-only",
    ("VIEWER", "/users"): "Users & Teams is ADMIN-only",
    ("VIEWER", "/ai-studio"): "the AI Studio is ADMIN and DATA_STEWARD",
    ("VIEWER", "/ai-studio/feedback-learning"):
        "the AI Studio is ADMIN and DATA_STEWARD",
    ("ANALYST", "/agent-operations"):
        "Agent Operations is ADMIN and DATA_STEWARD",
    ("VIEWER", "/agent-operations"):
        "Agent Operations is ADMIN and DATA_STEWARD",
    # The analysis page runs its analysis on load; execute is RequireAnalyst,
    # so a Viewer opening it sees the page and a refused execution. Keyed on
    # the route that actually executes - /studio/<method> renders the method
    # definition without running it, and refusing there would be wrong.
    ("VIEWER", "/analysis/approaching_sicr_threshold"):
        "a Viewer is read-only and may not execute an analysis",
    ("VIEWER", "/scorecard-validation"):
        "Retail Scorecard Validation is ADMIN, DATA_STEWARD and ANALYST",
}

#: Console lines that are noise rather than a defect. Kept deliberately short:
#: a long ignore list is how a real error gets ignored.
CONSOLE_IGNORE: tuple[str, ...] = (
    "download the react devtools",
    "favicon.ico",
)


@dataclass
class Visit:
    path: str
    role: str
    status: int = 0
    ok: bool = False
    reason: str = ""
    console: list[str] = field(default_factory=list)
    #: Requests the page made that came back >= 400, with their URLs.
    failed_requests: list[str] = field(default_factory=list)
    #: Set when every failure was a 403 on a route this role is meant to be
    #: refused. The product working, not a defect - and reported separately
    #: rather than counted as a pass, so it stays visible.
    refused_as_intended: str = ""
    links: int = 0
    ways_out: int = 0
    source: str = "route"
    #: Internal hrefs found on this page. Collected during the visit rather
    #: than by the caller afterwards, because the page does not outlive the
    #: visit any more. Not serialised - the COUNT is the reportable fact.
    hrefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "role": self.role, "status": self.status,
                "ok": self.ok, "reason": self.reason,
                "console": self.console[:5],
                "failed_requests": self.failed_requests[:5],
                "refused_as_intended": self.refused_as_intended,
                "links": self.links,
                "ways_out": self.ways_out, "source": self.source}


@dataclass
class Report:
    started: str = ""
    error: str = ""
    visits: list[Visit] = field(default_factory=list)
    resolved: dict[str, str] = field(default_factory=dict)
    #: Links the crawl found beyond the routes it was told about, and how many
    #: of them it actually followed. Reported separately so a capped run says
    #: so rather than looking complete.
    discovered: int = 0
    followed: int = 0

    @property
    def failures(self) -> list[Visit]:
        """Real defects. A permission refusal the product intends is not one."""
        return [v for v in self.visits
                if not v.ok and not v.refused_as_intended]

    @property
    def refusals(self) -> list[Visit]:
        return [v for v in self.visits if v.refused_as_intended]

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "error": self.error,
            "roles": [r for r, _ in ROLES],
            "resolved_ids": dict(self.resolved),
            "visits": [v.to_dict() for v in self.visits],
            "total": len(self.visits),
            "failed": len(self.failures),
            "refused_as_intended": len(self.refusals),
            "passed": len(self.visits) - len(self.failures)
                      - len(self.refusals),
            "links_discovered": self.discovered,
            "links_followed": self.followed,
            "max_discovered": MAX_DISCOVERED,
        }


def _api(path: str) -> Any:
    request = urllib.request.Request(
        f"{BACKEND}{path}",
        headers={"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _first(body: Any, key: str, field_name: str = "id") -> str:
    if isinstance(body, dict):
        body = body.get(key)
    if isinstance(body, list) and body:
        found = body[0]
        if isinstance(found, dict) and found.get(field_name) is not None:
            return str(found[field_name])
    return ""


def dynamic_routes(report: Report) -> list[str]:
    """Detail routes, built from ids that actually exist.

    An id that cannot be resolved is RECORDED as unresolved rather than
    guessed. A crawl of `/projects/1` against a database whose first Project
    is 2315 proves only that the not-found page works.
    """
    found: list[str] = []

    project = _first(_api("/api/v1/projects"), "projects")
    if project:
        report.resolved["project"] = project
        found.append(f"/projects/{project}")

    thread = _first(_api("/api/v1/investigations"), "investigations")
    if thread:
        report.resolved["investigation"] = thread
        found.append(f"/investigations/{thread}")

    # `/investigations/saved/{id}` takes an INVESTIGATION id, not a saved
    # Analysis id. The first version of this crawler passed the latter and
    # reported a 404 against the product; the 404 was real and the fault was
    # here. Two different objects are both called "saved" and their routes
    # look alike, which is worth knowing on its own.
    #
    # And the id is taken from the endpoint that route READS - not from the
    # Investigations list. An Investigation with no stored answer is a thread,
    # not a saved investigation, and building the route from a thread id tests
    # the not-found page rather than the feature.
    saved_thread = _first(_api("/api/v1/workspace/investigations"),
                          "investigations")
    if saved_thread:
        report.resolved["saved_investigation"] = saved_thread
        found.append(f"/investigations/saved/{saved_thread}")

    saved = _first(_api("/api/v1/analyses"), "analyses")
    if saved:
        report.resolved["saved_analysis"] = saved

    # `/analysis/{id}` takes the analysis DEFINITION id — a name like
    # `stage_distribution` — not a row id.
    definition = _first(_api("/api/v1/engine/analyses"), "analyses")
    if definition:
        report.resolved["analysis_definition"] = definition
        found.append(f"/analysis/{definition}")

    methods = _api("/api/v1/studio")
    method = _first(methods, "methods")
    if method:
        report.resolved["studio_method"] = method
        found.append(f"/studio/{method}")

    datasets = _api("/api/v1/data-builder/datasets")
    dataset = _first(datasets, "datasets", "name")
    if dataset:
        report.resolved["dataset"] = dataset
        found.append(f"/data-builder/dataset/{dataset}")

    lens = _first(_api("/api/v1/lenses"), "lenses", "slug")
    if lens:
        report.resolved["lens"] = lens
        found.append(f"/lenses/{lens}")

    run_id = _first(_api("/api/v1/analyses"), "analyses", "analysis_run_id")
    if run_id and run_id != "None":
        report.resolved["trace_run"] = run_id
        found.append(f"/trace/{run_id}")

    case = _first(_api("/api/v1/risk-cases"), "cases")
    if case:
        report.resolved["risk_case"] = case

    for name in ("project", "investigation", "saved_investigation",
                 "saved_analysis", "analysis_definition", "studio_method",
                 "dataset", "lens", "trace_run", "risk_case"):
        report.resolved.setdefault(name, "")
    return found


def _chromium() -> str | None:
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium_headless_shell-*/chrome-linux/headless_shell"):
        for found in sorted(root.glob(pattern), reverse=True):
            if found.is_file():
                return str(found)
    return None


def _wait(url: str, *, seconds: int = 150) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    return False


def _visit(context: Any, path: str, role: str, *, source: str) -> Visit:
    """Visit one route on a page of its own.

    A page per visit, not one page reused down the list. Reuse attributed
    findings to the wrong route twice over: Playwright listeners accumulate on
    a reused page, so the tenth visit recorded every earlier visit's console
    lines as well as its own; and a request still in flight when `goto` moved
    to the next route resolved AFTER the move, so its status was recorded
    against the page that happened to be open when it landed. That is how a
    Viewer's intended 403 on /scorecard-validation was reported as a defect on
    /projects/{id} - a route that makes no scorecard call at all.

    Closing the page ends both. The context is shared, so the role headers and
    any cookies still carry from route to route.
    """
    visit = Visit(path=path, role=role, source=source)
    page = context.new_page()
    try:
        return _visit_on(page, visit)
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001 - a page that already went is fine
            pass


def _visit_on(page: Any, visit: Visit) -> Visit:
    path, role = visit.path, visit.role
    console: list[str] = []
    page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
    page.on("console",
            lambda m: console.append(f"{m.type}: {m.text}")
            if m.type == "error" else None)

    # The failing REQUEST, not just the console line about it.
    #
    # Chromium's console says "Failed to load resource: the server responded
    # with a status of 404" and does not say WHICH resource, so the first
    # version of this report named a broken page and gave nobody a way to
    # find out what was broken on it. The response listener has the URL.
    failed: list[str] = []

    def _record(response: Any) -> None:
        try:
            if response.status >= 400:
                failed.append(f"{response.status} {response.url}")
        except Exception:  # noqa: BLE001 - a request that vanished is not news
            pass

    page.on("response", _record)
    try:
        response = page.goto(f"{FRONTEND}{path}",
                             wait_until="domcontentloaded",
                             timeout=VISIT_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001
        visit.reason = f"{type(e).__name__}: {str(e)[:140]}"
        return visit

    visit.status = response.status if response else 0
    if visit.status >= 400:
        visit.reason = f"HTTP {visit.status}"
        return visit

    try:
        page.wait_for_selector("main", timeout=SELECTOR_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        visit.reason = "no <main> rendered"

    try:
        text = (page.inner_text("body") or "").lower()
    except Exception:  # noqa: BLE001
        text = ""
    for marker, what in BROKEN_MARKERS:
        if marker in text:
            visit.reason = visit.reason or what
            break

    try:
        visit.links = page.evaluate(
            "() => document.querySelectorAll('a[href^=\"/\"]').length")
        visit.ways_out = page.evaluate(
            "() => document.querySelectorAll('nav a, [data-back], "
            "a[href=\"/\"]').length")
    except Exception:  # noqa: BLE001
        pass
    if not visit.ways_out and not visit.reason:
        visit.reason = "no way to leave this page"

    visit.console = [c for c in console
                     if not any(skip in c.lower() for skip in CONSOLE_IGNORE)]
    visit.failed_requests = [f for f in failed
                             if not any(skip in f.lower()
                                        for skip in CONSOLE_IGNORE)]
    if visit.failed_requests and not visit.reason:
        # Name the request. "console error: 404" is unactionable; the URL is
        # the whole of the finding.
        expected = EXPECTED_REFUSALS.get((role, path), "")
        only_403 = all(f.startswith("403 ") for f in visit.failed_requests)
        if expected and only_403:
            visit.refused_as_intended = expected
        else:
            visit.reason = "; ".join(visit.failed_requests[:2])[:200]
    elif visit.console and not visit.reason:
        visit.reason = f"console error: {visit.console[0][:140]}"

    visit.ok = not visit.reason
    visit.hrefs = _links(page)
    return visit


def _links(page: Any) -> list[str]:
    try:
        found = page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href^=\"/\"]'))"
            ".map(a => a.getAttribute('href'))")
    except Exception:  # noqa: BLE001
        return []
    clean: list[str] = []
    for href in found or []:
        if not href or href.startswith("//"):
            continue
        clean.append(href.split("#")[0].split("?")[0] or "/")
    return clean


def run(report: Report, *, follow_links: bool = True) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = "Playwright is not installed. The crawl did NOT run."
        return report

    routes = list(STATIC_ROUTES) + dynamic_routes(report)

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as e:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {e}. The crawl did "
                            "NOT run.")
            return report

        discovered: set[str] = set()
        for role, user_id in ROLES:
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"X-IPM-Role": role,
                                    "X-IPM-User-Id": user_id})
            for path in routes:
                visit = _visit(context, path, role, source="route")
                report.visits.append(visit)
                if visit.ok and role == "ADMIN":
                    discovered.update(visit.hrefs)
            context.close()

        if follow_links:
            # Everything the crawl FOUND that it was not told about. This is
            # where a dead Back link or a stale deep link turns up.
            found = sorted(discovered - set(routes))
            report.discovered = len(found)
            extra = found[:MAX_DISCOVERED]
            report.followed = len(extra)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"X-IPM-Role": "ADMIN",
                                    "X-IPM-User-Id": "1"})
            for path in extra:
                report.visits.append(
                    _visit(context, path, "ADMIN", source="discovered link"))
            context.close()
        browser.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--no-follow", action="store_true",
                        help="crawl the known routes only")
    parser.add_argument("--out", default="docs/route_crawl.json")
    args = parser.parse_args(argv)

    report = Report(started=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    processes: list[subprocess.Popen] = []
    try:
        if args.start:
            env = {**os.environ, "REQUIRE_LOGIN": "false"}
            processes.append(subprocess.Popen(
                [str(ROOT / ".venv/bin/python"), "-m", "uvicorn",
                 "backend.api.main:app", "--port", "8000"],
                cwd=ROOT, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            processes.append(subprocess.Popen(
                ["npm", "run", "start", "--", "--port", "3000"],
                cwd=ROOT / "frontend", env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            if not _wait(f"{BACKEND}/api/v1/health"):
                report.error = "the backend never became healthy"
            elif not _wait(FRONTEND):
                report.error = "the front end never became reachable"
        if not report.error:
            run(report, follow_links=not args.no_follow)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report.to_dict(), indent=2),
                              encoding="utf-8")

    if report.error:
        print(f"ROUTE CRAWL DID NOT RUN: {report.error}")
        return 2
    body = report.to_dict()
    print(f"{body['passed']}/{body['total']} visits passed across "
          f"{len(ROLES)} roles.")
    if body["refused_as_intended"]:
        print(f"  {body['refused_as_intended']} permission refusal(s), each "
              f"on a route that role has no link to - the product working")
        for refusal in report.refusals:
            print(f"    [{refusal.role:7}] {refusal.path:36} "
                  f"{refusal.refused_as_intended}")
    if body["links_discovered"]:
        print(f"  followed {body['links_followed']} of "
              f"{body['links_discovered']} discovered link(s) "
              f"(cap {MAX_DISCOVERED})")
    unresolved = [k for k, v in report.resolved.items() if not v]
    if unresolved:
        print(f"  unresolved ids (those detail routes were NOT crawled): "
              f"{', '.join(unresolved)}")
    for failure in report.failures:
        print(f"  FAIL [{failure.role:7}] {failure.path:44} {failure.reason}")
    print(f"  report {args.out}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
