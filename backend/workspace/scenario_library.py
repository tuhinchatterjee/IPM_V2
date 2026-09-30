"""Scenario Definitions: typed components, governed translation, overlap and
composition, and a live preview that never calculates ECL.

A Scenario Definition (§30.1) is a first-class object independent of any
execution: scope (reusable template or a bound cohort), one or more typed
components, a stage policy, an explicit composition policy, the methods it is
compatible with, and lineage. This module owns everything about a definition
that can be decided WITHOUT running it:

* **normalise** -- every component is checked against the book's own field
  dictionary (`scenario.fields`), the operation vocabulary (`scenario.units`)
  and the grid's column allowlist. A component the book cannot support is
  kept and labelled, never silently dropped or substituted.
* **translate** -- macro, rating, score and property-collateral components
  are turned into parameter moves ONLY through governed artefacts published
  with the release: the MEV sensitivity library (`sensitivity.artifact`, the
  §7.2 linear form), the rating masterscale and the product scorecards.
  Anything with no governed mapping is NEEDS_USER_MAPPING.
* **overlap** -- two components that reach the same variable family (PD,
  LGD, exposure, ECL, delinquency) over intersecting populations overlap. The
  intersection is counted on the book, not assumed. Macro-with-macro is the
  governed linear sum and needs no choice; every other overlap blocks
  execution until an explicit policy is recorded (§30.3, SC-05).
* **preview** -- the scope's population (entities, owners, EAD, booked ECL,
  stage and band mix), each component's translation, the overlap matrix, the
  method availability (ML read from the emulator's own gates) and a readable
  equation beside the machine-readable contract. Nothing is calculated: the
  preview says so, and P6's METHOD_SELECTION gate is where execution starts.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import units as un
from backend.workspace import grid, predicates
from backend.workspace.access import Book

LIBRARY_VERSION = "gw-scenario-library-1.0.0"

KINDS = ("parameter", "utilisation", "rating", "score", "delinquency",
         "macro", "collateral", "overlay")

#: Composition policies a user may choose for an overlap (§30.3).
POLICIES = ("compound", "additive", "max", "min", "priority")
POLICY_TEXT = {
    "compound": "sequential / compound: apply in the stated order, each on "
                "the result of the one before",
    "additive": "additive: sum the moves (only where both are the same "
                "operation type)",
    "max": "most severe wins: the larger stressed value per exposure",
    "min": "least severe wins: the smaller stressed value per exposure",
    "priority": "priority / override: the first component in the stated "
                "order applies on the overlap, the other does not",
    "governed_linear_sum": "governed §7.2 linear sum of sensitivity x change "
                           "(macro with macro; not a user choice)",
}
GOVERNED = "governed_linear_sum"

STAGE_POLICIES = {
    "frozen": "Stages held at their reported values.",
    "retest_sicr": "Re-test SICR: stage moves are computed only where the "
                   "book publishes the lifetime figure and horizon "
                   "(scenario.mappings.stages); elsewhere UNSUPPORTED.",
    "cure_retest": "Cure re-test (upside): stage improvements are computed "
                   "only under the same published-horizon contract.",
}

SEVERITIES = ("upside", "mild", "moderate", "severe")

#: Variable family of each directly movable field.
FAMILY = {
    "pd_pit_12m": "pd", "pd_lifetime": "pd", "lgd_pct": "lgd",
    "ead_sar_mn": "exposure", "drawn_sar_mn": "exposure",
    "undrawn_sar_mn": "exposure", "balance_sar_mn": "exposure",
    "ccf": "exposure", "ccf_pit": "exposure", "limit_sar_mn": "exposure",
    "ecl_modelled_sar_mn": "ecl", "ecl_overlay_sar_mn": "ecl",
    "stage": "stage",
}

#: Delta's own parameter list and structural fields (`scenario.delta`).
DELTA_PARAMETERS = ("pd_pit_12m", "pd_lifetime", "lgd_pct", "ead_sar_mn",
                    "ccf")
DELTA_STRUCTURAL = {"corporate": ("drawn_sar_mn", "undrawn_sar_mn", "ccf"),
                    "retail": ("balance_sar_mn",)}

UTILISATION_TARGET = {"corporate": "drawn_sar_mn", "retail": "balance_sar_mn"}

COLLATERAL_FACTOR = {"residential_property": "MEV09",
                     "commercial_property": "MEV10"}

DELINQUENCY_ORDER = ("Current", "1-30", "31-60", "61-90", "90+")

MACRO_OPERATIONS = ("percentage_points", "basis_points", "relative_percent",
                    "index_points")

MACRO_PARAMETERS = ("pd_pit_12m", "pd_lifetime", "lgd_pct")

TOP_BY = ("ead_sar_mn", "ecl_sar_mn", "drawn_sar_mn", "balance_sar_mn")


def _b(domain_id: str) -> str:
    return "corp" if domain_id == "corporate" else "retail"


def _period_col(domain_id: str) -> str:
    return "reporting_quarter" if domain_id == "corporate" else \
        "reporting_month"


def _refuse(code: str, message: str, status: int = 422, **extra: Any):
    raise HTTPException(status, {"error_code": code, "message": message,
                                 **extra})


def _decimal(value: Any, where: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _refuse("INVALID_COMPONENT", f"{where}: {value!r} is not a number.")
    if not d.is_finite():
        _refuse("INVALID_COMPONENT", f"{where}: {value!r} is not finite.")
    return d


# ---- scope ----------------------------------------------------------------------

def normalise_scope(scope: Any, *, columns: list[str], depth: int = 0
                    ) -> dict[str, Any]:
    if not isinstance(scope, dict):
        _refuse("INVALID_SCOPE", "a scope is an object with a `type`.")
    kind = scope.get("type")
    label = str(scope.get("label") or "")[:200]
    if kind == "whole_book":
        return {"type": "whole_book", "label": label or "Whole active book"}
    if kind == "filters":
        checked = predicates.normalise(scope.get("filters") or [],
                                       columns=columns)
        if not checked:
            _refuse("INVALID_SCOPE", "a filter scope needs at least one "
                                     "filter; use `whole_book` for the "
                                     "whole book.")
        return {"type": "filters", "label": label or
                predicates.describe(checked), "filters": checked}
    if kind == "top_owners":
        try:
            n = int(scope.get("n"))
        except (TypeError, ValueError):
            _refuse("INVALID_SCOPE", "`n` must be a whole number.")
        if not 1 <= n <= 500:
            _refuse("INVALID_SCOPE", "`n` must be between 1 and 500.")
        by = str(scope.get("by") or "ead_sar_mn")
        if by not in TOP_BY or by not in columns:
            _refuse("INVALID_SCOPE", f"`by` must be one of "
                                     f"{[c for c in TOP_BY if c in columns]}.")
        return {"type": "top_owners", "n": n, "by": by,
                "label": label or f"Top {n} by {by}"}
    if kind == "any_of":
        if depth > 1:
            _refuse("INVALID_SCOPE", "`any_of` scopes nest at most once.")
        parts = scope.get("scopes") or []
        if not isinstance(parts, list) or len(parts) < 2 or len(parts) > 8:
            _refuse("INVALID_SCOPE", "`any_of` needs 2-8 scopes.")
        return {"type": "any_of", "label": label or "Any of",
                "scopes": [normalise_scope(p, columns=columns, depth=depth + 1)
                           for p in parts]}
    if kind == "cohort":
        cid = str(scope.get("cohort_id") or "")
        if not cid.startswith("coh-"):
            _refuse("INVALID_SCOPE", "a cohort scope names a cohort id.")
        return {"type": "cohort", "cohort_id": cid,
                "cohort_version": int(scope.get("cohort_version") or 0),
                "label": label or f"Cohort {cid}",
                "filters": predicates.normalise(scope.get("filters") or [],
                                                columns=columns),
                "membership_hash": str(scope.get("membership_hash") or "")}
    _refuse("INVALID_SCOPE", f"{kind!r} is not a scope type. Scope types: "
                             f"whole_book, filters, top_owners, any_of, "
                             f"cohort.")
    raise AssertionError  # pragma: no cover


def scope_sql(scope: dict[str, Any], v: grid.View) -> tuple[str, list[Any]]:
    """A boolean SQL fragment over the grid view `g`, with bound params."""
    kind = scope["type"]
    if kind == "whole_book":
        return "TRUE", []
    if kind in ("filters", "cohort"):
        if not scope.get("filters"):
            return "TRUE", []
        sql, params = predicates.bound(scope["filters"])
        return f"({sql})", params
    if kind == "top_owners":
        # `n` and `by` are validated above; both are literals from an
        # allowlist, never user text.
        return (f"({v.owner} IN (SELECT {v.owner} FROM ({v.sql}) t GROUP BY 1 "
                f"ORDER BY SUM({scope['by']}) DESC, 1 LIMIT {int(scope['n'])}"
                f"))"), []
    if kind == "any_of":
        parts, params = [], []
        for sub in scope["scopes"]:
            s, p = scope_sql(sub, v)
            parts.append(s)
            params.extend(p)
        return "(" + " OR ".join(parts) + ")", params
    raise AssertionError(kind)  # pragma: no cover


def where_sql(where: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    if not where:
        return "TRUE", []
    sql, params = predicates.bound(where)
    return f"({sql})", params


def component_sql(c: dict[str, Any], v: grid.View) -> tuple[str, list[Any]]:
    """The component's own population inside the definition's scope."""
    w_sql, w_params = where_sql(c.get("where") or [])
    if not c.get("within"):
        return w_sql, w_params
    s_sql, s_params = scope_sql(c["within"], v)
    return f"({s_sql} AND {w_sql})", [*s_params, *w_params]


# ---- components -----------------------------------------------------------------

def _field(domain_id: str, field_id: str) -> fd.Field | None:
    for f in fd.fields_for(domain_id):
        if f.field_id == field_id:
            return f
    return None


def normalise_component(raw: Any, *, domain_id: str, columns: list[str],
                        index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _refuse("INVALID_COMPONENT", f"component {index} is not an object.")
    kind = raw.get("kind")
    if kind not in KINDS:
        _refuse("INVALID_COMPONENT", f"component {index}: {kind!r} is not a "
                                     f"component kind. Kinds: {KINDS}.")
    cid = str(raw.get("component_id") or f"c{index}")[:40]
    out: dict[str, Any] = {
        "component_id": cid, "kind": kind,
        "label": str(raw.get("label") or "")[:200],
        "priority": int(raw.get("priority") or index),
        "where": predicates.normalise(raw.get("where") or [], columns=columns),
    }
    if raw.get("within"):
        # A component carried from another scenario keeps that scenario's
        # scope exactly (any scope type), ANDed with its own filters.
        out["within"] = normalise_scope(raw["within"], columns=columns)
    if raw.get("source"):
        out["source"] = {k: raw["source"].get(k) for k in
                         ("object_id", "version", "component_id", "scenario")}
    op = str(raw.get("operation") or "")
    value = raw.get("value")
    if kind == "parameter":
        field_id = str(raw.get("field") or "")
        if op not in un.OPERATIONS:
            _refuse("INVALID_COMPONENT",
                    f"component {cid}: {op!r} is not an operation. They are "
                    f"{un.OPERATIONS}; relative percent, percentage points "
                    f"and basis points are never interchangeable.")
        out.update(field=field_id, operation=op,
                   value=str(_decimal(value, cid)))
    elif kind in ("utilisation", "overlay"):
        if op != "relative_pct":
            _refuse("INVALID_COMPONENT", f"component {cid}: a {kind} move is "
                                         f"a relative percent.")
        out.update(operation=op, value=str(_decimal(value, cid)))
    elif kind == "rating":
        n = _decimal(value, cid)
        if op != "notches" or n % 1 != 0 or n == 0 or abs(n) > 6:
            _refuse("INVALID_COMPONENT", f"component {cid}: a rating move is "
                                         f"a whole number of notches (1-6; "
                                         f"positive is a downgrade).")
        out.update(operation="notches", value=str(int(n)))
    elif kind == "score":
        st = str(raw.get("score_type") or "").upper()
        if st not in ("BEHAVIOURAL", "APPLICATION"):
            _refuse("INVALID_COMPONENT", f"component {cid}: score_type is "
                                         f"BEHAVIOURAL or APPLICATION; one "
                                         f"is never substituted for the "
                                         f"other.")
        if op not in ("points", "bands"):
            _refuse("INVALID_COMPONENT", f"component {cid}: a score move is "
                                         f"in points or scorecard bands.")
        d = _decimal(value, cid)
        if op == "bands" and (d % 1 != 0 or d == 0):
            _refuse("INVALID_COMPONENT", f"component {cid}: bands move by a "
                                         f"whole number.")
        out.update(score_type=st, operation=op, value=str(d))
    elif kind == "delinquency":
        d = _decimal(value, cid)
        if op != "bands" or d % 1 != 0 or d == 0:
            _refuse("INVALID_COMPONENT", f"component {cid}: delinquency moves "
                                         f"by a whole number of bands.")
        out.update(operation="bands", value=str(int(d)))
    elif kind == "macro":
        fid = str(raw.get("factor_id") or "")
        if not (fid.startswith("MEV") and fid[3:].isdigit()):
            _refuse("INVALID_COMPONENT", f"component {cid}: {fid!r} is not a "
                                         f"factor id.")
        if op not in MACRO_OPERATIONS:
            _refuse("INVALID_COMPONENT", f"component {cid}: macro moves are "
                                         f"{MACRO_OPERATIONS}.")
        out.update(factor_id=fid, operation=op,
                   value=str(_decimal(value, cid)))
    elif kind == "collateral":
        asset = str(raw.get("asset") or "")
        if asset not in ("residential_property", "commercial_property",
                         "vehicle"):
            _refuse("INVALID_COMPONENT", f"component {cid}: collateral asset "
                                         f"is residential_property, "
                                         f"commercial_property or vehicle.")
        if op != "relative_pct":
            _refuse("INVALID_COMPONENT", f"component {cid}: a collateral "
                                         f"value move is a relative percent.")
        out.update(asset=asset, operation=op, value=str(_decimal(value, cid)))
    if not out["label"]:
        out["label"] = describe_component(out)
    return out


def describe_component(c: dict[str, Any]) -> str:
    kind, v = c["kind"], c.get("value", "")
    sign = "" if str(v).startswith("-") else "+"
    if kind == "parameter":
        unit = {"relative_pct": "% relative", "absolute_pp": " pp",
                "basis_points": " bps", "multiply": "x", "set_to": " (set)",
                "points": " points", "notches": " notches",
                "absolute_amount": " SAR mn"}.get(c["operation"], "")
        return f"{c['field']} {sign}{v}{unit}"
    if kind == "utilisation":
        return f"Utilisation {sign}{v}% (limit fixed)"
    if kind == "rating":
        return f"Rating {'-' if int(v) > 0 else '+'}{abs(int(v))} notch(es)"
    if kind == "score":
        return f"{c['score_type'].title()} score {sign}{v} {c['operation']}"
    if kind == "delinquency":
        return f"Delinquency {sign}{v} band(s)"
    if kind == "macro":
        return f"{c['factor_id']} {sign}{v} {c['operation'].replace('_', ' ')}"
    if kind == "collateral":
        return f"{c['asset'].replace('_', ' ')} value {sign}{v}%"
    if kind == "overlay":
        return f"User overlay {sign}{v}% ECL"
    return kind


def normalise_definition(raw: dict[str, Any], *, book: Book
                         ) -> dict[str, Any]:
    """The definition body, checked against THIS book. Refuses, never fixes."""
    v = grid.view(book)
    cols = list(v.keys)
    domain = book.domain_id
    if raw.get("domain_id") and raw["domain_id"] != domain:
        _refuse("DOMAIN_MISMATCH", f"this definition is for "
                                   f"{raw['domain_id']}; the book open is "
                                   f"{domain}.")
    comps = raw.get("components") or []
    if not isinstance(comps, list) or not comps:
        _refuse("INVALID_DEFINITION", "a scenario needs at least one "
                                      "component.")
    if len(comps) > 12:
        _refuse("INVALID_DEFINITION", "at most 12 components per scenario.")
    normalised = [normalise_component(c, domain_id=domain, columns=cols,
                                      index=i)
                  for i, c in enumerate(comps, 1)]
    ids = [c["component_id"] for c in normalised]
    if len(set(ids)) != len(ids):
        _refuse("INVALID_DEFINITION", "component ids must be unique.")
    stage = str(raw.get("stage_policy") or "frozen")
    if stage not in STAGE_POLICIES:
        _refuse("INVALID_DEFINITION", f"stage policy is one of "
                                      f"{list(STAGE_POLICIES)}.")
    severity = str(raw.get("severity") or "moderate")
    if severity not in SEVERITIES:
        _refuse("INVALID_DEFINITION", f"severity is one of {SEVERITIES}.")
    comp_policy = raw.get("composition_policy") or {}
    resolutions = {}
    for key, res in (comp_policy.get("resolutions") or {}).items():
        resolutions[str(key)] = _normalise_resolution(res, ids)
    methods = [m for m in (raw.get("supported_methods") or
                           ["delta", "ml", "user_defined"])
               if m in ("delta", "ml", "user_defined")]
    name = str(raw.get("name") or "").strip()
    if not name:
        _refuse("INVALID_DEFINITION", "a scenario needs a name.")
    return {
        "name": name[:160],
        "description": str(raw.get("description") or "")[:2000],
        "risk_thesis": str(raw.get("risk_thesis") or "")[:2000],
        "domain_id": domain,
        "scope": normalise_scope(raw.get("scope") or {"type": "whole_book"},
                                 columns=cols),
        "components": normalised,
        "stage_policy": stage,
        "composition_policy": {"resolutions": resolutions,
                               "note": str(comp_policy.get("note") or "")[:600]},
        "supported_methods": methods,
        "severity": severity,
        "tags": [str(t)[:40] for t in (raw.get("tags") or [])][:20],
        "assumptions": [str(a)[:400] for a in (raw.get("assumptions") or [])],
        "limitations": [str(a)[:400] for a in (raw.get("limitations") or [])],
        "bounds_policy": dict(raw.get("bounds_policy") or {}),
        "baseline": dict(raw.get("baseline") or {"kind": "reported"}),
        "bound_cohort": raw.get("bound_cohort"),
        "template_id": str(raw.get("template_id") or ""),
        "status": str(raw.get("status") or "DRAFT"),
        "parents": list(raw.get("parents") or []),
        "library_version": LIBRARY_VERSION,
        **({"seed_version": raw["seed_version"]}
           if raw.get("seed_version") else {}),
    }


def _normalise_resolution(res: Any, ids: list[str]) -> dict[str, Any]:
    if not isinstance(res, dict):
        _refuse("INVALID_COMPOSITION", "a resolution is an object with a "
                                       "`policy`.")
    policy = str(res.get("policy") or "")
    if policy not in POLICIES:
        _refuse("INVALID_COMPOSITION", f"{policy!r} is not a composition "
                                       f"policy. Choose one of {POLICIES}; "
                                       f"none is assumed.")
    order = [str(o) for o in (res.get("order") or [])]
    unknown = [o for o in order if o not in ids]
    if unknown:
        _refuse("INVALID_COMPOSITION", f"order names unknown components "
                                       f"{unknown}.")
    return {"policy": policy, "order": order,
            "chosen_by": str(res.get("chosen_by") or "user")[:80]}


# ---- governed translation -------------------------------------------------------

def _pop(book: Book, v: grid.View, cond: str, params: list[Any]
         ) -> dict[str, Any]:
    row = book.rows(
        f"SELECT COUNT(*) AS n, COUNT(DISTINCT {v.owner}) AS owners, "
        f"COALESCE(SUM(ead_sar_mn),0) AS ead, COALESCE(SUM(ecl_sar_mn),0) AS "
        f"ecl, AVG(pd_pit_12m) AS pd, AVG(lgd_pct) AS lgd FROM ({v.sql}) g "
        f"WHERE {cond}", params)[0]
    return {"entities": int(row["n"] or 0), "owners": int(row["owners"] or 0),
            "ead": float(row["ead"] or 0), "ecl": float(row["ecl"] or 0),
            "mean_pd": _f(row["pd"]), "mean_lgd_pct": _f(row["lgd"])}


def _f(x: Any) -> float | None:
    if x is None:
        return None
    f = float(x)
    return None if math.isnan(f) else f


def _macro_registry(book: Book, factor_id: str) -> dict[str, Any] | None:
    b = _b(book.domain_id)
    rows = book.rows(
        f"SELECT factor_id, factor_name, shock_convention, native_unit, "
        f"availability, absent_reason FROM whatif_{b}_mev_registry WHERE "
        f"factor_id = ? LIMIT 1", [factor_id])
    return rows[0] if rows else None


def _macro_level(book: Book, factor_id: str) -> tuple[float | None, str]:
    b = _b(book.domain_id)
    pc = _period_col(book.domain_id)
    table = f"whatif_{b}_macro_{'quarter' if b == 'corp' else 'month'}"
    rows = book.rows(
        f"SELECT value, {pc} AS period FROM {table} WHERE factor_id = ? AND "
        f"scenario_id = 'baseline' AND observation_status = 'ACTUAL' "
        f"ORDER BY {pc} DESC LIMIT 1", [factor_id])
    if not rows:
        return None, ""
    return _f(rows[0]["value"]), str(rows[0]["period"])


def _slopes(book: Book, factor_id: str) -> list[dict[str, Any]]:
    b = _b(book.domain_id)
    return book.rows(f"SELECT * FROM whatif_{b}_sensitivity WHERE factor_id = "
                     f"? ORDER BY parameter", [factor_id])


def _native_change(convention: str, op: str, value: float,
                   level: float | None) -> tuple[float | None, str]:
    """The factor move in the factor's own native units, or a refusal."""
    if convention in ("percentage_points", "basis_points"):
        if op == "percentage_points":
            return value, f"{value:+g} percentage points"
        if op == "basis_points":
            return value / 100.0, (f"{value:+g} bps = {value / 100.0:+g} "
                                   f"percentage points")
        return None, (f"this factor moves in {convention}; a "
                      f"{op.replace('_', ' ')} move is not converted.")
    if convention in ("relative_percent", "index_points"):
        if op == "index_points" and convention == "index_points":
            return value, f"{value:+g} index points"
        if op == "relative_percent":
            if level is None:
                return None, "no observed level to convert a relative move."
            return level * value / 100.0, (
                f"{value:+g}% of the latest observed level {level:g} = "
                f"{level * value / 100.0:+.4g} native units")
        return None, (f"this factor moves in {convention}; a "
                      f"{op.replace('_', ' ')} move is not converted.")
    return None, f"unknown shock convention {convention!r}."


