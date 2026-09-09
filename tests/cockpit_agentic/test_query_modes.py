"""What kind of question this is decides whether the data is touched at all.

Sections 8 through 16. Before this existed, everything that was not a referral
was treated as an analysis — so "what is ECL?" would have spent one of the
five execution submissions available for answering questions about the
portfolio, and "what did the regulator announce yesterday?" had no defined
path at all.

The proofs here are about the APPLICATION: which mode reaches the analytical
pipeline, which cannot, and what each consumes. Whether a real model
classifies a given sentence correctly is a different question, and the
labelled mock cannot answer it.
"""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider

SQL = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
       "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")

PLAN = {"plan_id": "plan-qm", "subquestions": ["the change in reported ECL"],
        "fields_required": ["ecl_reported"],
        "method_summary": "compare the two latest quarters"}

ANSWER = {"decision": "ANSWER",
          "per_subquestion": [{"subquestion": "the change in reported ECL",
                               "answered": True}],
          "answer": {"narrative": "ECL moved between the two quarters.",
                     "complete": True}}


def _steps(code=SQL, step_id="s1"):
    return [{"step_id": step_id, "language": "sql", "code": code}]


def _provider(sonnet_answers, *turns):
    return FakeProvider(structured_script=list(sonnet_answers),
                        converse_script=[(lambda _r, t=t: t) for t in turns])


def _gate(mode, owner, **extra):
    body = {"decision": "PROCEED_COCKPIT", "scores": scores(),
            "public_explanation": "why", "query_mode": mode, "owner": owner}
    body.update(extra)
    return body


# ============================================ the enums, as specified

def test_the_query_mode_enum_is_the_six_that_were_specified():
    assert list(K.QUERY_MODES) == [
        "PRODUCT_HELP", "THEORY_CONCEPT", "DATA_ANALYSIS",
        "OTHER_FUNCTIONALITY", "CLARIFICATION_REQUIRED", "UNSUPPORTED"]


def test_the_owner_enum_is_the_eight_that_were_specified():
    assert list(K.OWNERS) == [
        "COCKPIT", "EWS", "CREDIT_SCORING", "SCORECARD_VALIDATION",
        "WHAT_IF", "LENSES", "GENERAL_CREDITPROBE_HELP", "NONE"]


def test_every_registry_functionality_maps_to_an_owner():
    from backend.cockpit_agentic import registry

    for fid in registry.FUNCTIONALITY_IDS:
        assert fid in K.OWNER_OF_FUNCTIONALITY
        assert K.OWNER_OF_FUNCTIONALITY[fid] in K.OWNERS


def test_only_data_analysis_owned_by_the_cockpit_may_execute():
    """Section 17, as a property of the decision object rather than of the
    runtime that reads it."""
    for mode in K.QUERY_MODES:
        for owner in K.OWNERS:
            if mode == K.DATA_ANALYSIS and owner == K.OWNER_COCKPIT:
                continue
            if mode in K.NO_EXECUTION_MODES:
                continue      # constructed separately: they carry an answer
            decision = K.FunctionalityDecision(
                decision=K.CLARIFY_FUNCTIONALITY, query_mode=mode,
                owner=owner, clarification_question="which?")
            assert decision.may_execute is False


def test_a_decision_that_claims_to_execute_in_a_non_analysis_mode_is_refused():
    """The two vocabularies must agree. A contradiction is not something to
    resolve downstream -- it is a malformed decision."""
    with pytest.raises(K.ContractError):
        K.FunctionalityDecision(
            decision=K.PROCEED_COCKPIT, query_mode=K.THEORY_CONCEPT,
            owner=K.OWNER_COCKPIT, scores=[])


def test_a_no_execution_mode_must_carry_its_answer():
    """There is no second call coming, so a mode that promises an answer in
    this turn and does not carry one is an empty success."""
    with pytest.raises(K.ContractError):
        K.FunctionalityDecision(
            decision=K.PROCEED_COCKPIT, query_mode=K.PRODUCT_HELP,
            owner=K.OWNER_GENERAL_HELP)


def test_a_no_execution_mode_cannot_require_sql_or_python():
    with pytest.raises(K.ContractError):
        K.FunctionalityDecision(
            decision=K.PROCEED_COCKPIT, query_mode=K.THEORY_CONCEPT,
            owner=K.OWNER_GENERAL_HELP, requires_sql=True,
            answer=K.AnswerEnvelope(kind="explanation", narrative="x"))


# ================================ product help runs no SQL and no Python

