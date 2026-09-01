"""
§80 — pairwise analyst-judgment cases.

    "Create pairwise preference cases. … Use for prompt/critic evaluation.
     Do not claim model fine-tuning occurred."

The property these tests protect
--------------------------------
An evaluation set whose wrong answers are obviously wrong measures nothing.
The failure §80 is about is precisely that the wrong answer is persuasive:
fluent, grounded in the same evidence, and exactly what a competent person
would write. So the tests below check that both answers in every pair are
substantial, that the pair isolates one dimension, and that the rejected
answer carries the failure tags naming what is actually wrong with it —
rather than checking a count of cases, which would pass on ten pairs of
"good answer" against "asdf".
"""

from __future__ import annotations

from backend.teaching import failures as fl
from intelligence_factory import judgment_cases as jc


def test_every_dimension_section_80_names_has_at_least_one_pair():
    assert len(jc.DIMENSIONS) == 10
    assert jc.gaps() == []
    assert set(jc.coverage()) == set(jc.DIMENSIONS)


def test_case_ids_are_unique_and_indexed():
    ids = [c.case_id for c in jc.CASES]
    assert len(set(ids)) == len(ids)
    assert set(jc.BY_ID) == set(ids)


def test_every_case_declares_a_dimension_the_taxonomy_knows():
    for case in jc.CASES:
        assert case.dimension in jc.DIMENSIONS


def test_both_answers_are_answers_a_reader_would_believe():
    """The bad answers here are deliberately good. A pair where the rejected
    answer is also badly written measures writing, and there is no shortage
    of that."""
    for case in jc.CASES:
        for answer in (case.answer_a, case.answer_b):
            # Nine, not twenty: the exceptions pair's rejected answer is
            # deliberately terse — "Manufacturing improved over the quarter,
            # with ECL down SAR 3m." is arithmetically true and describes the
            # portfolio as badly as any sentence could, and its brevity is the
            # failure being isolated rather than a defect in the fixture.
            assert len(answer.split()) >= 9, case.case_id
            assert answer.strip().endswith("."), case.case_id
        # Neither is a stub of the other.
        assert case.answer_a != case.answer_b


def test_both_answers_in_a_pair_were_given_the_same_evidence():
    """A pair where one answer had better evidence measures the evidence."""
    for case in jc.CASES:
        assert case.validated_evidence, case.case_id
        assert len(case.validated_evidence) >= 1


def test_every_preference_is_explained_rather_than_asserted():
    """Knowing that a judge picked B is worth much less than knowing why B is
    the wrong pick, so a pair with no reasons is not usable for prompt or
    critic evaluation."""
    for case in jc.CASES:
        assert len(case.preference_reasons) >= 2, case.case_id
        for reason in case.preference_reasons:
            assert len(reason.split()) >= 6, case.case_id


def test_every_rejected_answer_is_tagged_with_a_known_failure_category():
    """§34's taxonomy, so a judge's misses aggregate with everything else's."""
    for case in jc.CASES:
        assert case.failure_tags, case.case_id
        for tag in case.failure_tags:
            assert tag in fl.IDS, (case.case_id, tag)


def test_preferred_and_rejected_resolve_to_the_two_answers():
    for case in jc.CASES:
        assert case.preferred_answer in (jc.A, jc.B)
        assert {case.preferred, case.rejected} == {case.answer_a,
                                                   case.answer_b}


def test_a_correct_judgement_carries_no_reasons_and_a_miss_carries_them():
    case = jc.BY_ID["pj-ground-1"]

    hit = jc.judge(case, "A")
    assert hit["correct"] is True
    assert hit["reasons"] == []
    assert hit["failure_tags"] == []

    miss = jc.judge(case, "b")
    assert miss["correct"] is False
    assert miss["reasons"] == case.preference_reasons
    assert miss["failure_tags"] == case.failure_tags


def test_scoring_is_reported_by_dimension_not_as_one_number():
    """A judge that is perfect on concision and blind to grounding is a judge
    that will approve exactly the answers that matter most, and a single
    accuracy figure hides that completely."""
    judgements = [jc.judge(c, jc.B if c.dimension == jc.GROUNDING
                           else c.preferred_answer) for c in jc.CASES]

    scored = jc.score(judgements)

    assert scored["total"] == len(jc.CASES)
    assert scored["correct"] == len(jc.CASES) - 1
    assert scored["blind_spots"] == [jc.GROUNDING]
    assert scored["by_dimension"][jc.GROUNDING]["correct"] == 0
    assert scored["by_dimension"][jc.CONCISION]["correct"] == 1


def test_an_empty_run_scores_zero_rather_than_dividing_by_nothing():
    scored = jc.score([])

    assert scored["total"] == 0
    assert scored["accuracy"] == 0.0
    assert scored["blind_spots"] == []


def test_a_perfect_run_reports_no_blind_spots():
    judgements = [jc.judge(c, c.preferred_answer) for c in jc.CASES]

    scored = jc.score(judgements)

    assert scored["accuracy"] == 1.0
    assert scored["blind_spots"] == []


def test_the_honesty_pair_rejects_the_plausible_lag_story():
    """The one pair that is the whole of §84 in miniature: the rejected answer
    is the standard, sensible, expected explanation, and it is contradicted by
    the timing check having already run and cleared."""
    case = jc.BY_ID["pj-honest-1"]

    assert case.dimension == jc.HONESTY
    assert "lag" in case.rejected.lower()
    assert "none explains" in case.preferred or "fifteen" in case.preferred
    assert "GROUNDING" in case.failure_tags


def test_the_materiality_pair_rejects_ranking_by_percentage():
    case = jc.BY_ID["pj-material-1"]

    assert case.dimension == jc.MATERIALITY
    assert "48%" in case.rejected
    # The preferred answer gives both the percentage and the amount, so the
    # reader can see why the ranking differs from the percentages.
    assert "48%" in case.preferred


def test_cases_serialise_with_everything_a_reviewer_needs():
    payload = jc.BY_ID["pj-breadth-1"].to_dict()

    assert set(payload) == {
        "case_id", "dimension", "question", "validated_evidence", "answer_a",
        "answer_b", "preferred_answer", "preference_reasons", "failure_tags"}
    assert payload["dimension"] == jc.BREADTH


def test_nothing_in_this_module_trains_anything():
    """§80's last line and §1's. These are evaluation cases for prompts and
    critics; no provider fine-tuning occurs and this module cannot cause
    any."""
    source = jc.__doc__ or ""
    assert "No provider fine-tuning occurs" in source
    assert not hasattr(jc, "train")
    assert not hasattr(jc, "fine_tune")
