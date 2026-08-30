"""
Data Builder as a control plane: who depends on what, and what may be replaced.

An inventory tells you which datasets exist. A control plane tells you what
would break if one of them went away, and refuses the change until someone has
seen the answer. That is the difference this module makes.

Three questions it answers
--------------------------
**Who uses this?** Before a dataset is archived, CreditProbe lists what reads it: the
governed purposes it is authoritative for, the certified analyses that depend on
those purposes, the relationships joining to it, and the saved investigations
whose Trace names it. An archive with dependants is refused unless the caller
says, explicitly, to go ahead anyway.

**What is actually powering CreditProbe right now?** For each governed purpose, which
dataset answers it and whether that dataset is client data or CreditProbe's bundled
demonstration book. A bank must never be unclear about this.

**Can this dataset replace that one?** Replacement is a governed act, not a
re-upload. The incoming dataset must cover the fields the outgoing one supplies,
and the differences are reported field by field before anything moves.

What this module will not do
----------------------------
It does not migrate data, and it does not rewrite an analysis. It changes which
dataset is AUTHORITATIVE for a purpose; the resolution in
backend/data_access/authority.py does the rest, and every read records which
dataset it actually used on the Trace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.data_access.catalog import GOVERNED_PURPOSES, DatasetOrigin
from backend.models.platform import (
    DS_ARCHIVED,
    DS_PUBLISHED,
    DatasetDefinition,
    DatasetRelationship,
)
from backend.services.data_builder import DataBuilderError, get_dataset

logger = logging.getLogger(__name__)

VALID_ORIGINS = {o.value for o in DatasetOrigin}


# ========================================================= the domain library
#
# CreditProbe's bundled demonstration book is generated to metadata/catalog.json by
# scripts/build_data_lake.py, which is what the Data Access Layer reads. Data
# Builder needs those datasets in the database too — not to change how they are
# read, but so a steward can SEE them: which domain they sit in, that they are
# demonstration data, what they are authoritative for, and what would break if
# they were replaced.
#
# The sync is one-directional and non-destructive. It creates or updates the
# governance record; it never touches the Parquet, never renames a field, and
# never overwrites a decision a steward has made about a CLIENT dataset.


def sync_bundled_catalog(session: Session) -> dict[str, Any]:
    """Register the bundled datasets in Data Builder so they can be governed.

    Idempotent, and safe to run on every start: a dataset already recorded has
    its description refreshed, and one a steward has re-marked as client data is
    left exactly as they left it.
    """
    import json

    from backend.config import settings
    from backend.models.platform import DataDomain, FieldDefinition

    path = settings.metadata_dir / "catalog.json"
    if not path.exists():
        return {"synced": [], "skipped": [],
                "message": "No catalogue file — run scripts/generate_saudi_universe.py first."}

    catalogue = json.loads(path.read_text(encoding="utf-8"))
    synced: list[str] = []
    skipped: list[str] = []

    for entry in catalogue.get("datasets") or []:
        name = str(entry.get("name") or "")
        if not name:
            continue

        domain_name = str(entry.get("domain") or "Ungoverned")
        if not session.execute(
            select(DataDomain).where(DataDomain.name == domain_name)
        ).scalar_one_or_none():
            session.add(DataDomain(
                name=domain_name,
                description="Created from CreditProbe's bundled catalogue.",
                owner=str(entry.get("owner") or ""),
            ))
            session.flush()

        dataset = session.execute(
            select(DatasetDefinition).where(DatasetDefinition.name == name)
        ).scalar_one_or_none()

        if dataset is not None and dataset.origin == DatasetOrigin.CLIENT.value:
            # A steward has said this is the bank's own data. The bundled
            # catalogue does not get to contradict that.
            skipped.append(name)
            continue

        if dataset is None:
            dataset = DatasetDefinition(name=name, domain=domain_name)
            session.add(dataset)

        dataset.domain = domain_name
        dataset.business_name = str(entry.get("business_name") or name)
        dataset.purpose = str(entry.get("purpose") or "")
        dataset.grain = str(entry.get("grain") or "")
        dataset.primary_keys = list(entry.get("primary_keys") or [])
        dataset.period_field = str(entry.get("period_field") or "")
        dataset.owner = str(entry.get("owner") or "")
        dataset.version = str(entry.get("version") or "1.0.0")
        dataset.is_synthetic = bool(entry.get("is_synthetic"))
        dataset.lifecycle = DS_PUBLISHED
        dataset.source_type = "bundled"
        dataset.origin = str(entry.get("origin") or DatasetOrigin.DEMO.value)
        dataset.dataset_family = str(entry.get("dataset_family") or name)
        dataset.authoritative_for = list(entry.get("authoritative_for") or [])
        # B44. Carried through like every other governance field: a database
        # row overrides the bundled entry of the same name, so a scope left out
        # here is not merely missing - it is ERASED, and the corporate book
        # comes back indistinguishable from the credit book.
        dataset.portfolio_scope = str(
            entry.get("portfolio_scope") or "CREDIT_BOOK")
        session.flush()

        existing = {f.name: f for f in dataset.fields}
        for field_entry in entry.get("fields") or []:
            field_name = str(field_entry.get("name") or "")
            if not field_name:
                continue
            definition = existing.get(field_name) or FieldDefinition(
                dataset_id=dataset.id, name=field_name
            )
            definition.business_name = str(field_entry.get("business_name") or field_name)
            definition.definition = str(field_entry.get("definition") or "")
            definition.data_type = str(field_entry.get("data_type") or "string")
            definition.unit = field_entry.get("unit")
            definition.allowed_values = field_entry.get("allowed_values")
            definition.nullable = bool(field_entry.get("nullable", True))
            definition.sensitivity = str(field_entry.get("sensitivity") or "internal")
            definition.source_field = str(field_entry.get("source_column") or field_name)
            if field_name not in existing:
                session.add(definition)
        session.flush()
        synced.append(name)

    return {
        "synced": synced,
        "skipped": skipped,
        "message": (
            f"{len(synced)} bundled dataset(s) registered in Data Builder"
            + (f"; {len(skipped)} left alone because they now hold client data."
               if skipped else ".")
        ),
    }


# ============================================================== dependencies


@dataclass(frozen=True)
class Dependant:
    """One thing that would be affected if this dataset went away."""

    kind: str          # purpose | analysis | relationship | investigation
    name: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "detail": self.detail}


@dataclass
class UsedBy:
    """The full answer to "who depends on this dataset?"."""

    dataset: str
    dependants: list[Dependant] = field(default_factory=list)

    @property
    def blocking(self) -> list[Dependant]:
        """Dependants that make removal a governance event rather than tidying.

        A relationship can be re-pointed. A certified analysis losing its
        authoritative source cannot — it simply stops being answerable.
        """
        return [d for d in self.dependants if d.kind in ("purpose", "analysis")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "dependants": [d.to_dict() for d in self.dependants],
            "blocking": [d.to_dict() for d in self.blocking],
            "safe_to_archive": not self.blocking,
        }


def _analyses_needing(purposes: set[str]) -> list[Dependant]:
    """Registered analyses that declare they need one of these purposes."""
    from backend.engine.registry import get_registry

    out: list[Dependant] = []
    for analysis_id in get_registry().ids():
        try:
            contract = get_registry().contract(analysis_id)
        except Exception:  # pragma: no cover - a broken contract is its own problem
            continue
        needed = set(getattr(contract, "required_domains", []) or [])
        overlap = needed & purposes
        if overlap:
            out.append(Dependant(
                kind="analysis",
                name=contract.name or analysis_id,
                detail=(
                    f"{contract.certification} · needs "
                    f"{', '.join(sorted(overlap))}"
                ),
            ))
    return out


def _investigations_naming(dataset_name: str) -> list[Dependant]:
    """Saved investigations whose stored Trace names this dataset."""
    from backend.config import settings

    if not settings.has_database:  # pragma: no cover - caller already has a session
        return []
    from backend.db.engine import get_session
    from backend.models.platform import Investigation, InvestigationVersion, TraceVersionRow

    out: list[Dependant] = []
    with get_session() as session:
        rows = session.execute(
            select(Investigation.id, Investigation.title, TraceVersionRow.graph)
            .join(InvestigationVersion,
                  InvestigationVersion.investigation_id == Investigation.id)
            .join(TraceVersionRow,
                  TraceVersionRow.analysis_run_id == InvestigationVersion.analysis_run_id)
        ).all()
        seen: set[int] = set()
        for investigation_id, title, graph in rows:
            if investigation_id in seen:
                continue
            nodes = (graph or {}).get("nodes") or []
            if any(str(n.get("dataset") or "") == dataset_name for n in nodes):
                seen.add(investigation_id)
                out.append(Dependant(
                    kind="investigation", name=title,
                    detail="A saved answer was produced from this dataset.",
                ))
    return out


def used_by(session: Session, dataset_name: str) -> UsedBy:
    """Everything that depends on one dataset."""
    dataset = get_dataset(session, dataset_name)
    dependants: list[Dependant] = []

    purposes = set(dataset.authoritative_for or [])
    for purpose in sorted(purposes):
        # Only a purpose this dataset is the ONLY authoritative source for is a
        # dependency. Where something else also serves it, removal is safe.
        others = session.execute(
            select(DatasetDefinition).where(
                DatasetDefinition.lifecycle == DS_PUBLISHED,
                DatasetDefinition.name != dataset.name,
                DatasetDefinition.authoritative_for.contains([purpose]),
            )
        ).scalars().all()
        if others:
            continue
        dependants.append(Dependant(
            kind="purpose",
            name=purpose,
            detail=(
                f"{GOVERNED_PURPOSES.get(purpose, 'A governed purpose')} — no other "
                "published dataset is authoritative for it."
            ),
        ))

    dependants.extend(_analyses_needing({d.name for d in dependants if d.kind == "purpose"}))

    for relationship in session.execute(
        select(DatasetRelationship).where(
            (DatasetRelationship.from_dataset == dataset.name)
            | (DatasetRelationship.to_dataset == dataset.name)
        )
    ).scalars().all():
        dependants.append(Dependant(
            kind="relationship",
            name=relationship.name,
            detail=(
                f"{relationship.from_dataset}.{relationship.from_field} → "
                f"{relationship.to_dataset}.{relationship.to_field}"
            ),
        ))

    dependants.extend(_investigations_naming(dataset.name))
    return UsedBy(dataset=dataset.name, dependants=dependants)


def archive_dataset(session: Session, dataset_name: str, *,
                    acknowledge: bool = False) -> dict[str, Any]:
    """Take a dataset out of service, once someone has seen what depends on it."""
    dataset = get_dataset(session, dataset_name)
    usage = used_by(session, dataset_name)

    if usage.blocking and not acknowledge:
        raise DataBuilderError(
            f"'{dataset_name}' cannot be archived yet: "
            + "; ".join(f"{d.kind} {d.name}" for d in usage.blocking)
            + ". Publish a replacement and mark it authoritative, or archive it "
              "again with acknowledge=true to proceed knowing this."
        )

    dataset.lifecycle = DS_ARCHIVED
    # An archived dataset is authoritative for nothing. Leaving the claim behind
    # would let a purpose resolve to something out of service.
    dataset.authoritative_for = []
    session.flush()
    logger.info("Dataset '%s' archived (%d dependant(s) acknowledged).",
                dataset_name, len(usage.blocking))
    return {"dataset": dataset_name, "lifecycle": dataset.lifecycle,
            "acknowledged": [d.to_dict() for d in usage.blocking]}


# ================================================================= authority


def set_origin(session: Session, dataset_name: str, origin: str) -> DatasetDefinition:
    """Say whether this is client data or CreditProbe's demonstration book."""
    if origin not in VALID_ORIGINS:
        raise DataBuilderError(
            f"'{origin}' is not a dataset origin. Valid: {', '.join(sorted(VALID_ORIGINS))}."
        )
    dataset = get_dataset(session, dataset_name)
    dataset.origin = origin
    session.flush()
    return dataset


