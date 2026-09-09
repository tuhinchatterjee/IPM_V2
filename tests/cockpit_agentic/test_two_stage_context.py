"""The two-stage Opus context. Defect 1 of the live UAT.

Live UAT stopped "Who are you?" before it was sent: 60,530 input tokens plus
the 4,096 the same call needs for its reply is 64,626 against a 64,000-token
ceiling. The packet was the complete field dictionary — 751 field definitions,
40 ratio formulas, the join graph, the coverage table, the sample rows and the
SQL execution contract — assembled to find out whether the question was about
the portfolio at all. It was not.

So there are two packets now. Stage A is what the gate decides from. Stage B is
the complete analytical packet, and it is built ONLY for a request the gate has
ruled `query_mode = DATA_ANALYSIS` and `owner = COCKPIT`.

These tests use the LABELLED MOCK provider. They prove what the application
sends and when — which is the defect. They prove nothing about how a real model
classifies a sentence.
"""

from __future__ import annotations

import json

import pytest

from backend.cockpit_agentic import catalog as catalog_mod
from backend.cockpit_agentic import context as context_mod
from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic import ledger as L
from backend.cockpit_agentic import opus as opus_mod
from backend.cockpit_agentic import scope as scope_mod
from backend.cockpit_agentic import sql as sql_mod
from backend.cockpit_agentic import states as st
from backend.cockpit_agentic.contracts import (CleanedQuestion,
                                               NormalizedQuestion)
from tests.cockpit_agentic.conftest import Principal, RELEASE, scores
from tests.cockpit_agentic.fake_provider import FakeProvider, expand

SQL = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
       "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")

PLAN = {"plan_id": "plan-2s", "subquestions": ["the change in reported ECL"],
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
                        converse_script=[(lambda _r, t=t: t)
                                        for t in expand(turns)])


def _gate(mode, owner, **extra):
    body = {"decision": "PROCEED_COCKPIT", "scores": scores(),
            "public_explanation": "why", "query_mode": mode, "owner": owner}
    body.update(extra)
    return body


def _who_are_you(sonnet_answers):
    """The exact live-UAT question, through both preprocessing passes."""
    return [
        {"language": "en", "english_text": "Who are you?",
         "preserved_terms": [], "uncertainties": []},
        {"business_question": "Who are you?", "subquestions": ["who are you"],
         "requested_measures": [], "requested_actions": ["explain"],
         "explicit_scope": {}, "inherited_scope": {}, "periods": [],
         "entity_references": [], "unresolved_ambiguity": []},
    ]


PRODUCT_ANSWER = {"narrative": "I am the Cockpit: the part of CreditProbe that "
                               "answers questions about your recorded IFRS 9 "
                               "credit book.", "complete": True}


# ---------------------------------------------------------------- fixtures

@pytest.fixture()
def packets(lake):
    """Both packets for one question, built the way the runtime builds them."""
    def make(question="Who are you?"):
        scope = scope_mod.for_principal(Principal(),
                                        dataset_release_id=RELEASE)
        catalog = catalog_mod.build(dataset_release_id=RELEASE,
                                    calendar=lake["calendar"],
                                    tenant_id=scope.tenant_id)
        ledger, _ = L.LedgerStore().open(request_id="two-stage",
                                         mode="standard", prices=L.Prices())
        cleaned = CleanedQuestion(original_text=question,
                                  detected_language="en",
                                  english_text=question, preserved_terms=[],
                                  uncertainties=[])
        normalized = NormalizedQuestion(
            business_question=question, subquestions=[question],
            requested_measures=[], requested_actions=[], explicit_scope={},
            inherited_scope={}, periods=[], entity_references=[],
            unresolved_ambiguity=[])
        session = sql_mod.open_session(scope=scope, catalog=catalog)
        args = dict(request_id="two-stage", cleaned=cleaned,
                    normalized=normalized, scope=scope, catalog=catalog,
                    coverage=lake["coverage"], ledger=ledger, session=session)
        gate = context_mod.build_gate(
            **args, reserve_tokens=ledger.limits.max_opus_output_tokens,
            measure=opus_mod.request_sizer(stage=context_mod.GATE_STAGE,
                                           contract="opus_gate",
                                           schema=opus_mod.GATE_SCHEMA))
        analysis = context_mod.build(
            **args,
            reserve_tokens=(ledger.limits.max_opus_output_tokens
                            + opus_mod.CONVERSATION_RESERVE),
            measure=opus_mod.request_sizer(stage=context_mod.ANALYSIS_STAGE,
                                           contract="opus_plan",
                                           schema=opus_mod.PLAN_SCHEMA))
        # The packet as it USED to be built for the gate: the whole thing,
        # measured against the per-call cap on its own, so the reduction
        # ladder never fired. That is the request the live run assembled.
        before = context_mod.build(**args)
        return gate, analysis, ledger, before

    return make


