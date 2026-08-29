"""
§7-§24 acceptance: feedback, observations, candidates, review, replay, local
models and Learning Releases.

The test this file exists for
------------------------------
    §11: RAW FEEDBACK CANNOT MODIFY Assurance status, Assurance score,
    Accuracy score, coverage, critical checks, plan fingerprint, result,
    certification, teaching release, production prompts, routing policy,
    model selection, ontology, methods.
    "Add source-level and runtime tests proving this."

Both are here. The source-level test runs the static guard over the whole
feedback path. The runtime test takes a real stored Assurance Record, submits
real feedback about it, and asserts the record is byte-identical afterwards —
because a static check can be defeated and an effect cannot.
"""

from __future__ import annotations

import uuid

import pytest

from backend.learning import candidate as cd
from backend.learning import feedback as fb
from backend.learning import guard as gd
from backend.learning import models as ml
from backend.learning import observation as ob
from backend.learning import preference as pref
from backend.learning import release as lr
from backend.learning import replay as rp
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="the learning service needs the database")


# ===================================================== §7 the prompt


def test_the_question_is_the_exact_words():
    """A question that drifts makes a satisfaction series uncomparable across
    the quarters it exists to be compared over."""
    assert fb.QUESTION == "Was this answer accurate and useful?"


def test_there_are_five_answers_and_they_are_the_named_ones():
    assert fb.ANSWERS == ("YES", "PARTLY", "NO", "NOT_SURE", "SKIP")
    for answer in fb.ANSWERS:
        assert fb.ANSWER_LABELS[answer]
        assert fb.ANSWER_MEANS[answer]


def test_partly_and_no_open_the_detail_panel_and_nothing_else_does():
    assert fb.WANTS_DETAIL == frozenset({fb.PARTLY, fb.NO})


def test_a_skip_is_recorded_and_is_not_a_rating():
    """A skipped prompt says the user saw the question and declined. Reading
    it as never having been asked makes the response rate meaningless."""
    assert fb.SKIP in fb.ANSWERS
    assert fb.SKIP not in fb.RATED
    assert len(fb.RATED) == 4


@pytest.mark.parametrize("state,expected", [
    ({"complete": False}, fb.RUNNING),
    ({"complete": True, "is_skeleton": True}, fb.SKELETON),
    ({"complete": True, "is_error": True}, fb.SYSTEM_ERROR),
    ({"complete": True, "dismissed": True}, fb.DISMISSED),
    ({"complete": True, "thread_muted": True}, fb.THREAD_OFF),
    ({"complete": True, "user_muted": True}, fb.USER_OFF),
    ({"complete": True, "already_answered": True}, fb.ALREADY_GIVEN),
])
def test_the_prompt_is_suppressed_where_seven_says_it_must_be(state, expected):
    found = fb.placement(**state)

    assert found.show is False
    assert found.because == expected


def test_the_prompt_appears_on_a_completed_answer():
    found = fb.placement(complete=True)

    assert found.show is True
    assert found.to_dict()["question"] == fb.QUESTION
    assert len(found.to_dict()["answers"]) == 5


def test_a_muted_user_is_told_that_rather_than_that_it_is_still_running():
    """The most specific state the caller is in wins. Telling somebody who
    turned prompts off that the answer is still running is a lie about their
    own settings."""
    found = fb.placement(complete=False, user_muted=True)

    assert found.because == fb.USER_OFF


# ===================================================== §8 issue categories


def test_there_are_twenty_three_issue_categories():
    assert len(fb.CATEGORY_IDS) == 23
    assert len(set(fb.CATEGORY_IDS)) == 23


def test_every_category_says_what_it_means():
    for name in fb.CATEGORY_IDS:
        assert fb.CATEGORY_LABELS[name]
        assert len(fb.CATEGORY_MEANS[name]) > 20


def test_the_categories_run_in_pipeline_order():
    """A user scanning the list should find the earliest thing that went
    wrong, not the most visible one: a wrong period PRODUCES a wrong result,
    and reporting the symptom loses the cause."""
    order = list(fb.CATEGORY_IDS)

    assert order.index("wrong_intent") < order.index("wrong_dataset")
    assert order.index("wrong_period") < order.index("wrong_result")
    assert order.index("wrong_calculation") < order.index(
        "wrong_interpretation")
    assert order[-1] == "other"


def test_an_unknown_category_is_refused_with_its_name():
    with pytest.raises(fb.FeedbackError) as caught:
        fb.create(rating=fb.NO, answer_id="a1", categories=["wrong_vibe"])
    assert "wrong_vibe" in str(caught.value)


