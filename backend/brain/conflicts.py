"""Contradictory learning between two Brains. §20, §21.

Two installations both learned something, and they disagree. That is not a
merge conflict in the source-control sense - both sides are somebody's
considered judgement, backed by their own evidence, about a portfolio the
other has never seen.

So the resolutions here are the ones a credit governance function actually
uses, and "newest wins" is not among them. §21 is explicit: "No automatic
winner merely because incoming is newer." A Riyadh installation that
tightened a covenant threshold last week has not thereby overruled a London
policy set two years ago after a regulatory review; the answer is usually
SCOPE_SPLIT, and the product's job is to make that the easy option rather
than the clever one.

The twelve conflict classes come from §20 verbatim. Each detector is
deterministic - it compares two declared items - because a model asked
whether two policies contradict each other will find a reading in which
they do not.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

CONFLICTS_VERSION = "1.0.0"

# ------------------------------------------------------------- the classes

CONCEPT_DIRECTION = "CONCEPT_DIRECTION"
ALIAS_TARGET = "ALIAS_TARGET"
PATTERN_OBJECTIVE = "PATTERN_OBJECTIVE"
METHOD_FORMULA = "METHOD_FORMULA"
REGULATION_INTERPRETATION = "REGULATION_INTERPRETATION"
THRESHOLD_SCOPE = "THRESHOLD_SCOPE"
CASE_EXPECTED_PLAN = "CASE_EXPECTED_PLAN"
BLUEPRINT_OBJECTIVES = "BLUEPRINT_OBJECTIVES"
VISUALIZATION_DEFAULT = "VISUALIZATION_DEFAULT"
ROUTING_POLICY = "ROUTING_POLICY"
TERM_MEANING = "TERM_MEANING"
METHOD_VERSION_CONTENT = "METHOD_VERSION_CONTENT"

CLASSES: tuple[tuple[str, str], ...] = (
    (CONCEPT_DIRECTION,
     "the same ontology concept, with opposite deterioration directions"),
    (ALIAS_TARGET,
     "the same alias pointing at different canonical concepts"),
    (PATTERN_OBJECTIVE,
     "the same question pattern, decomposed into different objectives"),
    (METHOD_FORMULA, "the same method, with a different formula"),
    (REGULATION_INTERPRETATION,
     "the same regulation, interpreted differently"),
    (THRESHOLD_SCOPE,
     "the same threshold, at a different scope or effective date"),
    (CASE_EXPECTED_PLAN,
     "the same teaching case, expecting a different plan"),
    (BLUEPRINT_OBJECTIVES,
     "the same blueprint, with incompatible mandatory objectives"),
    (VISUALIZATION_DEFAULT,
     "the same visualisation shape, with an incompatible default"),
    (ROUTING_POLICY, "the same routing policy, taking opposing routes"),
    (TERM_MEANING, "the same term, meaning different things"),
    (METHOD_VERSION_CONTENT,
     "the same method at the same version, with different content"),
)

CLASS_IDS: tuple[str, ...] = tuple(c for c, _ in CLASSES)

# --------------------------------------------------------- the resolutions
#
# §21's list. `ACCEPT_INCOMING` sits alongside `KEEP_LOCAL` rather than
# above it, and there is deliberately no "NEWER_WINS".

KEEP_LOCAL = "KEEP_LOCAL"
ACCEPT_INCOMING = "ACCEPT_INCOMING"
CREATE_NEW_VERSION = "CREATE_NEW_VERSION"
SCOPE_SPLIT = "SCOPE_SPLIT"
MERGE_MANUALLY = "MERGE_MANUALLY"
RETIRE_LOCAL = "RETIRE_LOCAL"
RETIRE_INCOMING = "RETIRE_INCOMING"
DEFER = "DEFER"

RESOLUTIONS: tuple[str, ...] = (
    KEEP_LOCAL, ACCEPT_INCOMING, CREATE_NEW_VERSION, SCOPE_SPLIT,
    MERGE_MANUALLY, RETIRE_LOCAL, RETIRE_INCOMING, DEFER,
)

#: The axes a scope split can be made on. §21's examples.
SPLIT_AXES: tuple[str, ...] = (
    "portfolio", "jurisdiction", "product", "language", "effective_date",
)

#: What a resolution touches downstream. §21 wants this shown before the
#: decision, not after.
DOWNSTREAM: tuple[str, ...] = (
    "teaching_cases", "methods", "blueprints", "regulatory_rules",
    "prompts", "routing", "evaluations", "releases",
)


@dataclass
class Side:
    """One installation's version of a thing."""

    origin: str                 # "local" or "incoming"
    item_id: str
    version: str = ""
    value: Any = None
    scope: str = ""
    jurisdiction: str = ""
    effective_from: str = ""
    provenance: str = ""
    evidence: str = ""
    approved_by: str = ""
    approved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Conflict:
    """One disagreement, and everything needed to settle it."""

    conflict_id: str = ""
    conflict_class: str = ""
    kind: str = ""
    local: Side | None = None
    incoming: Side | None = None
    detail: str = ""
    risk: str = "medium"
    recommended: str = DEFER
    recommendation_reason: str = ""
    downstream: dict[str, int] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)

    # once settled
    status: str = "OPEN"
    resolution: str = ""
    resolution_reason: str = ""
    resolved_by: str = ""
    resolved_at: str = ""
    split_axis: str = ""

    def __post_init__(self) -> None:
        self.conflict_id = self.conflict_id or f"cfl_{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "conflict_class": self.conflict_class,
            "kind": self.kind,
            "local": self.local.to_dict() if self.local else None,
            "incoming": self.incoming.to_dict() if self.incoming else None,
            "detail": self.detail, "risk": self.risk,
            "recommended": self.recommended,
            "recommendation_reason": self.recommendation_reason,
            "downstream": dict(self.downstream),
            "evaluation": dict(self.evaluation),
            "status": self.status, "resolution": self.resolution,
            "resolution_reason": self.resolution_reason,
            "resolved_by": self.resolved_by, "resolved_at": self.resolved_at,
            "split_axis": self.split_axis,
        }


