"""
What one question cost, and where the cost went. R2 §16.

Measure before deciding
-----------------------
The instruction this module answers is "instrument the actual cause before
guessing". A cost problem attracts guesses — the prompt is too long, the model
is too big, it loops too much — and all three can be true at once while only
one of them accounts for the bill. So nothing here optimises anything. It
records, per question:

* every model call, with the role it served and the model that served it;
* input, output, cache-read and cache-write tokens on each of those calls;
* how many of the input tokens were catalogue/metadata and how many were
  gathered evidence, so a prompt that grows with the investigation is visible
  as growth rather than as a single large number;
* tool calls, and how many of them repeated a call already made;
* loop steps and provider retries;
* whether the answer came from the run-key cache, which costs nothing;
* wall-clock.

Why cost units rather than money
--------------------------------
§22 asks for budgets "in token/call budgets (not money)", and it is right to:
a currency figure needs a price list, a price list goes stale, and a stale
price list in a governed product is a number somebody will quote. So the meter
publishes TOKENS, which are measured, and COST UNITS, which are a declared
weighting of those tokens by tier. A cost unit is not a currency and is never
shown as one; it exists so that "this question got 4x cheaper" is a sentence
with arithmetic behind it.

The weighting says two things that are true of every provider worth using:
output tokens cost several times what input tokens cost, and a cached input
token costs a small fraction of a fresh one. The tier multiplier says the third
— that a deep model costs a multiple of a light one. Where a deployment knows
its own rates it can set them; where it does not, the defaults are relative and
declared rather than invented precision.

No key, no prompts, no client data
----------------------------------
The meter records sizes, counts, roles and model ids. It never records prompt
text, tool arguments, evidence values or borrower identifiers, and it cannot
see the API key. What it holds is safe to show an administrator on a screen
they may screenshot.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

COST_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Question classes — §16's A / B / C
# ---------------------------------------------------------------------------

#: Pure data or metadata. A governed lookup with an exact answer.
CLASS_A = "A_DATA"
#: Tool orchestration. Several governed calls, read and assembled.
CLASS_B = "B_ORCHESTRATION"
#: High-judgement credit analysis. Interpretation, synthesis, recommendation.
CLASS_C = "C_JUDGEMENT"

CLASSES: tuple[str, ...] = (CLASS_A, CLASS_B, CLASS_C)

CLASS_LABELS: dict[str, str] = {
    CLASS_A: "Data and metadata",
    CLASS_B: "Evidence gathering",
    CLASS_C: "Credit judgement",
}

# ---------------------------------------------------------------------------
# Tiers and the weighting
# ---------------------------------------------------------------------------

LIGHT = "light"
STANDARD = "standard"
DEEP = "deep"

TIERS: tuple[str, ...] = (LIGHT, STANDARD, DEEP)

#: Relative cost of a token at each tier. Declared, not measured — see the
#: module docstring. The ratios are conservative: a real price list has the
#: gap between a light and a deep model wider than this, so a saving computed
#: with these weights understates rather than flatters.
TIER_WEIGHT: dict[str, float] = {LIGHT: 1.0, STANDARD: 4.0, DEEP: 16.0}

#: An output token costs about five times an input one, and a cache-read token
#: about a tenth. A cache WRITE costs more than a fresh input token, which is
#: why caching a prefix used once is a loss and the weighting has to say so.
OUTPUT_WEIGHT = 5.0
CACHE_READ_WEIGHT = 0.1
CACHE_WRITE_WEIGHT = 1.25

#: Cost units are per thousand weighted tokens, so the numbers a report carries
#: are readable rather than six decimal places of nothing.
PER = 1000.0

#: Characters per token. An estimate, used only to apportion an input-token
#: count between catalogue and evidence — never to replace a measured count.
CHARS_PER_TOKEN = 4.0


def tokens_in(text: str) -> int:
    """A size estimate for a prompt section, in tokens."""
    return int(len(text or "") / CHARS_PER_TOKEN)


#: What each job is WORTH, before any measurement. Reading which kind of
#: request this is, and reading a governed table back, are light work; forming
#: a credit judgement on conflicting evidence is not. The map is the routing
#: intent; the model id recorded beside it is what actually served the call,
#: and the two are kept apart so that a deployment claiming differentiated
#: routing can be checked rather than believed.
TIER_BY_ROLE: dict[str, str] = {
    "router": LIGHT,
    "metadata": LIGHT,
    "planner": STANDARD,
    "orchestration": STANDARD,
    "interpretation": STANDARD,
    "critic": STANDARD,
    "analyst": DEEP,
    "complex_planner": DEEP,
    "judgement": DEEP,
}


def tier_for(role: str) -> str:
    """The tier a role is served at, with a deployment override.

    `AI_TIER_ANALYST=standard` moves the analyst without a code change, which
    is what an administrator tuning a bill needs. An unrecognised value is
    ignored rather than obeyed: a typo must not silently reprice the report.
    """
    override = (os.environ.get(f"AI_TIER_{(role or '').upper()}") or "").strip()
    if override.lower() in TIERS:
        return override.lower()
    return TIER_BY_ROLE.get((role or "").lower(), STANDARD)


# ---------------------------------------------------------------------------
# One model call
# ---------------------------------------------------------------------------


@dataclass
class ModelCall:
    """One request to a provider, and what it consumed."""

    purpose: str = ""
    role: str = ""
    model: str = ""
    tier: str = STANDARD
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    #: 1 when the provider answered first time. Anything higher is a retry.
    attempts: int = 1
    duration_ms: int = 0
    ok: bool = True

    @property
    def retries(self) -> int:
        return max(0, self.attempts - 1)

    @property
    def weighted_tokens(self) -> float:
        return (self.input_tokens
                + self.output_tokens * OUTPUT_WEIGHT
                + self.cache_read_tokens * CACHE_READ_WEIGHT
                + self.cache_write_tokens * CACHE_WRITE_WEIGHT)

    @property
    def cost_units(self) -> float:
        weight = TIER_WEIGHT.get(self.tier, TIER_WEIGHT[STANDARD])
        return self.weighted_tokens * weight / PER

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose, "role": self.role, "model": self.model,
            "tier": self.tier, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "attempts": self.attempts, "retries": self.retries,
            "duration_ms": self.duration_ms, "ok": self.ok,
            "cost_units": round(self.cost_units, 4),
        }


# ---------------------------------------------------------------------------
# One question
# ---------------------------------------------------------------------------


@dataclass
class Meter:
    """Everything one question spent.

    Created by the route, threaded into the loop, and read afterwards. It is a
    plain object rather than a global because two questions can be in flight at
    once and a module-level counter would attribute one to the other — which is
    exactly the kind of measurement error that makes an optimisation look like
    it worked.
    """

    question: str = ""
    question_class: str = CLASS_B
    #: Why the class came out that way, in a sentence. Recorded so a routing
    #: decision can be argued with rather than merely observed.
    class_reason: str = ""
    calls: list[ModelCall] = field(default_factory=list)
    #: Governed tool invocations, and the ones that repeated an earlier call.
    tool_calls: int = 0
    repeated_tool_calls: int = 0
    #: Turns of the agent loop actually taken.
    loop_steps: int = 0
    #: Estimated input tokens spent on the tool catalogue and dataset metadata,
    #: summed across every call. This is the number that grows when a prompt is
    #: rebuilt from scratch each turn.
    metadata_tokens: int = 0
    #: Estimated input tokens spent on evidence gathered so far, summed the
    #: same way. Grows quadratically in a loop that re-sends its whole ledger.
    evidence_tokens: int = 0
    #: The answer came back from the run-key store, so nothing was spent.
    reproduced: bool = False
    #: The path that answered: analyst, deterministic, reproduced.
    path: str = ""
    started: float = field(default_factory=time.perf_counter)
    duration_ms: int = 0

    # ---- recording -------------------------------------------------------

    def classify(self, question_class: str, why: str = "") -> None:
        self.question_class = question_class
        self.class_reason = why

    def record_call(self, *, purpose: str = "", role: str = "",
                    model: str = "", tier: str = STANDARD,
                    input_tokens: int = 0, output_tokens: int = 0,
                    cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                    attempts: int = 1, duration_ms: int = 0,
                    ok: bool = True) -> ModelCall:
        call = ModelCall(
            purpose=purpose, role=role, model=model, tier=tier,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            attempts=attempts, duration_ms=duration_ms, ok=ok)
        self.calls.append(call)
        return call

    def record_result(self, result: Any, *, purpose: str = "", role: str = "",
                      tier: str = STANDARD) -> ModelCall:
        """Record from an `LLMResult`, whatever provider produced it."""
        return self.record_call(
            purpose=purpose, role=role,
            model=str(getattr(result, "model", "") or ""), tier=tier,
            input_tokens=int(getattr(result, "input_tokens", 0) or 0),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(result, "cache_read_tokens", 0) or 0),
            cache_write_tokens=int(
                getattr(result, "cache_write_tokens", 0) or 0),
            attempts=int(getattr(result, "attempts", 1) or 1),
            duration_ms=int(getattr(result, "duration_ms", 0) or 0))

    def record_failed_call(self, *, purpose: str = "", role: str = "",
                           model: str = "", tier: str = STANDARD,
                           attempts: int = 1) -> ModelCall:
        """A call that cost tokens and returned nothing. Counted, because a
        failure that is not counted makes a retry look free."""
        return self.record_call(purpose=purpose, role=role, model=model,
                                tier=tier, attempts=attempts, ok=False)

    def record_prompt(self, *, metadata: str = "", evidence: str = "") -> None:
        """The shape of one prompt, before it is sent."""
        self.metadata_tokens += tokens_in(metadata)
        self.evidence_tokens += tokens_in(evidence)

    def record_tool(self, *, repeated: bool = False) -> None:
        self.tool_calls += 1
        if repeated:
            self.repeated_tool_calls += 1

    def step(self) -> None:
        self.loop_steps += 1

    def finish(self, *, path: str = "", reproduced: bool = False) -> Meter:
        self.path = path or self.path
        self.reproduced = reproduced or self.reproduced
        self.duration_ms = int((time.perf_counter() - self.started) * 1000)
        return self

    # ---- what it adds up to ----------------------------------------------

    @property
    def model_calls(self) -> int:
        return len(self.calls)

    @property
    def models(self) -> list[str]:
        seen: list[str] = []
        for call in self.calls:
            if call.model and call.model not in seen:
                seen.append(call.model)
        return seen

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def cache_read_tokens(self) -> int:
        return sum(c.cache_read_tokens for c in self.calls)

    @property
    def cache_write_tokens(self) -> int:
        return sum(c.cache_write_tokens for c in self.calls)

    @property
    def retries(self) -> int:
        return sum(c.retries for c in self.calls)

    @property
    def cost_units(self) -> float:
        return sum(c.cost_units for c in self.calls)

    @property
    def cached_share(self) -> float:
        """How much of the input arrived from the provider's cache."""
        fresh = self.input_tokens + self.cache_read_tokens
        return (self.cache_read_tokens / fresh) if fresh else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": COST_VERSION,
            "question_class": self.question_class,
            "class_label": CLASS_LABELS.get(self.question_class,
                                            self.question_class),
            "class_reason": self.class_reason,
            "path": self.path,
            "reproduced": self.reproduced,
            "model_calls": self.model_calls,
            "models": self.models,
            "tool_calls": self.tool_calls,
            "repeated_tool_calls": self.repeated_tool_calls,
            "loop_steps": self.loop_steps,
            "retries": self.retries,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cached_share": round(self.cached_share, 4),
            "metadata_tokens": self.metadata_tokens,
            "evidence_tokens": self.evidence_tokens,
            "cost_units": round(self.cost_units, 4),
            "duration_ms": self.duration_ms,
            "calls": [c.to_dict() for c in self.calls],
        }


