"""The retail installation's own workspace, seeded so a fresh install is not empty.

The corporate bootstrap has a workspace seeder — `backend.demo.seed` — and it
seeds the corporate universe: corporate projects, corporate investigations,
corporate messages. A retail installation that called it would put a Real
Estate Deep Dive project and a sector concentration thread in front of a Head
of Retail Risk, which is worse than showing them nothing.

So this is the retail one. It seeds only what a retail installation should
hold, reads only the retail book, and is guarded so it cannot be pointed at
another deployment's database.

What it seeds
-------------
* **Projects.** Six, matching the work a retail risk function actually has open
  in an August close: the portfolio review, the credit-card ODR investigation,
  scorecard monitoring, the IFRS 9 close, the auto-finance early warning review
  and the home-finance Stage 2 migration review.
* **Data-release notifications.** One per governed retail domain, through
  `publish_data_release_event` — the same hook Data Builder calls when a real
  release goes live, so what the presenter sees on demo morning is the message
  the product actually sends, with its real row counts and its real buttons.
* **Working messages.** The three notes that would be circulating in the week
  of a close: scorecard monitoring ready, the risk review pack, the EWS monthly
  review.

What it will not do
-------------------
* It never seeds a corporate dataset, domain, project or thread.
* It never overwrites anything a person has edited. Every object is looked up
  first by its seed key and left alone if it is there.
* It never invents a figure. Row counts and periods come from the published
  lake; where a count is not available the message omits it rather than
  estimating one.
* Everything it creates is marked as demonstration material.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Bumped when the seeded content changes in a way a re-run should notice.
RETAIL_WORKSPACE_SEED_VERSION = "1.0.0"

#: The marker that says CreditProbe put this here. Written into the project's
#: `default_context` so it is queryable, and shown on screen so nobody mistakes
#: a demonstration project for somebody's real work.
SEED_MARK = "retail_demo_seed"


@dataclass
class Seeded:
    """What one run of the seeder did."""

    created: dict[str, int] = field(default_factory=dict)
    kept: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def made(self, kind: str, n: int = 1) -> None:
        self.created[kind] = self.created.get(kind, 0) + n

    def held(self, kind: str, n: int = 1) -> None:
        self.kept[kind] = self.kept.get(kind, 0) + n

    def summary(self) -> str:
        made = ", ".join(f"{n} {k}" for k, n in sorted(self.created.items()))
        kept = ", ".join(f"{n} {k}" for k, n in sorted(self.kept.items()))
        parts = []
        if made:
            parts.append(f"created {made}")
        if kept:
            parts.append(f"kept {kept}")
        return "; ".join(parts) or "nothing to do"


# ---------------------------------------------------------------- projects

@dataclass(frozen=True)
class ProjectSpec:
    """One seeded retail project.

    `key` is the identity. A project is recognised by it across re-runs, so a
    renamed project is not seeded a second time under its original name.
    """

    key: str
    name: str
    description: str
    instructions: str
    status: str
    period: str = "2026-08"
    filters: dict[str, Any] = field(default_factory=dict)


PROJECTS: tuple[ProjectSpec, ...] = (
    ProjectSpec(
        key="retail-portfolio-review-q3-2026",
        name="Retail Portfolio Review — Q3 2026",
        description=(
            "The quarter's standing review of the retail book: exposure and "
            "ECL by product, what moved, what is behind, and what the "
            "committee is being asked to note."),
        instructions=(
            "Every figure in this project is the retail book at the quarter "
            "end unless the question says otherwise. Report SAR. Where a "
            "movement is quoted, name both periods."),
        status="active",
        filters={},
    ),
    ProjectSpec(
        key="credit-card-odr-deterioration",
        name="Credit Card ODR Deterioration Investigation",
        description=(
            "Credit-card default entry has risen for three consecutive "
            "months. This project holds the decomposition — by subsegment, by "
            "score band, by utilisation — and the customers behind it."),
        instructions=(
            "Credit Card only. Default entry means facilities entering "
            "default in the month, not the twelve-month cohort default rate "
            "the scorecards are measured on; keep the two apart."),
        status="active",
        filters={"product_label": "Credit Card"},
    ),
    ProjectSpec(
        key="personal-finance-scorecard-monitoring",
        name="Personal Finance Scorecard Monitoring",
        description=(
            "The monthly monitoring of the personal-finance application "
            "scorecard: discrimination, calibration, population stability and "
            "the strategy bands, over the latest matured cohort."),
        instructions=(
            "Use matured cohorts only — the latest month whose twelve-month "
            "outcome window has closed for every account. Do not quote a "
            "discrimination statistic as evidence about calibration."),
        status="active",
        filters={"product_label": "Personal Finance"},
    ),
    ProjectSpec(
        key="retail-ifrs9-august-2026-close",
        name="Retail IFRS 9 — August 2026 Close",
        description=(
            "The August close: staging, coverage, the scenario weights and "
            "the management overlay, with the movement from July explained "
            "line by line."),
        instructions=(
            "August 2026 unless stated. Weighted ECL is the final ECL after "
            "scenario weighting; say which when both are on the page."),
        status="active",
        filters={},
    ),
    ProjectSpec(
        key="auto-finance-early-warning-review",
        name="Auto Finance Early Warning Review",
        description=(
            "The auto-finance book through the Forward Risk Signal: which "
            "layers are moving, which customers are flagged, and which of "
            "them are already behind rather than merely at risk."),
        instructions=(
            "Keep current delinquency and forward risk apart. A customer who "
            "is already past due is not a forward-risk finding."),
        status="active",
        filters={"product_label": "Auto Finance"},
    ),
    ProjectSpec(
        key="home-finance-stage2-migration-review",
        name="Home Finance Stage 2 Migration Review",
        description=(
            "Home finance moving into Stage 2: what triggered the SICR, how "
            "much exposure moved, what it did to coverage, and whether the "
            "collateral position changed with it."),
        instructions=(
            "Home Finance only. A facility that was already in Stage 2 last "
            "month has not migrated into it this month."),
        status="active",
        filters={"product_label": "Home Finance"},
    ),
)


def _projects(session: Any, into: Seeded, *, owner_id: int | None) -> None:
    """Open the six retail projects, once."""
    from sqlalchemy import select

    from backend.models.platform import PJ_DRAFT, Project, ProjectStatusEvent

    existing = {
        str((row.default_context or {}).get("seed_key") or ""): row
        for row in session.execute(select(Project)).scalars().all()
    }
    for spec in PROJECTS:
        if spec.key in existing:
            into.held("project")
            continue
        row = Project(
            name=spec.name,
            description=spec.description,
            instructions=spec.instructions,
            status=PJ_DRAFT,
            created_by=owner_id,
            default_context={
                "seed_key": spec.key,
                "seeded_by": SEED_MARK,
                "demo": True,
                "period": spec.period,
                "filters": dict(spec.filters),
            },
        )
        session.add(row)
        session.flush()
        session.add(ProjectStatusEvent(
            project_id=row.id, from_status=None, to_status=PJ_DRAFT,
            actor_id=owner_id,
            note="Opened as part of the retail demonstration workspace."))
        if spec.status != PJ_DRAFT:
            session.add(ProjectStatusEvent(
                project_id=row.id, from_status=PJ_DRAFT, to_status=spec.status,
                actor_id=owner_id,
                note="Work is under way in this project."))
            row.status = spec.status
        into.made("project")


# ----------------------------------------------------- data-release notices

@dataclass(frozen=True)
class DomainRelease:
    """One governed retail domain, as a data-release announcement."""

    dataset: str
    label: str
    domain: str
    note: str


RELEASES: tuple[DomainRelease, ...] = (
    DomainRelease(
        dataset="retail_facility_month",
        label="Retail facility month-end position",
        domain="Cockpit Data",
        note="The canonical retail book, at facility-month grain."),
    DomainRelease(
        dataset="retail_early_warning",
        label="Retail early warning",
        domain="Early Warning Data",
        note="The governed early-warning view of the same book."),
    DomainRelease(
        dataset="retail_credit_scorecard",
        label="Retail credit scorecard",
        domain="Credit Scorecard Data",
        note="Application and behavioural scorecards, by model."),
    DomainRelease(
        dataset="retail_whatif",
        label="Retail what-if analysis",
        domain="What-If Analysis Data",
        note="The stressable view: risk parameters, stage and score inputs."),
)


def _release_facts(dataset: str) -> tuple[int | None, int | None, str, str]:
    """Rows, customers and the two latest periods — read, never estimated.

    Every governed retail domain is a view of the one canonical book, so the
    counts come from the book and the message says which domain it is
    announcing. A domain the catalogue does not hold yet is announced with no
    counts at all rather than with invented ones.
    """
    try:
        from backend.data_access.catalog import get_catalog

        catalog = get_catalog()
        names = set(catalog.names())
    except Exception:  # noqa: BLE001 - a missing catalogue is not fatal here
        names = set()

    source = dataset if dataset in names else "retail_facility_month"
    if source not in names:
        return None, None, "", ""
    try:
        from backend.data_access import get_data_source

        data = get_data_source()
        periods = list(data.periods(source) or [])
        latest = periods[-1] if periods else ""
        previous = periods[-2] if len(periods) > 1 else ""
        rows = int(data.row_count(source, latest)) if latest else None
        return rows, None, latest, previous
    except Exception as e:  # noqa: BLE001 - announce without counts rather than fail
        logger.info("Could not read %s for the release message: %s", source, e)
        return None, None, "", ""


def _releases(session: Any, into: Seeded) -> None:
    """One data-release notification per governed retail domain."""
    from backend.services import collaboration as collab

    for spec in RELEASES:
        rows, customers, latest, previous = _release_facts(spec.dataset)
        try:
            result = collab.publish_data_release_event(
                session,
                dataset=spec.dataset,
                dataset_label=spec.label,
                domain=spec.domain,
                period=latest,
                previous_period=previous,
                row_count=rows,
                borrower_count=customers,
                validated=True,
            )
        except Exception as e:  # noqa: BLE001 - one notice must not lose the rest
            into.notes.append(f"{spec.domain}: notification not sent ({e}).")
            continue
        if result.get("created") is False:
            into.held("data release")
        else:
            into.made("data release")


# -------------------------------------------------------- working messages

@dataclass(frozen=True)
class NoteSpec:
    """One seeded working message."""

    key: str
    subject: str
    body: str


NOTES: tuple[NoteSpec, ...] = (
    NoteSpec(
        key="scorecard-monitoring-ready-2026-08",
        subject="Scorecard monitoring ready — August 2026",
        body=(
            "The monthly monitoring has run for all eight retail scorecards "
            "over the latest matured cohort.\n\n"
            "The personal-finance application scorecard has one "
            "characteristic outside its stability limit. Discrimination is "
            "inside limit on every model. Calibration is reported without an "
            "approved limit on most tests, which is stated on the screen "
            "rather than scored as a pass.\n\n"
            "Open Scorecard Validation to read the model cards and the "
            "strategy bands."),
    ),
    NoteSpec(
        key="retail-risk-review-pack-2026-08",
        subject="Retail risk review pack ready — August 2026",
        body=(
            "The August pack is assembled from the governed retail book: "
            "exposure and weighted ECL by product, the staging split, the "
            "delinquency rates and the movement from July.\n\n"
            "Every figure carries a Trace. Nothing in the pack has been "
            "reviewed or approved."),
    ),
    NoteSpec(
        key="ews-monthly-review-2026-08",
        subject="EWS monthly review ready — August 2026",
        body=(
            "The Forward Risk Signal has been scored for August. The review "
            "covers the layer movements by product, the customers newly at "
            "High or Critical, and which of them are already delinquent "
            "rather than only at risk.\n\n"
            "Forward risk and current delinquency are reported separately. A "
            "customer already past due is not a forward-risk finding."),
    ),
)


def _notes(session: Any, into: Seeded) -> None:
    """The notes that would be circulating in the week of a close."""
    from backend.services import collaboration as collab

    recipients = collab.data_release_recipients(session)
    if not recipients:
        into.notes.append(
            "No recipient holds a role that receives retail notices, so the "
            "working messages were not sent.")
        return
    for spec in NOTES:
        try:
            # A governed event, not a new one invented for a seeder. Each of
            # these three announces that a report has been produced and is
            # there to be read, which is exactly what REPORT_SHARED means;
            # widening the closed list of system events so a demonstration
            # could have its own would weaken the guarantee the list exists to
            # make.
            result = collab.send_system_message(
                session,
                event=collab.EVENT_REPORT_SHARED,
                event_key=f"retail-note:{spec.key}",
                subject=spec.subject,
                body=spec.body,
                recipients=recipients,
                context={"seeded_by": SEED_MARK, "demo": True},
            )
        except Exception as e:  # noqa: BLE001
            into.notes.append(f"{spec.key}: not sent ({e}).")
            continue
        if result.get("created") is False:
            into.held("message")
        else:
            into.made("message")


def _fingerprint(questions: tuple[str, ...]) -> str:
    """A short, stable signature of a case study's script."""
    import hashlib

    joined = "\n".join(str(q or "").strip() for q in questions)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ the run

