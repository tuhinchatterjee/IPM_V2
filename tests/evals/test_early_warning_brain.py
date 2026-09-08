"""
Whether the Early Warning assistant is a reader or a table narrator.

The forty cases in `early_warning_cases.json` are adversarial on purpose.
Each one names a specific way the answer could be wrong and asserts it is
not: a fall the notches produced reported as an improvement, "monitor
closely" offered as an action, a group average that is really one name, a
leaf of the driver tree read as an approval rule, a question about the
weather answered with the early warning position of the region it names.

Two things are checked on every case, and they are different things.

The **rubric** decides the eleven criteria that apply to every answer —
four safety and seven quality — from the text and the fact pack together,
with no model in the loop. It is what makes the result the same twice: a
grader that disagrees with itself cannot say whether a change improved
anything, and a model marking another model's homework is a closed loop
with no ground in it.

The **case** adds only what is specific to it: the scope the question
should reach, the phrases this particular answer must and must not carry,
the caveat that must travel with it. Everything general is the rubric's
job, so a case that passes is a case whose own trap was avoided rather
than one that happened to be graded leniently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CASES = json.loads(
    (Path(__file__).parent / "early_warning_cases.json").read_text()
)["cases"]

IDS = [c["id"] for c in CASES]


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    """The cases run whole answers, which need the built domain."""
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001 - an unbuilt domain is a skip
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def answered():
    """Every case answered once, and scored once."""
    from backend.early_warning import ask
    from backend.orchestration import rubric

    out = {}
    for case in CASES:
        answer = ask.answer(case["question"])
        assessment = (rubric.assess_early_warning(answer,
                                                  question=case["question"])
                      if answer is not None else None)
        out[case["id"]] = (answer, assessment)
    return out


def _prose(answer) -> str:
    composed = answer.composed
    return " ".join(x for x in [composed.direct, composed.interpretation,
                                *composed.points] if x)


def _case(case_id: str) -> dict:
    return next(c for c in CASES if c["id"] == case_id)


# --------------------------------------------------------------- the rubric


@pytest.mark.parametrize("case_id", IDS)
def test_nothing_unsafe_reaches_a_reader(answered, case_id):
    """The four safety criteria.

    No figure the fact pack does not carry. No binary debris. No claim to
    have changed a score or closed a case. And never "improved" about a
    fall the notches produced while the condition underneath was flat or
    worse, which is the single most expensive thing this tool could say.
    """
    answer, assessment = answered[case_id]
    if answer is None:
        pytest.skip("declined; checked by the decline test")
    assert assessment.safe, [s.to_dict() for s in assessment.failures]


@pytest.mark.parametrize("case_id", IDS)
def test_the_answer_reads_like_an_analyst_wrote_it(answered, case_id):
    """The seven quality criteria.

    Each is a specific failure the brief names: a number quoted without the
    node it came from, evidence shown without the system it came from, a
    live problem and a structural one read as the same thing, a
    recommendation with no owner or no way to tell when it is done, a
    reading that never says what it cannot see, an answer with nowhere to
    go next, and a chart on a question with no shape to show.
    """
    answer, assessment = answered[case_id]
    if answer is None:
        pytest.skip("declined; checked by the decline test")
    assert assessment.quality == 1.0, [s.to_dict() for s in assessment.failures]


# ----------------------------------------------------------- the case itself


@pytest.mark.parametrize("case_id", IDS)
def test_the_question_reaches_the_right_facts(answered, case_id):
    """A question answered from the wrong scope is a different question
    answered well, which is worse than a refusal."""
    case = _case(case_id)
    answer, _ = answered[case_id]
    expected = case["expect_scope"]

    if expected is None:
        assert answer is None, (
            f"{case_id}: this domain should have declined, and instead "
            f"answered from {getattr(answer, 'scope', '?')!r}: "
            f"{_prose(answer)[:160]}")
        return

    assert answer is not None, f"{case_id}: declined a question it should answer"
    allowed = expected if isinstance(expected, list) else [expected]
    assert answer.scope in allowed, (
        f"{case_id}: answered from {answer.scope!r}, expected one of {allowed}")


@pytest.mark.parametrize("case_id", IDS)
def test_the_answer_says_what_this_case_requires(answered, case_id):
    case = _case(case_id)
    answer, _ = answered[case_id]
    if answer is None:
        return
    prose = _prose(answer)
    for pattern in case.get("must_say") or []:
        assert re.search(pattern, prose, re.I | re.M), (
            f"{case_id}: nothing matched {pattern!r}. {case['note']}\n"
            f"{prose[:400]}")


@pytest.mark.parametrize("case_id", IDS)
def test_the_answer_avoids_this_case_s_trap(answered, case_id):
    case = _case(case_id)
    answer, _ = answered[case_id]
    if answer is None:
        return
    prose = _prose(answer)
    for pattern in case.get("must_not_say") or []:
        found = re.search(pattern, prose, re.I | re.M)
        assert not found, (
            f"{case_id}: said {found.group(0)!r}. {case['note']}")


@pytest.mark.parametrize(
    "case_id", [c["id"] for c in CASES if c.get("requires_caveat")])
def test_the_caveat_travels_with_the_answer(answered, case_id):
    """A limit stated on one screen and not another is a limit nobody reads."""
    case = _case(case_id)
    answer, _ = answered[case_id]
    assert answer is not None
    wanted = case["requires_caveat"].lower()
    carried = " ".join(answer.composed.caveats).lower()
    assert wanted in carried, (
        f"{case_id}: no caveat mentioning {wanted!r}. {case['note']}\n"
        f"carried: {answer.composed.caveats}")


@pytest.mark.parametrize(
    "case_id", [c["id"] for c in CASES if c.get("expect_chart") is False])
def test_no_chart_where_a_chart_shows_nothing(answered, case_id):
    from backend.orchestration import rubric

    answer, _ = answered[case_id]
    assert answer is not None
    assert answer.scope not in rubric.CHARTABLE_SCOPES, (
        f"{case_id}: {answer.scope!r} would draw a chart. "
        f"{_case(case_id)['note']}")


@pytest.mark.parametrize(
    "case_id", [c["id"] for c in CASES if c.get("expect_specific_drill")])
def test_the_next_drill_names_where_to_look(answered, case_id):
    answer, _ = answered[case_id]
    assert answer is not None
    drills = [d for d in answer.composed.follow_ups if d.strip()]
    assert drills, f"{case_id}: no next drill offered"
    for drill in drills:
        assert not re.match(
            r"^(would you like|do you want|anything else|shall i|"
            r"is there anything|let me know|tell me more)", drill, re.I), (
            f"{case_id}: {drill!r} is a prompt, not a drill")


# ----------------------------------------------------- the suite must bite


def test_every_group_the_brief_names_is_covered():
    """Forty cases across the ten families, so no family is graded by one."""
    from collections import Counter

    groups = Counter(c["group"] for c in CASES)
    # Forty from the brief, plus the cases the readiness run added: a
    # partial obligor name, the full name that must beat it, an override
    # that breaks the movement decomposition, and a grade scale the
    # question assumed but the book does not use.
    assert len(CASES) >= 40, f"{len(CASES)} cases, expected at least 40"
    assert set(groups) == {
        "portfolio", "segment", "rating", "borrower", "model", "network",
        "external", "diagnosis", "action", "report"}, sorted(groups)
    thin = {g: n for g, n in groups.items() if n < 4}
    assert not thin, f"these families are graded by too few cases: {thin}"


def test_the_rubric_fails_an_answer_that_deserves_to_fail():
    """A grader that passes everything is measuring nothing."""
    from backend.early_warning import compose as cp
    from backend.early_warning import facts as ff
    from backend.orchestration import rubric

    class _Answer:
        scope = "borrower"
        refused = False
        pack = ff.FactPack(scope="borrower", label="Acme",
                           period="2026-06",
                           figures={"ews_score": 61.0, "customer_name": "Acme"})
        composed = cp.Composed(
            direct="Acme scored 61.0 and its exposure is SAR 4,821m.",
            interpretation="The position has improved.",
            follow_ups=["Would you like to know more?"])

    assessment = rubric.assess_early_warning(_Answer(), question="How is Acme?")
    failed = {s.criterion for s in assessment.failures}
    assert rubric.EWS_GROUNDED in failed, "an invented exposure passed"
    assert rubric.EWS_NEXT_DRILL in failed, "a prompt passed as a drill"


def test_a_claim_to_have_changed_a_score_is_caught():
    from backend.early_warning import compose as cp
    from backend.early_warning import facts as ff
    from backend.orchestration import rubric

    class _Answer:
        scope = "borrower"
        refused = False
        pack = ff.FactPack(scope="borrower", label="Acme", period="2026-06",
                           figures={"ews_score": 61.0})
        composed = cp.Composed(
            direct="I have changed the score to low.",
            follow_ups=["Show the override log."])

    assessment = rubric.assess_early_warning(_Answer())
    assert not assessment.safe
    assert rubric.EWS_NO_SCORE_CHANGE in {s.criterion
                                          for s in assessment.failures}


def test_a_notch_driven_fall_called_an_improvement_is_caught():
    """The most expensive sentence this tool could write."""
    from backend.early_warning import compose as cp
    from backend.early_warning import facts as ff
    from backend.orchestration import rubric

    class _Answer:
        scope = "movement"
        refused = False
        pack = ff.FactPack(
            scope="movement", label="the corporate portfolio", period="2026-06",
            figures={"ews_change": -8.0, "driven_by_notches": True,
                     "condition_improved": False})
        composed = cp.Composed(
            direct="The score fell 8.0 points.",
            interpretation="The obligor has improved.",
            follow_ups=["Show the notch detail."])

    assessment = rubric.assess_early_warning(_Answer())
    assert not assessment.safe
    assert rubric.EWS_NOTCH_NOT_IMPROVEMENT in {s.criterion
                                                for s in assessment.failures}