# ---------------------------------------------------------------------------
# The administrator's cost trace
# ---------------------------------------------------------------------------

#: How many questions the trace keeps. Bounded: this is a diagnostic window,
#: not an audit log, and the durable record is ai_usage_log in Postgres.
HISTORY = 200


class Trace:
    """The recent questions and what each of them cost.

    In process and bounded. A deployment that wants history queries the usage
    table; what an administrator wants on a screen is the last few dozen
    questions with the expensive ones visible, and that is what this is.
    """

    def __init__(self, limit: int = HISTORY) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._meters: list[Meter] = []

    def add(self, meter: Meter) -> Meter:
        with self._lock:
            self._meters.append(meter)
            if len(self._meters) > self._limit:
                del self._meters[:-self._limit]
        return meter

    def clear(self) -> None:
        with self._lock:
            self._meters.clear()

    def recent(self, limit: int = 50) -> list[Meter]:
        with self._lock:
            return list(self._meters[-limit:])[::-1]

    def summary(self) -> dict[str, Any]:
        """Cost by question class — the shape §16 asks a report to carry."""
        with self._lock:
            meters = list(self._meters)
        by_class: dict[str, dict[str, Any]] = {}
        for name in CLASSES:
            rows = [m for m in meters if m.question_class == name]
            by_class[name] = _class_summary(name, rows)
        answered = [m for m in meters if not m.reproduced]
        reproduced = [m for m in meters if m.reproduced]
        avoided = _avoided(answered, reproduced)
        return {
            "version": COST_VERSION,
            "questions": len(meters),
            "answered": len(answered),
            "reproduced": len(reproduced),
            "cache_hit_rate": round(
                len(reproduced) / len(meters), 4) if meters else 0.0,
            "cost_units": round(sum(m.cost_units for m in meters), 4),
            "cost_units_avoided": round(avoided, 4),
            "model_calls": sum(m.model_calls for m in meters),
            "by_class": by_class,
        }


