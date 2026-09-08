"""The agentic loop: the gate, the counters, the repair ownership, the stops.
Specification sections 6, 7.6A, 8, 9 and 11.

Every test here uses the LABELLED MOCK provider. They prove the application's
guarantees. They prove nothing about a real model's behaviour, and live
validation is BLOCKED until a credential is configured.
"""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import states as st
from backend.cockpit_agentic import ledger as L
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider

GOOD_SQL = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
            "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")


def plan(plan_id="plan-1"):
    return {"plan_id": plan_id, "subquestions": ["the change in reported ECL"],
            "fields_required": ["ecl_reported", "reporting_quarter"],
            "method_summary": "compare the booked ECL across the two latest "
                              "reporting quarters",
            "expected_output_grain": "one row per reporting quarter",
            "expected_units": "INR crore"}


def steps(code=GOOD_SQL, step_id="s1"):
    return [{"step_id": step_id, "language": "sql", "code": code,
             "purpose": "the two latest quarters"}]


def answer(narrative="Reported ECL fell between the two latest quarters."):
    return {"decision": "ANSWER",
            "per_subquestion": [{"subquestion": "the change in reported ECL",
                                 "answered": True}],
            "answer": {"narrative": narrative, "complete": True}}


def provider(sonnet_answers, *turns) -> FakeProvider:
    return FakeProvider(structured_script=list(sonnet_answers),
                        converse_script=[(lambda _r, t=t: t) for t in turns])


# ============================================== the happy path

def test_a_cockpit_question_is_planned_executed_reviewed_and_answered(
        runtime_factory, sonnet_answers):
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "The Cockpit owns stored ECL history.",
                  "plan": plan(), "steps": steps()},
                 answer())
    outcome = runtime_factory(p).run("How much did ECL change?")
    assert outcome.status == st.COMPLETED
    assert outcome.envelope.kind == "answer"
    assert outcome.results and outcome.results[0].steps[0].row_count == 2
    assert p.purposes() == ["opus_gate_and_plan", "opus_review"]
    assert outcome.budget["submissions_used"] == 1
    assert outcome.budget["analysis_rounds_used"] == 1


def test_the_states_run_in_order_and_the_gate_comes_first(
        runtime_factory, sonnet_answers):
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(), "steps": steps()},
                 answer())
    outcome = runtime_factory(p).run("How much did ECL change?")
    visited = [h["state"] for h in outcome.machine["history"]]
    assert visited.index(st.FUNCTIONALITY_ASSESSMENT) < visited.index(
        st.VALIDATING)
    assert visited.index(st.NORMALIZING_1) < visited.index(st.NORMALIZING_2)
    assert st.EXECUTING in visited and st.REVIEWING in visited


# ============================================== the ownership gate

def test_an_ews_question_is_referred_and_executes_nothing(
        runtime_factory, sonnet_answers):
    p = provider(sonnet_answers,
                 {"decision": "REDIRECT",
                  "scores": scores(cockpit=20, ews=95),
                  "best_fit": "ews",
                  "referral_destination": "ews",
                  "referral_reason": "This asks why an early-warning score "
                                     "rose, which the Early Warning module "
                                     "owns.",
                  "public_explanation": "Answering this is not part of the "
                                        "Cockpit's responsibility.",
                  "alternatives": [
                      {"question": "Compare this borrower's stored 12-month "
                                   "PIT PD over the latest four quarters.",
                       "required_fields": ["pd_pit_12m", "reporting_quarter"]}],
                  # Supplied deliberately: a referral must not execute it.
                  "plan": plan(), "steps": steps()})
    outcome = runtime_factory(p).run("Why did the EWS score rise?")
    assert outcome.status == st.REDIRECTED
    assert outcome.envelope.kind == "referral"
    assert outcome.results == [], "a referral executed a query"
    assert outcome.budget["submissions_used"] == 0
    assert outcome.budget["analysis_rounds_used"] == 0
    assert st.VALIDATING not in [h["state"] for h in outcome.machine["history"]]
    assert outcome.envelope.referral["route"] == "/early-warning"
    assert outcome.envelope.referral["enabled"] is True
    assert len(outcome.envelope.alternatives) == 1


def test_a_referral_to_an_unavailable_module_offers_no_link(
        runtime_factory, sonnet_answers):
    p = provider(sonnet_answers,
                 {"decision": "REDIRECT",
                  "scores": scores(cockpit=15, credit_scoring=92),
                  "referral_destination": "credit_scoring",
                  "referral_reason": "Assigning a new score is Credit "
                                     "Scoring's, not the Cockpit's.",
                  "public_explanation": "The Cockpit reads stored ratings; it "
                                        "does not generate one."})
    outcome = runtime_factory(p).run("Give this borrower a credit score")
    assert outcome.status == st.REDIRECTED
    assert outcome.envelope.referral["route"] is None
    assert outcome.envelope.referral["enabled"] is False
    assert outcome.envelope.referral["navigation_available"] is False
    assert outcome.results == []


