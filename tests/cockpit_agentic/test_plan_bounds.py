"""The planning turn is bounded, and a truncated one is recoverable.
Live-UAT defect: the plan reached 4,096 tokens and the provider cut it off.

The observed failure. "Which sectors saw the largest increase in Stage 2
exposure over the latest year?" -- one aggregation and one ranking -- reached
`Planning the analysis` and stopped with "The model's response was cut off at
its 4096-token output limit so the opus_plan is incomplete."

Two things were wrong. The planning CONTRACT asked for a credit memo: narrative
reasoning, per-field justification, a discussion of alternatives, and prose
about what the numbers would mean -- all at the moment the model was supposed
to be writing executable instructions. And there was no defined behaviour when
a reply overran: the truncation surfaced as a provider failure, which it is
not, and the partial turn was left in the conversation where it would have made
the next request malformed.

These tests use the LABELLED MOCK provider. They prove what this application
asks for, what it accepts, and what it does when a reply overruns. They prove
nothing about how verbose a real model chooses to be -- that is measured live,
and `docs/cockpit_v3/PLAN_BOUNDS.md` records the measurement.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import ledger as L
from backend.cockpit_agentic import opus as opus_mod
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider, TRUNCATE

PROMPTS = pathlib.Path(opus_mod.__file__).parent / "prompts"

STAGE2_SQL = (
    "SELECT sector_name, "
    "sum(CASE WHEN reporting_quarter = '2026Q2' THEN ead_reported ELSE 0 END) "
    "- sum(CASE WHEN reporting_quarter = '2025Q2' THEN ead_reported ELSE 0 END)"
    " AS change_rcy FROM cockpit_facility_quarter WHERE ifrs9_stage = 2 "
    "AND reporting_quarter IN ('2025Q2', '2026Q2') GROUP BY 1 "
    "ORDER BY 2 DESC")

COMPACT_PLAN = {
    "plan_id": "plan-stage2",
    "subquestions": ["the change in Stage 2 exposure by sector over four "
                     "quarters"],
    "fields_required": ["sector_name", "reporting_quarter", "ifrs9_stage",
                        "ead_reported"],
    "method_summary": "Sum reported EAD for Stage 2 positions in the latest "
                      "populated quarter and in the quarter four earlier, by "
                      "sector, and rank the difference descending.",
    "expected_output_grain": "one row per sector",
    "expected_units": "INR crore",
}

COMPACT_STEPS = [{"step_id": "s1", "language": "sql", "code": STAGE2_SQL,
                  "purpose": "Stage 2 EAD by sector, both quarters"}]

ANSWER = {"decision": "ANSWER",
          "per_subquestion": [{"subquestion": "the change in Stage 2 exposure "
                                              "by sector over four quarters",
                               "answered": True}],
          "answer": {"narrative": "Stage 2 exposure rose most in the sectors "
                                  "in the table.", "complete": True}}


def _sonnet(question: str):
    return [
        {"language": "en", "english_text": question, "preserved_terms": [],
         "uncertainties": []},
        {"business_question": question, "subquestions": [question],
         "requested_measures": ["ead_reported"],
         "requested_actions": ["compare", "rank"],
         "explicit_scope": {}, "inherited_scope": {}, "periods": [],
         "entity_references": [], "unresolved_ambiguity": []},
    ]


def _gate():
    return {"decision": "PROCEED_COCKPIT", "query_mode": K.DATA_ANALYSIS,
            "owner": K.OWNER_COCKPIT, "scores": scores(),
            "public_explanation": "the stored Stage 2 book is the Cockpit's"}


def _plan_turn(plan=None, steps=None):
    return {"action": "submit_the_first_step",
            "plan": dict(plan or COMPACT_PLAN),
            "steps": list(steps or COMPACT_STEPS)}


def _provider(question: str, *turns):
    return FakeProvider(
        structured_script=_sonnet(question),
        converse_script=[(lambda _r, t=t: t) for t in turns])


QUESTION = ("Which sectors saw the largest increase in Stage 2 exposure over "
            "the latest year?")
SIMPLE = "What is total exposure at default by sector in the latest quarter?"


# ================================================== 1. the contract is compact

def test_the_planning_contract_does_not_ask_for_a_credit_memo():
    """The prompt is the first cause. It asked for narrative reasoning,
    per-field justification and a discussion of alternatives."""
    plan = (PROMPTS / "opus_plan.md").read_text()
    lower = plan.lower()

    assert "this is an execution plan, not the final answer" in lower or \
        "execution plan, not the final answer" in lower
    assert "be concise" in lower
    # It says, in terms, what does not belong here.
    for forbidden in ("narrative reasoning", "field definitions",
                      "justification of each field",
                      "discussion of alternatives",
                      "final answer"):
        assert forbidden in lower, f"the contract does not exclude {forbidden}"
    # And it does not ask for the things that made the reply a memo.
    assert "how the results will answer each subquestion" not in lower
    # Ownership scoring belongs to the gate and is not repeated here.
    assert "score every" not in lower


def test_the_compact_regeneration_contract_exists_and_says_what_it_is_for():
    compact = " ".join(
        (PROMPTS / "opus_plan_compact.md").read_text().lower().split())
    assert "smallest complete valid execution plan" in compact
    assert "discarded unread" in compact
    assert "no execution submission was spent" in compact
    # The SQL is never what gets shortened.
    assert "a select is exactly as long as correctness requires" in compact


# ================================================== 2. the bounds are explicit

def test_the_bounds_are_the_ones_specified():
    assert K.PLAN_BOUNDS.subquestions == 5
    assert K.PLAN_BOUNDS.fields_required == 30
    assert K.PLAN_BOUNDS.joins_required == 10
    assert K.PLAN_BOUNDS.assumptions == 8
    assert K.PLAN_BOUNDS.method_summary_chars == 600
    assert K.PLAN_BOUNDS.alternative_method_chars == 400
    assert K.PLAN_BOUNDS.missingness_handling_chars == 400
    assert K.PLAN_BOUNDS.step_purpose_chars == 300


def test_the_step_bound_comes_from_the_ledger_not_from_a_second_copy():
    """Six in Standard and eight in Deep -- and read from
    `Limits.steps_per_submission`, so the plan contract and the execution
    ledger cannot drift apart."""
    assert K.bounds_for(L.limits_for("standard")).steps == 6
    assert K.bounds_for(L.limits_for("deep")).steps == 8
    assert L.limits_for("standard").steps_per_submission == 6
    assert L.limits_for("deep").steps_per_submission == 8


def test_the_schema_states_the_bounds_so_the_model_is_told():
    plan = opus_mod.PLAN_SCHEMA["properties"]["plan"]["properties"]
    assert plan["subquestions"]["maxItems"] == 5
    assert plan["fields_required"]["maxItems"] == 30
    assert plan["joins_required"]["maxItems"] == 10
    assert plan["assumptions"]["maxItems"] == 8
    assert plan["method_summary"]["maxLength"] == 600
    step = opus_mod.PLAN_SCHEMA["properties"]["steps"]["items"]["properties"]
    assert step["purpose"]["maxLength"] == 300
    # The SQL is NOT bounded. A query trimmed to fit an allowance is a query
    # that returns the wrong thing.
    assert "maxLength" not in step["code"]


def test_the_bounds_are_enforced_even_when_the_model_ignores_the_schema():
    """A schema states a limit; it does not guarantee one."""
    bounds = K.bounds_for(L.limits_for("standard"))
    raw = {
        "plan_id": "p",
        "subquestions": [f"q{i}" for i in range(12)],
        "fields_required": [f"field_{i}" for i in range(60)],
        "joins_required": [f"j{i}" for i in range(25)],
        "assumptions": [f"a{i}" for i in range(20)],
        "steps": [f"s{i}" for i in range(15)],
        "method_summary": "m" * 2_000,
        "alternative_method": "a" * 2_000,
        "missingness_handling": "x" * 2_000,
    }
    bounded, applied = K.bound_plan(raw, bounds)
    assert len(bounded["subquestions"]) == 5
    assert len(bounded["fields_required"]) == 30
    assert len(bounded["joins_required"]) == 10
    assert len(bounded["assumptions"]) == 8
    assert len(bounded["steps"]) == 6
    assert len(bounded["method_summary"]) <= 604
    assert len(bounded["missingness_handling"]) <= 404
    # Everything trimmed is reported. Nothing is quietly shortened and then
    # allowed to read as what the model wrote.
    assert len(applied) >= 7


def test_bounding_never_shortens_the_sql():
    long_sql = "SELECT " + ", ".join(f"c{i}" for i in range(400)) + " FROM t"
    steps, applied = K.bound_steps(
        [{"step_id": "s1", "language": "sql", "code": long_sql,
          "purpose": "p" * 900}], K.PLAN_BOUNDS)
    assert steps[0]["code"] == long_sql
    assert len(steps[0]["purpose"]) <= 304
    assert any("purpose" in note for note in applied)


def test_too_many_executable_steps_are_bounded_not_run():
    steps, applied = K.bound_steps(
        [{"step_id": f"s{i}", "language": "sql", "code": "SELECT 1"}
         for i in range(11)], K.bounds_for(L.limits_for("standard")))
    assert len(steps) == 6
    assert any("kept the first 6" in note for note in applied)


# ============================== 3. the catalogue is input, not output

@pytest.mark.parametrize("written,expected", [
    ("sector_name", "sector_name"),
    ("sector_name - the economic sector of the borrower", "sector_name"),
    ("ead_reported — exposure at default, in INR crore", "ead_reported"),
    ("reporting_quarter: the quarter this row reports", "reporting_quarter"),
    ("ifrs9_stage (1, 2 or 3 under IFRS 9)", "ifrs9_stage"),
    ("cockpit_facility_quarter.ead_reported", "cockpit_facility_quarter.ead_reported"),
])
def test_a_field_reference_is_a_canonical_name_not_a_definition(written,
                                                                expected):
    assert K.canonical_field_name(written) == expected


def test_copied_field_definitions_are_reduced_and_the_reduction_is_reported():
    bounded, applied = K.bound_plan({
        "plan_id": "p", "subquestions": ["q"], "method_summary": "m",
        "fields_required": [
            "sector_name - this represents the economic sector of the "
            "borrower as recorded in the customer master",
            "reporting_quarter - this is the reporting quarter, one of the "
            "twenty in this release",
            "ead_reported"]})
    assert bounded["fields_required"] == [
        "sector_name", "reporting_quarter", "ead_reported"]
    assert any("canonical name" in note for note in applied)


def test_the_schema_tells_the_model_that_a_field_is_a_name_only():
    field = (opus_mod.PLAN_SCHEMA["properties"]["plan"]["properties"]
             ["fields_required"]["items"])
    assert "Canonical name only" in field["description"]
    assert "No description" in field["description"]
    assert field["maxLength"] == K.PLAN_BOUNDS.field_name_chars


# ====================== 4. a simple question produces a simple plan

@pytest.mark.parametrize("question", [QUESTION, SIMPLE])
def test_a_one_aggregation_question_plans_compactly_and_executes(
        runtime_factory, question):
    provider = _provider(question, _gate(), _plan_turn(), ANSWER)
    outcome = runtime_factory(provider).run(question)

    assert outcome.status == st.COMPLETED
    assert provider.purposes() == ["opus_gate", "opus_plan", "opus_review"]
    assert outcome.planning["attempts"] == 1
    assert outcome.planning["regenerated"] is False
    assert outcome.planning["bounds_applied"] == []
    assert outcome.results and outcome.results[0].steps[0].status != "failed"

    # The planning RESPONSE, measured. The target is well below 2,000 tokens
    # and preferably below 1,000; a compact plan for one aggregation and one
    # ranking is a few hundred.
    plan_turn = next(t for t in outcome.tokens["turns"]
                     if t["purpose"] == "opus_plan")
    emitted = len(json.dumps(_plan_turn(), default=str)) // 4
    assert emitted < 1_000, f"the compact plan emitted {emitted} tokens"
    assert plan_turn["truncated"] is False
    print(f"\n{question!r}\n  planning output ~{emitted} tokens "
          f"(limit {L.limits_for('standard').max_opus_output_tokens:,})")


# ====================== 5-6. truncation, one retry, and a bounded stop

def test_a_truncated_plan_is_regenerated_once_and_then_executes(
        runtime_factory):
    """The exact live failure, and the recovery.

    The first planning reply overruns. Nothing partial is executed, the turn is
    rolled out of the conversation, and OPUS is asked once for the smallest
    complete plan. That plan runs.
    """
    provider = _provider(QUESTION, _gate(), TRUNCATE, _plan_turn(), ANSWER)
    outcome = runtime_factory(provider).run(QUESTION)

    assert outcome.status == st.COMPLETED
    assert provider.purposes() == [
        "opus_gate", "opus_plan", "opus_plan_compact", "opus_review"]
    assert outcome.planning["attempts"] == 2
    assert outcome.planning["regenerated"] is True
    # It really executed, and it executed the SECOND plan.
    assert outcome.results
    assert outcome.results[0].steps[0].executed_code == STAGE2_SQL


def test_the_regeneration_asks_opus_for_a_smaller_plan_and_says_why(
        runtime_factory):
    provider = _provider(QUESTION, _gate(), TRUNCATE, _plan_turn(), ANSWER)
    runtime_factory(provider).run(QUESTION)

    retry = next(r for r in provider.requests
                 if r["purpose"] == "opus_plan_compact")
    sent = json.dumps(retry, default=str)
    assert "EXCEEDED THE OUTPUT ALLOWANCE" in sent
    assert "SMALLEST COMPLETE VALID PLAN" in sent
    # The original request is still there: the retry is not a different
    # question asked more tersely.
    assert "Stage 2 exposure" in sent
    assert "PROCEED_COCKPIT" in sent
    # And the compact contract is the system prompt for it.
    assert "There is no fourth way out, and there is no third attempt." in sent


def test_a_second_truncation_stops_without_executing_anything(
        runtime_factory):
    provider = _provider(QUESTION, _gate(), TRUNCATE, TRUNCATE)
    outcome = runtime_factory(provider).run(QUESTION)

    assert outcome.status == st.STOPPED_OUTPUT_LIMIT
    assert outcome.envelope.kind == "stop"
    assert outcome.envelope.stop_reason == K.PLAN_OUTPUT_TRUNCATED
    assert outcome.results == []
    assert outcome.budget["submissions_used"] == 0
    # Two planning generations and no third.
    assert provider.purposes().count("opus_plan") == 1
    assert provider.purposes().count("opus_plan_compact") == 1


def test_the_bounded_stop_explains_itself_without_provider_internals(
        runtime_factory):
    provider = _provider(QUESTION, _gate(), TRUNCATE, TRUNCATE)
    outcome = runtime_factory(provider).run(QUESTION)

    shown = " ".join([outcome.envelope.narrative,
                      outcome.envelope.what_would_help,
                      *outcome.envelope.what_was_tried])
    assert "response allowance" in shown
    for internal in ("max_tokens", "stop_reason", "JSON", "schema",
                     "tool_use", "opus_plan"):
        assert internal not in shown, f"{internal} reached the reader"
    # It does not push a perfectly clear question back at the user. What
    # overran was the model's own plan, and the stop says so.
    assert "rephras" not in shown.lower()
    assert "reword" in shown.lower()
    assert "Nothing is wrong with the question" in shown


# ====================== 7. how the retry counts

def test_the_retry_is_a_provider_call_but_not_an_execution_submission(
        runtime_factory):
    without = _provider(QUESTION, _gate(), _plan_turn(), ANSWER)
    plain = runtime_factory(without).run(QUESTION)

    with_retry = _provider(QUESTION, _gate(), TRUNCATE, _plan_turn(), ANSWER)
    retried = runtime_factory(with_retry).run(QUESTION)

    assert retried.status == plain.status == st.COMPLETED
    # One more provider request, and tokens spent on it.
    assert (retried.budget["model_requests_used"]
            == plain.budget["model_requests_used"] + 1)
    assert retried.budget["tokens_used"] > plain.budget["tokens_used"]
    # And nothing else moved.
    assert retried.budget["submissions_used"] == \
        plain.budget["submissions_used"] == 1
    assert retried.budget["analysis_rounds_used"] == \
        plain.budget["analysis_rounds_used"] == 1
    assert retried.budget["submissions_remaining"] == \
        plain.budget["submissions_remaining"] == 4


def test_a_double_truncation_still_leaves_every_execution_attempt_unspent(
        runtime_factory):
    provider = _provider(QUESTION, _gate(), TRUNCATE, TRUNCATE)
    outcome = runtime_factory(provider).run(QUESTION)
    assert outcome.budget["submissions_used"] == 0
    assert outcome.budget["submissions_remaining"] == 5
    # The analysis round WAS opened -- the request did reach PLANNING -- and
    # the retry did not open a second one.
    assert outcome.budget["analysis_rounds_used"] == 1


# ====================== 8. CreditProbe does not author the plan

def test_creditprobe_writes_no_part_of_the_regenerated_plan(runtime_factory):
    """Section 7.6A. On truncation this application asks Opus again. It does
    not compose a plan, shorten the model's prose into one, or reuse the
    partial response."""
    provider = _provider(QUESTION, _gate(), TRUNCATE, _plan_turn(), ANSWER)
    outcome = runtime_factory(provider).run(QUESTION)

    # Every field of the executed plan is exactly what the model returned.
    assert outcome.plan.plan_id == COMPACT_PLAN["plan_id"]
    assert outcome.plan.method_summary == COMPACT_PLAN["method_summary"]
    assert outcome.plan.fields_required == COMPACT_PLAN["fields_required"]
    assert outcome.results[0].steps[0].executed_code == STAGE2_SQL

    # The retry BRIEF carries no candidate plan and no SQL of this
    # application's writing. (The packet above it legitimately contains the
    # word "select" inside field descriptions; the brief is what this
    # application composed for the turn.)
    retry = next(r for r in provider.requests
                 if r["purpose"] == "opus_plan_compact")
    brief = retry["messages"][-1]["content"]
    assert "SELECT" not in brief.upper()
    assert "plan_id" not in brief
    assert COMPACT_PLAN["method_summary"] not in brief


def test_a_truncated_turn_is_rolled_out_of_the_conversation(runtime_factory):
    """A partial tool_use with no matching tool_result makes the NEXT request
    malformed, and re-sending the prose that overran spends the retry's
    allowance on it."""
    provider = _provider(QUESTION, _gate(), TRUNCATE, _plan_turn(), ANSWER)
    runtime_factory(provider).run(QUESTION)

    retry = next(r for r in provider.requests
                 if r["purpose"] == "opus_plan_compact")
    roles = [m["role"] for m in retry["messages"]]
    # Opening context, then the retry brief. No assistant turn in between,
    # because the truncated one was discarded.
    assert roles == ["user", "user"], roles
    assert not any(m["role"] == "assistant" for m in retry["messages"])


# ====================== 9. progress, and what the reader is not shown

def test_the_progress_line_stays_business_friendly(runtime_factory):
    provider = _provider(QUESTION, _gate(), TRUNCATE, _plan_turn(), ANSWER)
    outcome = runtime_factory(provider).run(QUESTION)

    progress = outcome.machine["progress"]
    assert "Planning the analysis" in progress
    assert "Refining the analysis plan" in progress
    assert progress.index("Planning the analysis") < \
        progress.index("Refining the analysis plan")
    joined = " ".join(progress)
    for internal in ("max_tokens", "JSON", "schema", "truncat", "opus_",
                     "tool_use", "stop_reason"):
        assert internal not in joined, f"{internal} reached the progress line"


def test_the_operator_can_still_see_what_happened(runtime_factory):
    """Business-friendly for the reader is not opaque for an operator."""
    provider = _provider(QUESTION, _gate(), TRUNCATE, _plan_turn(), ANSWER)
    outcome = runtime_factory(provider).run(QUESTION)

    assert outcome.planning["attempts"] == 2
    assert outcome.planning["regenerated"] is True
    assert outcome.planning["bounds"]["steps"] == 6
    truncated = [t for t in outcome.tokens["turns"] if t["truncated"]]
    assert len(truncated) == 1 and truncated[0]["purpose"] == "opus_plan"
    assert any("output allowance" in h.get("why", "")
               for h in outcome.machine["history"])


# ====================== 10. the final answer is a different budget

def test_the_output_allowances_were_not_changed_to_fix_planning():
    assert L.STANDARD_LIMITS.max_opus_output_tokens == 4_096
    assert L.DEEP_LIMITS.max_opus_output_tokens == 6_144


def test_the_final_answer_contract_is_not_told_to_be_terse():
    """Do not reduce final-answer quality to make planning smaller."""
    review = (PROMPTS / "opus_review_and_answer.md").read_text().lower()
    assert "be concise. this is an execution plan" not in review
    assert "smallest complete" not in review
