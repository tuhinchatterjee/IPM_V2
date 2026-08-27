"""
The eight things a live provider has to get right, defined once.

The failure this exists for
---------------------------
`verify-live-ai.ps1 -Quick` reported FAILED against a provider that was
perfectly healthy. The stored report said:

    component: live_smoke   passed: false   latency_ms: 45
    input_tokens: 0         output_tokens: 0

Forty-five milliseconds and no tokens is not a model that answered badly. It is
a model that was never asked. Quick ran the live smoke checks by shelling out
to `pytest tests/llm/test_live_smoke.py` **inside the production backend
container**, and the production image ships neither `tests/` nor pytest — on
purpose. The subprocess died before it reached a single assertion, and the
verifier recorded that as the model failing.

The lesson is narrower than "don't shell out". It is that a production
verification tool may only depend on what production ships. Shipping the test
suite to make the verifier work would have inverted the problem: the sealed
holdout, the fixtures and the benchmark answers do not belong in a deployed
image, and a product that can reach its own exam has no exam.

What this module is
-------------------
The eight checks, as ordinary functions in production code, importing only what
the running application already imports. `live_verify.quick()` calls them
directly. `tests/llm/test_live_smoke.py` calls the same functions, so the
pytest suite and the production verifier cannot drift: there is one definition
of what "the live path works" means, and both read it.

Every check returns an `Outcome` rather than raising. A verification tool needs
to report eight results, not stop at the first bad one, and an exception is a
poor carrier for latency and token counts.

What is deliberately NOT here
------------------------------
Anything that asserts what the model *said*. These prove that a real structured
response came back, that the telemetry recorded it honestly, that the routing
decision was the right one, and that the figures still come from the governed
runtime. What the prose contained is the interpretation rubric's job.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Check:
    """One thing the live path has to get right."""

    id: str
    title: str
    #: What passing it establishes, in a sentence. Shown on the report so a
    #: reader meets the claim rather than the function name.
    proves: str
    #: Roughly what it costs. Summed in the estimate the operator sees before
    #: anything runs.
    calls: int = 1


@dataclass
class Outcome:
    """What one check found. Never raises; a failure is a result."""

    check: str
    passed: bool
    detail: str = ""
    calls: int = 0
    model: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: A sanitised category, never a raw provider message.
    error_category: str = ""
    #: Which configured role served it, where one did.
    role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "passed": self.passed,
                "detail": self.detail, "calls": self.calls,
                "model": self.model, "latency_ms": self.latency_ms,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "error_category": self.error_category, "role": self.role}


# ---------------------------------------------------------------------------
# The five routing checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Routing:
    """One question, and the capability it must be read as."""

    id: str
    question: str
    expected: str
    proves: str


#: Five requests, chosen to exercise five different routing decisions rather
#: than five phrasings of the same one. A model that reads all five as ANALYSIS
#: is not a model that understands the catalogue.
ROUTING: tuple[Routing, ...] = (
    Routing(
        id="data_discovery",
        question="What data do you have about borrower ratings?",
        expected="DATA_DISCOVERY",
        proves="a question about what is held is read as discovery, not as an "
               "analysis of the portfolio"),
    Routing(
        id="data_dictionary",
        question="What fields are available in the ratings data?",
        expected="DATA_DICTIONARY",
        proves="a question about one dataset's fields is read as a dictionary "
               "lookup"),
    Routing(
        id="data_relationship",
        question="How is the ratings data connected to IFRS 9 data?",
        expected="DATA_RELATIONSHIP",
        proves="a question about how two datasets join is read as a "
               "relationship question rather than as an analysis"),
    Routing(
        id="dynamic_analysis",
        question="What is total EAD by sector in the latest quarter?",
        expected="ANALYSIS",
        proves="an aggregate over a governed measure is routed to the "
               "analytical runtime"),
    Routing(
        id="entity_ranking",
        question="Show me the five largest Real Estate customers by EAD.",
        expected="ANALYSIS",
        proves="a ranking of named counterparties is routed to the analytical "
               "runtime"),
)


# ---------------------------------------------------------------------------
# Watching what the calls actually cost
# ---------------------------------------------------------------------------


class _Watch:
    """The provider calls made inside a block, and what they cost.

    Reads the telemetry ledger rather than threading token counts back through
    every call site. The ledger is already the single record of what was sent,
    it is what Settings shows, and taking the numbers from it means the report
    cannot disagree with the header chip.
    """

    def __init__(self) -> None:
        from backend.llm import telemetry

        self._ledger = telemetry.ledger()
        self.before = 0
        self.calls: list[Any] = []

    def __enter__(self) -> _Watch:
        self.before = len(self._ledger.calls)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.calls = list(self._ledger.calls)[self.before:]

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def input_tokens(self) -> int:
        return sum(int(getattr(c, "input_tokens", 0) or 0) for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(int(getattr(c, "output_tokens", 0) or 0) for c in self.calls)

    @property
    def model(self) -> str:
        for call in reversed(self.calls):
            if getattr(call, "ok", False) and getattr(call, "model", ""):
                return str(call.model)
        return ""

    @property
    def role(self) -> str:
        for call in reversed(self.calls):
            if getattr(call, "role", ""):
                return str(call.role)
        return ""


def _category(error: BaseException) -> str:
    from backend.llm import telemetry

    try:
        return telemetry.classify(error)
    except Exception:  # noqa: BLE001 - a category must not lose an outcome
        return "unknown"


def _sanitise(text: str) -> str:
    from backend.llm import telemetry

    try:
        return telemetry.sanitise(text)[:200]
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# The checks themselves
# ---------------------------------------------------------------------------


def routing_check(routing: Routing) -> Outcome:
    """One question, read live, routed to the capability it belongs to."""
    from backend.orchestration.context import retrieve
    from backend.orchestration.router import read

    started = time.perf_counter()
    try:
        with _Watch() as watch:
            result = read(routing.question, context=retrieve(routing.question))
    except Exception as e:  # noqa: BLE001 - a failure is the finding
        return Outcome(check=routing.id, passed=False,
                       latency_ms=int((time.perf_counter() - started) * 1000),
                       error_category=_category(e),
                       detail="the live reading raised")

    elapsed = int((time.perf_counter() - started) * 1000)
    common = {
        "calls": watch.count, "model": watch.model or result.reading.model,
        "latency_ms": elapsed, "input_tokens": watch.input_tokens,
        "output_tokens": watch.output_tokens, "role": watch.role,
    }

    if result.degraded_reason:
        return Outcome(check=routing.id, passed=False, **common,
                       detail=f"the live path degraded: "
                              f"{_sanitise(result.degraded_reason)}")
    if result.calls < 1:
        return Outcome(check=routing.id, passed=False, **common,
                       detail="no model call was made")
    if result.reading.source not in ("llm", "guardrail"):
        return Outcome(check=routing.id, passed=False, **common,
                       detail=f"the reading came from {result.reading.source!r}, "
                              "not from the model")
    if not result.reading.model:
        return Outcome(check=routing.id, passed=False, **common,
                       detail="the response did not say which model answered")
    if result.reading.intent != routing.expected:
        return Outcome(check=routing.id, passed=False, **common,
                       detail=f"read as {result.reading.intent}, "
                              f"not {routing.expected}")
    return Outcome(check=routing.id, passed=True, **common,
                   detail=f"read as {routing.expected}")


def provider_connected() -> Outcome:
    """CONNECTED has to be earned by a response, not assumed from a key.

    Proved without resetting the running process's telemetry. The pytest
    version cleared the global ledger to show a fresh one reports CONFIGURED;
    doing that inside a live container would erase the health history the
    header chip is showing somebody. A fresh `Ledger` proves the same rule and
    touches nothing.
    """
    from backend.llm import get_provider, health, telemetry

    started = time.perf_counter()
    try:
        empty = telemetry.Ledger().state(configured=True)
        if empty != telemetry.CONFIGURED:
            return Outcome(
                check="provider_connected", passed=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                detail=f"a key with no calls behind it reports {empty}, "
                       "which would make CONNECTED meaningless")

        if not get_provider().configured:
            return Outcome(check="provider_connected", passed=False,
                           detail="no provider key is configured")

        from backend.orchestration.context import retrieve
        from backend.orchestration.router import read

        with _Watch() as watch:
            read("What data do you have about arrears?",
                 context=retrieve("arrears"))
    except Exception as e:  # noqa: BLE001
        return Outcome(check="provider_connected", passed=False,
                       latency_ms=int((time.perf_counter() - started) * 1000),
                       error_category=_category(e),
                       detail="the connectivity probe raised")

    elapsed = int((time.perf_counter() - started) * 1000)
    common = {"calls": watch.count, "model": watch.model, "latency_ms": elapsed,
              "input_tokens": watch.input_tokens,
              "output_tokens": watch.output_tokens, "role": watch.role}

    observed = health()
    if observed.get("state") != telemetry.CONNECTED:
        return Outcome(check="provider_connected", passed=False, **common,
                       detail=f"after a real response the provider reports "
                              f"{observed.get('state')!r}, not connected")
    if int((observed.get("counts") or {}).get("succeeded") or 0) < 1:
        return Outcome(check="provider_connected", passed=False, **common,
                       detail="no successful call was recorded")

    last = observed.get("last_success") or {}
    if int(last.get("latency_ms") or 0) <= 0 or not last.get("model"):
        return Outcome(check="provider_connected", passed=False, **common,
                       detail="the recorded success carries no latency or model")
    return Outcome(check="provider_connected", passed=True, **common,
                   detail=f"connected, last success from {last.get('model')}")


def telemetry_secret_safety() -> Outcome:
    """Nothing key-shaped in anything the product is willing to display.

    Costs nothing: it inspects what the previous checks already recorded.
    """
    from backend.config import settings
    from backend.llm import health

    started = time.perf_counter()
    key = (settings.anthropic_api_key or "").strip()
    if not key:
        return Outcome(check="telemetry_secret_safety", passed=False,
                       detail="no key is configured, so this proves nothing")

    try:
        blob = repr(health())
    except Exception as e:  # noqa: BLE001
        return Outcome(check="telemetry_secret_safety", passed=False,
                       error_category=_category(e),
                       detail="the health record could not be read")

    elapsed = int((time.perf_counter() - started) * 1000)
    if key in blob:
        return Outcome(check="telemetry_secret_safety", passed=False,
                       latency_ms=elapsed,
                       detail="the health record contains the configured key")
    # A prefix is enough to identify an account, so a truncated key is still a
    # leak. Twelve characters is well past "sk-ant-" and into the opaque part.
    if len(key) >= 12 and key[:12] in blob:
        return Outcome(check="telemetry_secret_safety", passed=False,
                       latency_ms=elapsed,
                       detail="the health record contains a prefix of the key")
    return Outcome(check="telemetry_secret_safety", passed=True,
                   latency_ms=elapsed,
                   detail="no key-shaped material in the recorded telemetry")


def runtime_computes_result() -> Outcome:
    """Every figure still comes from the governed runtime, not the model.

    The one check that runs a whole investigation. It is the product's central
    claim: the model decides what to compute and the runtime computes it, so a
    live path that started answering from the model's own arithmetic would be
    a different product wearing this one's Trace.
    """
    from backend.orchestration.executor import answer_investigation

    question = "What is total EAD by sector in the latest quarter?"
    started = time.perf_counter()
    try:
        with _Watch() as watch:
            investigation, answered = answer_investigation(question,
                                                           persist=False)
    except Exception as e:  # noqa: BLE001
        return Outcome(check="runtime_computes_result", passed=False,
                       latency_ms=int((time.perf_counter() - started) * 1000),
                       error_category=_category(e),
                       detail="the investigation raised")

    elapsed = int((time.perf_counter() - started) * 1000)
    common = {"calls": watch.count, "model": watch.model, "latency_ms": elapsed,
              "input_tokens": watch.input_tokens,
              "output_tokens": watch.output_tokens, "role": watch.role}

    if investigation.status != "succeeded":
        return Outcome(check="runtime_computes_result", passed=False, **common,
                       detail=f"the investigation came back "
                              f"{investigation.status}")
    if answered.runtime is None:
        return Outcome(check="runtime_computes_result", passed=False, **common,
                       detail="no analytical runtime result was produced")
    rows = ((investigation.steps or [{}])[0].result or {}).get("rows") \
        if investigation.steps else None
    if not rows:
        return Outcome(check="runtime_computes_result", passed=False, **common,
                       detail="no rows were computed")
    if int((investigation.conversation or {}).get("model_calls", 0)) < 1:
        return Outcome(check="runtime_computes_result", passed=False, **common,
                       detail="the answer was produced without a model call, "
                              "so the live path was not exercised")
    return Outcome(check="runtime_computes_result", passed=True, **common,
                   detail=f"{len(rows)} rows computed by the governed runtime")


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def _routing_runner(routing: Routing) -> Callable[[], Outcome]:
    def run() -> Outcome:
        return routing_check(routing)

    return run


CHECKS: tuple[Check, ...] = (
    *(Check(id=r.id, title=r.question, proves=r.proves, calls=1)
      for r in ROUTING),
    Check(id="provider_connected",
          title="The provider reports CONNECTED only after a real response",
          proves="the state the product displays is earned by a response "
                 "rather than assumed from the presence of a key",
          calls=1),
    Check(id="telemetry_secret_safety",
          title="No recorded telemetry carries anything key-shaped",
          proves="the health record the product is willing to display cannot "
                 "leak the credential behind it",
          calls=0),
    Check(id="runtime_computes_result",
          title="An answer end to end is computed by the runtime",
          proves="on the live path every figure still comes from the governed "
                 "analytical runtime rather than from the model",
          calls=2),
)

RUNNERS: dict[str, Callable[[], Outcome]] = {
    **{r.id: _routing_runner(r) for r in ROUTING},
    "provider_connected": provider_connected,
    "telemetry_secret_safety": telemetry_secret_safety,
    "runtime_computes_result": runtime_computes_result,
}

#: What the whole suite costs, for the estimate shown before anything runs.
ESTIMATED_CALLS = sum(c.calls for c in CHECKS)


@dataclass
class Suite:
    """Every check, run once, with nothing hidden behind a summary."""

    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.outcomes) and all(o.passed for o in self.outcomes)

    @property
    def calls(self) -> int:
        return sum(o.calls for o in self.outcomes)

    @property
    def failures(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.passed]


def run(check_id: str) -> Outcome:
    """One check by name. An unknown name is a failure, never a silent pass."""
    runner = RUNNERS.get(check_id)
    if runner is None:
        return Outcome(check=check_id, passed=False,
                       detail=f"{check_id!r} is not a known live smoke check")
    try:
        return runner()
    except Exception as e:  # noqa: BLE001 - a check that raises did not pass
        logger.warning("The %s check raised: %s", check_id, e)
        return Outcome(check=check_id, passed=False,
                       error_category=_category(e),
                       detail="the check raised")


def run_all(stop_early: bool = False) -> Suite:
    """Every check, in order.

    `stop_early` is off by default. A verification that halts at the first
    failure tells the operator about one problem when there may be three, and
    the calls the remaining checks would have made are the cheap part of the
    exercise.
    """
    suite = Suite()
    for check in CHECKS:
        outcome = run(check.id)
        suite.outcomes.append(outcome)
        if stop_early and not outcome.passed:
            break
    return suite


def describe() -> list[dict[str, Any]]:
    """The catalogue, for the report and for anything documenting it."""
    return [{"check": c.id, "title": c.title, "proves": c.proves,
             "estimated_calls": c.calls} for c in CHECKS]


__all__ = [
    "CHECKS", "ESTIMATED_CALLS", "ROUTING", "RUNNERS",
    "Check", "Outcome", "Routing", "Suite",
    "describe", "provider_connected", "routing_check", "run", "run_all",
    "runtime_computes_result", "telemetry_secret_safety",
]
