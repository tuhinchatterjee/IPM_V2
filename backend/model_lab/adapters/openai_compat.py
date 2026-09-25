"""
OpenAI-compatible (Ollama /v1, vLLM, RunPod-style) and Ollama-native adapter.

MECHANICAL WIRE TRANSLATION ONLY. The frozen engine speaks Anthropic
Messages; this adapter converts that request to the target dialect and the
response back, and never edits analytical content:

* roles, instruction order, history, tool schemas and tool-result text are
  carried byte-for-byte (JSON is re-serialised with ensure_ascii=False, so
  Unicode, quotes and newlines in SQL/Python survive -- A04);
* streamed tool-call fragments are assembled by index and dispatched ONLY
  when the stream has finished and the arguments parse as one JSON object
  (A05); a partial call is never returned;
* tool-call ids are preserved; when a server omits one, a deterministic id is
  minted and recorded (A07);
* stop reasons map to the frozen engine's set; anything unknown stays
  unknown, so the engine fails the turn rather than guessing (A06/A10);
* failures are raised as the frozen typed `ProviderFailure`, never as
  strings for the engine to pattern-match (OG-03);
* no retry happens here (allow_retry is always False from the engine), and
  no hidden repair/extra turn is ever added.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

import httpx

from backend.cockpit_v4.provider import OutputTruncated, ProviderFailure
from backend.cockpit_v4.states import (
    INVALID_MODEL_OUTPUT,
    PROVIDER_AUTH,
    PROVIDER_RATE_LIMIT,
    PROVIDER_REQUEST_INVALID,
    PROVIDER_UNAVAILABLE,
)

_FINISH = {"tool_calls": "tool_use", "function_call": "tool_use",
           "stop": "end_turn", "length": "max_tokens",
           "content_filter": "refusal", "eos": "end_turn"}


class ConverseResult:
    """Same attribute shape as the frozen adapter's result."""

    def __init__(self, **kw: Any) -> None:
        self.assistant_blocks: list[dict[str, Any]] = kw.get(
            "assistant_blocks", [])
        self.text: str = kw.get("text", "")
        self.tool_calls: list[dict[str, Any]] = kw.get("tool_calls", [])
        self.stop_reason: str = kw.get("stop_reason", "")
        self.model: str = kw.get("model", "")
        self.request_id: str = kw.get("request_id", "")
        self.input_tokens = kw.get("input_tokens")
        self.output_tokens = kw.get("output_tokens")
        self.cache_read_tokens = kw.get("cache_read_tokens") or 0
        self.cache_write_tokens = 0
        self.native_usage = kw.get("native_usage")
        self.native_timing = kw.get("native_timing")
        self.first_protocol_event_ms = kw.get("first_protocol_event_ms")
        self.first_visible_text_ms = kw.get("first_visible_text_ms")
        self.first_complete_tool_ms = kw.get("first_complete_tool_ms")
        self.translation_notes: list[str] = kw.get("translation_notes", [])
        self.raw_digest = kw.get("raw_digest")


# ---- request translation --------------------------------------------------

