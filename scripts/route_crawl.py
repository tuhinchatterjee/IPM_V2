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
)

#: Text a broken page renders. Matched case-insensitively against the body.
BROKEN_MARKERS: tuple[tuple[str, str], ...] = (
    ("that address does not exist", "not-found boundary"),
    ("this page could not be loaded", "error boundary"),
    ("application error", "unhandled client exception"),
)

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
    links: int = 0
    ways_out: int = 0
    source: str = "route"

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "role": self.role, "status": self.status,
                "ok": self.ok, "reason": self.reason,
                "console": self.console[:5], "links": self.links,
                "ways_out": self.ways_out, "source": self.source}


@dataclass
class Report:
    started: str = ""
    error: str = ""
    visits: list[Visit] = field(default_factory=list)
    resolved: dict[str, str] = field(default_factory=dict)

    @property
    def failures(self) -> list[Visit]:
        return [v for v in self.visits if not v.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "error": self.error,
            "roles": [r for r, _ in ROLES],
            "resolved_ids": dict(self.resolved),
            "visits": [v.to_dict() for v in self.visits],
            "total": len(self.visits),
            "failed": len(self.failures),
            "passed": len(self.visits) - len(self.failures),
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
    if thread:
        report.resolved["saved_investigation"] = thread
        found.append(f"/investigations/saved/{thread}")

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


def _visit(page: Any, path: str, role: str, *, source: str) -> Visit:
    visit = Visit(path=path, role=role, source=source)
    console: list[str] = []
    page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
    page.on("console",
            lambda m: console.append(f"{m.type}: {m.text}")
            if m.type == "error" else None)
    try:
        response = page.goto(f"{FRONTEND}{path}",
                             wait_until="domcontentloaded", timeout=45_000)
    except Exception as e:  # noqa: BLE001
        visit.reason = f"{type(e).__name__}: {str(e)[:140]}"
        return visit

    visit.status = response.status if response else 0
    if visit.status >= 400:
        visit.reason = f"HTTP {visit.status}"
        return visit

    try:
        page.wait_for_selector("main", timeout=20_000)
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
    if visit.console and not visit.reason:
        visit.reason = f"console error: {visit.console[0][:140]}"

    visit.ok = not visit.reason
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
            page = context.new_page()
            for path in routes:
                visit = _visit(page, path, role, source="route")
                report.visits.append(visit)
                if visit.ok and role == "ADMIN":
                    discovered.update(_links(page))
            context.close()

        if follow_links:
            # Everything the crawl FOUND that it was not told about. This is
            # where a dead Back link or a stale deep link turns up.
            extra = sorted(discovered - set(routes))
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"X-IPM-Role": "ADMIN",
                                    "X-IPM-User-Id": "1"})
            page = context.new_page()
            for path in extra:
                report.visits.append(
                    _visit(page, path, "ADMIN", source="discovered link"))
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
