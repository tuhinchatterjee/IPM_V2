"""Comparing executed scenarios on common KPIs and decompositions (§30).

A comparison is a governed object: which result versions, which method,
the common KPIs of both scopes and every taxonomy component side by side.
It holds no rows and recomputes nothing -- every number is copied from the
results' own published decompositions, so the comparison and the results
cannot disagree. Only compatible results are compared: the same book and
period, and a method every one of them ran. Nothing is aligned by guesswork.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.cockpit_v4.scenario import decomposition as dc
from backend.workspace.objects import ObjectService, Principal

PREFERENCE = ("delta", "user_defined", "ml")
KPI_KEYS = ("opening", "closing", "change", "change_pct")


def _refuse(code: str, message: str) -> None:
    raise HTTPException(422, {"error_code": code, "message": message})


def compare(svc: ObjectService, who: Principal, result_ids: list[str], *,
            method: str = "", title: str = "") -> dict[str, Any]:
    ids = list(dict.fromkeys(str(i) for i in result_ids if str(i).strip()))
    if len(ids) < 2:
        _refuse("TOO_FEW", "a comparison needs at least two results.")
    if len(ids) > 6:
        _refuse("TOO_MANY", "compare at most six results at once.")
    results = [svc.get(i, who) for i in ids]
    for r in results:
        if r["kind"] != "scenario_result":
            _refuse("NOT_A_RESULT", f"{r['object_id']} is a {r['kind']}, not "
                                    f"an executed scenario result.")
    books = {(r["body"]["domain_id"], r["body"]["period"]) for r in results}
    if len(books) != 1:
        _refuse("INCOMPATIBLE", "results on different books or periods are "
                                "not compared: "
                + ", ".join(f"{d} {p}" for d, p in sorted(books)) + ".")
    common = set.intersection(*(set(r["body"]["decomposition"])
                                for r in results))
    if method:
        if method not in common:
            _refuse("INCOMPATIBLE", f"not every result ran {method}; common "
                                    f"methods: {sorted(common) or 'none'}.")
        chosen = method
    else:
        chosen = next((m for m in PREFERENCE if m in common), "")
        if not chosen:
            _refuse("INCOMPATIBLE", "these results share no method, so their "
                                    "decompositions are not comparable.")
    domain_id, period = next(iter(books))
    items, kpis = [], []
    components = [{"id": c.id, "label": c.label, "kind": c.kind,
                   "values": {}} for c in dc.TAXONOMY]
    by_id = {c["id"]: c for c in components}
    for r in results:
        b = r["body"]
        d = b["decomposition"][chosen]
        items.append({
            "result_id": r["object_id"], "version": r["version"],
            "scenario_name": b["scenario_name"],
            "scenario_id": b["scenario_id"],
            "scenario_version": b["scenario_version"],
            "run_id": b.get("run_id", ""),
            "baseline_mode": b["baseline"].get("mode", "SOURCE_BASELINE"),
            "chain": [c.get("name") for c in b.get("chain") or []],
            "cohort": b["cohort"].get("description", ""),
            "entities": b["cohort"].get("entity_count"),
            "membership_hash": b["cohort"].get("membership_hash", ""),
            "methods_ran": b["methods"]["ran"],
            "contract_digest": b.get("contract_digest", ""),
            "content_hash": r["content_hash"]})
        row = {"result_id": r["object_id"]}
        for scope in ("selected", "total"):
            s = d["scopes"][scope]
            for k in KPI_KEYS:
                row[f"{scope}_{k}"] = s[k]
        row["rest_of_book_delta"] = d["cross_scope"]["rest_of_book_delta"]
        kpis.append(row)
        for scope in ("selected", "total"):
            for c in d["scopes"][scope]["components"]:
                by_id[c["id"]]["values"].setdefault(r["object_id"], {})[
                    scope] = {"value": c["value"], "status": c["status"]}
    body = {"domain_id": domain_id, "period": period, "method": chosen,
            "items": items, "kpis": kpis, "components": components,
            "contract_version": dc.CONTRACT_VERSION,
            "note": "Every value is copied from the results' published "
                    "decompositions; nothing is recomputed."}
    name = title or "Compare: " + " vs ".join(i["scenario_name"]
                                               for i in items)
    return svc.derive("comparison", who, body,
                      sources=[(r["object_id"], r["version"])
                               for r in results],
                      operation="compare", title=name[:160],
                      domain_id=domain_id,
                      release_id=results[0]["release_id"],
                      fingerprint=results[0]["fingerprint"], period=period)


__all__ = ["compare"]
