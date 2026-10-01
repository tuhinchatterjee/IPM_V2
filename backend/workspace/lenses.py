"""Lenses 2.0 (§32, §45): persistent, refreshable dashboards on governed metrics.

A Lens is a governed object: identity, data scope and default filters, the
metric ids and versions it uses, visual specifications, layout, refresh
default, breach rules, delivery and lineage. It stores NO figures; rendering
evaluates every visual now, through the same metric engine the Metric
Catalogue documents. A refresh records an immutable observation (values,
release fingerprints, what changed against the previous successful one, and
which breach rules fire) -- the record Monitoring works from.

Creating a Lens never persists a vague prompt: a proposal is returned as a
preview (N KPIs, M charts, T tables, the refresh rule) and only a confirmed
save creates the object. Editing a saved Lens writes a new version.
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import HTTPException

from backend.workspace import access, grid, metrics, predicates
from backend.workspace import lens_seed as seed
from backend.workspace import metric_catalog as mc
from backend.workspace.objects import LIBRARY_OWNER, ObjectService, Principal, can_edit

VISUALS = ("kpi", "trend", "breakdown", "stage_mix", "top_owners",
           "scenario_results", "alerts", "sensitivity", "table", "groups")
CADENCES = ("manual", "on_publication", "on_result", "daily", "weekly",
            "monthly", "continuous")
COMPARISONS = ("gt", "lt", "abs_gt", "move_pct_gt", "move_abs_gt")
LIBRARY_PERMISSIONS = {"visibility": "tenant", "readers": [], "editors": []}
SPARK = 6


def _refuse(status: int, code: str, message: str) -> None:
    raise HTTPException(status, {"error_code": code, "message": message})


def object_id(lens_id: str) -> str:
    return "lens-" + lens_id.lower().replace("lens-", "")


# ---- validation -----------------------------------------------------------------

def validate(spec: dict[str, Any], who: dict[str, Any]) -> dict[str, Any]:
    """Refuse anything a Lens cannot honestly render. Never repairs."""
    for key in ("name", "description", "persona", "domain_scope", "visuals",
                "refresh"):
        if not spec.get(key):
            _refuse(422, "INVALID_LENS", f"a Lens needs {key}.")
    scope = list(spec["domain_scope"])
    if not set(scope) <= {"corporate", "retail"}:
        _refuse(422, "INVALID_LENS", "domain_scope is corporate and/or "
                                     "retail.")
    views = {d: grid.view(access.book(who, d)) for d in scope}
    if spec["refresh"].get("cadence") not in CADENCES:
        _refuse(422, "INVALID_LENS", f"refresh cadence is one of {CADENCES}.")
    seen = set()
    for v in spec["visuals"]:
        if v.get("type") not in VISUALS:
            _refuse(422, "INVALID_VISUAL", f"visual type is one of {VISUALS}.")
        if v.get("domain") not in scope:
            _refuse(422, "INVALID_VISUAL", f"{v.get('title')}: its book is "
                                           f"outside the Lens's scope.")
        for mid in v.get("metric_ids") or [v.get("metric_id")]:
            metric = mc.BY_ID.get(str(mid))
            if metric is None:
                _refuse(422, "ANONYMOUS_METRIC",
                        f"{v.get('title')}: {mid!r} is not a governed "
                        f"metric. A Lens shows catalogue metrics only.")
            if not mc.applies(metric, v["domain"]):
                _refuse(422, "INVALID_VISUAL", f"{mid} does not apply to the "
                                               f"{v['domain']} book.")
        if v.get("group_by") and v["group_by"] not in views[v["domain"]].keys:
            _refuse(422, "INVALID_VISUAL", f"{v['group_by']} is not a column "
                                           f"of the {v['domain']} book.")
        if v.get("visual_id") in seen:
            _refuse(422, "INVALID_VISUAL", "visual ids must be unique.")
        seen.add(v.get("visual_id"))
    for d, flt in (spec.get("filters") or {}).items():
        if d not in views:
            _refuse(422, "INVALID_FILTER", f"a filter on {d} is outside the "
                                           f"Lens's scope.")
        predicates.normalise(flt, columns=views[d].keys)
    for r in spec.get("breach_rules") or []:
        if r.get("metric_id") not in mc.BY_ID:
            _refuse(422, "ANONYMOUS_METRIC", f"rule {r.get('rule_id')}: "
                                             f"unknown metric.")
        if r.get("comparison") not in COMPARISONS:
            _refuse(422, "INVALID_RULE", f"comparison is one of "
                                         f"{COMPARISONS}.")
    out = dict(spec)
    # Pin every metric to the version the Lens was built on.
    out["metrics"] = [{"metric_id": m["metric_id"], "domain": m["domain"],
                       "version": mc.BY_ID[m["metric_id"]]["version"]}
                      for m in _metric_refs(spec)]
    out.setdefault("audience", [spec["persona"]])
    out.setdefault("breach_rules", [])
    out.setdefault("filters", {})
    out.setdefault("delivery", {"workspace": True, "inbox": True,
                                "digest": False})
    out.setdefault("layout", {})
    return out


def _metric_refs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for v in spec["visuals"]:
        for mid in v.get("metric_ids") or [v["metric_id"]]:
            ref = {"metric_id": mid, "domain": v["domain"]}
            if ref not in refs:
                refs.append(ref)
    for r in spec.get("breach_rules") or []:
        ref = {"metric_id": r["metric_id"], "domain": r["domain"]}
        if ref not in refs:
            refs.append(ref)
    return refs


# ---- the library ------------------------------------------------------------------

def ensure_seeded(svc: ObjectService, who: dict[str, Any]) -> dict[str, Any]:
    principal = Principal.of(who)
    key = f"lens_seed:{principal.tenant}"
    if svc.store.meta(key) == seed.SEED_VERSION:
        return {"created": 0}
    library = Principal(id=LIBRARY_OWNER, tenant=principal.tenant,
                        roles=frozenset({"administrator"}))
    created = 0
    for lens in seed.LENSES:
        oid = object_id(lens["lens_id"])
        if svc.store.get(oid, tenant_id=principal.tenant) is not None:
            continue
        body = validate(lens, who)
        svc.create("lens", library, body, title=lens["name"],
                   status="ACTIVE", object_id=oid, owner_id=LIBRARY_OWNER,
                   permissions=dict(LIBRARY_PERMISSIONS), seeded=True,
                   tags=list(lens.get("tags") or []) + [lens["persona"]],
                   lineage={"origin": "seeded",
                            "seed_version": seed.SEED_VERSION,
                            "lens_id": lens["lens_id"]})
        created += 1
    _seed_results(svc, who)
    svc.store.set_meta(key, seed.SEED_VERSION)
    return {"created": created}


#: Executed demo results the Scenario Impact Lens shows on first launch:
#: library-owned, tenant-visible, labelled synthetic.
_DEMO_RESULTS = (("CORP-02", "corporate"), ("RET-06", "retail"))


def _seed_results(svc: ObjectService, who: dict[str, Any]) -> None:
    from backend.workspace import runs, scenarios

    tenant = Principal.of(who).tenant
    library = {"id": LIBRARY_OWNER, "tenant": tenant,
               "roles": ("administrator",)}
    lib_p = Principal.of(library)
    scenarios.ensure_seeded(svc, library)
    for template, domain in _DEMO_RESULTS:
        try:
            run = runs.create(svc, library,
                              scenario_id=scenarios.template_object_id(
                                  template),
                              session_id=f"seed-lens-{domain}",
                              baseline={"mode": "SOURCE_BASELINE"},
                              entry="library")
            run = runs.confirm(svc, library, run["object_id"],
                               run["body"]["contract"]["digest"])
            run = runs.choose_method(svc, library, run["object_id"],
                                     ["delta"])
            done = runs.execute(svc, library, run["object_id"])
        except HTTPException:
            continue  # the book is not published here
        res = done["result"]
        svc.revise(res["object_id"], lib_p,
                   permissions=dict(LIBRARY_PERMISSIONS),
                   title=f"[SYNTHETIC DEMO] {res['title']}"[:160],
                   reason="seeded demo result for the Lens Library",
                   force=True)


def card(svc: ObjectService, lens: dict[str, Any]) -> dict[str, Any]:
    b = lens["body"]
    last = svc.store.observations(lens["object_id"],
                                  tenant_id=lens["tenant_id"], limit=1)
    counts = {t: sum(1 for v in b["visuals"] if v["type"] == t)
              for t in VISUALS}
    return {"object_id": lens["object_id"], "version": lens["version"],
            "lens_id": b.get("lens_id", ""), "name": b["name"],
            "description": b["description"], "persona": b["persona"],
            "domain_scope": b["domain_scope"], "status": lens["status"],
            "owner_id": lens["owner_id"], "seeded": lens["seeded"],
            "refresh": b["refresh"], "kpis": counts["kpi"],
            "charts": sum(counts[t] for t in VISUALS
                          if t not in ("kpi", "table")),
            "tables": counts["table"], "metrics": len(b["metrics"]),
            "breach_rules": len(b.get("breach_rules") or []),
            "filters": b.get("filters") or {},
            "last_refresh": None if not last else {
                "at": last[0]["finished_at"], "status": last[0]["status"],
                "material_changes": len(last[0]["body"].get(
                    "material_changes") or []),
                "breaches": sum(1 for x in last[0]["body"].get("breaches")
                                or [] if x.get("breached"))},
            "content_hash": lens["content_hash"]}


def listing(svc: ObjectService, who: dict[str, Any], *, q: str = "",
            persona: str = "", domain: str = "") -> dict[str, Any]:
    ensure_seeded(svc, who)
    principal = Principal.of(who)
    rows = [card(svc, r) for r in svc.list("lens", principal)
            if r["status"] != "ARCHIVED"]
    needle = q.strip().lower()
    out = [c for c in rows
           if (not needle or needle in f"{c['name']} {c['description']} "
                                       f"{c['persona']}".lower())
           and (not persona or c["persona"] == persona)
           and (not domain or domain in c["domain_scope"])]
    out.sort(key=lambda c: (not c["seeded"], c["lens_id"] or "~",
                            c["name"]))
    return {"lenses": out, "total": len(rows), "shown": len(out),
            "state": "EMPTY_BY_FILTER" if rows and not out else
            ("NOT_CONFIGURED" if not rows else "OK")}


# ---- rendering ---------------------------------------------------------------------

def _filters_for(spec: dict[str, Any], domain: str, v: grid.View,
                 cross: list[dict[str, Any]]) -> tuple[list, list]:
    """The Lens's default filters for this book plus every compatible
    cross-filter; incompatible ones are reported, never guessed."""
    applied = list((spec.get("filters") or {}).get(domain) or [])
    skipped = []
    for f in cross or []:
        if f.get("domain") and f["domain"] != domain:
            skipped.append(f)
            continue
        if f.get("column") in v.keys:
            applied.append({k: f[k] for k in ("column", "op", "values",
                                               "value") if k in f})
        else:
            skipped.append(f)
    return applied, skipped


def _top_owners(book, v: grid.View, flt: list, n: int) -> list[dict]:
    where, params = "", []
    if flt:
        sql, params = predicates.bound(predicates.normalise(
            flt, columns=v.keys))
        where = f"WHERE {sql}" if sql else ""
    label = "borrower_name" if "borrower_name" in v.keys else v.owner
    return book.rows(
        f"SELECT {v.owner} AS owner, MAX({label}) AS name, "
        f"SUM(ead_sar_mn) AS ead, SUM(ecl_sar_mn) AS ecl, COUNT(*) AS n "
        f"FROM ({v.sql}) g {where} GROUP BY 1 ORDER BY 3 DESC LIMIT {int(n)}",
        params)


def _render_visual(book, spec, vis, *, period: str, cross: list
                   ) -> dict[str, Any]:
    v = grid.view(book, period)
    flt, skipped = _filters_for(spec, vis["domain"], v, cross)
    mid = vis.get("metric_id") or (vis.get("metric_ids") or [""])[0]
    metric = mc.BY_ID.get(mid, {})
    out = {"visual_id": vis["visual_id"], "type": vis["type"],
           "title": vis.get("title") or metric.get("name", ""),
           "domain": vis["domain"], "period": v.period,
           "prior_period": v.prior_period, "release_id": book.release_id,
           "fingerprint": book.fingerprint, "metric_id": mid,
           "metric_version": metric.get("version"),
           "unit": metric.get("unit"), "direction":
           metric.get("directionality"), "filters_applied": flt,
           "filters_skipped": skipped, "status": "OK"}
    t = vis["type"]
    if t == "kpi":
        now = metrics.evaluate(book, mid, period=v.period, filters=flt)
        out["value"] = now.get("value")
        out["note"] = now.get("note")
        if out["value"] is None and metric.get("kind") == "scenario":
            out["note"] = ("No executed scenario result you can open on this "
                           "book yet — run one in What-If.")
        if metric.get("kind") in ("book",) and v.prior_period:
            prior = metrics.evaluate(book, mid, period=v.prior_period,
                                     filters=flt)
            out["prior"] = prior.get("value")
        if metric.get("kind") in ("book", "delta", "delta_pct"):
            out["spark"] = metrics.series(book, mid, periods=SPARK,
                                          filters=flt,
                                          end_period=v.period)["points"]
        if not out.get("title"):
            out["title"] = metric.get("name", mid)
    elif t == "trend":
        out["series"] = [{"metric_id": m, "metric_version":
                          mc.BY_ID[m]["version"], "name": mc.BY_ID[m]["name"],
                          "unit": mc.BY_ID[m]["unit"],
                          "points": metrics.series(
                              book, m, periods=int(vis.get("periods") or 8),
                              filters=flt, end_period=v.period)["points"]}
                         for m in vis["metric_ids"]]
    elif t in ("breakdown", "stage_mix"):
        r = metrics.evaluate(book, mid, period=v.period, filters=flt,
                             group_by=vis["group_by"])
        out["group_by"] = vis["group_by"]
        out["groups"] = r.get("groups") or []
    elif t == "top_owners":
        out["rows"] = _top_owners(book, v, flt, int(vis.get("n") or 10))
        out["total_ead"] = metrics.evaluate(book, "M018", period=v.period,
                                            filters=flt).get("value")
    elif t in ("scenario_results", "alerts", "sensitivity", "groups"):
        # `groups`: any catalogue metric whose evaluator publishes named
        # groups (EWS reasons, alerts by state / metric / owner, a result
        # by method / segment / stage), drawn as one bar per group.
        r = metrics.evaluate(book, mid, period=v.period, filters=flt)
        out["groups"] = r.get("groups") or []
        out["value"] = r.get("value")
        for k in ("latest_result", "scenario_name", "stage_policy", "note",
                  "rules_not_evaluated"):
            if r.get(k) is not None:
                out[k] = r[k]
    elif t == "table":
        q = grid.query(book, period=v.period, filters=flt or None,
                       sort=vis.get("sort") or "ecl_sar_mn", limit=25)
        cols = [c for c in vis.get("columns") or [] if c in v.keys] or \
            list(v.keys)[:8]
        out["columns"] = cols
        out["rows"] = [{c: r.get(c) for c in [v.key, *cols]}
                       for r in q["rows"]]
        out["total"] = q["total"]
        out["key"] = v.key
    return out


def render(svc: ObjectService, who: dict[str, Any], oid: str, *,
           version: int | None = None, periods: dict[str, str] | None = None,
           cross: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ensure_seeded(svc, who)
    lens = svc.get(oid, Principal.of(who), version=version)
    if lens["kind"] != "lens":
        _refuse(422, "NOT_A_LENS", f"{oid} is not a Lens.")
    spec = lens["body"]
    books = {d: access.book(who, d) for d in spec["domain_scope"]}
    started = time.perf_counter()
    token = metrics.VIEWER.set(Principal.of(who))
    try:
        visuals = _render_all(spec, books, periods=periods, cross=cross)
    finally:
        metrics.VIEWER.reset(token)
    return _rendered(svc, who, lens, spec, books, visuals, periods=periods,
                     cross=cross, started=started)


def _render_all(spec, books, *, periods, cross) -> list[dict[str, Any]]:
    visuals = []
    for vis in spec["visuals"]:
        book = books[vis["domain"]]
        try:
            visuals.append(_render_visual(
                book, spec, vis, period=(periods or {}).get(vis["domain"], ""),
                cross=cross or []))
        except HTTPException as exc:
            visuals.append({"visual_id": vis["visual_id"], "type":
                            vis["type"], "title": vis.get("title", ""),
                            "domain": vis["domain"], "status": "ERROR",
                            "message": str(exc.detail)})
    return visuals


def _rendered(svc, who, lens, spec, books, visuals, *, periods, cross,
              started) -> dict[str, Any]:
    oid = lens["object_id"]
    obs = svc.store.observations(oid, tenant_id=lens["tenant_id"], limit=1)
    return {"lens": {**card(svc, lens), "body": spec,
                     "lineage": lens["lineage"],
                     "permissions": lens["permissions"],
                     "can_edit": can_edit(lens, Principal.of(who)),
                     "following": Principal.of(who).id in
                     svc.store.subscribers(oid, tenant_id=lens["tenant_id"])},
            "books": {d: {"period": grid.view(b, (periods or {}).get(d, "")
                                              ).period,
                          "periods": b.periods[-12:],
                          "latest_period": b.latest_period,
                          "release_id": b.release_id,
                          "fingerprint": b.fingerprint}
                      for d, b in books.items()},
            "cross_filters": cross or [], "visuals": visuals,
            "last_observation": obs[0] if obs else None,
            "server_ms": int((time.perf_counter() - started) * 1000)}


# ---- refresh -------------------------------------------------------------------------

def _material(metric: dict[str, Any], now: float | None,
              prior: float | None) -> bool:
    if now is None or prior is None:
        return now is not prior
    t = metric.get("thresholds") or {}
    move = now - prior
    if "materiality_move_pp" in t:
        return abs(move) * 100 >= float(t["materiality_move_pp"])
    if "materiality_abs_sar_mn" in t and abs(move) >= float(
            t["materiality_abs_sar_mn"]):
        return True
    if "materiality_move_pct" in t or "move_pct_amber" in t:
        pct = float(t.get("materiality_move_pct") or t["move_pct_amber"])
        return prior != 0 and abs(move / prior) >= pct
    if "materiality_move_abs" in t or "materiality_abs" in t:
        return abs(move) >= float(t.get("materiality_move_abs")
                                  or t["materiality_abs"])
    if "move_bps_amber" in t:
        return abs(move) * 10000 >= float(t["move_bps_amber"])
    return abs(move) > 0.05 * abs(prior) if prior else move != 0


def _breached(rule: dict[str, Any], now: float | None, prior: float | None
              ) -> bool:
    if now is None:
        return False
    th, op = float(rule["threshold"]), rule["comparison"]
    if op == "gt":
        return now > th
    if op == "lt":
        return now < th
    if op == "abs_gt":
        return abs(now) > th
    if op == "move_pct_gt":
        return prior not in (None, 0) and (now - prior) / abs(prior) > th
    if op == "move_abs_gt":
        return prior is not None and abs(now - prior) > th
    return False


def refresh(svc: ObjectService, who: dict[str, Any], oid: str, *,
            trigger: str = "manual") -> dict[str, Any]:
    """Evaluate every Lens metric now; record an immutable observation."""
    ensure_seeded(svc, who)
    principal = Principal.of(who)
    lens = svc.get(oid, principal)
    spec = lens["body"]
    started = time.time()
    prev = next((o for o in svc.store.observations(
        oid, tenant_id=principal.tenant, limit=20)
        if o["status"] == "SUCCEEDED"), None)
    try:
        books = {d: access.book(who, d) for d in spec["domain_scope"]}
    except HTTPException as exc:
        # A failed refresh is an operational event, recorded as FAILED --
        # never a silent reuse of the previous values as if current.
        return svc.store.add_observation({
            "tenant_id": principal.tenant, "lens_id": oid,
            "lens_version": lens["version"], "trigger": trigger,
            "status": "FAILED", "started_at": started,
            "finished_at": time.time(),
            "body": {"values": {}, "material_changes": [], "breaches": [],
                     "what_changed": "Refresh FAILED: the governed book is "
                                     "not available. Nothing below is "
                                     "current; the last successful "
                                     "observation is "
                                     + (time.strftime("%Y-%m-%d %H:%M UTC",
                                                      time.gmtime(
                                                          prev["finished_at"]))
                                        if prev else "none") + ".",
                     "fingerprints": {}, "errors": [str(exc.detail)],
                     "previous_observation": (prev or {}).get(
                         "observation_id")},
            "error": str(exc.detail)[:2000]})
    prev = next((o for o in svc.store.observations(
        oid, tenant_id=principal.tenant, limit=20)
        if o["status"] == "SUCCEEDED"), None)
    fingerprints = {d: b.fingerprint for d, b in books.items()}
    if prev and trigger != "manual" and prev["body"].get("fingerprints") == \
            fingerprints and prev["lens_version"] == lens["version"]:
        # Idempotent: the same release and Lens version were observed.
        return {**prev, "idempotent": True}
    token = metrics.VIEWER.set(principal)
    try:
        values, errors = _observe(spec, books)
    finally:
        metrics.VIEWER.reset(token)
    return _record(svc, principal, lens, spec, books, prev, values, errors,
                   trigger=trigger, started=started, fingerprints=fingerprints)


def _observe(spec, books) -> tuple[dict[str, dict[str, Any]], list]:
    values: dict[str, dict[str, Any]] = {}
    errors = []
    for ref in spec["metrics"]:
        d, mid = ref["domain"], ref["metric_id"]
        book = books[d]
        v = grid.view(book)
        flt = list((spec.get("filters") or {}).get(d) or [])
        try:
            now = metrics.evaluate(book, mid, filters=flt or None)
            prior = None
            if mc.BY_ID[mid]["kind"] == "book" and v.prior_period:
                prior = metrics.evaluate(book, mid, period=v.prior_period,
                                         filters=flt or None).get("value")
            values.setdefault(d, {})[mid] = {
                "value": now.get("value"), "prior": prior,
                "period": now.get("period"),
                "version": mc.BY_ID[mid]["version"]}
        except HTTPException as exc:
            errors.append({"metric_id": mid, "domain": d,
                           "message": str(exc.detail)})
    return values, errors


def _record(svc, principal, lens, spec, books, prev, values, errors, *,
            trigger, started, fingerprints) -> dict[str, Any]:
    oid = lens["object_id"]
    previous = (prev or {}).get("body", {}).get("values", {})
    changes = []
    for d, per in values.items():
        for mid, cur in per.items():
            before = (previous.get(d) or {}).get(mid, {}).get("value")
            if prev and _material(mc.BY_ID[mid], cur["value"], before):
                changes.append({"metric_id": mid, "domain": d,
                                "name": mc.BY_ID[mid]["name"],
                                "unit": mc.BY_ID[mid]["unit"],
                                "from": before, "to": cur["value"]})
    breaches = []
    for rule in spec.get("breach_rules") or []:
        cur = (values.get(rule["domain"]) or {}).get(rule["metric_id"], {})
        breaches.append({**{k: rule[k] for k in (
            "rule_id", "name", "metric_id", "domain", "comparison",
            "threshold", "severity")},
            "observed": cur.get("value"), "prior": cur.get("prior"),
            "breached": _breached(rule, cur.get("value"), cur.get("prior"))})
    if not prev:
        summary = "First observation of this Lens version: baseline recorded."
    elif not changes:
        summary = "No material change since the previous refresh."
    else:
        summary = "; ".join(f"{c['name']} ({c['domain']}) moved"
                            for c in changes[:6])
    row = svc.store.add_observation({
        "tenant_id": principal.tenant, "lens_id": oid,
        "lens_version": lens["version"], "trigger": trigger,
        "release_id": ",".join(f"{d}:{b.release_id}"
                               for d, b in books.items()),
        "fingerprint": ",".join(fingerprints.values()),
        "period": ",".join(f"{d}:{b.latest_period}"
                           for d, b in books.items()),
        "status": "FAILED" if errors and not values else "SUCCEEDED",
        "started_at": started, "finished_at": time.time(),
        "body": {"values": values, "material_changes": changes,
                 "breaches": breaches, "what_changed": summary,
                 "fingerprints": fingerprints, "errors": errors,
                 "previous_observation": (prev or {}).get("observation_id")},
        "error": "; ".join(e["message"] for e in errors)[:2000]})
    return row


def history(svc: ObjectService, who: dict[str, Any], oid: str
            ) -> list[dict[str, Any]]:
    ensure_seeded(svc, who)
    principal = Principal.of(who)
    svc.get(oid, principal)
    return svc.store.observations(oid, tenant_id=principal.tenant, limit=50)


# ---- creating a Lens ------------------------------------------------------------------

#: Words -> the seeded Lens a request most resembles (its spec is the draft).
_PERSONA = (
    (r"\bcro\b|executive|overview", "LENS-01"),
    (r"\bboard\b|committee", "LENS-14"),
    (r"corporate credit|head of corporate", "LENS-02"),
    (r"head of retail|retail risk", "LENS-03"),
    (r"ifrs|ecl oversight|stage share|overlay", "LENS-04"),
    (r"early warning|\bews\b|warned", "LENS-05"),
    (r"credit card|\bcard\b", "LENS-08"),
    (r"personal finance|affordab|salary", "LENS-09"),
    (r"home finance|mortgage", "LENS-10"),
    (r"auto finance|\bauto\b|vehicle", "LENS-11"),
    (r"collection|recover|roll.?forward|\bcure", "LENS-12"),
    (r"appetite|limit", "LENS-13"),
    (r"construction|real estate|\bcre\b", "LENS-15"),
    (r"scenario|stress|what.?if", "LENS-16"),
    (r"data quality|completeness|freshness|coverage", "LENS-17"),
    (r"breach|monitoring|alert", "LENS-18"),
    (r"bnpl|buy now", "LENS-20"),
    (r"hospitality|transport|travel", "LENS-19"),
    (r"corporate portfolio|concentration|obligor", "LENS-06"),
    (r"retail portfolio|vintage", "LENS-07"),
)


def _metric_matches(text: str, domain: str) -> list[str]:
    """Catalogue metrics whose name appears in the request."""
    out = []
    for m in mc.METRICS:
        if not mc.applies(m, domain):
            continue
        name = m["name"].lower()
        if len(name) > 5 and name in text:
            out.append(m["metric_id"])
    return out


def propose(who: dict[str, Any], prompt: str, *,
            base: dict[str, Any] | None = None, domain: str = ""
            ) -> dict[str, Any]:
    """A complete Lens PREVIEW from one request. Nothing is saved."""
    text = prompt.strip().lower()
    if not text and base is None:
        _refuse(422, "EMPTY_REQUEST", "describe the dashboard you want.")
    matched, reasons = None, []
    if base is not None:
        spec = {k: (list(v) if isinstance(v, list) else v)
                for k, v in base.items()}
        spec["visuals"] = [dict(v) for v in base["visuals"]]
        reasons.append("refining the previous preview")
    else:
        for pattern, lens_id in _PERSONA:
            if re.search(pattern, text):
                matched = lens_id
                reasons.append(f"'{re.search(pattern, text).group(0)}' → "
                               f"{seed.by_id()[lens_id]['name']} template")
                break
        template = seed.by_id()[matched or ("LENS-03" if "retail" in text
                                            else "LENS-02" if "corporate"
                                            in text else "LENS-01")]
        if not matched:
            reasons.append(f"no persona named; starting from "
                           f"{template['name']}")
        spec = {k: v for k, v in template.items() if k != "lens_id"}
        spec["visuals"] = [dict(v) for v in template["visuals"]]
        spec["name"] = prompt.strip()[:80] or template["name"]
        spec["tags"] = ["proposed"]
    scope = list(spec["domain_scope"])
    if domain and domain in ("corporate", "retail"):
        scope = [domain]
        spec["visuals"] = [v for v in spec["visuals"] if v["domain"] == domain]
        spec["breach_rules"] = [r for r in spec.get("breach_rules") or []
                                if r["domain"] == domain]
        spec["domain_scope"] = scope
    # "add <metric>" / "remove <metric>" refine the KPI row.
    for d in scope:
        for mid in _metric_matches(text, d):
            if not any(v["type"] == "kpi" and v["metric_id"] == mid
                       and v["domain"] == d for v in spec["visuals"]) \
                    and not re.search(r"\b(remove|drop|without)\b", text):
                spec["visuals"].append({"type": "kpi", "metric_id": mid,
                                        "domain": d, "title": ""})
                reasons.append(f"added KPI {mid} {mc.BY_ID[mid]['name']}")
    if re.search(r"\b(remove|drop|without)\b", text):
        for d in scope:
            for mid in _metric_matches(text, d):
                before = len(spec["visuals"])
                spec["visuals"] = [v for v in spec["visuals"] if not (
                    v.get("metric_id") == mid and v["domain"] == d
                    and v["type"] == "kpi")]
                if len(spec["visuals"]) < before:
                    reasons.append(f"removed KPI {mid}")
    for cadence in ("daily", "weekly", "monthly"):
        if cadence in text:
            spec["refresh"] = {**spec["refresh"], "cadence": cadence}
            reasons.append(f"refresh {cadence}")
    for i, v in enumerate(spec["visuals"], 1):
        v["visual_id"] = f"v{i:02d}"
    spec["metrics"] = _metric_refs(spec)
    spec["layout"] = {"kpi_row": [v["visual_id"] for v in spec["visuals"]
                                  if v["type"] == "kpi"]}
    checked = validate(spec, who)
    kinds = [v["type"] for v in checked["visuals"]]
    return {"spec": checked, "matched_template": matched, "reasons": reasons,
            "summary": {"kpis": kinds.count("kpi"),
                        "charts": sum(1 for k in kinds
                                      if k not in ("kpi", "table")),
                        "tables": kinds.count("table"),
                        "metrics": len(checked["metrics"]),
                        "breach_rules": len(checked["breach_rules"]),
                        "refresh": checked["refresh"]["cadence"]},
            "saved": False}


def save(svc: ObjectService, who: dict[str, Any], spec: dict[str, Any], *,
         source: dict[str, Any] | None = None) -> dict[str, Any]:
    body = validate(spec, who)
    body["status"] = "ACTIVE"
    body.pop("lens_id", None)
    body["source"] = dict(source or {"kind": "prompt"})
    principal = Principal.of(who)
    lineage: dict[str, Any] = {"origin": body["source"]["kind"],
                               "source": body["source"]}
    if body["source"].get("object_id"):
        lineage["derived_from"] = [[body["source"]["object_id"],
                                    int(body["source"].get("version") or 1)]]
    return svc.create("lens", principal, body, title=body["name"][:160],
                      status="ACTIVE", tags=list(body.get("tags") or []),
                      lineage=lineage)


def revise(svc: ObjectService, who: dict[str, Any], oid: str,
           changes: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Editing a Lens: a new version of your own, or your own copy of a
    library/shared one (the original is not changed)."""
    ensure_seeded(svc, who)
    principal = Principal.of(who)
    lens = svc.get(oid, principal)
    body = validate({**lens["body"], **changes}, who)
    if can_edit(lens, principal) and lens["owner_id"] != LIBRARY_OWNER:
        return svc.revise(oid, principal, body=body, reason=reason,
                          title=body["name"][:160])
    body["source"] = {"kind": "copy", "object_id": oid,
                      "version": lens["version"]}
    body.pop("lens_id", None)
    return svc.derive("lens", principal, body, sources=[(oid, lens["version"])],
                      operation="duplicate", title=body["name"][:160],
                      status="ACTIVE", tags=lens["tags"])