def test_a_yes_with_a_list_of_what_went_wrong_is_two_different_answers():
    with pytest.raises(fb.FeedbackError):
        fb.create(rating=fb.YES, answer_id="a1", categories=["wrong_period"])


def test_feedback_needs_the_answer_it_is_about():
    with pytest.raises(fb.FeedbackError):
        fb.create(rating=fb.NO, answer_id="")


# ===================================================== §9, §10 the event


def test_a_credential_pasted_into_a_comment_is_scrubbed():
    event = fb.create(rating=fb.NO, answer_id="a1",
                      comment="it failed, my key is sk-ant-abcdefgh12345")

    assert "sk-ant" not in event.comment
    assert fb.REDACTED in event.comment


def test_an_event_carries_every_link_ten_asks_for():
    event = fb.create(
        rating=fb.PARTLY, answer_id="a1", categories=["wrong_period"],
        tenant="t", user_id="u", project_id="p", investigation_id="i",
        message_id="m", question="q", agentic_run_id="ar",
        plan_fingerprint="pf", assurance_record_id="as", build_sha="sha",
        officer_level=2, officer_title="Senior Credit Officer",
        agents=["ifrs9"])
    links = event.links()

    for name in ("tenant", "user", "project", "investigation", "message",
                 "question", "answer", "analysis_runs", "trace_version",
                 "agentic_run", "result_fingerprint", "officer_level",
                 "officer", "agents", "model_roles", "build_sha",
                 "data_versions", "method_versions", "plan_fingerprint",
                 "assurance_record", "rating", "categories", "consent", "at"):
        assert name in links, name
    assert len(links) >= 24


def test_a_revision_is_a_new_event_that_points_at_the_old_one():
    """§10: a subsequent edit creates a new version. A user who changes their
    mind has said two things and which came first is part of what they
    said."""
    first = fb.create(rating=fb.NO, answer_id="a1",
                      categories=["wrong_period"])
    second = fb.revise(first, rating=fb.PARTLY, comment="on reflection")

    assert second.event_id != first.event_id
    assert second.supersedes == first.event_id
    assert second.version == first.version + 1
    assert first.rating == fb.NO


def test_the_acknowledgement_never_promises_learning():
    """§25: do not promise "CreditProbe has learned this immediately"."""
    for rating in fb.ANSWERS:
        said = fb.acknowledgement(rating).lower()
        for promise in ("learned", "will remember", "now knows", "retrained"):
            assert promise not in said, rating


def test_positive_feedback_has_its_own_object():
    """§9's fields exist so a product metric can be measured, and live apart
    from anything that could be confused with an accuracy score."""
    found = fb.Satisfaction(satisfaction=5, trust=4, used_as=["exported"])

    assert found.to_dict()["satisfaction"] == 5
    assert "accuracy" not in str(found.to_dict())


def test_an_irreproducible_answer_is_marked_as_such():
    """A feedback item that records the rating and not the build is an
    opinion; with them it is a bug report somebody can reproduce."""
    thin = fb.create(rating=fb.NO, answer_id="a1")
    full = fb.create(rating=fb.NO, answer_id="a1", build_sha="sha",
                     plan_fingerprint="pf")

    assert thin.reproducible is False
    assert full.reproducible is True


# ===================================================== §29 consent


def test_consent_fails_closed_when_the_default_is_unknown():
    """A deployment that has not configured a default does not thereby
    consent on its users' behalf."""
    assert fb.may_learn_from(fb.CONSENT_UNSET) is False
    assert fb.may_learn_from(fb.CONSENT_UNSET,
                             default=fb.CONSENT_GRANTED) is True
    assert fb.may_learn_from(fb.CONSENT_REFUSED,
                             default=fb.CONSENT_GRANTED) is False


def test_the_consent_question_is_the_exact_sentence():
    assert fb.CONSENT_QUESTION == ("Use this feedback to improve this bank's "
                                   "CreditProbe")


# ============================================== §11 the guard, source level


def test_no_path_from_feedback_writes_to_protected_state():
    """§11, at source level. The static half of the proof.

    It can be defeated by anybody determined to defeat it. It is a guard
    against the honest mistake — the "trending down, lower the confidence"
    line somebody adds because it seems obviously right — which is the one
    that actually happens.
    """
    report = gd.report()

    assert report.ok, report.sentence()


