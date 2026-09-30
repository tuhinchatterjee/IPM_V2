"""
Model I/O Trace view: the chronological call / tool round-trip timeline.

Read-only. Built from what is already stored -- the lab's `model_io.call`
trace events (captured by the observer, see `io_trace.py`), the frozen run
store (call report, events, submissions, persisted history) and the current
evaluation (stage links). Opening a trace never calls a model.

Per model call, four views:

* ENGINE REQUEST  -- what the frozen engine handed the provider seam
  (system prompt, messages, tools, tool_choice, limits, controls), plus the
  frozen call report's counted input / reserved output / timeout;
* WIRE REQUEST    -- the provider-specific HTTP request(s) actually sent,
  credential-free (none for an in-process fixture);
* RAW RESPONSE    -- status, safe headers, JSON body or every SSE event in
  arrival order, and the assembled provider response;
* NORMALIZED      -- the object the adapter returned to the engine, or the
  typed failure.

Per tool call, one round trip: the model's tool call, the frozen validation
and execution records, and the EXACT tool_result the next request carried.
Calls the frozen engine refused before dispatch appear as NOT_SENT.
"""

from __future__ import annotations

import json
from typing import Any

from backend.model_lab import io_trace

VIEWS = ("engine_request", "wire_request", "wire_response_raw",
         "normalized_response")
_VALIDATION = ("tool.validated", "tool.failed", "intent.validated",
               "answer.validated", "tool.rejected")
_EXECUTION = ("tool.started", "tool.completed")


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _size(obj: Any) -> dict[str, Any]:
    text = _dump(obj)
    return {"bytes": len(text.encode()), "sha256": io_trace.sha256_text(text)}


