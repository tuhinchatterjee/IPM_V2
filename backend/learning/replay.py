"""
The Replay Lab: current production versus a candidate. §37.

What it compares and why each axis is there
---------------------------------------------
    officer     a candidate that gets the right answer through a Chief
                Orchestrator where production used a Credit Analyst has made
                the product more expensive, not better
    agents      the same, one level down
    plan        two plans that produce the same number are not the same
                answer if one of them read a different dataset
    datasets    where a silent scope change shows up
    tools       where a silent capability change shows up
    result      the figures
    assurance   the operational verdict
    reference   the independent answer, where one exists
    answer      the prose, which is what the user actually read
    abstention  a candidate that answers what production refused has either
                fixed an over-cautious abstention or invented an answer, and
                which one it is cannot be guessed
    latency     what it cost in time
    calls       what it cost in money

Improvements and regressions are reported SEPARATELY and are never netted. A
release that fixes six cases and breaks one that matters is a worse release,
and a single "net +5" number is how it ships.

Nothing here calls a provider
-------------------------------
A replay runs the deterministic governed path. §19: "Do not automatically call
an external LLM without explicit policy/cost approval. Deterministic replay
may run locally."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REPLAY_VERSION = "1.0.0"

#: The axes, and whether a difference on one is MATERIAL — worth blocking a
#: release over — or informational.
AXES: tuple[tuple[str, bool, str], ...] = (
    ("officer", True, "The officer level the work was done at."),
    ("agents", True, "Which specialists were engaged."),
    ("plan", True, "The plan fingerprint."),
    ("datasets", True, "Which governed sources were read."),
    ("tools", False, "Which tools were called."),
    ("result", True, "The figures returned."),
    ("assurance", True, "The operational assurance verdict."),
    ("reference", True, "The independent reference answer, where one exists."),
    ("answer", False, "The prose the user read."),
    ("abstention", True, "Whether it answered, clarified or refused."),
    ("latency_ms", False, "How long it took."),
    ("model_calls", False, "How many model calls it would have cost."),
)

AXIS_NAMES: tuple[str, ...] = tuple(a for a, _, _ in AXES)
MATERIAL_AXES: frozenset[str] = frozenset(a for a, material, _ in AXES
                                          if material)
AXIS_MEANS: dict[str, str] = {a: means for a, _, means in AXES}

IMPROVED = "IMPROVED"
REGRESSED = "REGRESSED"
UNCHANGED = "UNCHANGED"
#: One side recorded nothing on this axis, so nothing can be concluded. Kept
#: apart from UNCHANGED, which is a finding; this is the absence of one.
UNMEASURED = "UNMEASURED"

VERDICTS: tuple[str, ...] = (IMPROVED, REGRESSED, UNCHANGED, UNMEASURED)


@dataclass
class AxisResult:
    """One axis, on one case."""

    axis: str
    verdict: str
    production: Any = None
    candidate: Any = None
    detail: str = ""

    @property
    def material(self) -> bool:
        return self.axis in MATERIAL_AXES and self.verdict == REGRESSED

    def to_dict(self) -> dict[str, Any]:
        return {"axis": self.axis, "verdict": self.verdict,
                "production": self.production, "candidate": self.candidate,
                "detail": self.detail, "material": self.material,
                "means": AXIS_MEANS.get(self.axis, "")}


@dataclass
class CaseReplay:
    """One case, run both ways."""

    case_id: str
    question: str = ""
    axes: list[AxisResult] = field(default_factory=list)
    #: Whether the case was expected to pass. A critical case that regresses
    #: blocks the release however well everything else did.
    critical: bool = False

    @property
    def improved(self) -> list[AxisResult]:
        return [a for a in self.axes if a.verdict == IMPROVED]

    @property
    def regressed(self) -> list[AxisResult]:
        return [a for a in self.axes if a.verdict == REGRESSED]

    @property
    def material_regressions(self) -> list[AxisResult]:
        return [a for a in self.axes if a.material]

    @property
    def unmeasured(self) -> list[str]:
        return [a.axis for a in self.axes if a.verdict == UNMEASURED]

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "question": self.question,
                "critical": self.critical,
                "axes": [a.to_dict() for a in self.axes],
                "improved": [a.axis for a in self.improved],
                "regressed": [a.axis for a in self.regressed],
                "material_regressions": [a.axis
                                         for a in self.material_regressions],
                "unmeasured": self.unmeasured}


@dataclass
class Run:
    """A whole replay: every case, both ways."""

    run_id: str = ""
    release_id: str = ""
    tenant: str = ""
    cases: list[CaseReplay] = field(default_factory=list)
    #: Set by a reviewer who has looked and decided this must not ship.
    blocked_by: str = ""
    blocked_because: str = ""

    @property
    def improved(self) -> int:
        return sum(1 for c in self.cases if c.improved and not c.regressed)

    @property
    def regressed(self) -> int:
        return sum(1 for c in self.cases if c.regressed)

    @property
    def critical_regressions(self) -> list[CaseReplay]:
        return [c for c in self.cases
                if c.critical and c.material_regressions]

    @property
    def clean(self) -> bool:
        """Whether this candidate may be put to a release gate at all.

        Not "whether it is better". A replay with no critical regression is
        eligible to be evaluated; deciding it is an improvement is the gate's
        job, and conflating the two is how a neutral release ships as a win.
        """
        return not self.critical_regressions and not self.blocked_by

    def sentence(self) -> str:
        if self.blocked_by:
            return (f"Blocked by {self.blocked_by}: {self.blocked_because}")
        parts = [f"{len(self.cases)} case(s) replayed",
                 f"{self.improved} improved",
                 f"{self.regressed} regressed"]
        if self.critical_regressions:
            parts.append(f"{len(self.critical_regressions)} CRITICAL "
                         "regression(s), which block the release")
        return "; ".join(parts) + "."

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "release_id": self.release_id,
                "tenant": self.tenant,
                "cases": [c.to_dict() for c in self.cases],
                "improved": self.improved, "regressed": self.regressed,
                "critical_regressions": [c.case_id
                                         for c in self.critical_regressions],
                "clean": self.clean, "blocked_by": self.blocked_by,
                "blocked_because": self.blocked_because,
                "explanation": self.sentence(),
                "version": REPLAY_VERSION}


def _compare(axis: str, production: Any, candidate: Any,
             *, better: Any = None) -> AxisResult:
    """One axis, compared. Absence on either side is UNMEASURED.

    `better` names the expected value where one is known — from a reviewed
    candidate case, or from an independent reference. Without it a difference
    is a difference and nothing more, which is reported as REGRESSED only for
    axes where moving at all is the concern.
    """
    if production is None or candidate is None:
        return AxisResult(axis, UNMEASURED, production, candidate,
                          "one side recorded nothing on this axis")
    if production == candidate:
        return AxisResult(axis, UNCHANGED, production, candidate)
    if better is not None:
        if candidate == better and production != better:
            return AxisResult(axis, IMPROVED, production, candidate,
                              "the candidate matches the expected value and "
                              "production did not")
        if production == better and candidate != better:
            return AxisResult(axis, REGRESSED, production, candidate,
                              "production matched the expected value and the "
                              "candidate does not")
        return AxisResult(axis, UNCHANGED, production, candidate,
                          "both differ from the expected value")
    return AxisResult(axis, REGRESSED, production, candidate,
                      "the candidate behaves differently and no expected "
                      "value says which is right")


def compare(case_id: str, production: dict[str, Any],
            candidate: dict[str, Any], *, question: str = "",
            expected: dict[str, Any] | None = None,
            critical: bool = False) -> CaseReplay:
    """One case, both ways, on every axis."""
    wanted = expected or {}
    return CaseReplay(
        case_id=case_id, question=question, critical=critical,
        axes=[_compare(axis, production.get(axis), candidate.get(axis),
                       better=wanted.get(axis))
              for axis in AXIS_NAMES])


def block(run: Run, *, reviewer: str, why: str) -> Run:
    """A reviewer who has looked and decided this must not ship. §37."""
    if not str(reviewer).strip() or not str(why).strip():
        raise ValueError("blocking a release needs a named reviewer and a "
                         "reason")
    run.blocked_by = reviewer.strip()
    run.blocked_because = why.strip()
    return run


__all__ = ["AXES", "AXIS_MEANS", "AXIS_NAMES", "AxisResult", "CaseReplay",
           "IMPROVED", "MATERIAL_AXES", "REGRESSED", "REPLAY_VERSION", "Run",
           "UNCHANGED", "UNMEASURED", "VERDICTS", "block", "compare"]