def _class_summary(name: str, rows: list[Meter]) -> dict[str, Any]:
    count = len(rows)
    if not count:
        return {"class": name, "label": CLASS_LABELS.get(name, name),
                "questions": 0, "model_calls": 0, "avg_model_calls": 0.0,
                "avg_cost_units": 0.0, "avg_duration_ms": 0,
                "avg_input_tokens": 0, "avg_output_tokens": 0}
    return {
        "class": name,
        "label": CLASS_LABELS.get(name, name),
        "questions": count,
        "model_calls": sum(m.model_calls for m in rows),
        "avg_model_calls": round(sum(m.model_calls for m in rows) / count, 2),
        "avg_cost_units": round(sum(m.cost_units for m in rows) / count, 4),
        "avg_duration_ms": int(sum(m.duration_ms for m in rows) / count),
        "avg_input_tokens": int(sum(m.input_tokens for m in rows) / count),
        "avg_output_tokens": int(sum(m.output_tokens for m in rows) / count),
    }


def _avoided(answered: list[Meter], reproduced: list[Meter]) -> float:
    """What the cache saved. §20.

    Priced at what a question of that class actually cost when it was
    computed, rather than at an average over everything: a reproduced
    catalogue lookup did not avoid the cost of a forensic decomposition, and
    a saving reported that way would be flattery.
    """
    if not reproduced:
        return 0.0
    by_class: dict[str, list[float]] = {}
    for meter in answered:
        by_class.setdefault(meter.question_class, []).append(meter.cost_units)
    overall = [c for costs in by_class.values() for c in costs]
    default = sum(overall) / len(overall) if overall else 0.0
    total = 0.0
    for meter in reproduced:
        costs = by_class.get(meter.question_class) or []
        total += (sum(costs) / len(costs)) if costs else default
    return total


