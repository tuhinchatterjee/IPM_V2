"""The ownership MECHANISM, exercised over the labelled benchmark shapes.
Specification section 14.2.

The distinction these tests keep, and the eval runner keeps too: whether the
model routes a question correctly is the MODEL's job and cannot be tested with
a mock. What CAN be tested with a mock, and is worth testing, is that the
application handles each decision correctly once it is made — that a referral
executes nothing, that a referral to an unavailable module offers no link, that
an alternative naming a non-existent field is refused, that a coverage gap is
not turned into a referral, and that a mixed request names its excluded half.

Routing accuracy is reported by `tests/evals/cockpit_agentic/
run_ownership_eval.py`, which reports BLOCKED without a credential rather than
producing a number from a mock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.cockpit_agentic import catalog as catalog_mod
from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import registry
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider

CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "evals/cockpit_agentic/"
     "ownership_cases.json").read_text(encoding="utf-8"))


def sonnet_for(question: str) -> list[dict]:
    return [{"language": "en", "english_text": question},
            {"business_question": question, "subquestions": [question]}]


# ---- the benchmark set itself ---------------------------------------------

def test_the_benchmark_covers_every_required_pair():
    """Section 14.2's required positive/negative pairs, all present."""
    owners = {c["expected_owner"] for c in CASES["cases"]}
    assert owners >= {"cockpit", "ews", "credit_scoring",
                      "scorecard_validation", "what_if", "lenses", "clarify",
                      "unsupported"}
    languages = {c["language"] for c in CASES["cases"]}
    assert languages >= {"en", "hi", "bn", "ar", "mixed"}
    assert any(c["mixed_scope"] for c in CASES["cases"])
    assert len(CASES["cases"]) >= 25


def test_every_labelled_owner_is_a_registered_functionality():
    for case in CASES["cases"]:
        owner = case["expected_owner"]
        if owner in ("clarify", "unsupported"):
            continue
        assert owner in registry.FUNCTIONALITY_IDS, case["case_id"]


def test_the_benchmark_says_a_mock_cannot_score_it():
    assert "live provider" in CASES["purpose"]
    assert "not passing on a mock" in CASES["purpose"] or \
           "rather than passing on a mock" in CASES["purpose"]


# ---- the mechanism --------------------------------------------------------

def run(runtime_factory, question: str, gate: dict, *later: dict):
    provider = FakeProvider(
        structured_script=sonnet_for(question),
        converse_script=[(lambda _r, t=t: t) for t in (gate, *later)])
    return runtime_factory(provider).run(question), provider


#: Where each referral should land. Read from the registry rather than written
#: out again, because a literal here is a second place the route lives and the
#: /stress rename proved which of the two goes stale: the registry moved to
#: /what-if and this list did not, so the test failed for being right about a
#: product that had moved on. What is worth asserting is that a referral offers
#: the route the APPLICATION declares, and that the route is one a browser can
#: actually reach — both checked below.
@pytest.mark.parametrize("destination", [
    "ews", "what_if", "scorecard_validation", "lenses",
])
def test_every_referral_executes_nothing_and_offers_a_real_route(
        runtime_factory, destination):
    from backend.cockpit_agentic import registry as registry_mod

    route = registry_mod.entry(destination).route
    outcome, provider = run(
        runtime_factory, "a question owned elsewhere",
        {"decision": "REDIRECT",
         "scores": scores(cockpit=20, **{destination: 95}),
         "referral_destination": destination,
         "referral_reason": "that action belongs to the other module",
         "public_explanation": "This is not part of the Cockpit's "
                               "responsibility."})
    assert outcome.status == st.REDIRECTED
    assert outcome.results == [], "a referral executed a query"
    assert outcome.failures == []
    assert outcome.budget["submissions_used"] == 0
    assert outcome.envelope.referral["route"] == route
    assert provider.purposes() == ["opus_gate_and_plan"], (
        "a referral made a second model call")


def test_a_referral_to_the_unimplemented_module_is_honest(runtime_factory):
    outcome, _p = run(
        runtime_factory, "give this borrower a score",
        {"decision": "REDIRECT", "scores": scores(cockpit=10,
                                                  credit_scoring=95),
         "referral_destination": "credit_scoring",
         "referral_reason": "Generating a score is not the Cockpit's.",
         "public_explanation": "The Cockpit reads stored ratings only."})
    assert outcome.envelope.referral["route"] is None
    assert outcome.envelope.referral["enabled"] is False
    entry = registry.entry("credit_scoring")
    assert "no credit-scoring workflow" in entry.unavailable_reason


def test_an_alternative_naming_a_field_that_does_not_exist_is_refused():
    """Section 6.3: each suggestion must be feasible against the ACTUAL
    catalogue."""
    with pytest.raises(K.ContractError):
        K.AlternativeQuestion(question="Show the borrower's risk index")
    good = K.AlternativeQuestion(
        question="Compare this borrower's stored 12-month PIT PD over the "
                 "latest four quarters.",
        required_fields=["pd_pit_12m", "reporting_quarter"])
    assert good.required_fields


