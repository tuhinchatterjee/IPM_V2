"""
Model A/B, threshold selection, and what a batch costs before you run it.
§30, §31, §40, §42.

Four sections, one workflow
---------------------------
An experiment is: pick some arms, estimate what running them costs, get an
explicit confirmation, run them over a case set, and compare the results by
family with a rule for choosing that is not "highest average". §30 supplies the
arms, §31 supplies the thresholds one of them may vary, §40 supplies the metric
that decides, and §42 supplies the estimate and the confirmation.

The rule for choosing
---------------------
    "Do not select a model based only on average score.
     Require zero critical-case regressions."

Implemented literally, and the order matters: critical regressions are checked
first and end the comparison. An arm that is two points better overall and
newly wrong on one grounding case has not won — it has moved the failure
somewhere nobody was looking.

What "accepted-answer precision" means, and what it does not
-------------------------------------------------------------
§40's metric is correct DISPLAYED answers over all displayed answers. A
clarification is not a displayed answer and a safe abstention is not a wrong
one, so neither appears in the denominator. Coverage — the share of questions
that got an answer at all — is reported beside it and never folded into it,
because the two trade against each other and one number hiding that trade is
the number people quote.

Confidence intervals are Wilson, from `metrics`. §40: "Do not claim 99.99%
until statistically supported." A precision of 1.0 over forty cases has a
lower bound near 0.91, and the honest sentence is the bound.

No credits are spent here
--------------------------
`estimate` costs nothing and `run` takes a runner callable. In Claude Code the
runner is the deterministic evaluator; a caller wiring a live provider supplies
its own and does so having seen the estimate first. §42: "Do not spend credits
automatically."
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.teaching import failures as fl
from backend.teaching import policy as pol
from intelligence_factory import metrics

logger = logging.getLogger(__name__)

EXPERIMENT_VERSION = "1.0.0"

# ---------------------------------------------------------------- §30's arms
BASELINE = "BASELINE"
CANDIDATE_A = "CANDIDATE_A"
CANDIDATE_B = "CANDIDATE_B"
CANDIDATE_C = "CANDIDATE_C"

ARMS: tuple[str, ...] = (BASELINE, CANDIDATE_A, CANDIDATE_B, CANDIDATE_C)

ARM_PURPOSE: dict[str, str] = {
    BASELINE: "The current configuration, exactly as production runs it.",
    CANDIDATE_A: "The routine model alone — no escalation at all. Establishes "
                 "what the cheap path is actually worth.",
    CANDIDATE_B: "Routine plus complex escalation. The configuration the "
                 "product is meant to run.",
    CANDIDATE_C: "The complex model directly for the hard families. Buys the "
                 "ceiling, and shows what escalation is leaving on the table.",
}

#: §30's per-family dimensions. Every arm is scored on all of them, because an
#: arm that gains on plans and loses on invariants is a different decision from
#: one that gains on both.
DIMENSIONS: tuple[str, ...] = (
    "same_turn_referents", "objectives", "data_relationships", "plan",
    "query", "result", "invariants", "interpretation", "chart", "trace",
    "abstention",
)

#: What a call is assumed to cost when the caller supplies no price. Used only
#: for the ESTIMATE, and named so a report can say the estimate is nominal.
NOMINAL_INPUT_TOKENS = 2500
NOMINAL_OUTPUT_TOKENS = 700
NOMINAL_CALLS_PER_TURN = 2


# ---------------------------------------------------------------------------
# §42 — the estimate, before anything runs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Price:
    """What a thousand tokens costs, per role.

    Supplied by the caller. Nothing here knows a provider's prices, and a
    number written into this file would be wrong the week after it was
    written.
    """

    input_per_1k: float = 0.0
    output_per_1k: float = 0.0


@dataclass
class Estimate:
    """§42's dry run: what a batch would cost, before it is confirmed."""

    arms: list[str] = field(default_factory=list)
    cases: int = 0
    turns: int = 0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    #: True when no price was supplied, so `cost` is zero for lack of a price
    #: rather than because the run is free.
    nominal: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "arms": list(self.arms), "cases": self.cases, "turns": self.turns,
            "calls": self.calls, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": round(self.cost, 4), "nominal": self.nominal,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        """What a person reads before saying yes."""
        money = ("cost unknown — no price was supplied" if self.nominal
                 else f"about ${self.cost:,.2f}")
        return (f"{len(self.arms)} arm(s) over {self.cases} cases "
                f"({self.turns} turns): about {self.calls:,} model calls, "
                f"{self.input_tokens + self.output_tokens:,} tokens, {money}.")


def estimate(cases: Sequence[Any], *, arms: Sequence[str] = (BASELINE,),
             price: Price | None = None,
             calls_per_turn: int = NOMINAL_CALLS_PER_TURN) -> Estimate:
    """§42's dry-run estimate. Costs nothing to produce.

    Deliberately rough and deliberately labelled rough: §42 wants a number on
    screen before anything starts, and the direction is what matters. A batch
    that would cost forty dollars and one that would cost four hundred are
    different decisions, and neither needs three significant figures.
    """
    turns = sum(max(1, len(getattr(c, "turns", ()) or ())) for c in cases)
    per_arm_calls = turns * max(1, int(calls_per_turn))
    total_calls = per_arm_calls * max(1, len(arms))
    found = Estimate(
        arms=list(arms), cases=len(cases), turns=turns, calls=total_calls,
        input_tokens=total_calls * NOMINAL_INPUT_TOKENS,
        output_tokens=total_calls * NOMINAL_OUTPUT_TOKENS,
        nominal=price is None)
    if price is not None:
        found.nominal = False
        found.cost = (found.input_tokens / 1000 * price.input_per_1k
                      + found.output_tokens / 1000 * price.output_per_1k)
    return found


class NotConfirmed(RuntimeError):
    """A batch was started without an explicit confirmation. §42."""


# ---------------------------------------------------------------------------
# Running one arm
# ---------------------------------------------------------------------------

@dataclass
class Outcome:
    """One case under one arm."""

    case_id: str
    family: str
    passed: bool
    #: Which of §34's categories the failure belongs to, where it failed.
    failure: str = ""
    #: What the run DID: answered, clarified, abstained, failed.
    behaviour: str = "answered"
    critical: bool = False
    dimensions: dict[str, bool] = field(default_factory=dict)
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "family": self.family,
            "passed": self.passed, "failure": self.failure,
            "behaviour": self.behaviour, "critical": self.critical,
            "dimensions": dict(self.dimensions),
            "latency_ms": round(self.latency_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


#: What an arm may have done with a case. Only ANSWERED lands in §40's
#: denominator.
ANSWERED = "answered"
CLARIFIED = "clarified"
ABSTAINED = "abstained"
FAILED = "failed"

BEHAVIOURS: tuple[str, ...] = (ANSWERED, CLARIFIED, ABSTAINED, FAILED)

#: A runner takes a case and returns an Outcome. Everything about how the case
#: was run — which model, which policy, whether a provider was involved at all
#: — belongs to the runner, so this module can compare arms it knows nothing
#: about.
Runner = Callable[[Any], Outcome]


@dataclass
class ArmResult:
    """Everything one arm did, and what it is worth. §30, §40."""

    arm: str
    policy: pol.Policy | None = None
    outcomes: list[Outcome] = field(default_factory=list)
    started_at: str = ""
    duration_ms: float = 0.0

    # ---- §40's two numbers, kept apart ------------------------------------
    @property
    def displayed(self) -> int:
        """Answers actually shown. Clarifications and abstentions are not."""
        return sum(1 for o in self.outcomes if o.behaviour == ANSWERED)

    @property
    def correct(self) -> int:
        return sum(1 for o in self.outcomes
                   if o.behaviour == ANSWERED and o.passed)

    @property
    def precision(self) -> metrics.Rate:
        """§40's key commercial metric, with its interval."""
        return metrics.rate("accepted-answer precision", self.correct,
                            self.displayed)

    @property
    def coverage(self) -> metrics.Rate:
        """How often a question got an answer at all.

        Reported beside precision and never folded into it. The two trade: an
        arm that abstains on everything hard has perfect precision and is
        useless, and one number hiding that trade is the number people quote.
        """
        return metrics.rate("coverage", self.displayed, len(self.outcomes))

    @property
    def critical_failures(self) -> list[Outcome]:
        return [o for o in self.outcomes
                if o.critical or fl.is_critical(o.failure)]

    def by_family(self) -> dict[str, dict[str, Any]]:
        """§30: evaluate by family. An average over families hides the family
        that broke."""
        grouped: dict[str, list[Outcome]] = {}
        for outcome in self.outcomes:
            grouped.setdefault(outcome.family, []).append(outcome)
        return {
            family: {
                "cases": len(rows),
                "passed": sum(1 for o in rows if o.passed),
                "displayed": sum(1 for o in rows if o.behaviour == ANSWERED),
                "correct": sum(1 for o in rows
                               if o.behaviour == ANSWERED and o.passed),
                "critical": sum(1 for o in rows
                                if o.critical or fl.is_critical(o.failure)),
            } for family, rows in sorted(grouped.items())
        }

    def by_dimension(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {
            d: {"checked": 0, "passed": 0} for d in DIMENSIONS}
        for outcome in self.outcomes:
            for name, ok in outcome.dimensions.items():
                row = counts.setdefault(name, {"checked": 0, "passed": 0})
                row["checked"] += 1
                row["passed"] += int(bool(ok))
        return counts

    def failures(self) -> dict[str, int]:
        return fl.tally([o.failure for o in self.outcomes if o.failure])

    def cost(self, price: Price | None = None) -> dict[str, Any]:
        inputs = sum(o.input_tokens for o in self.outcomes)
        outputs = sum(o.output_tokens for o in self.outcomes)
        money = 0.0
        if price is not None:
            money = (inputs / 1000 * price.input_per_1k
                     + outputs / 1000 * price.output_per_1k)
        return {"input_tokens": inputs, "output_tokens": outputs,
                "cost": round(money, 4), "priced": price is not None}

    def to_dict(self, price: Price | None = None) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "purpose": ARM_PURPOSE.get(self.arm, ""),
            "policy": self.policy.to_dict() if self.policy else None,
            "policy_fingerprint": (self.policy.fingerprint if self.policy
                                   else ""),
            "cases": len(self.outcomes),
            "displayed": self.displayed,
            "correct": self.correct,
            "precision": self.precision.to_dict(),
            "coverage": self.coverage.to_dict(),
            "critical_failures": [o.case_id for o in self.critical_failures],
            "by_family": self.by_family(),
            "by_dimension": self.by_dimension(),
            "failures": {k: v for k, v in self.failures().items() if v},
            "latency_ms": round(sum(o.latency_ms for o in self.outcomes), 2),
            "cost": self.cost(price),
            "started_at": self.started_at,
            "duration_ms": round(self.duration_ms, 2),
        }