def traces_by_child(coord, cid: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in coord.store.events(cid, coord.cfg.tenant_id, 0, 10 ** 7):
        if e["event_type"] != "model_io.call" or not e.get("payload_ref"):
            continue
        rec = json.loads(coord.store.get_blob(e["payload_ref"]))
        out.setdefault(e["child_run_id"], []).append(rec)
    return out


def _report(runs, run_id: str) -> list[dict[str, Any]]:
    for d in runs.details_for_run(run_id).values():
        if isinstance(d, dict) and "call_report" in d:
            return list(d["call_report"].get("calls") or [])
    return []


def _tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    norm = trace.get("normalized_response") or {}
    return [c for c in norm.get("tool_calls") or [] if isinstance(c, dict)]


def _tool_result_in(engine: dict[str, Any] | None, tool_id: str) -> Any:
    for m in (engine or {}).get("messages") or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" \
                        and b.get("tool_use_id") == tool_id:
                    return b
    return None


def _event(runs, ev) -> dict[str, Any]:
    detail = runs.get_detail(ev.detail_ref) if ev.detail_ref else None
    return {"seq": ev.seq, "event_type": ev.event_type,
            "operation": ev.operation, "status": ev.status,
            "elapsed_ms": ev.elapsed_ms, "message": ev.public_message,
            "detail": (detail or {}).get("body") if detail else None}


def _stage_index(ev_body: dict | None) -> dict[str, dict[str, Any]]:
    """call_id -> stage link, from the current evaluation."""
    out: dict[str, dict[str, Any]] = {}
    for k in (ev_body or {}).get("children") or []:
        for c in k.get("calls") or []:
            out[c["call_id"]] = {"stage_tags": c.get("stage_tags") or [],
                                 "shared_span": bool(c.get("shared_span")),
                                 "attribution_basis":
                                 c.get("attribution_basis") or ""}
    return out


def _counted(req: Any, entry: dict[str, Any]) -> dict[str, Any]:
    """The frozen engine's input count for this call.

    The frozen run store redacts every `*_tokens` key when it persists the
    call report, so the number it used is not stored. For the local
    conservative estimate the formula is known (frozen `Analyst.count_input`:
    len(json.dumps({system, messages, tools})) / 2.2 + 1) and is recomputed
    from the captured request; a provider-side count cannot be recomputed.
    """
    stored = entry.get("counted_input_tokens")
    if isinstance(stored, int):
        return {"counted_input_tokens": stored,
                "counted_input_tokens_source": "frozen call report"}
    if entry.get("count_method") == "local_conservative_estimate" and \
            isinstance(req, dict):
        payload = json.dumps({"system": req.get("system"),
                              "messages": req.get("messages"),
                              "tools": req.get("tools")},
                             ensure_ascii=False, default=str)
        return {"counted_input_tokens": int(len(payload) / 2.2) + 1,
                "counted_input_tokens_source":
                    "recomputed from the captured engine request with the "
                    "frozen local estimate formula (the frozen store "
                    "redacts *_tokens keys)"}
    return {"counted_input_tokens": None,
            "counted_input_tokens_source":
                f"unavailable: count_method={entry.get('count_method')}; "
                f"the frozen store redacts *_tokens keys"}


def _engine_view(trace: dict[str, Any] | None, entry: dict[str, Any],
                 stage: dict[str, Any]) -> dict[str, Any]:
    t = trace or {}
    req = t.get("engine_request")
    ctx = t.get("context") or {}
    parts = {}
    if isinstance(req, dict):
        parts = {k: _size(req.get(k))["bytes"]
                 for k in ("system", "messages", "tools")}
        parts["total"] = _size(req)["bytes"]
    allowance = entry.get("output_allowance") or {}
    return {
        "metadata": {
            "timestamp": t.get("engine_request_captured_at"),
            "comparison_id": ctx.get("comparison_id"),
            "child_run_id": ctx.get("child_run_id"),
            "question_id": ctx.get("question_id"),
            "profile_id": ctx.get("profile_id"),
            "requested_model": ctx.get("requested_model"),
            "stage_tags": stage.get("stage_tags"),
            "purpose": entry.get("purpose"), "phase": entry.get("phase"),
            "context_capacity_tokens": ctx.get("declared_context_tokens"),
            **_counted(req, entry),
            "count_method": entry.get("count_method"),
            "reserved_output_tokens": allowance.get("granted"),
            "output_allowance": allowance or None,
            "call_timeout_seconds": entry.get("call_timeout_seconds"),
            "request_controls": ctx.get("request_controls"),
            "frozen_context_bytes": entry.get("context_bytes"),
            "request_bytes": parts,
        },
        "request": req,
    }


def _wire_request_view(trace: dict[str, Any] | None) -> Any:
    if not trace:
        return None
    if trace.get("dispatch_status") == "IN_PROCESS_NO_NETWORK":
        return {"boundary": "in-process fixture provider; no network "
                            "request exists. The ENGINE REQUEST is exactly "
                            "what the fixture received."}
    return [dict(x["request"], attempt=i + 1)
            for i, x in enumerate(trace.get("wire_exchanges") or [])]


def _wire_response_view(trace: dict[str, Any] | None) -> Any:
    if not trace:
        return None
    if trace.get("dispatch_status") == "IN_PROCESS_NO_NETWORK":
        return {"boundary": "in-process fixture provider; the NORMALIZED "
                            "RESPONSE is exactly what it returned."}
    return [dict(x["response"], attempt=i + 1,
                 wall_time=x.get("wall_time"))
            for i, x in enumerate(trace.get("wire_exchanges") or [])]


def build(coord, cid: str, *, include_bodies: bool = False
          ) -> dict[str, Any]:
    tenant = coord.cfg.tenant_id
    runs = coord.runs
    cur = coord.store.current_evaluation(cid, tenant)
    stages_by_call = _stage_index(cur["body"] if cur else None)
    eval_children = {k["child_run_id"]: k for k in
                     ((cur or {}).get("body") or {}).get("children") or []}
    traces = traces_by_child(coord, cid)
    spec = coord._spec(cid)
    out_children = []
    n_call = n_tool = 0
    for child in coord.store.children(cid):
        ch_id = child["child_run_id"]
        pending = list(traces.get(ch_id) or [])
        timeline: list[dict[str, Any]] = []
        stage_links: dict[str, dict[str, list]] = {
            s: {"calls": [], "shared_calls": [], "tool_roundtrips": []}
            for s in ("S1", "S2", "S3", "S4")}
        for turn_index, turn in enumerate(coord.store.child_runs(ch_id)):
            run_id = turn["run_id"]
            report = _report(runs, run_id)
            fevents = runs.events_since(run_id)
            requested = [e.seq for e in fevents
                         if e.event_type == "model.requested"]
            messages = runs.load_messages(run_id)
            subs = {s["submission_id"]: s
                    for s in runs.submissions_for_run(run_id)}
            sent_traces: list[dict[str, Any]] = []
            call_items: list[dict[str, Any]] = []
            for entry in report:
                not_sent = entry.get("outcome") == "refused_before_send"
                trace = None if not_sent else (pending.pop(0) if pending
                                               else None)
                n_call += 1
                call_id = (trace or {}).get("call_id") or \
                    f"{run_id}#{entry.get('seq')}"
                stage = stages_by_call.get(call_id, {})
                norm = (trace or {}).get("normalized_response") or {}
                wire = (trace or {}).get("wire_exchanges") or []
                views = {
                    "engine_request": _engine_view(trace, entry, stage),
                    "wire_request": _wire_request_view(trace),
                    "wire_response_raw": _wire_response_view(trace),
                    "normalized_response": ({"response": norm,
                                             "error": trace.get("error")}
                                            if trace else None),
                }
                item = {
                    "kind": "call", "n": n_call, "call_id": call_id,
                    "child_run_id": ch_id, "run_id": run_id,
                    "turn_index": turn_index, "report_seq": entry.get("seq"),
                    "dispatch_status": ("NOT_SENT" if not_sent else
                                        (trace or {}).get("dispatch_status")
                                        or "UNTRACED"),
                    "dispatch_reason": (entry.get("refusal") or
                                        "refused by CreditProbe before "
                                        "provider dispatch") if not_sent
                    else (trace or {}).get("dispatch_reason") or (
                        "" if trace else "no trace recorded (tracing was "
                        "off, or the run predates the trace)"),
                    "purpose": entry.get("purpose"),
                    "phase": entry.get("phase"),
                    "tool_choice": entry.get("tool_choice"),
                    "stage_tags": stage.get("stage_tags") or [],
                    "shared_span": stage.get("shared_span", False),
                    "requested_model": ((trace or {}).get("context") or {})
                    .get("requested_model"),
                    "resolved_model": norm.get("model"),
                    "input_tokens": norm.get("input_tokens"),
                    "output_tokens": norm.get("output_tokens"),
                    "counted_input_tokens": views["engine_request"][
                        "metadata"].get("counted_input_tokens"),
                    "duration_ms": (trace or {}).get("duration_ms"),
                    "stop_reason": norm.get("stop_reason") or
                    entry.get("stop_reason"),
                    "tool_calls": [{"id": c.get("id"), "name": c.get("name")}
                                   for c in _tool_calls(trace or {})],
                    "error": (trace or {}).get("error"),
                    "wire_request_bytes": sum(
                        x["request"]["body_bytes"] for x in wire),
                    "wire_response_bytes": sum(
                        x["response"]["body_bytes"] for x in wire),
                    "wire_attempts": len(wire),
                    "sizes": {v: _size(views[v]) for v in VIEWS},
                }
                if include_bodies:
                    item["views"] = views
                for s in item["stage_tags"]:
                    if s in stage_links:
                        key = ("shared_calls" if item["shared_span"]
                               else "calls")
                        stage_links[s][key].append(n_call)
                call_items.append(item)
                if trace and not not_sent:
                    sent_traces.append(trace)
            # tool round trips, in call order
            ti = 0
            for item in call_items:
                timeline.append(item)
                if item["dispatch_status"] == "NOT_SENT":
                    continue
                trace = sent_traces[ti] if ti < len(sent_traces) else None
                nxt = sent_traces[ti + 1] if ti + 1 < len(sent_traces) \
                    else None
                lo = requested[ti] if ti < len(requested) else None
                hi = requested[ti + 1] if ti + 1 < len(requested) else None
                ti += 1
                seg = [e for e in fevents if lo is not None and e.seq > lo
                       and (hi is None or e.seq < hi)
                       and not e.event_type.startswith("model.")]
                for call in _tool_calls(trace or {}):
                    n_tool += 1
                    returned = _tool_result_in(
                        (nxt or {}).get("engine_request"), call.get("id"))
                    source = "next model request (exact bytes sent)"
                    if returned is None:
                        returned = _tool_result_in({"messages": messages},
                                                   call.get("id"))
                        source = ("frozen stored history (no later model "
                                  "call carried it)")
                    evs = [_event(runs, e) for e in seg]
                    sub_ids = {str((e["detail"] or {}).get("submission_id"))
                               for e in evs if isinstance(e["detail"], dict)}
                    rt = {
                        "kind": "tool", "n": n_tool, "call_n": item["n"],
                        "call_id": item["call_id"], "child_run_id": ch_id,
                        "run_id": run_id, "stage_tags": item["stage_tags"],
                        "model_tool_call": call,
                        "validation": [e for e in evs
                                       if e["event_type"] in _VALIDATION],
                        "execution": [e for e in evs
                                      if e["event_type"] in _EXECUTION],
                        "all_engine_events": evs,
                        "submissions": [subs[s] for s in sorted(sub_ids)
                                        if s in subs],
                        "tool_result_returned": returned,
                        "tool_result_source": source,
                        "tool_result_bytes": _size(returned)["bytes"],
                        "tool_result_sha256": _size(returned)["sha256"],
                        "is_final_response": call.get("name") ==
                        "finalize_response",
                        "event_attribution": "engine events between this "
                                             "call's model.requested and the "
                                             "next one (frozen order)",
                    }
                    for s in rt["stage_tags"]:
                        if s in stage_links:
                            stage_links[s]["tool_roundtrips"].append(n_tool)
                    timeline.append(rt)
        for leftover in pending:        # traces with no frozen report row
            n_call += 1
            timeline.append({"kind": "call", "n": n_call,
                             "call_id": leftover.get("call_id"),
                             "child_run_id": ch_id,
                             "dispatch_status": leftover.get(
                                 "dispatch_status"),
                             "dispatch_reason": "no matching frozen call "
                                                "report row",
                             "error": leftover.get("error"),
                             "sizes": {}})
        ek = eval_children.get(ch_id, {})
        out_children.append({
            "child_run_id": ch_id, "profile_id": child["profile_id"],
            "display_name": ek.get("display_name") or child["profile_id"],
            "execution_state": child["state"],
            "timeline": timeline, "stage_links": stage_links,
            "traced_calls": len(traces.get(ch_id) or []),
        })
    return {
        "comparison_id": cid,
        "trace_flag": io_trace.ENV_FLAG,
        "question_text": spec.get("question_text"),
        "assistance_packet": spec.get("assistance_packet"),
        "policy": {
            "captures": "the actual request/response boundary: engine "
                        "request, wire request, raw response, normalized "
                        "response, and each tool round trip",
            "excluded": "provider credentials (Authorization, API keys, "
                        "cookies, URL secrets) and hidden reasoning "
                        f"({io_trace.HIDDEN})",
            "truncation": "none: bodies are stored as transmitted; tool "
                          "results are exactly what CreditProbe sent, "
                          "including any bounded preview it chose",
        },
        "children": out_children,
    }


def call_detail(coord, cid: str, call_id: str) -> dict[str, Any] | None:
    for ch in build(coord, cid, include_bodies=True)["children"]:
        for item in ch["timeline"]:
            if item.get("kind") == "call" and item.get("call_id") == call_id:
                return item
    return None


# ---- export pack ------------------------------------------------------------

README_LINE = ("Model I/O Trace captures the actual request/response "
               "boundary. Provider credentials and hidden reasoning are "
               "excluded.")


def _html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str)


