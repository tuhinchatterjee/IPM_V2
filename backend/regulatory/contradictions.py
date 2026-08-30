"""Regulatory contradictions and how they are settled. §34.

Twelve ways two regulatory positions can disagree, ten governed ways to
settle it, and one thing this module will not do.

§34's own instruction: **do not ask simply "which one to delete."**

That is the whole design. A regulatory contradiction is almost never a
mistake to be cleaned up — it is usually two rules that are both real, from
different regulators, different dates or different products, and the work is
to say WHICH APPLIES WHEN rather than which survives. A resolution set
offering only "keep this one" forces a reviewer to destroy a true statement
in order to close a ticket, and the fact it was true does not come back.

So SUPERSEDES carries a date, MORE SPECIFIC SCOPE carries the scope, and
BOTH APPLY exists. Every resolution keeps the history: §34 ends "Preserve
history", and nothing in this module deletes.

Nothing here decides
---------------------
`detect()` finds; `resolve()` records what a person decided. There is no
automatic resolution, and there is deliberately no confidence score
suggesting one — resolving a regulatory conflict is a legal opinion, and a
number beside it would invite somebody to accept the machine's.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

logger = logging.getLogger(__name__)

CONTRADICTIONS_VERSION = "1.0.0"

# --------------------------------------------------------------- §34's twelve

NEW_VS_PRIOR_CIRCULAR = "NEW_VS_PRIOR_CIRCULAR"
INTERPRETATION_VS_LOCAL_POLICY = "INTERPRETATION_VS_LOCAL_POLICY"
REGULATOR_VS_REGULATOR = "REGULATOR_VS_REGULATOR"
EFFECTIVE_DATE_OVERLAP = "EFFECTIVE_DATE_OVERLAP"
SCOPE_OR_PRODUCT_CONFLICT = "SCOPE_OR_PRODUCT_CONFLICT"
DEFINITION_CONFLICT = "DEFINITION_CONFLICT"
THRESHOLD_CONFLICT = "THRESHOLD_CONFLICT"
FORMULA_CONFLICT = "FORMULA_CONFLICT"
METHOD_CONFLICT = "METHOD_CONFLICT"
DATA_REQUIREMENT_CONFLICT = "DATA_REQUIREMENT_CONFLICT"
STUDIO_METHOD_CONFLICT = "EXISTING_STUDIO_METHOD_CONFLICT"
TEACHING_CASE_CONFLICT = "EXISTING_TEACHING_CASE_CONFLICT"

CLASSES: tuple[tuple[str, str], ...] = (
    (NEW_VS_PRIOR_CIRCULAR,
     "A newer circular from the same regulator says something different from "
     "one already held. Usually supersession — but only usually, and the "
     "date it takes effect is the answer rather than which file is newer."),
    (INTERPRETATION_VS_LOCAL_POLICY,
     "The regulation permits what the bank's own policy forbids, or the "
     "reverse. A stricter local policy is not a conflict to resolve away; it "
     "is a decision the bank made."),
    (REGULATOR_VS_REGULATOR,
     "Two regulators require different things. Neither is wrong, and a bank "
     "operating in both jurisdictions owes both."),
    (EFFECTIVE_DATE_OVERLAP,
     "Two rules are simultaneously in force over an overlapping window, "
     "usually because a transitional arrangement was not read."),
    (SCOPE_OR_PRODUCT_CONFLICT,
     "The same treatment is required of populations that are defined "
     "differently — corporate against retail, on-balance against off."),
    (DEFINITION_CONFLICT,
     "The same term means two things. The most dangerous class here, "
     "because every downstream figure inherits the ambiguity silently."),
    (THRESHOLD_CONFLICT,
     "Two numbers for the same trigger. Whichever is applied, exposures sit "
     "on the wrong side of the other one, and the count of them is the "
     "size of the problem."),
    (FORMULA_CONFLICT,
     "Two ways to compute the same figure. Both produce a number, both look "
     "right on a page, and only the provenance distinguishes them."),
    (METHOD_CONFLICT,
     "Two required approaches to the same assessment — a model against a "
     "standardised table, say. Not reconcilable by averaging."),
    (DATA_REQUIREMENT_CONFLICT,
     "Different fields, granularities or retention required for the same "
     "purpose."),
    (STUDIO_METHOD_CONFLICT,
     "The requirement contradicts a certified Analysis Studio method that is "
     "in production and has been producing numbers."),
    (TEACHING_CASE_CONFLICT,
     "The requirement contradicts an approved teaching case, which means "
     "CreditProbe has been answering questions the other way."),
)

CLASS_IDS: tuple[str, ...] = tuple(c for c, _ in CLASSES)

EXPECTED_CLASSES = 12
if len(CLASSES) != EXPECTED_CLASSES:
    raise AssertionError(
        f"§34 names {EXPECTED_CLASSES} contradiction classes; this module "
        f"has {len(CLASSES)}.")

#: Classes where something in production is already acting on the losing
#: side. These are not merely disagreements to file: numbers have been
#: produced and shown, and a resolution has to say what happens to them.
IN_PRODUCTION: frozenset[str] = frozenset({
    STUDIO_METHOD_CONFLICT, TEACHING_CASE_CONFLICT,
    INTERPRETATION_VS_LOCAL_POLICY,
})

# ------------------------------------------------------------ §34's ten

SUPERSEDES_FROM_DATE = "SUPERSEDES_FROM_DATE"
MORE_SPECIFIC_SCOPE = "MORE_SPECIFIC_SCOPE"
LOCAL_POLICY_STRONGER = "LOCAL_POLICY_STRONGER"
JURISDICTION_SPECIFIC = "JURISDICTION_SPECIFIC"
PRODUCT_SPECIFIC = "PRODUCT_SPECIFIC"
BOTH_APPLY = "BOTH_APPLY"
EXCEPTION = "EXCEPTION"
KEEP_LOCAL_PENDING_REVIEW = "KEEP_LOCAL_PENDING_REVIEW"
RETIRE_PRIOR = "RETIRE_PRIOR"
CREATE_NEW_VERSION = "CREATE_NEW_VERSION"

RESOLUTIONS: tuple[tuple[str, str], ...] = (
    (SUPERSEDES_FROM_DATE,
     "The newer rule replaces the older one FROM a stated date. Before that "
     "date the old rule is still the right answer, and a restatement of a "
     "prior period has to quote it."),
    (MORE_SPECIFIC_SCOPE,
     "Both are real; the narrower one governs where it applies and the wider "
     "one everywhere else."),
    (LOCAL_POLICY_STRONGER,
     "The bank has chosen to be stricter than required. Recorded as a "
     "decision rather than as a regulatory position."),
    (JURISDICTION_SPECIFIC,
     "Each rule governs its own jurisdiction. Nothing is discarded."),
    (PRODUCT_SPECIFIC,
     "Each rule governs its own product or portfolio."),
    (BOTH_APPLY,
     "Both obligations stand and the bank owes both — usually the stricter "
     "binds in practice, and saying so is not the same as retiring the "
     "other."),
    (EXCEPTION,
     "One rule is a carve-out from the other rather than a contradiction of "
     "it."),
    (KEEP_LOCAL_PENDING_REVIEW,
     "Not settled. What is already here keeps applying while somebody gets "
     "an opinion. Visible as unresolved rather than quietly closed."),
    (RETIRE_PRIOR,
     "The older position is withdrawn entirely. The record of it stays, "
     "because answers were produced under it."),
    (CREATE_NEW_VERSION,
     "Neither as written. A new version is drafted that reconciles them, and "
     "goes through validation like anything else."),
)

RESOLUTION_IDS: tuple[str, ...] = tuple(r for r, _ in RESOLUTIONS)

EXPECTED_RESOLUTIONS = 10
if len(RESOLUTIONS) != EXPECTED_RESOLUTIONS:
    raise AssertionError(
        f"§34 names {EXPECTED_RESOLUTIONS} resolutions; this module has "
        f"{len(RESOLUTIONS)}.")

#: Resolutions that need a date to mean anything. "Supersedes" with no date
#: is "delete the old one", which §34 forbids.
NEEDS_DATE: frozenset[str] = frozenset({SUPERSEDES_FROM_DATE})
#: Resolutions that need the axis they split on. Without it a split is a
#: deferral wearing a decision's name.
NEEDS_AXIS: frozenset[str] = frozenset({
    MORE_SPECIFIC_SCOPE, JURISDICTION_SPECIFIC, PRODUCT_SPECIFIC,
})
#: The one resolution that leaves the conflict open. Counted as unresolved
#: everywhere, so a queue cannot be emptied by choosing it.
DEFERRING: frozenset[str] = frozenset({KEEP_LOCAL_PENDING_REVIEW})

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"
CRITICAL = "CRITICAL"
SEVERITIES: tuple[str, ...] = (LOW, MEDIUM, HIGH, CRITICAL)


class ContradictionError(Exception):
    """A resolution that was refused, and why."""


@dataclass
class Position:
    """One side of a contradiction, whatever kind of thing it is."""

    kind: str = ""            # requirement, method, teaching case, policy
    identifier: str = ""
    label: str = ""
    source: str = ""          # document reference, or "local policy"
    regulator: str = ""
    jurisdiction: str = ""
    scope: str = ""
    product: str = ""
    effective_from: date | None = None
    effective_to: date | None = None
    value: float | None = None
    unit: str = ""
    statement: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "identifier": self.identifier,
            "label": self.label, "source": self.source,
            "regulator": self.regulator, "jurisdiction": self.jurisdiction,
            "scope": self.scope, "product": self.product,
            "effective_from": (self.effective_from.isoformat()
                               if self.effective_from else ""),
            "effective_to": (self.effective_to.isoformat()
                             if self.effective_to else ""),
            "value": self.value, "unit": self.unit,
            "statement": self.statement,
        }


@dataclass
class Contradiction:
    """Two positions that cannot both be applied as written."""

    contradiction_id: str = ""
    conflict_class: str = ""
    severity: str = MEDIUM
    summary: str = ""
    incoming: Position = field(default_factory=Position)
    existing: Position = field(default_factory=Position)

    #: What §34's ten would fit here, ranked. Options, not a recommendation:
    #: the module suggests what is available and does not choose.
    available: tuple[str, ...] = ()
    resolution: str = ""
    resolution_reason: str = ""
    effective_from: str = ""
    split_axis: str = ""
    resolved_by: str = ""
    resolved_at: str = ""

    created_at: str = ""
    tenant: str = ""

    def __post_init__(self) -> None:
        self.contradiction_id = (self.contradiction_id
                                 or f"rcon_{uuid.uuid4().hex[:16]}")
        self.created_at = self.created_at or datetime.now(UTC).isoformat()
        if not self.available:
            self.available = _available(self)

    @property
    def resolved(self) -> bool:
        """Whether this is settled.

        KEEP_LOCAL_PENDING_REVIEW is explicitly not: it is a decision to
        wait, and a queue that counted it as resolved could be emptied
        without settling anything.
        """
        return bool(self.resolution) and self.resolution not in DEFERRING

    @property
    def blocking(self) -> bool:
        """Whether this must be settled before a release.

        A high-severity conflict that somebody chose to defer is still
        blocking. Deferring is a legitimate answer to "what do we do?" and
        not an answer to "is it safe to release?".
        """
        return not self.resolved and self.severity in (HIGH, CRITICAL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "conflict_class": self.conflict_class,
            "class_means": dict(CLASSES).get(self.conflict_class, ""),
            "severity": self.severity,
            "summary": self.summary,
            "incoming": self.incoming.to_dict(),
            "existing": self.existing.to_dict(),
            "available_resolutions": [
                {"id": r, "means": dict(RESOLUTIONS)[r],
                 "needs_date": r in NEEDS_DATE,
                 "needs_axis": r in NEEDS_AXIS,
                 "leaves_it_open": r in DEFERRING}
                for r in self.available],
            "resolution": self.resolution,
            "resolution_reason": self.resolution_reason,
            "effective_from": self.effective_from,
            "split_axis": self.split_axis,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "resolved": self.resolved,
            "blocking": self.blocking,
            "in_production": self.conflict_class in IN_PRODUCTION,
        }


def _available(conflict: Contradiction) -> tuple[str, ...]:
    """Which of §34's ten could apply here.

    Offers rather than recommends, and always includes the two that keep
    both positions alive — BOTH_APPLY and KEEP_LOCAL_PENDING_REVIEW — so a
    reviewer under time pressure is never left with only destructive
    options.
    """
    incoming, existing = conflict.incoming, conflict.existing
    options: list[str] = []

    if conflict.conflict_class == NEW_VS_PRIOR_CIRCULAR:
        options += [SUPERSEDES_FROM_DATE, CREATE_NEW_VERSION, RETIRE_PRIOR]
    if conflict.conflict_class == INTERPRETATION_VS_LOCAL_POLICY:
        options += [LOCAL_POLICY_STRONGER, BOTH_APPLY, CREATE_NEW_VERSION]
    if conflict.conflict_class == REGULATOR_VS_REGULATOR:
        options += [JURISDICTION_SPECIFIC, BOTH_APPLY]
    if conflict.conflict_class == EFFECTIVE_DATE_OVERLAP:
        options += [SUPERSEDES_FROM_DATE, EXCEPTION, BOTH_APPLY]

    if incoming.jurisdiction and existing.jurisdiction and \
            incoming.jurisdiction != existing.jurisdiction:
        options.append(JURISDICTION_SPECIFIC)
    if incoming.product and existing.product and \
            incoming.product != existing.product:
        options.append(PRODUCT_SPECIFIC)
    if incoming.scope and existing.scope and incoming.scope != existing.scope:
        options.append(MORE_SPECIFIC_SCOPE)
    if conflict.conflict_class in (THRESHOLD_CONFLICT, FORMULA_CONFLICT,
                                  METHOD_CONFLICT, DEFINITION_CONFLICT):
        options += [CREATE_NEW_VERSION, EXCEPTION]
    if conflict.conflict_class in IN_PRODUCTION:
        options.append(CREATE_NEW_VERSION)

    # Always available: both can be true, and waiting is an honest answer.
    options += [BOTH_APPLY, KEEP_LOCAL_PENDING_REVIEW]

    seen: list[str] = []
    for option in options:
        if option not in seen:
            seen.append(option)
    return tuple(seen)


# ------------------------------------------------------------------ detect


def _overlaps(a: Position, b: Position) -> bool:
    """Whether two positions are in force over an overlapping window.

    Fail-open on a missing date: a position that does not say when it starts
    is treated as possibly overlapping, so an undated rule surfaces as a
    conflict for a person to look at rather than being quietly excluded.
    """
    if a.effective_from is None or b.effective_from is None:
        return True
    a_end = a.effective_to or date.max
    b_end = b.effective_to or date.max
    return a.effective_from <= b_end and b.effective_from <= a_end


def detect(incoming: Position, existing: list[Position], *,
           tenant: str = "") -> list[Contradiction]:
    """Find where an incoming position disagrees with what is already held.

    Deliberately generous. A false positive costs a reviewer thirty seconds;
    a missed definition conflict propagates silently into every figure that
    inherits the term.
    """
    found: list[Contradiction] = []
    for other in existing:
        conflict_class, severity, summary = _compare(incoming, other)
        if not conflict_class:
            continue
        found.append(Contradiction(
            conflict_class=conflict_class, severity=severity,
            summary=summary, incoming=incoming, existing=other,
            tenant=tenant))
    return found


def _compare(incoming: Position, existing: Position
             ) -> tuple[str, str, str]:
    """Classify one pair. Empty class means no disagreement found."""
    if not _overlaps(incoming, existing):
        return "", "", ""

    if existing.kind == "studio_method":
        return (STUDIO_METHOD_CONFLICT, CRITICAL,
                f"{incoming.label or 'This requirement'} contradicts the "
                f"certified method {existing.label or existing.identifier}, "
                "which is in production and has been producing numbers.")
    if existing.kind == "teaching_case":
        return (TEACHING_CASE_CONFLICT, HIGH,
                f"{incoming.label or 'This requirement'} contradicts an "
                f"approved teaching case, so CreditProbe has been answering "
                "questions the other way.")
    if existing.kind == "local_policy":
        return (INTERPRETATION_VS_LOCAL_POLICY, HIGH,
                "The regulation and the bank's own policy do not say the "
                "same thing. A stricter local policy is a decision, not a "
                "defect.")

    if (incoming.value is not None and existing.value is not None
            and incoming.unit == existing.unit
            and incoming.value != existing.value):
        return (THRESHOLD_CONFLICT, HIGH,
                f"Two thresholds for the same trigger: "
                f"{incoming.value}{incoming.unit} against "
                f"{existing.value}{existing.unit}.")

    if incoming.regulator and existing.regulator and \
            incoming.regulator != existing.regulator:
        return (REGULATOR_VS_REGULATOR, HIGH,
                f"{incoming.regulator} and {existing.regulator} require "
                "different things over the same window. Neither is wrong.")

    if incoming.source and existing.source and \
            incoming.source != existing.source and \
            incoming.regulator == existing.regulator:
        if incoming.effective_from and existing.effective_from and \
                incoming.effective_from > existing.effective_from:
            return (NEW_VS_PRIOR_CIRCULAR, MEDIUM,
                    f"{incoming.source} is later than {existing.source} and "
                    "says something different. Probably supersession — the "
                    "date it takes effect is the answer, not which file is "
                    "newer.")
        return (EFFECTIVE_DATE_OVERLAP, MEDIUM,
                f"{incoming.source} and {existing.source} are both in force "
                "over an overlapping window.")

    if incoming.scope and existing.scope and incoming.scope != existing.scope:
        return (SCOPE_OR_PRODUCT_CONFLICT, MEDIUM,
                f"The same treatment is required of {incoming.scope} and of "
                f"{existing.scope}, which are defined differently.")

    return "", "", ""


# ----------------------------------------------------------------- resolve


def resolve(conflict: Contradiction, resolution: str, *, reason: str,
            by: str, effective_from: str = "",
            split_axis: str = "") -> Contradiction:
    """Record a person's decision. Nothing decides on its own.

    Refuses SUPERSEDES_FROM_DATE without the date, because supersession with
    no date is deletion — and §34's instruction is not to ask which one to
    delete.
    """
    if resolution not in RESOLUTION_IDS:
        raise ContradictionError(
            f"{resolution!r} is not one of §34's ten resolutions; expected "
            f"one of {', '.join(RESOLUTION_IDS)}")
    if not reason.strip():
        raise ContradictionError(
            "a resolution with no reason cannot be defended later, and this "
            "is exactly the decision a regulator will ask about")
    if not by.strip():
        raise ContradictionError("a resolution needs a named person")
    if resolution in NEEDS_DATE and not effective_from.strip():
        raise ContradictionError(
            "supersession needs the date it takes effect. Without one this "
            "is 'delete the old rule', and a restatement of a prior period "
            "still has to quote what applied then")
    if resolution in NEEDS_AXIS and not split_axis.strip():
        raise ContradictionError(
            f"{resolution} needs the axis it splits on — which "
            "jurisdiction, which product, which population. Without it the "
            "split cannot be applied to anything")

    conflict.resolution = resolution
    conflict.resolution_reason = reason.strip()
    conflict.effective_from = effective_from.strip()
    conflict.split_axis = split_axis.strip()
    conflict.resolved_by = by.strip()
    conflict.resolved_at = datetime.now(UTC).isoformat()
    return conflict


def summary(conflicts: list[Contradiction]) -> dict[str, Any]:
    """What is outstanding, with deferrals counted as outstanding."""
    unresolved = [c for c in conflicts if not c.resolved]
    blocking = [c for c in conflicts if c.blocking]
    deferred = [c for c in conflicts if c.resolution in DEFERRING]
    return {
        "total": len(conflicts),
        "unresolved": len(unresolved),
        "blocking": len(blocking),
        "deferred": len(deferred),
        "blocking_ids": [c.contradiction_id for c in blocking],
        "by_class": {cid: sum(1 for c in conflicts
                              if c.conflict_class == cid)
                     for cid in CLASS_IDS},
        "note": (
            "A conflict somebody chose to keep pending is counted as "
            "unresolved. Deferring is an honest answer to 'what do we do?' "
            "and is not an answer to 'is it safe to release?'."
        ),
    }