def test_pure_product_help_executes_nothing_and_consumes_nothing(
        runtime_factory, sonnet_answers):
    """Section 10, end to end."""
    provider = _provider(sonnet_answers, _gate(
        K.PRODUCT_HELP, K.OWNER_GENERAL_HELP,
        answer={"narrative": "The Cockpit answers questions about the stored "
                             "twenty-quarter corporate credit dataset."}))
    outcome = runtime_factory(provider).run("What can I do in Cockpit?")

    assert outcome.status == st.COMPLETED
    assert outcome.decision.query_mode == K.PRODUCT_HELP
    # Zero SQL, zero Python, zero submissions, zero rounds.
    assert outcome.results == []
    assert outcome.python_audit == []
    assert outcome.budget["submissions_used"] == 0
    assert outcome.budget["analysis_rounds_used"] == 0
    assert outcome.budget["submissions_remaining"] == 5
    # One Opus call. The classification and the answer are the same turn.
    assert provider.purposes() == ["opus_gate_and_plan"]
    # And the machine never entered the analytical states.
    visited = [h["state"] for h in outcome.machine["history"]]
    assert st.VALIDATING not in visited and st.EXECUTING not in visited


def test_theory_executes_nothing_and_consumes_nothing(
        runtime_factory, sonnet_answers):
    """Section 11, end to end."""
    provider = _provider(sonnet_answers, _gate(
        K.THEORY_CONCEPT, K.OWNER_GENERAL_HELP,
        answer={"narrative": "Expected credit loss is the probability-weighted "
                             "present value of the shortfalls over a horizon."}))
    outcome = runtime_factory(provider).run("What is ECL?")

    assert outcome.status == st.COMPLETED
    assert outcome.decision.query_mode == K.THEORY_CONCEPT
    assert outcome.results == []
    assert outcome.python_audit == []
    assert outcome.budget["submissions_used"] == 0
    assert outcome.budget["analysis_rounds_used"] == 0
    visited = [h["state"] for h in outcome.machine["history"]]
    assert st.VALIDATING not in visited and st.EXECUTING not in visited


def test_a_theory_answer_is_not_held_to_evidence_it_could_not_have(
        runtime_factory, sonnet_answers):
    """A theory answer explaining that a 12-month PD covers twelve months has
    no executed result to trace "12" to, and demanding one would make the
    check absurd rather than strict."""
    provider = _provider(sonnet_answers, _gate(
        K.THEORY_CONCEPT, K.OWNER_GENERAL_HELP,
        answer={"narrative": "A 12-month PD is the probability of default "
                             "over the next 12 months; lifetime PD covers the "
                             "remaining term."}))
    outcome = runtime_factory(provider).run("What is lifetime PD?")
    assert outcome.status == st.COMPLETED
    assert outcome.envelope.complete is True


def test_a_no_execution_mode_that_arrives_with_a_plan_has_it_discarded(
        runtime_factory, sonnet_answers):
    """Belt and braces: the plan is dropped at the gate, before anything
    downstream could act on it."""
    provider = _provider(sonnet_answers, _gate(
        K.THEORY_CONCEPT, K.OWNER_GENERAL_HELP,
        answer={"narrative": "SICR is a significant increase in credit risk "
                             "since initial recognition."},
        plan=PLAN, steps=_steps()))
    outcome = runtime_factory(provider).run("What is SICR?")
    assert outcome.status == st.COMPLETED
    assert outcome.plan is None
    assert outcome.results == []


# ==================================== mixed theory and data DOES analyse

def test_a_question_asking_for_both_meaning_and_numbers_runs_the_analysis(
        runtime_factory, sonnet_answers):
    """Section 13. "Explain PIT PD and show how it moved" is DATA_ANALYSIS:
    both halves are owed an answer, and the second needs the book."""
    provider = _provider(
        sonnet_answers,
        _gate(K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN, steps=_steps(),
              requires_cockpit_data=True, requires_sql=True),
        ANSWER)
    outcome = runtime_factory(provider).run(
        "Explain PIT PD and show how it changed for this borrower")

    assert outcome.status == st.COMPLETED
    assert outcome.decision.query_mode == K.DATA_ANALYSIS
    assert outcome.results, "the analysis actually ran"
    assert outcome.budget["submissions_used"] == 1
    assert outcome.budget["analysis_rounds_used"] == 1


# ===================================== other functionality, and unsupported

