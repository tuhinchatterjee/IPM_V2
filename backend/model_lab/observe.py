"""
Passive observation at the existing provider seam.

`observe(provider, sink)` returns an object the frozen `Analyst` cannot tell
apart from `provider`: every keyword argument is forwarded unchanged, the
inner result object is returned as-is (not a copy), and exceptions propagate
untouched. The only addition is a record appended to `sink` AFTER the inner
call has returned or raised.

`count_tokens` is exposed only if the inner provider has it, because the
frozen engine probes for it with `getattr` and would change its token
accounting if a wrapper invented one (OG-04). The record is built from
attributes the frozen engine itself reads; nothing here parses prose.

With a `trace_sink` (the lab's full model I/O trace), the engine request is
serialised BEFORE the call -- a copy, so later history appends cannot alter
it, taken before the clock starts so timing is unaffected -- and the wire
exchanges recorded by the provider's `RecordingTransport` plus the normalised
result are serialised AFTER it. Hidden reasoning is replaced by markers and
credentials never enter the record (see `io_trace.py`).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

Sink = Callable[[dict[str, Any]], None]

_USAGE = ("input_tokens", "output_tokens", "cache_read_tokens",
          "cache_write_tokens")


class _Observed:
    def __init__(self, inner: Any, sink: Sink, *, clock=time.monotonic,
                 wall=time.time, trace_sink: Sink | None = None,
                 recorder: Any = None,
                 trace_context: dict[str, Any] | None = None) -> None:
        self._inner = inner
        self._sink = sink
        self._clock = clock
        self._wall = wall
        self._seq = 0
        self._trace_sink = trace_sink
        self._recorder = recorder
        self._trace_context = trace_context or {}

    def __getattr__(self, name: str) -> Any:     # anything else: the inner's
        return getattr(self._inner, name)

    def converse(self, **kwargs: Any) -> Any:
        self._seq += 1
        call_id = f"call-{uuid.uuid4().hex[:12]}"
        engine = self._snapshot(kwargs) if self._trace_sink else None
        mark = self._recorder.mark() if (self._trace_sink and
                                         self._recorder) else 0
        start_wall = self._wall()
        start = self._clock()
        try:
            result = self._inner.converse(**kwargs)
        except BaseException as exc:
            end = self._clock()
            if self._trace_sink:
                self._trace(call_id, start_wall, (end - start) * 1000.0,
                            engine, mark, None, exc)
            self._emit({"call_id": call_id, "seq": self._seq,
                        "kind": "converse", "status": "error",
                        "start_monotonic": start, "end_monotonic": end,
                        "wall_time": start_wall,
                        "duration_ms": (end - start) * 1000.0,
                        "purpose": kwargs.get("purpose", ""),
                        "requested_model": kwargs.get("model", ""),
                        "max_tokens": kwargs.get("max_tokens"),
                        "tool_choice": kwargs.get("tool_choice"),
                        "error_type": type(exc).__name__,
                        "error_code": getattr(exc, "code", ""),
                        "error": str(exc)[:300]})
            raise
        end = self._clock()
        native = getattr(result, "native_usage", None)
        timing = getattr(result, "native_timing", None)
        self._emit({
            "call_id": call_id, "seq": self._seq, "kind": "converse",
            "status": "ok", "start_monotonic": start, "end_monotonic": end,
            "wall_time": start_wall, "duration_ms": (end - start) * 1000.0,
            "purpose": kwargs.get("purpose", ""),
            "requested_model": kwargs.get("model", ""),
            "resolved_model": str(getattr(result, "model", "") or ""),
            "max_tokens": kwargs.get("max_tokens"),
            "tool_choice": kwargs.get("tool_choice"),
            "stop_reason": str(getattr(result, "stop_reason", "") or ""),
            "tool_names": [c.get("name") for c in
                           (getattr(result, "tool_calls", None) or [])
                           if isinstance(c, dict)],
            "text_chars": len(str(getattr(result, "text", "") or "")),
            "usage": {k: getattr(result, k, None) for k in _USAGE},
            "native_usage": native, "native_timing": timing,
            "first_protocol_event_ms": getattr(
                result, "first_protocol_event_ms", None),
            "first_visible_text_ms": getattr(
                result, "first_visible_text_ms", None),
            "first_complete_tool_ms": getattr(
                result, "first_complete_tool_ms", None),
            "request_id": str(getattr(result, "request_id", "") or ""),
            "request_controls": getattr(result, "request_controls", None),
            "reasoning_chars": getattr(result, "reasoning_chars", None),
        })
        if self._trace_sink:
            self._trace(call_id, start_wall, (end - start) * 1000.0, engine,
                        mark, result, None)
        return result

    # -- full model I/O trace (lab-only; observation, never behaviour) -----
    def _snapshot(self, kwargs: dict[str, Any]) -> Any:
        try:
            from backend.model_lab import io_trace
            text = json.dumps(io_trace.redact_reasoning(
                io_trace.to_jsonable(kwargs)), default=str)
            return {"captured_at": self._wall(), "json": text}
        except Exception as exc:  # noqa: BLE001 - telemetry never gates
            return {"capture_error": f"{type(exc).__name__}: {exc}"[:300]}

    def _assistance(self) -> dict[str, Any] | None:
        rec = getattr(self._inner, "assistance_record", None)
        if not rec:
            return None
        return {"lane": "ASSISTED_V1", "applied": True,
                "delivery": rec["delivery"], "bytes": rec["bytes"],
                "sha256": rec["sha256"],
                "appended_system_block": rec["rendered_text"]}

    def _trace(self, call_id: str, wall: float, duration_ms: float,
               engine: Any, mark: int, result: Any,
               exc: BaseException | None) -> None:
        try:
            from backend.model_lab import io_trace

            secrets = io_trace.secret_values()
            exchanges = (self._recorder.since(mark) if self._recorder
                         else [])
            wire = [io_trace.exchange_view(x, secrets) for x in exchanges]
            if result is not None:
                normalized = io_trace.redact_reasoning(
                    io_trace.to_jsonable(result))
            else:
                normalized = None
            if self._recorder is None:
                dispatch = "IN_PROCESS_NO_NETWORK"
            elif wire:
                dispatch = "SENT"
            else:
                dispatch = "NOT_SENT"
            error = None
            if exc is not None:
                error = {"type": type(exc).__name__,
                         "code": getattr(exc, "code", "") or "",
                         "retry_class": getattr(exc, "retry_class", ""),
                         "message": str(exc)[:2000],
                         "detail": io_trace.to_jsonable(
                             getattr(exc, "detail", None))}
            engine_json = (json.loads(engine["json"]) if engine and
                           "json" in engine else engine)
            record = {
                "call_id": call_id, "seq": self._seq, "wall_time": wall,
                "duration_ms": duration_ms,
                "dispatch_status": dispatch,
                "dispatch_reason": ("" if dispatch != "NOT_SENT" else
                                    "the adapter raised before any HTTP "
                                    "request left the process"),
                "context": self._trace_context,
                "engine_request": engine_json,
                "engine_request_captured_at": (engine or {}).get(
                    "captured_at"),
                "wire_exchanges": wire,
                "normalized_response": normalized,
                "error": error,
                "assistance": self._assistance(),
            }
            text = io_trace.scrub(json.dumps(record, default=str), secrets)
            self._trace_sink(json.loads(text))
        except Exception:  # noqa: BLE001 - telemetry must never gate the run
            pass

    def _emit(self, record: dict[str, Any]) -> None:
        try:
            self._sink(record)
        except Exception:  # noqa: BLE001 - telemetry must never gate the run
            pass


class _ObservedCounting(_Observed):
    def count_tokens(self, **kwargs: Any) -> int:
        start = self._clock()
        try:
            return self._inner.count_tokens(**kwargs)
        finally:
            end = self._clock()
            self._emit({"call_id": f"count-{uuid.uuid4().hex[:12]}",
                        "kind": "count_tokens", "status": "ok",
                        "start_monotonic": start, "end_monotonic": end,
                        "duration_ms": (end - start) * 1000.0})


def observe(provider: Any, sink: Sink, **kw: Any) -> Any:
    cls = (_ObservedCounting if callable(getattr(provider, "count_tokens",
                                                 None)) else _Observed)
    return cls(provider, sink, **kw)
