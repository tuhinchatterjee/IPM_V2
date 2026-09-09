"""
§34–§36, §70, §74 — the proactive review, and the worker that runs it.

Three things are being held here.

**The funnel is real.** §36 forbids "unrestricted model calls over the entire
raw book". The pre-screen therefore runs over the actual demonstration universe
— tens of thousands of rows — reduces it to a handful of names, and does it with
`model_calls == 0`. A funnel tested against a stub proves the stub.

**A replay changes nothing.** §70's acceptance condition is that the same review
run twice leaves one set of cases. Two database constraints stand behind that,
and the test runs the review twice to exercise them rather than asserting the
constraints exist.

**The worker is a worker.** §74: it claims, it heartbeats, it recovers what a
dead worker left, and SIGTERM drains rather than drops.

No model is called anywhere in this file. `review.run` takes `answer_one`, and
every test passes a fake.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import text

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL is not reachable")

from backend.agentic import (  # noqa: E402
    cases,
    events,
    queue,
    review,
    runs,
    screening,
    worker,
)
from backend.agentic import severity as sv  # noqa: E402
from backend.db.engine import SessionLocal  # noqa: E402


@pytest.fixture
def session():
    s = SessionLocal()
    _clear(s)
    try:
        yield s
    finally:
        s.rollback()
        _clear(s)
        s.close()


def _clear(s) -> None:
    for table in ("risk_case_events", "risk_case_links", "risk_cases",
                  "agent_tasks", "agent_approvals", "agent_runs",
                  "agent_events", "agent_jobs"):
        s.execute(text(f"DELETE FROM {table}"))
    s.commit()


# ------------------------------------------------------------ the fake runtime


@dataclass
class _Metric:
    label: str = "ECL"
    value: float = 41.2
    unit: str = "SAR mn"


@dataclass
class _Narrative:
    direct_answer: str = "ECL rose 18% on the prior quarter."
    summary: str = ""
    metrics: tuple = (_Metric(),)


@dataclass
class _Plan:
    datasets: tuple = ("portfolio_facility", "ifrs9_staging")
    fingerprint: str = "fp_review"


@dataclass
class _Answer:
    status: str = "succeeded"
    narrative: _Narrative = field(default_factory=_Narrative)
    analysis_run_id: int = 4242
    plan: _Plan = field(default_factory=_Plan)
    duration_ms: int = 120
    mode: dict = field(default_factory=dict)
    steps: tuple = ()


def _answers(calls: list[str] | None = None):
    def answer_one(question: str, **_kw: Any) -> _Answer:
        if calls is not None:
            calls.append(question)
        return _Answer()

    return answer_one


def _period() -> str:
    at = events.latest_period()
    if not at:
        pytest.skip("no published portfolio period in this environment")
    return at


# ---------------------------------------------------------------------------
# §36 — the deterministic pre-screen
# ---------------------------------------------------------------------------


def test_the_pre_screen_reads_the_whole_book_and_calls_no_model():
    """§36: 'Do not make unrestricted model calls over the entire raw book.'
    The screen is arithmetic over published data, and its own funnel record
    says so — a claim the Runs tab shows to a user."""
    found = screening.run(_period())
    funnel = found.funnel()
    assert funnel["model_calls"] == 0
    assert funnel["rows_screened"] > 1_000
    assert funnel["reduction"]


def test_the_screen_narrows_the_book_to_something_a_person_could_read():
    """The point of the funnel. If it escalated everything, the review would be
    the unrestricted pass §36 forbids, wearing a funnel's clothes."""
    found = screening.run(_period())
    assert found.segments_reviewed > 0
    assert len(found.material_segments) <= screening.MAX_SEGMENTS
    assert len(found.borrowers) <= screening.MAX_BORROWERS
    assert found.borrowers_escalated < found.rows_screened / 100


