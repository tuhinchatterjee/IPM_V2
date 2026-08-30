"""
Two-Brain merge. §21, §22.

`conflicts.py` finds where two installations disagree and records what a
person decided about each disagreement. This module is the step after: it
takes those decisions and *produces the third Brain* — the merged item set,
the decision record that explains every item in it, and a manifest that
names both parents.

Why this is a separate module
------------------------------
Detection and resolution are judgements about two things. A merge is the
construction of a third thing, and it has its own refusals — most of them
about what a merge is *not* allowed to decide on its own.

What a merge may not do
------------------------
**It may not settle anything itself.** Every conflict `conflicts.blocking()`
returns must already be resolved. A merge that quietly picked a side for
the leftovers would produce a Brain whose behaviour nobody chose.

**It may not author content.** `CREATE_NEW_VERSION` and `MERGE_MANUALLY`
are decisions to write something new. This module will not write it — it
refuses until the authored body is supplied. Synthesising "the merge of two
ECL definitions" is exactly the operation that produces a definition
neither institution uses.

**It may not carry either parent's scores.** The merged Brain has never
been evaluated. Inheriting the better parent's numbers would make a
regression look like an improvement, and the merge is where two sets of
learning first interact — the one place where measuring afresh matters
most. `evaluation_metrics` comes out empty, and the limitation is written
into the manifest so the receiver reads it rather than inferring it.

**It may not activate.** The output is a package. Installing and activating
it goes through the same quarantine, Lift Lab and approval path as any
imported Brain, because that is what it now is.

What DEFER means here
----------------------
A deferred conflict does not fall back to local. The item is left out of
the merged Brain entirely and reported as dormant. Falling back to local
would mean "we could not decide, so we chose local" while telling the
reviewer nothing was chosen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.brain import conflicts as conflicts_mod
from backend.brain import pack

MERGE_SCHEMA_VERSION = "1.0.0"


class MergeError(Exception):
    """A merge that may not be performed as asked."""


# ---------------------------------------------------------------- outcomes

#: What happened to one item. Every item in the merged Brain has exactly
#: one of these, and every one of them names the side it came from, so
#: "why is this rule here" is answerable without re-running the merge.
CARRIED_LOCAL = "CARRIED_LOCAL"
CARRIED_INCOMING = "CARRIED_INCOMING"
TAKEN_LOCAL = "TAKEN_LOCAL"
TAKEN_INCOMING = "TAKEN_INCOMING"
AUTHORED_NEW_VERSION = "AUTHORED_NEW_VERSION"
AUTHORED_MANUAL_MERGE = "AUTHORED_MANUAL_MERGE"
SCOPED_BOTH = "SCOPED_BOTH"
RETIRED_LOCAL = "RETIRED_LOCAL"
RETIRED_INCOMING = "RETIRED_INCOMING"
DORMANT = "DORMANT"

OUTCOMES: tuple[str, ...] = (
    CARRIED_LOCAL, CARRIED_INCOMING, TAKEN_LOCAL, TAKEN_INCOMING,
    AUTHORED_NEW_VERSION, AUTHORED_MANUAL_MERGE, SCOPED_BOTH,
    RETIRED_LOCAL, RETIRED_INCOMING, DORMANT,
)

#: The outcome each resolution produces. Kept as data so the mapping can be
#: read in one place rather than reconstructed from a chain of branches.
_OUTCOME: dict[str, str] = {
    conflicts_mod.KEEP_LOCAL: TAKEN_LOCAL,
    conflicts_mod.ACCEPT_INCOMING: TAKEN_INCOMING,
    conflicts_mod.CREATE_NEW_VERSION: AUTHORED_NEW_VERSION,
    conflicts_mod.MERGE_MANUALLY: AUTHORED_MANUAL_MERGE,
    conflicts_mod.SCOPE_SPLIT: SCOPED_BOTH,
    # RETIRE_LOCAL retires the local item, so the incoming one is what
    # survives — and vice versa. Naming the outcome after what was retired
    # rather than after what survived is the reading that matches the
    # resolution's own name in the review UI.
    conflicts_mod.RETIRE_LOCAL: RETIRED_LOCAL,
    conflicts_mod.RETIRE_INCOMING: RETIRED_INCOMING,
    conflicts_mod.DEFER: DORMANT,
}

#: Resolutions that are a decision to write something new. The merge will
#: not write it; it refuses until a person supplies the body.
NEEDS_AUTHORING: frozenset[str] = frozenset({
    conflicts_mod.CREATE_NEW_VERSION,
    conflicts_mod.MERGE_MANUALLY,
})


@dataclass
class Decision:
    """One item's fate, and who decided it."""

    kind: str
    item_id: str
    outcome: str
    origin: str = ""            # "local", "incoming", "both", or "" if none
    conflict_id: str = ""
    conflict_class: str = ""
    resolution: str = ""
    reason: str = ""
    decided_by: str = ""
    split_axis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Merged:
    """The third Brain, before it is written to a package."""

    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)
    local_brain_id: str = ""
    incoming_brain_id: str = ""
    merged_at: str = ""
    merged_by: str = ""

    @property
    def dormant(self) -> list[Decision]:
        return [d for d in self.decisions if d.outcome == DORMANT]

    @property
    def authored(self) -> list[Decision]:
        return [d for d in self.decisions
                if d.outcome in (AUTHORED_NEW_VERSION, AUTHORED_MANUAL_MERGE)]

    def counts(self) -> dict[str, int]:
        by_outcome: dict[str, int] = {}
        for decision in self.decisions:
            by_outcome[decision.outcome] = by_outcome.get(
                decision.outcome, 0) + 1
        return by_outcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "merge_schema_version": MERGE_SCHEMA_VERSION,
            "local_brain_id": self.local_brain_id,
            "incoming_brain_id": self.incoming_brain_id,
            "merged_at": self.merged_at,
            "merged_by": self.merged_by,
            "kinds": {k: len(v) for k, v in sorted(self.items.items())},
            "items_total": sum(len(v) for v in self.items.values()),
            "by_outcome": self.counts(),
            "dormant": [d.to_dict() for d in self.dormant],
            "note": (
                "This Brain has never been evaluated. It carries neither "
                "parent's scores, because a merge is the first time two "
                "sets of learning interact and that is the one place where "
                "an inherited number would hide a regression."),
        }


