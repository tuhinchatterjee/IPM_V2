"""The Metric Catalogue as governed, versioned objects (P8, §46).

`metric_catalog.py` is the reviewed source of every definition; this module
publishes each one as a `metric` object (library-owned, tenant-visible,
seeded) so the catalogue is browsed, versioned, referenced and COUNTED from
persisted objects like every other governed thing. A definition whose text
changes in a later catalogue release becomes a new version of the same
object -- the old version stays readable, and Lenses keep naming the version
they were built on.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.workspace import metric_catalog as mc
from backend.workspace.objects import LIBRARY_OWNER, ObjectService, Principal

PERMISSIONS = {"visibility": "tenant", "readers": [], "editors": []}


def object_id(metric_id: str) -> str:
    return f"met-{metric_id.lower()}"


def body_of(metric: dict[str, Any]) -> dict[str, Any]:
    return {**metric, "direction": metric["directionality"]}


def _digest() -> str:
    blob = json.dumps([body_of(m) for m in mc.METRICS], sort_keys=True,
                      default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def ensure_seeded(svc: ObjectService, who: dict[str, Any]) -> dict[str, Any]:
    principal = Principal.of(who)
    key = f"metric_seed:{principal.tenant}"
    digest = _digest()
    if svc.store.meta(key) == digest:
        return {"created": 0, "revised": 0}
    created = revised = 0
    library = Principal(id=LIBRARY_OWNER, tenant=principal.tenant,
                        roles=frozenset({"administrator"}))
    for metric in mc.METRICS:
        oid = object_id(metric["metric_id"])
        body = body_of(metric)
        found = svc.store.get(oid, tenant_id=principal.tenant)
        if found is None:
            svc.create("metric", library, body, title=metric["name"],
                       status="", object_id=oid, owner_id=LIBRARY_OWNER,
                       permissions=dict(PERMISSIONS), seeded=True,
                       tags=[metric["domain"], metric.get("family") or ""],
                       lineage={"origin": "seeded",
                                "catalog_version": mc.CATALOG_VERSION})
            created += 1
        elif json.dumps(found["body"], sort_keys=True, default=str) != \
                json.dumps(body, sort_keys=True, default=str):
            svc.revise(oid, library, body=body, force=True,
                       reason=f"catalogue {mc.CATALOG_VERSION}")
            revised += 1
    svc.store.set_meta(key, digest)
    return {"created": created, "revised": revised}


def listing(svc: ObjectService, who: dict[str, Any], domain_id: str = ""
            ) -> list[dict[str, Any]]:
    """Every persisted metric definition, in catalogue order."""
    ensure_seeded(svc, who)
    principal = Principal.of(who)
    rows = [r for r in svc.list("metric", principal)
            if not domain_id or r["body"]["domain"] in ("both", domain_id)]
    rows.sort(key=lambda r: r["body"]["metric_id"])
    return [{**r["body"], "object_id": r["object_id"],
             "object_version": r["version"],
             "content_hash": r["content_hash"]} for r in rows]


def get(svc: ObjectService, who: dict[str, Any], metric_id: str,
        version: int | None = None) -> dict[str, Any]:
    ensure_seeded(svc, who)
    return svc.get(object_id(metric_id), Principal.of(who), version=version)


__all__ = ["body_of", "ensure_seeded", "get", "listing", "object_id"]
