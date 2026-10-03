"""HTTP surface for the governance Trace and governed export packages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import exports, trace
from backend.workspace.errors import GovernedRoute

router = APIRouter(tags=["workspace-trace"], route_class=GovernedRoute)

#: Largest package `verify` accepts.
VERIFY_MAX_BYTES = 64_000_000


@router.get("/trace/objects/{object_id}")
async def object_trace(object_id: str,
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    """Versions, hashes, ledger links, lineage, events and LLM exchanges."""
    return trace.object_trace(who, object_id)


@router.get("/trace/ledger/verify")
async def verify_ledger(who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    """Re-walk this tenant's hash chain and re-hash every governed record."""
    return trace.verify_tenant(who)


class ExportRequest(BaseModel):
    include_llm_exchange: bool = False
    snapshots: list[dict[str, Any]] = Field(default_factory=list,
                                            max_length=exports.MAX_SNAPSHOTS)


def _zip(data: bytes, manifest: dict[str, Any]) -> Response:
    root = manifest["root"]
    name = f"creditprobe_{root['object_id']}_v{root['version']}.zip"
    return Response(content=data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Package-Root-Hash": root["content_hash"],
        "X-Package-Files": str(len(manifest["files"])),
        # The page reads these from another origin (the V4 API).
        "Access-Control-Expose-Headers":
            "Content-Disposition, X-Package-Root-Hash, X-Package-Files"})


@router.post("/exports/objects/{object_id}")
async def export_object(object_id: str, body: ExportRequest,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> Response:
    """A governed package; the page may attach its chart snapshots."""
    data, manifest = exports.package(
        who, object_id, include_llm_exchange=body.include_llm_exchange,
        snapshots=body.snapshots)
    return _zip(data, manifest)


@router.get("/exports/objects/{object_id}")
async def export_object_plain(object_id: str,
                              include_llm_exchange: bool = False,
                              who: dict[str, Any] = Depends(
                                  v4routes.principal)) -> Response:
    data, manifest = exports.package(
        who, object_id, include_llm_exchange=include_llm_exchange)
    return _zip(data, manifest)


@router.post("/exports/verify")
async def verify_export(request: Request,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    """Upload a package (raw ZIP body): files, objects and tables are
    re-hashed and held against the store."""
    data = await request.body()
    if len(data) > VERIFY_MAX_BYTES:
        from fastapi import HTTPException

        raise HTTPException(413, {"error_code": "PACKAGE_TOO_LARGE",
                                  "message": "Package exceeds the verify "
                                             "limit."})
    return exports.verify_package(who, data)