def run_arm(arm: str, runner: Runner, cases: Sequence[Any], *,
            policy: pol.Policy | None = None) -> ArmResult:
    """One arm over one case set.

    A runner that raises scores the case as a controlled failure rather than
    stopping the experiment: an arm that crashes on one case in fifty is an
    arm with a defect, and losing the other forty-nine measurements hides it.
    """
    result = ArmResult(arm=arm, policy=policy,
                       started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime()))
    started = time.perf_counter()
    for case in cases:
        try:
            outcome = runner(case)
        except Exception as error:  # noqa: BLE001 - a crash is a result
            outcome = Outcome(
                case_id=str(getattr(case, "id", "") or "?"),
                family=str(getattr(case, "family", "") or "?"),
                passed=False, behaviour=FAILED, failure="EXECUTION",
                dimensions={"error": False})
            logger.warning("%s crashed on %s: %s", arm, outcome.case_id,
                           error)
        result.outcomes.append(outcome)
    result.duration_ms = (time.perf_counter() - started) * 1000
    return result


# ---------------------------------------------------------------------------
# §30 — comparing arms
# ---------------------------------------------------------------------------

@dataclass
class Comparison:
    """Which arm won, and why — or why none did."""

    baseline: ArmResult
    candidates: list[ArmResult] = field(default_factory=list)
    winner: str = ""
    reason: str = ""
    #: Per candidate: the critical cases it regressed on.
    regressions: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self, price: Price | None = None) -> dict[str, Any]:
        return {
            "version": EXPERIMENT_VERSION,
            "baseline": self.baseline.to_dict(price),
            "candidates": [c.to_dict(price) for c in self.candidates],
            "winner": self.winner,
            "reason": self.reason,
            "regressions": {k: list(v) for k, v in self.regressions.items()},
            "decision": "adopt" if self.winner else "keep the baseline",
        }