def test_the_feedback_path_cannot_even_import_the_assurance_store():
    """The strongest check, and the cheapest: you cannot mutate a record you
    never imported. §35's link from a Feedback Event to an Assurance Record
    is an ID string, and that is the point."""
    assert "backend.assurance.store" in gd.FORBIDDEN_IMPORTS
    assert gd.imports() == []


def test_every_exemption_carries_a_reason():
    """An exemption nobody can see is a hole with a comment on it."""
    report = gd.report()

    for exemption in report.exempted:
        assert exemption["reason"], exemption
        assert len(exemption["reason"]) > 20


def test_the_guard_catches_a_write_it_is_meant_to_catch(tmp_path):
    """A guard nobody has seen fire is a guard nobody should trust."""
    module = tmp_path / "backend" / "services"
    module.mkdir(parents=True)
    (module / "learning.py").write_text(
        "def helpful(record):\n"
        "    record.overall_status = 'VALIDATED'\n", encoding="utf-8")

    findings = gd.audit(tmp_path, modules=("backend/services/learning.py",))

    assert len(findings) == 1
    assert findings[0].target == "overall_status"
    assert "Assurance status" in findings[0].protects


def test_the_guard_catches_a_forbidden_import(tmp_path):
    module = tmp_path / "backend" / "services"
    module.mkdir(parents=True)
    (module / "learning.py").write_text(
        "from backend.assurance import store\n", encoding="utf-8")

    findings = gd.imports(tmp_path, modules=("backend/services/learning.py",))

    assert len(findings) == 1
    assert findings[0].target == "backend.assurance.store"


def test_the_guard_catches_a_promise_of_learning(tmp_path):
    module = tmp_path / "backend" / "services"
    module.mkdir(parents=True)
    (module / "learning.py").write_text(
        'THANKS = "Thank you — CreditProbe has learned this."\n',
        encoding="utf-8")

    found = gd.promises(tmp_path, modules=("backend/services/learning.py",))

    assert len(found) == 1


def test_a_docstring_explaining_the_rule_is_not_a_promise(tmp_path):
    """The first version of this check reported the paragraph forbidding the
    promise, which would have taught the next person to delete the
    explanation rather than keep the rule."""
    module = tmp_path / "backend" / "services"
    module.mkdir(parents=True)
    (module / "learning.py").write_text(
        '"""Never say CreditProbe has learned this."""\n', encoding="utf-8")

    assert gd.promises(tmp_path,
                       modules=("backend/services/learning.py",)) == []


# ===================================================== §12 observations


def test_an_observation_with_no_feedback_is_unlabeled_not_satisfied():
    """§12: do not assume no feedback means satisfaction."""
    found = ob.Observation(question="q", build_sha="s", plan_fingerprint="p")

    assert found.label == ob.UNLABELED
    assert found.labelled is False
    assert "not approval" in ob.LABEL_MEANS[ob.UNLABELED]


def test_an_unlabeled_observation_may_be_replayed_and_may_not_teach():
    found = ob.Observation(question="q", build_sha="s", plan_fingerprint="p")

    for purpose in ob.UNLABELED_USES:
        ok, _ = found.may_be_used_for(purpose)
        assert ok, purpose
    for purpose in ob.FORBIDDEN_UNLABELED_USES:
        ok, why = found.may_be_used_for(purpose)
        assert ok is False
        assert "Silence is not approval" in why


def test_a_labelled_observation_may_become_teaching_truth():
    found = ob.Observation(question="q", build_sha="s", plan_fingerprint="p")
    ob.label(found, fb.create(rating=fb.NO, answer_id="a1"))

    assert found.label == ob.LABELED
    assert found.may_be_used_for(ob.TEACHING_TRUTH)[0] is True


def test_a_skip_labels_the_observation_declined_rather_than_labeled():
    found = ob.Observation(question="q")
    ob.label(found, fb.create(rating=fb.SKIP, answer_id="a1"))

    assert found.label == ob.DECLINED
    assert found.labelled is False


def test_an_observation_with_no_plan_cannot_be_replayed():
    found = ob.Observation(question="q")

    assert found.replayable is False
    ok, why = found.may_be_used_for(ob.REPLAY)
    assert ok is False
    assert "nothing to replay" in why


# ===================================================== §13 the two channels


def test_channel_a_is_a_closed_set():
    for name in pref.NAMES:
        values, default, what = pref.SETTINGS[name]
        assert values and default in values and what


