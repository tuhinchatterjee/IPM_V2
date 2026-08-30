"""
Change-isolation experiments. §68.

`measurement.Contribution` carries an `isolated` flag, and until now nothing
in the system could set it to True honestly: every attribution was a
judgement about which of several simultaneous changes moved the number.
This module is what earns that flag. It runs a controlled A/B — baseline
against baseline-plus-exactly-one-change — over the same cases, and reports
the delta that one change is responsible for.

What an isolated experiment is
-------------------------------
Two arms, evaluated on **the same case set**, differing in **exactly one**
declared change. Both conditions are checked, not assumed:

* Different case sets mean the arms are not comparable, and the difference
  between them measures the cases as much as the change.
* More than one change means the result is a joint effect. It may still be
  worth reporting — but not as `isolated`, and not on the waterfall as an
  additive contribution.

Either way the experiment does not fail silently: it produces a result whose
`isolated` is False and whose `why_not_isolated` says which rule it broke.

What it will not do
--------------------
**It will not call a live provider without authorization.** §68: "Do not
automatically run expensive live-provider A/B tests without authorization."
An A/B doubles the call count by construction, and a runner that could
quietly decide to do that is a runner that spends somebody's budget on its
own initiative. `run()` refuses a live arm unless `authorization` names who
approved it.

**It will not claim isolation on too few cases.** An experiment under
`measurement.MINIMUM_CASES` produces a contribution with `isolated=False`,
because a clean design measured on twelve cases is still twelve cases.

**It will not evaluate anything itself.** The `evaluate` callable is
supplied. In tests that is a deterministic fixture; in the product it is the
same evaluation path everything else uses. Nothing here knows how to score
an answer, which is what keeps a second, divergent scorer from appearing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.continuous import measurement, partitions

ISOLATION_VERSION = "1.0.0"


class IsolationError(Exception):
    """An experiment that may not be run or may not be reported as asked."""


# ------------------------------------------------------------- §68's arms

#: §68's four worked examples, plus the three other things that move a
#: score. Each maps to the attribution source it can legitimately claim on
#: the waterfall, so an experiment cannot invent a source of its own.
CHANGE_KINDS: dict[str, str] = {
    "TEACHING_CASE_BATCH": "Teaching Cases",
    "BLUEPRINT_CHANGE": "Blueprint changes",
    "ROUTING_CHANGE": "Routing/model changes",
    "JUDGMENT_CHANGE": "Judgment changes",
    "REGULATORY_LEARNING": "Regulatory learning",
    "FEEDBACK_FIX": "Feedback fixes",
    "BRAIN_PATCH": "Brain imports",
}

KIND_IDS: tuple[str, ...] = tuple(CHANGE_KINDS)

#: Execution modes. DETERMINISTIC is the default and the only one that runs
#: without a person's name attached to it.
DETERMINISTIC = "DETERMINISTIC"
LIVE_PROVIDER = "LIVE_PROVIDER"
MODES: tuple[str, ...] = (DETERMINISTIC, LIVE_PROVIDER)


@dataclass
class Arm:
    """One side of the experiment: what was configured, and what it scored.

    `changes` is the full set of things this arm differs from a bare
    baseline by. The runner compares the two arms' sets rather than trusting
    a label, so "baseline + one change" has to actually be that.
    """

    label: str
    changes: frozenset[str] = frozenset()
    #: case_id -> score in [0, 1]. The same keys must appear in both arms.
    scores: dict[str, float] = field(default_factory=dict)
    #: case_id -> family, for §68's case-family delta.
    families: dict[str, str] = field(default_factory=dict)
    #: dimension -> score in [0, 1], for §68's six-dimension delta.
    dimensions: dict[str, float] = field(default_factory=dict)
    #: Cases that failed a critical check in this arm.
    critical_failures: frozenset[str] = frozenset()
    latency_ms: float = 0.0
    cost_units: float = 0.0

    @property
    def mean(self) -> float:
        return (sum(self.scores.values()) / len(self.scores)
                if self.scores else 0.0)


@dataclass
class Experiment:
    """A declared experiment, before it is run."""

    change_kind: str
    change_id: str
    baseline: Arm
    treatment: Arm
    partition: str = partitions.VALIDATION
    mode: str = DETERMINISTIC
    experiment_id: str = ""

    def __post_init__(self) -> None:
        self.experiment_id = (self.experiment_id
                              or f"exp_{uuid.uuid4().hex[:12]}")

    @property
    def introduced(self) -> frozenset[str]:
        """What the treatment arm adds over the baseline arm."""
        return self.treatment.changes - self.baseline.changes

    @property
    def removed(self) -> frozenset[str]:
        return self.baseline.changes - self.treatment.changes


# ------------------------------------------------------------- the result


@dataclass
class Result:
    """What one experiment established, and what it did not."""

    experiment_id: str
    change_kind: str
    change_id: str
    partition: str
    mode: str
    isolated: bool
    why_not_isolated: str
    overall: measurement.Change
    by_family: dict[str, measurement.Change] = field(default_factory=dict)
    by_dimension: dict[str, measurement.Change] = field(default_factory=dict)
    critical_regressions: tuple[str, ...] = ()
    critical_fixes: tuple[str, ...] = ()
    latency_delta_ms: float = 0.0
    cost_delta_units: float = 0.0
    ran_at: str = ""
    ran_by: str = ""
    authorization: str = ""

    @property
    def source(self) -> str:
        return CHANGE_KINDS[self.change_kind]

    def contribution(self) -> measurement.Contribution:
        """The waterfall entry this experiment supports — and only that.

        This is the whole point of the module. `isolated=True` appears here
        and nowhere else, because this is the only place that checked the
        two conditions that make the word true.
        """
        return measurement.Contribution(
            source=self.source,
            points=self.overall.points,
            isolated=self.isolated,
            evidence=(f"{self.experiment_id}: {self.overall.cases} case(s) "
                      f"on {self.partition}, {self.mode.lower()}"
                      if self.isolated else self.why_not_isolated))

    def to_dict(self) -> dict[str, Any]:
        return {
            "isolation_version": ISOLATION_VERSION,
            "experiment_id": self.experiment_id,
            "change_kind": self.change_kind,
            "change_id": self.change_id,
            "attributed_source": self.source,
            "partition": self.partition,
            "mode": self.mode,
            "isolated": self.isolated,
            "why_not_isolated": self.why_not_isolated,
            "overall": self.overall.to_dict(),
            "by_case_family": {k: v.to_dict()
                               for k, v in sorted(self.by_family.items())},
            "by_dimension": {k: v.to_dict()
                             for k, v in sorted(self.by_dimension.items())},
            "critical_regressions": list(self.critical_regressions),
            "critical_fixes": list(self.critical_fixes),
            "latency_delta_ms": round(self.latency_delta_ms, 2),
            "cost_delta_units": round(self.cost_delta_units, 4),
            "ran_at": self.ran_at,
            "ran_by": self.ran_by,
            "authorization": self.authorization,
            "reads_as": self.sentence(),
        }

    def sentence(self) -> str:
        if self.critical_regressions:
            return (f"{self.source}: {len(self.critical_regressions)} "
                    "critical case(s) regressed. That is the finding, "
                    "whatever the average did.")
        if not self.isolated:
            return (f"{self.source}: {self.overall.points:+.1f} pp, but this "
                    f"is not an isolated result. {self.why_not_isolated}")
        return f"{self.source}, isolated: {self.overall.sentence()}"


# ---------------------------------------------------------------- running


def _comparable(experiment: Experiment) -> str:
    """Why these two arms are not a controlled comparison, or "" if they are.

    Order matters: the case-set check comes first because arms scored on
    different cases are not comparable at all, whereas arms differing in two
    changes still produce a real — just joint — measurement.
    """
    base, treat = experiment.baseline, experiment.treatment
    if not base.scores or not treat.scores:
        return ("one arm scored nothing. An experiment with an empty arm "
                "measures nothing and must not report a delta.")
    if set(base.scores) != set(treat.scores):
        only_base = len(set(base.scores) - set(treat.scores))
        only_treat = len(set(treat.scores) - set(base.scores))
        return (f"the arms were scored on different cases ({only_base} only "
                f"in baseline, {only_treat} only in treatment). The "
                "difference between them measures the cases as much as the "
                "change.")
    introduced, removed = experiment.introduced, experiment.removed
    if removed:
        return ("the treatment arm removes " + ", ".join(sorted(removed))
                + " as well as adding a change, so it is not baseline plus "
                  "one thing.")
    if len(introduced) != 1:
        return (f"the treatment arm introduces {len(introduced)} changes "
                f"({', '.join(sorted(introduced)) or 'none'}). A joint "
                "effect is a real measurement but not an isolated one, and "
                "must not be added to a waterfall as if it were.")
    return ""


def run(experiment: Experiment, *, by: str,
        authorization: str = "",
        evaluate: Callable[[Arm], Arm] | None = None) -> Result:
    """Run one change-isolation experiment and report what it established.

    `evaluate` is called once per arm if the arm has no scores yet. Nothing
    here scores anything: passing the evaluator in is what keeps a second
    scorer from growing inside the experiment runner and disagreeing with
    the one everything else uses.
    """
    if experiment.change_kind not in CHANGE_KINDS:
        raise IsolationError(
            f"{experiment.change_kind!r} is not a change kind. An experiment "
            "that cannot name what it changed cannot attribute anything.")
    if experiment.mode not in MODES:
        raise IsolationError(f"{experiment.mode!r} is not an execution mode")
    if not by.strip():
        raise IsolationError("an experiment nobody ran is not evidence")

    if experiment.mode == LIVE_PROVIDER and not authorization.strip():
        raise IsolationError(
            "§68: a live-provider A/B may not run without authorization. An "
            "A/B doubles the call count by construction, and this runner "
            "will not spend that on its own initiative. Name who approved "
            "it, or run the experiment deterministically.")

    allowed, why = partitions.tuning_allowed(experiment.partition)
    if experiment.partition == partitions.SEALED_HOLDOUT:
        raise IsolationError(
            "an isolation experiment may not run on the sealed holdout. "
            f"{why} Running variants against it is exactly the repeated "
            "exposure that stops it being a holdout.")
    del allowed

    if evaluate is not None:
        if not experiment.baseline.scores:
            experiment.baseline = evaluate(experiment.baseline)
        if not experiment.treatment.scores:
            experiment.treatment = evaluate(experiment.treatment)

    problem = _comparable(experiment)
    base, treat = experiment.baseline, experiment.treatment
    cases = sorted(set(base.scores) & set(treat.scores))

    critical_regressions = tuple(sorted(
        treat.critical_failures - base.critical_failures))
    critical_fixes = tuple(sorted(
        base.critical_failures - treat.critical_failures))

    overall = measurement.Change(
        label=f"{CHANGE_KINDS[experiment.change_kind]} ({experiment.change_id})",
        before=_mean(base.scores, cases), after=_mean(treat.scores, cases),
        cases=len(cases), partition=experiment.partition,
        critical_fixed=len(critical_fixes),
        critical_introduced=len(critical_regressions))

    isolated = not problem and len(cases) >= measurement.MINIMUM_CASES
    if problem:
        why_not = problem
    elif not isolated:
        why_not = (f"{len(cases)} case(s) is below the {measurement.MINIMUM_CASES} "
                   "needed to call a delta measured rather than noticed. The "
                   "design is clean; the sample is not big enough to carry it.")
    else:
        why_not = ""

    return Result(
        experiment_id=experiment.experiment_id,
        change_kind=experiment.change_kind, change_id=experiment.change_id,
        partition=experiment.partition, mode=experiment.mode,
        isolated=isolated, why_not_isolated=why_not,
        overall=overall,
        by_family=_by_family(experiment, cases),
        by_dimension=_by_dimension(experiment),
        critical_regressions=critical_regressions,
        critical_fixes=critical_fixes,
        latency_delta_ms=treat.latency_ms - base.latency_ms,
        cost_delta_units=treat.cost_units - base.cost_units,
        ran_at=datetime.now(UTC).isoformat(), ran_by=by,
        authorization=authorization)


def _mean(scores: dict[str, float], cases: list[str]) -> float:
    return sum(scores[c] for c in cases) / len(cases) if cases else 0.0


def _by_family(experiment: Experiment,
               cases: list[str]) -> dict[str, measurement.Change]:
    """§68's case-family delta. Families come from the baseline arm."""
    families: dict[str, list[str]] = {}
    for case in cases:
        family = experiment.baseline.families.get(case, "")
        if family:
            families.setdefault(family, []).append(case)

    out: dict[str, measurement.Change] = {}
    for family, members in sorted(families.items()):
        out[family] = measurement.Change(
            label=family, cases=len(members),
            partition=experiment.partition,
            before=_mean(experiment.baseline.scores, members),
            after=_mean(experiment.treatment.scores, members))
    return out


