"""
Ask CreditProbe, from question to answer.

This is the front door, and the order of its stages is the architecture:

    question
      → READ      what kind of request is this, and what is it about
      → ROUTE     metadata question, method question, or an analysis
      → PLAN      an Analytical IR, from concepts rather than from phrases
      → VALIDATE  against the governed catalogue (backend/runtime/validation)
      → EXECUTE   parameterised SQL and allowlisted kernels
      → INTERPRET the model reads the RESULT, never the data

Two things about that order matter more than anything else in this module.

**Nothing computes before something has decided the request is a computation.**
The old front door assumed every question was a request for a number, so a
question about the catalogue came back as a portfolio summary. Here a
non-analytical request never reaches the engine at all.

**The model plans; it does not calculate.** It emits a structured reading and,
where configured, an analytical plan. Every figure comes back from the runtime.
There is no branch in this file where model output becomes a number.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.llm import get_provider, is_configured, provider_status
from backend.orchestration import analysis_planner as ap
from backend.orchestration import capability as cap
from backend.orchestration import handlers
from backend.orchestration.context import retrieve
from backend.orchestration.router import read_request

logger = logging.getLogger(__name__)

#: The stages the UI shows while a question is being answered.
STAGES = [
    {"id": "reading", "label": "Reading the request"},
    {"id": "retrieving", "label": "Retrieving governed metadata"},
    {"id": "planning", "label": "Composing the analysis"},
    {"id": "running", "label": "Running the governed runtime"},
    {"id": "interpreting", "label": "Reading the result"},
]


def mode() -> dict[str, Any]:
    """What the product says about how it is answering questions.

    The honesty rule lives here. With no provider key the label is LIMITED
    OFFLINE MODE and the description says what is constrained — it does not
    describe a deterministic phrase reader as though it were full natural
    language understanding.
    """
    from backend.orchestration.vocabulary import get_vocabulary

    status = provider_status()
    vocab = get_vocabulary()
    configured = status.configured

    return {
        "mode": "model" if configured else "offline",
        "configured": configured,
        "label": "CreditProbe AI" if configured else "LIMITED OFFLINE MODE",
        "provider": status.provider,
        "model_name": status.model or None,
        "state": status.state,
        "state_label": status.label,
        "description": (
            status.detail if configured else
            "No AI provider key is configured, so CreditProbe is in LIMITED "
            "OFFLINE MODE. Questions are read by a deterministic semantic "
            "planner over the governed catalogue: it understands credit "
            "concepts, governed fields and the relationship model, but not "
            "arbitrary phrasing, and it will ask rather than guess. Every "
            "figure is still computed by the governed runtime."),
        "limitations": ([] if configured else [
            "Questions phrased unusually may not be understood.",
            "Follow-up questions carry less context.",
            "The written interpretation is assembled from the result rather "
            "than composed.",
        ]),
        "stages": STAGES,
        "periods": list(vocab.periods),
        "latest_period": vocab.periods[-1] if vocab.periods else "",
        "dimensions": {k: len(v) for k, v in vocab.dimensions.items()},
        "capabilities": [
            {"id": name, "label": cap.LABELS[name],
             "computes": name in cap.COMPUTES}
            for name in cap.ALL
        ],
    }


class Answered:
    """What the orchestrator produces, before it is shaped for the API."""

    def __init__(self, *, reading: cap.Reading, question: str) -> None:
        self.reading = reading
        self.question = question
        self.result: handlers.HandlerResult | None = None
        self.build: ap.AnalysisBuild | None = None
        self.runtime: Any = None
        self.clarification: str = ""
        self.duration_ms: int = 0

    @property
    def computed(self) -> bool:
        return self.runtime is not None


def answer(question: str, *, context: Any = None) -> Answered:
    """Read, route, and either answer from metadata or compose and run.

    Raises nothing for an unreadable question: it comes back as a clarification,
    because a question CreditProbe cannot read is a conversation rather than an
    error.
    """
    started = time.perf_counter()
    context = context or retrieve(question)
    reading = read_request(question, context=context)

    answered = Answered(reading=reading, question=question)

    # The router asked for something back.
    if reading.clarification:
        answered.clarification = reading.clarification
        answered.duration_ms = int((time.perf_counter() - started) * 1000)
        return answered

    # A reading nobody should act on. Below the floor CreditProbe asks rather
    # than running, because a confident answer to the wrong question is the
    # failure this whole path exists to prevent.
    if reading.confidence < cap.MIN_CONFIDENCE and not reading.computes:
        answered.clarification = (
            "CreditProbe is not sure what that is asking for. Name the figure "
            "or the dataset you mean and it will compose the analysis.")
        answered.duration_ms = int((time.perf_counter() - started) * 1000)
        return answered

    # Not an analysis: answer from governed metadata, with no engine call.
    handled = handlers.handle(question, reading, context)
    if handled is not None:
        answered.result = handled
        answered.duration_ms = int((time.perf_counter() - started) * 1000)
        return answered

    # An analysis. Plan it, validate it, run it.
    from backend.runtime.executor import ExecutionClass, execute

    try:
        build = ap.plan(reading, context, question=question)
    except ap.CannotPlan as e:
        answered.clarification = e.clarification
        answered.duration_ms = int((time.perf_counter() - started) * 1000)
        return answered

    answered.build = build
    answered.runtime = execute(
        build.plan, question=question, intent=build.summary,
        certification=ExecutionClass.DYNAMIC,
        population_steps=_population_steps(build))
    answered.duration_ms = int((time.perf_counter() - started) * 1000)
    return answered


def _population_steps(build: ap.AnalysisBuild) -> list[str] | None:
    """Which steps the reconciliation should count.

    Only the two-period shapes have a population that narrows across several
    steps; a single-period aggregate has one scan and one group, and
    reconciling that would be a table with two rows saying nothing.
    """
    if build.shape not in (ap.COHORT, ap.MOVEMENT):
        return None
    return [str(op.get("id")) for op in build.plan.get("operations") or []]


__all__ = ["STAGES", "Answered", "answer", "get_provider", "is_configured",
           "mode"]
