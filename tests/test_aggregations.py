"""
Core portfolio aggregations — IFRS 9 staging, KPIs, rating migration, concentration
and EAD build-up. Invariants and independent cross-checks against the raw DataFrame.
"""

import pytest

from backend import data_loader as dl

TOL = 1e-6


def approx(v):
    return pytest.approx(v, rel=1e-9, abs=TOL)


def _cur(q):
    return dl.filtered_quarter(q)


# --------------------------------------------------------------------- KPIs

def test_total_ead_matches_raw(q):
    k = dl.compute_kpis(q)
    assert k["total_ead"] == approx(_cur(q)[dl.EAD_COL].sum())


def test_npl_ratio_matches_raw(q):
    k = dl.compute_kpis(q)
    cur = _cur(q)
    expected = cur.loc[cur["NPL"] == "Yes", dl.EAD_COL].sum() / cur[dl.EAD_COL].sum() * 100
    assert k["npl_ratio"] == approx(expected)


def test_stage_ead_sums_to_total(q):
    k = dl.compute_kpis(q)
    total = _cur(q)[dl.EAD_COL].sum()
    assert sum(k["stage_ead"].values()) == approx(total)


# ------------------------------------------------------------------ IFRS 9

def test_ifrs9_stage_breakdown_sums_to_100(q):
    stages = dl.compute_stage_breakdown(q)
    assert sum(s["pct"] for s in stages.values()) == approx(100.0)


def test_ecl_bridge_opening_plus_moves_reconciles_to_closing(q):
    bridge = dl.compute_ecl_bridge(q)
    moves = sum(item["value"] for item in bridge["bridge"])  # opening + all deltas
    assert moves == approx(bridge["closing"])


def test_ecl_coverage_is_ecl_over_ead(q):
    bridge = dl.compute_ecl_bridge(q)
    cur = _cur(q)
    expected = cur["Total ECL (USD mn)"].sum() / cur[dl.EAD_COL].sum() * 100
    assert bridge["ecl_coverage"] == approx(expected)


# --------------------------------------------------------------- migration

def test_migration_counts_reconcile(q):
    m = dl.compute_rating_migration(q)
    matrix_total = m["matrix"].to_numpy().sum()
    assert m["upgrades"] + m["downgrades"] + m["stable"] == matrix_total
    assert m["net_migration"] == m["upgrades"] - m["downgrades"]


def test_migration_matrix_is_square_over_buckets(q):
    m = dl.compute_rating_migration(q)
    n = len(m["buckets"])
    assert m["matrix"].shape == (n, n)


# ----------------------------------------------------------- concentration

def test_hhi_between_zero_and_one(q):
    conc = dl.compute_concentration_heatmap(q)
    assert 0.0 < conc["hhi"] <= 1.0


def test_top10_pct_reasonable(q):
    conc = dl.compute_concentration_heatmap(q)
    assert 0.0 < conc["top10_pct"] <= 100.0


def test_sector_caps_utilisation_consistent(q):
    conc = dl.compute_concentration_heatmap(q)
    for row in conc["sector_caps"]:
        if row["cap_pct"]:
            assert row["utilisation"] == approx(row["pct_of_book"] / row["cap_pct"] * 100)


# ------------------------------------------------------------------- EAD

def test_ead_buildup_components_present(q):
    data = dl.compute_ead_buildup(q)
    assert data["ccf_adjusted"] == approx(_cur(q)[dl.EAD_COL].sum())
    assert {b["component"] for b in data["buildup"]} >= {"Funded loans", "Undrawn commitments"}


# ------------------------------------------------------------- borrower list

def test_borrower_list_totals(q):
    bl = dl.compute_borrower_list(q, top_n=10)
    # customer-level roll-up: unique customers, EAD is positive and sorted desc.
    eads = [r["ead"] for r in bl["rows"]]
    assert eads == sorted(eads, reverse=True)
    assert bl["total"] == _cur(q)["Customer ID"].nunique()


def test_borrower_list_search_filters(q):
    bl = dl.compute_borrower_list(q, search="marina", top_n=60)
    assert all("marina" in r["borrower"].lower() or "marina" in r["customer_id"].lower()
               for r in bl["rows"])


# -------------------------------------------------------- sector outlook / macro

def test_sector_outlook_weighted_between_scenarios(q):
    """The probability-weighted projected PD lies within the min/max of the three
    scenario projections for each sector."""
    base = dl.compute_sector_outlook(q, "Baseline")
    for r in base["rows"]:
        drifts = [r["pd"] * (1 + dl.SCENARIO_PD_DRIFT[s] * r["beta"]) for s in dl.MACRO_SCENARIOS]
        assert min(drifts) - TOL <= r["weighted_pd_proj"] <= max(drifts) + TOL
