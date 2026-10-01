"""
An OpenAI-compatible chat-completions adapter, for open-weight models.

vLLM, Ollama, LM Studio, TGI and most hosted open-weight endpoints speak the
chat-completions dialect. CreditProbe's canonical conversation is the
Anthropic-shaped one the analyst loop builds (system blocks, content blocks,
`tool_use`/`tool_result` pairs), so this adapter TRANSLATES in both
directions and says exactly what it translated:

    Canonical request -> Adapter request -> Raw provider response
                      -> Normalized response

Each of the four is recorded by `backend.llm.exchange` when a call is
observed, and every lossy step -- system blocks concatenated, an `effort`
setting the dialect has no field for -- is written into the record's
`adapter_translation` rather than silently dropped.

It is used by the AI Model Lab to replay a recorded canonical request
against an open-weight model. It is NOT wired into the Advanced Cockpit
analyst path: `service.resolve_provider` accepts one provider, and changing
which model answers a banker's question is a decision this module does not
make.

The credential, when one is needed, is read from the environment at call time,
sent only as an HTTP header, and never passed to the recorder: the recorder
sees the JSON body, never the headers.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.llm import exchange
from backend.llm.base import ConverseResult, LLMError

#: The environment the AI Model Lab reads its open-weight target from.
URL_VAR = "CREDITPROBE_MODEL_LAB_OPENWEIGHT_URL"
MODEL_VAR = "CREDITPROBE_MODEL_LAB_OPENWEIGHT_MODEL"
KEY_VAR = "CREDITPROBE_MODEL_LAB_OPENWEIGHT_KEY"

_FINISH = {"tool_calls": "tool_use", "function_call": "tool_use",
           "stop": "end_turn", "length": "max_tokens",
           "content_filter": "refusal"}


def _text_of(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        return str(block.get("text", ""))
    return str(getattr(block, "text", "") or "")


def _plain(block: Any) -> Any:
    return block if isinstance(block, (dict, str)) else exchange.to_plain(block)


def translate_request(*, system: Any, messages: list[dict[str, Any]],
                      tools: list[dict[str, Any]] | None, max_tokens: int,
                      model: str, tool_choice: dict[str, Any] | None,
                      output_config: dict[str, Any] | None
                      ) -> tuple[dict[str, Any], list[str]]:
    """Canonical (Anthropic-shaped) -> chat-completions body, and the notes."""
    notes: list[str] = []
    out: list[dict[str, Any]] = []
    if isinstance(system, list):
        texts = [_text_of(b) for b in system]
        if len(texts) > 1:
            notes.append(f"{len(texts)} system blocks were concatenated into "
                         f"one system message (the dialect has one).")
        cache_marked = sum(1 for b in system if isinstance(b, dict)
                           and b.get("cache_control"))
        if cache_marked:
            notes.append(f"{cache_marked} cache_control marker(s) dropped: "
                         f"the dialect has no prompt-cache field.")
        system_text = "\n\n".join(t for t in texts if t)
    else:
        system_text = str(system or "")
    if system_text:
        out.append({"role": "system", "content": system_text})
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        blocks = [_plain(b) for b in (content or [])]
        if role == "assistant":
            text = "".join(b.get("text", "") for b in blocks
                           if isinstance(b, dict) and b.get("type") == "text")
            calls = [{"id": b.get("id", ""), "type": "function",
                      "function": {"name": b.get("name", ""),
                                   "arguments": json.dumps(
                                       b.get("input", {}),
                                       ensure_ascii=False)}}
                     for b in blocks if isinstance(b, dict)
                     and b.get("type") == "tool_use"]
            entry: dict[str, Any] = {"role": "assistant",
                                     "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        texts = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                body = block.get("content")
                if not isinstance(body, str):
                    body = json.dumps(body, ensure_ascii=False, default=str)
                if block.get("is_error"):
                    notes.append("a tool_result's is_error flag was carried "
                                 "as text: the dialect has no error flag.")
                    body = "[tool error] " + body
                out.append({"role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": body})
            elif block.get("type") == "text":
                texts.append(block.get("text", ""))
        if texts:
            out.append({"role": "user", "content": "\n".join(texts)})
    body: dict[str, Any] = {"model": model, "messages": out,
                            "max_tokens": int(max_tokens)}
    if tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "parameters": t.get("input_schema", {})}} for t in tools]
    if tool_choice:
        kind = tool_choice.get("type")
        if kind == "any":
            body["tool_choice"] = "required"
        elif kind == "tool":
            body["tool_choice"] = {"type": "function",
                                   "function": {"name": tool_choice.get(
                                       "name", "")}}
        elif kind == "auto":
            body["tool_choice"] = "auto"
        if tool_choice.get("disable_parallel_tool_use"):
            body["parallel_tool_calls"] = False
    if output_config:
        notes.append(f"output_config {sorted(output_config)} dropped: the "
                     f"dialect has no equivalent field.")
    return body, notes


def normalize_response(raw: dict[str, Any], *, model: str,
                       duration_ms: int) -> ConverseResult:
    """chat-completions response -> the `ConverseResult` the loop continues with."""
    choices = raw.get("choices") or []
    if not choices:
        raise LLMError("The open-weight endpoint returned no choices.")
    message = choices[0].get("message") or {}
    blocks: list[dict[str, Any]] = []
    text = message.get("content") or ""
    if text:
        blocks.append({"type": "text", "text": text})
    calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        arguments = fn.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments) if isinstance(
                arguments, str) else arguments
        except ValueError as exc:
            raise LLMError(
                f"The open-weight model returned tool arguments that are "
                f"not JSON: {str(arguments)[:200]}") from exc
        block = {"type": "tool_use", "id": call.get("id", ""),
                 "name": fn.get("name", ""), "input": parsed}
        blocks.append(block)
        calls.append({"id": block["id"], "name": block["name"],
                      "input": parsed})
    usage = raw.get("usage") or {}
    return ConverseResult(
        assistant_blocks=blocks, text=text, tool_calls=calls,
        stop_reason=_FINISH.get(str(choices[0].get("finish_reason") or ""),
                                str(choices[0].get("finish_reason") or "")),
        model=str(raw.get("model") or model), duration_ms=duration_ms,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        attempts=1, request_id=str(raw.get("id") or ""))


def _http_transport(url: str, body: dict[str, Any], headers: dict[str, str],
                    timeout: float) -> dict[str, Any]:
    import httpx

    response = httpx.post(url, json=body, headers=headers,
                          timeout=timeout or 120.0)
    response.raise_for_status()
    return response.json()


@dataclass
class OpenAICompatibleProvider:
    """One open-weight endpoint. The key, if any, is read at call time."""

    base_url: str
    model: str
    name: str = "open_weight"
    #: Injectable so the translation can be tested without a network.
    transport: Callable[..., dict[str, Any]] = field(
        default=_http_transport, repr=False)
    key_var: str = KEY_VAR

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def converse(self, *, system: Any, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None,
                 max_tokens: int = 4096, model: str = "",
                 purpose: str = "conversation", role: str = "",
                 effort: str = "", timeout: float = 0.0,
                 allow_retry: bool = False,
                 tool_choice: dict[str, Any] | None = None,
                 output_config: dict[str, Any] | None = None
                 ) -> ConverseResult:
        if not self.configured:
            raise LLMError("No open-weight endpoint is configured "
                           f"({URL_VAR}, {MODEL_VAR}).")
        chosen = (model or "").strip() or self.model
        body, notes = translate_request(
            system=system, messages=messages, tools=tools,
            max_tokens=max_tokens, model=chosen, tool_choice=tool_choice,
            output_config=output_config)
        exchange.adapter_stage(adapter="openai.chat_completions",
                               provider=self.name, request=body,
                               translation="; ".join(notes))
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(self.key_var, "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        started = time.perf_counter()
        raw = self.transport(self.base_url.rstrip("/") + "/chat/completions",
                             body, headers, timeout)
        exchange.adapter_stage(adapter="openai.chat_completions",
                               provider=self.name, raw_response=raw)
        return normalize_response(
            raw, model=chosen,
            duration_ms=int((time.perf_counter() - started) * 1000))


def from_environment() -> OpenAICompatibleProvider | None:
    url = os.environ.get(URL_VAR, "").strip()
    model = os.environ.get(MODEL_VAR, "").strip()
    if not (url and model):
        return None
    return OpenAICompatibleProvider(base_url=url, model=model)


__all__ = ["KEY_VAR", "MODEL_VAR", "OpenAICompatibleProvider", "URL_VAR",
           "from_environment", "normalize_response", "translate_request"]