# ------------------------------------------------------------------ merge


def _authoring_gaps(settled: list[conflicts_mod.Conflict],
                    authored: dict[str, dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    for conflict in settled:
        if conflict.resolution not in NEEDS_AUTHORING:
            continue
        body = authored.get(conflict.conflict_id)
        if not isinstance(body, dict) or not body:
            label = dict(conflicts_mod.CLASSES).get(
                conflict.conflict_class, conflict.conflict_class)
            gaps.append(
                f"{conflict.conflict_id} ({conflict.kind}/"
                f"{conflict.local.item_id if conflict.local else '?'}, "
                f"{label}) was resolved {conflict.resolution}, which is a "
                "decision to write something new. No body was supplied.")
    return gaps


def merge(local: dict[str, dict[str, Any]],
          incoming: dict[str, dict[str, Any]],
          settled: list[conflicts_mod.Conflict],
          *,
          by: str,
          authored: dict[str, dict[str, Any]] | None = None,
          local_brain_id: str = "",
          incoming_brain_id: str = "") -> Merged:
    """Build the third item set from two, given the settled conflicts.

    `local` and `incoming` are `{kind: {item_id: payload}}` — the same shape
    `conflicts.detect()` takes, so the maps that produced the conflicts are
    the maps that get merged. No re-derivation, and no chance of merging a
    different set from the one somebody reviewed.
    """
    authored = dict(authored or {})
    if not by.strip():
        raise MergeError("a merge nobody signed is not a decision")

    blocking = conflicts_mod.blocking(settled)
    if blocking:
        raise MergeError(
            f"{len(blocking)} conflict(s) are still open or deferred at high "
            "risk. A merge that picked a side for them would produce a Brain "
            "whose behaviour nobody chose: "
            + ", ".join(c.conflict_id for c in blocking[:5]))

    gaps = _authoring_gaps(settled, authored)
    if gaps:
        raise MergeError(
            "this merge cannot write the content it was asked to write. "
            "Synthesising the merge of two definitions produces a definition "
            "neither institution uses. " + " ".join(gaps))

    result = Merged(
        local_brain_id=local_brain_id, incoming_brain_id=incoming_brain_id,
        merged_at=datetime.now(UTC).isoformat(), merged_by=by)

    #: conflicts by (kind, item_id), so the item loop can find its decision.
    settled_by_item: dict[tuple[str, str], conflicts_mod.Conflict] = {}
    for conflict in settled:
        side = conflict.local or conflict.incoming
        if side is not None:
            settled_by_item[(conflict.kind, side.item_id)] = conflict

    for kind in sorted(set(local) | set(incoming)):
        mine = local.get(kind) or {}
        theirs = incoming.get(kind) or {}
        merged_kind: dict[str, Any] = {}

        for item_id in sorted(set(mine) | set(theirs)):
            conflict = settled_by_item.get((kind, item_id))
            if conflict is None:
                # Uncontested: present on one side, or identical on both.
                in_local, in_incoming = item_id in mine, item_id in theirs
                merged_kind[item_id] = (mine if in_local else theirs)[item_id]
                result.decisions.append(Decision(
                    kind=kind, item_id=item_id,
                    outcome=CARRIED_LOCAL if in_local else CARRIED_INCOMING,
                    origin="both" if in_local and in_incoming else (
                        "local" if in_local else "incoming"),
                    reason="no disagreement between the two Brains"))
                continue

            decision, payload = _settle(
                kind, item_id, conflict, mine, theirs, authored)
            if payload is not None:
                merged_kind[item_id] = payload
            result.decisions.append(decision)

        if merged_kind:
            result.items[kind] = merged_kind

    return result


def _settle(kind: str, item_id: str, conflict: conflicts_mod.Conflict,
            mine: dict[str, Any], theirs: dict[str, Any],
            authored: dict[str, dict[str, Any]],
            ) -> tuple[Decision, dict[str, Any] | None]:
    """Apply one settled conflict to one item. Returns the item or None."""
    resolution = conflict.resolution
    outcome = _OUTCOME.get(resolution, DORMANT)
    decision = Decision(
        kind=kind, item_id=item_id, outcome=outcome,
        conflict_id=conflict.conflict_id,
        conflict_class=conflict.conflict_class,
        resolution=resolution, reason=conflict.resolution_reason,
        decided_by=conflict.resolved_by, split_axis=conflict.split_axis)

    if outcome in (TAKEN_LOCAL, RETIRED_INCOMING):
        decision.origin = "local"
        return decision, mine.get(item_id)
    if outcome in (TAKEN_INCOMING, RETIRED_LOCAL):
        decision.origin = "incoming"
        return decision, theirs.get(item_id)
    if outcome in (AUTHORED_NEW_VERSION, AUTHORED_MANUAL_MERGE):
        decision.origin = "both"
        return decision, dict(authored[conflict.conflict_id])
    if outcome == SCOPED_BOTH:
        decision.origin = "both"
        return decision, _scoped(conflict, mine.get(item_id),
                                 theirs.get(item_id))
    # DORMANT. Deliberately absent from the merged Brain rather than
    # silently defaulting to local.
    decision.origin = ""
    return decision, None


def _scoped(conflict: conflicts_mod.Conflict, ours: dict[str, Any] | None,
            theirs: dict[str, Any] | None) -> dict[str, Any]:
    """A scope split keeps both, each narrowed on the axis that was named.

    Nothing here invents the boundary. The axis came from the person who
    resolved the conflict, and each side keeps the value it already carried
    on that axis; the split records that the item is now conditional rather
    than universal, which is the thing a reader has to know.
    """
    axis = conflict.split_axis
    return {
        "scoped": True,
        "split_axis": axis,
        "branches": [
            {"origin": "local", "axis_value": _axis_value(conflict.local,
                                                          axis),
             "value": (ours or {}).get("value")},
            {"origin": "incoming", "axis_value": _axis_value(
                conflict.incoming, axis),
             "value": (theirs or {}).get("value")},
        ],
        "note": (f"split on {axis} by {conflict.resolved_by}: "
                 f"{conflict.resolution_reason}"),
    }


def _axis_value(side: conflicts_mod.Side | None, axis: str) -> str:
    if side is None:
        return ""
    return str(getattr(side, axis, "") or getattr(side, "scope", "") or "")


# ---------------------------------------------------------------- packaging


#: What the merged Brain is known not to have. Written into the manifest so
#: the receiver reads it rather than having to infer it from an empty
#: metrics block.
MERGE_LIMITATIONS: tuple[str, ...] = (
    "This Brain was produced by merging two Brains and has not been "
    "evaluated since. It carries no inherited scores.",
    "Measure it against your own baseline in the Lift Lab before "
    "activating any part of it.",
)


def manifest_for(merged: Merged, *, brain_name: str, brain_version: str,
                 local_manifest: pack.Manifest,
                 incoming_manifest: pack.Manifest,
                 created_by: str) -> pack.Manifest:
    """The third Brain's manifest: both parents named, no inherited scores."""
    cases = merged.items.get("cases") or {}
    return pack.Manifest(
        brain_id=f"brain_{uuid.uuid4().hex[:12]}",
        brain_name=brain_name,
        brain_version=brain_version,
        package_kind=pack.BRAIN_PACK,
        created_at=merged.merged_at,
        created_by=created_by,
        source_instance_id=local_manifest.source_instance_id,
        source_build_sha=local_manifest.source_build_sha,
        app_version=local_manifest.app_version,
        ontology_version=local_manifest.ontology_version,
        blueprint_version=local_manifest.blueprint_version,
        judgment_policy_version=local_manifest.judgment_policy_version,
        visualization_grammar_version=(
            local_manifest.visualization_grammar_version),
        routing_policy_version=local_manifest.routing_policy_version,
        supported_modules=tuple(sorted(
            set(local_manifest.supported_modules)
            & set(incoming_manifest.supported_modules))),
        required_modules=tuple(sorted(
            set(local_manifest.required_modules)
            | set(incoming_manifest.required_modules))),
        minimum_app_version=max(local_manifest.minimum_app_version,
                                incoming_manifest.minimum_app_version),
        supported_languages=tuple(sorted(
            set(local_manifest.supported_languages)
            & set(incoming_manifest.supported_languages))) or ("en",),
        case_counts={"merged": len(cases)},
        # Deliberately empty. See MERGE_LIMITATIONS.
        evaluation_metrics={},
        known_limitations=tuple(
            dict.fromkeys(
                local_manifest.known_limitations
                + incoming_manifest.known_limitations
                + MERGE_LIMITATIONS)),
        parent_brain_ids=(local_manifest.brain_id, incoming_manifest.brain_id),
        merge_history=(
            local_manifest.merge_history
            + incoming_manifest.merge_history
            + ({
                "merged_at": merged.merged_at,
                "merged_by": merged.merged_by,
                "local_brain_id": local_manifest.brain_id,
                "incoming_brain_id": incoming_manifest.brain_id,
                "by_outcome": merged.counts(),
                "dormant": len(merged.dormant),
            },)),
    )


#: Which merged kind is written to which path in the package. A kind with
#: nowhere to go is refused rather than dropped: silently losing a whole
#: category of learning is the failure that looks like success.
KIND_PATHS: dict[str, str] = {
    "cases": "teaching/cases.jsonl",
    "blueprints": "blueprints/blueprints.jsonl",
    "methods": "methods/methods.jsonl",
    "regulatory": "regulatory/requirements.jsonl",
    "concepts": "ontology/concepts.json",
    "aliases": "ontology/aliases.json",
    "terms": "ontology/terms.json",
    "patterns": "teaching/patterns.json",
    "thresholds": "judgment/thresholds.json",
    "visualizations": "visualization/grammar.json",
    "routing": "routing/policy.json",
}

#: Paths written as one JSON object keyed by item id rather than as rows.
_OBJECT_PATHS: frozenset[str] = frozenset({
    "ontology/concepts.json", "ontology/aliases.json", "ontology/terms.json",
    "teaching/patterns.json", "judgment/thresholds.json",
    "visualization/grammar.json", "routing/policy.json",
})


def package(merged: Merged, manifest: pack.Manifest) -> pack.Contents:
    """Write the merged Brain as package contents.

    The decision record travels with it. A merged Brain whose provenance
    stayed behind on the machine that made it is one nobody downstream can
    audit, and the whole point of naming both parents is that somebody can.
    """
    unknown = set(merged.items) - set(KIND_PATHS)
    if unknown:
        raise MergeError(
            "no package path is defined for merged item kind(s): "
            + ", ".join(sorted(unknown))
            + ". Writing the package without them would silently lose a "
              "whole category of learning.")

    contents = pack.Contents()
    for kind, items in sorted(merged.items.items()):
        path = KIND_PATHS[kind]
        if path in _OBJECT_PATHS:
            contents.add(path, items)
        else:
            contents.add_jsonl(path, [
                {"item_id": item_id, **(payload if isinstance(payload, dict)
                                        else {"value": payload})}
                for item_id, payload in sorted(items.items())])

    contents.add("provenance/merge.json", merged.to_dict())
    contents.add_jsonl("provenance/decisions.jsonl",
                       [d.to_dict() for d in merged.decisions])
    contents.add("evaluations/summary.json", {
        "evaluated": False,
        "reason": ("a merged Brain has never been run. Measure it against "
                   "your own baseline before activating any part of it."),
        "inherited_from_parents": False,
    })
    problems = pack.validate_manifest(manifest)
    if problems:
        raise MergeError("the merged manifest is not valid: "
                         + "; ".join(problems))
    return contents