def regressions(baseline: ArmResult, candidate: ArmResult) -> list[str]:
    """Critical cases the baseline got right and the candidate did not.

    Critical is §34's definition — grounding, invariants, grain, relationships,
    permission, scope, Trace — not "important-looking". A case that was never
    critical cannot become a critical regression by failing.
    """
    was = {o.case_id: o for o in baseline.outcomes}
    out: list[str] = []
    for outcome in candidate.outcomes:
        before = was.get(outcome.case_id)
        if before is None or not before.passed or outcome.passed:
            continue
        if outcome.critical or fl.is_critical(outcome.failure):
            out.append(outcome.case_id)
    return sorted(out)


def compare(baseline: ArmResult, candidates: Sequence[ArmResult], *,
            margin: float = 0.01) -> Comparison:
    """§30's decision rule, in §30's order.

    Critical regressions first, and they end it. Then precision — the LOWER
    BOUND of the interval rather than the point estimate, because a candidate
    that is nominally ahead on forty cases is not ahead. Then, among survivors,
    the one that is ahead by the largest margin.
    """
    found = Comparison(baseline=baseline, candidates=list(candidates))
    survivors: list[tuple[float, ArmResult]] = []

    for candidate in candidates:
        broke = regressions(baseline, candidate)
        found.regressions[candidate.arm] = broke
        if broke:
            continue
        gain = (candidate.precision.point - baseline.precision.point) / 100.0
        if gain < margin:
            continue
        # The LOWER bound, not the point estimate. §40: do not claim a number
        # the sample does not support. A candidate nominally ahead on forty
        # cases is not ahead.
        if candidate.precision.lower <= baseline.precision.point:
            continue
        survivors.append((gain, candidate))

    if not survivors:
        blocked = [arm for arm, broke in found.regressions.items() if broke]
        if blocked:
            found.reason = (
                f"{', '.join(blocked)} regressed on critical cases. §30 "
                "requires zero critical regressions, so no candidate is "
                "adopted however good its average.")
        else:
            found.reason = ("No candidate beat the baseline by more than the "
                            "margin with its interval clear of it.")
        return found

    survivors.sort(key=lambda pair: -pair[0])
    gain, best = survivors[0]
    found.winner = best.arm
    found.reason = (
        f"{best.arm} is {gain:+.1%} on accepted-answer precision "
        f"({best.precision.sentence()}) with no critical regressions across "
        f"{len(best.outcomes)} cases.")
    return found


