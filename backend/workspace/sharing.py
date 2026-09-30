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

from backend.workspace.objects import LIBRARY_OWNER, ObjectService, Principal, can_edit

SHAREABLE = ("cohort", "scenario", "scenario_result", "finding",
             "investigation", "lens", "alert", "run", "comparison")


def _top_components(d: dict[str, Any], n: int = 3) -> list[dict[str, Any]]:
    comps = [c for c in d["scopes"]["selected"]["components"]
             if c["kind"] != "total" and c["value"] not in (None, "")
             and abs(float(c["value"])) > 0]
    comps.sort(key=lambda c: -abs(float(c["value"])))
    return [{"id": c["id"], "label": c["label"], "value": c["value"]}
            for c in comps[:n]]


def card_for(obj: dict[str, Any]) -> dict[str, Any]:
    """What a message card shows: identity and a summary, no rows."""
    b = obj["body"]
    base = {"object_id": obj["object_id"], "version": obj["version"],
            "kind": obj["kind"], "title": obj["title"],
            "status": obj["status"], "domain_id": obj["domain_id"],
            "release_id": obj["release_id"], "period": obj["period"],
            "owner_id": obj["owner_id"], "content_hash": obj["content_hash"],
            "seeded": bool(obj.get("seeded"))}
    kind = obj["kind"]
    if kind == "cohort":
        base.update(name=b["name"], entities=b["counts"]["entities"],
                    owners=b["counts"]["owners"], ead=b["ead"], ecl=b["ecl"],
                    membership_hash=b["membership_hash"],
                    description=b.get("filter_description", ""))
    elif kind == "scenario":
        base.update(name=b["name"], executed=False,
                    scope_label=b["scope"].get("label", ""),
                    template_id=b.get("template_id", ""),
                    components=[c["label"] for c in b["components"]],
                    stage_policy=b.get("stage_policy", ""),
                    author=obj["owner_id"],
                    parents=[p.get("name") for p in b.get("parents", [])])
    elif kind == "scenario_result":
        method = next((m for m in ("delta", "user_defined", "ml")
                       if m in b["decomposition"]), "")
        d = b["decomposition"].get(method) if method else None
        base.update(
            name=b["scenario_name"], executed=True,
            scenario_id=b["scenario_id"],
            scenario_version=b["scenario_version"],
            methods=b["methods"]["ran"],
            methods_unavailable=b["methods"].get("unavailable", {}),
            baseline=b["baseline"].get("mode", "SOURCE_BASELINE"),
            chain=[c.get("name") for c in b.get("chain") or []],
            scope_label=b["cohort"].get("description", ""),
            entities=b["cohort"].get("entity_count"),
            changes={m: v.get("change") for m, v in b["results"].items()
                     if v.get("ran")},
            summary_method=method,
            selected_change=d["scopes"]["selected"]["change"] if d else None,
            total_change=d["scopes"]["total"]["change"] if d else None,
            top_components=_top_components(d) if d else [],
            limitations=[n for n in b.get("notes", [])][:4],
            entry=b.get("entry", "whatif"),
            thread_id=b.get("thread_id", ""))
    elif kind == "run":
        base.update(name=b.get("scenario_name", obj["title"]),
                    state=obj["status"],
                    methods=b.get("methods_ran") or b.get("methods_chosen"),
                    baseline=b.get("baseline", {}).get("mode", ""),
                    result_id=b.get("result_id", ""))
    elif kind == "comparison":
        base.update(name=obj["title"], method=b["method"],
                    items=[i["scenario_name"] for i in b["items"]],
                    result_ids=[i["result_id"] for i in b["items"]])
    else:
        base.update(name=b.get("name") or obj["title"])
    return base


def _dependencies(svc: ObjectService, who: Principal, obj: dict[str, Any]
                  ) -> list[tuple[str, int | None]]:
    """What the recipient needs to open or re-run the shared object: a
    result's scenario version and cohort, a scenario's bound cohort, a
    comparison's results. Same tenant, same book; object identity only."""
    b, kind = obj["body"], obj["kind"]
    out: list[tuple[str, int | None]] = []
    if kind == "scenario_result" and b.get("entry") != "cockpit":
        out.append((b["scenario_id"], b.get("scenario_version")))
        coh = (b.get("cohort") or {}).get("object") or {}
        if coh.get("cohort_id"):
            out.append((coh["cohort_id"], coh.get("version")))
    elif kind == "scenario":
        scope = b.get("scope") or {}
        if scope.get("type") == "cohort" and scope.get("cohort_id"):
            out.append((scope["cohort_id"], scope.get("cohort_version")))
    elif kind == "comparison":
        out.extend((i["result_id"], i.get("version")) for i in b["items"])
    elif kind == "run":
        out.append((b["scenario_id"], b.get("scenario_version")))
        if b.get("result_id"):
            out.append((b["result_id"], None))
    return out


def _grant(svc: ObjectService, who: Principal, object_id: str,
           recipients: list[str]) -> dict[str, Any]:
    """Name the recipients as readers of an object the sharer OWNS."""
    obj = svc.get(object_id, who)
    perms = dict(obj.get("permissions") or {})
    if obj["owner_id"] == who.id and perms.get("visibility") != "tenant":
        readers = sorted(set(perms.get("readers") or []) | set(recipients))
        if readers != sorted(perms.get("readers") or []):
            obj = svc.revise(object_id, who,
                             permissions={**perms, "readers": readers},
                             reason=f"shared with {', '.join(recipients)}")
    return obj


def share(svc: ObjectService, who: Principal, object_id: str, *,
          to: list[str], message: str = "", version: int | None = None,
          seeded: bool = False) -> dict[str, Any]:
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
    pinned = obj["version"]
    obj = _grant(svc, who, object_id, recipients)
    # Readers are a property of the object; the share still names the
    # version the sender chose (a grant writes a new version with the same
    # body and content hash).
    if version is not None:
        obj = svc.get(object_id, who, version=pinned) \
            if pinned != obj["version"] else obj
    attached = []
    for dep_id, dep_version in _dependencies(svc, who, obj):
        try:
            dep = _grant(svc, who, dep_id, recipients)
        except HTTPException:
            continue  # not the sender's to share: the recipient sees why
        attached.append({"object_id": dep_id, "kind": dep["kind"],
                         "version": dep_version or dep["version"]})
    card = card_for(obj)
    card["attachments"] = attached
    rows = [svc.store.add_share(tenant_id=who.tenant, object_id=object_id,
                                version=obj["version"], kind=obj["kind"],
                                from_id=who.id, to_id=r,
                                message=message[:2000], card=card,
                                seeded=seeded)
            for r in recipients]
    return {"shared": rows, "object": card}


__all__ = ["SHAREABLE", "card_for", "share"]
