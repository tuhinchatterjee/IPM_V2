"""
Excel parity is the acceptance criterion for the climate engine.

The golden master below is the Oman Climate Stressed PD v5.1 workbook: the
figures are read straight off its cells, and the engine has to reproduce them
from the v5.1 fixture. The tolerance is 1e-11 relative, which is tighter than
Excel's own precision — anything looser would let a real drift through.

The property tests then cover what a golden master cannot: that the structure
holds for inputs the workbook never contained.
"""

import math

import pytest

from backend.climate import checks, defaults, engine, sensitivity
from backend.climate.normal import norm_cdf, norm_ppf

REL_TOL = 1e-11


@pytest.fixture(scope="module")
def model():
    return defaults.default_model()


@pytest.fixture(scope="module")
def result(model):
    return engine.calculate(model)


def close(actual, expected, tol=REL_TOL):
    assert actual == pytest.approx(expected, rel=tol, abs=1e-15), f"{actual!r} != {expected!r}"


# --------------------------------------------------------- NORMSINV / NORMSDIST

@pytest.mark.parametrize("p,expected", [
    # Excel NORMSINV, 15 significant figures.
    (0.0001, -3.71901648545568),
    (0.001, -3.09023230616781),
    (0.0025, -2.8070337683438042),
    (0.005, -2.5758293035489),
    (0.01, -2.32634787404084),
    (0.02, -2.05374891063182),
    (0.045, -1.69539771027214),
    (0.05, -1.64485362695147),
    (0.1, -1.2815515655446),
    (0.5, 0.0),
    (0.9, 1.2815515655446),
    (0.99, 2.32634787404084),
])
def test_norm_ppf_matches_excel(p, expected):
    close(norm_ppf(p), expected, tol=1e-13)


def test_norm_ppf_round_trips_across_the_pd_range():
    """The grid only ever consumes probabilities in this band, so parity there is
    what actually matters."""
    p = 0.0001
    while p <= 0.10:
        assert norm_cdf(norm_ppf(p)) == pytest.approx(p, rel=1e-13)
        p += 0.0001


def test_norm_ppf_rejects_degenerate_probabilities():
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            norm_ppf(bad)


def test_norm_cdf_matches_excel():
    close(norm_cdf(0.0), 0.5, tol=1e-15)
    close(norm_cdf(-2.05374891063182), 0.02, tol=1e-13)
    close(norm_cdf(1.2815515655446), 0.9, tol=1e-13)


# ------------------------------------------------------------ the transform g

def test_g_log_limit_at_theta_zero():
    """The log branch must be the true limit, approached smoothly from both sides.
    This is what breaks if g is evaluated by literally raising to a power and
    subtracting one: the subtraction discards the significant digits."""
    for x in (0.0, 0.001, 0.0078669, 0.5, 1.02, 12.0):
        close(engine.g(x, 0.0), math.log1p(x), tol=1e-15)
        close(engine.g(x, 1e-9), math.log1p(x), tol=1e-8)
        close(engine.g(x, -1e-9), math.log1p(x), tol=1e-8)
        close(engine.g(x, 1e-13), math.log1p(x), tol=1e-15)


def test_g_is_linear_at_theta_one():
    for x in (0.0, 0.25, 1.0, 8.0):
        close(engine.g(x, 1.0), x, tol=1e-14)


def test_g_is_monotone_in_the_cost_ratio():
    previous = -1.0
    for i in range(200):
        value = engine.g(i * 0.01, 0.0)
        assert value > previous
        previous = value


# ------------------------------------------------------------- golden master

def test_calibration_matches_workbook(result):
    cal = result["calibration"]
    close(cal["push_eu"], 0.00206097533312555)
    close(cal["eu_intensity"], 90.0)
    close(cal["route1_economy_intensity"], 157.894736842105)
    close(cal["route2_intensity"], 306.0)
    close(cal["anchor_price_eur"], 87.41)
    close(cal["cost_ratio_eu"], 0.0078669)
    close(cal["g_at_anchor"], 0.00783611727985288)
    close(result["k"], 0.263009761023414)
    close(cal["push_ratio_high_median"], 3.97489321270291)
    close(cal["implied_intensity_multiple"], 4.02164713756821)


def test_coal_anchor_is_rejected_out_of_sample(result):
    coal = result["calibration"]["coal"]
    close(coal["push_ratio"], 198.39892166989)
    close(coal["required_multiple"], 474.590801078599)
    close(coal["discrepancy"], 47.4590801078599)
    assert coal["rejected"] is True


