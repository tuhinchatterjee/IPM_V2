"""
The climate stressed-PD calculation engine.

Pure and deterministic: `calculate(model)` takes a fully resolved input dict and
returns a complete result dict. No database, no UI, no globals, no I/O — which is
what makes it testable to Excel parity and safe to run once per request.

Dependency order of the seven steps (this is also the order they appear below):

  1  derived intensities      sector emissions / denominator
  2  k calibration            k = push_EU / g(cost_ratio_EU, theta)
  3  transition cost ratio    price x deflator x intensity x (1 - pass-through)
  4  physical cost ratio      AAL x severity x normalised exposure x retained x P&L share
  5  push                     k x g(transition + physical)      <- added INSIDE g()
  6  macro shift              beta x GDP LEVEL deviation x macro_beta
  7  the grid                 N( N-1(PD_0) + push + macro_shift )

Three invariants the code deliberately protects, each of which the workbook got
wrong at least once before fixing:

  * The two cost ratios are summed BEFORE the transform, never pushed separately.
    g is concave, so two separate pushes understate facing both shocks at once.
  * k is a function of theta and is refitted whenever theta moves. It is never a
    stored constant.
  * The macro leg consumes a GDP LEVEL deviation, never a growth rate.
"""

import math

from backend.climate.normal import norm_cdf, norm_ppf

ENGINE_VERSION = "1.0.0"

# Below this, the generalised power transform is evaluated as its log limit.
THETA_EPS = 1e-12

THETA_FORMS = [(1.0, "linear"), (0.5, "near-linear"), (0.0, "log (v4/v5 default)"),
               (-0.5, "concave"), (-1.0, "saturating")]


# ------------------------------------------------------------ transform helpers

def g(x: float, theta: float) -> float:
    """The generalised push transform g(x, theta) = ((1+x)^theta - 1) / theta.

    theta = +1 is linear, theta = 0 is the logarithmic form (the default carried
    from v4), theta = -1 is saturating. The log branch is the analytic limit, not
    an approximation, so the family is continuous through theta = 0.

    Evaluated as expm1(theta * log1p(x)) / theta rather than by literally raising
    to a power and subtracting one. The two are identical in exact arithmetic, but
    the literal form loses most of its significant digits for small theta: at
    theta = 1e-9 the power is 1 + O(1e-12), so subtracting 1 discards twelve digits
    before the division ever happens. The workbook has the same weakness; it simply
    never exercised a theta between its 1e-12 guard and about 1e-6.
    """
    if abs(theta) < THETA_EPS:
        return math.log1p(x)
    return math.expm1(theta * math.log1p(x)) / theta


def g_inverse_argument(y: float, x_ref: float, theta: float) -> float:
    """Invert g to the intensity multiple implied by a push ratio y.

    Used only for calibration diagnostics: given that a group's push is y times
    the median firm's, what emission-intensity multiple would reproduce it?
    Returns None where the saturating form cannot reach y at any intensity.
    """
    g_ref = g(x_ref, theta)
    if x_ref <= 0:
        return None
    if abs(theta) < THETA_EPS:
        return (math.exp(g_ref * y) - 1.0) / x_ref
    base = 1.0 + theta * g_ref * y
    if base <= 0:
        return None
    return (base ** (1.0 / theta) - 1.0) / x_ref


# ------------------------------------------------------------- small statistics
# Sample (n-1) moments, matching Excel's STDEV / CORREL / SLOPE / INTERCEPT / RSQ.