def test_a_tie_becomes_a_clarification_not_a_silent_execution(
        runtime_factory, sonnet_answers):
    """Section 6.2: proceed only if Cockpit is the UNIQUE highest scorer."""
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT",
                  "scores": scores(cockpit=80, what_if=80),
                  "public_explanation": "x", "plan": plan(), "steps": steps()})
    outcome = runtime_factory(p).run("Compare the downside scenario")
    assert outcome.status == st.CLARIFICATION_REQUIRED
    assert outcome.results == [], "a tie executed a query"
    assert outcome.budget["submissions_used"] == 0
    assert outcome.envelope.clarification_question


def test_the_server_overrides_a_decision_that_contradicts_its_own_scores(
        runtime_factory, sonnet_answers):
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT",
                  "scores": scores(cockpit=30, ews=91),
                  "public_explanation": "x", "plan": plan(), "steps": steps()})
    outcome = runtime_factory(p).run("Why did the alert fire?")
    assert outcome.status == st.CLARIFICATION_REQUIRED
    assert outcome.results == []


# ============================================== repair ownership

def test_creditprobe_returns_facts_and_opus_writes_the_repair(
        runtime_factory, sonnet_answers):
    """Section 7.6A: CreditProbe validates, executes and diagnoses. It never
    authors the next candidate."""
    seen: dict[str, object] = {}

    def gate(_request):
        return {"decision": "PROCEED_COCKPIT", "scores": scores(),
                "public_explanation": "x", "plan": plan(),
                "steps": steps("SELECT pd_12_month FROM "
                               "cockpit_facility_quarter LIMIT 1")}

    def repaired(request):
        # What CreditProbe handed back is in the conversation, and it is the
        # facts -- not a corrected query.
        blob = str(request["messages"])
        seen["blob"] = blob
        return {"action": "submit_repaired_code",
                "what_went_wrong": "pd_12_month does not exist",
                "plan": plan(), "steps": steps()}

    p = FakeProvider(structured_script=list(sonnet_answers),
                     converse_script=[gate, repaired, lambda _r: answer()])
    outcome = runtime_factory(p).run("Show me PD")

    assert outcome.status == st.COMPLETED
    assert len(outcome.failures) == 1
    packet = outcome.failures[0]
    assert packet.category == K.UNRESOLVED_FIELD
    assert packet.unresolved_name == "pd_12_month"
    names = [a.field_name for a in packet.available_alternatives]
    assert names[:2] == ["pd_pit_12m", "pd_ttc_12m"]
    # The alternatives are reported as facts, with meanings and units, and
    # CreditProbe expresses no preference between them.
    assert all(a.meaning and a.unit for a in packet.available_alternatives[:2])
    # No repaired SQL anywhere in what CreditProbe sent.
    blob = seen["blob"]
    assert "pd_12_month" in blob, "the exact failed code was not returned"
    assert "SELECT reporting_quarter, sum(ecl_reported)" not in blob, (
        "CreditProbe put a corrected query into the conversation")
    assert outcome.budget["submissions_used"] == 2


def test_a_security_refusal_fails_closed_without_spending_more_attempts(
        runtime_factory, sonnet_answers):
    """Section 8.3: do not waste five attempts on forbidden data access."""
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(),
                  "steps": steps("SELECT * FROM ews_alerts")})
    outcome = runtime_factory(p).run("Show me the alerts table")
    assert outcome.status == st.EXECUTION_FAILED
    assert outcome.failures[0].category == K.OUT_OF_SCOPE_ACCESS
    assert outcome.failures[0].repairable is False
    assert outcome.budget["submissions_used"] == 1, (
        "a fail-closed refusal spent more than one attempt")
    assert p.purposes() == ["opus_gate_and_plan"], (
        "the model was asked to repair an unrepairable refusal")


# ============================================== the counters

def test_five_failed_submissions_and_no_sixth(runtime_factory, sonnet_answers):
    bad = "SELECT nope_{} FROM cockpit_facility_quarter"
    turns = [lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                         "public_explanation": "x", "plan": plan(),
                         "steps": steps(bad.format(0))}]
    for i in range(1, 8):
        turns.append(
            lambda _r, i=i: {"action": "submit_repaired_code",
                             "plan": plan(), "steps": steps(bad.format(i))})
    p = FakeProvider(structured_script=list(sonnet_answers),
                     converse_script=turns)
    outcome = runtime_factory(p).run("Show me something")

    assert outcome.status == st.EXECUTION_FAILED
    assert outcome.budget["submissions_used"] == 5
    assert outcome.budget["submissions_remaining"] == 0
    assert len(outcome.failures) == 5
    # Four repair turns after the gate, and then it stopped rather than a fifth.
    assert p.purposes().count("opus_repair") == 4
    assert "5 attempts" in outcome.envelope.narrative or \
           "5 submissions" in outcome.envelope.narrative
    assert "not being asked to fix" in outcome.envelope.what_would_help