# ============================================ 1-2. what stage A carries

def test_the_gate_packet_carries_everything_the_gate_decides_from(packets):
    gate, _analysis, _ledger, _before = packets()
    payload = gate.payload
    assert gate.stage == context_mod.GATE_STAGE

    # The whole question, in all three forms, with what preprocessing found.
    request = payload["A_request"]
    assert request["original_question"] == "Who are you?"
    assert request["english_translation"] == "Who are you?"
    assert request["business_request"] == "Who are you?"
    for key in ("subquestions", "requested_measures", "requested_actions",
                "entity_references", "periods", "unresolved_ambiguity"):
        assert key in request, f"the gate cannot see {key}"

    # The module and the high-level scope.
    assert payload["B_scope"]["current_module"] == "Cockpit"
    assert payload["B_scope"]["dataset_release_id"] == RELEASE

    # The thread: a follow-up cannot be classified without what it follows.
    assert "rolling_summary" in payload["C_thread"]
    assert "recent_exchanges" in payload["C_thread"]

    # Product knowledge: the complete functionality registry, unreduced.
    from backend.cockpit_agentic import registry

    listed = {f["id"]
              for f in payload["H_functionalities"]["functionalities"]}
    assert listed == set(registry.FUNCTIONALITY_IDS)

    # The domain by name, in outline, with the quarters that exist.
    outline = payload["D_domain_outline"]
    assert outline["domain_name"]
    assert len(outline["reporting_quarters"]) == 20
    assert {a["relation"] for a in outline["subject_areas"]} == \
        set(catalog_mod.QUERYABLE_RELATIONS)

    # Coverage at a high level, and the ledger's budgets.
    assert payload["F_coverage_outline"]["row_counts"]
    assert payload["J_budget"]["max_input_tokens_per_call"] == 64_000


def test_the_gate_packet_carries_none_of_the_analytical_detail(packets):
    """The list of what stage A must NOT contain, checked item by item."""
    gate, _analysis, _ledger, _before = packets()
    blob = json.dumps(gate.payload, default=str)

    assert "D_E_catalogue" not in gate.payload
    assert "G_samples" not in gate.payload
    assert "F_coverage" not in gate.payload

    # No relation.column catalogue and no field definitions. Every one of
    # these is in the dictionary and nowhere else. (Relation GRAIN keys --
    # borrower_id, reporting_quarter, statement_scope -- do appear, because
    # naming the grain of a subject area is what an outline is for.)
    for column in ("ecl_reported", "pd_pit_12m", "pd_ttc_12m", "lgd_reported",
                   "gross_market_value", "ifrs9_stage", "ead_reported"):
        assert column not in blob, f"{column} reached the gate packet"

    # The ratio definitions are a COUNT here, not forty formulas.
    outline = gate.payload["D_domain_outline"]
    assert isinstance(outline["ratio_definitions"], int)
    assert "DATA SEMANTICS" not in blob
    assert "_source_value" not in blob

    # No qualitative question text and no macro pivot columns.
    assert "real_gdp_growth_yoy_lead4" not in blob
    assert "question_text" not in blob
    assert "offset_suffixes" not in blob

    # No join graph, no per-field missingness table, no sample rows, and no
    # SQL execution contract.
    assert '"joins"' not in blob
    assert '"fields_with_gaps"' not in blob
    assert "miss_applicable" not in blob
    assert "quarters_fully_missing" not in blob
    assert "DuckDB" not in blob
    assert "max_model_rows" not in blob
    assert "statement_rule" not in blob
    assert "wall_seconds_per_step" not in blob
    assert "samples" not in blob

    # And it says what it is, so nothing downstream can mistake it for the
    # dictionary and plan from it.
    assert "NOT THE FIELD DICTIONARY" in \
        gate.payload["D_domain_outline"]["outline_note"].upper()


# ============================================ 3-5. who gets which packet

@pytest.mark.parametrize("mode", [K.PRODUCT_HELP, K.THEORY_CONCEPT])
def test_a_question_answered_from_knowledge_never_assembles_the_dictionary(
        runtime_factory, sonnet_answers, mode):
    provider = _provider(
        _who_are_you(sonnet_answers),
        _gate(mode, K.OWNER_COCKPIT, answer=PRODUCT_ANSWER))
    outcome = runtime_factory(provider).run("Who are you?")

    assert outcome.status == st.COMPLETED
    assert provider.purposes() == ["opus_gate"], (
        "a question answered from knowledge made more than the gate call")
    assert outcome.context["stages_built"] == ["gate"]
    assert outcome.context["full_catalogue_sent"] is False
    # Nothing from the dictionary went anywhere near the provider.
    blob = provider.serialized()
    assert "ecl_reported" not in blob
    assert "DATA SEMANTICS" not in blob
    assert "DuckDB" not in blob


