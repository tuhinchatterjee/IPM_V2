"""
CBUAE / BRF regulatory computations — the highest-priority tests because these
feed regulatory returns. Each expected value is recomputed independently from the
raw DataFrame (not copied from the function under test) or asserted as an invariant.
"""

import numpy as np
import pytest

from backend import data_loader as dl

TOL = 1e-6


def pytest_approx(value):
    return pytest.approx(value, rel=1e-9, abs=TOL)


def _quarter_df(q):
    return dl.filtered_quarter(q)


# ------------------------------------------------------------- asset quality

def test_classification_buckets_sum_to_total(q):
    aq = dl.compute_brf_asset_quality(q)
    bucket_ead = sum(r["ead"] for r in aq["rows"])
    assert bucket_ead == pytest_approx(aq["total_ead"])


def test_classification_accounts_cover_quarter(q):
    aq = dl.compute_brf_asset_quality(q)
    assert sum(r["accounts"] for r in aq["rows"]) == len(_quarter_df(q))


def test_cbuae_class_mapping_matches_stage_and_dpd(q):
    cur = _quarter_df(q).copy()
    expected = np.where(
        cur["IFRS 9 Stage"] == 3,
        np.where(cur["DPD (days)"] > 365, "Loss",
                 np.where(cur["DPD (days)"] > 180, "Doubtful", "Substandard")),
        np.where(cur["IFRS 9 Stage"] == 2, "OLEM", "Normal"),
    )
    got = dl._cbuae_class_series(cur).to_numpy()
    assert (got == expected).all()


def test_classified_ead_is_substandard_doubtful_loss(q):
    aq = dl.compute_brf_asset_quality(q)
    classified = sum(r["ead"] for r in aq["rows"] if r["class"] in ("Substandard", "Doubtful", "Loss"))
    assert classified == pytest_approx(aq["classified_ead"])


def test_npl_ratio_cross_check(q):
    aq = dl.compute_brf_asset_quality(q)
    cur = _quarter_df(q)
    total = cur[dl.EAD_COL].sum()
    npl = cur.loc[cur["NPL"] == "Yes", dl.EAD_COL].sum()
    assert aq["npl_pct"] == pytest_approx(npl / total * 100)


def test_general_provision_floor_flag(q):
    aq = dl.compute_brf_asset_quality(q)
    assert aq["general_ok"] == (aq["general_provisions"] >= aq["min_general"])
    assert aq["min_general"] == pytest_approx(dl.GENERAL_PROVISION_MIN_PCT / 100 * aq["crwa"])


def test_provision_coverage_of_npl(q):
    aq = dl.compute_brf_asset_quality(q)
    cur = _quarter_df(q)
    npl_ead = cur.loc[cur["NPL"] == "Yes", dl.EAD_COL].sum()
    expected = aq["specific_provisions"] / npl_ead * 100 if npl_ead else 0.0
    assert aq["provision_coverage_npl"] == pytest_approx(expected)


# --------------------------------------------------------- economic activity

def test_economic_activity_ead_sums_to_total(q):
    ea = dl.compute_brf_economic_activity(q)
    assert sum(r["ead"] for r in ea["rows"]) == pytest_approx(ea["total_ead"])


def test_economic_activity_mapping_spot_checks(q):
    ea = dl.compute_brf_economic_activity(q)
    by_activity = {r["activity"] for r in ea["rows"]}
    # Energy and Real Estate map to their CBUAE categories.
    assert dl.CBUAE_ACTIVITY_MAP["Energy"] in by_activity
    assert dl.CBUAE_ACTIVITY_MAP["Real Estate"] in by_activity


def test_economic_activity_npl_not_negative(q):
    ea = dl.compute_brf_economic_activity(q)
    assert all(r["npl_ead"] >= 0 and 0 <= r["npl_pct"] <= 100 for r in ea["rows"])


# ------------------------------------------------------------ large exposures

def test_capital_base_is_ratio_of_crwa(q):
    le = dl.compute_brf_large_exposures(q)
    crwa = dl._crwa_proxy(_quarter_df(q))
    assert le["capital_base"] == pytest_approx(crwa * dl.CAPITAL_RATIO)


def test_reportable_exposures_above_threshold(q):
    le = dl.compute_brf_large_exposures(q)
    assert all(e["pct_capital"] >= dl.LARGE_EXPOSURE_REPORT_PCT for e in le["rows"])


def test_breach_flag_matches_limit(q):
    le = dl.compute_brf_large_exposures(q)
    for e in le["rows"]:
        assert e["breach"] == (e["pct_capital"] > dl.LARGE_EXPOSURE_LIMIT_PCT)


def test_group_exposure_aggregates_members(q):
    """A reported obligor group's exposure equals the sum of its member facilities."""
    le = dl.compute_brf_large_exposures(q)
    groups = [e for e in le["rows"] if e["type"] == "Group"]
    if not groups:
        return  # no groups reportable at this quarter — nothing to assert
    cur = _quarter_df(q)
    top_group = groups[0]["name"]
    member_ead = cur.loc[cur["Obligor Group"] == top_group, dl.EAD_COL].sum()
    assert groups[0]["ead"] == pytest_approx(member_ead)


# ------------------------------------------------------------------ overview

def test_overview_matches_components(q):
    ov = dl.compute_brf_overview(q)
    aq = dl.compute_brf_asset_quality(q)
    le = dl.compute_brf_large_exposures(q)
    assert ov["npl_pct"] == pytest_approx(aq["npl_pct"])
    assert ov["capital_base"] == pytest_approx(le["capital_base"])
    assert ov["reportable_count"] == le["reportable_count"]


# ------------------------------------------------------------ AED conversion

def test_aed_peg_conversion():
    assert dl.AED_PER_USD == 3.6725
    assert dl.fmt_aed_bn(1000) == f"AED {1000 * 3.6725 / 1000:,.1f}bn"
    assert dl.fmt_aed_mn(None) == "—"
