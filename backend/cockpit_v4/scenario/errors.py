"""The fourteen ways a scenario can fail, mapped onto the errors that exist.

Section 19 names a minimum set of actionable domain error categories and then
says exactly what to do with them: *"Map these into the existing error
contract and repair flow; do not replace core exceptions or swallow their
evidence."*

So they are not added to `states.ERROR_CODES`. That tuple is a protected core
constant, and growing it would be a protected-core change made to avoid
writing a mapping. Instead every domain category declares which existing code
it travels as, and the domain name rides in `Rejection.detail` where the tool
result shows it. The analyst sees both: the class the runtime already knows how
to handle, and the specific thing that went wrong.

THE SPLIT THAT MATTERS, and which section 19's flat list does not make.

Two of these are not errors at all. `UNIT_AMBIGUOUS` fires when a reader typed
"increase by 20" and a rate could mean four different things; `RULE_CONFLICT`
fires when two rules touch the same field on overlapping rows without a
declared order. Neither is a defect in a submission -- both are questions only
the reader can answer, and both have a home already: `disposition:
"clarification"`, the question in `clarification_question` and the choices in
`clarification_options`.

Returning those as rejections would send the analyst back to repair code that
was never wrong, which is the failure mode `action_state.decide`'s
`must_clarify` branch was built to end. `KIND` records which is which, so a
caller cannot get it wrong by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.cockpit_v4 import states as st
from backend.cockpit_v4.contracts import Rejection

#: Put the question to the reader. Not a rejection; there is nothing to fix.
ASK = "ask"

#: Hand it back to the analyst with enough detail to author a correction.
REJECT = "reject"

#: A bound was reached. The existing budget machinery owns the outcome.
BUDGET = "budget"


@dataclass(frozen=True)
class Category:
    """One domain failure: what it is, how it travels, what to do about it."""

    code: str
    kind: str
    maps_to: str
    meaning: str
    next_action: str


#: The scenario names a cohort that does not resolve -- an empty selection, a
#: reference to a thread that holds none, or a membership the snapshot no
#: longer contains. Section 6.1: it must not silently widen.
COHORT_UNRESOLVED = "COHORT_UNRESOLVED"

#: Corporate data reached through a Retail scenario or the reverse. A scope
#: violation, not a data gap.
BOOK_MISMATCH = "BOOK_MISMATCH"

#: The release moved under a scenario that was built against an older one.
SOURCE_VERSION_MISMATCH = "SOURCE_VERSION_MISMATCH"

#: "Increase by 20" against a rate, a score or a currency field.
UNIT_AMBIGUOUS = "UNIT_AMBIGUOUS"

#: Two rules on the same field and overlapping rows with no declared
#: composition. Section 5.2: never silently assume "more specific wins".
RULE_CONFLICT = "RULE_CONFLICT"

#: A probability above one, a negative exposure, a stage that is not 1, 2 or 3.
PARAMETER_OUT_OF_RANGE = "PARAMETER_OUT_OF_RANGE"

#: A rating notch or score move with no validated mapping to a risk parameter.
MAPPING_UNAVAILABLE = "MAPPING_UNAVAILABLE"

#: A macro factor with no estimable sensitivity for this book and parameter.
SENSITIVITY_NOT_SUPPORTED = "SENSITIVITY_NOT_SUPPORTED"

#: The ML emulator artifact is absent, stale, or its optional dependencies are
#: not installed. Section 11 is not built in this pass, so this is the honest
#: standing answer for Method 2.
MODEL_NOT_READY = "MODEL_NOT_READY"

#: A selected method cannot cover some eligible rows. Section 9.1: reason-coded
#: ineligibility, never a hidden zero and never a silent substitution.
METHOD_COVERAGE_GAP = "METHOD_COVERAGE_GAP"

#: The confirmed preview no longer describes what would run.
CONFIRMATION_STALE = "CONFIRMATION_STALE"

#: A bound in the existing budget contract was reached.
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

#: The method ran and did not produce a usable result.
CALCULATION_FAILED = "CALCULATION_FAILED"

#: The parts do not sum to the whole within the declared tolerance. Section
#: 13.2: a residual is shown, never spread across drivers to make a waterfall
#: look perfect -- so this fires when even the residual cannot be stated.
RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


CATEGORIES: tuple[Category, ...] = (
    Category(
        COHORT_UNRESOLVED, REJECT, st.DATA_UNAVAILABLE,
        "the rows this scenario is about could not be resolved",
        "name the book, the period and the filter, or reference a cohort this "
        "thread actually froze"),
    Category(
        BOOK_MISMATCH, REJECT, st.SECURITY_DENIED,
        "the scenario reaches data outside the active book",
        "open a thread in that book; a scenario cannot span both"),
    Category(
        SOURCE_VERSION_MISMATCH, REJECT, st.DATA_UNAVAILABLE,
        "the release this scenario was built against is not the one in scope",
        "rebuild the scenario against the current release, which creates a "
        "new version and needs a new confirmation"),
    Category(
        UNIT_AMBIGUOUS, ASK, st.ANSWER_VALIDATION,
        "the quantity could be relative, percentage points, basis points or a "
        "replacement, and they give different books",
        "ask once, listing the readings, with the choices clickable"),
    Category(
        RULE_CONFLICT, ASK, st.ANSWER_VALIDATION,
        "two rules move the same field on rows that overlap, with no declared "
        "order",
        "ask whether the second overrides, composes on the transformed value, "
        "or applies to the remainder"),
    Category(
        PARAMETER_OUT_OF_RANGE, REJECT, st.SQL_VALIDATION,
        "a transformed value falls outside what the field can hold",
        "correct the shock, or declare an explicit capping rule whose effect "
        "is shown as its own reconciling component"),
    Category(
        MAPPING_UNAVAILABLE, REJECT, st.DATA_UNAVAILABLE,
        "there is no validated mapping from this move to a risk parameter",
        "supply the assumption explicitly under the user-defined method, or "
        "drop the clause"),
    Category(
        SENSITIVITY_NOT_SUPPORTED, REJECT, st.DATA_UNAVAILABLE,
        "no sensitivity for this factor, book, parameter and horizon is "
        "supportably estimable",
        "state the parameter move directly, or supply an explicit assumption"),
    Category(
        MODEL_NOT_READY, REJECT, st.DATA_UNAVAILABLE,
        "the emulator artifact for this book is absent, stale or unloadable",
        "choose a method that is ready; the preview lists which are"),
    Category(
        METHOD_COVERAGE_GAP, REJECT, st.DATA_UNAVAILABLE,
        "a selected method cannot cover part of the eligible population",
        "accept a labelled common-subset comparison, or drop the method"),
    Category(
        CONFIRMATION_STALE, REJECT, st.ANSWER_VALIDATION,
        "the confirmed preview no longer describes what would run",
        "show the new preview and ask again; an old approval is not "
        "transferable"),
    Category(
        BUDGET_EXCEEDED, BUDGET, st.EXECUTION_LIMIT,
        "a bound in the run's existing budget was reached",
        "narrow the scope, or accept the partial status with its coverage"),
    Category(
        CALCULATION_FAILED, REJECT, st.SQL_RUNTIME,
        "the method ran and produced no usable result",
        "read the engine's own diagnostic, which is carried in the detail"),
    Category(
        RECONCILIATION_FAILED, REJECT, st.ANSWER_VALIDATION,
        "the parts do not sum to the whole and the difference cannot be "
        "stated as a residual",
        "this is a defect in the run, not in the request; nothing is "
        "published from it"),
)

BY_CODE: dict[str, Category] = {c.code: c for c in CATEGORIES}

#: Which of the fourteen go to the reader rather than back to the analyst.
KIND: dict[str, str] = {c.code: c.kind for c in CATEGORIES}

ASK_CODES: frozenset[str] = frozenset(
    c.code for c in CATEGORIES if c.kind == ASK)


class ScenarioError(Exception):
    """A scenario failure carrying its domain category.

    Kept distinct from `Rejection` so the caller has to decide how it
    surfaces -- `as_rejection()` for the analyst, `as_clarification()` for the
    reader. A single type that did both would make the ASK/REJECT split a
    comment rather than a mechanism.
    """

    def __init__(self, code: str, message: str, *, field_path: str = "",
                 detail: dict[str, Any] | None = None) -> None:
        if code not in BY_CODE:
            raise KeyError(
                f"{code!r} is not a scenario error category. The categories "
                f"are: {', '.join(sorted(BY_CODE))}.")
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_path = field_path
        self.detail = dict(detail or {})
        self.category = BY_CODE[code]

    def as_rejection(self) -> Rejection:
        """The existing contract, with the domain name visible in the detail.

        The `code` on the wire is the one the runtime already routes on. The
        domain category, its meaning and its next action ride alongside, so
        nothing is swallowed to make the mapping fit.
        """
        if self.category.kind == ASK:
            raise TypeError(
                f"{self.code} is a question for the reader, not a rejection. "
                f"Use as_clarification(); see this module's header.")
        return Rejection(
            self.category.maps_to, self.message,
            field_path=self.field_path,
            detail={**self.detail,
                    "whatif_error": self.code,
                    "meaning": self.category.meaning,
                    "next_action": self.category.next_action})

    def as_clarification(self, *, question: str,
                         options: list[str] | None = None) -> dict[str, Any]:
        """The payload for a turn that puts the choice back to the reader.

        Shaped for `finalize_response`: the fields are the ones the existing
        clarification round trip already carries, so the reply is projected
        back by `context.build` without anything new.
        """
        if self.category.kind != ASK:
            raise TypeError(
                f"{self.code} is a defect the analyst can correct, not a "
                f"question for the reader. Use as_rejection().")
        return {
            "disposition": "clarification",
            "clarification_question": question,
            "clarification_options": list(options or []),
            "whatif_error": self.code,
            "meaning": self.category.meaning,
            **({"detail": self.detail} if self.detail else {}),
        }


def raise_for(code: str, message: str, *, field_path: str = "",
              **detail: Any) -> None:
    """Shorthand at the call sites, which are many and want to stay readable."""
    raise ScenarioError(code, message, field_path=field_path, detail=detail)


__all__ = [
    "ASK", "ASK_CODES", "BUDGET", "BUDGET_EXCEEDED", "BY_CODE",
    "CALCULATION_FAILED", "CATEGORIES", "COHORT_UNRESOLVED",
    "CONFIRMATION_STALE", "Category", "KIND", "MAPPING_UNAVAILABLE",
    "METHOD_COVERAGE_GAP", "MODEL_NOT_READY", "PARAMETER_OUT_OF_RANGE",
    "RECONCILIATION_FAILED", "REJECT", "RULE_CONFLICT", "ScenarioError",
    "SENSITIVITY_NOT_SUPPORTED", "SOURCE_VERSION_MISMATCH",
    "UNIT_AMBIGUOUS", "BOOK_MISMATCH", "raise_for",
]