def test_an_identical_resubmission_is_blocked_before_execution(
        runtime_factory, sonnet_answers):
    same = "SELECT nope FROM cockpit_facility_quarter"
    p = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[
            lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                        "public_explanation": "x", "plan": plan(),
                        "steps": steps(same)},
            # The same query, only reindented. Not a changed approach.
            lambda _r: {"action": "submit_repaired_code", "plan": plan(),
                        "steps": steps("SELECT   nope\n  FROM "
                                       "cockpit_facility_quarter")},
        ])
    outcome = runtime_factory(p).run("Show me something")
    assert outcome.status == st.INSUFFICIENT_DATA
    assert outcome.budget["submissions_used"] == 1, (
        "the blocked duplicate consumed an attempt")
    assert "Repeating it" in outcome.envelope.narrative


def test_a_new_plan_does_not_reset_the_submission_counter(
        runtime_factory, sonnet_answers):
    """Section 9.2 example B."""
    bad = "SELECT nope_{} FROM cockpit_facility_quarter"
    turns = [lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                         "public_explanation": "x", "plan": plan("plan-A"),
                         "steps": steps(bad.format(0))}]
    for i in range(1, 8):
        turns.append(
            lambda _r, i=i: {"action": "revise_the_analysis_plan",
                             "plan": plan(f"plan-{i}"),
                             "steps": steps(bad.format(i))})
    p = FakeProvider(structured_script=list(sonnet_answers),
                     converse_script=turns)
    outcome = runtime_factory(p).run("Show me something")
    assert outcome.budget["submissions_used"] == 5
    assert outcome.status == st.EXECUTION_FAILED


def widen(n: int) -> str:
    """A genuinely different query each round. Resubmitting the same one is a
    no-progress case and is blocked, which a different test covers."""
    return (f"SELECT reporting_quarter, sum(ecl_reported) AS ecl "
            f"FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC "
            f"LIMIT {n + 2}")


def test_three_insufficient_rounds_stop_without_a_fourth(
        runtime_factory, sonnet_answers):
    def revise(n):
        def turn(_request):
            return {"decision": "REVISE_ANALYSIS",
                    "per_subquestion": [
                        {"subquestion": "the change in ECL", "answered": False,
                         "gap": "the comparison period is not settled"}],
                    "gap_addressed": "a wider period",
                    "plan": plan(f"plan-{n}"), "steps": steps(widen(n))}
        return turn

    p = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[
            lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                        "public_explanation": "x", "plan": plan(),
                        "steps": steps()},
            revise(1), revise(2), revise(3), revise(4)])
    outcome = runtime_factory(p).run("How much did ECL change?")
    assert outcome.budget["analysis_rounds_used"] == 3
    assert outcome.status == st.PARTIAL
    assert "3 analysis rounds" in outcome.envelope.narrative
    assert "inventing the remainder" in outcome.envelope.narrative
    assert outcome.envelope.limitations


def test_a_successful_fifth_submission_with_an_incomplete_answer_stops(
        runtime_factory, sonnet_answers):
    """Section 9.2 example C: no submission six."""
    bad = "SELECT nope_{} FROM cockpit_facility_quarter"
    turns = [lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                         "public_explanation": "x", "plan": plan(),
                         "steps": steps(bad.format(0))}]
    for i in range(1, 4):
        turns.append(lambda _r, i=i: {"action": "submit_repaired_code",
                                      "plan": plan(),
                                      "steps": steps(bad.format(i))})
    # The fifth submission succeeds, and the review wants another.
    turns.append(lambda _r: {"action": "submit_repaired_code", "plan": plan(),
                             "steps": steps()})
    turns.append(lambda _r: {
        "decision": "REVISE_ANALYSIS",
        "per_subquestion": [{"subquestion": "the change", "answered": False,
                             "gap": "one more quarter is needed"}],
        "gap_addressed": "one more quarter", "plan": plan(),
        "steps": steps()})
    p = FakeProvider(structured_script=list(sonnet_answers),
                     converse_script=turns)
    outcome = runtime_factory(p).run("Show me something")
    assert outcome.budget["submissions_used"] == 5
    assert outcome.status in (st.EXECUTION_FAILED, st.PARTIAL,
                              st.INSUFFICIENT_DATA)
    assert outcome.budget["submissions_remaining"] == 0