def test_extrapolation_multiple_matches_workbook(result):
    close(result["max_cost_ratio"], 1.02037884770977)
    close(result["calibration"]["extrapolation"]["multiple"], 129.705328364384)


@pytest.mark.parametrize("sector_id,expected", [
    ("S01", 717.449754858143), ("S02", 1185.10067398957), ("S03", 1334.90360594737),
    ("S04", 2087.94479673583), ("S05", 8926.9691855998), ("S06", 198.61821606592),
    ("S07", 428.016626906395), ("S08", 1190.44019280374), ("S09", 730.030784475165),
    ("S10", 161.898628866796),
])
def test_sector_intensities_match_workbook(result, sector_id, expected):
    sector = next(s for s in result["sectors"] if s["id"] == sector_id)
    close(sector["intensity"], expected)


def test_emissions_allocation_matches_workbook(result):
    em = result["emissions"]
    close(em["national_total_mt"], 132.27)
    close(em["allocated_total_mt"], 132.27, tol=1e-12)
    close(em["households_mt"], 24.215)
    close(em["corporate_share"], 0.816927496786875)
    close(em["buildings_per_head"], 4.19433962264151)
    close(result["totals"]["economy_intensity"], 990.061088829765)
    close(result["totals"]["total_gva_local"], 41963.907291)


@pytest.mark.parametrize("sector_id,expected", [
    ("S01", 0.305095508253425), ("S02", 0.638354478044483), ("S03", 0.52982324120051),
    ("S04", 0.828705289824451), ("S05", 1.01231830564702), ("S06", 0.0563082642546883),
    ("S07", 0.0728056282367778), ("S08", 0.269991835727888), ("S09", 0.269052845618322),
    ("S10", 0.0367186090269893),
])
def test_transition_cost_ratios_net_zero(result, sector_id, expected):
    close(result["by_cell"][(sector_id, "NZ")]["transition_cost"], expected)


@pytest.mark.parametrize("sector_id,scenario,expected", [
    ("S01", "NZ", 0.0164764753794968), ("S01", "DT", 0.0182823097380213),
    ("S01", "CP", 0.0276149214746485), ("S01", "FW", 0.0229917975234853),
    ("S02", "NZ", 0.00649948135817854), ("S03", "CP", 0.0196164248609235),
    ("S04", "CP", 0.0107226968673174), ("S05", "FW", 0.0111458563458659),
    ("S06", "CP", 0.0221149528488265), ("S07", "DT", 0.00417810205213588),
    ("S08", "NZ", 0.00670739237761484), ("S09", "NZ", 0.00567199721146509),
    ("S10", "DT", 0.00182140478889122),
])
def test_physical_cost_ratios_match_workbook(result, sector_id, scenario, expected):
    close(result["by_cell"][(sector_id, scenario)]["physical_cost"], expected)


def test_physical_baseline_is_derived_from_the_event_record(result):
    phys = result["physical"]
    close(phys["observed_damage_usd_m"], 5400.0)
    close(phys["national_gva_usd_m"], 109139.730082433)
    close(phys["event_aal_share"], 0.00274876985469371)
    close(phys["hazards"][0]["baseline_aal"], 0.00274876985469371)
    close(phys["warming"]["CP"]["at_horizon"], 1.64)
    close(phys["severity"]["H2"]["CP"], 2.00771233500228)
    close(phys["gva_weighted_cost"]["NZ"], 0.00543906718745168)
    close(phys["gva_weighted_cost"]["CP"], 0.00940864929940253)


def test_macro_leg_matches_workbook(result):
    macro = result["macro"]
    close(macro["correlation_estimated"], -0.529103679607976)
    close(macro["beta_ols"], -0.952018563725665)
    close(macro["intercept"], 0.0577095150788311)
    close(macro["r2"], 0.2799507037747)
    close(macro["sd_d_probit"], 0.0590955720196972)
    close(macro["sd_gdp_growth"], 0.0328435660769006)
    close(macro["beta_in_use"], -0.952011942990949)
    close(macro["by_scenario"]["NZ"]["shift"], 0.00952011942990949)
    close(macro["by_scenario"]["DT"]["shift"], 0.019040238859819)
    assert macro["by_scenario"]["CP"]["shift"] == 0.0
    assert macro["by_scenario"]["FW"]["shift"] == 0.0


