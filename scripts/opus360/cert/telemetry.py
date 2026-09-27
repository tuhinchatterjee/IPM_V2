"""
Per-turn telemetry derived from the frozen product's persisted events and the
harness's pass-through call records.

Provider-native token usage is AUTHORITATIVE and is never replaced by an
estimate. The decomposition of input tokens into system / tool schema /
history / tool results is an ESTIMATE (byte-share allocation of the native
input total over the exact request bytes, optionally with provider-counted
static blocks) and is always labelled with its method.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable
from typing import Any

from cert.engine import parse_iso
from cert.observe import UNKNOWN

TERMINAL_EVENTS = {"answer.ready", "run.failed", "run.cancelled", "run.expired", "run.interrupted"}
TOOLS = ("inspect_catalog", "inspect_product_knowledge", "execute_analysis", "read_artifact",
         "finalize_response")


def _h(obj: Any) -> str:
    raw = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _ts(e: dict[str, Any]) -> float | None:
    return parse_iso(str(e.get("occurred_at") or ""))


# ---- tool activity ---------------------------------------------------------------

def tool_activity(events: list[dict[str, Any]], calls: list[dict[str, Any]],
                  messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per tool call, in order, with timing, outcome and payload hashes."""
    inputs: list[dict[str, Any]] = []
    for c in calls:
        for tc in c.get("response_tool_calls") or []:
            inputs.append(tc)
    results: dict[str, str] = {}
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results[str(block.get("tool_use_id") or "")] = _h(block.get("content"))
    rows = []
    idx_in = {name: [i for i in inputs if i.get("name") == name] for name in TOOLS}
    used = {name: 0 for name in TOOLS}
    for i, e in enumerate(events):
        if e.get("event_type") != "tool.requested":
            continue
        tool = str(e.get("operation") or "")
        if tool not in TOOLS:
            continue
        end = e
        outcome = "ok"
        validation = ""
        for f in events[i + 1:]:
            if f.get("event_type") in ("tool.requested", "model.requested") or f.get("event_type") in TERMINAL_EVENTS:
                break
            end = f
            if f.get("event_type") == "tool.failed":
                outcome = "rejected" if f.get("status") == "rejected" or f.get("stage") == "validating" else "failed"
            if f.get("event_type") == "tool.validated":
                validation = "validated"
            if f.get("event_type") == "answer.validated":
                validation = "answer_" + str(f.get("status") or "")
                if f.get("status") == "rejected":
                    outcome = "rejected"
        t0, t1 = _ts(e), _ts(end)
        n = used[tool]
        used[tool] += 1
        tc = idx_in[tool][n] if n < len(idx_in[tool]) else {}
        rows.append({
            "tool": tool, "order": len(rows) + 1, "event_seq": e.get("seq"),
            "started_at": e.get("occurred_at"), "ended_at": end.get("occurred_at"),
            "elapsed_ms": int((t1 - t0) * 1000) if (t0 and t1) else UNKNOWN,
            "outcome": outcome, "validation": validation,
            "submission": e.get("submission") or end.get("submission") or "",
            "input_hash": _h(tc.get("input")) if tc else UNKNOWN,
            "result_hash": results.get(str(tc.get("id") or ""), UNKNOWN) if tc else UNKNOWN,
            "tool_use_id": tc.get("id", "") if tc else "",
        })
    return rows


# ---- timings --------------------------------------------------------------------------