def set_family(session: Session, dataset_name: str, family: str) -> DatasetDefinition:
    """Put a dataset in a family, so a replacement is a governed act."""
    dataset = get_dataset(session, dataset_name)
    dataset.dataset_family = family.strip()
    session.flush()
    return dataset


def set_authoritative(session: Session, dataset_name: str,
                      purposes: list[str]) -> dict[str, Any]:
    """Declare which governed purposes this dataset is the source of truth for.

    Marking a dataset authoritative for a purpose is the moment client data
    replaces demonstration data: every certified analysis reading that purpose
    follows immediately, and each read records the redirect on its Trace.
    """
    unknown = [p for p in purposes if p not in GOVERNED_PURPOSES]
    if unknown:
        raise DataBuilderError(
            f"Not governed purposes: {', '.join(unknown)}. "
            f"Known purposes: {', '.join(sorted(GOVERNED_PURPOSES))}."
        )

    dataset = get_dataset(session, dataset_name)
    if purposes and dataset.lifecycle != DS_PUBLISHED:
        raise DataBuilderError(
            f"'{dataset_name}' is {dataset.lifecycle}, not published. A dataset the "
            "engine cannot read cannot be authoritative for anything."
        )

    displaced: list[str] = []
    for purpose in purposes:
        for other in session.execute(
            select(DatasetDefinition).where(
                DatasetDefinition.name != dataset.name,
                DatasetDefinition.authoritative_for.contains([purpose]),
                DatasetDefinition.origin == DatasetOrigin.DEMO.value,
            )
        ).scalars().all():
            # Demonstration data steps aside the moment client data claims the
            # purpose. Two authoritative sources for one purpose is not a state
            # the product allows.
            other.authoritative_for = [
                p for p in (other.authoritative_for or []) if p != purpose
            ]
            displaced.append(other.name)

    dataset.authoritative_for = sorted(set(purposes))
    session.flush()
    return {
        "dataset": dataset.name,
        "authoritative_for": dataset.authoritative_for,
        "displaced_demo_datasets": sorted(set(displaced)),
    }