class ConflictError(Exception):
    """A resolution that may not be recorded."""


# ---------------------------------------------------------------- detection


def _recommend(conflict_class: str, local: Side,
               incoming: Side) -> tuple[str, str]:
    """What the product suggests, and why. Never what it decides.

    A recommendation is a starting point for a person, and it says its
    reasoning so the person can disagree with the reasoning rather than
    with the conclusion.
    """
    if local.scope and incoming.scope and local.scope != incoming.scope:
        return SCOPE_SPLIT, (
            f"the two sides are about different populations - "
            f"{local.scope} and {incoming.scope} - so both can be true at "
            "once and neither has to lose")
    if (local.jurisdiction and incoming.jurisdiction
            and local.jurisdiction != incoming.jurisdiction):
        return SCOPE_SPLIT, (
            f"different jurisdictions ({local.jurisdiction} and "
            f"{incoming.jurisdiction}); a rule that applies in one is not "
            "overruled by a rule in the other")
    if (local.effective_from and incoming.effective_from
            and local.effective_from != incoming.effective_from):
        return CREATE_NEW_VERSION, (
            "the two sides have different effective dates, so this is a "
            "sequence rather than a contradiction")
    if conflict_class in (REGULATION_INTERPRETATION, THRESHOLD_SCOPE,
                          METHOD_FORMULA):
        return DEFER, (
            "a regulatory or calculation difference needs a person who "
            "knows both books; nothing here can tell which is right")
    if local.approved_by and not incoming.approved_by:
        return KEEP_LOCAL, (
            "the local side carries a named approval and the incoming side "
            "does not")
    return DEFER, (
        "both sides are somebody's considered judgement and nothing "
        "available distinguishes them")


def _risk(conflict_class: str) -> str:
    if conflict_class in (REGULATION_INTERPRETATION, METHOD_FORMULA,
                          THRESHOLD_SCOPE, METHOD_VERSION_CONTENT):
        return "high"
    if conflict_class in (CONCEPT_DIRECTION, ALIAS_TARGET, TERM_MEANING):
        return "high"
    return "medium"


def _conflict(conflict_class: str, kind: str, local: Side, incoming: Side,
              detail: str) -> Conflict:
    recommended, why = _recommend(conflict_class, local, incoming)
    return Conflict(
        conflict_class=conflict_class, kind=kind, local=local,
        incoming=incoming, detail=detail, risk=_risk(conflict_class),
        recommended=recommended, recommendation_reason=why)


def detect(local: dict[str, dict[str, Any]],
           incoming: dict[str, dict[str, Any]]) -> list[Conflict]:
    """Every disagreement between two sets of declared items.

    Both sides are `{kind: {item_id: payload}}`. Deterministic by design: a
    model asked whether two policies contradict each other will find a
    reading in which they do not.
    """
    found: list[Conflict] = []

    for kind, items in incoming.items():
        mine = local.get(kind) or {}
        for item_id, theirs in items.items():
            ours = mine.get(item_id)
            if ours is None:
                continue                    # an addition, not a conflict

            left = _side("local", item_id, ours)
            right = _side("incoming", item_id, theirs)
            conflict_class = _classify(kind, ours, theirs)
            if conflict_class is None:
                continue

            found.append(_conflict(
                conflict_class, kind, left, right,
                _describe(conflict_class, kind, item_id, ours, theirs)))
    return found