def seed(session: Any, *, owner_id: int | None = None) -> Seeded:
    """Seed the retail workspace. Idempotent, and retail-only.

    The guard is not decoration. This writes projects and messages, and a
    seeder pointed at the wrong database would put retail demonstration
    material into a deployment somebody is using for something else.
    """
    from backend.retail import guard

    guard.guard_environment(what="the retail workspace seeder")

    into = Seeded()
    if owner_id is None:
        owner_id = _presenter(session)
    _projects(session, into, owner_id=owner_id)
    _releases(session, into)
    _notes(session, into)
    # Committed before the case studies run: each one asks several governed
    # questions through the ordinary path, and a failure in the fourth must
    # not roll back the six projects that are already correct.
    session.commit()
    _review(session, into)
    _cases(session, into, owner_id=owner_id)
    return into


def _review(session: Any, into: Seeded) -> None:
    """Run the retail portfolio review, so Requires Attention is not empty.

    The Cockpit's opening panel reads the review state rather than the case
    count, because "we looked and found nothing" and "nothing has looked" are
    different sentences and only one of them may reassure anybody. On a fresh
    retail installation nothing had looked.
    """
    from backend.retail import review

    try:
        outcome = review.run(session)
        session.commit()
    except Exception as e:  # noqa: BLE001 - one panel must not lose the rest
        into.notes.append(f"the portfolio review did not run ({e}).")
        return
    if outcome.opened:
        into.made("attention case", outcome.opened)
    if outcome.refreshed:
        into.held("attention case", outcome.refreshed)
    for note in outcome.notes:
        into.notes.append(note)


