"""The scenario as a typed, immutable, hashable object.

Section 14.1 lists what a `ScenarioSpec` must carry and section 6.2 lists the
states it moves through. Both are here, and the two rules that make them worth
having are:

**A scenario is never edited.** `revise()` returns a new version with the old
one as its parent. Section 5.2: *"Each candidate scenario is an overlay over
the baseline. Editing a scenario ... must not repeatedly compound onto a
previously modified source dataframe."* An object that could be mutated in
place would make that rule a convention; one that cannot makes it a fact, and
it is also what lets a saved run reopen its own numbers rather than today's.

**Confirmation is bound to a hash, not to a conversation.** `digest()` is a
SHA-256 over the canonical form of everything that could change the answer:
the book, the release and its fingerprint, the cohort's membership hash, every
shock with its unit, the rule ordering, the selected methods and submodes, the
user's own assumptions, and the material warnings the reader was shown. Change
any of them and the hash moves, the confirmation is stale, and section 6.2's
"do not execute an old approval after a source refresh, book switch, cohort
edit, model replacement or ambiguity repair" stops being a promise and starts
being arithmetic.

What is deliberately NOT in the digest: the scenario's name, its id, its
timestamps, and the reader's original wording. Renaming a scenario does not
change what it computes, and a confirmation that expired because someone fixed
a typo in a label would train people to click through the preview.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import (
    CONFIRMATION_STALE,
    RULE_CONFLICT,
    ScenarioError,
    raise_for,
)

# ---- lifecycle ---------------------------------------------------------
#
# Section 6.2, verbatim in its ordering. The names say what is true, not what
# is happening: SCENARIO_RESOLVED means the assumptions and cohort are
# complete, and the specification is explicit that it does NOT mean ECL has
# been calculated.

DRAFT = "DRAFT"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
SCENARIO_RESOLVED = "SCENARIO_RESOLVED"
METHOD_SELECTION = "METHOD_SELECTION"
PREVIEW_READY = "PREVIEW_READY"
CONFIRMED = "CONFIRMED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
PARTIAL = "PARTIAL"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

STATES: tuple[str, ...] = (
    DRAFT, NEEDS_CLARIFICATION, SCENARIO_RESOLVED, METHOD_SELECTION,
    PREVIEW_READY, CONFIRMED, RUNNING, COMPLETED, PARTIAL, FAILED, CANCELLED,
)

TERMINAL: frozenset[str] = frozenset({COMPLETED, PARTIAL, FAILED, CANCELLED})

#: Where a state may go next. Cancellation is reachable from everywhere that
#: is not already finished, because a reader who changes their mind mid-preview
#: should not have to confirm a scenario in order to abandon it.
TRANSITIONS: dict[str, frozenset[str]] = {
    DRAFT: frozenset({NEEDS_CLARIFICATION, SCENARIO_RESOLVED, CANCELLED}),
    NEEDS_CLARIFICATION: frozenset({DRAFT, SCENARIO_RESOLVED, CANCELLED}),
    SCENARIO_RESOLVED: frozenset({METHOD_SELECTION, NEEDS_CLARIFICATION,
                                  DRAFT, CANCELLED}),
    METHOD_SELECTION: frozenset({PREVIEW_READY, SCENARIO_RESOLVED,
                                 NEEDS_CLARIFICATION, CANCELLED}),
    # Back to DRAFT from a preview is the revise path: a changed assumption
    # invalidates the preview, so there is no edge from PREVIEW_READY to
    # RUNNING that skips CONFIRMED.
    PREVIEW_READY: frozenset({CONFIRMED, DRAFT, METHOD_SELECTION, CANCELLED}),
    CONFIRMED: frozenset({RUNNING, DRAFT, CANCELLED}),
    RUNNING: frozenset({COMPLETED, PARTIAL, FAILED, CANCELLED}),
    COMPLETED: frozenset(),
    PARTIAL: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}


# ---- methods -----------------------------------------------------------

#: Section 10. Proportional parameter elasticity over the observed ECL.
DELTA = "delta"

#: Section 11. Not built in this pass; `methods.readiness()` says so.
ML = "ml"

#: Section 12. The reader's own impact assumption.
USER_DEFINED = "user_defined"

METHODS: tuple[str, ...] = (DELTA, ML, USER_DEFINED)

#: Section 10.1 versus 10.2. A submode is a mode of Delta, NOT a fourth
#: method -- the specification says so twice and oracle O05 turns on the two
#: giving different answers (2,160 proportional against 1,840 structural).
PROPORTIONAL = "proportional"
STRUCTURAL_EAD = "structural_ead"
DELTA_SUBMODES: tuple[str, ...] = (PROPORTIONAL, STRUCTURAL_EAD)


# ---- the pieces --------------------------------------------------------

@dataclass(frozen=True)
class Shock:
    """One typed move of one field over one scope.

    `origin` is the reader's clause that produced it and `derived_from` is the
    shock that induced it, if any. Section 5.2: *"Store the originating rule
    and mapping for every derived change"* -- and section 13.2 needs it, so
    that a macro instruction and the PD move it induced are one grouped
    intervention in the headline bridge rather than two additive bars.
    """

    field_id: str
    amount: un.Amount
    #: A normalized predicate over the cohort. `{}` means every row in it.
    where: dict[str, Any] = field(default_factory=dict)
    #: The reader's own clause, kept verbatim for the audit record.
    origin: str = ""
    #: The `field_id` of the shock this one was derived from, if it was.
    derived_from: str = ""
    #: `mappings.py` version that produced a derived shock. Empty when direct.
    mapping_version: str = ""

    def is_derived(self) -> bool:
        return bool(self.derived_from)

    def canonical(self) -> dict[str, Any]:
        """The part of this shock that could change a number."""
        return {
            "field": self.field_id,
            "operation": self.amount.operation,
            "value": str(self.amount.value),
            "where": _canonical(self.where),
            "derived_from": self.derived_from,
            "mapping_version": self.mapping_version,
        }


@dataclass(frozen=True)
class CohortRef:
    """A frozen membership, by reference and by hash.

    Section 6.1 wants the full membership or a stable server-side reference,
    plus counts, baseline totals and a cryptographic membership hash. The hash
    is what makes "these customers" mean the same rows on turn three as it did
    on turn one, and what makes a re-resolved segment a DIFFERENT cohort rather
    than a silent substitution.
    """

    cohort_id: str
    membership_hash: str
    grain: str
    entity_count: int
    #: Baseline totals, stored as strings so they survive JSON without
    #: becoming floats. `Decimal` everywhere, per `units`' header.
    baseline_ead: str = "0"
    baseline_ecl: str = "0"
    #: True when membership is the rows resolved BEFORE the scenario, which is
    #: the default; False only when the reader asked for a segment that
    #: re-evaluates after a rating or stage change.
    fixed: bool = True

    def canonical(self) -> dict[str, Any]:
        return {"membership_hash": self.membership_hash, "grain": self.grain,
                "entity_count": self.entity_count, "fixed": self.fixed}


@dataclass(frozen=True)
class SourceRef:
    """Which bytes this scenario was built against."""

    domain_id: str
    release_id: str
    release_fingerprint: str
    reporting_period: str

    def canonical(self) -> dict[str, Any]:
        return {"domain_id": self.domain_id, "release_id": self.release_id,
                "release_fingerprint": self.release_fingerprint,
                "reporting_period": self.reporting_period}


@dataclass(frozen=True)
class ScenarioSpec:
    """Everything that decides what a scenario computes, and its version.

    Frozen. `revise()` is the only way to change one, and it always produces a
    new version with this one as parent.
    """

    scenario_id: str
    version: int
    source: SourceRef
    cohort: CohortRef
    shocks: tuple[Shock, ...] = ()
    methods: tuple[str, ...] = (DELTA,)
    delta_submode: str = PROPORTIONAL
    #: Section 12. Normalized, and the reader's statement kept verbatim.
    user_assumption: dict[str, Any] = field(default_factory=dict)
    #: Section 8: stages frozen unless an approved rule says otherwise.
    stage_policy: str = "frozen"
    #: Section 9.1: the overlay is held fixed unless explicitly changed.
    overlay_policy: str = "fixed"
    #: Section 9.2: constant baseline FX unless FX stress was asked for.
    fx_policy: str = "constant"
    #: Declared caps and floors, each with the effect it had.
    bounds_policy: dict[str, Any] = field(default_factory=dict)
    #: Warnings the reader was shown. In the digest, because a confirmation
    #: given without seeing a warning is not a confirmation of this scenario.
    warnings: tuple[str, ...] = ()
    #: Mapping and model versions in force. Empty until P5/P7 supply them.
    artifact_versions: dict[str, str] = field(default_factory=dict)

    # -- identity, not arithmetic: excluded from the digest --
    name: str = ""
    parent_version: int = 0
    state: str = DRAFT
    original_clauses: tuple[str, ...] = ()
    confirmed_digest: str = ""

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ScenarioError(
                CONFIRMATION_STALE,
                f"{self.state!r} is not a scenario state. They are: "
                f"{', '.join(STATES)}.")
        unknown = [m for m in self.methods if m not in METHODS]
        if unknown:
            raise ScenarioError(
                CONFIRMATION_STALE,
                f"{unknown} are not methods. They are: {', '.join(METHODS)}.")
        if self.delta_submode not in DELTA_SUBMODES:
            raise ScenarioError(
                CONFIRMATION_STALE,
                f"{self.delta_submode!r} is not a Delta submode. They are: "
                f"{', '.join(DELTA_SUBMODES)}.")

    # -- the hash ---------------------------------------------------------

    def canonical(self) -> dict[str, Any]:
        """Everything that could change a number, in a stable order.

        Shocks are sorted by their own canonical form rather than left in
        authoring order, so two readers who typed the same two rules the other
        way round get the same hash. Rule ORDER is carried separately in
        `ordering()`, because order can change the answer and must therefore
        be in the digest as its own fact.
        """
        return {
            "source": self.source.canonical(),
            "cohort": self.cohort.canonical(),
            "shocks": sorted((s.canonical() for s in self.shocks),
                             key=lambda c: json.dumps(c, sort_keys=True)),
            "ordering": list(self.ordering()),
            "methods": sorted(self.methods),
            "delta_submode": self.delta_submode,
            "user_assumption": _canonical(self.user_assumption),
            "stage_policy": self.stage_policy,
            "overlay_policy": self.overlay_policy,
            "fx_policy": self.fx_policy,
            "bounds_policy": _canonical(self.bounds_policy),
            "warnings": sorted(self.warnings),
            "artifact_versions": _canonical(self.artifact_versions),
        }

    def ordering(self) -> tuple[str, ...]:
        """The sequence shocks are applied in, as authored.

        Section 5.2 gives a default sequence and says a reader-requested
        alternative ordering creates a new explicit revision. Carrying the
        order here, in the digest, is what makes that true.
        """
        return tuple(f"{s.field_id}:{s.amount.operation}" for s in self.shocks)

    def digest(self) -> str:
        """SHA-256 over the canonical form. The confirmation hash."""
        blob = json.dumps(self.canonical(), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def is_confirmed(self) -> bool:
        """Does the recorded approval still describe what would run?

        Both halves matter. A spec in CONFIRMED whose digest has moved is
        exactly the case section 6.2 forbids executing, and it is reachable
        without anyone acting in bad faith -- a source refresh does it.
        """
        return bool(self.confirmed_digest
                    and self.confirmed_digest == self.digest())

    def require_confirmed(self) -> None:
        if self.is_confirmed():
            return
        if not self.confirmed_digest:
            raise_for(CONFIRMATION_STALE,
                      "this scenario has not been confirmed. Show the "
                      "preview and ask before calculating anything.",
                      field_path="confirmed_digest")
        raise_for(CONFIRMATION_STALE,
                  "the confirmation was given for a different version of "
                  "this scenario. Something that changes the answer has "
                  "moved since; show the new preview and ask again.",
                  field_path="confirmed_digest",
                  confirmed=self.confirmed_digest, now=self.digest())

    # -- versioning -------------------------------------------------------

    def revise(self, **changes: Any) -> ScenarioSpec:
        """A new version, with this one as its parent.

        Any change drops the confirmation, without the caller having to
        remember to: a revised scenario is by definition not the one that was
        approved.
        """
        changes.pop("version", None)
        changes.pop("parent_version", None)
        changes.pop("confirmed_digest", None)
        return replace(self, version=self.version + 1,
                       parent_version=self.version, confirmed_digest="",
                       **changes)

    def confirm(self) -> ScenarioSpec:
        """Bind the approval to what is on screen right now."""
        if self.state != PREVIEW_READY:
            raise_for(CONFIRMATION_STALE,
                      f"a scenario is confirmed from {PREVIEW_READY}, not "
                      f"from {self.state}. Reading the sensitivities or "
                      f"saying 'use ML' is not confirmation of an unseen "
                      f"calculation.",
                      field_path="state")
        return replace(self, state=CONFIRMED, confirmed_digest=self.digest())

    def advance(self, to: str) -> ScenarioSpec:
        """Move to the next state, or say why that is not a move."""
        if to not in STATES:
            raise_for(CONFIRMATION_STALE, f"{to!r} is not a scenario state.",
                      field_path="state")
        if to not in TRANSITIONS[self.state]:
            allowed = ", ".join(sorted(TRANSITIONS[self.state])) or "nothing"
            raise_for(CONFIRMATION_STALE,
                      f"a scenario in {self.state} can go to {allowed}, not "
                      f"to {to}.",
                      field_path="state")
        # Leaving CONFIRMED for anything but RUNNING drops the approval.
        drop = self.state == CONFIRMED and to != RUNNING
        return replace(self, state=to,
                       confirmed_digest="" if drop else self.confirmed_digest)

    # -- what the preview and the audit record read -----------------------

    def direct_shocks(self) -> tuple[Shock, ...]:
        """Shocks the reader stated, as opposed to ones a mapping induced."""
        return tuple(s for s in self.shocks if not s.is_derived())

    def derived_shocks(self) -> tuple[Shock, ...]:
        return tuple(s for s in self.shocks if s.is_derived())

    def conflicts(self) -> tuple[tuple[Shock, Shock], ...]:
        """Pairs that move the same field with no declared composition.

        Section 5.2: overlapping rules on one field are a conflict *unless*
        their order or composition is explicit. This finds the pairs; it does
        not resolve them, because "more specific wins" is exactly the silent
        assumption the specification forbids. `rules.py` turns a pair into the
        question the reader answers.

        A derived shock and the direct shock it came from are not a conflict
        with each other -- one caused the other. A derived shock and an
        unrelated direct shock on the same field are.
        """
        out: list[tuple[Shock, Shock]] = []
        for i, left in enumerate(self.shocks):
            for right in self.shocks[i + 1:]:
                if left.field_id != right.field_id:
                    continue
                if (left.derived_from == right.field_id
                        or right.derived_from == left.field_id):
                    continue
                if not _may_overlap(left.where, right.where):
                    continue
                out.append((left, right))
        return tuple(out)

    def require_no_conflicts(
            self, *,
            acknowledged: Sequence[tuple[Shock, Shock]] = ()) -> None:
        """Raise on the first overlapping pair the reader has not been shown.

        `acknowledged` is the pairs already surfaced as a question -- the
        preview shows overlaps with their counts and amounts and asks which
        composition applies, and it could not do that if merely having an
        overlap stopped it being built. An acknowledged pair is still
        unresolved; it is just no longer silent, which is the whole of what
        section 5.2 forbids.
        """
        seen = {_pair_key(left, right) for left, right in acknowledged}
        pairs = tuple(p for p in self.conflicts()
                      if _pair_key(*p) not in seen)
        if not pairs:
            return
        left, right = pairs[0]
        raise_for(
            RULE_CONFLICT,
            f"two rules move {left.field_id} on rows that overlap: "
            f"{left.origin or left.amount.describe()!r} and "
            f"{right.origin or right.amount.describe()!r}. Which applies -- "
            f"does the second replace the first, compose on the value the "
            f"first produced, or apply only to the rows the first did not "
            f"cover?",
            field_path="shocks",
            field_id=left.field_id, pairs=len(pairs))


def _pair_key(left: Shock, right: Shock) -> str:
    """A stable name for one overlapping pair, by value rather than identity.

    Canonical form, so a pair acknowledged before a round trip through JSON
    is the same pair afterwards.
    """
    return json.dumps([left.canonical(), right.canonical()], sort_keys=True)


def _may_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Could these two predicates select a row in common?

    Conservative on purpose. An empty predicate is every row, so it overlaps
    everything. Two predicates that constrain the same key to different values
    cannot overlap; anything else is treated as if it might, because a missed
    conflict publishes a wrong number and a spurious one costs a question.
    """
    if not left or not right:
        return True
    for key in left.keys() & right.keys():
        if left[key] != right[key]:
            return False
    return True


