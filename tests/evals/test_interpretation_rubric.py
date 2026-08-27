"""
Whether the reading is any good, decided the same way twice.

"Unimpressive, generic, indirect or incomplete" is a fair complaint and a
useless test result. These run the rubric — every criterion decided from the
text and the result together, with no model in the loop — over a spread of real
answers, and assert both that nothing unsafe reaches a reader and that the
reading says the specific things the result made available to say.

An LLM reviewer is deliberately absent. A grader that disagrees with itself
cannot say whether a change improved anything, and a model marking another
model's homework is a closed loop with no ground in it.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available

QUESTIONS = [
    "What is total EAD by sector in the latest quarter?",
    "Show me the five largest Real Estate customers by EAD.",
    "Which customers had a rating downgrade and an increase in ECL over the "
    "latest year?",
    "For each rating grade, show average ECL coverage and average DSCR.",
    "For each sector, calculate Stage 2 EAD as a percentage of total sector "
    "EAD, compare it with four quarters ago, and rank sectors by the largest "
    "increase.",
    "Does the relationship between grade, ECL coverage and DSCR appear "
    "consistent across grades?",
]


@pytest.fixture(scope="module", autouse=True)
def _require_the_lake():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if not database_available():
        pytest.skip("The rubric runs whole answers, which need a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


@pytest.fixture(scope="module")
def scored():
    from backend.orchestration import rubric
    from backend.orchestration.executor import answer_investigation

    out = {}
    for question in QUESTIONS:
        investigation, answered = answer_investigation(question, persist=False)
        if investigation.status != "succeeded":
            out[question] = None
            continue
        values = (investigation.steps[0].result or {}).get("values") or {}
        out[question] = (
            investigation,
            rubric.assess(investigation.narrative, answered.runtime,
                          answered.build, question=question,
                          suggestions=investigation.plan.follow_ups,
                          association=answered.association, values=values))
    return out


def test_every_answer_ran(scored):
    unanswered = [q for q, v in scored.items() if v is None]
    assert not unanswered, f"these did not compute: {unanswered}"


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda q: q[:34])
def test_nothing_unsafe_reaches_a_reader(scored, question):
    """The four criteria that mean the answer should not have been shown.

    No figure the result does not carry. No name it does not contain. No binary
    debris. No asserted cause.
    """
    found = scored[question]
    assert found is not None
    _, assessment = found
    assert assessment.safe, [s.to_dict() for s in assessment.failures]


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda q: q[:34])
def test_the_reading_says_what_the_result_made_available(scored, question):
    """The six quality criteria.

    Every one of them is a specific thing an analyst would say and the result
    supports: the first sentence answers, it is short enough to read, it names
    the largest contributor, it names the rows that do not fit, it states what
    limits the conclusion, and it leaves somewhere to go next.
    """
    found = scored[question]
    assert found is not None
    _, assessment = found
    assert assessment.quality == 1.0, [s.to_dict() for s in assessment.failures]


def test_a_reading_that_invents_a_figure_is_caught():
    """The rubric has to fail something, or it is measuring nothing."""
    from backend.orchestration import rubric

    class _Narrative:
        direct_answer = "Total exposure is 125,259 USD mn across 15 sectors."
        interpretation = "Contracting rose to 91,400 USD mn because of the "\
                         "construction cycle."
        findings: list = []
        caveats: list = []

    class _Runtime:
        rows = [{"sector": "Contracting", "ead": 18475.0}]
        row_count = 1
        columns = [{"name": "sector"}, {"name": "ead"}]
        summary: dict = {}
        truncated = 0
        warnings: list = []

    assessment = rubric.assess(_Narrative(), _Runtime(), None,
                               question="What is total EAD by sector?")
    failed = {s.criterion for s in assessment.failures}
    assert not assessment.safe
    assert rubric.GROUNDED_FIGURES in failed, "91,400 is not in the result"
    assert rubric.NON_CAUSAL in failed, "'because of' asserts a cause"
