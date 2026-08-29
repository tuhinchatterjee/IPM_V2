"""
One request, driven through the real governed path, measured. §2, §3.

    §3: "A different officer badge is not proof of a different execution
         path."

What a probe is
----------------
A single call into `agentic.run` — the same function the Cockpit and a
Project Investigation both reach — with everything §2 asks for read back off
what was PERSISTED rather than off what the code intended to do. The
distinction matters: a field the orchestrator computed and dropped on the
floor is exactly the kind of defect this phase exists to find, and a probe
that read the in-memory object would never see it.

Why the probe is in `backend/` rather than in `tests/`
-------------------------------------------------------
Because the baseline script, the divergence assertions, the regression matrix
and the before/after report all need the same measurement, and four copies of
it would drift. The probe is the measuring instrument; the tests are
assertions about what it measures.

No provider, ever
------------------
The probe runs the deterministic governed path. With no key configured that
is what `agentic.run` does anyway, and `assert_no_provider_calls` makes it
structural rather than incidental: any attempt to reach a provider inside a
probe raises, so a probe cannot quietly become a live call.
"""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PROBE_VERSION = "1.0.0"


class ProviderCalled(AssertionError):
    """A probe tried to reach a model. §0: no live calls, no credits."""


@contextlib.contextmanager
def assert_no_provider_calls():
    """Make any provider call raise for the duration.

    Structural rather than a promise. Every entry point on the Anthropic
    provider is replaced with something that raises, so a probe that reached
    a model would fail loudly rather than spend money quietly.
    """
    from backend.llm import anthropic_provider as ap

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise ProviderCalled(
            "A proof probe attempted a live provider call. §0 forbids live "
            "Anthropic calls and API credits in Claude Code.")

    originals: dict[str, Any] = {}
    for name in ("structured", "complete", "stream"):
        if hasattr(ap.AnthropicProvider, name):
            originals[name] = getattr(ap.AnthropicProvider, name)
            setattr(ap.AnthropicProvider, name, explode)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(ap.AnthropicProvider, name, original)


# ---------------------------------------------------------------- the probe