def test_analytical_behaviour_cannot_be_set_as_a_preference():
    """"The user prefers less detail" is a preference. "The user prefers the
    shorter number" is analytical behaviour wearing a preference's clothes."""
    found = pref.Preference(user_id="u")

    for name in ("dataset", "method", "period", "grain", "officer", "model",
                 "threshold", "rounding"):
        with pytest.raises(pref.PreferenceError) as caught:
            pref.apply(found, name, "anything")
        assert "governed channel" in str(caught.value)


def test_a_value_outside_the_enumeration_is_refused_with_the_list():
    found = pref.Preference(user_id="u")

    with pytest.raises(pref.PreferenceError) as caught:
        pref.apply(found, "answer_length", "a paragraph of instructions")
    assert "brief" in str(caught.value)


def test_a_thread_can_be_muted():
    found = pref.Preference(user_id="u")
    pref.mute_thread(found, "thread-1")

    assert found.thread_muted("thread-1") is True
    assert found.thread_muted("thread-2") is False


def test_a_mixed_report_is_not_read_as_a_preference():
    """An answer that was too detailed AND used the wrong period is a
    correctness report, and reading the first half as a preference quietly
    discards the second."""
    mixed = fb.create(rating=fb.PARTLY, answer_id="a1",
                      categories=["too_much_detail", "wrong_period"])
    clean = fb.create(rating=fb.PARTLY, answer_id="a1",
                      categories=["too_much_detail"])

    assert pref.from_feedback(mixed) == []
    assert pref.from_feedback(clean) == [("answer_length", "brief")]


def test_a_presentation_preference_is_offered_and_not_applied():
    """A product that silently changes its own behaviour because somebody
    said "too much detail" once has made a decision the user did not."""
    event = fb.create(rating=fb.PARTLY, answer_id="a1",
                      categories=["too_much_detail"])
    found = pref.Preference(user_id="u")
    pref.from_feedback(event)

    assert found.get("answer_length") == "standard"


# ===================================================== §15 candidates


def test_there_are_nine_candidate_statuses():
    assert len(cd.STATUSES) == 9
    assert set(cd.STATUSES) == {
        "DRAFT", "AUTO_PROPOSED", "NEEDS_REVIEW",
        "SYSTEM_REFERENCE_VALIDATED", "HUMAN_REVIEWED", "HUMAN_APPROVED",
        "REJECTED", "RETIRED", "APPLIED_TO_RELEASE"}


def test_only_human_approved_may_enter_a_release():
    """A deterministic validation passing is not a person agreeing."""
    assert cd.RELEASABLE == frozenset({cd.HUMAN_APPROVED})
    assert cd.SYSTEM_REFERENCE_VALIDATED not in cd.RELEASABLE
    assert cd.HUMAN_REVIEWED not in cd.RELEASABLE


def test_an_unknown_status_permits_nothing():
    assert cd.may_move("SOMETHING", cd.HUMAN_APPROVED) is False


def test_retired_is_terminal():
    assert cd.TRANSITIONS[cd.RETIRED] == frozenset()


def _consented(**extra):
    return fb.create(rating=fb.NO, answer_id="a1",
                     categories=extra.pop("categories", ["wrong_period"]),
                     consent=fb.CONSENT_GRANTED, build_sha="sha",
                     plan_fingerprint="pf", **extra)


def test_a_yes_cannot_become_a_candidate():
    event = fb.create(rating=fb.YES, answer_id="a1",
                      consent=fb.CONSENT_GRANTED, build_sha="s",
                      plan_fingerprint="p")

    with pytest.raises(cd.CandidateError) as caught:
        cd.propose(event)
    assert "no claim that anything was wrong" in str(caught.value)


def test_feedback_without_consent_cannot_become_a_candidate():
    event = fb.create(rating=fb.NO, answer_id="a1", build_sha="s",
                      plan_fingerprint="p")

    with pytest.raises(cd.CandidateError) as caught:
        cd.propose(event)
    assert "without consent" in str(caught.value)


def test_feedback_about_an_irreproducible_answer_cannot_become_a_candidate():
    event = fb.create(rating=fb.NO, answer_id="a1",
                      consent=fb.CONSENT_GRANTED)

    with pytest.raises(cd.CandidateError) as caught:
        cd.propose(event)
    assert "cannot be reproduced" in str(caught.value)


def test_the_users_correction_is_never_copied_into_the_proposal():
    """§8: do not treat a user correction as automatically correct."""
    event = _consented(correction=fb.Correction(
        conclusion="it should have been Q2", preferred_period="Q2 2025"))
    case = cd.propose(event)

    assert case.user_correction["preferred_period"] == "Q2 2025"
    assert case.proposed_reading == {}
    assert case.proposed_plan == {}
    assert case.has_proposal is False


