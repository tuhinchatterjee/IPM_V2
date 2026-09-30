"""The Scenario Library as saved objects: seeding, listing, and every verb that
creates a new definition or a new version without touching an existing one.

Templates are seeded per tenant, idempotently, owned by the library
(`LIBRARY_OWNER`), visible to the whole tenant and editable by nobody: a user
clones one to change it. Every write goes through `ObjectService`, whose store
refuses UPDATE and DELETE -- so "no destructive mutation of source scenarios"
is a property of the table, and the tests below prove it on the rows.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException

from backend.workspace import access, cohorts
from backend.workspace import scenario_library as lib
from backend.workspace import scenario_seed as seed
from backend.workspace.objects import LIBRARY_OWNER, ObjectService, Principal, can_edit

LIBRARY_PERMISSIONS = {"visibility": "tenant", "readers": [], "editors": []}


def template_object_id(template_id: str) -> str:
    return "scn-tpl-" + template_id.lower()


def ensure_seeded(svc: ObjectService, who: dict[str, Any]) -> dict[str, Any]:
    """Seed the §44 catalogue for this tenant once; report what exists."""
    principal = Principal.of(who)
    key = f"scenario_seed:{principal.tenant}"
    if svc.store.meta(key) == seed.SEED_VERSION:
        return {"seed_version": seed.SEED_VERSION, "created": 0}
    created, skipped = 0, []
    books: dict[str, Any] = {}
    for tpl in seed.TEMPLATES:
        domain = tpl["domain_id"]
        if domain not in books:
            try:
                books[domain] = access.book(who, domain)
            except HTTPException as exc:
                books[domain] = None
                skipped.append({"domain": domain, "reason": str(exc.detail)})
        book = books[domain]
        if book is None:
            continue
        oid = template_object_id(tpl["template_id"])
        if svc.store.get(oid, tenant_id=principal.tenant) is not None:
            continue
        body = lib.normalise_definition(tpl, book=book)
        body["status"] = "TEMPLATE"
        svc.create("scenario", principal, body, title=body["name"],
                   domain_id=domain, release_id=book.release_id,
                   fingerprint=book.fingerprint, period=book.latest_period,
                   status="TEMPLATE", tags=body["tags"],
                   permissions=dict(LIBRARY_PERMISSIONS), seeded=True,
                   object_id=oid, owner_id=LIBRARY_OWNER,
                   lineage={"origin": "seeded", "seed_version":
                            seed.SEED_VERSION,
                            "template_id": tpl["template_id"]})
        created += 1
    if not skipped:
        svc.store.set_meta(key, seed.SEED_VERSION)
    return {"seed_version": seed.SEED_VERSION, "created": created,
            "skipped": skipped}


# ---- listing --------------------------------------------------------------------

def card(obj: dict[str, Any], who: Principal, *, results: int = 0
         ) -> dict[str, Any]:
    body = obj["body"]
    return {
        "object_id": obj["object_id"], "version": obj["version"],
        "name": body["name"], "template_id": body.get("template_id", ""),
        "domain_id": obj["domain_id"], "description": body["description"],
        "risk_thesis": body.get("risk_thesis", ""),
        "scope_label": body["scope"].get("label", ""),
        "scope_type": body["scope"]["type"],
        "components": [{"component_id": c["component_id"], "kind": c["kind"],
                        "label": c["label"]} for c in body["components"]],
        "supported_methods": body["supported_methods"],
        "stage_policy": body["stage_policy"], "severity": body["severity"],
        "tags": body["tags"], "status": obj["status"],
        "owner_id": obj["owner_id"], "is_template": obj["owner_id"] ==
        LIBRARY_OWNER, "can_edit": can_edit(obj, who),
        "bound_cohort": body.get("bound_cohort"),
        "parents": body.get("parents", []),
        "resolved_overlaps": len(body.get("composition_policy", {})
                                 .get("resolutions") or {}),
        "results": results, "content_hash": obj["content_hash"],
        "created_at": obj["created_at"], "release_id": obj["release_id"],
        "lineage_origin": obj["lineage"].get("origin", ""),
    }


def listing(svc: ObjectService, who: dict[str, Any], *, domain: str = "",
            q: str = "", tag: str = "", severity: str = "", status: str = "",
            owner: str = "", method: str = "", include_archived: bool = False
            ) -> dict[str, Any]:
    ensure_seeded(svc, who)
    principal = Principal.of(who)
    objs = svc.list("scenario", principal, domain_id=domain)
    results_by: dict[str, int] = {}
    for r in svc.store.latest_of_kind("scenario_result",
                                      tenant_id=principal.tenant):
        sid = r["body"].get("scenario_id")
        results_by[sid] = results_by.get(sid, 0) + 1
    needle = q.strip().lower()
    out = []
    for o in objs:
        if o["status"] == "ARCHIVED" and not include_archived and \
                status != "ARCHIVED":
            continue
        b = o["body"]
        hay = " ".join([b["name"], b["description"], b.get("risk_thesis", ""),
                        b.get("template_id", ""), b["scope"].get("label", ""),
                        " ".join(b["tags"]),
                        " ".join(c["label"] for c in b["components"])]).lower()
        if needle and needle not in hay:
            continue
        if tag and tag not in b["tags"]:
            continue
        if severity and b["severity"] != severity:
            continue
        if status and o["status"] != status:
            continue
        if method and method not in b["supported_methods"]:
            continue
        if owner == "template" and o["owner_id"] != LIBRARY_OWNER:
            continue
        if owner == "mine" and o["owner_id"] != principal.id:
            continue
        if owner == "shared" and o["owner_id"] in (principal.id,
                                                   LIBRARY_OWNER):
            continue
        out.append(card(o, principal, results=results_by.get(
            o["object_id"], 0)))
    out.sort(key=lambda c: (not c["is_template"], c.get("template_id") or "~",
                            -c["created_at"]))
    facets: dict[str, dict[str, int]] = {"domain": {}, "severity": {},
                                         "tag": {}, "status": {}}
    for c in out:
        for k, val in (("domain", c["domain_id"]), ("severity", c["severity"]),
                       ("status", c["status"])):
            facets[k][val] = facets[k].get(val, 0) + 1
        for t in c["tags"]:
            facets["tag"][t] = facets["tag"].get(t, 0) + 1
    return {"scenarios": out, "total": len(out), "facets": facets,
            "seed_version": seed.SEED_VERSION}


# ---- verbs ----------------------------------------------------------------------

def _book_for(who: dict[str, Any], obj_or_body: dict[str, Any]):
    domain = obj_or_body.get("domain_id") or obj_or_body.get("body", {}).get(
        "domain_id")
    return access.book(who, domain)


def create(svc: ObjectService, who: dict[str, Any], definition: dict[str, Any],
           *, status: str = "DRAFT") -> dict[str, Any]:
    if status not in ("DRAFT", "SAVED"):
        raise HTTPException(422, {"error_code": "INVALID_STATUS",
                                  "message": "a new scenario is DRAFT or "
                                             "SAVED; nothing is executed."})
    book = access.book(who, definition.get("domain_id") or "corporate")
    body = lib.normalise_definition({**definition, "status": status,
                                     "template_id": ""}, book=book)
    return svc.create("scenario", Principal.of(who), body, title=body["name"],
                      domain_id=book.domain_id, release_id=book.release_id,
                      fingerprint=book.fingerprint, period=book.latest_period,
                      status=status, tags=body["tags"])


def revise(svc: ObjectService, who: dict[str, Any], object_id: str,
           changes: dict[str, Any], *, reason: str) -> dict[str, Any]:
    principal = Principal.of(who)
    current = svc.get(object_id, principal)
    if current["owner_id"] == LIBRARY_OWNER:
        raise HTTPException(403, {"error_code": "TEMPLATE_READ_ONLY",
                                  "message": "Library templates are not "
                                             "edited; clone one to make your "
                                             "own version."})
    merged = {**current["body"], **{k: v for k, v in changes.items()
                                    if k not in ("domain_id", "parents",
                                                 "template_id")}}
    body = lib.normalise_definition(merged, book=_book_for(who, current))
    status = changes.get("status") or current["status"]
    return svc.revise(object_id, principal, body=body, status=status,
                      title=body["name"], reason=reason)


def clone(svc: ObjectService, who: dict[str, Any], object_id: str, *,
          version: int | None = None, name: str = "",
          operation: str = "duplicate", changes: dict[str, Any] | None = None
          ) -> dict[str, Any]:
    """A NEW scenario from an existing one (duplicate or branch)."""
    principal = Principal.of(who)
    source = svc.get(object_id, principal, version=version)
    merged = {**source["body"], **(changes or {})}
    merged["name"] = name or (f"{source['body']['name']} (copy)"
                              if operation == "duplicate" else
                              f"{source['body']['name']} (branch)")
    merged["template_id"] = ""
    merged["parents"] = [{"object_id": object_id,
                          "version": source["version"],
                          "name": source["body"]["name"],
                          "content_hash": source["content_hash"]}]
    book = _book_for(who, source)
    body = lib.normalise_definition({**merged, "status": "DRAFT"}, book=book)
    if source["body"].get("template_id"):
        body["cloned_from_template"] = source["body"]["template_id"]
    return svc.derive("scenario", principal, body,
                      sources=[(object_id, source["version"])],
                      operation=operation, title=body["name"], status="DRAFT",
                      domain_id=book.domain_id, release_id=book.release_id,
                      fingerprint=book.fingerprint, period=book.latest_period,
                      tags=body["tags"])


def combine(svc: ObjectService, who: dict[str, Any],
            sources: list[dict[str, Any]], *, name: str,
            resolutions: dict[str, Any] | None = None, save: bool = True
            ) -> dict[str, Any]:
    principal = Principal.of(who)
    objs = [svc.get(s["object_id"], principal, version=s.get("version"))
            for s in sources]
    raw = lib.combine(objs, name=name or " + ".join(
        o["body"]["name"] for o in objs), resolutions=resolutions)
    book = _book_for(who, raw)
    body = lib.normalise_definition(raw, book=book)
    pv = lib.preview(book, body)
    if not save:
        return {"definition": body, "preview": pv}
    obj = svc.derive("scenario", principal, body,
                     sources=[(o["object_id"], o["version"]) for o in objs],
                     operation="combine", title=body["name"], status="DRAFT",
                     domain_id=book.domain_id, release_id=book.release_id,
                     fingerprint=book.fingerprint, period=book.latest_period,
                     tags=body["tags"])
    return {"scenario": obj, "preview": pv}


def resolve(svc: ObjectService, who: dict[str, Any], object_id: str,
            resolutions: dict[str, Any]) -> dict[str, Any]:
    """Record explicit composition policies as a new version."""
    principal = Principal.of(who)
    current = svc.get(object_id, principal)
    merged = dict(current["body"]["composition_policy"]["resolutions"])
    merged.update(resolutions)
    return revise(svc, who, object_id, {"composition_policy": {
        "resolutions": merged,
        "note": current["body"]["composition_policy"].get("note", "")}},
        reason="composition policy chosen")


def bind(svc: ObjectService, who: dict[str, Any], object_id: str,
         cohort_id: str) -> dict[str, Any]:
    """Bind to a governed cohort: a new version (own) or a new scenario
    (template / someone else's). The cohort must belong to the same book."""
    principal = Principal.of(who)
    scenario = svc.get(object_id, principal)
    cohort = svc.get(cohort_id, principal)
    if cohort["kind"] != "cohort":
        raise HTTPException(422, {"error_code": "NOT_A_COHORT",
                                  "message": f"{cohort_id} is not a cohort."})
    if cohort["domain_id"] != scenario["domain_id"]:
        raise HTTPException(422, {"error_code": "INCOMPATIBLE_COHORT",
                                  "message": f"The cohort is on the "
                                             f"{cohort['domain_id']} book and "
                                             f"the scenario is "
                                             f"{scenario['domain_id']}."})
    book = access.book(who, scenario["domain_id"])
    check = cohorts.verify(book, cohort)
    cb = cohort["body"]
    change = {"scope": {"type": "cohort", "cohort_id": cohort_id,
                        "cohort_version": cohort["version"],
                        "label": f"Cohort: {cb['name']}",
                        "filters": cb["filters"],
                        "membership_hash": cb["membership_hash"]},
              "bound_cohort": {"cohort_id": cohort_id,
                               "version": cohort["version"],
                               "membership_hash": cb["membership_hash"],
                               "entities": cb["counts"]["entities"],
                               "verified": check["status"],
                               "bound_at": time.time()}}
    if can_edit(scenario, principal):
        obj = revise(svc, who, object_id, change,
                     reason=f"bound to cohort {cohort_id}")
    else:
        obj = clone(svc, who, object_id, operation="bind", changes=change,
                    name=f"{scenario['body']['name']} on {cb['name']}")
    return {"scenario": obj, "cohort_check": check}


def results(svc: ObjectService, who: dict[str, Any], object_id: str
            ) -> list[dict[str, Any]]:
    """Persisted results of this scenario (any version), newest first."""
    principal = Principal.of(who)
    svc.get(object_id, principal)
    out = []
    for r in svc.list("scenario_result", principal):
        b = r["body"]
        if b.get("scenario_id") != object_id:
            continue
        out.append({**svc.summary(r), "run_id": b.get("run_id", ""),
                    "scenario_version": b.get("scenario_version"),
                    "methods_ran": b["methods"]["ran"],
                    "baseline_mode": b["baseline"].get("mode", ""),
                    "cohort": b["cohort"].get("description", ""),
                    "changes": {m: v.get("change") for m, v in
                                b["results"].items() if v.get("ran")}})
    return sorted(out, key=lambda x: -x["created_at"])


def retire(svc: ObjectService, who: dict[str, Any], object_id: str
           ) -> dict[str, Any]:
    principal = Principal.of(who)
    current = svc.get(object_id, principal)
    if current["owner_id"] == LIBRARY_OWNER:
        raise HTTPException(403, {"error_code": "TEMPLATE_READ_ONLY",
                                  "message": "Library templates are retired "
                                             "only by a new seed version."})
    return svc.revise(object_id, principal, status="ARCHIVED",
                      reason="retired")


def share(svc: ObjectService, who: dict[str, Any], object_id: str, *,
          to: list[str], message: str = "", version: int | None = None
          ) -> dict[str, Any]:
    """Share the object reference and version -- never its data (MSG-01/02).

    Tenant scoping is the store's: a recipient outside the tenant never sees
    the share, and opening it runs through the same `can_read` check.
    """
    principal = Principal.of(who)
    obj = svc.get(object_id, principal, version=version)
    recipients = [str(t)[:120] for t in to if str(t).strip()][:20]
    if not recipients:
        raise HTTPException(422, {"error_code": "NO_RECIPIENT",
                                  "message": "name at least one recipient."})
    if obj["owner_id"] not in (principal.id, LIBRARY_OWNER) and \
            not can_edit(obj, principal):
        # Re-sharing someone else's private scenario would widen access.
        perms = obj.get("permissions") or {}
        if perms.get("visibility") != "tenant":
            raise HTTPException(403, {"error_code": "NOT_SHAREABLE",
                                      "message": "Only the owner shares a "
                                                 "private scenario."})
    if obj["owner_id"] == principal.id:
        perms = dict(obj["permissions"])
        readers = sorted(set(perms.get("readers") or []) | set(recipients))
        if readers != sorted(perms.get("readers") or []):
            obj = svc.revise(object_id, principal,
                             permissions={**perms, "readers": readers},
                             reason=f"shared with {', '.join(recipients)}")
    summary = svc.summary(obj)
    rows = [svc.store.add_share(tenant_id=principal.tenant,
                                object_id=object_id, version=obj["version"],
                                kind="scenario", from_id=principal.id,
                                to_id=r, message=message[:2000],
                                card={**summary, "name": obj["body"]["name"],
                                      "executed": False,
                                      "scope_label": obj["body"]["scope"]
                                      .get("label", ""),
                                      "components": [c["label"] for c in
                                                     obj["body"]
                                                     ["components"]]})
            for r in recipients]
    return {"shared": rows, "scenario": summary}


__all__ = ["bind", "card", "clone", "combine", "create", "ensure_seeded",
           "listing", "resolve", "retire", "revise", "share",
           "template_object_id"]
