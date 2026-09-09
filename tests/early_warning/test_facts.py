"""The fact pack: every figure an answer may state, and nothing it may not.

The rule these tests defend is that prose never reaches for a number. It is
handed a pack first and may only quote what the pack carries, so anything
the pack cannot compute has to come back as an absence rather than a
plausible value. Several of these tests exist only to prove that an absence
is what happens.

The derived measures get the most attention, because they are the ones that
turn a description into a claim: how much of a move each layer accounts for,
whether risk sits in a few names, whether an obligor is structurally weak or
acutely deteriorating, and whether a fall in the score was the anchor moving
or only the notches.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.early_warning import facts
from backend.early_warning import v2_service as svc


@pytest.fixture(scope="module", autouse=True)
def _require_domain():
    try:
        svc.latest_period()
    except Exception:  # noqa: BLE001
        pytest.skip("Early Warning V2 domain is not built")


@pytest.fixture(scope="module")
def portfolio_pack():
    return facts.portfolio()


@pytest.fixture(scope="module")
def borrower_pack():
    return facts.borrower(svc.top_high_risk(limit=1)[0]["customer_id"])


# ------------------------------------------------------------- population


def test_portfolio_figures_reconcile_to_the_service(portfolio_pack):
    """The pack is a reading of the domain, not a second source of truth."""
    summary = svc.portfolio_summary()
    assert portfolio_pack.figures["obligors"] == summary["borrower_count"]
    assert portfolio_pack.figures["portfolio_ews"] == pytest.approx(
        summary["portfolio_ews"], abs=0.01)


def test_severity_distribution_accounts_for_every_obligor(portfolio_pack):
    counted = sum(b["obligors"] for b in portfolio_pack.figures["severity_distribution"])
    assert counted == portfolio_pack.figures["obligors"]


def test_every_pack_names_where_its_figures_came_from(portfolio_pack, borrower_pack):
    assert portfolio_pack.provenance
    assert borrower_pack.provenance
    assert all(p.startswith("early_warning") for p in borrower_pack.provenance)


def test_every_pack_carries_what_limits_it(portfolio_pack):
    """A figure produced by an uncalibrated model has to say so wherever it
    is read, not only in a methodology page nobody opens."""
    assert portfolio_pack.caveats
    assert any("not calibrated" in c for c in portfolio_pack.caveats)


# ------------------------------------------------------------ contribution


def test_layer_contributions_sum_to_the_dimension_move():
    periods = svc.periods()
    found = facts.contribution_by_layer(periods[0], periods[-1])
    assert found is not None
    total = sum(l["points_contributed"] for l in found["layers"])
    assert total == pytest.approx(found["ta_change"], abs=0.02)


def test_contribution_is_ordered_by_how_much_each_layer_explains():
    periods = svc.periods()
    found = facts.contribution_by_layer(periods[0], periods[-1])
    sizes = [abs(l["points_contributed"]) for l in found["layers"]]
    assert sizes == sorted(sizes, reverse=True)
    assert found["leading_layer"] == found["layers"][0]["layer"]


def test_a_missing_period_returns_no_contribution_rather_than_a_guess():
    """The specific failure this guards: a confident decomposition of a move
    between a period that exists and one that does not."""
    assert facts.contribution_by_layer("1999-01", svc.latest_period()) is None
    assert facts.contribution_by_layer(svc.latest_period(), "2099-12") is None


def test_movement_says_so_when_it_cannot_decompose():
    pack = facts.movement("1999-01", svc.latest_period())
    assert "unavailable" in pack.figures
    assert not pack.rows


# ----------------------------------------------------------- concentration


def test_concentration_measures_the_share_the_worst_names_carry(portfolio_pack):
    found = portfolio_pack.figures["concentration"]
    if found["high_plus_count"] == 0:
        pytest.skip("nothing at high or above this period")
    assert 0 <= found["top_n_share_pct"] <= 100
    assert len(found["names"]) == found["top_n"]


def test_a_population_with_nothing_high_is_not_reported_as_concentrated():
    empty = pd.DataFrame({"ews_band": ["LOW", "MEDIUM"], "exposure": [1.0, 2.0],
                          "customer_id": ["a", "b"], "customer_name": ["A", "B"],
                          "ews_score": [10.0, 40.0]})
    found = facts.concentration(empty)
    assert found["high_plus_count"] == 0
    assert found["is_concentrated"] is False
    assert found["top_n_share_pct"] is None


# ------------------------------------------------------- live vs structural


def test_a_weak_obligor_with_nothing_moving_reads_as_structural():
    found = facts.live_versus_structural(10.0, "VERY_LOW", 85.0, "VERY_HIGH")
    assert found["reading"] == "structural"
    assert found["diverges"] is True


def test_a_sound_obligor_in_acute_distress_reads_as_live():
    found = facts.live_versus_structural(85.0, "VERY_HIGH", 10.0, "VERY_LOW")
    assert found["reading"] == "live"


def test_two_dimensions_in_the_same_place_do_not_diverge():
    found = facts.live_versus_structural(72.0, "HIGH", 70.0, "HIGH")
    assert found["reading"] == "both"
    assert found["diverges"] is False


# --------------------------------------------------- movement attribution


def test_a_notch_driven_fall_is_not_reported_as_an_improvement():
    """The framework's own worked case, and the answer's worst failure mode.

    The anchor is unchanged; the whole fall came from two notches. An answer
    that calls this an improvement has told the reader the obligor got
    better when nothing about its condition did.
    """
    history = pd.DataFrame([
        {"snapshot_month": "2026-05", "ews_score": 72.0, "anchor_score": 72.0,
         "net_notches": 0},
        {"snapshot_month": "2026-06", "ews_score": 56.0, "anchor_score": 72.0,
         "net_notches": -2},
    ])
    found = facts.movement_attribution(history, months=1)
    assert found["ews_change"] == -16.0
    assert found["anchor_change"] == 0.0
    assert found["notch_change_points"] == -16.0
    assert found["driven_by_notches"] is True
    assert found["condition_improved"] is False


def test_a_falling_anchor_is_a_genuine_improvement():
    history = pd.DataFrame([
        {"snapshot_month": "2026-05", "ews_score": 72.0, "anchor_score": 72.0,
         "net_notches": 0},
        {"snapshot_month": "2026-06", "ews_score": 52.0, "anchor_score": 52.0,
         "net_notches": 0},
    ])
    found = facts.movement_attribution(history, months=1)
    assert found["condition_improved"] is True
    assert found["driven_by_notches"] is False


def test_too_little_history_returns_nothing_rather_than_a_movement():
    one = pd.DataFrame([{"snapshot_month": "2026-06", "ews_score": 50.0,
                         "anchor_score": 50.0, "net_notches": 0}])
    assert facts.movement_attribution(one, months=1) is None
    assert facts.movement_attribution(None, months=1) is None


# ------------------------------------------------------------ level/group


def test_any_field_that_partitions_the_book_can_become_a_level():
    for field_name in ("segment", "internal_rating", "ifrs9_stage",
                       "dominant_layer", "utilisation_band"):
        pack = facts.level(field_name)
        assert pack.rows, field_name
        assert pack.figures["level_field"] == field_name


def test_a_grade_level_always_carries_the_divergence_warning():
    """Grade and early warning are not supposed to track each other, and an
    answer that does not say so invites the reader to treat the divergence as
    an error rather than the alert it is."""
    pack = facts.level("internal_rating")
    assert any("review cycle" in c for c in pack.caveats)
    assert "divergence" in pack.figures


def test_an_unknown_level_field_is_refused():
    with pytest.raises(KeyError):
        facts.level("favourite_colour")


def test_a_group_reports_its_share_of_the_book():
    segments = facts.level("segment").rows
    pack = facts.group("segment", segments[0]["segment"])
    assert 0 < pack.figures["share_of_book_exposure_pct"] <= 100
    assert pack.rows


def test_an_unknown_group_value_is_refused():
    with pytest.raises(KeyError):
        facts.group("segment", "Not A Segment")


# --------------------------------------------------------------- borrower


def test_a_borrower_pack_carries_the_anchor_and_the_notches(borrower_pack):
    """Both, always. The final score alone cannot be challenged."""
    assert "anchor_score" in borrower_pack.figures
    assert "net_notches" in borrower_pack.figures
    assert len(borrower_pack.figures["notches"]) == 5


def test_a_borrower_pack_names_its_drivers_with_reason_text(borrower_pack):
    drivers = borrower_pack.figures["drivers"]
    if not drivers:
        pytest.skip("nothing scored for this obligor")
    for driver in drivers:
        assert driver["code"]
        assert driver["name"]
        assert driver["reason"], driver["code"]
        assert driver["dimension"] in ("C", "T&A")


def test_layer_3_drivers_always_declare_the_data_is_synthetic():
    """No live external feed exists here, and an answer that quotes a Layer 3
    event without saying so is presenting demonstration data as intelligence."""
    for row in svc.top_high_risk(limit=25):
        pack = facts.borrower(row["customer_id"])
        if any(d["code"].startswith("L3") for d in pack.figures["drivers"]):
            assert any("synthetic" in c for c in pack.caveats)
            return
    pytest.skip("no Layer 3 driver in the top population")


# --------------------------------------------------------------- evidence


def test_signal_evidence_is_absent_rather_than_empty():
    cid = svc.top_high_risk(limit=1)[0]["customer_id"]
    assert facts.signal_evidence(cid, "not_a_real_signal") is None


def test_numbers_collects_every_figure_for_grounding(borrower_pack):
    """The grounding check needs every figure the pack carries, at any depth,
    or a generated sentence quoting a nested value would look invented."""
    found = borrower_pack.numbers()
    assert borrower_pack.figures["ews_score"] in found
    assert borrower_pack.figures["anchor_score"] in found