def test_a_candidate_with_no_proposal_cannot_be_approved():
    case = cd.propose(_consented())
    cd.move(case, cd.NEEDS_REVIEW)

    with pytest.raises(cd.CandidateError) as caught:
        cd.move(case, cd.HUMAN_APPROVED, reviewer="r", note="fine")
    assert "Approving it would approve nothing" in str(caught.value)


def test_an_approval_needs_a_reviewer_and_a_reason():
    case = cd.propose(_consented())
    cd.move(case, cd.NEEDS_REVIEW)
    case.proposed_reading = {"periods": ["Q2 2025"]}

    with pytest.raises(cd.CandidateError):
        cd.move(case, cd.HUMAN_APPROVED, reviewer="", note="fine")
    with pytest.raises(cd.CandidateError):
        cd.move(case, cd.HUMAN_APPROVED, reviewer="r", note="")


def test_a_rejection_needs_a_reason():
    case = cd.propose(_consented())

    with pytest.raises(cd.CandidateError):
        cd.move(case, cd.REJECTED, reviewer="r", note="")


def test_the_failure_class_is_the_earliest_thing_that_went_wrong():
    """A user who ticks "wrong period" and "wrong result" has reported one
    failure and its consequence. Routing it as a computation error sends a
    reviewer to check arithmetic that is correct."""
    assert cd.classify(["wrong_period", "wrong_result"]) == "scope"
    assert cd.classify(["wrong_intent", "wrong_calculation"]) == "reading"
    assert cd.classify(["wrong_result"]) == "computation"
    assert cd.classify([]) == "unclassified"


# ===================================================== §24 releases


def _approved(count: int = 1) -> list[cd.CandidateCase]:
    made = []
    for index in range(count):
        case = cd.propose(_consented())
        cd.move(case, cd.NEEDS_REVIEW)
        case.proposed_reading = {"periods": ["Q2 2025"]}
        cd.move(case, cd.HUMAN_APPROVED, reviewer=f"r{index}",
                note="the period was wrong")
        made.append(case)
    return made


def test_a_release_cannot_be_built_with_nothing_approved():
    case = cd.propose(_consented())

    with pytest.raises(lr.ReleaseError) as caught:
        lr.build([case], created_by="a")
    assert "no candidate has been approved" in str(caught.value)


def test_a_release_with_an_unrun_gate_cannot_be_activated():
    """A gate that did not run is not a gate that passed."""
    release = lr.build(_approved(), created_by="a")

    with pytest.raises(lr.ReleaseError) as caught:
        lr.activate(release, approver="cro")
    assert "did not run" in str(caught.value)


def test_a_release_that_breaks_a_critical_case_is_blocked():
    release = lr.build(_approved(), created_by="a")
    lr.evaluate(release, critical_before=0, critical_after=1,
                improved={"officer_accuracy": True}, safety_regressions=[],
                holdout_overlap=[])

    assert release.status == lr.BLOCKED
    with pytest.raises(lr.ReleaseError) as caught:
        lr.activate(release, approver="cro")
    assert "no_new_critical_failures" in str(caught.value)


def test_holdout_leakage_blocks_a_release():
    release = lr.build(_approved(), created_by="a")
    lr.evaluate(release, critical_before=0, critical_after=0,
                improved={"officer_accuracy": True}, safety_regressions=[],
                holdout_overlap=["case-7"])

    with pytest.raises(lr.ReleaseError) as caught:
        lr.activate(release, approver="cro")
    assert "holdout" in str(caught.value)


def test_a_release_that_improved_nothing_is_blocked():
    """A release that changed nothing measurable is a change nobody can
    defend."""
    release = lr.build(_approved(), created_by="a")
    lr.evaluate(release, critical_before=0, critical_after=0, improved={},
                safety_regressions=[], holdout_overlap=[])

    with pytest.raises(lr.ReleaseError):
        lr.activate(release, approver="cro")


def test_the_only_reviewer_cannot_approve_the_release():
    cases = _approved(1)
    release = lr.build(cases, created_by="a")
    lr.evaluate(release, critical_before=0, critical_after=0,
                improved={"officer_accuracy": True}, safety_regressions=[],
                holdout_overlap=[])

    with pytest.raises(lr.ReleaseError) as caught:
        lr.activate(release, approver="r0")
    assert "second pair of eyes" in str(caught.value)


