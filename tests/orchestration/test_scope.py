"""
What an answer covers, and what each turn did to it.

Two failures, and they are the same shape. A thread narrows to five customers,
then somebody asks a portfolio question — answered over five names, correct
arithmetic, wrong by three orders of magnitude, nothing on screen saying so.
Or a follow-up meaning those ten customers is answered over the whole book and
comes back looking like a bigger version of the right answer.

Neither is visible unless the scope is a thing rather than an implication.
"""

from __future__ import annotations

import pytest

from backend.orchestration import scope as sc


def frame(**kwargs) -> sc.ScopeFrame:
    return sc.ScopeFrame(**kwargs)


# ----------------------------------------------------------------- the line


def test_a_carried_population_says_so_in_words():
    line = frame(entity_key="customer_id", entity_ids=["a", "b", "c"],
                 period="Q2 2026", metrics=["exposure at default"]).line()

    assert "3 customers carried from the previous answer" in line
    assert "Q2 2026" in line


def test_an_unpinned_scope_says_the_whole_portfolio():
    assert "the whole portfolio" in frame(period="Q2 2026").line()


def test_a_filtered_scope_names_the_filter():
    line = frame(filters=[{"field": "sector", "value": "Real Estate"}],
                 period="Q2 2026").line()

    assert "Real Estate" in line
    assert "whole portfolio" not in line


# ---------------------------------------------------------------- the deltas


def test_adding_a_filter_is_a_narrowing_not_a_change_of_measure():
    """Narrowing almost always adds a concept too.

    "Which of these are Stage 2?" adds a filter AND the stage concept, and
    calling that a change of measure describes the least important half of
    what happened.
    """
    before = frame(entity_ids=["a", "b"], metrics=["exposure at default"])
    after = frame(entity_ids=["a", "b"],
                  metrics=["exposure at default", "IFRS 9 stage"],
                  filters=[{"field": "ifrs9_stage", "value": "2"}])

    assert sc.classify(before, after).kind == sc.NARROW


def test_replacing_the_measure_is_a_change_of_measure():
    before = frame(entity_ids=["a"], metrics=["exposure at default"])
    after = frame(entity_ids=["a"], metrics=["expected credit loss"])

    delta = sc.classify(before, after)

    assert delta.kind == sc.CHANGE_MEASURE
    assert any("replaced by" in c for c in delta.changes)


def test_dropping_the_population_is_a_widening():
    before = frame(entity_key="customer_id", entity_ids=["a", "b", "c"],
                   metrics=["exposure at default"])
    after = frame(metrics=["exposure at default"], dimension="sector")

    delta = sc.classify(before, after)

    assert delta.kind == sc.WIDEN
    assert delta.widening_note
    assert "materially wider" in delta.widening_note


def test_a_reset_is_named_by_the_action_and_warns():
    before = frame(entity_key="customer_id", entity_ids=["a", "b"],
                   filters=[{"field": "sector", "value": "Real Estate"}])
    after = frame(dimension="sector")

    delta = sc.classify(before, after, action="RESET_SCOPE")

    assert delta.kind == sc.RESET
    assert delta.widening_note
    assert not delta.reuses_population


def test_a_presentation_change_reuses_everything():
    before = frame(entity_ids=["a"], metrics=["exposure at default"])
    after = frame(entity_ids=["a"], metrics=["exposure at default"],
                  presentation="chart")

    delta = sc.classify(before, after, action="MODIFY_PRESENTATION")

    assert delta.kind == sc.PRESENTATION_ONLY
    assert delta.reuses_population


def test_the_first_turn_of_a_thread_is_a_new_topic():
    assert sc.classify(frame(), frame(metrics=["ead"])).kind == sc.NEW_TOPIC


def test_a_single_dataset_is_not_pluralised():
    """A widening note is read at the moment somebody is deciding whether to
    trust a number, and "1 datasets" is the wrong moment to look careless."""
    before = frame(entity_ids=["a"], datasets=["portfolio_facility"])
    after = frame(datasets=["portfolio_facility"])

    note = sc.classify(before, after).widening_note

    assert "1 datasets" not in note
    assert "1 dataset" in note


def test_material_widening_needs_a_real_jump():
    small = frame(entity_ids=[str(i) for i in range(10)])
    slightly_bigger = frame(entity_ids=[str(i) for i in range(12)])
    much_bigger = frame(entity_ids=[str(i) for i in range(400)])

    assert not sc.is_material(small, slightly_bigger)
    assert sc.is_material(small, much_bigger)
    assert sc.is_material(small, frame())


# ----------------------------------------------------------- through the path


@pytest.fixture(scope="module")
def require_data():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


def _thread(questions: list[str]):
    from backend.orchestration import conversation as cv
    from backend.orchestration import memory as wm
    from backend.orchestration.executor import answer_investigation
    from backend.orchestration.orchestrator import remember as advance

    context: dict = {}
    out = []
    for question in questions:
        state, memory = cv.load(context), wm.load(context)
        investigation, answered = answer_investigation(
            question, persist=False, state=state, memory=memory)
        context = cv.save(context, advance(
            state, answered,
            headline=str(investigation.narrative.direct_answer or ""),
            run_id=None))
        context = wm.save(context, wm.observe(wm.load(context), answered,
                                              investigation))
        out.append((investigation, answered))
    return out


def test_a_reset_does_not_answer_a_portfolio_question_over_five_names(require_data):
    """The failure this whole module exists for."""
    turns = _thread([
        "Show the five largest Real Estate customers by EAD.",
        "Forget those and use the whole portfolio: what is total EAD by sector?",
    ])
    investigation, answered = turns[-1]

    assert investigation.status == "succeeded"
    assert answered.continuation.action == "RESET_SCOPE"
    assert answered.continuation.entity_ids == [], (
        "a reset must discard the population it exists to discard")
    assert answered.scope.kind == sc.RESET

    rows = (investigation.steps[0].result or {}).get("rows") or []
    assert len(rows) > 5, "a portfolio breakdown covers more than five names"


def test_every_answer_states_what_it_covers(require_data):
    investigation, answered = _thread([
        "What is total EAD by sector in the latest quarter?"])[0]

    assert investigation.narrative.scope
    assert "Q2 2026" in investigation.narrative.scope
    recorded = investigation.conversation.get("scope") or {}
    assert recorded.get("after", {}).get("line")


def test_a_narrowing_says_what_it_narrowed(require_data):
    turns = _thread([
        "Show the five largest Real Estate customers by EAD.",
        "Which of these are Stage 2 or Stage 3?",
    ])
    _, answered = turns[-1]

    assert answered.scope.kind in (sc.NARROW, sc.CHANGE_MEASURE)
    assert answered.scope.changes
    assert answered.scope.before.size == 5