def test_a_cockpit_data_analysis_gets_the_second_full_packet(
        runtime_factory, sonnet_answers):
    provider = _provider(
        sonnet_answers,
        _gate(K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN, steps=_steps()),
        ANSWER)
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.status == st.COMPLETED
    assert provider.purposes() == ["opus_gate", "opus_plan", "opus_review"]
    assert outcome.context["stages_built"] == ["gate", "analysis"]
    assert outcome.context["full_catalogue_sent"] is True
    assert outcome.context["analysis"]["stage"] == context_mod.ANALYSIS_STAGE


@pytest.mark.parametrize("mode,owner,expected", [
    (K.OTHER_FUNCTIONALITY, K.OWNER_EWS, st.REDIRECTED),
    (K.CLARIFICATION_REQUIRED, K.OWNER_NONE, st.WAITING_FOR_USER),
    (K.UNSUPPORTED_MODE, K.OWNER_NONE, st.UNSUPPORTED),
])
def test_no_other_route_out_of_the_gate_builds_the_full_packet(
        runtime_factory, sonnet_answers, mode, owner, expected):
    extra = {}
    if mode == K.OTHER_FUNCTIONALITY:
        extra = {"referral_destination": "ews", "referral_reason": "theirs"}
    if mode == K.CLARIFICATION_REQUIRED:
        extra = {"clarification_question": "Which book?"}
    provider = _provider(sonnet_answers, _gate(mode, owner, **extra))
    outcome = runtime_factory(provider).run("Something")

    assert outcome.status == expected
    assert provider.purposes() == ["opus_gate"]
    assert outcome.context["full_catalogue_sent"] is False


def test_a_failed_score_test_stops_at_the_gate_packet(
        runtime_factory, sonnet_answers):
    """The server's own ownership test, applied after the gate returns. It
    must not have cost a full analytical packet to get there."""
    tied = _gate(K.DATA_ANALYSIS, K.OWNER_COCKPIT,
                 scores=scores(cockpit=72, ews=71), plan=PLAN,
                 steps=_steps())
    provider = _provider(sonnet_answers, tied)
    outcome = runtime_factory(provider).run("Something ambiguous")

    assert outcome.status == st.WAITING_FOR_USER
    assert provider.purposes() == ["opus_gate"]
    assert outcome.context["full_catalogue_sent"] is False


# ============================================ 6. it is still Opus deciding

def test_the_gate_is_a_model_decision_and_not_a_keyword_router(
        runtime_factory, sonnet_answers):
    """Two questions that share their vocabulary and differ in what they ask
    for. The application does what the model said in each case, and there is
    no branch here that reads the words.

    This is the guarantee that shrinking the packet did not turn the gate into
    a router: the mock returns opposite decisions for near-identical text, and
    both are obeyed.
    """
    words = "Tell me about lifetime PD"

    theory = _provider(sonnet_answers,
                       _gate(K.THEORY_CONCEPT, K.OWNER_COCKPIT,
                             answer={"narrative": "Lifetime PD is the "
                                                  "probability of default over "
                                                  "the remaining life.",
                                     "complete": True}))
    first = runtime_factory(theory).run(words)

    analysis = _provider(sonnet_answers,
                         _gate(K.DATA_ANALYSIS, K.OWNER_COCKPIT, plan=PLAN,
                               steps=_steps()),
                         ANSWER)
    second = runtime_factory(analysis).run(words)

    assert first.decision.query_mode == K.THEORY_CONCEPT
    assert second.decision.query_mode == K.DATA_ANALYSIS
    assert theory.purposes() == ["opus_gate"]
    assert second.context["full_catalogue_sent"] is True
    # The gate packet the two requests were given is the same one.
    assert first.context["gate"]["breakdown"]["H_functionalities"] == \
        second.context["gate"]["breakdown"]["H_functionalities"]


# ============================================ 7-8. the measurement

def test_the_gate_request_is_a_fraction_of_what_it_was(packets):
    """BEFORE and AFTER for "Who are you?", measured the same way.

    BEFORE is the packet this module used to build for the gate: the complete
    dictionary, the coverage table, the sample rows and the execution
    contract, rendered into a gate request. AFTER is `build_gate`.

    Both are LOCAL ESTIMATES at the calibrated 2.2 characters per token, not
    provider counts -- there is no credential in this environment. The live
    reference point they are anchored to is the UAT measurement of 60,530
    tokens for the BEFORE request, against which the same estimator read
    63,767: the estimate runs about 5% above the provider's count for this
    content, so it is conservative in the right direction.
    """
    gate, analysis, ledger, before_packet = packets()

    before = opus_mod.request_sizer(
        stage=context_mod.ANALYSIS_STAGE, contract="opus_gate",
        schema=opus_mod.GATE_SCHEMA)(before_packet.payload)
    after = gate.request_tokens

    reply = ledger.limits.max_opus_output_tokens
    cap = ledger.limits.max_input_tokens_per_call

    # BEFORE: the whole thing, plus the reply the same call needs, over the
    # ceiling. This is the defect, reproduced.
    assert before + reply > cap, (
        f"the before-request no longer reproduces the defect: {before}")
    # AFTER: comfortably inside it, with room for the answer.
    assert after + reply < cap
    assert after < before / 3, (
        f"before={before} after={after}: the gate packet did not shrink")
    print(f"\n'Who are you?' gate request  BEFORE {before:,} tokens  "
          f"AFTER {after:,} tokens  (ceiling {cap:,}, reply {reply:,})")