@pytest.mark.parametrize("sector_id,scenario,expected", [
    ("S01", "NZ", 0.0733328877926169), ("S02", "FW", 0.0159405900510751),
    ("S04", "DT", 0.0755357877480243), ("S05", "NZ", 0.184970830880176),
    ("S10", "CP", 0.000916604364290975),
])
def test_push_matches_workbook(result, sector_id, scenario, expected):
    close(result["by_cell"][(sector_id, scenario)]["push"], expected)


@pytest.mark.parametrize("sector_id,grade,scenario,expected", [
    ("S01", "MR1", "NZ", 0.00131755373082972), ("S01", "MR5", "NZ", 0.0243678919051448),
    ("S02", "MR5", "NZ", 0.0278521701169089), ("S03", "MR6", "DT", 0.0521917296559422),
    ("S04", "MR5", "NZ", 0.0297452011050079), ("S04", "MR7", "DT", 0.117618634594387),
    ("S05", "MR1", "FW", 0.00108384047572622), ("S10", "MR5", "DT", 0.0211543935976402),
    ("S10", "MR7", "CP", 0.100160957032097),
])
def test_stressed_pd_grid_matches_workbook(result, sector_id, grade, scenario, expected):
    close(result["by_grid"][(sector_id, grade, scenario)]["stressed_pd"], expected)


@pytest.mark.parametrize("sector_id,scenario,expected", [
    ("S05", "NZ", 1.57476456980464), ("S04", "NZ", 1.4872600552504),
    ("S06", "DT", 1.07052538863888), ("S08", "CP", 1.01076712641623),
    ("S10", "FW", 1.00341519258913),
])
def test_mr5_multiples_match_workbook(result, sector_id, scenario, expected):
    close(result["by_grid"][(sector_id, "MR5", scenario)]["multiple"], expected)


@pytest.mark.parametrize("sector_id,expected", [
    ("S01", 0.0449953863889396), ("S02", 0.00795582834052092),
    ("S06", 0.172441509577423), ("S10", 0.0418551314118138),
])
def test_physical_share_of_push_matches_workbook(result, sector_id, expected):
    close(result["by_cell"][(sector_id, "NZ")]["physical_share"], expected)


@pytest.mark.parametrize("theta,k,push,multiple", [
    (1.0, 0.261980619192509, 0.267319482333944, 1.85074385750843),
    (0.5, 0.262494853649308, 0.221230826592052, 1.67185674989987),
    (0.0, 0.263009761023414, 0.184970830880176, 1.54134239415181),
    (-0.5, 0.263525341315868, 0.156253885921086, 1.44406587027446),
    (-1.0, 0.264041594525634, 0.133352444406615, 1.37019598943836),
])
def test_theta_band_matches_workbook(result, theta, k, push, multiple):
    """k is refitted at every theta — it is a function of theta, never a constant."""
    row = next(b for b in result["calibration"]["theta_band"] if b["theta"] == theta)
    close(row["k"], k)
    close(row["push_at_max"], push)
    close(row["pd_multiple"], multiple)


@pytest.mark.parametrize("intensity,k_a,k_b", [
    (50, 0.472594853224457, 2.34325999758484),
    (90, 0.263009761023414, 1.30407736727468),
    (150, 0.158216621950155, 0.78448311199174),
    (250, 0.0953397979025859, 0.472721895041135),
    (400, 0.0599702247006808, 0.297349468849457),
])
def test_k_sensitivity_grid_matches_workbook(result, intensity, k_a, k_b):
    row = next(r for r in result["calibration"]["k_sensitivity"] if r["intensity"] == intensity)
    close(row["k_a"], k_a)
    close(row["k_b"], k_b)


def test_grid_dimensions(result):
    assert len(result["sectors"]) == 10
    assert len(result["grades"]) == 7
    assert len(result["scenario_codes"]) == 4
    assert len(result["cells"]) == 40
    assert len(result["grid"]) == 280


# ------------------------------------------------------- structural properties

