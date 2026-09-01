"""
Optional narrow models, and the bar one has to clear. §32.

    "Implement only where measured improvement exists.
     Start with deterministic/statistical baselines.
     Do not add a model merely because it sounds agentic."

What this module is
-------------------
An interface and a measurement, not a set of models. CreditProbe already reads
intent, resolves same-turn coreference, decomposes objectives, parses periods
and classifies scope — deterministically, with code somebody can read and
argue with. §32's question is whether a narrow model beats any of those, and
the answer is an experiment rather than an assumption.

So a task has a BASELINE (what the product does today) and may have a
CANDIDATE. `compare` runs both over the same cases and returns the numbers §32
asks for. `Adoption` is the decision, and its default is no.

The bar, and why it is three conditions rather than one
--------------------------------------------------------
A candidate is adopted when it is more accurate, makes no more critical
errors, and is not materially slower. All three, because each alone is
gameable in a way that has happened to somebody:

- accuracy alone adopts a model that is right more often and catastrophically
  wrong in a new way — a period parser that gains two points overall by
  reading "last year" as a calendar year is worse, not better;
- critical errors alone adopts a model that is safe and useless;
- latency alone is not an argument for anything.

`MARGIN` exists because a development set of a few hundred cases cannot
distinguish a one-point difference from noise. Beating the baseline by less
than the margin is not beating it.

Nothing here calls a provider
------------------------------
`compare` takes two callables. A candidate that happens to be a model is the
caller's business; this module measures whatever it is given, offline, against
cases the caller supplies.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

CLASSIFIER_VERSION = "1.0.0"

# ---------------------------------------------------------------- the tasks
INTENT = "intent"
SAME_TURN = "same_turn_coreference"
ACTION = "conversation_action"
OBJECTIVES = "objective_decomposition"
PERIOD = "period_parser"
SCOPE = "scope_classifier"
RERANKER = "retrieval_reranker"

TASKS: tuple[str, ...] = (INTENT, SAME_TURN, ACTION, OBJECTIVES, PERIOD,
                          SCOPE, RERANKER)

#: What the product does today for each, named so a report can say what the
#: candidate is being compared against rather than "the baseline".
BASELINES: dict[str, str] = {
    INTENT: "backend.orchestration.capability — the deterministic reader",
    SAME_TURN: "backend.orchestration.discourse — local antecedents",
    ACTION: "backend.orchestration.conversation — the action taxonomy",
    OBJECTIVES: "backend.orchestration.objectives — clause decomposition",
    PERIOD: "backend.orchestration.periods — the governed vocabulary",
    SCOPE: "backend.teaching.retrieval — portfolio scope compatibility",
    RERANKER: "backend.teaching.retrieval — governed features and BM25",
}

#: How much better a candidate has to be before the difference counts. Two
#: points on a few hundred cases is inside the noise, and adopting on it means
#: adopting on a coin flip.
MARGIN = 0.02

#: How much slower a candidate may be. A narrow classifier that doubles the
#: time to first token is not a narrow classifier.
LATENCY_TOLERANCE = 1.5


class Predictor(Protocol):
    """Anything that turns one input into one label.

    Deliberately minimal. A predictor that needs configuration, a client or a
    warm-up is built by the caller and handed over ready.
    """

    def __call__(self, item: Any) -> Any:
        ...


@dataclass
class Measurement:
    """How one predictor did over one set of cases."""

    name: str
    total: int = 0
    correct: int = 0
    #: Errors on cases the caller marked critical. Counted separately because
    #: §32 asks for them separately, and because a model may trade them.
    critical_errors: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def per_call_ms(self) -> float:
        return self.latency_ms / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "total": self.total, "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "critical_errors": self.critical_errors,
            "latency_ms": round(self.latency_ms, 2),
            "per_call_ms": round(self.per_call_ms, 3),
            "errors": self.errors[:20],
        }


@dataclass
class Adoption:
    """Whether a candidate replaces the baseline, and why.

    `adopt` defaults to False and every path that sets it True has to say
    which of the three conditions it met. A decision object whose default was
    yes would make "nobody looked" indistinguishable from "it won".
    """

    task: str
    adopt: bool = False
    reason: str = ""
    baseline: Measurement | None = None
    candidate: Measurement | None = None

    @property
    def gain(self) -> float:
        if not self.baseline or not self.candidate:
            return 0.0
        return self.candidate.accuracy - self.baseline.accuracy

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "adopt": self.adopt,
            "reason": self.reason,
            "accuracy_gain": round(self.gain, 4),
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "candidate": self.candidate.to_dict() if self.candidate else None,
        }


@dataclass(frozen=True)
class Sample:
    """One labelled case. `critical` marks the ones where being wrong is not
    a percentage point."""

    item: Any
    expected: Any
    critical: bool = False
    note: str = ""


def measure(name: str, predictor: Predictor,
            samples: Sequence[Sample]) -> Measurement:
    """Run a predictor over labelled cases.

    A predictor that raises scores the case wrong rather than failing the
    measurement: a candidate that crashes on one input in fifty is a candidate
    with a defect, and hiding it behind an exception would make it look like a
    candidate that was never tried.
    """
    found = Measurement(name=name, total=len(samples))
    started = time.perf_counter()
    for sample in samples:
        try:
            predicted = predictor(sample.item)
        except Exception as error:  # noqa: BLE001 - a crash is a wrong answer
            predicted = f"<error: {error}>"
        if predicted == sample.expected:
            found.correct += 1
            continue
        if sample.critical:
            found.critical_errors += 1
        found.errors.append({
            "input": str(sample.item)[:160],
            "expected": str(sample.expected),
            "predicted": str(predicted),
            "critical": sample.critical,
            "note": sample.note,
        })
    found.latency_ms = (time.perf_counter() - started) * 1000
    return found


def compare(task: str, *, baseline: Predictor, candidate: Predictor,
            samples: Sequence[Sample], margin: float = MARGIN,
            latency_tolerance: float = LATENCY_TOLERANCE) -> Adoption:
    """§32's experiment, and its decision.

    The order of the checks is the order a reviewer would ask them in: did it
    make a new critical error, did it actually win, and is it fast enough.
    Critical errors first because that answer ends the conversation.
    """
    if task not in TASKS:
        raise ValueError(f"{task!r} is not one of §32's tasks")
    if not samples:
        return Adoption(task=task, reason="no labelled cases to compare on")

    left = measure(BASELINES.get(task, "baseline"), baseline, samples)
    right = measure("candidate", candidate, samples)
    verdict = Adoption(task=task, baseline=left, candidate=right)

    if right.critical_errors > left.critical_errors:
        verdict.reason = (
            f"the candidate made {right.critical_errors} critical errors "
            f"against the baseline's {left.critical_errors}. A model that is "
            "right more often and catastrophically wrong in a new way is "
            "worse, not better.")
        return verdict

    gain = right.accuracy - left.accuracy
    if gain < margin:
        verdict.reason = (
            f"the candidate is {gain:+.1%} on accuracy, inside the {margin:.0%} "
            "margin. A few hundred cases cannot tell that from noise.")
        return verdict

    if left.per_call_ms and right.per_call_ms > left.per_call_ms * \
            latency_tolerance:
        verdict.reason = (
            f"the candidate takes {right.per_call_ms:.1f}ms per call against "
            f"{left.per_call_ms:.1f}ms. A narrow classifier that slows the "
            "product down is not a narrow classifier.")
        return verdict

    verdict.adopt = True
    verdict.reason = (
        f"{gain:+.1%} on accuracy over {left.total} cases, no new critical "
        f"errors, {right.per_call_ms:.1f}ms per call.")
    return verdict


def report(decisions: Sequence[Adoption]) -> dict[str, Any]:
    """§32's report: every task, adopted or not, with its numbers.

    Tasks with no candidate appear too. A report listing only the experiments
    somebody ran cannot show which of the seven nobody has looked at.
    """
    by_task = {d.task: d for d in decisions}
    rows = []
    for task in TASKS:
        found = by_task.get(task)
        rows.append(found.to_dict() if found else {
            "task": task, "adopt": False,
            "reason": "no candidate has been measured against the "
                      "deterministic baseline",
            "accuracy_gain": 0.0, "baseline": None, "candidate": None,
        })
    return {
        "version": CLASSIFIER_VERSION,
        "tasks": rows,
        "adopted": [r["task"] for r in rows if r["adopt"]],
        "measured": [r["task"] for r in rows if r["candidate"]],
        "unmeasured": [r["task"] for r in rows if not r["candidate"]],
    }


def wrap(fn: Callable[[Any], Any]) -> Predictor:
    """A plain function as a Predictor. Exists so a caller does not have to
    care that the protocol is callable."""
    return fn


__all__ = ["ACTION", "Adoption", "BASELINES", "CLASSIFIER_VERSION",
           "INTENT", "LATENCY_TOLERANCE", "MARGIN", "Measurement",
           "OBJECTIVES", "PERIOD", "Predictor", "RERANKER", "SAME_TURN",
           "SCOPE", "Sample", "TASKS", "compare", "measure", "report", "wrap"]
