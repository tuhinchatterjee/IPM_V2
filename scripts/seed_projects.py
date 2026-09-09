#!/usr/bin/env python
"""Twenty-four Projects with threads somebody could have had. Part 4.

    python scripts/seed_projects.py            seed what is missing
    python scripts/seed_projects.py --check    report only; change nothing
    python scripts/seed_projects.py --force    rebuild the seeded set
    python scripts/seed_projects.py --json     machine-readable result

The defect this exists to fix
-----------------------------
The Projects list held 3,311 rows with SIX distinct names between them, 2,973
of them one repeated test fixture called "Contracting concentration review".
Alongside them sat 5,985 Investigations, 868 with no message at all. The
product's own `demo.workspace.residue()` check names every one of these as a
FAIL, and it was failing.

The rows came from `tests/api/test_hierarchy_api.py`, whose Project fixture is
function-scoped and cleaned up nothing, so every suite run left another few
dozen. That leak is closed separately, at the fixture. This builds what should
be there instead.

What a real thread is here
--------------------------
Each Project carries two threads. Each thread opens with a question a credit
officer would actually type, and the answer is a REAL run of a registered
analysis against the governed book — the assistant message carries the whole
run, and its text states only what that run computed. Nothing is written for
effect: if the analysis does not run, the thread is not created and the
failure is reported.

That constraint is the point. A seeded workspace whose conversations were
composed rather than computed teaches a reader to distrust the ones that were
not, and there is no way to tell them apart by looking.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: How a seeded Project identifies itself, so a rebuild replaces its own work
#: and nothing else. Carried in `default_context`, which is a governed field
#: rather than a note somebody might edit.
SEED_KEY = "seeded_by"
SEED_VALUE = "SYNTHETIC_DEMO part-4"

#: Twenty-four standing reviews, each with the threads it would carry.
#:
#: Named for the credit question they exist to answer, not for the
#: demonstration. "Demo Project" on a screen tells a client the product has
#: never been used for anything.
PROJECTS: tuple[dict[str, Any], ...] = (
    {"name": "Contracting sector review",
     "about": "Whether the Contracting book needs an action plan after Q2.",
     "threads": [("Where is exposure concentrated at Q2 2026?",
                  "sector_concentration", {}),
                 ("How is the book distributed across IFRS 9 stages?",
                  "stage_distribution", {})]},
    {"name": "IFRS 9 staging review",
     "about": "Stage migration and the SICR triggers behind it.",
     "threads": [("What moved between stages this quarter?",
                  "stage_migration", {}),
                 ("Which SICR triggers are firing?",
                  "sicr_trigger_breakdown", {})]},
    {"name": "ECL movement and attribution",
     "about": "What moved the impairment charge, and how much each driver did.",
     "threads": [("What drove the ECL movement this quarter?",
                  "ecl_movement", {}),
                 ("Decompose the ECL change into its drivers.",
                  "ecl_change_decomposition", {})]},
    {"name": "Approaching SICR watch",
     "about": "Borrowers close to a stage 2 trigger but not yet through it.",
     "threads": [("Who is approaching the SICR threshold?",
                  "approaching_sicr_threshold", {}),
                 ("How is ECL coverage split by stage?",
                  "ecl_coverage_by_stage", {})]},
    {"name": "Arrears and days past due",
     "about": "The arrears position and how the DPD buckets are moving.",
     "threads": [("What is the arrears position at Q2 2026?",
                  "arrears_position", {}),
                 ("How did the DPD buckets migrate?", "dpd_migration", {})]},
    {"name": "Obligor concentration limits",
     "about": "Single-name concentration against the appetite limits.",
     "threads": [("Which obligors carry the largest exposures?",
                  "obligor_concentration", {}),
                 ("Where is exposure concentrated by sector?",
                  "sector_concentration", {})]},
    {"name": "Connected group exposure",
     "about": "Exposure aggregated to the group rather than the borrower.",
     "threads": [("What is our exposure by connected group?",
                  "connected_group_exposure", {}),
                 ("Show the ownership and control structure.",
                  "ownership_and_control_structure", {})]},
    {"name": "Collateral coverage review",
     "about": "How much of the book is secured, and how well.",
     "threads": [("What is collateral coverage across the book?",
                  "collateral_coverage", {}),
                 ("How does ECL coverage look by stage?",
                  "ecl_coverage_by_stage", {})]},
    {"name": "Rating migration review",
     "about": "Internal grade movement and the actions behind it.",
     "threads": [("How did internal ratings migrate?",
                  "rating_transition_matrix", {}),
                 ("What rating actions were taken?", "rating_actions", {})]},
    {"name": "Rating distribution and calibration",
     "about": "Where the book sits on the masterscale.",
     "threads": [("How is the book distributed by rating grade?",
                  "rating_grade_distribution", {}),
                 ("What is the portfolio position at Q2 2026?",
                  "portfolio_summary", {})]},
    {"name": "Deteriorating borrowers",
     "about": "The names moving the wrong way fastest.",
     "threads": [("Which borrowers deteriorated most this quarter?",
                  "top_deteriorating_borrowers", {}),
                 ("What moved on the watchlist?", "watchlist_movement", {})]},
    {"name": "Utilisation and limit management",
     "about": "Drawn against limit, and where it is drifting.",
     "threads": [("How is facility utilisation drifting?",
                  "utilisation_drift", {}),
                 ("Who is utilised above the watch threshold?",
                  "high_utilisation_watchlist", {})]},
    {"name": "Downturn stress review",
     "about": "What a management downturn scenario does to impairment.",
     "threads": [("What happens to ECL under a moderate downturn?",
                  "stress_scenario_basic", {"scenario": "moderate"}),
                 ("And under a severe downturn?",
                  "stress_scenario_basic", {"scenario": "severe"})]},
    {"name": "Portfolio trend review",
     "about": "How the book has moved across the reporting quarters.",
     "threads": [("How has the portfolio moved over recent quarters?",
                  "portfolio_trend", {}),
                 ("Where does the book stand now?", "portfolio_summary", {})]},
    {"name": "Macroeconomic context",
     "about": "The macro backdrop the forward-looking view rests on.",
     "threads": [("What does the macroeconomic context look like?",
                  "macroeconomic_context", {}),
                 ("How has the portfolio moved against it?",
                  "portfolio_trend", {})]},
    {"name": "Network and contagion risk",
     "about": "Which names carry risk through the relationship graph.",
     "threads": [("Which borrowers rank highest on network risk?",
                  "network_risk_ranking", {}),
                 ("What is the exposure by connected group?",
                  "connected_group_exposure", {})]},
    {"name": "Relationship graph quality",
     "about": "Whether the graph the network analytics rest on is sound.",
     "threads": [("What is the quality of the relationship graph?",
                  "graph_data_quality", {}),
                 ("Show the ownership and control structure.",
                  "ownership_and_control_structure", {})]},
    {"name": "Credit file review",
     "about": "What the credit files themselves are signalling.",
     "threads": [("What signals are the credit files showing?",
                  "credit_file_signals", {}),
                 ("Who is approaching a SICR trigger?",
                  "approaching_sicr_threshold", {})]},
    {"name": "Stage 3 and default review",
     "about": "The defaulted book and what is feeding it.",
     "threads": [("How is the book distributed across stages?",
                  "stage_distribution", {}),
                 ("What is the arrears position?", "arrears_position", {})]},
    {"name": "Quarterly committee pack",
     "about": "The standing figures the credit committee opens with.",
     "threads": [("What is the portfolio position at Q2 2026?",
                  "portfolio_summary", {}),
                 ("What drove the ECL movement?", "ecl_movement", {})]},
    {"name": "Sector appetite review",
     "about": "Whether sector exposure sits within appetite.",
     "threads": [("How is exposure concentrated by sector?",
                  "sector_concentration", {}),
                 ("Which obligors are largest?", "obligor_concentration", {})]},
    {"name": "Watchlist governance",
     "about": "What entered and left the watchlist, and why.",
     "threads": [("What moved on the watchlist this quarter?",
                  "watchlist_movement", {}),
                 ("Which borrowers deteriorated most?",
                  "top_deteriorating_borrowers", {})]},
    {"name": "Stage migration flow",
     "about": "The flow between stages, not just the closing distribution.",
     "threads": [("Show the flow between IFRS 9 stages.",
                  "stage_migration_flow", {}),
                 ("What moved between stages?", "stage_migration", {})]},
    {"name": "Early warning follow-up",
     "about": "Following the early-warning signal into the exposures behind it.",
     "threads": [("Which borrowers deteriorated most this quarter?",
                  "top_deteriorating_borrowers", {}),
                 ("How is utilisation drifting?", "utilisation_drift", {})]},
)

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_CANNOT_RUN = 2


@dataclass
class Built:
    name: str
    project_id: int | None = None
    threads: int = 0
    failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "project_id": self.project_id,
                "threads": self.threads, "failed": self.failed}


@dataclass
class Report:
    built: list[Built] = field(default_factory=list)
    removed: int = 0
    error: str = ""

    @property
    def threads(self) -> int:
        return sum(b.threads for b in self.built)

    @property
    def failures(self) -> list[str]:
        return [f"{b.name}: {one}" for b in self.built for one in b.failed]

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.error, "projects": len(self.built),
                "threads": self.threads, "replaced": self.removed,
                "failures": self.failures,
                "detail": [b.to_dict() for b in self.built]}


def _states(result: Any) -> str:
    """One sentence, composed only of what the run actually computed.

    Not a summary written in advance and attached to whatever came back. Every
    number here was produced by the analysis being described, which is why the
    wording is plain: an answer that reads better than its evidence is the
    thing this whole seed exists not to do.
    """
    payload = result.to_dict()
    values = payload.get("values") or {}
    rows = payload.get("rows") or []
    said = values.get("statement")
    if isinstance(said, str) and said.strip():
        return said.strip()
    parts: list[str] = []
    if rows:
        parts.append(f"{len(rows)} row(s) returned")
    period = values.get("period")
    if period:
        parts.append(f"for {period}")
    read = payload.get("input_row_count")
    if isinstance(read, int) and read:
        parts.append(f"from {read:,} input row(s)")
    return ("The analysis returned " + ", ".join(parts) + "."
            if parts else "The analysis ran and returned no rows.")


def _seeded_projects() -> list[int]:
    from backend.db.engine import get_session
    from backend.models.platform import Project

    with get_session() as session:
        return [p.id for p in session.query(Project).all()
                if (p.default_context or {}).get(SEED_KEY) == SEED_VALUE]


def _remove(project_ids: list[int]) -> int:
    from backend.db.engine import get_session
    from backend.models.platform import (
        Investigation,
        InvestigationMessage,
        Project,
        SavedAnalysis,
    )

    if not project_ids:
        return 0
    with get_session() as session:
        threads = [t.id for t in session.query(Investigation.id).filter(
            Investigation.project_id.in_(project_ids)).all()]
        if threads:
            session.query(InvestigationMessage).filter(
                InvestigationMessage.investigation_id.in_(threads)
            ).delete(synchronize_session=False)
            session.query(SavedAnalysis).filter(
                SavedAnalysis.investigation_id.in_(threads)
            ).delete(synchronize_session=False)
            session.query(Investigation).filter(
                Investigation.id.in_(threads)).delete(synchronize_session=False)
        session.query(SavedAnalysis).filter(
            SavedAnalysis.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        gone = session.query(Project).filter(
            Project.id.in_(project_ids)).delete(synchronize_session=False)
        session.commit()
        return int(gone or 0)


def run(*, check: bool = False, force: bool = False) -> Report:
    report = Report()
    try:
        from backend.config import settings
    except Exception as e:  # noqa: BLE001
        report.error = f"Configuration could not be read: {e}"
        return report
    if not settings.has_database:
        report.error = "No database is configured, so nothing can be seeded."
        return report

    existing = _seeded_projects()
    if check:
        for spec in PROJECTS:
            report.built.append(Built(name=spec["name"]))
        report.removed = len(existing)
        return report
    if existing and not force:
        for spec in PROJECTS:
            report.built.append(Built(name=spec["name"]))
        return report

    report.removed = _remove(existing)

    from backend.engine.runner import run_analysis
    from backend.services import projects as project_svc
    from backend.services import threads as thread_svc

    for spec in PROJECTS:
        entry = Built(name=spec["name"])
        report.built.append(entry)
        view = project_svc.create(
            name=spec["name"], description=spec["about"],
            instructions=("Answer for the corporate book at the latest closed "
                          "quarter unless a question says otherwise."))
        entry.project_id = getattr(view, "id", None)

        from backend.db.engine import get_session
        from backend.models.platform import Project

        with get_session() as session:
            row = session.get(Project, entry.project_id)
            if row is not None:
                row.default_context = {**dict(row.default_context or {}),
                                       SEED_KEY: SEED_VALUE}
                session.commit()

        for question, analysis_id, params in spec["threads"]:
            try:
                found = run_analysis(analysis_id, params=params,
                                     period="latest")
            except Exception as e:  # noqa: BLE001
                entry.failed.append(f"{analysis_id}: {type(e).__name__}: {e}")
                continue
            if found.status != "succeeded" or found.result is None:
                entry.failed.append(
                    f"{analysis_id}: {found.error or 'no result'}")
                continue

            thread = thread_svc.create(question=question,
                                       project_id=entry.project_id)
            thread_svc.append(
                thread.id, role="assistant",
                content=_states(found.result),
                payload={"analysis_id": analysis_id,
                         "certification": found.certification,
                         "params": dict(found.params or {}),
                         "result": found.result.to_dict(),
                         "origin": SEED_VALUE})
            entry.threads += 1

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run(check=args.check, force=args.force)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.error:
            print(f"! {report.error}")
        if report.removed:
            print(f"  replaced {report.removed} previously seeded Project(s)")
        for one in report.built:
            print(f"  {one.name:36s} {one.threads} thread(s)"
                  + (f"  FAILED: {'; '.join(one.failed)[:80]}"
                     if one.failed else ""))
        print(f"\n{len(report.built)} project(s), {report.threads} thread(s), "
              f"{len(report.failures)} failure(s).")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_OK if not report.failures else EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
