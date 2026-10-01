"""
Evaluate governed metrics over the book in use. No model, no ad-hoc SQL.

A book metric is its catalogue `num`/`den` aggregate over the governed grid
view (`grid.view`) for one period, optionally grouped by one governed
dimension and narrowed by typed filters (bound as parameters). Deltas compare
two published periods of the same book. Named evaluators cover what is not a
single aggregate: ranked concentration, borrower-level rating migration,
customer-level score movement and EWS populations, published sensitivities,
data quality, scenario results and monitoring state.

Results carry their provenance: metric id and version, release, fingerprint,
period, filters, numerator, denominator, row count and the SQL shape used --
so a KPI on a Lens can always say exactly what it is.
"""

from __future__ import annotations

import contextvars
import json
import time
from typing import Any

from fastapi import HTTPException

from backend.workspace import grid, predicates
from backend.workspace import metric_catalog as mc
from backend.workspace.access import Book

_CACHE: dict[tuple, Any] = {}
_CACHE_MAX = 4000


def _key(book: Book, *parts: Any) -> tuple:
    return (book.tenant_id, book.domain_id, book.release_id, book.fingerprint,
            json.dumps(parts, sort_keys=True, default=str))


def _cached(key: tuple, compute):
    if key in _CACHE:
        return _CACHE[key]
    value = compute()
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = value
    return value


def clear_cache() -> None:
    _CACHE.clear()


def _metric(metric_id: str, domain_id: str) -> dict[str, Any]:
    metric = mc.BY_ID.get(metric_id)
    if metric is None:
        raise HTTPException(404, {"error_code": "UNKNOWN_METRIC",
                                  "message": f"{metric_id!r} is not in the "
                                             f"metric catalogue."})
    if not mc.applies(metric, domain_id):
        raise HTTPException(422, {"error_code": "METRIC_NOT_APPLICABLE",
                                  "message": f"{metric_id} ({metric['name']}) "
                                             f"is defined for "
                                             f"{metric['domain']} only."})
    return metric


def _where(v: grid.View, filters: Any) -> tuple[str, list[Any]]:
    checked = predicates.normalise(filters, columns=v.keys)
    sql, params = predicates.bound(checked)
    return (f"WHERE {sql}" if sql else ""), params


def _ratio(num: Any, den: Any) -> float | None:
    if num is None:
        return None
    if den is None:
        return float(num)
    den = float(den)
    return None if den == 0 else float(num) / den


def _base_value(book: Book, metric: dict[str, Any], *, period: str,
                filters: Any, group_by: str = "") -> Any:
    v = grid.view(book, period)
    where, params = _where(v, filters)
    num = metric["num_sql"]
    den = metric["den_sql"]
    select = f"{num} AS num" + (f", {den} AS den" if den else "")
    if group_by:
        if group_by not in v.keys:
            raise HTTPException(422, {"error_code": "INVALID_DIMENSION",
                                      "message": f"{group_by!r} is not a "
                                                 f"governed dimension."})
        rows = book.rows(
            f"SELECT {group_by} AS dim, {select}, COUNT(*) AS n FROM "
            f"({v.sql}) g {where} GROUP BY 1 ORDER BY 1", params)
        return [{"dimension": r["dim"],
                 "value": _ratio(r["num"], r.get("den") if den else None),
                 "numerator": _f(r["num"]),
                 "denominator": _f(r.get("den")) if den else None,
                 "rows": int(r["n"])} for r in rows]
    row = book.rows(f"SELECT {select}, COUNT(*) AS n FROM ({v.sql}) g {where}",
                    params)[0]
    return {"value": _ratio(row["num"], row.get("den") if den else None),
            "numerator": _f(row["num"]),
            "denominator": _f(row.get("den")) if den else None,
            "rows": int(row["n"])}


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


# ---- named evaluators ----------------------------------------------------------

def _owner(book: Book) -> str:
    return grid.SPEC[book.domain_id]["owner"]


