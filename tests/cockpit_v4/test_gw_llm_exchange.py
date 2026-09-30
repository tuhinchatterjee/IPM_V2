"""P1 — the Full LLM Exchange Trace: passive, faithful, sanitized, shared.

EVIDENCE LABEL: **MODEL MOCK.** The analyst is the suite's scripted provider;
the worker, orchestrator, store, ledger, SQL runner and release are real. The
Anthropic adapter is exercised with an injected fake SDK client, and the
open-weight adapter with an injected transport -- no network call is made and
no credential is read.

What is proven here, in the order the specification states it:

* passivity -- the recorder forwards the identical argument objects, adds no
  call, and the requests a run sends are byte-identical with it on or off;
* fidelity -- the recorded canonical request equals, byte for byte after
  sanitization, what the provider received; tool calls and exact arguments,
  stop reason, usage and model identity are recorded;
* adapter stages -- Canonical -> Adapter -> Raw -> Normalized for Anthropic
  and for an open-weight OpenAI-compatible endpoint;
* secrets -- keys, bearer tokens and authorization headers never reach the
  store, while ordinary telemetry (`max_tokens`, `input_tokens`) stays;
* hidden reasoning is never recorded;
* immutability, failure isolation, reopen-without-calls, export, access
  control, tenancy, data visibility and the AI Model Lab comparison.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from types import SimpleNamespace

import pytest
from conftest import ScriptedResult, final, intent, tool_call
from test_catalog_convergence import finish
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import routes
from backend.llm import exchange
from backend.llm.anthropic_provider import AnthropicProvider
from backend.llm.openai_compatible import (OpenAICompatibleProvider,
                                           translate_request)
from backend.workspace import api as workspace_api
from backend.workspace import exchange_api

FAKE_KEY = "sk-ant-api03-" + "Q" * 40
P = "/api/v1/cockpit-v4/workspace"


def _finalize_script():
    return [ScriptedResult(tool_calls=[tool_call(
        "finalize_response",
        final(intent=intent(), disposition="answer", narrative="ok"))])]


EAD_SQL = ("SELECT sector_name, SUM(ead_reported) AS ead_sar_mn FROM "
           "cockpit_facility_quarter WHERE reporting_quarter = ? "
           "GROUP BY 1 ORDER BY 2 DESC")


def _two_call_script():
    """An action that executes real SQL, then an answer -- two model calls."""
    execute = tool_call("execute_analysis", {
        "intent": intent("DATA_ANALYSIS", "COCKPIT"),
        "objective": "EAD by sector", "subquestions": ["a"],
        "scope": {"reporting_periods": [], "filters": {}},
        "metadata_receipt_ids": [], "fields_required": ["ead_reported"],
        "expected_output_grain": "sector", "expected_units": "SAR million",
        "steps": [{"step_id": "s1", "language": "sql", "code": EAD_SQL,
                   "parameters": {"1": "2026Q2"}, "purpose": "p",
                   "input_artifact_ids": [], "depends_on_step_ids": []}],
        "repair_of_submission_id": ""}, "tu-a")
    # The answer quotes the executed row, as a real analyst must: the
    # finalizer rejects an unbound narrative and a rejection is a third call.
    return [ScriptedResult(tool_calls=[execute]), finish]


@pytest.fixture
def recorder_on(monkeypatch, v4_config):
    """The store the worker's binding resolves to for this runtime."""
    monkeypatch.setenv(exchange.FLAG, "1")
    return exchange.store_at(exchange.store_path_for(v4_config))


@pytest.fixture
def recorder_off(monkeypatch):
    monkeypatch.delenv(exchange.FLAG, raising=False)


# ---- passivity ------------------------------------------------------------------

def test_bind_returns_the_same_provider_object_when_the_flag_is_off(
        recorder_off):
    provider = object()
    assert exchange.bind(provider, runtime=None, run=None) is provider


def test_the_recorder_forwards_the_identical_argument_objects(tmp_path):
    seen = {}

    class Inner:
        name = "inner"

        def converse(self, **kwargs):
            seen.update(kwargs)
            return ScriptedResult(text="hi", stop_reason="end_turn")

    system = [{"type": "text", "text": "S"}]
    messages = [{"role": "user", "content": "Q"}]
    tools = [{"name": "t", "input_schema": {"type": "object"}}]
    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    proxy = exchange.RecordingProvider(Inner(), store, exchange.Binding(
        run_id="r1", tenant_id="t1"))
    result = proxy.converse(system=system, messages=messages, tools=tools,
                            max_tokens=10, model="m")
    assert seen["system"] is system and seen["messages"] is messages
    assert seen["tools"] is tools
    assert result.text == "hi"
    assert store.count() == 1


