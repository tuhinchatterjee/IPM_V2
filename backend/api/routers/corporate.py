"""Borrower 360 and the corporate relationship graph, over HTTP. Phase 3.

Every route reads the Parquet lake and the derived graph datasets. None of
them recomputes an analytic: the derivation runs at build time and the screen
reads what it produced, so the screen, the export and Ask cannot disagree.

Three contracts the routes hold
-------------------------------
**A subgraph is a subgraph.** `/graph/ego` expands the neighbourhood
server-side to a bounded depth and says when it truncated. No route returns
the whole network, and none is expected to be filtered in the browser.

**Identity is a narrower permission than exposure.** Seeing a borrower's
numbers and seeing the named people behind it are separate acts. The views
that show natural persons require BORROWER_360_UBO_VIEW, and a caller
without it is told the view exists and is refused - not shown an empty graph
that reads as "no owners".

**An ambiguous name is never resolved silently.** The search route returns
the candidates and says the term was ambiguous. Picking the best match and
returning it as the answer is the failure this prevents, because nothing on
the screen would say a choice had been made.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from backend.api.permissions import (
    BORROWER_360_UBO_VIEW,
    Principal,
    RequireBorrower360Graph,
    RequireBorrower360View,
)
from backend.corporate import NOT_CLIENT_DATA, ORIGIN
from backend.corporate import graphquality as gq
from backend.corporate import lineage as lineage_mod
from backend.corporate import network as net
from backend.corporate import service as service_mod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/corporate", tags=["borrower-360"])


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)})


def _not_built(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "data_not_built", "message": str(exc)})


def _refused(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "refused", "message": message})


def _forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "forbidden", "message": message})


def _native(value: Any) -> Any:
    """numpy and pandas scalars, as JSON can carry them.

    Everything here comes out of pandas, so an untouched payload is full of
    `numpy.int64` and `numpy.bool_`. Pydantic cannot serialise those and
    fails at RESPONSE time - after the work is done, with a 500 that says
    nothing about the route. Converted once, at the boundary, rather than
    remembered at each of the forty places a frame is turned into a dict.
    """
    if isinstance(value, dict):
        return {str(key): _native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_native(item) for item in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        # NaN and infinity are not JSON. Null says "absent", which is what a
        # NaN in a governed frame means, and the sentinel columns beside it
        # say WHICH kind of absent.
        return None if not np.isfinite(number) else number
    if isinstance(value, np.ndarray):
        return [_native(item) for item in value.tolist()]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Every response says what the data is. B54."""
    payload.setdefault("origin", ORIGIN)
    payload.setdefault("not_client_data", NOT_CLIENT_DATA)
    payload.setdefault("service_version", service_mod.SERVICE_VERSION)
    return _native(payload)


# --------------------------------------------------------------- metadata


@router.get("/meta")
def meta(principal: Principal = RequireBorrower360View) -> dict[str, Any]:
    """What this module offers, and what the caller may see of it.

    Returned rather than hard-coded in the frontend so the screen cannot
    offer a tab the API does not serve or hide one it does.
    """
    may_see_people = principal.role in BORROWER_360_UBO_VIEW
    try:
        available = service_mod.periods()
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc

    return _envelope({
        "periods": available,
        "latest_period": available[-1] if available else None,
        "tabs": [{"key": key, "label": label, "datasets": list(datasets),
                  "is_graph_tab": key in service_mod.GRAPH_TABS}
                 for key, label, datasets in service_mod.TABS],
        "network_views": [
            {"key": view["key"], "label": view["label"],
             "purpose": view["purpose"],
             "requires_ubo_permission": bool(
                 view.get("requires_ubo_permission")),
             "permitted": may_see_people
             or not view.get("requires_ubo_permission")}
            for view in service_mod.NETWORK_VIEWS],
        "group_concepts": [dict(concept)
                           for concept in service_mod.GROUP_CONCEPTS],
        "max_graph_depth": service_mod.MAX_DEPTH,
        "may_see_natural_persons": may_see_people,
        "network_risk_score_label": net.NRS_LABEL,
        "searchable_attributes": list(
            service_mod.SEARCHABLE),
    })


@router.get("/lineage")
def lineage(principal: Principal = RequireBorrower360View) -> dict[str, Any]:
    """Where every Borrower 360 field comes from. B5.

    Served so that VIEW SOURCE on the screen lands on the exact Data Builder
    object rather than on a domain landing page.
    """
    return _envelope({
        "fields": [entry.to_dict() for entry in lineage_mod.FIELDS],
        "field_count": len(lineage_mod.FIELDS),
        "lineage_version": lineage_mod.LINEAGE_VERSION,
        "authoritative_field_count": sum(
            1 for entry in lineage_mod.FIELDS
            if entry.authority == lineage_mod.AUTHORITATIVE),
        "note": ("No field here is AUTHORITATIVE. The Borrower 360 is a fast "
                 "denormalised read, and a field marked authoritative would "
                 "be one the snapshot had quietly taken ownership of."),
    })


