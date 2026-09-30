"""
The governance Trace of a workspace object: everything that made it, in one
reading, with the hashes that let a reviewer prove it.

For any object the viewer may open -- a finding, cohort, scenario, run (the
method decisions), scenario result, comparison, Lens (its refreshes), alert
(its state history) or metric -- the Trace returns:

* every version with its content hash, re-verified on read, and the version's
  entry in the tenant's hash-chained ledger (does it still link, does the
  stored row still hash to it);
* its lineage: ancestors walked through `derived_from` to the roots, and the
  objects derived from it;
* its events: comments, shares, the run's state log (confirmation, method
  choice, execution), Lens observations, alert transitions -- each append-only
  record with its own ledger entry;
* the LLM exchanges behind it: every recorded model call of the Cockpit
  thread(s) the object came from, by reference and hash (the full exchange
  opens in the LLM Exchange Trace; auditors only).

It reads. It never recomputes a number, never repairs a record and never
calls a model.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.workspace import access, service
from backend.workspace.objects import ObjectService, can_read
from backend.workspace.store import IntegrityError

#: How far the ancestor walk goes before it stops (and says so).
MAX_DEPTH = 12


def _thread_ids(body: Any, depth: int = 0) -> list[str]:
    """Cockpit thread ids an object's body names (`thread_id`, a cockpit
    run's `session_id`, a `source.thread_id`)."""
    found: list[str] = []
    if depth > 3:
        return found
    if isinstance(body, dict):
        for key, value in body.items():
            if key == "thread_id" and isinstance(value, str) and value:
                found.append(value)
            elif isinstance(value, (dict, list)):
                found += _thread_ids(value, depth + 1)
        if body.get("entry") == "cockpit" and body.get("session_id"):
            found.append(str(body["session_id"]))
    elif isinstance(body, list):
        for item in body[:50]:
            found += _thread_ids(item, depth + 1)
    return list(dict.fromkeys(found))


def _link(store: Any, tenant: str, kind: str, record_id: str
          ) -> dict[str, Any] | None:
    e = store.ledger_entry(tenant_id=tenant, kind=kind, record_id=record_id)
    if e is None:
        return None
    return {"seq": e["seq"], "record_hash": e["record_hash"],
            "chain_hash": e["chain_hash"], "backfilled": bool(e["backfilled"]),
            "links": e["links"], "row_matches": e["row_matches"]}


def _ancestors(svc: ObjectService, who: Any, obj: dict[str, Any]
               ) -> tuple[list[dict[str, Any]], bool]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    frontier = [(src, int(ver), 1) for src, ver in
                obj["lineage"].get("derived_from", []) or []]
    truncated = False
    while frontier:
        src, ver, depth = frontier.pop(0)
        if (src, ver) in seen:
            continue
        seen.add((src, ver))
        if depth > MAX_DEPTH:
            truncated = True
            continue
        found = svc.store.get(src, tenant_id=who.tenant, version=ver)
        latest = svc.store.get(src, tenant_id=who.tenant)
        if not found or not latest or not can_read(latest, who):
            out.append({"object_id": src, "version": ver, "depth": depth,
                        "readable": False})
            continue
        out.append({"object_id": src, "version": ver, "depth": depth,
                    "readable": True, "kind": found["kind"],
                    "title": found["title"],
                    "content_hash": found["content_hash"],
                    "operation": found["lineage"].get("origin", "")})
        frontier += [(s, int(v), depth + 1) for s, v in
                     found["lineage"].get("derived_from", []) or []]
    return out, truncated


def _events(svc: ObjectService, who: Any, obj: dict[str, Any]
            ) -> list[dict[str, Any]]:
    store, tenant, oid = svc.store, who.tenant, obj["object_id"]
    events: list[dict[str, Any]] = []
    for c in store.comments(oid, tenant_id=tenant):
        events.append({"at": c["created_at"], "type": "comment",
                       "actor": c["author_id"], "version": c["version"],
                       "detail": c["body"], "record_id": c["comment_id"],
                       "ledger": _link(store, tenant, "comment",
                                       c["comment_id"])})
    owner = obj["owner_id"] == who.id
    for s in store.shares_of(oid, tenant_id=tenant):
        if not owner and who.id not in (s["from_id"], s["to_id"]):
            continue
        events.append({"at": s["created_at"], "type": "share",
                       "actor": s["from_id"], "version": s["version"],
                       "detail": f"shared with {s['to_id']}",
                       "record_id": s["share_id"],
                       "ledger": _link(store, tenant, "share", s["share_id"])})
    if obj["kind"] == "run":
        for entry in obj["body"].get("state_log", []) or []:
            events.append({"at": entry.get("at"), "type": "run_state",
                           "actor": obj["owner_id"],
                           "detail": f"{entry.get('state')}: "
                                     f"{entry.get('reason', '')}"})
    if obj["kind"] == "lens":
        for o in store.observations(oid, tenant_id=tenant, limit=200):
            events.append({"at": o["started_at"], "type": "lens_refresh",
                           "actor": o["trigger"],
                           "detail": f"{o['status']} · {o['period']} · "
                                     f"{o['release_id']}"
                                     + (f" · {o['error']}" if o["error"]
                                        else ""),
                           "record_id": o["observation_id"],
                           "ledger": _link(store, tenant, "observation",
                                           o["observation_id"])})
    if obj["kind"] == "alert":
        for e in store.alert_events(oid, tenant_id=tenant):
            events.append({"at": e["at"], "type": "alert_state",
                           "actor": e["actor_id"],
                           "detail": f"{e['from_state'] or '—'} → "
                                     f"{e['to_state']}"
                                     + (f" · {e['note']}" if e["note"] else ""),
                           "record_id": e["event_id"],
                           "ledger": _link(store, tenant, "alert_event",
                                           e["event_id"])})
    return sorted(events, key=lambda e: e.get("at") or 0)