def test_non_converse_attributes_pass_through_untouched(tmp_path):
    inner = SimpleNamespace(name="p", model="m1", count_tokens=lambda **k: 42,
                            converse=lambda **k: None)
    proxy = exchange.RecordingProvider(
        inner, exchange.ExchangeStore(":memory:"), exchange.Binding())
    assert proxy.count_tokens(system="x") == 42
    assert proxy.model == "m1" and proxy.wrapped is inner


def test_a_run_sends_byte_identical_requests_with_the_recorder_on(
        drive, monkeypatch, tmp_path):
    monkeypatch.delenv(exchange.FLAG, raising=False)
    _o, off, _r = drive("What is total EAD by sector?", _two_call_script())
    monkeypatch.setenv(exchange.FLAG, "1")
    _o, on, record = drive("What is total EAD by sector?", _two_call_script())
    assert len(off.sent) == len(on.sent) == 2

    def stable(sent):
        # The run id, thread id and clock legitimately differ between two
        # runs; everything the model is TOLD about the request's shape --
        # system, tools, tool choice, settings, model -- must not.
        return [{k: v for k, v in call.items() if k != "messages"}
                for call in sent]
    assert (exchange.canonical_bytes(stable(off.sent))
            == exchange.canonical_bytes(stable(on.sent)))
    assert [len(c["messages"]) for c in off.sent] == \
        [len(c["messages"]) for c in on.sent]


def test_the_recorder_adds_no_model_call(drive, recorder_on):
    _o, provider, record = drive("How many facilities?", _two_call_script())
    calls = recorder_on.for_run(record.run_id, tenant_id=record.tenant_id)
    assert len(calls) == len(provider.sent) == 2


# ---- fidelity ----------------------------------------------------------------------

def test_the_recorded_request_is_what_the_provider_received(
        drive, recorder_on):
    _o, provider, record = drive("How many facilities?", _two_call_script())
    calls = recorder_on.for_run(record.run_id, tenant_id=record.tenant_id)
    for sent, call in zip(provider.sent, calls):
        req = call["canonical_request"]
        for key in ("system", "tools", "tool_choice", "max_tokens", "model",
                    "output_config"):
            assert (exchange.canonical_bytes(exchange.sanitize(sent[key]))
                    == exchange.canonical_bytes(req.get(key))), key
        assert (exchange.canonical_bytes(exchange.sanitize(sent["messages"]))
                == exchange.canonical_bytes(req["messages"]))
        assert call["hashes"]["canonical_request"] == exchange.digest(req)


def test_calls_are_recorded_in_order_with_purpose_model_and_usage(
        drive, recorder_on):
    _o, _p, record = drive("How many facilities?", _two_call_script())
    calls = recorder_on.for_run(record.run_id, tenant_id=record.tenant_id)
    assert [c["seq"] for c in calls] == [1, 2]
    assert all(c["purpose"] for c in calls)
    assert all(c["requested_model"] == "mock-analyst" for c in calls)
    assert all(c["resolved_model"] == "mock-analyst" for c in calls)
    assert calls[0]["usage"]["input_tokens"] == 1200
    assert calls[0]["usage"]["output_tokens"] == 300
    assert calls[0]["stop_reason"] == "tool_use"
    assert calls[0]["thread_id"] == record.thread_id


def test_tool_calls_are_recorded_with_their_exact_arguments(
        drive, recorder_on):
    _o, _p, record = drive("How many facilities?", _two_call_script())
    first = recorder_on.for_run(record.run_id,
                                tenant_id=record.tenant_id)[0]
    call = first["normalized_response"]["tool_calls"][0]
    assert call["name"] == "execute_analysis" and call["id"] == "tu-a"
    assert call["input"]["steps"][0]["code"] == EAD_SQL


def test_the_second_request_carries_the_first_tool_result(drive, recorder_on):
    _o, _p, record = drive("How many facilities?", _two_call_script())
    second = recorder_on.for_run(record.run_id,
                                 tenant_id=record.tenant_id)[1]
    blocks = [b for m in second["canonical_request"]["messages"]
              if isinstance(m.get("content"), list) for b in m["content"]]
    results = [b for b in blocks if b.get("type") == "tool_result"]
    assert results and results[0]["tool_use_id"] == "tu-a"
    assert second["transmitted_data"]["tool_results"] >= 1


