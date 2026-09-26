"""Opt-in per-profile request controls (reasoning_effort) and the
Qwen3.5-4B no-thinking runtime variant.

Offline only: mock servers and the pre-change adapter from Git. No model is
called. These tests prove the lab sends the control exactly when a profile
configures it, records it as evidence, and fails loudly otherwise; they say
nothing about how any real model behaves with thinking off.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import subprocess
import sys
from typing import Any

import httpx
import pytest
from conftest import ROOT, child, make_service, run
from test_adapters import TOOLS, _history, _openai_reference_server

from backend.model_lab import probe, registry
from backend.model_lab.adapters import AdapterUnavailable, build_provider
from backend.model_lab.adapters.openai_compat import (
    OpenAICompatProvider,
    RequestControlError,
    translate_request,
    validate_request_controls,
)

#: The last commit before request controls existed. The adapter and the base
#: Qwen3.5-4B profile at this commit are the byte-equivalence reference.
PRE_CONTROLS = "8b0d422cf5f244a1d83752469ffbe4f331f60470"
NOTHINK = "qwen3.5-4b-nothink"
BASE = "qwen3.5-4b"


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                              capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


@pytest.fixture(scope="module")
def old_adapter():
    """openai_compat.py exactly as it was before request controls."""
    src = _git("show", f"{PRE_CONTROLS}:backend/model_lab/adapters/"
                       "openai_compat.py")
    if src is None:
        pytest.skip("pre-change commit not in this checkout's history")
    name = "_lab_openai_compat_pre_controls"
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    exec(compile(src, f"{PRE_CONTROLS}:openai_compat.py", "exec"),
         mod.__dict__)
    return mod


CHOICES = [None, {"type": "any"}, {"type": "auto"},
           {"type": "tool", "name": "execute_analysis",
            "disable_parallel_tool_use": True}]


def _cases():
    sysblk = [{"type": "text", "text": "S1"}, {"type": "text", "text": "S2"}]
    for native in (False, True):
        for choice in CHOICES:
            for tools in (TOOLS, None):
                if tools is None and choice is not None:
                    continue
                yield dict(system=sysblk, messages=_history(), tools=tools,
                           tool_choice=choice, max_tokens=8192,
                           model="qwen3.5:4b", native_ollama=native)


# ---- 1. existing profiles: byte-equivalent requests -----------------------

def test_translate_request_is_byte_equivalent_without_controls(old_adapter):
    for kw in _cases():
        old_body, old_notes = old_adapter.translate_request(**kw)
        for extra in ({}, {"request_controls": None},
                      {"request_controls": {}}):
            new_body, new_notes = translate_request(**kw, **extra)
            assert json.dumps(new_body, ensure_ascii=False) == \
                json.dumps(old_body, ensure_ascii=False)
            assert new_notes == old_notes


def _wire(provider_cls_or_obj, **kw) -> dict[str, Any]:
    """The exact JSON body a provider POSTs for one converse call."""
    seen: list[bytes] = []

    def handler(request):
        seen.append(request.content)
        ev = [{"model": "m", "choices": [{"delta": {"content": "ok"},
                                          "finish_reason": "stop"}]}]
        if request.url.path.endswith("/api/chat"):
            return httpx.Response(200, json={
                "model": "m", "message": {"role": "assistant",
                                          "content": "ok"},
                "done": True, "done_reason": "stop"})
        return httpx.Response(200, text="".join(
            f"data: {json.dumps(e)}\n\n" for e in ev) + "data: [DONE]\n\n")
    p = provider_cls_or_obj
    p._transport = httpx.MockTransport(handler)
    p.converse(system=[{"type": "text", "text": "S"}], messages=_history(),
               tools=TOOLS, max_tokens=kw.get("max_tokens", 8192),
               tool_choice={"type": "tool", "name": "execute_analysis",
                            "disable_parallel_tool_use": True})
    return seen[0]


def test_every_existing_profile_sends_the_same_bytes(old_adapter):
    profiles = registry.load_profiles()
    checked = 0
    for p in profiles.values():
        if p.route not in ("openai_compat", "ollama_native") or \
                p.raw.get("request_controls"):
            continue
        ep = p.raw.get("endpoint") or {}
        env = {ep["api_key_env"]: "k"} if ep.get("api_key_env") else {}
        base = ep.get("base_url_default") or "https://gpu.example/v1"
        if ep.get("base_url_env"):
            env[ep["base_url_env"]] = base
        new = build_provider(p, env=env)
        old = old_adapter.OpenAICompatProvider(
            base_url=base, model=p.requested_model,
            api_key=env.get(ep.get("api_key_env") or ""),
            endpoint_class=ep.get("class", "local_loopback"),
            native_ollama=(p.route == "ollama_native"))
        assert _wire(new) == _wire(old), p.profile_id
        checked += 1
    assert checked >= 3


# ---- 2. the no-thinking variant adds exactly one key ----------------------

def test_nothink_profile_adds_exactly_reasoning_effort_none():
    profiles = registry.load_profiles()
    base = json.loads(_wire(build_provider(profiles[BASE], env={})))
    var = json.loads(_wire(build_provider(profiles[NOTHINK], env={})))
    assert set(var) - set(base) == {"reasoning_effort"}
    assert set(base) - set(var) == set()
    assert var["reasoning_effort"] == "none"
    for key in base:
        assert var[key] == base[key], key   # tools, choice, msgs, budget
    assert "reasoning_effort" not in base


def test_controls_leave_tools_forcing_messages_and_budget_unchanged():
    for kw in _cases():
        if kw["native_ollama"]:
            continue
        plain, notes = translate_request(**kw)
        ctl, ctl_notes = translate_request(
            **kw, request_controls={"reasoning_effort": "none"})
        assert {k: v for k, v in ctl.items() if k != "reasoning_effort"} \
            == plain
        assert ctl["reasoning_effort"] == "none"
        assert ctl_notes == notes + [
            "request control applied: reasoning_effort=none"]


def test_variant_profile_is_the_parent_model_with_one_control():
    profiles = registry.load_profiles()
    base, var = profiles[BASE].raw, profiles[NOTHINK].raw
    assert var["parent_profile_id"] == BASE
    assert var["variant_kind"] == "runtime_reasoning_control"
    assert var["endpoint"] == base["endpoint"]
    for key in ("registry_id", "route", "family", "max_output_tokens",
                "allowed_modes", "requires_probe", "price"):
        assert var[key] == base[key], key
    assert var["request_controls"] == {"reasoning_effort": "none"}
    assert var["artifact"]["expected_digest_prefix"] == "2a654d98e6fb"
    assert "request_controls" not in base


def test_base_qwen_profile_file_is_untouched():
    old = _git("rev-parse", f"{PRE_CONTROLS}:profiles/qwen3.5-4b.json")
    if old is None:
        pytest.skip("pre-change commit not in this checkout's history")
    now = _git("hash-object", "profiles/qwen3.5-4b.json")
    assert now.strip() == old.strip()


# ---- 3. end to end through the real frozen engine -------------------------

def _thinking_server():
    """The reference strategy, plus a streamed `delta.reasoning` chunk
    whenever the request did NOT turn reasoning off (as Qwen3.5 does)."""
    handler, seen = _openai_reference_server()

    def wrapped(request):
        body = json.loads(request.content)
        r = handler(request)
        if body.get("reasoning_effort") == "none":
            return r
        think = {"choices": [{"delta": {"reasoning": "let me think" * 10}}]}
        text = f"data: {json.dumps(think)}\n\n" + r.text
        return httpx.Response(200, text=text,
                              headers={"content-type": "text/event-stream"})
    return wrapped, seen


def _ready(p: registry.Profile) -> registry.Profile:
    return dataclasses.replace(p, declared_status="READY_E2E", raw=p.raw | {
        "requires_probe": False, "status": "READY_E2E"})


def test_engine_sends_the_control_only_for_the_variant(tmp_path):
    handler, seen = _thinking_server()
    loaded = registry.load_profiles()
    profiles = loaded | {BASE: _ready(loaded[BASE]),
                         NOTHINK: _ready(loaded[NOTHINK])}
    bodies: dict[str, list[dict]] = {BASE: [], NOTHINK: []}

    def factory(profile):
        p = build_provider(profile, env={})
        if profile.profile_id in bodies:
            def h(request, pid=profile.profile_id):
                bodies[pid].append(json.loads(request.content))
                return handler(request)
            p._transport = httpx.MockTransport(h)
        return p

    svc = make_service(tmp_path, profiles=profiles, provider_factory=factory)
    cid, ev = run(svc, [BASE, NOTHINK], comparator="")
    base, var = child(ev, BASE), child(ev, NOTHINK)
    assert base["execution_state"] == var["execution_state"] == "COMPLETED"
    assert bodies[BASE] and bodies[NOTHINK]
    assert all(b.get("reasoning_effort") == "none" for b in bodies[NOTHINK])
    assert all("reasoning_effort" not in b for b in bodies[BASE])
    # Evidence distinguishes the two runtime configurations.
    assert var["request_controls"] == {"reasoning_effort": "none"}
    assert var["reasoning_variant"] == "reasoning_effort=none"
    assert var["parent_profile_id"] == BASE
    assert base["request_controls"] is None
    assert base["reasoning_variant"].startswith("runtime-default")
    assert all(c["request_controls"] == {"reasoning_effort": "none"}
               for c in var["calls"])
    assert all(c["request_controls"] is None for c in base["calls"])
    assert all(c["reasoning_chars"] == 0 for c in var["calls"])
    assert all(c["reasoning_chars"] > 0 for c in base["calls"])
    # Same answer-bearing checks: the control changed no tool semantics.
    assert [c["outcome"] for c in var["checks"]] == \
        [c["outcome"] for c in base["checks"]]
    # And the export carries it.
    from backend.model_lab import export
    tables = export.rows(ev)
    row = next(r for r in tables["summary"] if r["profile_id"] == NOTHINK)
    assert row["reasoning_variant"] == "reasoning_effort=none"
    assert json.loads(row["request_controls"]) == {"reasoning_effort": "none"}
    assert all(json.loads(c["request_controls"]) == {"reasoning_effort":
                                                     "none"}
               for c in tables["calls"] if c["profile_id"] == NOTHINK)


# ---- 4. unsupported controls fail explicitly ------------------------------

@pytest.mark.parametrize("controls,route", [
    ({"thinking_budget": 0}, "openai_compat"),
    ({"reasoning_effort": "extreme"}, "openai_compat"),
    ({"reasoning_effort": "none"}, "ollama_native"),
    ({"reasoning_effort": "none"}, "anthropic"),
    ("none", "openai_compat"),
])
def test_unsupported_controls_raise(controls, route):
    with pytest.raises(RequestControlError):
        validate_request_controls(controls, route)


def test_unsupported_control_is_refused_at_load_and_in_the_adapter(tmp_path):
    raw = json.loads((ROOT / "profiles" / f"{NOTHINK}.json").read_text())
    raw["request_controls"] = {"thinking_budget": 0}
    (tmp_path / "bad.json").write_text(json.dumps(raw))
    with pytest.raises(registry.RegistryError, match="thinking_budget"):
        registry.load_profiles(tmp_path)
    with pytest.raises(ValueError, match="thinking_budget"):
        OpenAICompatProvider(base_url="http://127.0.0.1:11434/v1",
                             model="qwen3.5:4b",
                             request_controls={"thinking_budget": 0})
    with pytest.raises(ValueError):
        OpenAICompatProvider(base_url="http://127.0.0.1:11434/v1",
                             model="qwen3.5:4b", native_ollama=True,
                             request_controls={"reasoning_effort": "none"})


def test_a_child_with_a_bad_control_is_blocked_never_run_without_it(
        tmp_path):
    loaded = registry.load_profiles()
    bad = _ready(loaded[NOTHINK])
    bad = dataclasses.replace(bad, raw=bad.raw | {
        "request_controls": {"reasoning_effort": "extreme"}})
    with pytest.raises(AdapterUnavailable, match="extreme"):
        build_provider(bad, env={})
    sent: list[dict] = []

    def factory(profile):
        p = build_provider(profile, env={})
        p._transport = httpx.MockTransport(
            lambda r: sent.append(r) or httpx.Response(500))
        return p

    svc = make_service(tmp_path, profiles=loaded | {NOTHINK: bad},
                       provider_factory=factory)
    cid, ev = run(svc, [NOTHINK], comparator="")
    k = child(ev, NOTHINK)
    assert k["execution_state"] in ("BLOCKED", "FAILED")
    assert "extreme" in json.dumps(k)
    assert sent == []                          # no request ever left


# ---- 5. probe proves the runtime accepts the control ----------------------

def _probe_server(*, refuse_control: bool = False,
                  digest: str = "sha256:2a654d98e6fb" + "0" * 52):
    seen: list[dict] = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen3.5:4b"}]})
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [
                {"name": "qwen3.5:4b", "model": "qwen3.5:4b",
                 "digest": digest}]})
        body = json.loads(request.content)
        seen.append(body)
        if refuse_control and "reasoning_effort" in body:
            return httpx.Response(400, json={"error": "unknown field "
                                             "reasoning_effort"})
        ev = []
        if body.get("reasoning_effort") != "none":
            ev.append({"choices": [{"delta": {"reasoning": "hmm" * 20}}]})
        if any(m["role"] == "tool" for m in body["messages"]):
            ev.append({"choices": [{"delta": {"content": "7"},
                                    "finish_reason": "stop"}]})
        else:
            ev += [{"model": "qwen3.5:4b", "choices": [{"delta": {
                "tool_calls": [{"index": 0, "id": "p1", "function": {
                    "name": "probe_echo", "arguments": '{"value": 7}'}}]}}]},
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
        return httpx.Response(200, text="".join(
            f"data: {json.dumps(e)}\n\n" for e in ev) + "data: [DONE]\n\n")
    return handler, seen


def _probe(pid: str, **kw):
    prof = registry.load_profiles()[pid]
    handler, seen = _probe_server(**kw)
    res = probe.probe_profile(prof, base_url="http://127.0.0.1:11434/v1",
                              transport=httpx.MockTransport(handler))
    status = registry.readiness(prof, approvals={},
                                probes={pid: res}).status
    return res, status, seen


def test_probe_proves_the_control_is_accepted():
    res, status, seen = _probe(NOTHINK)
    assert status == "READY_E2E", res
    assert res["controls"]["request_controls_accepted"] is True
    assert res["first_call"]["request_controls"] == {"reasoning_effort":
                                                     "none"}
    assert res["first_call"]["reasoning_chars"] == 0
    assert res["digest_match"] is True
    assert len(seen) == 2 and all(b["reasoning_effort"] == "none"
                                  for b in seen)


def test_probe_reports_a_refused_control_as_incompatible():
    res, status, _ = _probe(NOTHINK, refuse_control=True)
    assert res["controls"]["request_controls_accepted"] is False
    assert res["request_controls_refused"] == "HTTP 400"
    assert status == "INCOMPATIBLE_PROTOCOL"


def test_probe_digest_mismatch_is_incompatible():
    res, status, _ = _probe(NOTHINK, digest="sha256:" + "f" * 64)
    assert res["digest_match"] is False
    assert status == "INCOMPATIBLE_PROTOCOL"


def test_base_profile_probe_is_unchanged_and_needs_no_control():
    res, status, seen = _probe(BASE)
    assert status == "READY_E2E"
    assert "request_controls_accepted" not in res["controls"]
    assert "digest_match" not in res
    assert all("reasoning_effort" not in b for b in seen)
    assert res["first_call"]["reasoning_chars"] > 0   # thinking observed