def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def translate_request(*, system: Any, messages: list[dict[str, Any]],
                      tools: list[dict[str, Any]] | None,
                      tool_choice: dict[str, Any] | None,
                      max_tokens: int, model: str, native_ollama: bool = False
                      ) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    out: list[dict[str, Any]] = []
    if isinstance(system, list):
        text = "\n\n".join(b.get("text", "") for b in system
                           if isinstance(b, dict) and b.get("type") == "text")
    else:
        text = str(system or "")
    if text:
        out.append({"role": "system", "content": text})
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for part in content or []:
            t = part.get("type")
            if t == "text":
                texts.append(part.get("text", ""))
            elif t == "tool_use":
                args = part.get("input") or {}
                calls.append({"id": part.get("id"), "type": "function",
                              "function": {"name": part.get("name"),
                                           "arguments": args if native_ollama
                                           else _dump(args)}})
            elif t == "tool_result":
                body = part.get("content")
                if isinstance(body, list):
                    body = "".join(b.get("text", "") for b in body
                                   if isinstance(b, dict))
                body = "" if body is None else str(body)
                if part.get("is_error") and not body.lstrip().startswith(
                        "{"):
                    # OpenAI tool messages carry no error flag; a JSON error
                    # body already says "rejected"/"failed", a bare string
                    # does not. Marked, and recorded as a translation.
                    body = "ERROR: " + body
                    notes.append("is_error carried as an 'ERROR: ' prefix on "
                                 "a non-JSON tool result")
                results.append({"role": "tool",
                                "tool_call_id": part.get("tool_use_id"),
                                "content": body})
            else:
                notes.append(f"unsupported content block {t!r} dropped")
        if role == "assistant":
            msg: dict[str, Any] = {"role": "assistant",
                                   "content": "\n".join(texts) or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            out.extend(results)          # tool results answer in order
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    body: dict[str, Any] = {"model": model, "messages": out}
    if tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("input_schema") or {"type": "object"}}}
            for t in tools]
    if tool_choice:
        typ = tool_choice.get("type")
        if typ == "tool":
            body["tool_choice"] = {"type": "function",
                                   "function": {"name": tool_choice["name"]}}
        elif typ == "any":
            body["tool_choice"] = "required"
        elif typ == "auto":
            body["tool_choice"] = "auto"
        if tool_choice.get("disable_parallel_tool_use"):
            body["parallel_tool_calls"] = False
    if native_ollama:
        body["options"] = {"num_predict": max_tokens}
        if "tool_choice" in body:
            notes.append("Ollama native /api/chat has no tool_choice; the "
                         "forced-tool control is NOT enforced on this route")
            body.pop("tool_choice")
            body.pop("parallel_tool_calls", None)
    else:
        body["max_tokens"] = max_tokens
    return body, notes


# ---- response translation --------------------------------------------------

def _blocks(text: str, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for c in calls:
        blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"],
                       "input": c["input"]})
    return blocks


