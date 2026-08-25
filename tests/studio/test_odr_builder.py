"""
Building a method from a description, and proving it before certifying it.

This is the flagship path: a credit officer describes a forward-looking default
rate in a sentence, CreditProbe reads it, asks only the questions that change
the answer, builds an Analytical IR plan, runs it against a twelve-case fixture
through the production compiler, and compares against a second implementation
written independently from the methodology text.

The point of the second implementation is that it shares no code with the IR,
the compiler or DuckDB. When the two agree, they agree by arithmetic rather than
by construction. It has already earned its keep: it caught the plan reading the
OPENING IFRS 9 stage where it meant the forward one, which would have returned a
plausible number answering a different question.
"""

from __future__ import annotations

import pytest

from backend.studio.builder import (
    FORWARD_RATE_CLARIFICATIONS,
    build_forward_rate_plan,
    build_method,
    read_description,
)
from backend.studio.model import Lifecycle
from backend.studio.validation import (
    FORWARD_RATE_CASES,
    build_forward_rate_pack,
    run_pack,
)

DESCRIPTION = (
    "I want to measure the share of facilities that are performing at a "
    "reporting date and 90 or more days past due one year later."
)


def make_method(answers: dict[str, str], *, id: str = "odr_test"):
    reading = read_description(DESCRIPTION)
    return build_method(
        id=id, name="One Year Forward Default Rate", description=DESCRIPTION,
        reading=reading, answers=answers,
        opening_period="OPEN", closing_period="CLOSE",
    )


def rate_for(answers: dict[str, str]) -> float:
    method = make_method(answers)
    pack = run_pack(build_forward_rate_pack(method), method)
    total = next(c for c in pack.cases if c.id == "portfolio_total")
    assert total.passed, (
        f"The independent calculation and the runtime disagree for {answers}: "
        f"expected {total.expected}, got {total.actual}"
    )
    return float(total.actual["forward_default_rate_pct"])


# --------------------------------------------------------------- reading it


def test_the_description_is_understood_as_a_forward_rate():
    reading = read_description(DESCRIPTION)
    assert reading.understood
    assert reading.kind == "forward_rate"
    assert reading.horizon_periods == 4
    assert reading.detected["dpd_threshold"] == 90


def test_an_unreadable_description_says_so_rather_than_guessing():
    reading = read_description("make it better please")
    assert not reading.understood
    assert not reading.clarifications
    assert "could not tell" in reading.note


def test_the_clarifications_are_the_ones_that_change_the_answer():
    # "facilities" settles the grain, so it is not asked. Everything the
    # sentence left open is.
    reading = read_description(DESCRIPTION)
    asked = {c.id for c in reading.clarifications}
    assert {"default_definition", "timing", "exits", "weighting"} <= asked
    assert reading.detected["grain"] == "facility"


def test_a_clarification_already_answered_by_the_text_is_not_asked_again():
    reading = read_description(
        "share of CUSTOMERS performing now and in default one year later, "
        "weighted by EAD"
    )
    asked = {c.id for c in reading.clarifications}
    assert "grain" not in asked
    assert "weighting" not in asked


def test_every_clarification_explains_why_it_matters():
    for clarification in FORWARD_RATE_CLARIFICATIONS:
        assert clarification.because.strip()
        assert len(clarification.options) >= 2
        assert clarification.default in {o["id"] for o in clarification.options}


# -------------------------------------------------------------- building it


def test_a_built_method_is_not_born_certified():
    method = make_method({})
    assert method.lifecycle == Lifecycle.BUILT
    assert not method.is_certified
    assert method.source == "bank"


def test_a_built_method_states_its_methodology_and_its_limits():
    method = make_method({})
    assert "Opening population" in method.methodology
    assert "Default:" in method.methodology
    assert method.limitations.strip()
    assert method.required_fields


def test_the_answers_are_recorded_on_the_plan():
    answers = {"grain": "customer", "default_definition": "either"}
    plan = build_forward_rate_plan(opening_period="OPEN", closing_period="CLOSE",
                                   answers=answers)
    assert plan["meta"]["answers"] == answers
    assert plan["meta"]["kind"] == "forward_rate"


