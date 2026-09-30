"""Sharing a governed object: the reference and version travel, never data.

MSG-01: a share is an object id + version + a summary card. MSG-02: opening it
goes through the recipient's own `can_read` and tenant scope, so a share can
never grant data access the recipient does not already have. The sender's
private object becomes readable by a named recipient only because the OWNER
shared it (a new version recording the reader), never by anyone else.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.workspace.objects import (LIBRARY_OWNER, ObjectService, Principal,
                                       can_edit)

SHAREABLE = ("cohort", "scenario", "scenario_result", "finding",
             "investigation", "lens", "alert", "run")


def card_for(obj: dict[str, Any]) -> dict[str, Any]:
    """What a message card shows: identity and a summary, no rows."""
    b = obj["body"]
    base = {"object_id": obj["object_id"], "version": obj["version"],
            "kind": obj["kind"], "title": obj["title"],
            "status": obj["status"], "domain_id": obj["domain_id"],
            "release_id": obj["release_id"], "period": obj["period"],
            "owner_id": obj["owner_id"], "content_hash": obj["content_hash"]}
    kind = obj["kind"]
    if kind == "cohort":
        base.update(name=b["name"], entities=b["counts"]["entities"],
                    owners=b["counts"]["owners"], ead=b["ead"], ecl=b["ecl"],
                    membership_hash=b["membership_hash"],
                    description=b.get("filter_description", ""))
    elif kind == "scenario":
        base.update(name=b["name"], executed=False,
                    scope_label=b["scope"].get("label", ""),
                    components=[c["label"] for c in b["components"]],
                    parents=[p.get("name") for p in b.get("parents", [])])
    elif kind == "scenario_result":
        base.update(name=b.get("name", obj["title"]), executed=True,
                    methods=b.get("methods", []),
                    headline=b.get("headline", {}),
                    scope_label=b.get("scope_label", ""))
    elif kind == "run":
        base.update(name=b.get("name", obj["title"]),
                    state=obj["status"], methods=b.get("selected_methods", []))
    else:
        base.update(name=b.get("name") or obj["title"])
    return base


def share(svc: ObjectService, who: Principal, object_id: str, *,
          to: list[str], message: str = "", version: int | None = None
          ) -> dict[str, Any]:
    obj = svc.get(object_id, who, version=version)
    if obj["kind"] not in SHAREABLE:
        raise HTTPException(422, {"error_code": "NOT_SHAREABLE",
                                  "message": f"a {obj['kind']} is not shared "
                                             f"as an object."})
    recipients = [str(t).strip()[:120] for t in to if str(t).strip()][:20]
    if not recipients:
        raise HTTPException(422, {"error_code": "NO_RECIPIENT",
                                  "message": "name at least one recipient."})
    if who.id in recipients:
        recipients = [r for r in recipients if r != who.id]
        if not recipients:
            raise HTTPException(422, {"error_code": "NO_RECIPIENT",
                                      "message": "you cannot share with "
                                                 "yourself."})
    perms = dict(obj.get("permissions") or {})
    if obj["owner_id"] not in (who.id, LIBRARY_OWNER) and \
            perms.get("visibility") != "tenant" and not can_edit(obj, who):
        # Re-sharing someone else's private object would widen access.
        raise HTTPException(403, {"error_code": "NOT_SHAREABLE",
                                  "message": "Only the owner shares a private "
                                             "object."})
    if obj["owner_id"] == who.id and perms.get("visibility") != "tenant":
        readers = sorted(set(perms.get("readers") or []) | set(recipients))
        if readers != sorted(perms.get("readers") or []):
            obj = svc.revise(object_id, who,
                             permissions={**perms, "readers": readers},
                             reason=f"shared with {', '.join(recipients)}")
    card = card_for(obj)
    rows = [svc.store.add_share(tenant_id=who.tenant, object_id=object_id,
                                version=obj["version"], kind=obj["kind"],
                                from_id=who.id, to_id=r,
                                message=message[:2000], card=card)
            for r in recipients]
    return {"shared": rows, "object": card}


__all__ = ["SHAREABLE", "card_for", "share"]
