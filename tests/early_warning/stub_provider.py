"""
A provider that answers, so the seam can be tested without a vendor key.

Why a stub rather than a mock
-----------------------------
The thing under test is not "does the code call a model" — that is one line and
a mock would prove it. It is whether the seven stages hold their contract when
a model DOES answer: whether the ledger counts the calls, whether the families
route where the architecture says, whether a reply that does not conform is
discarded, whether a model plan naming another dataset is still refused by the
validator, and whether prose carrying a figure the packet does not hold is
thrown away rather than shown.

So this is a real `LLMProvider`: it is reached through `backend.llm.get_provider`
like any other, it returns `LLMResult` objects with model ids and token counts,
and it answers each stage's schema from the stage's own packet — echoing back
what the deterministic floor already established, so a passing test means the
wiring held rather than that the stub was generous.

It is never registered as a CreditProbe provider and never imported by the
backend. A test injects it; nothing else can reach it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.llm.base import LLMError, LLMResult, ProviderStatus


def _packet(prompt: str) -> dict[str, Any]:
    """The JSON context the stage sent, read back out of its prompt."""
    start = prompt.find("{")
    if start < 0:
        return {}
    try:
        return json.loads(prompt[start:])
    except json.JSONDecodeError:
        return {}


@dataclass
class StubProvider:
    """Answers every Early Warning stage, and records what it was asked."""

    name: str = "stub"
    model: str = "stub-default"
    configured_flag: bool = True
    #: Every call, in order: tool name, the model that served it, the role and
    #: effort that travelled with it, and the packet it was given.
    calls: list[dict[str, Any]] = field(default_factory=list)
    #: Force a failure mode. "error" raises; "malformed" returns a reply that
    #: does not conform; "ungrounded" writes a figure the packet does not hold;
    #: "open_the_gate" tries to route a foreign question into Early Warning;
    #: "foreign_domain" plans a step against another dataset.
    behaviour: str = ""
    #: Which stage the behaviour applies to. Empty means every stage.
    behaviour_for: str = ""
    #: Canned replies by tool name, for testing the exact document shapes a
    #: real model returns. Takes precedence over everything else, so a test
    #: can paste a response transcribed from a live run and assert that the
    #: seam accepts it.
    replies: dict[str, Any] = field(default_factory=dict)
    #: Stop reason to report, so truncation can be exercised.
    stop_reason: str = "tool_use"

    @property
    def configured(self) -> bool:
        return self.configured_flag

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider=self.name, model=self.model,
            configured=self.configured_flag, state="connected",
            detail="A stub provider, used only by the tests.")

    def structured(self, *, system: str, prompt: str, schema: dict[str, Any],
                   tool_name: str, tool_description: str,
                   max_tokens: int = 2000, purpose: str = "reading",
                   model: str = "", role: str = "", effort: str = "",
                   **_: Any) -> LLMResult:
        served = (model or "").strip() or self.model
        packet = _packet(prompt)
        self.calls.append({"tool": tool_name, "model": served, "role": role,
                           "effort": effort, "purpose": purpose,
                           "packet": packet, "system": system,
                           "max_tokens": max_tokens})

        if tool_name in self.replies:
            canned = self.replies[tool_name]
            if isinstance(canned, Exception):
                raise canned
            return LLMResult(data=canned, model=served, duration_ms=3,
                             input_tokens=100, output_tokens=60,
                             request_id="stub-request")

        misbehaving = self.behaviour and (
            not self.behaviour_for or self.behaviour_for == tool_name)
        if misbehaving and self.behaviour == "error":
            raise LLMError("the stub was told to fail")
        if misbehaving and self.behaviour == "malformed":
            return LLMResult(data={"nonsense": True}, model=served,
                             duration_ms=1, input_tokens=10, output_tokens=5)

        data = _ANSWERS[tool_name](packet, self.behaviour if misbehaving else "")
        del schema, tool_description
        return LLMResult(data=data, model=served, duration_ms=7,
                         input_tokens=120, output_tokens=40,
                         request_id="stub-request")


def _clean(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    del behaviour
    return {"cleaned_english": str(packet.get("question") or "")
            or "The question, in clean English.",
            "translation_applied": False,
            "detected_entities": [], "uncertainties": [],
            "transcription_uncertainties": []}


def _read(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    del behaviour
    floor = packet.get("first_reading") or {}
    return {
        "normalized_business_request": str(
            floor.get("normalized_business_request") or ""),
        "subquestions": list(floor.get("subquestions") or []),
        "requested_analyses": list(floor.get("requested_analyses") or []),
        "requested_scope": str(floor.get("requested_scope") or ""),
        "requested_actions": list(floor.get("requested_actions") or []),
        "requested_grouping": str(floor.get("requested_grouping") or ""),
        "requested_period": str(floor.get("requested_period") or ""),
        "comparison_period": str(floor.get("comparison_period") or ""),
        "requested_evidence": bool(floor.get("requested_evidence")),
        "ambiguities": list(floor.get("ambiguities") or []),
        "clarification_needed": bool(floor.get("clarification_needed")),
    }


def _select(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    reading = (packet.get("pattern_reading") or {}).get("selected") or \
        "early_warning"
    if behaviour == "open_the_gate":
        reading = "early_warning"
    return {"selected_functionality": reading, "confidence": 0.88,
            "ownership_rationale": ("That product exists to answer this kind "
                                    "of question, whichever holds the data."),
            "ambiguous": False, "clarification": ""}


def _plan(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    floor = packet.get("deterministic_plan") or {}
    steps = [dict(s) for s in (floor.get("steps") or [])]
    if behaviour == "foreign_domain":
        steps = [dict(steps[0], domain="ifrs9_staging")] if steps else [
            {"analysis": "population", "domain": "ifrs9_staging",
             "rationale": "read the staging table"}]
    return {"steps": steps or [{"analysis": "population",
                                "domain": "early_warning",
                                "rationale": "the population position"}],
            "output_grain": str(floor.get("output_grain") or "population_month"),
            "intent": str(floor.get("intent") or ""),
            "notes": []}


def _review(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    floor = packet.get("coverage_map") or {}
    if behaviour == "declare_incomplete":
        # A review that always wants one more step, so the revision path can
        # be driven against a squeezed budget.
        return {"complete": False, "uncovered": ["concentration"],
                "unsupported_claims": [], "next_analysis": "concentration",
                "next_analysis_rationale": "the review wants one more",
                "presentation": "narrative"}
    if behaviour == "declare_complete":
        return {"complete": True, "uncovered": [], "unsupported_claims": [],
                "next_analysis": "", "presentation": "narrative"}
    return {"complete": bool(floor.get("complete", True)),
            "uncovered": list(floor.get("uncovered") or []),
            "unsupported_claims": list(floor.get("unsupported_claims") or []),
            "next_analysis": "",
            "presentation": str(floor.get("presentation") or "narrative")}


def _interpret(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    floor = packet.get("deterministic_reading") or {}
    direct = str(floor.get("direct") or "The position, stated directly.")
    reading = str(floor.get("interpretation") or "What the position means.")
    if behaviour == "ungrounded":
        reading += " Total exposure across the segment is SAR 88,412.7m."
    return {"direct": direct, "interpretation": reading,
            "points": [], "drivers": list(floor.get("drivers") or []),
            "follow_ups": list(floor.get("follow_ups") or []),
            "caveats": []}


def _summarise(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    del behaviour
    state = packet.get("thread_state") or {}
    return {"confirmed": list(state.get("confirmed") or [])[:3],
            "unresolved": [], "next_drills": []}


_ANSWERS = {
    "clean_the_question": _clean,
    "read_the_business_request": _read,
    "select_functionality": _select,
    "plan_the_analysis": _plan,
    "review_sufficiency": _review,
    "interpret_the_result": _interpret,
    "update_the_thread_summary": _summarise,
}


def install(monkeypatch, provider: StubProvider) -> StubProvider:
    """Reach the stub the way every stage reaches a provider.

    Patched at `backend.llm.get_provider`, which is what the seam imports at
    call time. Nothing in the Early Warning code is patched, so a test that
    passes proves the seam's own path rather than a path built for it.
    """
    import backend.llm as llm

    monkeypatch.setattr(llm, "get_provider",
                        lambda *, refresh=False: provider)
    return provider


__all__ = ["StubProvider", "install"]
