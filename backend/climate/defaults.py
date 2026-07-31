"""
The Oman Climate Stressed PD v5.1 dataset, as a plain JSON-serialisable model dict.

This module is *data*, not code: Oman is one dataset, not a hard-wired country.
Everything the workbook held on an input tab lives here as an editable value, so
a second country is a second dict — no engine change. `default_model()` returns a
deep copy, so callers can mutate freely.

Scenario codes throughout: NZ = Net Zero 2050, DT = Delayed Transition,
CP = Current Policies, FW = Fragmented World. Hazard codes: H1 = tropical cyclone
and flood, H2 = extreme heat, H3 = water stress and drought.

Status vocabulary on every sourced row (rendered as badges in the UI):
VERIFIED, TO_VERIFY, UNVERIFIED, PLAUSIBLE, JUDGEMENT, ASSUMPTION, INPUT, SAMPLE,
DERIVED, SOURCED, PLACEHOLDER.
"""

import copy

MODEL_NAME = "Oman Climate Stressed PD"
MODEL_VERSION_LABEL = "v5.1"
HORIZON_YEARS = [2030, 2035, 2040, 2050]

SCENARIO_ORDER = ["NZ", "DT", "CP", "FW"]
HAZARD_ORDER = ["H1", "H2", "H3"]

# ------------------------------------------------------------------- sectors

_SECTORS = [
    dict(id="S01", name="Agriculture, Forestry & Fishing", isic="A", gva_omr=996.814843,
         turnover_gva=1.0, pass_through=0.25, macro_beta=1.0,
         rationale="Commodity price-takers, partly supported by domestic subsidy. Low pass-through."),
    dict(id="S02", name="Oil & Gas Extraction", isic="B (petroleum part)", gva_omr=14750.293609,
         turnover_gva=1.0, pass_through=0.05, macro_beta=1.0,
         rationale="World-priced crude and LNG. A domestic carbon cost cannot be passed to an "
                   "international buyer. Near-zero pass-through."),
    dict(id="S03", name="Mining & Quarrying (non-oil)", isic="B (remainder)", gva_omr=205.8,
         turnover_gva=1.0, pass_through=0.30, macro_beta=1.0,
         rationale="Limestone, gypsum, chromite, copper. Part exported at world prices, part sold "
                   "into the domestic construction chain."),
    dict(id="S04", name="Manufacturing", isic="C", gva_omr=3819.751676,
         turnover_gva=1.0, pass_through=0.30, macro_beta=1.0,
         rationale="Dominated in Oman by refining, petrochemicals and metals, all internationally "
                   "traded against unabated Gulf and Asian competitors. Weighted below the 45% base rate."),
    dict(id="S05", name="Electricity, Gas, Water & Waste", isic="D, E", gva_omr=970.07565,
         turnover_gva=1.0, pass_through=0.80, macro_beta=1.0,
         rationale="Regulated tariffs with cost recovery through the regulator and state subsidy. Cost "
                   "migrates to the sovereign rather than the utility. Corollary: residual credit risk "
                   "becomes sovereign-linked, which this model does not capture."),
    dict(id="S06", name="Construction", isic="F", gva_omr=2766.34407,
         turnover_gva=1.0, pass_through=0.50, macro_beta=1.0,
         rationale="Domestic, contract-based. Cost-escalation clauses on long contracts, fixed price "
                   "on many others."),
    dict(id="S07", name="Wholesale & Retail Trade", isic="G", gva_omr=3165.689408,
         turnover_gva=1.0, pass_through=0.70, macro_beta=1.0,
         rationale="Passes input cost to the final consumer over the medium term. Thin margins but "
                   "high pass-through."),
    dict(id="S08", name="Transport & Storage", isic="H", gva_omr=1680.825971,
         turnover_gva=1.0, pass_through=0.60, macro_beta=1.0,
         rationale="Fuel surcharges are standard contractual practice in freight and warehousing; partly "
                   "offset by international competition in shipping and aviation."),
    dict(id="S09", name="Accommodation & Food Services", isic="I", gva_omr=585.411617,
         turnover_gva=1.0, pass_through=0.35, macro_beta=1.0,
         rationale="Price-elastic international demand competing with regional destinations. "
                   "Below-average pass-through."),
    dict(id="S10", name="Financial, Professional, Public & Other Services",
         isic="J, K, L, M, N, O, P, Q, R, S, T", gva_omr=13022.900447,
         turnover_gva=1.0, pass_through=0.60, macro_beta=1.0,
         rationale="Domestic and largely non-traded. Includes real estate (ISIC L), which Oman's SNA "
                   "submission does not itemise separately."),
]

