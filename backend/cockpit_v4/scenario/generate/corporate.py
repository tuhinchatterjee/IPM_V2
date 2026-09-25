"""The Corporate candidate book: macro first, then risk, then measurement.

`v4-whatif-corporate-20q-s1`. Same four relations the accepted Corporate book
publishes, at the same grain and in the same columns, plus the seven candidate
relations `candidate_schema.py` declares. Nothing about the accepted release is
read or written here.

**The order of construction is the substance.** For each quarter:

1. the shared economic cycle and the twenty-factor panel exist first
   (`macro.py`);
2. each borrower's PD responds to the cycle *one quarter ago*, scaled by its
   sector's own beta and its own credit quality, through a logit link;
3. LGD responds to the property cycle, also lagged, through its collateral;
4. stage follows arrears and SICR, not the other way round;
5. and only then does `reference_ecl.py` measure the exposure — term
   structure, three scenarios, discounting, overlay.

A book built the other way round -- risk first, macro columns bolted on --
would let a sensitivity fitter report coefficients, an R-squared and a
heatmap, all of them artefacts. Here there is a relationship to recover, its
true native slope is computable from the parameters in this file, and
`test_whatif_sensitivity.py` checks that the estimator recovers it.

**Everything is SYNTHETIC_DEMO.** These borrowers do not exist, the economy
did not happen, and `reference_ecl.py` is a calculator written for this
demonstration rather than a bank engine.
"""

from __future__ import annotations

import math
import random
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.generate.totals import exact_total, whole_total
from backend.cockpit_v4.scenario import reference_ecl as ref
from backend.cockpit_v4.scenario.candidate_schema import ORIGIN, SCENARIOS
from backend.cockpit_v4.scenario.generate import (
    CORPORATE_BORROWERS,
    CORPORATE_SEED,
    quarter_range,
    signed,
    stable,
    unit_interval,
)
from backend.cockpit_v4.scenario.generate import macro as mv

#: The published rating scale, strongest first, with the default grade last.
#: `grade_rank` is this order, and a one-notch downgrade steps it by one.
#: There is nothing after D: a downgrade from default is refused, not wrapped.
RATINGS: tuple[str, ...] = ("AA", "A", "BBB+", "BBB", "BBB-", "BB+", "BB",
                            "BB-", "B+", "B", "CCC")
DEFAULT_GRADE = "D"
SCALE: tuple[str, ...] = RATINGS + (DEFAULT_GRADE,)
INVESTMENT_GRADE: frozenset[str] = frozenset({"AA", "A", "BBB+", "BBB",
                                              "BBB-"})
RATING_MAPPING_VERSION = "whatif-corp-ratings-1.0"

#: Through-the-cycle PD for each grade. Roughly geometric, which is what a
#: published masterscale looks like; the exact numbers are generator
#: parameters, published in `whatif_corp_rating_map` so a reader can check
#: every mapped figure against them.
GRADE_PD: dict[str, float] = {
    "AA": 0.0007, "A": 0.0014, "BBB+": 0.0026, "BBB": 0.0041,
    "BBB-": 0.0065, "BB+": 0.0102, "BB": 0.0161, "BB-": 0.0254,
    "B+": 0.0400, "B": 0.0630, "CCC": 0.1550, "D": 1.0,
}

SECTORS: tuple[str, ...] = (
    "Construction", "Real Estate", "Manufacturing", "Wholesale Trade",
    "Transport", "Healthcare", "Education", "Hospitality",
    "Utilities", "Petrochemicals", "Retail Trade", "Professional Services")

#: How hard each sector's PD responds to the cycle. This is the thing a
#: fitted sensitivity is trying to see, and it differs by sector on purpose:
#: section 7.2 asks for estimation "within stable, economically meaningful
#: book/segment groups", and a book where every sector moved identically
#: would make that instruction untestable.
SECTOR_BETA: dict[str, float] = {
    "Construction": 0.85, "Real Estate": 0.78, "Manufacturing": 0.52,
    "Wholesale Trade": 0.44, "Transport": 0.48, "Healthcare": 0.18,
    "Education": 0.16, "Hospitality": 0.66, "Utilities": 0.12,
    "Petrochemicals": 0.58, "Retail Trade": 0.40,
    "Professional Services": 0.28}

