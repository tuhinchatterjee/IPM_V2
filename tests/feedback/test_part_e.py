"""
Part E — agentic health, truthful Requires Attention, and the governed
feedback loop. §134-§136, §148-§160.

The four sentences this part is built on
------------------------------------------
    §136: "Do not infer COMPLETED_NO_CASES from an empty case table."
    §149: "Do not claim immediate learning."
    §154: "Do not automatically mark the user correct or the system wrong."
    §158: "Component validation scores must not be raw Good/Bad percentages."

Each is a place where the convenient behaviour is a lie a user would believe.
An empty case table reads as a clean portfolio. A thank-you that promises
learning buys goodwill with a claim that will be contradicted. An automatic
triage that closes its own finding is a system agreeing with itself. A thumbs
percentage measures who bothered to click, which is overwhelmingly people who
were annoyed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.agentic import health as ah
from backend.feedback import components as fc
from backend.feedback import schema as fs

# ================================================== §135 the health model


def test_the_four_state_machines_section_135_names_are_all_present():
    assert len(ah.WORKER_STATES) == 5
    assert len(ah.QUEUE_STATES) == 4
    assert len(ah.SCHEDULER_STATES) == 4
    assert len(ah.REVIEW_STATES) == 9


def test_every_review_state_says_what_it_means_and_what_to_do():
    """NOT_RUN, STALLED, DISABLED and STALE all mean "nothing current has
    been checked" to a reader. They are kept apart because the fix differs,
    and a single "unavailable" would leave somebody guessing which."""
    for state in ah.REVIEW_STATES:
        means, action = ah.REVIEW_MEANS[state]
        assert means.strip(), state
    assert ah.REVIEW_MEANS[ah.NOT_RUN][1]
    assert ah.REVIEW_MEANS[ah.STALE][1]
    assert ah.REVIEW_MEANS[ah.REVIEW_FAILED][1]


def test_a_worker_that_has_not_beaten_is_offline_whatever_a_process_says():
    """The heartbeat is the only evidence that the worker can still reach the
    database and claim work, which is the thing "healthy" is meant to mean."""
    assert ah.worker_state(last_heartbeat=None) == ah.OFFLINE
    assert ah.worker_state(
        last_heartbeat=datetime.now(UTC) - timedelta(minutes=5)) == ah.OFFLINE
    assert ah.worker_state(
        last_heartbeat=datetime.now(UTC)) == ah.HEALTHY


def test_repeated_failures_are_degraded_rather_than_healthy():
    assert ah.worker_state(last_heartbeat=datetime.now(UTC),
                           consecutive_failures=3) == ah.DEGRADED


def test_work_waiting_while_a_worker_reports_healthy_is_stalled():
    """The one queue state that matters: the worker is alive and not picking
    work up, which every other combination of these numbers looks nothing
    like."""
    stalled = ah.queue_state(depth=4, running=0, oldest_queued_age=1200,
                             worker=ah.HEALTHY)
    assert stalled == ah.STALLED

    busy = ah.queue_state(depth=4, running=2, oldest_queued_age=1200,
                          worker=ah.HEALTHY)
    assert busy == ah.ACTIVE

    # An offline worker with waiting work is not STALLED — it is an offline
    # worker, and saying "stalled" would send somebody to the wrong problem.
    assert ah.queue_state(depth=4, running=0, oldest_queued_age=1200,
                          worker=ah.OFFLINE) == ah.ACTIVE


def test_an_empty_queue_is_idle_not_healthy():
    assert ah.queue_state(depth=0, running=0, oldest_queued_age=0,
                          worker=ah.HEALTHY) == ah.IDLE


def test_completed_no_cases_is_never_inferred_from_an_empty_table():
    """§136's last line. With no run there is no state but NOT_RUN, however
    empty the case table is."""
    assert ah.review_state(run_status="", validated=True,
                           cases=0) == ah.NOT_RUN


def test_an_unvalidated_run_is_validating_however_many_cases_it_produced():
    assert ah.review_state(run_status="completed", validated=False,
                           cases=0) == ah.VALIDATING
    assert ah.review_state(run_status="completed", validated=False,
                           cases=9) == ah.VALIDATING


def test_only_a_validated_completed_run_may_say_the_book_is_clean():
    assert ah.review_state(run_status="completed", validated=True,
                           cases=0) == ah.COMPLETED_NO_CASES
    assert ah.review_state(run_status="completed", validated=True,
                           cases=3) == ah.COMPLETED_WITH_CASES


def test_an_unrecognised_run_status_is_not_a_completed_one():
    """Fails closed, the same way every other unknown in this product does."""
    assert ah.review_state(run_status="probably_fine", validated=True,
                           cases=0) == ah.REVIEW_FAILED


def test_a_stale_review_is_stale_whatever_it_found():
    assert ah.review_state(run_status="completed", validated=True, cases=5,
                           stale_reasons=["the data has changed"]) == ah.STALE


def test_staleness_names_the_axis_that_moved():
    reasons = ah.stale_because(review_data_version="v1",
                               current_data_version="v2",
                               review_sha="abc", current_sha="abc")

    assert reasons == ["the data has changed since the review"]


def test_an_axis_nobody_can_version_today_is_skipped():
    """Reporting "changed" from ignorance would make the check noise."""
    assert ah.stale_because(review_data_version="v1",
                            current_data_version="") == []


def test_the_worst_state_is_named_rather_than_averaged():
    """A healthy worker with a stalled queue is not "mostly fine"; it is a
    stalled queue, and the average hides the only thing anybody can act on."""
    health = ah.Health(worker_state=ah.HEALTHY, queue_state=ah.STALLED,
                       scheduler_state=ah.ENABLED,
                       latest_review_state=ah.COMPLETED_NO_CASES)

    assert health.worst == "queue STALLED"
    assert "STALLED" in health.sentence()


def test_a_healthy_worker_that_never_ran_a_review_is_not_operating():
    """§134's first gate condition. A worker that is healthy and has never
    picked up a job has not been shown to execute anything."""
    never = ah.Health(worker_state=ah.HEALTHY, queue_state=ah.IDLE,
                      latest_review_state=ah.NOT_RUN)

    assert never.operating is False

    ran = ah.Health(worker_state=ah.HEALTHY, queue_state=ah.IDLE,
                    latest_review_state=ah.COMPLETED_NO_CASES)
    assert ran.operating is True


def test_a_stale_review_is_not_reviewed_however_it_completed():
    health = ah.Health(latest_review_state=ah.COMPLETED_NO_CASES,
                       stale_reasons=["the build has changed"])

    assert health.reviewed is False


def test_the_health_payload_carries_every_field_section_135_names():
    payload = ah.Health().to_dict()

    for field_name in ("worker_state", "queue_state", "scheduler_state",
                       "latest_review_state", "worker_last_heartbeat",
                       "worker_version", "worker_build_sha", "queue_depth",
                       "oldest_queued_age", "running_jobs", "failed_jobs_24h",
                       "retrying_jobs", "dead_letter_jobs",
                       "scheduled_reviews_due", "scheduled_reviews_late",
                       "latest_review_id", "latest_review_scope",
                       "latest_review_data_version",
                       "latest_review_started_at",
                       "latest_review_completed_at",
                       "latest_review_duration",
                       "latest_review_case_counts",
                       "latest_review_validation_status",
                       "latest_review_error_category",
                       "latest_review_error_detail_safe",
                       "current_agentic_release", "current_teaching_release",
                       "model_configuration_fingerprint", "data_version",
                       "stale_reasons"):
        assert field_name in payload, field_name


# ================================================ §148-§152 the feedback object


def test_the_thank_you_does_not_claim_learning():
    """§149. "Thanks, I'll learn from that" is what every product says and it
    is almost always false — a claim that will be contradicted the next time
    the user asks the same question."""
    said = fs.acknowledgement(fs.GOOD)

    assert said == fs.THANKS
    assert "reviewed" in said
    for claim in ("learn", "learning", "learned", "improving now",
                  "immediately"):
        assert claim not in said.lower()
    assert fs.acknowledgement(fs.BAD) == said


def test_the_reason_lists_section_149_and_150_name_are_complete():
    assert len(fs.GOOD_REASONS) == 8
    assert len(fs.BAD_REASONS) == 18
    for code in (*fs.GOOD_REASONS, *fs.BAD_REASONS):
        assert fs.LABELS[code].strip(), code


def test_a_reason_nobody_defined_is_refused():
    """A distribution with an unbounded tail of one-off strings is not a
    distribution."""
    with pytest.raises(ValueError):
        fs.create(rating=fs.BAD, answer_id="a", reasons=["it_was_rubbish"])
    with pytest.raises(ValueError):
        # A GOOD reason on a BAD rating.
        fs.create(rating=fs.BAD, answer_id="a", reasons=["clear"])


def test_a_bad_rating_without_a_reason_is_recorded_rather_than_refused():
    """§150 says require or strongly encourage. Refusing loses the signal
    from the user who is annoyed and about to close the tab, and that user's
    annoyance is data."""
    given = fs.create(rating=fs.BAD, answer_id="a")

    assert given.reason_missing is True
    assert given.status == fs.NEW


def test_a_comment_carrying_a_credential_is_refused():
    """The most common way a key reaches a database is somebody pasting a
    failing curl command into a free-text box, and the box accepting it."""
    for pasted in ("here is my key sk-ant-api03-abcdefgh",
                   "Authorization: Bearer abcdefghijklmnop",
                   "api_key = something-secret"):
        with pytest.raises(fs.WouldStoreSecret):
            fs.create(rating=fs.BAD, answer_id="a", comment=pasted)


def test_a_payload_may_not_carry_a_forbidden_field_at_all():
    for forbidden in ("chain_of_thought", "gold_answer", "raw_rows",
                      "api_key"):
        with pytest.raises(fs.WouldStoreSecret):
            fs.create(rating=fs.GOOD, answer_id="a",
                      **{forbidden: "anything"})


def test_feedback_with_no_run_or_build_is_an_opinion_not_a_bug_report():
    opinion = fs.create(rating=fs.BAD, answer_id="a",
                        reasons=["wrong_numbers"])
    assert opinion.reproducible is False

    report = fs.create(rating=fs.BAD, answer_id="a",
                       reasons=["wrong_numbers"],
                       analysis_run_id="run-1", build_sha="abc123")
    assert report.reproducible is True


def test_nothing_may_jump_from_new_to_released():
    """An item that could is an item that changed production without being
    reviewed, which is the one thing this whole mechanism exists to
    prevent."""
    assert fs.may_move(fs.NEW, fs.RELEASED) is False
    assert fs.may_move(fs.NEW, fs.TRIAGED) is True
    assert fs.may_move(fs.TRIAGED, fs.FIXED) is False
    assert fs.may_move(fs.FIXED, fs.RELEASED) is True


def test_every_status_can_be_reached_and_released_is_terminal():
    reachable = {fs.NEW}
    for _ in range(len(fs.STATUSES)):
        for status in list(reachable):
            reachable.update(fs.TRANSITIONS[status])
    assert reachable == set(fs.STATUSES)
    assert fs.TRANSITIONS[fs.RELEASED] == ()


def test_an_unadjudicated_item_is_not_adjudicated_however_far_it_moved():
    item = fs.create(rating=fs.BAD, answer_id="a", reasons=["wrong_numbers"])
    item.status = fs.ADJUDICATED

    assert item.adjudicated is False

    item.reviewer = "model risk"
    assert item.adjudicated is True


# ==================================================== §153, §154 attribution


def test_the_twenty_components_section_159_names_are_all_present():
    assert len(fc.COMPONENTS) == 20
    for component in fc.COMPONENTS:
        assert component.isupper()


def test_a_reason_suggests_components_rather_than_naming_a_culprit():
    """"wrong numbers" usually means the query and sometimes means the
    ontology, and only a person who reproduced it knows which."""
    item = fs.create(rating=fs.BAD, answer_id="a", reasons=["wrong_numbers"])

    suggested = fc.triage(item)

    assert set(suggested.components) == {fc.QUERY, fc.RESULT, fc.INVARIANTS}
    assert suggested.to_dict()["advisory_only"] is True
    assert suggested.to_dict()["requires_adjudication"] is True


def test_triage_never_marks_the_user_correct_or_the_system_wrong():
    """§154, checked on the payload rather than on the prose."""
    item = fs.create(rating=fs.BAD, answer_id="a", reasons=["wrong_numbers"],
                     analysis_run_id="r", build_sha="abc")

    payload = fc.triage(item).to_dict()

    assert "verdict" not in payload
    assert "system_wrong" not in payload
    assert "user_correct" not in payload
    assert payload["confidence"] <= 1.0


def test_a_reasonless_bad_is_a_weaker_signal_rather_than_no_signal():
    with_reason = fc.triage(fs.create(rating=fs.BAD, answer_id="a",
                                      reasons=["unsupported_claim"],
                                      build_sha="abc",
                                      analysis_run_id="r"))
    without = fc.triage(fs.create(rating=fs.BAD, answer_id="a",
                                  build_sha="abc", analysis_run_id="r"))

    assert without.confidence < with_reason.confidence
    assert "no reason was given" in " ".join(without.evidence)


def test_a_grounding_complaint_is_high_severity():
    item = fs.create(rating=fs.BAD, answer_id="a",
                     reasons=["unsupported_claim"])

    assert fc.triage(item).severity == "HIGH"


def test_good_feedback_has_no_severity():
    assert fc.triage(fs.create(rating=fs.GOOD,
                               answer_id="a")).severity == "NONE"


# ============================================== §158, §159 the two numbers


def test_raw_feedback_says_it_is_not_a_validation_score():
    """It measures who bothered to click, which is overwhelmingly people who
    were annoyed — and agreement, which is not correctness."""
    raw = fc.RawFeedback(answers=1000, rated=40, good=25, bad=15,
                         reasons={"wrong_numbers": 9})

    payload = raw.to_dict()
    assert payload["is_a_validation_score"] is False
    assert payload["feedback_rate"] == 0.04
    assert "annoyed" in payload["note"]


def test_a_component_score_is_not_derived_from_thumbs():
    score = fc.Score(fc.GROUNDING, passed=190, total=200,
                     last_evaluation="2026-08-01", release="rel-3")

    payload = score.to_dict()
    assert payload["derived_from_thumbs"] is False
    assert payload["observed"]["total"] == 200
    assert payload["supported_lower_bound"] is not None


def test_a_component_with_too_few_cases_has_insufficient_evidence():
    """Not a grade. There is not enough evidence to grade it, which is a
    different statement and the honest one far more often."""
    score = fc.Score(fc.TRACE, passed=8, total=8)

    assert score.status == fc.INSUFFICIENT
    assert "too few cases" in score.sentence()


def test_a_critical_failure_overrides_a_good_component_rate():
    score = fc.Score(fc.GROUNDING, passed=199, total=200,
                     critical_failures=["thread F reported an uncited "
                                        "figure"])

    assert score.status == fc.FAILED
    assert "overrides the average" in score.sentence()


def test_adjudicated_feedback_failures_degrade_a_component():
    """An adjudicated failure is evidence. An unreviewed thumb is not, and
    does not appear here at all."""
    clean = fc.Score(fc.INTERPRETATION, passed=195, total=200)
    assert clean.status == fc.HEALTHY

    degraded = fc.Score(fc.INTERPRETATION, passed=195, total=200,
                        adjudicated_failures=2)
    assert degraded.status == fc.DEGRADED


def test_a_stale_component_score_is_stale_whatever_it_measured():
    score = fc.Score(fc.PLAN, passed=200, total=200,
                     stale_reasons=["the ontology has changed"])

    assert score.status == fc.STALE
    assert "since changed" in score.sentence()


# ================================================== §160 how a score moves


def _score(**over):
    base = dict(component=fc.GROUNDING, passed=190, total=200)
    base.update(over)
    return fc.Score(**base)


def test_a_score_may_not_move_without_all_five_conditions():
    """The permissive version — record the change and note that it was
    ungoverned — produces a score history in which the governed and
    ungoverned entries look identical a month later."""
    previous, new = _score(), _score(passed=198)

    for kwargs in ({"evaluation_completed": False},
                   {"reviewer": ""},
                   {"reason": ""},
                   {"release": ""}):
        with pytest.raises(fc.NotGoverned):
            fc.move(fc.GROUNDING, previous=previous, new=new,
                    **{"reason": "fix", "reviewer": "model risk",
                       "evaluation_completed": True, "release": "rel-4",
                       **kwargs})


def test_a_governed_move_records_everything_section_160_asks_for():
    moved = fc.move(fc.GROUNDING, previous=_score(), new=_score(passed=198),
                    reason="the uncited-figure defect was fixed and the "
                           "regression passes",
                    reviewer="model risk", evaluation_completed=True,
                    release="rel-4")

    payload = moved.to_dict()
    for field_name in ("previous_score", "new_score", "case_set_delta",
                       "failure_delta", "release_delta", "reason",
                       "reviewer"):
        assert field_name in payload, field_name
    assert payload["new_score"] > payload["previous_score"]
    assert moved.at


def test_a_score_may_not_move_for_a_component_nobody_defined():
    with pytest.raises(KeyError):
        fc.move("VIBES", previous=_score(), new=_score(),
                reason="x", reviewer="y", evaluation_completed=True,
                release="z")


# ============================================ §156 good feedback is not gold


def test_good_feedback_is_not_automatically_a_teaching_case():
    """The commonest condition to skip is redaction, because a good answer
    about a real borrower is a good answer containing a real borrower."""
    item = fs.create(rating=fs.GOOD, answer_id="a", reasons=["correct"])
    item.status = fs.ADJUDICATED
    item.reviewer = "credit risk sme"

    ok, missing = fc.promotable(item, validations_passed=True,
                                redacted=False, has_regression=True)

    assert ok is False
    assert any("redact" in m for m in missing)


def test_good_feedback_with_every_condition_met_may_be_promoted():
    item = fs.create(rating=fs.GOOD, answer_id="a", reasons=["correct"])
    item.status = fs.ADJUDICATED
    item.reviewer = "credit risk sme"

    ok, missing = fc.promotable(item, validations_passed=True,
                                redacted=True, has_regression=True)

    assert ok is True
    assert missing == []


def test_unreviewed_good_feedback_may_not_be_promoted():
    item = fs.create(rating=fs.GOOD, answer_id="a", reasons=["correct"])

    ok, missing = fc.promotable(item, validations_passed=True,
                                redacted=True, has_regression=True)

    assert ok is False
    assert any("reviewer" in m for m in missing)


# ======================================================= over HTTP


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def _admin() -> dict[str, str]:
    return {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}


def test_the_health_route_answers_with_all_four_states(client):
    response = client.get("/api/v1/agentic/health", headers=_admin())

    assert response.status_code == 200
    body = response.json()
    assert body["worker_state"] in ah.WORKER_STATES
    assert body["queue_state"] in ah.QUEUE_STATES
    assert body["scheduler_state"] in ah.SCHEDULER_STATES
    assert body["latest_review_state"] in ah.REVIEW_STATES
    assert body["sentence"]


def test_the_health_route_never_claims_a_clean_book_without_a_review(client):
    """§136's last line, at the route. With no completed validated review the
    state may not be COMPLETED_NO_CASES, whatever the case table holds."""
    body = client.get("/api/v1/agentic/health", headers=_admin()).json()

    if body["latest_review_state"] == ah.COMPLETED_NO_CASES:
        assert body["latest_review_id"] is not None
        assert body["latest_review_completed_at"]
    else:
        assert body["reviewed"] is False or body["latest_review_id"]


def test_the_health_route_leaks_nothing(client):
    text = client.get("/api/v1/agentic/health", headers=_admin()).text.lower()

    for forbidden in ("sk-ant", "authorization:", "password", "traceback",
                      "sqlalchemy.exc"):
        assert forbidden not in text


def test_the_feedback_control_is_open_to_every_signed_in_role(client):
    """§148: after EVERY response. The people most likely to notice a wrong
    answer are the analysts who read them all day, not the administrators who
    read the Studio."""
    for role in ("ADMIN", "DATA_STEWARD", "ANALYST", "VIEWER"):
        headers = {"X-IPM-Role": role, "X-IPM-User-Id": "2"}
        response = client.post(
            "/api/v1/feedback", headers=headers,
            json={"rating": "GOOD", "answer_id": "a1",
                  "reason_codes": ["correct"]})
        assert response.status_code == 201, role


def test_the_acknowledgement_the_route_returns_promises_only_review(client):
    body = client.post(
        "/api/v1/feedback", headers=_admin(),
        json={"rating": "BAD", "answer_id": "a1",
              "reason_codes": ["wrong_numbers"],
              "analysis_run_id": "run-1"}).json()

    assert body["acknowledgement"] == fs.THANKS
    assert body["changes_production"] is False
    assert body["triage"]["advisory_only"] is True


def test_the_route_refuses_a_comment_carrying_a_credential(client):
    response = client.post(
        "/api/v1/feedback", headers=_admin(),
        json={"rating": "BAD", "answer_id": "a1",
              "comment": "it failed with key sk-ant-api03-abcdefgh"})

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "would_store_secret"


def test_the_route_refuses_a_reason_nobody_defined(client):
    response = client.post(
        "/api/v1/feedback", headers=_admin(),
        json={"rating": "BAD", "answer_id": "a1",
              "reason_codes": ["it_was_rubbish"]})

    assert response.status_code == 422


def test_the_options_route_is_the_single_source_of_the_reason_lists(client):
    """Two lists in two places become two different lists, and the one users
    see will be the stale one."""
    body = client.get("/api/v1/feedback/options", headers=_admin()).json()

    assert [r["code"] for r in body["reasons"]["GOOD"]] == \
        list(fs.GOOD_REASONS)
    assert [r["code"] for r in body["reasons"]["BAD"]] == list(fs.BAD_REASONS)
    assert body["acknowledgement"] == fs.THANKS


def test_the_workflow_route_is_administrator_only(client):
    refused = client.get("/api/v1/feedback/workflow",
                         headers={"X-IPM-Role": "ANALYST",
                                  "X-IPM-User-Id": "2"})
    assert refused.status_code == 403

    allowed = client.get("/api/v1/feedback/workflow", headers=_admin())
    assert allowed.status_code == 200
    assert allowed.json()["no_automatic_self_training"] is True


def test_the_components_route_keeps_the_two_numbers_apart(client):
    body = client.get("/api/v1/feedback/components", headers=_admin()).json()

    assert body["two_numbers"]["never_mixed"] is True
    assert len(body["score_moves_only_when"]) == 5
    assert len(body["components"]) == 20


# ============================================== §134 the agentic release gate


def test_the_eleven_conditions_section_134_names_all_ask_something():
    from backend.release import agentic_gate as ag

    assert len(ag.CONDITIONS) == 11
    for condition in ag.CONDITIONS:
        assert ag.ASKS[condition].endswith("?"), condition


def test_a_gate_with_nothing_supplied_is_not_ready():
    from backend.release import agentic_gate as ag

    result = ag.gate({})

    assert result.ready is False
    assert len(result.blocking) == 11


def test_a_healthy_worker_alone_does_not_satisfy_the_gate():
    """A worker that is healthy and has never picked up a job has not been
    shown to execute anything. A gate satisfied by a heartbeat would pass on
    the day the queue stopped being drained."""
    from backend.release import agentic_gate as ag

    healthy_but_idle = ah.Health(worker_state=ah.HEALTHY,
                                 queue_state=ah.IDLE,
                                 latest_review_state=ah.NOT_RUN)

    result = ag.from_health(healthy_but_idle)

    assert result.ready is False
    assert ag.WORKER_HEALTHY in result.blocking[0].condition
    for condition in ag.EXECUTION:
        assert result.get(condition).outcome == ag.FAIL


def test_an_agentic_layer_that_does_everything_is_ready():
    from backend.release import agentic_gate as ag

    working = ah.Health(worker_state=ah.HEALTHY, queue_state=ah.ACTIVE,
                        latest_review_state=ah.COMPLETED_WITH_CASES)

    result = ag.from_health(
        working, manual_completed=True, scheduled_completed=True,
        cases_cite_evidence=True, failed_runs_retryable=True,
        trace_consistent=True, approvals_enforced=True,
        feedback_linked=True, scores_governed=True)

    assert result.ready is True
    assert "genuinely executes" in result.sentence()


def test_duplicate_cases_from_a_repeated_review_block_the_gate():
    from backend.release import agentic_gate as ag

    working = ah.Health(worker_state=ah.HEALTHY, queue_state=ah.ACTIVE,
                        latest_review_state=ah.COMPLETED_WITH_CASES)

    result = ag.from_health(
        working, manual_completed=True, scheduled_completed=True,
        cases_cite_evidence=True, duplicate_cases=4,
        failed_runs_retryable=True, trace_consistent=True,
        approvals_enforced=True, feedback_linked=True, scores_governed=True)

    assert result.ready is False
    assert "4 duplicate case" in result.get(ag.IDEMPOTENT).detail


def test_the_agentic_gate_is_separate_from_the_intelligence_gate():
    """A product with excellent judgement and a dead worker answers every
    question well and never notices a deteriorating portfolio, which is
    precisely the failure Part E was written after."""
    from backend.release import agentic_gate as ag
    from backend.release import promotion as pr

    assert set(ag.CONDITIONS) & set(pr.CONDITIONS) == set()