def from_canonical(canonical: Mapping[str, Any], *, scenario_id: str,
                   version: int, name: str = "", state: str = CONFIRMED,
                   confirmed_digest: str = "", cohort_id: str = "",
                   cohort_baseline_ead: str = "0",
                   cohort_baseline_ecl: str = "0",
                   original_clauses: Sequence[str] = ()) -> ScenarioSpec:
    """Rebuild a spec from the canonical form a thread stored.

    WHY THIS EXISTS, AND WHY IT IS NOT A CONVENIENCE.

    `thread.state_of` decides ACTIVE or INVALIDATED by comparing two values
    that were BOTH written at the same moment -- `confirmed_digest` and
    `digest_now`. That is a fine staleness check and a poor authorisation
    check: it proves the two strings agree, not that either describes the
    scenario stored beside them. Anything that edited the stored canonical
    form would leave both digests untouched and still read as ACTIVE.

    So the execution path does not trust them. It rebuilds the spec from the
    canonical form itself and calls `require_confirmed()`, which recomputes
    the digest from the rules that are actually about to run. A canonical
    form and a confirmation that disagree is then a refusal, not a run.

    Everything outside the digest is passed in rather than inferred, because
    it was stored separately: the identity fields, and the cohort's id and
    baselines, which `CohortRef.canonical` deliberately leaves out.

    The shocks are returned to their AUTHORED order, from `ordering`, rather
    than left in the sorted order the digest uses. Order can change the
    answer, and a spec rebuilt with the rules in a different sequence would
    be a different scenario that happened to hash the same.
    """
    if not isinstance(canonical, Mapping):
        raise ScenarioError(
            CONFIRMATION_STALE,
            "the stored scenario has no canonical form, so what was "
            "confirmed cannot be reconstructed. Nothing was run.")
    src = dict(canonical.get("source") or {})
    coh = dict(canonical.get("cohort") or {})
    shocks = [_shock_from_canonical(raw)
              for raw in (canonical.get("shocks") or [])]
    shocks = _in_authored_order(shocks, canonical.get("ordering") or [])
    return ScenarioSpec(
        scenario_id=str(scenario_id),
        version=int(version),
        source=SourceRef(
            domain_id=str(src.get("domain_id", "")),
            release_id=str(src.get("release_id", "")),
            release_fingerprint=str(src.get("release_fingerprint", "")),
            reporting_period=str(src.get("reporting_period", ""))),
        cohort=CohortRef(
            cohort_id=str(cohort_id),
            membership_hash=str(coh.get("membership_hash", "")),
            grain=str(coh.get("grain", "")),
            entity_count=int(coh.get("entity_count", 0) or 0),
            baseline_ead=str(cohort_baseline_ead),
            baseline_ecl=str(cohort_baseline_ecl),
            fixed=bool(coh.get("fixed", True))),
        shocks=tuple(shocks),
        methods=tuple(str(m) for m in (canonical.get("methods") or (DELTA,))),
        delta_submode=str(canonical.get("delta_submode") or PROPORTIONAL),
        user_assumption=dict(canonical.get("user_assumption") or {}),
        stage_policy=str(canonical.get("stage_policy") or "frozen"),
        overlay_policy=str(canonical.get("overlay_policy") or "fixed"),
        fx_policy=str(canonical.get("fx_policy") or "constant"),
        bounds_policy=dict(canonical.get("bounds_policy") or {}),
        warnings=tuple(str(w) for w in (canonical.get("warnings") or ())),
        artifact_versions=dict(canonical.get("artifact_versions") or {}),
        name=str(name), state=str(state),
        original_clauses=tuple(str(c) for c in original_clauses),
        confirmed_digest=str(confirmed_digest))


