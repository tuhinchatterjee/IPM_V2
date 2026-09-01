"""Build the demonstration workspace. §12.

    "Every object must deep-link correctly. No stale or contradictory seeded
     state."

Every object here is REAL. The analyses are executed by the deterministic
engine through `run_analysis`, persisted through `persist_run`, and carry
their own Trace. The Risk Cases come from the actual new-period review, whose
first six steps are DuckDB aggregates over Parquet with no model in them at
all. The workflow item goes through `workflow.send`, so it has the events, the
recipients and the notifications a real one has.

Nothing is fabricated, and that is not fastidiousness. A seeded Risk Case
whose evidence was written by a seeding script is a case whose Investigate
button leads somewhere that disagrees with it, and the first person to click
it in front of a client finds out.

What this refuses to do
-----------------------
It makes no provider call. The demonstration's opening questions are asked
live, by the presenter, against their own key; pre-answering them here would
be exactly the "preload model answers" §26 forbids.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.demo import workspace as ws

logger = logging.getLogger(__name__)

#: The Project a presenter opens. One, named for what it is about rather than
#: for the demonstration, because "Demo Project" on screen tells a client the
#: product has never been used for anything.
PROJECT = {
    "name": "Contracting sector deep dive",
    "description": (
        'Standing review of the Contracting book after the Q2 2026 close. '
        'synthetic data.'),
    "instructions": (
        "Work at segment grain unless a question names a customer. Compare "
        "against Q1 2026 and flag anything that moved more than the book."),
}

#: The saved Analyses. Each is a registered, certified analysis run by the
#: deterministic engine — an id, the period, and the title a reader sees.
ANALYSES: tuple[tuple[str, str], ...] = (
    ("portfolio_summary", "Portfolio position at Q2 2026"),
    ("sector_concentration", "Exposure concentration by sector"),
    ("stage_distribution", "IFRS 9 stage distribution"),
)

#: The two Investigations §12 requires, one of each kind. The questions are
#: real questions, and the demonstration's own script asks different ones —
#: these exist so the screens are not empty before the presenter types
#: anything.
GLOBAL_INVESTIGATION = {
    "title": "Where is exposure concentrated at Q2 2026?",
    "question": "Where is exposure concentrated at Q2 2026?",
}
PROJECT_INVESTIGATION = {
    "title": "What moved in Contracting since Q1 2026?",
    "question": "What moved in Contracting since Q1 2026?",
}


def _context() -> dict[str, Any]:
    """The marker every seeded object carries, and the pinned period."""
    from backend.demo import mode

    return {
        "source": ws.MARK,
        "period": ws.PERIOD,
        "prior_period": ws.PRIOR_PERIOD,
        "data_release": mode.DATA_RELEASE,
        "synthetic": True,
    }


def _users(session: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from backend.db.models import User

    rows = session.execute(select(User)).scalars().all()
    return {u.username: u for u in rows}


def build(session: Any, *, run_review: bool = True) -> ws.Result:
    """Create the whole demonstration workspace.

    Idempotent in the only sense that matters here: it is meant to run on a
    workspace that has just been reset. Run against a populated one it will
    add a second Project, which is why `demo-reset.ps1` resets first.
    """
    result = ws.Result(action="seed")
    people = _users(session)
    if "alex.rahman" not in people:
        result.error = ("The sign-in accounts are missing. Run "
                        "scripts/seed_demo_users.py first.")
        return result

    admin = people["alex.rahman"]
    analyst = people.get("omar.nasser", admin)

    project_id = _project(session, admin, result)
    # Committed before the analyses run. `persist_run` opens its OWN session,
    # so an uncommitted Project is invisible to it and every run is refused by
    # the foreign key — which is what happened the first time this ran.
    session.commit()
    runs = _analyses(session, admin, project_id, result)
    global_id = _investigation(session, admin, None, GLOBAL_INVESTIGATION,
                               published=True)
    project_thread = _investigation(session, admin, project_id,
                                    PROJECT_INVESTIGATION, published=False)
    result.created["investigations"] = 2
    session.flush()

    _saved(session, admin, project_id, project_thread, runs, result)
    session.commit()

    if run_review:
        _review(session, result)

    _workflow(session, admin, analyst, project_id, result)
    _lens(session, admin, result)
    session.commit()

    result.notes.append(
        f"Global Investigation #{global_id} is published globally; "
        f"Project Investigation #{project_thread} is Project-only and must "
        "stay that way until somebody publishes it.")
    return result


def _project(session: Any, owner: Any, result: ws.Result) -> int:
    from backend.models.platform import Project, ProjectStatusEvent

    row = Project(
        name=PROJECT["name"],
        description=PROJECT["description"],
        instructions=PROJECT["instructions"],
        status="active",
        created_by=owner.id,
        default_context=_context(),
    )
    session.add(row)
    session.flush()
    session.add(ProjectStatusEvent(
        project_id=row.id, from_status="draft", to_status="active",
        actor_id=owner.id, note="Opened for the Q2 2026 review."))
    result.created["projects"] = 1
    return int(row.id)


def _investigation(session: Any, owner: Any, project_id: int | None,
                   spec: dict[str, str], *, published: bool) -> int:
    from datetime import UTC, datetime

    from backend.models.platform import Investigation

    row = Investigation(
        project_id=project_id,
        title=spec["title"],
        question=spec["question"],
        scope={"period": ws.PERIOD},
        plan={},
        context=_context(),
        status="live",
        owner_id=owner.id,
        published_globally=published,
        published_at=datetime.now(UTC) if published else None,
        published_by=owner.id if published else None,
        # Zero, not one. These are conversation THREADS; neither has a stored
        # answer yet, because the presenter asks the questions live.
        #
        # The first version of this seed claimed version 1, and
        # `investigations.load()` correctly refuses an Investigation that
        # claims a version it has no stored answer for - so the object listed
        # happily in /investigations and its saved view returned 404. An
        # object that appears in a list and 404s on its own detail route is
        # exactly the broken deep link the route crawl exists to find, and it
        # found this one.
        current_version=0,
        message_count=0,
    )
    session.add(row)
    session.flush()
    return int(row.id)


def _analyses(session: Any, owner: Any, project_id: int,
              result: ws.Result) -> list[tuple[str, str, int]]:
    """Execute each demo analysis for real and persist its run.

    A failure here is recorded and the seed continues: one analysis that
    cannot run on this data is worth knowing about, and is not a reason to
    leave the presenter with no workspace at all.
    """
    from backend.engine.runner import persist_run, run_analysis

    made: list[tuple[str, str, int]] = []
    for analysis_id, title in ANALYSES:
        try:
            run = run_analysis(analysis_id, params={}, period=ws.PERIOD,
                               filters={}, user_id=owner.id)
            if run.status == "failed":
                why = run.error or "no reason given"
                result.notes.append(f"{analysis_id} did not run: {why}")
                continue
            run_id = persist_run(run, project_id=project_id,
                                 investigation_id=None, user_id=owner.id)
            made.append((analysis_id, title, int(run_id)))
        except Exception as e:  # noqa: BLE001 - one bad analysis is not fatal
            result.notes.append(f"{analysis_id} raised: {type(e).__name__}: "
                                f"{str(e)[:160]}")
    result.created["analysis_runs"] = len(made)
    return made


def _saved(session: Any, owner: Any, project_id: int, investigation_id: int,
           runs: list[tuple[str, str, int]], result: ws.Result) -> None:
    from backend.models.platform import AnalysisRun, SavedAnalysis

    saved = 0
    for analysis_id, title, run_id in runs:
        run_row = session.get(AnalysisRun, run_id)
        if run_row is None:
            continue
        session.add(SavedAnalysis(
            title=title,
            analysis_id=analysis_id,
            analysis_version=getattr(run_row, "analysis_version", "") or "1.0.0",
            certification=getattr(run_row, "certification", "") or "certified",
            analysis_run_id=run_id,
            investigation_id=investigation_id,
            project_id=project_id,
            params={}, filters={},
            period={"label": ws.PERIOD},
            result={}, data_versions={},
            note="Saved during the Q2 2026 review.",
            owner_id=owner.id,
        ))
        saved += 1
    result.created["saved_analyses"] = saved


def _review(session: Any, result: ws.Result) -> None:
    """Run the real new-period review, which is what creates Risk Cases.

    Steps 2 to 6 are deterministic aggregates. Step 7 would enrich a material
    finding through the governed runtime, and with no provider configured it
    simply does not enrich — which is the correct behaviour and is why this
    can run here at all.
    """
    from backend.agentic import review

    try:
        _, found = review.run(session, period=ws.PERIOD,
                              prior_period=ws.PRIOR_PERIOD)
        session.commit()
        result.created["risk_cases"] = int(getattr(found, "case_count", 0) or 0)
        result.notes.append(
            f"The Q2 2026 review created {result.created['risk_cases']} Risk "
            "Case(s) from the deterministic screen. Which classes appear "
            "depends on what actually moved in the data; none is fabricated "
            "to fill a filter.")
    except Exception as e:  # noqa: BLE001
        session.rollback()
        result.notes.append(f"The new-period review did not run: "
                            f"{type(e).__name__}: {str(e)[:200]}")


def _workflow(session: Any, sender: Any, reviewer: Any, project_id: int,
              result: ws.Result) -> None:
    from backend.services import workflow as wf

    try:
        wf.send(
            object_type="project",
            object_id=str(project_id),
            title=PROJECT["name"],
            action="review",
            message=("Q2 2026 close is done. Please review the Contracting "
                     "position before it goes to the committee."),
            priority="normal",
            requested_by=sender.id,
            recipients=[reviewer.id],
        )
        result.created["workflow_items"] = 1
    except Exception as e:  # noqa: BLE001
        result.notes.append(f"The workflow item was not created: "
                            f"{type(e).__name__}: {str(e)[:200]}")


LENS_SLUG = "q2-2026-portfolio-position"


def _lens(session: Any, owner: Any, result: ws.Result) -> None:
    """One Lens, so the Lenses screen is not empty after a reset.

    Checked before it is added. The `try` below cannot catch a duplicate
    slug: the unique constraint fires at flush, not at `session.add`, so a
    second `--force` run of the bootstrap raised an IntegrityError out of the
    commit and failed a step whose whole contract is that running it twice is
    safe.
    """
    from sqlalchemy import select

    from backend.models.platform import Lens

    existing = session.execute(
        select(Lens).where(Lens.slug == LENS_SLUG)).scalar_one_or_none()
    if existing is not None:
        result.notes.append("The starter Lens was already present.")
        return

    try:
        session.add(Lens(
            slug=LENS_SLUG,
            name="Q2 2026 portfolio position",
            description=("Position, stage distribution and sector "
                         "concentration at the Q2 2026 close."),
            audience="Credit Risk Committee",
            # Panels live inside `definition`, which is the shape
            # backend/services/lenses.py reads. A Lens built any other way
            # renders as an empty dashboard.
            definition={"panels": [
                {"title": "Position", "analysis_id": "portfolio_summary",
                 "params": {}, "visualization": "table", "note": ""},
                {"title": "Stage distribution",
                 "analysis_id": "stage_distribution",
                 "params": {}, "visualization": "bar", "note": ""},
                {"title": "Sector concentration",
                 "analysis_id": "sector_concentration",
                 "params": {}, "visualization": "bar", "note": ""},
            ]},
            status="published",
            version=1,
            origin="demo",
            owner_id=owner.id,
        ))
        result.created["lenses"] = 1
    except Exception as e:  # noqa: BLE001
        result.notes.append(f"The starter Lens was not created: "
                            f"{type(e).__name__}: {str(e)[:200]}")
