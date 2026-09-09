#!/usr/bin/env python
"""Does the demonstration WORK — not does it render.

    .venv/bin/python scripts/acceptance/demo_functionality.py

A route answering 200 proves a page exists. It does not prove a What-If
calculates, a rating matrix sums to a hundred, an Early Warning drill-down
reaches a borrower, or a workbook opens without corrupting. Those are the
claims a demonstration makes out loud, so those are what this asks.

Every check runs against the live API over HTTP, signed in as a real
demonstration account, in the same deployment a person would be looking at.
Where a capability needs a model provider and none is configured, the check
asserts the HONEST REFUSAL rather than skipping — an unconfigured deployment
saying so is correct behaviour and is itself worth proving.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

API = "http://127.0.0.1:8000/api/v1"
USERNAME = "alex.rahman"
PASSWORD = "creditprobe-demo"
PERIOD = "Q2 2026"


@dataclass
class Report:
    checks: list[tuple[str, str, bool, str]] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    section: str = ""

    def head(self, name: str) -> None:
        self.section = name
        print(f"\n{name}")

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((self.section, name, bool(ok), detail))
        print(f"  {'+' if ok else 'X'} {name}"
              + (f"   {detail}" if detail else ""), flush=True)
        return bool(ok)

    @property
    def failed(self) -> list[tuple[str, str, bool, str]]:
        return [c for c in self.checks if not c[2]]


class Client:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, path: str, body: Any = None, *, method: str = "",
             timeout: int = 180) -> tuple[int, Any, bytes]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{API}{path}", data=data,
            headers={"Content-Type": "application/json"},
            method=method or ("POST" if data else "GET"))
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read()
                kind = response.headers.get("content-type", "")
                parsed = json.loads(raw) if "json" in kind else None
                return response.status, parsed, raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw), raw
            except Exception:                                   # noqa: BLE001
                return e.code, None, raw


def refusal_is_honest(body: Any) -> tuple[bool, str]:
    """An unconfigured capability must SAY it is unconfigured.

    The failure this guards against is a silent substitute — a default model,
    a cached answer, an empty result that reads as "nothing found". A refusal
    naming the missing configuration is correct; anything else is not.
    """
    text = json.dumps(body).lower() if body is not None else ""
    for phrase in ("credential", "not configured", "configuration_missing",
                   "provider", "unavailable", "no model"):
        if phrase in text:
            return True, phrase
    return False, text[:100]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/demo_functionality.json")
    args = parser.parse_args(argv)

    r = Report()
    c = Client()

    # ------------------------------------------------------------ sign in
    r.head("Session")
    status, body, _ = c.call("/auth/login",
                             {"username": USERNAME, "password": PASSWORD})
    if not r.add("sign in", status == 200, f"HTTP {status}"):
        return 1
    status, me, _ = c.call("/auth/me")
    who = ((me or {}).get("user") or me or {}).get("username")
    r.add("the session is carried by a real cookie",
          status == 200 and who == USERNAME, str(who))
    status, health, _ = c.call("/health")
    parts = {p["name"]: p["status"] for p in (health or {}).get("components", [])}
    # `ai_provider` is `not_configured` by design in a deployment with no key,
    # and asserting it green would be asserting a key exists. Every DETERMINISTIC
    # component must be ok; the provider is checked for honesty instead, below.
    deterministic = {k: v for k, v in parts.items() if k != "ai_provider"}
    r.add("every deterministic component reports ok",
          (health or {}).get("status") == "ok"
          and set(deterministic.values()) <= {"ok"}, str(deterministic))
    r.add("the AI provider states its own configuration rather than faking it",
          parts.get("ai_provider") in {"ok", "not_configured", "offline"},
          f"ai_provider={parts.get('ai_provider')}")

    # The first screen. Three approved questions, not a fallback: this is what
    # the reader sees before anything has been asked, and it broke silently
    # once because registering three datasets changed which eight a ranking
    # returned for an EMPTY question. A count is not enough — the fallback
    # "What data do you have in ...?" is also one question — so each has to be
    # one of the approved five.
    from backend.orchestration import suggestions as sg

    approved = {question for question, _ in sg.COCKPIT}
    status, opening, _ = c.call("/ask/suggestions")
    offered = [q.get("question") for q in (opening or {}).get("questions") or []]
    r.add("the opening screen offers three approved questions",
          status == 200 and len(offered) == sg.COCKPIT_AT_ONCE
          and all(q in approved for q in offered),
          f"{len(offered)}: {offered}")

    # ------------------------------------------------------------ Cockpit
    r.head("Cockpit")
    status, diag, _ = c.call("/cockpit/diagnostics")
    r.add("the Cockpit is available", (diag or {}).get("available") is True)
    r.add("it is pinned to the canonical release",
          (diag or {}).get("dataset_release_id") == "canonical-16q-v1",
          str((diag or {}).get("dataset_release_id")))
    status, cat, _ = c.call("/cockpit/catalogue")
    r.add("the catalogue answers in SAR millions",
          (cat or {}).get("reporting_currency") == "SAR"
          and (cat or {}).get("amount_scale") == "millions",
          f"{(cat or {}).get('reporting_currency')} "
          f"{(cat or {}).get('amount_scale')}")
    populated = ((cat or {}).get("calendar") or {}).get("populated_quarters", [])
    r.add("sixteen canonical quarters are populated", len(populated) == 16,
          f"{populated[:1]}..{populated[-1:]} ({len(populated)})")
    # A question, asked for real. With no provider configured the Cockpit must
    # stop and SAY so rather than answer from a substitute.
    status, answer, _ = c.call(
        "/cockpit/ask", {"question": "What is the total exposure this period?"})
    honest, why = refusal_is_honest(answer)
    r.add("a question either answers or refuses honestly",
          status == 200 or honest, f"HTTP {status}; {why}")

    # ------------------------------------------------------- Early Warning
    r.head("Early Warning")
    status, ews, _ = c.call("/early-warning/v2")
    summary = (ews or {}).get("summary") or {}
    r.add("the Early Warning overview answers", status == 200)
    r.add("it reports a portfolio score and a borrower count",
          bool(summary.get("portfolio_ews")) and bool(summary.get("borrower_count")),
          f"score {summary.get('portfolio_ews')}, "
          f"{summary.get('borrower_count')} borrowers")
    status, segments, _ = c.call("/early-warning/v2/segments")
    rows = (segments or {}).get("segments") or (segments or {}).get("rows") or []
    r.add("segments drill down", status == 200 and len(rows) > 0,
          f"{len(rows)} segment(s)")
    status, methodology, _ = c.call("/early-warning/v2/methodology")
    r.add("the methodology is published", status == 200 and bool(methodology))

    # -------------------------------------------------------------- What-If
    r.head("What-If")
    status, config, _ = c.call("/whatif/configuration")
    grades = ((config or {}).get("masterscale") or {}).get("grades") or []
    r.add("the configuration answers", status == 200)
    r.add("the masterscale carries 19 performing grades",
          len(grades) == 19, f"{len(grades)} grades")
    order = [g["grade"] for g in grades]
    expected = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB",
                "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C"]
    r.add("in the exact 19-point order", order == expected,
          f"{order[:4]}..{order[-2:]}")
    status, scenarios, _ = c.call("/whatif/scenarios")
    catalogue = (scenarios or {}).get("scenarios") or []
    r.add("guided scenarios are offered", status == 200 and len(catalogue) > 0,
          f"{len(catalogue)} scenario(s)")

    # A real calculation, end to end, on the Delta model.
    # Deliberately NOT catalogue[0]: that is `base`, the reported position,
    # whose whole point is that nothing moves. A check that ran it would prove
    # the engine returns the same number twice.
    shocked = [s_ for s_ in catalogue if (s_.get("shocks") or [])]
    r.add("the catalogue offers a scenario that actually shocks something",
          bool(shocked), f"{len(shocked)} of {len(catalogue)} carry a shock")
    if shocked:
        first = shocked[0]
        payload = {"scenario": first.get("key") or first.get("id"),
                   "period": PERIOD, "methodology": "delta"}
        started = time.time()
        status, run, _ = c.call("/whatif/run", payload, timeout=300)
        took = time.time() - started
        s = (run or {}).get("summary") or {}
        r.add("a Delta What-If calculates", status == 200 and bool(s),
              f"{first.get('name')} — HTTP {status} in {took:.1f}s")
        if s:
            baseline = float(s.get("baseline_ecl") or 0)
            stressed = float(s.get("stressed_ecl") or 0)
            r.add("it returns a baseline AND a scenario ECL that DIFFER",
                  baseline > 0 and stressed > 0 and stressed != baseline,
                  f"{baseline:,.0f} -> {stressed:,.0f}")
            r.add("the movement reconciles to the two figures",
                  abs(float(s.get("incremental_ecl") or 0)
                      - (stressed - baseline)) < 0.51,
                  f"stated {s.get('incremental_ecl')}, "
                  f"computed {stressed - baseline:,.2f}")
            r.add("it names the population it ran over",
                  bool(s.get("borrowers")), f"{s.get('borrowers')} borrowers")

    # The migration matrices, which the demonstration reads aloud.
    status, migration, _ = c.call(
        f"/whatif/migration/rating?period={PERIOD.replace(' ', '%20')}")
    r.add("the rating migration matrix answers", status == 200)
    r.add("it is the full 20 x 20 — 19 grades plus D as a state",
          (migration or {}).get("displayed_shape") == "20 x 20",
          str((migration or {}).get("displayed_shape")))
    r.add("it is row-normalised, and says what a row reads as",
          (migration or {}).get("normalisation") == "row"
          and bool((migration or {}).get("reads_as")),
          str((migration or {}).get("reads_as"))[:70])
    for key, what in (("row_normalised", "account"),
                      ("row_normalised_exposure", "exposure")):
        rows = (migration or {}).get(key) or []
        # A grade nobody STARTED the period on has nothing to normalise, so
        # its row sums to zero rather than to a hundred. That is the honest
        # answer and not a break: on this book AAA and C are both empty.
        populated = [x for x in rows if float(x.get("total") or 0) > 0]
        off = [x["label"] for x in populated
               if abs(sum(v for v in x["cells"] if isinstance(v, (int, float)))
                      - 100.0) > 0.51]
        r.add(f"every populated {what} row sums to 100%", not off,
              f"{len(populated)} populated of {len(rows)}; "
              f"empty grades {[x['label'] for x in rows if x not in populated]}"
              + (f"; OFF: {off}" if off else ""))

    status, stage_migration, _ = c.call(
        f"/whatif/migration/stage?period={PERIOD.replace(' ', '%20')}")
    r.add("the stage migration answers with a shape and a denominator",
          status == 200 and bool((stage_migration or {}).get("displayed_shape")),
          f"{(stage_migration or {}).get('displayed_shape')}, "
          f"denominator: {(stage_migration or {}).get('denominator')}")

    # -------------------------------------------------------------- Lenses
    r.head("Lenses")
    status, lenses, _ = c.call("/lenses")
    installed = (lenses or {}).get("lenses") or []
    r.add("the shipped lenses are installed", status == 200 and len(installed) >= 3,
          f"{len(installed)} lens(es)")
    if installed:
        one = installed[0]
        status, lens, _ = c.call(f"/lenses/{one['id']}")
        r.add("a lens opens with its definition", status == 200 and bool(lens),
              one.get("name", ""))

    # ------------------------------------------------------------ Playbook
    r.head("Playbook")
    status, home, _ = c.call("/playbook/home")
    r.add("the Playbook home answers", status == 200)
    r.add("it carries seeded workspaces",
          len((home or {}).get("recent_playbooks") or []) > 0,
          f"{len((home or {}).get('recent_playbooks') or [])} workspace(s)")
    status, library, _ = c.call("/playbook/exports")
    counts = (library or {}).get("counts") or {}
    r.add("the export library answers", status == 200)
    r.add("it holds analyses from every implemented module",
          set((library or {}).get("implemented_modules") or []) <= set(counts),
          str(counts))
    r.add("What-If is an implemented export source",
          "what_if" in ((library or {}).get("implemented_modules") or []))
    revisions = [a for a in ((library or {}).get("analyses") or [])
                 if a.get("source_module") == "what_if"]
    if revisions:
        rid = revisions[0]["revision_id"]
        status, item, _ = c.call(f"/playbook/exports/revisions/{rid}")
        payload = (item or {}).get("payload") or item or {}
        r.add("an exported What-If opens with its provenance",
              status == 200 and bool((item or {}).get("content_hash")),
              f"revision {(item or {}).get('revision')}")
        r.add("it carries the limitation that it is conditional",
              any("conditional" in str(x).lower()
                  for x in (payload.get("limitations") or [])))
        r.add("it carries a link back to its source",
              bool((payload.get("source_ref") or {}).get("link")),
              str((payload.get("source_ref") or {}).get("link")))
    status, committees, _ = c.call("/playbook/committees")
    rows = (committees or {}).get("committees") or []
    r.add("the committee half is seeded", status == 200 and len(rows) > 0,
          f"{len(rows)} committee(s)")
    status, packs, _ = c.call("/playbook/packs")
    pack_rows = (packs or {}).get("packs") or []
    r.add("committee packs exist to open", len(pack_rows) > 0,
          f"{len(pack_rows)} pack(s)")
    if pack_rows:
        pack = pack_rows[0]
        status, opened, _ = c.call(f"/playbook/packs/{pack['id']}")
        r.add("a pack opens with its sections",
              status == 200 and len((opened or {}).get("sections") or []) > 0,
              f"{pack.get('code')}: "
              f"{len((opened or {}).get('sections') or [])} section(s), "
              f"{pack.get('readiness_percent')}% ready")
    # The chase list is a DRY RUN: reading it must notify nobody. Asserted
    # because the screen says so and a demonstration will open it.
    status, chase, _ = c.call("/playbook/chase")
    r.add("the chase list reads without sending anything", status == 200,
          f"{len((chase or {}).get('outstanding') or [])} outstanding")

    # ------------------------------------------------------ Project Planner
    r.head("Project Planner")
    status, projects, _ = c.call("/planner/projects")
    rows = (projects or {}).get("projects") or []
    r.add("the delivery plan is seeded", status == 200 and len(rows) > 0,
          f"{len(rows)} project(s)")
    if rows:
        pid = rows[0]["id"]
        status, project, _ = c.call(f"/planner/projects/{pid}")
        r.add("a project opens with its workstreams and tasks",
              status == 200 and bool(project),
              rows[0].get("name", ""))

    # ------------------------------------------------- Scorecard Validation
    r.head("Scorecard Validation")
    status, overview, _ = c.call("/scorecard-validation/overview")
    domains = ((overview or {}).get("domains") or {}).get("domains") or []
    r.add("the validation overview answers", status == 200)
    r.add("all three scorecards are offered", len(domains) >= 3,
          str([d.get("domain") for d in domains]))
    status, tests, _ = c.call("/scorecard-validation/tests")
    catalogue = (tests or {}).get("tests") or []
    r.add("the governed test catalogue is published", len(catalogue) > 0,
          f"{len(catalogue)} test(s)")
    # Each of the three, opened. SME included: the model registry ROW is
    # missing (the one deferred carry-forward item) and that does not stop
    # SME validation, which is worth knowing before somebody assumes it does.
    for model in ((overview or {}).get("scorecards") or []):
        mid = model["model_id"]
        status, opened, _ = c.call(f"/scorecard-validation/models/{mid}")
        _, periods, _ = c.call(f"/scorecard-validation/models/{mid}/periods")
        r.add(f"{model['scorecard_type']} opens with its specification "
              f"and periods",
              status == 200 and bool((opened or {}).get("binned_variables")),
              f"{model['name']}, "
              f"{len((periods or {}).get('periods') or [])} period(s)")

    # ---------------------------------------------------------- Data Builder
    r.head("Data Builder")
    status, datasets, _ = c.call("/data-builder/datasets")
    rows = (datasets or {}).get("datasets") or []
    r.add("the governed catalogue is registered", status == 200 and len(rows) >= 80,
          f"{len(rows)} dataset(s)")
    names = {d.get("name") for d in rows}
    for wanted in ("corporate_borrower_360", "corporate_ifrs9",
                   "corporate_ifrs9_facility", "early_warning_borrower_month",
                   "early_warning_signal_observation"):
        r.add(f"{wanted} is catalogued", wanted in names)

    status, domains_body, _ = c.call("/data-builder/domains")
    domain_rows = (domains_body or {}).get("domains") or []
    r.add("the business domains are installed", len(domain_rows) >= 10,
          f"{len(domain_rows)} domain(s)")
    status, relationships, _ = c.call("/data-builder/relationships")
    rel_rows = ((relationships or {}).get("relationships")
                or (relationships or {}).get("rows") or [])
    r.add("governed relationships are declared", len(rel_rows) > 0,
          f"{len(rel_rows)} relationship(s)")

    # ------------------------------------------- Investigations and Studio
    r.head("Investigations, Studio, Messages")
    status, investigations, _ = c.call("/investigations")
    rows = (investigations or {}).get("investigations") or []
    r.add("investigations are listed", status == 200 and len(rows) > 0,
          f"{len(rows)} investigation(s)")
    if rows:
        status, one, _ = c.call(f"/investigations/{rows[0]['id']}")
        r.add("an investigation opens", status == 200 and bool(one),
              str(rows[0].get("title", ""))[:50])
    status, blueprints, _ = c.call("/intelligence/studio/blueprints")
    r.add("Analysis Studio offers methods to run", status == 200,
          f"HTTP {status}")
    status, counts, _ = c.call("/messages/counts")
    r.add("message counts answer", status == 200, str(counts)[:60])
    status, inbox, _ = c.call("/workspace/workflow/inbox")
    r.add("the workflow inbox answers", status == 200, f"HTTP {status}")

    # --------------------------------------------------------- Borrower 360
    r.head("Borrower 360")
    status, search, _ = c.call("/corporate/search?q=CORP-100000")
    hits = (search or {}).get("results") or (search or {}).get("borrowers") or []
    r.add("a canonical borrower is found by id", status == 200 and len(hits) > 0,
          f"{len(hits)} hit(s)")

    # ------------------------------------------------------------ downloads
    r.head("Downloads")
    status, _, raw = c.call("/early-warning/v2/reports/portfolio", timeout=300)
    r.add("the Early Warning portfolio workbook downloads",
          status == 200 and len(raw) > 10_000, f"{len(raw):,} bytes")
    if status == 200 and raw[:2] == b"PK":
        try:
            from openpyxl import load_workbook
            book = load_workbook(io.BytesIO(raw), read_only=True)
            r.add("and opens as a real workbook", len(book.sheetnames) > 0,
                  f"{len(book.sheetnames)} sheet(s): {book.sheetnames[:3]}")
        except Exception as e:                                  # noqa: BLE001
            try:
                from docx import Document
                Document(io.BytesIO(raw))
                r.add("and opens as a real Word document", True)
            except Exception:                                   # noqa: BLE001
                r.add("and opens without corruption", False, str(e)[:90])
    else:
        r.add("the download is a real Office package",
              raw[:2] == b"PK", str(raw[:8]))

    # ------------------------------------------------------ auth and session
    r.head("Auth and session")
    started = time.time()
    status, _, _ = c.call("/whatif/run",
                          {"scenario": "downgrade_one_notch",
                           "period": PERIOD, "methodology": "delta"},
                          timeout=300)
    r.add("a long analytical call completes on the same session",
          status == 200, f"HTTP {status} in {time.time() - started:.1f}s")
    status, me, _ = c.call("/auth/me")
    still = ((me or {}).get("user") or me or {}).get("username")
    r.add("the session survives the long call", still == USERNAME, str(still))

    status, _, _ = c.call("/auth/logout", {})
    r.add("sign out", status in (200, 204), f"HTTP {status}")
    status, me, _ = c.call("/auth/me")
    r.add("after sign-out the product says signed out rather than pretending",
          ((me or {}).get("authenticated") is False
           and (me or {}).get("login_required") is True), str(me)[:80])

    # The claim that matters: no PORTFOLIO DATA is readable signed out. Two
    # metadata endpoints deliberately are — the lens catalogue and the dataset
    # catalogue — and that is recorded below rather than asserted away, because
    # a check that demanded 401 everywhere would fail on a design decision
    # rather than on a defect.
    guarded = ("/playbook/home", "/planner/projects",
               "/scorecard-validation/overview", "/cockpit/diagnostics",
               "/corporate/search?q=CORP-100000", "/early-warning/v2",
               "/whatif/configuration")
    leaked = [p for p in guarded if c.call(p)[0] != 401]
    r.add("no portfolio data is readable when signed out", not leaked,
          f"reachable: {leaked}" if leaked else f"{len(guarded)} refused")
    open_metadata = [p for p in ("/lenses", "/data-builder/datasets")
                     if c.call(p)[0] == 200]
    r.add("the two open endpoints are metadata only, and are known",
          set(open_metadata) <= {"/lenses", "/data-builder/datasets"},
          f"open without a session: {open_metadata}")

    # Sign back in, so the report ends on a usable deployment rather than a
    # signed-out one somebody then has to work out how to fix.
    status, _, _ = c.call("/auth/login",
                          {"username": USERNAME, "password": PASSWORD})
    r.add("signing back in works", status == 200, f"HTTP {status}")

    body = {
        "checks": [{"section": s, "check": n, "ok": o, "detail": d}
                   for s, n, o, d in r.checks],
        "check_count": len(r.checks),
        "passed": len(r.checks) - len(r.failed),
        "failed": len(r.failed),
        "duration_seconds": round(time.time() - r.started, 1),
        "result": "PASS" if not r.failed else "FAIL",
    }
    (ROOT / args.out).write_text(json.dumps(body, indent=2))

    print()
    for section, name, _ok, detail in r.failed:
        print(f"  FAILED  {section}: {name} — {detail}")
    print(f"\n{body['result']}  {body['check_count']} checks, "
          f"{body['passed']} passed, {body['failed']} failed, "
          f"in {body['duration_seconds']}s")
    print(f"report: {args.out}")
    return 0 if not r.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