# ------------------------------------------------------ EDGAR emissions allocation
# `mt=None` marks the plug row: national total less every other category.

_EDGAR = [
    dict(code="E1", name="Fuel Exploitation", mt=42.24,
         definition="Upstream oil and gas: fugitive methane, venting, flaring, own energy use. IPCC 1B.",
         judgement=False,
         shares={"S01": 0, "S02": 1, "S03": 0, "S04": 0, "S05": 0, "S06": 0, "S07": 0,
                 "S08": 0, "S09": 0, "S10": 0, "HH": 0}),
    dict(code="E2", name="Power Industry", mt=17.15,
         definition="Public electricity and heat generation. IPCC 1A1a.",
         judgement=False,
         shares={"S01": 0, "S02": 0, "S03": 0, "S04": 0, "S05": 1, "S06": 0, "S07": 0,
                 "S08": 0, "S09": 0, "S10": 0, "HH": 0}),
    dict(code="E3", name="Industrial Combustion", mt=14.29,
         definition="Fuel combustion in manufacturing industries AND construction. IPCC 1A2.",
         judgement=True,
         shares={"S01": 0, "S02": 0, "S03": 0.05, "S04": 0.85, "S05": 0, "S06": 0.10, "S07": 0,
                 "S08": 0, "S09": 0, "S10": 0, "HH": 0}),
    dict(code="E4", name="Transport", mt=13.01,
         definition="Road, domestic aviation, domestic navigation, rail. INCLUDES private household "
                    "vehicles. IPCC 1A3.",
         judgement=True,
         shares={"S01": 0, "S02": 0, "S03": 0, "S04": 0, "S05": 0, "S06": 0, "S07": 0.10,
                 "S08": 0.40, "S09": 0, "S10": 0, "HH": 0.50}),
    dict(code="E5", name="Agriculture", mt=1.86,
         definition="Enteric fermentation, manure, soils, agricultural fuel use. IPCC 3.",
         judgement=False,
         shares={"S01": 1, "S02": 0, "S03": 0, "S04": 0, "S05": 0, "S06": 0, "S07": 0,
                 "S08": 0, "S09": 0, "S10": 0, "HH": 0}),
    dict(code="E6", name="Buildings", mt=22.23,
         definition="Residential, commercial and institutional fuel combustion, i.e. building OCCUPANCY "
                    "energy. IPCC 1A4. NOT the construction industry.",
         judgement=True,
         shares={"S01": 0, "S02": 0, "S03": 0, "S04": 0, "S05": 0, "S06": 0, "S07": 0.10,
                 "S08": 0, "S09": 0.05, "S10": 0.15, "HH": 0.70}),
    dict(code="E7", name="Residual (industrial processes, waste, other)", mt=None,
         definition="PLUG: national total less the six categories above.",
         judgement=True,
         shares={"S01": 0, "S02": 0.15, "S03": 0, "S04": 0.40, "S05": 0.25, "S06": 0, "S07": 0,
                 "S08": 0, "S09": 0, "S10": 0.10, "HH": 0.10}),
]

# ----------------------------------------------------------------- scenarios
# `gdp_deviation` 2035 is derived as the midpoint of 2030 and 2040 (the workbook
# interpolates it); the engine recomputes it, so editing the endpoints is enough.

