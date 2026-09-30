"""HTTP surface of the Scenario Library (§30, §44, P4).

No route here executes a scenario. Preview resolves a definition against the
book and says what WOULD happen; execution is P6's METHOD_SELECTION path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import access, service
from backend.workspace import scenario_library as lib
from backend.workspace import scenarios

router = APIRouter(tags=["workspace-scenarios"])


class Definition(BaseModel):
    definition: dict[str, Any]
    status: str = Field(default="DRAFT", pattern="^(DRAFT|SAVED)$")


class Revision(BaseModel):
    changes: dict[str, Any]
    reason: str = Field(default="edited", max_length=200)


class CloneBody(BaseModel):
    name: str = Field(default="", max_length=160)
    version: int | None = None
    changes: dict[str, Any] = Field(default_factory=dict)


class SourceRef(BaseModel):
    object_id: str = Field(min_length=4, max_length=80)
    version: int | None = None


class CombineBody(BaseModel):
    sources: list[SourceRef] = Field(min_length=2, max_length=8)
    name: str = Field(default="", max_length=160)
    resolutions: dict[str, Any] = Field(default_factory=dict)


class ResolveBody(BaseModel):
    resolutions: dict[str, Any]


class BindBody(BaseModel):
    cohort_id: str = Field(min_length=4, max_length=80)


class ShareBody(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    message: str = Field(default="", max_length=2000)
    version: int | None = None


@router.get("/scenarios")
async def list_scenarios(domain: str = "", q: str = Query("", max_length=200),
                         tag: str = "", severity: str = "", status: str = "",
                         owner: str = Query("", pattern="^(|template|mine|shared)$"),
                         method: str = "", include_archived: bool = False,
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    if domain:
        access.parse_domain(domain)
    return scenarios.listing(service.objects(), who, domain=domain, q=q,
                             tag=tag, severity=severity, status=status,
                             owner=owner, method=method,
                             include_archived=include_archived)


@router.get("/scenarios/meta")
async def scenario_meta(who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    return {"kinds": lib.KINDS, "policies": lib.POLICIES,
            "policy_text": lib.POLICY_TEXT,
            "stage_policies": lib.STAGE_POLICIES,
            "severities": lib.SEVERITIES,
            "macro_operations": lib.MACRO_OPERATIONS,
            "library_version": lib.LIBRARY_VERSION}


@router.get("/scenarios/{object_id}")
async def read_scenario(object_id: str, version: int | None = None,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    svc = service.objects()
    scenarios.ensure_seeded(svc, who)
    principal = service.principal(who)
    obj = svc.get(object_id, principal, version=version)
    return {"scenario": obj,
            "card": scenarios.card(obj, principal),
            "lineage": svc.lineage_tree(object_id, principal),
            "equation": lib.equation(obj["body"]),
            "contract_hash": lib.contract_hash(obj["body"]),
            "comments": svc.store.comments(object_id,
                                           tenant_id=principal.tenant)}


@router.post("/scenarios/{object_id}/preview")
async def preview_saved(object_id: str, version: int | None = None,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    svc = service.objects()
    scenarios.ensure_seeded(svc, who)
    obj = svc.get(object_id, service.principal(who), version=version)
    book = access.book(who, obj["domain_id"])
    out = lib.preview(book, obj["body"])
    out["object_id"], out["version"] = obj["object_id"], obj["version"]
    out["defined_on"] = {"release_id": obj["release_id"],
                         "fingerprint": obj["fingerprint"],
                         "period": obj["period"]}
    return out


@router.post("/scenarios/preview")
async def preview_unsaved(body: Definition,
                          who: dict[str, Any] = Depends(v4routes.principal)
                          ) -> dict[str, Any]:
    book = access.book(who, body.definition.get("domain_id") or "corporate")
    defn = lib.normalise_definition(body.definition, book=book)
    return lib.preview(book, defn)


@router.post("/scenarios", status_code=201)
async def create_scenario(body: Definition,
                          who: dict[str, Any] = Depends(v4routes.principal)
                          ) -> dict[str, Any]:
    return scenarios.create(service.objects(), who, body.definition,
                            status=body.status)


@router.post("/scenarios/combine", status_code=201)
async def combine_scenarios(body: CombineBody,
                            who: dict[str, Any] = Depends(v4routes.principal)
                            ) -> dict[str, Any]:
    return scenarios.combine(service.objects(), who,
                             [s.model_dump() for s in body.sources],
                             name=body.name, resolutions=body.resolutions)


@router.post("/scenarios/combine-preview")
async def combine_preview(body: CombineBody,
                          who: dict[str, Any] = Depends(v4routes.principal)
                          ) -> dict[str, Any]:
    """The component and overlap matrix BEFORE anything is saved."""
    return scenarios.combine(service.objects(), who,
                             [s.model_dump() for s in body.sources],
                             name=body.name, resolutions=body.resolutions,
                             save=False)


@router.post("/scenarios/{object_id}/revise")
async def revise_scenario(object_id: str, body: Revision,
                          who: dict[str, Any] = Depends(v4routes.principal)
                          ) -> dict[str, Any]:
    return scenarios.revise(service.objects(), who, object_id, body.changes,
                            reason=body.reason)


@router.post("/scenarios/{object_id}/clone", status_code=201)
async def clone_scenario(object_id: str, body: CloneBody,
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    return scenarios.clone(service.objects(), who, object_id,
                           version=body.version, name=body.name,
                           changes=body.changes)


@router.post("/scenarios/{object_id}/branch", status_code=201)
async def branch_scenario(object_id: str, body: CloneBody,
                          who: dict[str, Any] = Depends(v4routes.principal)
                          ) -> dict[str, Any]:
    return scenarios.clone(service.objects(), who, object_id,
                           version=body.version, name=body.name,
                           operation="branch", changes=body.changes)


@router.post("/scenarios/{object_id}/resolve")
async def resolve_overlaps(object_id: str, body: ResolveBody,
                           who: dict[str, Any] = Depends(v4routes.principal)
                           ) -> dict[str, Any]:
    return scenarios.resolve(service.objects(), who, object_id,
                             body.resolutions)


@router.post("/scenarios/{object_id}/bind")
async def bind_scenario(object_id: str, body: BindBody,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    return scenarios.bind(service.objects(), who, object_id, body.cohort_id)


@router.post("/scenarios/{object_id}/retire")
async def retire_scenario(object_id: str,
                          who: dict[str, Any] = Depends(v4routes.principal)
                          ) -> dict[str, Any]:
    return scenarios.retire(service.objects(), who, object_id)


@router.post("/scenarios/{object_id}/share")
async def share_scenario(object_id: str, body: ShareBody,
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    return scenarios.share(service.objects(), who, object_id, to=body.to,
                           message=body.message, version=body.version)


__all__ = ["router"]