_TRACE = Trace()


def trace() -> Trace:
    return _TRACE


def record(meter: Meter) -> Meter:
    return _TRACE.add(meter)


# ---------------------------------------------------------------------------
# The ambient meter
# ---------------------------------------------------------------------------

#: The meter for the request being served on this context, if any.
#:
#: A context variable rather than a parameter threaded through the
#: orchestrator, and the reason is honesty about the measurement: model calls
#: are made from five places across two packages, and a parameter that has to
#: be passed through every intervening function is one that will be dropped
#: somewhere, producing a cost report that is quietly missing a call. The
#: variable is per-context, so two questions in flight cannot be confused —
#: which a module-level counter would do, and which would make an
#: optimisation look like it worked when it had only moved the spending
#: somewhere the meter could not see.
_CURRENT: contextvars.ContextVar[Meter | None] = contextvars.ContextVar(
    "creditprobe_cost_meter", default=None)


def current() -> Meter | None:
    """The meter for this request, or None outside one."""
    return _CURRENT.get()


@contextlib.contextmanager
def measuring(question: str = "", *, question_class: str = CLASS_B,
              why: str = "", keep: bool = True) -> Any:
    """Measure everything one question spends.

    Yields the meter. On exit it is finished and — unless `keep` is off —
    added to the administrator's trace. Nested use returns the OUTER meter
    rather than starting a second one: a question is one unit of cost however
    many layers it passes through, and a nested meter would split the total
    across two rows that neither adds up.
    """
    existing = _CURRENT.get()
    if existing is not None:
        yield existing
        return
    meter = Meter(question=question, question_class=question_class,
                  class_reason=why)
    token = _CURRENT.set(meter)
    try:
        yield meter
    finally:
        _CURRENT.reset(token)
        meter.finish()
        if keep:
            record(meter)


def note_result(result: Any, *, purpose: str = "", role: str = "") -> None:
    """Record one model call on the ambient meter, if there is one.

    A no-op outside a measured request, so a call site can say what it spent
    without knowing whether anybody is counting.
    """
    meter = _CURRENT.get()
    if meter is not None:
        meter.record_result(result, purpose=purpose, role=role,
                            tier=tier_for(role or purpose))


def note_failure(*, purpose: str = "", role: str = "", model: str = "",
                 attempts: int = 1) -> None:
    meter = _CURRENT.get()
    if meter is not None:
        meter.record_failed_call(purpose=purpose, role=role, model=model,
                                 tier=tier_for(role or purpose),
                                 attempts=attempts)


__all__ = ["CACHE_READ_WEIGHT", "CACHE_WRITE_WEIGHT", "CHARS_PER_TOKEN",
           "CLASSES", "CLASS_A", "CLASS_B", "CLASS_C", "CLASS_LABELS",
           "COST_VERSION", "DEEP", "HISTORY", "LIGHT", "Meter", "ModelCall",
           "OUTPUT_WEIGHT", "PER", "STANDARD", "TIERS", "TIER_BY_ROLE",
           "TIER_WEIGHT", "Trace", "current", "measuring", "note_failure",
           "note_result", "record", "tier_for", "tokens_in", "trace"]