_SCENARIOS = [
    dict(code="NZ", name="Net Zero 2050", quadrant="Orderly", warming_2100=1.4,
         carbon_price={2030: 200, 2035: 294, 2040: 420, 2050: 630},
         gdp_deviation={2030: -1.5, 2035: -1.25, 2040: -1.0, 2050: -0.8},
         intensity_index=1.0, denominator_index=1.0),
    dict(code="DT", name="Delayed Transition", quadrant="Disorderly", warming_2100=1.7,
         carbon_price={2030: 5, 2035: 100, 2040: 165, 2050: 315},
         gdp_deviation={2030: -0.3, 2035: -1.15, 2040: -2.0, 2050: -1.7},
         intensity_index=1.0, denominator_index=1.0),
    dict(code="CP", name="Current Policies", quadrant="Hot House World", warming_2100=3.0,
         carbon_price={2030: 5, 2035: 6, 2040: 8, 2050: 10},
         gdp_deviation={2030: 0.0, 2035: 0.0, 2040: 0.0, 2050: 0.0},
         intensity_index=1.0, denominator_index=1.0),
    dict(code="FW", name="Fragmented World", quadrant="Too Little Too Late", warming_2100=2.4,
         carbon_price={2030: 5, 2035: 20, 2040: 35, 2050: 55},
         gdp_deviation={2030: 0.0, 2035: 0.0, 2040: 0.0, 2050: 0.0},
         intensity_index=1.0, denominator_index=1.0),
]

# ------------------------------------------------------------ physical hazards

_HAZARDS = [
    dict(id="H1", name="Tropical cyclone and flood", baseline_aal=None, elasticity=2.0,
         insurance_recovery=0.25, pnl_share=0.60, status="SOURCED",
         mechanism="Destruction of physical capital, followed by business interruption while "
                   "operations are restored.",
         note="Derived from Oman's own event record below, not entered directly."),
    dict(id="H2", name="Extreme heat", baseline_aal=0.003, elasticity=3.0,
         insurance_recovery=0.0, pnl_share=1.0, status="INPUT",
         mechanism="Loss of outdoor labour productivity, midday working restrictions, higher cooling "
                   "load and equipment derating.",
         note="Replace with NGFS Phase V acute heatwave damage for the Middle East region."),
    dict(id="H3", name="Water stress and drought", baseline_aal=0.001, elasticity=1.5,
         insurance_recovery=0.0, pnl_share=1.0, status="INPUT",
         mechanism="Constrained output, higher input costs, higher desalination energy cost.",
         note="Replace with NGFS Phase V acute drought damage for the Middle East region."),
]

_CYCLONE_EVENTS = [
    dict(event="Cyclone Gonu", year=2007, damage_usd_m=4200.0,
         source="Fritz et al. (2010); IWA Water Practice & Technology 17(12). Widely reported at "
                "US$4.0 to 4.2bn (2007 dollars). Still the worst natural disaster in Oman's history."),
    dict(event="Cyclone Phet", year=2010, damage_usd_m=700.0,
         source="Haggag & Badry (2012). Damage exceeded US$700m in Oman."),
    dict(event="Cyclone Shaheen", year=2021, damage_usd_m=500.0,
         source="Government of Oman estimate of direct economic losses, cited in Al-Manji (2022)."),
]

# 30 judgement cells: raw relative exposure per sector per hazard.
_EXPOSURE_RAW = {
    "S01": {"H1": 2.5, "H2": 3.0, "H3": 5.0},
    "S02": {"H1": 0.7, "H2": 1.5, "H3": 1.5},
    "S03": {"H1": 1.0, "H2": 3.0, "H3": 1.5},
    "S04": {"H1": 2.0, "H2": 1.0, "H3": 1.2},
    "S05": {"H1": 2.2, "H2": 1.2, "H3": 2.0},
    "S06": {"H1": 1.5, "H2": 3.5, "H3": 0.8},
    "S07": {"H1": 1.8, "H2": 0.5, "H3": 0.2},
    "S08": {"H1": 2.0, "H2": 1.5, "H3": 0.2},
    "S09": {"H1": 2.0, "H2": 0.8, "H3": 1.0},
    "S10": {"H1": 0.5, "H2": 0.3, "H3": 0.2},
}