#: How hard each sector's LGD responds to the property cycle, through the
#: collateral it posts. Smaller than the PD betas: recovery moves less than
#: default does.
SECTOR_LGD_BETA: dict[str, float] = {
    s: round(0.30 * b, 4) for s, b in SECTOR_BETA.items()}

SUB_SECTORS: dict[str, tuple[str, ...]] = {
    "Construction": ("Civil Engineering", "Building Contracting",
                     "Specialist Trades"),
    "Real Estate": ("Commercial Leasing", "Residential Development"),
    "Manufacturing": ("Metals", "Food Processing", "Plastics"),
    "Wholesale Trade": ("Industrial Supplies", "Food Distribution"),
    "Transport": ("Road Freight", "Marine Logistics"),
    "Healthcare": ("Hospitals", "Clinics"),
    "Education": ("Schools", "Higher Education"),
    "Hospitality": ("Hotels", "Food Service"),
    "Utilities": ("Power", "Water"),
    "Petrochemicals": ("Basic Chemicals", "Refining"),
    "Retail Trade": ("Department Stores", "Speciality Retail"),
    "Professional Services": ("Engineering Consultancy", "Advisory"),
}

REGIONS: tuple[str, ...] = ("Riyadh", "Makkah", "Eastern Province", "Madinah",
                            "Asir", "Qassim", "Tabuk", "Hail")
TIERS: tuple[str, ...] = ("Strategic", "Core", "Standard")
PRODUCTS: tuple[str, ...] = ("Term Loan", "Revolving Credit Facility",
                             "Working Capital Line", "Project Finance",
                             "Trade Finance", "Guarantee Facility")
FACILITY_CLASS: dict[str, str] = {
    "Term Loan": "Funded", "Revolving Credit Facility": "Funded",
    "Working Capital Line": "Funded", "Project Finance": "Funded",
    "Trade Finance": "Contingent", "Guarantee Facility": "Contingent"}

#: Products with an undrawn commitment a CCF converts. A CCF stress applies
#: to these and to nothing else -- section 7.4's "correct populations such as
#: eligible undrawn facilities for CCF".
REVOLVING: frozenset[str] = frozenset({
    "Revolving Credit Facility", "Working Capital Line", "Trade Finance",
    "Guarantee Facility"})

COLLATERAL_TYPES: tuple[str, ...] = (
    "Commercial Property", "Residential Property", "Plant and Machinery",
    "Receivables", "Cash Deposit", "Corporate Guarantee")
COVENANT_TYPES: tuple[str, ...] = (
    "Net Debt / EBITDA", "Interest Cover", "DSCR", "Current Ratio")

#: The logit intercept the book's PD level is set by, and how hard the cycle
#: moves it. `CYCLE_TO_LOGIT` is the true coefficient a sensitivity fitter is
#: trying to recover, before sector scaling.
BASE_LOGIT = -4.05
CYCLE_TO_LOGIT = 0.62
QUALITY_TO_LOGIT = 1.55

#: LGD's own level and response, as a fraction.
BASE_LGD = 0.41
LGD_CYCLE = 0.085

#: Overlays. Held on the sectors a credit committee would hold them on, and
#: FIXED under a parameter stress unless the scenario says otherwise.
OVERLAY_SECTORS: frozenset[str] = frozenset({"Construction", "Real Estate",
                                             "Hospitality"})
OVERLAY_RATE = 0.06

MODEL_VERSION = ref.VERSION


def _logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _grade_for(pd_value: float) -> str:
    """The published grade whose masterscale PD is nearest, from below.

    A rating is the scale's verdict on a PD, not a relabelling of it, so the
    mapping is the scale's own boundaries rather than a continuous inverse.
    """
    for grade in RATINGS:
        if pd_value <= GRADE_PD[grade] * 1.35:
            return grade
    return "CCC"


def _notches(earlier: str, later: str) -> int:
    """How many grades apart two ratings are, positive for a downgrade."""
    return SCALE.index(later) - SCALE.index(earlier)