def _by_dimension(experiment: Experiment) -> dict[str, measurement.Change]:
    """§68's six-dimension delta, over the dimensions both arms scored."""
    shared = sorted(set(experiment.baseline.dimensions)
                    & set(experiment.treatment.dimensions))
    return {
        dimension: measurement.Change(
            label=dimension, partition=experiment.partition,
            before=experiment.baseline.dimensions[dimension],
            after=experiment.treatment.dimensions[dimension],
            cases=len(set(experiment.baseline.scores)
                      & set(experiment.treatment.scores)))
        for dimension in shared
    }


# ------------------------------------------------------- the set of results


def contributions(results: list[Result]) -> list[measurement.Contribution]:
    """Waterfall entries from a set of experiments, isolation preserved.

    Deliberately not filtered to the isolated ones. `waterfall()` already
    knows what to do with a non-isolated contribution — it declines to treat
    it as additive — and dropping them here would make the residual larger
    with no explanation of where it went.
    """
    return [result.contribution() for result in results]


def summary(results: list[Result]) -> dict[str, Any]:
    isolated = [r for r in results if r.isolated]
    regressions = [r for r in results if r.critical_regressions]
    return {
        "experiments": len(results),
        "isolated": len(isolated),
        "not_isolated": len(results) - len(isolated),
        "with_critical_regressions": len(regressions),
        "live_provider_runs": sum(1 for r in results
                                  if r.mode == LIVE_PROVIDER),
        "by_source": {r.source: r.overall.points for r in isolated},
        "note": (
            "Only the isolated experiments may be added together. The rest "
            "measured something real and measured it jointly, which is a "
            "different claim."),
    }
