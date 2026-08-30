"""
Natural-language learning questions. §84.

The Studio answers questions like "how much has CreditProbe improved since
last month?" — and answers them from persisted snapshots and evaluations,
never from a model's recollection of them.

The rule this module exists to enforce
---------------------------------------
§84: "Do not let an LLM invent performance numbers."

That is not a prompt instruction; it is an architecture. Nothing here calls
a model. A question is matched to one of nine governed shapes by
deterministic keyword scoring, and each shape is answered by a function that
can only read the `Facts` it is handed. Every number that comes out carries
the id of the snapshot or evaluation it came from, so a reader can go and
look at it.

Two failure modes are handled explicitly rather than smoothed over:

**A question nobody planned for.** `match()` returns None. The answer is
"this is not one of the questions I can answer from the persisted
evaluations", with the list of the ones that are — not a plausible-sounding
paragraph built from the nearest snapshot.

**A question with no data behind it.** The shape matched, the facts are
missing. `answerable` comes back False and `missing` names what would be
needed. A zero here would read as "no improvement" when the truth is "never
measured", and those lead to opposite decisions.

Where the numbers come from
----------------------------
`Facts` is assembled by the caller from what is already persisted:
`measurement.DimensionResult` per dimension, the `Contribution` waterfall,
snapshot comparisons, the un-activated learning queue. This module does no
arithmetic beyond selecting and ordering — the measurement rules live in
`measurement.py` and are not reimplemented here, because two implementations
of "did this improve" is one more than can stay consistent.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.continuous import measurement

QUESTIONS_VERSION = "1.0.0"


class QuestionError(Exception):
    """A question that cannot be answered as asked."""


# --------------------------------------------------------------- the facts


@dataclass
class Facts:
    """Everything an answer may draw on. Persisted, not inferred."""

    #: Per-dimension measurement over the window in question.
    dimensions: list[measurement.DimensionResult] = field(
        default_factory=list)
    #: §78's attribution, including the non-isolated entries.
    contributions: list[measurement.Contribution] = field(
        default_factory=list)
    #: What was captured in the window: new_cases, new_regulatory, etc.
    quantity: dict[str, int] = field(default_factory=dict)
    #: Learning that is approved but not yet live, as {id: description}.
    pending_activation: list[dict[str, Any]] = field(default_factory=list)
    #: Brain imports measured in the Lift Lab, keyed by brain name.
    brain_lift: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: What one person's feedback led to, when the question is "my feedback".
    feedback_attribution: dict[str, Any] = field(default_factory=dict)
    #: The window these facts describe, and the snapshots that back them.
    window: str = ""
    window_label: str = ""
    baseline_snapshot_id: str = ""
    current_snapshot_id: str = ""

    @property
    def basis(self) -> list[str]:
        return [s for s in (self.baseline_snapshot_id,
                            self.current_snapshot_id) if s]

    def dimension(self, name: str) -> measurement.DimensionResult | None:
        wanted = _normalise(name)
        for result in self.dimensions:
            if _normalise(result.dimension) == wanted:
                return result
        return None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# ------------------------------------------------------------- the answers


@dataclass
class Answer:
    """One answered question, with the provenance of every number in it."""

    question_id: str
    asked: str
    answerable: bool
    headline: str
    detail: list[str] = field(default_factory=list)
    numbers: list[dict[str, Any]] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "questions_version": QUESTIONS_VERSION,
            "question_id": self.question_id,
            "asked": self.asked,
            "answerable": self.answerable,
            "headline": self.headline,
            "detail": list(self.detail),
            "numbers": list(self.numbers),
            "basis_snapshots": list(self.basis),
            "missing": list(self.missing),
            "caveats": list(self.caveats),
            "source": "persisted snapshots and evaluations",
            "not_generated": (
                "Every figure here was read from a stored evaluation. "
                "§84: no model produced any number on this screen."),
        }


def _number(label: str, value: Any, unit: str, source: str,
            reads_as: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit,
            "source": source, "reads_as": reads_as}


def _unanswerable(question_id: str, asked: str, headline: str,
                  missing: list[str]) -> Answer:
    return Answer(question_id=question_id, asked=asked, answerable=False,
                  headline=headline, missing=missing,
                  caveats=["Reporting zero here would read as 'no "
                           "improvement' when the truth is 'never "
                           "measured'."])


# ------------------------------------------------------- the nine builders


def _improvement_since(asked: str, facts: Facts) -> Answer:
    measured = [d for d in facts.dimensions
                if d.validation.verdict != measurement.INSUFFICIENT_EVIDENCE]
    if not measured:
        where = facts.window_label or "in this window"
        return _unanswerable(
            "improvement_since", asked,
            f"Nothing was measured on validation {where}, so there is no "
            "improvement figure to give.",
            ["a validation evaluation in this window"])

    verdict = measurement.quality_verdict(
        quantity=facts.quantity, dimensions=facts.dimensions)
    mean_points = round(
        sum(d.validation.points for d in measured) / len(measured), 2)
    return Answer(
        question_id="improvement_since", asked=asked, answerable=True,
        headline=verdict["headline"],
        detail=[d._sentence() for d in measured],
        numbers=[_number(
            "Mean validation movement", mean_points, "percentage points",
            facts.current_snapshot_id,
            f"{mean_points:+.2f} pp across {len(measured)} measured "
            "dimension(s)")],
        basis=facts.basis,
        caveats=[verdict["why_they_are_separate"]])


def _what_learned(asked: str, facts: Facts) -> Answer:
    captured = {k: v for k, v in facts.quantity.items() if v}
    if not captured:
        return _unanswerable(
            "what_learned", asked,
            "Nothing was captured in this window.",
            ["capture counts for the window"])
    verdict = measurement.quality_verdict(
        quantity=facts.quantity, dimensions=facts.dimensions)
    return Answer(
        question_id="what_learned", asked=asked, answerable=True,
        headline=verdict["headline"],
        detail=[f"{k.replace('_', ' ')}: {v}"
                for k, v in sorted(captured.items())],
        numbers=[_number(k.replace("_", " "), v, "items",
                         facts.current_snapshot_id)
                 for k, v in sorted(captured.items())],
        basis=facts.basis,
        caveats=[verdict["why_they_are_separate"]])


def _best_area(asked: str, facts: Facts) -> Answer:
    measured = [d for d in facts.dimensions
                if d.validation.verdict != measurement.INSUFFICIENT_EVIDENCE]
    if not measured:
        return _unanswerable(
            "best_area", asked,
            "No dimension has enough validation evidence to be ranked.",
            ["a validation evaluation with at least "
             f"{measurement.MINIMUM_CASES} cases per dimension"])
    best = max(measured, key=lambda d: d.validation.points)
    if best.validation.points <= 0:
        return Answer(
            question_id="best_area", asked=asked, answerable=True,
            headline="No area improved on validation in this window.",
            detail=[d._sentence() for d in measured],
            numbers=[], basis=facts.basis,
            caveats=["The best-performing dimension still did not move up, "
                     "so naming it 'the most improved' would be wrong."])
    return Answer(
        question_id="best_area", asked=asked, answerable=True,
        headline=f"{best.dimension} improved the most on validation.",
        detail=[best._sentence()],
        numbers=[_number(best.dimension, best.validation.points,
                         "percentage points", facts.current_snapshot_id,
                         best.validation.sentence())],
        basis=facts.basis)


def _imported_brain(asked: str, facts: Facts) -> Answer:
    if not facts.brain_lift:
        return _unanswerable(
            "imported_brain", asked,
            "No imported Brain has been measured in the Lift Lab.",
            ["a Lift Lab measurement for the imported Brain"])
    named = _named_brain(asked, facts)
    if named is None:
        return _unanswerable(
            "imported_brain", asked,
            "That Brain has not been measured here.",
            [f"a Lift Lab measurement; measured Brains are: "
             f"{', '.join(sorted(facts.brain_lift))}"])
    name, lift = named
    points = lift.get("validation_points")
    if points is None:
        return _unanswerable(
            "imported_brain", asked,
            f"{name} was imported but never measured against a baseline.",
            ["a Lift Lab run for this import"])
    verdict = lift.get("verdict") or (
        measurement.IMPROVED if points > 0 else measurement.REGRESSED)
    return Answer(
        question_id="imported_brain", asked=asked, answerable=True,
        headline=f"{name}: {verdict} on validation "
                 f"({float(points):+.2f} pp).",
        detail=[str(lift.get("reads_as") or "")] if lift.get("reads_as")
        else [],
        numbers=[_number(f"{name} validation movement", points,
                         "percentage points",
                         str(lift.get("evaluation_id")
                             or facts.current_snapshot_id))],
        basis=facts.basis,
        caveats=[] if lift.get("isolated") else [
            "This Brain was activated alongside other changes, so the "
            "movement is not attributable to the import alone."])


def _named_brain(asked: str,
                 facts: Facts) -> tuple[str, dict[str, Any]] | None:
    lowered = _normalise(asked)
    for name, lift in facts.brain_lift.items():
        if _normalise(name) and _normalise(name) in lowered:
            return name, lift
    if len(facts.brain_lift) == 1:
        return next(iter(facts.brain_lift.items()))
    return None


def _one_dimension(asked: str, facts: Facts) -> Answer:
    result = _dimension_in(asked, facts)
    if result is None:
        return _unanswerable(
            "one_dimension", asked,
            "That dimension has not been measured in this window.",
            [f"a measurement for one of: "
             f"{', '.join(d.dimension for d in facts.dimensions)}"]
            if facts.dimensions else ["any dimension measurement"])
    return Answer(
        question_id="one_dimension", asked=asked, answerable=True,
        headline=f"{result.dimension}: {result.verdict}.",
        detail=[result._sentence()],
        numbers=[
            _number(f"{result.dimension} (validation)",
                    result.validation.points, "percentage points",
                    facts.current_snapshot_id,
                    result.validation.sentence()),
            _number(f"{result.dimension} (development)",
                    result.development.points, "percentage points",
                    facts.current_snapshot_id,
                    result.development.sentence()),
        ],
        basis=facts.basis,
        caveats=["Development is the set that was tuned against. Where the "
                 "two disagree, the validation figure is the one to "
                 "believe."])


def _dimension_in(asked: str,
                  facts: Facts) -> measurement.DimensionResult | None:
    lowered = _normalise(asked)
    best: measurement.DimensionResult | None = None
    best_len = 0
    for result in facts.dimensions:
        name = _normalise(result.dimension)
        if name and name in lowered and len(name) > best_len:
            best, best_len = result, len(name)
    return best


def _validation_or_development(asked: str, facts: Facts) -> Answer:
    if not facts.dimensions:
        return _unanswerable(
            "validation_or_development", asked,
            "Neither partition has been measured in this window.",
            ["a measurement run over development and validation"])
    over = measurement.overfitting(facts.dimensions)
    dev = round(sum(d.development.points for d in facts.dimensions)
                / len(facts.dimensions), 2)
    val = round(sum(d.validation.points for d in facts.dimensions)
                / len(facts.dimensions), 2)
    return Answer(
        question_id="validation_or_development", asked=asked, answerable=True,
        headline=(f"Development moved {dev:+.2f} pp and validation moved "
                  f"{val:+.2f} pp."),
        detail=[d._sentence() for d in facts.dimensions],
        numbers=[
            _number("Development", dev, "percentage points",
                    facts.current_snapshot_id),
            _number("Validation", val, "percentage points",
                    facts.current_snapshot_id),
            _number("Gap", round(dev - val, 2), "percentage points",
                    facts.current_snapshot_id,
                    "the gap, not either number, is the overfitting signal"),
        ],
        basis=facts.basis,
        caveats=[over._recommendation()])


def _cause_of_regression(asked: str, facts: Facts) -> Answer:
    result = _dimension_in(asked, facts)
    if result is None:
        regressed = [d for d in facts.dimensions
                     if d.verdict == measurement.REGRESSED]
        if not regressed:
            return _unanswerable(
                "cause_of_regression", asked,
                "No dimension regressed in this window.",
                ["a regressed dimension to explain"])
        result = regressed[0]
    if result.verdict != measurement.REGRESSED:
        return Answer(
            question_id="cause_of_regression", asked=asked, answerable=True,
            headline=f"{result.dimension} did not regress: {result.verdict}.",
            detail=[result._sentence()], basis=facts.basis,
            caveats=["There is no cause to explain because there is no "
                     "regression."])
    if not result.learning_items and not result.releases:
        return _unanswerable(
            "cause_of_regression", asked,
            f"{result.dimension} regressed, and nothing recorded which "
            "learning was responsible.",
            ["a change-isolation experiment, or the learning items "
             "attributed to this dimension"])
    return Answer(
        question_id="cause_of_regression", asked=asked, answerable=True,
        headline=f"{result.dimension} regressed "
                 f"{result.validation.points:+.2f} pp on validation.",
        detail=([f"Learning items in scope: "
                 f"{', '.join(result.learning_items)}"]
                if result.learning_items else [])
        + ([f"Releases in scope: {', '.join(result.releases)}"]
           if result.releases else []),
        numbers=[_number(result.dimension, result.validation.points,
                         "percentage points", facts.current_snapshot_id,
                         result.validation.sentence())],
        basis=facts.basis,
        caveats=["These are the changes that were in scope, not a proven "
                 "cause. Run a change-isolation experiment to attribute it "
                 "to one of them."])


def _not_activated(asked: str, facts: Facts) -> Answer:
    if not facts.pending_activation:
        return Answer(
            question_id="not_activated", asked=asked, answerable=True,
            headline="Nothing approved is waiting to be activated.",
            basis=facts.basis)
    return Answer(
        question_id="not_activated", asked=asked, answerable=True,
        headline=f"{len(facts.pending_activation)} approved item(s) are not "
                 "yet live.",
        detail=[str(item.get("description") or item.get("id") or "")
                for item in facts.pending_activation],
        numbers=[_number("Awaiting activation",
                         len(facts.pending_activation), "items",
                         facts.current_snapshot_id)],
        basis=facts.basis,
        caveats=["Approved is not activated. Until it is activated it is "
                 "changing nothing about the answers users see."])


def _my_feedback(asked: str, facts: Facts) -> Answer:
    attribution = facts.feedback_attribution
    if not attribution:
        return _unanswerable(
            "my_feedback", asked,
            "Your feedback has not been traced to a measured change.",
            ["feedback-to-learning attribution for this person"])
    contribution = next(
        (c for c in facts.contributions if c.source == "Feedback fixes"),
        None)
    numbers = [
        _number("Feedback you gave", attribution.get("submitted", 0),
                "items", facts.current_snapshot_id),
        _number("Became teaching cases", attribution.get("became_cases", 0),
                "items", facts.current_snapshot_id),
        _number("Activated", attribution.get("activated", 0), "items",
                facts.current_snapshot_id),
    ]
    if contribution is None:
        return Answer(
            question_id="my_feedback", asked=asked, answerable=True,
            headline=("Your feedback has been captured and reviewed, but no "
                      "measured movement has been attributed to it yet."),
            numbers=numbers, basis=facts.basis,
            caveats=["Capture is not improvement. Attribution needs an "
                     "evaluation after the change was activated."])
    numbers.append(_number(
        "Attributed movement", contribution.points, "percentage points",
        facts.current_snapshot_id, contribution.evidence))
    return Answer(
        question_id="my_feedback", asked=asked, answerable=True,
        headline=(f"Feedback fixes account for {contribution.points:+.2f} pp "
                  "of the movement in this window."),
        numbers=numbers, basis=facts.basis,
        caveats=[] if contribution.isolated else [
            "This was not measured in isolation, so it is a share of a "
            "joint effect rather than a figure caused by your feedback "
            "alone."])


# ------------------------------------------------------------- the catalogue


@dataclass(frozen=True)
class Shape:
    """One governed question, and what recognises it."""

    question_id: str
    canonical: str
    #: All of these must appear for the shape to be considered.
    requires: tuple[str, ...]
    #: Any of these adds to the score. Ties break toward more specific.
    boosts: tuple[str, ...] = ()
    builder: Callable[[str, Facts], Answer] | None = None


#: §84's nine questions, in §84's order. `requires` is deliberately narrow:
#: a question that matches nothing is answered honestly, and that is a
#: better outcome than a question matched to the wrong shape and answered
#: confidently with the wrong snapshot.
SHAPES: tuple[Shape, ...] = (
    Shape("improvement_since", "How much has CreditProbe improved since "
          "last month?", ("improv",), ("how much", "since", "month", "week"),
          _improvement_since),
    Shape("what_learned", "What did CreditProbe learn this week?",
          ("learn",), ("what", "week", "month", "captured"), _what_learned),
    Shape("best_area", "Which area improved the most?",
          ("most",), ("which", "area", "improv", "best", "dimension"),
          _best_area),
    Shape("imported_brain", "Did the imported Riyadh Brain make us better?",
          ("brain",), ("import", "better", "made us", "worse"),
          _imported_brain),
    Shape("one_dimension", "Has Judgment & Presentation improved?",
          ("improv",), ("judgment", "presentation", "understanding",
                        "analytical", "computation", "evidence", "agentic",
                        "reliability", "experience", "design", "context"),
          _one_dimension),
    Shape("validation_or_development", "Did validation improve or only "
          "development?", ("validation",), ("development", "only", "or",
                                            "overfit"),
          _validation_or_development),
    Shape("cause_of_regression", "What caused Analytical Design to regress?",
          ("regress",), ("caused", "cause", "why", "worse"),
          _cause_of_regression),
    Shape("not_activated", "What learning has not yet been activated?",
          ("activat",), ("not", "yet", "pending", "waiting", "learning"),
          _not_activated),
    Shape("my_feedback", "How much did my feedback improve CreditProbe?",
          ("feedback",), ("my", "improve", "how much", "mine"),
          _my_feedback),
)

QUESTION_IDS: tuple[str, ...] = tuple(s.question_id for s in SHAPES)
EXPECTED_QUESTIONS = 9


def catalogue() -> list[dict[str, str]]:
    """The questions this screen can answer, for the empty state."""
    return [{"question_id": s.question_id, "question": s.canonical}
            for s in SHAPES]


def match(asked: str) -> Shape | None:
    """Which governed shape a question is, or None.

    Deterministic scoring, and no fallback to a nearest neighbour. §84's
    numbers are only trustworthy if the question that selected them was the
    question the user asked; a shape picked because it scored 1 out of 6 is
    a wrong answer delivered confidently.
    """
    lowered = _normalise(asked)
    if not lowered:
        return None

    best: Shape | None = None
    best_score = 0
    for shape in SHAPES:
        if not all(term in lowered for term in shape.requires):
            continue
        score = 10 * len(shape.requires) + sum(
            1 for term in shape.boosts if term in lowered)
        if score > best_score:
            best, best_score = shape, score
    return best


def ask(asked: str, facts: Facts) -> Answer:
    """Answer one question from persisted facts, or say why not."""
    shape = match(asked)
    if shape is None or shape.builder is None:
        return Answer(
            question_id="", asked=asked, answerable=False,
            headline=("That is not one of the questions I can answer from "
                      "the persisted evaluations."),
            detail=[s.canonical for s in SHAPES],
            missing=["a governed question shape"],
            caveats=["Answering it anyway would mean producing a number "
                     "that no stored evaluation supports."])
    return shape.builder(asked, facts)
