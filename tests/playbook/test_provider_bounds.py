"""A provider call that can never hang, and never runs without a model.

Both failures here were found by the first real live run, and neither could
have been found without one:

* the suite hung inside the streaming iterator until somebody pressed Ctrl+C;
* an earlier run reached the SDK with no model and died on
  `Messages.stream() missing 1 required keyword-only argument: 'model'`.

The client is faked at the transport, not at `provider.author`, because the
bug was in the transport. `_Timeout.__name__` is set to the SDK's class name
for the same reason `tests/llm/test_provider.py` does it: `telemetry.classify`
keys on the exception's class name, so this is what makes a fake read as a
real timeout.
"""

from __future__ import annotations

import time

import pytest

from backend.playbook import provider


class _Timeout(Exception):
    """Stands in for anthropic.APITimeoutError."""


_Timeout.__name__ = "APITimeoutError"


class _Delta:
    def __init__(self, text):
        self.type = "text_delta"
        self.text = text


class _Event:
    def __init__(self, text):
        self.type = "content_block_delta"
        self.delta = _Delta(text)


class _Message:
    def __init__(self):
        self.content = [type("B", (), {"type": "text", "text": "done"})()]
        self.stop_reason = "end_turn"
        self.model = "test-model"
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
        self.container = None
        self._request_id = "req_test"


class _Stream:
    """A stream that yields what the test says, as slowly as it says."""

    def __init__(self, events, *, pause=0.0, raises=None):
        self.events, self.pause, self.raises = events, pause, raises
        self.request_id = "req_test"
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def __iter__(self):
        for event in self.events:
            if self.pause:
                time.sleep(self.pause)
            yield event
        if self.raises:
            raise self.raises

    def get_final_message(self):
        return _Message()


class _Client:
    def __init__(self, stream):
        self._stream = stream
        self.beta = type("Beta", (), {"messages": self})()
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return self._stream


@pytest.fixture
def instant_deadline(monkeypatch):
    """A deadline that has already passed, so nothing waits in a test."""
    monkeypatch.setattr(provider, "RUN_DEADLINE_SECONDS", 0.05)


class TestTheTransportIsBoundedInEveryPhase:
    def test_the_four_phases_are_set_separately(self, monkeypatch):
        """The bug: a bare float sets connect, read, write and pool to the
        same number, which shipped a 900-second CONNECT timeout."""
        import httpx

        captured = {}

        class _Anthropic:
            def __init__(self, **kw):
                captured.update(kw)

        monkeypatch.setattr(provider, "status",
                            lambda: provider.Status(True, "", "anthropic", "m"))
        monkeypatch.setitem(__import__("sys").modules, "anthropic",
                            type("M", (), {"Anthropic": _Anthropic}))
        provider._client()

        timeout = captured["timeout"]
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.connect == provider.CONNECT_TIMEOUT_SECONDS
        assert timeout.read == provider.READ_TIMEOUT_SECONDS
        assert timeout.write == provider.WRITE_TIMEOUT_SECONDS
        assert timeout.pool == provider.POOL_TIMEOUT_SECONDS
        assert timeout.connect != timeout.read, "a bare float again"

    def test_the_sdk_does_not_retry_behind_our_back(self, monkeypatch):
        captured = {}

        class _Anthropic:
            def __init__(self, **kw):
                captured.update(kw)

        monkeypatch.setattr(provider, "status",
                            lambda: provider.Status(True, "", "anthropic", "m"))
        monkeypatch.setitem(__import__("sys").modules, "anthropic",
                            type("M", (), {"Anthropic": _Anthropic}))
        provider._client()
        assert captured["max_retries"] == 0

    def test_the_run_deadline_is_below_the_readers_idle_timeout(self):
        """So the worker always reports the failure before the browser's
        reader gives up on it and invents its own explanation."""
        from backend.playbook import stream

        assert provider.RUN_DEADLINE_SECONDS < stream.IDLE_TIMEOUT_SECONDS


class TestAStalledStreamIsStopped:
    def test_a_stream_that_stalls_before_the_first_token_times_out(
            self, instant_deadline):
        """A read timeout cannot catch this on its own: the deadline is what
        bounds the operation rather than the gap between reads."""
        client = _Client(_Stream([_Event("x")], pause=0.2))
        with pytest.raises(provider.AuthoringTimeout) as exc:
            provider._stream_once(client, {}, on_delta=None,
                                  is_cancelled=None,
                                  deadline=time.monotonic() - 10)
        assert "was stopped" in str(exc.value)

    def test_a_stream_that_stalls_mid_response_times_out(self, monkeypatch):
        """Text is delivered, then the stream drags on past the deadline. The
        partial text has already reached the caller; what must not happen is
        the run continuing for ever behind it."""
        monkeypatch.setattr(provider, "RUN_DEADLINE_SECONDS", 0.25)
        seen = []
        client = _Client(_Stream(
            [_Event("The weighted "), _Event("ECL "), _Event("rose "),
             _Event("to "), _Event("SAR "), _Event("22.77 "),
             _Event("million.")],
            pause=0.06))
        with pytest.raises(provider.AuthoringTimeout):
            provider._stream_once(client, {}, on_delta=seen.append,
                                  is_cancelled=None,
                                  deadline=time.monotonic())
        assert seen, "it stopped before delivering anything at all"
        assert len(seen) < 7, "it ran to completion instead of timing out"

    def test_the_connection_is_released_when_it_times_out(self,
                                                          instant_deadline):
        stream = _Stream([_Event("x")], pause=0.2)
        client = _Client(stream)
        with pytest.raises(provider.AuthoringTimeout):
            provider._stream_once(client, {}, on_delta=None, is_cancelled=None,
                                  deadline=time.monotonic() - 10)
        assert stream.closed, "a timed-out stream must not hold the socket"

    def test_a_timeout_names_what_it_was_doing(self, monkeypatch):
        monkeypatch.setattr(provider, "RUN_DEADLINE_SECONDS", 0.0)
        with pytest.raises(provider.AuthoringTimeout) as exc:
            provider._check_clock(time.monotonic(), "building the files")
        assert "building the files" in str(exc.value)
        assert "previous version is unchanged" in str(exc.value)
        assert "elapsed" in str(exc.value), "it must report what it measured"

    def test_a_run_inside_its_deadline_is_left_alone(self):
        provider._check_clock(time.monotonic(), "writing")  # does not raise

    def test_a_zero_origin_is_treated_as_unset_not_as_the_epoch(self):
        """The telemetry defect, pinned.

        0.0 is falsy but not None, so a `started is None` guard let it through
        and the clock then measured `time.monotonic()` itself — container
        uptime. Any process older than the deadline was declared timed out on
        its first event, and the "latency" reported was the age of the process.
        That is the shape of the 1636923 ms recorded against a 281s attempt.
        """
        provider._check_clock(0.0, "writing")     # must not raise
        provider._check_clock(None, "writing")    # must not raise
        provider._check_clock(-5.0, "writing")    # nor a nonsense origin


