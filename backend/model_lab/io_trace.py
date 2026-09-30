"""
Full model I/O trace: what crossed the provider boundary, captured passively.

Lab-only observability (MODEL_LAB_FULL_IO_TRACE, on by default). Two capture
points, neither of which can change what is sent or received:

* the ENGINE REQUEST -- the keyword arguments the frozen engine hands the
  provider seam, serialised before the call (see `observe.py`);
* the WIRE -- a `RecordingTransport` wrapped around the httpx transport the
  provider already uses. It forwards the httpx request object untouched and
  returns a response whose byte stream yields exactly the inner stream's
  chunks, recording each one as it passes.

Excluded by construction, and tested:

* credentials -- only an allowlist of headers is kept; URL user-info and query
  strings are dropped; any value of a secret-looking environment variable
  that appears in a recorded body is replaced;
* hidden reasoning -- `thinking` / `redacted_thinking` blocks and `reasoning` /
  `reasoning_content` fields are replaced by a marker with their presence,
  length and SHA-256 (HIDDEN_REASONING_NOT_EXPORTED); the text is never stored.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

ENV_FLAG = "MODEL_LAB_FULL_IO_TRACE"
HIDDEN = "HIDDEN_REASONING_NOT_EXPORTED"
SECRET_MARK = "[REDACTED_SECRET]"

#: Headers that can never carry a credential. Everything else is dropped.
SAFE_REQUEST_HEADERS = frozenset({
    "content-type", "content-length", "accept", "accept-encoding",
    "user-agent", "anthropic-version", "anthropic-beta", "x-stainless-lang",
    "x-stainless-package-version", "x-stainless-runtime",
    "x-stainless-runtime-version", "x-stainless-os", "x-stainless-arch",
    "x-stainless-retry-count", "x-stainless-timeout", "x-stainless-read-timeout"})
SAFE_RESPONSE_HEADERS = frozenset({
    "content-type", "content-length", "date", "request-id", "x-request-id",
    "anthropic-organization-id-present", "retry-after", "server",
    "transfer-encoding", "content-encoding"})

_REASONING_KEYS = ("reasoning", "reasoning_content", "thinking")
_HIDDEN_BLOCK_TYPES = ("thinking", "redacted_thinking")
_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|COOKIE|AUTH)",
                          re.I)


def enabled(env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(ENV_FLAG, "true")).strip().lower() not in (
        "0", "false", "no", "off")


def sha256_text(text: str | bytes) -> str:
    data = text.encode() if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def _marker(value: Any) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return {"field_present": True, "chars": len(text),
            "sha256": sha256_text(text), "reason": HIDDEN}


def redact_reasoning(obj: Any) -> Any:
    """A copy with hidden reasoning replaced by markers. Never mutates."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        hidden_block = obj.get("type") in _HIDDEN_BLOCK_TYPES
        for k, v in obj.items():
            if hidden_block and k in ("thinking", "data", "signature"):
                out[k] = _marker(v)
            elif k in _REASONING_KEYS and isinstance(v, str) and v:
                out[k] = _marker(v)
            else:
                out[k] = redact_reasoning(v)
        return out
    if isinstance(obj, list):
        return [redact_reasoning(v) for v in obj]
    return obj


def to_jsonable(obj: Any) -> Any:
    """SDK objects, dataclasses and plain values as JSON-able data."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return to_jsonable(dump(mode="json", exclude_none=True))
        except Exception:  # noqa: BLE001 - fall through to a safe form
            pass
    if hasattr(obj, "__dict__"):
        return {k: to_jsonable(v) for k, v in vars(obj).items()
                if not k.startswith("_")}
    return repr(obj)


def secret_values(env: dict[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    return sorted({v for k, v in env.items()
                   if _SECRET_NAME.search(k) and v and len(v) >= 8},
                  key=len, reverse=True)


def scrub(text: str, secrets: list[str] | None = None) -> str:
    for s in (secret_values() if secrets is None else secrets):
        if s in text:
            text = text.replace(s, SECRET_MARK)
    return text


def safe_url(url: str) -> str:
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def safe_headers(headers: Any, allow: frozenset[str]) -> dict[str, str]:
    return {k.lower(): v for k, v in dict(headers).items()
            if k.lower() in allow}


# ---- wire capture ----------------------------------------------------------

class _RecordingStream(httpx.SyncByteStream):
    """Yields the inner stream's chunks unchanged, recording each one."""

    def __init__(self, inner: Any, record: dict[str, Any], t0: float) -> None:
        self._inner = inner
        self._rec = record
        self._t0 = t0

    def __iter__(self):
        try:
            for chunk in self._inner:
                self._rec["chunks"].append(
                    ((time.monotonic() - self._t0) * 1000.0, bytes(chunk)))
                yield chunk
            self._rec["complete"] = True
        except BaseException as exc:
            self._rec["stream_error"] = f"{type(exc).__name__}: {exc}"[:500]
            raise

    def close(self) -> None:
        self._rec["closed"] = True
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()