_EXPOSURE_RATIONALE = {
    "S01": "Batinah farms were the worst-hit sector in Shaheen. Outdoor labour throughout. "
           "Overwhelmingly the most water-dependent activity in the economy.",
    "S02": "Producing fields are largely inland and away from cyclone tracks, though export terminals "
           "and coastal infrastructure are exposed. Outdoor operations in extreme heat.",
    "S03": "Quarries are dispersed. Entirely outdoor work, so heat exposure is at the top of the range.",
    "S04": "Oman's industrial base is concentrated in coastal zones at Sohar, Duqm and Salalah, which "
           "is exactly where cyclones make landfall. Production is mostly indoors.",
    "S05": "Generation and desalination plants sit on the coast, and distribution networks failed widely "
           "in both Gonu and Shaheen. Desalination energy demand rises with water stress.",
    "S06": "Sites, plant and stored materials are exposed. Highest heat exposure of any sector: outdoor "
           "labour subject to statutory midday working bans in summer.",
    "S07": "Retail premises and warehousing are concentrated along the populated Batinah coast.",
    "S08": "Ports, roads and logistics assets are coastal and were among the most visibly damaged in Shaheen.",
    "S09": "Hotel stock is overwhelmingly coastal, and tourism is water-intensive per guest.",
    "S10": "Offices, dispersed and mostly inland. Lowest physical exposure of any sector on all three hazards.",
}

# --------------------------------------------------------------- k calibration

_ANCHORS = [
    dict(id=1, group="Median European firm", baseline_pd=0.02, rel_change=0.005, use="FIT",
         identification="Orderly transition vs hot house world, policy implementation phase (Section 5.3). "
                        "Hot house world has no transition policy, so this is a clean transition-only difference.",
         mechanism="Scope 1 carbon cost into operating expenses (Section 5.1)."),
    dict(id=2, group="High-emitting firms (top 10% by intensity)", baseline_pd=0.02, rel_change=0.02, use="FIT",
         identification="Orderly transition vs no policy action, short term (Section 5.4). Stated in the same "
                        "sentence as the median 0.5% figure, so it is the same identification.",
         mechanism="Scope 1 carbon cost into operating expenses."),
    dict(id=3, group="Coal mining NACE B05, orderly", baseline_pd=0.02, rel_change=1.5, use="CHECK",
         identification="PD rises to 5.0%, a 150% increase on current values (Section 5.4). Measured against "
                        "the 2020 starting point, not against hot house world.",
         mechanism="MAINLY Scope 3 abatement investment raising leverage, stated explicitly in Section 5.4. "
                   "NOT a Scope 1 cost response."),
    dict(id=4, group="Coal mining NACE B05, disorderly", baseline_pd=0.02, rel_change=1.0, use="CHECK",
         identification="PD rises to 4.0%, a 100% increase on current values (Section 5.4).",
         mechanism="As anchor 3."),
]

_CALIBRATION = dict(
    anchors=_ANCHORS,
    baseline_pd=0.02,
    anchor_a_rel=0.005,
    anchor_b_rel=0.025,
    anchor_in_use="A",
    anchor_a_note="VERIFIED: OP 281 Section 5.3. The median firm carries a PD about 0.5% HIGHER under "
                  "orderly transition than under hot house world during the policy implementation phase. "
                  "Hot house world has no transition policy, so this is a clean transition-only effect.",
    anchor_b_note="VERIFIED: OP 281 Section 5.3. Median-firm PDs are about 2.5% higher by 2050 under "
                  "disorderly than under orderly transition. Not transition-only; retained for sensitivity.",
    route_in_use=1,
    # Route 1 — symmetric: national Scope 1 emissions over national GVA, built exactly
    # as the Oman intensity is, so the turnover conversion never enters.
    route1=dict(eu_total_ghg_mt=3000.0, household_share=0.20, eu_gva_eur_bn=15200.0,
                median_to_average=0.57),
    # Route 2 — firm-level. Retained for comparison; reintroduces the turnover/GVA conversion.
    route2=dict(median_total_intensity=850.0, scope1_share=0.12, turnover_gva_ratio=3.0),
    anchor_price_usd=100.0,
    usd_eur=0.8741,
    eu_pass_through=0.0,
    coal_plausible_intensity_multiple=10.0,
    k_sensitivity_intensities=[50, 90, 150, 250, 400],
    theta_band=[1.0, 0.5, 0.0, -0.5, -1.0],
)

# ------------------------------------------------------------------ macro leg

