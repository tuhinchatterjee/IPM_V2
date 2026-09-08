"""
Which ECL methodology a What-If runs on, and the question that must be asked
before it runs.

Why this is a gate and not a setting
------------------------------------
The Delta Model and the ML Model can give materially different answers to the
same scenario, and neither is "the right one" — they answer differently-shaped
questions. Delta is a transparent proportional sensitivity; ML is a learned
nonlinear response. A product that quietly picked one and printed a number
would be making a methodological choice on the user's behalf and presenting it
as arithmetic.

So the choice is a GATE. Before the first ECL impact is calculated in a thread,
the product asks, offers both with an explanation of the difference, and does
not compute until the answer exists. After that the choice is the thread's
active methodology: it is shown on every result, it can be switched
deliberately, and it is never switched silently.

What does NOT trigger the gate
------------------------------
Informational questions. "Show Stage 1 PD by sector" calculates no ECL impact,
so asking which ECL methodology to use would be noise — there is no ECL being
estimated. The gate is at the calculation boundary, not at the door.

When the question is already answered
-------------------------------------
If the instruction says "calculate this with the Delta Model", asking again is
not carefulness, it is not listening. A methodology stated in the request is
read, confirmed in the answer, and used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.whatif import delta

DELTA = "delta"
ML = "ml"
METHODS: tuple[str, ...] = (DELTA, ML)

#: The names each methodology is offered and recognised under.
#:
#: `DELTA` and `ML` are the CONTRACT — the values that travel on a scenario
#: state, an API body, a saved What-If, a workbook and a model card. The labels
#: below are what a person reads, and they are not interchangeable with the
#: values: "ML Model — XGBoost" is eighteen characters of display text, and
#: sending it where a value belongs failed the detailed export with "Check:
#: methodology" before it reached any code that could have said what was
#: actually wrong.
LABELS: dict[str, str] = {DELTA: "Delta Model", ML: "ML Model — XGBoost"}

#: Every string that resolves to a methodology, so a caller sending a label —
#: an older client, a copied state, a person typing into an API console — is
#: understood rather than refused on a length check.
_ALIASES: dict[str, str] = {
    **{value: value for value in (DELTA, ML)},
    **{label.casefold(): value for value, label in LABELS.items()},
    "ml model": ML, "xgboost": ML, "ml_xgboost": ML, "ml-xgboost": ML,
    "delta model": DELTA, "delta_model": DELTA,
}


def canonical(said: str) -> str:
    """The governed value for whatever a caller sent, or "" for nothing.

    One place turns a methodology into its contract value. A label reaching a
    validator is a bug in the caller, but refusing it there produces "Check:
    methodology" and nothing a reader can act on, so it is normalised here and
    the caller is fixed separately.
    """
    text = str(said or "").strip()
    if not text:
        return ""
    return _ALIASES.get(text.casefold(), "")

_SAYS_DELTA = re.compile(
    r"\bdelta\b|\bdeterministic\b|\btransparent\s+model\b", re.IGNORECASE)
_SAYS_ML = re.compile(
    r"\bml\b|\bmachine[\s-]?learn\w*\b|\bxgboost\b|\bxgb\b|\bgradient[\s-]?boost\w*\b",
    re.IGNORECASE)
#: A question that merely mentions a model without choosing one.
_ASKS_ABOUT = re.compile(
    r"\bwhat(?:'s| is)\s+the\s+difference\b|\bwhich\s+model\s+should\b"
    r"|\bexplain\s+the\s+(?:delta|ml)\b", re.IGNORECASE)


class MethodologyError(ValueError):
    """A methodology that cannot be resolved, said rather than assumed."""


@dataclass(frozen=True)
class Choice:
    """A methodology, and how it came to be chosen."""

    method: str
    version: str
    #: "asked" — the person answered the gate.
    #: "stated" — the instruction named it.
    #: "carried" — the thread already had one.
    source: str = "asked"

    @property
    def label(self) -> str:
        return LABELS.get(self.method, self.method)

    @property
    def stamp(self) -> str:
        """The line every result carries."""
        return f"{self.label} v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "label": self.label,
                "version": self.version, "source": self.source,
                "stamp": self.stamp}


def version_of(method: str, *, model_version: str = "") -> str:
    """The version stamped on a result for one methodology."""
    if method == DELTA:
        return delta.DELTA_VERSION
    if method == ML:
        return model_version or "unversioned"
    raise MethodologyError(f"'{method}' is not an ECL methodology.")


def read(text: str) -> str:
    """The methodology an instruction names, or "" if it names none.

    A question ABOUT the models is not a choice between them. "What is the
    difference between the Delta Model and ML?" mentions both and chooses
    neither, and reading it as a selection would run a calculation the person
    did not ask for.
    """
    said = str(text or "")
    if _ASKS_ABOUT.search(said):
        return ""
    delta_named = bool(_SAYS_DELTA.search(said))
    ml_named = bool(_SAYS_ML.search(said))
    if delta_named and ml_named:
        return ""
    if delta_named:
        return DELTA
    if ml_named:
        return ML
    return ""


def refusal(said: str) -> str:
    """Why this is not a methodology, in words a reader can act on."""
    return (f"'{said}' is not an ECL methodology. The choices are "
            + ", ".join(f"{LABELS[m]} ({m})" for m in METHODS) + ".")


def resolve(*, requested: str = "", instruction: str = "",
            active: str = "", model_version: str = "") -> Choice | None:
    """The methodology to run on, or None when the gate must be asked.

    The order is the argument. An explicit request wins, because the person
    just answered. A methodology named in the instruction comes next, because
    they said it in their own words. The thread's active choice comes last, and
    only carries forward — it never overrides something newly stated.
    """
    if str(requested or "").strip():
        chosen = canonical(requested)
        if not chosen:
            raise MethodologyError(refusal(requested))
        return Choice(chosen, version_of(chosen, model_version=model_version),
                      "asked")
    spoken = read(instruction)
    if spoken:
        return Choice(spoken, version_of(spoken, model_version=model_version), "stated")
    carried = canonical(active)
    if carried:
        return Choice(carried, version_of(carried, model_version=model_version), "carried")
    return None


def needs_gate(*, calculates_ecl: bool, requested: str = "",
               instruction: str = "", active: str = "") -> bool:
    """Whether the product must stop and ask before computing.

    False for an informational question whatever the thread has settled: no ECL
    impact is being estimated, so there is no methodology to choose.
    """
    if not calculates_ecl:
        return False
    return resolve(requested=requested, instruction=instruction, active=active) is None


def question(*, active: str = "", ml_available: bool = True,
             ml_note: str = "") -> dict[str, Any]:
    """The gate itself: the question, the chips, and why the choice matters.

    Offered as options rather than prose because a finite choice deserves
    buttons — and alongside a composer, because the person may want to say
    "use ML but compare it against Delta", which no button covers.
    """
    options = [
        {"value": DELTA, "label": LABELS[DELTA], "available": True,
         "summary": ("Transparent deterministic sensitivity using the official "
                     "ECL and the relative PD, LGD and EAD changes."),
         "detail": ("Every figure can be reproduced with a calculator: the "
                    "reported ECL multiplied by the factors the scenario "
                    "implies."),
         "version": delta.DELTA_VERSION},
        {"value": ML, "label": LABELS[ML], "available": bool(ml_available),
         "summary": ("XGBoost-based nonlinear response learned from historical "
                     "Corporate IFRS 9 outcomes, anchored to the official "
                     "baseline ECL."),
         "detail": ("A 20% PD shock does not necessarily produce a 20% ECL "
                    "move: the model has learned how Stage, collateral "
                    "coverage and the rest interact."),
         "unavailable_because": ml_note if not ml_available else ""},
    ]
    return {
        "gate": "ecl_methodology",
        "question": "Which ECL methodology should I use for this What-If?",
        "why": ("The two methods can give materially different answers to the "
                "same scenario. Choosing one is a methodological decision, so "
                "the product asks rather than picking for you."),
        "options": options,
        "active": active or None,
        "active_label": LABELS.get(active) if active else None,
        "free_text": True,
        "note": ("You can also type an instruction — for example "
                 "\"use ML\" or \"calculate this with the Delta Model\"."),
    }


def confirmation(choice: Choice, *, switched_from: str = "") -> str:
    """What the answer says about the methodology it used."""
    if switched_from and switched_from != choice.method:
        return (f"Switched from {LABELS.get(switched_from, switched_from)} to "
                f"{choice.stamp} for this calculation.")
    if choice.source == "stated":
        return f"Using the {choice.stamp}, as your instruction asked."
    if choice.source == "carried":
        return (f"Using the {choice.stamp}, which this thread has been running "
                "on. Say so if you would like to switch.")
    return f"Using the {choice.stamp}."


def describe(*, ml_available: bool = True, model_version: str = "") -> dict[str, Any]:
    """Both methodologies, for the Model Configuration area."""
    return {
        "methods": [
            {"key": DELTA, **{k: v for k, v in delta.describe().items()
                              if k in ("name", "version", "owner", "purpose",
                                       "formula", "anchor")}},
            {"key": ML, "name": LABELS[ML],
             "version": model_version or "unversioned",
             "available": bool(ml_available),
             "purpose": ("A learned nonlinear response, anchored so the "
                         "official baseline ECL remains the truth."),
             "anchor": ("What-If ECL = Official Baseline ECL x "
                        "(shocked model rate / baseline model rate)")},
        ],
        "gate": ("Model selection is required before the first ECL impact in a "
                 "thread, and is shown on every result thereafter."),
    }


__all__ = [
    "DELTA", "LABELS", "METHODS", "ML", "Choice", "MethodologyError",
    "confirmation", "describe", "needs_gate", "question", "read", "resolve",
    "version_of",
]
