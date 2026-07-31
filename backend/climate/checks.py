"""
The 24 live quality checks, re-implemented as a post-calculation test suite.

Every check returns {id, name, result, status, explanation, expected, blocking}.
`status` is one of PASS / FAIL / FLAG / ACTION / INFO / DISCLOSE / REJECTED.

Only FAIL is blocking: a run carrying one cannot be marked final. FLAG, ACTION,
DISCLOSE and REJECTED are visible disclosures, not defects, and four of them are
expected on delivery of the Oman dataset — 14 (EDGAR Buildings per head),
15 (Fragmented World transition deviation), 19 (the coal anchor, an intended
diagnostic) and 24 (the warming interpolation). Those carry `expected=True` so the
UI can separate them from anything that has genuinely gone wrong.

Checks 22 and 23 together are the supervisory headline. Transition severity must
follow the carbon price ordering (NZ >= DT >= FW >= CP) and physical severity must
follow the warming ordering (CP >= FW >= DT >= NZ) — the exact reverse. If both
pass, the model has internally coherent opposing channels, which is the single
most important structural test of a climate scenario model.
"""

from backend.climate.normal import norm_cdf, norm_ppf

TOL = 1e-9
ORDER_TOL = 1e-12

STATUS_BLOCKING = {"FAIL"}
STATUS_TONE = {
    "PASS": "ok", "INFO": "info", "FLAG": "warn", "ACTION": "warn",
    "DISCLOSE": "warn", "REJECTED": "warn", "FAIL": "bad",
}

# Structural ordering the two channels must obey, best-to-worst.
TRANSITION_ORDER = ["NZ", "DT", "FW", "CP"]
PHYSICAL_ORDER = ["CP", "FW", "DT", "NZ"]


def _check(cid, name, result, status, explanation, expected=False):
    return {
        "id": cid, "name": name, "result": result, "status": status,
        "explanation": explanation, "expected": expected,
        "blocking": status in STATUS_BLOCKING,
        "tone": STATUS_TONE.get(status, "info"),
    }


def _ordering_violations(result, order, key):
    """Count adjacent pairs that break the required ordering, over all sectors."""
    violations = []
    for s in result["sectors"]:
        for better, worse in zip(order, order[1:], strict=False):
            a = result["by_cell"][(s["id"], better)][key]
            b = result["by_cell"][(s["id"], worse)][key]
            if a < b - ORDER_TOL:
                violations.append({"sector": s["name"], "pair": f"{better} < {worse}",
                                   "values": (a, b)})
    return violations