_MACRO_OBSERVATIONS = [
    dict(year=2014, npl_ratio=0.019, gdp_growth=0.01292252294),
    dict(year=2015, npl_ratio=0.017, gdp_growth=0.05017057997),
    dict(year=2016, npl_ratio=0.018, gdp_growth=0.05046423946),
    dict(year=2017, npl_ratio=0.019, gdp_growth=0.003040575659),
    dict(year=2018, npl_ratio=0.027, gdp_growth=0.01287103915),
    dict(year=2019, npl_ratio=0.035, gdp_growth=-0.01128638017),
    dict(year=2020, npl_ratio=0.042, gdp_growth=-0.03379720527),
    dict(year=2021, npl_ratio=0.042, gdp_growth=0.02582472509),
    dict(year=2022, npl_ratio=0.044, gdp_growth=0.07985394093),
    dict(year=2023, npl_ratio=0.045, gdp_growth=0.01414087155),
    dict(year=2024, npl_ratio=0.045, gdp_growth=0.01631663974),
]

# The 17 specifications tested when selecting the macro leg. Reference only — the
# engine estimates S8 live from the observations above.
_REGRESSION_TESTS = [
    ("S1", "N-1(NPLR) ~ g", "level", 11, 0.028, -0.079, -0.984, -0.51, 0.620, 0.16,
     "Specification used in v2. Durbin-Watson 0.16: severe positive residual autocorrelation, the level "
     "series is near non-stationary, the fit is spurious."),
    ("S2", "N-1(NPLR) ~ g(-1)", "level", 11, 0.100, 0.000, -1.761, -1.00, 0.344, 0.29,
     "Autocorrelation unresolved."),
    ("S3", "N-1(NPLR) ~ g(-2)", "level", 11, 0.206, 0.118, -2.184, -1.53, 0.161, 0.38,
     "Autocorrelation unresolved."),
    ("S4", "N-1(NPLR) ~ MA2(g,g-1)", "level", 11, 0.102, 0.002, -2.385, -1.01, 0.338, 0.21,
     "Autocorrelation unresolved."),
    ("S5", "N-1(NPLR) ~ MA2(g-1,g-2)", "level", 11, 0.236, 0.151, -3.128, -1.67, 0.130, 0.37,
     "Autocorrelation unresolved."),
    ("S6", "N-1(NPLR) ~ MA3(g..g-2)", "level", 11, 0.277, 0.197, -4.620, -1.86, 0.096, 0.23,
     "Highest level-form R2, but DW 0.23 makes the standard errors uninterpretable. Rejected."),
    ("S7", "N-1(NPLR) ~ g + g(-1)", "level", 11, 0.114, -0.108, -0.698, -0.35, 0.732, 0.25,
     "Adding a lag lowers adjusted R2."),
    ("S8", "D N-1(NPLR) ~ g", "difference", 10, 0.280, 0.190, -0.952, -1.76, 0.116, 1.886,
     "SELECTED. Differencing removes the near unit root. DW 1.89, correct sign, correlation -0.53. The "
     "implied mapping runs from the GDP LEVEL to the probit default rate, which is exactly what an NGFS "
     "GDP level deviation supplies."),
    ("S9", "D N-1(NPLR) ~ g(-1)", "difference", 10, 0.044, -0.076, -0.376, -0.60, 0.562, 1.09,
     "Lagging destroys the fit."),
    ("S10", "D N-1(NPLR) ~ MA2(g,g-1)", "difference", 10, 0.227, 0.131, -1.108, -1.53, 0.163, 1.58,
     "Close second; smoothing adds nothing over S8."),
    ("S11", "D N-1(NPLR) ~ Dg", "difference", 10, 0.063, -0.054, -0.357, -0.74, 0.483, 1.16,
     "Over-differenced."),
    ("S12", "D N-1(NPLR) ~ Dg(-1)", "difference", 10, 0.007, -0.117, -0.114, -0.24, 0.818, 1.00,
     "No relationship."),
    ("S13", "N-1(NPLR) ~ g + lag dep.", "dynamic", 10, 0.927, 0.906, -0.966, -1.73, 0.128, 1.91,
     "R2 0.93 is entirely the lagged dependent variable, whose coefficient is 0.93 with p<0.001, i.e. a "
     "near unit root. Implied long-run beta -13.9, unusable."),
    ("S14", "N-1(NPLR) ~ g(-1) + lag dep.", "dynamic", 10, 0.902, 0.874, -0.445, -0.68, 0.518, 1.10, "As S13."),
    ("S15", "N-1(NPLR) ~ output gap", "level", 11, 0.106, 0.007, 1.966, 1.04, 0.327, 0.35,
     "Sign wrong (positive). Rejected."),
    ("S16", "N-1(NPLR) ~ output gap(-1)", "level", 11, 0.050, -0.056, 1.344, 0.69, 0.509, 0.23,
     "Sign wrong. Rejected."),
    ("S17", "D N-1(NPLR) ~ output gap(-1)", "difference", 10, 0.063, -0.054, -0.467, -0.74, 0.483, 1.14,
     "Correct sign, no explanatory power."),
]