def _ev_top_n_share(book, metric, *, period, filters, n=10):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    owner = _owner(book)
    row = book.rows(
        f"WITH o AS (SELECT {owner} AS k, SUM(ead_sar_mn) AS e FROM "
        f"({v.sql}) g {where} GROUP BY 1) SELECT (SELECT SUM(e) FROM (SELECT "
        f"e FROM o ORDER BY e DESC LIMIT {int(n)})) AS num, SUM(e) AS den, "
        f"COUNT(*) AS n FROM o", params)[0]
    return {"value": _ratio(row["num"], row["den"]), "numerator": _f(row["num"]),
            "denominator": _f(row["den"]), "rows": int(row["n"])}


def _ev_largest_name_share(book, metric, *, period, filters):
    return _ev_top_n_share(book, metric, period=period, filters=filters, n=1)


def _ev_segment_share(book, metric, *, period, filters):
    dim = "sector" if book.domain_id == "corporate" else "product"
    v = grid.view(book, period)
    where, params = _where(v, filters)
    rows = book.rows(
        f"SELECT {dim} AS dim, SUM(ead_sar_mn) AS e FROM ({v.sql}) g {where} "
        f"GROUP BY 1 ORDER BY 2 DESC", params)
    total = sum(float(r["e"] or 0) for r in rows)
    return {"value": None, "numerator": None, "denominator": total,
            "rows": len(rows),
            "groups": [{"dimension": r["dim"], "value": _ratio(r["e"], total),
                        "numerator": _f(r["e"])} for r in rows]}


def _ev_rating_migration_rate(book, metric, *, period, filters):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    sign = ">" if metric["metric_id"] == "M023" else "<"
    extra = "AND" if where else "WHERE"
    row = book.rows(
        f"SELECT COUNT(DISTINCT CASE WHEN rating_notches_moved {sign} 0 THEN "
        f"borrower_id END) AS num, COUNT(DISTINCT borrower_id) AS den FROM "
        f"({v.sql}) g {where} {extra} rating_previous IS NOT NULL", params)[0]
    return {"value": _ratio(row["num"], row["den"]),
            "numerator": _f(row["num"]), "denominator": _f(row["den"]),
            "rows": int(row["den"] or 0)}


def _ev_avg_notch_movement(book, metric, *, period, filters):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    extra = "AND" if where else "WHERE"
    row = book.rows(
        f"WITH b AS (SELECT DISTINCT borrower_id, rating_notches_moved FROM "
        f"({v.sql}) g {where} {extra} rating_previous IS NOT NULL) SELECT "
        f"SUM(rating_notches_moved) AS num, COUNT(*) AS den FROM b", params)[0]
    return {"value": _ratio(row["num"], row["den"]),
            "numerator": _f(row["num"]), "denominator": _f(row["den"]),
            "rows": int(row["den"] or 0)}


def _ev_avg_score_movement(book, metric, *, period, filters):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    row = book.rows(
        f"WITH c AS (SELECT DISTINCT customer_id, behaviour_score_change FROM "
        f"({v.sql}) g {where}) SELECT SUM(behaviour_score_change) AS num, "
        f"COUNT(behaviour_score_change) AS den FROM c", params)[0]
    return {"value": _ratio(row["num"], row["den"]),
            "numerator": _f(row["num"]), "denominator": _f(row["den"]),
            "rows": int(row["den"] or 0)}


def _ev_application_score_distribution(book, metric, *, period, filters):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    rows = book.rows(
        f"SELECT CAST(FLOOR(application_score / 100) * 100 AS INTEGER) AS band,"
        f" COUNT(DISTINCT customer_id) AS n FROM ({v.sql}) g {where} GROUP BY 1"
        f" ORDER BY 1", params)
    total = sum(int(r["n"]) for r in rows if r["band"] is not None)
    return {"value": total, "numerator": total, "denominator": None,
            "rows": total,
            "groups": [{"dimension": f"{r['band']}-{r['band'] + 99}",
                        "value": int(r["n"]), "numerator": int(r["n"])}
                       for r in rows if r["band"] is not None]}


def _ev_owner_where(book, *, period, filters, condition: str):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    extra = "AND" if where else "WHERE"
    owner = _owner(book)
    row = book.rows(f"SELECT COUNT(DISTINCT {owner}) AS n FROM ({v.sql}) g "
                    f"{where} {extra} {condition}", params)[0]
    return int(row["n"] or 0)


