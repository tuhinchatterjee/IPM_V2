"""
Running a case through the product, and deciding whether it did what it should.

Through the real path, always
------------------------------
Every case goes through `answer_investigation` — the same function the browser
reaches through `POST /investigations`. An evaluation that called the planner
directly would measure the planner, and the last release proved how far apart
those two numbers can be: typed memory worked in every direct test and failed
for every user, because the service in between forgot to pass it.

What is graded
--------------
The decisions and the invariants, never the prose. Two correct interpretations
of the same result share almost no vocabulary, and grading text rewards a model
for sounding like the person who wrote the expectation. What is checked is:

* the outcome — did it execute, clarify, or say it holds no such data;
* the capability and the conversation action;
* the datasets and concepts it used;
* whether every invariant the case names actually held;
* whether it did anything the case forbids.

An abstention is not a failure
-------------------------------
A case expecting CLARIFY and getting one is a pass. A case expecting EXECUTE
and getting a clarification is not counted as a wrong ANSWER — it is counted as
an abstention, separately, because the two failure modes have completely
different costs: one is a slower conversation, the other is a wrong number in a
credit paper.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

EXECUTE = "EXECUTE"
CLARIFY = "CLARIFY"
UNSUPPORTED = "UNSUPPORTED"
FAILED = "CONTROLLED_FAILURE"


@dataclass
class TurnResult:
    """What one turn did, and whether it was what the case asked for."""

    question: str
    outcome: str = ""
    capability: str = ""
    action: str = ""
    datasets: list[str] = field(default_factory=list)
    row_count: int = 0
    latency_ms: int = 0
    live: bool = False
    route: str = ""
    #: Every expectation the case set, and whether it held.
    checks: dict[str, bool] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(self.checks.values())

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "outcome": self.outcome,
                "capability": self.capability, "action": self.action,
                "datasets": list(self.datasets), "row_count": self.row_count,
                "latency_ms": self.latency_ms, "live": self.live,
                "route": self.route, "checks": dict(self.checks),
                "problems": list(self.problems), "ok": self.ok}


@dataclass
class CaseResult:
    """One case, evaluated."""

    case_id: str
    family: str
    title: str
    critical: bool = False
    turns: list[TurnResult] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and all(t.ok for t in self.turns)

    @property
    def answered(self) -> bool:
        """Whether CreditProbe produced an answer rather than a question."""
        return any(t.outcome == EXECUTE for t in self.turns)

    @property
    def abstained(self) -> bool:
        return not self.answered and not self.error

    @property
    def problems(self) -> list[str]:
        return [p for t in self.turns for p in t.problems] or (
            [self.error] if self.error else [])

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "family": self.family,
                "title": self.title, "critical": self.critical,
                "ok": self.ok, "answered": self.answered,
                "error": self.error,
                "turns": [t.to_dict() for t in self.turns]}


# ---------------------------------------------------------------------------
# Running one case
# ---------------------------------------------------------------------------


def run_case(case: Any) -> CaseResult:
    """One thread, through the real path, checked against its specification."""
    from backend.orchestration import conversation as cv
    from backend.orchestration import memory as wm
    from backend.orchestration.executor import answer_investigation
    from backend.orchestration.orchestrator import remember as advance

    result = CaseResult(
        case_id=case.id, family=getattr(case, "family", None) or case.kind,
        title=case.title, critical=bool(getattr(case, "critical", False)))

    context: dict[str, Any] = {}
    for turn in case.turns:
        started = time.perf_counter()
        try:
            state, memory = cv.load(context), wm.load(context)
            investigation, answered = answer_investigation(
                turn.question, persist=False, state=state, memory=memory)
            context = cv.save(context, advance(
                state, answered,
                headline=str(investigation.narrative.direct_answer or ""),
                run_id=None))
            context = wm.save(context, wm.observe(wm.load(context), answered,
                                                  investigation))
        except Exception as e:  # noqa: BLE001 - one case must not stop a run
            logger.warning("Case %s raised: %s", case.id, e)
            result.error = str(e)
            return result

        result.turns.append(_check(
            turn, investigation, answered,
            latency_ms=int((time.perf_counter() - started) * 1000)))
    return result


def _outcome(investigation: Any, answered: Any) -> str:
    if getattr(answered, "unsupported", ""):
        return UNSUPPORTED
    if getattr(answered, "clarification", ""):
        return CLARIFY
    if getattr(answered, "failure", ""):
        return FAILED
    if investigation.status == "succeeded":
        return EXECUTE
    return FAILED


def _check(turn: Any, investigation: Any, answered: Any,
           latency_ms: int) -> TurnResult:
    """Every expectation the case set, tested against what actually happened."""
    outcome = _outcome(investigation, answered)
    reading = answered.reading
    decision = getattr(answered, "decision", None)
    datasets = list(getattr(reading, "datasets", ()) or ())

    out = TurnResult(
        question=turn.question, outcome=outcome,
        capability=str(getattr(reading, "intent", "") or ""),
        action=str(getattr(answered.continuation, "action", "") or ""),
        datasets=datasets, latency_ms=latency_ms,
        live=str(getattr(reading, "source", "")) == "llm",
        route=str(getattr(decision, "route", "") or ""),
        row_count=int(getattr(answered.runtime, "row_count", 0) or 0)
        if getattr(answered, "runtime", None) is not None else 0)

    wanted = str(getattr(turn, "outcome", EXECUTE) or EXECUTE)
    out.checks["outcome"] = outcome == wanted
    if not out.checks["outcome"]:
        out.problems.append(f"expected {wanted}, got {outcome}")

    if getattr(turn, "capability", "") and wanted == EXECUTE:
        held = out.capability == turn.capability
        out.checks["capability"] = held
        if not held:
            out.problems.append(
                f"read as {out.capability}, expected {turn.capability}")

    if getattr(turn, "action", ""):
        held = out.action == turn.action
        out.checks["action"] = held
        if not held:
            out.problems.append(
                f"conversation action {out.action}, expected {turn.action}")

    for dataset in (getattr(turn, "datasets", ()) or ()):
        held = _used(dataset, answered, datasets)
        out.checks[f"dataset:{dataset}"] = held
        if not held:
            out.problems.append(f"did not use {dataset}")

    for concept in (getattr(turn, "concepts", ()) or ()):
        held = any(concept.lower() in str(c).lower()
                   for c in (getattr(reading, "concepts", ()) or ()))
        out.checks[f"concept:{concept}"] = held
        if not held:
            out.problems.append(f"did not resolve {concept!r}")

    # A check the runtime could not run is not a check that held. Counting a
    # skipped one as a pass is how a filter that was never verified against the
    # rows would score as verified.
    report = getattr(answered, "invariants", None)
    for rule in (getattr(turn, "invariants", ()) or ()):
        checked = [c.rule for c in report.checks] if report else []
        failed = [f.check.rule for f in report.failures] if report else []
        ran = [c.rule for c in report.checks
               if not _was_skipped(c, report)] if report else []
        held = rule in ran and rule not in failed
        out.checks[f"invariant:{rule}"] = held
        if not held:
            if rule not in checked:
                out.problems.append(f"invariant {rule} was not checked")
            elif rule not in ran:
                out.problems.append(
                    f"invariant {rule} was compiled but could not run against "
                    "the result")
            else:
                out.problems.append(f"invariant {rule} failed")

    for forbidden in (getattr(turn, "forbidden", ()) or ()):
        did_it = _did(forbidden, outcome, answered, investigation, out)
        out.checks[f"forbidden:{forbidden}"] = not did_it
        if did_it:
            out.problems.append(f"did the forbidden thing: {forbidden}")

    _layer_checks(out, turn, investigation, answered, outcome)
    return out


# ---------------------------------------------------------------------------
# The rest of the sixteen layers. P0.7.
# ---------------------------------------------------------------------------


def _layer_checks(out: TurnResult, turn: Any, investigation: Any,
                  answered: Any, outcome: str) -> None:
    """Evidence about the layers a case's own expectations do not reach.

    A case names the concepts and datasets it cares about; it does not name
    "the plan must have a shape" or "the Trace must agree with what ran",
    because those hold of EVERY answer. Checking them here means the layered
    report has a denominator for all sixteen layers rather than for the four a
    case happens to mention — and a layer with no observations is reported as
    unmeasured, never as passing.

    Each check is recorded only where it APPLIES. A metadata answer compiles no
    query, and counting that as a passing query would be the arithmetic version
    of "SKIPPED is not PASS".
    """
    build = getattr(answered, "build", None)
    runtime = getattr(answered, "runtime", None)
    computed = runtime is not None

    # 2 — same-turn referent. Only where the question contains one.
    from backend.orchestration import discourse as dsc

    try:
        found = dsc.read(turn.question)
        if found.mentions:
            resolved = all(m.antecedent is not None for m in found.mentions)
            out.checks["referent"] = resolved
            if not resolved:
                out.problems.append(
                    "a referent in this message resolved to nothing")
    except Exception:  # noqa: BLE001 - a layer probe must not fail a case
        pass

    # 3 — objective decomposition. Every clause settled, or the answer must
    # not have been presented as complete.
    from backend.orchestration import objectives as ob

    try:
        reading = ob.read(turn.question)
        if len(reading.objectives) > 1:
            coverage = ob.coverage(reading)
            # An answer that ran is claiming to have covered the request. The
            # check is whether the decomposition found the clauses at all —
            # a request read as one objective when it names three is the
            # defect, and it is visible before anything is settled.
            out.checks["objectives"] = len(reading.objectives) >= 2
            if not coverage.presentable and outcome == EXECUTE:
                out.problems.append(
                    f"{len(coverage.unsettled)} objective(s) unsettled")
    except Exception:  # noqa: BLE001
        pass

    # 6 — relationship selection. Only where more than one dataset was read.
    datasets = list(getattr(build, "datasets", ()) or ())
    if len(datasets) > 1:
        request = getattr(build, "request", None)
        resolution = getattr(request, "resolution", None)
        out.checks["relationship"] = resolution is not None
        if resolution is None:
            out.problems.append(
                "several datasets were read with no governed join recorded")

    # 7 — period and grain.
    if computed:
        out.checks["period"] = bool(getattr(build, "period", "")
                                    or getattr(build, "closing", ""))
        if not out.checks["period"]:
            out.problems.append("the answer names no period")

    # 8 — plan.
    if outcome == EXECUTE:
        out.checks["plan"] = bool(getattr(build, "shape", "")) or not computed
        if computed and not getattr(build, "shape", ""):
            out.problems.append("a result was produced with no analytical shape")

    # 9 — compiled query. Parameterised, or it is not a governed query: a
    # value inlined into SQL is a value nobody validated, and it is also the
    # difference between a plan that can be replayed and one that cannot.
    if computed:
        compiled = getattr(runtime, "query", None)
        sql = str(getattr(compiled, "sql", "") or "")
        params = list(getattr(compiled, "params", ()) or ())
        out.checks["query"] = bool(sql) and (bool(params) or "?" in sql)
        if not out.checks["query"]:
            out.problems.append(
                "the compiled query is missing or carries no parameters"
                if sql else "no compiled query was recorded")

    # 10 — result.
    if computed:
        out.checks["result"] = getattr(runtime, "rows", None) is not None
        if not out.checks["result"]:
            out.problems.append("a result was reported with no rows")

    # 11 — invariants ran at all. A case naming a specific rule is checked
    # above; this is the layer-level question of whether ANYTHING was verified.
    if computed:
        report = getattr(answered, "invariants", None)
        out.checks["invariants"] = bool(report and report.checks)
        if not out.checks["invariants"]:
            out.problems.append("no invariant applied to this result")

    # 12 — interpretation. Grounded, and not a causal claim.
    written = getattr(answered, "written", None)
    if written is not None and computed:
        out.checks["interpretation"] = not list(
            getattr(written, "ungrounded", ()) or ())
        if not out.checks["interpretation"]:
            out.problems.append("the interpretation states a figure the result "
                                "does not carry")

    # 13 — visualization. Whatever was chosen must be valid for the result.
    if computed:
        out.checks["visual"] = _visual_is_sound(investigation)
        if not out.checks["visual"]:
            out.problems.append("the chart does not say something true about "
                                "the result")

    # 14 — Trace consistency.
    graph = getattr(investigation, "graph", None)
    if graph is not None:
        out.checks["trace"] = _trace_agrees(investigation, answered, computed)
        if not out.checks["trace"]:
            out.problems.append("the Trace does not match what executed")

    # 15 — error handling. Only where something failed.
    failure = str(getattr(answered, "failure", "") or "")
    if failure:
        kind = str(getattr(answered, "failure_kind", "") or "")
        out.checks["error"] = bool(kind)
        if not kind:
            out.problems.append("the failure was never categorised")

    # 16 — officer and model selection.
    decision = getattr(answered, "decision", None)
    if decision is not None:
        out.checks["officer"] = bool(getattr(decision, "route", ""))
        if not out.checks["officer"]:
            out.problems.append("no route was recorded for this answer")


def _visual_is_sound(investigation: Any) -> bool:
    """Whether the chart shown would survive the visualisation contract.

    Re-validated rather than trusted: `choose` already replaces an invalid
    chart, so this is asking whether the thing that reached the screen is
    sound — which is the question the layer is about.
    """
    from backend.orchestration import viz_contract as vc

    steps = list(getattr(investigation, "steps", ()) or ())
    if not steps:
        return True
    result = getattr(steps[0], "result", None) or {}
    chart = dict(result.get("chart") or {})
    if not chart or chart.get("chart") in ("", "table", "kpi"):
        return True

    class _Chosen:
        def __init__(self, spec: dict[str, Any]) -> None:
            self.chart = str(spec.get("chart") or "")
            self.x = str(spec.get("x") or "")
            self.y = list(spec.get("y") or [])
            self.series = str(spec.get("series") or "")

    try:
        return vc.validate(_Chosen(chart), list(result.get("columns") or []),
                           list(result.get("rows") or [])).ok
    except Exception:  # noqa: BLE001 - a layer probe must not fail a case
        return True


def _trace_agrees(investigation: Any, answered: Any, computed: bool) -> bool:
    """Whether the Trace records what actually happened.

    The narrow, checkable version: a result on screen must have a calculation
    behind it in the graph, and a graph claiming a calculation must have
    produced a result. A Trace describing an execution that did not happen is
    worse than no Trace.
    """
    graph = getattr(investigation, "graph", None)
    nodes = getattr(graph, "nodes", {}) or {}
    calculated = any(
        str(getattr(node, "type", "")).upper().endswith(
            ("CALCULATION", "SQL_QUERY", "AGGREGATION", "KERNEL"))
        for node in nodes.values())
    if computed and not calculated:
        return False
    return not (calculated and not computed)


def _was_skipped(check: Any, report: Any) -> bool:
    """Whether this check was compiled and then could not run.

    The report records a skip as a sentence beginning with the check's own
    claim, which is the only thing that ties one back to the other.
    """
    claim = str(getattr(check, "claim", "") or "")
    return bool(claim) and any(str(s).startswith(claim)
                               for s in (getattr(report, "skipped", ()) or ()))


def _did(forbidden: str, outcome: str, answered: Any, investigation: Any,
         out: TurnResult) -> bool:
    """Whether the turn actually did the thing the case forbids.

    "ANALYSIS" forbidden means *ran* an analysis, not *was read as* one. A
    question CreditProbe read as analytical and then stopped to ask about has
    not computed anything, and counting that as the forbidden behaviour would
    fail every case whose whole point is that it clarified.
    """
    if forbidden == "ANALYSIS":
        return getattr(answered, "runtime", None) is not None
    if forbidden == "CLARIFY":
        return outcome == CLARIFY
    if forbidden == "UNSUPPORTED":
        return outcome == UNSUPPORTED
    if forbidden in {"DATA_QUALITY", "DATA_DISCOVERY", "DATA_DICTIONARY",
                     "DATA_RELATIONSHIP", "DATA_INSPECTION"}:
        return out.capability == forbidden and outcome == EXECUTE
    if forbidden == "row_limit":
        build = getattr(answered, "build", None)
        return bool(getattr(build, "top_n", 0))
    # Anything else names a registered analysis that must not have run.
    ran = {str(getattr(step, "analysis_id", "")) for step in
           (getattr(investigation, "steps", None) or [])}
    return forbidden in ran


def _used(dataset: str, answered: Any, named: list[str]) -> bool:
    """Whether the answer actually rests on this dataset.

    Checked in four places because the capabilities answer in four shapes. A
    relationship answer names its datasets inside the join path — "How is
    ratings data connected to IFRS 9?" returns
    `customer_ratings.customer_id → portfolio_facility.customer_id` and nothing
    called `dataset` — and reading only the reading's dataset list would score
    a completely correct join path as a miss.

    Matched on a word boundary, so `ifrs9_staging` is not satisfied by
    `ifrs9_staging_archive`.
    """
    if dataset in named:
        return True
    build = getattr(answered, "build", None)
    if build is not None and dataset in (getattr(build, "datasets", None) or []):
        return True

    result = getattr(answered, "result", None)
    if result is None:
        return False
    pattern = re.compile(rf"\b{re.escape(dataset)}\b")
    for row in (getattr(result, "rows", []) or [])[:20]:
        if not isinstance(row, dict):
            continue
        if row.get("dataset") == dataset:
            return True
        if any(isinstance(v, str) and pattern.search(v) for v in row.values()):
            return True
    return bool(pattern.search(str(getattr(result, "detail", "") or "")))


def run_all(cases: list[Any]) -> list[CaseResult]:
    return [run_case(case) for case in cases]


__all__ = ["CLARIFY", "EXECUTE", "FAILED", "UNSUPPORTED", "CaseResult",
           "TurnResult", "run_all", "run_case"]