def _side(origin: str, item_id: str, payload: dict[str, Any]) -> Side:
    return Side(
        origin=origin, item_id=item_id,
        version=str(payload.get("version") or ""),
        value=payload.get("value"),
        scope=str(payload.get("scope") or ""),
        jurisdiction=str(payload.get("jurisdiction") or ""),
        effective_from=str(payload.get("effective_from") or ""),
        provenance=str(payload.get("provenance") or ""),
        evidence=str(payload.get("evidence") or ""),
        approved_by=str(payload.get("approved_by") or ""),
        approved_at=str(payload.get("approved_at") or ""),
    )


#: Which conflict class a disagreement in each kind of item belongs to.
_KIND_CLASS: dict[str, str] = {
    "concepts": CONCEPT_DIRECTION,
    "aliases": ALIAS_TARGET,
    "patterns": PATTERN_OBJECTIVE,
    "methods": METHOD_FORMULA,
    "regulatory": REGULATION_INTERPRETATION,
    "thresholds": THRESHOLD_SCOPE,
    "cases": CASE_EXPECTED_PLAN,
    "blueprints": BLUEPRINT_OBJECTIVES,
    "visualizations": VISUALIZATION_DEFAULT,
    "routing": ROUTING_POLICY,
    "terms": TERM_MEANING,
}


def _classify(kind: str, ours: dict[str, Any],
              theirs: dict[str, Any]) -> str | None:
    if ours.get("value") == theirs.get("value"):
        # Same content. A version disagreement over identical content is
        # still a conflict - two installations calling different things
        # "v2" is how a merge silently picks one.
        if (ours.get("version") and theirs.get("version")
                and ours["version"] != theirs["version"]):
            return METHOD_VERSION_CONTENT if kind == "methods" else None
        return None
    if kind == "methods" and ours.get("version") == theirs.get("version"):
        return METHOD_VERSION_CONTENT
    return _KIND_CLASS.get(kind, PATTERN_OBJECTIVE)


def _describe(conflict_class: str, kind: str, item_id: str,
              ours: dict[str, Any], theirs: dict[str, Any]) -> str:
    label = dict(CLASSES).get(conflict_class, conflict_class)
    return (f"{kind}/{item_id}: {label}. Local says "
            f"{ours.get('value')!r}; incoming says {theirs.get('value')!r}.")


# --------------------------------------------------------------- resolving


def resolve(conflict: Conflict, resolution: str, *, by: str, why: str,
            split_axis: str = "") -> Conflict:
    """Settle a conflict. A reason is required and a split names its axis.

    §21: "Require reason." Not decoration - a merge decision nobody
    explained is one nobody can revisit when the other installation asks
    why their policy stopped applying.
    """
    if resolution not in RESOLUTIONS:
        raise ConflictError(f"{resolution!r} is not a resolution")
    if not why.strip():
        raise ConflictError(
            "a resolution with no reason cannot be revisited when the other "
            "installation asks why their policy stopped applying")
    if not by.strip():
        raise ConflictError("a resolution nobody signed is not a decision")
    if resolution == SCOPE_SPLIT:
        if split_axis not in SPLIT_AXES:
            raise ConflictError(
                "a scope split has to name the axis it splits on; "
                f"one of {', '.join(SPLIT_AXES)}")
        conflict.split_axis = split_axis

    conflict.resolution = resolution
    conflict.resolution_reason = why
    conflict.resolved_by = by
    conflict.resolved_at = datetime.now(UTC).isoformat()
    conflict.status = "DEFERRED" if resolution == DEFER else "RESOLVED"
    return conflict


def unresolved(conflicts: list[Conflict]) -> list[Conflict]:
    return [c for c in conflicts if c.status == "OPEN"]


def blocking(conflicts: list[Conflict]) -> list[Conflict]:
    """Conflicts that must be settled before a merge may activate.

    A deferred high-risk conflict blocks. Deferring is a legitimate answer
    to "which of these is right" and is not a legitimate answer to "may
    this activate": a merge that activated with an unsettled regulatory
    contradiction would be running two contradictory rules at once.
    """
    return [c for c in conflicts
            if c.status == "OPEN"
            or (c.status == "DEFERRED" and c.risk == "high")]


def summary(conflicts: list[Conflict]) -> dict[str, Any]:
    by_class: dict[str, int] = {}
    by_resolution: dict[str, int] = {}
    for conflict in conflicts:
        by_class[conflict.conflict_class] = by_class.get(
            conflict.conflict_class, 0) + 1
        if conflict.resolution:
            by_resolution[conflict.resolution] = by_resolution.get(
                conflict.resolution, 0) + 1
    return {
        "total": len(conflicts),
        "open": len(unresolved(conflicts)),
        "blocking": len(blocking(conflicts)),
        "by_class": by_class,
        "by_resolution": by_resolution,
        "note": "no side wins for being newer. §21: a merge decision is a "
                "person's, with a reason.",
    }