# ----------------------------------------------------------------- search


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=200),
           period: str | None = None,
           limit: int = Query(25, ge=1, le=200),
           principal: Principal = RequireBorrower360View) -> dict[str, Any]:
    """Find a borrower. An ambiguous term stays ambiguous. Phase 3.2."""
    try:
        return _envelope(service_mod.find(q, period, limit=limit))
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc
    except service_mod.BorrowerNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/cohort")
def cohort(period: str | None = None,
           sector: str | None = None,
           region: str | None = None,
           segment: str | None = None,
           internal_rating: str | None = None,
           stage: str | None = None,
           watchlist_flag: bool = False,
           breach_flag: bool = False,
           default_flag: bool = False,
           borrower_ids: str | None = None,
           limit: int = Query(50, ge=1, le=200),
           principal: Principal = RequireBorrower360View) -> dict[str, Any]:
    """A faceted cohort, or a named list of borrowers. Phase 3.3.

    A named list that contains an id this book does not have comes back with
    that id in `not_found`. Returning the nine that matched and staying quiet
    about the tenth is how a portfolio review silently loses a borrower.
    """
    facets = {name: value for name, value in (
        ("sector", sector), ("region", region), ("segment", segment),
        ("internal_rating", internal_rating), ("stage", stage))
        if value}
    flags = [name for name, on in (
        ("watchlist_flag", watchlist_flag), ("breach_flag", breach_flag),
        ("default_flag", default_flag)) if on]
    names = [part.strip() for part in (borrower_ids or "").split(",")
             if part.strip()]
    try:
        return _envelope(service_mod.filter_cohort(
            period, facets=facets, flags=flags, borrower_ids=names,
            limit=limit))
    except service_mod.UnknownFacetError as exc:
        raise _refused(str(exc)) from exc
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc


# ------------------------------------------------------------- the borrower


@router.get("/borrowers/{borrower_id}")
def borrower(borrower_id: str, period: str | None = None,
             principal: Principal = RequireBorrower360View) -> dict[str, Any]:
    """The Borrower 360 row, grouped into its tabs. Phase 3.1."""
    try:
        chosen = period or service_mod.latest_period()
        row = service_mod.borrower_row(borrower_id, chosen)
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc
    except service_mod.BorrowerNotFound as exc:
        raise _not_found(exc) from exc

    may_see_people = principal.role in BORROWER_360_UBO_VIEW
    fields: dict[str, dict[str, Any]] = {}
    for entry in lineage_mod.FIELDS:
        if entry.name not in row.index:
            continue
        value = row[entry.name]
        fields[entry.name] = {
            "value": None if value is None else value,
            "group": entry.group,
            "unit": entry.unit,
            "authority": entry.authority,
            "source_dataset": entry.source_dataset,
            "source_field": entry.source_field,
            "source_period": entry.source_period,
        }

    if not may_see_people:
        # A count of the natural persons behind a borrower is still a fact
        # about those persons. Withheld with a reason, never zeroed.
        for name in ("ubo_count", "director_count"):
            if name in fields:
                fields[name]["value"] = "PERMISSION_REQUIRED"
                fields[name]["withheld_reason"] = (
                    "BORROWER_360_UBO_VIEW is required to see the natural "
                    "persons behind a borrower.")

    return _envelope({
        "borrower_id": borrower_id,
        "period": chosen,
        "period_end_date": str(row["period_end_date"]),
        "fields": fields,
        "tabs": [{"key": key, "label": label,
                  "fields": [entry.name for entry in lineage_mod.FIELDS
                             if entry.name in fields
                             and _tab_of(entry.group) == key]}
                 for key, label, _ in service_mod.TABS],
        "may_see_natural_persons": may_see_people,
    })


#: Lineage group -> tab. Declared, because deriving it from a name match
#: would put GRAPH SUMMARY on the "group" tab and DATA QUALITY nowhere.
_GROUP_TAB: dict[str, str] = {
    "IDENTITY": "overview",
    "RATING": "ratings",
    "FINANCIALS": "financials",
    "EXPOSURE": "exposure",
    "IFRS9": "ifrs9",
    "DELINQUENCY": "delinquency",
    "COVENANTS": "covenants",
    "COLLATERAL": "collateral",
    "LIMIT": "limits",
    "GRAPH SUMMARY": "network",
    "DATA QUALITY": "quality",
}


def _tab_of(group: str) -> str:
    return _GROUP_TAB.get(group, "overview")