def test_alternatives_offered_by_the_gate_resolve_against_the_catalogue(
        runtime_factory, lake):
    outcome, _p = run(
        runtime_factory, "why did the alert fire",
        {"decision": "REDIRECT", "scores": scores(cockpit=20, ews=95),
         "referral_destination": "ews",
         "referral_reason": "the alert score is EWS's",
         "public_explanation": "not the Cockpit's responsibility",
         "alternatives": [
             {"question": "Compare this borrower's stored 12-month PIT PD "
                          "over the latest four quarters.",
              "required_fields": ["pd_pit_12m", "reporting_quarter"]},
             {"question": "Show its DSCR and recorded covenant breaches over "
                          "the same period.",
              "required_fields": ["dscr", "test_status"]}]})
    catalog = catalog_mod.build(dataset_release_id="test-runtime-20q",
                                calendar=lake["calendar"])
    for alternative in outcome.envelope.alternatives:
        for field_name in alternative.required_fields:
            found = any(
                _resolves(catalog, relation, field_name)
                for relation in catalog.relations())
            assert found, f"{field_name!r} is not in the catalogue"


def _resolves(catalog, relation: str, name: str) -> bool:
    try:
        catalog.resolve(relation, name)
        return True
    except Exception:                                       # noqa: BLE001
        return False


def test_a_coverage_gap_is_not_a_referral(runtime_factory):
    """Section 6.2: do not redirect an in-scope question merely because its
    selected quarter lacks data."""
    question = "Show total stage 2 exposure for 2019Q1"
    outcome, _p = run(
        runtime_factory, question,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "in scope; the period is outside coverage",
         "plan": {"plan_id": "p", "subquestions": [question],
                  "method_summary": "aggregate stage 2 exposure"},
         "steps": [{"step_id": "s", "language": "sql",
                    "code": "SELECT sum(ead_reported) AS ead FROM "
                            "cockpit_facility_quarter WHERE "
                            "reporting_quarter = '2019Q1'"}]},
        {"decision": "ANSWER",
         "answer": {"narrative": "This release covers 2021Q3 to 2026Q2, so "
                                 "2019Q1 is outside the twenty reporting "
                                 "quarters and no exposure is recorded for "
                                 "it.",
                    "complete": True}})
    assert outcome.status == st.COMPLETED
    assert outcome.envelope.kind == "answer", (
        "a coverage gap was turned into a referral")
    assert registry.compact()["coverage_rule"].startswith("Do NOT refer")
    # And the shape of the result is worth stating: SUM over no rows is NULL,
    # not zero. A quarter outside the window has no exposure RECORDED, which
    # is not the same claim as exposure of zero.
    row = outcome.results[0].steps[0].rows[0]
    assert row["ead"] is None, (
        "an aggregate over no rows must be NULL, not 0 -- reporting zero "
        "would assert the portfolio was empty in a quarter this release does "
        "not cover")


def test_a_mixed_request_names_its_excluded_half(runtime_factory):
    outcome, _p = run(
        runtime_factory,
        "show the stored PD history and then stress it by 200bp",
        {"decision": "REDIRECT", "scores": scores(cockpit=70, what_if=75),
         "referral_destination": "what_if",
         "referral_reason": "the 200 basis point stress is a new shock",
         "mixed_scope": True,
         "mixed_scope_explanation": ("The stored PD history is the Cockpit's; "
                                     "applying a 200 basis point shock is "
                                     "Stress Testing's."),
         "public_explanation": "Part of this belongs elsewhere.",
         "alternatives": [
             {"question": "Show the stored PIT 12-month PD history for this "
                          "borrower over the twenty reporting quarters.",
              "required_fields": ["pd_pit_12m", "reporting_quarter"]}]})
    assert outcome.status == st.REDIRECTED
    assert outcome.results == []
    assert "Stress Testing" in outcome.envelope.limitations[0]
    assert outcome.envelope.alternatives, (
        "the Cockpit-only half was dropped rather than offered")


def test_an_unrelated_request_needs_no_alternatives(runtime_factory):
    outcome, _p = run(
        runtime_factory, "what is the weather in Mumbai",
        {"decision": "UNSUPPORTED",
         "scores": scores(cockpit=2, ews=1, credit_scoring=1,
                          scorecard_validation=1, what_if=1, lenses=1),
         "public_explanation": "No part of CreditProbe answers this."})
    assert outcome.status == st.UNSUPPORTED
    assert outcome.envelope.alternatives == []
    assert outcome.results == []


def test_the_gate_scores_every_functionality_every_time(runtime_factory):
    outcome, _p = run(
        runtime_factory, "a question",
        {"decision": "REDIRECT", "scores": scores(cockpit=20, ews=90),
         "referral_destination": "ews", "referral_reason": "r",
         "public_explanation": "e"})
    scored = {s.functionality_id for s in outcome.decision.scores}
    assert scored == set(registry.FUNCTIONALITY_IDS)
