#!/usr/bin/env python
"""
Bring the retail installation up to demo-ready, in one idempotent step.

    .venv/bin/python scripts/bootstrap_retail_installation.py

Registers the published retail book in Data Builder's governance tables so that
"Cockpit Data" and its twenty-five monthly members appear on screen, and marks
the retail dataset as authoritative for the retail governed purposes.

Guarded: it refuses any database or metadata target that is not the retail
installation's, so it cannot be pointed at a frozen source demo.

Idempotent. Run it as often as you like; it changes nothing that is already
correct, and it never invents a dataset the lake does not hold.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--check", action="store_true",
        help="Report what a retail installation is still missing, and change "
             "nothing. Exit 0 when it is ready to demonstrate.")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(message)s")
    log = logging.getLogger("bootstrap_retail")

    from backend.retail import guard
    from backend.config import settings

    guard.require_retail_directory(Path(settings.analytics_dir), what="bootstrap")
    guard.require_retail_directory(Path(settings.metadata_dir), what="bootstrap")
    guard.require_retail_database(os.environ.get("DATABASE_URL", ""), what="bootstrap")

    if args.check:
        return _check(log)

    from backend.data_access.catalog import reload_catalog
    catalog = reload_catalog()
    if not catalog.names():
        from backend.retail.profile import missing_seed_error
        raise SystemExit(str(missing_seed_error()))

    log.info("Governed catalogue: %s", ", ".join(catalog.names()))

    from backend.db.engine import get_session
    from backend.services import governance

    with get_session() as session:
        result = governance.sync_bundled_catalog(session)
    log.info("Registered the bundled retail book in Data Builder: %s", result)

    from backend.services.data_builder import published_datasets
    with get_session() as session:
        published = [d.name for d in published_datasets(session)]
    log.info("Data Builder now publishes: %s", ", ".join(published) or "(none)")

    # The workspace. Publishing the book leaves a fresh retail database with
    # no projects, no data-release notifications and no working messages, so
    # the first thing a Head of Retail Risk sees on three screens is an empty
    # state. Seeded through the same services the product writes through, and
    # idempotent: a re-run keeps what is already there.
    from backend.retail import workspace_seed

    with get_session() as session:
        seeded = workspace_seed.seed(session)
        session.commit()
    log.info("Retail workspace: %s", seeded.summary())
    for note in seeded.notes:
        log.warning("  %s", note)

    # The early-warning panel. Evaluating twenty governed rules over
    # twenty-five months takes about a minute and a half, which is fine once
    # at bootstrap and far too slow inside a page load — so Early Warning
    # reads a precomputed roll-up, and a fresh install that skips this step
    # opens on "the early-warning panel has not been built". Idempotent: a
    # month already written is left alone.
    from backend.retail import ews_portfolio

    built = ews_portfolio.build()
    log.info("Early-warning panel: %d month(s) scored, %d already present, "
             "%d rows written", built.months, built.skipped, built.rows)
    for note in built.notes or []:
        log.warning("  %s", note)

    # The Early Warning SCORE domain: twenty monthly snapshots at
    # customer-facility-month grain, carrying the four-layer model's own
    # output. The workspace reads nothing else, so a fresh install without it
    # opens on an empty state.
    from backend.retail import domains as retail_domains
    from backend.retail import ews_score

    scored = ews_score.build()
    log.info("Early Warning Score domain: %s", scored.summary())
    for note in scored.notes or []:
        log.info("  %s", note)
    if retail_domains.register_ews_score():
        log.info("Registered %s in the governed catalogue.",
                 retail_domains.EWS_SCORE_DATASET)
    for problem in ews_score.check():
        log.warning("  %s", problem)

    # The three governed VIEWS of the book: Early Warning Data (the raw
    # retail / IFRS 9 / bureau source the score is computed from), Credit
    # Scorecard Data and What-If Analysis Data. Nothing built these, so a
    # fresh install came up with the Early Warning Score domain in Data
    # Builder and the source domain behind it missing — and the readiness
    # check passed, because it only ever asked about the score. The
    # generator rewrites the catalogue from the book, so registration has to
    # happen after it, here, rather than once by hand.
    views = retail_domains.build()
    log.info("Governed views: %s",
             ", ".join(f"{name} {count} period(s)"
                       for name, count in sorted(views.written.items()))
             or "nothing written")
    for note in views.notes or []:
        log.warning("  %s", note)
    registered = retail_domains.register()
    if registered:
        log.info("Registered %s in the governed catalogue.",
                 ", ".join(registered))

    # A view builds only the periods it is missing, which is right while the
    # book underneath is the same book. Regenerating the book changes every
    # period without changing their names, so the incremental build has
    # nothing to do and the views keep serving the old one — reconciled
    # against a canonical total they no longer match. Here, the reconciliation
    # is not a report, it is the trigger: if the views disagree with the book,
    # they are rebuilt from it and checked again.
    problems = retail_domains.reconcile()
    if problems:
        log.warning("The governed views disagree with the book, so they are "
                    "being rebuilt from it:")
        for problem in problems:
            log.warning("  %s", problem)
        again = retail_domains.build(replace=True)
        log.info("Rebuilt: %s", ", ".join(
            f"{name} {rows} period(s)"
            for name, rows in sorted(again.written.items())) or "nothing")
        retail_domains.register()
        problems = retail_domains.reconcile()
    for problem in problems:
        log.warning("  STILL UNRECONCILED: %s", problem)

    # The What-If challenger's artifact. §10.2.
    #
    # Fitted here rather than on the first scenario that asks for it, so the
    # model page has a model to describe from the moment the installation
    # comes up, and so the first reader to choose the challenger does not pay
    # for the fit. It is stamped with the book, so a regenerated book refits
    # it rather than serving a model trained on data that is gone.
    from backend.retail import challenger_registry

    try:
        _, challenger = challenger_registry.build()
        log.info("What-If challenger: %s fitted on %d facilities, held back "
                 "%d, R² %.4f on the held-back rows",
                 challenger.library, challenger.rows_fitted,
                 challenger.rows_held_back,
                 challenger.metrics.get("r2", 0.0))
    except challenger_registry.ChallengerUnavailable as problem:
        log.warning("  The What-If challenger could not be fitted: %s. "
                    "Scenarios asking for it will say so rather than "
                    "returning a number.", problem)

    # The demonstration CONTENT: twelve projects, the saved analyses under
    # them, the investigation threads, the committee papers and the product
    # dashboards. §17 to §20.
    #
    # This runs last on purpose. Every one of those objects is computed from
    # the book through the governed measure engine, so it needs the views
    # above to exist and to reconcile first — seeded before them, a project's
    # headline figure would be computed from a book the views had not caught
    # up with, which is exactly the version confusion this release is about.
    #
    # It has to be HERE rather than in a script somebody remembers to run.
    # Without it a fresh Mac bootstraps successfully and opens on a Workspace
    # with no projects, an Analyses list with nothing in it and a Documents
    # screen reading "Nothing yet" — with every one of those capabilities
    # built and working underneath.
    #
    # Idempotent: an object already seeded at this book version is left
    # alone, and one whose figures have moved is refreshed, not duplicated.
    from backend.retail import seed_workspace

    with get_session() as session:
        content = seed_workspace.build(session)
        session.commit()
    log.info("Demonstration content: %s",
             ", ".join(f"{kind} {one['total']}"
                       for kind, one in sorted(
                           (content.get("summary") or {}).items()))
             or "nothing written")
    for problem in (content.get("errors") or [])[:10]:
        log.warning("  %s", problem)

    # And the residue a retail installation should not be showing: the
    # corporate saved analyses a test left behind, and the investigations
    # with no messages and no project. Anything carrying content is untouched.
    with get_session() as session:
        removed = seed_workspace.tidy(session, preview=False)
        session.commit()
    if removed.get("removed"):
        log.info("Removed non-retail residue: %s", removed["removed"])

    if "retail_facility_month" not in published:
        log.warning(
            "retail_facility_month is not published in Data Builder. The Cockpit will "
            "still answer from the governed catalogue, but the Data Builder screen "
            "will not list the domain."
        )
        return 1
    with get_session() as session:
        missing = workspace_seed.check(session)
    if missing:
        for item in missing:
            log.warning("Still missing: %s", item)
        return 1

    log.info("")
    log.info("The retail installation is bootstrapped.")
    return 0


def _check(log) -> int:
    """What this installation is still missing, without changing anything.

    A readiness check that runs the seeder would always report ready, which is
    the one answer it must never be able to give by accident. This reads, and
    says what it found.
    """
    from backend.data_access.catalog import reload_catalog
    from backend.db.engine import get_session
    from backend.retail import workspace_seed
    from backend.services.data_builder import published_datasets

    problems: list[str] = []
    catalog = reload_catalog()
    if "retail_facility_month" not in catalog.names():
        problems.append("the governed catalogue does not hold "
                        "retail_facility_month")
    with get_session() as session:
        published = [d.name for d in published_datasets(session)]
        problems.extend(workspace_seed.check(session))
    if "retail_facility_month" not in published:
        problems.append("Data Builder does not publish retail_facility_month")
    from backend.retail import ews_portfolio, ews_score, readiness
    held = {str(d.get("name")) for d in _catalogue_datasets()}
    if ews_score.DOMAIN not in held:
        problems.append(
            f"{ews_score.DOMAIN} is not registered in the governed "
            "catalogue, so the Early Warning Score domain will not appear in "
            "Data Builder")
    from backend.retail import domains as retail_domains
    for view in retail_domains.DERIVED:
        if view.dataset not in held:
            problems.append(
                f"{view.dataset} is not registered in the governed "
                f"catalogue, so {view.domain} will not appear in Data Builder")

    # Everything above is about files. None of it was ever about the thing a
    # person opens. A fresh install reported itself ready while the Early
    # Warning screen read "The Early Warning Score domain could not be read":
    # twenty partitions on disk, the domain in the catalogue file, Data
    # Builder synced — and a server exposing no /retail/ews route at all,
    # because the process answering requests had been started before any of it
    # existed. So the application is asked directly: its routing table, its
    # endpoints, and the server actually listening on API_PORT if there is one.
    problems.extend(readiness.check())
    scored = ews_portfolio._panel_months()
    if not scored:
        problems.append("the early-warning panel has not been built, so "
                        "Early Warning opens on an empty state")
    else:
        published_months = ews_portfolio._months()
        if len(scored) < len(published_months):
            problems.append(
                f"the early-warning panel covers {len(scored)} of the "
                f"{len(published_months)} published months")

    # The demonstration content, counted rather than assumed. A readiness
    # check that stops at the datasets reports READY for an installation
    # whose Workspace, Analyses, Investigations, Documents and Lenses screens
    # are all empty — which is what a presenter actually opens.
    #
    # Counted against the seed definitions, so the floor moves with them
    # rather than being a number typed here that goes stale the first time a
    # project is added.
    from sqlalchemy import func, select

    from backend.models.platform import (
        Document,
        Investigation,
        Lens,
        Project,
        SavedAnalysis,
    )
    from backend.retail import seed_catalogue, seed_documents, seed_lenses
    from backend.retail import seed_threads
    from backend.retail.seed_workspace import KEY

    wanted = {
        "projects": (Project, len(seed_catalogue.PROJECTS)),
        "saved analyses": (SavedAnalysis, len(seed_catalogue.ANALYSES)),
        "investigations": (Investigation, len(seed_threads.all_threads())),
        "documents": (Document, len(seed_documents.PAPERS)),
        "lenses": (Lens, len(seed_lenses.LENSES)),
    }
    with get_session() as session:
        for label, (model, floor) in wanted.items():
            held = session.execute(
                select(func.count()).select_from(model)).scalar() or 0
            if held < floor:
                problems.append(
                    f"the {label} screen holds {held} of the {floor} this "
                    f"release seeds, so it opens thin or empty")
        # A seeded object whose figures were computed against a different
        # book is worse than a missing one: it is on screen, it looks
        # current, and it disagrees with the analysis beside it.
        from backend.retail import measures

        every = measures.months()
        now = measures.stamp(every[-1]).get("source_hash", "") if every else ""
        if now:
            stale = session.execute(
                select(func.count()).select_from(SavedAnalysis)
                .where(SavedAnalysis.params[KEY].astext.isnot(None))
                .where(SavedAnalysis.data_versions["source_hash"].astext
                       != now)).scalar() or 0
            if stale:
                problems.append(
                    f"{stale} seeded analyses were computed against an "
                    f"older book than the one published now ({now[:12]}); "
                    f"re-run the bootstrap to refresh them")

    from backend.retail import challenger_registry

    if challenger_registry.held() is None:
        problems.append(
            "no What-If challenger artifact is stored, so the XGBoost model "
            "page has no model to describe and the first scenario that asks "
            "for the challenger pays to fit one")
    elif challenger_registry.stale():
        problems.append(
            "the stored What-If challenger was fitted on a different book "
            "than the one published now")

    for item in problems:
        log.warning("Still missing: %s", item)
    if problems:
        log.warning("")
        log.warning("Run this script without --check to seed what is missing.")
        return 1
    log.info("The retail installation is ready to demonstrate.")
    return 0


def _catalogue_datasets() -> list:
    """What the governed catalogue holds, read rather than assumed."""
    import json
    import os

    from backend.config import settings

    path = Path(os.environ.get("METADATA_DIR") or settings.metadata_dir) \
        / "catalog.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("datasets") or []


if __name__ == "__main__":
    raise SystemExit(main())
