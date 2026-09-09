"""
The governed tools Cockpit V2 adds to the analyst registry. Brief §5.

Five tools, registered into the EXISTING registry in `backend/analyst/tools.py`
rather than into a parallel one, and only when the switch is on. All arithmetic
runs here, in the controlled backend; the model chooses which tool to call and
never computes any of it.

* `decompose_ecl_factors` — the mandatory one. WHICH PARAMETER moved ECL.
* `decompose_movement`    — WHERE an additive measure moved, by dimension.
* `decompose_ratio`       — a ratio movement split into numerator and
                            denominator effects.
* `metric_history`        — a measure over its actual published periods.
* `list_certified_analyses` — the compact permission-filtered registry, so the
                            model never has to guess an analysis id and pay a
                            tool call to read the refusal.

Every result carries scope, units, dates, versions, filters, coverage,
supporting rows and totals, reconciliation status and limitations, and says
when rows were truncated and how to drill into the rest.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.analyst.evidence import Observation
from backend.analyst.safety import READ_METADATA, RUN_ANALYSIS, Principal
from backend.cockpit_v2 import ATTRIBUTION_VERSION, DATA_VERSION, MODEL_VERSION, POLICY_VERSION, enabled, reader
from backend.cockpit_v2 import attribution as attr
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import schema as schema_mod
from backend.cockpit_v2 import scope as scope_mod

logger = logging.getLogger(__name__)

#: Rows returned to the model. The rest are reachable through the drill-down
#: handle on the observation, and the observation says how many there were.
MAX_ROWS = 50


def _refuse(tool: str, arguments: dict[str, Any], reason: str) -> Observation:
    return Observation(tool=tool, arguments=dict(arguments), refused=reason,
                       purpose=reason)


def _versions() -> dict[str, str]:
    return {"data_version": DATA_VERSION, "model_version": MODEL_VERSION,
            "policy_version": POLICY_VERSION,
            "attribution_version": ATTRIBUTION_VERSION}


def _periods(principal: Principal, arguments: dict[str, Any]) -> dict[str, Any]:
    return reader.resolve_period_pair(
        to_period=str(arguments.get("to_period") or ""),
        from_period=str(arguments.get("from_period") or ""),
        principal=principal)


def _filtered(quarter: str, principal: Principal, where: Any):
    frame = reader.snapshot(quarter, principal)
    for clause in (where or []):
        if not isinstance(clause, dict):
            continue
        field = str(clause.get("field") or "")
        value = clause.get("value")
        op = str(clause.get("op") or "eq")
        if field not in frame.columns:
            continue
        if op == "eq":
            frame = frame[frame[field] == value]
        elif op == "ne":
            frame = frame[frame[field] != value]
        elif op == "in":
            frame = frame[frame[field].isin(list(value or []))]
        elif op == "gt":
            frame = frame[frame[field] > value]
        elif op == "gte":
            frame = frame[frame[field] >= value]
        elif op == "lt":
            frame = frame[frame[field] < value]
        elif op == "lte":
            frame = frame[frame[field] <= value]
        elif op == "contains":
            frame = frame[frame[field].astype(str).str.contains(
                str(value), case=False, na=False)]
    return frame


# ------------------------------------------------------------------ handlers


def decompose_ecl_factors(principal: Principal, **arguments: Any) -> Observation:
    """WHICH PARAMETER moved ECL between two published quarters."""
    started = time.perf_counter()
    tool = "decompose_ecl_factors"
    periods = _periods(principal, arguments)
    if not periods["available"]:
        return _refuse(tool, arguments, periods["reason"])

    try:
        opening_rows = _filtered(periods["opening"], principal,
                                 arguments.get("where"))
        closing_rows = _filtered(periods["closing"], principal,
                                 arguments.get("where"))
    except scope_mod.OutOfScope as e:
        return _refuse(tool, arguments, str(e))

    wanted = sorted(set(opening_rows["facility_id"])
                    | set(closing_rows["facility_id"]))
    found = attr.decompose_ecl_factors(
        list(reader.measurements_for(periods["opening"], principal,
                                     wanted).values()),
        list(reader.measurements_for(periods["closing"], principal,
                                     wanted).values()),
        opening_date=periods["opening_date"],
        closing_date=periods["closing_date"],
        top_facilities=int(arguments.get("top") or 15))

    rows = [{"component": f.label, "kind": "factor",
             "contribution": round(f.contribution, 6),
             "share_of_net_change_pct": (None if f.share_of_net_change is None
                                         else round(f.share_of_net_change, 3)),
             "meaning": f.meaning}
            for f in found.factors]
    rows.extend({"component": s.label, "kind": "structural",
                 "contribution": round(s.amount, 6),
                 "accounts": s.accounts, "meaning": s.note}
                for s in found.structural)

    return Observation(
        tool=tool, arguments=dict(arguments), rows=rows[:MAX_ROWS],
        total_rows=len(rows),
        columns=["component", "kind", "contribution",
                 "share_of_net_change_pct", "meaning"],
        datasets=[cal.dataset_name(periods["opening"]),
                  cal.dataset_name(periods["closing"]), "cockpit_risk_curves"],
        period=f"{periods['opening']} to {periods['closing']}",
        purpose=("Which parameter group moved reported ECL between the two "
                 "quarters, allocated by exact Shapley value through the "
                 "governed calculator. This is a factor attribution, not a "
                 "breakdown by sector, and not a statement of real-world "
                 "cause."),
        duration_ms=int((time.perf_counter() - started) * 1000),
        plan={**_versions(), "method": found.method,
              "opening_ecl": round(found.opening_ecl, 6),
              "closing_ecl": round(found.closing_ecl, 6),
              "net_change": round(found.net_change, 6),
              "unit": found.unit, "currency": found.currency,
              "reconciled": found.reconciled, "residual": found.residual,
              "coverage": {"continuing": found.continuing_accounts,
                           "entered": found.entered_accounts,
                           "exited": found.exited_accounts},
              "shares_available": found.shares_available,
              "limitations": found.limitations,
              "by_facility": found.by_facility[:MAX_ROWS],
              "drill_down": {"dataset": "cockpit_credit_history",
                             "periods": [periods["opening"],
                                         periods["closing"]]}})


def decompose_movement(principal: Principal, **arguments: Any) -> Observation:
    """WHERE an additive measure moved, by member of one dimension."""
    started = time.perf_counter()
    tool = "decompose_movement"
    measure = schema_mod.resolve_measure(
        str(arguments.get("measure") or "reported_ecl")) or "reported_ecl"
    described = schema_mod.MEASURE_BY_NAME.get(measure, {})
    if described.get("aggregation") not in (schema_mod.ADDITIVE, None):
        return _refuse(
            tool, arguments,
            f"{measure} is declared {described.get('aggregation')} and cannot "
            f"be summed across members. Use decompose_ratio for a ratio, or "
            f"ask for its approved weighted form: "
            f"{described.get('approved_weight') or 'none declared'}.")

    dimension = str(arguments.get("dimension") or "sector")
    if dimension not in schema_mod.DIMENSION_NAMES:
        return _refuse(tool, arguments,
                       f"{dimension!r} is not a governed dimension. Available: "
                       f"{', '.join(schema_mod.DIMENSION_NAMES)}.")

    periods = _periods(principal, arguments)
    if not periods["available"]:
        return _refuse(tool, arguments, periods["reason"])
    try:
        opening = _filtered(periods["opening"], principal,
                            arguments.get("where"))
        closing = _filtered(periods["closing"], principal,
                            arguments.get("where"))
    except scope_mod.OutOfScope as e:
        return _refuse(tool, arguments, str(e))

    found = attr.decompose_movement(
        opening.groupby(dimension)[measure].sum().to_dict(),
        closing.groupby(dimension)[measure].sum().to_dict(),
        measure_name=measure, unit=described.get("unit", ""),
        opening_date=periods["opening_date"],
        closing_date=periods["closing_date"],
        top=int(arguments.get("top") or 0))

    return Observation(
        tool=tool, arguments=dict(arguments),
        rows=found["rows"][:MAX_ROWS], total_rows=found["rows_total"],
        columns=["member", "opening", "closing", "change",
                 "share_of_net_change", "membership"],
        datasets=[cal.dataset_name(periods["opening"]),
                  cal.dataset_name(periods["closing"])],
        period=f"{periods['opening']} to {periods['closing']}",
        purpose=(f"Where {measure} moved, by {dimension}. Amounts stay in "
                 f"{described.get('unit', '')}; a currency movement is not "
                 f"converted to basis points."),
        duration_ms=int((time.perf_counter() - started) * 1000),
        plan={**_versions(), "method": found["method"],
              "opening_total": found["opening_total"],
              "closing_total": found["closing_total"],
              "net_change": found["net_change"],
              "positive_contributions": found["positive_contributions"],
              "negative_contributions": found["negative_contributions"],
              "matched": found["matched"], "new": found["new"],
              "exited": found["exited"],
              "shares_available": found["shares_available"],
              "shares_note": found["shares_note"],
              "reconciled": found["reconciled"],
              "truncated": found["truncated"] or found["rows_total"] > MAX_ROWS,
              "unit": described.get("unit", ""),
              "limitations": found["limitations"]})


def decompose_ratio(principal: Principal, **arguments: Any) -> Observation:
    """A ratio movement split into a numerator and a denominator effect."""
    started = time.perf_counter()
    tool = "decompose_ratio"
    numerator = schema_mod.resolve_measure(
        str(arguments.get("numerator") or "reported_ecl")) or "reported_ecl"
    denominator = schema_mod.resolve_measure(
        str(arguments.get("denominator") or "exposure")) or "exposure"

    periods = _periods(principal, arguments)
    if not periods["available"]:
        return _refuse(tool, arguments, periods["reason"])
    try:
        opening = _filtered(periods["opening"], principal,
                            arguments.get("where"))
        closing = _filtered(periods["closing"], principal,
                            arguments.get("where"))
    except scope_mod.OutOfScope as e:
        return _refuse(tool, arguments, str(e))

    found = attr.decompose_ratio(
        numerator_opening=float(opening[numerator].sum()),
        numerator_closing=float(closing[numerator].sum()),
        denominator_opening=float(opening[denominator].sum()),
        denominator_closing=float(closing[denominator].sum()),
        ratio_name=f"{numerator} / {denominator}",
        opening_date=periods["opening_date"],
        closing_date=periods["closing_date"])
    if not found["available"]:
        return _refuse(tool, arguments, found["reason"])

    rows = [
        {"component": "numerator", "measure": numerator,
         "opening": found["numerator_opening"],
         "closing": found["numerator_closing"],
         "effect_bp": round(found["numerator_effect_scaled"], 4)},
        {"component": "denominator", "measure": denominator,
         "opening": found["denominator_opening"],
         "closing": found["denominator_closing"],
         "effect_bp": round(found["denominator_effect_scaled"], 4)},
    ]
    return Observation(
        tool=tool, arguments=dict(arguments), rows=rows, total_rows=2,
        columns=["component", "measure", "opening", "closing", "effect_bp"],
        datasets=[cal.dataset_name(periods["opening"]),
                  cal.dataset_name(periods["closing"])],
        period=f"{periods['opening']} to {periods['closing']}",
        purpose=("A ratio movement split exactly into a numerator effect and "
                 "a denominator effect. The two sum to the whole change; "
                 "there is no third mix term."),
        duration_ms=int((time.perf_counter() - started) * 1000),
        plan={**_versions(), "method": found["method"],
              "method_note": found["method_note"],
              "opening_ratio": found["opening_ratio"],
              "closing_ratio": found["closing_ratio"],
              "change_bp": found["change_scaled"], "unit": "basis points",
              "reconciled": found["reconciled"]})


def metric_history(principal: Principal, **arguments: Any) -> Observation:
    """A measure over the quarters actually published."""
    started = time.perf_counter()
    tool = "metric_history"
    measure = schema_mod.resolve_measure(
        str(arguments.get("measure") or "reported_ecl")) or "reported_ecl"
    described = schema_mod.MEASURE_BY_NAME.get(measure, {})
    try:
        quarters = reader.published_quarters(principal)
        frame = reader.history(principal)
    except (reader.NotPublished, scope_mod.OutOfScope) as e:
        return _refuse(tool, arguments, str(e))
    for clause in (arguments.get("where") or []):
        if isinstance(clause, dict) and clause.get("field") in frame.columns:
            frame = frame[frame[clause["field"]] == clause.get("value")]

    additive = described.get("aggregation") == schema_mod.ADDITIVE
    points = []
    for quarter in quarters:
        rows = frame[frame["period"] == quarter]
        if not len(rows):
            points.append((quarter, None))
        elif additive:
            points.append((quarter, float(rows[measure].sum())))
        else:
            # A non-additive measure is exposure-weighted, never averaged flat,
            # and the weight is reported so a reader can check it.
            weight = rows["ead"] if "ead" in rows.columns else None
            points.append((quarter, float(
                (rows[measure] * weight).sum() / weight.sum())
                if weight is not None and weight.sum() else float(
                    rows[measure].mean())))

    found = attr.metric_history(points, measure_name=measure,
                                unit=described.get("unit", ""))
    return Observation(
        tool=tool, arguments=dict(arguments), rows=found["points"],
        total_rows=len(found["points"]), columns=["period", "value"],
        datasets=["cockpit_credit_history"],
        period=f"{quarters[0]} to {quarters[-1]}" if quarters else "",
        purpose=(f"{measure} at each published quarter, with the latest "
                 f"compared against the preceding observations only."),
        duration_ms=int((time.perf_counter() - started) * 1000),
        plan={**_versions(), "unit": described.get("unit", ""),
              "aggregation": ("sum" if additive
                              else "exposure-weighted average"),
              "weight": ("" if additive else "ead"),
              "observations": found["observations"],
              "latest": found["latest"], "prior": found["prior"],
              "change": found["change"], "mean": found["mean"],
              "std_dev": found["std_dev"], "z_score": found["z_score"],
              "z_score_basis": found["z_score_basis"],
              "comparator_periods": found["comparator_periods"],
              "is_statistically_robust": found["is_statistically_robust"],
              "missing_periods": found["missing_periods"],
              "limitations": found["limitations"]})


def list_certified_analyses(principal: Principal, **arguments: Any) -> Observation:
    """Every capability the Cockpit can run, with its parameters.

    Free to call, permission-filtered, and bounded. Without it the model can
    only find a capability by guessing a name and reading the refusal, which
    costs a call out of the budget to learn something that never changes
    between questions.
    """
    started = time.perf_counter()
    from backend.cockpit_v2 import understand as understand_mod

    catalogue = [
        {"analysis_id": understand_mod.ECL_FACTOR_DECOMPOSITION,
         "purpose": "Reconciled opening-to-closing ECL bridge BY PARAMETER "
                    "GROUP. Not a sector breakdown.",
         "tool": "decompose_ecl_factors",
         "parameters": "from_period, to_period, where, top"},
        {"analysis_id": understand_mod.MOVEMENT_BY_DIMENSION,
         "purpose": "Where an additive measure moved, by dimension member.",
         "tool": "decompose_movement",
         "parameters": "measure, dimension, from_period, to_period, where, top"},
        {"analysis_id": understand_mod.RATIO_MOVEMENT,
         "purpose": "A ratio movement split into numerator and denominator "
                    "effects.",
         "tool": "decompose_ratio",
         "parameters": "numerator, denominator, from_period, to_period, where"},
        {"analysis_id": understand_mod.METRIC_HISTORY,
         "purpose": "A measure across the published quarters, with honest "
                    "statistics over a short series.",
         "tool": "metric_history", "parameters": "measure, where"},
        {"analysis_id": understand_mod.COMPOSITION,
         "purpose": "The current position by stage, sector, product or "
                    "geography. Not a movement.",
         "tool": "cockpit_answer", "parameters": "to_period, dimension, where"},
        {"analysis_id": understand_mod.SCENARIO_COMPARISON,
         "purpose": "Base, upturn, downturn and weighted ECL, and why the "
                    "weighted result sits where it does.",
         "tool": "cockpit_answer", "parameters": "to_period, where"},
        {"analysis_id": understand_mod.RATING_REVIEW,
         "purpose": "Rating movements by exposure and the financial ratios "
                    "behind them.",
         "tool": "cockpit_answer", "parameters": "to_period, from_period, where"},
        {"analysis_id": understand_mod.COVENANT_REVIEW,
         "purpose": "Covenant thresholds, observed values, headroom, breaches "
                    "and waiver validity.",
         "tool": "cockpit_answer", "parameters": "to_period, where"},
        {"analysis_id": understand_mod.COLLATERAL_REVIEW,
         "purpose": "Recognised collateral, allocation across shared assets, "
                    "valuation age and coverage.",
         "tool": "cockpit_answer", "parameters": "to_period, where"},
        {"analysis_id": understand_mod.STAGE_REVIEW,
         "purpose": "Stage migrations and the SICR rule that triggered each.",
         "tool": "cockpit_answer", "parameters": "to_period, from_period, where"},
        {"analysis_id": understand_mod.CONCENTRATION,
         "purpose": "Composition and concentration by sector, product, "
                    "geography and connected group.",
         "tool": "cockpit_answer", "parameters": "to_period, where"},
        {"analysis_id": understand_mod.MACRO_DEPENDENCY,
         "purpose": "Which macro predictors enter the declared model for a "
                    "sector, with coefficient and lag.",
         "tool": "cockpit_answer", "parameters": "sector"},
        {"analysis_id": understand_mod.DATA_QUALITY,
         "purpose": "Missing statements, stale ratings and valuations, "
                    "untested covenants.",
         "tool": "cockpit_answer", "parameters": "to_period, where"},
        {"analysis_id": understand_mod.DEFINITION,
         "purpose": "A governed definition. No investigation and no chart.",
         "tool": "cockpit_answer", "parameters": "term"},
    ]
    digest = scope_mod.describe(principal)
    return Observation(
        tool="list_certified_analyses", arguments=dict(arguments),
        rows=catalogue, total_rows=len(catalogue),
        columns=["analysis_id", "purpose", "tool", "parameters"],
        datasets=sorted(digest["scope"]["datasets"]),
        purpose=("Every Cockpit capability with its parameters, filtered to "
                 "what this principal may run."),
        duration_ms=int((time.perf_counter() - started) * 1000),
        plan={**_versions(), "catalogue_digest": digest})


# ------------------------------------------------------------- registration


def cockpit_tools() -> tuple[Any, ...]:
    """The Tool records, built lazily so importing this module is cheap."""
    from backend.analyst.tools import Tool

    return (
        Tool("decompose_ecl_factors",
             "Reconcile the movement in reported ECL between two quarters to "
             "the PARAMETER GROUPS that moved it: PD curves, recovery and "
             "LGD, exposure and EAD, staging horizon, scenario weights and "
             "discounting, plus entry, exit, overlay, FX and method change. "
             "This is what to call for 'what drove the ECL movement' or 'the "
             "impact of PD'. It is NOT a breakdown by sector.",
             RUN_ANALYSIS,
             {"from_period": "the opening quarter, e.g. '2026Q1'; empty means "
                             "the quarter before the closing one",
              "to_period": "the closing quarter; empty means the latest "
                           "published quarter",
              "where": "list of {field, op, value} over the facility snapshot",
              "top": "how many facilities to return in the drill-down"},
             (), decompose_ecl_factors),
        Tool("decompose_movement",
             "Where an ADDITIVE measure moved between two quarters, by member "
             "of one dimension, with opening, closing, change, signed share of "
             "the net movement, membership and reconciliation.",
             RUN_ANALYSIS,
             {"measure": "the governed measure, e.g. 'reported_ecl'",
              "dimension": "the dimension to break it down by, e.g. 'sector'",
              "from_period": "the opening quarter",
              "to_period": "the closing quarter",
              "where": "list of {field, op, value}",
              "top": "how many members to return"},
             (), decompose_movement),
        Tool("decompose_ratio",
             "Split a ratio movement exactly into a numerator effect and a "
             "denominator effect, in basis points. An NPL ratio rising "
             "because bad loans grew and one rising because the book shrank "
             "are different facts.",
             RUN_ANALYSIS,
             {"numerator": "the numerator measure",
              "denominator": "the denominator measure",
              "from_period": "the opening quarter",
              "to_period": "the closing quarter",
              "where": "list of {field, op, value}"},
             (), decompose_ratio),
        Tool("metric_history",
             "A measure at each published quarter, with the latest compared "
             "against the preceding observations only, and the observation "
             "count stated so a short series is not read as a robust one.",
             RUN_ANALYSIS,
             {"measure": "the governed measure",
              "where": "list of {field, op, value}"},
             (), metric_history),
        Tool("list_certified_analyses",
             "Every Cockpit capability with its purpose and parameters, "
             "filtered to what you may run. Call this rather than guessing an "
             "analysis id.",
             READ_METADATA, {}, (), list_certified_analyses, discovery=True),
    )


def install() -> list[str]:
    """Add the Cockpit tools to the analyst registry. Idempotent, flag-gated.

    Called from `backend.api.main`'s startup. With the switch off it does
    nothing and the registry is exactly what it was on the base commit, which
    is what `tests/cockpit_v2/test_flag_off.py` holds shut.
    """
    if not enabled():
        return []
    from backend.analyst import tools as analyst_tools

    existing = {tool.name for tool in analyst_tools.REGISTRY}
    added: list[str] = []
    for tool in cockpit_tools():
        if tool.name in existing:
            continue
        analyst_tools.REGISTRY = (*analyst_tools.REGISTRY, tool)
        analyst_tools.BY_NAME[tool.name] = tool
        added.append(tool.name)
    if added:
        logger.info("Cockpit V2 registered governed tools: %s",
                    ", ".join(added))
    return added


__all__ = ["MAX_ROWS", "cockpit_tools", "decompose_ecl_factors",
           "decompose_movement", "decompose_ratio", "install",
           "list_certified_analyses", "metric_history"]