# ---------------------------------------------------------------------------
# §31 — choosing thresholds
# ---------------------------------------------------------------------------

@dataclass
class Sweep:
    """A threshold sweep over the DEVELOPMENT set. §31."""

    results: list[ArmResult] = field(default_factory=list)
    chosen: pol.Policy | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tried": len(self.results),
            "chosen": self.chosen.to_dict() if self.chosen else None,
            "fingerprint": self.chosen.fingerprint if self.chosen else "",
            "reason": self.reason,
            "policies": [{
                "fingerprint": r.policy.fingerprint if r.policy else "",
                "policy": r.policy.to_dict() if r.policy else None,
                "precision": r.precision.to_dict(),
                "coverage": r.coverage.to_dict(),
                "critical": len(r.critical_failures),
            } for r in self.results],
        }


def sweep(cases: Sequence[Any], runner_for: Callable[[pol.Policy], Runner], *,
          policies: Sequence[pol.Policy] | None = None) -> Sweep:
    """§31: choose thresholds on the development set.

    `cases` must be development cases. Nothing here can tell — a list of cases
    is a list of cases — which is exactly why the sealed holdout lives in a
    module this one cannot import, and why the caller that supplies holdout
    cases here would have to do it deliberately.

    Chosen by precision with zero critical failures, and ties broken by
    coverage: two policies that answer equally well are separated by which
    answers more often.
    """
    found = Sweep()
    tried = list(policies or pol.candidates())
    for candidate in tried:
        found.results.append(
            run_arm(f"policy:{candidate.fingerprint}", runner_for(candidate),
                    cases, policy=candidate))

    clean = [r for r in found.results if not r.critical_failures]
    if not clean:
        found.reason = ("Every policy produced at least one critical failure. "
                        "The thresholds are not the problem.")
        return found

    clean.sort(key=lambda r: (-r.precision.point, -r.coverage.point))
    best = clean[0]
    found.chosen = best.policy
    found.reason = (
        f"{best.precision.sentence()}, coverage "
        f"{best.coverage.point:.1f}%, no critical failures, over "
        f"{len(cases)} development cases and {len(tried)} candidate "
        "policies.")
    return found


