"""
What a Forward Risk Signal model may be called, and when.

This module exists to make one thing impossible: describing an unvalidated
model as validated.

"Validated" is not a compliment in credit risk. It is a statement that an
independent function has tested the model against its intended use, documented
the result, and signed it. A credit committee that reads "validated" stops
asking the questions it would otherwise ask — which is precisely why the word
must never appear on a model that has not been through that.

So the label is derived here, from evidence, rather than typed anywhere. A model
displays as a PROTOTYPE unless a validation record actually exists on it, and
the words "validated", "production model" and "regulatory model" are reachable
only through `label_for`, which will not return them without one.
"""

from __future__ import annotations

from typing import Any

PROTOTYPE = "prototype"
CANDIDATE = "candidate"
VALIDATED = "validated"
APPROVED = "approved"
RETIRED = "retired"

LIFECYCLES = (PROTOTYPE, CANDIDATE, VALIDATED, APPROVED, RETIRED)

#: What each lifecycle stage is called on screen. Note that nothing below the
#: validated stage may use the word.
LIFECYCLE_LABEL = {
    PROTOTYPE: "Prototype",
    CANDIDATE: "Candidate",
    VALIDATED: "Independently validated",
    APPROVED: "Approved for use",
    RETIRED: "Retired",
}

#: The standing description of the whole capability. Used wherever the module
#: introduces itself.
CAPABILITY_LABEL = "Prototype Forward Risk Signal"

CAPABILITY_NOTICE = (
    "This is a prototype forward risk signal, fitted on CreditProbe's synthetic "
    "demonstration data. It has not been independently validated, it is not a "
    "production or regulatory model, and no credit decision should rest on it."
)

#: A validation record must carry all of these before the word is permitted.
REQUIRED_VALIDATION_KEYS = ("validated_by", "validated_on", "report_reference")


def has_validation(validation: dict[str, Any] | None) -> bool:
    """Whether a real, independent validation record exists.

    A record with a `validated_by` and nothing else is somebody typing their own
    name into a box. All three fields — who, when, and where the report is —
    have to be there before the model is allowed to say it was validated.
    """
    if not isinstance(validation, dict):
        return False
    return all(str(validation.get(key) or "").strip() for key in REQUIRED_VALIDATION_KEYS)


def effective_lifecycle(stored: str, validation: dict[str, Any] | None) -> str:
    """The lifecycle a model is actually in, whatever the row says.

    The stored value is a request; the validation record is the evidence. Where
    they disagree, the evidence wins and the model falls back to candidate —
    never quietly upward.
    """
    stage = stored if stored in LIFECYCLES else PROTOTYPE
    if stage in (VALIDATED, APPROVED) and not has_validation(validation):
        return CANDIDATE
    return stage


def label_for(stored: str, validation: dict[str, Any] | None) -> str:
    """The name to put on screen."""
    return LIFECYCLE_LABEL[effective_lifecycle(stored, validation)]


def display_name(target_label: str, stored: str,
                 validation: dict[str, Any] | None) -> str:
    """The full name of one model, as a heading.

    e.g. "Prototype Forward Risk Signal — Stage 1 to Stage 2".
    """
    stage = effective_lifecycle(stored, validation)
    prefix = (
        CAPABILITY_LABEL if stage in (PROTOTYPE, CANDIDATE, RETIRED)
        else "Forward Risk Signal"
    )
    return f"{prefix} — {target_label}"


def notice_for(stored: str, validation: dict[str, Any] | None) -> str:
    """The sentence that goes with the model, wherever it is shown."""
    stage = effective_lifecycle(stored, validation)
    if stage == PROTOTYPE:
        return CAPABILITY_NOTICE
    if stage == CANDIDATE:
        return (
            "This model is a candidate. It has been fitted and backtested but "
            "not independently validated, so it is not a production or "
            "regulatory model and no credit decision should rest on it."
        )
    if stage == RETIRED:
        return "This model has been retired and is kept for the record only."
    who = str((validation or {}).get("validated_by") or "").strip()
    when = str((validation or {}).get("validated_on") or "").strip()
    reference = str((validation or {}).get("report_reference") or "").strip()
    return (
        f"Independently validated by {who} on {when}. Report: {reference}. "
        "Use is subject to the conditions recorded in that report."
    )


__all__ = [
    "APPROVED",
    "CANDIDATE",
    "CAPABILITY_LABEL",
    "CAPABILITY_NOTICE",
    "LIFECYCLES",
    "LIFECYCLE_LABEL",
    "PROTOTYPE",
    "REQUIRED_VALIDATION_KEYS",
    "RETIRED",
    "VALIDATED",
    "display_name",
    "effective_lifecycle",
    "has_validation",
    "label_for",
    "notice_for",
]
