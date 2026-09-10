"""A LABELLED MOCK provider, for structural tests only.

This is not a model and nothing it produces is evidence that the agentic
architecture works against a real one. Section 18 and the task's own standing
constraint are explicit: mocks are for explicitly labelled automated tests, and
live-provider behaviour is BLOCKED/UNVERIFIED until a credential is configured.

What it IS good for is proving the things that are the application's
responsibility rather than the model's: that the gate runs first, that a
referral executes nothing, that five submissions is five, that a repair
continuation carries the full effective context, that CreditProbe never edits
the SQL it was handed, and that a stop says something true.

It records every outbound request verbatim, which is what lets
`test_repair_context.py` read the serialized conversation and assert what it
contains.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.llm.base import ConverseResult, LLMResult


class _Truncate:
    """A scripted turn that the provider cuts off at max_tokens.

    Returned from a `converse_script` entry instead of a payload. The result is
    what a real provider gives on truncation: a partial tool_use block, no
    parsed tool call, and `stop_reason="max_tokens"`.
    """

    def __repr__(self) -> str:                              # pragma: no cover
        return "TRUNCATE"


#: The sentinel itself. `lambda _r: TRUNCATE` is one truncated turn.
TRUNCATE = _Truncate()


def two_stage(payload: dict[str, Any]) -> list[Any]:
    """Split one gate-and-plan payload into the two Opus stages.

    Cockpit V3 asks Opus twice for a data analysis: once at the gate, over the
    light packet, for the decision alone; then once over the full analytical
    packet, for the plan and the first step. A test whose subject is something
    else -- the counters, the repair context, a stop -- says what the model
    decided and what it planned in one dict, and this turns that into the two
    turns the runtime will actually make.

    A payload with no plan and no steps is a single turn: a referral, a
    clarification, a product-help answer and an unsupported request all end at
    the gate, and inventing a second turn for them would let a test pass while
    the runtime made a call it must never make.

    Only a GATE payload is split. A repair turn and a review turn also carry a
    plan and steps, and splitting one of those would silently insert a turn the
    runtime never makes -- which is how this helper first went wrong.
    """
    if "decision" not in payload or "scores" not in payload:
        return [payload]
    if not (payload.get("plan") or payload.get("steps")):
        return [payload]
    gate = {k: v for k, v in payload.items() if k not in ("plan", "steps")}
    plan = {"action": "submit_the_first_step",
            "plan": payload.get("plan"),
            "steps": payload.get("steps") or []}
    return [gate, plan]


def expand(turns) -> list[Any]:
    """Apply `two_stage` to every plain-dict turn in a script.

    Callables are left alone: a test that scripts a turn as a function is
    reading the request to decide its answer, and it knows which turn it is
    answering.
    """
    out: list[Any] = []
    for turn in turns:
        if isinstance(turn, dict):
            out.extend(two_stage(turn))
        else:
            out.append(turn)
    return out


@dataclass
class Block:
    """A stand-in for a provider content block."""

    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeProvider:
    """Scripted turns, with every request recorded.

    `converse_script` is a list of callables. Each receives the request and
    returns the tool payload for that turn, so a test can make the model's
    third answer depend on what the second failure said.
    """

    converse_script: list[Callable[[dict[str, Any]], dict[str, Any]]] = \
        field(default_factory=list)
    structured_script: list[dict[str, Any]] = field(default_factory=list)
    #: Every outbound request, verbatim. The evidence for the context tests.
    requests: list[dict[str, Any]] = field(default_factory=list)
    structured_requests: list[dict[str, Any]] = field(default_factory=list)
    name: str = "fake"
    model: str = "fake-model"
    #: Set to raise instead of answering, to test the unavailable path.
    raises: Exception | None = None

    @property
    def configured(self) -> bool:
        return True

    # ---- the conversation ------------------------------------------------

    def converse(self, *, system: Any, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None,
                 max_tokens: int = 4096, model: str = "",
                 purpose: str = "conversation", role: str = "",
                 effort: str = "", timeout: float = 0.0,
                 allow_retry: bool = True) -> ConverseResult:
        request = {"system": system, "messages": [dict(m) for m in messages],
                   "tools": tools, "purpose": purpose,
                   "max_tokens": max_tokens,
                   # As above: the id on the wire, not the id in a log line.
                   "model": model, "role": role, "effort": effort}
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        if not self.converse_script:
            raise AssertionError(
                f"the fake provider ran out of scripted turns at "
                f"{purpose!r} (turn {len(self.requests)})")
        payload = self.converse_script.pop(0)(request)
        tool_name = (tools or [{}])[0].get("name", "tool")
        if payload is TRUNCATE:
            # What a real provider returns when the reply reaches max_tokens
            # mid-answer: a partial tool_use block, no parsed call, and
            # stop_reason="max_tokens". The partial block is deliberately
            # included, because leaving it in the conversation is exactly the
            # bug the caller has to avoid.
            partial = Block(type="tool_use",
                            id=f"toolu_{len(self.requests):02d}",
                            name=tool_name, input={})
            return ConverseResult(
                assistant_blocks=[partial], text="", stop_reason="max_tokens",
                tool_calls=[], model=self.model,
                input_tokens=self.serialized_size(request) // 4,
                output_tokens=max_tokens)
        block = Block(type="tool_use", id=f"toolu_{len(self.requests):02d}",
                      name=tool_name, input=payload)
        return ConverseResult(
            assistant_blocks=[block], text="", stop_reason="tool_use",
            tool_calls=[{"id": block.id, "name": tool_name, "input": payload}],
            model=self.model, input_tokens=self.serialized_size(request) // 4,
            output_tokens=len(json.dumps(payload, default=str)) // 4)

    # ---- the single-shot call -------------------------------------------

    def structured(self, *, system: str, prompt: str, schema: dict[str, Any],
                   tool_name: str, tool_description: str,
                   max_tokens: int = 2000, purpose: str = "reading",
                   model: str = "", role: str = "", effort: str = "",
                   system_blocks: Any = None,
                   cache_prefix: str = "") -> LLMResult:
        self.structured_requests.append(
            {"system": system, "prompt": prompt, "purpose": purpose,
             "tool_name": tool_name,
             # Recorded so a test can read WHICH MODEL this application asked
             # for, rather than trusting a log that says which one it meant to.
             "model": model, "role": role, "effort": effort})
        if self.raises is not None:
            raise self.raises
        if not self.structured_script:
            raise AssertionError(
                f"the fake provider ran out of scripted structured answers at "
                f"{purpose!r}")
        data = self.structured_script.pop(0)
        return LLMResult(data=data, model=self.model,
                         input_tokens=len(prompt) // 4,
                         output_tokens=len(json.dumps(data, default=str)) // 4)

    # ---- inspection ------------------------------------------------------

    @staticmethod
    def serialized_size(request: dict[str, Any]) -> int:
        return len(json.dumps(request, default=str))

    def serialized(self, index: int = -1) -> str:
        """One outbound request as a single string, exactly as it was sent.

        This is what the retry-context tests read: section 14.3 asks for the
        actual serialized outbound request, and a schema hash passing a check
        must fail it.
        """
        return json.dumps(self.requests[index], default=str)

    def last_purpose(self) -> str:
        return self.requests[-1]["purpose"] if self.requests else ""

    def purposes(self) -> list[str]:
        return [r["purpose"] for r in self.requests]
