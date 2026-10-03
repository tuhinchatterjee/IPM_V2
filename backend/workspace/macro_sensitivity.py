"""
Macro-sensitivity tornado (MAC07): the material MEV sensitivities of the
active population, ranked, from the governed sensitivity library only.

For every macroeconomic variable the book publishes, a symmetric standard
shock (stated per the factor's own shock convention) is pushed through the
SAME governed translation the Scenario Library uses
(`scenario_library.translate_macro`): the published slope, the population's
own baseline PD / LGD, the fitted lag. Each bar is one (MEV, risk parameter)
pair: the down-shock and up-shock parameter movement in percentage points.

What it refuses to do
---------------------
* invent a number: every value is the translation of a published slope; a
  DIAGNOSTIC_ONLY estimate is listed, labelled, and NOT drawn;
* correct a sign: a counter-intuitive fitted sign is drawn as fitted. Where
  the governed collateral rule applies (property-price factors moving LGD
  down when values fall -- RET-07 / CORP-03), the row carries the same
  SIGN_REVIEW warning the Scenario Library shows;
* call a model.

This is the new governed What-If experience. The accepted Cockpit chat's
"tornado substitute" (`cockpit_v4.scenario.results.tornado_substitute`) is
untouched and still answers with its waterfall on that path.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.workspace import grid, metrics
from backend.workspace import scenario_library as sl

#: The standard shock per shock convention: (operation, size). Stated on
#: every row; the reader can scale it.
STANDARD_SHOCK: dict[str, tuple[str, float]] = {
    "percentage_points": ("percentage_points", 1.0),
    "basis_points": ("basis_points", 100.0),
    "relative_percent": ("relative_percent", 10.0),
    "index_points": ("index_points", 5.0),
}

PARAMETER_LABEL = {"pd_pit_12m": "PD 12m", "pd_lifetime": "PD lifetime",
                   "lgd_pct": "LGD"}
PARAMETER_FAMILY = {"pd_pit_12m": "pd", "pd_lifetime": "pd", "lgd_pct": "lgd"}

#: Factors the governed collateral rule reads as collateral values.
COLLATERAL_FACTORS = frozenset(sl.COLLATERAL_FACTOR.values())


def _shock_label(convention: str, op: str, size: float) -> str:
    unit = {"percentage_points": "pp", "basis_points": "bp",
            "relative_percent": "%", "index_points": "index pts"}[op]
    return f"±{size:g} {unit}" + (" of the level" if op == "relative_percent"
                                  else "")


def _sign_review(factor_id: str, parameter: str, down_pp: float
                 ) -> str | None:
    if parameter == "lgd_pct" and factor_id in COLLATERAL_FACTORS and \
            down_pp < 0:
        return ("SIGN_REVIEW: the governed slope moves LGD DOWN "
                f"({down_pp:+.3f} pp) when collateral values fall. It is the "
                "fitted artefact's sign on this synthetic history and is "
                "shown, not corrected; review before relying on it.")
    return None


def tornado(book: Any, *, filters: Any = None, parameter: str = "all",
            top: int = 12, scale: float = 1.0) -> dict[str, Any]:
    if parameter not in ("all", "pd", "lgd"):
        raise HTTPException(422, {"error_code": "INVALID_PARAMETER",
                                  "message": "parameter is all, pd or lgd."})
    if not 0 < scale <= 5:
        raise HTTPException(422, {"error_code": "INVALID_SCALE",
                                  "message": "scale is between 0 and 5."})
    top = max(1, min(int(top), 60))
    v = grid.view(book)
    where, params, checked = grid._where(v, filters)
    cond = where[len("WHERE "):] if where else "1=1"
    population = sl._pop(book, v, cond, params)
    # An empty population is a state, as it is in the grid and the explorer
    # (EMPTY_BY_FILTER), not a refused request: a filter that matches
    # nothing answers with no bars and says why (VAL-DEF-043).
    empty = population["entities"] == 0
    published = metrics.sensitivity_rows(book)
    by_key = {(r["factor_id"], r["parameter"]): r for r in published}
    factors = [] if empty else list(dict.fromkeys(
        r["factor_id"] for r in published))
    series = {r["factor_id"]: r["series_id"] for r in book.rows(
        f"SELECT factor_id, series_id FROM "
        f"whatif_{sl._b(book.domain_id)}_mev_registry")}
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for factor_id in factors:
        reg = sl._macro_registry(book, factor_id) or {}
        convention = str(reg.get("shock_convention") or "")
        if convention not in STANDARD_SHOCK:
            continue
        op, size = STANDARD_SHOCK[convention]
        size *= scale
        up = sl.translate_macro(book, factor_id, op, size,
                                baseline=population)
        down = sl.translate_macro(book, factor_id, op, -size,
                                  baseline=population)
        for x in up.get("excluded", []):
            meta = by_key.get((factor_id, x["parameter"]), {})
            excluded.append({
                "factor_id": factor_id, "factor_name": reg.get("factor_name"),
                "parameter": x["parameter"],
                "parameter_label": PARAMETER_LABEL.get(x["parameter"]),
                "readiness": x["readiness"], "reason": x["reason"],
                "coefficient": meta.get("coefficient")})
        downs = {d["field"]: d for d in down.get("derived", [])}
        for d in up.get("derived", []):
            p = d["field"]
            if parameter != "all" and PARAMETER_FAMILY[p] != parameter:
                continue
            meta = by_key.get((factor_id, p), {})
            up_pp = float(d["value"])
            down_pp = float(downs[p]["value"]) if p in downs else None
            swing = max(abs(up_pp), abs(down_pp or 0.0))
            warnings = sorted(set(up.get("warnings", [])
                                  + down.get("warnings", [])))
            review = _sign_review(factor_id, p, down_pp or 0.0)
            rows.append({
                "factor_id": factor_id,
                "factor_name": reg.get("factor_name") or factor_id,
                "series_id": series.get(factor_id),
                "native_unit": reg.get("native_unit"),
                "shock_convention": convention, "shock_operation": op,
                "shock_size": size,
                "shock_label": _shock_label(convention, op, size),
                "conversion_up": up.get("conversion"),
                "factor_change_up": d["factor_change"],
                "parameter": p, "parameter_label": PARAMETER_LABEL[p],
                "family": PARAMETER_FAMILY[p],
                "coefficient": meta.get("coefficient"),
                "native_derivative": d["native_derivative"],
                "native_derivative_unit": d["native_derivative_unit"],
                "sign": "+" if (meta.get("coefficient") or 0) >= 0 else "-",
                "parameter_baseline": d["parameter_baseline"],
                "up_pp": up_pp, "down_pp": down_pp, "swing_pp": swing,
                "readiness": d["readiness"], "method": meta.get("method"),
                "lag": d["lag"], "train_start": meta.get("train_start"),
                "train_end": meta.get("train_end"),
                "training_periods": meta.get("training_periods"),
                "sign_stability": meta.get("sign_stability"),
                "artifact_version": d["artifact_version"],
                "limitation": meta.get("limitation"),
                "sign_review": review, "warnings": warnings})
    rows.sort(key=lambda r: (-r["swing_pp"], r["factor_id"], r["parameter"]))
    return {
        "domain_id": book.domain_id, "release_id": book.release_id,
        "fingerprint": book.fingerprint, "period": v.period,
        "filters": checked,
        "population": {k: population[k] for k in (
            "entities", "owners", "ead", "mean_pd", "mean_lgd_pct")},
        "parameter": parameter, "scale": scale,
        "standard_shocks": {k: {"operation": o, "size": s * scale,
                                "label": _shock_label(k, o, s * scale)}
                            for k, (o, s) in STANDARD_SHOCK.items()},
        "rows": rows[:top], "material_rows": len(rows),
        "excluded": excluded, "model_calls": 0,
        "empty": ({"error_code": "EMPTY_BY_FILTER",
                   "message": "No exposures match the filter, so there is "
                              "nothing to rank."} if empty else None),
        "evidence": "Governed sensitivity library translated by the "
                    "Scenario Library's own macro translation; no model "
                    "call; signs as fitted.",
    }


__all__ = ["COLLATERAL_FACTORS", "PARAMETER_LABEL", "STANDARD_SHOCK",
           "tornado"]
