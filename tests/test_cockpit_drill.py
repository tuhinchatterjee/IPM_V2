"""
Cockpit Health Index drill-down: the arithmetic and the invariants that keep the
three screens telling one consistent story.

DB-free — the bundled dataset is loaded by data_loader at import, same as the
other suites here.
"""

import pytest

import backend.cockpit_data as cd
import backend.data_loader as dl

# ------------------------------------------------------------------ AI score

def test_ai_display_score_inverts_the_risk_scale():
    """The ledger stores risk 0-1 (higher = worse); every screen shows 0-100
    (higher = better). Getting this backwards would rank the book upside down."""
    assert cd.ai_display_score(0.0) == 100.0
    assert cd.ai_display_score(1.0) == 0.0
    assert cd.ai_display_score(0.45) == pytest.approx(55.0)


def test_ai_display_score_is_clipped():
    assert cd.ai_display_score(-0.5) == 100.0
    assert cd.ai_display_score(1.5) == 0.0


def test_worse_risk_gives_lower_display_score():
    assert cd.ai_display_score(0.9) < cd.ai_display_score(0.3)


# ------------------------------------------------------------- health index

def test_health_index_matches_the_published_formula():
    assert dl.health_index(0.0, 0.0) == 100.0
    assert dl.health_index(4.0, 10.0) == 100.0 - 20.0 - 15.0
    # clipped, never negative
    assert dl.health_index(50.0, 50.0) == 0.0


def test_health_screen_score_agrees_with_its_own_inputs():
    """The headline score must be reconstructible from the two ratios shown
    beneath it — that is the whole point of publishing the formula."""
    data = cd.compute_health_screen()
    expected = dl.health_index(data["asset_quality"]["npl_ratio"], data["stage2_pct"])
    assert abs(data["score"] - expected) < 1e-9


def test_health_screen_band_contains_the_score():
    data = cd.compute_health_screen()
    assert data["band"]["lo"] <= data["score"] <= data["band"]["hi"]


def test_band_for_covers_the_whole_range():
    for score in (0, 25, 49.9, 50, 74.9, 75, 100):
        assert cd.band_for(score)["label"] in {"AT RISK", "WATCH", "HEALTHY"}


def test_index_history_is_bounded_and_ordered():
    """Chronological order comes from QUARTER_SHEETS, not from sorting the labels
    — 'Q2 2024' sorts after 'Q1 2025' as a string."""
    history = cd.compute_index_history(dl.DEFAULT_QUARTER)
    assert 0 < len(history) <= cd.INDEX_HISTORY_QUARTERS
    quarters = [h["quarter"] for h in history]
    expected = dl.QUARTER_SHEETS[-len(quarters):]
    assert quarters == expected
    assert all(0 <= h["score"] <= 100 for h in history)


# ----------------------------------------------------------- risk appetite

def test_appetite_rows_classify_against_the_stated_direction():
    rows = {r["key"]: r for r in cd.compute_appetite_rows(dl.DEFAULT_QUARTER)}
    assert set(rows) == {s["key"] for s in cd.APPETITE_LIMITS}
    for r in rows.values():
        if r["direction"] == "max":
            assert (r["status"] == "BREACH") == (r["value"] > r["appetite"])
        else:
            assert (r["status"] == "BREACH") == (r["value"] < r["appetite"])


def test_capital_adequacy_reuses_the_brf_capital_proxy():
    """One proxy for capital across the tool, so BRF and the cockpit cannot
    quote different capital ratios for the same book."""
    rows = {r["key"]: r for r in cd.compute_appetite_rows(dl.DEFAULT_QUARTER)}
    assert rows["capital_adequacy"]["value"] == dl.CAPITAL_RATIO * 100


# ------------------------------------------------------------ sector matrix

def test_sector_matrix_covers_every_sector_and_ranks_worst_first():
    data = cd.compute_sector_matrix(dl.DEFAULT_QUARTER)
    cur = dl.filtered_quarter(dl.DEFAULT_QUARTER)
    assert {r["sector"] for r in data["rows"]} == set(cur["Sector"].unique())
    scores = [r["ai_score"] for r in data["rows"]]
    assert scores == sorted(scores), "worst AI score must lead the table"


def test_sector_matrix_exposure_reconciles_to_the_book():
    data = cd.compute_sector_matrix(dl.DEFAULT_QUARTER)
    total = sum(r["ead"] for r in data["rows"])
    assert abs(total - data["total_ead"]) < 1e-6