def run_checks(result: dict, model: dict) -> list[dict]:
    """Run all 24 checks against a completed calculation."""
    settings = result["settings"]
    emissions = result["emissions"]
    cal = result["calibration"]
    phys = result["physical"]
    macro = result["macro"]
    out = []

    # 1 — sector GVA reconciles to the SNA total value added.
    total_gva = result["totals"]["total_gva_local"]
    sna = float(settings["sna_total_gva_omr"])
    out.append(_check(
        1, "Sector GVA reconciles to SNA total value added", total_gva,
        "PASS" if abs(total_gva - sna) < 0.01 else "FAIL",
        f"Sector GVA must equal the published total value added of {sna:,.1f} exactly. Every ISIC "
        f"section sits in exactly one sector, so there are no gaps and no double counting."))

    # 2 — every EDGAR row's allocation shares sum to 1.00.
    bad_rows = [c["code"] for c in emissions["categories"] if abs(c["share_sum"] - 1.0) > 1e-6]
    out.append(_check(
        2, "Every EDGAR row's allocation shares sum to 1.00", len(bad_rows),
        "PASS" if not bad_rows else "FAIL",
        "Each source category must be fully distributed across the lending sectors plus households. "
        + (f"Rows out of balance: {', '.join(bad_rows)}." if bad_rows else "All rows balance.")))

    # 3 — the stated categories reconcile to the national total.
    delta3 = abs(emissions["category_sum_mt"] - emissions["national_total_mt"])
    out.append(_check(
        3, "EDGAR categories reconcile to the national total", emissions["category_sum_mt"],
        "PASS" if delta3 < 0.001 else "FAIL",
        "The residual row is a plug, so this holds unless the national total itself is edited."))

    # 4 — allocation has neither lost nor created emissions.
    delta4 = abs(emissions["allocated_total_mt"] - emissions["national_total_mt"])
    out.append(_check(
        4, "Allocated sector emissions reconcile to the national total", emissions["allocated_total_mt"],
        "PASS" if delta4 < 0.001 else "FAIL",
        "Allocation redistributes emissions across sectors; it must not change the national total."))

    # 5 — no sector may end up with a zero denominator and therefore no stress.
    zero_intensity = [s["name"] for s in result["sectors"] if s["intensity"] <= 0]
    out.append(_check(
        5, "Sectors with zero computed intensity", len(zero_intensity),
        "PASS" if not zero_intensity else "FAIL",
        "Must be zero. This was the v3 defect: rows existed for ISIC sections the country does not "
        "itemise, so those sectors had no denominator and silently received no stress at all."
        + (f" Affected: {', '.join(zero_intensity)}." if zero_intensity else "")))

    # 6 — no de-stress anywhere in the grid.
    destress = sum(1 for r in result["grid"] if r["stressed_pd"] < r["baseline_pd"] - TOL)
    out.append(_check(
        6, "No de-stress: stressed PD is never below baseline", destress,
        "PASS" if destress == 0 else "FAIL",
        f"All {len(result['grid'])} cells checked. Under the probit-shift form this can only fail if a "
        f"push or a macro shift is negative. The conditional-Vasicek form used in v2 failed it by "
        f"construction."))

    # 7 — the probit transform round-trips.
    identity = norm_cdf(norm_ppf(0.02))
    out.append(_check(
        7, "Probit identity: N(N-1(2%)) = 2%", identity,
        "PASS" if abs(identity - 0.02) < 1e-9 else "FAIL",
        "Confirms the transform round-trips and the baseline is returned exactly at zero stress."))

    # 8 — physical/transition crossover under Current Policies (diagnostic).
    crossover = sum(1 for s in result["sectors"]
                    if result["by_cell"][(s["id"], "CP")]["physical_cost"]
                    > result["by_cell"][(s["id"], "CP")]["transition_cost"])
    out.append(_check(
        8, "Sectors where physical cost exceeds transition cost under Current Policies", crossover,
        "INFO",
        "Diagnostic, not a pass or fail. Current Policies carries almost no transition cost by "
        "construction, so physical damage should dominate there. A reading of zero at a long horizon "
        "means the physical module is switched off or mis-scaled."))

    # 9 / 10 / 11 — configuration disclosures.
    out.append(_check(
        9, "Denominator basis in use", result["totals"]["basis"], "INFO",
        "GVA by default, because most emerging-market statistical offices publish value added by "
        "activity but not turnover. The EU anchor is converted onto the same basis rather than left "
        "as an implicit unit mismatch."))

    out.append(_check(
        10, "EU intensity route in use",
        f"Route {cal['route_in_use']} ({'symmetric' if cal['route_in_use'] == 1 else 'firm-level'})",
        "INFO",
        "Route 1 builds the EU intensity exactly as the local intensity is built — national Scope 1 "
        "emissions over national GVA — so the turnover conversion never enters."))

    deflator = result["us_gdp_deflator"]
    out.append(_check(
        11, "US GDP deflator applied to the carbon price", deflator,
        "PASS" if deflator > 1.01 else "FAIL",
        f"NGFS prices are in US${settings['carbon_price_base_year']}; the denominator is in "
        f"{settings['denominator_base_year']} dollars. Omitting the deflator understates every cost "
        f"ratio by roughly a quarter."))

    # 12 — household exclusion still switched on.
    share = emissions["corporate_share"]
    out.append(_check(
        12, "Corporate share of national emissions", share,
        "PASS" if 0.4 < share < 0.9 else "REVIEW",
        "The remainder is households and own-account use. Above 90% the household exclusion has been "
        "switched off and private vehicle and residential emissions are being charged to borrowers."))

    # 13 — the live estimate reproduces the selected specification.
    slope_gap = abs(macro["beta_ols"] - _reported_beta(model, macro))
    out.append(_check(
        13, "Live regression reproduces the reported slope", slope_gap,
        "PASS" if slope_gap < 1e-3 else "FAIL",
        f"The engine estimates specification {macro['selected_specification']} directly from the "
        f"historical series; it must reproduce the coefficient recorded in the specification table."))

    # 14 — EDGAR Buildings plausibility (expected to flag).
    bph = emissions["buildings_per_head"]
    out.append(_check(
        14, "EDGAR Buildings emissions per head (tCO2e)", bph,
        "PASS" if bph < 3 else "FLAG",
        "EXPECTED TO FLAG. This is direct building fuel combustion only, since air-conditioning "
        "electricity already sits under Power Industry. Above about 3 tCO2e per head the figure is not "
        "credible for a hot climate. 70% is allocated to households so it does not distort corporate "
        "intensities, but the EDGAR sector file should be re-downloaded.", expected=bph >= 3))

    # 15 — Fragmented World deviation (expected to require action).
    fw = next((s for s in model["scenarios"] if s["code"] == "FW"), None)
    fw_zero = fw is not None and all(float(v) == 0 for v in fw["gdp_deviation"].values())
    out.append(_check(
        15, "Fragmented World carries a non-zero GDP deviation",
        "zero in every year" if fw_zero else "non-zero", "ACTION" if fw_zero else "PASS",
        "EXPECTED TO SHOW ACTION. Fragmented World is not plotted in the published NGFS chart and no "
        "public figure exists, but a zero deviation for a high-cost, badly co-ordinated transition is "
        "not credible. Requires the IIASA portal pull.", expected=fw_zero))

    # 16 — which anchor is in force.
    anchor = cal["anchor_in_use"]
    out.append(_check(
        16, "k anchor decision recorded",
        f"Anchor {anchor} ({cal['anchor_rel']:+.1%} relative)", "INFO",
        "Anchor A is the transition-only identification (orderly vs hot house world) and is the default "
        "because it is the only clean one. Anchor B is the disorderly-vs-orderly 2050 figure, retained "
        "for sensitivity."))

    # 17 — how far k is extrapolated beyond its calibration point.
    multiple = cal["extrapolation"]["multiple"] if cal.get("extrapolation") else 0.0
    out.append(_check(
        17, "Extrapolation multiple of k beyond its calibration point", multiple,
        "PASS" if multiple < 10 else "DISCLOSE",
        f"k is calibrated at an EU cost ratio of {cal['cost_ratio_eu']:.4%} of value added and applied "
        f"to local cost ratios up to {result['max_cost_ratio']:.1%}. Above 10x, disclose or cap."))

    # 18 — the curvature parameter in force.
    theta = result["theta"]
    out.append(_check(
        18, "Curvature parameter theta in use", theta, "INFO",
        "theta = 0 is the logarithmic form. The ECB anchors cannot identify this parameter because both "
        "sit below a 4% cost ratio, where every smooth form is indistinguishable from a straight line. "
        "It is exposed so the range can be reported rather than assumed away."))

    # 19 — coal out-of-sample check (expected to reject).
    coal = cal.get("coal") or {}
    disc = coal.get("discrepancy")
    out.append(_check(
        19, "Coal anchor out-of-sample check", disc if disc is not None else "unreachable",
        "REJECTED" if coal.get("rejected") else "PASS",
        "EXPECTED TO REJECT. The coal-mining PD response demands an emission intensity 20 to 50 times "
        "higher than coal plausibly has on a Scope 1 basis, confirming the paper's own statement that "
        "the response is driven by Scope 3 abatement investment raising leverage. It therefore cannot "
        "calibrate a Scope 1 cost curve.", expected=bool(coal.get("rejected"))))

    # 20 — the cap and what it binds on.
    cap = result["cost_ratio_cap"]
    bound = result["cap_binding_cells"]
    out.append(_check(
        20, "Cost ratio cap and cells bound",
        f"{bound} cell(s) bound; cap {'OFF' if cap > 100 else f'{cap:.2f}'}",
        "PASS" if bound == 0 else "DISCLOSE",
        "Given that curvature above the calibration range cannot be estimated, a cap is the only "
        "mechanism that bounds the utilities and manufacturing result."))

    # 21 — exposure weights preserve the national loss total.
    means = phys["normalised_weighted_mean"]
    ok21 = all(abs(v - 1.0) < 1e-4 for v in means.values())
    out.append(_check(
        21, "Physical exposure weights normalise to 1.00",
        ", ".join(f"{h}={v:.4f}" for h, v in means.items()), "PASS" if ok21 else "FAIL",
        "Exposure weights redistribute the national annual average loss across sectors; they must not "
        "change its total. The GVA-weighted mean of the normalised weights must be exactly 1.000 for "
        "every hazard."))

    # 22 / 23 — the two opposing orderings. This pair is the supervisory headline.
    tv = _ordering_violations(result, TRANSITION_ORDER, "transition_cost")
    out.append(_check(
        22, "Transition ordering: NZ >= DT >= FW >= CP", len(tv),
        "PASS" if not tv else "FAIL",
        "Transition severity must follow the carbon price ordering, per sector."
        + (f" Violations: {tv[:3]}" if tv else "")))

    pv = _ordering_violations(result, PHYSICAL_ORDER, "physical_cost")
    out.append(_check(
        23, "Physical ordering: CP >= FW >= DT >= NZ", len(pv),
        "PASS" if not pv else "FAIL",
        "Physical severity must follow the warming ordering, i.e. the exact reverse of transition. If "
        "both 22 and 23 pass, the model has internally coherent opposing channels — the single most "
        "important structural test of a climate scenario model."
        + (f" Violations: {pv[:3]}" if pv else "")))

    # 24 — the warming path is interpolated, not sourced (expected to flag).
    warm_cp = phys["warming"]["CP"]["at_horizon"] if "CP" in phys["warming"] else 0.0
    out.append(_check(
        24, "Warming path at horizon is interpolated, not sourced", warm_cp, "FLAG",
        "EXPECTED TO FLAG. Warming at the horizon is a straight-line interpolation between today and "
        "2100. Replace with the MAGICC temperature path published with NGFS Phase V. This is the "
        "weakest input in the physical module.", expected=True))

    return out


def _reported_beta(model, macro):
    """The beta recorded for the selected specification in the specification table."""
    selected = macro.get("selected_specification")
    for spec in model["macro"].get("regression_tests", []):
        if spec["id"] == selected:
            return float(spec["beta"])
    return macro["beta_ols"]


def summarise(checks: list[dict]) -> dict:
    """Headline counts + the run's approval gate."""
    by_status = {}
    for c in checks:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    failures = [c for c in checks if c["blocking"]]
    attention = [c for c in checks if c["status"] in {"FAIL", "FLAG", "ACTION", "REJECTED", "DISCLOSE"}]
    unexpected = [c for c in attention if not c["expected"]]
    return {
        "total": len(checks),
        "by_status": by_status,
        "passed": sum(1 for c in checks if c["status"] == "PASS"),
        "failures": failures,
        "failure_count": len(failures),
        "attention_count": len(attention),
        "expected_count": sum(1 for c in attention if c["expected"]),
        "unexpected": unexpected,
        "can_finalise": not failures,
        "structural_pair_ok": all(c["status"] == "PASS" for c in checks if c["id"] in (22, 23)),
    }
