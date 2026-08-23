"""
The Engine Registry — the menu the AI may order from.

Every analytical capability in IPM is registered here with a declared contract
(see contracts.py) and a bound Python implementation. Three things depend on it:

  * the planner   — may only name registered, runnable analyses
  * the validator — rejects any plan referring to something not registered
  * Engine Builder — displays the library, its metadata and its certification

Registering is a decorator:

    @register(AnalysisContract(id="stage_distribution", ...))
    def stage_distribution(context: AnalysisContext, params: dict) -> AnalysisResult:
        ...

Phase 2 adds the ten certified analyses. This module is the mechanism they plug
into, so it exists and is tested first.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.engine.contracts import AnalysisContract, Category, Certification, ContractError

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """The structured output of one engine function.

    Deliberately *not* a bare DataFrame. A number without its unit, its row count
    and the warnings raised while producing it is not a defensible result — and
    the narrative layer receives exactly this object, never the underlying rows,
    so everything it needs to quote a figure correctly has to be in here.
    """

    # Tabular output — the rows a chart or table renders.
    rows: list[dict[str, Any]] = field(default_factory=list)
    # Scalar headline figures, e.g. {"total_ead": 48600.0, "npl_ratio": 4.2}.
    values: dict[str, Any] = field(default_factory=dict)
    # Units keyed by output name, from the contract.
    units: dict[str, str] = field(default_factory=dict)
    # How many source rows the calculation consumed — shown in the Trace node.
    input_row_count: int = 0
    # Non-fatal observations: a small sample, a suppressed division, a stale period.
    warnings: list[str] = field(default_factory=list)
    # Anything the visualization layer needs that is not a number.
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "values": self.values,
            "units": self.units,
            "input_row_count": self.input_row_count,
            "warnings": self.warnings,
            "meta": self.meta,
        }


# An engine function takes one ExecutionContext — which carries the explicit
# analysis context, the validated parameters, the governed reader and the trace
# being written — and returns a structured result. No globals, no LLM.
#
# Typed loosely to avoid a circular import: execution.py imports the trace model,
# which the registry does not need to know about.
EngineFunction = Callable[[Any], AnalysisResult]


class RegistryError(RuntimeError):
    pass


class UnknownAnalysisError(RegistryError):
    """Raised when a plan names an analysis that does not exist. This is the error
    that stops an invented calculation from ever running."""


@dataclass(frozen=True)
class RegisteredAnalysis:
    contract: AnalysisContract
    fn: EngineFunction

    @property
    def id(self) -> str:
        return self.contract.id

    @property
    def version(self) -> str:
        return self.contract.version


class Registry:
    """All registered analytical capabilities, keyed by id."""

    def __init__(self) -> None:
        self._items: dict[str, RegisteredAnalysis] = {}

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, analysis_id: object) -> bool:
        return analysis_id in self._items

    def add(self, contract: AnalysisContract, fn: EngineFunction) -> None:
        if contract.id in self._items:
            raise RegistryError(
                f"Analysis '{contract.id}' is already registered "
                f"(version {self._items[contract.id].version})."
            )
        self._items[contract.id] = RegisteredAnalysis(contract=contract, fn=fn)
        logger.debug("Registered analysis %s v%s (%s)", contract.id, contract.version,
                     contract.certification.value)

    def get(self, analysis_id: str) -> RegisteredAnalysis:
        try:
            return self._items[analysis_id]
        except KeyError:
            raise UnknownAnalysisError(
                f"'{analysis_id}' is not a registered IPM analysis. "
                f"Available: {', '.join(self.ids()) or '(none registered yet)'}"
            ) from None

    def contract(self, analysis_id: str) -> AnalysisContract:
        return self.get(analysis_id).contract

    def ids(self) -> list[str]:
        return sorted(self._items)

    def all(self) -> list[RegisteredAnalysis]:
        return [self._items[i] for i in self.ids()]

    def contracts(self) -> list[AnalysisContract]:
        return [a.contract for a in self.all()]

    def by_category(self, category: Category) -> list[RegisteredAnalysis]:
        return [a for a in self.all() if a.contract.category is category]

    def certified(self) -> list[RegisteredAnalysis]:
        return [a for a in self.all() if a.contract.is_certified]

    def runnable(self) -> list[RegisteredAnalysis]:
        """What the planner is allowed to choose from. Draft and deprecated
        analyses are visible in Engine Builder but are not on the menu."""
        return [a for a in self.all() if a.contract.is_runnable]

    def require_runnable(self, analysis_id: str) -> RegisteredAnalysis:
        """Fetch an analysis, refusing one that may not be executed."""
        item = self.get(analysis_id)
        if not item.contract.is_runnable:
            raise ContractError(
                f"Analysis '{analysis_id}' is {item.contract.certification.value} "
                "and may not be executed."
            )
        return item

    def summary(self) -> dict[str, Any]:
        by_cert: dict[str, int] = {}
        for a in self.all():
            key = a.contract.certification.value
            by_cert[key] = by_cert.get(key, 0) + 1
        return {"total": len(self), "by_certification": by_cert, "ids": self.ids()}


# The process-wide registry.
REGISTRY = Registry()


def register(contract: AnalysisContract) -> Callable[[EngineFunction], EngineFunction]:
    """Decorator binding an implementation to its declared contract."""

    def decorator(fn: EngineFunction) -> EngineFunction:
        REGISTRY.add(contract, fn)
        return fn

    return decorator


def get_registry() -> Registry:
    """Return the registry, importing the function modules on first use.

    The import is what triggers the @register decorators. Doing it lazily keeps
    module import order from mattering and avoids a circular import between the
    registry and the functions that register into it.
    """
    if len(REGISTRY) == 0:
        try:
            from backend.engine import functions  # noqa: F401  (registers on import)
        except ImportError:  # pragma: no cover - only while functions/ is empty
            logger.debug("No engine functions to load yet.")
    return REGISTRY


__all__ = [
    "REGISTRY",
    "AnalysisResult",
    "Certification",
    "EngineFunction",
    "RegisteredAnalysis",
    "Registry",
    "RegistryError",
    "UnknownAnalysisError",
    "get_registry",
    "register",
]