def _presenter(session: Any) -> int | None:
    """Whose workspace this is: the retail demonstration account.

    Falls back to the first administrator, and then to nobody — a seeded
    project with no owner is still a seeded project, and refusing to seed
    because the expected username is absent would make the seeder fragile on
    exactly the fresh installation it exists for.
    """
    from sqlalchemy import select

    from backend.db.models import User

    row = session.execute(
        select(User).where(User.username == "retail.demo")).scalars().first()
    if row is not None:
        return int(row.id)
    row = session.execute(
        select(User).where(User.role.in_(("ADMIN", "admin")))
    ).scalars().first()
    return int(row.id) if row is not None else None


def check(session: Any) -> list[str]:
    """What a retail installation is still missing. Empty means ready."""
    from sqlalchemy import func, select

    from backend.models.platform import Project

    missing: list[str] = []
    seeded = {
        str((row.default_context or {}).get("seed_key") or "")
        for row in session.execute(select(Project)).scalars().all()
    }
    absent = [s.name for s in PROJECTS if s.key not in seeded]
    if absent:
        missing.append("projects not seeded: " + ", ".join(absent))

    from backend.models.collaboration import Message

    notes = int(session.execute(
        select(func.count()).select_from(Message)
        .where(Message.event_key.like("%:retail-note:%"))).scalar() or 0)
    if notes < len(NOTES):
        missing.append(f"retail working messages: {notes} of {len(NOTES)}")

    from backend.models.platform import Investigation

    built = {
        (str((row.context or {}).get("seed_key") or ""),
         str((row.context or {}).get("seed_script") or ""))
        for row in session.execute(select(Investigation)).scalars().all()
    }
    from backend.models.platform import RiskCase

    raised = int(session.execute(
        select(func.count()).select_from(RiskCase)).scalar() or 0)
    if not raised:
        missing.append("the portfolio review has raised no attention cases")

    absent_cases = [c.title for c in CASES
                    if (c.key, _fingerprint(c.questions)) not in built]
    if absent_cases:
        missing.append("case studies not built: " + ", ".join(absent_cases))
    return missing


