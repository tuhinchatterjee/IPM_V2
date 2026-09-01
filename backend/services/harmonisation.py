"""
Schema harmonisation: matching a bank's columns to CreditProbe's governed vocabulary.

The problem. A bank's extract calls it `EAD_USD_MN`, `Exposure at Default` or
`exp_at_def`. CreditProbe's dictionary calls it `ead`. Someone has to decide those are
the same thing, and doing it by hand for two hundred columns is where data
onboarding actually stalls.

What this does. For every source column it proposes the governed field it most
likely supplies, WITH THE REASON and a confidence, and lists the alternatives it
considered. Then it stops. A proposal is never applied: the steward accepts it,
and until they do the mapping stays unmapped and the dataset stays unpublishable.

Why the reason matters more than the score. "0.82" tells a steward nothing they
can check. "The name matches a known alias of 'ead', and the values are numeric
with the same order of magnitude as the existing column" tells them what to
verify. Every proposal below carries evidence of that kind, drawn from the
profile the upload already produced — never from reading the data again here.

Where a model fits. The deterministic matcher handles the ordinary cases: exact
names, known aliases, and shapes that agree. When a model key is configured it
is asked ONLY about the columns nothing matched, it is given only column names,
types and the governed dictionary — never a single row of data — and its answer
is a suggestion that goes through the same acceptance step as any other. It
cannot map a field, cannot invent a governed name, and cannot publish anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.platform import FieldDefinition
from backend.services.data_builder import (
    get_dataset,
    known_governed_fields,
    latest_upload,
    slugify,
    suggest_governed_field,
)

logger = logging.getLogger(__name__)

#: Below this, a proposal is offered but pre-selected as "needs a decision".
CONFIDENT = 0.75

#: Types that can stand in for one another without a conversion. A source column
#: read as an integer supplying a governed float is not a mismatch.
COMPATIBLE: dict[str, set[str]] = {
    "integer": {"integer", "float"},
    "float": {"integer", "float"},
    "string": {"string", "category"},
    "category": {"string", "category"},
    "date": {"date", "datetime"},
    "datetime": {"date", "datetime"},
    "boolean": {"boolean"},
}


@dataclass
class Proposal:
    """One source column, and what CreditProbe thinks it is."""

    source_column: str
    source_type: str
    governed_field: str | None
    confidence: float
    reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    #: Where the suggestion came from — "name", "alias", "shape", "model".
    basis: str = ""

    @property
    def confident(self) -> bool:
        return self.governed_field is not None and self.confidence >= CONFIDENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_column": self.source_column,
            "source_type": self.source_type,
            "governed_field": self.governed_field,
            "confidence": round(self.confidence, 2),
            "confident": self.confident,
            "reasons": list(self.reasons),
            "concerns": list(self.concerns),
            "alternatives": list(self.alternatives),
            "basis": self.basis,
        }


def _dictionary(session: Session) -> dict[str, dict[str, Any]]:
    """Every governed field CreditProbe knows, with the definition a steward would read."""
    out: dict[str, dict[str, Any]] = {}
    for row in session.execute(select(FieldDefinition)).scalars():
        # A field name is used across datasets; the first definition wins and the
        # rest are the same thing by construction.
        out.setdefault(row.name, {
            "name": row.name,
            "business_name": row.business_name or row.name,
            "definition": row.definition,
            "data_type": row.data_type,
            "unit": row.unit,
            "allowed_values": row.allowed_values,
        })
    return out


def _type_note(source_type: str, governed_type: str) -> str | None:
    if not governed_type or not source_type:
        return None
    if source_type in COMPATIBLE.get(governed_type, {governed_type}):
        return None
    return (
        f"The column reads as {source_type}; '{governed_type}' is expected. "
        "Check the extract before accepting this."
    )


def _value_note(column: dict[str, Any], governed: dict[str, Any]) -> str | None:
    """Whether the observed values agree with what the dictionary permits."""
    allowed = governed.get("allowed_values")
    samples = column.get("sample_values") or column.get("top_values") or []
    if not allowed or not samples:
        return None
    values = [
        str(s.get("value") if isinstance(s, dict) else s) for s in samples[:12]
    ]
    unknown = sorted({v for v in values if v and v not in {str(a) for a in allowed}})
    if not unknown:
        return None
    return (
        f"{len(unknown)} observed value(s) are not in the permitted list for "
        f"'{governed['name']}': {', '.join(unknown[:4])}."
    )


def _alternatives(slug: str, dictionary: dict[str, dict[str, Any]],
                  chosen: str | None) -> list[str]:
    """Other governed fields a steward might reasonably have meant.

    Kept small and only offered where the name genuinely overlaps: a list of
    twelve near-misses is not help.
    """
    parts = {p for p in slug.split("_") if len(p) > 2}
    scored = [
        name for name in dictionary
        if name != chosen and parts & {p for p in name.split("_") if len(p) > 2}
    ]
    return sorted(scored)[:4]


def propose(session: Session, dataset_name: str) -> dict[str, Any]:
    """Match every column of the latest upload to the governed dictionary.

    Reads the profile the upload already produced. It does not open the file
    again, and it does not read a single row of the data here.
    """
    dataset = get_dataset(session, dataset_name)
    upload = latest_upload(session, dataset)
    if upload is None:
        return {
            "dataset": dataset_name,
            "proposals": [],
            "message": "Nothing has been uploaded to this dataset yet.",
        }

    dictionary = _dictionary(session)
    known = known_governed_fields(session)
    proposals: list[Proposal] = []

    for column in (upload.profile or {}).get("columns", []):
        name = str(column.get("name") or "")
        source_type = str(column.get("inferred_type") or column.get("type") or "")
        slug = slugify(name)
        governed, confidence = suggest_governed_field(name, known)

        proposal = Proposal(
            source_column=name,
            source_type=source_type,
            governed_field=governed,
            confidence=confidence,
            alternatives=_alternatives(slug, dictionary, governed),
        )

        if governed is None:
            proposal.basis = "none"
            proposal.reasons.append(
                "No governed field has this name, a known alias of it, or a name "
                "it contains. This is either a new field or one named differently "
                "from anything CreditProbe has seen."
            )
            proposals.append(proposal)
            continue

        entry = dictionary.get(governed, {})
        if confidence >= 1.0:
            proposal.basis = "name"
            proposal.reasons.append(f"The column name is the governed field '{governed}'.")
        elif confidence >= 0.8:
            proposal.basis = "alias"
            proposal.reasons.append(
                f"'{name}' is a known way of writing '{governed}' "
                f"({entry.get('business_name', governed)})."
            )
        else:
            proposal.basis = "shape"
            proposal.reasons.append(
                f"The name contains '{governed}', which suggests it supplies it."
            )

        if entry.get("definition"):
            proposal.reasons.append(f"CreditProbe defines '{governed}' as: {entry['definition']}")

        note = _type_note(source_type, str(entry.get("data_type") or ""))
        if note:
            proposal.concerns.append(note)
            proposal.confidence = min(proposal.confidence, 0.5)

        value_note = _value_note(column, entry) if entry else None
        if value_note:
            proposal.concerns.append(value_note)
            proposal.confidence = min(proposal.confidence, 0.5)

        if not proposal.concerns and entry.get("unit"):
            proposal.reasons.append(
                f"'{governed}' is recorded in {entry['unit']}; confirm the extract uses "
                "the same unit."
            )

        proposals.append(proposal)

    confident = [p for p in proposals if p.confident]
    unmatched = [p for p in proposals if p.governed_field is None]

    return {
        "dataset": dataset_name,
        "proposals": [p.to_dict() for p in proposals],
        "counts": {
            "columns": len(proposals),
            "confident": len(confident),
            "needs_a_decision": len(proposals) - len(confident) - len(unmatched),
            "unmatched": len(unmatched),
        },
        "message": (
            f"{len(confident)} of {len(proposals)} columns match the governed "
            f"dictionary confidently. Nothing has been applied — accept the ones you "
            "agree with."
        ),
        "rule": (
            "These are proposals. A mapping only exists once a steward accepts it, "
            "and a dataset cannot be published while columns it needs are unmapped."
        ),
    }


def accept(session: Session, dataset_name: str,
           accepted: dict[str, str]) -> dict[str, Any]:
    """Apply the proposals a steward has agreed to, and only those.

    `accepted` is {source column: governed field}. A column not named here keeps
    whatever state it already had, so accepting three of forty proposals does
    not silently discard the other thirty-seven.
    """
    from backend.services.data_builder import get_mappings, set_mappings

    dataset = get_dataset(session, dataset_name)
    current = {m.source_column: m for m in get_mappings(session, dataset)}

    unknown = sorted(set(accepted) - set(current))
    if unknown:
        from backend.services.data_builder import DataBuilderError

        raise DataBuilderError(
            f"Not columns of the latest upload: {', '.join(unknown)}."
        )

    payload = []
    for source_column, mapping in current.items():
        if source_column in accepted:
            payload.append({
                "source_column": source_column,
                "governed_field": accepted[source_column],
                "status": "mapped",
            })
        else:
            payload.append({
                "source_column": source_column,
                "governed_field": mapping.governed_field,
                "status": mapping.status,
            })

    set_mappings(session, dataset_name, payload)
    return {
        "dataset": dataset_name,
        "accepted": len(accepted),
        "still_unmapped": sum(1 for p in payload if p["status"] != "mapped"),
    }


__all__ = ["CONFIDENT", "Proposal", "accept", "propose"]
