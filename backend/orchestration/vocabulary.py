"""
The vocabulary a planner is allowed to use.

Two rules meet here.

    1. The planner may only name registered analyses and their declared
       parameters. That list comes from the Engine Registry.
    2. The planner may only name filter values that genuinely exist in the
       governed data. That list is read from the Data Access Layer.

Both matter for the same reason. If "Real Estate" were a string the planner
made up, "Stress the Real Estate portfolio" would silently return an empty book
and the narrative would confidently describe nothing. Because the sector list is
read from the published data, a sector the planner cannot match is reported as
unmatched instead.

Nothing in this module computes a credit figure. It reads names.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from backend.data_access import get_data_source
from backend.data_access.context import AnalysisContext
from backend.data_access.protocol import DataAccessError
from backend.engine.helpers import FACILITY
from backend.engine.registry import get_registry

logger = logging.getLogger(__name__)

# The dimensions a question may filter on. Low-cardinality governed fields only:
# an account id is not something anyone asks a question about.
FILTERABLE_DIMENSIONS = [
    "sector",
    "region",
    "segment",
    "product_type",
    "rating_bucket",
    "country",
    "ifrs9_stage",
]

MAX_VALUES_PER_DIMENSION = 60

# Dimensions never inferred from free text, because their values are short codes
# a question mentions descriptively rather than as a filter.
AMBIGUOUS_DIMENSIONS = {"ifrs9_stage"}

# A value shorter than this is too likely to appear inside an unrelated word.
MIN_MATCHABLE_VALUE = 4


@dataclass(frozen=True)
class Vocabulary:
    """Everything the planner is permitted to refer to, read from live sources."""

    periods: list[str] = field(default_factory=list)
    latest: str | None = None
    previous: str | None = None
    earliest: str | None = None
    # dimension name -> the values actually present in the latest period
    dimensions: dict[str, list[str]] = field(default_factory=dict)
    # analysis id -> a compact contract description for the planner
    analyses: dict[str, dict[str, Any]] = field(default_factory=dict)

    def resolve_dimension_value(self, text: str) -> tuple[str, str] | None:
        """Find a governed dimension value mentioned in free text.

        Matching is done against the real values, longest first, so "Commercial
        Real Estate" is preferred over "Real Estate" when both exist. Returns
        (dimension, value) or None.

        Short and numeric values are deliberately not matched. The IFRS 9 stage
        values are "1", "2", "3", and "Why has Stage 2 increased?" is a question
        *about* Stage 2 — not a request to throw away every other stage before
        answering it. A silent filter there would have produced a confident
        answer to a different question.
        """
        haystack = " " + _normalise(text) + " "
        best: tuple[str, str] | None = None
        best_len = 0
        for dimension, values in self.dimensions.items():
            if dimension in AMBIGUOUS_DIMENSIONS:
                continue
            for value in values:
                if len(str(value)) < MIN_MATCHABLE_VALUE or not re.search(r"[a-z]", str(value).lower()):
                    continue
                needle = " " + _normalise(value) + " "
                if needle in haystack and len(value) > best_len:
                    best, best_len = (dimension, value), len(value)
        return best

    def other_values(self, dimension: str, excluded: str) -> list[str]:
        """Every value of a dimension except one.

        This is how an exclusion is expressed. The governed reader filters by
        equality against a list of permitted values, so "exclude Real Estate"
        becomes "include every other sector" — an instruction the data layer can
        already enforce, rather than a new query capability.
        """
        return [v for v in self.dimensions.get(dimension, []) if v != excluded]

    def to_dict(self) -> dict[str, Any]:
        return {
            "periods": self.periods,
            "latest": self.latest,
            "previous": self.previous,
            "earliest": self.earliest,
            "dimensions": self.dimensions,
            "analyses": self.analyses,
        }


def _normalise(text: str) -> str:
    """Lower-case, punctuation-free words.

    Punctuation has to go: "Exclude Real Estate." ends in a full stop, and a
    naive substring match for " real estate " would miss it and report the
    instruction as not understood.
    """
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def _analysis_menu() -> dict[str, dict[str, Any]]:
    """The registered analyses a plan may name, with their declared parameters."""
    menu: dict[str, dict[str, Any]] = {}
    for item in get_registry().runnable():
        c = item.contract
        menu[c.id] = {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "category": c.category.value,
            "certification": c.certification.value,
            "requires_compare_period": c.requires_compare_period,
            # Registry metadata the planner reasons over rather than guessing
            # from the name. `trigger_questions` is also what a clarification
            # offers when CreditProbe has not understood, so the list of things
            # it can do is read from the registry and cannot drift out of date.
            "when_to_use": getattr(c, "when_to_use", "") or "",
            "limitations": getattr(c, "limitations", "") or "",
            "trigger_questions": list(getattr(c, "trigger_questions", []) or []),
            "answer_shape": getattr(c.answer_shape, "value", ""),
            "period_requirement": getattr(c.period_requirement, "value", ""),
            "required_domains": list(getattr(c, "required_domains", []) or []),
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type.value,
                    "description": p.description,
                    "default": p.default,
                    "allowed_values": p.allowed_values,
                }
                for p in c.parameters
            ],
        }
    return menu


def _dimension_values(period: str | None) -> dict[str, list[str]]:
    if period is None:
        return {}
    source = get_data_source()
    try:
        from backend.data_access import get_catalog

        spec = get_catalog().dataset(FACILITY)
    except Exception:  # pragma: no cover - catalogue unavailable
        return {}

    ctx = AnalysisContext(period=period)
    out: dict[str, list[str]] = {}
    for name in FILTERABLE_DIMENSIONS:
        if name not in spec.fields:
            continue
        try:
            frame = source.aggregate(FACILITY, context=ctx, group_by=[name],
                                     measures={"ead": "sum"}, period=period)
        except DataAccessError:
            continue
        values = [str(v) for v in frame[name].dropna().tolist()][:MAX_VALUES_PER_DIMENSION]
        if values:
            out[name] = values
    return out


@lru_cache(maxsize=1)
def get_vocabulary() -> Vocabulary:
    """Build the vocabulary, cached for the life of the process.

    Cached because it is read on every question and changes only when a dataset
    is published — at which point `reset_vocabulary()` is called.
    """
    periods: list[str] = []
    try:
        periods = list(get_data_source().periods(FACILITY))
    except Exception as e:  # pragma: no cover - no data published yet
        logger.warning("Vocabulary could not read periods: %s", e)

    latest = periods[-1] if periods else None
    previous = periods[-2] if len(periods) > 1 else None
    earliest = periods[0] if periods else None

    return Vocabulary(
        periods=periods,
        latest=latest,
        previous=previous,
        earliest=earliest,
        dimensions=_dimension_values(latest),
        analyses=_analysis_menu(),
    )


def reset_vocabulary() -> None:
    """Forget the cached vocabulary — called after a dataset is published."""
    get_vocabulary.cache_clear()


__all__ = [
    "FILTERABLE_DIMENSIONS",
    "Vocabulary",
    "get_vocabulary",
    "reset_vocabulary",
]