def families(session: Session) -> list[dict[str, Any]]:
    """The dataset families, and what is in each."""
    grouped: dict[str, list[DatasetDefinition]] = {}
    for dataset in session.execute(
        select(DatasetDefinition).order_by(DatasetDefinition.name)
    ).scalars().all():
        grouped.setdefault(dataset.dataset_family or dataset.domain or "Ungrouped", []).append(
            dataset
        )

    return [
        {
            "family": name,
            "datasets": [
                {
                    "name": d.name,
                    "business_name": d.business_name or d.name,
                    "origin": d.origin,
                    "lifecycle": d.lifecycle,
                    "authoritative_for": list(d.authoritative_for or []),
                }
                for d in members
            ],
            "has_client_data": any(d.origin == DatasetOrigin.CLIENT.value for d in members),
        }
        for name, members in sorted(grouped.items())
    ]


def control_plane(session: Session) -> dict[str, Any]:
    """What is powering CreditProbe right now, purpose by purpose."""
    out: list[dict[str, Any]] = []
    for purpose, description in sorted(GOVERNED_PURPOSES.items()):
        candidates = session.execute(
            select(DatasetDefinition).where(
                DatasetDefinition.lifecycle == DS_PUBLISHED,
                DatasetDefinition.authoritative_for.contains([purpose]),
            ).order_by(DatasetDefinition.name)
        ).scalars().all()
        # Client data outranks demonstration data; this mirrors the ordering in
        # data_access/authority.py, which is what the engine actually applies.
        chosen = next(
            (d for d in candidates if d.origin == DatasetOrigin.CLIENT.value),
            candidates[0] if candidates else None,
        )
        out.append({
            "purpose": purpose,
            "description": description,
            "resolved": chosen is not None,
            "dataset": chosen.name if chosen else None,
            "origin": chosen.origin if chosen else None,
            "is_demo": bool(chosen and chosen.origin == DatasetOrigin.DEMO.value),
            "family": (chosen.dataset_family or "") if chosen else "",
            "alternatives": [d.name for d in candidates if chosen and d.name != chosen.name],
            "message": None if chosen else (
                f"No published dataset is authoritative for '{purpose}'. "
                "Publish one and mark it authoritative."
            ),
        })

    return {
        "purposes": out,
        "using_demo_data": any(p["is_demo"] for p in out),
        "unresolved": [p["purpose"] for p in out if not p["resolved"]],
    }


