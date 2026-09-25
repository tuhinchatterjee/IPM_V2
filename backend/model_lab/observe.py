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
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

Sink = Callable[[dict[str, Any]], None]

_USAGE = ("input_tokens", "output_tokens", "cache_read_tokens",
          "cache_write_tokens")


class _Observed:
    def __init__(self, inner: Any, sink: Sink, *, clock=time.monotonic,
                 wall=time.time) -> None:
        self._inner = inner
        self._sink = sink
        self._clock = clock
        self._wall = wall
        self._seq = 0

    def __getattr__(self, name: str) -> Any:     # anything else: the inner's
        return getattr(self._inner, name)

    def converse(self, **kwargs: Any) -> Any:
        self._seq += 1
        call_id = f"call-{uuid.uuid4().hex[:12]}"
        start_wall = self._wall()
        start = self._clock()
        try:
            result = self._inner.converse(**kwargs)
        except BaseException as exc:
            end = self._clock()
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
        })
        return result

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