def obligors(rng: random.Random) -> list[dict[str, Any]]:
    """The book's borrowers, with the properties their risk is generated from."""
    out: list[dict[str, Any]] = []
    for index in range(CORPORATE_BORROWERS):
        borrower_id = f"WCB{index + 1:05d}"
        sector = SECTORS[index % len(SECTORS)]
        subs = SUB_SECTORS[sector]
        out.append({
            "borrower_id": borrower_id,
            "borrower_name": f"{sector.split()[0]} Holding {index + 1:04d}",
            "group_id": f"WCG{stable(borrower_id + '|group', 400) + 100:04d}",
            "group_name": f"Group {stable(borrower_id + '|group', 400) + 100}",
            "sector": sector,
            "sub_sector": subs[stable(borrower_id + "|sub", len(subs))],
            "region": REGIONS[stable(borrower_id + "|region", len(REGIONS))],
            "relationship_tier": TIERS[index % len(TIERS)],
            # Credit quality: 0 is the strongest name in the book, 1 the
            # weakest. Fixed for the borrower and constant through the
            # window, so a rating move is the cycle's doing rather than the
            # borrower quietly becoming a different company.
            "quality": rng.uniform(0.0, 1.0),
            "base_revenue": round(rng.uniform(220.0, 4200.0), 1),
            "base_margin": rng.uniform(0.08, 0.30),
            "origination_rating": RATINGS[stable(
                borrower_id + "|orig", len(RATINGS))],
            "eir": round(0.045 + 0.035 * rng.random(), 4),
        })
    return out


def facilities_of(borrowers: list[dict[str, Any]],
                  rng: random.Random) -> list[dict[str, Any]]:
    """Two or three exposures per borrower, so the book is a book of
    exposures."""
    out: list[dict[str, Any]] = []
    for borrower in borrowers:
        count = 2 + stable(borrower["borrower_id"] + "|count", 2)
        for slot in range(count):
            facility_id = f"{borrower['borrower_id']}F{slot + 1}"
            product = PRODUCTS[stable(facility_id + "|product",
                                      len(PRODUCTS))]
            limit = round(rng.uniform(4.0, 260.0), 3)
            out.append({
                "facility_id": facility_id,
                "borrower_id": borrower["borrower_id"],
                "product_type": product,
                "facility_class": FACILITY_CLASS[product],
                "limit": limit,
                "revolving": product in REVOLVING,
                "base_utilisation": 0.34 + 0.55 * unit_interval(
                    facility_id + "|util"),
                "ccf": round(0.20 + 0.55 * unit_interval(facility_id + "|ccf"),
                             4),
                "maturity_months": 24 + stable(facility_id + "|mat", 97),
                "collateral_cover": 0.15 + 1.25 * unit_interval(
                    facility_id + "|cover"),
                "collateral_type": COLLATERAL_TYPES[stable(
                    facility_id + "|coll", len(COLLATERAL_TYPES))],
                "origination_quarter": "",
            })
    return out


def _risk_for(borrower: dict[str, Any], facility: dict[str, Any],
              quarter: str, *, driver: float, property_driver: float,
              scenario: str) -> dict[str, float]:
    """One exposure's PD, LGD and arrears in one quarter under one scenario.

    The logit link is the point: PD responds to the cycle multiplicatively in
    odds and stays inside (0, 1) without clipping, which is what section 7.2's
    preferred specification assumes when it fits a change in `logit(PD)`.
    """
    beta = SECTOR_BETA[borrower["sector"]]
    idiosyncratic = signed(f"{facility['facility_id']}|{quarter}|pd") * 0.22
    logit = (BASE_LOGIT
             + QUALITY_TO_LOGIT * (borrower["quality"] - 0.5) * 2.0
             + CYCLE_TO_LOGIT * beta * driver
             + idiosyncratic)
    pd_12m = _clamp(_logistic(logit), 0.0002, 0.55)

    lgd = _clamp(
        BASE_LGD
        + LGD_CYCLE * SECTOR_LGD_BETA[borrower["sector"]] * property_driver
        - 0.16 * min(facility["collateral_cover"], 1.2)
        + signed(f"{facility['facility_id']}|{quarter}|lgd") * 0.05,
        0.08, 0.88)

    # Arrears follow the same conditions, with their own threshold. A book
    # where stage moved independently of PD would make every stage rule in
    # section 8 untestable.
    pressure = (pd_12m * 9.0
                + 0.30 * max(driver, 0.0)
                + unit_interval(f"{facility['facility_id']}|{quarter}|dpd")
                * 0.5)
    if pressure > 1.55:
        dpd = 90 + stable(f"{facility['facility_id']}|{quarter}|d3", 210)
    elif pressure > 1.05:
        dpd = 31 + stable(f"{facility['facility_id']}|{quarter}|d2", 58)
    elif pressure > 0.80:
        dpd = 1 + stable(f"{facility['facility_id']}|{quarter}|d1", 29)
    else:
        dpd = 0
    return {"pd_12m": pd_12m, "lgd": lgd, "dpd": float(dpd),
            "scenario": scenario}