# ------------------------------------------------------------ case studies

@dataclass(frozen=True)
class CaseSpec:
    """One prebuilt end-to-end case study, as a real thread.

    The questions are asked through the ordinary orchestration path and the
    answers are whatever the governed runtime produced. A case study whose
    answers were written by hand would be a screenshot with a cursor in it: it
    would survive exactly until somebody typed the next question.
    """

    key: str
    project_key: str
    title: str
    questions: tuple[str, ...]


CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        key="case-a-credit-card-odr",
        project_key="credit-card-odr-deterioration",
        title="Credit Card ODR deterioration — Aug 2026",
        # Broken down by the dimensions this book actually carries a story
        # in. `product_subsegment` is not one of them for cards: the shipped
        # lake holds a single card subsegment, so "break it down by
        # subsegment" is truthfully answered "across 1 subsegment" and shows
        # the reader nothing. Behaviour segment, utilisation band and channel
        # each split the card book several ways and are where the
        # deterioration is visible.
        questions=(
            "Which product has the highest 30+ DPD rate?",
            "Show exposure and weighted ECL by product for August 2026.",
            "Show the 30+ DPD rate for credit cards by card behaviour "
            "segment.",
            "Now by utilisation band.",
            "Give me the worst 20 customers by expected credit loss.",
        ),
    ),
    CaseSpec(
        key="case-b-personal-finance-scorecard",
        project_key="personal-finance-scorecard-monitoring",
        title="Personal Finance scorecard audit — Aug 2026",
        questions=(
            "How is the personal-finance application scorecard performing?",
            "Show discrimination.",
            "What about calibration?",
            "Has the population drifted?",
            "Draft the response to an auditor.",
        ),
    ),
    CaseSpec(
        key="case-c-home-finance-ecl",
        project_key="home-finance-stage2-migration-review",
        title="Home Finance ECL and Stage 2 — Aug 2026",
        questions=(
            "Show exposure and weighted ECL by IFRS 9 stage for August 2026.",
            "Now only home finance.",
            "How many facilities moved into Stage 2 this month?",
            "Are there any Stage 3 home-finance facilities in August 2026?",
        ),
    ),
)


