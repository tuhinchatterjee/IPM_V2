"""
The provider contract.

None of these needs a key or a network. What is being tested is the boundary
CreditProbe relies on: a structured answer or an error, never prose salvaged
into a plan, and never a quiet pretence that a model answered.
"""

from __future__ import annotations

import pytest

from backend.llm.anthropic_provider import MAX_ATTEMPTS, AnthropicProvider
from backend.llm.base import LLMError, NullProvider

SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}},
          "required": ["intent"]}


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Message:
    def __init__(self, content, usage=None):
        self.content = content
        self.usage = usage


class _Usage:
    input_tokens = 120
    output_tokens = 45


class _Client:
    """A transport that returns what the test tells it to."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _tool_reply(payload):
    return _Message([_Block("tool_use", name="plan", input=payload)], _Usage())


def _prose_reply(text):
    return _Message([_Block("text", text=text)])


class _Timeout(Exception):
    """Stands in for anthropic.APITimeoutError without importing the SDK's
    exception hierarchy into the test."""


_Timeout.__name__ = "APITimeoutError"


# ---------------------------------------------------------------- no provider


def test_no_key_means_no_pretending():
    """The offline path must be decided where it can be labelled. A provider
    that returned something plausible would make LIMITED OFFLINE MODE
    unreportable."""
    provider = NullProvider()
    assert provider.configured is False
    with pytest.raises(LLMError):
        provider.structured(system="", prompt="", schema=SCHEMA,
                            tool_name="plan", tool_description="")


#: Words that describe a fault. A deployment that was never given an external
#: provider key does not have one, and a client reading the header must not be
#: told it does. §13.
_FAULT_WORDS = ("degraded", "limited", "offline", "unavailable", "error",
                "failed", "down", "broken", "disabled")


def test_the_offline_status_names_the_mode_and_does_not_report_a_fault():
    """Replaces `test_the_offline_status_says_what_is_degraded`.

    That test pinned the two literals "AI OFFLINE" and "LIMITED OFFLINE MODE".
    Both were wrong for the deployment they describe, and pinning them meant
    the product could not be corrected without the suite objecting: on the
    acceptance Mac, which had no provider key by design, the header read
    "AI OFFLINE" beside an orange "Backend degraded" badge while the backend
    was returning healthy 200s.

    The old assertion is obsolete because the string it pinned was the defect.
    What replaces it is stronger, not weaker: the old test allowed any label
    at all as long as it was that one, and said nothing about the rest of the
    status. This one holds the state machine (`offline` is still the state, so
    routing and telemetry are unchanged), requires the label to come from the
    one governed label table rather than a literal duplicated here, and adds
    the constraint the old test did not make - that neither the label nor the
    detail may describe a fault, in ANY of nine words, while still requiring
    the detail to state the real limitation so nobody can pass it by saying
    nothing.
    """
    from backend.llm import telemetry

    status = NullProvider().status()
    assert status.state == telemetry.OFFLINE
    assert status.configured is False
    assert status.label == telemetry.LABELS[telemetry.OFFLINE]

    surfaced = f"{status.label} {status.detail}".lower()
    for word in _FAULT_WORDS:
        assert word not in surfaced, (
            f"the no-provider status calls the deployment {word!r}, which a "
            f"client reads as an outage: {status.label!r} / {status.detail!r}")

    # And it must still say what is actually different, or "no fault" would
    # be satisfiable by saying nothing at all.
    assert "governed" in surfaced and "phrasing" in surfaced, (
        f"the status does not state the real limitation: {status.detail!r}")


def test_a_configured_provider_that_is_failing_still_reports_degraded():
    """The guard above must not have made every state sound fine.

    `degraded` means a key exists and calls to it are failing. That IS a
    fault, it IS actionable by an administrator, and it must keep saying so.
    """
    from backend.llm import telemetry

    assert telemetry.LABELS[telemetry.DEGRADED] == "AI DEGRADED"
    assert telemetry.LABELS[telemetry.DEGRADED] != telemetry.LABELS[
        telemetry.OFFLINE]


def test_a_provider_without_a_key_is_not_configured():
    assert AnthropicProvider(api_key="").configured is False
    assert AnthropicProvider(api_key="").status().state == "offline"


def test_the_status_never_carries_the_key():
    """It is rendered on a screen a user can screenshot."""
    secret = "sk-ant-do-not-leak-me"
    status = AnthropicProvider(api_key=secret).status()
    assert secret not in str(status.to_dict())


# ------------------------------------------------------------ structured call


def test_a_tool_call_is_the_answer():
    client = _Client(_tool_reply({"intent": "ANALYSIS"}))
    provider = AnthropicProvider(api_key="k", client=client)
    result = provider.structured(system="s", prompt="p", schema=SCHEMA,
                                 tool_name="plan", tool_description="d")
    assert result.data == {"intent": "ANALYSIS"}
    assert result.input_tokens == 120 and result.output_tokens == 45
    assert result.attempts == 1


def test_the_model_is_forced_through_the_tool():
    """Left to choose, it sometimes explains its plan instead of emitting one."""
    client = _Client(_tool_reply({"intent": "ANALYSIS"}))
    AnthropicProvider(api_key="k", client=client).structured(
        system="s", prompt="p", schema=SCHEMA, tool_name="plan",
        tool_description="d")
    call = client.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "plan"}
    assert call["tools"][0]["input_schema"] == SCHEMA


def test_prose_is_an_error_rather_than_something_to_salvage():
    """A plausible object with a misspelled key silently loses a filter, and the
    analysis then answers a slightly different question with confidence."""
    client = _Client(_prose_reply("I would group by sector and sum EAD."),
                     _prose_reply("Again in prose."),
                     _prose_reply("And again."))
    with pytest.raises(LLMError, match="prose"):
        AnthropicProvider(api_key="k", client=client).structured(
            system="s", prompt="p", schema=SCHEMA, tool_name="plan",
            tool_description="d")


def test_prose_once_then_a_tool_call_succeeds():
    client = _Client(_prose_reply("thinking out loud"),
                     _tool_reply({"intent": "DATA_DISCOVERY"}))
    result = AnthropicProvider(api_key="k", client=client).structured(
        system="s", prompt="p", schema=SCHEMA, tool_name="plan",
        tool_description="d")
    assert result.data["intent"] == "DATA_DISCOVERY"
    assert result.attempts == 2


def test_a_transport_failure_is_retried():
    client = _Client(_Timeout("timed out"), _tool_reply({"intent": "ANALYSIS"}))
    result = AnthropicProvider(api_key="k", client=client).structured(
        system="s", prompt="p", schema=SCHEMA, tool_name="plan",
        tool_description="d")
    assert result.attempts == 2


def test_retrying_stops_rather_than_hammering():
    client = _Client(*[_Timeout("nope")] * (MAX_ATTEMPTS + 3))
    with pytest.raises(LLMError):
        AnthropicProvider(api_key="k", client=client).structured(
            system="s", prompt="p", schema=SCHEMA, tool_name="plan",
            tool_description="d")
    assert len(client.calls) == MAX_ATTEMPTS


def test_a_refusal_is_not_retried():
    """Retrying a permanent error turns one clear failure into three slow ones."""

    class _BadKey(Exception):
        pass

    _BadKey.__name__ = "AuthenticationError"
    client = _Client(*[_BadKey("invalid x-api-key")] * 3)
    with pytest.raises(LLMError):
        AnthropicProvider(api_key="k", client=client).structured(
            system="s", prompt="p", schema=SCHEMA, tool_name="plan",
            tool_description="d")
    assert len(client.calls) == 1


def test_a_non_object_answer_is_refused():
    client = _Client(_Message([_Block("tool_use", name="plan", input=["a"])]))
    with pytest.raises(LLMError, match="rather than an object"):
        AnthropicProvider(api_key="k", client=client).structured(
            system="s", prompt="p", schema=SCHEMA, tool_name="plan",
            tool_description="d")


def test_a_json_string_argument_is_parsed():
    client = _Client(_Message([_Block("tool_use", name="plan",
                                      input='{"intent": "ANALYSIS"}')]))
    result = AnthropicProvider(api_key="k", client=client).structured(
        system="s", prompt="p", schema=SCHEMA, tool_name="plan",
        tool_description="d")
    assert result.data["intent"] == "ANALYSIS"


def test_the_model_is_pinned_not_an_alias():
    """A provider-side change to what 'latest' means must not alter how
    CreditProbe reads a question without a release."""
    from backend.llm.anthropic_provider import DEFAULT_MODEL

    assert "latest" not in DEFAULT_MODEL
    assert DEFAULT_MODEL.count("-") >= 3


# -------------------------------------------------------------- selection


def test_offline_is_selectable_even_with_a_key(monkeypatch):
    """A bank that wants the deterministic path must be able to have it."""
    import dataclasses

    from backend import llm
    from backend.config import settings

    monkeypatch.setattr(llm, "settings", dataclasses.replace(
        settings, ai_provider="offline", anthropic_api_key="sk-present"))
    provider = llm.get_provider(refresh=True)
    assert provider.configured is False
    llm.get_provider(refresh=True)


def test_an_unknown_provider_degrades_rather_than_crashing(monkeypatch):
    import dataclasses

    from backend import llm
    from backend.config import settings

    monkeypatch.setattr(llm, "settings", dataclasses.replace(
        settings, ai_provider="mystery", anthropic_api_key="sk-present"))
    assert llm.get_provider(refresh=True).configured is False
    llm.get_provider(refresh=True)
