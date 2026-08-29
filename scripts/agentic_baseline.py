"""
The reproducible baseline. §2, and later the post-tuning run. §27.

    §2: "Write a baseline report before tuning."
    §2: "Do not overwrite the baseline after fixes."

Run it as:

    .venv/bin/python scripts/agentic_baseline.py --out docs/BASELINE_AGENTIC.md

and after tuning:

    .venv/bin/python scripts/agentic_baseline.py --out docs/POST_TUNING_AGENTIC.md

Two files, never one edited twice. A "baseline" that gets regenerated after
the fixes is a description of the fixes.

What it runs
-------------
§28's eight Cockpit acceptance threads and §29's six Project threads, through
`agentic.run` — the same function the browser reaches. No provider is called:
`assert_no_provider_calls` makes any attempt raise, so this cannot quietly
become a live run.

What it measures
-----------------
Every field §2 lists, read off what was persisted. Plus the two things this
phase turns on: which flow class each turn belongs to, and whether its
assurance coverage meets that flow's gate.

Determinism
------------
Each run gets a fresh Investigation id and the conversation state is carried
forward inside a thread exactly as the service carries it, so a multi-turn
case (H, "does this trend make sense?") is genuinely a follow-up rather than
a cold question with a leading phrase.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------- the cases

#: §28's eight Cockpit threads. `expected_officer` is what the brief says the
#: route SHOULD be; where the brief allows either of two officers (thread D),
#: it is left None and the officer is reported rather than scored, because
#: scoring against a range invites moving the range.
COCKPIT: tuple[dict[str, Any], ...] = (
    {"id": "A", "label": "metadata",
     "question": "What ratings data do you have?",
     "expected_officer": 1, "expected_outcome": "answer",
     "note": "Credit Analyst; no unnecessary agent swarm."},
    {"id": "B", "label": "simple analysis",
     "question": "Show IFRS 9 EAD by sector for the latest quarter.",
     "expected_officer": 1, "expected_outcome": "answer",
     "note": "Credit Analyst; deterministic calculation; chart/table."},
    {"id": "C", "label": "multi-domain",
     "question": "Which customers had a rating downgrade and an increase in "
                 "ECL over the latest year?",
     "expected_officer": 2, "expected_outcome": "answer",
     "note": "Senior Credit Officer; Ratings + IFRS 9 specialists."},
    {"id": "D", "label": "segment investigation",
     "question": "Something seems wrong with Contracting. Investigate it.",
     "expected_officer": None, "expected_outcome": "answer",
     "note": "Portfolio Risk Lead or Chief Orchestrator, per the actual "
             "plan."},
    {"id": "E", "label": "portfolio review",
     "question": "Review the latest portfolio and tell me everything that "
                 "genuinely requires CRO attention.",
     "expected_officer": 4, "expected_outcome": "answer",
     "note": "Chief Orchestrator; deterministic pre-screen; no full-book "
             "fan-out."},
    {"id": "F", "label": "ambiguity",
     "question": "Show me exposure.",
     "expected_officer": 1, "expected_outcome": "clarification",
     "note": "Clarification unless thread context resolves the concept."},
    {"id": "G", "label": "unsupported",
     "question": "Which borrowers had their CEO resign?",
     "expected_officer": 1, "expected_outcome": "unsupported",
     "note": "Unsupported; no unrelated analysis."},
)

#: §28 H is a follow-up and only means anything after a first turn, so it is
#: a thread rather than a question.
PREVIOUS_RESULT_THREAD: tuple[dict[str, Any], ...] = (
    {"id": "H1", "label": "previous result — setup",
     "question": "Show IFRS 9 ECL by sector for the last four quarters.",
     "expected_officer": None, "expected_outcome": "answer"},
    {"id": "H2", "label": "previous result — reuse",
     "question": "Does this trend make sense?",
     "expected_officer": None, "expected_outcome": "answer",
     "note": "Reuse the prior result; no data rescan where sufficient."},
)

#: §29's six Project threads. Run against a Project id so the scope rules and
#: the PROJECT flow class are exercised.
PROJECT: tuple[dict[str, Any], ...] = (
    {"id": "PA", "label": "project — unresolved risks",
     "question": "Review unresolved risks in this Project."},
    {"id": "PB", "label": "project — refresh analyses",
     "question": "Refresh the saved Analyses with the latest published data."},
    {"id": "PC", "label": "project — create investigations",
     "question": "Create Investigations for the three most material open "
                 "borrower cases."},
    {"id": "PD", "label": "project — what changed",
     "question": "Which Project conclusions changed since the last review?"},
    {"id": "PE", "label": "project — send for review",
     "question": "Send the updated Project to Portfolio Risk for review."},
    {"id": "PF", "label": "project — publish globally",
     "question": "Publish this Investigation globally."},
)


# ------------------------------------------------------------------ running


def _thread(cases: tuple[dict[str, Any], ...], *, project_id: str = "",
            carry: bool = False) -> list[Any]:
    """Run a set of cases, optionally carrying conversation state forward."""
    from backend.orchestration import conversation as cv
    from backend.orchestration import memory as wm
    from backend.orchestration.orchestrator import remember as advance
    from backend.proof.probe import run_probe

    probes: list[Any] = []
    context: dict[str, Any] = {}
    for index, case in enumerate(cases):
        state = cv.load(context) if carry else None
        memory = wm.load(context) if carry else None
        probe, officer = run_probe(
            case["question"], label=f"{case['id']} — {case['label']}",
            project_id=project_id,
            state=state, memory=memory, turn_index=index,
            expected_officer=case.get("expected_officer"),
            expected_specialists=tuple(case.get("expected_specialists", ())),
            expected_outcome=str(case.get("expected_outcome", "")))
        probe.label = f"{case['id']} — {case['label']}"
        probes.append(probe)
        if carry and officer is not None:
            investigation = getattr(officer, "investigation", None)
            answered = getattr(officer, "answered", None)
            try:
                context = cv.save(context, advance(
                    cv.load(context), answered,
                    headline=str(getattr(getattr(investigation, "narrative",
                                                 None),
                                         "direct_answer", "") or ""),
                    run_id=None))
                context = wm.save(context, wm.observe(
                    wm.load(context), answered, investigation))
            except Exception:  # pragma: no cover - carrying is best-effort
                pass
    return probes


def _proof_project() -> int:
    """A real Project row to run the Project threads against.

    `project_id` is an integer foreign key throughout the platform, so a
    made-up string is not a scope — it is a type error that surfaces deep
    inside an INSERT. Creating a genuine Project also means the Project
    threads exercise the real scoping rules rather than a value the
    database happens to accept.
    """
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Project

    name = "Agentic proof harness"
    with get_session() as session:
        found = session.execute(
            select(Project).where(Project.name == name)).scalars().first()
        if found is not None:
            return int(found.id)
        made = Project(name=name,
                       description="Created by scripts/agentic_baseline.py "
                                   "to exercise Project-scoped agentic "
                                   "flows. Contains no client data.")
        session.add(made)
        session.commit()
        return int(made.id)


def collect() -> dict[str, Any]:
    """Run everything and return the raw measurement."""
    from backend.proof import coverage as cv
    from backend.proof import divergence as dv
    from backend.proof import flows as fl

    started = time.perf_counter()
    cockpit = _thread(COCKPIT)
    follow_up = _thread(PREVIOUS_RESULT_THREAD, carry=True)
    project = _thread(PROJECT, project_id=str(_proof_project()))
    every = cockpit + follow_up + project

    by_flow: dict[str, list[Any]] = {}
    for probe in every:
        by_flow.setdefault(probe.flow or fl.CONVERSATIONAL, []).append(probe)

    flow_rows: list[dict[str, Any]] = []
    for flow, probes in sorted(by_flow.items()):
        flow_rows.append({
            "flow": flow,
            "label": fl.LABELS.get(flow, flow),
            "probes": len(probes),
            "applicable": len(fl.applicable(flow)),
            "critical_applicable": len(fl.critical_for(flow)),
            "mean_coverage_pct": round(
                sum(p.coverage_pct for p in probes) / len(probes), 1)
            if probes else 0.0,
            "statuses": sorted({p.assurance_status for p in probes}),
            "scored": len([p for p in probes
                           if p.assurance_score is not None]),
        })

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "duration_s": round(time.perf_counter() - started, 1),
        "probes": [p.to_dict() for p in every],
        "cockpit": [p.to_dict() for p in cockpit],
        "follow_up": [p.to_dict() for p in follow_up],
        "project": [p.to_dict() for p in project],
        "divergence": dv.matrix(cockpit),
        "coverage_map": cv.summary(),
        "flows": flow_rows,
        "metrics": metrics(every),
        "no_provider_calls": True,
    }


def metrics(probes: list[Any]) -> dict[str, Any]:
    """§27's before/after numbers, computed the same way both times."""
    ran = [p for p in probes if p.ok]
    scored_officer = [p for p in ran if p.officer_correct is not None]
    scored_outcome = [p for p in ran if p.outcome_correct is not None]
    with_assurance = [p for p in ran if p.assurance_status]
    executed = [p for p in ran if p.executed]
    grounded = [p for p in ran if p.grounded is not None]

    def pct(part: list[Any], whole: list[Any]) -> float | None:
        return round(len(part) / len(whole) * 100.0, 1) if whole else None

    return {
        "probes": len(probes),
        "completed": len(ran),
        "errors": len([p for p in probes if not p.ok]),
        "officer_accuracy_pct": pct(
            [p for p in scored_officer if p.officer_correct], scored_officer),
        "officer_scored": len(scored_officer),
        "outcome_accuracy_pct": pct(
            [p for p in scored_outcome if p.outcome_correct], scored_outcome),
        "outcome_scored": len(scored_outcome),
        "unnecessary_specialists": sum(len(p.unnecessary_specialists)
                                       for p in ran),
        "missed_specialists": sum(len(p.missed_specialists) for p in ran),
        "mean_specialists": round(
            sum(len(p.specialists) for p in ran) / len(ran), 2) if ran else 0,
        "mean_tasks": round(sum(p.task_count for p in ran) / len(ran), 2)
        if ran else 0,
        "mean_model_calls": round(
            sum(p.model_calls for p in ran) / len(ran), 2) if ran else 0,
        "mean_latency_ms": round(
            sum(p.duration_ms for p in ran) / len(ran)) if ran else 0,
        "p95_latency_ms": (sorted(p.duration_ms for p in ran)[
            max(0, int(len(ran) * 0.95) - 1)] if ran else 0),
        "executed_pct": pct(executed, ran),
        "invariants_passed_pct": pct(
            [p for p in executed if p.invariants_passed], executed),
        "grounded_pct": pct([p for p in grounded if p.grounded], grounded),
        "mean_assurance_coverage_pct": round(
            sum(p.coverage_pct for p in with_assurance) / len(with_assurance),
            1) if with_assurance else 0.0,
        "records_scored": len([p for p in ran
                               if p.assurance_score is not None]),
        "records_unverified": len([p for p in ran
                                   if p.assurance_status == "UNVERIFIED"]),
        "records_failed": len([p for p in ran
                               if p.assurance_status == "FAILED"]),
        "critical_failures": sum(len(p.critical_failures) for p in ran),
        "critical_not_available": sum(len(p.critical_not_available)
                                      for p in ran),
        "mandatory_unresolved": sum(len(p.mandatory_unresolved) for p in ran),
    }