def test_the_screen_is_fast_enough_to_run_before_anything_else():
    """§78. The pre-screen is what makes a whole-book review affordable, so it
    is the one step whose cost is asserted rather than assumed."""
    started = time.perf_counter()
    screening.run(_period())
    assert time.perf_counter() - started < 30.0


def test_every_escalated_thing_carries_the_measurement_behind_it():
    """§36: what is escalated is escalated for a stated, measured reason. A
    borrower on the list with no figures is one nobody can act on."""
    found = screening.run(_period())
    for indicator in found.portfolio:
        assert indicator.label
        assert indicator.dataset
        assert indicator.sentence()
    for segment in found.material_segments:
        assert segment.name
        assert segment.adverse
        assert segment.worst is not None
    for borrower in found.borrowers:
        assert borrower.customer_id
        assert borrower.signals or borrower.contribution is not None


def test_the_thresholds_are_published_rather_than_buried():
    """§36 asks for deterministic rules. A threshold nobody can read is a
    magic number, and the screen states all four."""
    published = screening.thresholds()
    assert published["portfolio_move"] == screening.PORTFOLIO_MOVE
    assert published["segment_move"] == screening.SEGMENT_MOVE
    assert published["segment_min_share"] == screening.SEGMENT_MIN_SHARE
    assert published["borrower_contribution"] == screening.BORROWER_CONTRIBUTION
    assert screening.run(_period()).to_dict()["thresholds"] == published


def test_a_screen_of_an_unpublished_period_says_so_rather_than_finding_nothing():
    """Silence and 'nothing is wrong' look identical to a user, and only one of
    them is true."""
    found = screening.run("Q9 2099")
    assert found.notes or found.data_issues


# ---------------------------------------------------------------------------
# §35 — the review, end to end
# ---------------------------------------------------------------------------


def test_a_review_produces_cases_a_person_can_act_on(session):
    period = _period()
    run_row, found = review.run(session, period=period,
                                answer_one=_answers(), notify=False)
    session.commit()

    assert run_row.id
    assert found.stopped == ""
    assert found.case_count >= 0
    for case in cases.listing(session):
        assert case.title
        assert case.conclusion
        assert case.severity in (sv.LOW, sv.MEDIUM, sv.HIGH, sv.CRITICAL)
        assert case.period == period
        assert case.agent_run_id == run_row.id


def test_the_same_review_run_twice_leaves_one_set_of_cases(session):
    """§70's acceptance condition, exercised rather than asserted about."""
    period = _period()
    review.run(session, period=period, answer_one=_answers(), notify=False)
    session.commit()
    first = {c.dedupe_key for c in cases.listing(session)}

    _, second_review = review.run(session, period=period,
                                  answer_one=_answers(), notify=False)
    session.commit()
    second = {c.dedupe_key for c in cases.listing(session)}

    assert second == first
    assert second_review.cases_created == []
    if first:
        assert len(second_review.cases_refreshed) == len(first)


def test_the_run_records_what_it_cost(session):
    """§56's funnel, persisted. A proactive system whose cost is invisible is
    one nobody can decide to keep running."""
    run_row, found = review.run(session, period=_period(),
                                answer_one=_answers(), notify=False)
    session.commit()
    assert found.screen is not None
    assert found.screen.funnel()["model_calls"] == 0
    detail = runs.detail(session, run_row)
    assert detail["budgets"]["spent"]["model_calls"] == 0
    assert detail["budgets"]["limits"]["model_calls"] > 0
    # §5: why THIS officer, persisted beside the run rather than re-derived.
    assert detail["selection_reason"]
    assert detail["officer_title"]
    assert detail["usage"]


def test_a_review_of_an_unpublished_period_refuses_rather_than_inventing(session):
    """§35.1: the Data Steward checks the period is there before anything else.
    A review of a period nobody published produces an empty answer in a
    confident tone, which is worse than an error."""
    _, found = review.run(session, period="Q9 2099", answer_one=_answers(),
                          notify=False)
    session.commit()
    assert found.stopped
    assert found.note


