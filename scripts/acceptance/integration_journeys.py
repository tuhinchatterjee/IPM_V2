#!/usr/bin/env python
"""The checks that only fail when the features are running together.

    .venv/bin/python scripts/acceptance/integration_journeys.py
    .venv/bin/python scripts/acceptance/integration_journeys.py --json

Why this exists
---------------
Each feature already has a journey suite of its own — `lens_journeys.py`,
`planner_journeys.py`, `playbook_journeys/browser_journeys.py`,
`browser/scorecard-validation-journeys.mjs` — and every one of them passes on
the branch that wrote it. None of them can catch an integration defect,
because each one is run by somebody who has just prepared the state it needs.

The integration rehearsal started the container from an empty volume and found
two things no feature suite could have found:

* the Project Planner and the Playbook were **empty**, because each branch
  shipped a seed script and neither wired a step into `backend/bootstrap/plan.py`
  — the single thing the Docker entrypoint runs;
* the three shipped Lenses were **absent**, because `lenses.install()` says in
  its own docstring that it is "called from the demo bootstrap" and no caller
  existed.

Both were invisible to their own branches and obvious the moment the four
features shared one deployment. So the checks below are deliberately not
feature checks. They ask what a deployment looks like when nobody has prepared
it, and whether one feature's data still reads correctly through another
feature's surface.

What it needs
-------------
A running stack that has been bootstrapped, and nothing else:

    CREDITPROBE_API   default http://127.0.0.1:8000
    CREDITPROBE_WEB   default http://127.0.0.1:3000
    CREDITPROBE_USER  default alex.rahman

It FAILS rather than skips when a precondition is missing. "The Planner was
empty so we skipped the Planner" is the exact report that let this through.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API = os.environ.get("CREDITPROBE_API", "http://127.0.0.1:8000").rstrip("/")
WEB = os.environ.get("CREDITPROBE_WEB", "http://127.0.0.1:3000").rstrip("/")
WHO = os.environ.get("CREDITPROBE_USER", "alex.rahman")

EXIT_OK = 0
EXIT_FAILED = 1


# ------------------------------------------------------------------ reporting


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def ok(self, name: str, detail: str = "") -> None:
        self.passed.append(name)
        print(f"  [PASS] {name}" + (f"  — {detail}" if detail else ""))

    def no(self, name: str, why: str) -> None:
        self.failed.append((name, why))
        print(f"  [FAIL] {name}\n         {why}")

    def check(self, name: str, condition: bool, why: str = "",
              detail: str = "") -> bool:
        if condition:
            self.ok(name, detail)
        else:
            self.no(name, why or "the condition did not hold")
        return bool(condition)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": len(self.passed), "failed": len(self.failed),
                "failures": [{"check": n, "why": w} for n, w in self.failed]}


# ----------------------------------------------------------------- the client


class Client:
    """A signed-in HTTP session. No token juggling: the product uses a cookie."""

    def __init__(self) -> None:
        import requests

        self.session = requests.Session()
        self.session.trust_env = False  # the sandbox proxy is not in the way

    def sign_in(self, password: str) -> Any:
        r = self.session.post(f"{API}/api/v1/auth/login",
                              json={"username": WHO, "password": password},
                              timeout=30)
        r.raise_for_status()
        return r.json()

    def get(self, path: str, **kw: Any) -> Any:
        return self.session.get(f"{API}{path}", timeout=120, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.session.post(f"{API}{path}", timeout=300, **kw)


# ------------------------------------------------------- A. core CreditProbe


def core(client: Client, report: Report) -> None:
    print("\nA. Core CreditProbe")

    r = client.get("/api/v1/health")
    body = r.json() if r.ok else {}
    report.check("A the API is healthy", r.status_code == 200
                 and body.get("status") == "ok",
                 f"health returned {r.status_code}: {str(body)[:160]}")
    # `ai_provider` is deliberately excluded. With no provider key configured
    # it reports offline, and that is the CORRECT answer — §11 of the rehearsal
    # says live AI stays NOT VERIFIED rather than being faked. Asserting it
    # green here would be asserting the thing we are declining to claim.
    bad = [c for c in body.get("components", [])
           if str(c.get("status")) not in ("ok", "OK")
           and c.get("name") != "ai_provider"]
    report.check("A every health component but the AI provider is ok", not bad,
                 f"components not ok: {[c.get('name') for c in bad]}",
                 f"{len(body.get('components', []))} component(s), "
                 "ai_provider excluded by design")

    r = client.get("/api/v1/readiness")
    ready = r.json() if r.ok else {}
    failed = [c["key"] for c in ready.get("checks", [])
              if c.get("status") != "OK"]
    report.check("A every readiness check passes", ready.get("ready") is True
                 and not failed,
                 f"not ready; failing checks: {failed}",
                 ready.get("sentence", ""))

    r = client.get("/api/v1/build")
    build = r.json().get("build", {}) if r.ok else {}
    report.check("A the running image is not stale",
                 build.get("stale") is False,
                 f"image {build.get('image_sha')} against source "
                 f"{build.get('source_sha')}: {build.get('stale_detail', '')}",
                 f"image {str(build.get('image_sha'))[:12]}")

    # An ordinary Cockpit question, through the real Ask route.
    r = client.post("/api/v1/ask",
                    json={"question": "What is the total retail balance?"})
    answer = r.json() if r.ok else {}
    report.check("A the Cockpit answers an ordinary question",
                 r.status_code == 200,
                 f"ask returned {r.status_code}: {str(answer)[:200]}")
    if r.status_code == 200:
        text = json.dumps(answer)
        report.check("A the answer carries a computed result rather than prose",
                     any(k in text for k in ("\"result\"", "\"rows\"",
                                             "\"value\"", "\"trace")),
                     "the answer had no result, rows, value or trace")


# ------------------------------------- E. Scorecard Validation, end to end


def scorecard(client: Client, report: Report) -> dict[str, Any]:
    print("\nE. Scorecard Validation — persistence, history, report")
    made: dict[str, Any] = {}

    r = client.get("/api/v1/scorecard-validation/overview")
    over = r.json() if r.ok else {}
    models = [m.get("model_id") for m in over.get("scorecards", [])]
    for want in ("retail_application_champion", "retail_behaviour_champion",
                 "sme_champion"):
        report.check(f"E {want} is available", want in models,
                     f"the overview listed {models}")

    # A real run, persisted.
    r = client.post("/api/v1/scorecard-validation/models/"
                    "sme_champion/categories/discrimination")
    ran = r.json() if r.ok else {}
    key = str(ran.get("run_key") or "")
    report.check("E running a category returns a persisted run key",
                 r.status_code == 200 and bool(key),
                 f"run returned {r.status_code}: {str(ran)[:200]}", key)
    if not key:
        return made
    made["run_key"] = key

    # The AUC this run measured, for the numerical cross-check.
    auc = None
    for row in ran.get("results", []):
        if row.get("test_id") == "DISC-AUC":
            auc = row.get("value")
    report.check("E the run measured DISC-AUC", auc is not None,
                 "no DISC-AUC result in the run",
                 f"AUC = {auc}")
    made["auc"] = auc

    # History reads it back from storage.
    r = client.get("/api/v1/scorecard-validation/runs")
    runs = r.json().get("runs", []) if r.ok else []
    report.check("E the run appears in Validation History",
                 any(x.get("run_key") == key for x in runs),
                 f"history held {len(runs)} run(s), none of them {key}",
                 f"{len(runs)} run(s)")

    r = client.get(f"/api/v1/scorecard-validation/runs/{key}")
    stored = r.json() if r.ok else {}
    report.check("E a stored run opens", r.status_code == 200,
                 f"opening the run returned {r.status_code}")
    stored_auc = None
    for row in stored.get("results", []):
        if row.get("test_id") == "DISC-AUC":
            stored_auc = row.get("value")
    report.check("E the stored figure is the figure that was measured",
                 stored_auc == auc,
                 f"measured {auc}, read back {stored_auc}",
                 f"{stored_auc}")

    # A report from that run, and the .docx it renders to.
    r = client.post(f"/api/v1/scorecard-validation/runs/{key}/report")
    drafted = (r.json() or {}).get("report", {}) if r.ok else {}
    report_key = str(drafted.get("report_key") or "")
    report.check("E a report can be drafted from the persisted run",
                 r.status_code == 200 and bool(report_key),
                 f"draft returned {r.status_code}: {str(drafted)[:200]}",
                 report_key)
    if report_key:
        made["report_key"] = report_key
        r = client.get(f"/api/v1/scorecard-validation/reports/"
                       f"{report_key}.docx")
        blob = r.content if r.ok else b""
        report.check("E the report renders to a .docx",
                     r.status_code == 200 and blob[:2] == b"PK"
                     and len(blob) > 20000,
                     f"docx returned {r.status_code}, {len(blob)} byte(s)",
                     f"{len(blob)} bytes")
        made["docx"] = blob
    return made


# --------------------------------------------------- F. the domain boundary


def isolation(client: Client, report: Report) -> None:
    print("\nF. Domain isolation, in both directions")

    # The general Cockpit must not LIST the restricted datasets, and must not
    # DESCRIBE one asked for by name. The question itself is echoed back in
    # the response, so a substring test would be a false positive: what is
    # asserted is the shape of the answer, not the absence of the word.
    restricted = ("sme_scorecard_monthly_validation",
                  "retail_application_scorecard_monthly_validation",
                  "retail_behavioral_scorecard_monthly_validation",
                  "sme_scorecard_decisions")

    r = client.post("/api/v1/ask", json={"question": "What datasets do you have?"})
    listed = json.dumps(r.json()) if r.ok else ""
    named = [d for d in restricted if d in listed]
    report.check("F the Cockpit does not list the restricted datasets",
                 not named, f"the catalogue answer named {named}",
                 "none of the seven appear in the catalogue listing")

    for dataset in restricted[:2]:
        r = client.post("/api/v1/ask",
                        json={"question": f"Describe the dataset {dataset}."})
        body = r.json() if r.ok else {}
        said = str(((body.get("narrative") or {}) or {}).get("direct_answer")
                   or json.dumps(body))
        # The product's own non-oracle refusal, the same wording it uses for a
        # name that was never governed. Confirming the dataset exists and then
        # declining would itself be the disclosure.
        refused = "no governed dataset called" in said.lower()
        described = ("governed field" in said.lower()
                     and "rows" in said.lower() and dataset in said)
        report.check(f"F {dataset[:38]}… is not described",
                     refused and not described,
                     f"the Cockpit answered: {said[:220]}")

    # And the specialist must not reach a foreign domain.
    r = client.post("/api/v1/scorecard-validation/ask",
                    json={"question": "What is the corporate IFRS 9 ECL?"})
    said = json.dumps(r.json()) if r.ok else ""
    report.check("F the specialist refuses a question outside its three "
                 "scorecards",
                 r.status_code in (200, 422) and "corporate_ifrs9" not in said,
                 f"the specialist answered about a foreign domain: {said[:200]}")

    # The governed aggregate metrics the other features depend on must still
    # resolve — the isolation must not have been achieved by breaking them.
    r = client.get("/api/v1/metrics/retail.balance/value")
    val = r.json() if r.ok else {}
    report.check("F governed retail metrics still resolve",
                 r.status_code == 200,
                 f"retail.balance returned {r.status_code}: {str(val)[:160]}",
                 str(val.get("value"))[:24])


# ----------------------------------------------------------- cross-feature


def cross(client: Client, report: Report, made: dict[str, Any]) -> None:
    print("\nX. Cross-feature")

    # X1  Playbook -> Project Planner.
    r = client.get("/api/v1/playbook/actions")
    actions = r.json().get("actions", []) if r.ok else []
    report.check("X the Playbook has committee actions to link",
                 bool(actions), "no actions on any seeded committee",
                 f"{len(actions)} action(s)")
    r = client.get("/api/v1/planner/projects")
    projects = r.json().get("projects", []) if r.ok else []
    report.check("X the Project Planner has a project to link into",
                 bool(projects), "the Planner is empty",
                 f"{len(projects)} project(s)")

    if actions and projects:
        # Link one if none is linked yet. Written to tolerate either state,
        # because this check runs against a live deployment whose actions may
        # already have been linked by a person or by an earlier run — and a
        # check that only works on a pristine database is a check that stops
        # being run.
        free = [a for a in actions if not a.get("planner_task_id")]
        if free:
            r = client.post(f"/api/v1/playbook/actions/{free[0]['id']}/planner",
                            json={"project_id": projects[0]["id"]})
            report.check("X a committee action can be sent to the Planner",
                         r.status_code in (200, 201),
                         f"the bridge returned {r.status_code}: "
                         f"{str(r.json())[:220]}")
            actions = client.get("/api/v1/playbook/actions").json()["actions"]

        linked = [a for a in actions if a.get("planner_task_id")]
        report.check("X a committee action reaches the Project Planner",
                     bool(linked),
                     "no committee action carries a Planner task id",
                     f"{len(linked)} of {len(actions)} action(s) linked")

        # The task must actually be there. A foreign key written into the
        # Playbook that names nothing in the Planner is the integration defect
        # this check exists for.
        if linked:
            task_id = linked[0]["planner_task_id"]
            project_id = linked[0].get("planner_project_id") or projects[0]["id"]
            # The PROJECT, not the critical-path schedule: `/schedule` returns
            # only the nodes on the CPM graph, so a task the bridge created
            # and nobody has scheduled yet is legitimately absent from it.
            # Asking the schedule was this check's own first mistake.
            r = client.get(f"/api/v1/planner/projects/{project_id}")
            ids: set[Any] = set()

            def _walk(node: Any) -> None:
                if isinstance(node, dict):
                    if {"id", "title", "status"} <= set(node):
                        ids.add(node["id"])
                    for value in node.values():
                        _walk(value)
                elif isinstance(node, list):
                    for value in node:
                        _walk(value)

            _walk(r.json() if r.ok else {})
            report.check("X the Planner really holds the task the action names",
                         task_id in ids,
                         f"the action names Planner task {task_id}, which is "
                         f"not among the {len(ids)} task(s) on project "
                         f"{project_id} — the Playbook holds a reference the "
                         "Planner cannot show",
                         f"task {task_id} on project {project_id}")

            # And it must refuse to link the same action twice. An action that
            # appears as two Planner tasks is two people doing one thing, which
            # is the failure mode a committee bridge exists to prevent.
            again = client.post(
                f"/api/v1/playbook/actions/{linked[0]['id']}/planner",
                json={"project_id": projects[0]["id"]})
            said = str(again.json())
            report.check("X the bridge refuses to link one action twice",
                         again.status_code == 422
                         and "already linked" in said.lower(),
                         f"re-linking returned {again.status_code}: {said[:200]}")

    # X2  Metric Catalogue -> Playbook.  Every metric a committee pack
    #     DECLARES must still resolve through the governed metric service.
    #     This is the check that fails if the Metric Catalogue renames or
    #     retires a metric out from under a pack that was built against it —
    #     the pack would then render a hole in a committee room, and neither
    #     feature's own suite would notice.
    r = client.get("/api/v1/playbook/packs")
    packs = r.json().get("packs", []) if r.ok else []
    declared: set[str] = set()
    for pack in packs[:4]:
        rr = client.get(f"/api/v1/playbook/packs/{pack['id']}")
        body = rr.json() if rr.ok else {}
        body = body.get("pack") or body
        for section in body.get("sections", []) or []:
            for block in section.get("blocks", []) or []:
                metric_id = (block.get("config") or {}).get("metric_id")
                if metric_id:
                    declared.add(str(metric_id))
    report.check("X the committee packs declare governed metrics",
                 bool(declared), "no pack block declared a metric_id",
                 f"{len(declared)} distinct metric(s)")
    unresolved = []
    for metric_id in sorted(declared):
        rr = client.get(f"/api/v1/metrics/{metric_id}/value")
        if rr.status_code != 200 or (rr.json() or {}).get("value") is None:
            unresolved.append(metric_id)
    report.check("X every metric a pack declares still resolves",
                 not unresolved,
                 f"the governed metric service could not value {unresolved}; "
                 "a committee pack built on these would render a hole",
                 f"{len(declared) - len(unresolved)} of {len(declared)} resolve")

    # X3  Metric Catalogue -> Scorecard Validation: the corrected governed
    #     kernels must still be what the scorecard engine calls.
    auc = made.get("auc")
    report.check("X the scorecard engine still produces its branch figure",
                 auc is not None and abs(float(auc) - 0.6547) < 5e-4,
                 f"the SME champion AUC read {auc}, not the 0.6547 the "
                 "Scorecard Validation branch verified",
                 f"AUC {auc}")

    # X4  Scorecard Validation -> Word.  Proved structurally: it is a real
    #     OOXML package and it names the run it came from.
    blob = made.get("docx") or b""
    if blob:
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(blob)) as pack:
            names = pack.namelist()
            document = pack.read("word/document.xml").decode("utf-8", "ignore")
        report.check("X the .docx is a real OOXML package",
                     "word/document.xml" in names and "[Content_Types].xml"
                     in names, f"parts: {names[:6]}", f"{len(names)} parts")
        report.check("X the document names the run it was built from",
                     str(made.get("run_key", "")) in document,
                     "the run key is not printed in the document, so a "
                     "committee holding only the file cannot trace it")

    # X5  Notifications: two features, one inbox, no collisions.
    r = client.get("/api/v1/messages")
    inbox = r.json() if r.ok else {}
    items = inbox.get("messages") or inbox.get("threads") or []
    ids = [i.get("id") for i in items if isinstance(i, dict)]
    report.check("X the message inbox serves with both features installed",
                 r.status_code == 200,
                 f"messages returned {r.status_code}")
    report.check("X no two inbox items share an id",
                 len(ids) == len(set(ids)),
                 f"{len(ids) - len(set(ids))} duplicate id(s) in one inbox")

    # X6  Scheduler: the two sweeps are distinct kinds on one queue.
    from backend.agentic import worker

    worker._install_defaults()
    kinds = set(worker._HANDLERS)
    report.check("X planner and playbook sweeps are separate job kinds",
                 {"planner_sweep", "playbook_sweep"} <= kinds,
                 f"registered kinds: {sorted(kinds)}",
                 f"{len(kinds)} kind(s), one queue")
    targets = [f"{v.__module__}.{v.__name__}" for v in worker._HANDLERS.values()]
    report.check("X no handler is registered for two kinds",
                 len(targets) == len(set(targets)),
                 "one function serves two job kinds, so a sweep could consume "
                 "the other feature's jobs")


# ------------------------------------------------- the bootstrap invariant


def bootstrap(report: Report) -> None:
    """The check that would have caught both defects this file was born from.

    Deliberately not a browser check: it asks the plan itself, so it fails in
    a unit run on a laptop rather than only in a container somebody remembered
    to start from an empty volume.
    """
    print("\nB. The bootstrap covers every shipped feature")

    from backend.bootstrap import plan

    keys = [s.key for s in plan.steps()]
    for want, why in (
        ("lenses", "the three shipped Lenses would not be installed"),
        ("planner", "the Project Planner would be empty"),
        ("playbook", "the Playbook would have no committees"),
    ):
        report.check(f"B the bootstrap has a '{want}' step", want in keys,
                     f"{why} on a deployment nobody prepared by hand. "
                     f"Steps present: {keys}")

    report.check("B the portfolio review is still the last step",
                 keys and keys[-1] == "review",
                 f"the last step is '{keys[-1] if keys else None}'; the review "
                 "reads the finished book, so anything after it is something "
                 "the review did not see")

    letters = [s.letter for s in plan.steps()]
    report.check("B no two steps share a letter",
                 len(letters) == len(set(letters)),
                 f"duplicate letters: {letters}")


# -------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = Report()
    from backend.services.demo_users import DEMO_PASSWORD

    client = Client()
    try:
        who = client.sign_in(DEMO_PASSWORD)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        print(f"  [FAIL] sign in\n         {exc}")
        report.no("sign in", str(exc))
        if args.json:
            print(json.dumps(report.to_dict()))
        return EXIT_FAILED
    report.ok("sign in", who.get("user", {}).get("display_name", WHO))

    bootstrap(report)
    core(client, report)
    made = scorecard(client, report) or {}
    isolation(client, report)
    cross(client, report, made)

    print(f"\n{len(report.passed)} passed, {len(report.failed)} failed.")
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    return EXIT_OK if not report.failed else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