# ---- the Anthropic adapter stage ------------------------------------------------

class _FakeMessage:
    def __init__(self, blocks, model="claude-opus-test"):
        self._blocks = blocks
        self.content = [SimpleNamespace(**b) for b in blocks]
        self.model = model
        self.stop_reason = "tool_use"
        self.usage = SimpleNamespace(input_tokens=321, output_tokens=12,
                                     cache_read_input_tokens=0,
                                     cache_creation_input_tokens=0)
        self.id = "msg_fake_1"

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model, "role": "assistant",
                "type": "message", "content": list(self._blocks),
                "stop_reason": self.stop_reason,
                "usage": {"input_tokens": 321, "output_tokens": 12}}


class _FakeClient:
    def __init__(self, blocks):
        self.created = []
        self.blocks = blocks
        self.messages = self

    def create(self, **request):
        self.created.append(request)
        return _FakeMessage(self.blocks)


def _anthropic(blocks):
    client = _FakeClient(blocks)
    return AnthropicProvider(api_key=FAKE_KEY, client=client), client


def test_the_anthropic_adapter_request_and_raw_response_are_recorded(
        tmp_path):
    blocks = [{"type": "tool_use", "id": "tu-9", "name": "finalize_response",
               "input": {"narrative": "x"}}]
    provider, client = _anthropic(blocks)
    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    proxy = exchange.RecordingProvider(provider, store, exchange.Binding(
        run_id="r", tenant_id="t"))
    proxy.converse(system=[{"type": "text", "text": "S"}],
                   messages=[{"role": "user", "content": "Q"}],
                   tools=[{"name": "finalize_response",
                           "input_schema": {"type": "object"}}],
                   max_tokens=99, model="claude-opus-test",
                   tool_choice={"type": "any"}, allow_retry=False)
    call = store.for_run("r", tenant_id="t")[0]
    assert call["adapter"] == "anthropic.messages"
    assert call["adapter_request"][0] == exchange.sanitize(client.created[0])
    assert call["raw_response"][0]["id"] == "msg_fake_1"
    assert call["raw_response_available"] is True
    assert call["normalized_response"]["tool_calls"][0]["input"] == \
        {"narrative": "x"}
    assert call["resolved_model"] == "claude-opus-test"


# ---- secrets --------------------------------------------------------------------------

def test_no_credential_reaches_the_store(tmp_path):
    provider, _client = _anthropic([{"type": "text", "text": "ok"}])
    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    proxy = exchange.RecordingProvider(provider, store, exchange.Binding(
        run_id="r", tenant_id="t"))
    proxy.converse(
        system="S", model="m", max_tokens=5,
        messages=[{"role": "user",
                   "content": f"here is my key {FAKE_KEY} and "
                              f"Authorization: Bearer abcdefghijklmnopqrstu"}],
        allow_retry=False)
    raw = (tmp_path / "x.sqlite3").read_bytes()
    for db in [raw] + [p.read_bytes() for p in tmp_path.glob("x.sqlite3*")]:
        assert b"sk-ant-api03" not in db
        assert b"abcdefghijklmnopqrstu" not in db
    call = store.for_run("r", tenant_id="t")[0]
    text = json.dumps(call)
    assert exchange.REDACTED in text
    assert {r["reason"] for r in call["redactions"]} >= {"anthropic_key",
                                                        "bearer_token"}


def test_secret_keys_are_redacted_but_telemetry_is_not():
    found = []
    clean = exchange.sanitize({
        "api_key": "abc", "Authorization": "Bearer xyz",
        "x-api-key": "k", "password": "p", "max_tokens": 512,
        "usage": {"input_tokens": 10, "output_tokens": 3,
                  "cache_read_input_tokens": 1}}, found=found)
    assert clean["api_key"] == clean["Authorization"] == exchange.REDACTED
    assert clean["x-api-key"] == clean["password"] == exchange.REDACTED
    assert clean["max_tokens"] == 512
    assert clean["usage"] == {"input_tokens": 10, "output_tokens": 3,
                              "cache_read_input_tokens": 1}
    assert len(found) == 4