def _parse_args(raw: Any, name: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
    except (TypeError, ValueError) as exc:
        raise ProviderFailure(
            INVALID_MODEL_OUTPUT,
            f"tool call {name!r} arguments were not complete JSON "
            f"({exc}); nothing was dispatched",
            detail={"origin": "model_output", "raw_prefix":
                    str(raw)[:200]}) from exc
    if not isinstance(val, dict):
        raise ProviderFailure(INVALID_MODEL_OUTPUT,
                              f"tool call {name!r} arguments are not an "
                              f"object", detail={"origin": "model_output"})
    return val


def translate_response(data: dict[str, Any], *, seq: int
                       ) -> ConverseResult:
    notes: list[str] = []
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or ""
    calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        cid = tc.get("id")
        if not cid:
            cid = f"lab_call_{seq}_{i}"
            notes.append(f"server omitted a tool-call id; minted {cid}")
        calls.append({"id": cid, "name": fn.get("name", ""),
                      "input": _parse_args(fn.get("arguments"),
                                           fn.get("name", ""))})
    finish = choice.get("finish_reason") or ""
    stop = _FINISH.get(finish, finish)
    if calls and stop == "end_turn":
        stop = "tool_use"
        notes.append("finish_reason 'stop' with tool calls mapped to "
                     "tool_use")
    usage = data.get("usage") or {}
    cached = ((usage.get("prompt_tokens_details") or {})
              .get("cached_tokens") or 0)
    prompt = usage.get("prompt_tokens")
    return ConverseResult(
        assistant_blocks=_blocks(text, calls), text=text, tool_calls=calls,
        stop_reason=stop, model=data.get("model", ""),
        request_id=data.get("id", ""),
        input_tokens=(prompt - cached) if prompt is not None else None,
        output_tokens=usage.get("completion_tokens"),
        cache_read_tokens=cached, native_usage=usage or None,
        translation_notes=notes)


def assemble_stream(chunks: Iterable[dict[str, Any]], *, seq: int,
                    t0: float, clock=time.monotonic) -> ConverseResult:
    """Assemble OpenAI-style streamed deltas. Returns only when complete."""
    text_parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    finish = ""
    model = rid = ""
    usage: dict[str, Any] = {}
    first_evt = first_text = None
    for ch in chunks:
        now = clock()
        if first_evt is None:
            first_evt = (now - t0) * 1000
        model = ch.get("model") or model
        rid = ch.get("id") or rid
        if ch.get("usage"):
            usage = ch["usage"]
        for choice in ch.get("choices") or []:
            d = choice.get("delta") or {}
            if d.get("content"):
                if first_text is None:
                    first_text = (now - t0) * 1000
                text_parts.append(d["content"])
            for tc in d.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = calls.setdefault(idx, {"id": None, "name": "",
                                              "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    # Some servers repeat the name on every fragment.
                    if not slot["name"]:
                        slot["name"] = fn["name"]
                if fn.get("arguments"):
                    a = fn["arguments"]
                    # Cumulative servers resend the whole prefix; deltas
                    # append. Detect cumulative by prefix match.
                    if slot["args"] and a.startswith(slot["args"]):
                        slot["args"] = a
                    else:
                        slot["args"] += a
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    done = clock()
    if not finish:
        raise ProviderFailure(PROVIDER_UNAVAILABLE,
                              "the stream ended without a finish reason; "
                              "the turn is incomplete and nothing was "
                              "dispatched", retry_class="transport",
                              detail={"origin": "transport"})
    msg_calls = [{"id": s["id"], "type": "function",
                  "function": {"name": s["name"], "arguments": s["args"]}}
                 for _, s in sorted(calls.items())]
    res = translate_response({"choices": [{"message": {
        "content": "".join(text_parts), "tool_calls": msg_calls},
        "finish_reason": finish}], "usage": usage, "model": model,
        "id": rid}, seq=seq)
    res.first_protocol_event_ms = first_evt
    res.first_visible_text_ms = first_text
    res.first_complete_tool_ms = ((done - t0) * 1000 if msg_calls else None)
    return res


def translate_ollama_native(data: dict[str, Any], *, seq: int
                            ) -> ConverseResult:
    msg = data.get("message") or {}
    calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        calls.append({"id": tc.get("id") or f"lab_call_{seq}_{i}",
                      "name": fn.get("name", ""),
                      "input": _parse_args(fn.get("arguments"),
                                           fn.get("name", ""))})
    reason = data.get("done_reason") or ("stop" if data.get("done") else "")
    stop = {"stop": "end_turn", "length": "max_tokens"}.get(reason, reason)
    if calls and stop == "end_turn":
        stop = "tool_use"
    ns = 1_000_000.0
    timing = {k.replace("_duration", "_duration_ms"): data[k] / ns
              for k in ("total_duration", "load_duration",
                        "prompt_eval_duration", "eval_duration")
              if isinstance(data.get(k), (int, float))}
    timing["eval_count"] = data.get("eval_count")
    timing["prompt_eval_count"] = data.get("prompt_eval_count")
    return ConverseResult(
        assistant_blocks=_blocks(msg.get("content") or "", calls),
        text=msg.get("content") or "", tool_calls=calls, stop_reason=stop,
        model=data.get("model", ""),
        input_tokens=data.get("prompt_eval_count"),
        output_tokens=data.get("eval_count"),
        native_usage={k: data.get(k) for k in (
            "prompt_eval_count", "eval_count", "total_duration",
            "load_duration", "prompt_eval_duration", "eval_duration")},
        native_timing=timing)


# ---- the provider ------------------------------------------------------------

class OpenAICompatProvider:
    def __init__(self, *, base_url: str, model: str,
                 api_key: str | None = None,
                 endpoint_class: str = "local_loopback",
                 native_ollama: bool = False, stream: bool = True,
                 transport: httpx.BaseTransport | None = None) -> None:
        if endpoint_class == "local_loopback" and not base_url.startswith(
                ("http://127.0.0.1", "http://localhost", "http://[::1]")):
            raise ValueError("a local profile must use a loopback endpoint")
        if endpoint_class == "remote_gpu" and not base_url.startswith(
                "https://"):
            raise ValueError("a remote endpoint must use TLS (or an "
                             "approved SSH tunnel to loopback)")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._key = api_key
        self.native = native_ollama
        self.stream = stream and not native_ollama
        self._transport = transport
        self.seq = 0
        self.last_request: dict[str, Any] | None = None

    def _client(self, timeout: float) -> httpx.Client:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return httpx.Client(timeout=timeout or 60.0, headers=headers,
                            transport=self._transport)

    def converse(self, *, system, messages, tools=None, max_tokens=4096,
                 model="", purpose="", role="", timeout=0.0,
                 allow_retry=False, tool_choice=None, output_config=None,
                 **_: Any) -> ConverseResult:
        self.seq += 1
        if model and model != self.model:
            raise ProviderFailure(PROVIDER_REQUEST_INVALID,
                                  f"engine asked for {model!r} but this "
                                  f"child is pinned to {self.model!r}")
        body, notes = translate_request(
            system=system, messages=messages, tools=tools,
            tool_choice=tool_choice, max_tokens=max_tokens,
            model=self.model, native_ollama=self.native)
        if output_config:
            notes.append("output_config not sent (no equivalent control on "
                         "this route)")
        self.last_request = body
        url = self.base_url + ("/api/chat" if self.native else
                               "/chat/completions")
        if self.native:
            body["stream"] = False
        elif self.stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        t0 = time.monotonic()
        try:
            with self._client(timeout) as c:
                if self.stream:
                    with c.stream("POST", url, json=body) as r:
                        self._raise_for(r, stream=True)
                        res = assemble_stream(self._sse(r), seq=self.seq,
                                              t0=t0)
                else:
                    r = c.post(url, json=body)
                    self._raise_for(r)
                    data = r.json()
                    res = (translate_ollama_native(data, seq=self.seq)
                           if self.native else
                           translate_response(data, seq=self.seq))
        except ProviderFailure:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderFailure(PROVIDER_UNAVAILABLE,
                                  f"the request timed out after "
                                  f"{timeout:.0f}s", retry_class="transport",
                                  detail={"timed_out": True}) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure(PROVIDER_UNAVAILABLE,
                                  f"connection failed: {type(exc).__name__}",
                                  retry_class="transport") from exc
        res.translation_notes = notes + res.translation_notes
        if res.stop_reason == "max_tokens":
            # Let the frozen engine raise its own OutputTruncated from the
            # stop reason; nothing is dispatched from a cut-off turn.
            pass
        return res

    @staticmethod
    def _sse(r: httpx.Response) -> Iterable[dict[str, Any]]:
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except ValueError as exc:
                raise ProviderFailure(PROVIDER_UNAVAILABLE,
                                      "malformed stream event",
                                      retry_class="transport") from exc

    @staticmethod
    def _raise_for(r: httpx.Response, stream: bool = False) -> None:
        if r.status_code < 400:
            return
        if stream:
            r.read()
        text = r.text[:300]
        code = {401: PROVIDER_AUTH, 403: PROVIDER_AUTH,
                429: PROVIDER_RATE_LIMIT}.get(r.status_code)
        if code is None:
            code = (PROVIDER_REQUEST_INVALID if 400 <= r.status_code < 500
                    else PROVIDER_UNAVAILABLE)
        raise ProviderFailure(code, f"HTTP {r.status_code}: {text}",
                              retry_class=("transport" if r.status_code >= 500
                                           else "none"),
                              detail={"status_code": r.status_code,
                                      "rejected_before_inference":
                                      r.status_code < 500})


__all__ = ["OpenAICompatProvider", "translate_request", "translate_response",
           "assemble_stream", "translate_ollama_native", "ConverseResult",
           "OutputTruncated"]