def _mean(xs):
    return sum(xs) / len(xs)


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _correl(ys, xs):
    my, mx = _mean(ys), _mean(xs)
    sxy = sum((y - my) * (x - mx) for y, x in zip(ys, xs, strict=True))
    syy = sum((y - my) ** 2 for y in ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if syy <= 0 or sxx <= 0:
        return 0.0
    return sxy / math.sqrt(syy * sxx)


def _slope_intercept(ys, xs):
    my, mx = _mean(ys), _mean(xs)
    sxy = sum((y - my) * (x - mx) for y, x in zip(ys, xs, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return 0.0, my
    slope = sxy / sxx
    return slope, my - slope * mx


# ------------------------------------------------------------- step 1: intensity

def _resolve_emissions(model):
    """Allocate EDGAR source categories onto the lending taxonomy.

    The plug row (mt=None) absorbs the national total less every stated category,
    so the reconciliation holds by construction. The Households column is carried
    through but excluded from every corporate intensity — it removes roughly 18%
    of national emissions that belong to private vehicles and residential energy,
    not to any borrower.
    """
    settings = model["settings"]
    sector_ids = [s["id"] for s in model["sectors"]]
    total = float(settings["national_total_ghg_mt"])

    stated = sum(float(c["mt"]) for c in model["edgar_categories"] if c.get("mt") is not None)
    categories = []
    for cat in model["edgar_categories"]:
        mt = total - stated if cat.get("mt") is None else float(cat["mt"])
        shares = {k: float(v) for k, v in cat["shares"].items()}
        categories.append({
            "code": cat["code"], "name": cat["name"], "definition": cat.get("definition", ""),
            "judgement": bool(cat.get("judgement")), "is_plug": cat.get("mt") is None,
            "mt": mt, "shares": shares, "share_sum": sum(shares.values()),
        })

    by_sector = {sid: sum(c["mt"] * c["shares"].get(sid, 0.0) for c in categories) for sid in sector_ids}
    households = sum(c["mt"] * c["shares"].get("HH", 0.0) for c in categories)
    allocated_total = sum(by_sector.values()) + households
    corporate = allocated_total - households

    return {
        "categories": categories,
        "by_sector": by_sector,
        "households_mt": households,
        "allocated_total_mt": allocated_total,
        "corporate_mt": corporate,
        "national_total_mt": total,
        "category_sum_mt": sum(c["mt"] for c in categories),
        "corporate_share": (corporate / allocated_total) if allocated_total else 0.0,
        "per_head": total / float(settings["population_m"]) if settings.get("population_m") else 0.0,
        "buildings_per_head": next(
            (c["mt"] / float(settings["population_m"]) for c in categories
             if c["name"].lower().startswith("building") and settings.get("population_m")), 0.0),
    }


def _resolve_sectors(model, emissions):
    settings = model["settings"]
    peg = float(settings["currency_peg"])
    basis = str(settings.get("denominator_basis", "GVA")).upper()
    total_gva_local = sum(float(s["gva_omr"]) for s in model["sectors"])

    sectors = []
    for s in model["sectors"]:
        gva_local = float(s["gva_omr"])
        gva_usd = gva_local * peg
        denominator = gva_usd * float(s.get("turnover_gva", 1.0)) if basis == "TURNOVER" else gva_usd
        mt = emissions["by_sector"][s["id"]]
        intensity = (mt * 1e6 / denominator) if denominator > 0 else 0.0
        sectors.append({
            "id": s["id"], "name": s["name"], "isic": s.get("isic", ""),
            "gva_local": gva_local, "gva_usd": gva_usd, "denominator_usd": denominator,
            "turnover_gva": float(s.get("turnover_gva", 1.0)),
            "gva_share": (gva_local / total_gva_local) if total_gva_local else 0.0,
            "emissions_mt": mt, "intensity": intensity,
            "pass_through": float(s["pass_through"]), "macro_beta": float(s.get("macro_beta", 1.0)),
            "rationale": s.get("rationale", ""),
        })

    denominator_total = sum(x["denominator_usd"] for x in sectors)
    return sectors, {
        "total_gva_local": total_gva_local,
        "total_gva_usd": total_gva_local * peg,
        "total_denominator_usd": denominator_total,
        "total_emissions_mt": sum(x["emissions_mt"] for x in sectors),
        "economy_intensity": (sum(x["emissions_mt"] for x in sectors) * 1e6 / denominator_total)
                             if denominator_total else 0.0,
        "basis": basis,
    }


# ---------------------------------------------------------- step 2: calibration

def _calibrate(model, theta, max_cost_ratio=None):
    """Fit k on the ECB anchor at the current theta, and run the calibration
    diagnostics: the second-anchor validation, the coal out-of-sample rejection,
    the k sensitivity grid and the theta band.

    `max_cost_ratio` is fed back in on a second pass once the Oman cost ratios are
    known, so the extrapolation multiple and the theta band can be reported. The
    fitted k itself never depends on it.
    """
    cal = model["calibration"]
    basis = str(model["settings"].get("denominator_basis", "GVA")).upper()

    r1 = cal["route1"]
    route1_intensity = (float(r1["eu_total_ghg_mt"]) * (1.0 - float(r1["household_share"])) * 1000.0
                        / float(r1["eu_gva_eur_bn"]))
    route1_median = route1_intensity * float(r1["median_to_average"])

    r2 = cal["route2"]
    route2 = float(r2["median_total_intensity"]) * float(r2["scope1_share"])
    if basis != "TURNOVER":
        route2 *= float(r2["turnover_gva_ratio"])

    eu_intensity = route1_median if int(cal.get("route_in_use", 1)) == 1 else route2

    baseline_pd = float(cal["baseline_pd"])
    anchor_rel = float(cal["anchor_a_rel"] if cal.get("anchor_in_use", "A") == "A" else cal["anchor_b_rel"])
    stressed_pd = baseline_pd * (1.0 + anchor_rel)
    push_eu = norm_ppf(stressed_pd) - norm_ppf(baseline_pd)

    price_eur = float(cal["anchor_price_usd"]) * float(cal["usd_eur"])
    pt = float(cal["eu_pass_through"])
    cost_ratio_eu = price_eur * eu_intensity * (1.0 - pt) / 1e6

    g_anchor = g(cost_ratio_eu, theta)
    k = push_eu / g_anchor if g_anchor != 0 else 0.0

    # Every anchor on a common basis, so the workbench can show what each identifies.
    anchors = []
    for a in cal["anchors"]:
        pd0, rel = float(a["baseline_pd"]), float(a["rel_change"])
        pd1 = pd0 * (1.0 + rel)
        anchors.append({**a, "stressed_pd": pd1, "push": norm_ppf(pd1) - norm_ppf(pd0)})

    fit = [a for a in anchors if a.get("use") == "FIT"]
    push_ratio_high = (fit[1]["push"] / fit[0]["push"]) if len(fit) >= 2 and fit[0]["push"] else 0.0
    implied_multiple = g_inverse_argument(push_ratio_high, cost_ratio_eu, theta) if push_ratio_high else None

    checks_ = [a for a in anchors if a.get("use") == "CHECK"]
    coal = None
    if checks_ and fit and fit[0]["push"]:
        ratio = checks_[0]["push"] / fit[0]["push"]
        required = g_inverse_argument(ratio, cost_ratio_eu, theta)
        plausible = float(cal.get("coal_plausible_intensity_multiple", 10.0))
        discrepancy = (required / plausible) if required else None
        if required is None:
            verdict = "REJECTED - form cannot reach the coal anchor at any intensity"
        elif discrepancy > 3:
            verdict = "REJECTED - coal response is not a Scope 1 cost response"
        else:
            verdict = "consistent"
        coal = {"push_ratio": ratio, "required_multiple": required, "plausible_multiple": plausible,
                "discrepancy": discrepancy, "verdict": verdict,
                "rejected": required is None or discrepancy > 3}

    k_sensitivity = []
    for intensity in cal.get("k_sensitivity_intensities", []):
        cr = price_eur * float(intensity) * (1.0 - pt) / 1e6
        gx = g(cr, theta)
        k_sensitivity.append({
            "intensity": float(intensity),
            "k_a": (norm_ppf(baseline_pd * (1 + float(cal["anchor_a_rel"]))) - norm_ppf(baseline_pd)) / gx,
            "k_b": (norm_ppf(baseline_pd * (1 + float(cal["anchor_b_rel"]))) - norm_ppf(baseline_pd)) / gx,
        })

    theta_band = []
    if max_cost_ratio is not None:
        ref_pd = baseline_pd
        forms = dict(THETA_FORMS)
        for t in cal.get("theta_band", [1.0, 0.5, 0.0, -0.5, -1.0]):
            t = float(t)
            gt = g(cost_ratio_eu, t)
            kt = fit[0]["push"] / gt if gt else 0.0
            push_max = kt * g(max_cost_ratio, t)
            pd_ref = norm_cdf(norm_ppf(ref_pd) + push_max)
            theta_band.append({
                "theta": t, "form": forms.get(t, ""), "k": kt,
                "implied_multiple": g_inverse_argument(push_ratio_high, cost_ratio_eu, t),
                "push_at_max": push_max, "pd_at_reference": pd_ref,
                "pd_multiple": pd_ref / ref_pd if ref_pd else 0.0,
            })

    extrapolation = None
    if max_cost_ratio is not None:
        extrapolation = {
            "calibration_cost_ratio": cost_ratio_eu,
            "max_cost_ratio": max_cost_ratio,
            "multiple": (max_cost_ratio / cost_ratio_eu) if cost_ratio_eu else 0.0,
        }

    return {
        "k": k, "theta": theta, "g_at_anchor": g_anchor,
        "push_eu": push_eu, "cost_ratio_eu": cost_ratio_eu,
        "baseline_pd": baseline_pd, "anchor_rel": anchor_rel, "anchor_stressed_pd": stressed_pd,
        "anchor_in_use": cal.get("anchor_in_use", "A"),
        "route_in_use": int(cal.get("route_in_use", 1)),
        "eu_intensity": eu_intensity,
        "route1_economy_intensity": route1_intensity, "route1_intensity": route1_median,
        "route2_intensity": route2,
        "anchor_price_eur": price_eur, "eu_pass_through": pt,
        "anchors": anchors,
        "push_ratio_high_median": push_ratio_high,
        "implied_intensity_multiple": implied_multiple,
        "coal": coal, "k_sensitivity": k_sensitivity, "theta_band": theta_band,
        "extrapolation": extrapolation,
    }


# ------------------------------------------------------------- step 4: physical

def _resolve_physical(model, sectors, scenarios):
    """Hazard baselines, the warming path, severity multipliers and the normalised
    exposure weights.

    Exposure weights are RELATIVE. Normalising by the GVA-weighted mean guarantees
    the national annual average loss is preserved exactly, so an error in the
    weights can misallocate risk between sectors but can never inflate or deflate
    system-wide risk.
    """
    settings = model["settings"]
    warming_today = float(settings["warming_today"])
    base_year, terminal = int(settings["base_year"]), int(settings.get("terminal_year", 2100))
    horizon = int(settings["horizon_year"])

    national_gva_usd = sum(s["gva_usd"] for s in sectors)
    window = float(settings.get("cyclone_observation_years", 18)) or 1.0
    observed = sum(float(e["damage_usd_m"]) for e in model.get("cyclone_events", []))
    event_aal_usd = observed / window
    event_aal_share = (event_aal_usd / national_gva_usd) if national_gva_usd else 0.0

    hazards = []
    for h in model["hazards"]:
        aal = event_aal_share if h.get("baseline_aal") is None else float(h["baseline_aal"])
        hazards.append({**h, "baseline_aal": aal, "derived_from_events": h.get("baseline_aal") is None})

    span = float(terminal - base_year) or 1.0
    warming = {}
    for sc in scenarios:
        at_horizon = warming_today + (float(sc["warming_2100"]) - warming_today) * (horizon - base_year) / span
        warming[sc["code"]] = {
            "warming_2100": float(sc["warming_2100"]),
            "at_horizon": at_horizon,
            "ratio": (at_horizon / warming_today) if warming_today else 1.0,
        }

    severity = {
        h["id"]: {sc["code"]: warming[sc["code"]]["ratio"] ** float(h["elasticity"]) for sc in scenarios}
        for h in hazards
    }

    raw = model["exposure_raw"]
    weighted_mean = {
        h["id"]: sum(s["gva_share"] * float(raw[s["id"]][h["id"]]) for s in sectors)
        for h in hazards
    }
    used = {
        s["id"]: {
            h["id"]: (float(raw[s["id"]][h["id"]]) / weighted_mean[h["id"]]) if weighted_mean[h["id"]] else 0.0
            for h in hazards
        }
        for s in sectors
    }
    normalised_mean = {
        h["id"]: sum(s["gva_share"] * used[s["id"]][h["id"]] for s in sectors) for h in hazards
    }

    cost = {}
    for s in sectors:
        cost[s["id"]] = {}
        for sc in scenarios:
            code = sc["code"]
            cost[s["id"]][code] = sum(
                h["baseline_aal"] * severity[h["id"]][code] * used[s["id"]][h["id"]]
                * (1.0 - float(h["insurance_recovery"])) * float(h["pnl_share"])
                for h in hazards
            )

    gva_weighted_cost = {
        sc["code"]: sum(s["gva_share"] * cost[s["id"]][sc["code"]] for s in sectors) for sc in scenarios
    }

    return {
        "hazards": hazards,
        "national_gva_usd_m": national_gva_usd,
        "observed_damage_usd_m": observed,
        "observation_years": window,
        "event_aal_usd_m": event_aal_usd,
        "event_aal_share": event_aal_share,
        "warming_today": warming_today,
        "warming": warming,
        "severity": severity,
        "raw_weighted_mean": weighted_mean,
        "normalised_weighted_mean": normalised_mean,
        "exposure_used": used,
        "cost": cost,
        "gva_weighted_cost": gva_weighted_cost,
        "capital_share_left_for_lgd": {h["id"]: 1.0 - float(h["pnl_share"]) for h in hazards},
    }


# ---------------------------------------------------------------- step 6: macro

def _resolve_macro(model, scenarios, horizon):
    """Estimate the macro leg live on the historical series, then apply the
    scenario GDP LEVEL deviation.

    Sign convention: beta is negative and a GDP deviation is negative, so the
    product is POSITIVE and raises the probit — i.e. raises PD. Feeding a growth
    rate here instead of a level deviation is the units trap that broke the
    original regression.
    """
    macro = model["macro"]
    obs = sorted(macro["observations"], key=lambda o: o["year"])

    series = []
    prev_probit = None
    for o in obs:
        probit = norm_ppf(float(o["npl_ratio"]))
        row = {"year": int(o["year"]), "npl_ratio": float(o["npl_ratio"]), "probit": probit,
               "d_probit": None if prev_probit is None else probit - prev_probit,
               "gdp_growth": float(o["gdp_growth"])}
        series.append(row)
        prev_probit = probit

    paired = [r for r in series if r["d_probit"] is not None]
    ys = [r["d_probit"] for r in paired]
    xs = [r["gdp_growth"] for r in paired]

    correlation = _correl(ys, xs) if len(paired) >= 2 else 0.0
    slope, intercept = _slope_intercept(ys, xs) if len(paired) >= 2 else (0.0, 0.0)
    sd_y, sd_x = _stdev(ys), _stdev(xs)
    r2 = correlation ** 2

    corr_in_use = float(macro.get("correlation_in_use", correlation))
    beta_in_use = corr_in_use * sd_y / sd_x if sd_x else 0.0

    by_scenario = {}
    for sc in scenarios:
        deviation_pct = float(sc["gdp_deviation"][horizon])
        fraction = deviation_pct / 100.0
        by_scenario[sc["code"]] = {
            "deviation_pct": deviation_pct,
            "deviation_fraction": fraction,
            "shift": beta_in_use * fraction,
            "sd_units": (fraction / sd_x) if sd_x else 0.0,
        }

    return {
        "series": series, "n_paired": len(paired),
        "correlation_estimated": correlation, "correlation_in_use": corr_in_use,
        "beta_ols": slope, "intercept": intercept, "r2": r2,
        "sd_d_probit": sd_y, "sd_gdp_growth": sd_x, "beta_in_use": beta_in_use,
        "selected_specification": macro.get("selected_specification", "S8"),
        "by_scenario": by_scenario,
    }


# ----------------------------------------------------------------------- driver

def _resolve_scenarios(model, horizon):
    """Copy the scenarios with the interpolated GDP deviation filled in.

    The workbook derives the mid horizon as the midpoint of its neighbours; that
    is reproduced here so editing the endpoints is enough.
    """
    horizons = sorted({int(y) for sc in model["scenarios"] for y in sc["carbon_price"]})
    out = []
    for sc in model["scenarios"]:
        prices = {int(y): float(v) for y, v in sc["carbon_price"].items()}
        dev = {int(y): float(v) for y, v in sc["gdp_deviation"].items()}
        if len(horizons) >= 3:
            lo, mid, hi = horizons[0], horizons[1], horizons[2]
            if lo in dev and hi in dev:
                dev[mid] = (dev[lo] + dev[hi]) / 2.0
        out.append({**sc, "carbon_price": prices, "gdp_deviation": dev})
    if horizon not in horizons:
        raise ValueError(f"horizon_year {horizon} is not one of the scenario horizons {horizons}")
    return out, horizons


def calculate(model: dict) -> dict:
    """Run the full model. Returns every intermediate quantity, not just the grid —
    the drill-down, the quality checks and the export pack all read from here."""
    settings = model["settings"]
    horizon = int(settings["horizon_year"])
    theta = float(settings["theta"])
    cap = float(settings["cost_ratio_cap"])
    deflator = float(settings["us_gdp_deflator"])

    scenarios, horizons = _resolve_scenarios(model, horizon)
    emissions = _resolve_emissions(model)
    sectors, totals = _resolve_sectors(model, emissions)
    physical = _resolve_physical(model, sectors, scenarios)
    macro = _resolve_macro(model, scenarios, horizon)

    # k first (it does not depend on the Oman cost ratios), then the cost ratios,
    # then a second calibration pass that reports the extrapolation range.
    calibration = _calibrate(model, theta)
    k = calibration["k"]

    scenario_context = {}
    for sc in scenarios:
        price = float(sc["carbon_price"][horizon])
        scenario_context[sc["code"]] = {
            "code": sc["code"], "name": sc["name"], "quadrant": sc.get("quadrant", ""),
            "carbon_price": price, "carbon_price_deflated": price * deflator,
            "intensity_index": float(sc.get("intensity_index", 1.0)),
            "denominator_index": float(sc.get("denominator_index", 1.0)),
            "warming_2100": float(sc["warming_2100"]),
            "warming_at_horizon": physical["warming"][sc["code"]]["at_horizon"],
            "gdp_deviation_pct": macro["by_scenario"][sc["code"]]["deviation_pct"],
            "macro_shift": macro["by_scenario"][sc["code"]]["shift"],
        }

    cells, by_cell = [], {}
    for s in sectors:
        for sc in scenarios:
            code = sc["code"]
            ctx = scenario_context[code]
            if s["intensity"] <= 0:
                transition = 0.0
            else:
                transition = (ctx["carbon_price_deflated"] * s["intensity"] * ctx["intensity_index"]
                              * (1.0 - s["pass_through"]) / (1e6 * ctx["denominator_index"]))
            phys = physical["cost"][s["id"]][code]
            uncapped = transition + phys
            total = min(uncapped, cap)

            push = k * g(total, theta)
            push_transition_only = k * g(transition, theta)
            push_physical = push - push_transition_only
            macro_shift = ctx["macro_shift"] * s["macro_beta"]

            cell = {
                "sector_id": s["id"], "sector": s["name"], "scenario": code,
                "scenario_name": sc["name"],
                "intensity": s["intensity"], "pass_through": s["pass_through"],
                "macro_beta": s["macro_beta"],
                "carbon_price": ctx["carbon_price"],
                "carbon_price_deflated": ctx["carbon_price_deflated"],
                "transition_cost": transition, "physical_cost": phys,
                "uncapped_cost": uncapped, "total_cost": total, "cap_binds": uncapped > total,
                "push": push, "push_transition": push_transition_only, "push_physical": push_physical,
                "physical_share": (push_physical / push) if push else 0.0,
                "macro_shift": macro_shift, "probit_shift": push + macro_shift,
            }
            cells.append(cell)
            by_cell[(s["id"], code)] = cell

    max_cost_ratio = max((c["total_cost"] for c in cells), default=0.0)
    calibration = _calibrate(model, theta, max_cost_ratio=max_cost_ratio)

    grades = [{"grade": rg["grade"], "baseline_pd": float(rg["baseline_pd"])}
              for rg in model["rating_grades"]]

    grid, by_grid = [], {}
    for s in sectors:
        for grade in grades:
            probit0 = norm_ppf(grade["baseline_pd"])
            for sc in scenarios:
                cell = by_cell[(s["id"], sc["code"])]
                stressed = norm_cdf(probit0 + cell["probit_shift"])
                row = {
                    "sector_id": s["id"], "sector": s["name"], "grade": grade["grade"],
                    "scenario": sc["code"], "scenario_name": sc["name"],
                    "baseline_pd": grade["baseline_pd"], "stressed_pd": stressed,
                    "multiple": stressed / grade["baseline_pd"] if grade["baseline_pd"] else 0.0,
                    "delta_bps": (stressed - grade["baseline_pd"]) * 10000.0,
                }
                grid.append(row)
                by_grid[(s["id"], grade["grade"], sc["code"])] = row

    reference_grade = settings.get("reference_grade") or grades[len(grades) // 2]["grade"]
    summary = []
    for s in sectors:
        row = {"sector_id": s["id"], "sector": s["name"], "intensity": s["intensity"],
               "pass_through": s["pass_through"], "gva_share": s["gva_share"], "multiples": {},
               "stressed_pd": {}, "transition_cost": {}, "physical_cost": {}, "push": {},
               "physical_share": {}}
        for sc in scenarios:
            code = sc["code"]
            cell = by_cell[(s["id"], code)]
            gr = by_grid[(s["id"], reference_grade, code)]
            row["multiples"][code] = gr["multiple"]
            row["stressed_pd"][code] = gr["stressed_pd"]
            row["transition_cost"][code] = cell["transition_cost"]
            row["physical_cost"][code] = cell["physical_cost"]
            row["push"][code] = cell["push"]
            row["physical_share"][code] = cell["physical_share"]
        summary.append(row)

    return {
        "engine_version": ENGINE_VERSION,
        "model_name": model.get("name", ""),
        "country": model.get("country", ""),
        "settings": dict(settings),
        "horizon_year": horizon, "horizons": horizons, "theta": theta,
        "cost_ratio_cap": cap, "us_gdp_deflator": deflator,
        "k": k,
        "reference_grade": reference_grade,
        "scenarios": [scenario_context[sc["code"]] for sc in scenarios],
        "scenario_codes": [sc["code"] for sc in scenarios],
        "sectors": sectors, "totals": totals,
        "emissions": emissions,
        "calibration": calibration,
        "physical": physical,
        "macro": macro,
        "grades": grades,
        "cells": cells, "by_cell": by_cell,
        "grid": grid, "by_grid": by_grid,
        "summary": summary,
        "max_cost_ratio": max_cost_ratio,
        "cap_binding_cells": sum(1 for c in cells if c["cap_binds"]),
    }


# -------------------------------------------------------------- worked example

def decompose(result: dict, sector_id: str, grade: str, scenario: str) -> dict:
    """The full waterfall behind one grid cell, in the order a validator reads it:
    price -> deflated -> intensity -> pass-through -> transition ratio -> plus
    physical ratio -> push -> plus macro -> probit shift -> stressed PD.

    This is the artefact that makes the model reviewable rather than merely
    plausible, so every step carries its own arithmetic in `detail`.
    """
    cell = result["by_cell"][(sector_id, scenario)]
    row = result["by_grid"][(sector_id, grade, scenario)]
    sector = next(s for s in result["sectors"] if s["id"] == sector_id)
    phys = result["physical"]
    theta, k = result["theta"], result["k"]

    hazard_rows = []
    for h in phys["hazards"]:
        contribution = (h["baseline_aal"] * phys["severity"][h["id"]][scenario]
                        * phys["exposure_used"][sector_id][h["id"]]
                        * (1.0 - float(h["insurance_recovery"])) * float(h["pnl_share"]))
        hazard_rows.append({
            "id": h["id"], "name": h["name"], "baseline_aal": h["baseline_aal"],
            "severity": phys["severity"][h["id"]][scenario],
            "exposure": phys["exposure_used"][sector_id][h["id"]],
            "insurance_recovery": float(h["insurance_recovery"]), "pnl_share": float(h["pnl_share"]),
            "contribution": contribution,
        })

    steps = [
        ("NGFS carbon price at horizon", cell["carbon_price"], "US$2010 / tCO2e",
         f"{result['horizon_year']} shadow price under {cell['scenario_name']}"),
        ("Deflated to denominator-year dollars", cell["carbon_price_deflated"], "US$ / tCO2e",
         f"{cell['carbon_price']:,.0f} x {result['us_gdp_deflator']:.2f} US GDP deflator"),
        ("Sector emission intensity", sector["intensity"], "tCO2e / US$m",
         f"{sector['emissions_mt']:.4f} MtCO2e / US${sector['denominator_usd']:,.0f}m"),
        ("Gross carbon cost", cell["carbon_price_deflated"] * sector["intensity"] / 1e6,
         "share of value added", "price x intensity / 1,000,000"),
        ("Less pass-through", -(cell["carbon_price_deflated"] * sector["intensity"] / 1e6)
         * sector["pass_through"], "share of value added",
         f"{sector['pass_through']:.0%} of the cost is recovered in prices"),
        ("= Transition cost ratio", cell["transition_cost"], "share of value added", ""),
        ("+ Physical cost ratio", cell["physical_cost"], "share of value added",
         "3 hazards x severity x normalised exposure x retained x P&L share"),
        ("= Total cost ratio", cell["total_cost"], "share of value added",
         "capped" if cell["cap_binds"] else "cap not binding"),
        ("push = k x g(total, theta)", cell["push"], "probit",
         f"k = {k:.6f}, theta = {theta:g}"),
        ("+ macro shift", cell["macro_shift"], "probit",
         f"beta {result['macro']['beta_in_use']:.4f} x GDP level deviation "
         f"{result['macro']['by_scenario'][scenario]['deviation_pct']:.2f}% x macro_beta "
         f"{sector['macro_beta']:.2f}"),
        ("= total probit shift", cell["probit_shift"], "probit", ""),
        ("Baseline PD", row["baseline_pd"], "probability", f"grade {grade}"),
        ("N-1(baseline PD)", norm_ppf(row["baseline_pd"]), "probit", ""),
        ("Stressed PD = N(probit + shift)", row["stressed_pd"], "probability",
         f"{row['multiple']:.3f}x baseline, +{row['delta_bps']:.0f} bps"),
    ]

    return {
        "sector_id": sector_id, "sector": sector["name"], "grade": grade,
        "scenario": scenario, "scenario_name": cell["scenario_name"],
        "cell": cell, "row": row, "sector_detail": sector,
        "hazards": hazard_rows,
        "steps": [{"label": s[0], "value": s[1], "unit": s[2], "detail": s[3]} for s in steps],
    }
