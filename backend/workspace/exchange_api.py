"""
Trace > LLM Exchange, and the AI Model Lab, over ONE set of records.

Every view here READS: the exchange store written by `backend/llm/exchange.py`,
and the run's own persisted events and artifacts. Opening a trace therefore
makes zero model calls -- the only route in this module that calls a model is
`POST /model-lab/replay`, which a person presses deliberately, which records
its call as a new exchange linked to the one it replays, and which refuses
when no target is configured rather than substituting one.
"""

from __future__ import annotations

import csv
import io
import json
import time
import zipfile
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.llm import exchange
from backend.workspace import access

router = APIRouter(tags=["workspace-llm-exchange"])


def exchange_store() -> exchange.ExchangeStore:
    return exchange.store_at(exchange.store_path_for(access.config()))


def _iso_to_epoch(value: str) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")
                                      ).timestamp()
    except ValueError:
        return 0.0


def _owned_run(run_id: str, who: dict[str, Any]) -> Any:
    record = access.run_store().get_run(run_id)
    if record is None or str(record.tenant_id) != access.tenant_of(who):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such run is available to "
                                             "you."})
    return record


# ---- the run view -----------------------------------------------------------

def context_growth(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How the request grew call by call: MEASURED bytes, EXACT billed tokens."""
    out = []
    previous = 0
    for call in calls:
        comp = call.get("context_composition") or {}
        total = int(comp.get("total_bytes") or 0)
        usage = call.get("usage") or {}
        out.append({
            "seq": call.get("seq"), "exchange_id": call.get("exchange_id"),
            "purpose": call.get("purpose"),
            "total_bytes": total, "growth_bytes": total - previous,
            "messages": comp.get("message_count", 0),
            "tools": comp.get("tool_count", 0),
            "system_bytes": (comp.get("totals_bytes") or {}).get("system", 0),
            "tool_schema_bytes": (comp.get("totals_bytes") or {}).get(
                "tool_schema", 0),
            "tool_result_bytes": (comp.get("totals_bytes") or {}).get(
                "tool_result", 0),
            "input_tokens_exact": usage.get("input_tokens", 0),
            "output_tokens_exact": usage.get("output_tokens", 0),
            "token_basis": "provider-reported usage (exact)"})
        previous = total
    return out


def data_visibility(run: Any, calls: list[dict[str, Any]]) -> dict[str, Any]:
    """AVAILABLE TO CREDITPROBE versus ACTUALLY TRANSMITTED TO THE MODEL.

    Available: the release the run was pinned to (every relation's row count
    from its manifest) and every artifact the run computed (rows it produced,
    which can exceed the rows it stored). Transmitted: the tool results that
    appear in the requests the model was actually sent -- de-duplicated by
    tool_use id, because the conversation is re-sent on every call and a
    result sent five times is still one result.
    """
    from backend.cockpit_v4 import lake as lake_mod

    store = access.run_store()
    release_rows: dict[str, int] = {}
    try:
        manifest = lake_mod.read_manifest(str(run.release_id))
        release_rows = {str(k): int(v) for k, v in (
            manifest.get("row_counts") or {}).items()}
    except Exception:  # noqa: BLE001 - a legacy release has no V4 manifest
        release_rows = {}
    artifacts = []
    for artifact_id in store.artifact_ids_for_run(run.run_id,
                                                  tenant_id=run.tenant_id):
        found = store.get_artifact(artifact_id, tenant_id=run.tenant_id) or {}
        scope = found.get("scope") or {}
        artifacts.append({
            "artifact_id": artifact_id, "kind": found.get("kind"),
            "rows_stored": found.get("row_count", 0),
            "rows_produced": int(scope.get("produced_rows") or
                                 found.get("row_count") or 0),
            "relations": scope.get("referenced_relations") or []})
    unique: dict[str, dict[str, Any]] = {}
    per_call = []
    for call in calls:
        sent = call.get("transmitted_data") or {}
        per_call.append({"seq": call.get("seq"),
                         "tool_results": sent.get("tool_results", 0),
                         "rows": sent.get("rows", 0),
                         "bytes": sent.get("bytes", 0)})
        for item in sent.get("detail") or []:
            unique.setdefault(str(item.get("tool_use_id")), item)
    return {
        "available_to_creditprobe": {
            "release_id": run.release_id,
            "release_relations": release_rows,
            "release_rows_total": sum(release_rows.values()),
            "artifacts": artifacts,
            "artifact_rows_produced": sum(a["rows_produced"]
                                          for a in artifacts)},
        "actually_transmitted_to_model": {
            "unique_tool_results": len(unique),
            "rows": sum(int(i.get("rows") or 0) for i in unique.values()),
            "bytes": sum(int(i.get("bytes") or 0) for i in unique.values()),
            "per_call": per_call,
            "basis": ("rows counted inside tool_result payloads of the "
                      "requests actually sent; de-duplicated by tool_use id")},
    }


def timeline(calls: list[dict[str, Any]], events: list[Any]
             ) -> list[dict[str, Any]]:
    """Model calls and the deterministic CreditProbe activity between them."""
    items: list[dict[str, Any]] = []
    for call in calls:
        items.append({"at": call.get("started_at"), "kind": "llm_call",
                      "seq": call.get("seq"),
                      "exchange_id": call.get("exchange_id"),
                      "label": f"Model call {call.get('seq')} — "
                               f"{call.get('purpose') or 'generation'}",
                      "detail": f"{call.get('resolved_model')} · "
                                f"{call.get('provider_ms')} ms · "
                                f"{call.get('stop_reason') or call.get('status')}"})
    for event in events:
        data = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        items.append({"at": _iso_to_epoch(data.get("occurred_at", "")),
                      "kind": "creditprobe_event",
                      "event_type": data.get("event_type"),
                      "stage": data.get("stage"),
                      "label": data.get("public_message") or
                      data.get("event_type"),
                      "detail": " · ".join(str(x) for x in (
                          data.get("operation"), data.get("status"))
                          if x)})
    items.sort(key=lambda i: (i.get("at") or 0))
    return items


def run_view(run_id: str, who: dict[str, Any]) -> dict[str, Any]:
    access.require_exchange_reader(who)
    run = _owned_run(run_id, who)
    calls = exchange_store().for_run(run_id, tenant_id=run.tenant_id)
    events = access.run_store().events_since(run_id, 0, 5000)
    return {
        "run_id": run_id, "thread_id": run.thread_id,
        "question": run.question, "release_id": run.release_id,
        "recorder": {"flag": exchange.FLAG, "enabled": exchange.enabled(),
                     "record_version": exchange.RECORD_VERSION,
                     "calls_recorded": len(calls)},
        "calls": calls,
        "timeline": timeline(calls, events),
        "context_growth": context_growth(calls),
        "data_visibility": data_visibility(run, calls),
        "notes": [
            "Each call shows the canonical request CreditProbe handed its "
            "provider adapter, the adapter's provider-native request, the raw "
            "provider response where the SDK exposes it, and the normalized "
            "response the run continued with.",
            "Secrets are redacted before storage. Hidden model reasoning is "
            "never requested, recorded or shown.",
            "Opening this view made no model call."],
    }


@router.get("/llm-exchange/runs/{run_id}")
async def get_run_exchange(run_id: str,
                           who: dict[str, Any] = Depends(v4routes.principal)
                           ) -> dict[str, Any]:
    return run_view(run_id, who)


@router.get("/llm-exchange/calls/{exchange_id}")
async def get_exchange(exchange_id: str,
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    access.require_exchange_reader(who)
    found = exchange_store().get(exchange_id,
                                 tenant_id=access.tenant_of(who))
    if found is None:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such exchange is available "
                                             "to you."})
    return found


# ---- export ---------------------------------------------------------------------

def readable_request(call: dict[str, Any]) -> str:
    req = call.get("canonical_request") or {}
    lines = [f"# Call {call.get('seq')} — {call.get('purpose')}", "",
             f"Model requested: {call.get('requested_model')}  ",
             f"Provider/adapter: {call.get('provider')} / "
             f"{call.get('adapter')}", "", "## System", ""]
    system = req.get("system")
    for block in system if isinstance(system, list) else [system]:
        lines.append(block.get("text", "") if isinstance(block, dict)
                     else str(block or ""))
        lines.append("")
    lines += ["## Tools offered", ""]
    for tool in req.get("tools") or []:
        lines.append(f"- {tool.get('name')}: {tool.get('description', '')}")
    lines += ["", f"Tool choice: {json.dumps(req.get('tool_choice'))}", "",
              "## Messages", ""]
    for i, message in enumerate(req.get("messages") or []):
        lines.append(f"### {i + 1}. {message.get('role')}")
        content = message.get("content")
        if isinstance(content, str):
            lines.append(content)
        else:
            for block in content or []:
                lines.append("```json")
                lines.append(json.dumps(block, ensure_ascii=False, indent=2,
                                        default=str))
                lines.append("```")
        lines.append("")
    return "\n".join(lines)


def readable_response(call: dict[str, Any]) -> str:
    norm = call.get("normalized_response") or {}
    lines = [f"# Response to call {call.get('seq')}", "",
             f"Resolved model: {call.get('resolved_model')}  ",
             f"Stop reason: {norm.get('stop_reason') or call.get('status')}  ",
             f"Usage: {json.dumps(norm.get('usage') or {})}", "",
             "## Text", "", str(norm.get("text") or "(none)"), "",
             "## Tool calls", ""]
    for tc in norm.get("tool_calls") or []:
        lines.append(f"### {tc.get('name')} ({tc.get('id')})")
        lines.append("```json")
        lines.append(json.dumps(tc.get("input"), ensure_ascii=False,
                                indent=2, default=str))
        lines.append("```")
    if call.get("error"):
        lines += ["", "## Error", "", str(call["error"])]
    return "\n".join(lines)


def export_package(view: dict[str, Any]) -> bytes:
    """llm_exchange/call_N/{...} + llm_calls.csv + composition + growth."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        def dump(name: str, value: Any) -> None:
            zf.writestr(name, json.dumps(value, ensure_ascii=False, indent=2,
                                         default=str))

        for call in view["calls"]:
            base = f"llm_exchange/call_{call.get('seq')}"
            dump(f"{base}/canonical_request.json",
                 call.get("canonical_request"))
            dump(f"{base}/provider_request.json", call.get("adapter_request"))
            dump(f"{base}/provider_response.json", call.get("raw_response"))
            dump(f"{base}/normalized_response.json",
                 call.get("normalized_response"))
            zf.writestr(f"{base}/readable_request.md", readable_request(call))
            zf.writestr(f"{base}/readable_response.md",
                        readable_response(call))
            dump(f"{base}/metadata.json", {
                k: call.get(k) for k in (
                    "exchange_id", "run_id", "thread_id", "seq", "purpose",
                    "role", "provider", "adapter", "requested_model",
                    "resolved_model", "status", "error", "stop_reason",
                    "request_id", "started_at", "ended_at", "provider_ms",
                    "settings", "usage", "hashes", "redactions",
                    "adapter_translation", "replay_of")})
        calls_csv = io.StringIO()
        writer = csv.writer(calls_csv)
        writer.writerow(["seq", "exchange_id", "purpose", "provider",
                         "adapter", "requested_model", "resolved_model",
                         "status", "stop_reason", "provider_ms",
                         "input_tokens", "output_tokens", "request_bytes",
                         "canonical_request_sha256"])
        for call in view["calls"]:
            usage = call.get("usage") or {}
            writer.writerow([
                call.get("seq"), call.get("exchange_id"), call.get("purpose"),
                call.get("provider"), call.get("adapter"),
                call.get("requested_model"), call.get("resolved_model"),
                call.get("status"), call.get("stop_reason"),
                call.get("provider_ms"), usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                (call.get("context_composition") or {}).get("total_bytes", 0),
                (call.get("hashes") or {}).get("canonical_request", "")])
        zf.writestr("llm_calls.csv", calls_csv.getvalue())
        comp_csv = io.StringIO()
        writer = csv.writer(comp_csv)
        writer.writerow(["seq", "component", "detail", "bytes",
                         "estimated_tokens", "token_basis"])
        for call in view["calls"]:
            for part in (call.get("context_composition") or {}).get(
                    "parts") or []:
                writer.writerow([call.get("seq"), part["component"],
                                 part["detail"], part["bytes"],
                                 part["estimated_tokens"],
                                 part["token_basis"]])
        zf.writestr("context_composition.csv", comp_csv.getvalue())
        growth_csv = io.StringIO()
        writer = csv.writer(growth_csv)
        fields = ["seq", "exchange_id", "purpose", "total_bytes",
                  "growth_bytes", "messages", "tools", "system_bytes",
                  "tool_schema_bytes", "tool_result_bytes",
                  "input_tokens_exact", "output_tokens_exact"]
        writer.writerow(fields)
        for row in view["context_growth"]:
            writer.writerow([row.get(f) for f in fields])
        zf.writestr("context_growth.csv", growth_csv.getvalue())
        dump("data_visibility.json", view["data_visibility"])
        dump("timeline.json", view["timeline"])
    return buffer.getvalue()


@router.get("/llm-exchange/runs/{run_id}/export")
async def export_run_exchange(run_id: str,
                              who: dict[str, Any] = Depends(
                                  v4routes.principal)) -> Response:
    view = run_view(run_id, who)
    return Response(
        content=export_package(view), media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="llm_exchange_{run_id}.zip"'})


# ---- AI Model Lab ----------------------------------------------------------

@router.get("/model-lab/exchanges")
async def model_lab_exchanges(model: str = Query(""), purpose: str = Query(""),
                              run_id: str = Query(""),
                              limit: int = Query(200, ge=1, le=1000),
                              who: dict[str, Any] = Depends(
                                  v4routes.principal)) -> dict[str, Any]:
    access.require_exchange_reader(who)
    rows = exchange_store().search(tenant_id=access.tenant_of(who),
                                   model=model, purpose=purpose,
                                   run_id=run_id, limit=limit)
    models = sorted({r["resolved_model"] for r in rows if
                     r.get("resolved_model")})
    return {"exchanges": rows, "models": models,
            "source": "the same LLM exchange records the Trace shows"}


def _diff_list(a: list[Any], b: list[Any]) -> list[dict[str, Any]]:
    out = []
    for i in range(max(len(a), len(b))):
        left = a[i] if i < len(a) else None
        right = b[i] if i < len(b) else None
        out.append({"index": i, "same": exchange.digest(left) ==
                    exchange.digest(right)})
    return out


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Two calls side by side: what was sent, what came back, what it cost."""
    ra, rb = a.get("canonical_request") or {}, b.get("canonical_request") or {}
    na, nb = a.get("normalized_response") or {}, b.get(
        "normalized_response") or {}

    def summary(call: dict[str, Any]) -> dict[str, Any]:
        norm = call.get("normalized_response") or {}
        return {"exchange_id": call.get("exchange_id"),
                "provider": call.get("provider"),
                "adapter": call.get("adapter"),
                "model": call.get("resolved_model"),
                "purpose": call.get("purpose"),
                "status": call.get("status"),
                "stop_reason": call.get("stop_reason"),
                "provider_ms": call.get("provider_ms"),
                "usage": call.get("usage"),
                "request_bytes": (call.get("context_composition") or {}).get(
                    "total_bytes"),
                "tool_calls": [{"name": t.get("name"), "input": t.get("input")}
                               for t in norm.get("tool_calls") or []],
                "text": norm.get("text"),
                "adapter_translation": call.get("adapter_translation")}

    names_a = [t.get("name") for t in na.get("tool_calls") or []]
    names_b = [t.get("name") for t in nb.get("tool_calls") or []]
    return {
        "a": summary(a), "b": summary(b),
        "request": {
            "same_canonical_request": (a.get("hashes") or {}).get(
                "canonical_request") == (b.get("hashes") or {}).get(
                "canonical_request"),
            "same_system": exchange.digest(ra.get("system")) ==
            exchange.digest(rb.get("system")),
            "same_tools": exchange.digest(ra.get("tools")) ==
            exchange.digest(rb.get("tools")),
            "same_tool_choice": ra.get("tool_choice") == rb.get(
                "tool_choice"),
            "messages": _diff_list(ra.get("messages") or [],
                                   rb.get("messages") or []),
            "note": ("a replay sends the recorded canonical request "
                     "unchanged except for the model id")},
        "response": {
            "same_tool_sequence": names_a == names_b,
            "tool_names_a": names_a, "tool_names_b": names_b,
            "same_arguments": exchange.digest(
                [t.get("input") for t in na.get("tool_calls") or []]) ==
            exchange.digest([t.get("input") for t in
                             nb.get("tool_calls") or []]),
            "same_stop_reason": na.get("stop_reason") == nb.get(
                "stop_reason")},
    }


@router.get("/model-lab/compare")
async def model_lab_compare(a: str = Query(...), b: str = Query(...),
                            who: dict[str, Any] = Depends(v4routes.principal)
                            ) -> dict[str, Any]:
    access.require_exchange_reader(who)
    store = exchange_store()
    tenant = access.tenant_of(who)
    left, right = store.get(a, tenant_id=tenant), store.get(b, tenant_id=tenant)
    if left is None or right is None:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "Both exchanges must be "
                                             "available to you."})
    return compare(left, right)


def targets() -> list[dict[str, Any]]:
    from backend.cockpit_v4 import service as v4service
    from backend.llm import openai_compatible

    open_weight = openai_compatible.from_environment()
    return [
        {"target": "anthropic", "label": "Anthropic (Cockpit credential)",
         "configured": v4service.credential_status() == "PRESENT",
         "requires": "COCKPIT_ANTHROPIC_API_KEY"},
        {"target": "open_weight",
         "label": (f"Open-weight: {open_weight.model}" if open_weight
                   else "Open-weight (OpenAI-compatible endpoint)"),
         "configured": open_weight is not None,
         "requires": f"{openai_compatible.URL_VAR} and "
                     f"{openai_compatible.MODEL_VAR}"},
    ]


@router.get("/model-lab/targets")
async def model_lab_targets(who: dict[str, Any] = Depends(v4routes.principal)
                            ) -> dict[str, Any]:
    access.require_exchange_reader(who)
    return {"targets": targets(),
            "note": "A replay is a real, billable model call. It runs only "
                    "when you press Replay, and only against a configured "
                    "target; nothing is substituted when a target is "
                    "missing."}


class Replay(BaseModel):
    exchange_id: str = Field(min_length=6, max_length=80)
    target: str = Field(pattern="^(anthropic|open_weight)$")
    model: str = Field(default="", max_length=200)


def _provider_for(target: str) -> Any:
    from backend.cockpit_v4 import service as v4service
    from backend.llm import openai_compatible
    from backend.llm.anthropic_provider import AnthropicProvider

    if target == "open_weight":
        provider = openai_compatible.from_environment()
        if provider is None:
            return None
        return provider
    if v4service.credential_status() != "PRESENT":
        return None
    import os

    from backend.cockpit_v4 import config as v4config
    return AnthropicProvider(api_key=os.environ.get(v4config.CREDENTIAL_VAR,
                                                    ""))


def replay(original: dict[str, Any], provider: Any, *, model: str,
           store: exchange.ExchangeStore, who: dict[str, Any]
           ) -> dict[str, Any]:
    """Send the recorded canonical request to another model; record the call."""
    request = dict(original.get("canonical_request") or {})
    kwargs = {k: request[k] for k in ("system", "messages", "tools",
                                      "max_tokens", "tool_choice",
                                      "output_config") if k in request}
    kwargs["model"] = model or getattr(provider, "model", "")
    kwargs["purpose"] = f"model_lab_replay:{original.get('purpose', '')}"
    kwargs["role"] = "ai_model_lab"
    kwargs["allow_retry"] = False
    binding = exchange.Binding(
        run_id=f"lab-{original.get('run_id') or original.get('exchange_id')}",
        thread_id=str(original.get("thread_id") or ""),
        tenant_id=access.tenant_of(who), domain_id=str(
            original.get("domain_id") or ""),
        surface="ai_model_lab", replay_of=str(original.get("exchange_id")))
    recorder = exchange.RecordingProvider(provider, store, binding)
    started = time.time()
    try:
        recorder.converse(**kwargs)
        status = "OK"
        error = ""
    except Exception as exc:  # noqa: BLE001 - recorded, reported
        status, error = "ERROR", exchange.scrub_text(str(exc), "$", [])[:500]
    rows = store.search(tenant_id=access.tenant_of(who),
                        run_id=binding.run_id, limit=50)
    newest = next((r for r in rows if r.get("replay_of") ==
                   original.get("exchange_id") and r["started_at"] >=
                   started - 1), None)
    return {"status": status, "error": error,
            "replay_exchange_id": newest["exchange_id"] if newest else "",
            "replay_of": original.get("exchange_id")}


@router.post("/model-lab/replay")
async def model_lab_replay(body: Replay,
                           who: dict[str, Any] = Depends(v4routes.principal)
                           ) -> dict[str, Any]:
    access.require_exchange_reader(who)
    store = exchange_store()
    original = store.get(body.exchange_id, tenant_id=access.tenant_of(who))
    if original is None:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such exchange is available "
                                             "to you."})
    provider = _provider_for(body.target)
    if provider is None:
        raise HTTPException(409, {
            "error_code": "TARGET_NOT_CONFIGURED",
            "message": f"The {body.target} target is not configured, so "
                       f"nothing was sent and nothing was substituted."})
    return replay(original, provider, model=body.model, store=store, who=who)


__all__ = ["compare", "context_growth", "data_visibility", "export_package",
           "readable_request", "readable_response", "replay", "router",
           "run_view", "targets", "timeline"]
