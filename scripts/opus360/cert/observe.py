"""
Pass-through observation of every model call. Changes nothing it observes.

Three observers, from the outside in:

* `ObservingProvider` wraps the provider object the frozen runtime is given.
  `converse` and `count_tokens` are forwarded with identical arguments and
  the identical result object is returned. It records timing, the request
  payload (for token decomposition) and the native usage the adapter read.
* `install_sdk_shims()` wraps `anthropic.resources.messages.Messages.create`
  and `.count_tokens`, and `httpx.Client.send`, as pass-throughs. They exist
  because the frozen adapter discards the served model id (it reports the
  requested one) and because the SDK's internal retries are invisible to the
  product (see docs/opus360/STATIC_FINDINGS.md, S-02 and S-03).

Nothing here decides anything about a run. A recorder failure is swallowed
and counted (`observer_errors`) so that observation can never change what the
system under test does; the count is reported, never hidden.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UNKNOWN = "UNKNOWN"


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def to_jsonable(obj: Any) -> Any:
    """SDK objects -> plain JSON (model_dump), everything else best-effort."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return to_jsonable(dump())
        except Exception:  # noqa: BLE001
            pass
    return str(obj)


def digest(obj: Any) -> str:
    raw = json.dumps(to_jsonable(obj), sort_keys=True, ensure_ascii=False,
                     default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass
class CallRecord:
    """One provider round trip as seen from outside the frozen code."""

    seq: int
    kind: str                      # "converse" | "count_tokens"
    started_at: str
    started_mono: float
    thread: str
    purpose: str = ""
    requested_model: str = ""
    max_tokens: int | None = None
    tool_choice: str = ""
    tools_exposed: int = 0
    tool_names: list[str] = field(default_factory=list)
    effort: str = ""
    finished_at: str = ""
    finished_mono: float = 0.0
    elapsed_ms: int = 0
    status: str = "pending"        # ok | error
    error_class: str = ""
    error_text: str = ""
    # native usage as returned by the adapter (authoritative)
    input_tokens: Any = UNKNOWN
    output_tokens: Any = UNKNOWN
    cache_read_tokens: Any = UNKNOWN
    cache_write_tokens: Any = UNKNOWN
    reasoning_tokens: Any = UNKNOWN
    stop_reason: str = ""
    adapter_model: str = ""
    request_id: str = ""
    # from the SDK shim (the served model and the raw usage)
    served_model: str = UNKNOWN
    sdk_usage: dict[str, Any] = field(default_factory=dict)
    sdk_message_id: str = ""
    # from the httpx shim
    http_attempts: list[dict[str, Any]] = field(default_factory=list)
    counted_tokens: Any = UNKNOWN  # count_tokens result
    payload_digest: str = ""
    payload_path: str = ""
    response_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    response_text_chars: int = 0
    context_bytes: dict[str, int] = field(default_factory=dict)

    @property
    def http_ms(self) -> int:
        return int(sum(a.get("elapsed_ms", 0) for a in self.http_attempts))

    @property
    def provider_retries(self) -> int:
        return max(0, len(self.http_attempts) - 1)

    @property
    def rate_limit_events(self) -> int:
        return sum(1 for a in self.http_attempts if a.get("status") == 429)

    def to_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items()
               if k not in ("started_mono", "finished_mono")}
        out["http_ms"] = self.http_ms if self.http_attempts else UNKNOWN
        out["local_ms"] = (self.elapsed_ms - self.http_ms
                           if self.http_attempts else UNKNOWN)
        out["provider_retries"] = self.provider_retries
        out["rate_limit_events"] = self.rate_limit_events
        if all(isinstance(x, int) for x in (self.input_tokens,
                                            self.output_tokens)):
            out["total_tokens"] = int(self.input_tokens) + int(self.output_tokens)
        else:
            out["total_tokens"] = UNKNOWN
        return out


