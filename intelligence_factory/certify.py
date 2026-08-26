"""
The certification run, and the frozen Intelligence Release it produces.

    python -m intelligence_factory.certify              development evaluation
    python -m intelligence_factory.certify --certify    sealed holdout, frozen

What certification is
---------------------
Running the sealed holdout through the real path, measuring what happened, and
writing a manifest that says which configuration was measured and what the
evidence supports. The manifest is the artefact Docker consumes: a release
image without one is UNCERTIFIED and says so.

What it refuses to do
---------------------
Claim more than the sample supports. Every rate carries a Wilson interval and
the gate compares the LOWER bound, so a hundred clean cases produce "99.99% is
not yet demonstrated — about thirty thousand consecutive clean cases would be
needed" rather than "100%". A single critical failure blocks certification
whatever the aggregate says, because the aggregate is not what a credit officer
meets.

Cost
----
Nothing runs on import and nothing runs on a timer. A full certification makes
one model call per turn where a provider is configured, and the command prints
what that will cost in calls before it starts.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where a frozen release is written. Docker copies this directory in.
RELEASE_DIR = Path("intelligence_release")

#: The precision a release is gated on. Deliberately not 99.99%: a gate nobody
#: can pass is a gate somebody removes.
GATE_PRECISION = 95.0

#: The gate tests the OBSERVED rate, not the lower bound of its interval.
#:
#: This distinction is the whole of the honesty problem, so it is worth being
#: explicit. A twenty-four case holdout that answers twenty-three correctly has
#: a 95% Wilson lower bound near 76%: the interval cannot support a claim of
#: 95% no matter how the cases came out, because the sample is too small for
#: any claim that strong. Gating on the lower bound would therefore fail every
#: release forever, and a gate that can never pass gets deleted rather than
#: met.
#:
#: So the two questions are separated and both are reported:
#:
#:   the GATE asks "did this build do what was asked of it, on cases it has
#:   never seen, with nothing critical broken" — a question about behaviour,
#:   which twenty-four cases can answer;
#:
#:   the CLAIM asks "what precision does this evidence support" — a question
#:   about statistics, answered by the interval, and never rounded up. It is
#:   reported on the manifest and it gates nothing, which is what stops a
#:   passing build from being described as 99.99% accurate.


@dataclass
class Report:
    """One certification run."""

    mode: str
    started_at: str
    duration_ms: int = 0
    cases: list[Any] = field(default_factory=list)
    accuracy: Any = None
    release_id: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Whether this build may be released. Behaviour, not statistics."""
        if self.accuracy is None or not self.cases:
            return False
        if self.accuracy.critical_failures:
            return False
        precision = self.accuracy.rates.get("accepted_precision")
        if precision is None or precision.point < GATE_PRECISION:
            return False
        # Every turn has to have done the right KIND of thing. A build that
        # answers where it should have asked is not 95% right, it is wrong in
        # the way that matters most, and the aggregate hides it.
        outcome = self.accuracy.rates.get("outcome")
        return outcome is not None and outcome.point >= 100.0

    @property
    def blockers(self) -> list[str]:
        """Why it did not pass, in the order a reader should act on them."""
        if self.accuracy is None or not self.cases:
            return ["the certification run produced no results"]
        out = [f"critical case failed — {f}"
               for f in self.accuracy.critical_failures]
        precision = self.accuracy.rates.get("accepted_precision")
        if precision is not None and precision.point < GATE_PRECISION:
            out.append(
                f"observed precision {precision.point:.2f}% is below the "
                f"{GATE_PRECISION:g}% gate")
        outcome = self.accuracy.rates.get("outcome")
        if outcome is not None and outcome.point < 100.0:
            out.append(
                f"{outcome.total - outcome.successes} turn(s) executed, "
                "clarified or refused where the case required the other")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "started_at": self.started_at,
                "duration_ms": self.duration_ms,
                "passed": self.passed, "blockers": self.blockers,
                "release_id": self.release_id,
                "accuracy": self.accuracy.to_dict() if self.accuracy else None,
                "cases": [c.to_dict() for c in self.cases]}


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def measure(results: list[Any]) -> Any:
    """Turn case outcomes into rates with intervals.

    `accepted_precision` is the number the product is tempted to quote, so it
    is defined narrowly: of the cases where CreditProbe chose to ANSWER, how
    many were right. A case it declined to answer is counted as an abstention
    and excluded — an abstention is a slower conversation, not a wrong figure,
    and averaging the two together hides the one that matters.
    """
    from intelligence_factory import metrics

    accuracy = metrics.Accuracy()
    accepted = [r for r in results if r.answered]
    abstained = [r for r in results if not r.answered]
    accuracy.accepted = len(accepted)
    accuracy.abstained = len(abstained)

    accuracy.add("accepted_precision",
                 sum(1 for r in accepted if r.ok), len(accepted))
    accuracy.add("overall", sum(1 for r in results if r.ok), len(results))
    accuracy.add("abstention_correct",
                 sum(1 for r in abstained if r.ok), len(abstained))

    for dimension in ("outcome", "capability", "action"):
        checked = [(t.checks.get(dimension), t) for r in results
                   for t in r.turns if dimension in t.checks]
        accuracy.add(dimension, sum(1 for held, _ in checked if held),
                     len(checked))

    invariants = [(held, name) for r in results for t in r.turns
                  for name, held in t.checks.items()
                  if name.startswith("invariant:")]
    accuracy.add("invariants", sum(1 for held, _ in invariants if held),
                 len(invariants))

    grounding = [(held, name) for r in results for t in r.turns
                 for name, held in t.checks.items()
                 if name.startswith("dataset:") or name.startswith("concept:")]
    accuracy.add("grounding", sum(1 for held, _ in grounding if held),
                 len(grounding))

    accuracy.critical_failures = [
        f"{r.case_id}: {'; '.join(r.problems[:2])}"
        for r in results if r.critical and not r.ok]
    return accuracy


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def development(*, variants: bool = True) -> Report:
    """The open curriculum. Safe to tune against; not evidence."""
    from intelligence_factory import curriculum, generators

    cases = list(curriculum.CASES)
    if variants:
        cases = generators.expand(cases)
    return _run("development", cases)


