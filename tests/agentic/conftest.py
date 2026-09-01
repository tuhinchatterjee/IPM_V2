"""
Fixtures for the agentic suite.

The agentic tests never call a model. §0 and §83 are explicit that no live
Anthropic call may be made in this phase and no API credits may be spent, and
the way that is guaranteed here is structural rather than by discipline: the
orchestration entry points take an `answer_one` callable, and every test in this
package passes a fake. There is no code path from these tests to a provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeReading:
    """The fields `officers` and the planner actually read off a Reading."""

    datasets: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    periods: tuple[str, ...] = ()
    period_requirement: str = "none"
    grain: str = ""
    dimensions: tuple[str, ...] = ()
    operation_count: int = 0
    confidence: float = 0.9
    clarification: str = ""
    intent: str = "ANALYSIS"


@pytest.fixture
def reading() -> Any:
    return FakeReading


@dataclass
class FakeResult:
    """What a governed analysis returns, reduced to what an agent reads."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)
    rows_read: int = 0
    fingerprint: str = "fp_test"
