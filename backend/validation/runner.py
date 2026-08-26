"""
Running an intelligence check, and the order that makes it honest.

The sequence is the whole design
--------------------------------
1. load a benchmark thread — question(s) only;
2. run it through the **real** Investigation path, the same one the browser uses;
3. take what CreditProbe produced;
4. **only now** compute the reference, from a separate implementation;
5. score;
6. show the user both, side by side.

Step 4 cannot happen earlier, and nothing before it can see a reference. That is
enforced structurally rather than by care: `gold` and `benchmarks` are imported
here and nowhere in production, so there is no path by which an expected answer
could reach a prompt, a retrieval context, a planner or a tool description.

What a run is not
-----------------
It is not an Investigation. A benchmark thread is executed with `persist=False`
and never files a run, a message or a Trace version — a user's Investigations
list is theirs, and filling it with hidden test threads would be a strange thing
to do to somebody who pressed a button labelled RUN INTELLIGENCE CHECK.

A case that answered without reaching the live model FAILS the live-AI benchmark
however good its numbers are. The check exists to say whether the AI works; a
deterministic reading that happened to be right does not answer that question.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.validation import benchmarks, gold, scoring

logger = logging.getLogger(__name__)

#: How many threads one check runs, and how the sample is balanced (§AG).
SAMPLE = ("metadata", "calculation", "conversation")

#: Rows of a result kept on a case record, for the comparison view. Enough to
#: show a table; not a data export.
MAX_ROWS = 20


@dataclass
class CaseResult:
    """One benchmark thread, run and scored."""

    benchmark_id: str
    category: str
    title: str
    score: float = 0.0
    verdict: str = scoring.FAIL
    latency_ms: int = 0
    used_fallback: bool = False
    components: dict[str, float] = field(default_factory=dict)
    turns: list[dict[str, Any]] = field(default_factory=list)
    deductions: list[str] = field(default_factory=list)
    reference: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id, "category": self.category,
            "title": self.title, "score": self.score, "verdict": self.verdict,
            "latency_ms": self.latency_ms, "used_fallback": self.used_fallback,
            "components": dict(self.components), "turns": list(self.turns),
            "deductions": list(self.deductions),
            "reference": dict(self.reference),
        }


@dataclass
class RunResult:
    """One intelligence check."""

    score: float = 0.0
    band: str = ""
    tone: str = ""
    cases: list[CaseResult] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    ai_state: str = ""
    build_sha: str = ""
    app_version: str = ""
    benchmark_version: str = gold.BENCHMARK_VERSION
    data_version: str = ""
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    run_id: int | None = None

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.verdict == scoring.PASS)

    @property
    def partial(self) -> int:
        return sum(1 for c in self.cases if c.verdict == scoring.PARTIAL)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if c.verdict == scoring.FAIL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.run_id, "score": self.score, "band": self.band,
            "tone": self.tone, "label": f"AI POWERED · {self.band}"
            if self.band else "AI POWERED",
            "components": dict(self.components),
            "cases": [c.to_dict() for c in self.cases],
            "provider": self.provider, "model": self.model,
            "ai_state": self.ai_state, "build_sha": self.build_sha,
            "app_version": self.app_version,
            "benchmark_version": self.benchmark_version,
            "data_version": self.data_version,
            "duration_ms": self.duration_ms,
            "case_count": len(self.cases), "passed": self.passed,
            "partial": self.partial, "failed": self.failed,
            "notes": list(self.notes),
        }


def choose(count_per_family: int = 1) -> list[dict[str, Any]]:
    """A balanced random sample: one metadata, one calculation, one conversation.

    Random on purpose. A fixed set is a set the product can be tuned to pass, and
    a score that only ever exercises the same three threads stops being evidence
    about the other hundred.
    """
    import secrets

    chosen: list[dict[str, Any]] = []
    for family in SAMPLE:
        pool = benchmarks.by_family(family)
        for _ in range(count_per_family):
            if not pool:
                continue
            pick = pool[secrets.randbelow(len(pool))]
            if pick not in chosen:
                chosen.append(pick)
    return chosen


def run(cases: list[dict[str, Any]] | None = None, *,
        user_id: int | None = None) -> RunResult:
    """Run an intelligence check and return everything needed to inspect it."""
    from backend.build_info import build_info
    from backend.llm import health as ai_health

    started = time.perf_counter()
    chosen = cases if cases is not None else choose()
    observed = ai_health()
    info = build_info()

    result = RunResult(
        provider=str(observed.get("provider") or ""),
        model=str(observed.get("model") or ""),
        ai_state=str(observed.get("state") or ""),
        build_sha=info.short_sha, app_version=info.version,
        data_version=_data_version(),
    )

    if not observed.get("configured"):
        result.notes.append(
            "No AI provider is configured, so this check exercised CreditProbe's "
            "deterministic governed reader rather than the live model. The score "
            "below measures the analytical runtime, not the AI.")

    for case in chosen:
        result.cases.append(_run_case(case))

    scores = [c.score for c in result.cases]
    result.score = round(sum(scores) / len(scores), 1) if scores else 0.0
    result.components = _average_components(result.cases)
    result.band, result.tone = scoring.band(result.score)
    result.duration_ms = int((time.perf_counter() - started) * 1000)

    if any(c.used_fallback for c in result.cases):
        result.notes.append(
            f"{sum(1 for c in result.cases if c.used_fallback)} of "
            f"{len(result.cases)} cases were answered without reaching the live "
            "model. Those cases fail the live-AI benchmark whatever their "
            "figures say.")
    return result


def _run_case(case: dict[str, Any]) -> CaseResult:
    """One thread, through the real path, then compared with the reference."""
    from backend.orchestration import conversation as cv
    from backend.orchestration import orchestrator
    from backend.orchestration.executor import answer_investigation

    outcome = CaseResult(benchmark_id=case["id"], category=case["category"],
                         title=case["title"])
    state = cv.ConversationState()
    turn_scores: list[scoring.TurnScore] = []
    started = time.perf_counter()

    for index, turn in enumerate(case["turns"], start=1):
        question = str(turn["question"])
        expect = dict(turn.get("expect") or {})
        try:
            investigation, answered = answer_investigation(
                question, persist=False, state=state)
        except Exception as e:  # noqa: BLE001 - a crash is a failing case
            logger.exception("Benchmark %s turn %d raised", case["id"], index)
            turn_scores.append(_crashed(str(e)))
            outcome.turns.append({"index": index, "question": question,
                                  "error": str(e), "score": 0.0})
            continue

        seen = _observe(investigation, answered)
        if answered is not None:
            state = orchestrator.remember(
                state, answered,
                headline=str(investigation.narrative.direct_answer or ""))
            seen["ids"] = list(state.result.entity_ids)

        # ---- ONLY NOW is the reference computed. --------------------------
        reference = (gold.compute(expect["reference"])
                     if expect.get("reference") else None)

        score = scoring.score_turn(expect, seen, reference)
        turn_scores.append(score)
        if not seen.get("live"):
            outcome.used_fallback = True

        outcome.turns.append({
            "index": index,
            "question": question,
            "answer": seen.get("answer"),
            "interpretation": seen.get("interpretation"),
            "status": seen.get("status"),
            "reading": seen.get("reading"),
            "plan": seen.get("plan"),
            "sql": seen.get("sql"),
            "rows": seen.get("rows"),
            "columns": seen.get("columns"),
            "values": seen.get("values"),
            "live": seen.get("live"),
            "score": round(score.pct, 1),
            "components": score.components(),
            "deductions": list(score.deductions),
            "reference": reference.to_dict() if reference else None,
            "expected": _readable_expectation(expect),
        })
        if reference is not None and not outcome.reference:
            outcome.reference = reference.to_dict()

    outcome.latency_ms = int((time.perf_counter() - started) * 1000)
    outcome.score, outcome.components, outcome.deductions = scoring.combine(
        turn_scores)
    outcome.verdict = scoring.verdict(outcome.score)
    if outcome.used_fallback:
        outcome.verdict = scoring.FAIL
        outcome.deductions.insert(
            0, "This case was answered without reaching the live model, so it "
               "fails the live-AI benchmark regardless of its figures.")
    return outcome


def _crashed(reason: str) -> scoring.TurnScore:
    score = scoring.TurnScore(live=False)
    for name, weight in scoring.WEIGHTS.items():
        score.add(name, 0, weight,
                  f"The turn failed: {reason}" if name == "intent" else "")
    return score


def _observe(investigation: Any, answered: Any) -> dict[str, Any]:
    """What CreditProbe produced, flattened for scoring and for the panel."""
    conversation = investigation.conversation or {}
    reading = conversation.get("reading") or {}
    continuation = conversation.get("continuation") or {}
    certified = conversation.get("certified") or {}
    written = conversation.get("interpretation") or {}
    build = getattr(answered, "build", None)
    step = investigation.steps[0] if investigation.steps else None
    payload = (step.result or {}) if step else {}

    return {
        "status": investigation.status,
        "intent": reading.get("intent"),
        "action": continuation.get("action"),
        "population_count": continuation.get("entity_count") or 0,
        "certified": certified.get("analysis_id"),
        "analysis_id": step.analysis_id if step else "",
        # "Computed" means the governed RUNTIME ran. A metadata handler also
        # produces a step with a result — it just did not calculate anything,
        # and counting it here would score every catalogue answer as a
        # calculation.
        "computed": (getattr(answered, "runtime", None) is not None
                     or getattr(answered, "certified", None) is not None),
        "live": bool(conversation.get("model_calls"))
        and not conversation.get("degraded_reason"),
        "shape": getattr(build, "shape", ""),
        "dimension": getattr(build, "dimension", ""),
        "top_n": getattr(build, "top_n", 0),
        "grain": getattr(build, "grain", ""),
        "period": getattr(build, "period", "") or investigation.plan.scope.to_period,
        "opening": getattr(build, "opening", "") or investigation.plan.scope.from_period,
        "closing": getattr(build, "closing", "") or investigation.plan.scope.to_period,
        "filters": {f: v for f, v in getattr(build, "filters", [])} if build
        else dict(investigation.plan.scope.filters or {}),
        "datasets": (list(getattr(build, "datasets", []))
                     or list(payload.get("datasets") or [])
                     or _datasets_named(payload)),
        "join_path": list(getattr(build, "joins", [])),
        "values": _values(payload, build),
        "rows": list(payload.get("rows") or [])[:MAX_ROWS],
        "columns": list(payload.get("columns") or []),
        "answer": investigation.narrative.direct_answer,
        "interpretation": investigation.narrative.interpretation,
        "caveats": list(investigation.narrative.caveats or []),
        "ungrounded": list(written.get("ungrounded") or []),
        "reading": reading,
        "plan": (build.to_dict() if build is not None else
                 {"certified": certified.get("analysis_id")}),
        "sql": _sql_of(investigation),
        "ids": [],
    }


def _values(payload: dict[str, Any], build: Any) -> dict[str, Any]:
    """The figures the answer asserts, in the names the reference uses.

    An analytical answer already carries them. A metadata answer states its
    figures in rows — one row per field, or a row per dataset carrying its period
    count — so they are lifted out here rather than left uncomparable. Without
    this a catalogue answer scores zero on result accuracy for having been
    correct in the wrong shape.
    """
    values = dict(payload.get("values") or {})
    rows = list(payload.get("rows") or [])
    if build is not None or not rows:
        return values

    first = rows[0]
    if "field" in first:
        values.setdefault("field_count", len(rows))
    if "periods" in first:
        values.setdefault("period_count", first.get("periods"))
        values.setdefault("first_period", first.get("from"))
        values.setdefault("latest_period", first.get("to"))
    if "fields" in first:
        values.setdefault("field_count", first.get("fields"))
    if "step" in first:
        values.setdefault("hops", len(rows))
    return values


def _datasets_named(payload: dict[str, Any]) -> list[str]:
    """The datasets a metadata answer actually named."""
    out: list[str] = []
    for row in payload.get("rows") or []:
        for key in ("dataset", "from", "to"):
            value = str(row.get(key) or "").split(".")[0]
            if value and value not in out:
                out.append(value)
    return out


def _sql_of(investigation: Any) -> str:
    """The mathematical query that ran, from the Trace."""
    for node in (investigation.graph.nodes or {}).values():
        config = getattr(node, "config", None) or {}
        for key in ("sql", "query", "statement"):
            if config.get(key):
                return str(config[key])
    return ""


def _readable_expectation(expect: dict[str, Any]) -> list[str]:
    """What this turn was supposed to do, in sentences a non-developer reads."""
    out: list[str] = []
    if expect.get("clarification"):
        out.append("Should have asked a question rather than answering.")
    if expect.get("intent"):
        out.append(f"Should be routed to {expect['intent']}.")
    if expect.get("certified"):
        out.append(f"Should run the certified {expect['certified']}.")
    if expect.get("datasets"):
        out.append("Should read " + ", ".join(expect["datasets"]) + ".")
    if expect.get("dimension"):
        out.append(f"Should break the answer down by {expect['dimension']}.")
    if expect.get("top_n"):
        out.append(f"Should return {expect['top_n']} rows.")
    if expect.get("filters"):
        out.append("Should restrict to " + ", ".join(
            f"{k} = {v}" for k, v in expect["filters"].items()) + ".")
    period = expect.get("period")
    if isinstance(period, dict):
        out.append(f"Should compare {period.get('from')} with {period.get('to')}.")
    elif period:
        out.append(f"Should answer as at {period}.")
    if expect.get("grain"):
        out.append(f"Should answer one row per {expect['grain']}.")
    if expect.get("action"):
        out.append(f"Should read this as {expect['action']}.")
    if expect.get("population_from_previous"):
        out.append("Should carry the previous turn's rows into this one.")
    if expect.get("forbidden_methods"):
        out.append("Must NOT answer with "
                   + ", ".join(expect["forbidden_methods"]) + ".")
    return out


def _average_components(cases: list[CaseResult]) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for case in cases:
        for name, value in case.components.items():
            totals.setdefault(name, []).append(value)
    return {name: round(sum(v) / len(v), 1) for name, v in totals.items() if v}


def _data_version() -> str:
    """A stamp for the analytical universe, so a data change marks a score stale."""
    try:
        from backend.data_access import get_data_source

        source = get_data_source()
        names = sorted(source.datasets())
        latest = source.periods(names[0])[-1] if names else ""
        return f"{len(names)} datasets @ {latest}"
    except Exception:  # noqa: BLE001
        return ""


__all__ = ["MAX_ROWS", "SAMPLE", "CaseResult", "RunResult", "choose", "run"]