class Recorder:
    """Thread-safe store of CallRecords, with a thread-local active call."""

    def __init__(self, payload_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._calls: list[CallRecord] = []
        self._local = threading.local()
        self.payload_dir = payload_dir
        self.observer_errors = 0
        self.observer_error_notes: list[str] = []

    # -- bookkeeping -----------------------------------------------------
    def _note_error(self, where: str, exc: BaseException) -> None:
        with self._lock:
            self.observer_errors += 1
            if len(self.observer_error_notes) < 50:
                self.observer_error_notes.append(f"{where}: {type(exc).__name__}: {exc}"[:300])

    def begin(self, kind: str, **fields: Any) -> CallRecord:
        with self._lock:
            rec = CallRecord(seq=len(self._calls) + 1, kind=kind,
                             started_at=utcnow(), started_mono=time.monotonic(),
                             thread=threading.current_thread().name, **fields)
            self._calls.append(rec)
        self._local.active = rec
        return rec

    def end(self, rec: CallRecord) -> None:
        rec.finished_mono = time.monotonic()
        rec.finished_at = utcnow()
        rec.elapsed_ms = int((rec.finished_mono - rec.started_mono) * 1000)
        if getattr(self._local, "active", None) is rec:
            self._local.active = None

    def active(self) -> CallRecord | None:
        return getattr(self._local, "active", None)

    def calls(self) -> list[CallRecord]:
        with self._lock:
            return list(self._calls)

    def calls_between(self, start_mono: float, end_mono: float) -> list[CallRecord]:
        return [c for c in self.calls()
                if c.started_mono >= start_mono - 0.001
                and c.started_mono <= end_mono + 0.001]

    def save_payload(self, rec: CallRecord, payload: dict[str, Any]) -> None:
        try:
            jsonable = to_jsonable(payload)
            rec.payload_digest = digest(jsonable)
            rec.context_bytes = payload_bytes(jsonable)
            if self.payload_dir is not None:
                self.payload_dir.mkdir(parents=True, exist_ok=True)
                path = self.payload_dir / f"call-{rec.seq:06d}-{rec.payload_digest[:12]}.json.gz"
                with gzip.open(path, "wt", encoding="utf-8") as fh:
                    json.dump(jsonable, fh, ensure_ascii=False)
                rec.payload_path = str(path)
        except Exception as exc:  # noqa: BLE001
            self._note_error("save_payload", exc)


def payload_bytes(payload: dict[str, Any]) -> dict[str, int]:
    def size(obj: Any) -> int:
        if isinstance(obj, str):
            return len(obj.encode("utf-8"))
        return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))
    s, t, m = (size(payload.get("system") or []), size(payload.get("tools") or []),
               size(payload.get("messages") or []))
    return {"system": s, "tools": t, "messages": m, "total": s + t + m}