def timings(events: list[dict[str, Any]], record: dict[str, Any], calls: list[dict[str, Any]],
            tools: list[dict[str, Any]], post_mono: float, terminal_mono: float) -> dict[str, Any]:
    accepted = next((_ts(e) for e in events if e.get("event_type") == "run.accepted"), None)
    claimed = next((_ts(e) for e in events if e.get("event_type") != "run.accepted"), None)
    settled = parse_iso(str(record.get("updated_at") or ""))
    conv = [c for c in calls if c.get("kind") == "converse"]
    counts = [c for c in calls if c.get("kind") == "count_tokens"]
    model_ms = sum(int(c.get("elapsed_ms") or 0) for c in conv)
    count_ms = sum(int(c.get("elapsed_ms") or 0) for c in counts)
    http_ms = sum(int(a.get("elapsed_ms") or 0) for c in calls for a in (c.get("http_attempts") or []))
    provider_retry_ms = sum(int(a.get("elapsed_ms") or 0) for c in calls
                            for a in (c.get("http_attempts") or [])[:-1])

    def span(tool: str) -> int:
        return sum(int(t["elapsed_ms"]) for t in tools if t["tool"] == tool and isinstance(t["elapsed_ms"], int))

    validation_ms = 0
    execution_ms = 0
    for i, e in enumerate(events):
        if e.get("event_type") == "tool.requested" and e.get("operation") == "execute_analysis":
            t0 = _ts(e)
            for f in events[i + 1:]:
                if f.get("event_type") in ("tool.validated",) or (
                        f.get("event_type") == "tool.failed" and f.get("stage") == "validating"):
                    t1 = _ts(f)
                    if t0 and t1:
                        validation_ms += int((t1 - t0) * 1000)
                    break
                if f.get("event_type") in ("model.requested",) or f.get("event_type") in TERMINAL_EVENTS:
                    break
        if e.get("event_type") == "tool.validated":
            t0 = _ts(e)
            last = None
            for f in events[i + 1:]:
                if f.get("event_type") in ("model.requested", "tool.requested") or f.get("event_type") in TERMINAL_EVENTS:
                    break
                last = f
            if t0 and last is not None and _ts(last):
                execution_ms += int((_ts(last) - t0) * 1000)
    first_fail = next((_ts(e) for e in events if e.get("event_type") == "tool.failed"
                       and e.get("stage") in ("validating", "executing")), None)
    first_ok_exec = next((_ts(e) for e in events if e.get("event_type") == "tool.completed"
                          and e.get("stage") == "executing"), None)
    repair_ms = int((first_ok_exec - first_fail) * 1000) if (first_fail and first_ok_exec and first_ok_exec > first_fail) else 0
    e2e_processing = int((settled - accepted) * 1000) if (settled and accepted) else UNKNOWN
    queue = int((claimed - accepted) * 1000) if (claimed and accepted) else UNKNOWN
    local = (e2e_processing - model_ms - count_ms - (queue if isinstance(queue, int) else 0)
             if isinstance(e2e_processing, int) else UNKNOWN)
    return {
        "accepted_at": next((e.get("occurred_at") for e in events if e.get("event_type") == "run.accepted"), ""),
        "settled_at": record.get("updated_at", ""),
        "queue_wait_ms": queue,
        "model_call_ms": model_ms,
        "token_count_call_ms": count_ms,
        "provider_http_ms": http_ms if any(c.get("http_attempts") for c in calls) else UNKNOWN,
        "provider_retry_ms": provider_retry_ms,
        "local_deterministic_ms": local,
        "catalog_ms": span("inspect_catalog"),
        "product_knowledge_ms": span("inspect_product_knowledge"),
        "analysis_validation_ms": validation_ms,
        "execution_ms": execution_ms,
        "artifact_read_ms": span("read_artifact"),
        "finalization_ms": span("finalize_response"),
        "repair_ms": repair_ms,
        "e2e_processing_ms": e2e_processing,
        "e2e_wall_ms": int((terminal_mono - post_mono) * 1000),
        "time_to_first_successful_execute_ms": int((first_ok_exec - accepted) * 1000) if (first_ok_exec and accepted) else UNKNOWN,
        "success_to_final_ms": int((settled - first_ok_exec) * 1000) if (settled and first_ok_exec) else UNKNOWN,
    }


# ---- token decomposition ----------------------------------------------------------------