class TestATimeoutIsNeverRetriedAutomatically:
    def test_the_deadline_error_is_not_retried(self, instant_deadline):
        """Retrying a run that is already out of time spends the tokens again
        for a generation nobody is waiting for."""
        client = _Client(_Stream([_Event("x")], pause=0.2))
        with pytest.raises(provider.AuthoringTimeout):
            provider._call(client, model="m", system="s", messages=[],
                           tools=[], container={}, purpose="test",
                           role=type("R", (), {"effort": ""})(),
                           deadline=time.monotonic() - 10)
        assert len(client.calls) == 1, "it tried again after timing out"

    def test_a_socket_timeout_is_not_retried_either(self):
        client = _Client(_Stream([], raises=_Timeout("read timed out")))
        with pytest.raises(provider.AuthoringError) as exc:
            provider._call(client, model="m", system="s", messages=[],
                           tools=[], container={}, purpose="test",
                           role=type("R", (), {"effort": ""})())
        assert exc.value.category == "timeout"
        assert len(client.calls) == 1

    def test_a_connection_failure_is_still_retried(self):
        """It fires before any token is spent, so trying again is free."""
        class _ConnError(Exception):
            pass
        _ConnError.__name__ = "APIConnectionError"

        client = _Client(_Stream([], raises=_ConnError("no route")))
        with pytest.raises(provider.AuthoringError):
            provider._call(client, model="m", system="s", messages=[],
                           tools=[], container={}, purpose="test",
                           role=type("R", (), {"effort": ""})())
        assert len(client.calls) == provider.MAX_ATTEMPTS

    def test_the_timeout_message_carries_no_secret(self):
        message = provider._message_for("timeout", _Timeout("boom"))
        assert "sk-ant" not in message
        assert "did not respond in time" in message

    def test_a_connection_failure_has_a_sentence_of_its_own(self):
        """It used to fall through to raw SDK text."""
        message = provider._message_for("connection", RuntimeError("boom"))
        assert "could not reach the provider" in message


class TestAuthorRefusesWithoutAModel:
    def test_it_fails_before_the_sdk_is_ever_called(self, monkeypatch):
        """The SDK's own error — missing keyword argument 'model' — is a stack
        trace, not something an administrator can act on."""
        monkeypatch.setattr(provider.role_config, "role",
                            lambda name: provider.role_config.Role(
                                name="author", model="", effort=""))

        def _no(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("the client was built without a model")

        monkeypatch.setattr(provider, "_client", _no)
        with pytest.raises(provider.ProviderNotConfigured) as exc:
            provider.author(system="s", messages=[], formats=["docx"])
        assert "AUTHOR_MODEL_NOT_CONFIGURED" in str(exc.value)
        assert "AI_AUTHOR_MODEL" in str(exc.value)

    def test_the_status_says_so_rather_than_reporting_configured(
            self, monkeypatch):
        import dataclasses

        from backend.config import settings as real

        monkeypatch.setattr(provider, "role_config", provider.role_config)
        monkeypatch.setattr(
            "backend.config.settings",
            dataclasses.replace(real, ai_provider="anthropic",
                                anthropic_api_key="sk-ant-test", ai_model=""))
        monkeypatch.setattr(provider.role_config, "role",
                            lambda name: provider.role_config.Role(
                                name="author", model="", effort=""))
        state = provider.status()
        assert state.configured is False
        assert "AUTHOR_MODEL_NOT_CONFIGURED" in state.reason
        assert "sk-ant" not in state.reason

    def test_a_configured_model_still_reports_configured(self, monkeypatch):
        import dataclasses

        from backend.config import settings as real

        monkeypatch.setattr(
            "backend.config.settings",
            dataclasses.replace(real, ai_provider="anthropic",
                                anthropic_api_key="sk-ant-test"))
        monkeypatch.setattr(provider.role_config, "role",
                            lambda name: provider.role_config.Role(
                                name="author", model="claude-test", effort=""))
        assert provider.status().configured is True
