"""The latest-period portfolio grid over HTTP: schema, query, values, export.

Server-side paging, sorting and filtering only. The largest page is
`grid.PAGE_MAX` rows; the whole book never reaches the browser (GRID14/PV-06).
An export writes the filtered rows with the release, fingerprint, period and
filter definition as header lines, raw values unchanged (GRID21/FMT08).
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import access, grid, predicates, service

router = APIRouter(tags=["workspace-grid"])


@router.get("/grid/schema")
async def grid_schema(domain: str = Query("corporate"), period: str = Query(""),
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    return grid.schema(access.book(who, domain), period)


class GridQuery(BaseModel):
    domain: str = Field(default="corporate", max_length=20)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    sort: str = Field(default="ecl_sar_mn", max_length=60)
    desc: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=grid.PAGE_MAX)
    period: str = Field(default="", max_length=12)


@router.post("/grid/query")
async def grid_query(body: GridQuery,
                     who: dict[str, Any] = Depends(v4routes.principal)
                     ) -> dict[str, Any]:
    return grid.query(access.book(who, body.domain), filters=body.filters,
                      sort=body.sort, desc=body.desc, offset=body.offset,
                      limit=body.limit, period=body.period)


@router.get("/grid/values")
async def grid_values(domain: str = Query("corporate"), column: str = Query(...),
                      search: str = Query("", max_length=100),
                      period: str = Query(""),
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    return grid.distinct(access.book(who, domain), column, search=search,
                         period=period)


class GridGroup(BaseModel):
    domain: str = Field(default="corporate", max_length=20)
    dimension: str = Field(max_length=60)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    period: str = Field(default="", max_length=12)


@router.post("/grid/group")
async def grid_group(body: GridGroup,
                     who: dict[str, Any] = Depends(v4routes.principal)
                     ) -> dict[str, Any]:
    book = access.book(who, body.domain)
    return {"dimension": body.dimension,
            "groups": grid.grouped(book, dimension=body.dimension,
                                   filters=body.filters, period=body.period)}


class GridGroup2(BaseModel):
    domain: str = Field(default="corporate", max_length=20)
    x: str = Field(max_length=60)
    y: str = Field(max_length=60)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    period: str = Field(default="", max_length=12)


@router.post("/grid/group2")
async def grid_group2(body: GridGroup2,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    """Two-dimension aggregate: heatmaps and stage-migration flows."""
    book = access.book(who, body.domain)
    return grid.grouped2(book, x=body.x, y=body.y, filters=body.filters,
                         period=body.period)


def export_csv(book: access.Book, *, filters: Any, period: str = "",
               title: str = "filtered latest-period data",
               extra_meta: dict[str, Any] | None = None,
               only_keys: set[str] | None = None) -> bytes:
    v, checked, rows = grid.rows_for(book, filters=filters, period=period)
    if only_keys is not None:
        rows = [r for r in rows if str(r.get(v.key)) in only_keys]
    out = io.StringIO()
    meta = {"export": title, "domain": book.domain_id,
            "release": book.release_id, "fingerprint": book.fingerprint,
            "period": v.period, "grain": grid.SPEC[book.domain_id]["noun"],
            "filters": predicates.describe(checked),
            "filter_definition": checked, "rows": len(rows),
            "units": "money columns are SAR million (raw); PD/CCF fractions;"
                     " LGD/utilisation/LTV percent",
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **(extra_meta or {})}
    for key, value in meta.items():
        out.write(f"# {key}: {value}\n")
    writer = csv.writer(out)
    columns = list(v.keys)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_safe(row.get(c)) for c in columns])
    return out.getvalue().encode("utf-8")


def _safe(value: Any) -> Any:
    """Formula-injection guard for text cells; numbers pass unchanged."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        try:
            float(value)
            return value
        except ValueError:
            return "'" + value
    return value


class GridExport(BaseModel):
    domain: str = Field(default="corporate", max_length=20)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    period: str = Field(default="", max_length=12)


@router.post("/grid/export")
async def grid_export(body: GridExport,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> Response:
    book = access.book(who, body.domain)
    data = export_csv(book, filters=body.filters, period=body.period)
    return Response(content=data, media_type="text/csv", headers={
        "Content-Disposition":
        f'attachment; filename="creditprobe_{book.domain_id}_grid.csv"'})


@router.get("/cohorts/{object_id}/export")
async def cohort_export(object_id: str,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> Response:
    from backend.workspace import cohorts

    cohort = service.objects().get(object_id, service.principal(who))
    book = access.book(who, cohort["domain_id"])
    body = cohort["body"]
    meta = {"cohort_id": object_id, "cohort_version": cohort["version"],
            "cohort_name": body.get("name", ""),
            "cohort_definition": body.get("filter_description")
            or body.get("description") or "",
            "cohort_source": (body.get("source") or {}).get("kind", ""),
            "membership_hash": body["membership_hash"],
            "predicate_hash": body["predicate_hash"],
            "selection": body["selection"], "counts": body["counts"]}
    members: set[str] | None = None
    if not body.get("filters"):
        # A cohort frozen in a conversation carries its engine predicate,
        # not grid filters: export exactly its members, and only when its
        # saved question still resolves to the same membership.
        check = cohorts.verify(book, cohort)
        if not check["identical"]:
            raise HTTPException(409, {
                "error_code": "MEMBERSHIP_CHANGED",
                "message": check.get("message") or "This cohort no longer "
                           "resolves to the membership it was frozen with."})
        members = set(cohorts._member_ids(book, None,
                                          cohorts.resolve_stored(book, body)))
        meta["members_exported"] = len(members)
    data = export_csv(book, filters=body["filters"], period=body["period"],
                      title="frozen cohort", extra_meta=meta,
                      only_keys=members)
    return Response(content=data, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{object_id}.csv"'})


__all__ = ["export_csv", "router"]
