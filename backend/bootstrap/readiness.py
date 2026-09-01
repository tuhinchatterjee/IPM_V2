"""What has to be true before a presenter is handed the URL.

This is the list the fresh-Mac acceptance run checked by hand, written down
so a machine checks it instead. Each check answers one question a presenter
would otherwise discover in front of a client: is there a corporate book, are
there scorecard months, did the Q2 review actually run.

Two rules govern everything here.

**A check reports, it never repairs.** Readiness is the measurement; the
bootstrap is the work. Keeping them apart is what lets the acceptance test
run readiness against a deliberately broken deployment and get a useful
answer instead of a silently fixed one.

**A check that cannot run is not a check that passed.** `UNKNOWN` is a
distinct outcome from `OK`, and `ready()` refuses on it. The failure this
prevents is the one that produced the whole remediation: a startup that
reported success because the step that would have failed was never reached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

READINESS_VERSION = "1.0.0"

OK = "OK"
MISSING = "MISSING"
UNKNOWN = "UNKNOWN"

#: The period the bundled demonstration is presented at.
PERIOD = "Q2 2026"
PRIOR_PERIOD = "Q1 2026"

#: Datasets the core Saudi portfolio build produces. A missing one is not a
#: cosmetic gap: every analysis that reads it reports "no data" rather than
#: an error, which is the failure mode hardest to notice from the screen.
PORTFOLIO_DATASETS: tuple[str, ...] = (
    "portfolio_facility", "ifrs9_staging", "customer_ratings", "macro_saudi",
    "borrower_financials", "facility_delinquency", "credit_memo_signals",
    "collateral_register", "covenant_tests", "facility_limits",
    "watchlist_register", "recoveries", "payment_history", "group_structure",
    "rating_transitions", "risk_appetite_limits", "pd_model_performance",
    "scenario_definitions", "facility_profitability", "climate_risk",
)

CORPORATE_DATASETS: tuple[str, ...] = (
    "corporate_customer_master", "corporate_facilities", "corporate_financials",
    "corporate_ratings", "corporate_ifrs9", "corporate_covenants",
    "corporate_collateral", "corporate_delinquency", "corporate_limits",
    "corporate_watchlist", "corporate_borrower_360",
    "corporate_ownership_edges", "corporate_connected_groups",
)

RETAIL_DATASETS: tuple[str, ...] = (
    "retail_application_scorecard_monthly_validation",
    "retail_application_scorecard_development_reference",
    "retail_behavioral_scorecard_monthly_validation",
    "retail_behavioral_scorecard_development_reference",
)

IFRS9_DATASETS: tuple[str, ...] = ("ifrs9_staging", "corporate_ifrs9",
                                   "scenario_definitions")

#: Below this the corporate book is a fixture, not a demonstration. The
#: builder makes 3,800; a deployment holding forty has been quietly truncated
#: and Borrower 360 search returns almost nothing.
MINIMUM_CORPORATE_BORROWERS = 1_000
MINIMUM_CORPORATE_QUARTERS = 8
MINIMUM_SCORECARD_MONTHS = 6
MINIMUM_SCORECARD_MODELS = 2
MINIMUM_RISK_CASES = 1


@dataclass
class Check:
    """One question, its answer, and what to do about it."""

    key: str
    title: str
    status: str = UNKNOWN
    detail: str = ""
    remedy: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == OK

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "status": self.status,
                "detail": self.detail, "remedy": self.remedy,
                "data": dict(self.data)}


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def sentence(self) -> str:
        if not self.checks:
            return "Nothing was checked, so nothing is known."
        if self.ready:
            return f"All {len(self.checks)} readiness checks passed."
        bad = self.failures
        return (f"{len(bad)} of {len(self.checks)} readiness checks did not "
                f"pass: {', '.join(c.key for c in bad)}.")

    def to_dict(self) -> dict[str, Any]:
        return {"version": READINESS_VERSION, "ready": self.ready,
                "sentence": self.sentence(),
                "checks": [c.to_dict() for c in self.checks]}


# ------------------------------------------------------------- the checks


def _lake() -> tuple[set[str], str]:
    """What the analytical store holds, and why it could not be read."""
    try:
        from backend.data_access import get_data_source

        return set(get_data_source().datasets()), ""
    except Exception as e:  # noqa: BLE001 - reported, never raised
        return set(), f"{type(e).__name__}: {e}"


def _datasets_check(key: str, title: str, wanted: tuple[str, ...],
                    present: set[str], why: str, remedy: str) -> Check:
    if why:
        return Check(key=key, title=title, status=UNKNOWN,
                     detail=f"The analytical store could not be read. {why}",
                     remedy=remedy)
    absent = [name for name in wanted if name not in present]
    if absent:
        return Check(
            key=key, title=title, status=MISSING,
            detail=(f"{len(absent)} of {len(wanted)} dataset(s) are absent: "
                    f"{', '.join(absent[:6])}"
                    f"{'...' if len(absent) > 6 else ''}"),
            remedy=remedy, data={"missing": absent})
    return Check(key=key, title=title, status=OK,
                 detail=f"All {len(wanted)} dataset(s) present.",
                 data={"count": len(wanted)})


def _corporate_scale(present: set[str], why: str) -> Check:
    """The corporate book has to be a book, not a fixture."""
    key, title = "corporate_scale", "Corporate book is at full scale"
    remedy = "scripts/bootstrap_demo.py --step corporate"
    if why or "corporate_customer_master" not in present:
        return Check(key=key, title=title, status=UNKNOWN if why else MISSING,
                     detail=(why or "corporate_customer_master is not built."),
                     remedy=remedy)
    try:
        from backend.data_access import get_data_source

        source = get_data_source()
        # `profile` rather than reading the frame: the question is how many
        # DISTINCT borrowers there are, and pulling 3,800 rows into pandas to
        # count them is work a readiness probe on every boot should not do.
        profile = source.profile("corporate_customer_master",
                                 distinct=["borrower_id"])
        borrowers = int(
            ((profile.get("distinct") or {}).get("borrower_id")
             or source.row_count("corporate_customer_master")) or 0)
        quarters = len(source.periods("corporate_facilities") or [])
    except Exception as e:  # noqa: BLE001
        return Check(key=key, title=title, status=UNKNOWN,
                     detail=f"{type(e).__name__}: {e}", remedy=remedy)

    data = {"borrowers": borrowers, "quarters": quarters}
    if borrowers < MINIMUM_CORPORATE_BORROWERS or \
            quarters < MINIMUM_CORPORATE_QUARTERS:
        return Check(
            key=key, title=title, status=MISSING,
            detail=(f"{borrowers:,} borrower(s) over {quarters} quarter(s). "
                    f"A full book needs at least "
                    f"{MINIMUM_CORPORATE_BORROWERS:,} over "
                    f"{MINIMUM_CORPORATE_QUARTERS}; this book has been "
                    "truncated and Borrower 360 search will look empty."),
            remedy=remedy, data=data)
    return Check(key=key, title=title, status=OK,
                 detail=(f"{borrowers:,} borrowers over {quarters} quarters."),
                 data=data)


def _scorecard_months(present: set[str], why: str) -> Check:
    key, title = "scorecard_months", "Scorecard validation months exist"
    remedy = "scripts/bootstrap_demo.py --step retail"
    dataset = "retail_application_scorecard_monthly_validation"
    if why or dataset not in present:
        return Check(key=key, title=title, status=UNKNOWN if why else MISSING,
                     detail=(why or f"{dataset} is not built — the Scorecard "
                                    "Validation screen reports no months for "
                                    "APPLICATION."),
                     remedy=remedy)
    try:
        from backend.data_access import get_data_source

        source = get_data_source()
        application = len(source.periods(dataset) or [])
        behavioural = len(source.periods(
            "retail_behavioral_scorecard_monthly_validation") or [])
    except Exception as e:  # noqa: BLE001
        return Check(key=key, title=title, status=UNKNOWN,
                     detail=f"{type(e).__name__}: {e}", remedy=remedy)

    data = {"application_months": application, "behavioural_months": behavioural}
    if min(application, behavioural) < MINIMUM_SCORECARD_MONTHS:
        return Check(
            key=key, title=title, status=MISSING,
            detail=(f"{application} application month(s) and {behavioural} "
                    f"behavioural — at least {MINIMUM_SCORECARD_MONTHS} of "
                    "each are needed for the validation tabs to have "
                    "anything to show."),
            remedy=remedy, data=data)
    return Check(key=key, title=title, status=OK,
                 detail=(f"{application} application and {behavioural} "
                         "behavioural validation months."), data=data)


def _catalogue() -> Check:
    key, title = "catalogue", "Governed catalogue includes every book"
    remedy = "scripts/bootstrap_demo.py --step catalogue"
    try:
        from backend.data_access import get_catalog

        names = set(get_catalog().names())
    except Exception as e:  # noqa: BLE001
        return Check(key=key, title=title, status=UNKNOWN,
                     detail=f"{type(e).__name__}: {e}", remedy=remedy)

    wanted = set(PORTFOLIO_DATASETS) | set(CORPORATE_DATASETS) | set(RETAIL_DATASETS)
    absent = sorted(wanted - names)
    if absent:
        return Check(
            key=key, title=title, status=MISSING,
            detail=(f"{len(absent)} governed dataset(s) are built but not in "
                    f"the catalogue: {', '.join(absent[:6])}"
                    f"{'...' if len(absent) > 6 else ''}. A dataset outside "
                    "the catalogue cannot be read by any analysis."),
            remedy=remedy, data={"missing": absent})
    return Check(key=key, title=title, status=OK,
                 detail=f"{len(names)} governed datasets catalogued.",
                 data={"count": len(names)})


def _database_checks(session: Any) -> list[Check]:
    """Everything that lives in PostgreSQL rather than the lake."""
    from sqlalchemy import func, select

    from backend.models.platform import DS_PUBLISHED, DataDomain, DatasetDefinition
    from backend.services import data_domains as dd

    checks: list[Check] = []

    # -- registered, published, and in a business domain a person can find
    rows = session.execute(select(DatasetDefinition)).scalars().all()
    by_name = {d.name: d for d in rows}
    wanted = set(PORTFOLIO_DATASETS) | set(CORPORATE_DATASETS) | set(RETAIL_DATASETS)
    unregistered = sorted(wanted - set(by_name))
    checks.append(Check(
        key="datasets_registered", title="Datasets registered in Data Builder",
        status=OK if not unregistered else MISSING,
        detail=(f"{len(by_name)} dataset(s) registered."
                if not unregistered else
                f"{len(unregistered)} not registered: "
                f"{', '.join(unregistered[:6])}"),
        remedy="scripts/bootstrap_demo.py --step catalogue",
        data={"registered": len(by_name), "missing": unregistered}))

    unpublished = sorted(n for n in wanted & set(by_name)
                         if by_name[n].lifecycle != DS_PUBLISHED)
    checks.append(Check(
        key="datasets_published", title="Bundled datasets are published",
        status=OK if not unpublished else MISSING,
        detail=("Every bundled dataset is published."
                if not unpublished else
                f"{len(unpublished)} registered but not published: "
                f"{', '.join(unpublished[:6])}"),
        remedy="scripts/bootstrap_demo.py --step catalogue",
        data={"unpublished": unpublished}))

    authoritative = [n for n, d in by_name.items() if d.authoritative_for]
    checks.append(Check(
        key="datasets_authoritative",
        title="Governed datasets are authoritative",
        status=OK if authoritative else MISSING,
        detail=(f"{len(authoritative)} dataset(s) carry an authoritative "
                "purpose." if authoritative else
                "No dataset is authoritative for any purpose, so every "
                "governed read is refused at the authority layer."),
        remedy="scripts/bootstrap_demo.py --step catalogue",
        data={"count": len(authoritative)}))

    domain_names = {d.name for d in session.execute(
        select(DataDomain)).scalars().all()}
    absent_domains = [n for n in dd.NAMES if n not in domain_names]
    checks.append(Check(
        key="data_builder_domains", title="Data Builder business domains exist",
        status=OK if not absent_domains else MISSING,
        detail=(f"All {len(dd.NAMES)} business domains are defined."
                if not absent_domains else
                f"{len(absent_domains)} of {len(dd.NAMES)} missing: "
                f"{', '.join(absent_domains)}"),
        remedy="scripts/bootstrap_demo.py --step domains",
        data={"missing": absent_domains, "defined": len(domain_names)}))

    # -- the demonstration accounts
    from backend.db.models import User

    users = session.execute(select(func.count()).select_from(User)).scalar() or 0
    checks.append(Check(
        key="demo_users", title="Sign-in accounts exist",
        status=OK if users else MISSING,
        detail=f"{users} account(s)." if users else "No users — nobody can sign in.",
        remedy="scripts/bootstrap_demo.py --step users",
        data={"count": int(users)}))

    checks.append(_scorecard_models(session))
    checks.append(_workspace(session))
    checks.append(_review(session))
    return checks


def _scorecard_models(session: Any) -> Check:
    key, title = "scorecard_models", "Scorecard model registry is populated"
    remedy = "scripts/bootstrap_demo.py --step models"
    try:
        from sqlalchemy import select

        from backend.models.platform import ScorecardModel

        rows = session.execute(select(ScorecardModel)).scalars().all()
    except Exception as e:  # noqa: BLE001
        return Check(key=key, title=title, status=UNKNOWN,
                     detail=f"{type(e).__name__}: {e}", remedy=remedy)
    kinds = {str(getattr(r, "scorecard_type", "") or "").upper() for r in rows}
    enough = len(rows) >= MINIMUM_SCORECARD_MODELS and len(kinds) >= 2
    return Check(
        key=key, title=title, status=OK if enough else MISSING,
        detail=(f"{len(rows)} model(s) across {sorted(kinds)}." if enough else
                f"{len(rows)} model(s) across {sorted(kinds) or 'nothing'} — "
                "the Models and Governance tabs have nothing to show."),
        remedy=remedy, data={"models": len(rows), "types": sorted(kinds)})


def _workspace(session: Any) -> Check:
    key, title = "demo_workspace", "Workspace is populated"
    remedy = "scripts/bootstrap_demo.py --step workspace"
    try:
        from sqlalchemy import func, select

        from backend.models.platform import Investigation, Project

        projects = session.execute(
            select(func.count()).select_from(Project)).scalar() or 0
        investigations = session.execute(
            select(func.count()).select_from(Investigation)).scalar() or 0
    except Exception as e:  # noqa: BLE001
        return Check(key=key, title=title, status=UNKNOWN,
                     detail=f"{type(e).__name__}: {e}", remedy=remedy)
    enough = projects >= 1 and investigations >= 1
    return Check(
        key=key, title=title, status=OK if enough else MISSING,
        detail=(f"{projects} project(s), {investigations} investigation(s)."
                if enough else
                "The Projects and Investigations screens are empty."),
        remedy=remedy,
        data={"projects": int(projects), "investigations": int(investigations)})


def _review(session: Any) -> Check:
    """Did the Q2 2026 review actually run, and did it leave anything?

    Both halves matter. A review that ran and found nothing is a legitimate
    state on a quiet book; a review that never ran is the Cockpit saying
    "nothing here has been checked yet", which is what the fresh Mac showed.
    """
    key, title = "portfolio_review", f"{PERIOD} portfolio review completed"
    remedy = "scripts/bootstrap_demo.py --step review"
    try:
        from sqlalchemy import func, select

        from backend.models.platform import RiskCase

        cases = session.execute(
            select(func.count()).select_from(RiskCase)).scalar() or 0
    except Exception as e:  # noqa: BLE001
        return Check(key=key, title=title, status=UNKNOWN,
                     detail=f"{type(e).__name__}: {e}", remedy=remedy)

    reviewed = _review_ran(session)
    if not reviewed:
        return Check(key=key, title=title, status=MISSING,
                     detail=(f"No review of {PERIOD} has been recorded, so "
                             "the Cockpit reports the book as unchecked."),
                     remedy=remedy, data={"risk_cases": int(cases)})
    if cases < MINIMUM_RISK_CASES:
        return Check(key=key, title=title, status=MISSING,
                     detail=(f"The {PERIOD} review ran and produced no Risk "
                             "Cases at all. On the bundled book that means "
                             "the deterioration patterns did not reach the "
                             "screen, not that the book is quiet."),
                     remedy=remedy, data={"risk_cases": 0})
    return Check(key=key, title=title, status=OK,
                 detail=(f"The {PERIOD} review completed and left "
                         f"{cases} Risk Case(s)."),
                 data={"risk_cases": int(cases)})


def _review_ran(session: Any) -> bool:
    """Whether the attention state says this period has been reviewed."""
    try:
        from backend.agentic import attention

        # `reviewed` is the module's own definition of the word - a run that
        # COMPLETED, with or without cases. Asking it rather than counting
        # runs is deliberate: a queued run and a failed one are both rows,
        # and neither is a review anybody can stand behind.
        return bool(attention.state(session, period=PERIOD).reviewed)
    except Exception as e:  # noqa: BLE001 - reported by the caller as UNKNOWN
        logger.warning("Could not read the review state for %s: %s", PERIOD, e)
        return False


# --------------------------------------------------------------- public API


def report(session: Any | None = None) -> Report:
    """Every readiness check, run once.

    `session` is optional so the lake-only half can be checked on a machine
    with no database — which is a real state during a build, and reporting
    "database checks did not run" is more useful than refusing to report.
    """
    present, why = _lake()
    checks = [
        _datasets_check("portfolio_data", "Core portfolio datasets exist",
                        PORTFOLIO_DATASETS, present, why,
                        "scripts/bootstrap_demo.py --step portfolio"),
        _datasets_check("corporate_data", "Corporate Borrower 360 datasets exist",
                        CORPORATE_DATASETS, present, why,
                        "scripts/bootstrap_demo.py --step corporate"),
        _datasets_check("retail_data", "Retail scorecard datasets exist",
                        RETAIL_DATASETS, present, why,
                        "scripts/bootstrap_demo.py --step retail"),
        _datasets_check("ifrs9_data", "IFRS 9 datasets exist",
                        IFRS9_DATASETS, present, why,
                        "scripts/bootstrap_demo.py --step portfolio"),
        _corporate_scale(present, why),
        _scorecard_months(present, why),
        _catalogue(),
    ]

    if session is not None:
        checks.extend(_database_checks(session))
    else:
        checks.append(Check(
            key="database", title="Database-backed synthetic data state",
            status=UNKNOWN,
            detail="No database session was supplied, so nothing that lives "
                   "in PostgreSQL was checked.",
            remedy="Run with DATABASE_URL configured."))

    return Report(checks=checks)


def ready(session: Any | None = None) -> bool:
    return report(session).ready


__all__ = [
    "CORPORATE_DATASETS", "Check", "IFRS9_DATASETS",
    "MINIMUM_CORPORATE_BORROWERS", "MINIMUM_CORPORATE_QUARTERS",
    "MINIMUM_RISK_CASES", "MINIMUM_SCORECARD_MODELS",
    "MINIMUM_SCORECARD_MONTHS", "MISSING", "OK", "PERIOD", "PORTFOLIO_DATASETS",
    "PRIOR_PERIOD", "READINESS_VERSION", "RETAIL_DATASETS", "Report", "UNKNOWN",
    "ready", "report",
]