@dataclass
class Probe:
    """§2's capture for one request.

    Every field is either read from a persisted record or left at its default
    and reported as absent. Nothing here is inferred from the question text —
    the whole point is to measure what the system DID.
    """

    # ---- what was asked
    probe_id: str = ""
    label: str = ""
    question: str = ""
    context: str = "cockpit"          # cockpit | project
    project_id: str = ""
    investigation_id: str = ""
    turn_index: int = 0

    # ---- what was expected (from the case, for scoring)
    expected_officer: int | None = None
    expected_specialists: tuple[str, ...] = ()
    expected_datasets: tuple[str, ...] = ()
    expected_outcome: str = ""        # answer | clarification | unsupported

    # ---- what actually happened
    ok: bool = False
    error: str = ""
    status: str = ""
    officer_level: int | None = None
    officer_title: str = ""
    officer_reason: str = ""
    complexity: int | None = None
    risk: int | None = None
    orchestrated: bool = False
    coordinated: bool = False
    escalated: bool = False
    specialists: list[str] = field(default_factory=list)
    task_count: int = 0
    agent_count: int = 0
    tool_calls: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    #: Catalogue entries a metadata answer LOOKED AT. Not datasets it read:
    #: a discovery answer reads dataset metadata and returns no rows, and
    #: counting the two together makes both numbers meaningless.
    consulted: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    period: str = ""
    grain: str = ""
    plan_steps: int = 0
    #: Steps the runtime actually executed. Different from `plan_steps`: a
    #: broad investigation runs governed probes and leaves executed steps
    #: without an AnalysisPlan, so plan steps is 0 on the most complex thing
    #: the product does.
    executed_steps: int = 0
    probes: int = 0
    plan_valid: bool = False
    rows_returned: int | None = None
    executed: bool = False
    invariants_passed: bool | None = None
    grounded: bool | None = None
    ungrounded: list[str] = field(default_factory=list)
    clarified: bool = False
    unsupported: bool = False
    conflicts: int = 0
    findings: int = 0
    limitations: list[str] = field(default_factory=list)
    repairs: int = 0
    model_calls: int = 0
    approvals_required: int = 0
    trace_nodes: list[str] = field(default_factory=list)

    # ---- assurance
    flow: str = ""
    assurance_status: str = ""
    assurance_score: float | None = None
    coverage_pct: float = 0.0
    critical_failures: list[str] = field(default_factory=list)
    critical_not_available: list[str] = field(default_factory=list)
    mandatory_unresolved: list[str] = field(default_factory=list)
    checks_by_outcome: dict[str, int] = field(default_factory=dict)

    # ---- cost
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id, "label": self.label,
            "question": self.question, "context": self.context,
            "project_id": self.project_id,
            "investigation_id": self.investigation_id,
            "turn_index": self.turn_index,
            "expected": {
                "officer": self.expected_officer,
                "specialists": list(self.expected_specialists),
                "datasets": list(self.expected_datasets),
                "outcome": self.expected_outcome,
            },
            "ok": self.ok, "error": self.error, "status": self.status,
            "officer": {
                "level": self.officer_level, "title": self.officer_title,
                "reason": self.officer_reason,
                "complexity": self.complexity, "risk": self.risk,
                "orchestrated": self.orchestrated,
                "coordinated": self.coordinated, "escalated": self.escalated,
            },
            "specialists": list(self.specialists),
            "agent_count": self.agent_count, "task_count": self.task_count,
            "tool_calls": list(self.tool_calls),
            "datasets": list(self.datasets), "methods": list(self.methods),
            "period": self.period, "grain": self.grain,
            "plan": {"steps": self.plan_steps, "valid": self.plan_valid,
                     "executed_steps": self.executed_steps,
                     "probes": self.probes},
            "execution": {"executed": self.executed,
                          "rows": self.rows_returned},
            "invariants_passed": self.invariants_passed,
            "grounded": self.grounded, "ungrounded": list(self.ungrounded),
            "clarified": self.clarified, "unsupported": self.unsupported,
            "conflicts": self.conflicts, "findings": self.findings,
            "limitations": list(self.limitations),
            "repairs": self.repairs, "model_calls": self.model_calls,
            "approvals_required": self.approvals_required,
            "trace_nodes": list(self.trace_nodes),
            "assurance": {
                "flow": self.flow,
                "status": self.assurance_status,
                "operational_assurance": self.assurance_score,
                "coverage_pct": round(self.coverage_pct, 1),
                "critical_failures": list(self.critical_failures),
                "critical_not_available": list(self.critical_not_available),
                "mandatory_unresolved": list(self.mandatory_unresolved),
                "checks": dict(self.checks_by_outcome),
            },
            "duration_ms": self.duration_ms,
        }

    # ---- the scoring §27 reports on ------------------------------------

    @property
    def officer_correct(self) -> bool | None:
        if self.expected_officer is None:
            return None
        return self.officer_level == self.expected_officer

    @property
    def specialists_correct(self) -> bool | None:
        """Precision AND recall against what the case expects.

        Both, because the two failure modes are opposite and equally bad: a
        missed specialist means the answer is thin, and an unnecessary one
        means the run cost more and took longer for nothing.
        """
        if not self.expected_specialists:
            return None
        got = {s.lower() for s in self.specialists}
        want = {s.lower() for s in self.expected_specialists}
        return got == want

    @property
    def unnecessary_specialists(self) -> list[str]:
        if not self.expected_specialists:
            return []
        want = {s.lower() for s in self.expected_specialists}
        return sorted(s for s in self.specialists if s.lower() not in want)

    @property
    def missed_specialists(self) -> list[str]:
        if not self.expected_specialists:
            return []
        got = {s.lower() for s in self.specialists}
        return sorted(s for s in self.expected_specialists
                      if s.lower() not in got)

    @property
    def outcome_correct(self) -> bool | None:
        if not self.expected_outcome:
            return None
        actual = ("clarification" if self.clarified else
                  "unsupported" if self.unsupported else
                  "answer" if self.status in ("succeeded", "partial") else
                  self.status)
        return actual == self.expected_outcome


def _selection_fields(selection: Any) -> dict[str, Any]:
    """Read the officer selection without assuming its shape.

    Defensive because this is a measuring instrument: a probe that raised
    because a field was renamed would take the whole baseline with it, and
    "the field is absent" is itself a finding worth recording.
    """
    if selection is None:
        return {}
    found: dict[str, Any] = {}
    for source, target in (("level", "level"), ("title", "title"),
                           ("complexity", "complexity"), ("risk", "risk")):
        value = getattr(selection, source, None)
        if value is not None:
            found[target] = value
    reasons = getattr(selection, "reasons", None) or []
    if reasons:
        found["reason"] = "; ".join(
            str(getattr(r, "text", None) or getattr(r, "why", None) or r)
            for r in reasons[:3])
    elif getattr(selection, "reason", ""):
        found["reason"] = str(selection.reason)
    return found


def _trace_nodes(investigation: Any) -> list[str]:
    graph = getattr(investigation, "graph", None)
    if graph is None:
        return []
    try:
        return sorted(str(n.get("id", ""))
                      for n in graph.to_dict().get("nodes", []))
    except Exception:  # pragma: no cover - a malformed graph is a finding
        return []


