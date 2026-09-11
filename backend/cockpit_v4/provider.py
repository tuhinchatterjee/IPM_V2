"""
The provider boundary: one explicit model, native tool calls, real deadlines.

What this module refuses to do
------------------------------
It does not choose a model. `AI_COCKPIT_REASONING_MODEL` names one id, it is
verified against the provider, and if it is missing or will not serve, the run
fails with a configuration error. There is no "latest", no inheriting
`AI_MODEL`, no substituting a cheaper model when the named one is unavailable,
and no second model to fall back to on a refusal.

It also does not extract JSON from prose. A tool call arrives as a complete
tool_use block or it does not arrive; a regex over a half-written sentence is
how a truncated plan becomes an executed query.

Deadlines are enforced OUTSIDE the client. An HTTP read timeout bounds one
socket read, not an end-to-end run, and an SDK that retries internally can
turn a 30-second timeout into three minutes. SDK retries are switched off here
so every actual HTTP attempt passes through the ledger.
"""

from __future__ import annotations

import hashlib
import re
import json
import time
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4.budgets import BudgetExceeded, Ledger
from backend.cockpit_v4.capability import Capability
from backend.cockpit_v4.states import (COST_LIMIT, INPUT_CONTEXT_LIMIT,
                                       INVALID_MODEL_OUTPUT, OUTPUT_LIMIT,
                                       PROVIDER_AUTH, PROVIDER_RATE_LIMIT,
                                       PROVIDER_REQUEST_INVALID,
                                       PROVIDER_UNAVAILABLE,
                                       TOOL_SCHEMA_INVALID)

#: Stop reasons that mean the model finished a turn we can act on.
COMPLETE_STOPS: frozenset[str] = frozenset({"tool_use", "end_turn",
                                            "stop_sequence"})
TRUNCATED_STOP = "max_tokens"
REFUSAL_STOPS: frozenset[str] = frozenset({"refusal"})