def test_a_clean_release_activates_and_rolls_back():
    first = lr.build(_approved(2), created_by="a")
    lr.evaluate(first, critical_before=1, critical_after=0,
                improved={"officer_accuracy": True}, safety_regressions=[],
                holdout_overlap=[])
    lr.activate(first, approver="cro")
    assert first.status == lr.ACTIVE

    second = lr.build(_approved(2), created_by="a")
    lr.evaluate(second, critical_before=0, critical_after=0,
                improved={"grain_accuracy": True}, safety_regressions=[],
                holdout_overlap=[])
    lr.activate(second, approver="cro", current=first)

    assert second.status == lr.ACTIVE
    assert first.status == lr.ROLLED_BACK
    assert second.replaces == first.release_id

    lr.rollback(second, first, approver="cro", why="a regression in the wild")
    assert second.status == lr.ROLLED_BACK
    assert first.status == lr.ACTIVE


def test_an_unmeasured_metric_is_reported_as_unmeasured_not_zero():
    metrics = lr.Metrics(officer_accuracy=0.9)

    assert "officer_accuracy" in metrics.measured
    assert "independent_accuracy" in metrics.unmeasured
    assert metrics.to_dict()["independent_accuracy"] is None


def test_satisfaction_is_in_the_manifest_and_is_not_a_gate():
    """§23: do not activate a candidate merely because user satisfaction
    improved."""
    assert "satisfaction" in lr.Metrics().to_dict()
    assert not any("satisfaction" in name for name in lr.GATE_NAMES)


# ===================================================== §37 replay


def test_improvements_and_regressions_are_never_netted():
    run = rp.Run(cases=[
        rp.compare("c1", {"officer": 2}, {"officer": 3}),
        rp.compare("c2", {"officer": 3}, {"officer": 2},
                   expected={"officer": 2}),
    ])

    assert run.improved == 1
    assert run.regressed == 1
    assert "1 improved" in run.sentence()
    assert "1 regressed" in run.sentence()


def test_a_critical_regression_blocks_the_candidate():
    run = rp.Run(cases=[rp.compare("c1", {"result": {"total": 1}},
                                   {"result": {"total": 2}}, critical=True)])

    assert run.critical_regressions
    assert run.clean is False


def test_an_axis_one_side_did_not_record_is_unmeasured_not_unchanged():
    """Reporting an absence as agreement is how a comparison that measured
    nothing comes to read as a clean run."""
    found = rp.compare("c1", {"officer": 2}, {})
    axis = next(a for a in found.axes if a.axis == "officer")

    assert axis.verdict == rp.UNMEASURED
    assert axis.material is False


def test_a_reviewer_can_block_a_release_from_the_replay():
    run = rp.Run(cases=[rp.compare("c1", {"officer": 2}, {"officer": 2})])
    rp.block(run, reviewer="cro", why="the sample is not representative")

    assert run.clean is False
    assert "cro" in run.sentence()


# ===================================================== §20, §21 local models


def test_a_generative_credit_model_will_not_be_trained():
    for task in ("answer_generation", "interpretation", "risk_rating",
                 "pd_estimation", "ecl_calculation"):
        with pytest.raises(ml.ModelError) as caught:
            ml.start(task)
        assert "will not be trained here" in str(caught.value)


def test_the_task_set_is_closed_and_is_the_nine_named():
    assert len(ml.TASK_NAMES) == 9
    with pytest.raises(ml.ModelError) as caught:
        ml.start("something_useful")
    assert "The set is closed" in str(caught.value)


def test_an_artifact_with_a_client_identifier_is_refused():
    run = ml.start("officer_level")

    with pytest.raises(ml.ModelError) as caught:
        ml.seal(run, {"rows": [{"customer_id": "C1", "ead": 1}]})
    assert "client identifiers" in str(caught.value)
    assert run.status == ml.FAILED


def test_an_artifact_with_a_credential_is_refused():
    run = ml.start("officer_level")

    with pytest.raises(ml.ModelError):
        ml.seal(run, {"note": "api_key: sk-ant-abcdefgh12345"})


def test_a_model_that_does_not_beat_the_baseline_is_not_activated():
    run = ml.start("officer_level")
    ml.seal(run, {"weights": [1, 2]})
    run.metrics = {"accuracy": 0.80}
    run.baseline_metrics = {"accuracy": 0.83}
    run.critical_result = {"failures": []}

    with pytest.raises(ml.ModelError) as caught:
        ml.activate(run, approver="a")
    assert "worse than the deterministic baseline" in str(caught.value)