def test_the_open_weight_credential_is_never_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("CREDITPROBE_MODEL_LAB_OPENWEIGHT_KEY",
                       "ow-secret-value-123456789")
    captured = {}

    def transport(url, body, headers, timeout):
        captured["headers"] = headers
        return {"id": "cmpl-1", "model": "qwen-test",
                "choices": [{"message": {"content": "ok"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1}}

    provider = OpenAICompatibleProvider(base_url="http://ow.local/v1",
                                        model="qwen-test",
                                        transport=transport)
    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    exchange.RecordingProvider(provider, store, exchange.Binding(
        run_id="r", tenant_id="t")).converse(
        system="S", messages=[{"role": "user", "content": "Q"}],
        max_tokens=5)
    assert captured["headers"]["Authorization"].startswith("Bearer ow-")
    for path in tmp_path.glob("x.sqlite3*"):
        assert b"ow-secret-value" not in path.read_bytes()


# ---- hidden reasoning ----------------------------------------------------------

def test_hidden_reasoning_is_never_recorded(tmp_path):
    blocks = [{"type": "thinking", "thinking": "private chain of thought",
               "signature": "sig"},
              {"type": "text", "text": "public answer"}]
    provider, _ = _anthropic(blocks)
    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    exchange.RecordingProvider(provider, store, exchange.Binding(
        run_id="r", tenant_id="t")).converse(
        system="S", messages=[{"role": "user", "content": "Q"}],
        max_tokens=5, allow_retry=False)
    for path in tmp_path.glob("x.sqlite3*"):
        assert b"private chain of thought" not in path.read_bytes()
    call = store.for_run("r", tenant_id="t")[0]
    assert call["hidden_reasoning_recorded"] is False
    assert call["raw_response"][0]["content"][0]["withheld"]


# ---- immutability and failure isolation --------------------------------------

def test_exchange_records_are_immutable(tmp_path):
    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    exchange.RecordingProvider(
        SimpleNamespace(name="p", converse=lambda **k: ScriptedResult(
            text="a", stop_reason="end_turn")),
        store, exchange.Binding(run_id="r", tenant_id="t")).converse(
        system="S", messages=[], max_tokens=1)
    conn = sqlite3.connect(tmp_path / "x.sqlite3")
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("UPDATE llm_exchanges SET status='EDITED'")


def test_a_recorder_failure_never_breaks_the_call(tmp_path):
    class Broken(exchange.ExchangeStore):
        def insert(self, record):
            raise RuntimeError("disk full")

    result = exchange.RecordingProvider(
        SimpleNamespace(name="p", converse=lambda **k: ScriptedResult(
            text="kept", stop_reason="end_turn")),
        Broken(":memory:"), exchange.Binding()).converse(
        system="S", messages=[], max_tokens=1)
    assert result.text == "kept"


def test_a_provider_error_is_recorded_and_the_same_exception_propagates(
        tmp_path):
    boom = RuntimeError("503 overloaded")

    def fail(**_):
        raise boom

    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    with pytest.raises(RuntimeError) as caught:
        exchange.RecordingProvider(
            SimpleNamespace(name="p", converse=fail), store,
            exchange.Binding(run_id="r", tenant_id="t")).converse(
            system="S", messages=[], max_tokens=1)
    assert caught.value is boom
    call = store.for_run("r", tenant_id="t")[0]
    assert call["status"] == "ERROR" and "503 overloaded" in call["error"]


# ---- the open-weight adapter ---------------------------------------------------

def test_open_weight_translation_preserves_the_canonical_conversation():
    body, notes = translate_request(
        system=[{"type": "text", "text": "A"}, {"type": "text", "text": "B"}],
        messages=[
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "execute_analysis",
                 "input": {"steps": [1]}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "{\"rows\": [{\"n\": 1}]}"}]}],
        tools=[{"name": "execute_analysis", "description": "run",
                "input_schema": {"type": "object"}}],
        max_tokens=100, model="qwen", tool_choice={"type": "any"},
        output_config={"effort": "high"})
    assert body["messages"][0] == {"role": "system", "content": "A\n\nB"}
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == \
        json.dumps({"steps": [1]})
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "t1",
                                   "content": "{\"rows\": [{\"n\": 1}]}"}
    assert body["tool_choice"] == "required"
    assert body["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert any("concatenated" in n for n in notes)
    assert any("output_config" in n for n in notes)


def test_open_weight_records_canonical_adapter_raw_and_normalized(tmp_path):
    def transport(url, body, headers, timeout):
        return {"id": "cmpl-7", "model": "qwen-2.5-72b",
                "choices": [{"message": {"content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "finalize_response",
                                 "arguments": "{\"narrative\": \"n\"}"}}]},
                    "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 9}}

    provider = OpenAICompatibleProvider(base_url="http://ow.local/v1",
                                        model="qwen-2.5-72b",
                                        transport=transport)
    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")
    exchange.RecordingProvider(provider, store, exchange.Binding(
        run_id="r", tenant_id="t")).converse(
        system=[{"type": "text", "text": "S"}],
        messages=[{"role": "user", "content": "Q"}],
        tools=[{"name": "finalize_response",
                "input_schema": {"type": "object"}}],
        max_tokens=64, tool_choice={"type": "any"})
    call = store.for_run("r", tenant_id="t")[0]
    assert call["adapter"] == "openai.chat_completions"
    assert call["canonical_request"]["system"][0]["text"] == "S"
    assert call["adapter_request"][0]["tool_choice"] == "required"
    assert call["raw_response"][0]["id"] == "cmpl-7"
    assert call["normalized_response"]["stop_reason"] == "tool_use"
    assert call["normalized_response"]["tool_calls"][0]["input"] == \
        {"narrative": "n"}
    assert call["usage"]["input_tokens"] == 50


# ---- the API: reopen, export, access, tenancy, visibility, Model Lab ------------

@pytest.fixture
def lab(store_db, runtime, recorder_on, monkeypatch):
    who = {"id": "u1", "tenant": "demo-tenant", "roles": ("administrator",)}
    holder = {"who": who}
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: holder["who"],
                   startup_sha="testsha")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    monkeypatch.setattr(exchange_api, "exchange_store", lambda: recorder_on)
    return TestClient(app), holder