class ProviderFailure(RuntimeError):
    """A provider or protocol failure, with the code the run stops under."""

    def __init__(self, code: str, message: str, *,
                 retry_class: str = "none",
                 detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_class = retry_class
        self.detail = dict(detail or {})


class OutputTruncated(ProviderFailure):
    """The response hit its output allowance. INCOMPLETE, not shorter.

    Nothing in the truncated turn executes. Half a tool call is not a tool
    call, and the partial assistant message is rolled out of history so the
    next request is not malformed by an unanswered tool_use.
    """

    def __init__(self, message: str, *, limit: int) -> None:
        super().__init__(OUTPUT_LIMIT, message, retry_class="format")
        self.limit = limit


class InputTooLarge(ProviderFailure):
    def __init__(self, message: str, *, counted: int, capacity: int) -> None:
        super().__init__(INPUT_CONTEXT_LIMIT, message)
        self.counted = counted
        self.capacity = capacity


@dataclass
class ToolCall:
    """One complete tool_use block. Never a fragment."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Turn:
    """One provider round trip, with everything the ledger and trace need."""

    assistant_blocks: list[Any]
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    model: str
    request_id: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    counted_input_tokens: int
    count_method: str

    def usage(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read_tokens,
                "cache_write_tokens": self.cache_write_tokens}


@dataclass
class Analyst:
    """The one model conversation. Owns the history and its tool pairing.

    `messages` is the canonical provider history. Assistant blocks go back
    verbatim and in order -- including any opaque signature block the provider
    requires and nobody may invent -- and every accepted tool_use is answered
    by its matching tool_result in the same order on the next turn.
    """

    provider: Any
    capability: Capability
    ledger: Ledger
    system: list[dict[str, Any]] | str
    tools: list[dict[str, Any]]
    messages: list[dict[str, Any]] = field(default_factory=list)
    #: tool_use ids awaiting their tool_result, in the order they arrived.
    _pending: list[str] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    #: What the last generation asked for and what the budget granted.
    response_allowance: dict[str, Any] = field(default_factory=dict)

    # -- history ---------------------------------------------------------

    def user(self, text: str) -> None:
        if self._pending:
            raise ProviderFailure(
                INVALID_MODEL_OUTPUT,
                f"{len(self._pending)} tool call(s) are unanswered; a user "
                f"turn cannot be appended before their tool results.")
        self.messages.append({"role": "user", "content": text})

    def tool_result(self, tool_use_id: str, payload: Any, *,
                    is_error: bool = False) -> None:
        """Answer one tool_use. Order is checked, not assumed.

        A history with a tool_use that has no matching tool_result is
        malformed on the next request; a history whose results arrive out of
        order is accepted by some providers and silently misattributed. Both
        are refused here.
        """
        if not self._pending:
            raise ProviderFailure(
                INVALID_MODEL_OUTPUT,
                "there is no outstanding tool call to answer.")
        expected = self._pending[0]
        if tool_use_id != expected:
            raise ProviderFailure(
                INVALID_MODEL_OUTPUT,
                f"tool results must follow their calls in order: expected "
                f"{expected}, got {tool_use_id}.")
        self._pending.pop(0)
        body = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, default=str)
        block = {"type": "tool_result", "tool_use_id": tool_use_id,
                 "content": body}
        if is_error:
            block["is_error"] = True
        if (self.messages and self.messages[-1]["role"] == "user"
                and isinstance(self.messages[-1].get("content"), list)):
            self.messages[-1]["content"].append(block)
        else:
            self.messages.append({"role": "user", "content": [block]})

    @property
    def awaiting_results(self) -> tuple[str, ...]:
        return tuple(self._pending)

    # -- counting --------------------------------------------------------

    def count_input(self) -> tuple[int, str]:
        """Count the WHOLE assembled request against the serving model.

        Includes the system blocks and the tool schemas, because both are
        input the provider bills and the context window holds. A local
        character estimate is labelled an estimate; it is never presented as
        a calibrated truth.
        """
        counter = getattr(self.provider, "count_tokens", None)
        if callable(counter) and self.capability.supports_token_counting:
            try:
                self.ledger.spend_provider_attempt()
                value = counter(system=self.system, messages=self.messages,
                                tools=self.tools,
                                model=self.capability.model_id)
                return int(value), "provider_count_tokens"
            except Exception:  # noqa: BLE001 - fall back, but say so
                pass
        payload = json.dumps(
            {"system": self.system, "messages": self.messages,
             "tools": self.tools}, ensure_ascii=False, default=str)
        # Deliberately conservative: over-estimating stops a run early, and
        # under-estimating sends a request the model cannot hold.
        return int(len(payload) / 2.2) + 1, "local_conservative_estimate"

    def fits(self, *, reserved_output: int) -> tuple[bool, int, str]:
        counted, method = self.count_input()
        margin = max(1024, int(counted * 0.02))
        return (counted + reserved_output + margin
                <= self.capability.context_tokens), counted, method

    # -- the call --------------------------------------------------------

    def ask(self, *, purpose: str, max_output_tokens: int,
            tool_choice: str = "any") -> Turn:
        """One generation attempt. Bounded, reserved, counted and settled."""
        self.ledger.check_deadline()
        attempt = self.ledger.spend_generation()

        reserved_output = min(max_output_tokens,
                              self.capability.max_output_tokens)
        ok, counted, method = self.fits(reserved_output=reserved_output)
        if not ok:
            raise InputTooLarge(
                f"the assembled request measured {counted:,} tokens "
                f"({method}) and, with {reserved_output:,} tokens reserved "
                f"for the response, does not fit the "
                f"{self.capability.context_tokens:,}-token capacity of "
                f"{self.capability.model_id}. Nothing was sent.",
                counted=counted, capacity=self.capability.context_tokens)

        # Ask for the answer the budget can actually carry. Reserving the
        # maximum and then refusing the run was how a real analysis stopped
        # at COST_LIMIT with $0.71 committed: a shorter answer was affordable
        # and nobody offered one. The cap SENT to the provider is reduced to
        # match, so the reservation stays a true projection.
        affordable = self.ledger.affordable_output_tokens(
            input_tokens=counted, wanted=reserved_output)
        self.response_allowance = {
            "wanted": reserved_output, "granted": min(reserved_output,
                                                      affordable),
            "reduced": affordable < reserved_output}
        if affordable < reserved_output:
            if affordable < self.ledger.MIN_RESPONSE_TOKENS:
                raise BudgetExceeded(
                    COST_LIMIT,
                    f"the remaining budget affords {affordable:,} response "
                    f"tokens against a {self.ledger.MIN_RESPONSE_TOKENS:,}-"
                    f"token minimum, so no useful answer could be bought. "
                    f"Nothing was sent.")
            reserved_output = affordable
            ok, counted, method = self.fits(reserved_output=reserved_output)

        reservation = self.ledger.reserve(
            purpose=purpose, input_tokens=counted,
            output_tokens=reserved_output)

        # The deadline the CLIENT gets is bounded by the time the RUN has
        # left, so a stalled socket cannot outlive the run's own watchdog.
        timeout = max(1.0, min(self.ledger.remaining_seconds,
                               self.ledger.limits.deadline_seconds))
        started = time.monotonic()
        try:
            self.ledger.spend_provider_attempt()
            result = self.provider.converse(
                system=self.system, messages=self.messages, tools=self.tools,
                max_tokens=reserved_output, model=self.capability.model_id,
                purpose=purpose, role="cockpit_v4_analyst", timeout=timeout,
                # Every HTTP attempt must pass through the ledger, so the
                # SDK is not allowed to retry behind our back.
                allow_retry=False)
        except BudgetExceeded:
            # OUR accounting refused the attempt, so nothing was sent and
            # nothing can have been billed. Settled at zero, and the budget
            # code is passed through: a run that used its attempt allowance
            # stopped on CALL_LIMIT, and reporting that as an outage sends an
            # operator looking for a provider that is working perfectly.
            self.ledger.settle(reservation, usage={}, uncertain=False)
            raise
        except Exception as exc:  # noqa: BLE001
            # The request may have reached the provider and been billed.
            # Held pending, never booked as zero.
            self.ledger.settle(reservation, usage={"error": str(exc)[:200]},
                               uncertain=True)
            raise _classify(exc) from exc

        self.ledger.settle(reservation, usage={
            "input_tokens": int(getattr(result, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(result, "output_tokens", 0) or 0),
            "cache_read_tokens": int(
                getattr(result, "cache_read_tokens", 0) or 0),
            "cache_write_tokens": int(
                getattr(result, "cache_write_tokens", 0) or 0)})

        stop_reason = str(getattr(result, "stop_reason", "") or "")
        blocks = list(getattr(result, "assistant_blocks", []) or [])

        turn = Turn(
            assistant_blocks=blocks, text=str(getattr(result, "text", "") or ""),
            tool_calls=[], stop_reason=stop_reason,
            model=str(getattr(result, "model", "") or
                      self.capability.model_id),
            request_id=str(getattr(result, "request_id", "") or ""),
            duration_ms=int((time.monotonic() - started) * 1000),
            input_tokens=int(getattr(result, "input_tokens", 0) or 0),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(result, "cache_read_tokens", 0) or 0),
            cache_write_tokens=int(getattr(result, "cache_write_tokens", 0)
                                   or 0),
            counted_input_tokens=counted, count_method=method)
        self.turns.append({
            "purpose": purpose, "attempt": attempt,
            "stop_reason": stop_reason, "request_id": turn.request_id,
            "counted_input_tokens": counted, "count_method": method,
            "reported_input_tokens": turn.input_tokens,
            "output_tokens": turn.output_tokens,
            "cache_read_tokens": turn.cache_read_tokens,
            "cache_write_tokens": turn.cache_write_tokens,
            "duration_ms": turn.duration_ms})

        if stop_reason == TRUNCATED_STOP:
            # The partial turn does NOT enter history. Keeping it would leave
            # an unanswered tool_use and make the next request malformed.
            raise OutputTruncated(
                f"the response reached its {reserved_output:,}-token output "
                f"allowance, so the {purpose} is incomplete. A truncated "
                f"tool call is not a smaller one, and nothing from it ran.",
                limit=reserved_output)
        if stop_reason in REFUSAL_STOPS:
            raise ProviderFailure(
                PROVIDER_UNAVAILABLE,
                "the model declined to answer this request. No other model "
                "was tried.", detail={"stop_reason": stop_reason})
        if stop_reason and stop_reason not in COMPLETE_STOPS:
            # An unknown finish reason is a defined failure, not a reason to
            # keep going and hope.
            raise ProviderFailure(
                INVALID_MODEL_OUTPUT,
                f"the provider returned an unrecognised stop reason "
                f"{stop_reason!r}. The turn was not treated as complete.",
                detail={"stop_reason": stop_reason})

        # Only now, with a complete turn, does history advance.
        if blocks:
            self.messages.append({"role": "assistant", "content": blocks})
        for raw in list(getattr(result, "tool_calls", []) or []):
            arguments = raw.get("input")
            if not isinstance(arguments, dict):
                raise ProviderFailure(
                    INVALID_MODEL_OUTPUT,
                    f"tool call {raw.get('name')!r} arrived without a "
                    f"complete argument object.")
            turn.tool_calls.append(ToolCall(
                id=str(raw.get("id") or ""), name=str(raw.get("name") or ""),
                arguments=dict(arguments)))
        self._pending = [c.id for c in turn.tool_calls]
        return turn

    def rollback_last_turn(self) -> None:
        """Drop an assistant turn that must not be replayed."""
        if self.messages and self.messages[-1]["role"] == "assistant":
            self.messages.pop()
        self._pending.clear()


#: `tools.0.custom.input_schema` and friends: which tool the provider refused.
_SCHEMA_PATH = re.compile(r"tools\.(\d+)\.[\w.]*input_schema[\w.]*")
#: The keywords the provider names when it rejects a tool schema.
_UNSUPPORTED_KEYWORD = re.compile(
    r"does not support ([^.;]+)", re.I)
#: Anything that looks like a key. Never echoed into a message.
_SECRETISH = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+)")


def _sanitize(text: str) -> str:
    return _SECRETISH.sub("[redacted]", text)


def _classify(exc: Exception) -> ProviderFailure:
    """Map a transport exception to the code an operator can act on.

    The distinction that matters most here is between "the provider could not
    be reached" and "the provider answered, and what it said was that our
    request was malformed". A live UAT showed PROVIDER_UNAVAILABLE for an
    HTTP 400 naming an unsupported tool-schema keyword — so an operator went
    looking for an outage while the actual fault was in the schema
    CreditProbe published, and nothing in the trace said the request had been
    rejected BEFORE any inference.

    A failure that ALREADY carries a code is returned untouched. Re-reading
    its message would throw away a classification made by the layer that had
    the provider's own response in hand, and re-derive a worse one from the
    string: that is exactly how a rejected credential or a rate limit ends up
    reported as an outage.
    """
    if isinstance(exc, ProviderFailure):
        return exc
    text = str(exc)
    lowered = text.lower()
    name = type(exc).__name__.lower()

    is_400 = ("400" in text or "invalid_request_error" in lowered
              or "badrequest" in name)
    if is_400:
        schema_path = _SCHEMA_PATH.search(text)
        keyword = _UNSUPPORTED_KEYWORD.search(text)
        detail = {
            "status_code": 400,
            "provider_error_type": "invalid_request_error",
            "rejected_before_inference": True,
            "provider_message": _sanitize(text)[:400],
        }
        if schema_path:
            detail["failing_schema_path"] = schema_path.group(0)
            detail["failing_tool_index"] = int(schema_path.group(1))
        if keyword:
            detail["unsupported_keywords"] = [
                k.strip() for k in keyword.group(1).split(",") if k.strip()]
        if schema_path or "input_schema" in lowered or "tools." in lowered:
            return ProviderFailure(
                TOOL_SCHEMA_INVALID,
                "CreditProbe sent a tool definition this provider does not "
                "accept, so the request was rejected before the model saw "
                "it. Nothing was inferred, nothing was billed for inference, "
                "and no other model was tried.",
                retry_class="none", detail=detail)
        return ProviderFailure(
            PROVIDER_REQUEST_INVALID,
            "The provider rejected this request as malformed before running "
            "it. This is a fault in what CreditProbe sent, not an outage.",
            retry_class="none", detail=detail)

    if "authentication" in lowered or "401" in text or "invalid api key" in lowered:
        return ProviderFailure(
            PROVIDER_AUTH,
            "the provider rejected this deployment's Cockpit credential. No "
            "other credential was tried.", retry_class="none",
            detail={"status_code": 401,
                    "rejected_before_inference": True})
    if "permission" in lowered or "403" in text:
        return ProviderFailure(
            PROVIDER_AUTH,
            "the provider refused this deployment's Cockpit credential for "
            "the configured model.", retry_class="none")
    if "rate" in lowered and "limit" in lowered or "429" in text:
        return ProviderFailure(
            PROVIDER_RATE_LIMIT,
            "the provider rate-limited this request.",
            retry_class="transport",
            detail={"status_code": 429,
                    "rejected_before_inference": True})
    if ("timeout" in lowered or "timed out" in name or "connection" in lowered
            or "503" in text or "502" in text or "overloaded" in lowered):
        return ProviderFailure(
            PROVIDER_UNAVAILABLE,
            f"the provider request did not complete: {text[:200]}",
            retry_class="transport")
    return ProviderFailure(
        PROVIDER_UNAVAILABLE,
        f"the provider request failed: {_sanitize(text)[:200]}",
        retry_class="none",
        detail={"provider_exception_type": type(exc).__name__,
                "rejected_before_inference": False})


def code_digest(code: str) -> str:
    """The digest that proves what executed equals what was authored."""
    return "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest()


__all__ = ["Analyst", "InputTooLarge", "OutputTruncated", "ProviderFailure",
           "ToolCall", "Turn", "code_digest"]
