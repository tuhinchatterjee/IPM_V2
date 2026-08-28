"""
What the evidence permits the product to claim. P0.9.

The defect this exists to make impossible
-----------------------------------------
A Trace was observed showing, at the same time:

    0 governed analyses          nothing was computed
    no assurance pass            no check ran
    Result stage: failed         and yet
    VALIDATED · 4 of 4 checks passed

Every one of those statements was produced by a different piece of code
reading a different thing, and none of them asked whether an analysis had
actually happened. "All checks passed" was asserted from the run's STATUS —
`if status == "succeeded"` — so a metadata lookup that succeeded at looking
nothing up reported that its checks had passed. There were no checks.

The rule
--------
Stage status is DERIVED from persisted facts, never asserted. P0.9 names them:

    ANALYSED    at least one governed analysis, or an explicitly valid
                no-analysis metadata task that says so
    VALIDATED   an assurance record with checks that actually ran
    DECIDED     a grounded conclusion record
    ACTIONED    a persisted action, case or workflow result — or an explicit
                "answer only", which is a real answer and is recorded as one
    RESULT      a persisted result

and two consequences that matter more than the list:

    SKIPPED IS NOT PASS.  A check that did not run is not a check that passed,
    and the only honest word for it is "not checked".

    FAILURE ROLLS UP.  A failed task fails its stage, and a failed stage fails
    the run. A green summary over a red step is the specific thing that makes
    a Trace worse than no Trace: it is confidently wrong.

How it is used
--------------
`permit()` is a CEILING. Nothing here raises a claim; it can only lower one.
Callers compute their status however they already do and then pass it through,
so a component that was already honest is unaffected and one that was not
cannot stay that way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage status
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT_RUN"
NOT_APPLICABLE = "NOT_APPLICABLE"

STATES: tuple[str, ...] = (PASS, FAIL, NOT_RUN, NOT_APPLICABLE)

ANALYSED = "ANALYSED"
VALIDATED = "VALIDATED"
DECIDED = "DECIDED"
ACTIONED = "ACTIONED"
RESULT = "RESULT"

STAGES: tuple[str, ...] = (ANALYSED, VALIDATED, DECIDED, ACTIONED, RESULT)

STAGE_LABELS: dict[str, str] = {
    ANALYSED: "Analysed",
    VALIDATED: "Validated",
    DECIDED: "Concluded",
    ACTIONED: "Actioned",
    RESULT: "Result",
}

#: What each state means on screen. NOT_RUN is worded as a statement of fact
#: rather than as a warning: "no check ran" is not an error, and dressing it as
#: one teaches people to ignore it.
STATE_MEANING: dict[str, str] = {
    PASS: "Completed, with evidence recorded.",
    FAIL: "Did not complete.",
    NOT_RUN: "Did not run. Nothing was recorded for this stage.",
    NOT_APPLICABLE: "Not required for this request, and said so explicitly.",
}


# ---------------------------------------------------------------------------
# The facts
# ---------------------------------------------------------------------------


@dataclass
class Evidence:
    """What a run actually left behind.

    Counts and flags only. Every field is something that was persisted or was
    not; there is no field here whose value depends on how a run described
    itself.
    """

    #: Governed analyses that ran and produced a result.
    analyses: int = 0
    #: Rows, figures or a stored result document — anything a reader can open.
    results: int = 0
    #: Checks that were actually executed. NOT the number defined.
    checks_run: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    #: A written conclusion that cites the run's own figures.
    conclusion_grounded: bool = False
    #: A case, workflow item or other persisted side effect.
    actions: int = 0
    #: True when the request was legitimately answerable with no analysis — a
    #: metadata lookup, a definition — and the run RECORDED that rather than
    #: leaving the stage empty.
    no_analysis_declared: bool = False
    #: True when the run is an answer and was never going to act.
    answer_only: bool = True
    #: Tasks or steps that failed.
    failures: int = 0
    #: Free-text notes, for the Trace.
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyses": self.analyses,
            "results": self.results,
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "conclusion_grounded": self.conclusion_grounded,
            "actions": self.actions,
            "no_analysis_declared": self.no_analysis_declared,
            "answer_only": self.answer_only,
            "failures": self.failures,
            "notes": list(self.notes),
        }


@dataclass
class Stage:
    """One stage, its derived status, and the fact behind it."""

    stage: str
    state: str
    because: str

    @property
    def label(self) -> str:
        return STAGE_LABELS.get(self.stage, self.stage)

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "label": self.label, "state": self.state,
                "meaning": STATE_MEANING.get(self.state, ""),
                "because": self.because}


def derive(evidence: Evidence) -> list[Stage]:
    """Every stage's status, from the facts alone."""
    stages: list[Stage] = []

    if evidence.failures and not evidence.analyses:
        stages.append(Stage(ANALYSED, FAIL,
                            f"{evidence.failures} step(s) failed and no "
                            f"governed analysis produced a result."))
    elif evidence.analyses:
        stages.append(Stage(ANALYSED, PASS,
                            f"{evidence.analyses} governed "
                            f"{'analysis' if evidence.analyses == 1 else 'analyses'} ran."))
    elif evidence.no_analysis_declared:
        stages.append(Stage(ANALYSED, NOT_APPLICABLE,
                            "This request was answered from the governed "
                            "catalogue; no analysis was required and the run "
                            "recorded that."))
    else:
        stages.append(Stage(ANALYSED, NOT_RUN,
                            "No governed analysis ran and nothing declared "
                            "that none was needed."))

    if evidence.checks_failed:
        stages.append(Stage(VALIDATED, FAIL,
                            f"{evidence.checks_failed} of "
                            f"{evidence.checks_run} checks did not pass."))
    elif evidence.checks_run:
        stages.append(Stage(VALIDATED, PASS,
                            f"{evidence.checks_passed} of "
                            f"{evidence.checks_run} checks passed."))
    else:
        # The one that was being reported as PASS. It is not a pass.
        stages.append(Stage(VALIDATED, NOT_RUN,
                            "No validation check ran, so nothing about these "
                            "figures has been checked."))

    stages.append(Stage(
        DECIDED, PASS if evidence.conclusion_grounded else NOT_RUN,
        "A conclusion was written and every figure in it comes from this run."
        if evidence.conclusion_grounded else
        "No grounded conclusion was recorded."))

    if evidence.actions:
        stages.append(Stage(ACTIONED, PASS,
                            f"{evidence.actions} action(s) were persisted."))
    elif evidence.answer_only:
        stages.append(Stage(ACTIONED, NOT_APPLICABLE,
                            "This request was answered rather than acted on."))
    else:
        stages.append(Stage(ACTIONED, NOT_RUN,
                            "An action was expected and none was persisted."))

    if evidence.results:
        stages.append(Stage(RESULT, PASS,
                            f"{evidence.results} result(s) are stored and can "
                            f"be opened."))
    elif evidence.failures:
        stages.append(Stage(RESULT, FAIL,
                            "The run failed before a result was stored."))
    elif evidence.no_analysis_declared:
        stages.append(Stage(RESULT, NOT_APPLICABLE,
                            "No result was expected for a catalogue answer."))
    else:
        stages.append(Stage(RESULT, NOT_RUN, "No result was stored."))

    return stages


