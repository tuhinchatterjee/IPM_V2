"""
The Anthropic provider.

Structured output is obtained through **tool use**, not through asking for JSON
in prose: the schema CreditProbe supplies becomes a tool's input schema, and the
model's answer is the tool call's arguments. A reply that does not call the tool
is an error, because the alternative — salvaging prose — is how a plan quietly
loses a filter and answers a slightly different question.

Retries cover the two failures that are worth retrying: a transport hiccup, and
a model reply that came back as prose. Anything else is reported, because a
provider that retries a refusal is a provider that turns one problem into three.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.llm import caching, telemetry
from backend.llm.base import LLMError, LLMResult, ProviderStatus, register

logger = logging.getLogger(__name__)

#: Pinned rather than an alias. A provider-side change to what "latest" means
#: must not alter how CreditProbe reads a question without a release.
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

#: Two attempts after the first. A third rarely converts and triples the
#: latency a user is sitting in front of.
MAX_ATTEMPTS = 3

#: How long one orchestration call may take before it is abandoned. Chosen so a
#: hung provider degrades to offline mode inside the request rather than
#: occupying a worker until the client gives up.
TIMEOUT_SECONDS = 60.0


@dataclass
class AnthropicProvider:
    """Anthropic Claude, used as an orchestrator rather than an author."""

    api_key: str
    model: str = DEFAULT_MODEL
    name: str = "anthropic"
    timeout: float = TIMEOUT_SECONDS
    #: Injectable so the contract can be tested without a key or a network. The
    #: default is built lazily, because constructing a client at import time
    #: would make the whole backend fail to start on a bad key.
    client: Any = field(default=None, repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def status(self) -> ProviderStatus:
        """The observed state, not the configured one.

        A key is a necessary condition and never a sufficient one, so the state
        comes from the ledger of calls actually made. See backend/llm/telemetry.
        """
        observed = telemetry.health(provider=self.name, model=self.model,
                                    configured=self.configured)
        return ProviderStatus(
            provider=self.name, model=self.model,
            configured=self.configured, state=observed["state"],
            detail=observed["detail"], health=observed)

    # ---- the one call ------------------------------------------------------

    def structured(self, *, system: str, prompt: str, schema: dict[str, Any],
                   tool_name: str, tool_description: str,
                   max_tokens: int = 2000,
                   purpose: str = "reading",
                   model: str = "",
                   role: str = "", effort: str = "",
                   system_blocks: list[dict[str, Any]] | None = None,
                   cache_prefix: str = "") -> LLMResult:
        """One structured answer.

        `model` overrides the configured default for this call, so a role can
        be served by the model an administrator chose for it. Empty means the
        configured one — never a substitution, and never a guess.

        `system_blocks` is §19's prompt caching: the same system prompt, split
        into content blocks with a cache breakpoint at the end of the stable
        prefix. Composed by `backend.llm.caching`, which owns the rule that a
        client-sensitive block is never inside the cached span. When it is
        absent the plain `system` string is sent and nothing about the call
        changes — caching is an optimisation, never a different prompt.
        """
        if not self.configured:
            raise LLMError("No Anthropic API key is configured.")

        chosen = (model or "").strip() or self.model
        client = self._client()
        tool = {"name": tool_name, "description": tool_description,
                "input_schema": schema}
        started = time.perf_counter()
        last: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                message = client.messages.create(
                    model=chosen,
                    max_tokens=max_tokens,
                    system=system_blocks if system_blocks else system,
                    tools=[tool],
                    # The model must answer through the tool. Left to choose, it
                    # sometimes explains its plan in prose instead of emitting
                    # it, which is a reply CreditProbe cannot execute.
                    tool_choice={"type": "tool", "name": tool_name},
                    messages=[{"role": "user", "content": prompt}],
                )
                data = _tool_input(message, tool_name)
                usage = getattr(message, "usage", None)
                cached = caching.usage(usage)
                elapsed = int((time.perf_counter() - started) * 1000)
                telemetry.record_success(
                    provider=self.name, model=chosen, purpose=purpose,
                    role=role, effort=effort,
                    latency_ms=elapsed, request_id=_request_id(message),
                    attempts=attempt,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    cache_write_tokens=cached["cache_creation_input_tokens"],
                    cache_read_tokens=cached["cache_read_input_tokens"],
                    cache_prefix=cache_prefix)
                return LLMResult(
                    data=data, model=chosen, duration_ms=elapsed,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    cache_read_tokens=cached["cache_read_input_tokens"],
                    cache_write_tokens=cached["cache_creation_input_tokens"],
                    attempts=attempt,
                    request_id=_request_id(message),
                )
            except Exception as e:  # noqa: BLE001 - reported, not swallowed
                last = e
                if not _worth_retrying(e) or attempt == MAX_ATTEMPTS:
                    break
                logger.info("Retrying the orchestrator (attempt %d): %s",
                            attempt + 1, e)
                time.sleep(0.4 * attempt)

        # Recorded before it is raised, so a failure is visible in Settings even
        # though the caller degrades quietly to the offline reader.
        telemetry.record_failure(
            provider=self.name, model=chosen, purpose=purpose,
            role=role, effort=effort,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=last, request_id=_error_request_id(last),
            attempts=min(attempt, MAX_ATTEMPTS))
        raise LLMError(
            f"The orchestrator did not answer: {telemetry.sanitise(str(last))}"
        ) from last

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        import anthropic

        self.client = anthropic.Anthropic(api_key=self.api_key,
                                          timeout=self.timeout)
        return self.client


def _tool_input(message: Any, tool_name: str) -> dict[str, Any]:
    """The tool call's arguments, or an error naming what came back instead."""
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", "") == "tool_use" and block.name == tool_name:
            payload = block.input
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                raise LLMError(
                    f"The orchestrator returned a {type(payload).__name__} "
                    "rather than an object.")
            return payload
    spoken = " ".join(
        getattr(b, "text", "") for b in getattr(message, "content", []) or []
    ).strip()
    raise LLMError(
        "The orchestrator answered in prose rather than calling "
        f"{tool_name}: {spoken[:200] or '(nothing)'}")


def _request_id(message: Any) -> str:
    """The provider's own identifier for this call.

    Safe to show a user and the only thing that lets a provider trace a request
    on their side, which is why it is surfaced in Settings.
    """
    for attribute in ("_request_id", "id"):
        value = getattr(message, attribute, "")
        if value:
            return str(value)
    return ""


def _error_request_id(error: Exception | None) -> str:
    return str(getattr(error, "request_id", "") or "") if error else ""


def _worth_retrying(error: Exception) -> bool:
    """Whether a second attempt could plausibly succeed.

    A refusal, a bad key or an unknown model will fail identically forever, and
    retrying them turns one clear error into three slow ones.
    """
    name = type(error).__name__
    if name in {"APIConnectionError", "APITimeoutError", "InternalServerError",
                "RateLimitError", "APIStatusError", "OverloadedError"}:
        return True
    if isinstance(error, LLMError):
        # Prose instead of a tool call: a second attempt often lands.
        return "in prose" in str(error)
    return isinstance(error, (TimeoutError, ConnectionError))


register("anthropic", lambda key, model: AnthropicProvider(
    api_key=key, model=model or DEFAULT_MODEL))

__all__ = ["DEFAULT_MODEL", "MAX_ATTEMPTS", "AnthropicProvider"]