def test_zero_shock_returns_the_baseline_exactly(model):
    """The reason for the pure probit shift: at zero stress the model returns PD_0
    exactly. The conditional-Vasicek form used in v2 returned values BELOW it."""
    flat = defaults.default_model()
    for scenario in flat["scenarios"]:
        for year in scenario["carbon_price"]:
            scenario["carbon_price"][year] = 0.0
            scenario["gdp_deviation"][year] = 0.0
    for hazard in flat["hazards"]:
        hazard["baseline_aal"] = 0.0
    flat["cyclone_events"] = []

    out = engine.calculate(flat)
    for row in out["grid"]:
        assert row["stressed_pd"] == pytest.approx(row["baseline_pd"], rel=1e-14)
        assert row["multiple"] == pytest.approx(1.0, rel=1e-14)


def test_no_cell_ever_de_stresses(result):
    for row in result["grid"]:
        assert row["stressed_pd"] >= row["baseline_pd"] - 1e-12


def test_push_is_monotone_in_the_cost_ratio(model):
    """Doubling every carbon price can only raise the push, never lower it."""
    base = engine.calculate(model)
    hotter = defaults.default_model()
    for scenario in hotter["scenarios"]:
        for year in scenario["carbon_price"]:
            scenario["carbon_price"][year] *= 2
    out = engine.calculate(hotter)
    for key, cell in base["by_cell"].items():
        assert out["by_cell"][key]["push"] >= cell["push"] - 1e-15


def test_exposure_weights_are_scale_invariant(model, result):
    """Weights are relative: multiplying all 30 by any constant must leave every
    result untouched, because normalisation divides by the GVA-weighted mean."""
    scaled = defaults.default_model()
    for sector_weights in scaled["exposure_raw"].values():
        for hazard in sector_weights:
            sector_weights[hazard] *= 7.3
    out = engine.calculate(scaled)
    for key, cell in result["by_cell"].items():
        close(out["by_cell"][key]["physical_cost"], cell["physical_cost"], tol=1e-12)


def test_exposure_normalisation_preserves_the_national_loss(result):
    for hazard, mean in result["physical"]["normalised_weighted_mean"].items():
        assert mean == pytest.approx(1.0, abs=1e-12), hazard


def test_cap_at_999_changes_nothing(model, result):
    lifted = defaults.default_model()
    lifted["settings"]["cost_ratio_cap"] = 1e9
    out = engine.calculate(lifted)
    for key, cell in result["by_cell"].items():
        close(out["by_cell"][key]["total_cost"], cell["total_cost"], tol=1e-15)
    assert result["cap_binding_cells"] == 0


def test_cap_binds_when_lowered(model):
    capped = defaults.default_model()
    capped["settings"]["cost_ratio_cap"] = 0.25
    out = engine.calculate(capped)
    assert out["cap_binding_cells"] > 0
    for cell in out["cells"]:
        assert cell["total_cost"] <= 0.25 + 1e-15


def test_cost_ratios_are_summed_inside_the_transform(result):
    """The concavity trap: k*g(a+b) must be strictly LESS than k*g(a)+k*g(b) at
    theta = 0, and the engine must be computing the former."""
    cell = result["by_cell"][("S05", "NZ")]
    k, theta = result["k"], result["theta"]
    joint = k * engine.g(cell["total_cost"], theta)
    separate = k * engine.g(cell["transition_cost"], theta) + k * engine.g(cell["physical_cost"], theta)
    close(cell["push"], joint, tol=1e-14)
    assert joint < separate


def test_transition_ordering_holds_for_every_sector(result):
    for sector in result["sectors"]:
        values = [result["by_cell"][(sector["id"], code)]["transition_cost"]
                  for code in checks.TRANSITION_ORDER]
        assert values == sorted(values, reverse=True), sector["name"]


def test_physical_ordering_holds_for_every_sector(result):
    """The exact reverse of the transition ordering. Both holding at once is the
    single most important structural test of a climate scenario model."""
    for sector in result["sectors"]:
        values = [result["by_cell"][(sector["id"], code)]["physical_cost"]
                  for code in checks.PHYSICAL_ORDER]
        assert values == sorted(values, reverse=True), sector["name"]


def test_grade_ladder_is_replaceable_without_code_change():
    swapped = defaults.default_model()
    swapped["rating_grades"] = [{"grade": "AAA", "baseline_pd": 0.0003},
                                {"grade": "BBB", "baseline_pd": 0.012},
                                {"grade": "CCC", "baseline_pd": 0.18}]
    swapped["settings"]["reference_grade"] = "BBB"
    out = engine.calculate(swapped)
    assert len(out["grid"]) == 10 * 3 * 4
    assert out["reference_grade"] == "BBB"
    for row in out["grid"]:
        assert row["stressed_pd"] >= row["baseline_pd"] - 1e-12


