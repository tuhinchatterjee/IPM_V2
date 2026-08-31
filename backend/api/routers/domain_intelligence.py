"""
Domain intelligence over HTTP. §21, §30-§33.

Not the AI Intelligence Studio, which lives next door in `intelligence.py`
and is about how the product itself is performing. This one is about a
BORROWER: what four governed domains say about one name at one reporting
date. The prefix is `/domain-intelligence` for exactly that reason - two
routers under one path would have been a collision waiting for whichever
of them loaded second.

Four domains, one shape, and the shape is the point: a caller that can read an
IFRS 9 reading can read a covenant one without learning a second contract, and
a screen cannot present the same evidence differently in two places because
there is only one place it is composed.

Reading is a read. Nothing here writes, so nothing here needs more than the
permission to run an analysis.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend.api.permissions import RequireAnalyst
from backend.intelligence import DOMAINS, INTELLIGENCE_VERSION, OWNER
from backend.intelligence import collateral as collateral_reader
from backend.intelligence import covenant as covenant_reader
from backend.intelligence import external as external_reader
from backend.intelligence import ifrs9 as ifrs9_reader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/domain-intelligence",
                   tags=["domain intelligence"])

READERS = {
    "ifrs9": ifrs9_reader,
    "covenant": covenant_reader,
    "collateral": collateral_reader,
    "external": external_reader,
}


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)})


@router.get("", summary="What the four domain readers are and what they test")
def overview() -> dict:
    """The contract, published rather than described in a docstring.

    A screen that has to guess which fields a reading carries is a screen that
    will guess wrong once and then hard-code around it.
    """
    return {
        "version": INTELLIGENCE_VERSION,
        "owner": OWNER,
        "domains": [
            {
                "id": key,
                "domain": module_domain(key),
                "label": DOMAINS[module_domain(key)],
                "dataset": READERS[key].DATASET,
                "means": (READERS[key].__doc__ or "").strip().split("\n\n")[1]
                if len((READERS[key].__doc__ or "").split("\n\n")) > 1 else "",
            }
            for key in READERS
        ],
        "shape": {
            "findings": "What the reader found, each naming the dataset, the "
                        "field and the rule it was tested against.",
            "missing": "What could not be read, and why. An absence of data "
                       "is never reported as an absence of risk.",
            "measured": "The figures the reader looked at whether or not "
                        "anything was found.",
            "score": "There is deliberately no score, in any of the four "
                     "domains.",
        },
    }


def module_domain(key: str) -> str:
    from backend import intelligence as base

    return {"ifrs9": base.IFRS9, "covenant": base.COVENANT,
            "collateral": base.COLLATERAL, "external": base.EXTERNAL}[key]


@router.get("/{domain}/{borrower_id}",
            summary="One domain's reading of one borrower",
            dependencies=[RequireAnalyst])
def reading(domain: str, borrower_id: str, period: str = "") -> dict:
    """A reading, or an honest account of why there is not one."""
    module = READERS.get(domain.strip().lower())
    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_domain",
                    "message": (f"'{domain}' is not a domain this product "
                                f"reads. It reads "
                                f"{', '.join(sorted(READERS))}.")})
    try:
        return module.read(borrower_id, period).to_dict()
    except Exception as exc:  # noqa: BLE001 - said, never substituted
        logger.warning("The %s reading could not be built: %s", domain, exc)
        raise _unavailable(exc) from exc


@router.get("/external/{customer_id}/memos",
            summary="The memo text itself, verbatim",
            dependencies=[RequireAnalyst])
def memos(customer_id: str, period: str = "", limit: int = 5) -> dict:
    """Extracts, quoted rather than summarised.

    A generated summary of somebody's judgement, shown next to their name, is
    a claim they did not make. These are the words that were written.
    """
    try:
        found = external_reader.extracts(customer_id, period, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc
    return {
        "customer_id": customer_id,
        "period": period,
        "memos": found,
        "note": ("Quoted verbatim from the credit file. Nothing here is "
                 "paraphrased or generated."),
    }