def test_reopening_a_trace_makes_zero_model_calls(drive, lab, recorder_on):
    client, _ = lab
    _o, provider, record = drive("How many facilities?", _two_call_script())
    before = len(provider.sent)
    view = client.get(f"{P}/llm-exchange/runs/{record.run_id}")
    assert view.status_code == 200, view.text
    again = client.get(f"{P}/llm-exchange/runs/{record.run_id}")
    assert again.json()["calls"] == view.json()["calls"]
    assert len(provider.sent) == before
    body = view.json()
    assert body["recorder"]["calls_recorded"] == 2
    kinds = {i["kind"] for i in body["timeline"]}
    assert kinds == {"llm_call", "creditprobe_event"}


def test_context_growth_and_data_visibility_are_reported(drive, lab):
    client, _ = lab
    _o, _p, record = drive("How many facilities?", _two_call_script())
    body = client.get(f"{P}/llm-exchange/runs/{record.run_id}").json()
    growth = body["context_growth"]
    assert [g["seq"] for g in growth] == [1, 2]
    assert growth[1]["total_bytes"] > growth[0]["total_bytes"]
    assert growth[0]["input_tokens_exact"] == 1200
    vis = body["data_visibility"]
    assert set(vis) == {"available_to_creditprobe",
                        "actually_transmitted_to_model"}
    assert vis["actually_transmitted_to_model"]["unique_tool_results"] == 1
    assert vis["available_to_creditprobe"]["artifacts"]


def test_the_export_package_reproduces_every_record(drive, lab):
    client, _ = lab
    _o, _p, record = drive("How many facilities?", _two_call_script())
    view = client.get(f"{P}/llm-exchange/runs/{record.run_id}").json()
    raw = client.get(f"{P}/llm-exchange/runs/{record.run_id}/export")
    assert raw.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(raw.content))
    names = set(zf.namelist())
    for n in (1, 2):
        for part in ("canonical_request.json", "provider_request.json",
                     "provider_response.json", "normalized_response.json",
                     "readable_request.md", "readable_response.md",
                     "metadata.json"):
            assert f"llm_exchange/call_{n}/{part}" in names
    assert {"llm_calls.csv", "context_composition.csv",
            "context_growth.csv"} <= names
    exported = json.loads(zf.read("llm_exchange/call_1/canonical_request.json"))
    assert exported == view["calls"][0]["canonical_request"]
    assert exchange.digest(exported) == \
        view["calls"][0]["hashes"]["canonical_request"]


def test_the_exchange_needs_a_reviewer_role(drive, lab):
    client, holder = lab
    _o, _p, record = drive("How many facilities?", _finalize_script())
    holder["who"] = {"id": "u2", "tenant": "demo-tenant", "roles": ()}
    assert client.get(
        f"{P}/llm-exchange/runs/{record.run_id}").status_code == 403