def test_the_default_test_reads_the_forward_observation_not_the_opening_one():
    """The bug the validation pack caught, pinned so it cannot come back."""
    import json

    plan = build_forward_rate_plan(opening_period="OPEN", closing_period="CLOSE",
                                   answers={"default_definition": "either"})
    text = json.dumps(plan)
    assert "forward_dpd_days" in text
    assert "forward_ifrs9_stage" in text
    assert '"args": ["dpd_days"' not in text


def test_default_at_any_point_is_refused_rather_than_approximated():
    """The second bug the pack caught. Reading status only at the horizon and
    calling it 'default at any point' understates the rate silently."""
    with pytest.raises(ValueError, match="every reporting period"):
        build_forward_rate_plan(opening_period="OPEN", closing_period="CLOSE",
                                answers={"timing": "anytime"})


def test_the_builder_refuses_a_kind_it_cannot_build():
    reading = read_description("the split of exposure by sector")
    with pytest.raises(ValueError, match="forward-looking rates"):
        build_method(id="x", name="X", description="", reading=reading,
                     answers={}, opening_period="OPEN", closing_period="CLOSE")


# --------------------------------------------------------------- proving it


def test_the_pack_covers_the_contentious_situations():
    ids = {c["id"] for c in FORWARD_RATE_CASES}
    assert {"stays_performing", "defaults_at_horizon", "already_defaulted",
            "boundary_89", "boundary_90_closing", "no_forward_observation",
            "cured_before_horizon", "stage3_no_arrears"} <= ids


def test_the_pack_carries_its_own_fixture_and_expectations():
    pack = build_forward_rate_pack(make_method({}))
    assert pack.dataset, "A reviewer must be able to read the rows."
    assert len(pack.cases) == len(FORWARD_RATE_CASES) + 1
    assert all(c.expected for c in pack.cases)


def test_the_runtime_agrees_with_the_independent_calculation():
    assert rate_for({}) == pytest.approx(44.444444, abs=1e-4)


def test_an_unrun_pack_is_not_a_passed_pack():
    pack = build_forward_rate_pack(make_method({}))
    assert not pack.complete
    assert not pack.all_passed


def test_a_run_pack_is_complete():
    method = make_method({})
    pack = run_pack(build_forward_rate_pack(method), method)
    assert pack.complete
    assert pack.all_passed
    assert pack.failed == 0


# ------------------------------------------------- the answers change the answer


@pytest.mark.parametrize("answers,expected", [
    ({}, 44.444444),                                    # 90+ DPD at horizon
    ({"default_definition": "stage3"}, 11.111111),      # accounting definition
    ({"default_definition": "either"}, 55.555556),      # the widest
    ({"exits": "non_default"}, 40.0),                   # exits counted as good
    ({"grain": "customer"}, 44.444444),                 # one facility each here
    ({"weighting": "ead"}, 44.444444),
])
def test_each_methodology_choice_produces_the_rate_it_should(answers, expected):
    assert rate_for(answers) == pytest.approx(expected, abs=1e-4)


def test_the_choices_genuinely_diverge():
    """If every answer produced the same number the clarifications would be
    theatre. They are not."""
    rates = {
        rate_for({}),
        rate_for({"default_definition": "stage3"}),
        rate_for({"default_definition": "either"}),
        rate_for({"exits": "non_default"}),
    }
    assert len(rates) == 4


def test_a_method_may_be_certified_only_once_its_pack_has_passed():
    method = make_method({})
    ok, missing = method.can_certify()
    assert not ok and "test cases" in " ".join(missing)

    pack = run_pack(build_forward_rate_pack(method), method)
    method.test_cases = pack.cases
    ok, missing = method.can_certify()
    assert ok, f"Still missing: {missing}"


def test_a_failing_pack_blocks_certification():
    method = make_method({})
    pack = run_pack(build_forward_rate_pack(method), method)
    method.test_cases = pack.cases
    method.test_cases[0].passed = False
    ok, missing = method.can_certify()
    assert not ok
    assert any("failing" in m for m in missing)