# ============================================== budgets and stops

def test_the_deadline_stops_the_request(runtime_factory, sonnet_answers):
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(), "steps": steps()},
                 answer())
    runtime = runtime_factory(p)
    clock = {"t": 0.0}
    runtime.ledger._clock = lambda: clock["t"]
    runtime.ledger._started = 0.0
    clock["t"] = 61.0
    outcome = runtime.run("How much did ECL change?")
    assert outcome.status == st.TIMED_OUT
    assert outcome.envelope.kind == "stop"
    assert "new question starts a new budget" in outcome.envelope.what_would_help


def test_cancellation_stops_new_work(runtime_factory, sonnet_answers):
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(), "steps": steps()})
    runtime = runtime_factory(p)
    runtime.cancel()
    outcome = runtime.run("How much did ECL change?")
    assert outcome.status == st.CANCELLED
    assert outcome.results == []


def test_no_provider_is_reported_never_substituted(runtime_factory):
    """Sections 17 and 18: no hidden fallback and no canned decomposition."""
    from backend.llm.base import NullProvider

    outcome = runtime_factory(NullProvider()).run("How much did ECL change?")
    assert outcome.status == st.PROVIDER_ERROR
    assert outcome.envelope.kind == "stop"
    assert outcome.results == []
    assert "no deterministic stand-in" in outcome.envelope.narrative
    # Nothing that could be mistaken for an analysis.
    assert not outcome.envelope.tables and not outcome.envelope.charts


def test_a_truncated_response_is_incomplete_not_a_shorter_answer(
        runtime_factory, sonnet_answers, monkeypatch):
    from backend.llm.base import ConverseResult

    p = FakeProvider(structured_script=list(sonnet_answers),
                     converse_script=[lambda _r: {}])

    def truncated(**kwargs):
        p.requests.append(kwargs)
        return ConverseResult(assistant_blocks=[], text="half a plan",
                              stop_reason="max_tokens", tool_calls=[])

    monkeypatch.setattr(p, "converse", truncated)
    outcome = runtime_factory(p).run("How much did ECL change?")
    assert outcome.status == st.PROVIDER_ERROR
    assert "cut off" in outcome.envelope.narrative
    assert "half a plan, not a smaller one" in outcome.envelope.narrative


def test_the_chart_limit_is_enforced_by_the_server(
        runtime_factory, sonnet_answers):
    charts = [{"kind": "bar", "title": f"chart {i}"} for i in range(5)]
    reply = answer()
    reply["answer"]["charts"] = charts
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(), "steps": steps()},
                 reply)
    outcome = runtime_factory(p).run("Chart it")
    assert len(outcome.envelope.charts) == 2, "standard mode permits two"
    assert any("charts is the limit" in x for x in outcome.envelope.limitations)


def test_a_citation_to_nothing_is_removed_and_the_removal_is_recorded(
        runtime_factory, sonnet_answers):
    reply = answer()
    reply["answer"]["fact_ids"] = ["art-invented", "art-also-invented"]
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(), "steps": steps()},
                 reply)
    outcome = runtime_factory(p).run("How much did ECL change?")
    assert outcome.envelope.fact_ids == []
    assert any("did not match a result" in x
               for x in outcome.envelope.limitations)


def test_the_same_request_id_continues_one_budget(runtime_factory,
                                                  sonnet_answers):
    """Section 9.3: a double click does not open a second budget."""
    shared = L.LedgerStore()
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(), "steps": steps()},
                 answer())
    first = runtime_factory(p, request_id="req-shared", store_=shared)
    first.run("How much did ECL change?")
    second = runtime_factory(
        FakeProvider(structured_script=list(sonnet_answers)),
        request_id="req-shared", store_=shared)
    assert second.resumed is True
    assert second.ledger.submissions == 1
    assert second.ledger is first.ledger


def test_an_empty_result_is_not_a_failure(runtime_factory, sonnet_answers):
    empty = ("SELECT * FROM cockpit_facility_quarter "
             "WHERE sector_name = 'Aerospace'")
    p = provider(sonnet_answers,
                 {"decision": "PROCEED_COCKPIT", "scores": scores(),
                  "public_explanation": "x", "plan": plan(),
                  "steps": steps(empty)},
                 answer("No facilities matched that sector in this release."))
    outcome = runtime_factory(p).run("Show me Aerospace")
    assert outcome.status == st.COMPLETED
    assert outcome.results[0].status == "empty"
    assert outcome.failures == []
    assert "not proof that the quantity is zero" in outcome.results[0].note