def certification() -> Report:
    """The sealed holdout. Evidence, and the only thing a claim may cite."""
    from intelligence_factory import holdout

    return _run("certification", list(holdout.CASES))


def _run(mode: str, cases: list[Any]) -> Report:
    from intelligence_factory import evaluate

    started = time.perf_counter()
    report = Report(mode=mode, started_at=_now())
    report.cases = evaluate.run_all(cases)
    report.accuracy = measure(report.cases)
    report.duration_ms = int((time.perf_counter() - started) * 1000)
    return report


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Freezing
# ---------------------------------------------------------------------------


def manifest(report: Report) -> dict[str, Any]:
    """What was measured, and against what. Never a key."""
    from backend.build_info import build_info
    from backend.llm import health as ai_health
    from backend.llm import roles
    from backend.semantics import ontology
    from intelligence_factory import (
        FACTORY_VERSION,
        curriculum,
        generators,
        holdout,
    )

    observed = ai_health()
    info = build_info()
    accuracy = report.accuracy

    return {
        "release_id": report.release_id,
        "created_at": report.started_at,
        "factory_version": FACTORY_VERSION,
        "app_version": info.version,
        "build_sha": info.short_sha,
        "ontology_version": ontology.ONTOLOGY_VERSION,
        "ontology_fingerprint": ontology.fingerprint(),
        "curriculum_version": curriculum.CURRICULUM_VERSION,
        "holdout_version": holdout.HOLDOUT_VERSION,
        "provider": observed.get("provider", ""),
        "ai_state": observed.get("state", ""),
        "roles": roles.describe()["roles"],
        "development": generators.describe(list(curriculum.CASES)),
        "holdout": {"cases": len(holdout.CASES),
                    "turns": holdout.turn_count(),
                    "critical": len(holdout.critical()),
                    "kinds": holdout.coverage(),
                    # Published, not buried. A score is only as trustworthy as
                    # the expectations behind it, and these two changed.
                    "corrections": [dict(c) for c in holdout.CORRECTIONS]},
        "certification": {
            "status": "PASSED" if report.passed else "NOT PASSED",
            "gate_precision_pct": GATE_PRECISION,
            "critical_failures": list(accuracy.critical_failures)
            if accuracy else [],
            "rates": {k: v.to_dict() for k, v in accuracy.rates.items()}
            if accuracy else {},
            "coverage": accuracy.coverage.to_dict() if accuracy else None,
            "claim_99_99": accuracy.claim(99.99) if accuracy else None,
            "blockers": report.blockers,
            "duration_ms": report.duration_ms,
        },
        # Kept apart from the gate deliberately. This is what may be SAID about
        # the build; `certification.status` is only whether it may ship.
        "evidence": _evidence(accuracy),
    }