def test_the_ceiling_was_not_raised_to_make_this_fit():
    """The guardrail is untouched. The packet got smaller, not the limit
    bigger."""
    assert L.STANDARD_LIMITS.max_input_tokens_per_call == 64_000
    assert L.STANDARD_LIMITS.max_opus_output_tokens == 4_096
    assert L.DEEP_LIMITS.max_input_tokens_per_call == 96_000
    assert L.DEEP_LIMITS.max_opus_output_tokens == 6_144


# ============================================ 9-10. stage B is still complete

def test_the_analysis_packet_still_carries_the_complete_dictionary(packets):
    """Section 7.4 is unchanged: the packet that PLANS an analysis carries
    every authorized field. Stage A is a different packet, not an abridged
    one."""
    _gate_packet, analysis, _ledger, _before = packets()
    catalogue = analysis.payload["D_E_catalogue"]
    named = set()
    for relation, body in catalogue["relations"].items():
        for spec in body.get("fields", []):
            named.add((relation, spec["n"]))
        for family in body.get("column_families", []):
            for name in family["names"]:
                named.add((relation, name))
    for key in catalogue["common_keys"]["fields"]:
        for relation in F.RELATIONS:
            named.add((relation, key["n"]))

    missing = [(r, s.name) for r in F.RELATIONS
               for s in F.fields_of(r) if (r, s.name) not in named]
    assert not missing, f"the analysis packet abridged the dictionary: {missing[:5]}"
    assert len(catalogue["ratio_definitions"]) == len(F.RATIO_DEFINITIONS)
    assert catalogue["joins"] == [dict(j) for j in F.JOINS]


def test_the_two_stages_pin_different_prefixes_and_neither_changes_under_itself(
        packets):
    """Two stages are two conversations. Each has ONE cache breakpoint, and
    the block above it is what that stage pinned -- the outline for the gate,
    the dictionary for the analysis."""
    gate, analysis, _ledger, _before = packets()

    gate_blocks = opus_mod.system_blocks(gate, "opus_gate")
    analysis_blocks = opus_mod.system_blocks(analysis, "opus_plan")

    for blocks in (gate_blocks, analysis_blocks):
        breakpoints = [b for b in blocks if b.get("cache_control")]
        assert len(breakpoints) == 1
        assert blocks.index(breakpoints[0]) == 1

    assert "domain_outline" in gate_blocks[1]["text"]
    assert "catalogue" in analysis_blocks[1]["text"]
    assert "ecl_reported" not in gate_blocks[1]["text"]
    assert "ecl_reported" in analysis_blocks[1]["text"]

    # Rendering twice gives byte-identical prefixes, so every turn of a stage
    # is a cache hit rather than a re-read.
    assert opus_mod.system_blocks(gate, "opus_gate")[:2] == gate_blocks[:2]
    assert opus_mod.system_blocks(analysis, "opus_plan")[:2] == \
        analysis_blocks[:2]


def test_how_many_analysis_turns_each_mode_affords(packets):
    """The capacity finding, recorded rather than discovered in production.

    Under a calibrated token estimate the complete dictionary plus a growing
    repair conversation does not fit Standard's per-call cap for the whole
    five-submission path. Standard affords the plan and about one further
    turn; Deep affords the full sequence. This is a configuration fact about
    this domain's dictionary, and it is pinned here so that a change to either
    the packet or the cap has to come past it.
    """
    _gate_packet, analysis, ledger, _before = packets()
    first = analysis.request_tokens
    reply = ledger.limits.max_opus_output_tokens
    standard = L.STANDARD_LIMITS.max_input_tokens_per_call

    assert first + reply < standard, (
        "the first analysis turn no longer fits Standard at all")
    headroom = standard - reply - first
    # Measured: a repair turn carrying its failure packet costs about 3,300.
    assert headroom < 4 * 3_300, (
        "Standard now affords the full five-submission path; if that is real, "
        "the tests that were moved to Deep for this reason can come back")
    assert L.DEEP_LIMITS.max_input_tokens_per_call - reply - first \
        > 4 * 3_300