def test_turnover_basis_switches_both_sides_together():
    """Switching the denominator basis must move the EU calibration with it, or the
    two sides silently end up on different units — the original v2 defect."""
    turnover = defaults.default_model()
    turnover["settings"]["denominator_basis"] = "TURNOVER"
    turnover["calibration"]["route_in_use"] = 2
    for sector in turnover["sectors"]:
        sector["turnover_gva"] = 2.5
    out = engine.calculate(turnover)
    close(out["calibration"]["route2_intensity"], 850.0 * 0.12)
    assert out["totals"]["basis"] == "TURNOVER"


# ------------------------------------------------------------- quality checks

def test_all_quality_checks_run(model, result):
    rows = checks.run_checks(result, model)
    assert [c["id"] for c in rows] == list(range(1, 25))


def test_no_check_fails_on_the_v51_fixture(model, result):
    rows = checks.run_checks(result, model)
    summary = checks.summarise(rows)
    assert summary["failure_count"] == 0
    assert summary["can_finalise"] is True
    assert summary["structural_pair_ok"] is True


def test_the_four_expected_flags_are_exactly_as_documented(model, result):
    rows = checks.run_checks(result, model)
    assert sorted(c["id"] for c in rows if c["expected"]) == [14, 15, 19, 24]


def test_a_broken_allocation_row_fails_check_two():
    broken = defaults.default_model()
    broken["edgar_categories"][2]["shares"]["S04"] = 0.5   # row no longer sums to 1.00
    out = engine.calculate(broken)
    rows = checks.run_checks(out, broken)
    assert next(c for c in rows if c["id"] == 2)["status"] == "FAIL"
    assert checks.summarise(rows)["can_finalise"] is False


def test_a_zero_gva_sector_fails_check_five():
    broken = defaults.default_model()
    broken["sectors"][3]["gva_omr"] = 0.0
    out = engine.calculate(broken)
    rows = checks.run_checks(out, broken)
    assert next(c for c in rows if c["id"] == 5)["status"] == "FAIL"


# ---------------------------------------------------------------- sensitivity

def test_one_way_sweep_recalculates_each_point(model):
    sweep = sensitivity.one_way(model, "theta")
    assert len(sweep["points"]) == 5
    ks = [p["k"] for p in sweep["points"]]
    assert len(set(ks)) == 5, "k must be refitted at every theta"


def test_k_intensity_lever_reproduces_the_calibration_grid(model):
    sweep = sensitivity.one_way(model, "k_intensity", [50, 90, 400])
    close(sweep["points"][0]["k"], 0.472594853224457, tol=1e-9)
    close(sweep["points"][1]["k"], 0.263009761023414, tol=1e-9)
    close(sweep["points"][2]["k"], 0.0599702247006808, tol=1e-9)


def test_tornado_is_sorted_by_span(model):
    tor = sensitivity.tornado(model, ["theta", "correlation", "horizon"])
    spans = [b["span"] for b in tor["bars"]]
    assert spans == sorted(spans, reverse=True)


def test_run_comparison_reports_no_change_for_identical_runs(model, result):
    diff = sensitivity.compare_runs(result, result)
    assert diff["changed_count"] == 0
    assert diff["headline"]["max_abs_bps"] == pytest.approx(0.0)


def test_run_comparison_detects_a_horizon_change(model, result):
    later = defaults.default_model()
    later["settings"]["horizon_year"] = 2050
    diff = sensitivity.compare_runs(result, engine.calculate(later))
    assert diff["changed_count"] == 40
    assert diff["headline"]["max_abs_bps"] > 0


# -------------------------------------------------------------- decomposition

def test_decomposition_reconciles_to_the_grid(result):
    dec = engine.decompose(result, "S05", "MR5", "NZ")
    close(dec["row"]["stressed_pd"], 0.0315, tol=1e-2)
    contributions = sum(h["contribution"] for h in dec["hazards"])
    close(contributions, dec["cell"]["physical_cost"], tol=1e-12)
    close(dec["cell"]["push"] + dec["cell"]["macro_shift"], dec["cell"]["probit_shift"], tol=1e-15)
    close(norm_cdf(norm_ppf(dec["row"]["baseline_pd"]) + dec["cell"]["probit_shift"]),
          dec["row"]["stressed_pd"], tol=1e-14)