def _exchanges(who_raw: dict[str, Any], tenant: str, threads: list[str]
               ) -> dict[str, Any]:
    if not threads:
        return {"threads": [], "calls": [], "visible": True}
    try:
        access.require_exchange_reader(who_raw)
    except HTTPException:
        return {"threads": threads, "calls": [], "visible": False,
                "note": "The full LLM exchange is shown to administrators, "
                        "model-risk reviewers and auditors."}
    from backend.workspace.exchange_api import exchange_store

    store = exchange_store()
    calls = []
    for thread in threads:
        for c in store.search(tenant_id=tenant, thread_id=thread, limit=500):
            full = store.get(c["exchange_id"], tenant_id=tenant) or {}
            calls.append({
                "exchange_id": c["exchange_id"], "run_id": c["run_id"],
                "thread_id": thread, "seq": c["seq"],
                "purpose": c["purpose"], "model": c["resolved_model"],
                "status": c["status"], "started_at": c["started_at"],
                "replay_of": c["replay_of"],
                "hashes": full.get("hashes", {})})
    return {"threads": threads, "visible": True,
            "calls": sorted(calls, key=lambda c: (c["started_at"] or 0,
                                                  c["seq"]))}


def object_trace(who_raw: dict[str, Any], object_id: str) -> dict[str, Any]:
    svc = service.objects()
    who = service.principal(who_raw)
    try:
        obj = svc.get(object_id, who)
        versions = svc.history(object_id, who)
    except IntegrityError as err:
        return {"object_id": object_id, "integrity": {
            "ok": False, "problem": "CONTENT_HASH_MISMATCH",
            "message": str(err)}}
    out_versions = []
    for v in versions:
        rid = f"{object_id}@v{v['version']}"
        out_versions.append({
            "version": v["version"], "status": v["status"],
            "title": v["title"], "reason": v["lineage"].get("reason", ""),
            "operation": v["lineage"].get("origin", ""),
            "content_hash": v["content_hash"], "content_verified": True,
            "release_id": v["release_id"], "fingerprint": v["fingerprint"],
            "period": v["period"], "created_at": v["created_at"],
            "created_by": v["created_by"],
            "ledger": _link(svc.store, who.tenant, "object", rid)})
    ancestors, truncated = _ancestors(svc, who, obj)
    descendants = svc.lineage_tree(object_id, who)["descendants"]
    events = _events(svc, who, obj)
    threads = list(dict.fromkeys(t for v in versions
                                 for t in _thread_ids(v["body"])))
    llm = _exchanges(who_raw, who.tenant, threads)
    links = [v["ledger"] for v in out_versions] + \
        [e["ledger"] for e in events if "ledger" in e]
    unledgered = sum(1 for link in links if link is None)
    broken = sum(1 for link in links if link and not (
        link["links"] and link["row_matches"]))
    body = obj["body"]
    return {
        "object_id": object_id, "kind": obj["kind"], "title": obj["title"],
        "version": obj["version"], "owner_id": obj["owner_id"],
        "domain_id": obj["domain_id"], "release_id": obj["release_id"],
        "fingerprint": obj["fingerprint"], "period": obj["period"],
        "status": obj["status"], "seeded": obj["seeded"],
        "digests": {k: body[k] for k in ("contract_digest",
                                         "execution_digest",
                                         "membership_hash", "predicate_hash",
                                         "digest") if k in body},
        "versions": out_versions,
        "lineage": {"ancestors": ancestors, "descendants": descendants,
                    "truncated": truncated, "max_depth": MAX_DEPTH},
        "events": events,
        "llm_exchange": llm,
        "integrity": {
            "ok": unledgered == 0 and broken == 0,
            "content_hashes_verified": len(out_versions),
            "ledger_links": len(links) - unledgered,
            "unledgered": unledgered, "broken": broken,
            "note": "Content hashes are re-computed on every read; each "
                    "record's ledger entry is checked against the entry "
                    "before it and against the stored row."},
        "model_calls": 0,
    }


def verify_tenant(who_raw: dict[str, Any]) -> dict[str, Any]:
    who = service.principal(who_raw)
    return service.objects().store.verify_ledger(tenant_id=who.tenant)


__all__ = ["MAX_DEPTH", "object_trace", "verify_tenant"]