_MACRO = dict(
    observations=_MACRO_OBSERVATIONS,
    correlation_in_use=-0.5291,
    selected_specification="S8",
    regression_tests=[
        dict(id=t[0], specification=t[1], form=t[2], n=t[3], r2=t[4], adj_r2=t[5], beta=t[6],
             t_stat=t[7], p=t[8], dw=t[9], assessment=t[10])
        for t in _REGRESSION_TESTS
    ],
    npl_source="As entered in the v2 workbook, no citation recorded. TO VERIFY against the CBO Annual "
               "Report or Financial Stability Report.",
    gdp_source="Economist Intelligence Unit, Oman, Real GDP (% change, period on period), series DGDP.",
)

# --------------------------------------------------------------- rating grades

_RATING_GRADES = [
    dict(grade="MR1", baseline_pd=0.0010),
    dict(grade="MR2", baseline_pd=0.0025),
    dict(grade="MR3", baseline_pd=0.0050),
    dict(grade="MR4", baseline_pd=0.0100),
    dict(grade="MR5", baseline_pd=0.0200),
    dict(grade="MR6", baseline_pd=0.0450),
    dict(grade="MR7", baseline_pd=0.1000),
]

# ------------------------------------------------------------------- settings

_SETTINGS = dict(
    horizon_year=2040,
    theta=0.0,
    cost_ratio_cap=999.0,
    denominator_basis="GVA",           # GVA | TURNOVER
    us_gdp_deflator=1.35,
    currency_peg=2.6008,               # local currency units per US$
    currency_code="OMR",
    carbon_price_base_year=2010,
    denominator_base_year=2023,
    warming_today=1.3,
    base_year=2025,
    terminal_year=2100,
    national_total_ghg_mt=132.27,
    population_m=5.3,
    sna_total_gva_omr=41963.907406,
    cyclone_observation_years=18,
    reference_grade="MR5",
)


def default_model() -> dict:
    """A fresh, fully-resolved v5.1 Oman model input dict."""
    return copy.deepcopy({
        "name": f"{MODEL_NAME} {MODEL_VERSION_LABEL}",
        "country": "Oman",
        "basis_note": "GVA 2023 current prices against 2024 EDGAR emissions — a one-year timing "
                      "mismatch, disclosed rather than papered over.",
        "settings": _SETTINGS,
        "sectors": _SECTORS,
        "edgar_categories": _EDGAR,
        "scenarios": _SCENARIOS,
        "hazards": _HAZARDS,
        "cyclone_events": _CYCLONE_EVENTS,
        "exposure_raw": _EXPOSURE_RAW,
        "exposure_rationale": _EXPOSURE_RATIONALE,
        "calibration": _CALIBRATION,
        "macro": _MACRO,
        "rating_grades": _RATING_GRADES,
    })


def normalise_model(model: dict) -> dict:
    """Coerce a model dict that has been round-tripped through JSON back into its
    native types.

    JSON object keys are always strings, so `carbon_price[2040]` comes back as
    `carbon_price["2040"]` after a save/load cycle. Rather than making every
    consumer defend against both forms, the conversion happens once here, at the
    boundary where stored JSON re-enters the application.
    """
    for scenario in model.get("scenarios", []):
        for field in ("carbon_price", "gdp_deviation"):
            values = scenario.get(field)
            if isinstance(values, dict):
                scenario[field] = {int(year): float(value) for year, value in values.items()}
    return model


def scenario_names(model: dict | None = None) -> dict:
    scen = (model or default_model())["scenarios"]
    return {s["code"]: s["name"] for s in scen}