def _evidence(accuracy: Any) -> dict[str, Any]:
    """What this sample can and cannot support, stated before anyone asks."""
    from intelligence_factory import metrics

    if accuracy is None:
        return {}
    precision = accuracy.rates.get("accepted_precision")
    if precision is None:
        return {}
    supported = precision.lower if precision.reportable else 0.0
    return {
        "observed_precision_pct": round(precision.point, 4),
        "observations": precision.total,
        "supported_precision_pct": round(supported, 4),
        "reportable": precision.reportable,
        "minimum_observations": metrics.MIN_OBSERVATIONS,
        "cases_for_99_99": metrics.cases_needed(99.99),
        "cases_for_gate": metrics.cases_needed(GATE_PRECISION),
        "sentence": (
            f"The holdout observed {precision.point:.2f}% precision over "
            f"{precision.total} accepted answers. "
            + (f"That sample supports a claim of {supported:.2f}% at 95% "
               "confidence. " if precision.reportable else
               f"Below {metrics.MIN_OBSERVATIONS} observations no rate claim "
               "is supportable at all, so this build's precision is reported "
               "as observed and claimed as nothing. ")
            + f"Demonstrating {GATE_PRECISION:g}% would need about "
            f"{metrics.cases_needed(GATE_PRECISION):,} consecutive clean "
            f"cases, and 99.99% about {metrics.cases_needed(99.99):,}."),
    }


def freeze(report: Report, *, directory: Path = RELEASE_DIR) -> Path:
    """Write the release. Returns the manifest path."""
    import hashlib

    payload = json.dumps(
        {"at": report.started_at, "mode": report.mode,
         "cases": [c.case_id for c in report.cases]}, sort_keys=True)
    report.release_id = "ir-" + hashlib.sha256(payload.encode()).hexdigest()[:12]
    report.manifest = manifest(report)

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    path.write_text(json.dumps(report.manifest, indent=2) + "\n",
                    encoding="utf-8")
    (directory / "certification_report.json").write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def cost_estimate(cases: list[Any]) -> dict[str, Any]:
    """What a run will spend, before it spends it."""
    turns = sum(len(c.turns) for c in cases)
    configured = bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())
    return {"cases": len(cases), "turns": turns,
            "model_calls_if_live": turns * 2 if configured else 0,
            "provider_configured": configured,
            "note": ("No provider is configured, so this run exercises the "
                     "deterministic governed reader and costs nothing."
                     if not configured else
                     "Each turn makes at most one reading call and one "
                     "interpretation call.")}


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="intelligence_factory.certify",
        description="Evaluate CreditProbe and, optionally, freeze a release.")
    parser.add_argument("--certify", action="store_true",
                        help="run the SEALED HOLDOUT and write a release")
    parser.add_argument("--no-variants", action="store_true",
                        help="development mode only: skip generated variants")
    parser.add_argument("--estimate", action="store_true",
                        help="print what the run would cost and stop")
    parser.add_argument("--out", default=str(RELEASE_DIR),
                        help="where to write the frozen release")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(message)s")

    from intelligence_factory import curriculum, generators, holdout

    cases = (list(holdout.CASES) if args.certify else
             (list(curriculum.CASES) if args.no_variants
              else generators.expand(list(curriculum.CASES))))

    estimate = cost_estimate(cases)
    print(f"{'CERTIFICATION' if args.certify else 'DEVELOPMENT'}: "
          f"{estimate['cases']} cases, {estimate['turns']} turns, "
          f"up to {estimate['model_calls_if_live']} model calls.")
    print(estimate["note"])
    if args.estimate:
        return 0

    report = certification() if args.certify else development(
        variants=not args.no_variants)
    accuracy = report.accuracy

    print()
    for measured in accuracy.rates.values():
        print(" ", measured.sentence())
    print(" ", accuracy.coverage.sentence())
    print()
    claim = accuracy.claim(99.99)
    print(" ", claim["sentence"])
    print(" ", _evidence(accuracy).get("sentence", ""))

    if accuracy.critical_failures:
        print("\nCRITICAL FAILURES — these block a release:")
        for failure in accuracy.critical_failures:
            print("  ✗", failure)

    failed = [c for c in report.cases if not c.ok]
    if failed:
        print(f"\n{len(failed)} case(s) did not do what was asked:")
        for case in failed[:12]:
            print(f"  ✗ {case.case_id}: {'; '.join(case.problems[:2])}")

    if args.certify:
        path = freeze(report, directory=Path(args.out))
        print(f"\nRelease {report.release_id} written to {path}")
        print("Status:", report.manifest["certification"]["status"])
        for blocker in report.blockers:
            print("  blocked by:", blocker)
        return 0 if report.passed else 1

    return 0 if not accuracy.critical_failures else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["GATE_PRECISION", "RELEASE_DIR", "Report", "certification",
           "cost_estimate", "development", "freeze", "main", "manifest",
           "measure"]