class ObservingProvider:
    """Forward everything to the real provider; record, never alter."""

    def __init__(self, inner: Any, recorder: Recorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def converse(self, **kwargs: Any) -> Any:
        rec = None
        try:
            tools = kwargs.get("tools") or []
            choice = kwargs.get("tool_choice")
            config = kwargs.get("output_config") or {}
            rec = self._recorder.begin(
                "converse", purpose=str(kwargs.get("purpose") or ""),
                requested_model=str(kwargs.get("model") or ""),
                max_tokens=kwargs.get("max_tokens"),
                tool_choice=(json.dumps(choice, sort_keys=True) if choice else "auto"),
                tools_exposed=len(tools),
                tool_names=[str(t.get("name") or "") for t in tools if isinstance(t, dict)],
                effort=str(config.get("effort") or "") if isinstance(config, dict) else "")
            self._recorder.save_payload(rec, {"system": kwargs.get("system"),
                                              "messages": kwargs.get("messages"),
                                              "tools": tools})
        except Exception as exc:  # noqa: BLE001
            self._recorder._note_error("converse.begin", exc)
        try:
            result = self._inner.converse(**kwargs)
        except BaseException as exc:
            if rec is not None:
                try:
                    rec.status = "error"
                    rec.error_class = type(exc).__name__
                    rec.error_text = _sanitize(str(exc))[:400]
                    self._recorder.end(rec)
                except Exception as note:  # noqa: BLE001
                    self._recorder._note_error("converse.error", note)
            raise
        if rec is not None:
            try:
                rec.status = "ok"
                for name in ("input_tokens", "output_tokens",
                             "cache_read_tokens", "cache_write_tokens"):
                    value = getattr(result, name, None)
                    setattr(rec, name, int(value) if isinstance(value, (int, float)) else UNKNOWN)
                rec.stop_reason = str(getattr(result, "stop_reason", "") or "")
                rec.adapter_model = str(getattr(result, "model", "") or "")
                rec.request_id = str(getattr(result, "request_id", "") or "")
                rec.response_tool_calls = [
                    {"id": str(c.get("id") or ""), "name": str(c.get("name") or ""),
                     "input": to_jsonable(c.get("input"))}
                    for c in (getattr(result, "tool_calls", None) or []) if isinstance(c, dict)]
                rec.response_text_chars = len(str(getattr(result, "text", "") or ""))
                self._recorder.end(rec)
            except Exception as exc:  # noqa: BLE001
                self._recorder._note_error("converse.end", exc)
        return result

    def count_tokens(self, **kwargs: Any) -> Any:
        rec = None
        try:
            rec = self._recorder.begin("count_tokens",
                                       requested_model=str(kwargs.get("model") or ""),
                                       tools_exposed=len(kwargs.get("tools") or []))
        except Exception as exc:  # noqa: BLE001
            self._recorder._note_error("count.begin", exc)
        try:
            value = self._inner.count_tokens(**kwargs)
        except BaseException as exc:
            if rec is not None:
                rec.status = "error"
                rec.error_class = type(exc).__name__
                rec.error_text = _sanitize(str(exc))[:400]
                self._recorder.end(rec)
            raise
        if rec is not None:
            rec.status = "ok"
            rec.counted_tokens = int(value) if isinstance(value, (int, float)) else UNKNOWN
            self._recorder.end(rec)
        return value


# ---- SDK and transport shims ---------------------------------------------

_SHIMS: dict[str, Any] = {}
_SHIM_LOCK = threading.Lock()
_RECORDER_FOR_SHIMS: list[Recorder] = []


def _current() -> CallRecord | None:
    return _RECORDER_FOR_SHIMS[0].active() if _RECORDER_FOR_SHIMS else None


def install_sdk_shims(recorder: Recorder) -> dict[str, bool]:
    """Idempotent. Returns which shims were installed."""
    with _SHIM_LOCK:
        _RECORDER_FOR_SHIMS[:] = [recorder]
        installed = {"messages.create": False, "httpx.send": False}
        try:
            from anthropic.resources.messages import Messages

            if "create" not in _SHIMS:
                original = Messages.create
                _SHIMS["create"] = original

                def create(self, *args, **kwargs):  # noqa: ANN001
                    message = original(self, *args, **kwargs)
                    try:
                        rec = _current()
                        if rec is not None:
                            rec.served_model = str(getattr(message, "model", "") or UNKNOWN)
                            rec.sdk_message_id = str(getattr(message, "id", "") or "")
                            usage = getattr(message, "usage", None)
                            rec.sdk_usage = to_jsonable(usage) if usage is not None else {}
                            if isinstance(rec.sdk_usage, dict):
                                for key in ("reasoning_tokens", "thinking_tokens"):
                                    if isinstance(rec.sdk_usage.get(key), int):
                                        rec.reasoning_tokens = rec.sdk_usage[key]
                    except Exception as exc:  # noqa: BLE001
                        recorder._note_error("sdk.create", exc)
                    return message

                create.__wrapped__ = original  # type: ignore[attr-defined]
                Messages.create = create  # type: ignore[method-assign]
            installed["messages.create"] = True
        except Exception as exc:  # noqa: BLE001
            recorder._note_error("install.create", exc)
        try:
            import httpx

            if "send" not in _SHIMS:
                original_send = httpx.Client.send
                _SHIMS["send"] = original_send

                def send(self, request, *args, **kwargs):  # noqa: ANN001
                    host = str(getattr(request.url, "host", "") or "")
                    watch = "anthropic" in host
                    started = time.monotonic()
                    try:
                        response = original_send(self, request, *args, **kwargs)
                    except BaseException as exc:
                        if watch:
                            _note_attempt(request, None, started, exc)
                        raise
                    if watch:
                        _note_attempt(request, response, started, None)
                    return response

                send.__wrapped__ = original_send  # type: ignore[attr-defined]
                httpx.Client.send = send  # type: ignore[method-assign]
            installed["httpx.send"] = True
        except Exception as exc:  # noqa: BLE001
            recorder._note_error("install.httpx", exc)
        return installed


def _note_attempt(request: Any, response: Any, started: float,
                  exc: BaseException | None) -> None:
    try:
        rec = _current()
        if rec is None:
            return
        entry: dict[str, Any] = {
            "path": str(getattr(request.url, "path", "")),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "at": utcnow(),
        }
        if response is not None:
            headers = getattr(response, "headers", {}) or {}
            entry.update(status=int(getattr(response, "status_code", 0) or 0),
                         request_id=str(headers.get("request-id", "") or ""),
                         retry_after=str(headers.get("retry-after", "") or ""),
                         should_retry=str(headers.get("x-should-retry", "") or ""))
        else:
            entry.update(status=0, error=type(exc).__name__ if exc else "")
        rec.http_attempts.append(entry)
    except Exception as note:  # noqa: BLE001
        if _RECORDER_FOR_SHIMS:
            _RECORDER_FOR_SHIMS[0]._note_error("httpx.attempt", note)


def uninstall_sdk_shims() -> None:
    with _SHIM_LOCK:
        try:
            from anthropic.resources.messages import Messages

            if "create" in _SHIMS:
                Messages.create = _SHIMS.pop("create")  # type: ignore[method-assign]
        except Exception:  # noqa: BLE001
            pass
        try:
            import httpx

            if "send" in _SHIMS:
                httpx.Client.send = _SHIMS.pop("send")  # type: ignore[method-assign]
        except Exception:  # noqa: BLE001
            pass
        _RECORDER_FOR_SHIMS.clear()


def _sanitize(text: str) -> str:
    from cert.safe_io import redact

    return redact(text)
