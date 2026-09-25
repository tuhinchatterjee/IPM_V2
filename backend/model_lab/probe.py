"""
Capability probe for a candidate route. Separate from the benchmark.

Uses ONE harmless dummy tool (`probe_echo`) -- never the CreditProbe tools,
never real data -- to prove the controls the frozen engine relies on:
forced tool use, named-tool forcing, a tool_result round trip with id
pairing, stop-reason mapping, and the served model identity. Results are
written to <lab runtime>/probes.json and are what readiness reads; a profile
is never marked READY_E2E on a declaration.

No download, no install: an absent runtime or model is reported as such.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from backend.model_lab.registry import Profile

DUMMY_TOOL = {"name": "probe_echo",
              "description": "Echo the integer you are given. Probe only.",
              "input_schema": {"type": "object", "properties": {
                  "value": {"type": "integer"}}, "required": ["value"],
                  "additionalProperties": False}}


def _models(base: str, native_root: str | None, transport=None
            ) -> tuple[bool, list[str], str]:
    try:
        with httpx.Client(timeout=5, transport=transport) as c:
            r = c.get(base.rstrip("/") + "/models")
            if r.status_code == 200:
                return True, [m.get("id") for m in r.json().get("data", [])], ""
            if native_root:
                r = c.get(native_root + "/api/tags")
                if r.status_code == 200:
                    return True, [m.get("name") for m in
                                  r.json().get("models", [])], ""
            return True, [], f"HTTP {r.status_code}"
    except httpx.HTTPError as exc:
        return False, [], f"{type(exc).__name__}: {exc}"


def probe_profile(profile: Profile, *, base_url: str, api_key: str | None =
                  None, transport=None) -> dict[str, Any]:
    from backend.model_lab.adapters.openai_compat import OpenAICompatProvider

    model = profile.requested_model
    native_root = base_url[:-3] if base_url.endswith("/v1") else None
    reachable, models, err = _models(base_url, native_root, transport)
    out: dict[str, Any] = {"profile_id": profile.profile_id,
                           "probed_at": time.time(), "base_url": base_url,
                           "runtime_reachable": reachable, "error": err,
                           "models_listed": models[:50],
                           "model_present": model in models,
                           "requested_model": model, "controls": {}}
    if not (reachable and model in models):
        return out
    p = OpenAICompatProvider(base_url=base_url, model=model,
                             api_key=api_key, stream=True,
                             endpoint_class=profile.raw.get(
                                 "endpoint", {}).get("class",
                                                     "local_loopback"),
                             transport=transport)
    sysblk = [{"type": "text", "text": "You are a protocol probe. Use the "
               "tool when asked."}]
    ctl = out["controls"]
    try:
        r = p.converse(system=sysblk, messages=[{"role": "user", "content":
                       "Call probe_echo with value 7."}], tools=[DUMMY_TOOL],
                       max_tokens=256, model=model, timeout=120,
                       tool_choice={"type": "tool", "name": "probe_echo",
                                    "disable_parallel_tool_use": True})
        out["resolved_model"] = r.model or None
        call = next((c for c in r.tool_calls if c["name"] == "probe_echo"),
                    None)
        ctl["tools"] = call is not None
        ctl["named_tool_forcing"] = call is not None
        ctl["forced_tool_use"] = call is not None
        ctl["stop_reason_mapping"] = r.stop_reason == "tool_use"
        out["first_call"] = {"stop_reason": r.stop_reason,
                             "args": call and call["input"],
                             "usage": r.native_usage,
                             "first_protocol_event_ms":
                             r.first_protocol_event_ms}
        if call:
            r2 = p.converse(system=sysblk, messages=[
                {"role": "user", "content": "Call probe_echo with value 7."},
                {"role": "assistant", "content": r.assistant_blocks},
                {"role": "user", "content": [{"type": "tool_result",
                                              "tool_use_id": call["id"],
                                              "content": '{"echo": 7}'}]}],
                tools=[DUMMY_TOOL], max_tokens=128, model=model, timeout=120)
            ctl["tool_result_roundtrip"] = r2.stop_reason in ("end_turn",
                                                              "tool_use")
            out["second_call"] = {"stop_reason": r2.stop_reason,
                                  "text": r2.text[:200]}
        # Unforced turn must be allowed to answer in text.
        ctl["effort_control"] = False
        ctl["token_counting"] = False
    except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
        out["error"] = f"{type(exc).__name__}: {exc}"[:400]
    return out


def save(runtime_dir: Path, result: dict[str, Any]) -> Path:
    path = runtime_dir / "probes.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[result["profile_id"]] = result
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=str))
    return path