def _ev_ews_owners(book, metric, *, period, filters):
    n = _ev_owner_where(book, period=period, filters=filters,
                        condition="ews_band <> 'none'")
    return {"value": n, "numerator": n, "denominator": None, "rows": n}


def _ev_ews_severe_share(book, metric, *, period, filters):
    warned = _ev_owner_where(book, period=period, filters=filters,
                             condition="ews_band <> 'none'")
    severe = _ev_owner_where(book, period=period, filters=filters,
                             condition="ews_band IN ('high', 'critical')")
    return {"value": _ratio(severe, warned), "numerator": severe,
            "denominator": warned, "rows": warned}


def _ev_forward_risk_owners(book, metric, *, period, filters):
    n = _ev_owner_where(book, period=period, filters=filters, condition=(
        "stage = 1 AND prior_pd_pit_12m > 0 AND pd_pit_12m >= "
        "prior_pd_pit_12m * 1.2"))
    return {"value": n, "numerator": n, "denominator": None, "rows": n}


def _ev_deteriorated_customers(book, metric, *, period, filters):
    n = _ev_owner_where(book, period=period, filters=filters,
                        condition="score_migration = 'Deteriorated'")
    return {"value": n, "numerator": n, "denominator": None, "rows": n}


def _ev_owner_count(book, metric, *, period, filters):
    n = _ev_owner_where(book, period=period, filters=filters, condition="1=1")
    return {"value": n, "numerator": n, "denominator": None, "rows": n}


_SENS = {"corporate": "whatif_corp_sensitivity",
         "retail": "whatif_retail_sensitivity"}


def sensitivity_rows(book: Book) -> list[dict[str, Any]]:
    relation = _SENS[book.domain_id]
    if relation not in set(getattr(book.session, "relations", ()) or ()):
        return []
    return book.rows(
        f"SELECT s.factor_id, r.factor_name, s.parameter, s.lag, s.coefficient,"
        f" s.native_derivative, s.native_derivative_unit, s.std_error, "
        f"s.ci_low, s.ci_high, s.sign_stability, s.readiness, s.method, "
        f"s.training_periods, s.validation_periods, s.train_start, "
        f"s.train_end, s.limitation, s.transformation, s.standardised_response,"
        f" s.reference_parameter_value, s.reference_factor_value, "
        f"r.native_unit, r.shock_convention, s.artifact_id, s.artifact_version "
        f"FROM {relation} s LEFT JOIN {relation.replace('sensitivity', 'mev_registry')}"
        f" r ON r.factor_id = s.factor_id ORDER BY ABS(s.standardised_response)"
        f" DESC NULLS LAST")


def _ev_sensitivity_coefficient(book, metric, *, period, filters):
    rows = sensitivity_rows(book)
    return {"value": len(rows), "numerator": None, "denominator": None,
            "rows": len(rows),
            "groups": [{"dimension": f"{r['factor_id']}·{r['parameter']}",
                        "value": _f(r["coefficient"]),
                        "readiness": r["readiness"], "lag": r["lag"],
                        "method": r["method"]} for r in rows]}


def _ev_sensitivity_stability(book, metric, *, period, filters):
    rows = sensitivity_rows(book)
    return {"value": len(rows), "numerator": None, "denominator": None,
            "rows": len(rows),
            "groups": [{"dimension": f"{r['factor_id']}·{r['parameter']}",
                        "value": _f(r["sign_stability"]),
                        "readiness": r["readiness"]} for r in rows]}


REQUIRED_FIELDS = ("ead_sar_mn", "ecl_sar_mn", "stage", "pd_pit_12m",
                   "lgd_pct", "limit_sar_mn")


def _ev_completeness(book, metric, *, period, filters):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    fields = [f for f in REQUIRED_FIELDS if f in v.keys]
    nonnull = " + ".join(f"COUNT({f})" for f in fields)
    row = book.rows(f"SELECT {nonnull} AS num, COUNT(*) * {len(fields)} AS den"
                    f" FROM ({v.sql}) g {where}", params)[0]
    return {"value": _ratio(row["num"], row["den"]),
            "numerator": _f(row["num"]), "denominator": _f(row["den"]),
            "rows": int((row["den"] or 0) / max(len(fields), 1)),
            "required_fields": fields}