def test_another_tenant_cannot_read_the_exchange(drive, lab):
    client, holder = lab
    _o, _p, record = drive("How many facilities?", _finalize_script())
    holder["who"] = {"id": "x", "tenant": "other-bank",
                     "roles": ("administrator",)}
    assert client.get(
        f"{P}/llm-exchange/runs/{record.run_id}").status_code == 404


def test_model_lab_reads_the_same_records_and_compares_opus_with_open_weight(
        lab, recorder_on):
    client, _ = lab
    provider, _ = _anthropic([{"type": "tool_use", "id": "t",
                               "name": "finalize_response",
                               "input": {"narrative": "a"}}])
    exchange.RecordingProvider(provider, recorder_on, exchange.Binding(
        run_id="run-lab", tenant_id="demo-tenant")).converse(
        system=[{"type": "text", "text": "S"}],
        messages=[{"role": "user", "content": "Q"}],
        tools=[{"name": "finalize_response",
                "input_schema": {"type": "object"}}],
        max_tokens=64, model="claude-opus-test",
        tool_choice={"type": "any"}, allow_retry=False)
    listed = client.get(f"{P}/model-lab/exchanges").json()
    assert listed["exchanges"][0]["run_id"] == "run-lab"
    original = recorder_on.get(listed["exchanges"][0]["exchange_id"],
                               tenant_id="demo-tenant")

    def transport(url, body, headers, timeout):
        return {"id": "c", "model": "qwen-test", "choices": [{"message": {
            "content": None, "tool_calls": [{"id": "x", "type": "function",
                                             "function": {
                                                 "name": "finalize_response",
                                                 "arguments": "{\"narrative\": \"b\"}"}}]},
            "finish_reason": "tool_calls"}], "usage": {}}

    open_weight = OpenAICompatibleProvider(base_url="http://ow/v1",
                                           model="qwen-test",
                                           transport=transport)
    who = {"id": "u1", "tenant": "demo-tenant"}
    out = exchange_api.replay(original, open_weight, model="qwen-test",
                              store=recorder_on, who=who)
    assert out["status"] == "OK" and out["replay_exchange_id"]
    diff = client.get(f"{P}/model-lab/compare", params={
        "a": original["exchange_id"], "b": out["replay_exchange_id"]}).json()
    assert diff["a"]["model"] == "claude-opus-test"
    assert diff["b"]["model"] == "qwen-test"
    assert diff["request"]["same_system"] and diff["request"]["same_tools"]
    assert all(m["same"] for m in diff["request"]["messages"])
    assert diff["response"]["same_tool_sequence"] is True
    assert diff["response"]["same_arguments"] is False
    replayed = recorder_on.get(out["replay_exchange_id"],
                               tenant_id="demo-tenant")
    assert replayed["replay_of"] == original["exchange_id"]
    assert replayed["surface"] == "ai_model_lab"


def test_a_replay_with_no_configured_target_sends_nothing(lab, recorder_on,
                                                          monkeypatch):
    client, _ = lab
    monkeypatch.delenv("CREDITPROBE_MODEL_LAB_OPENWEIGHT_URL", raising=False)
    exchange.RecordingProvider(
        SimpleNamespace(name="p", converse=lambda **k: ScriptedResult(
            text="a", stop_reason="end_turn")),
        recorder_on, exchange.Binding(run_id="r0", tenant_id="demo-tenant")
    ).converse(system="S", messages=[], max_tokens=1)
    exchange_id = recorder_on.for_run("r0", tenant_id="demo-tenant")[0][
        "exchange_id"]
    before = recorder_on.count()
    response = client.post(f"{P}/model-lab/replay", json={
        "exchange_id": exchange_id, "target": "open_weight"})
    assert response.status_code == 409
    assert recorder_on.count() == before


def test_the_workspace_router_is_absent_when_its_flag_is_off(
        monkeypatch, v4_config):
    from backend.cockpit_v4 import app as v4app
    from backend.workspace import flags

    monkeypatch.delenv(flags.FLAG, raising=False)
    off = TestClient(v4app.create_app(v4_config, verify_model=False,
                                      start_workers=False))
    assert off.get(f"{P}/model-lab/targets").status_code == 404
    monkeypatch.setenv(flags.FLAG, "1")
    on = TestClient(v4app.create_app(v4_config, verify_model=False,
                                     start_workers=False))
    assert on.get(f"{P}/model-lab/targets").status_code == 200