# =============================================================== replacement


def compare_schemas(session: Session, outgoing: str, incoming: str) -> dict[str, Any]:
    """Field-by-field: can `incoming` stand in for `outgoing`?

    This is the check that has to happen before client data replaces the demo
    book. A missing field is not a warning — every analysis reading it stops
    working — so the answer is a plain "can it or not", with the list.
    """
    old = get_dataset(session, outgoing)
    new = get_dataset(session, incoming)

    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}

    missing = sorted(set(old_fields) - set(new_fields))
    added = sorted(set(new_fields) - set(old_fields))

    retyped = sorted(
        name for name in set(old_fields) & set(new_fields)
        if old_fields[name].data_type != new_fields[name].data_type
    )
    unit_changed = sorted(
        name for name in set(old_fields) & set(new_fields)
        if (old_fields[name].unit or "") != (new_fields[name].unit or "")
    )

    return {
        "outgoing": old.name,
        "incoming": new.name,
        "compatible": not missing and not retyped,
        "missing_fields": [
            {"name": n, "definition": old_fields[n].definition,
             "unit": old_fields[n].unit, "data_type": old_fields[n].data_type}
            for n in missing
        ],
        "added_fields": added,
        "type_changes": [
            {"name": n, "from": old_fields[n].data_type, "to": new_fields[n].data_type}
            for n in retyped
        ],
        "unit_changes": [
            {"name": n, "from": old_fields[n].unit, "to": new_fields[n].unit}
            for n in unit_changed
        ],
        "verdict": (
            f"'{new.name}' supplies every field '{old.name}' does, with the same types."
            if not missing and not retyped else
            f"'{new.name}' cannot replace '{old.name}' yet: "
            + ", ".join(
                filter(None, [
                    f"{len(missing)} field(s) missing" if missing else "",
                    f"{len(retyped)} type change(s)" if retyped else "",
                ])
            )
            + "."
        ),
    }