# ------------------------------------------------------------- the report


def render(data: dict[str, Any], *, title: str) -> str:
    """A markdown report. Deliberately plain: this is evidence, not a
    brochure."""
    m = data["metrics"]
    lines: list[str] = [
        f"# {title}", "",
        f"Generated {data['generated_at']} · {data['duration_s']}s · "
        f"{m['probes']} probes",
        "",
        "**No provider call was made.** Every probe runs inside "
        "`assert_no_provider_calls`, which makes any attempt to reach a model "
        "raise. This is structural, not a promise.",
        "",
        "## Headline metrics", "",
        "| Metric | Value |", "| --- | --- |",
    ]
    for key, label in (
        ("completed", "Probes completed"),
        ("errors", "Probes that raised"),
        ("officer_accuracy_pct", "Officer selection accuracy %"),
        ("officer_scored", "…of which scored"),
        ("outcome_accuracy_pct", "Outcome accuracy % (answer/clarify/refuse)"),
        ("unnecessary_specialists", "Unnecessary specialists (total)"),
        ("missed_specialists", "Missed specialists (total)"),
        ("mean_specialists", "Mean specialists per request"),
        ("mean_tasks", "Mean tasks per request"),
        ("mean_model_calls", "Mean model-call estimate per request"),
        ("mean_latency_ms", "Mean latency (ms)"),
        ("p95_latency_ms", "p95 latency (ms)"),
        ("executed_pct", "Requests that executed an analysis %"),
        ("invariants_passed_pct", "Invariants passed % (of executed)"),
        ("grounded_pct", "Grounded % (where grounding ran)"),
        ("mean_assurance_coverage_pct", "Mean assurance coverage %"),
        ("records_scored", "Records that received a score"),
        ("records_unverified", "Records UNVERIFIED"),
        ("records_failed", "Records FAILED"),
        ("critical_failures", "Critical failures"),
        ("critical_not_available", "Critical checks with no signal"),
        ("mandatory_unresolved", "Mandatory checks unresolved"),
    ):
        value = m.get(key)
        lines.append(f"| {label} | {'—' if value is None else value} |")

    lines += ["", "## Officer selection, per request", "",
              "| # | Request | Flow | Officer | Expected | Specialists | "
              "Tasks | Datasets | Executed | Status | Coverage |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
              "--- |"]
    for probe in data["probes"]:
        officer = probe["officer"]
        expected = probe["expected"]["officer"]
        lines.append(
            f"| {probe['label'].split(' — ')[0]} "
            f"| {probe['question'][:44]} "
            f"| {probe['assurance']['flow']} "
            f"| {officer['level']} {officer['title']} "
            f"| {expected if expected is not None else '—'} "
            f"| {len(probe['specialists'])} "
            f"| {probe['task_count']} "
            f"| {len(probe['datasets'])} "
            f"| {'yes' if probe['execution']['executed'] else 'no'} "
            f"| {probe['assurance']['status'] or probe['status']} "
            f"| {probe['assurance']['coverage_pct']}% |")

    div = data["divergence"]
    lines += ["", "## Is the officer badge real? (§3)", "",
              f"Verdict: **{div['verdict']}** — {div['material']} material, "
              f"{div['decorative']} decorative, monotonic: "
              f"{div['monotonic']}", "",
              "| Lower | Higher | Verdict | What actually differed |",
              "| --- | --- | --- | --- |"]
    for comparison in div["comparisons"]:
        differed = ", ".join(comparison["expensive_differences"])
        lines.append(
            f"| L{comparison['lower']['officer_level']} "
            f"{comparison['lower']['label'][:26]} "
            f"| L{comparison['higher']['officer_level']} "
            f"{comparison['higher']['label'][:26]} "
            f"| {comparison['verdict']} "
            f"| {differed or 'nothing expensive'} |")

    cov = data["coverage_map"]
    lines += ["", "## Assurance coverage map (§19)", "",
              f"{cov['mapped']} of {cov['subcomponents']} subcomponents "
              f"mapped · {cov['wired']} wired ({cov['wired_pct']}%) · "
              f"{cov['planned']} planned · {cov['out_of_band']} out of band",
              "",
              f"Critical: {cov['critical_wired']} of {cov['critical']} wired "
              f"({cov['critical_pct']}%)",
              "",
              "| Dimension | Subcomponents | Wired | Planned | Out of band | "
              "Critical wired |",
              "| --- | --- | --- | --- | --- | --- |"]
    for row in cov["by_dimension"]:
        lines.append(
            f"| {row['label']} | {row['subcomponents']} | {row['wired']} "
            f"| {row['planned']} | {row['out_of_band']} "
            f"| {row['critical_wired']}/{row['critical']} |")

    lines += ["", "## Coverage by flow class (§21)", "",
              "| Flow | Probes | Applicable | Critical applicable | "
              "Mean coverage | Statuses | Scored |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in data["flows"]:
        lines.append(
            f"| {row['label']} | {row['probes']} | {row['applicable']} "
            f"| {row['critical_applicable']} | {row['mean_coverage_pct']}% "
            f"| {', '.join(row['statuses']) or '—'} | {row['scored']} |")

    errors = [p for p in data["probes"] if not p["ok"]]
    if errors:
        lines += ["", "## Probes that raised", ""]
        for probe in errors:
            lines.append(f"- **{probe['label']}** — `{probe['error']}`")

    lines += ["", "---", "",
              "Every number above is measured from what the run persisted. "
              "Nothing is inferred from the question's wording.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/BASELINE_AGENTIC.md")
    parser.add_argument("--json", default="")
    parser.add_argument("--title", default="Agentic baseline")
    args = parser.parse_args(argv)

    data = collect()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, title=args.title), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=2, default=str),
                                   encoding="utf-8")
    m = data["metrics"]
    print(f"{m['completed']}/{m['probes']} probes completed, "
          f"{m['errors']} raised. Mean coverage "
          f"{m['mean_assurance_coverage_pct']}%. "
          f"Divergence: {data['divergence']['verdict']}. Wrote {out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