def _shock_from_canonical(raw: Mapping[str, Any]) -> Shock:
    """One shock, back from its digest form.

    `origin` is not reconstructed and deliberately is not: it is the reader's
    own sentence, it sits outside the digest, and inventing one here would
    put words in their mouth in the audit record. The clauses are carried
    whole on the spec instead.
    """
    if not isinstance(raw, Mapping):
        raise ScenarioError(
            CONFIRMATION_STALE,
            "a stored rule is not an object, so the confirmed scenario "
            "cannot be reconstructed. Nothing was run.")
    return Shock(
        field_id=str(raw.get("field", "")),
        amount=un.parse(raw.get("value"), str(raw.get("operation", ""))),
        where=dict(raw.get("where") or {}),
        derived_from=str(raw.get("derived_from", "")),
        mapping_version=str(raw.get("mapping_version", "")))


def _in_authored_order(shocks: Sequence[Shock],
                       ordering: Sequence[Any]) -> list[Shock]:
    """The shocks, back in the sequence `ordering` records.

    A rule named in `ordering` but absent from `shocks`, or the reverse, is a
    stored scenario that contradicts itself. It is refused rather than
    reordered on a best effort: the sequence is in the digest because it
    changes the answer.
    """
    wanted = [str(key) for key in ordering]
    if not wanted:
        return list(shocks)
    remaining = list(shocks)
    out: list[Shock] = []
    for key in wanted:
        match = next((s for s in remaining
                      if f"{s.field_id}:{s.amount.operation}" == key), None)
        if match is None:
            raise ScenarioError(
                CONFIRMATION_STALE,
                f"the stored scenario applies {key!r} in its recorded order "
                f"but carries no such rule, so the sequence that was "
                f"confirmed cannot be reproduced. Nothing was run.")
        remaining.remove(match)
        out.append(match)
    if remaining:
        raise ScenarioError(
            CONFIRMATION_STALE,
            f"the stored scenario carries {len(remaining)} rule(s) that its "
            f"recorded order does not place. Rule order changes the answer, "
            f"so nothing was run.")
    return out


def _canonical(value: Any) -> Any:
    """JSON-safe and order-stable, with Decimal kept exact as a string."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, un.Amount):
        return {"operation": value.operation, "value": str(value.value)}
    return value


__all__ = [
    "CANCELLED", "COMPLETED", "CONFIRMED", "CohortRef", "DELTA",
    "DELTA_SUBMODES", "DRAFT", "FAILED", "METHODS", "METHOD_SELECTION", "ML",
    "NEEDS_CLARIFICATION", "PARTIAL", "PREVIEW_READY", "PROPORTIONAL",
    "RUNNING", "SCENARIO_RESOLVED", "STATES", "STRUCTURAL_EAD",
    "ScenarioSpec", "Shock", "SourceRef", "TERMINAL", "TRANSITIONS",
    "USER_DEFINED", "from_canonical",
]