def test_a_model_that_wins_on_average_and_loses_a_component_is_not_activated():
    """An average that improves while a component gets worse is not an
    improvement — it is a trade nobody agreed to."""
    run = ml.start("officer_level")
    ml.seal(run, {"weights": [1]})
    run.metrics = {"accuracy": 0.95, "recall": 0.50}
    run.baseline_metrics = {"accuracy": 0.83, "recall": 0.70}
    run.critical_result = {"failures": []}

    with pytest.raises(ml.ModelError):
        ml.activate(run, approver="a")


def test_a_model_that_breaks_a_critical_case_is_not_activated():
    run = ml.start("officer_level")
    ml.seal(run, {"weights": [1]})
    run.metrics = {"accuracy": 0.95}
    run.baseline_metrics = {"accuracy": 0.83}
    run.critical_result = {"failures": ["permission-1"]}

    with pytest.raises(ml.ModelError) as caught:
        ml.activate(run, approver="a")
    assert "critical case" in str(caught.value)


def test_unrun_critical_cases_are_not_a_pass():
    run = ml.start("officer_level")
    ml.seal(run, {"weights": [1]})
    run.metrics = {"accuracy": 0.95}
    run.baseline_metrics = {"accuracy": 0.83}

    with pytest.raises(ml.ModelError) as caught:
        ml.activate(run, approver="a")
    assert "did not run is not a check that passed" in str(caught.value)


def test_a_leaking_split_is_not_a_holdout():
    run = ml.start("officer_level")
    ml.seal(run, {"weights": [1]})
    run.split = ml.Split(train=["a", "b"], holdout=["b"])
    run.metrics = {"accuracy": 0.95}
    run.baseline_metrics = {"accuracy": 0.83}
    run.critical_result = {"failures": []}

    with pytest.raises(ml.ModelError) as caught:
        ml.activate(run, approver="a")
    assert "more than one side of the split" in str(caught.value)


def test_a_good_model_activates_and_rolls_back():
    run = ml.start("officer_level", seed=7)
    ml.seal(run, {"weights": [1, 2]})
    run.split = ml.Split(train=["a"], validation=["b"], holdout=["c"])
    run.metrics = {"accuracy": 0.95}
    run.baseline_metrics = {"accuracy": 0.83}
    run.critical_result = {"failures": []}

    ml.activate(run, approver="cro")
    assert run.status == ml.ACTIVE and run.activated is True

    ml.rollback(run, why="it disagreed with the ladder in production")
    assert run.activated is False


# ============================================ §11 the guard, at runtime


@db
def test_feedback_does_not_change_the_assurance_record_it_is_about():
    """§11's runtime half, and the one that matters.

    A static check can be defeated. An effect cannot: this stores a real
    Assurance Record, submits real feedback naming it, and asserts the record
    is byte-identical afterwards — status, score, coverage, critical checks
    and fingerprint.
    """
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import AssuranceRecord
    from backend.services import learning as ls

    record_id = f"ar-{uuid.uuid4().hex[:12]}"
    answer_id = f"ans-{uuid.uuid4().hex[:10]}"
    with get_session() as session:
        session.add(AssuranceRecord(
            assurance_record_id=record_id, answer_id=answer_id,
            overall_status="VALIDATED", coverage_pct=93.3,
            critical_failure_count=0, fingerprint="f" * 16))
        session.flush()
        watched = ("overall_status", "coverage_pct", "critical_failure_count",
                   "fingerprint")
        before = {
            c: getattr(session.execute(
                select(AssuranceRecord).where(
                    AssuranceRecord.assurance_record_id == record_id)
            ).scalars().one(), c)
            for c in watched}

        for rating in (fb.NO, fb.PARTLY, fb.YES, fb.NOT_SURE, fb.SKIP):
            ls.record_feedback(
                session, rating=rating, answer_id=answer_id,
                categories=(["wrong_result"] if rating in fb.WANTS_DETAIL
                            else []),
                assurance_record_id=record_id, build_sha="sha",
                plan_fingerprint="pf", consent=fb.CONSENT_GRANTED)

        after = session.execute(
            select(AssuranceRecord).where(
                AssuranceRecord.assurance_record_id == record_id)
        ).scalars().one()
        for name, value in before.items():
            assert getattr(after, name) == value, name
        session.rollback()


