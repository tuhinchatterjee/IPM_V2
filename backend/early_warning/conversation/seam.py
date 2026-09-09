"""
Where a model actually runs, and what happens when it does not.

Why this module exists
----------------------
Every stage of the Early Warning turn has a deterministic implementation, and
for a while that was the whole story: the stages carried names like
`sonnet_pass_1` and reported `model_calls: 0`. A stage named after a model that
never runs is a diagram, not an architecture, and a trace that reads like one is
worse than an honest `deterministic` — a reader cannot tell the difference and
will assume the name is true.

So this is the one place an Early Warning stage may reach a model. It reuses
CreditProbe's own provider infrastructure — `backend.llm.get_provider` for the
client and `backend.llm.roles` for which model serves which job — because a
second provider stack would mean two places that hold a key, two health
reports, and two answers to "which model served this".

The contract every stage keeps
------------------------------
1. **A structured packet in.** The model is given the stage's own inputs and
   nothing else. It never sees the data; values reach the answer through
   validated execution.
2. **Schema-validated structured output.** The provider makes the schema a tool
   contract; this module validates the reply against the same schema again
   before anything downstream sees it. A reply that does not conform is a
   fallback, not something to salvage.
3. **The SAME ledger.** A model call spends from the turn's one budget. There
   is no per-stage allowance, because the failure that costs money is the
   recursive one and every recursion looks affordable if each stage starts
   fresh.
4. **Real metadata.** Provider, model id, role, effort, latency, tokens and
   request id come off the call that happened. Nothing is asserted.
5. **Fallback that says why.** No provider, no budget, a refusal, a malformed
   reply, a timeout — each produces the deterministic result with the reason
   recorded, and `engine` reads `deterministic`.

The rule the model never gets to break
--------------------------------------
**A model may tighten a control and never loosen one.** It may route a question
out of Early Warning, mark an answer incomplete, or add a caveat. It may not
route a question INTO Early Warning against the deterministic gate, declare an
incomplete answer complete, or put a figure into prose that the result packet
does not carry. Each of those is enforced by the caller, not requested in a
prompt.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning.conversation import budget as budget_mod

logger = logging.getLogger(__name__)

#: The two families the architecture routes between. Recorded on the ledger so
#: "how many Sonnet calls and how many Opus calls" is a counted fact.
SONNET = "sonnet"
OPUS = "opus"

MODEL = "model"
DETERMINISTIC = "deterministic"

#: Stage keys. These are the seams, not the pipeline's event names — a stage
#: may emit several events and still be one place a model is asked something.
PASS_1 = "sonnet_pass_1"
PASS_2 = "sonnet_pass_2"
FUNCTIONALITY = "opus_functionality_selection"
PLAN = "opus_analysis_plan"
SUFFICIENCY = "opus_sufficiency_review"
INTERPRETATION = "opus_final_interpretation"
SUMMARY = "sonnet_summary_update"


@dataclass(frozen=True)
class Stage:
    """One seam: which family serves it, under which configured role."""

    key: str
    family: str
    #: A role from `backend.llm.roles`. The model id comes from whatever an
    #: administrator configured for that role — this module never names one.
    role: str
    purpose: str
    tool_name: str
    tool_description: str
    max_tokens: int = 1400


#: Which model does which job.
#:
#: The mapping is onto CreditProbe's EXISTING roles rather than onto new
#: Early-Warning-only variables, so a deployment that has already configured
#: `AI_COMPLEX_PLANNER_MODEL` and `AI_ANALYST_MODEL` gets the intended routing
#: without setting anything else, and an administrator has one settings page
#: rather than two.
#:
#: The families follow the shipped example configuration: ROUTER and
#: TRANSLATION are Sonnet-grade jobs, COMPLEX_PLANNER, CRITIC and ANALYST are
#: the ones worth an Opus. Two stages share ROUTER because reading a request
#: and updating a rolling summary are the same kind of short structured job;
#: the telemetry keeps them apart by `purpose`.
STAGES: dict[str, Stage] = {
    PASS_1: Stage(
        key=PASS_1, family=SONNET, role="translation",
        purpose="early_warning_language",
        tool_name="clean_the_question",
        tool_description=(
            "Return the same question in clean English. Correct spelling, "
            "transcription noise and translation only. Resolve nothing."),
        max_tokens=700),
    PASS_2: Stage(
        key=PASS_2, family=SONNET, role="router",
        purpose="early_warning_request",
        tool_name="read_the_business_request",
        tool_description=(
            "Say what is being asked: which parts, over what scope, for which "
            "period, and what remains genuinely unclear."),
        max_tokens=1200),
    FUNCTIONALITY: Stage(
        key=FUNCTIONALITY, family=OPUS, role="complex_planner",
        purpose="early_warning_functionality",
        tool_name="select_functionality",
        tool_description=(
            "Decide which CreditProbe functionality owns this request, before "
            "any analysis is planned."),
        max_tokens=900),
    PLAN: Stage(
        key=PLAN, family=OPUS, role="complex_planner",
        purpose="early_warning_plan",
        tool_name="plan_the_analysis",
        tool_description=(
            "Compose the bounded Early Warning analysis steps that answer "
            "every part of the request."),
        max_tokens=2000),
    SUFFICIENCY: Stage(
        key=SUFFICIENCY, family=OPUS, role="critic",
        purpose="early_warning_sufficiency",
        tool_name="review_sufficiency",
        tool_description=(
            "Say whether the executed evidence answers every part of the "
            "request, and what single further step would close a gap."),
        max_tokens=1000),
    INTERPRETATION: Stage(
        key=INTERPRETATION, family=OPUS, role="analyst",
        purpose="early_warning_interpretation",
        tool_name="interpret_the_result",
        tool_description=(
            "Say what the Early Warning result means to a senior credit risk "
            "officer, using only figures the result carries."),
        max_tokens=1600),
    SUMMARY: Stage(
        key=SUMMARY, family=SONNET, role="router",
        purpose="early_warning_summary",
        tool_name="update_the_thread_summary",
        tool_description=(
            "Update the rolling analytical summary of this thread from the "
            "answer that was actually supported."),
        max_tokens=700),
}


@dataclass
class Outcome:
    """What a seam produced, and by what.

    `engine` is the only field anything branches on, and it is set from what
    happened rather than from what was intended. A stage that wanted a model
    and did not get one reports `deterministic` with a reason.
    """

    stage: str
    engine: str = DETERMINISTIC
    data: dict[str, Any] = field(default_factory=dict)
    family: str = ""
    provider: str = ""
    model: str = ""
    role: str = ""
    effort: str = ""
    duration_ms: int = 0
    request_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    #: Why the deterministic implementation is what ran, when it is.
    fallback_reason: str = ""
    #: What was wrong with the model's reply, when there was something.
    schema_errors: list[str] = field(default_factory=list)

    @property
    def used_model(self) -> bool:
        return self.engine == MODEL

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"stage": self.stage, "engine": self.engine,
                               "family": self.family}
        if self.used_model:
            out.update({
                "provider": self.provider, "model": self.model,
                "role": self.role, "effort": self.effort,
                "duration_ms": self.duration_ms,
                "request_id": self.request_id,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "attempts": self.attempts,
                "served_family": family_of(self.model),
            })
        if self.fallback_reason:
            out["fallback_reason"] = self.fallback_reason
        if self.schema_errors:
            out["schema_errors"] = list(self.schema_errors)
        return out


def family_of(model_id: str) -> str:
    """Which family a model id belongs to, read from the id itself.

    Reported alongside the family the stage ASKED for, because those are two
    different facts. A deployment that configured one shared model gets Opus
    routing decisions served by whatever that model is, and a trace that
    claimed otherwise would be a trace with no evidential value.
    """
    lowered = (model_id or "").lower()
    if "opus" in lowered:
        return OPUS
    if "sonnet" in lowered:
        return SONNET
    if "haiku" in lowered:
        return "haiku"
    return "unknown" if lowered else ""


def provider_available() -> bool:
    """Whether a configured provider exists to be called at all."""
    try:
        from backend.llm import get_provider

        return bool(get_provider().configured)
    except Exception as e:  # noqa: BLE001 - an unreadable provider is offline
        logger.debug("The Early Warning seam could not read the provider: %s", e)
        return False


def routing() -> list[dict[str, Any]]:
    """The stage-to-model routing, resolved against the live configuration.

    What Settings and the handoff read. Every row says which family the stage
    asks for, which role carries it, which model that role currently resolves
    to, and whether that model is in the family the stage asked for.
    """
    rows: list[dict[str, Any]] = []
    for stage in STAGES.values():
        configured = _role(stage.role)
        served = family_of(configured.get("model", ""))
        rows.append({
            "stage": stage.key,
            "intended_family": stage.family,
            "role": stage.role,
            "model": configured.get("model", ""),
            "effort": configured.get("effort", ""),
            "served_family": served,
            "matches_intent": bool(served) and served == stage.family,
        })
    return rows


def _role(name: str) -> dict[str, str]:
    """The model and effort configured for one role, in call shape."""
    try:
        from backend.llm import roles

        configured = roles.role(name)
        return {"model": configured.model, "effort": configured.effort}
    except Exception as e:  # noqa: BLE001 - a role that cannot be read inherits
        logger.debug("Could not resolve the %r role: %s", name, e)
        return {"model": "", "effort": ""}


def _conforms(data: Any, schema: dict[str, Any]) -> list[str]:
    """Every way the reply fails the schema, in plain sentences.

    Validated here as well as at the provider boundary. The provider makes the
    schema a tool contract, which is the strong control; this is the one that
    survives a provider that is lenient about it, and it costs nothing.
    """
    if not isinstance(data, dict):
        return [f"the reply is a {type(data).__name__}, not an object"]
    try:
        from jsonschema import Draft202012Validator

        validator = Draft202012Validator(schema)
        return [f"{'.'.join(str(p) for p in e.path) or 'the reply'}: {e.message}"
                for e in list(validator.iter_errors(data))[:5]]
    except ImportError:  # pragma: no cover - jsonschema ships with the backend
        missing = [key for key in schema.get("required", []) if key not in data]
        return [f"missing required field {key!r}" for key in missing]


def call(stage_key: str, *, system: str, prompt: str, schema: dict[str, Any],
         ledger: budget_mod.Ledger | None = None) -> Outcome:
    """Ask the model that serves this stage, or say why it was not asked.

    Never raises. Every failure — no provider, no budget, a provider error, a
    reply that does not conform — becomes an Outcome whose engine is
    `deterministic` and whose reason says which of those it was. A stage that
    could lose a turn to a provider outage would be a stage that made the
    product less reliable than the deterministic one it replaced.
    """
    stage = STAGES.get(stage_key)
    if stage is None:
        return Outcome(stage=stage_key,
                       fallback_reason=f"{stage_key!r} is not a known stage")

    from backend.llm import LLMError, get_provider

    try:
        provider = get_provider()
    except Exception as e:  # noqa: BLE001
        return Outcome(stage=stage.key, family=stage.family,
                       fallback_reason=f"the provider could not be built: {e}")

    if not provider.configured:
        return Outcome(
            stage=stage.key, family=stage.family, provider=provider.name,
            fallback_reason="no AI provider is configured")

    # The budget is checked BEFORE the call and spent ON it. A stage that
    # checked afterwards would be a stage that could always afford one more.
    if ledger is not None and not ledger.can("model_calls"):
        return Outcome(
            stage=stage.key, family=stage.family, provider=provider.name,
            fallback_reason=(
                f"this turn's model-call budget is spent "
                f"({ledger.model_calls} of "
                f"{ledger.ceilings.get('model_calls')})"))

    configured = _role(stage.role)
    if ledger is not None:
        try:
            ledger.model_call(family=stage.family)
        except budget_mod.Exhausted as stop:
            # The wall clock went while this stage was being prepared. The
            # deterministic implementation still answers, which is a better
            # outcome than losing the turn to an optional enhancement.
            return Outcome(
                stage=stage.key, family=stage.family, provider=provider.name,
                fallback_reason=str(stop))

    started = time.perf_counter()
    try:
        result = provider.structured(
            system=system, prompt=prompt, schema=schema,
            tool_name=stage.tool_name,
            tool_description=stage.tool_description,
            max_tokens=stage.max_tokens,
            purpose=stage.purpose,
            model=configured["model"],
            role=stage.role, effort=configured["effort"])
    except LLMError as e:
        return Outcome(
            stage=stage.key, family=stage.family, provider=provider.name,
            model=configured["model"], role=stage.role,
            effort=configured["effort"],
            duration_ms=int((time.perf_counter() - started) * 1000),
            fallback_reason=f"the model did not answer: {e}")
    except Exception as e:  # noqa: BLE001 - a seam must never lose a turn
        logger.warning("The Early Warning %s seam failed: %s", stage.key, e)
        return Outcome(
            stage=stage.key, family=stage.family, provider=provider.name,
            model=configured["model"], role=stage.role,
            effort=configured["effort"],
            duration_ms=int((time.perf_counter() - started) * 1000),
            fallback_reason=f"the model call failed: {e}")

    problems = _conforms(result.data, schema)
    if problems:
        return Outcome(
            stage=stage.key, family=stage.family, provider=provider.name,
            model=result.model, role=stage.role, effort=configured["effort"],
            duration_ms=result.duration_ms, request_id=result.request_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens, attempts=result.attempts,
            fallback_reason="the reply did not conform to the schema",
            schema_errors=problems)

    return Outcome(
        stage=stage.key, engine=MODEL, data=dict(result.data),
        family=stage.family, provider=provider.name, model=result.model,
        role=stage.role, effort=configured["effort"],
        duration_ms=result.duration_ms, request_id=result.request_id,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        attempts=result.attempts)


__all__ = ["DETERMINISTIC", "FUNCTIONALITY", "INTERPRETATION", "MODEL",
           "OPUS", "Outcome", "PASS_1", "PASS_2", "PLAN", "SONNET", "STAGES",
           "SUFFICIENCY", "SUMMARY", "Stage", "call", "family_of",
           "provider_available", "routing"]