def _ev_freshness(book, metric, *, period, filters):
    """Hours since the release in use was published in THIS runtime.

    Basis, stated: the manifest's own `built_at` when the release records
    one, else the manifest file's modification time on this machine (the
    moment `lake.publish` wrote it). Never a guess and never 0.
    """
    from datetime import datetime

    from backend.cockpit_v4 import lake

    manifest = lake.read_manifest(book.release_id)
    built = str(manifest.get("built_at") or "")
    basis = "manifest.built_at"
    stamp = None
    if built:
        try:
            stamp = datetime.fromisoformat(built.replace("Z", "+00:00")
                                           ).timestamp()
        except ValueError:
            stamp = None
    if stamp is None:
        path = lake.root() / book.release_id / "manifest.json"
        if path.exists():
            stamp = path.stat().st_mtime
            basis = "manifest file time on this machine (publication here)"
    if stamp is None:
        return {"value": None, "numerator": None, "denominator": None,
                "rows": 0, "status": "UNAVAILABLE",
                "note": "The release records no publication time."}
    hours = (time.time() - stamp) / 3600.0
    return {"value": hours, "numerator": hours, "denominator": None,
            "rows": 1, "basis": basis}


def _ev_reconciliation_residual(book, metric, *, period, filters):
    v = grid.view(book, period)
    where, params = _where(v, filters)
    row = book.rows(
        f"SELECT SUM(ecl_sar_mn) AS total, SUM(CASE WHEN stage = 1 THEN "
        f"ecl_sar_mn ELSE 0 END) + SUM(CASE WHEN stage = 2 THEN ecl_sar_mn "
        f"ELSE 0 END) + SUM(CASE WHEN stage = 3 THEN ecl_sar_mn ELSE 0 END) "
        f"AS parts FROM ({v.sql}) g {where}", params)[0]
    residual = float(row["total"] or 0) - float(row["parts"] or 0)
    return {"value": residual, "numerator": _f(row["total"]),
            "denominator": _f(row["parts"]), "rows": 1}


#: Who is looking. Scenario results are objects with their own permissions:
#: a metric over them counts only what the viewer may open. With no viewer
#: set, only tenant-visible results are counted (the safe default).
VIEWER: contextvars.ContextVar[Any] = contextvars.ContextVar("metric_viewer",
                                                             default=None)


def _scenario_results(book: Book) -> list[dict[str, Any]]:
    from backend.workspace import service
    from backend.workspace.objects import can_read

    viewer = VIEWER.get()
    try:
        rows = service.store().latest_of_kind(
            "scenario_result", tenant_id=book.tenant_id,
            domain_id=book.domain_id)
    except Exception:  # noqa: BLE001 - no store outside a running app
        return []
    if viewer is None:
        return [r for r in rows if (r.get("permissions") or {}).get(
            "visibility") == "tenant"]
    return [r for r in rows if can_read(r, viewer)]


_PREFERRED = ("delta", "user_defined", "ml")


def _scenario_groups(book: Book, pick) -> list[dict[str, Any]]:
    """One group per persisted Scenario Result on this book, newest first,
    read from its published decomposition (nothing is recomputed). `pick`
    maps (method, decomposition, result body) to the value or None."""
    rows = sorted(_scenario_results(book), key=lambda r: -r["created_at"])
    out = []
    for r in rows:
        b = r["body"]
        decomp = b.get("decomposition") or {}
        method = next((m for m in _PREFERRED if m in decomp), "")
        if not method:
            continue
        value = pick(method, decomp[method], b)
        out.append({"dimension": f"{b.get('scenario_name', r['title'])} · "
                                 f"{r['object_id']}",
                    "value": value, "object_id": r["object_id"],
                    "method": method, "period": b.get("period", ""),
                    "baseline": (b.get("baseline") or {}).get("mode", "")})
    return out