def pending_artifact_rows(stamp: dict[str, Any], period: str, *,
                          sensitivity: bool) -> list[dict[str, Any]]:
    """One honest row for an artifact this build did not fit.

    A release has to carry every relation its schema declares, and the
    sensitivity and model-card relations are filled by steps that come after
    the data exists. When a build runs without them, the relation says so in
    a row a reader can see -- `readiness = INSUFFICIENT_HISTORY` or
    `validated = NOT_APPLICABLE` with a sentence -- rather than being empty,
    which reads as "no effect" rather than "not built".

    `scripts/whatif/seed_candidate.py` runs the whole pipeline in one process
    and replaces these before publishing, so a published candidate release
    normally carries real artifacts. This is what the honest alternative
    looks like when it does not.
    """
    if sensitivity:
        return [{
            **stamp, "artifact_id": "not-fitted", "artifact_version": "0",
            "reporting_quarter": period, "parameter": "pd_pit_12m",
            "factor_id": "MEV03", "lag": 0, "transformation": "",
            "coefficient": 0.0, "native_derivative": 0.0,
            "native_derivative_unit": "", "reference_parameter_value": 0.0,
            "reference_factor_value": 0.0, "standardised_response": 0.0,
            "std_error": 0.0, "ci_low": 0.0, "ci_high": 0.0,
            "sign_stability": 0.0, "training_periods": 0,
            "validation_periods": 0, "train_start": "", "train_end": "",
            "effective_df": 0.0, "max_df_allowed": 0.0, "collinearity": 0.0,
            "fit_error": 0.0, "validation_error": 0.0,
            "readiness": "INSUFFICIENT_HISTORY",
            "limitation": ("This build published the book without fitting "
                           "sensitivities. Nothing here is an estimate; run "
                           "scripts/whatif/seed_candidate.py to produce the "
                           "artifact."),
            "support_low": 0.0, "support_high": 0.0, "method": "none",
            "source_release_id": "", "source_fingerprint": ""}]
    return [{
        **stamp, "model_id": "not-trained", "model_version": "0",
        "reporting_quarter": period, "component": "blend", "split": "none",
        "group_dimension": "overall", "group_value": "all",
        "metric_name": "status", "metric_value": 0.0, "observations": 0,
        "validated": "NOT_APPLICABLE",
        "note": ("No emulator was trained in this build, so Method 2 reports "
                 "MODEL_NOT_READY. A zero here is the absence of a model, "
                 "not a measured error of zero.")}]


