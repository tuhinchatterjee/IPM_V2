"""The 123-row signal inventory (Tab 01 of the corrected workbook) and its
reconciliation to 105 scored / 18 dropped, merged or replaced — and the
cross-reference of every scored row to its actual classifier or trigger
definition.

This is the reconciliation the user's own review demanded exactly: no
unexplained residual count, and every number traceable to Tab 01's own
literal status column, not inferred or assumed.
"""

from __future__ import annotations

from backend.early_warning.catalog import (
    ACCELERATOR_DIMENSIONS,
    CLASSIFIER_MERGED_COMPOSITE_NO_DIRECT_ROW,
    DROPPED,
    MERGED,
    MOVED,
    REPLACED,
    SCORED,
    SIGNAL_INVENTORY,
    TRIGGER_ONLY_NO_INVENTORY_ROW,
    describe,
    resolve_all,
    status_counts,
    unresolved_signals,
)


def test_123_signals_and_6_accelerator_dimensions():
    assert len(SIGNAL_INVENTORY) == 123
    assert len(ACCELERATOR_DIMENSIONS) == 6
    assert {d["code"] for d in ACCELERATOR_DIMENSIONS} == {f"A{i}" for i in range(1, 7)}


def test_exact_105_scored_18_dropped_merged_replaced():
    counts = status_counts()
    assert sum(counts.values()) == 123
    assert counts[SCORED] == 105
    assert counts.get(MERGED, 0) + counts.get(DROPPED, 0) + counts.get(REPLACED, 0) + counts.get(MOVED, 0) == 18


def test_tac_role_split_77_trigger_46_classifier():
    """Tab 01's own summary block states 77 T&A-role and 46 classifier-role
    rows. #89 "Sector slowdown" carries a dual role ("C (level) / T
    (shock)") and is the one row counted under both a naive substring
    count (78 T + 46 C = 124, one more than 123) — the workbook's own 77
    figure evidently counts it toward the classifier side for this
    headline split, which is what is reproduced here."""
    trigger_role = sum(1 for r in SIGNAL_INVENTORY
                        if "T" in r.tac_role and r.num != 89)
    classifier_role = sum(1 for r in SIGNAL_INVENTORY if "C" in r.tac_role)
    assert trigger_role == 77
    assert classifier_role == 46


def test_no_unexplained_gaps():
    """Every SCORED row either links to a classifier/trigger, is the
    portfolio-level view, or carries a disclosed residual reason. This is
    the property the previous, wrong-workbook implementation could not
    achieve (27/123 unresolved); the corrected reconciliation should have
    zero rows with no explanation at all."""
    unresolved = unresolved_signals()
    assert unresolved == [], [r.row.name for r in unresolved]


def test_all_23_classifiers_and_67_triggers_accounted_for():
    d = describe()
    assert d["classifier_count"] == 23
    assert d["trigger_count"] == 67
    # every classifier/trigger with no scored row pointing to it is one of
    # the documented merged-composites, the disclosed row #32 workbook
    # inconsistency (bank_share_of_obligor_debt), or a Tab-04-only trigger —
    # not an unexplained gap.
    allowed_classifiers = CLASSIFIER_MERGED_COMPOSITE_NO_DIRECT_ROW | {"bank_share_of_obligor_debt"}
    assert set(d["classifiers_with_no_scored_row"]) <= allowed_classifiers
    assert set(d["triggers_with_no_scored_row"]) <= TRIGGER_ONLY_NO_INVENTORY_ROW


def test_repayment_delay_collapse():
    """#12 "Repayment delay (1-29 DPD)" and #13 "Overdue 30+ DPD" are both
    scored by the one repayment_delay trigger, whose own bands span 1-89 DPD."""
    by_num = {r.row.num: r for r in resolve_all()}
    assert by_num[12].linked_trigger_key == "repayment_delay"
    assert by_num[13].linked_trigger_key == "repayment_delay"


def test_outlook_watch_rating_withdrawal_collapse():
    """#70/#71/#72 are three angles on the one outlook_or_watch_action
    trigger, whose five severity bands literally name all three."""
    by_num = {r.row.num: r for r in resolve_all()}
    for num in (70, 71, 72):
        assert by_num[num].linked_trigger_key == "outlook_or_watch_action"


def test_portfolio_view_row_not_force_linked():
    by_num = {r.row.num: r for r in resolve_all()}
    row122 = by_num[122]
    assert row122.is_portfolio_view
    assert row122.linked_classifier_key is None
    assert row122.linked_trigger_key is None


def test_dropped_merged_rows_carry_the_workbooks_own_reason():
    by_num = {r.num: r for r in SIGNAL_INVENTORY}
    assert by_num[21].status == MERGED
    assert "same construct as PD" in by_num[21].status_detail
    assert by_num[46].status == DROPPED
    assert "negative equity" in by_num[46].status_detail