HEADERS = [
    ("USER REQUEST (original wording, unmodified):", "current_question"),
    ("ACTIVE INVESTIGATION", "investigation_context"),
    ("ANALYSIS PACKET FOR THIS INVESTIGATION", "investigation_context"),
    ("CASE FILE FOR THIS INVESTIGATION", "investigation_context"),
    ("RECENT COMPLETED TURNS IN THIS THREAD", "history"),
    ("OLDER-HISTORY SUMMARY", "history_summary"),
    ("Decide what this request is, who owns it, and take your next action now.", "instruction_tail"),
]
COMPONENTS = ("system_instruction", "system_static_knowledge", "system_volatile", "system_other",
              "tool_schema", "current_question", "history_user", "history_assistant", "history_other",
              "history_summary", "investigation_context", "instruction_tail", "first_message_other",
              "in_run_assistant", "in_run_tool_results_current", "in_run_tool_results_replayed",
              "in_run_instructions")


def _b(obj: Any) -> int:
    if isinstance(obj, str):
        return len(obj.encode("utf-8"))
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))


def _split_first(text: str, out: dict[str, int]) -> None:
    positions = []
    for header, comp in HEADERS:
        start = 0
        while True:
            i = text.find(header, start)
            if i < 0:
                break
            positions.append((i, header, comp))
            start = i + len(header)
    positions.sort()
    if not positions:
        out["first_message_other"] += _b(text)
        return
    if positions[0][0] > 0:
        out["first_message_other"] += _b(text[:positions[0][0]])
    for n, (i, _header, comp) in enumerate(positions):
        j = positions[n + 1][0] if n + 1 < len(positions) else len(text)
        chunk = text[i:j]
        if comp != "history":
            out[comp] += _b(chunk)
            continue
        body = chunk[chunk.find("\n") + 1:] if "\n" in chunk else ""
        try:
            entries = json.loads(body.strip())
        except (ValueError, json.JSONDecodeError):
            out["history_other"] += _b(chunk)
            continue
        used = 0
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            q = _b(entry.get("question") or "")
            a = sum(_b(entry.get(k) or "") for k in ("answer", "you_asked", "you_offered"))
            out["history_user"] += q
            out["history_assistant"] += a
            used += q + a
        out["history_other"] += max(0, _b(chunk) - used)


def decompose_payload(payload: dict[str, Any]) -> dict[str, int]:
    out = {c: 0 for c in COMPONENTS}
    system = payload.get("system")
    if isinstance(system, list):
        for i, block in enumerate(system):
            text = block.get("text") if isinstance(block, dict) else block
            key = {0: "system_instruction", 1: "system_static_knowledge", 2: "system_volatile"}.get(i, "system_other")
            out[key] += _b(text or "")
    elif system:
        out["system_instruction"] += _b(system)
    out["tool_schema"] = _b(payload.get("tools") or [])
    messages = payload.get("messages") or []
    names: dict[str, str] = {}
    last_user_index = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    for i, m in enumerate(messages):
        content = m.get("content")
        if m.get("role") == "assistant":
            out["in_run_assistant"] += _b(content)
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    names[str(block.get("id") or "")] = str(block.get("name") or "")
            continue
        if i == 0 and isinstance(content, str):
            _split_first(content, out)
            continue
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        for block in blocks:
            if not isinstance(block, dict):
                out["in_run_instructions"] += _b(block)
            elif block.get("type") == "tool_result":
                key = "in_run_tool_results_current" if i == last_user_index else "in_run_tool_results_replayed"
                out[key] += _b(block)
            elif i == 0 and block.get("type") == "text":
                _split_first(str(block.get("text") or ""), out)
            else:
                out["in_run_instructions"] += _b(block)
    return out