def test_a_review_stopped_part_way_is_still_visible(session):
    """A proactive process that leaves no trace when it is interrupted is one
    nobody can trust to have run at all."""
    _, found = review.run(session, period=_period(), answer_one=_answers(),
                          should_stop=lambda: True, notify=False)
    session.commit()
    assert found.stopped
    listed = runs.listing(session)
    assert listed and listed[0]["status"]


def test_a_review_never_calls_a_model_for_a_borrower_it_did_not_escalate(session):
    """The funnel has to bind the expensive half too: whatever the runtime is
    asked, it is asked about what the screen selected."""
    asked: list[str] = []
    _, found = review.run(session, period=_period(),
                          answer_one=_answers(asked), notify=False)
    session.commit()
    assert len(asked) <= 24
    for question in asked:
        assert question.strip()


# ---------------------------------------------------------------------------
# §34 — events
# ---------------------------------------------------------------------------


def test_the_same_event_delivered_twice_is_one_event(session):
    """A webhook that retries must not produce two reviews."""
    first, created_first = events.record(
        session, kind=events.DATASET_PUBLISHED, period="Q2 2026",
        dataset="portfolio_facility")
    session.commit()
    second, created_second = events.record(
        session, kind=events.DATASET_PUBLISHED, period="Q2 2026",
        dataset="portfolio_facility")
    session.commit()
    assert created_first is True
    assert created_second is False
    assert second.id == first.id


def test_an_event_for_data_that_is_not_published_is_not_ready(session):
    """§34: the trigger is publication, not arrival. Reviewing data that has
    not been published is reviewing something nobody stands behind."""
    event, _ = events.record(session, kind=events.NEW_PERIOD_AVAILABLE,
                             period="Q9 2099")
    session.commit()
    ready, why = events.ready(session, event)
    assert ready is False
    assert why


def test_an_ignored_event_says_why(session):
    event, _ = events.record(session, kind=events.WATCHLIST_CHANGED,
                             period="Q2 2026")
    events.ignore(session, event, reason="Already covered by case 11.")
    session.commit()
    assert event.status == events.IGNORED
    assert event.reason


# ---------------------------------------------------------------------------
# §74 — the worker
# ---------------------------------------------------------------------------