def from_investigation(svc: ObjectService, who: dict[str, Any], inv_id: str
                       ) -> dict[str, Any]:
    """Save-analysis-as-Lens: a PREVIEW scoped to the investigation's cohort."""
    principal = Principal.of(who)
    inv = svc.get(inv_id, principal)
    if inv["kind"] != "investigation":
        _refuse(422, "NOT_AN_INVESTIGATION", f"{inv_id} is not one.")
    cohort = svc.get(inv["body"]["cohort_id"], principal)
    domain = inv["body"].get("domain_id") or cohort["domain_id"]
    out = propose(who, domain, domain=domain)
    spec = out["spec"]
    spec["name"] = f"Lens: {inv['title']}"[:120]
    spec["description"] = (f"Saved from the investigation '{inv['title']}'; "
                           f"scoped to its governed cohort "
                           f"{cohort['object_id']}.")
    spec["filters"] = {domain: list(cohort["body"]["filters"])}
    spec["tags"] = ["from-investigation"]
    out["spec"] = validate(spec, who)
    out["source"] = {"kind": "investigation", "object_id": inv_id,
                     "version": inv["version"],
                     "cohort_id": cohort["object_id"],
                     "thread_id": inv["body"].get("thread_id", "")}
    out["reasons"].insert(0, f"scoped to the investigation's cohort "
                             f"({cohort['body']['counts']['entities']} "
                             f"exposures)")
    return out


