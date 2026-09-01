"""
What a teaching case is allowed to be, and what it takes to get there. §5, §6.

The one decision this module exists to make
-------------------------------------------
Whether a case may be retrieved into a live prompt. Everything else here —
the statuses, the transitions, the staleness axes — is the reasoning behind
that one answer, written down so it is auditable instead of implied.

Two cases may be retrieved: APPROVED, which means a named person read it and
signed for it, and SYSTEM_VALIDATED, which means it was derived from a
deterministic contract and re-derives correctly today. The second is narrower
than it looks: §5 permits it only "where explicitly governed", so it is off
unless a caller turns it on, and turning it on is a decision somebody makes
rather than a default they inherit.

Why unknown counts as stale
---------------------------
A case records the ontology, method and schema versions it was validated
against. When one of those has moved, the case is STALE. When the case never
recorded the version at all, it is *also* stale — not "assumed current".

This is the same shape as the assurance ceiling in `backend/agentic/
consistency.py`, and for the same reason: the natural implementation ranks the
unrecognised value as the weakest, which makes it compare as already-safe and
pass through untouched. A case with no recorded ontology version is precisely
the case most likely to predate the ontology that governs it now.

Nothing here trains anything
----------------------------
An approved case becomes retrievable — a worked example a planner may be shown
alongside a question. No weight changes. §1 is explicit and so is this module:
"training" in this codebase means governed application-level teaching, and the
word is not used loosely anywhere it could be read as fine-tuning.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

STATUS_VERSION = "1.0.0"

# ----------------------------------------------------------------- statuses
#: Authored, incomplete, or being worked on. Never retrieved.
DRAFT = "DRAFT"
#: Passed the deterministic validators — schema, family rules, plan validity.
#: A machine agreed with itself. That is not review, and the name says so.
AUTO_VALIDATED = "AUTO_VALIDATED"
#: A validator declined to vouch for it: a generated variant that changed
#: meaning, an ambiguity nobody adjudicated, a plan that would not compile.
SME_REVIEW_REQUIRED = "SME_REVIEW_REQUIRED"
#: A named person READ it and recorded what they thought — and did not sign
#: for production. §16's HUMAN_REVIEWED.
#:
#: The gap between reading and signing is real work, and collapsing it was
#: costing the review workflow its most useful state: a reviewer who has
#: looked at forty cases and approved eight has thirty-two they have genuinely
#: assessed, and before this they were indistinguishable from the ones nobody
#: had opened. It is NOT retrievable: reviewed is not approved.
HUMAN_REVIEWED = "HUMAN_REVIEWED"
#: A named person read it and signed for it. Retrievable.
APPROVED = "APPROVED"
#: §16 calls this HUMAN_APPROVED, which is what APPROVED has always meant —
#: `may_approve` refuses any approval without a named human behind it. The
#: alias exists so the brief's vocabulary resolves in code and in the API,
#: without a migration that rewrites the stored value on 2,453 rows and every
#: audit event that references it.
HUMAN_APPROVED = APPROVED
#: Reviewed and refused. Kept, not deleted: a rejected case records a reading
#: somebody decided was wrong, which is worth as much as one they accepted.
REJECTED = "REJECTED"
#: Deliberately withdrawn. Terminal.
RETIRED = "RETIRED"
#: Something it was validated against has changed underneath it.
STALE = "STALE"
#: Derived from a deterministic contract and re-derived today (§6).
SYSTEM_VALIDATED = "SYSTEM_VALIDATED"
#: §16's name for the same thing: validated against a deterministic
#: reference rather than by a person. Aliased rather than renamed for the
#: reason above.
SYSTEM_REFERENCE_VALIDATED = SYSTEM_VALIDATED

STATUSES: tuple[str, ...] = (
    DRAFT, AUTO_VALIDATED, SME_REVIEW_REQUIRED, HUMAN_REVIEWED, APPROVED,
    REJECTED, RETIRED, STALE, SYSTEM_VALIDATED,
)

#: The statuses production retrieval may draw from.
#:
#: §16: "Default production retrieval: HUMAN_APPROVED." SYSTEM_VALIDATED is
#: in this set and GATED — `retrievable` refuses it unless an administrator
#: has explicitly governed it on, and the surfaces label it when they do.
#: AUTO_VALIDATED is deliberately absent: a machine agreeing with itself is
#: not a review, and all 2,453 of the library's cases are in that state.
RETRIEVABLE: frozenset[str] = frozenset({APPROVED, SYSTEM_VALIDATED})

#: What each status means, in one sentence, for every surface that shows one.
#: Written here so the Studio, the API and the review workbench cannot each
#: invent their own gloss.
STATUS_MEANS: dict[str, str] = {
    DRAFT: "Authored and incomplete. Never retrieved.",
    AUTO_VALIDATED: "Passed the deterministic validators. A machine agreed "
                    "with itself, which is not review — and not retrievable.",
    SME_REVIEW_REQUIRED: "A validator declined to vouch for it. A person has "
                         "to look.",
    HUMAN_REVIEWED: "A named person read it and recorded an assessment, and "
                    "has not signed for production. Not retrievable.",
    APPROVED: "A named person read it and signed for it. Retrievable by "
              "production.",
    SYSTEM_VALIDATED: "Re-derived today from a deterministic contract. "
                      "Retrievable only where an administrator has governed "
                      "it on, and labelled where it is.",
    REJECTED: "Reviewed and refused. Kept rather than deleted: a rejected "
              "case records a reading somebody decided was wrong.",
    RETIRED: "Deliberately withdrawn. Terminal.",
    STALE: "Something it was validated against has changed underneath it.",
}

# ---------------------------------------------------------- authoring method
#: Written by a person, word by word.
HUMAN = "HUMAN"
#: Instantiated from a reviewed blueprint over the governed vocabulary. The
#: SPECIFICATION was written and reviewed by a person once; the SUBJECT is
#: governed; the PHRASING is generated. Distinct from HUMAN because calling a
#: generated instance hand-written is the exact dishonesty this phase forbids,
#: and distinct from LLM_GENERATED because no model was involved and the
#: blueprint has a line number somebody can read.
BLUEPRINT = "BLUEPRINT"
#: Written by a model. §5: never labelled human reviewed on the strength of
#: having been validated.
LLM_GENERATED = "LLM_GENERATED"
#: A paraphrase or variant of another case (§14).
VARIANT = "VARIANT"
#: Derived from a deterministic engine or semantic contract (§6).
DERIVED = "DERIVED_FROM_CONTRACT"
#: Migrated from the Phase 0 curriculum or a certified method example (§13).
MIGRATED = "MIGRATED"
#: Promoted from an adjudicated production failure (§33).
REVIEWED_FAILURE = "REVIEWED_FAILURE"

AUTHORING_METHODS: tuple[str, ...] = (
    HUMAN, BLUEPRINT, LLM_GENERATED, VARIANT, DERIVED, MIGRATED,
    REVIEWED_FAILURE,
)

#: Methods where no person wrote the words. Used for reporting, never for
#: permission: a blueprint case is as eligible for approval as any other, and
#: what this set exists for is to stop a count of 1,828 reading as 1,828
#: sentences somebody typed.
GENERATED: frozenset[str] = frozenset({BLUEPRINT, LLM_GENERATED, VARIANT,
                                       DERIVED, MIGRATED})

#: Methods whose output no validator may vouch for on its own. A model that
#: writes a case and a model that checks it agree far more often than either
#: agrees with the truth.
MACHINE_AUTHORED: frozenset[str] = frozenset({LLM_GENERATED, VARIANT})

# ------------------------------------------------------- system-validated
# §6: the only sources a SYSTEM_VALIDATED case may be derived from.
ENGINE_CONTRACT = "ENGINE_CONTRACT"
CERTIFIED_METHOD = "CERTIFIED_METHOD"
REVIEWED_TEST = "REVIEWED_TEST"
SEMANTIC_CONTRACT = "SEMANTIC_CONTRACT"
DIAGNOSTIC_DATASET = "DIAGNOSTIC_DATASET"

SYSTEM_SOURCES: tuple[str, ...] = (
    ENGINE_CONTRACT, CERTIFIED_METHOD, REVIEWED_TEST, SEMANTIC_CONTRACT,
    DIAGNOSTIC_DATASET,
)

# ------------------------------------------------------------- sensitivity
#: Structure only — question shapes, plans, invariants. The default, and what
#: §8 asks production teaching cases to be.
PUBLIC = "STRUCTURE_ONLY"
#: Synthetic figures used to validate a method (§8). Reference data, never
#: shown to a planner before execution.
DIAGNOSTIC = "DIAGNOSTIC"
#: Anything touching a real client. §47 forbids it as a teaching case, and
#: this value exists so the forbidding is enforceable rather than hoped for.
CLIENT = "CLIENT"

SENSITIVITIES: tuple[str, ...] = (PUBLIC, DIAGNOSTIC, CLIENT)

# ------------------------------------------------------------- transitions
# What may follow what. RETIRED is terminal: reviving a withdrawn case as a
# draft would let its history be quietly rewritten, and a new case costs
# nothing.
TRANSITIONS: dict[str, frozenset[str]] = {
    DRAFT: frozenset({AUTO_VALIDATED, SME_REVIEW_REQUIRED, SYSTEM_VALIDATED,
                      REJECTED, RETIRED}),
    AUTO_VALIDATED: frozenset({SME_REVIEW_REQUIRED, HUMAN_REVIEWED, APPROVED,
                               SYSTEM_VALIDATED, REJECTED, STALE, RETIRED,
                               DRAFT}),
    SME_REVIEW_REQUIRED: frozenset({HUMAN_REVIEWED, APPROVED, REJECTED, DRAFT,
                                    STALE, RETIRED}),
    #: A reviewer who has read a case may sign for it, refuse it, send it
    #: back for changes, or retire it. They may not leave it retrievable by
    #: having read it, which is why there is no edge to production from here
    #: other than APPROVED.
    HUMAN_REVIEWED: frozenset({APPROVED, REJECTED, DRAFT, SME_REVIEW_REQUIRED,
                               STALE, RETIRED}),
    APPROVED: frozenset({STALE, SME_REVIEW_REQUIRED, HUMAN_REVIEWED,
                         RETIRED}),
    SYSTEM_VALIDATED: frozenset({STALE, SME_REVIEW_REQUIRED, RETIRED}),
    REJECTED: frozenset({DRAFT, RETIRED}),
    STALE: frozenset({DRAFT, AUTO_VALIDATED, SME_REVIEW_REQUIRED,
                      HUMAN_REVIEWED, RETIRED}),
    RETIRED: frozenset(),
}

# ------------------------------------------------------------- staleness
#: The axes §5 names. A case records the version it was validated against on
#: each; a mismatch — or a blank — makes it STALE.
ONTOLOGY = "ontology"
METHOD = "method"
RELATIONSHIP = "relationship"
DATASET_CONTRACT = "dataset_contract"
PLANNER_SCHEMA = "planner_schema"
PROMPT_SCHEMA = "prompt_schema"
MODEL_FAMILY = "model_family"

STALENESS_AXES: tuple[str, ...] = (
    ONTOLOGY, METHOD, RELATIONSHIP, DATASET_CONTRACT, PLANNER_SCHEMA,
    PROMPT_SCHEMA, MODEL_FAMILY,
)


@dataclass(frozen=True)
class Decision:
    """Whether something is permitted, and why not when it is not."""

    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def _clean(value: object) -> str:
    return str(value or "").strip()


def known(status: str) -> bool:
    return _clean(status).upper() in STATUSES


def retrievable(status: str, *, system_validated_enabled: bool = False,
                sensitivity: str = PUBLIC) -> Decision:
    """May a case in this state be retrieved into a live prompt?

    Three ways the answer is no, and each is a different failure:

    - the status is not one that may be retrieved (or is not a status at all);
    - the status is SYSTEM_VALIDATED and nobody has governed it on;
    - the case carries client data, which no status redeems (§47).
    """
    state = _clean(status).upper()
    if _clean(sensitivity).upper() == CLIENT:
        return Decision(False, "client data is never retrievable as a "
                               "teaching case")
    if state not in RETRIEVABLE:
        return Decision(False, f"{state or 'no status'} is not retrievable")
    if state == SYSTEM_VALIDATED and not system_validated_enabled:
        return Decision(False, "SYSTEM_VALIDATED retrieval is not governed on")
    return Decision(True)


def may_transition(current: str, target: str) -> Decision:
    """Is this a state change the workflow allows at all?"""
    now, then = _clean(current).upper(), _clean(target).upper()
    if not known(now):
        return Decision(False, f"{now or 'no status'} is not a known status")
    if not known(then):
        return Decision(False, f"{then or 'no status'} is not a known status")
    if then not in TRANSITIONS[now]:
        return Decision(False, f"{now} cannot become {then}")
    return Decision(True)


def may_approve(*, authoring_method: str, reviewer: str,
                reviewer_is_human: bool = True) -> Decision:
    """§5's rule, as code: an approval needs a person behind it.

    A validator passing is `AUTO_VALIDATED`. Only a named human reviewer makes
    a case `APPROVED`, and a machine-authored case cannot reach approval by
    being signed off by another machine — which is the exact shape of "label
    LLM-generated cases human reviewed" that §5 forbids.
    """
    who = _clean(reviewer)
    if not who:
        return Decision(False, "approval requires a named reviewer")
    if not reviewer_is_human:
        return Decision(False, "approval requires a human reviewer; a "
                               "validated case is AUTO_VALIDATED, not "
                               "APPROVED")
    method = _clean(authoring_method).upper()
    if method and method not in AUTHORING_METHODS:
        return Decision(False, f"{method} is not a known authoring method")
    return Decision(True)


def may_system_validate(*, source: str, provenance: str,
                        deterministic_validation_passed: bool,
                        sensitivity: str = PUBLIC,
                        model_generated_gold: bool = False,
                        from_holdout: bool = False) -> Decision:
    """§6's five requirements, checked in the order they can fail.

    The holdout check is last and unconditional rather than folded into the
    source check, because a case can name a legitimate source and still have
    been built from a sealed question — and that is the failure that would
    quietly turn the seal into decoration.
    """
    src = _clean(source).upper()
    if src not in SYSTEM_SOURCES:
        return Decision(False, f"{src or 'no source'} is not a governed "
                               "system-validation source")
    if not _clean(provenance):
        return Decision(False, "the exact source must be recorded")
    if not deterministic_validation_passed:
        return Decision(False, "deterministic validation did not pass")
    if model_generated_gold:
        return Decision(False, "system validation cannot rest on "
                               "model-generated gold")
    if _clean(sensitivity).upper() == CLIENT:
        return Decision(False, "client raw data cannot be system validated")
    if from_holdout:
        return Decision(False, "a sealed-holdout source can never be "
                               "system validated")
    return Decision(True)


def stale_because(recorded: Mapping[str, str],
                  current: Mapping[str, str]) -> tuple[str, ...]:
    """The axes on which a case no longer matches the world it was validated
    against.

    An axis the caller does not currently version is skipped — there is
    nothing to compare against, and inventing a mismatch would make every case
    stale the moment a new axis is declared. An axis the *case* never recorded
    is stale, because a blank is not evidence of agreement.
    """
    moved: list[str] = []
    for axis in STALENESS_AXES:
        now = _clean(current.get(axis))
        if not now:
            continue
        if _clean(recorded.get(axis)) != now:
            moved.append(axis)
    return tuple(moved)


def is_stale(recorded: Mapping[str, str],
             current: Mapping[str, str]) -> bool:
    return bool(stale_because(recorded, current))


def describe(status: str) -> str:
    """The sentence an administrator sees next to the status."""
    return {
        DRAFT: "Authored, not yet validated. Not retrieved.",
        AUTO_VALIDATED: "Passed automated validation. Not human reviewed.",
        SME_REVIEW_REQUIRED: "A validator declined to vouch for it. "
                             "Waiting on a reviewer.",
        APPROVED: "Reviewed and signed for by a named person. Retrievable.",
        REJECTED: "Reviewed and refused. Kept as a record.",
        RETIRED: "Withdrawn. Terminal.",
        STALE: "Something it was validated against has changed. "
               "Needs revalidation.",
        SYSTEM_VALIDATED: "Derived from a deterministic contract and "
                          "re-derived today. Retrievable where governed on.",
    }.get(_clean(status).upper(), "")


__all__ = [
    "APPROVED", "AUTHORING_METHODS", "AUTO_VALIDATED", "BLUEPRINT",
    "CERTIFIED_METHOD", "GENERATED",
    "CLIENT", "DERIVED", "DIAGNOSTIC", "DIAGNOSTIC_DATASET", "DRAFT",
    "ENGINE_CONTRACT", "HUMAN", "LLM_GENERATED", "MACHINE_AUTHORED",
    "HUMAN_APPROVED", "HUMAN_REVIEWED", "STATUS_MEANS",
    "SYSTEM_REFERENCE_VALIDATED",
    "MIGRATED", "PUBLIC", "REJECTED", "RETIRED", "RETRIEVABLE",
    "REVIEWED_FAILURE", "REVIEWED_TEST", "SEMANTIC_CONTRACT", "SENSITIVITIES",
    "SME_REVIEW_REQUIRED", "STALE", "STALENESS_AXES", "STATUSES",
    "STATUS_VERSION", "SYSTEM_SOURCES", "SYSTEM_VALIDATED", "TRANSITIONS",
    "VARIANT", "Decision", "describe", "is_stale", "known", "may_approve",
    "may_system_validate", "may_transition", "retrievable", "stale_because",
    "ONTOLOGY", "METHOD", "RELATIONSHIP", "DATASET_CONTRACT", "PLANNER_SCHEMA",
    "PROMPT_SCHEMA", "MODEL_FAMILY",
]
