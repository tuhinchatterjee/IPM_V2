"""
Shared governed objects: identity, versions, lineage and who may see them.

Every workspace object -- cohort, finding, investigation, scenario, scenario
result, lens, lens observation, metric, alert, share -- is created, revised,
duplicated and derived HERE, so the rules are the same for all of them:

* identity is `(object_id, version)`; an id never changes meaning;
* an edit writes a new version with `lineage.parent = [id, version]` and a
  reason; a duplicate or a composition writes a NEW id whose lineage names
  every source `[id, version]` and the operation; sources are never touched;
* every object carries domain, release, fingerprint, period, owner,
  permissions, trace references and a content hash;
* reading requires the same tenant AND (tenant-visible, owner, or a named
  reader); editing requires ownership or a named editor. Sharing an object
  with someone makes them a reader of THE OBJECT only: the portfolio data it
  refers to is always re-read through the reader's own tenant and book
  session, so a share can never widen data access (MSG-02).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from backend.workspace.store import WorkspaceStore

#: Object kinds and their id prefixes. Closed: an unknown kind is refused.
KINDS: dict[str, str] = {
    "cohort": "coh",
    "finding": "fnd",
    "investigation": "inv",
    "scenario": "scn",
    "scenario_result": "res",
    "lens": "lens",
    "metric": "met",
    "alert": "alr",
    "issue": "iss",
}

#: Fields the body of each kind must carry. Checked on every write, so a
#: half-formed object can never be saved and later mistaken for a real one.
REQUIRED: dict[str, tuple[str, ...]] = {
    "cohort": ("name", "domain_id", "release_id", "fingerprint", "period",
               "relation", "grain", "selection", "filters", "membership_hash",
               "predicate_hash", "counts", "ead", "ecl", "source"),
    "finding": ("statement", "evidence", "confidence", "limitations"),
    "investigation": ("title", "path"),
    "scenario": ("name", "description", "domain_id", "components",
                 "stage_policy", "composition_policy", "supported_methods",
                 "scope", "tags", "assumptions", "limitations", "severity",
                 "risk_thesis", "status"),
    "scenario_result": ("scenario_id", "scenario_version", "cohort",
                        "baseline", "methods", "results", "decomposition",
                        "release_id"),
    "lens": ("name", "description", "persona", "domain_scope", "metrics",
             "visuals", "layout", "filters", "refresh", "breach_rules",
             "audience"),
    "metric": ("metric_id", "name", "definition", "formula", "unit",
               "direction", "grain"),
    "alert": ("rule_id", "rule_version", "lens_id", "lens_version",
              "observed", "threshold", "state", "severity"),
    "issue": ("title", "severity", "evidence"),
}

#: Status vocabularies, per kind. A status outside these is refused.
STATUSES: dict[str, tuple[str, ...]] = {
    "scenario": ("DRAFT", "READY_FOR_CONFIRMATION", "CONFIRMED",
                 "METHOD_SELECTION", "EXECUTABLE", "EXECUTED", "SAVED",
                 "TEMPLATE", "SUPERSEDED", "ARCHIVED"),
    "cohort": ("ACTIVE", "STALE", "ARCHIVED"),
    "alert": ("NEW", "ACTIVE", "WORSENING", "ACKNOWLEDGED", "RESOLVED",
              "SUPPRESSED"),
    "lens": ("ACTIVE", "DRAFT", "ARCHIVED"),
}

ADMIN_ROLES = frozenset({"administrator"})
LIBRARY_OWNER = "creditprobe-library"


@dataclass(frozen=True)
class Principal:
    id: str
    tenant: str
    roles: frozenset[str]

    @classmethod
    def of(cls, who: dict[str, Any]) -> "Principal":
        from backend.workspace.access import roles_of, tenant_of

        return cls(id=str(who.get("id") or ""), tenant=tenant_of(who),
                   roles=frozenset(roles_of(who)))

    @property
    def admin(self) -> bool:
        return bool(self.roles & ADMIN_ROLES)


def new_id(kind: str) -> str:
    return f"{KINDS[kind]}-{uuid.uuid4().hex[:12]}"


def can_read(obj: dict[str, Any], who: Principal) -> bool:
    if obj["tenant_id"] != who.tenant:
        return False
    perms = obj.get("permissions") or {}
    if perms.get("visibility", "private") == "tenant":
        return True
    return (obj["owner_id"] == who.id or who.id in (perms.get("readers") or [])
            or who.id in (perms.get("editors") or []) or who.admin)


def can_edit(obj: dict[str, Any], who: Principal) -> bool:
    if obj["tenant_id"] != who.tenant:
        return False
    perms = obj.get("permissions") or {}
    return (obj["owner_id"] == who.id or who.id in (perms.get("editors") or [])
            or (who.admin and obj["owner_id"] != LIBRARY_OWNER))


def _check(kind: str, body: dict[str, Any], status: str) -> None:
    if kind not in KINDS:
        raise HTTPException(400, {"error_code": "UNKNOWN_KIND",
                                  "message": f"{kind!r} is not a workspace "
                                             f"object kind."})
    missing = [f for f in REQUIRED.get(kind, ()) if f not in body]
    if missing:
        raise HTTPException(422, {"error_code": "INCOMPLETE_OBJECT",
                                  "message": f"a {kind} needs {missing}; "
                                             f"nothing was saved.",
                                  "missing": missing})
    allowed = STATUSES.get(kind)
    if allowed and status and status not in allowed:
        raise HTTPException(422, {"error_code": "INVALID_STATUS",
                                  "message": f"{status!r} is not a {kind} "
                                             f"status; allowed: {allowed}."})


class ObjectService:
    def __init__(self, store: WorkspaceStore) -> None:
        self.store = store

    # ---- write ---------------------------------------------------------------

    def create(self, kind: str, who: Principal, body: dict[str, Any], *,
               title: str = "", domain_id: str = "", release_id: str = "",
               fingerprint: str = "", period: str = "", status: str = "",
               lineage: dict[str, Any] | None = None,
               permissions: dict[str, Any] | None = None,
               tags: list[str] | None = None,
               trace_refs: list[str] | None = None, seeded: bool = False,
               object_id: str = "", owner_id: str = "",
               created_at: float | None = None) -> dict[str, Any]:
        _check(kind, body, status)
        return self.store.insert_version({
            "object_id": object_id or new_id(kind), "version": 1,
            "kind": kind, "tenant_id": who.tenant,
            "owner_id": owner_id or who.id, "domain_id": domain_id,
            "release_id": release_id, "fingerprint": fingerprint,
            "period": period, "status": status, "title": title,
            "body": body, "lineage": lineage or {"origin": "created"},
            "permissions": permissions or {"visibility": "private",
                                           "readers": [], "editors": []},
            "trace_refs": trace_refs or [], "tags": tags or [],
            "seeded": seeded, "created_at": created_at or time.time(),
            "created_by": who.id})

    def revise(self, object_id: str, who: Principal, *,
               body: dict[str, Any] | None = None, status: str | None = None,
               title: str | None = None, reason: str,
               permissions: dict[str, Any] | None = None,
               release_id: str | None = None, fingerprint: str | None = None,
               period: str | None = None,
               trace_refs: list[str] | None = None,
               force: bool = False) -> dict[str, Any]:
        """A new version of the SAME object. The previous version stays."""
        current = self.get(object_id, who)
        if not force and not can_edit(current, who):
            raise HTTPException(403, {
                "error_code": "NOT_EDITABLE",
                "message": "Only the owner or a named editor revises this "
                           "object. Duplicate it to make your own version; "
                           "the original is not changed."})
        new_body = body if body is not None else current["body"]
        new_status = status if status is not None else current["status"]
        _check(current["kind"], new_body, new_status)
        return self.store.insert_version({
            **{k: current[k] for k in ("object_id", "kind", "tenant_id",
                                       "owner_id", "domain_id", "tags",
                                       "seeded")},
            "version": current["version"] + 1,
            "release_id": current["release_id"] if release_id is None
            else release_id,
            "fingerprint": current["fingerprint"] if fingerprint is None
            else fingerprint,
            "period": current["period"] if period is None else period,
            "status": new_status,
            "title": current["title"] if title is None else title,
            "body": new_body,
            "lineage": {"parent": [object_id, current["version"]],
                        "reason": reason,
                        "derived_from": current["lineage"].get(
                            "derived_from", [])},
            "permissions": permissions or current["permissions"],
            "trace_refs": trace_refs if trace_refs is not None
            else current["trace_refs"],
            "created_at": time.time(), "created_by": who.id})

    def derive(self, kind: str, who: Principal, body: dict[str, Any], *,
               sources: list[tuple[str, int]], operation: str,
               title: str = "", status: str = "", **meta: Any
               ) -> dict[str, Any]:
        """A NEW object built from sources (duplicate, compose, branch)."""
        return self.create(
            kind, who, body, title=title, status=status,
            lineage={"origin": operation,
                     "derived_from": [[i, int(v)] for i, v in sources]},
            **meta)

    def duplicate(self, object_id: str, who: Principal, *,
                  version: int | None = None, title: str = "",
                  body_patch: dict[str, Any] | None = None,
                  status: str | None = None) -> dict[str, Any]:
        source = self.get(object_id, who, version=version)
        body = dict(source["body"])
        body.update(body_patch or {})
        if "name" in body and title:
            body["name"] = title
        return self.derive(
            source["kind"], who, body,
            sources=[(object_id, source["version"])], operation="duplicate",
            title=title or f"{source['title']} (copy)",
            status=status if status is not None else source["status"],
            domain_id=source["domain_id"], release_id=source["release_id"],
            fingerprint=source["fingerprint"], period=source["period"],
            tags=source["tags"])

    # ---- read ------------------------------------------------------------------

    def get(self, object_id: str, who: Principal, *,
            version: int | None = None) -> dict[str, Any]:
        found = self.store.get(object_id, tenant_id=who.tenant,
                               version=version)
        if found is None or not can_read(found, who):
            raise HTTPException(404, {
                "error_code": "NOT_FOUND",
                "message": "No such object is available to you."})
        return found

    def list(self, kind: str, who: Principal, *, domain_id: str = ""
             ) -> list[dict[str, Any]]:
        return [o for o in self.store.latest_of_kind(
            kind, tenant_id=who.tenant, domain_id=domain_id)
            if can_read(o, who)]

    def history(self, object_id: str, who: Principal) -> list[dict[str, Any]]:
        self.get(object_id, who)
        return self.store.versions(object_id, tenant_id=who.tenant)

    def lineage_tree(self, object_id: str, who: Principal) -> dict[str, Any]:
        """Ancestors (from lineage) and descendants (objects naming this one)."""
        obj = self.get(object_id, who)
        ancestors = []
        for src, ver in obj["lineage"].get("derived_from", []) or []:
            found = self.store.get(src, tenant_id=who.tenant, version=ver)
            if found and can_read(found, who):
                ancestors.append({"object_id": src, "version": ver,
                                  "title": found["title"],
                                  "kind": found["kind"]})
        children = [{"object_id": c["object_id"], "version": c["version"],
                     "title": c["title"], "kind": c["kind"],
                     "operation": c["lineage"].get("origin")}
                    for c in self.store.children_of(object_id,
                                                    tenant_id=who.tenant)
                    if c["object_id"] != object_id and can_read(c, who)]
        return {"object_id": object_id, "version": obj["version"],
                "ancestors": ancestors, "descendants": children,
                "versions": [{"version": v["version"], "status": v["status"],
                              "reason": v["lineage"].get("reason", ""),
                              "content_hash": v["content_hash"],
                              "created_at": v["created_at"]}
                             for v in self.store.versions(
                                 object_id, tenant_id=who.tenant)]}

    def summary(self, obj: dict[str, Any]) -> dict[str, Any]:
        """What a list or a message card shows: no body, no data."""
        return {k: obj[k] for k in ("object_id", "version", "kind", "title",
                                    "status", "domain_id", "release_id",
                                    "period", "owner_id", "tags",
                                    "content_hash", "seeded", "created_at")}


__all__ = ["ADMIN_ROLES", "KINDS", "LIBRARY_OWNER", "ObjectService",
           "Principal", "REQUIRED", "STATUSES", "can_edit", "can_read",
           "new_id"]
