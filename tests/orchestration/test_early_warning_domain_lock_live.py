"""The Early Warning chat domain lock, exercised live over the real call
chain a browser actually drives — not just the dormant `validate_plan` unit
tests in `test_early_warning_domain_lock.py`.

A thread opened with `context={"domain": "early_warning"}` (exactly what an
EWS-scoped ask composer sends, see Part D) must have EVERY turn — its
opening question (`POST /investigations`, answered inline by
`backend.api.routers.hierarchy.start_thread`) and every follow-up
(`POST /investigations/{id}/messages`, via `backend.services.threads.ask`)
— refused the instant it names a certified analysis outside the Early
Warning dataset allow-list, on the SAME live path that answers every other
thread in the product.

This environment's registered legacy engine analyses (arrears_position,
portfolio_summary, ...) reference an older dataset-naming generation
(`facility_delinquency`, `portfolio_facility`, ...) that predates the
`corporate_*` Data Builder datasets actually published here — a pre-existing
gap unrelated to Early Warning, which means no non-EWS analysis can
actually SUCCEED in this environment regardless of the domain lock. That
rules out a positive control (a cross-domain question succeeding when
unlocked), so these tests assert the property that matters directly: with
the lock set, the certified route is refused BY THE LOCK ITSELF — captured
from the real log line `backend.orchestration.executor` emits at the one
choke point (`_run_certified`) — and the resulting turn never carries a
successfully-executed step against a non-EWS dataset. Without the lock, the
same request reaches the certified route and is never refused for a
domain reason, proving the gate is opt-in.

Requires a reachable PostgreSQL database; skips cleanly otherwise, following
the same `database_available()` convention as the rest of the suite.
"""

from __future__ import annotations

import logging

import pytest

from tests.conftest import database_available

CROSS_DOMAIN_QUESTION = "How much is in arrears?"
REFUSAL_LOGGER = "backend.orchestration.executor"


@pytest.fixture(autouse=True)
def _require_db():
    if not database_available():
        pytest.skip("no reachable database")


def _no_successful_non_ews_step(run: dict) -> bool:
    """No step in this turn's stored plan actually executed a non-EWS
    analysis — the property that matters: nothing was silently answered
    from another domain, whatever shape the refusal itself took."""
    from backend.orchestration import domain_lock as dl

    for step in (run.get("plan") or {}).get("steps") or []:
        analysis_id = step.get("analysis_id")
        if not analysis_id or analysis_id == "dynamic_analysis":
            continue
        datasets = set(dl.datasets_for(analysis_id))
        if datasets and not (datasets & dl.DOMAIN_DATASETS[dl.EARLY_WARNING]):
            return False
    return True


def test_certified_route_is_refused_by_domain_lock_on_thread_open(caplog):
    """The FIRST question of an EWS-scoped thread reaches the certified
    route and is refused there — before the certified analysis, which needs
    a non-EWS dataset, ever executes.

    Goes through `backend.api.routers.hierarchy.start_thread`'s own direct
    `agentic.run(...)` call, which answers the opening question inline
    (it does not go through `threads.ask`) — the exact gap this closes: a
    thread's very first turn is checked by the same lock as every later one.
    """
    from backend.services import threads

    with caplog.at_level(logging.INFO, logger=REFUSAL_LOGGER):
        thread = threads.create(
            question=CROSS_DOMAIN_QUESTION,
            context={"domain": "early_warning"},
        )
        from backend.agentic import interactive as agentic
        from backend.db.engine import get_session
        from backend.orchestration import conversation as cv
        from backend.orchestration import memory as wm

        with get_session() as session:
            officer = agentic.run(
                session, question=CROSS_DOMAIN_QUESTION,
                investigation_id=thread.id,
                state=cv.load(thread.context), memory=wm.load(thread.context),
                domain_lock=thread.context.get("domain"),
            )

    refusals = [r for r in caplog.records
                if "refused by domain_lock='early_warning'" in r.getMessage()]
    assert refusals, "expected the live certified route to log a domain_lock refusal"
    assert "arrears_position" in refusals[0].getMessage()

    result = officer.investigation.to_dict()
    assert _no_successful_non_ews_step(result["plan"])


def test_a_locked_thread_refuses_a_cross_domain_follow_up(caplog):
    """A thread opened on an in-domain question stays locked for follow-ups.

    Proves the lock is read from the THREAD's own stored context (set once,
    at creation) rather than re-derived per request, so a later turn cannot
    widen it — through the real `threads.ask` a browser's follow-up call
    actually reaches.
    """
    from backend.services import threads

    thread = threads.create(
        question="Which borrowers are Early Warning HIGH this period?",
        context={"domain": "early_warning"},
    )

    with caplog.at_level(logging.INFO, logger=REFUSAL_LOGGER):
        result = threads.ask(thread.id, CROSS_DOMAIN_QUESTION)

    refusals = [r for r in caplog.records
                if "refused by domain_lock='early_warning'" in r.getMessage()]
    assert refusals, "expected the follow-up to be refused by the thread's own lock"
    assert _no_successful_non_ews_step(result["run"]["plan"])


def test_an_unlocked_thread_is_not_refused_by_the_domain_lock(caplog):
    """Confirms the lock is opt-in end to end: a thread opened with no
    `domain` in its context reaches the same certified route with no
    domain-lock refusal logged, so this wiring narrows nothing for every
    other user."""
    from backend.services import threads

    thread = threads.create(question=CROSS_DOMAIN_QUESTION)

    with caplog.at_level(logging.INFO):
        threads.ask(thread.id, CROSS_DOMAIN_QUESTION)

    domain_refusals = [
        r for r in caplog.records
        if "backend.orchestration.executor" in r.name
        and "refused by domain_lock" in r.getMessage()
    ]
    assert not domain_refusals, domain_refusals
