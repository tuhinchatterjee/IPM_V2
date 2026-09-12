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
    """Clean English, to the standard the product's own patterns reach.

    Pass one is the only stage whose prompt does NOT carry the deterministic
    floor — it is given the raw question and nothing else — so a stub that
    echoes its input is not "as good as the floor", it is worse than it, and
    a test built on it measures the stub. `wich contrcting names deterioted`
    would come back unspelled, the sector filter would never be read, and the
    turn would answer about the whole book.

    So the stub spells it the way the patterns do. It still invents nothing:
    this is the product's own corrector, run where a real Sonnet would run.
    """
    del behaviour
    from backend.early_warning.conversation import normalise as nm

    floor = nm._clean_deterministic(str(packet.get("question") or ""))
    return {"cleaned_english": floor.cleaned_english
            or "The question, in clean English.",
            "translation_applied": floor.translation_applied,
            "detected_entities": list(floor.detected_entities),
            "uncertainties": list(floor.uncertainties),
            "transcription_uncertainties": list(
                floor.transcription_uncertainties)}


#: The `requested_layer` values a live Sonnet actually produced, none of which
#: the closed enum accepts as sent.
LAYER_SHAPES: dict[str, Any] = {
    "lowercase_layer": "l3",
    "spelled_layer": "Layer 3",
    "described_layer": "external intelligence",
    "verbose_layer": "L3 external intelligence",
    "listed_layer": ["L3"],
    "blank_layer": "",
    "null_layer": None,
    "unknown_layer": "L9",
}


def _read(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    floor = packet.get("first_reading") or {}
    out: dict[str, Any] = {
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
    if behaviour in LAYER_SHAPES:
        out["requested_layer"] = LAYER_SHAPES[behaviour]
    return out


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


def _signed_figure(packet: dict[str, Any]) -> tuple[str, float] | None:
    """The first negative figure the packet carries, and where it lives.

    Movements are stored signed. Finding one lets the stub write the sentence
    a real Opus writes about it — "fell 11.31 points" — which is the exact
    shape that discarded four live certification readings.
    """
    def walk(value: Any, path: str):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and value < 0:
            return (path, float(value))
        if isinstance(value, dict):
            for key, item in value.items():
                got = walk(item, f"{path}.{key}" if path else str(key))
                if got:
                    return got
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                got = walk(item, f"{path}[{i}]")
                if got:
                    return got
        return None

    return walk(packet.get("figures") or {}, "")


def _row_exposures(packet: dict[str, Any]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for i, row in enumerate(packet.get("rows") or []):
        value = (row or {}).get("exposure")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append((f"rows[{i}].exposure", float(value)))
    return out


def _interpret(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    floor = packet.get("deterministic_reading") or {}
    direct = str(floor.get("direct") or "The position, stated directly.")
    reading = str(floor.get("interpretation") or "What the position means.")
    declared: list[dict[str, Any]] = []

    if behaviour == "ungrounded":
        reading += " Total exposure across the segment is SAR 88,412.7m."

    if behaviour == "writes_a_magnitude":
        # What every failing live reading did: state the SIZE of a movement
        # the packet stores signed, in the words a credit paragraph uses.
        signed = _signed_figure(packet)
        if signed:
            reading += f" It fell {abs(signed[1]):.2f} points over the window."
        # And the two phrases this stage's own system prompt asks for, both
        # of which the numeral scanner used to read as negative numbers.
        reading += (" The evidence rests on a single tier-3 source, and the "
                    "top-5 names carry most of it.")

    if behaviour in ("declares_arithmetic", "undeclared_arithmetic",
                     "bad_declaration"):
        pairs = _row_exposures(packet)[:2]
        if len(pairs) == 2:
            # The MEAN rather than the sum. A sum of the two largest rows is
            # very often a total the packet already carries, which would make
            # the undeclared case pass for the wrong reason — the figure would
            # be grounded directly and the declaration would prove nothing.
            average = round((pairs[0][1] + pairs[1][1]) / 2, 2)
            stated = average if behaviour != "bad_declaration" else average + 25.0
            reading += f" The two average SAR {stated:.2f}m each."
            if behaviour != "undeclared_arithmetic":
                declared.append({
                    "value": stated, "op": "mean",
                    "refs": [pairs[0][0], pairs[1][0]]})

    out = {"direct": direct, "interpretation": reading,
           "points": [], "drivers": list(floor.get("drivers") or []),
           "follow_ups": list(floor.get("follow_ups") or []),
           "caveats": []}
    if declared:
        out["derived_claims"] = declared
    return out


def _summarise(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    del behaviour
    state = packet.get("thread_state") or {}
    return {"confirmed": list(state.get("confirmed") or [])[:3],
            "unresolved": [], "next_drills": []}


def _repair_plan(packet: dict[str, Any], behaviour: str) -> dict[str, Any]:
    """A repair that does what a good one does: fix what was named.

    Drops any step the packet reports as unsupported and leaves the rest, so
    a test asserting "the repair happened" is asserting the seam rather than
    the stub's cleverness.
    """
    del behaviour
    refused = {int(u.get("step", -1))
               for u in (packet.get("unsupported") or [])}
    steps = [dict(s) for i, s in enumerate(
        (packet.get("plan") or {}).get("steps") or []) if i not in refused]
    if not steps:
        steps = [{"analysis": "population", "domain": "early_warning",
                  "rationale": "the position, after the refused steps went"}]
    return {"steps": steps,
            "output_grain": (packet.get("plan") or {}).get("output_grain")
            or "population_month",
            "intent": (packet.get("plan") or {}).get("intent") or "",
            "notes": []}


_ANSWERS = {
    "repair_the_plan": _repair_plan,
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