def failed(stages: list[Stage]) -> bool:
    """Whether any stage failed. Failure rolls up to the run."""
    return any(s.state == FAIL for s in stages)


def stage(stages: list[Stage], name: str) -> Stage | None:
    return next((s for s in stages if s.stage == name), None)


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------

#: Assurance statuses, worst first. Kept as strings rather than importing
#: `assurance` so this module has no dependency on the thing it constrains.
_ASSURANCE_ORDER: tuple[str, ...] = (
    "NEEDS REVIEW", "LIMITED EVIDENCE", "VALIDATED", "HIGH ASSURANCE",
)


def permit(status: str, evidence: Evidence) -> tuple[str, str]:
    """The highest assurance status this evidence supports, and why.

    A CEILING, never a promotion: the returned status is `status` or something
    weaker. A caller whose own reasoning was already honest sees no change.
    """
    stages = derive(evidence)
    ceiling, because = _ceiling(stages, evidence)
    if _rank(status) <= _rank(ceiling):
        return status, ""
    logger.info("assurance lowered from %s to %s: %s", status, ceiling, because)
    return ceiling, because


def _ceiling(stages: list[Stage], evidence: Evidence) -> tuple[str, str]:
    if failed(stages):
        broken = next(s for s in stages if s.state == FAIL)
        return "NEEDS REVIEW", (
            f"{broken.label} failed — {broken.because} A failed stage cannot "
            f"carry a validated answer.")

    analysed = stage(stages, ANALYSED)
    if analysed and analysed.state == NOT_RUN:
        return "LIMITED EVIDENCE", (
            "No governed analysis ran, so there is nothing for a validation "
            "to have validated.")

    validated = stage(stages, VALIDATED)
    if validated and validated.state == NOT_RUN:
        return "LIMITED EVIDENCE", (
            "No validation check ran. A check that did not run is not a check "
            "that passed.")

    return "HIGH ASSURANCE", ""


