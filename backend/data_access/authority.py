"""
Which dataset actually answers a governed purpose — and the refusal to guess.

The problem this solves
-----------------------
IPM ships with a synthetic book so the product can be seen working. A bank then
onboards its own data through Data Builder. The moment a client dataset is
published and marked AUTHORITATIVE for a purpose, every certified analysis must
read it — and must never quietly go on reading the demo book for that purpose.
Silently mixing the two would produce a credit figure that looks real, carries a
certification tick, and describes a portfolio that does not exist.

So resolution is explicit and has exactly three outcomes:

    a client dataset is authoritative   ->  use it
    only the demo dataset is available  ->  use it, and SAY it is demo
    neither                             ->  refuse, and say what is missing

There is no fourth branch where something plausible is substituted.

Where the answer shows up
-------------------------
The resolution is recorded on the Trace's DATASET node — origin, family,
version, authoritative status — so "where did this number come from?" is
answered by looking at the map rather than by trusting this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.data_access.catalog import (
    GOVERNED_PURPOSES,
    Catalog,
    DatasetDef,
    DatasetOrigin,
    get_catalog,
)
from backend.data_access.protocol import DataAccessError

logger = logging.getLogger(__name__)


class GovernedDataUnavailable(DataAccessError):
    """No dataset is authoritative for a purpose an analysis needs.

    Deliberately an error rather than a fallback. A missing authoritative source
    is a governance state a steward must fix in Data Builder, not something the
    engine should paper over.
    """


@dataclass(frozen=True)
class Resolution:
    """Which dataset was chosen for a purpose, and on what grounds."""

    purpose: str
    dataset: str
    domain: str
    origin: str
    dataset_family: str
    version: str
    is_demo: bool
    authoritative: bool
    # One sentence a reviewer can read on the Trace node.
    reason: str = ""
    # Other datasets that serve the purpose but were not chosen.
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "dataset": self.dataset,
            "domain": self.domain,
            "origin": self.origin,
            "dataset_family": self.dataset_family,
            "version": self.version,
            "is_demo": self.is_demo,
            "authoritative": self.authoritative,
            "reason": self.reason,
            "alternatives": list(self.alternatives),
        }


def _rank(dataset: DatasetDef) -> tuple[int, str]:
    """Ordering among candidates: client data before demo data, then by name.

    Only ever applied to datasets that are already authoritative for the
    purpose, so this decides between two deliberate choices rather than
    inventing one.
    """
    return (0 if dataset.origin == DatasetOrigin.CLIENT else 1, dataset.name)


def resolve_purpose(purpose: str, catalog: Catalog | None = None) -> Resolution:
    """The dataset that answers a governed purpose, or a refusal."""
    catalog = catalog or get_catalog()

    if purpose not in GOVERNED_PURPOSES:
        raise GovernedDataUnavailable(
            f"'{purpose}' is not a governed purpose. "
            f"Known purposes: {', '.join(sorted(GOVERNED_PURPOSES))}."
        )

    candidates = catalog.serving(purpose)
    if not candidates:
        raise GovernedDataUnavailable(
            f"No published dataset is marked authoritative for "
            f"'{purpose}' ({GOVERNED_PURPOSES[purpose]}). Publish one in Data "
            "Builder and mark it authoritative for this purpose."
        )

    ordered = sorted(candidates, key=_rank)
    chosen = ordered[0]
    others = [d.name for d in ordered[1:]]

    client_exists = any(d.origin == DatasetOrigin.CLIENT for d in candidates)
    if chosen.is_demo and client_exists:  # pragma: no cover - _rank prevents it
        raise GovernedDataUnavailable(
            f"Demo data would have been used for '{purpose}' while client data "
            "exists. This is refused."
        )

    if chosen.is_demo:
        reason = (
            "The only dataset marked authoritative for this purpose is IPM's "
            "bundled demonstration data. Onboard client data in Data Builder to "
            "replace it."
        )
    else:
        reason = (
            "Client data, published and marked authoritative for this purpose in "
            "Data Builder."
        )
        if others:
            reason += f" {len(others)} other dataset(s) serve it and were not used."

    return Resolution(
        purpose=purpose,
        dataset=chosen.name,
        domain=chosen.domain,
        origin=str(chosen.origin),
        dataset_family=chosen.family,
        version=chosen.version,
        is_demo=chosen.is_demo,
        authoritative=True,
        reason=reason,
        alternatives=others,
    )


def resolve_dataset(name_or_purpose: str, catalog: Catalog | None = None) -> Resolution:
    """Resolve either a governed purpose or a dataset named directly.

    Engine functions name datasets directly today (`portfolio_facility`). When
    that name is the DEMO dataset for a purpose and client data has since been
    made authoritative for the same purpose, the read is redirected to the
    client dataset — which is the whole point of marking something
    authoritative. The redirect is recorded, never silent: it appears on the
    Trace's DATASET node with its reason.
    """
    catalog = catalog or get_catalog()

    if name_or_purpose in GOVERNED_PURPOSES:
        return resolve_purpose(name_or_purpose, catalog)

    named = catalog.dataset(name_or_purpose)

    # Does this dataset stand for a purpose that something better now serves?
    for purpose in named.authoritative_for:
        resolution = resolve_purpose(purpose, catalog)
        if resolution.dataset != named.name:
            logger.info(
                "Read of '%s' redirected to authoritative '%s' for purpose '%s'.",
                named.name, resolution.dataset, purpose,
            )
            return Resolution(
                purpose=purpose,
                dataset=resolution.dataset,
                domain=resolution.domain,
                origin=resolution.origin,
                dataset_family=resolution.dataset_family,
                version=resolution.version,
                is_demo=resolution.is_demo,
                authoritative=True,
                reason=(
                    f"'{named.name}' is IPM's demonstration data for this purpose. "
                    f"'{resolution.dataset}' is published and marked authoritative, "
                    "so it was used instead."
                ),
                alternatives=[named.name, *resolution.alternatives],
            )
        return resolution

    # A dataset with no declared purpose is read exactly as asked for.
    return Resolution(
        purpose="",
        dataset=named.name,
        domain=named.domain,
        origin=str(named.origin),
        dataset_family=named.family,
        version=named.version,
        is_demo=named.is_demo,
        authoritative=False,
        reason="Read directly by name; this dataset is not authoritative for a governed purpose.",
    )


def governance_summary(catalog: Catalog | None = None) -> dict[str, Any]:
    """What Data Builder shows an administrator: what powers IPM right now."""
    catalog = catalog or get_catalog()
    out: list[dict[str, Any]] = []
    for purpose, description in sorted(GOVERNED_PURPOSES.items()):
        try:
            resolution = resolve_purpose(purpose, catalog)
            out.append({
                "purpose": purpose,
                "description": description,
                "resolved": True,
                **resolution.to_dict(),
            })
        except GovernedDataUnavailable as e:
            out.append({
                "purpose": purpose,
                "description": description,
                "resolved": False,
                "message": str(e),
            })
    return {
        "purposes": out,
        "using_demo_data": any(p.get("is_demo") for p in out),
        "unresolved": [p["purpose"] for p in out if not p["resolved"]],
    }


__all__ = [
    "GovernedDataUnavailable",
    "Resolution",
    "governance_summary",
    "resolve_dataset",
    "resolve_purpose",
]