def load_payload(path: str) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def decompose_call(call: dict[str, Any],
                   static_counter: Callable[[str, Any], int | None] | None = None) -> dict[str, Any]:
    """Estimated token components for one converse call; native total is authoritative."""
    native = call.get("input_tokens")
    payload = load_payload(call.get("payload_path", ""))
    if payload is None:
        return {"method": "UNAVAILABLE", "native_input_tokens": native}
    parts = decompose_payload(payload)
    total_bytes = sum(parts.values()) or 1
    method = "ESTIMATED_BYTE_SHARE"
    tokens: dict[str, float] = {}
    fixed: dict[str, int] = {}
    if static_counter is not None:
        system = payload.get("system") or []
        for i, key in ((0, "system_instruction"), (1, "system_static_knowledge")):
            if isinstance(system, list) and len(system) > i:
                counted = static_counter(key, system[i])
                if isinstance(counted, int):
                    fixed[key] = counted
        counted_tools = static_counter("tool_schema", payload.get("tools") or [])
        if isinstance(counted_tools, int):
            fixed["tool_schema"] = counted_tools
        if fixed:
            method = "PROVIDER_COUNTED_STATIC+ESTIMATED_BYTE_SHARE"
    if isinstance(native, int):
        residual_tokens = max(0, native - sum(fixed.values()))
        residual_bytes = sum(v for k, v in parts.items() if k not in fixed) or 1
        for k, v in parts.items():
            tokens[k] = float(fixed[k]) if k in fixed else residual_tokens * v / residual_bytes
    else:
        tokens = {k: UNKNOWN for k in parts}
    estimated_sum = sum(v for v in tokens.values() if isinstance(v, float))
    return {"method": method, "native_input_tokens": native, "bytes": parts,
            "bytes_total": total_bytes, "tokens": {k: (round(v, 1) if isinstance(v, float) else v)
                                                   for k, v in tokens.items()},
            "estimated_sum": round(estimated_sum, 1),
            "difference_vs_native": (round(native - estimated_sum, 1) if isinstance(native, int) else UNKNOWN)}


def token_summary(calls: list[dict[str, Any]], decompositions: list[dict[str, Any]],
                  first_failure_ts: float | None, first_correct_artifact_ts: float | None
                  ) -> dict[str, Any]:
    conv = [c for c in calls if c.get("kind") == "converse"]

    def tot(key: str) -> Any:
        vals = [c.get(key) for c in conv]
        if not vals:
            return 0
        if any(not isinstance(v, int) for v in vals):
            known = [v for v in vals if isinstance(v, int)]
            return sum(known) if known else UNKNOWN
        return sum(vals)

    comp: dict[str, float] = {k: 0.0 for k in COMPONENTS}
    for d in decompositions:
        for k, v in (d.get("tokens") or {}).items():
            if isinstance(v, (int, float)):
                comp[k] += float(v)
    input_total = tot("input_tokens")
    output_total = tot("output_tokens")

    def after(ts: float | None) -> Any:
        if ts is None:
            return 0
        s = 0
        for c in conv:
            start = parse_iso(str(c.get("started_at") or ""))
            if start and start >= ts and isinstance(c.get("input_tokens"), int) and isinstance(c.get("output_tokens"), int):
                s += c["input_tokens"] + c["output_tokens"]
        return s

    static = comp["system_instruction"] + comp["system_static_knowledge"] + comp["system_volatile"] + \
        comp["system_other"] + comp["tool_schema"]
    history = comp["history_user"] + comp["history_assistant"] + comp["history_other"] + comp["history_summary"]
    toolres = comp["in_run_tool_results_current"] + comp["in_run_tool_results_replayed"]
    denom = input_total if isinstance(input_total, int) and input_total else None
    return {
        "model_calls": len(conv),
        "token_count_calls": len([c for c in calls if c.get("kind") == "count_tokens"]),
        "native_input_tokens": input_total, "native_output_tokens": output_total,
        "native_total_tokens": (input_total + output_total) if isinstance(input_total, int) and isinstance(output_total, int) else UNKNOWN,
        "cache_read_tokens": tot("cache_read_tokens"), "cache_write_tokens": tot("cache_write_tokens"),
        "components_estimated": {k: round(v, 1) for k, v in comp.items()},
        "decomposition_method": sorted({d.get("method", "") for d in decompositions}),
        "static_context_tax": round(static / denom, 4) if denom else UNKNOWN,
        "history_tax": round(history / denom, 4) if denom else UNKNOWN,
        "tool_result_tax": round(toolres / denom, 4) if denom else UNKNOWN,
        "estimated_static_tokens": round(static, 1), "estimated_history_tokens": round(history, 1),
        "estimated_tool_result_tokens": round(toolres, 1),
        "repair_tokens": after(first_failure_ts),
        "finalization_tokens_after_correct_artifact": after(first_correct_artifact_ts),
    }