def _rank(status: str) -> int:
    try:
        return _ASSURANCE_ORDER.index(str(status or "").strip().upper())
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Reading the facts off what a run produced
# ---------------------------------------------------------------------------


def of_investigation(investigation: Any, answered: Any = None) -> Evidence:
    """The evidence a single governed analysis left behind.

    Reads the run rather than trusting its status word. A step whose execution
    was `metadata` looked something up in the catalogue; it computed nothing,
    and counting it as a calculation is how "1 calculation · all checks passed"
    came to be printed over a run that calculated nothing.
    """
    if investigation is None:
        return Evidence(answer_only=True)

    steps = list(getattr(investigation, "steps", ()) or [])
    analyses = 0
    results = 0
    metadata_only = 0
    failures = 0
    for step in steps:
        found = _as_dict(step)
        status = str(found.get("status") or "")
        result = found.get("result") or {}
        execution = str((result.get("meta") or {}).get("execution") or "")
        if status == "failed":
            failures += 1
            continue
        if execution == "metadata":
            metadata_only += 1
            continue
        analyses += 1
        if result.get("rows") or result.get("values"):
            results += 1

    narrative = getattr(investigation, "narrative", None)
    answer = str(getattr(narrative, "direct_answer", "") or "") if narrative else ""

    # The invariant report and the written interpretation, which is where the
    # runtime actually records what it checked. Reading these off the narrative
    # — which has no such fields — is why the single-analysis path counted zero
    # checks on runs that had validated their figures.
    report = getattr(answered, "invariants", None)
    checks = list(getattr(report, "checks", ()) or []) if report else []
    warnings = list(getattr(report, "failures", ()) or []) if report else []
    written = getattr(answered, "written", None)
    ungrounded = list(getattr(written, "ungrounded", ()) or []) if written else []

    status = str(getattr(investigation, "status", "") or "")
    return Evidence(
        analyses=analyses,
        results=results,
        checks_run=len(checks),
        checks_passed=max(0, len(checks) - len(warnings)),
        checks_failed=len(warnings),
        conclusion_grounded=bool(answer) and not ungrounded and analyses > 0,
        actions=0,
        no_analysis_declared=bool(metadata_only) and analyses == 0,
        answer_only=True,
        failures=failures + (1 if status in ("failed", "rejected") else 0),
    )


def _as_dict(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        return step
    found = getattr(step, "to_dict", None)
    if callable(found):
        try:
            return dict(found())
        except Exception:  # noqa: BLE001 - a step that cannot describe itself
            return {}
    return {
        "status": getattr(step, "status", ""),
        "result": getattr(step, "result", {}) or {},
    }


def parts(evidence: Evidence) -> list[str]:
    """The counts a completion line may state. §11.

    Only what happened. "all checks passed" appears when checks ran and passed,
    and never as a synonym for "the run did not crash".
    """
    found: list[str] = []
    if evidence.analyses:
        found.append(f"{evidence.analyses} "
                     f"{'calculation' if evidence.analyses == 1 else 'calculations'}")
    elif evidence.no_analysis_declared:
        found.append("no calculation needed")
    if evidence.checks_failed:
        found.append(f"{evidence.checks_failed} check(s) did not pass")
    elif evidence.checks_run:
        found.append(f"all {evidence.checks_run} checks passed"
                     if evidence.checks_run > 1 else "the check passed")
    else:
        found.append("not validated")
    return found


__all__ = [
    "ACTIONED",
    "ANALYSED",
    "DECIDED",
    "Evidence",
    "FAIL",
    "NOT_APPLICABLE",
    "NOT_RUN",
    "PASS",
    "RESULT",
    "STAGES",
    "STATES",
    "Stage",
    "VALIDATED",
    "derive",
    "failed",
    "of_investigation",
    "parts",
    "permit",
    "stage",
]