def freeze_policy(chosen: pol.Policy, *, path: Path) -> Path:
    """§31: freeze the selected thresholds into a versioned routing policy.

    Written as a file so a Teaching Release can carry it and a Trace can name
    its fingerprint. Refuses to overwrite for the same reason a release does.
    """
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"{target} already exists; a frozen policy is "
                              "frozen")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "version": pol.POLICY_VERSION,
        "fingerprint": chosen.fingerprint,
        "policy": chosen.to_dict(),
    }, indent=1, sort_keys=True), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# §42 — the batch workflow
# ---------------------------------------------------------------------------

@dataclass
class Batch:
    """A resumable batch run. §42.

    Resumable because the alternative is re-spending: a run that dies at case
    four hundred of five hundred and cannot be resumed costs the four hundred
    again. Results are appended to a JSONL as they arrive, and a resumed run
    skips the case ids already in it.
    """

    path: Path
    arm: str = BASELINE
    done: set[str] = field(default_factory=set)

    def load(self) -> list[Outcome]:
        out: list[Outcome] = []
        if not self.path.exists():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            out.append(Outcome(
                case_id=row.get("case_id", ""), family=row.get("family", ""),
                passed=bool(row.get("passed")),
                failure=row.get("failure", ""),
                behaviour=row.get("behaviour", ANSWERED),
                critical=bool(row.get("critical")),
                dimensions=dict(row.get("dimensions") or {}),
                latency_ms=float(row.get("latency_ms") or 0),
                input_tokens=int(row.get("input_tokens") or 0),
                output_tokens=int(row.get("output_tokens") or 0)))
        self.done = {o.case_id for o in out}
        return out

    def append(self, outcome: Outcome) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(outcome.to_dict(), sort_keys=True) + "\n")
        self.done.add(outcome.case_id)


def run_batch(cases: Sequence[Any], runner: Runner, *, batch: Batch,
              confirmed: bool = False,
              price: Price | None = None) -> ArmResult:
    """§42's workflow: estimate, confirm, run, resume.

    `confirmed` defaults to False and the run refuses without it. That is §42's
    "Do not spend credits automatically" as a parameter rather than as a
    convention — a caller that forgets gets an exception naming the estimate,
    not a bill.
    """
    if not confirmed:
        found = estimate(cases, arms=[batch.arm], price=price)
        raise NotConfirmed(
            f"This batch was not confirmed. {found.sentence()} Pass "
            "confirmed=True to run it.")

    already = batch.load()
    result = ArmResult(arm=batch.arm, outcomes=list(already),
                       started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime()))
    started = time.perf_counter()
    for case in cases:
        case_id = str(getattr(case, "id", "") or "")
        if case_id and case_id in batch.done:
            continue
        outcome = runner(case)
        batch.append(outcome)
        result.outcomes.append(outcome)
    result.duration_ms = (time.perf_counter() - started) * 1000
    return result


__all__ = ["ABSTAINED", "ANSWERED", "ARMS", "ARM_PURPOSE", "ArmResult",
           "BASELINE", "BEHAVIOURS", "Batch", "CANDIDATE_A", "CANDIDATE_B",
           "CANDIDATE_C", "CLARIFIED", "Comparison", "DIMENSIONS",
           "EXPERIMENT_VERSION", "Estimate", "FAILED", "NotConfirmed",
           "Outcome", "Price", "Runner", "Sweep", "compare", "estimate",
           "freeze_policy", "regressions", "run_arm", "run_batch", "sweep"]
