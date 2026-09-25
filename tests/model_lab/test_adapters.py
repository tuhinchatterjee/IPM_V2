"""A01-A16: protocol translation, identity and route honesty.

Scripted adapter fixtures prove the adapter handles each wire shape. The
end-to-end test runs an OpenAI-compatible MOCK SERVER (httpx transport)
through the real frozen engine; it proves translation, not that any real
model would act the same way.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from conftest import QUESTION, ROOT, make_service

from backend.cockpit_v4.provider import ProviderFailure
from backend.model_lab.adapters.openai_compat import (
    OpenAICompatProvider,
    assemble_stream,
    translate_ollama_native,
    translate_request,
    translate_response,
)

TOOLS = json.loads((ROOT / "docs/model_comparison/TOOL_CONTRACTS.json")
                   .read_text())["variants"]["corporate"][
    "answer_tools (full_tools)"]["tools"]
SQL = ("SELECT sector, SUM(ead_sar_mn) AS \"Σ EAD\" -- 'ünïcode' \"q\"\n"
       "FROM corp_facility_quarter\tWHERE note = 'a\\nb' AND x = '€'")


def _history():
    return [
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "running"},
            {"type": "tool_use", "id": "tu-1", "name": "execute_analysis",
             "input": {"objective": "o", "steps": [{"step_id": "s1",
                                                    "language": "sql",
                                                    "code": SQL}]}},
            {"type": "tool_use", "id": "tu-2", "name": "execute_analysis",
             "input": {"objective": "p", "steps": []}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu-1",
             "content": '{"status": "rejected", "error_code": '
                        '"SQL_VALIDATION", "message": "col x not found"}',
             "is_error": True},
            {"type": "tool_result", "tool_use_id": "tu-2",
             "content": "boom", "is_error": True}]},
    ]


def test_A02_roles_order_and_system_precedence():
    body, _ = translate_request(
        system=[{"type": "text", "text": "RULES"},
                {"type": "text", "text": "CATALOG"}],
        messages=_history(), tools=TOOLS, tool_choice=None, max_tokens=99,
        model="m")
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "tool"]
    assert body["messages"][0]["content"] == "RULES\n\nCATALOG"
    ids = [m["tool_call_id"] for m in body["messages"] if m["role"] == "tool"]
    assert ids == ["tu-1", "tu-2"]              # A07: order + pairing


def test_A03_actual_schemas_survive_conversion():
    body, _ = translate_request(system=[], messages=[], tools=TOOLS,
                                tool_choice=None, max_tokens=1, model="m")
    for src, dst in zip(TOOLS, body["tools"], strict=True):
        assert dst["function"]["name"] == src["name"]
        assert dst["function"]["parameters"] == src["input_schema"]


def test_A04_code_bytes_round_trip():
    body, _ = translate_request(system=[], messages=_history(), tools=None,
                                tool_choice=None, max_tokens=1, model="m")
    asst = next(m for m in body["messages"] if m["role"] == "assistant")
    args = asst["tool_calls"][0]["function"]["arguments"]
    assert json.loads(args)["steps"][0]["code"] == SQL
    back = translate_response({"choices": [{"message": {"tool_calls": [
        {"id": "c1", "function": {"name": "execute_analysis",
                                  "arguments": args}}]},
        "finish_reason": "tool_calls"}]}, seq=1)
    assert back.tool_calls[0]["input"]["steps"][0]["code"] == SQL


def test_A05_streamed_fragments_assemble_into_one_complete_call():
    args = json.dumps({"objective": "o", "steps": [{"code": SQL}]},
                      ensure_ascii=False)
    parts = [args[:7], args[7:30], args[30:]]
    chunks = [{"id": "r", "model": "m", "choices": [{"delta": {
        "tool_calls": [{"index": 0, "id": "c9", "function": {
            "name": "execute_analysis", "arguments": parts[0]}}]}}]}]
    chunks += [{"choices": [{"delta": {"tool_calls": [{"index": 0,
               "function": {"name": "execute_analysis",   # repeated name
                            "arguments": p}}]}}]} for p in parts[1:]]
    chunks += [{"choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4}}]
    r = assemble_stream(iter(chunks), seq=1, t0=0.0, clock=lambda: 0.001)
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0]["input"]["steps"][0]["code"] == SQL
    assert r.first_protocol_event_ms is not None


def test_A05_cumulative_stream_and_interleaved_calls():
    a, b = json.dumps({"v": 1}), json.dumps({"v": 2})
    chunks = [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "x", "function": {"name": "t",
                                                 "arguments": a[:3]}},
            {"index": 1, "id": "y", "function": {"name": "t",
                                                 "arguments": b[:2]}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 1, "function": {"arguments": b}},       # cumulative
            {"index": 0, "function": {"arguments": a[3:]}}]}}]},  # delta
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
    r = assemble_stream(iter(chunks), seq=1, t0=0.0)
    assert [c["input"]["v"] for c in r.tool_calls] == [1, 2]
    assert [c["id"] for c in r.tool_calls] == ["x", "y"]


def test_A05_a_truncated_stream_never_dispatches_partial_json():
    chunks = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x",
               "function": {"name": "t", "arguments": '{"v": '}}]}}]}]
    with pytest.raises(ProviderFailure):
        assemble_stream(iter(chunks), seq=1, t0=0.0)   # no finish reason
    bad = chunks + [{"choices": [{"delta": {},
                                  "finish_reason": "tool_calls"}]}]
    with pytest.raises(ProviderFailure) as e:
        assemble_stream(iter(bad), seq=1, t0=0.0)
    assert e.value.detail.get("origin") == "model_output"


def test_A06_tool_only_and_text_only_keep_their_meaning():
    tool_only = translate_response({"choices": [{"message": {
        "content": None, "tool_calls": [{"id": "a", "function": {
            "name": "t", "arguments": "{}"}}]}, "finish_reason": "stop"}]},
        seq=1)
    assert tool_only.stop_reason == "tool_use"      # not an empty success
    assert tool_only.text == "" and tool_only.tool_calls
    text_only = translate_response({"choices": [{"message": {
        "content": "prose"}, "finish_reason": "stop"}]}, seq=1)
    assert text_only.stop_reason == "end_turn" and not text_only.tool_calls


def test_A07_missing_ids_are_minted_and_recorded():
    r = translate_response({"choices": [{"message": {"tool_calls": [
        {"function": {"name": "t", "arguments": "{}"}},
        {"function": {"name": "t", "arguments": "{}"}}]},
        "finish_reason": "tool_calls"}]}, seq=4)
    assert [c["id"] for c in r.tool_calls] == ["lab_call_4_0", "lab_call_4_1"]
    assert r.translation_notes


def test_A08_error_feedback_is_preserved():
    body, notes = translate_request(system=[], messages=_history(),
                                    tools=None, tool_choice=None,
                                    max_tokens=1, model="m")
    tools = [m for m in body["messages"] if m["role"] == "tool"]
    assert json.loads(tools[0]["content"])["error_code"] == "SQL_VALIDATION"
    assert tools[1]["content"] == "ERROR: boom"
    assert notes


def test_A09_forced_and_named_tool_modes_are_mapped_or_disclosed():
    b, _ = translate_request(system=[], messages=[], tools=TOOLS,
                             tool_choice={"type": "tool",
                                          "name": "inspect_catalog",
                                          "disable_parallel_tool_use": True},
                             max_tokens=1, model="m")
    assert b["tool_choice"] == {"type": "function",
                                "function": {"name": "inspect_catalog"}}
    assert b["parallel_tool_calls"] is False
    b, _ = translate_request(system=[], messages=[], tools=TOOLS,
                             tool_choice={"type": "any"}, max_tokens=1,
                             model="m")
    assert b["tool_choice"] == "required"
    b, notes = translate_request(system=[], messages=[], tools=TOOLS,
                                 tool_choice={"type": "any"}, max_tokens=1,
                                 model="m", native_ollama=True)
    assert "tool_choice" not in b and any("NOT enforced" in n for n in notes)


def test_A10_A11_truncation_maps_to_max_tokens_and_counters_are_native():
    r = translate_response({"choices": [{"message": {"content": "x"},
                                         "finish_reason": "length"}],
                            "usage": {"prompt_tokens": 100,
                                      "completion_tokens": 50,
                                      "prompt_tokens_details":
                                      {"cached_tokens": 30}}}, seq=1)
    assert r.stop_reason == "max_tokens"
    assert r.input_tokens == 70 and r.cache_read_tokens == 30   # M08
    assert r.native_usage["prompt_tokens"] == 100              # M07
    unknown = translate_response({"choices": [{"message": {},
                                  "finish_reason": "weird"}]}, seq=1)
    assert unknown.stop_reason == "weird"   # engine refuses; not guessed


def test_M07_ollama_native_counters_convert_once():
    r = translate_ollama_native({"model": "q", "done": True,
                                 "done_reason": "stop",
                                 "message": {"content": "hi"},
                                 "prompt_eval_count": 12, "eval_count": 5,
                                 "eval_duration": 2_000_000_000,
                                 "load_duration": 500_000_000}, seq=1)
    assert r.input_tokens == 12 and r.output_tokens == 5
    assert r.native_timing["eval_duration_ms"] == 2000.0
    assert r.native_usage["eval_duration"] == 2_000_000_000


def _mock(handler):
    return httpx.MockTransport(handler)


def test_A01_A12_identity_errors_and_endpoint_rules():
    p = OpenAICompatProvider(base_url="http://127.0.0.1:1/v1", model="qwen",
                             transport=_mock(lambda r: httpx.Response(429,
                                                                      text="slow")),
                             stream=False)
    with pytest.raises(ProviderFailure) as e:
        p.converse(system=[], messages=[{"role": "user", "content": "x"}],
                   model="qwen")
    assert e.value.code == "PROVIDER_RATE_LIMIT"
    with pytest.raises(ProviderFailure):
        p.converse(system=[], messages=[], model="other-model")   # A01
    with pytest.raises(ValueError):
        OpenAICompatProvider(base_url="http://10.0.0.5/v1", model="m")
    with pytest.raises(ValueError):
        OpenAICompatProvider(base_url="http://gpu.example/v1", model="m",
                             endpoint_class="remote_gpu")


def test_A12_timeouts_are_transport_failures_and_not_retried_here():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)
    p = OpenAICompatProvider(base_url="http://127.0.0.1:1/v1", model="m",
                             transport=_mock(handler), stream=False)
    with pytest.raises(ProviderFailure) as e:
        p.converse(system=[], messages=[], model="m", timeout=1)
    assert e.value.retry_class == "transport" and calls["n"] == 1


# ---- end to end: an OpenAI-compatible mock server through the real engine --

def _openai_reference_server():
    """Plays the reference strategy in OpenAI wire format, streamed."""
    from backend.model_lab.adapters.fixture import STAGE2_SQL

    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        msgs = body["messages"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        forced = (body.get("tool_choice") or {})
        if isinstance(forced, dict) and forced.get("function", {}).get(
                "name") == "inspect_catalog":
            call = ("inspect_catalog", {"relation_ids":
                                        ["corp_facility_quarter"]})
        elif not tool_msgs or "submission_id" not in tool_msgs[-1][
                "content"]:
            call = ("execute_analysis", {
                "objective": "Stage 2 EAD by sector",
                "subquestions": ["Stage 2 EAD by sector"],
                "scope": {"reporting_periods": [], "filters": {}},
                "expected_output_grain": "sector",
                "expected_units": {"stage2_ead_sar_mn": "SAR million"},
                "steps": [{"step_id": "s1", "language": "sql",
                           "code": STAGE2_SQL, "parameters": {},
                           "purpose": "p", "input_artifact_ids": [],
                           "depends_on_step_ids": []}]})
        else:
            res = json.loads(tool_msgs[-1]["content"])
            step = res["steps"][0]
            top = max(step["preview"], key=lambda r: r["stage2_ead_sar_mn"])
            ref = {"artifact_id": step["artifact_id"],
                   "row_key": f"sector={top['sector']}",
                   "column_id": "stage2_ead_sar_mn"}
            call = ("finalize_response", {
                "disposition": "answer",
                "narrative": f"{top['sector']} is largest at "
                             "{{claim.top}}.",
                "numeric_claims": [{"claim_id": "top", "unit": "SAR million",
                                    "evidence": ref}],
                "coverage": [{"subquestion": "Stage 2 EAD by sector",
                              "status": "answered", "evidence_refs": [ref]}],
                "tables": [{"title": "t", "artifact_id": ref["artifact_id"],
                            "columns": ["sector", "stage2_ead_sar_mn"]}]})
        args = json.dumps(call[1], ensure_ascii=False)
        cut = len(args) // 2
        events = [
            {"id": "r1", "model": body["model"], "choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": f"c{len(seen)}",
                                "function": {"name": call[0],
                                             "arguments": args[:cut]}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
                "arguments": args[cut:]}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 900,
                                      "completion_tokens": 80}}]
        text = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + \
            "data: [DONE]\n\n"
        return httpx.Response(200, text=text,
                              headers={"content-type": "text/event-stream"})
    return handler, seen


def test_A02_A07_I11_openai_compatible_route_traverses_the_real_engine(
        tmp_path):
    import dataclasses

    from backend.model_lab.registry import load_profiles

    handler, seen = _openai_reference_server()
    base = load_profiles()["qwen3.5-9b"]
    ready = dataclasses.replace(base, declared_status="READY_E2E", raw=base.raw
                                | {"requires_probe": False,
                                   "status": "READY_E2E",
                                   "supported_controls": {
                                       "tools": True, "forced_tool_use": True,
                                       "named_tool_forcing": True,
                                       "tool_result_roundtrip": True,
                                       "stop_reason_mapping": True}})
    profiles = load_profiles() | {"qwen3.5-9b": ready}

    def factory(profile):
        if profile.profile_id == "qwen3.5-9b":
            return OpenAICompatProvider(
                base_url="http://127.0.0.1:11434/v1", model="qwen3.5:9b",
                transport=httpx.MockTransport(handler))
        from backend.model_lab.adapters import build_provider
        return build_provider(profile)

    svc = make_service(tmp_path, profiles=profiles,
                       provider_factory=factory)
    from conftest import child, run
    cid, ev = run(svc, ["fixture-reference", "qwen3.5-9b"])
    k = child(ev, "qwen3.5-9b")
    assert k["execution_state"] == "COMPLETED", k.get("error_code")
    assert k["identity"]["status"] == "MATCH"
    pop = next(c for c in k["checks"] if c["check_id"] == "S1S2-POP")
    assert pop["outcome"] == "PASS"
    assert all(b["model"] == "qwen3.5:9b" for b in seen)
    assert seen[0]["messages"][0]["role"] == "system"
    assert QUESTION in json.dumps(seen[0]["messages"])
    assert k["calls"][0]["token_status"] == "MEASURED"


def test_A13_candidate_children_never_reach_anthropic(tmp_path,
                                                      monkeypatch):
    """No hidden Opus helper: any Anthropic client construction during a
    candidate-only comparison fails the test."""
    import backend.llm.anthropic_provider as ap

    def boom(*a, **k):
        raise AssertionError("an Anthropic client was built for a "
                             "candidate-only comparison")
    monkeypatch.setattr(ap, "AnthropicProvider", boom)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", boom)
    svc = make_service(tmp_path)
    from conftest import run
    cid, ev = run(svc, ["fixture-reference", "fixture-repair"])
    assert all(k["execution_state"] == "COMPLETED" for k in ev["children"])


def test_A14_concurrent_groups_keep_their_own_providers(tmp_path):
    svc = make_service(tmp_path)
    a = svc.coord.create({"question": QUESTION,
                          "profile_ids": ["fixture-wrong-scope"],
                          "comparator_id": "fixture-wrong-scope"})
    b = svc.coord.create({"question": QUESTION,
                          "profile_ids": ["fixture-reference"],
                          "comparator_id": "fixture-reference"})
    svc.coord.wait(a["comparison_id"])
    svc.coord.wait(b["comparison_id"])
    ea = svc.coord.store.current_evaluation(a["comparison_id"],
                                            svc.cfg.tenant_id)["body"]
    eb = svc.coord.store.current_evaluation(b["comparison_id"],
                                            svc.cfg.tenant_id)["body"]
    assert ea["children"][0]["checks"][0]["outcome"] == "FAIL"
    assert eb["children"][0]["checks"][0]["outcome"] == "PASS"


def test_A15_registry_status_reflects_probes_not_declarations():
    from backend.model_lab import registry

    p = registry.load_profiles()["qwen3.5-9b"]
    assert registry.readiness(p, approvals={}, probes={}).status == \
        "NOT_INSTALLED"
    ok = {"qwen3.5-9b": {"runtime_reachable": True, "model_present": True,
                         "resolved_model": "qwen3.5:9b", "controls": {
                             "tools": True, "forced_tool_use": True,
                             "tool_result_roundtrip": True,
                             "stop_reason_mapping": True}}}
    assert registry.readiness(p, approvals={}, probes=ok).status == \
        "READY_E2E"
    bad = json.loads(json.dumps(ok))
    bad["qwen3.5-9b"]["controls"]["forced_tool_use"] = False
    assert registry.readiness(p, approvals={}, probes=bad).status == \
        "INCOMPATIBLE_PROTOCOL"
    wrong = json.loads(json.dumps(ok))
    wrong["qwen3.5-9b"]["resolved_model"] = "qwen3.5:4b"
    assert registry.readiness(p, approvals={}, probes=wrong).status == \
        "INCOMPATIBLE_PROTOCOL"
    down = {"qwen3.5-9b": {"runtime_reachable": False, "error": "refused"}}
    assert registry.readiness(p, approvals={}, probes=down).status == \
        "NOT_INSTALLED"
    opus = registry.load_profiles()["opus-frozen"]
    assert registry.readiness(opus, approvals={}, probes={},
                              env={}).status == "NEEDS_APPROVAL"
    assert registry.readiness(
        opus, approvals={"opus_spend": {"cap_usd": 5}}, probes={},
        env={"COCKPIT_ANTHROPIC_API_KEY": "k"}).status == "READY_E2E"


def test_A15_probe_uses_a_dummy_tool_against_a_mock_runtime(tmp_path):
    from backend.model_lab import probe, registry

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen3.5:9b"}]})
        body = json.loads(request.content)
        assert [t["function"]["name"] for t in body["tools"]] == \
            ["probe_echo"]                          # never CreditProbe tools
        if any(m["role"] == "tool" for m in body["messages"]):
            ev = [{"choices": [{"delta": {"content": "7"},
                                "finish_reason": "stop"}]}]
        else:
            ev = [{"model": "qwen3.5:9b", "choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "p1", "function": {
                    "name": "probe_echo", "arguments": '{"value": 7}'}}]}}]},
                  {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
        return httpx.Response(200, text="".join(
            f"data: {json.dumps(e)}\n\n" for e in ev) + "data: [DONE]\n\n")
    prof = registry.load_profiles()["qwen3.5-9b"]
    res = probe.probe_profile(prof, base_url="http://127.0.0.1:11434/v1",
                              transport=httpx.MockTransport(handler))
    assert res["controls"]["forced_tool_use"] is True
    assert res["resolved_model"] == "qwen3.5:9b"
    assert registry.readiness(prof, approvals={}, probes={
        prof.profile_id: res}).status == "READY_E2E"


def test_A16_multi_family_live_readiness_is_not_claimed(demo):
    """No non-Qwen family ran live in this environment, so nothing may say
    it did: every non-fixture candidate is blocked with a reason."""
    _, _, ev = demo
    real = [k for k in ev["children"] if not k["fixture"]]
    assert real and all(k["execution_state"] == "BLOCKED" for k in real)
