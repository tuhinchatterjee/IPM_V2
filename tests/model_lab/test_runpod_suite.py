"""RunPod suite, runner refusals and the no-substitution gates. Offline."""

from __future__ import annotations

import json
import sys

from conftest import ROOT

from backend.model_lab import registry

sys.path.insert(0, str(ROOT / "scripts" / "model_lab"))
import benchmark_suite  # noqa: E402

SUITE = json.loads((ROOT / "profiles" / "_runpod_suite.json").read_text())


def test_suite_shape_and_exclusions():
    ids = {m["profile_id"] for m in SUITE["models"]}
    assert len(SUITE["models"]) == 11 and len(SUITE["questions"]) == 15
    assert ids <= set(registry.load_profiles())
    names = " ".join(m["model"] for m in SUITE["models"])
    assert "Julia" not in names and "Saaras" not in names
    assert {e["model"] for e in SUITE["excluded_from_analyst_benchmark"]} \
        == {"Julia-1", "Saaras V4"}
    assert SUITE["lanes"]["ASSISTED_V1"]["status"] == "BLOCKED"
    assert SUITE["trace"]["required"] is True
    oracle = [q for q in SUITE["questions"]
              if q["oracle_status"] == "ORACLE_REGISTERED"]
    assert [q["oracle_task_id"] for q in oracle] == \
        ["corp-stage2-ead-by-sector-latest"]


def test_nothing_is_runnable_before_pinning_and_probing(tmp_path):
    p = benchmark_suite.plan(SUITE, runtime_dir=tmp_path,
                             lanes=list(SUITE["lanes"]), models=None,
                             questions=None)
    assert p["total_cells"] == 11 * 2 * 15 and p["runnable_cells"] == 0
    by = {(r["profile_id"], r["lane"]): r for r in p["rows"]}
    assert by[("minicpm5-2b-runpod", "FROZEN_BASELINE")]["readiness"] == \
        "DISCOVERED"
    assert by[("qwen3.8-27b-runpod", "FROZEN_BASELINE")]["readiness"] == \
        "BLOCKED_RESOURCE"
    assert "revision not pinned" in by[("qwen3.5-4b-runpod",
                                        "FROZEN_BASELINE")]["reason"]


def test_pinned_and_probed_profile_becomes_runnable_only_then():
    p = registry.load_profiles()["qwen3.5-4b-runpod"]
    ok_probe = {p.profile_id: {
        "runtime_reachable": True, "model_present": True,
        "resolved_model": "Qwen/Qwen3.5-4B", "controls": {
            "tools": True, "forced_tool_use": True,
            "tool_result_roundtrip": True, "stop_reason_mapping": True}}}
    assert registry.readiness(p, approvals={}, probes=ok_probe).status == \
        "NOT_INSTALLED"                            # probe alone is not enough
    pinned = registry._validate(p.raw | {"artifact": p.raw["artifact"] | {
        "revision": "0123456789abcdef"}}, ROOT / "x.json")
    assert registry.readiness(pinned, approvals={}, probes={}).status == \
        "NOT_INSTALLED"                            # pin alone is not enough
    assert registry.readiness(pinned, approvals={},
                              probes=ok_probe).status == "READY_E2E"


def test_runner_refuses_without_confirmation_trace_or_a_defined_lane(
        tmp_path, monkeypatch, capsys):
    args = ["--runtime-dir", str(tmp_path)]
    assert benchmark_suite.main(args) == 0            # dry run
    assert "no model was called" in capsys.readouterr().out
    assert benchmark_suite.main(args + ["--run"]) == 2
    assert "--confirm-model-calls" in capsys.readouterr().out
    monkeypatch.setenv("MODEL_LAB_FULL_IO_TRACE", "false")
    assert benchmark_suite.main(args + ["--run",
                                        "--confirm-model-calls"]) == 2
    assert "Model I/O Trace" in capsys.readouterr().out
    monkeypatch.setenv("MODEL_LAB_FULL_IO_TRACE", "true")
    assert benchmark_suite.main(args + ["--run", "--confirm-model-calls",
                                        "--lane", "ASSISTED_V1"]) == 2
    assert "ASSISTED_V1 is BLOCKED" in capsys.readouterr().out
    assert benchmark_suite.main(args + ["--run", "--confirm-model-calls",
                                        "--lane", "FROZEN_BASELINE"]) == 2
    assert "exactly ONE ready model" in capsys.readouterr().out


def test_runpod_profiles_never_point_at_ollama_artifacts():
    for pid, p in registry.load_profiles().items():
        if pid.endswith("-runpod"):
            ep = p.raw["endpoint"]
            assert ep["base_url_env"] == "LAB_VLLM_OPENAI_URL"
            assert ":" not in ep["model"].split("/")[-1] or \
                ep["model"].startswith("UNVERIFIED:")
            assert p.raw["artifact"]["revision_required"] is True
            assert p.raw["context_tokens"] == p.raw["runpod"]["max_model_len"]