class RecordingTransport(httpx.BaseTransport):
    """Pass-through transport that records each exchange (lab-only)."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.exchanges: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def mark(self) -> int:
        with self._lock:
            return len(self.exchanges)

    def since(self, mark: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.exchanges[mark:])

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        t0 = time.monotonic()
        try:
            body = request.content
        except httpx.RequestNotRead:        # a streamed upload: not ours
            body = b""
        rec: dict[str, Any] = {
            "wall_time": time.time(), "method": request.method,
            "url": safe_url(str(request.url)),
            "request_headers": safe_headers(request.headers,
                                            SAFE_REQUEST_HEADERS),
            "request_body": body, "chunks": [], "complete": False}
        with self._lock:
            self.exchanges.append(rec)
        try:
            resp = self.inner.handle_request(request)
        except BaseException as exc:
            rec["transport_error"] = f"{type(exc).__name__}: {exc}"[:500]
            rec["elapsed_ms"] = (time.monotonic() - t0) * 1000.0
            raise
        rec["status_code"] = resp.status_code
        rec["response_headers"] = safe_headers(resp.headers,
                                               SAFE_RESPONSE_HEADERS)
        rec["headers_ms"] = (time.monotonic() - t0) * 1000.0
        return httpx.Response(status_code=resp.status_code,
                              headers=resp.headers,
                              stream=_RecordingStream(resp.stream, rec, t0),
                              extensions=resp.extensions, request=request)

    def close(self) -> None:
        self.inner.close()


def attach_wire_recorder(provider: Any) -> RecordingTransport | None:
    """Wrap the provider's existing transport; None when there is no wire.

    OpenAI-compatible adapter: its `_transport` (None means httpx's default
    HTTPTransport). Frozen AnthropicProvider: its injectable `client`, built
    exactly as the frozen `_client()` would build it, plus the recording
    transport. A fixture has no network boundary.
    """
    if hasattr(provider, "_transport") and hasattr(provider, "last_request"):
        rec = RecordingTransport(provider._transport or httpx.HTTPTransport())
        provider._transport = rec
        return rec
    if type(provider).__name__ == "AnthropicProvider" and \
            getattr(provider, "client", None) is None and \
            getattr(provider, "configured", False):
        import anthropic

        rec = RecordingTransport(httpx.HTTPTransport())
        provider.client = anthropic.Anthropic(
            api_key=provider.api_key, timeout=provider.timeout,
            http_client=anthropic.DefaultHttpxClient(transport=rec))
        return rec
    return None


# ---- persisted forms -------------------------------------------------------

def _json_or_text(data: bytes) -> tuple[str, Any]:
    text = data.decode("utf-8", errors="replace")
    try:
        return "json", json.loads(text) if text.strip() else None
    except ValueError:
        return "text", text


def _sse_events(chunks: list[tuple[float, bytes]]) -> list[dict[str, Any]]:
    """SSE `data:` events in arrival order, each stamped with the time the
    chunk that completed it arrived. Reasoning is redacted per event."""
    events, buf = [], b""
    for t, chunk in chunks:
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            text = line.decode("utf-8", errors="replace")
            if text.startswith("data:"):
                payload = text[5:].strip()
                if payload == "[DONE]":
                    events.append({"t_ms": round(t, 3), "done": True})
                    continue
                try:
                    data = redact_reasoning(json.loads(payload))
                except ValueError:
                    data = payload
                events.append({"t_ms": round(t, 3), "data": data})
            else:
                events.append({"t_ms": round(t, 3), "line": text})
    if buf.strip():
        events.append({"t_ms": round(chunks[-1][0], 3) if chunks else None,
                       "incomplete_tail": buf.decode("utf-8",
                                                     errors="replace")})
    return events


def assemble_openai_stream(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The provider response the stream adds up to (OpenAI chat shape)."""
    content, calls = "", {}
    out: dict[str, Any] = {"object": "assembled.chat.completion"}
    for e in events:
        d = e.get("data")
        if not isinstance(d, dict):
            continue
        out.setdefault("id", d.get("id"))
        if d.get("model"):
            out["model"] = d["model"]
        if d.get("usage"):
            out["usage"] = d["usage"]
        for ch in d.get("choices") or []:
            delta = ch.get("delta") or {}
            content += delta.get("content") or ""
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {
                    "id": None, "type": "function",
                    "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                slot["function"]["arguments"] += fn.get("arguments") or ""
            if ch.get("finish_reason"):
                out["finish_reason"] = ch["finish_reason"]
    out["message"] = {"role": "assistant", "content": content or None,
                      "tool_calls": [calls[i] for i in sorted(calls)]}
    return out


def exchange_view(ex: dict[str, Any], secrets: list[str]) -> dict[str, Any]:
    """One recorded HTTP exchange, redacted and credential-free."""
    body = ex.get("request_body") or b""
    kind, parsed = _json_or_text(body)
    req = {"method": ex["method"], "url": ex["url"],
           "headers": ex["request_headers"],
           "body_bytes": len(body), "body_sha256": sha256_text(body),
           "body_format": kind,
           "body": redact_reasoning(parsed) if kind == "json" else parsed,
           "credentials": "excluded (Authorization / api-key headers, "
                          "cookies and URL secrets are never recorded)"}
    raw = b"".join(c for _, c in ex.get("chunks") or [])
    resp: dict[str, Any] = {
        "status_code": ex.get("status_code"),
        "headers": ex.get("response_headers") or {},
        "headers_ms": ex.get("headers_ms"),
        "body_bytes": len(raw), "body_sha256": sha256_text(raw),
        "chunk_count": len(ex.get("chunks") or []),
        "complete": ex.get("complete", False),
        "transport_error": ex.get("transport_error"),
        "stream_error": ex.get("stream_error")}
    ctype = (ex.get("response_headers") or {}).get("content-type", "")
    if "event-stream" in ctype or raw.lstrip().startswith(b"data:"):
        events = _sse_events(ex.get("chunks") or [])
        resp["format"] = "sse"
        resp["chunks"] = [{"t_ms": round(t, 3), "bytes": len(c)}
                          for t, c in ex.get("chunks") or []]
        resp["events"] = events
        resp["assembled"] = assemble_openai_stream(events)
    else:
        kind, parsed = _json_or_text(raw)
        resp["format"] = kind
        resp["body"] = redact_reasoning(parsed) if kind == "json" else parsed
    view = {"wall_time": ex.get("wall_time"), "request": req,
            "response": resp}
    return json.loads(scrub(json.dumps(view, default=str), secrets))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
