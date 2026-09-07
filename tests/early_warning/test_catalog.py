"""The 123-row signal inventory (Tab 1) and its cross-reference against the
transcribed classifier/trigger definitions (Tab 2/3) — Conflict D.

This is not a claim that all 123 signals are independently scored. It is a
mechanical, explainable cross-reference: Tab 1's own "scored in" column sets
the status, and a normalised-name match (falling back to token overlap)
links each row to its actual formula where one exists. What is left
unresolved is recorded, not hidden.
"""

from __future__ import annotations

from backend.early_warning.catalog import (
    ACCELERATOR_DIMENSIONS,
    SIGNAL_INVENTORY,
    resolve_all,
    status_counts,
    unresolved_signals,
)


def test_123_signals_and_6_accelerator_dimensions():
    assert len(SIGNAL_INVENTORY) == 123
    assert len(ACCELERATOR_DIMENSIONS) == 6
    assert {d["code"] for d in ACCELERATOR_DIMENSIONS} == {f"A{i}" for i in range(1, 7)}


def test_every_row_has_a_declared_workbook_status():
    for r in resolve_all():
        assert r.scoring_status != "UNKNOWN", r.row.name


def test_status_counts_sum_to_123():
    assert sum(status_counts().values()) == 123


def test_most_signals_resolve_to_an_actual_definition():
    """Not all 123 resolve to a standalone Tab 2/3 formula — some are raw
    identity fields (sanctioned limit), some fold into another row's bands
    (restructuring into the bankruptcy trigger's bands). The residual is
    bounded and documented, not silently assumed to be 100% or a specific
    invented number like "105"."""
    resolved = resolve_all()
    linked = [r for r in resolved if r.linked_classifier_key or r.linked_trigger_key
              or r.scoring_status == "NETWORK_PROPAGATED"]
    assert len(linked) >= 90, (
        f"only {len(linked)}/123 signals resolved to a definition; "
        f"unresolved: {[r.row.key for r in unresolved_signals()]}"
    )


def test_known_groupings_resolve():
    resolved = {r.row.key: r for r in resolve_all()}
    assert resolved["single_source_dependency"].linked_classifier_key == \
        "single_source_dependency_and_substitutability"
    assert resolved["supplier_substitutability"].linked_classifier_key == \
        "single_source_dependency_and_substitutability"


def test_network_propagated_signals_link_to_their_trigger_definitions():
    resolved = {r.row.key: r for r in resolve_all()}
    assert resolved["tier_2_supplier_distress"].linked_trigger_key == "tier_2_supplier_distress"
    assert resolved["customer_of_customer_distress"].linked_trigger_key == "customer_of_customer_distress"
    # the portfolio-contagion row has no per-borrower trigger of its own
    assert resolved["shared_counterparty_exposure_in_the_banks_portfolio"].linked_trigger_key is None
