"""The three questions from the live UAT run, as a regression fixture.

`live_uat_regression.json` records what was observed live and what must now
happen for each. This file drives all three through the runtime and holds the
result against that record.

LABELLED MOCK. What these prove is which packets this application builds, which
calls it makes, and how each request settles -- which is where all three
defects were. They prove nothing about how a real model classifies a sentence
or how good its answer is; that is the 84-question bank against the configured
models, and it has not been run.
"""

from __future__ import annotations

import json
import pathlib

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import ledger as L
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider, expand

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "live_uat_regression.json").read_text())
CASES = {case["case_id"]: case for case in FIXTURE["cases"]}

SQL = ("SELECT borrower_id, reporting_quarter, avg(pd_pit_12m) AS pd "
       "FROM cockpit_facility_quarter GROUP BY 1, 2 ORDER BY 2 DESC LIMIT 40")


def _sonnet(question: str, *, measures=(), actions=("explain",)):
    return [
        {"language": "en", "english_text": question, "preserved_terms": [],
         "uncertainties": []},
        {"business_question": question, "subquestions": [question],
         "requested_measures": list(measures),
         "requested_actions": list(actions),
         "explicit_scope": {}, "inherited_scope": {}, "periods": [],
         "entity_references": [], "unresolved_ambiguity": []},
    ]


def _run(runtime_factory, case_id: str, *turns):
    case = CASES[case_id]
    provider = FakeProvider(
        structured_script=_sonnet(case["question"]),
        converse_script=[(lambda _r, t=t: t) for t in expand(turns)])
    return case, provider, runtime_factory(provider).run(case["question"])


def _check(case, provider, outcome):
    assert outcome.status == case["expected_status"]
    assert outcome.decision.query_mode == case["expected_query_mode"]
    assert outcome.decision.owner == case["expected_owner"]
    assert provider.purposes() == case["expected_opus_purposes"]
    assert outcome.context["stages_built"] == case["expected_stages_built"]
    assert outcome.context["full_catalogue_sent"] == case[
        "full_catalogue_sent"]


# ---------------------------------------------------------------- case one

def test_who_are_you_is_answered_from_the_gate_packet(runtime_factory):
    case, provider, outcome = _run(
        runtime_factory, "uat-1-who-are-you",
        {"decision": K.ANSWER_WITHOUT_DATA, "query_mode": K.PRODUCT_HELP,
         "owner": K.OWNER_COCKPIT, "scores": scores(),
         "public_explanation": "a question about the product",
         "answer": {"narrative": "I am the Cockpit: the part of CreditProbe "
                                 "that answers questions about your recorded "
                                 "IFRS 9 credit book.", "complete": True}})
    _check(case, provider, outcome)

    # Nothing was executed and nothing was spent on the analytical budget.
    assert outcome.budget["submissions_used"] == 0
    assert outcome.budget["analysis_rounds_used"] == 0
    assert outcome.results == []

    # The request that was refused live, and the one that goes out now.
    live = case["live_before"]
    assert live["input_tokens"] + live["output_allowance"] > live[
        "per_call_cap"], "the fixture no longer records the defect"
    now = outcome.tokens["largest_request_tokens"]
    assert now + L.STANDARD_LIMITS.max_opus_output_tokens < \
        L.STANDARD_LIMITS.max_input_tokens_per_call
    print(f"\n{case['case_id']}: live BEFORE {live['input_tokens']:,} tokens "
          f"(provider count) -> AFTER {now:,} tokens (local estimate at the "
          f"calibrated 2.2 characters per token)")


# ---------------------------------------------------------------- case two

def test_pit_versus_ttc_is_theory_and_takes_the_light_gate(runtime_factory):
    case, provider, outcome = _run(
        runtime_factory, "uat-2-pit-vs-ttc",
        {"decision": K.ANSWER_WITHOUT_DATA, "query_mode": K.THEORY_CONCEPT,
         "owner": K.OWNER_COCKPIT, "scores": scores(),
         "public_explanation": "a question about what a term means",
         "answer": {"narrative": "A point-in-time PD conditions on today's "
                                 "conditions; a through-the-cycle PD averages "
                                 "over a cycle and moves less.",
                    "complete": True}})
    _check(case, provider, outcome)
    assert outcome.budget["submissions_used"] == 0
    assert outcome.budget["analysis_rounds_used"] == 0
    # The dictionary was never assembled, so no field name could have reached
    # the model -- including the two the question names.
    blob = provider.serialized()
    assert "pd_pit_12m" not in blob and "pd_ttc_12m" not in blob


# -------------------------------------------------------------- case three

def test_the_pd_increase_question_gets_the_full_analytical_packet(
        runtime_factory):
    case, provider, outcome = _run(
        runtime_factory, "uat-3-largest-pd-increase",
        {"decision": "PROCEED_COCKPIT", "query_mode": K.DATA_ANALYSIS,
         "owner": K.OWNER_COCKPIT, "scores": scores(),
         "public_explanation": "the stored PD history is the Cockpit's",
         "plan": {"plan_id": "p", "subquestions": [CASES[
             "uat-3-largest-pd-increase"]["question"]],
             "fields_required": ["pd_pit_12m", "borrower_id"],
             "method_summary": "compare the PIT 12-month PD across the four "
                               "latest quarters by borrower"},
         "steps": [{"step_id": "s1", "language": "sql", "code": SQL}]},
        {"decision": "ANSWER",
         "per_subquestion": [{"subquestion": CASES[
             "uat-3-largest-pd-increase"]["question"], "answered": True}],
         "answer": {"narrative": "The borrowers whose PIT 12-month PD rose "
                                 "most are in the table.", "complete": True}})
    _check(case, provider, outcome)

    # This one, and only this one, was given the dictionary.
    assert outcome.budget["submissions_used"] == 1
    assert outcome.budget["analysis_rounds_used"] == 1
    analysis = [r for r in provider.requests if r["purpose"] != "opus_gate"]
    assert analysis, "no analysis turn was made"
    for request in analysis:
        assert "pd_pit_12m" in json.dumps(request, default=str)
    gate = [r for r in provider.requests if r["purpose"] == "opus_gate"]
    assert "pd_pit_12m" not in json.dumps(gate, default=str)


# ------------------------------------------------------------- the fixture

def test_the_fixture_says_what_a_mock_cannot_show():
    assert "proves nothing about" in FIXTURE["not_a_quality_claim"]
    assert "BLOCKED/UNVERIFIED" in FIXTURE["not_a_quality_claim"]
    assert set(CASES) == {"uat-1-who-are-you", "uat-2-pit-vs-ttc",
                          "uat-3-largest-pd-increase"}
