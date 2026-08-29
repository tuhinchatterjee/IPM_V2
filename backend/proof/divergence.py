"""
Whether the officer badge means anything. §3.

    §3: "A different officer badge is not proof of a different execution
         path."
    §3: "Add assertions that materially different request classes produce
         materially different governed execution paths."

The failure this module exists to catch
-----------------------------------------
An agentic layer that computes an officer level, renders a different title,
and then runs the same code either way. Every screenshot looks right. Every
unit test passes — `select()` genuinely returns CHIEF_ORCHESTRATOR for the
hard question. And the product is decoration, because nothing downstream of
the badge behaves differently.

Catching that requires comparing two runs against each other rather than
checking either one on its own, which is why this is a module and not a
handful of assertions: the property is about the RELATIONSHIP between
execution paths, and no single-run test can express it.

What counts as materially different
-------------------------------------
Not the title. Not the label. Six observable things that cost time and money,
because those are the ones a decorative implementation cannot fake:

    orchestration      whether an orchestrator ran at all
    specialists        how many, and which
    tasks              how many tasks were planned and executed
    tools              how many governed executions occurred
    datasets           how much data was touched
    trace shape        which nodes the run actually left behind

A pair of requests that differ in officer level and in NONE of these is a
`DECORATIVE` verdict, and it fails the test. That is the assertion §3 asks
for, stated as a property rather than as a hope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.proof.probe import Probe

DIVERGENCE_VERSION = "1.0.0"

#: What we compare. Each is (field on the probe, human label, whether a
#: difference in it is EXPENSIVE — i.e. really cost something).
AXES: tuple[tuple[str, str, bool], ...] = (
    ("orchestrated", "an orchestrator ran", True),
    ("agent_count", "specialist count", True),
    ("task_count", "task count", True),
    ("tool_call_count", "governed executions", True),
    ("dataset_count", "datasets touched", True),
    ("trace_node_count", "Trace nodes recorded", False),
    ("coordinated", "the run was coordinated", True),
    # Governed work actually executed, not the shape of an AnalysisPlan. A
    # broad investigation runs its probes without one, so `plan_steps` was 0
    # on the most expensive request in the product and made every escalation
    # to it look like a step DOWN.
    ("governed_work", "governed analyses executed", True),
)

MATERIAL = "MATERIAL"
DECORATIVE = "DECORATIVE"
SAME_CLASS = "SAME_CLASS"

VERDICTS: tuple[str, ...] = (MATERIAL, DECORATIVE, SAME_CLASS)

VERDICT_MEANS: dict[str, str] = {
    MATERIAL: "The two requests took materially different governed execution "
              "paths. The officer level corresponds to real work.",
    DECORATIVE: "The two requests were assigned different officers and ran "
                "the same way. The badge is decoration.",
    SAME_CLASS: "The two requests were assigned the same officer, so there "
                "is nothing to prove about divergence between them.",
}


def _axis(probe: Probe, name: str) -> Any:
    """Read one comparison axis, deriving the counted ones."""
    if name == "tool_call_count":
        return len(probe.tool_calls)
    if name == "dataset_count":
        return len(probe.datasets)
    if name == "trace_node_count":
        return len(probe.trace_nodes)
    if name == "governed_work":
        return max(probe.plan_steps, probe.executed_steps, probe.probes)
    return getattr(probe, name, None)


@dataclass
class Difference:
    axis: str
    label: str
    lower: Any
    higher: Any
    expensive: bool

    @property
    def differs(self) -> bool:
        return self.lower != self.higher

    def to_dict(self) -> dict[str, Any]:
        return {"axis": self.axis, "label": self.label, "lower": self.lower,
                "higher": self.higher, "differs": self.differs,
                "expensive": self.expensive}


@dataclass
class Comparison:
    """Two probes at different officer levels, compared."""

    lower: Probe
    higher: Probe
    differences: list[Difference] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.lower.officer_level == self.higher.officer_level:
            return SAME_CLASS
        # Only EXPENSIVE differences count. A run that recorded two more
        # Trace nodes and did nothing else did not do more work; it wrote
        # more down about doing the same work.
        if any(d.differs and d.expensive for d in self.differences):
            return MATERIAL
        return DECORATIVE

    @property
    def expensive_differences(self) -> list[Difference]:
        return [d for d in self.differences if d.differs and d.expensive]

    @property
    def unmeasured_axes(self) -> list[str]:
        """Axes the higher run reports NOTHING on while the lower reports
        something.

        Kept apart from a regression on purpose, because they are different
        facts and conflating them makes the instrument lie. A coordinated
        review reports zero datasets and zero tool calls not because it read
        less, but because its Investigation does not aggregate what its
        specialist sub-analyses touched — those were persisted as separate
        Investigations. That is a real gap in what the Trace can show, and
        it is recorded as a gap rather than reported as the run having done
        less work than a single-dataset query.
        """
        gaps: list[str] = []
        for difference in self.differences:
            if not difference.expensive:
                continue
            lower, higher = difference.lower, difference.higher
            if isinstance(lower, bool) or isinstance(higher, bool):
                continue
            if (isinstance(lower, int | float)
                    and isinstance(higher, int | float)
                    and lower > 0 and higher == 0):
                gaps.append(difference.axis)
        return gaps

    @property
    def regressions(self) -> list[str]:
        """Axes where the higher officer genuinely did LESS.

        Both sides measured, and the higher one smaller. That is an
        escalation that took a different, smaller route and put a bigger
        badge on it.
        """
        found: list[str] = []
        unmeasured = set(self.unmeasured_axes)
        for difference in self.differences:
            if not difference.expensive or difference.axis in unmeasured:
                continue
            lower, higher = difference.lower, difference.higher
            if isinstance(lower, bool) or isinstance(higher, bool):
                if lower and not higher:
                    found.append(difference.axis)
                continue
            if (isinstance(lower, int | float)
                    and isinstance(higher, int | float) and higher < lower):
                found.append(difference.axis)
        return found

    @property
    def escalation_is_monotonic(self) -> bool:
        """The higher officer did at least as much everywhere it can be
        compared."""
        return not self.regressions

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "verdict_means": VERDICT_MEANS[self.verdict],
            "lower": {"label": self.lower.label,
                      "officer_level": self.lower.officer_level,
                      "officer_title": self.lower.officer_title,
                      "flow": self.lower.flow},
            "higher": {"label": self.higher.label,
                       "officer_level": self.higher.officer_level,
                       "officer_title": self.higher.officer_title,
                       "flow": self.higher.flow},
            "differences": [d.to_dict() for d in self.differences],
            "expensive_differences": [d.axis
                                      for d in self.expensive_differences],
            "monotonic": self.escalation_is_monotonic,
            "regressions": self.regressions,
            "unmeasured_axes": self.unmeasured_axes,
        }


def compare(lower: Probe, higher: Probe) -> Comparison:
    """Compare two probes. `lower` should be the cheaper officer level."""
    differences = [
        Difference(axis=name, label=label,
                   lower=_axis(lower, name), higher=_axis(higher, name),
                   expensive=expensive)
        for name, label, expensive in AXES]
    return Comparison(lower=lower, higher=higher, differences=differences)


def matrix(probes: list[Probe]) -> dict[str, Any]:
    """Every adjacent officer-level pair, compared.

    Adjacent rather than all-pairs: the interesting question is whether each
    STEP up the ladder buys anything. A Credit Analyst and a Chief
    Orchestrator differing tells you little if the two middle levels are
    indistinguishable from their neighbours, which is the shape a
    half-implemented ladder actually takes.
    """
    by_level: dict[int, list[Probe]] = {}
    for probe in probes:
        if probe.officer_level is None or not probe.ok:
            continue
        by_level.setdefault(probe.officer_level, []).append(probe)

    levels = sorted(by_level)
    comparisons: list[Comparison] = []
    for lower_level, higher_level in zip(levels, levels[1:], strict=False):
        comparisons.append(compare(by_level[lower_level][0],
                                   by_level[higher_level][0]))

    decorative = [c for c in comparisons if c.verdict == DECORATIVE]
    return {
        "version": DIVERGENCE_VERSION,
        "levels_observed": levels,
        "comparisons": [c.to_dict() for c in comparisons],
        "material": len([c for c in comparisons if c.verdict == MATERIAL]),
        "decorative": len(decorative),
        "monotonic": all(c.escalation_is_monotonic for c in comparisons),
        "unmeasured_axes": sorted({axis for c in comparisons
                                   for axis in c.unmeasured_axes}),
        "verdict": (DECORATIVE if decorative else
                    MATERIAL if comparisons else SAME_CLASS),
        "note": ("Only expensive axes count. A run that recorded more Trace "
                 "nodes and did nothing else did not do more work."),
    }