def from_thread(svc: ObjectService, who: dict[str, Any], thread_id: str
                ) -> dict[str, Any]:
    """Save a Cockpit analysis as a Lens: a PREVIEW. The conversation's
    frozen cohort scopes it when it can be expressed as grid filters."""
    from backend.workspace import whatif

    principal = Principal.of(who)
    for inv in svc.list("investigation", principal):
        if inv["body"].get("thread_id") == thread_id:
            return from_investigation(svc, who, inv["object_id"])
    found = whatif.thread_cohort(who, thread_id)
    store = access.run_store()
    domain_row = store.thread_domain(thread_id) or {}
    domain = found.get("domain_id") or domain_row.get("domain_id") or \
        "corporate"
    out = propose(who, domain, domain=domain)
    title = store.thread_title(thread_id) or "Cockpit analysis"
    out["spec"]["name"] = f"Lens: {title}"[:120]
    out["spec"]["tags"] = ["from-cockpit"]
    out["source"] = {"kind": "cockpit", "thread_id": thread_id}
    if found.get("has_cohort"):
        cohort = whatif.adopt_thread_cohort(who, thread_id)
        ids = cohort["body"].get("member_ids") or []
        if cohort["body"]["filters"]:
            out["spec"]["filters"] = {domain: list(cohort["body"]["filters"])}
        elif 0 < cohort["body"]["counts"]["entities"] <= 500:
            v = grid.view(access.book(who, domain))
            if not ids:
                ids = [str(r["k"]) for r in access.book(who, domain).rows(
                    f"SELECT {v.key} AS k FROM ({v.sql}) g WHERE {v.key} IN "
                    f"(SELECT {ch_key(domain)} FROM "
                    f"{ch_relation(domain)} WHERE "
                    f"{cohort['body']['engine_predicate']})")]
            out["spec"]["filters"] = {domain: [{"column": v.key, "op": "in",
                                                "values": ids[:500]}]}
        else:
            out["reasons"].append(
                "the conversation's cohort is too large to pin by id; the "
                "Lens covers the book — filter it after saving")
        out["source"]["cohort_id"] = cohort["object_id"]
        out["spec"] = validate(out["spec"], who)
    return out


def ch_key(domain: str) -> str:
    from backend.cockpit_v4.scenario import cohort as ch

    return ch.GRAIN[domain]["key"]


def ch_relation(domain: str) -> str:
    from backend.cockpit_v4.scenario import cohort as ch

    return ch.GRAIN[domain]["relation"]


__all__ = ["CADENCES", "VISUALS", "card", "ensure_seeded", "from_investigation",
           "from_thread", "history", "listing", "object_id", "propose",
           "refresh", "render", "revise", "save", "validate"]