def translate_macro(book: Book, factor_id: str, op: str, value: float, *,
                    parameters: tuple[str, ...] = MACRO_PARAMETERS,
                    baseline: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """A macro move through the governed sensitivity library (§7.2)."""
    from backend.cockpit_v4.scenario.sensitivity import artifact

    reg = _macro_registry(book, factor_id)
    if reg is None:
        return {"status": "UNSUPPORTED", "reason": f"{factor_id} is not in "
                f"this book's MEV registry.", "derived": [], "excluded": []}
    if str(reg["availability"]).upper() != "PRESENT":
        return {"status": "UNSUPPORTED", "factor_name": reg["factor_name"],
                "reason": f"{reg['factor_name']} is not published for this "
                          f"book ({reg.get('absent_reason') or 'ABSENT'}).",
                "derived": [], "excluded": []}
    level, level_period = _macro_level(book, factor_id)
    change, conversion = _native_change(str(reg["shock_convention"]), op,
                                        value, level)
    out: dict[str, Any] = {
        "factor_id": factor_id, "factor_name": reg["factor_name"],
        "shock_convention": reg["shock_convention"],
        "native_unit": reg["native_unit"], "level": level,
        "level_period": level_period, "conversion": conversion,
        "derived": [], "excluded": [], "warnings": []}
    if change is None:
        return {**out, "status": "UNSUPPORTED", "reason": conversion}
    base = level if level is not None else 0.0
    for row in _slopes(book, factor_id):
        param = str(row["parameter"])
        if param not in parameters:
            continue
        readiness = str(row["readiness"])
        if readiness != "SUPPORTED_ESTIMATE":
            out["excluded"].append({
                "parameter": param, "readiness": readiness,
                "reason": str(row.get("limitation") or "") or
                "not a supported estimate; not applied automatically. State "
                "the parameter change as your own assumption to use it."})
            continue
        slope = artifact.from_row({**row, "source_fingerprint":
                                   row.get("source_fingerprint", "")})
        pbase = None
        if baseline:
            if param == "lgd_pct" and baseline.get("mean_lgd_pct") is not None:
                pbase = baseline["mean_lgd_pct"] / 100.0
            elif param.startswith("pd") and baseline.get("mean_pd") is not None:
                pbase = baseline["mean_pd"]
        t = artifact.translate(slope, factor_baseline=base,
                               factor_scenario=base + change,
                               parameter_baseline=pbase)
        out["warnings"].extend(t.warnings)
        out["derived"].append({
            "field": param, "operation": "absolute_pp",
            "value": f"{t.parameter_change_pp:.6f}",
            "native_derivative": slope.native_derivative,
            "native_derivative_unit": slope.native_derivative_unit,
            "lag": slope.lag, "factor_change": change,
            "parameter_baseline": t.parameter_baseline,
            "parameter_scenario": t.parameter_scenario,
            "artifact_version": slope.artifact_version,
            "readiness": readiness})
    out["status"] = "TRANSLATED" if out["derived"] else "UNSUPPORTED"
    if not out["derived"]:
        out["reason"] = (f"no supported sensitivity of "
                         f"{'/'.join(parameters)} to {reg['factor_name']} in "
                         f"this book.")
    return out


def translate_rating(book: Book, v: grid.View, cond: str, params: list[Any],
                     notches: int) -> dict[str, Any]:
    """Along the published masterscale (grade_rank), never the string."""
    scale = book.rows("SELECT rating_grade, grade_rank, pd_12m, pd_lifetime, "
                      "is_default_grade, mapping_version FROM "
                      "whatif_corp_rating_map ORDER BY grade_rank")
    by_grade = {r["rating_grade"]: r for r in scale}
    live = [r for r in scale if not r["is_default_grade"]]
    worst = max(r["grade_rank"] for r in live)
    by_rank = {r["grade_rank"]: r for r in live}
    counts = book.rows(
        f"SELECT rating_current AS grade, COUNT(*) AS n, SUM(ead_sar_mn) AS "
        f"ead FROM ({v.sql}) g WHERE {cond} GROUP BY 1", params)
    moves, capped = [], 0
    for c in sorted(counts, key=lambda r: by_grade.get(r["grade"], {})
                    .get("grade_rank", 99)):
        cur = by_grade.get(c["grade"])
        if cur is None:
            moves.append({"from": c["grade"], "to": None, "n": int(c["n"]),
                          "status": "UNMAPPED"})
            continue
        target = cur["grade_rank"] + notches
        hit_cap = target > worst
        target = min(max(target, 1), worst)
        new = by_rank[target]
        if hit_cap:
            capped += int(c["n"])
        ratio = new["pd_12m"] / cur["pd_12m"] if cur["pd_12m"] else None
        moves.append({"from": c["grade"], "to": new["rating_grade"],
                      "n": int(c["n"]), "ead": float(c["ead"] or 0),
                      "map_pd_from": cur["pd_12m"], "map_pd_to": new["pd_12m"],
                      "pd_relative_factor": ratio,
                      "status": "CAPPED_AT_WORST_LIVE_GRADE" if hit_cap
                      else "MOVED"})
    return {"status": "TRANSLATED", "mapping_version":
            scale[0]["mapping_version"] if scale else "",
            "moves": moves, "capped": capped,
            "rule": "Each borrower moves along the published grade_rank; its "
                    "PD moves by the ratio of the two grades' mapped PDs. A "
                    "notch past the worst live grade is capped there and "
                    "counted -- it is not a default.",
            "derived": [{"field": "pd_pit_12m", "operation": "multiply",
                         "value": "per-grade ratio (see moves)"}]}


def translate_score(book: Book, v: grid.View, cond: str, params: list[Any],
                    *, score_type: str, operation: str, value: Decimal
                    ) -> dict[str, Any]:
    """Through the governed product scorecards; the two scores stay apart."""
    column = "behaviour_score" if score_type == "BEHAVIOURAL" else \
        "application_score"
    product_key = "g.product" if score_type == "BEHAVIOURAL" else "'ALL'"
    period = book.latest_period
    smap = (f"(SELECT * FROM whatif_retail_score_map WHERE score_type = ? AND "
            f"reporting_month = ?)")
    idx = (f"(SELECT *, ROW_NUMBER() OVER (PARTITION BY product ORDER BY "
           f"band_low) AS ix FROM {smap} m0)")
    # The scope is applied INSIDE a subquery so its unqualified columns bind
    # to the grid view alone; parameters follow the SQL's textual order.
    scoped = f"(SELECT * FROM ({v.sql}) g0 WHERE {cond})"
    head = (f"SELECT a.band_label AS band_from, b.band_label AS band_to, "
            f"COUNT(*) AS n, AVG(a.pd_12m) AS pd_from, AVG(b.pd_12m) AS pd_to "
            f"FROM {scoped} g ")
    if operation == "points":
        new_score = f"LEAST(GREATEST(g.{column} + ?, 0), 100000)"
        sql = (head +
               f"LEFT JOIN {smap} a ON a.product = {product_key} AND "
               f"g.{column} >= a.band_low AND g.{column} < a.band_high + 1 "
               f"LEFT JOIN {smap} b ON b.product = {product_key} AND "
               f"{new_score} >= b.band_low AND {new_score} < b.band_high + 1 "
               f"GROUP BY 1, 2 ORDER BY 1, 2")
        args = [*params, score_type, period, score_type, period,
                float(value), float(value)]
    else:
        sql = (head +
               f"LEFT JOIN {idx} a ON a.product = {product_key} AND "
               f"g.{column} >= a.band_low AND g.{column} < a.band_high + 1 "
               f"LEFT JOIN {idx} b ON b.product = a.product AND b.ix = "
               f"GREATEST(a.ix + ?, 1) "
               f"GROUP BY 1, 2 ORDER BY 1, 2")
        args = [*params, score_type, period, score_type, period, int(value)]
    rows = book.rows(sql, args)
    direction = book.rows("SELECT DISTINCT direction, scorecard_version FROM "
                          "whatif_retail_score_map WHERE score_type = ?",
                          [score_type])
    moved = sum(int(r["n"]) for r in rows
                if r["band_from"] != r["band_to"] and r["band_to"])
    unmapped = sum(int(r["n"]) for r in rows if not r["band_from"])
    status = "TRANSLATED" if score_type == "BEHAVIOURAL" else \
        "TRANSLATION_ONLY"
    return {
        "status": status, "score_type": score_type, "column": column,
        "direction": direction[0]["direction"] if direction else "",
        "scorecard_version": direction[0]["scorecard_version"]
        if direction else "",
        "band_moves": [{"from": r["band_from"], "to": r["band_to"],
                        "n": int(r["n"]), "map_pd_from": _f(r["pd_from"]),
                        "map_pd_to": _f(r["pd_to"])} for r in rows],
        "accounts_changing_band": moved, "unmapped": unmapped,
        "rule": ("One band = one governed scorecard band (a published "
                 "row, matched half-open [band_low, band_high + 1) so a "
                 "fractional score is never lost between rows). Direction "
                 "is read from the scorecard metadata, never assumed."),
        "derived": [{"field": "pd_pit_12m", "operation": "multiply",
                     "value": "per-band ratio of mapped PDs"}]
        if status == "TRANSLATED" else [],
        **({"reason": "The application score is fixed at origination: its "
                      "band PD is shown for information, and executing it "
                      "needs a user-defined impact."}
           if status == "TRANSLATION_ONLY" else {}),
    }


def translate_delinquency(book: Book, v: grid.View, cond: str,
                          params: list[Any], bands: int) -> dict[str, Any]:
    rows = book.rows(f"SELECT delinquency_bucket AS b, COUNT(*) AS n FROM "
                     f"({v.sql}) g WHERE {cond} GROUP BY 1", params)
    moves = []
    for r in rows:
        b = r["b"]
        if b in DELINQUENCY_ORDER:
            i = min(max(DELINQUENCY_ORDER.index(b) + bands, 0),
                    len(DELINQUENCY_ORDER) - 1)
            moves.append({"from": b, "to": DELINQUENCY_ORDER[i],
                          "n": int(r["n"])})
        else:
            moves.append({"from": b, "to": None, "n": int(r["n"])})
    return {"status": "NEEDS_USER_MAPPING", "moves": moves,
            "reason": "No governed delinquency-to-PD mapping is published. "
                      "The band movement is shown; the PD effect must be "
                      "stated as a user-defined impact before it can run.",
            "derived": []}


# ---- per-component assessment ---------------------------------------------------

def assess_component(book: Book, v: grid.View, c: dict[str, Any], *,
                     scope_cond: str, scope_params: list[Any]
                     ) -> dict[str, Any]:
    """Status, target families, method compatibility and translation."""
    domain = book.domain_id
    w_sql, w_params = component_sql(c, v)
    cond = f"{scope_cond} AND {w_sql}"
    params = [*scope_params, *w_params]
    population = _pop(book, v, cond, params)
    kind = c["kind"]
    res: dict[str, Any] = {"component_id": c["component_id"], "kind": kind,
                           "label": c["label"], "population": population,
                           "families": [], "methods": {}, "translation": None}
    delta_ok = False
    ml_ok = False
    if kind == "parameter":
        f = _field(domain, c["field"])
        if f is None or f.availability == fd.ABSENT:
            res.update(status="UNSUPPORTED", reason=(
                f.absent_note if f is not None else
                f"{c['field']!r} is not a field of the {domain} book."))
        elif not f.mutable:
            res.update(status="UNSUPPORTED",
                       reason=f"{c['field']} is not a movable field.")
        else:
            res["status"] = "DIRECT"
            res["families"] = [FAMILY.get(c["field"], "other")]
            delta_ok = ("delta" in f.methods and (
                c["field"] in DELTA_PARAMETERS
                or c["field"] in DELTA_STRUCTURAL.get(domain, ())))
            ml_ok = c["field"] in ("pd_pit_12m", "pd_lifetime", "lgd_pct",
                                   "ead_sar_mn")
            res["translation"] = {"field": c["field"], "unit": f.unit,
                                  "operation": c["operation"],
                                  "value": c["value"],
                                  "delta_submode": "structural_ead"
                                  if c["field"] in DELTA_STRUCTURAL.get(
                                      domain, ()) and c["field"]
                                  not in DELTA_PARAMETERS else "proportional"}
    elif kind == "utilisation":
        target = UTILISATION_TARGET[domain]
        res.update(status="DIRECT", families=["exposure"])
        delta_ok = True
        res["translation"] = {
            "field": target, "operation": "relative_pct", "value": c["value"],
            "delta_submode": "structural_ead",
            "rule": f"Utilisation = {target} / limit with the limit held, so "
                    f"utilisation {c['value']}% relative is {target} "
                    f"{c['value']}% relative."}
    elif kind == "rating":
        if domain != "corporate":
            res.update(status="UNSUPPORTED",
                       reason="Retail carries scores, not ratings.")
        else:
            res["translation"] = translate_rating(book, v, cond, params,
                                                  int(c["value"]))
            res.update(status="TRANSLATED", families=["pd"])
            delta_ok = ml_ok = True
    elif kind == "score":
        if domain != "retail":
            res.update(status="UNSUPPORTED",
                       reason="Corporate carries ratings, not scores.")
        else:
            t = translate_score(book, v, cond, params,
                                score_type=c["score_type"],
                                operation=c["operation"],
                                value=Decimal(c["value"]))
            res["translation"] = t
            res.update(status=t["status"], families=["pd"])
            delta_ok = ml_ok = t["status"] == "TRANSLATED"
            if t.get("reason"):
                res["reason"] = t["reason"]
    elif kind == "delinquency":
        if "delinquency_bucket" not in v.keys:
            res.update(status="UNSUPPORTED", reason="This book publishes no "
                                                    "delinquency bucket.")
        else:
            t = translate_delinquency(book, v, cond, params, int(c["value"]))
            res.update(status=t["status"], translation=t,
                       families=["delinquency", "pd"], reason=t["reason"])
    elif kind == "macro":
        t = translate_macro(book, c["factor_id"], c["operation"],
                            float(c["value"]), baseline=population)
        res["translation"] = t
        res["status"] = t["status"]
        if t["status"] == "UNSUPPORTED":
            res["reason"] = t.get("reason", "")
        res["families"] = sorted({FAMILY[d["field"]] for d in t["derived"]})
        delta_ok = ml_ok = bool(t["derived"])
    elif kind == "collateral":
        factor = COLLATERAL_FACTOR.get(c["asset"])
        if factor is None:
            res.update(status="NEEDS_USER_MAPPING", families=["lgd"], reason=(
                "No governed index or sensitivity exists for this collateral "
                "type in this book; state the LGD effect to run it."))
        else:
            t = translate_macro(book, factor, "relative_percent",
                                float(c["value"]), parameters=("lgd_pct",),
                                baseline=population)
            t["rule"] = (f"The collateral value move is read as the same "
                         f"relative move in {t.get('factor_name', factor)} "
                         f"and translated to LGD only.")
            falling = float(c["value"]) < 0
            for d in t["derived"]:
                if falling and float(d["value"]) < 0:
                    t["warnings"].append(
                        f"SIGN_REVIEW: the governed slope moves LGD DOWN "
                        f"({float(d['value']):+.3f} pp) when collateral "
                        f"values fall. It is the fitted artefact's sign on "
                        f"this synthetic history and is shown, not "
                        f"corrected; review before relying on it or state "
                        f"your own LGD effect.")
                    res["sign_review"] = True
            res["translation"] = t
            res["status"] = t["status"]
            res["families"] = ["lgd"]
            if t["status"] == "UNSUPPORTED":
                res["reason"] = t.get("reason", "")
            delta_ok = ml_ok = bool(t["derived"])
    elif kind == "overlay":
        res.update(status="USER_DEFINED", families=["ecl"], reason=(
            "An overlay is the user's own impact assumption; it runs under "
            "the User-defined method only and is never estimated."))
    res["methods"] = {
        "delta": "COMPATIBLE" if delta_ok else "NOT_COMPATIBLE",
        "ml": "COMPATIBLE" if ml_ok else "NOT_COMPATIBLE",
        "user_defined": "COMPATIBLE"
        if res.get("status") != "UNSUPPORTED" else "NOT_COMPATIBLE",
    }
    return res


# ---- overlap and composition ----------------------------------------------------

def overlap_matrix(book: Book, v: grid.View, components: list[dict[str, Any]],
                   assessed: dict[str, dict[str, Any]], *, scope_cond: str,
                   scope_params: list[Any],
                   resolutions: dict[str, Any]) -> list[dict[str, Any]]:
    """Every pair of components, with overlap status and the policy in force."""
    out = []
    for i, a in enumerate(components):
        for b in components[i + 1:]:
            fa = set(assessed[a["component_id"]]["families"])
            fb = set(assessed[b["component_id"]]["families"])
            shared = sorted(fa & fb)
            wa, pa = component_sql(a, v)
            wb, pb = component_sql(b, v)
            n = int(book.rows(
                f"SELECT COUNT(*) AS n FROM ({v.sql}) g WHERE {scope_cond} AND "
                f"{wa} AND {wb}", [*scope_params, *pa, *pb])[0]["n"] or 0)
            base = {"a": a["component_id"], "b": b["component_id"],
                    "a_label": a["label"], "b_label": b["label"],
                    "shared_entities": n, "variables": shared}
            if not shared:
                out.append({**base, "status": "NO_CONFLICT",
                            "reason": "different variables"})
                continue
            if n == 0:
                out.append({**base, "status": "NO_CONFLICT",
                            "reason": "disjoint populations"})
                continue
            for family in shared:
                oid = overlap_id(a["component_id"], b["component_id"], family)
                if a["kind"] == "macro" and b["kind"] == "macro":
                    out.append({**base, "overlap_id": oid, "variable": family,
                                "status": "RESOLVED_BY_GOVERNED_RULE",
                                "policy": GOVERNED,
                                "policy_text": POLICY_TEXT[GOVERNED]})
                    continue
                chosen = resolutions.get(oid)
                allowed = allowed_policies(a, b)
                if chosen and chosen["policy"] not in allowed:
                    out.append({**base, "overlap_id": oid, "variable": family,
                                "status": "INVALID_POLICY",
                                "policy": chosen["policy"],
                                "allowed": allowed,
                                "reason": "additive is valid only for two "
                                          "moves of the same operation type"})
                elif chosen:
                    out.append({**base, "overlap_id": oid, "variable": family,
                                "status": "RESOLVED", **chosen,
                                "policy_text": POLICY_TEXT[chosen["policy"]],
                                "allowed": allowed})
                else:
                    out.append({**base, "overlap_id": oid, "variable": family,
                                "status": "NEEDS_POLICY", "allowed": allowed,
                                "reason": f"both reach {family} on {n:,} "
                                          f"shared entities; choose a "
                                          f"composition policy -- none is "
                                          f"assumed."})
    return out


def overlap_id(a: str, b: str, family: str) -> str:
    x, y = sorted((a, b))
    return f"{x}|{y}|{family}"


def _op_class(c: dict[str, Any]) -> str:
    if c["kind"] == "parameter":
        return c["operation"]
    if c["kind"] in ("utilisation", "overlay", "collateral"):
        return "relative_pct"
    if c["kind"] == "macro":
        return "absolute_pp"
    return c["kind"]


def allowed_policies(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    allowed = ["compound", "max", "min", "priority"]
    if _op_class(a) == _op_class(b) and _op_class(a) in (
            "relative_pct", "absolute_pp", "basis_points"):
        allowed.insert(1, "additive")
    return allowed


# ---- methods --------------------------------------------------------------------

def method_availability(book: Book, assessed: list[dict[str, Any]],
                        requested: list[str]) -> dict[str, Any]:
    from backend.cockpit_v4.scenario.ml import infer

    passed, failures, version = infer.gate_status(
        book.domain_id, release_id=book.release_id)
    out: dict[str, Any] = {}
    runnable = [a for a in assessed if a["status"] != "UNSUPPORTED"]
    for method in ("delta", "ml", "user_defined"):
        covered = [a["component_id"] for a in runnable
                   if a["methods"][method] == "COMPATIBLE"]
        missing = [a["component_id"] for a in runnable
                   if a["methods"][method] != "COMPATIBLE"]
        if method == "ml" and not passed:
            out[method] = {"status": "UNAVAILABLE", "model_version": version,
                           "reason": "ML emulator validation gate failed: "
                                     + "; ".join(failures) +
                                     ". Shown, never substituted."}
            continue
        if method == "user_defined":
            out[method] = {"status": "NEEDS_ASSUMPTION" if runnable else
                           "NOT_APPLICABLE",
                           "reason": "The user states the ECL impact; "
                                     "missing inputs trigger a targeted "
                                     "clarification, never a guess."}
            continue
        if not runnable:
            status = "NOT_APPLICABLE"
        elif not missing:
            status = "AVAILABLE"
        elif covered:
            status = "PARTIAL"
        else:
            status = "NOT_COMPATIBLE"
        out[method] = {"status": status, "covers": covered,
                       "does_not_cover": missing,
                       **({"model_version": version} if method == "ml"
                          else {})}
    for m in out:
        out[m]["requested"] = m in requested
    out["selected"] = None
    out["note"] = ("No method is selected by a definition. Execution enters "
                   "METHOD_SELECTION and waits for an explicit choice.")
    return out


# ---- preview --------------------------------------------------------------------

def equation(defn: dict[str, Any]) -> str:
    comps = " ; ".join(c["label"] for c in defn["components"])
    return (f"[{defn['scope']['label']}] : {comps} | stage policy "
            f"{defn['stage_policy']}")


def contract_hash(defn: dict[str, Any]) -> str:
    """What could change a number; name and prose excluded."""
    body = {k: defn[k] for k in ("domain_id", "scope", "components",
                                 "stage_policy", "composition_policy",
                                 "bounds_policy", "baseline")}
    body["composition_policy"] = {"resolutions": body["composition_policy"]
                                  ["resolutions"]}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def preview(book: Book, defn: dict[str, Any]) -> dict[str, Any]:
    v = grid.view(book)
    scope = defn["scope"]
    scope_cond, scope_params = scope_sql(scope, v)
    summary = grid.summary(book, v=v, where=f"WHERE {scope_cond}",
                           params=scope_params)
    book_total = grid.summary(book, v=v, where="", params=[])
    assessed = [assess_component(book, v, c, scope_cond=scope_cond,
                                 scope_params=scope_params)
                for c in defn["components"]]
    by_id = {a["component_id"]: a for a in assessed}
    matrix = overlap_matrix(book, v, defn["components"], by_id,
                            scope_cond=scope_cond, scope_params=scope_params,
                            resolutions=defn["composition_policy"]
                            ["resolutions"])
    methods = method_availability(book, assessed,
                                  defn.get("supported_methods") or [])
    blocking = []
    if summary["entities"] == 0:
        blocking.append({"code": "EMPTY_SCOPE", "message":
                         "The scope selects no exposures in this book."})
    for m in matrix:
        if m["status"] in ("NEEDS_POLICY", "INVALID_POLICY"):
            blocking.append({"code": "NEEDS_COMPOSITION_POLICY",
                             "overlap_id": m["overlap_id"],
                             "message": f"{m['a_label']} and {m['b_label']} "
                                        f"both reach {m['variable']} on "
                                        f"{m['shared_entities']:,} entities."})
    unsupported = [a for a in assessed if a["status"] == "UNSUPPORTED"]
    needs_mapping = [a for a in assessed if a["status"] in (
        "NEEDS_USER_MAPPING", "TRANSLATION_ONLY", "USER_DEFINED")]
    for a in unsupported:
        blocking.append({"code": "UNSUPPORTED_COMPONENT",
                         "component_id": a["component_id"],
                         "message": f"{a['label']}: {a.get('reason', '')}"})
    if blocking:
        readiness = "BLOCKED"
    elif needs_mapping:
        readiness = "READY_WITH_USER_DEFINED_INPUTS"
    else:
        readiness = "READY_FOR_CONFIRMATION"
    return {
        "calculated": False,
        "statement": "Nothing has been calculated. This is the definition "
                     "resolved against the book: population, translations, "
                     "overlaps and which methods could run. Execution starts "
                     "only after confirmation and an explicit method choice.",
        "domain_id": book.domain_id, "release_id": book.release_id,
        "fingerprint": book.fingerprint, "period": book.latest_period,
        "scope": {**scope, "summary": summary,
                  "share_of_book_ead": summary["ead"] / book_total["ead"]
                  if book_total["ead"] else None,
                  "share_of_book_ecl": summary["ecl"] / book_total["ecl"]
                  if book_total["ecl"] else None,
                  "book": {"entities": book_total["entities"],
                           "ead": book_total["ead"],
                           "ecl": book_total["ecl"]}},
        "components": assessed, "overlaps": matrix, "methods": methods,
        "stage_policy": {"policy": defn["stage_policy"],
                         "text": STAGE_POLICIES[defn["stage_policy"]]},
        "blocking": blocking, "readiness": readiness,
        "equation": equation(defn), "contract": {
            k: defn[k] for k in ("domain_id", "scope", "components",
                                 "stage_policy", "composition_policy",
                                 "bounds_policy", "baseline")},
        "contract_hash": contract_hash(defn),
        "library_version": LIBRARY_VERSION,
    }


# ---- composition ----------------------------------------------------------------

def combine(sources: list[dict[str, Any]], *, name: str,
            resolutions: dict[str, Any] | None = None,
            description: str = "") -> dict[str, Any]:
    """Scenario A + B (+ C ...) -> a NEW definition; sources are not touched.

    Each source's components keep their own scope as a component-level
    `where` (the combined scope is the union of the sources' scopes), carry a
    prefixed id (`A.c1`), and name their source object and version.
    """
    if len(sources) < 2:
        _refuse("INVALID_COMPOSITION", "combining needs at least two "
                                       "scenarios.")
    domains = {s["body"]["domain_id"] for s in sources}
    if len(domains) != 1:
        _refuse("INVALID_COMPOSITION", "scenarios from different books do "
                                       "not combine.")
    comps, scopes, parents = [], [], []
    letters = "ABCDEFGH"
    whole = False
    for i, s in enumerate(sources):
        tag = letters[i]
        body = s["body"]
        sc = body["scope"]
        if sc["type"] == "whole_book":
            whole = True
        elif sc["type"] == "any_of":
            scopes.extend(sc["scopes"])
        else:
            scopes.append(sc)
        for c in body["components"]:
            nc = dict(c)
            nc["component_id"] = f"{tag}.{c['component_id']}"
            nc["source"] = {"object_id": s["object_id"],
                            "version": s["version"],
                            "component_id": c["component_id"],
                            "scenario": body["name"]}
            if sc["type"] != "whole_book":
                nc["within"] = sc
            comps.append(nc)
        parents.append({"object_id": s["object_id"], "version": s["version"],
                        "name": body["name"], "content_hash":
                        s.get("content_hash", "")})
    if whole:
        scope = {"type": "whole_book", "label": "Whole active book (union)"}
    elif len(scopes) == 1:
        scope = scopes[0]
    else:
        unique = []
        for sc in scopes:
            if sc not in unique:
                unique.append(sc)
        if len(unique) > 8:
            _refuse("INVALID_COMPOSITION", "the union of these scopes has "
                                           "more than 8 parts; bind the "
                                           "combined scenario to a cohort.")
        scope = unique[0] if len(unique) == 1 else {
            "type": "any_of", "label": " + ".join(x["label"] for x in unique),
            "scopes": unique}
    first = sources[0]["body"]
    severities = [s["body"].get("severity", "moderate") for s in sources]
    return {
        "name": name, "domain_id": first["domain_id"],
        "description": description or "Combined from " + ", ".join(
            p["name"] for p in parents) + ".",
        "risk_thesis": " / ".join(s["body"].get("risk_thesis", "")
                                  for s in sources if s["body"].get(
                                      "risk_thesis"))[:2000],
        "scope": scope, "components": comps,
        "stage_policy": "retest_sicr" if any(
            s["body"]["stage_policy"] != "frozen" for s in sources)
        else "frozen",
        "composition_policy": {"resolutions": resolutions or {},
                               "note": "Combined scenario: every overlap "
                                       "needs an explicit policy."},
        "supported_methods": sorted({m for s in sources for m in
                                     s["body"]["supported_methods"]}),
        "severity": max(severities, key=SEVERITIES.index),
        "tags": sorted({t for s in sources for t in s["body"]["tags"]}
                       | {"combined"})[:20],
        "assumptions": [a for s in sources for a in s["body"]["assumptions"]],
        "limitations": [a for s in sources for a in s["body"]["limitations"]],
        "bounds_policy": {}, "baseline": {"kind": "reported"},
        "bound_cohort": None, "template_id": "", "status": "DRAFT",
        "parents": parents,
    }


__all__ = ["KINDS", "LIBRARY_VERSION", "POLICIES", "SEVERITIES",
           "STAGE_POLICIES", "allowed_policies", "assess_component", "combine",
           "contract_hash", "equation", "normalise_definition",
           "component_sql", "overlap_id", "overlap_matrix", "preview", "scope_sql",
           "translate_macro"]
