"""
When IPM should ask instead of answering.

The rule, from docs/PRODUCT_SPEC.md:

    Do not silently assume a period unless the analysis definition explicitly
    permits a governed default.

"Which sectors deteriorated?" has no answer until someone says *since when*.
Picking a comparison would produce a confident number answering a question
nobody asked, and it would carry a certification tick while doing it.

The opposite failure matters just as much. "What is our NPL ratio?" is a
point-in-time question with a governed default — the latest published period —
and interrogating the user about history there turns a product into a form.

So clarification is narrow by construction. It fires only when all three hold:

    1. the primary analysis genuinely spans time
       (period_requirement is not POINT_IN_TIME)
    2. its contract does NOT carry a governed default
       (governed_default_period is False)
    3. the question did not already settle the period

and it never fires when the data cannot offer a real choice.
"""

from __future__ import annotations

import logging

from backend.engine.contracts import AnalysisContract
from backend.engine.registry import get_registry
from backend.orchestration.periods import comparison_choices, detect_frequency
from backend.orchestration.schema import AnalysisPlan, Clarification
from backend.orchestration.vocabulary import Vocabulary, get_vocabulary

logger = logging.getLogger(__name__)


def _contract(analysis_id: str) -> AnalysisContract | None:
    try:
        return get_registry().contract(analysis_id)
    except Exception:
        return None


def needed_clarification(plan: AnalysisPlan,
                         vocab: Vocabulary | None = None) -> Clarification | None:
    """The one question IPM must ask before it can run this plan, or None."""
    vocab = vocab or get_vocabulary()

    primary = plan.primary
    if primary is None:
        return None

    contract = _contract(primary.analysis_id)
    if contract is None or not contract.needs_period_clarification:
        return None

    if plan.scope.period_specified:
        return None

    choices = comparison_choices(vocab.periods)
    if len(choices) < 2:
        # One period, or none. There is nothing to choose between, so asking
        # would be theatre — the executor runs with whatever exists and the
        # answer says which periods it used.
        logger.info("Period clarification skipped: only %d comparison(s) available.",
                    len(choices))
        return None

    unit = {
        "quarterly": "quarters",
        "monthly": "months",
        "annual": "years",
    }.get(detect_frequency(vocab.periods).value, "periods")

    return Clarification(
        kind="period",
        question="Which periods should IPM compare?",
        detail=(
            f"The book is reported in {unit}. "
            f"{len(vocab.periods)} periods are published, "
            f"{vocab.periods[0]} to {vocab.periods[-1]}."
        ),
        options=[c.to_dict() for c in choices],
        because=(
            f"{contract.name} measures change between two reporting periods, and the "
            "question did not say which. IPM will not choose one for you."
        ),
        allow_custom=True,
    )


__all__ = ["needed_clarification"]
