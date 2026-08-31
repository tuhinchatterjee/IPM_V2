"""The fourteen things that have to happen before a demonstration exists.

Before this file, demonstration setup was scattered across five scripts, a
Docker entrypoint that ran three of them, a README that named three more, and
a button on the Data Builder screen. The fresh-Mac acceptance run found the
consequence: the entrypoint built the Saudi portfolio and started the API, and
everything else — the corporate book, the retail scorecards, the catalogue
registration, the model registry, the workspace, the Q2 review — simply never
happened. Nothing failed. The API came up healthy and the product was empty.

So the sequence lives in one place, as data.

Three properties, each of which the old arrangement lacked
----------------------------------------------------------
**Each step knows whether it is needed.** `needed()` is a probe, not a flag
file: it asks the deployment what is actually there. A container restarted
twenty times does the work once, and a volume half-built by an interrupted
start finishes the half that is missing rather than starting again.

**A required step that fails, fails the bootstrap.** The old
`seed.build` caught every exception from the review and appended a note. That
is how a demonstration reaches a presenter with an empty Cockpit and a green
health check. A step marked required raises, and `READY` is never reported.

**Order is stated, not assumed.** `generate_saudi_universe.py` OVERWRITES
`metadata/catalog.json`; the corporate and retail builders MERGE into it.
Running them in the wrong order silently erases twenty-six catalogue entries
and leaves the Parquet in place — datasets on disk that no analysis can see.
That ordering was load-bearing and undocumented. It is now both.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.bootstrap import readiness

logger = logging.getLogger(__name__)

BOOTSTRAP_VERSION = "1.0.0"

DONE = "DONE"
SKIPPED = "SKIPPED"
FAILED = "FAILED"


@dataclass
class Outcome:
    key: str
    title: str
    status: str
    detail: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "status": self.status,
                "detail": self.detail, "seconds": round(self.seconds, 1)}


@dataclass
class Step:
    """One unit of demonstration setup."""

    key: str
    letter: str
    title: str
    #: Does this deployment still need it? True means run.
    needed: Callable[[], bool]
    #: Do it. Returns a sentence for the log.
    run: Callable[[], str]
    #: A required step that fails stops the bootstrap and blocks READY.
    required: bool = True
    #: Needs a database connection.
    needs_database: bool = False


@dataclass
class Result:
    outcomes: list[Outcome] = field(default_factory=list)
    report: readiness.Report | None = None
    seconds: float = 0.0

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.status == FAILED]

    @property
    def ok(self) -> bool:
        return not self.failed and bool(self.report and self.report.ready)

    def sentence(self) -> str:
        done = sum(1 for o in self.outcomes if o.status == DONE)
        skipped = sum(1 for o in self.outcomes if o.status == SKIPPED)
        head = (f"{done} step(s) performed, {skipped} already in place, "
                f"in {self.seconds:.0f}s.")
        if self.failed:
            return head + (f" {len(self.failed)} FAILED: "
                           f"{', '.join(o.key for o in self.failed)}.")
        if self.report and not self.report.ready:
            return head + " " + self.report.sentence()
        return head + " The deployment is ready."

    def to_dict(self) -> dict[str, Any]:
        return {"version": BOOTSTRAP_VERSION, "ok": self.ok,
                "sentence": self.sentence(),
                "seconds": round(self.seconds, 1),
                "steps": [o.to_dict() for o in self.outcomes],
                "readiness": self.report.to_dict() if self.report else None}


# ------------------------------------------------------------------ probes


def _lake_has(*names: str) -> bool:
    try:
        from backend.data_access import get_data_source

        present = set(get_data_source().datasets())
    except Exception:  # noqa: BLE001 - an unreadable lake is a lake to build
        return False
    return all(name in present for name in names)


def _refresh_data_access() -> None:
    """Forget what the process learned about the lake before it was built.

    The catalogue and the DuckDB source are cached per process. A bootstrap
    that builds three universes inside one process and then registers what it
    built would otherwise register the empty catalogue it read at import.
    """
    try:
        from backend import data_access

        # `reload_catalog` re-reads metadata/catalog.json; `reset_data_source`
        # drops the cached DuckDB handle so the newly written Parquet is
        # visible. Both are needed, and missing either is how a bootstrap
        # registers the catalogue it read before it built anything.
        for name in ("reset_data_source", "reload_catalog"):
            resetter = getattr(data_access, name, None)
            if callable(resetter):
                resetter()
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not reset the data-access caches: %s", e)

    # The Early Warning book is memoised per period on top of those caches -
    # standing three thousand borrowers up against thirty-four conditions
    # takes a little over two seconds, so a screen that paid it on every load
    # is a screen people stop opening. A bootstrap that regenerated the lake
    # and left the memo in place would serve the OLD book from the new
    # deployment, which is the worst possible direction for a cache to be
    # wrong in.
    try:
        from backend.early_warning import signals

        signals.reset()
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not reset the early-warning caches: %s", e)


def _session():
    from backend.db.engine import get_session

    return get_session()


# ------------------------------------------------------------------- steps


def _migrations_needed() -> bool:
    from backend.config import settings

    if not settings.has_database:
        return False
    try:
        from alembic.runtime.migration import MigrationContext

        from backend.db.engine import engine

        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        return current != _head_revision()
    except Exception as e:  # noqa: BLE001 - an unreadable schema is one to migrate
        # Logged, not swallowed. A database that cannot be read is a database
        # to migrate, but an import error in this probe would otherwise look
        # exactly like "the schema is out of date" and run the migrations on
        # every boot for ever without anybody noticing.
        logger.info("Could not read the current schema revision (%s); "
                    "treating the schema as out of date.", e)
        return True


def _head_revision() -> str:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def _run_migrations() -> str:
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(config, "head")
    return f"schema at {_head_revision()}"


def _users_needed() -> bool:
    from sqlalchemy import func, select

    from backend.db.models import User

    with _session() as session:
        return not (session.execute(
            select(func.count()).select_from(User)).scalar() or 0)


def _seed_users() -> str:
    from backend.services import demo_users

    with _session() as session:
        result = demo_users.seed(session)
        session.commit()
    return (f"{len(result.created)} account(s) created, "
            f"{len(result.kept)} already present")


def _portfolio_needed() -> bool:
    return not _lake_has(*readiness.PORTFOLIO_DATASETS)


def _build_portfolio() -> str:
    import scripts.generate_saudi_universe as builder

    # No argv: this builder's main() takes none, unlike the other two.
    if builder.main() != 0:
        raise RuntimeError("the Saudi portfolio build reported failure")
    _refresh_data_access()
    return f"{len(readiness.PORTFOLIO_DATASETS)} core portfolio dataset(s)"


def _corporate_needed() -> bool:
    return not _lake_has(*readiness.CORPORATE_DATASETS)


def _build_corporate() -> str:
    import scripts.build_corporate_universe as builder

    if builder.main([]) != 0:
        raise RuntimeError("the corporate universe build reported failure")
    _refresh_data_access()
    return "corporate Borrower 360 universe"


def _retail_needed() -> bool:
    return not _lake_has(*readiness.RETAIL_DATASETS)


def _build_retail() -> str:
    import scripts.build_retail_scorecards as builder

    if builder.main([]) != 0:
        raise RuntimeError("the retail scorecard build reported failure")
    _refresh_data_access()
    return "application and behavioural scorecard universes"


def _models_needed() -> bool:
    from sqlalchemy import func, select

    from backend.models.platform import ScorecardModel

    with _session() as session:
        return (session.execute(
            select(func.count()).select_from(ScorecardModel)).scalar() or 0) < \
            readiness.MINIMUM_SCORECARD_MODELS


def _seed_models() -> str:
    from backend.scorecard import registry

    with _session() as session:
        result = registry.seed(session)
        session.commit()
    models = result.get("models") or result.get("registered") or []
    return f"{len(models)} scorecard model(s) registered"


def _catalogue_needed() -> bool:
    from sqlalchemy import select

    from backend.models.platform import DatasetDefinition

    wanted = (set(readiness.PORTFOLIO_DATASETS)
              | set(readiness.CORPORATE_DATASETS)
              | set(readiness.RETAIL_DATASETS))
    with _session() as session:
        known = {d.name for d in session.execute(
            select(DatasetDefinition)).scalars()}
    return bool(wanted - known)


def _register_catalogue() -> str:
    from backend.services.governance import sync_bundled_catalog

    _refresh_data_access()
    with _session() as session:
        result = sync_bundled_catalog(session)
        session.commit()
    return f"{len(result.get('synced') or [])} dataset(s) registered"


def _domains_needed() -> bool:
    from sqlalchemy import select

    from backend.models.platform import DataDomain
    from backend.services import data_domains as dd

    with _session() as session:
        known = {d.name for d in session.execute(select(DataDomain)).scalars()}
    return bool(set(dd.NAMES) - known)


def _install_domains() -> str:
    from backend.services.governance import install_business_domains

    with _session() as session:
        result = install_business_domains(session)
        session.commit()
    return (f"{result['domains']} business domain(s), "
            f"{result['placed']} dataset(s) placed")


def _relationships_needed() -> bool:
    from sqlalchemy import func, select

    from backend.models.platform import DatasetRelationship

    with _session() as session:
        return not (session.execute(
            select(func.count()).select_from(DatasetRelationship)).scalar() or 0)


def _seed_relationships() -> str:
    from backend.services.relationships import seed

    with _session() as session:
        result = seed(session)
        session.commit()
    made = result.get("created", result.get("declared", 0))
    return f"{made} governed relationship(s)"


def _workspace_needed() -> bool:
    from sqlalchemy import func, select

    from backend.models.platform import Project

    with _session() as session:
        return not (session.execute(
            select(func.count()).select_from(Project)).scalar() or 0)


def _seed_workspace() -> str:
    from backend.demo import seed as demo_seed

    with _session() as session:
        # The review is its own step, so it is not run twice and so a failure
        # in it is attributed to the review rather than to the workspace.
        result = demo_seed.build(session, run_review=False)
        session.commit()
    if result.error:
        raise RuntimeError(result.error)
    return ", ".join(f"{n} {k}" for k, n in sorted(result.created.items())) \
        or "workspace objects"


def _review_needed() -> bool:
    """Needed whenever the readiness gate would not pass, not merely when no
    run row exists.

    The two used to disagree. The step asked "did a review COMPLETE?" and the
    gate asked "did a review complete AND leave cases?", so a database whose
    run row survived while its cases did not was simultaneously "already in
    place" and "not ready" - and re-running the bootstrap reported success
    while fixing nothing, which is the worst of the three possible outcomes.
    One definition of done, and it is the gate's.
    """
    with _session() as session:
        return not readiness._review(session).ok


def _run_review() -> str:
    from backend.agentic import review

    with _session() as session:
        _, found = review.run(session, period=readiness.PERIOD,
                              prior_period=readiness.PRIOR_PERIOD)
        session.commit()
        cases = int(getattr(found, "case_count", 0) or 0)
        if not readiness._review_ran(session):
            raise RuntimeError(
                f"the {readiness.PERIOD} review did not reach a completed "
                "state, so the Cockpit would still report the book as "
                "unchecked")
    return f"{cases} Risk Case(s) from the {readiness.PERIOD} review"


# ------------------------------------------------------------------- the plan


def steps() -> tuple[Step, ...]:
    """A to N, in the only order that works."""
    return (
        Step("migrations", "A", "Apply database migrations",
             _migrations_needed, _run_migrations, needs_database=True),
        Step("users", "B", "Seed the sign-in accounts",
             _users_needed, _seed_users, needs_database=True),
        # C before D and E: the Saudi builder OVERWRITES metadata/catalog.json
        # and the other two merge into it. Reversed, the corporate and retail
        # entries are erased and their Parquet becomes unreadable by any
        # analysis.
        Step("portfolio", "C", "Generate the core Saudi portfolio",
             _portfolio_needed, _build_portfolio),
        Step("corporate", "D", "Generate the corporate Borrower 360 universe",
             _corporate_needed, _build_corporate),
        Step("retail", "E", "Generate the retail scorecard universe",
             _retail_needed, _build_retail),
        Step("models", "F", "Populate the scorecard model registry",
             _models_needed, _seed_models, needs_database=True),
        Step("catalogue", "G", "Register the governed catalogue",
             _catalogue_needed, _register_catalogue, needs_database=True),
        Step("domains", "H", "Install the Data Builder business domains",
             _domains_needed, _install_domains, needs_database=True),
        # I is not a separate step: `sync_bundled_catalog` publishes each
        # dataset and carries its `authoritative_for` across as it registers
        # it. Splitting them would let a deployment exist in which a dataset
        # is registered and nothing is authoritative, which is the state that
        # makes every governed read fail at the authority layer.
        Step("relationships", "J", "Declare the governed joins",
             _relationships_needed, _seed_relationships, needs_database=True),
        Step("workspace", "K", "Seed the workspace",
             _workspace_needed, _seed_workspace, needs_database=True),
        Step("review", "L", f"Run the {readiness.PERIOD} portfolio review",
             _review_needed, _run_review, needs_database=True),
    )


def run(*, only: str = "", force: bool = False,
        skip_builders: bool = False) -> Result:
    """Perform whatever this deployment is missing, then verify.

    `only` runs one step by key. `force` runs a step whose probe says it is
    already done — for a rebuild. `skip_builders` leaves the three data
    universes alone, which is what a test wants when the lake is already
    there and only the database half is in question.
    """
    from backend.config import settings

    started = time.time()
    result = Result()
    has_db = settings.has_database

    for step in steps():
        if only and step.key != only:
            continue
        if skip_builders and step.key in ("portfolio", "corporate", "retail"):
            continue
        if step.needs_database and not has_db:
            result.outcomes.append(Outcome(
                step.key, step.title, SKIPPED,
                "No DATABASE_URL is configured."))
            continue

        began = time.time()
        try:
            if not force and not step.needed():
                result.outcomes.append(Outcome(
                    step.key, step.title, SKIPPED, "Already in place.",
                    time.time() - began))
                logger.info("[bootstrap] %s %s — already in place",
                            step.letter, step.title)
                continue
            logger.info("[bootstrap] %s %s ...", step.letter, step.title)
            detail = step.run()
            result.outcomes.append(Outcome(step.key, step.title, DONE, detail,
                                           time.time() - began))
            logger.info("[bootstrap] %s %s — %s", step.letter, step.title,
                        detail)
        except Exception as e:  # noqa: BLE001 - recorded, and it stops the run
            detail = f"{type(e).__name__}: {e}"
            result.outcomes.append(Outcome(step.key, step.title, FAILED,
                                           detail, time.time() - began))
            logger.error("[bootstrap] %s %s FAILED — %s", step.letter,
                         step.title, detail)
            if step.required:
                break

    # M. Verify. Always, including after a failure: the report is what tells
    # a person which of the eleven promises this deployment can keep.
    _refresh_data_access()
    if has_db:
        with _session() as session:
            result.report = readiness.report(session)
    else:
        result.report = readiness.report(None)
    result.seconds = time.time() - started
    return result


__all__ = ["BOOTSTRAP_VERSION", "DONE", "FAILED", "Outcome", "Result",
           "SKIPPED", "Step", "run", "steps"]