@router.get("/borrowers/{borrower_id}/groups")
def groups(borrower_id: str, period: str | None = None,
           principal: Principal = RequireBorrower360Graph) -> dict[str, Any]:
    """The six group concepts, side by side and not reconciled. Phase 3.11."""
    try:
        chosen = period or service_mod.latest_period()
        service_mod.borrower_row(borrower_id, chosen)
        return _envelope(service_mod.group_view(borrower_id, chosen))
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc
    except service_mod.BorrowerNotFound as exc:
        raise _not_found(exc) from exc


# ------------------------------------------------------------------ graph


@router.get("/borrowers/{borrower_id}/graph")
def ego_graph(borrower_id: str,
              view: str = "ownership",
              period: str | None = None,
              depth: int = Query(1, ge=0, le=service_mod.MAX_DEPTH),
              principal: Principal = RequireBorrower360Graph
              ) -> dict[str, Any]:
    """The neighbourhood around one borrower. Phase 3.9.

    Expanded here, not in the browser. A screen that fetches the whole
    network to show eleven edges ships 43,000 of them, and does it again on
    every click.
    """
    chosen_view = service_mod.VIEW_BY_KEY.get(view)
    if chosen_view is None:
        raise _refused(
            f"'{view}' is not a network view. Available: "
            + ", ".join(service_mod.NETWORK_VIEW_KEYS))
    if (chosen_view.get("requires_ubo_permission")
            and principal.role not in BORROWER_360_UBO_VIEW):
        raise _forbidden(
            f"The '{chosen_view['label']}' view shows named natural persons "
            "and requires BORROWER_360_UBO_VIEW. The view exists and this "
            "borrower may well have owners; you are not permitted to see "
            "them, which is different from there being none.")
    try:
        chosen = period or service_mod.latest_period()
        service_mod.borrower_row(borrower_id, chosen)
        found = service_mod.ego_graph(borrower_id, chosen, view=view,
                                      depth=depth)
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc
    except service_mod.BorrowerNotFound as exc:
        raise _not_found(exc) from exc
    return _envelope(found.to_dict())


@router.get("/borrowers/{borrower_id}/similar")
def similar(borrower_id: str, period: str | None = None,
            limit: int = Query(20, ge=1, le=100),
            principal: Principal = RequireBorrower360Graph
            ) -> dict[str, Any]:
    """Hidden relationship candidates. Never a relationship. Phase 2.15."""
    if principal.role not in BORROWER_360_UBO_VIEW:
        raise _forbidden(
            "Hidden relationship candidates are found from shared directors "
            "and shared addresses, so seeing them means seeing the people. "
            "BORROWER_360_UBO_VIEW is required.")
    try:
        chosen = period or service_mod.latest_period()
        stamp = service_mod.as_of_date(chosen)
        edges = service_mod.load("corporate_ownership_edges")
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc
    except service_mod.BorrowerNotFound as exc:
        raise _not_found(exc) from exc

    found = net.similarity_candidates(edges, stamp, subjects=[borrower_id],
                                      limit=limit)
    return _envelope({
        "borrower_id": borrower_id,
        "period": chosen,
        "as_of": stamp,
        "candidates": [candidate.to_edge() for candidate in found],
        "candidate_count": len(found),
        "threshold": net.SIMILARITY_THRESHOLD,
        "threshold_status": net.SIMILARITY_UNVERIFIED,
        "caveat": net.SIMILARITY_CAVEAT,
    })


# ---------------------------------------------------------- data quality


@router.get("/quality")
def quality(period: str | None = None,
            principal: Principal = RequireBorrower360View) -> dict[str, Any]:
    """The graph data-quality register for one quarter. Phase 2.17."""
    try:
        chosen = period or service_mod.latest_period()
        register = service_mod.load(service_mod.DQ)
    except service_mod.DataNotBuilt as exc:
        raise _not_built(exc) from exc

    block = register[register["period"] == chosen]
    issues = block.to_dict(orient="records")
    return _envelope({
        "period": chosen,
        "checks_run": len(issues),
        "passed": sum(1 for i in issues if i["status"] == gq.PASS),
        "flagged": sum(1 for i in issues if i["status"] == gq.FLAG),
        "rejected": sum(1 for i in issues if i["status"] == gq.REJECT),
        "overall_status": (
            gq.REJECT if any(i["status"] == gq.REJECT for i in issues)
            else gq.FLAG if any(i["status"] == gq.FLAG for i in issues)
            else gq.PASS),
        "issues": issues,
        "blocking_rule": (
            "A REJECT blocks the derived computation that depends on it. "
            "The affected borrowers' fields read DATA_QUALITY_BLOCKED rather "
            "than carrying a number computed from rejected input."),
        "quality_version": gq.QUALITY_VERSION,
    })
