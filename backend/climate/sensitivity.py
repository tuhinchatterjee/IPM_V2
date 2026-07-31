"""
One-way sensitivity over the five control levers, plus the disclosure bands.

The point of this module is not to find a "best" answer — it is to report how wide
the honest range is. Two of the levers (theta and the correlation) are parameters
the public sources demonstrably cannot pin down, so the band they generate is the
model's real uncertainty and belongs in front of a credit committee rather than
buried in a footnote.
"""

import copy

from backend.climate import engine

# The five levers, with the path into the model dict and a default disclosure band.
LEVERS = {
    "theta": {
        "label": "Curvature θ",
        "path": ("settings", "theta"),
        "values": [1.0, 0.5, 0.0, -0.5, -1.0],
        "format": "{:+.1f}",
        "note": "Unidentifiable from the ECB anchors: both sit below a 4% cost ratio, where every "
                "smooth form looks linear. +1 linear, 0 logarithmic, −1 saturating.",
    },
    "correlation": {
        "label": "NPL / GDP correlation",
        "path": ("macro", "correlation_in_use"),
        "values": [-0.35, -0.45, -0.5291, -0.60, -0.70],
        "format": "{:+.4f}",
        "note": "Estimated at −0.529 on ten annual observations with p = 0.116. The standard "
                "deviations are estimated adequately; the correlation is not.",
    },
    "cap": {
        "label": "Cost ratio cap",
        "path": ("settings", "cost_ratio_cap"),
        "values": [0.25, 0.50, 0.75, 1.00, 999.0],
        "format": "{:.2f}",
        "note": "Off at 999. Since curvature above the calibration range cannot be estimated, a cap "
                "is the only mechanism that bounds the utilities and manufacturing result.",
    },
    "horizon": {
        "label": "Horizon year",
        "path": ("settings", "horizon_year"),
        "values": [2030, 2035, 2040, 2050],
        "format": "{:.0f}",
        "note": "Carbon prices rise steeply and warming paths diverge slowly, so the transition "
                "channel dominates the horizon response and the physical channel barely moves.",
    },
    "k_intensity": {
        "label": "EU calibration intensity",
        "path": ("calibration", "route1", "__eu_intensity__"),
        "values": [50, 90, 150, 250, 400],
        "format": "{:.0f} t/EURm",
        "note": "The single largest source of uncertainty in k: no median-firm Scope 1 intensity is "
                "published anywhere in ECB OP 281. k moves by roughly a factor of eight across this band.",
    },
    "pass_through": {
        "label": "Pass-through (uniform shift)",
        "path": ("sectors", "__pass_through_shift__"),
        "values": [-0.20, -0.10, 0.0, 0.10, 0.20],
        "format": "{:+.0%}",
        "note": "A uniform shift applied to every sector's pass-through, clipped to [0, 1]. Tests how "
                "much of the result rests on the trade-exposure judgement.",
    },
}


def _apply(model: dict, parameter: str, value) -> dict:
    """Return a copy of the model with one lever moved. Two levers are not plain
    scalar cells, so they get an explicit rule rather than a path write."""
    m = copy.deepcopy(model)
    if parameter == "k_intensity":
        # Re-express the Route 1 inputs so the resulting median intensity equals `value`,
        # leaving the median-to-average adjustment visible and untouched.
        r1 = m["calibration"]["route1"]
        ratio = float(r1["median_to_average"]) or 1.0
        economy = float(value) / ratio
        r1["eu_gva_eur_bn"] = (float(r1["eu_total_ghg_mt"]) * (1.0 - float(r1["household_share"]))
                               * 1000.0 / economy)
        m["calibration"]["route_in_use"] = 1
    elif parameter == "pass_through":
        for s in m["sectors"]:
            s["pass_through"] = min(1.0, max(0.0, float(s["pass_through"]) + float(value)))
    elif parameter == "theta":
        m["settings"]["theta"] = float(value)
    elif parameter == "cap":
        m["settings"]["cost_ratio_cap"] = float(value)
    elif parameter == "horizon":
        m["settings"]["horizon_year"] = int(value)
    elif parameter == "correlation":
        m["macro"]["correlation_in_use"] = float(value)
    else:
        raise ValueError(f"unknown sensitivity parameter {parameter!r}")
    return m


def _headline(result: dict) -> dict:
    """Compact per-run metrics: enough to plot a band without carrying 280 cells."""
    grade = result["reference_grade"]
    rows = [r for r in result["grid"] if r["grade"] == grade]
    multiples = [r["multiple"] for r in rows]
    worst = max(rows, key=lambda r: r["multiple"]) if rows else None
    return {
        "k": result["k"],
        "reference_grade": grade,
        "max_cost_ratio": result["max_cost_ratio"],
        "cap_binding_cells": result["cap_binding_cells"],
        "mean_multiple": sum(multiples) / len(multiples) if multiples else 0.0,
        "max_multiple": max(multiples) if multiples else 0.0,
        "min_multiple": min(multiples) if multiples else 0.0,
        "worst_cell": {"sector": worst["sector"], "scenario": worst["scenario"],
                       "multiple": worst["multiple"], "stressed_pd": worst["stressed_pd"]} if worst else None,
        "by_sector_scenario": {f"{r['sector_id']}|{r['scenario']}": r["multiple"] for r in rows},
    }