def _consulted(answered: Any) -> list[str]:
    """The governed sources a catalogue answer looked at. §3 (D5).

    A metadata answer reads dataset METADATA rather than dataset rows, and
    it records which — in the handler result's own detail block. Nothing
    carried that up, so "what ratings data do you have?" reported zero
    datasets, and a catalogue answer that cannot say which catalogue it read
    cannot be checked against the catalogue.

    Kept separate from a build's datasets rather than merged into them: this
    is what was CONSULTED, and the probe's row count stays empty because no
    rows were read.
    """
    result = getattr(answered, "result", None)
    detail = getattr(result, "detail", None) or {}
    found: list[str] = []
    for entry in (detail.get("datasets") or []):
        name = (str(entry.get("name") or entry.get("dataset") or "")
                if isinstance(entry, dict) else str(entry or ""))
        if name and name not in found:
            found.append(name)
    if not found:
        primary = detail.get("primary")
        if isinstance(primary, dict):
            name = str(primary.get("dataset") or primary.get("name") or "")
            if name:
                found.append(name)
    return found


def run_probe(question: str, *, label: str = "", project_id: str = "",
              investigation_id: str | None = None,
              user_id: int | None = None,
              state: Any = None, memory: Any = None,
              expected_officer: int | None = None,
              expected_specialists: tuple[str, ...] = (),
              expected_datasets: tuple[str, ...] = (),
              expected_outcome: str = "",
              turn_index: int = 0) -> tuple[Probe, Any]:
    """Drive one request and capture everything §2 asks for.

    Returns the probe and the `Answered` object, so a caller running a
    multi-turn thread can carry the conversation state forward exactly as the
    service does.
    """
    from backend.agentic import interactive as agentic
    from backend.assurance import collect as ac
    from backend.assurance import record as rc
    from backend.db.engine import get_session
    from backend.proof import flows as fl

    probe = Probe(
        probe_id=f"pr-{uuid.uuid4().hex[:12]}", label=label or question[:60],
        question=question,
        context="project" if project_id else "cockpit",
        project_id=project_id, investigation_id=str(investigation_id or ""),
        turn_index=turn_index,
        expected_officer=expected_officer,
        expected_specialists=expected_specialists,
        expected_datasets=expected_datasets,
        expected_outcome=expected_outcome)

    started = time.perf_counter()
    officer: Any = None
    try:
        with assert_no_provider_calls(), get_session() as session:
            officer = agentic.run(
                session, question=question, user_id=user_id,
                project_id=project_id or None,
                investigation_id=investigation_id,
                state=state, memory=memory)
        probe.ok = True
    except ProviderCalled:
        raise
    except Exception as e:  # noqa: BLE001 - a failure is a measurement
        probe.error = f"{type(e).__name__}: {e}"
        probe.duration_ms = int((time.perf_counter() - started) * 1000)
        return probe, None
    probe.duration_ms = int((time.perf_counter() - started) * 1000)

    investigation = getattr(officer, "investigation", None)
    answered = getattr(officer, "answered", None)
    probe.status = str(getattr(investigation, "status", "") or "")
    probe.clarified = probe.status == "needs_clarification"
    probe.unsupported = bool(getattr(answered, "unsupported", None))

    chosen = _selection_fields(getattr(officer, "selection", None))
    probe.officer_level = chosen.get("level")
    probe.officer_title = str(chosen.get("title") or "")
    probe.officer_reason = str(chosen.get("reason") or "")
    probe.complexity = chosen.get("complexity")
    probe.risk = chosen.get("risk")
    probe.coordinated = bool(getattr(officer, "coordinated", False))
    probe.escalated = bool(getattr(officer, "escalated", False))

    outcome = getattr(officer, "outcome", None)
    probe.orchestrated = outcome is not None
    if outcome is not None:
        plan = getattr(outcome, "plan", None)
        agents = list(getattr(plan, "agents", None) or [])
        probe.agent_count = len(agents)
        probe.task_count = len(getattr(plan, "tasks", None) or [])
        probe.conflicts = len(getattr(outcome, "conflicts", None) or [])
        probe.findings = len(getattr(outcome, "findings", None) or [])
        probe.limitations = [str(x) for x in
                             (getattr(outcome, "limitations", None) or [])]
        try:
            from backend.agentic import registry

            probe.specialists = [registry.agent(a).business_name
                                 for a in agents if registry.agent(a)]
        except Exception:  # pragma: no cover
            probe.specialists = [str(a) for a in agents]

    build = getattr(answered, "build", None)
    # A composed answer — a broad investigation, a coordinated review — has no
    # build of its own; its work is in the sub-analyses. Reading only `build`
    # reported a review that ran six governed analyses over four datasets as
    # having executed nothing and read nothing. §3 (D4/D19).
    composition = getattr(answered, "composition", None)
    probe.datasets = sorted(
        str(d) for d in (getattr(composition, "datasets", None)
                         or getattr(build, "datasets", None)
                         or ([getattr(build, "dataset", "")]
                             if getattr(build, "dataset", "") else [])))
    # Kept apart from `datasets`, and the separation is the point. Merging
    # them made a metadata answer that consulted six catalogue entries report
    # more datasets than a two-domain analysis that READ three — so the
    # officer ladder stopped being monotonic on the dataset axis, and the
    # divergence instrument reported an escalation that did less work. It had
    # not; the instrument had started measuring two different things with one
    # number. §3 (D5).
    probe.consulted = sorted(_consulted(answered))
    probe.period = str(getattr(build, "period", "") or "")
    probe.grain = str(getattr(build, "output_grain", "")
                      or getattr(build, "grain", "") or "")
    method = getattr(build, "method", None)
    probe.methods = [str(method)] if method else []

    plan = getattr(investigation, "plan", None)
    steps = list(getattr(plan, "steps", None) or [])
    probe.plan_steps = len(steps)
    probe.plan_valid = bool(steps) and not (getattr(plan, "unmatched", None)
                                            or [])
    executed = list(getattr(investigation, "steps", None) or [])
    probe.executed_steps = len(executed)
    for step in executed:
        result = getattr(step, "result", None)
        if not isinstance(result, dict):
            continue
        summary = (result.get("detail") or {}).get("investigation") or {}
        found = summary.get("probes")
        if isinstance(found, list | tuple):
            probe.probes = max(probe.probes, len(found))
        elif isinstance(found, int):
            probe.probes = max(probe.probes, found)

    runtime = getattr(answered, "runtime", None)
    probe.executed = runtime is not None or bool(
        getattr(composition, "executed", False))
    if runtime is not None:
        probe.rows_returned = len(list(getattr(runtime, "rows", None) or []))
    elif composition is not None and composition.executed:
        probe.rows_returned = composition.rows
        probe.executed_steps = max(probe.executed_steps, composition.ran)

    invariants = getattr(answered, "invariants", None)
    if invariants is not None:
        # `Report` says `ok`. This read `passed`, which is on no invariant
        # report anywhere, so every executed analysis reported "invariants
        # not measured" and the baseline printed 0% — over runs where five
        # checks had been compiled and all five had held. D7 was raised as
        # "either the invariants do not hold or the signal is not surfaced in
        # a shape the collector reads"; it was the second. §3.
        #
        # A report with no checks stays None. Nothing was checked, and a
        # check that did not run is not a check that passed.
        checks = list(getattr(invariants, "checks", None) or [])
        probe.invariants_passed = (
            bool(getattr(invariants, "ok", False)) if checks else None)
    elif composition is not None:
        # None when nothing was checked, which is not the same as False. A
        # check that did not run is not a check that failed either. §3 (D7).
        probe.invariants_passed = composition.invariants_passed

    judgment = getattr(answered, "judgment", None) or {}
    contract = judgment.get("contract") or {}
    if contract.get("grounded") is not None:
        probe.grounded = bool(contract["grounded"])
        probe.ungrounded = [str(u) for u in (contract.get("ungrounded") or [])]

    probe.repairs = len(getattr(answered, "calls", None) or [])
    probe.model_calls = probe.repairs
    probe.trace_nodes = _trace_nodes(investigation)
    probe.tool_calls = [n for n in probe.trace_nodes
                        if n.startswith("run__") or n in ("query", "result")]

    # ---- the assurance record, built the same way the runtime builds it
    try:
        made = ac.build(investigation, answered,
                        investigation_id=str(investigation_id or ""),
                        project_id=project_id)
        verdict = made.overall()
        probe.assurance_status = verdict["overall_status"]
        probe.assurance_score = verdict["operational_assurance"]
        probe.coverage_pct = verdict["coverage_pct"]
        probe.critical_failures = list(made.critical_failures)
        probe.critical_not_available = list(made.critical_not_available)
        probe.mandatory_unresolved = list(made.skipped_mandatory)
        tally: dict[str, int] = {o: 0 for o in rc.OUTCOMES}
        for check in made.checks:
            tally[check.outcome] = tally.get(check.outcome, 0) + 1
        probe.checks_by_outcome = tally
    except Exception as e:  # noqa: BLE001 - measuring, not answering
        logger.warning("Probe could not build an assurance record: %s", e)

    probe.flow = fl.classify(
        answer_type=probe.status, executed=probe.executed,
        datasets=len(probe.datasets), consulted=len(probe.consulted),
        agentic_run=probe.orchestrated,
        specialists=len(probe.specialists), project_id=project_id)
    return probe, officer