def _scenario_value(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline is the most recent result's value; every result is a
    group (scenario, method and baseline ids travel with it)."""
    latest = next((g for g in groups if g["value"] is not None), None)
    return {"value": None if latest is None else latest["value"],
            "numerator": None, "denominator": None, "rows": len(groups),
            "groups": groups,
            "latest_result": None if latest is None else latest["object_id"]}


def _num(x: Any) -> float | None:
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def _ev_scenario_delta(book, metric, *, period, filters):
    return _scenario_value(_scenario_groups(
        book, lambda m, d, b: _num(d["scopes"]["selected"]["change"])))


def _ev_scenario_delta_pct(book, metric, *, period, filters):
    def pct(m, d, b):
        opening = _num(d["scopes"]["selected"]["opening"])
        change = _num(d["scopes"]["selected"]["change"])
        if opening is None or change is None or opening <= 0:
            return None
        return change / opening
    return _scenario_value(_scenario_groups(book, pct))


def _ev_scope_contribution(book, metric, *, period, filters):
    def share(m, d, b):
        total = _num(d["cross_scope"]["total_delta"])
        sel = _num(d["cross_scope"]["selected_delta"])
        if not total or sel is None:
            return None
        return sel / total
    return _scenario_value(_scenario_groups(book, share))


def _ev_calibration_gap(book, metric, *, period, filters):
    """Method 2 only: raw emulator baseline minus observed modelled ECL,
    as each ML result published it. Results without ML are not groups."""
    rows = sorted(_scenario_results(book), key=lambda r: -r["created_at"])
    groups = []
    for r in rows:
        ml = (r["body"].get("results") or {}).get("ml") or {}
        if not ml.get("ran"):
            continue
        groups.append({"dimension": f"{r['body'].get('scenario_name')} · "
                                    f"{r['object_id']}",
                       "value": _num(ml.get("calibration_gap")),
                       "object_id": r["object_id"], "method": "ml",
                       "period": r["body"].get("period", ""),
                       "baseline": (r["body"].get("baseline") or {}).get(
                           "mode", "")})
    return _scenario_value(groups)


def _ev_active_breaches(book, metric, *, period, filters):
    from backend.workspace import service
    from backend.workspace.objects import can_read

    try:
        alerts = service.store().latest_of_kind("alert",
                                                tenant_id=book.tenant_id)
    except Exception:  # noqa: BLE001
        alerts = []
    viewer = VIEWER.get()
    live = [a for a in alerts
            if a["status"] in ("NEW", "ACTIVE", "WORSENING")
            and a["body"].get("alert_type") == "breach"
            and not a["body"].get("demo_historical")
            and a["domain_id"] in (book.domain_id, "both")
            and (can_read(a, viewer) if viewer is not None else
                 (a.get("permissions") or {}).get("visibility") == "tenant")]
    by_lens: dict[str, int] = {}
    for a in live:
        name = a["body"].get("lens_name") or a["body"].get("lens_id", "")
        by_lens[name] = by_lens.get(name, 0) + 1
    n = len(live)
    return {"value": n, "numerator": n, "denominator": None, "rows": n,
            "groups": [{"dimension": k, "value": v}
                       for k, v in sorted(by_lens.items(),
                                          key=lambda kv: -kv[1])]}


def _ev_ews_reasons(book, metric, *, period, filters):
    """One group per governed EWS rule of this book: the exposures and EAD
    that trigger it (the rule's own SQL over the same view). An exposure
    with several reasons counts under each; `value` is the number of
    exposures with at least one."""
    from backend.workspace import ews

    v = grid.view(book, period)
    where, params = _where(v, filters)
    extra = "AND" if where else "WHERE"
    groups, skipped = [], []
    for rule in ews.RULES[book.domain_id]:
        if not ews._columns(rule["sql"]) <= set(v.keys):
            skipped.append(rule["id"])
            continue
        row = book.rows(f"SELECT COUNT(*) AS n, SUM(ead_sar_mn) AS ead FROM "
                        f"({v.sql}) g {where} {extra} ({rule['sql']})",
                        params)[0]
        groups.append({"dimension": rule["label"], "rule_id": rule["id"],
                       "value": int(row["n"] or 0),
                       "numerator": _f(row["ead"]) or 0.0,
                       "limitation": rule.get("limitation", "")})
    groups.sort(key=lambda g: -g["value"])
    any_row = book.rows(f"SELECT COUNT(*) AS n FROM ({v.sql}) g {where} "
                        f"{extra} ews_band <> 'none'", params)[0]
    return {"value": int(any_row["n"] or 0), "numerator": None,
            "denominator": None, "rows": int(any_row["n"] or 0),
            "groups": groups, "rules_not_evaluated": skipped,
            "ruleset": ews.RULESET_VERSION}


def _visible_alerts(book) -> list[dict[str, Any]]:
    """Breach alerts on this book the viewer may open (any state)."""
    from backend.workspace import service
    from backend.workspace.objects import can_read

    try:
        alerts = service.store().latest_of_kind("alert",
                                                tenant_id=book.tenant_id)
    except Exception:  # noqa: BLE001
        return []
    viewer = VIEWER.get()
    return [a for a in alerts
            if a["body"].get("alert_type") == "breach"
            and not a["body"].get("demo_historical")
            and a["domain_id"] in (book.domain_id, "both")
            and (can_read(a, viewer) if viewer is not None else
                 (a.get("permissions") or {}).get("visibility") == "tenant")]


ALERT_STATES = ("NEW", "ACTIVE", "WORSENING", "ACKNOWLEDGED", "RESOLVED")
_LIVE = ("NEW", "ACTIVE", "WORSENING")


def _count_by(items: list[dict[str, Any]], key) -> list[dict[str, Any]]:
    by: dict[str, int] = {}
    for a in items:
        k = key(a)
        by[k] = by.get(k, 0) + 1
    return [{"dimension": k, "value": n}
            for k, n in sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))]


def _ev_alerts_by_state(book, metric, *, period, filters):
    alerts = _visible_alerts(book)
    by = {s: 0 for s in ALERT_STATES}
    for a in alerts:
        by[a["status"]] = by.get(a["status"], 0) + 1
    return {"value": len(alerts), "numerator": len(alerts),
            "denominator": None, "rows": len(alerts),
            "groups": [{"dimension": s, "value": n} for s, n in by.items()]}


def _ev_breaches_by_metric(book, metric, *, period, filters):
    live = [a for a in _visible_alerts(book) if a["status"] in _LIVE]
    groups = _count_by(live, lambda a: str(a["body"].get("metric_id") or "?"))
    for g in groups:
        g["name"] = mc.BY_ID.get(g["dimension"], {}).get("name", "")
    return {"value": len(live), "numerator": len(live), "denominator": None,
            "rows": len(live), "groups": groups}


def _ev_breaches_by_assignee(book, metric, *, period, filters):
    live = [a for a in _visible_alerts(book) if a["status"] in _LIVE]
    return {"value": len(live), "numerator": len(live), "denominator": None,
            "rows": len(live), "groups": _count_by(
                live, lambda a: a["body"].get("assignee") or "(unassigned)")}


def _latest_result(book, *, delta_only: bool = False):
    for r in sorted(_scenario_results(book), key=lambda r: -r["created_at"]):
        ran = (r["body"].get("methods") or {}).get("ran") or []
        if not delta_only or "delta" in ran:
            return r
    return None


def _result_groups(r, rows, value_key, label) -> dict[str, Any]:
    if r is None:
        return {"value": None, "numerator": None, "denominator": None,
                "rows": 0, "groups": [], "latest_result": None,
                "note": "No executed scenario result you can open on this "
                        "book yet."}
    b = r["body"]
    groups = [{**{k: x[k] for k in x if k not in (value_key, "dimension")},
               "dimension": label(x), "value": _num(x.get(value_key)),
               "object_id": r["object_id"]}
              for x in rows]
    total = sum(g["value"] or 0 for g in groups)
    return {"value": total, "numerator": total, "denominator": None,
            "rows": len(groups), "groups": groups,
            "latest_result": r["object_id"],
            "scenario_name": b.get("scenario_name", r["title"]),
            "stage_policy": b.get("stage_policy", "")}


def _ev_scenario_methods(book, metric, *, period, filters):
    r = _latest_result(book)
    rows = [] if r is None else [
        {**o, "change": o.get("change")}
        for o in (r["body"].get("results") or {}).values() if o.get("ran")]
    out = _result_groups(r, rows, "change", lambda x: x.get("label")
                         or x.get("method", ""))
    out["value"] = None if not out["groups"] else out["groups"][0]["value"]
    return out


def _ev_scenario_pareto(book, metric, *, period, filters):
    r = _latest_result(book, delta_only=True)
    return _result_groups(r, [] if r is None else r["body"].get("pareto")
                          or [], "change", lambda x: x.get("group", ""))


def _ev_scenario_stages(book, metric, *, period, filters):
    r = _latest_result(book, delta_only=True)
    return _result_groups(r, [] if r is None else r["body"].get("stages")
                          or [], "change", lambda x: f"Stage {x['stage']}")


def _ev_material_changes(book, metric, *, period, filters):
    from backend.workspace import service

    total = 0
    try:
        for lens in service.store().latest_of_kind("lens",
                                                   tenant_id=book.tenant_id):
            obs = service.store().observations(lens["object_id"],
                                               tenant_id=book.tenant_id,
                                               limit=1)
            if obs and obs[0]["status"] == "SUCCEEDED":
                total += len(obs[0]["body"].get("material_changes") or [])
    except Exception:  # noqa: BLE001
        pass
    return {"value": total, "numerator": total, "denominator": None,
            "rows": total}


def _ev_refresh_age(book, metric, *, period, filters):
    """Hours since each Lens' last SUCCESSFUL observation (a failed refresh
    never resets it), one group per Lens of the tenant whose scope includes
    this book; the headline is the oldest. Lenses that never refreshed
    successfully are listed with no value, never as 0."""
    from backend.workspace import service

    now = time.time()
    groups = []
    try:
        store = service.store()
        lenses = store.latest_of_kind("lens", tenant_id=book.tenant_id)
    except Exception:  # noqa: BLE001
        lenses = []
    for lens in lenses:
        if book.domain_id not in (lens["body"].get("domain_scope") or []):
            continue
        obs = store.observations(lens["object_id"], tenant_id=book.tenant_id,
                                 limit=50)
        ok = next((o for o in obs if o["status"] == "SUCCEEDED"), None)
        groups.append({"dimension": lens["body"].get("name") or lens["title"],
                       "lens_id": lens["object_id"],
                       "value": None if ok is None else
                       (now - ok["finished_at"]) / 3600.0,
                       "last_success_at": None if ok is None else
                       ok["finished_at"],
                       "last_status": obs[0]["status"] if obs else "NEVER"})
    aged = [g["value"] for g in groups if g["value"] is not None]
    groups.sort(key=lambda g: -(g["value"] if g["value"] is not None
                                else float("inf")))
    return {"value": max(aged) if aged else None, "numerator": None,
            "denominator": None, "rows": len(groups), "groups": groups,
            "never_refreshed": sum(1 for g in groups if g["value"] is None),
            "note": None if aged else "No Lens on this book has refreshed "
                                      "successfully yet."}


EVALUATORS = {name[4:]: fn for name, fn in globals().items()
              if name.startswith("_ev_")}


# ---- public ----------------------------------------------------------------------

def evaluate(book: Book, metric_id: str, *, period: str = "",
             filters: Any = None, group_by: str = "") -> dict[str, Any]:
    metric = _metric(metric_id, book.domain_id)
    v = grid.view(book, period)
    chosen = v.period

    def compute():
        started = time.perf_counter()
        if metric["kind"] in ("delta", "delta_pct"):
            base = mc.BY_ID[metric["relative_to"]]
            now = _base_value(book, base, period=chosen, filters=filters,
                              group_by=group_by)
            prior = (_base_value(book, base, period=v.prior_period,
                                 filters=filters, group_by=group_by)
                     if v.prior_period else None)
            result = _delta(metric, now, prior)
        elif metric["evaluator"] and group_by and metric["kind"] == "book":
            result = _grouped_evaluator(book, metric, v, period=chosen,
                                        filters=filters, group_by=group_by)
        elif metric["evaluator"]:
            result = EVALUATORS[metric["evaluator"]](
                book, metric, period=chosen, filters=filters)
        else:
            result = _base_value(book, metric, period=chosen, filters=filters,
                                 group_by=group_by)
        envelope = {
            "metric_id": metric_id, "metric_version": metric["version"],
            "name": metric["name"], "unit": metric["unit"],
            "directionality": metric["directionality"],
            "domain_id": book.domain_id, "release_id": book.release_id,
            "fingerprint": book.fingerprint, "period": chosen,
            "prior_period": v.prior_period, "group_by": group_by,
            "filters": predicates.normalise(filters, columns=v.keys),
            "server_ms": int((time.perf_counter() - started) * 1000),
        }
        if isinstance(result, list):
            envelope["groups"] = result
        else:
            envelope.update(result)
        return envelope

    if metric["kind"] in ("platform", "scenario"):
        # Time- and state-dependent (freshness, alerts, scenario results):
        # never served from a cache keyed only by the release.
        return compute()
    return _cached(_key(book, "eval", metric_id, chosen, filters, group_by),
                   compute)


#: Most groups an evaluator metric is broken down into (one evaluation each).
GROUPS_MAX = 40


def _grouped_evaluator(book: Book, metric: dict[str, Any], v: grid.View, *,
                       period: str, filters: Any, group_by: str
                       ) -> list[dict[str, Any]]:
    """A breakdown of a metric whose value is not a ratio of sums: the same
    evaluator, once per value of the dimension, with that value added to the
    filters -- so each bar is exactly the metric on that slice."""
    if group_by not in v.keys:
        raise HTTPException(422, {"error_code": "UNKNOWN_DIMENSION",
                                  "message": f"{group_by} is not a column."})
    where, params = _where(v, filters)
    values = [r["d"] for r in book.rows(
        f"SELECT {group_by} AS d, SUM(ead_sar_mn) AS e FROM ({v.sql}) g "
        f"{where} GROUP BY 1 ORDER BY 2 DESC LIMIT {GROUPS_MAX}", params)]
    base = list(predicates.normalise(filters, columns=v.keys)) if filters \
        else []
    out = []
    for value in values:
        if value is None:
            continue
        sliced = [*base, {"column": group_by, "op": "in", "values": [value]}]
        r = EVALUATORS[metric["evaluator"]](book, metric, period=period,
                                            filters=sliced)
        out.append({"dimension": value, "value": r.get("value"),
                    "numerator": r.get("numerator"),
                    "denominator": r.get("denominator"),
                    "rows": r.get("rows")})
    return out


def _delta(metric, now, prior):
    pct = metric["kind"] == "delta_pct"

    def one(n, p):
        if p is None or n["value"] is None or p["value"] is None:
            return {"value": None, "current": n["value"],
                    "prior": None if p is None else p["value"]}
        if pct:
            value = None if p["value"] <= 0 else n["value"] / p["value"] - 1
        else:
            value = n["value"] - p["value"]
        return {"value": value, "current": n["value"], "prior": p["value"],
                "numerator": n["value"], "denominator": p["value"],
                "rows": n.get("rows", 0)}

    if isinstance(now, list):
        prior_map = {g["dimension"]: g for g in (prior or [])}
        return [{"dimension": g["dimension"],
                 **one(g, prior_map.get(g["dimension"]))} for g in now]
    return one(now, prior)


def series(book: Book, metric_id: str, *, periods: int = 8,
           filters: Any = None, end_period: str = "") -> dict[str, Any]:
    metric = _metric(metric_id, book.domain_id)
    end = end_period or book.latest_period
    all_periods = book.periods
    if end not in all_periods:
        raise HTTPException(422, {"error_code": "UNKNOWN_PERIOD",
                                  "message": f"{end!r} is not a period."})
    index = all_periods.index(end)
    wanted = all_periods[max(0, index - periods + 1):index + 1]
    points = []
    for p in wanted:
        if metric["kind"] in ("delta", "delta_pct") and all_periods.index(p) == 0:
            points.append({"period": p, "value": None})
            continue
        r = evaluate(book, metric_id, period=p, filters=filters)
        points.append({"period": p, "value": r.get("value"),
                       "numerator": r.get("numerator"),
                       "denominator": r.get("denominator")})
    return {"metric_id": metric_id, "metric_version": metric["version"],
            "name": metric["name"], "unit": metric["unit"],
            "release_id": book.release_id, "fingerprint": book.fingerprint,
            "points": points}


def catalogue(domain_id: str = "") -> list[dict[str, Any]]:
    return [m for m in mc.METRICS if not domain_id or mc.applies(m, domain_id)]


__all__ = ["EVALUATORS", "REQUIRED_FIELDS", "catalogue", "clear_cache",
           "evaluate", "sensitivity_rows", "series"]