def test_another_functionality_executes_nothing_and_is_referred(
        runtime_factory, sonnet_answers):
    provider = _provider(sonnet_answers, {
        "decision": "REDIRECT", "query_mode": K.OTHER_FUNCTIONALITY,
        "owner": K.OWNER_WHAT_IF,
        "scores": scores(cockpit=20, what_if=95),
        "best_fit": "what_if", "referral_destination": "what_if",
        "referral_reason": "This asks for a new calculation under a changed "
                           "parameter, which is a simulation.",
        "public_explanation": "What-if owns parameter changes."})
    outcome = runtime_factory(provider).run(
        "Increase ABC's PD by 20% and calculate the new ECL")

    assert outcome.status == st.REDIRECTED
    assert outcome.decision.query_mode == K.OTHER_FUNCTIONALITY
    assert outcome.decision.owner == K.OWNER_WHAT_IF
    assert outcome.results == []
    assert outcome.budget["submissions_used"] == 0


def test_a_current_external_information_request_is_closed_not_answered(
        runtime_factory, sonnet_answers):
    """Section 12. The Cockpit must not answer today's news from memory, and
    there must BE a defined path rather than a gap it falls into."""
    provider = _provider(sonnet_answers, {
        "decision": "UNSUPPORTED", "query_mode": K.UNSUPPORTED_MODE,
        "owner": K.OWNER_NONE,
        "scores": scores(cockpit=5, ews=5, credit_scoring=5,
                         scorecard_validation=5, what_if=5, lenses=5),
        "public_explanation": (
            "This asks what was announced yesterday. Nothing configured here "
            "holds current external information, and answering it from "
            "memory would be stating something this application cannot "
            "check.")})
    outcome = runtime_factory(provider).run("What did the RBI announce yesterday?")

    assert outcome.status == st.UNSUPPORTED
    assert outcome.results == []
    assert outcome.budget["submissions_used"] == 0
    assert "cannot check" in outcome.envelope.narrative


# ============================================ the ownership score test

def test_the_cockpit_must_clear_the_floor(runtime_factory, sonnet_answers):
    """Section 9: below 70 is not the Cockpit's, however the gate labelled
    it."""
    provider = _provider(sonnet_answers, _gate(
        K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN, steps=_steps(),
        scores=scores(cockpit=60)))
    outcome = runtime_factory(provider).run("Show me something")
    assert outcome.status == st.WAITING_FOR_USER
    assert outcome.results == []
    assert "below the 70" in outcome.decision.decision_reason


def test_the_cockpit_must_lead_by_ten(runtime_factory, sonnet_answers):
    """A near-tie is a question for the user, not a coin toss resolved in the
    Cockpit's favour."""
    provider = _provider(sonnet_answers, _gate(
        K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN, steps=_steps(),
        scores=scores(cockpit=80, ews=75)))
    outcome = runtime_factory(provider).run("Show me something")
    assert outcome.status == st.WAITING_FOR_USER
    assert outcome.results == []
    assert "too close to decide" in outcome.decision.decision_reason


def test_a_clear_lead_proceeds(runtime_factory, sonnet_answers):
    provider = _provider(
        sonnet_answers,
        _gate(K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN, steps=_steps(),
              scores=scores(cockpit=90, ews=40)),
        ANSWER)
    outcome = runtime_factory(provider).run("How much did ECL change?")
    assert outcome.status == st.COMPLETED


def test_the_score_test_is_applied_by_the_server_not_read_off_the_decision(
        runtime_factory, sonnet_answers):
    """The gate says PROCEED and the scores say otherwise. The scores win: a
    confident explanation is not evidence."""
    provider = _provider(sonnet_answers, _gate(
        K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN, steps=_steps(),
        scores=scores(cockpit=50, ews=95),
        public_explanation="I am confident the Cockpit owns this."))
    outcome = runtime_factory(provider).run("Show me something")
    assert outcome.status == st.WAITING_FOR_USER
    assert outcome.results == []


# ============================================== the mode is not inherited

def test_the_mode_is_decided_again_on_every_turn(runtime_factory,
                                                 sonnet_answers):
    """Section 33. Two turns, two modes, one thread. The second run gets its
    own gate call and its own classification."""
    theory = _provider(sonnet_answers, _gate(
        K.THEORY_CONCEPT, K.OWNER_GENERAL_HELP,
        answer={"narrative": "Lifetime PD covers the remaining term."}))
    first = runtime_factory(theory).run("What is lifetime PD?")
    assert first.decision.query_mode == K.THEORY_CONCEPT
    assert first.results == []

    analysis = _provider(
        sonnet_answers,
        _gate(K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN, steps=_steps()),
        ANSWER)
    second = runtime_factory(analysis).run(
        "Which borrowers had the largest lifetime PD increase?")
    assert second.decision.query_mode == K.DATA_ANALYSIS
    assert second.results, "the second turn is not held to the first's mode"
    # Each turn has its own gate call; there is no path that skips it.
    assert analysis.purposes()[0] == "opus_gate_and_plan"
