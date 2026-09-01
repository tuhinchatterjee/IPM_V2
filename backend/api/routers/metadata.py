"""The governed catalogue over HTTP. §12.

One authority, one endpoint set. The Data Builder screen, the AI analyst's
discovery tools, the orchestrator's data-capability answers and this router all
read `backend.metadata`, so a client that asks the API how many domains exist
gets the number the product would say in a sentence and the number the screen
would draw — which was three different numbers before this existed.

Reading the catalogue is a read. Nothing here writes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend import metadata as md
from backend.api.permissions import RequireAnalyst

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.get("/summary")
def summary(_: object = RequireAnalyst) -> dict:
    """The catalogue at a glance: the counts every surface must agree on."""
    return {"version": md.METADATA_VERSION, "counts": md.counts(),
            "periods": list(md.periods())}


@router.get("/domains")
def domains(_: object = RequireAnalyst) -> dict:
    found = md.domains()
    return {"version": md.METADATA_VERSION, "count": len(found),
            "domains": [d.to_dict() for d in found]}


@router.get("/domains/{name}")
def one_domain(name: str, _: object = RequireAnalyst) -> dict:
    found = md.domain(name)
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_domain",
                    "message": f"There is no governed data domain named "
                               f"“{name}”."})
    return {"version": md.METADATA_VERSION, "domain": found.to_dict(),
            "datasets": [d.to_dict() for d in md.datasets(found.name)]}


@router.get("/datasets")
def datasets(domain: str = "", subject: str = "",
             _: object = RequireAnalyst) -> dict:
    """Governed datasets, optionally within a domain or bearing on a subject."""
    if subject:
        found, not_covered = md.coverage(subject, limit=25)
        return {"version": md.METADATA_VERSION, "count": len(found),
                "subject": subject, "not_covered": list(not_covered),
                "datasets": [d.to_dict() for d in found]}
    found = md.datasets(domain)
    return {"version": md.METADATA_VERSION, "count": len(found),
            "domain": domain, "not_covered": [],
            "datasets": [d.to_dict() for d in found]}


@router.get("/datasets/{name}")
def one_dataset(name: str, _: object = RequireAnalyst) -> dict:
    found = md.dataset(name)
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_dataset",
                    "message": f"There is no governed dataset named "
                               f"“{name}”."})
    return {"version": md.METADATA_VERSION,
            "dataset": found.to_dict(with_fields=True),
            "relationships": [r.to_dict() for r in md.relationships(found.name)]}


@router.get("/relationships")
def relationships(dataset: str = "", _: object = RequireAnalyst) -> dict:
    found = md.relationships(dataset)
    return {"version": md.METADATA_VERSION, "count": len(found),
            "relationships": [r.to_dict() for r in found]}


__all__ = ["router"]