def test_sector_matrix_ratios_are_percentages():
    for r in cd.compute_sector_matrix(dl.DEFAULT_QUARTER)["rows"]:
        for key in ("npl", "stage2", "dpd30", "dpd90", "ecl_ratio"):
            assert 0.0 <= r[key] <= 100.0, f"{r['sector']}.{key} out of range"
        assert 0.0 <= r["ai_score"] <= 100.0


def test_90_plus_never_exceeds_30_plus():
    """A 90+ bucket larger than the 30+ bucket it is contained in would mean the
    DPD filters are the wrong way round."""
    for r in cd.compute_sector_matrix(dl.DEFAULT_QUARTER)["rows"]:
        assert r["dpd90"] <= r["dpd30"] + 1e-9, r["sector"]


def test_deteriorating_is_a_subset_ranked_worst_first():
    data = cd.compute_sector_matrix(dl.DEFAULT_QUARTER)
    names = {r["sector"] for r in data["rows"]}
    det = data["deteriorating"]
    assert len(det) <= 3
    assert {r["sector"] for r in det} <= names
    assert [r["ai_score"] for r in det] == sorted(r["ai_score"] for r in det)


# --------------------------------------------------------------- benchmark

def test_benchmark_reports_every_metric_with_a_quartile():
    bench = cd.compute_benchmark(dl.DEFAULT_QUARTER)
    assert len(bench["metrics"]) == len(cd.PEER_BENCHMARK["metrics"])
    for m in bench["metrics"]:
        assert m["quartile"]
        assert 0.0 <= m["position"] <= 1.0
        expected_ahead = (m["value"] < m["median"]) if m["better"] == "low" else (m["value"] > m["median"])
        assert m["ahead"] == expected_ahead


def test_quartile_direction_respects_better_low_vs_high():
    # For a "low is better" metric, beating the median must rank better.
    good, _ = cd._quartile(2.0, 4.0, "low")
    bad, _ = cd._quartile(8.0, 4.0, "low")
    assert good == "TOP 25%" and bad == "BOTTOM 25%"
    # And the sense flips for "high is better".
    good, _ = cd._quartile(8.0, 4.0, "high")
    bad, _ = cd._quartile(2.0, 4.0, "high")
    assert good == "TOP 25%" and bad == "BOTTOM 25%"


# ---------------------------------------------------------------- obligors

def test_obligor_screen_defaults_to_the_deteriorating_portfolios():
    """Screen 3 must answer the question screen 2 raised, not show an unrelated
    set of names."""
    matrix = cd.compute_sector_matrix(dl.DEFAULT_QUARTER)
    screen = cd.compute_obligor_screen(dl.DEFAULT_QUARTER)
    expected = [r["sector"] for r in matrix["deteriorating"]]
    assert [c["sector"] for c in screen["columns"]] == [s for s in expected
                                                        if any(c["sector"] == s for c in screen["columns"])]


def test_obligors_are_worst_first_and_carry_an_action():
    col = cd.compute_sector_obligors(dl.DEFAULT_QUARTER, "Contracting", top_n=5)
    assert col["obligors"], "Contracting should have flagged obligors"
    scores = [o["ai_score"] for o in col["obligors"]]
    assert scores == sorted(scores), "worst obligor must lead the column"
    for o in col["obligors"]:
        assert o["action"] in cd.ACTION_MENU
        assert o["trigger"] and o["borrower"]


def test_obligor_exposure_never_exceeds_its_sector():
    for col in cd.compute_obligor_screen(dl.DEFAULT_QUARTER)["columns"]:
        assert sum(o["ead"] for o in col["obligors"]) <= col["ead"] + 1e-6


def test_unknown_sector_returns_empty_rather_than_raising():
    col = cd.compute_sector_obligors(dl.DEFAULT_QUARTER, "Nonexistent Sector")
    assert col["obligors"] == [] and col["ead"] == 0.0


# ------------------------------------------------------------ every quarter

def test_all_three_screens_compute_for_every_quarter():
    """Includes the first quarter, which has no previous period — the QoQ deltas
    must come back None rather than blowing up."""
    for q in dl.QUARTER_SHEETS:
        health = cd.compute_health_screen(q)
        assert 0 <= health["score"] <= 100
        matrix = cd.compute_sector_matrix(q)
        assert matrix["rows"]
        assert cd.compute_obligor_screen(q) is not None


def test_first_quarter_has_no_prior_period_deltas():
    aq = cd.compute_health_screen(dl.QUARTER_SHEETS[0])["asset_quality"]
    assert aq["npl_delta"] is None
    assert aq["new_defaults"] is None
    assert aq["cure_rate"] is None