def build(release_id: str = "", tenant_id: str = lake.DEFAULT_TENANT,
          artifacts: dict[str, Any] | None = None) -> lake.Build:
    """The Corporate candidate release, in memory.

    `artifacts` supplies the fitted sensitivity and model-card frames when the
    caller has them. Without it the two relations carry the honest
    not-yet-built rows above rather than being absent, because a relation a
    release declares and does not publish is a release that will not open.
    """
    import pandas as pd

    from backend.cockpit_v4.scenario import candidate_schema as cs

    release_id = release_id or cs.RELEASES[dom.CORPORATE]
    quarters = quarter_range()
    rng = random.Random(CORPORATE_SEED)
    borrowers = obligors(rng)
    facilities = facilities_of(borrowers, rng)
    by_borrower = {b["borrower_id"]: b for b in borrowers}

    drivers = {s: mv.driver_index(dom.CORPORATE, quarters, s)
               for s, _n, _w in SCENARIOS}
    property_index = {
        s: mv.series(dom.CORPORATE, "MEV10", quarters, s)
        for s, _n, _w in SCENARIOS}
    weights = {s: w for s, _n, w in SCENARIOS}
    profile = ref.profile("corporate")

    gov = {"tenant_id": tenant_id, "dataset_release_id": release_id,
           "domain_id": dom.CORPORATE, "reporting_currency": "SAR"}
    stamp = dict(gov, origin=ORIGIN)

    borrower_rows: list[dict[str, Any]] = []
    facility_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    covenant_rows: list[dict[str, Any]] = []
    ifrs9_rows: list[dict[str, Any]] = []
    term_rows: list[dict[str, Any]] = []

    ratings_so_far: dict[str, list[str]] = {}
    stage_run: dict[str, int] = {}

    for index, quarter in enumerate(quarters):
        # LAGGED. A default this quarter follows conditions last quarter, and
        # a book where it followed this quarter's would let a fitter find its
        # relationship at lag zero -- which is not how credit works and would
        # make section 7.2's lag selection a formality.
        previous = quarters[max(index - 1, 0)]
        driver = {s: drivers[s][previous] for s in drivers}
        prop = {s: (property_index[s][previous] - 104.0) / 11.0
                for s in property_index}

        for borrower in borrowers:
            own = [f for f in facilities
                   if f["borrower_id"] == borrower["borrower_id"]]
            baseline = _risk_for(borrower, own[0], quarter,
                                 driver=driver["baseline"],
                                 property_driver=prop["baseline"],
                                 scenario="baseline")
            grade = _grade_for(baseline["pd_12m"])
            history = ratings_so_far.setdefault(
                borrower["borrower_id"], [borrower["origination_rating"]])
            previous_grade = history[-1]
            history.append(grade)
            moved = _notches(previous_grade, grade)
            revenue = round(borrower["base_revenue"]
                            * (1.0 - 0.06 * driver["baseline"]), 3)
            ebitda = round(revenue * borrower["base_margin"], 3)
            debt = round(revenue * (0.7 + 0.9 * borrower["quality"]), 3)
            cash = round(debt * 0.12, 3)
            borrower_rows.append({
                **gov,
                "borrower_id": borrower["borrower_id"],
                "borrower_name": borrower["borrower_name"],
                "group_id": borrower["group_id"],
                "group_name": borrower["group_name"],
                "reporting_quarter": quarter,
                "sector": borrower["sector"],
                "sub_sector": borrower["sub_sector"],
                "region": borrower["region"],
                "relationship_tier": borrower["relationship_tier"],
                "rating_current": grade,
                "rating_previous": previous_grade,
                "rating_at_origination": borrower["origination_rating"],
                "rating_notches_moved": int(moved),
                "rating_notches_from_origination": int(
                    _notches(borrower["origination_rating"], grade)),
                "rating_migration": ("Downgrade" if moved > 0
                                     else "Upgrade" if moved < 0
                                     else "Stable"),
                "rating_outlook": ("Negative" if driver["baseline"] > 0.4
                                   else "Positive" if driver["baseline"] < -0.4
                                   else "Stable"),
                "rating_driver": ("Macroeconomic conditions" if abs(moved)
                                  else "No change"),
                "pd_ttc_12m": round(GRADE_PD[grade], 6),
                "revenue_sar_mn": revenue,
                "ebitda_sar_mn": ebitda,
                "ebit_sar_mn": round(ebitda * 0.78, 3),
                "operating_cash_flow_sar_mn": round(ebitda * 0.82, 3),
                "total_debt_sar_mn": debt,
                "cash_sar_mn": cash,
                "net_debt_sar_mn": round(debt - cash, 3),
                "leverage_x": round(debt / max(ebitda, 0.5), 3),
                "dscr_x": round(max(ebitda / max(debt * 0.18, 0.2), 0.05), 3),
                "interest_cover_x": round(
                    max(ebitda / max(debt * 0.055, 0.1), 0.05), 3),
                "current_ratio_x": round(1.05 + 0.9 * (1 - borrower["quality"]),
                                         3),
                "quick_ratio_x": round(0.75 + 0.7 * (1 - borrower["quality"]),
                                       3),
                "ebitda_margin_pct": round(borrower["base_margin"] * 100, 3),
                "return_on_assets_pct": round(
                    max(0.2, 9.0 - 6.0 * borrower["quality"]
                        - 1.4 * driver["baseline"]), 3),
                "cash_conversion_pct": round(
                    _clamp(82.0 - 9.0 * driver["baseline"], 5.0, 130.0), 3),
                "qualitative_score": round(
                    _clamp(78.0 - 26.0 * borrower["quality"]
                           - 7.0 * driver["baseline"], 5.0, 99.0), 2),
                "watchlist_flag": int(grade in ("B", "CCC")),
                "watchlist_reason": ("Rating below policy floor"
                                     if grade in ("B", "CCC") else ""),
                "restructured_flag": int(
                    grade == "CCC" and moved > 0),
                "quarters_on_watchlist": int(whole_total(
                    1 for g in history if g in ("B", "CCC"))),
            })

        for facility in facilities:
            borrower = by_borrower[facility["borrower_id"]]
            per_scenario_risk = {
                s: _risk_for(borrower, facility, quarter,
                             driver=driver[s], property_driver=prop[s],
                             scenario=s)
                for s, _n, _w in SCENARIOS}
            base = per_scenario_risk["baseline"]

            utilisation = _clamp(
                facility["base_utilisation"] + 0.08 * driver["baseline"],
                0.05, 1.0)
            limit = facility["limit"]
            drawn = round(limit * utilisation, 4)
            undrawn = round(limit - drawn, 4)
            ccf = facility["ccf"] if facility["revolving"] else 0.0
            ead = round(drawn + ccf * undrawn, 4)

            dpd = int(base["dpd"])
            defaulted = dpd >= 90
            sicr = dpd >= 30 or base["pd_12m"] > 0.09
            stage = 3 if defaulted else (2 if sicr else 1)
            run = stage_run.get(facility["facility_id"] + str(stage), 0) + 1
            stage_run[facility["facility_id"] + str(stage)] = run

            per_scenario_buckets = {
                s: ref.term_structure(
                    pd_12m=per_scenario_risk[s]["pd_12m"],
                    lgd=per_scenario_risk[s]["lgd"],
                    ead=ead, eir=borrower["eir"],
                    remaining_maturity_months=float(
                        facility["maturity_months"]),
                    defaulted=defaulted, **profile)
                for s, _n, _w in SCENARIOS}

            overlay = round(
                OVERLAY_RATE * ead * 0.01
                if borrower["sector"] in OVERLAY_SECTORS else 0.0, 6)
            measured = ref.measure(per_scenario=per_scenario_buckets,
                                   weights=weights, stage=stage,
                                   overlay=overlay)
            # The accepted relation's contract: the recognised figure is the
            # stage-selected one, and `invariants._domain_specific` checks it.
            # The overlay rides on both so that the identity holds whichever
            # figure a stage selects.
            ecl_12m = round(measured.ecl_12m + overlay, 6)
            ecl_life = round(measured.ecl_lifetime + overlay, 6)
            ecl = ecl_12m if stage == 1 else ecl_life

            write_off = round(ead * 0.22, 4) if defaulted and dpd > 240 else 0.0
            recovery = round(write_off * 0.28, 4)

            facility_rows.append({
                **gov,
                "facility_id": facility["facility_id"],
                "borrower_id": borrower["borrower_id"],
                "borrower_name": borrower["borrower_name"],
                "reporting_quarter": quarter,
                "product_type": facility["product_type"],
                "facility_class": facility["facility_class"],
                "sector": borrower["sector"],
                "sub_sector": borrower["sub_sector"],
                "region": borrower["region"],
                "relationship_tier": borrower["relationship_tier"],
                "limit_sar_mn": limit,
                "drawn_sar_mn": drawn,
                "undrawn_sar_mn": undrawn,
                "utilisation_pct": round(utilisation * 100, 4),
                "ead_sar_mn": ead,
                "stage": stage,
                "sicr_flag": int(sicr),
                "default_flag": int(defaulted),
                "dpd_days": dpd,
                "pd_pit_12m": round(1.0 if defaulted else base["pd_12m"], 6),
                "pd_lifetime": round(
                    1.0 if defaulted
                    else _clamp(base["pd_12m"] * 2.6, base["pd_12m"], 0.97), 6),
                "lgd_pct": round(base["lgd"] * 100, 4),
                "ecl_12m_sar_mn": ecl_12m,
                "ecl_lifetime_sar_mn": ecl_life,
                "ecl_sar_mn": ecl,
                "ecl_coverage_pct": round(ecl / max(ead, 0.01) * 100, 4),
                "write_off_sar_mn": write_off,
                "recovery_sar_mn": recovery,
                "cure_flag": int(stage == 1 and dpd == 0 and run > 2),
                "past_due_flag": int(dpd > 0),
                "quarters_in_stage": int(run),
                "origination_quarter": quarters[0],
            })

            denominator = max(ead, 0.000001)
            ifrs9_rows.append({
                **stamp,
                "facility_id": facility["facility_id"],
                "reporting_quarter": quarter,
                "ecl_modelled_sar_mn": round(measured.ecl_recognised, 6),
                "ecl_overlay_sar_mn": overlay,
                "overlay_reason": (
                    "Sector overlay held by the credit committee"
                    if overlay else ""),
                "ecl_denominator": "ead_sar_mn",
                "ecl_rate": round(min(ecl / denominator, 1.0), 8),
                "effective_interest_rate": borrower["eir"],
                "remaining_maturity_months": float(
                    facility["maturity_months"]),
                "lifetime_horizon_months": float(sum(ref.CORPORATE_BUCKETS)),
                "ifrs9_model_version": MODEL_VERSION,
                "ccf_pit": round(ccf, 4),
                "ccf_eligible_flag": int(facility["revolving"]
                                         and undrawn > 0),
                "undrawn_eligible_sar_mn": round(
                    undrawn if facility["revolving"] else 0.0, 4),
            })

            for scenario_id, scenario_name, weight in SCENARIOS:
                for bucket in per_scenario_buckets[scenario_id]:
                    term_rows.append({
                        **stamp,
                        "facility_id": facility["facility_id"],
                        "reporting_quarter": quarter,
                        "scenario_id": scenario_id,
                        "scenario_name": scenario_name,
                        "scenario_weight": weight,
                        "horizon_index": bucket.index,
                        "horizon_end_period": quarters[min(
                            index + int(bucket.end_month // 3), len(quarters)
                            - 1)],
                        "horizon_months": round(bucket.months, 4),
                        "pd_marginal": round(bucket.pd_marginal, 8),
                        "pd_cumulative": round(bucket.pd_cumulative, 8),
                        "survival": round(bucket.survival, 8),
                        "lgd": round(bucket.lgd, 6),
                        "ead_sar_mn": round(bucket.ead, 6),
                        "discount_factor": round(bucket.discount_factor, 8),
                        "expected_shortfall_sar_mn": round(
                            bucket.expected_shortfall, 8),
                    })

            cover = _clamp(facility["collateral_cover"], 0.0, 2.4)
            market = round(ead * cover * 1.18, 4)
            haircut = 12.0 + 22.0 * unit_interval(
                facility["facility_id"] + "|hair")
            allocated = round(market * (1 - haircut / 100), 4)
            collateral_rows.append({
                **gov,
                "collateral_id": f"{facility['facility_id']}C",
                "facility_id": facility["facility_id"],
                "borrower_id": borrower["borrower_id"],
                "reporting_quarter": quarter,
                "collateral_type": facility["collateral_type"],
                "sector": borrower["sector"],
                "market_value_sar_mn": market,
                "haircut_pct": round(haircut, 4),
                "allocated_value_sar_mn": allocated,
                "coverage_pct": round(allocated / max(ead, 0.01) * 100, 4),
                "ltv_pct": round(ead / max(market, 0.01) * 100, 4),
                "valuation_age_quarters": int(
                    stable(f"{facility['facility_id']}|{quarter}|age", 8)),
            })

            covenant_type = COVENANT_TYPES[stable(
                facility["facility_id"] + "|cov", len(COVENANT_TYPES))]
            threshold = {"Net Debt / EBITDA": 3.5, "Interest Cover": 2.5,
                         "DSCR": 1.25, "Current Ratio": 1.1}[covenant_type]
            observed = round(
                threshold * (1.18 - 0.30 * borrower["quality"]
                             - 0.12 * driver["baseline"]), 4)
            breached = observed < threshold if covenant_type != (
                "Net Debt / EBITDA") else observed > threshold
            covenant_rows.append({
                **gov,
                "covenant_id": f"{facility['facility_id']}V",
                "facility_id": facility["facility_id"],
                "borrower_id": borrower["borrower_id"],
                "reporting_quarter": quarter,
                "sector": borrower["sector"],
                "covenant_type": covenant_type,
                "threshold_value": threshold,
                "observed_value": observed,
                "headroom_pct": round(
                    (observed - threshold) / threshold * 100, 4),
                "test_status": "Breached" if breached else "Passed",
                "breach_flag": int(breached),
                "waiver_flag": int(breached and stable(
                    f"{facility['facility_id']}|{quarter}|w", 3) == 0),
                "waiver_status": ("Granted" if breached and stable(
                    f"{facility['facility_id']}|{quarter}|w", 3) == 0
                    else "None"),
                "waiver_quarter": (quarter if breached and stable(
                    f"{facility['facility_id']}|{quarter}|w", 3) == 0
                    else ""),
                "consecutive_breaches": int(breached),
            })

    latest = quarters[-1]
    macro_rows = [
        {**stamp, "factor_id": r["factor_id"],
         "reporting_quarter": r["period"], "scenario_id": r["scenario_id"],
         "country_or_region": r["country_or_region"], "value": r["value"],
         "native_unit": r["native_unit"],
         "native_frequency": r["native_frequency"],
         "aggregation_rule": r["aggregation_rule"],
         "observation_status": r["observation_status"],
         "forecast_vintage": r["forecast_vintage"],
         "published_at": r["published_at"], "available_at": r["available_at"]}
        for r in mv.panel(dom.CORPORATE, quarters)]

    registry_rows = [{**stamp, "reporting_quarter": latest, **r}
                     for r in mv.registry(dom.CORPORATE)]

    rating_rows = [
        {**stamp, "mapping_version": RATING_MAPPING_VERSION,
         "rating_grade": grade, "reporting_quarter": latest,
         "grade_rank": rank + 1, "pd_12m": round(GRADE_PD[grade], 6),
         "pd_lifetime": round(min(GRADE_PD[grade] * 2.6, 1.0), 6),
         "horizon_months": 12.0,
         "is_default_grade": int(grade == DEFAULT_GRADE),
         "is_investment_grade": int(grade in INVESTMENT_GRADE),
         "effective_from": quarters[0], "effective_to": "",
         "source": "Generated masterscale published with this release."}
        for rank, grade in enumerate(SCALE)]

    frames = {
        "corp_borrower_quarter": pd.DataFrame(borrower_rows),
        "corp_facility_quarter": pd.DataFrame(facility_rows),
        "corp_collateral_quarter": pd.DataFrame(collateral_rows),
        "corp_covenant_quarter": pd.DataFrame(covenant_rows),
        "whatif_corp_macro_quarter": pd.DataFrame(macro_rows),
        "whatif_corp_mev_registry": pd.DataFrame(registry_rows),
        "whatif_corp_rating_map": pd.DataFrame(rating_rows),
        "whatif_corp_term_structure": pd.DataFrame(term_rows),
        "whatif_corp_ifrs9": pd.DataFrame(ifrs9_rows),
    }
    supplied = artifacts or {}
    frames["whatif_corp_sensitivity"] = supplied.get(
        "whatif_corp_sensitivity",
        pd.DataFrame(pending_artifact_rows(stamp, latest, sensitivity=True)))
    frames["whatif_corp_model_metric"] = supplied.get(
        "whatif_corp_model_metric",
        pd.DataFrame(pending_artifact_rows(stamp, latest, sensitivity=False)))
    present, absent = mv.factor_count(dom.CORPORATE)
    return lake.Build(
        domain_id=dom.CORPORATE, release_id=release_id, periods=quarters,
        frames=frames,
        counts={"borrowers": len(borrowers), "facilities": len(facilities),
                "groups": len({b["group_name"] for b in borrowers}),
                "sectors": len(SECTORS), "sub_sectors": whole_total(
                    len(v) for v in SUB_SECTORS.values()),
                "product_types": len(PRODUCTS), "regions": len(REGIONS),
                "macro_factors_present": present,
                "macro_factors_absent": absent,
                "economic_scenarios": len(SCENARIOS)},
        notes={
            "origin": ORIGIN,
            "not_a_bank_engine": (
                "ECL here is measured by reference_ecl.py, a calculator "
                "written for this demonstration. It is not a bank engine and "
                "its output is not an accounting figure."),
            "macro_is_generated": (
                "The macroeconomic panel is generated, not observed. It is "
                "not economic history."),
            "rating_scale": list(SCALE),
            "sector_pd_betas": dict(SECTOR_BETA),
            "true_cycle_coefficient": CYCLE_TO_LOGIT,
            "ecl_denominator": "ead_sar_mn",
            "reference_calculator": MODEL_VERSION,
            "scenario_weights": {s: w for s, _n, w in SCENARIOS},
            "total_ecl_sar_mn": round(exact_total(
                r["ecl_sar_mn"] for r in facility_rows), 4),
        })


__all__ = ["BASE_LGD", "BASE_LOGIT", "COLLATERAL_TYPES", "CYCLE_TO_LOGIT",
           "DEFAULT_GRADE", "GRADE_PD", "INVESTMENT_GRADE", "PRODUCTS",
           "RATINGS", "RATING_MAPPING_VERSION", "REVOLVING", "SCALE",
           "SECTORS", "SECTOR_BETA", "SECTOR_LGD_BETA", "build",
           "facilities_of", "obligors"]