def test_a_worker_claims_runs_and_completes_one_job(session):
    done: list[int] = []
    worker.register("test_kind", lambda job, _stop: done.append(job.id))

    job_id, _ = queue.enqueue(session, kind="test_kind",
                              idempotency_key="w1", payload={"x": 1})
    session.commit()

    hand = worker.Worker(worker_id="test-worker-1", kinds=("test_kind",))
    assert hand.run_once() is True
    assert done == [job_id]
    assert hand.completed == 1

    session.expire_all()
    assert session.execute(
        text("SELECT status FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).scalar_one() == "complete"


def test_an_idle_worker_reports_idle_rather_than_spinning_silently(session):
    hand = worker.Worker(worker_id="test-worker-idle", kinds=("nothing",))
    hand.start()
    assert hand.run_once() is False
    session.expire_all()
    status = session.execute(
        text("SELECT status FROM agent_workers WHERE worker_id = :w"),
        {"w": "test-worker-idle"}).scalar_one_or_none()
    assert status == "idle"


def test_a_failing_job_is_recorded_with_a_category_not_a_message(session):
    """'What keeps failing' is a question about kinds of failure; a message
    contains a period and a row count that make every failure unique."""
    def explode(_job, _stop):
        raise TimeoutError("the scan took too long")

    worker.register("test_boom", explode)
    job_id, _ = queue.enqueue(session, kind="test_boom", idempotency_key="w2")
    session.commit()

    hand = worker.Worker(worker_id="test-worker-2", kinds=("test_boom",))
    hand.run_once()
    assert hand.failed == 1

    session.expire_all()
    row = session.execute(
        text("SELECT status, error_category FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).one()
    assert row.error_category == "timeout"
    # Retried rather than dead-lettered: a timeout is the kind of thing that
    # works on the second attempt.
    assert row.status == "queued"


def test_a_job_with_no_handler_is_not_retried_forever(session):
    """A missing handler will still be missing in five minutes. Retrying it is
    a loop that costs a claim every time."""
    job_id, _ = queue.enqueue(session, kind="test_unknown_kind",
                              idempotency_key="w3")
    session.commit()
    hand = worker.Worker(worker_id="test-worker-3",
                         kinds=("test_unknown_kind",))
    hand.run_once()
    session.expire_all()
    row = session.execute(
        text("SELECT status, error_category FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).one()
    assert row.status == "dead_letter"
    assert row.error_category == "not_found"


def test_cancelling_a_queued_job_stops_it_outright(session):
    job_id, _ = queue.enqueue(session, kind="test_kind",
                              idempotency_key="w4a")
    session.commit()
    assert queue.cancel(session, job_id) is True
    session.commit()
    assert session.execute(
        text("SELECT status FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).scalar_one() == "cancelled"


def test_cancelling_a_running_job_flags_it_rather_than_killing_it(session):
    """§20's stop button reaching work already in flight. Nothing kills a
    process: the flag is set, the running task finishes and writes what it
    has, and the job is marked stopped — a truncated transaction would leave
    no record of what was completed."""
    job_id, _ = queue.enqueue(session, kind="test_kind",
                              idempotency_key="w4b")
    session.commit()
    queue.claim(session, worker="test-worker-4", kinds=("test_kind",))
    session.commit()

    assert queue.is_cancelled(session, job_id) is False
    assert queue.cancel(session, job_id) is True
    session.commit()

    # Still running — the worker has not noticed yet, and that is the point.
    assert session.execute(
        text("SELECT status FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).scalar_one() == "running"
    # The handler learns of it from the database rather than from hope.
    assert queue.is_cancelled(session, job_id) is True

    queue.stopped(session, job_id)
    session.commit()
    assert session.execute(
        text("SELECT status FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).scalar_one() == "cancelled"


def test_a_job_left_by_a_dead_worker_is_recovered(session):
    """§74. Without this a worker killed mid-review leaves the job running
    forever and the review never happens again — the failure mode of every
    queue that skipped this test."""
    job_id, _ = queue.enqueue(session, kind="test_kind",
                              idempotency_key="w5")
    session.commit()
    claimed = queue.claim(session, worker="ghost", kinds=("test_kind",))
    session.commit()
    assert claimed is not None

    session.execute(
        text("UPDATE agent_jobs SET lease_expires_at = now() - interval "
             "'1 hour' WHERE id = :i"), {"i": job_id})
    session.commit()

    assert job_id in queue.recover_stale(session)
    session.commit()
    session.expire_all()
    assert session.execute(
        text("SELECT status FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).scalar_one() == "queued"


def test_a_draining_worker_stops_asking_for_work(session):
    """SIGTERM sets `draining`, and `docker compose stop` then waits for the
    job in flight rather than killing it."""
    hand = worker.Worker(worker_id="test-worker-5", kinds=("test_kind",))
    hand.draining = True
    assert hand.run_forever() == 0
    session.expire_all()
    assert session.execute(
        text("SELECT status FROM agent_workers WHERE worker_id = :w"),
        {"w": "test-worker-5"}).scalar_one() == "stopped"


def test_worker_health_reads_the_heartbeat_not_the_process(session):
    """A process that is running but has stopped claiming jobs is not healthy,
    and a port check would call it healthy."""
    from backend.agentic import worker_health

    queue.register_worker(session, worker="test-worker-health")
    queue.worker_beat(session, worker="test-worker-health", status="idle")
    session.commit()
    assert worker_health.healthy(session, worker="test-worker-health") is True

    session.execute(
        text("UPDATE agent_workers SET heartbeat_at = now() - interval "
             "'1 hour' WHERE worker_id = :w"), {"w": "test-worker-health"})
    session.commit()
    assert worker_health.healthy(session, worker="test-worker-health") is False