def replace_dataset(session: Session, *, outgoing: str, incoming: str,
                    acknowledge: bool = False) -> dict[str, Any]:
    """Hand a purpose over from one dataset to another, and retire the old one.

    Refuses an incompatible replacement unless the caller acknowledges the
    difference, because a replacement that drops a field breaks every analysis
    reading it and "I did not realise" is not a defence a bank can offer.
    """
    comparison = compare_schemas(session, outgoing, incoming)
    if not comparison["compatible"] and not acknowledge:
        raise DataBuilderError(
            comparison["verdict"]
            + " Fix the incoming dataset's mappings, or replace again with "
              "acknowledge=true to proceed knowing what is lost."
        )

    old = get_dataset(session, outgoing)
    new = get_dataset(session, incoming)
    purposes = list(old.authoritative_for or [])

    if purposes:
        handover = set_authoritative(session, incoming, purposes)
    else:
        handover = {"dataset": new.name, "authoritative_for": [],
                    "displaced_demo_datasets": []}

    # The family follows the purpose: a replacement belongs with what it replaced.
    if old.dataset_family and not new.dataset_family:
        new.dataset_family = old.dataset_family

    old.authoritative_for = []
    old.lifecycle = DS_ARCHIVED
    session.flush()

    return {
        "outgoing": old.name,
        "incoming": new.name,
        "purposes_transferred": purposes,
        "comparison": comparison,
        "handover": handover,
        "note": (
            f"'{old.name}' is archived and authoritative for nothing. Every "
            "certified analysis now reads "
            f"'{new.name}' for {', '.join(purposes) or 'no governed purpose'}, and "
            "each read records that on its Trace."
        ),
    }


__all__ = [
    "Dependant",
    "sync_bundled_catalog",
    "UsedBy",
    "archive_dataset",
    "compare_schemas",
    "control_plane",
    "families",
    "replace_dataset",
    "set_authoritative",
    "set_family",
    "set_origin",
    "used_by",
]
