"""
The validator — the wall between what a model asked for and what runs.

Everything a planner produces passes through here, and nothing else does. The
checks are deliberately unforgiving, because each one closes a specific way a
confident-sounding wrong answer could reach a credit committee:

  * unregistered analysis      -> the model invented a capability
  * non-runnable analysis      -> a draft or deprecated method reached production
  * unknown parameter          -> the model thinks the function does something else
  * out-of-contract value      -> a shock multiplier of 40, a top_n of 100,000
  * unknown filter dimension   -> an attempt to slice on something ungoverned
  * unknown filter value       -> a sector that does not exist, silently empty
  * unknown period             -> a quarter the bank has no data for

A rejection is never silently repaired. Dropping an unrecognised parameter and
running anyway would answer a different question from the one asked, which is
worse than refusing.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.engine.contracts import ContractError
from backend.engine.registry import UnknownAnalysisError, get_registry
from backend.orchestration.schema import (
    MAX_PLAN_STEPS,
    AnalysisPlan,
    PlanRejected,
    PlanStep,
)
from backend.orchestration.vocabulary import FILTERABLE_DIMENSIONS, Vocabulary, get_vocabulary

logger = logging.getLogger(__name__)

# Period words the engine resolves itself.
PERIOD_ALIASES = {"latest", "earliest", "previous"}


def validate_step(step: PlanStep, vocab: Vocabulary | None = None) -> list[str]:
    """Check one step, returning every problem found (empty list means valid)."""
    vocab = vocab or get_vocabulary()
    problems: list[str] = []

    if not step.analysis_id:
        return ["A plan step named no analysis."]

    registry = get_registry()
    try:
        registered = registry.require_runnable(step.analysis_id)
    except UnknownAnalysisError:
        return [
            f"'{step.analysis_id}' is not a registered CreditProbe analysis, so it cannot be run. "
            "CreditProbe can only run analyses that exist in the Engine Library."
        ]
    except ContractError as e:
        return [str(e)]

    contract = registered.contract

    # Parameters: the contract is the authority, not this module.
    try:
        contract.validate_params(step.params)
    except ContractError as e:
        problems.append(str(e))

    # Period values must be real, or one of the aliases the engine resolves.
    for label, value in _period_values(step).items():
        if value is None:
            continue
        if value in PERIOD_ALIASES:
            continue
        if vocab.periods and value not in vocab.periods:
            problems.append(
                f"'{value}' is not a reporting period CreditProbe holds data for ({label}). "
                f"Available: {', '.join(vocab.periods)}."
            )

    # Filters: governed dimensions only, and only values present in the data.
    for dimension, value in (step.filters or {}).items():
        if dimension not in FILTERABLE_DIMENSIONS:
            problems.append(
                f"'{dimension}' is not a dimension CreditProbe allows filtering on. "
                f"Allowed: {', '.join(FILTERABLE_DIMENSIONS)}."
            )
            continue
        known = vocab.dimensions.get(dimension)
        if not known:
            continue
        candidates = value if isinstance(value, list) else [value]
        unknown = [str(v) for v in candidates if str(v) not in known and str(v) != "All"]
        if unknown:
            problems.append(
                f"{dimension}: {', '.join(sorted(set(unknown)))} "
                f"{'is' if len(unknown) == 1 else 'are'} not present in the governed data."
            )

    return problems


def _period_values(step: PlanStep) -> dict[str, Any]:
    """Every value in a step that is supposed to name a reporting period."""
    out: dict[str, Any] = {"period": step.period}
    for key in ("period", "from_period", "to_period", "compare_period"):
        if key in step.params:
            out[key] = step.params[key]
    return out


def validate_plan(plan: AnalysisPlan, vocab: Vocabulary | None = None) -> AnalysisPlan:
    """Validate a whole plan, raising PlanRejected with every reason.

    Returns the plan unchanged on success. It is returned rather than mutated so
    that the caller cannot accidentally execute an unvalidated object: the
    executor only accepts what this function handed back.
    """
    vocab = vocab or get_vocabulary()
    reasons: list[str] = []

    if not plan.steps:
        reasons.append("The plan contained no analyses to run.")
    if len(plan.steps) > MAX_PLAN_STEPS:
        reasons.append(
            f"The plan asked for {len(plan.steps)} analyses; CreditProbe runs at most "
            f"{MAX_PLAN_STEPS} for one question."
        )

    for index, step in enumerate(plan.steps, start=1):
        for problem in validate_step(step, vocab):
            reasons.append(f"Step {index} ({step.analysis_id or 'unnamed'}): {problem}")

    if reasons:
        logger.warning("Plan rejected for %r: %s", plan.question, reasons)
        raise PlanRejected(reasons)
    return plan


__all__ = ["PERIOD_ALIASES", "PlanRejected", "validate_plan", "validate_step"]