@db
def test_the_whole_pipeline_end_to_end():
    """Feedback → observation labelled → candidate → review → release.

    One test rather than five: the pipeline IS the feature, and each step is
    only meaningful as a gate on the next.
    """
    from backend.db.engine import get_session
    from backend.services import learning as ls

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    answer_id = f"ans-{uuid.uuid4().hex[:10]}"
    with get_session() as session:
        ls.record_observation(session, ob.Observation(
            tenant=tenant, answer_id=answer_id, question="What is total ECL?",
            build_sha="sha", plan_fingerprint="pf",
            reading={"concepts": ["expected credit loss"]}))

        event = ls.record_feedback(
            session, rating=fb.NO, answer_id=answer_id,
            categories=["wrong_period"], tenant=tenant, user_id="u",
            question="What is total ECL?", build_sha="sha",
            plan_fingerprint="pf", consent=fb.CONSENT_GRANTED,
            comment="the quarter was wrong")
        assert event["observation_labelled"] is True
        assert "learned" not in event["acknowledgement"].lower()

        labelled = ls.observations(session, tenant=tenant, label=ob.LABELED)
        assert len(labelled) == 1

        case = ls.propose_candidate(session, event["event_id"])
        assert case["status"] == cd.AUTO_PROPOSED
        assert case["failure_class"] == "scope"

        again = ls.propose_candidate(session, event["event_id"])
        assert again["already_present"] is True

        with pytest.raises(ls.LearningServiceError):
            ls.review_candidate(session, case["candidate_id"],
                                action="APPROVE_AS_TEACHING_CASE",
                                reviewer="r", reason="")

        ls.review_candidate(session, case["candidate_id"],
                            action="REQUEST_CHANGE", reviewer="r1",
                            reason="say which period it should have been")
        approved = ls.review_candidate(
            session, case["candidate_id"],
            action="APPROVE_AS_TEACHING_CASE", reviewer="r1",
            reason="the period was wrong and this is the right one",
            proposal={"reading": {"periods": ["Q2 2025"]}})
        assert approved["status"] == cd.HUMAN_APPROVED

        history = ls.review_history(session, case["candidate_id"])
        assert [h["action"] for h in history] == ["REQUEST_CHANGE",
                                                  "APPROVE_AS_TEACHING_CASE"]

        release = ls.build_release(session, created_by="head", tenant=tenant)
        assert release["status"] == lr.CANDIDATE

        with pytest.raises(ls.LearningServiceError):
            ls.activate_release(session, release["release_id"],
                                approver="cro")

        ls.evaluate_release(session, release["release_id"], critical_before=1,
                            critical_after=0, improved={"period_accuracy":
                                                        True},
                            safety_regressions=[], holdout_overlap=[])
        active = ls.activate_release(session, release["release_id"],
                                     approver="cro")
        assert active["status"] == lr.ACTIVE

        applied = ls.candidates(session, tenant=tenant,
                                status=cd.APPLIED_TO_RELEASE)
        assert len(applied) == 1

        metrics = ls.satisfaction_metrics(session, tenant=tenant)
        assert metrics["by_rating"][fb.NO] == 1
        assert "not accuracy" in metrics["note"]

        session.rollback()


@db
def test_one_tenants_feedback_is_not_visible_to_another():
    """§30: no cross-tenant learning."""
    from backend.db.engine import get_session
    from backend.services import learning as ls

    mine = f"t-{uuid.uuid4().hex[:8]}"
    theirs = f"t-{uuid.uuid4().hex[:8]}"
    with get_session() as session:
        ls.record_feedback(session, rating=fb.NO, answer_id="a1",
                           categories=["wrong_period"], tenant=mine,
                           build_sha="s", plan_fingerprint="p")

        assert len(ls.inbox(session, tenant=mine)) == 1
        assert ls.inbox(session, tenant=theirs) == []
        session.rollback()


@db
def test_a_revision_leaves_the_original_in_place():
    from backend.db.engine import get_session
    from backend.services import learning as ls

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with get_session() as session:
        first = ls.record_feedback(session, rating=fb.NO, answer_id="a1",
                                   categories=["wrong_period"], tenant=tenant,
                                   build_sha="s", plan_fingerprint="p")
        second = ls.revise_feedback(session, first["event_id"],
                                    rating=fb.PARTLY)

        rows = ls.inbox(session, tenant=tenant)
        assert len(rows) == 2
        assert second["supersedes"] == first["event_id"]
        assert {r["rating"] for r in rows} == {fb.NO, fb.PARTLY}
        session.rollback()