def one_way(model: dict, parameter: str, values=None) -> dict:
    """Recalculate across one lever. Cheap enough to run synchronously — the grid
    is 280 cells of pure arithmetic."""
    spec = LEVERS.get(parameter)
    if spec is None:
        raise ValueError(f"unknown sensitivity parameter {parameter!r}")
    values = list(values) if values else list(spec["values"])

    base_value = _current_value(model, parameter)
    points = []
    for v in values:
        result = engine.calculate(_apply(model, parameter, v))
        points.append({"value": v, "label": spec["format"].format(v), **_headline(result)})

    return {
        "parameter": parameter, "label": spec["label"], "note": spec["note"],
        "base_value": base_value, "points": points,
    }


def _current_value(model: dict, parameter: str):
    if parameter == "k_intensity":
        r1 = model["calibration"]["route1"]
        return (float(r1["eu_total_ghg_mt"]) * (1.0 - float(r1["household_share"])) * 1000.0
                / float(r1["eu_gva_eur_bn"])) * float(r1["median_to_average"])
    if parameter == "pass_through":
        return 0.0
    if parameter == "correlation":
        return float(model["macro"]["correlation_in_use"])
    return model["settings"][{"theta": "theta", "cap": "cost_ratio_cap",
                              "horizon": "horizon_year"}[parameter]]


def tornado(model: dict, parameters=None) -> dict:
    """One-way ranges for every lever, ranked by how much the reference-grade PD
    multiple moves. This is the chart that answers 'what is actually driving this'."""
    parameters = parameters or list(LEVERS)
    base = _headline(engine.calculate(model))

    bars = []
    for p in parameters:
        sweep = one_way(model, p)
        highs = [pt["max_multiple"] for pt in sweep["points"]]
        means = [pt["mean_multiple"] for pt in sweep["points"]]
        lo_i, hi_i = means.index(min(means)), means.index(max(means))
        bars.append({
            "parameter": p, "label": sweep["label"], "note": sweep["note"],
            "low": min(means), "high": max(means),
            "low_label": sweep["points"][lo_i]["label"], "high_label": sweep["points"][hi_i]["label"],
            "span": max(means) - min(means),
            "max_multiple_low": min(highs), "max_multiple_high": max(highs),
            "points": sweep["points"],
        })
    bars.sort(key=lambda b: b["span"], reverse=True)
    return {"base": base, "bars": bars}


def compare_runs(result_a: dict, result_b: dict, grade: str | None = None) -> dict:
    """Cell-level diff between two completed runs at one grade.

    Essential once inputs become editable: without it, 'the number changed' is an
    assertion rather than a finding.
    """
    grade = grade or result_a["reference_grade"]
    a = {(r["sector_id"], r["scenario"]): r for r in result_a["grid"] if r["grade"] == grade}
    b = {(r["sector_id"], r["scenario"]): r for r in result_b["grid"] if r["grade"] == grade}

    rows = []
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key), b.get(key)
        if ra is None or rb is None:
            rows.append({"sector_id": key[0], "scenario": key[1],
                         "sector": (ra or rb)["sector"], "status": "only in A" if rb is None else "only in B",
                         "pd_a": ra["stressed_pd"] if ra else None,
                         "pd_b": rb["stressed_pd"] if rb else None,
                         "delta_pd": None, "delta_bps": None, "delta_multiple": None})
            continue
        rows.append({
            "sector_id": key[0], "scenario": key[1], "sector": ra["sector"], "status": "both",
            "pd_a": ra["stressed_pd"], "pd_b": rb["stressed_pd"],
            "delta_pd": rb["stressed_pd"] - ra["stressed_pd"],
            "delta_bps": (rb["stressed_pd"] - ra["stressed_pd"]) * 10000.0,
            "multiple_a": ra["multiple"], "multiple_b": rb["multiple"],
            "delta_multiple": rb["multiple"] - ra["multiple"],
        })

    changed = [r for r in rows if r["delta_bps"] is None or abs(r["delta_bps"]) > 1e-6]
    return {
        "grade": grade, "rows": rows, "changed": changed, "changed_count": len(changed),
        "headline": {
            "k_a": result_a["k"], "k_b": result_b["k"],
            "horizon_a": result_a["horizon_year"], "horizon_b": result_b["horizon_year"],
            "theta_a": result_a["theta"], "theta_b": result_b["theta"],
            "max_abs_bps": max((abs(r["delta_bps"]) for r in rows if r["delta_bps"] is not None),
                               default=0.0),
        },
    }