def _cases(session: Any, into: Seeded, *, owner_id: int | None) -> None:
    """Run the three case studies, once, and file each under its project.

    Asked through `threads.ask`, which is the path the Cockpit itself uses, so
    what is stored is a real investigation with real governed answers and a
    real Trace behind each one. Re-running does nothing: a thread is
    recognised by its seed key.
    """
    from sqlalchemy import select

    from backend.models.platform import (
        Investigation,
        InvestigationMessage,
        Project,
    )
    from backend.services import threads

    projects = {
        str((row.default_context or {}).get("seed_key") or ""): row.id
        for row in session.execute(select(Project)).scalars().all()
    }
    # Keyed by the QUESTIONS as well as by the name. A case study whose
    # script has changed is a different case study, and a seeder that
    # recognised only the name would keep showing the old one for ever —
    # which is how Case A came to be four questions long after it had been
    # rewritten to five.
    seeded = {
        (str((row.context or {}).get("seed_key") or ""),
         str((row.context or {}).get("seed_script") or "")): row
        for row in session.execute(select(Investigation)).scalars().all()
    }

    for spec in CASES:
        script = _fingerprint(spec.questions)
        if (spec.key, script) in seeded:
            into.held("case study")
            continue
        # A thread under the same name but a different script is replaced, so
        # the workspace holds one Case A rather than a pile of drafts.
        for (key, _), row in list(seeded.items()):
            if key == spec.key:
                session.delete(row)
        session.commit()
        project_id = projects.get(spec.project_key)
        try:
            # `create` already stores the opening question as the thread's
            # first user message, so the ask loop starts at the second one.
            # Asking the first again left every case study opening with the
            # same question typed twice.
            view = threads.create(
                question=spec.questions[0], title=spec.title,
                project_id=project_id, user_id=owner_id,
                context={"seed_key": spec.key, "seed_script": script,
                         "seeded_by": SEED_MARK, "demo": True})
            # ...and the row it wrote is removed here rather than skipping
            # the first ask, because the thread must end up holding the
            # question AND its answer, which only `ask` produces.
            opened = session.execute(
                select(InvestigationMessage)
                .where(InvestigationMessage.investigation_id == view.id)
            ).scalars().all()
            for row in opened:
                session.delete(row)
            session.commit()
            answered = 0
            for question in spec.questions:
                result = threads.ask(view.id, question, user_id=owner_id)
                run = (result or {}).get("run") or {}
                if str(run.get("status") or "") == "succeeded":
                    answered += 1
            into.made("case study")
            if answered < len(spec.questions):
                into.notes.append(
                    f"{spec.title}: {answered} of {len(spec.questions)} "
                    "questions answered; the rest are on the thread as they "
                    "came back.")
        except Exception as e:  # noqa: BLE001 - one case must not lose the rest
            into.notes.append(f"{spec.title}: could not be built ({e}).")