def export_files(trace: dict[str, Any]
                 ) -> tuple[dict[str, bytes], dict[str, list[dict]]]:
    """model_io/, tool_roundtrips/, jsonl, HTML, manifest, checksums and
    the three workbook tables. Paths and hashes stand in for bodies in the
    workbook (Excel cells hold at most 32,767 characters)."""
    files: dict[str, bytes] = {}
    calls_rows: list[dict] = []
    req_rows: list[dict] = []
    tool_rows: list[dict] = []
    calls_jsonl: list[str] = []
    tools_jsonl: list[str] = []
    html: list[str] = []
    for ch in trace["children"]:
        html.append(f"<h2>{_html_escape(str(ch['display_name']))} "
                    f"({_html_escape(ch['child_run_id'])})</h2>")
        for it in ch["timeline"]:
            if it["kind"] == "call":
                d = f"model_io/call_{it['n']:03d}"
                views = it.get("views") or {}
                meta = {k: v for k, v in it.items() if k != "views"} | {
                    "child_display_name": ch["display_name"],
                    "profile_id": ch["profile_id"]}
                for v in VIEWS:
                    files[f"{d}/{v}.json"] = _pretty(views.get(v)).encode()
                files[f"{d}/metadata.json"] = _pretty(meta).encode()
                calls_jsonl.append(json.dumps(meta | {"views": views},
                                              default=str))
                er = (views.get("engine_request") or {})
                em = er.get("metadata") or {}
                rq = er.get("request") or {}
                msgs = rq.get("messages") or [] if isinstance(rq, dict) \
                    else []
                calls_rows.append({
                    "call_n": it["n"], "call_id": it["call_id"],
                    "child_run_id": it["child_run_id"],
                    "profile_id": ch["profile_id"],
                    "run_id": it.get("run_id"),
                    "dispatch_status": it["dispatch_status"],
                    "dispatch_reason": it.get("dispatch_reason"),
                    "stage_tags": " ".join(it.get("stage_tags") or []),
                    "shared_span": it.get("shared_span"),
                    "purpose": it.get("purpose"), "phase": it.get("phase"),
                    "requested_model": it.get("requested_model"),
                    "resolved_model": it.get("resolved_model"),
                    "input_tokens": it.get("input_tokens"),
                    "output_tokens": it.get("output_tokens"),
                    "duration_ms": it.get("duration_ms"),
                    "stop_reason": it.get("stop_reason"),
                    "tool_calls": " ".join(t["name"] or "" for t in
                                           it.get("tool_calls") or []),
                    "error": (it.get("error") or {}).get("code") or
                    (it.get("error") or {}).get("type") or "",
                    "wire_request_bytes": it.get("wire_request_bytes"),
                    "wire_response_bytes": it.get("wire_response_bytes"),
                    **{f"{v}_bytes": (it.get("sizes") or {}).get(
                        v, {}).get("bytes") for v in VIEWS},
                    **{f"{v}_sha256": (it.get("sizes") or {}).get(
                        v, {}).get("sha256") for v in VIEWS},
                    "path": d})
                roles: dict[str, int] = {}
                for m in msgs:
                    if isinstance(m, dict):
                        roles[m.get("role", "?")] = roles.get(
                            m.get("role", "?"), 0) + 1
                req_rows.append({
                    "call_n": it["n"], "call_id": it["call_id"],
                    "profile_id": ch["profile_id"],
                    "system_bytes": (em.get("request_bytes") or {}).get(
                        "system"),
                    "messages_bytes": (em.get("request_bytes") or {}).get(
                        "messages"),
                    "tools_bytes": (em.get("request_bytes") or {}).get(
                        "tools"),
                    "message_count": len(msgs),
                    "user_messages": roles.get("user", 0),
                    "assistant_messages": roles.get("assistant", 0),
                    "tools_offered": len(rq.get("tools") or [])
                    if isinstance(rq, dict) else None,
                    "tool_choice": json.dumps(rq.get("tool_choice"))
                    if isinstance(rq, dict) else None,
                    "max_tokens": rq.get("max_tokens")
                    if isinstance(rq, dict) else None,
                    "timeout": rq.get("timeout")
                    if isinstance(rq, dict) else None,
                    "output_config": json.dumps(rq.get("output_config"))
                    if isinstance(rq, dict) else None,
                    "request_controls": json.dumps(
                        em.get("request_controls")),
                    "context_capacity_tokens": em.get(
                        "context_capacity_tokens"),
                    "counted_input_tokens": em.get("counted_input_tokens"),
                    "counted_input_tokens_source": em.get(
                        "counted_input_tokens_source"),
                    "reserved_output_tokens": em.get(
                        "reserved_output_tokens"),
                    "call_timeout_seconds": em.get("call_timeout_seconds"),
                    "engine_request_path": f"{d}/engine_request.json"})
                html.append(
                    f"<details><summary><b>Call {it['n']}</b> · "
                    f"{_html_escape(' + '.join(it.get('stage_tags') or []))}"
                    f" · {_html_escape(str(it.get('purpose')))} · "
                    f"{_html_escape(str(it['dispatch_status']))}</summary>"
                    + "".join(
                        f"<details><summary>[{v}]</summary><pre>"
                        f"{_html_escape(_pretty(views.get(v)))}</pre>"
                        f"</details>" for v in VIEWS)
                    + "</details>")
            else:
                name = f"tool_roundtrips/tool_{it['n']:03d}.json"
                files[name] = _pretty(it).encode()
                tools_jsonl.append(json.dumps(it, default=str))
                tool_rows.append({
                    "tool_n": it["n"], "call_n": it["call_n"],
                    "call_id": it["call_id"],
                    "child_run_id": it["child_run_id"],
                    "profile_id": ch["profile_id"],
                    "stage_tags": " ".join(it.get("stage_tags") or []),
                    "tool_use_id": (it["model_tool_call"] or {}).get("id"),
                    "tool_name": (it["model_tool_call"] or {}).get("name"),
                    "validation": " ".join(
                        f"{e['event_type']}:{e['status']}"
                        for e in it["validation"]),
                    "execution": " ".join(
                        f"{e['event_type']}:{e['status']}"
                        for e in it["execution"]),
                    "submissions": " ".join(
                        str(s.get("submission_id")) for s in
                        it["submissions"]),
                    "tool_result_bytes": it["tool_result_bytes"],
                    "tool_result_sha256": it["tool_result_sha256"],
                    "tool_result_source": it["tool_result_source"],
                    "is_final_response": it["is_final_response"],
                    "path": name})
                html.append(
                    f"<details style='margin-left:2em'><summary>Tool "
                    f"round-trip {it['n']} · "
                    f"{_html_escape(str((it['model_tool_call'] or {}).get('name')))}"
                    f"</summary><pre>{_html_escape(_pretty(it))}</pre>"
                    f"</details>")
    files["model_io.jsonl"] = ("\n".join(calls_jsonl) + "\n").encode()
    files["tool_roundtrips.jsonl"] = ("\n".join(tools_jsonl) + "\n").encode()
    files["MODEL_IO_TRACE.html"] = (
        "<!doctype html><meta charset=utf-8><meta http-equiv="
        "\"Content-Security-Policy\" content=\"default-src 'none'; "
        "style-src 'unsafe-inline'\"><title>Model I/O Trace</title>"
        "<style>body{font:13px system-ui;margin:20px}pre{white-space:"
        "pre-wrap;word-break:break-all;background:#f4f4f4;padding:6px}"
        "</style>"
        f"<h1>Model I/O Trace — {_html_escape(trace['comparison_id'])}</h1>"
        f"<p><b>{_html_escape(README_LINE)}</b></p>"
        f"<p>{_html_escape(trace['policy']['truncation'])}.</p>"
        + "".join(html)).encode()
    if trace.get("assistance_packet") is not None:
        files["assistance_packet.json"] = _pretty(
            trace["assistance_packet"]).encode()
    listing = {n: {"bytes": len(b),
                   "sha256": io_trace.sha256_text(b)}
               for n, b in sorted(files.items())}
    files["MODEL_IO_MANIFEST.json"] = _pretty({
        "comparison_id": trace["comparison_id"],
        "trace_flag": trace["trace_flag"], "policy": trace["policy"],
        "statement": README_LINE,
        "calls": len(calls_rows), "tool_roundtrips": len(tool_rows),
        "files": listing}).encode()
    files["MODEL_IO_CHECKSUMS.sha256"] = "".join(
        f"{io_trace.sha256_text(files[n])}  {n}\n"
        for n in sorted(files)).encode()
    return files, {"model_calls": calls_rows, "request_summary": req_rows,
                   "tool_roundtrip_rows": tool_rows}
