"""The action library, held to the thing that makes it a control.

"Monitor closely" is the failure mode this library exists to prevent. An
alert that leaves the system without an owner, a due date and a specific
piece of evidence that closes it produces a file that looks identical a
month later. So these tests assert the four parts are always present, that
the owner is a real rung on the escalation ladder rather than a job title
somebody invented, and — the one that carries real judgement — that asked
for a single action the library picks by reversibility and cost rather than
by the score of the node it came from.
"""

from __future__ import annotations

from backend.early_warning import actions as act
from backend.early_warning import aggregation as agg
from backend.early_warning import classifiers_v2 as clf
from backend.early_warning import escalation as esc

ALL_NODES = set(agg.TA_SUBCATEGORIES) | set(clf.SUBCATEGORIES)
LADDER_LEVELS = {rung["level"] for rung in esc.LADDER}
SPECIALIST_CODES = {route["code"] for route in esc.SPECIALIST_ROUTES}


def test_every_scoring_node_has_an_action():
    """All 22 sub-categories. A driver with no recommendation is a driver the
    product can describe and not respond to."""
    assert set(act.ACTION_LIBRARY) == ALL_NODES


def test_every_action_names_an_owner_that_exists():
    for code, action in act.ACTION_LIBRARY.items():
        assert action.owner_role in LADDER_LEVELS | SPECIALIST_CODES, code
        # And it resolves to a real title rather than echoing the code back.
        assert action.owner_title != action.owner_role, code


def test_every_action_has_a_timeframe_and_a_closing_evidence_test():
    for code, action in act.ACTION_LIBRARY.items():
        assert action.timeframe_days >= 0, code
        assert action.evidence_to_close.strip(), code
        assert len(action.evidence_to_close) > 15, code


def test_no_action_is_advice_rather_than_an_action():
    """The specific words that mean nothing will happen."""
    banned = ("monitor closely", "keep an eye", "watch carefully",
              "as appropriate", "if necessary", "consider whether")
    for code, action in act.ACTION_LIBRARY.items():
        lowered = action.action.lower()
        for phrase in banned:
            assert phrase not in lowered, f"{code}: {action.action}"


def test_ranks_are_on_the_published_scale():
    for code, action in act.ACTION_LIBRARY.items():
        assert 1 <= action.reversibility_rank <= 5, code
        assert 1 <= action.cost_rank <= 5, code


def test_the_single_action_is_chosen_by_reversibility_not_by_score():
    """The framework's own worked case.

    Earnings quality (L2.4) scores highest for this obligor and its action is
    an independent business review — slow, expensive, and it forecloses
    nothing by waiting. The covenant action (L2.T2) costs nothing, is quick,
    and is the only one that preserves the bank's contractual position. A
    library that picked by score would recommend the review.
    """
    drivers = ["L2.4", "L2.T2", "L1.2"]  # worst-scoring first
    chosen = act.single_highest_value(act.for_drivers(drivers))
    assert chosen is not None
    assert chosen.sub_category == "L2.T2"


def test_a_cheap_reversible_action_beats_an_expensive_irreversible_one():
    cheap = act.Action("X", "cheap", "L1", 5, "evidence", 1, 1)
    dear = act.Action("Y", "dear", "L3", 60, "evidence", 4, 5)
    assert act.single_highest_value([dear, cheap]) is cheap


def test_for_drivers_keeps_order_and_drops_duplicates():
    found = act.for_drivers(["L2.T2", "L1.3", "L2.T2", "not_a_node"])
    assert [a.sub_category for a in found] == ["L2.T2", "L1.3"]


def test_no_actions_means_no_recommendation_rather_than_a_default():
    assert act.single_highest_value([]) is None
    assert act.for_subcategory("not_a_node") is None


def test_immediate_reads_as_immediate():
    assert act.for_subcategory("L1.2").timeframe == "immediate"
    assert act.for_subcategory("L2.T2").timeframe == "15 days"
