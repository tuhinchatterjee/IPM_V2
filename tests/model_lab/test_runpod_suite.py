"""RunPod suite v2: pinning, licence and fit gates, quantised variants, the
runner state machine, checkpoint/resume and partial reports. Offline: a
fake Hugging Face metadata source; no network, no weights, no model call."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys

import pytest
from conftest import ROOT, build_fixture_reference_set

from backend.model_lab import benchmark_questions as bq
from backend.model_lab import registry

sys.path.insert(0, str(ROOT / "scripts" / "model_lab"))
import benchmark_suite  # noqa: E402
import suite_report  # noqa: E402

SUITE = json.loads((ROOT / "profiles" / "_runpod_suite.json").read_text())


def _pp():
    spec = importlib.util.spec_from_file_location(
        "pin_and_probe", ROOT / "scripts/model_lab/runpod/"
        "pin_and_probe_models.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- suite shape --------------------------------------------------------------

def test_suite_v2_shape_order_and_questions():
    ids = [m["profile_id"] for m in SUITE["models"]]
    assert SUITE["suite_id"] == bq.SUITE_VERSION
    assert ids[:3] == ["minicpm5-2b-runpod", "lfm2.5-vl-3b-runpod",
                       "qwen3.5-4b-runpod"]
    assert ids[-2:] == ["qwen3.8-27b-runpod", "qwen3.8-27b-runpod--awq-4bit"]
    assert len([m for m in SUITE["models"] if "parent_profile_id" not in m]
               ) == 11
    assert [q["question_id"] for q in SUITE["questions"]] == \
        [q.qid for q in bq.QUESTIONS]
    assert [q["question"] for q in SUITE["questions"]] == \
        [q.text for q in bq.QUESTIONS]
    assert {k: v["status"] for k, v in SUITE["lanes"].items()} == \
        {"FROZEN_BASELINE": "READY", "ASSISTED_V1": "READY"}
    assert {e["model"] for e in SUITE["excluded_from_analyst_benchmark"]} \
        == {"Julia-1", "Saaras V4"}
    assert set(ids) <= set(registry.load_profiles())


def test_nothing_runs_before_pinning_fit_and_probe(tmp_path):
    p = benchmark_suite.plan(SUITE, runtime_dir=tmp_path,
                             lanes=list(SUITE["lanes"]), models=None,
                             questions=None)
    assert p["total_cells"] == 12 * 2 * 15 and p["runnable_cells"] == 0
    by = {r["profile_id"]: r for r in p["rows"]}
    assert by["minicpm5-2b-runpod"]["readiness"] == "DISCOVERED"
    assert by["qwen3.8-27b-runpod"]["readiness"] == "BLOCKED_RESOURCE"
    assert "not pinned" in by["qwen3.5-4b-runpod"]["reason"]


# ---- pinning with a fake Hugging Face ----------------------------------------------

SHA = {"Qwen/Qwen3.5-4B": "a" * 40, "google/gemma-4-12B-it": "b" * 40,
       "Qwen/Qwen3.8-27B": "c" * 40, "Qwen/Qwen3.8-27B-AWQ": "d" * 40,
       "LiquidAI/LFM2.5-VL-3B": "e" * 40}
CFG = {"architectures": ["Qwen3ForCausalLM"],
       "max_position_embeddings": 262144, "num_hidden_layers": 36,
       "num_attention_heads": 32, "num_key_value_heads": 8, "head_dim": 128,
       "torch_dtype": "bfloat16"}
WEIGHTS = {"Qwen/Qwen3.5-4B": 8e9, "google/gemma-4-12B-it": 24e9,
           "Qwen/Qwen3.8-27B": 55e9, "Qwen/Qwen3.8-27B-AWQ": 16e9,
           "LiquidAI/LFM2.5-VL-3B": 6e9}
LIC = {"google/gemma-4-12B-it": "gemma"}


def fake_fetch(url: str):
    hf = "https://huggingface.co"
    if url.startswith(f"{hf}/api/models?author=openbmb"):
        return [{"id": "openbmb/MiniCPM5-2B"}, {"id": "openbmb/MiniCPM5_2B"}]
    if url.startswith(f"{hf}/api/models?author=LiquidAI"):
        return [{"id": "LiquidAI/LFM2.5-VL-3B"}, {"id": "LiquidAI/LFM2-1B"}]
    if url.startswith(f"{hf}/api/models?author=Qwen"):
        return [{"id": "Qwen/Qwen3.8-27B-AWQ"}, {"id": "Qwen/Qwen3.8-27B"}]
    if url.startswith(f"{hf}/api/models/"):
        repo = url[len(f"{hf}/api/models/"):].split("?")[0]
        if repo not in SHA:
            raise OSError(f"404 {repo}")
        return {"id": repo, "sha": SHA[repo],
                "cardData": {"license": LIC.get(repo, "apache-2.0")},
                "safetensors": {"total": int(WEIGHTS[repo] / 2)},
                "siblings": [{"rfilename": "model.safetensors",
                              "size": int(WEIGHTS[repo]),
                              "lfs": {"sha256": "f" * 64}},
                             {"rfilename": "tokenizer.json"},
                             {"rfilename": "tokenizer_config.json"}]}
    if url.endswith("/config.json"):
        return CFG
    if url.endswith("/tokenizer_config.json"):
        return {"chat_template": "{% for tool in tools %}...{% endfor %}"}
    raise OSError(f"unexpected {url}")


@pytest.fixture()
def pinned(tmp_path, monkeypatch):
    prof_dir = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", prof_dir)
    pp = _pp()
    monkeypatch.setattr(pp, "PROFILES", prof_dir)
    monkeypatch.setattr(pp, "SUITE", prof_dir / "_runpod_suite.json")
    runtime = tmp_path / "rt"
    roster = pp.run(pp.suite_profiles(), fake_fetch, runtime,
                    do_probe=False, overrides={})
    return pp, prof_dir, runtime, {r["profile_id"]: r for r in roster}


def test_every_model_is_pinned_or_blocked_and_the_roster_continues(pinned):
    _, _, runtime, r = pinned
    assert len(r) == 12                                  # nobody stops it
    assert r["qwen3.5-4b-runpod"]["revision"] == "a" * 40
    assert r["lfm2.5-vl-3b-runpod"]["repository"] == "LiquidAI/LFM2.5-VL-3B"
    assert r["minicpm5-2b-runpod"]["pin_status"] == "PIN_BLOCKED"
    assert "exactly one" in r["minicpm5-2b-runpod"]["reason"]
    assert r["ornith-1.5-9b-runpod"]["pin_status"] == "PIN_BLOCKED"
    assert r["fin-r1-7b-runpod"]["pin_status"] == "PIN_BLOCKED"   # 404
    assert (runtime / "pins" / "ROSTER.json").exists()


def test_pin_records_full_identity_never_latest(pinned):
    _, prof_dir, runtime, _ = pinned
    raw = json.loads((prof_dir / "qwen3.5-4b-runpod.json").read_text())
    art = raw["artifact"]
    assert art["revision"] == "a" * 40 and art["revision"] not in (
        "main", "latest")
    assert art["tokenizer_revision"] == "a" * 40
    assert art["license"] == "apache-2.0"
    assert art["license_status"] == "LICENSE_OK"
    assert art["parameters"] == 4_000_000_000
    assert art["architecture"] == ["Qwen3ForCausalLM"]
    assert art["native_context"] == 262144
    assert art["weights_sha256"] == {"model.safetensors": "f" * 64}
    assert raw["runpod"]["runtime"] == "vllm"
    assert raw["runpod"]["resource_status"] == "FITS_A40"
    full = json.loads((runtime / "pins" / "qwen3.5-4b-runpod.json"
                       ).read_text())
    assert full["pin"]["chat_template_mentions_tools"] is True


def test_fit_arithmetic_and_resource_block(pinned):
    pp, prof_dir, _, r = pinned
    f = r["qwen3.5-4b-runpod"]["fit"]
    kv = 2 * 36 * 8 * 128 * 2 * 32768 / 1e9
    assert abs(f["kv_cache_gb"] - round(kv, 2)) < 0.01
    assert f["weights_gb"] == 8.0 and f["fits"] is True
    big = r["qwen3.8-27b-runpod"]
    assert big["resource_status"] == "RESOURCE_BLOCKED_A40"
    ps = registry.load_profiles(prof_dir)
    st = registry.readiness(ps["qwen3.8-27b-runpod"], approvals={},
                            probes={})
    assert st.status == "BLOCKED_RESOURCE"
    assert "RESOURCE_BLOCKED_A40" in st.reasons[0]


def test_quantized_variant_is_separate_and_never_overwrites_base(pinned):
    _, prof_dir, _, r = pinned
    base = json.loads((prof_dir / "qwen3.8-27b-runpod.json").read_text())
    var = json.loads((prof_dir / "qwen3.8-27b-runpod--awq-4bit.json"
                      ).read_text())
    assert base["artifact"]["repository"] == "Qwen/Qwen3.8-27B"
    assert base["artifact"]["quantization"] is None
    assert var["parent_profile_id"] == "qwen3.8-27b-runpod"
    assert var["artifact"]["quantization"] == "awq-4bit"
    assert var["artifact"]["repository"] == "Qwen/Qwen3.8-27B-AWQ"
    assert var["artifact"]["revision"] == "d" * 40
    assert "--quantization" in var["runpod"]["extra_args"]
    assert r["qwen3.8-27b-runpod--awq-4bit"]["resource_status"] == "FITS_A40"


def test_licence_review_blocks_until_approved(pinned):
    _, prof_dir, _, r = pinned
    assert r["gemma-4-12b-runpod"]["license_status"] == \
        "LICENSE_REVIEW_REQUIRED"
    p = registry.load_profiles(prof_dir)["gemma-4-12b-runpod"]
    ok_probe = {p.profile_id: {"runtime_reachable": True,
                               "model_present": True,
                               "resolved_model": "google/gemma-4-12B-it",
                               "controls": {"tools": True,
                                            "forced_tool_use": True,
                                            "tool_result_roundtrip": True,
                                            "stop_reason_mapping": True}}}
    assert registry.readiness(p, approvals={}, probes=ok_probe).status == \
        "NEEDS_APPROVAL"
    assert registry.readiness(
        p, approvals={"license:gemma-4-12b-runpod": {}},
        probes=ok_probe).status == "READY_E2E"


def test_exact_revision_and_probe_are_both_required(pinned):
    _, prof_dir, _, _ = pinned
    p = registry.load_profiles(prof_dir)["qwen3.5-4b-runpod"]
    assert registry.readiness(p, approvals={}, probes={}).status == \
        "NOT_INSTALLED"
    ok = {p.profile_id: {"runtime_reachable": True, "model_present": True,
                         "resolved_model": "Qwen/Qwen3.5-4B",
                         "controls": {"tools": True, "forced_tool_use": True,
                                      "tool_result_roundtrip": True,
                                      "stop_reason_mapping": True}}}
    assert registry.readiness(p, approvals={}, probes=ok).status == \
        "READY_E2E"
    unpinned = registry.load_profiles()["qwen3.5-4b-runpod"]
    assert registry.readiness(unpinned, approvals={},
                              probes=ok).status == "NOT_INSTALLED"


def test_probe_without_a_tool_parser_fails_explicitly(pinned, tmp_path):
    pp, _, runtime, _ = pinned
    res = pp.serve_and_probe("lfm2.5-vl-3b-runpod", runtime)
    assert res["probe_status"] == "PROBE_FAILED"
    assert "tool-call parser" in res["failure"]


# ---- runner: skip, continue, checkpoint, resume, report --------------------

@pytest.fixture(scope="module")
def mini_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("suite")
    suite = json.loads(json.dumps(SUITE))
    suite["suite_id"] = "test-suite"
    suite["models"] = [
        {"model": "MiniCPM5-2B", "profile_id": "minicpm5-2b-runpod"},
        {"model": "Reference fixture", "profile_id": "fixture-reference"},
        {"model": "Qwen3.8-27B", "profile_id": "qwen3.8-27b-runpod"}]
    suite["questions"] = [q for q in suite["questions"]
                          if q["question_id"] in ("Q01", "Q02")]
    sp = tmp / "suite.json"
    sp.write_text(json.dumps(suite))
    rt = tmp / "rt"
    # The candidate gate: a saved (fixture-as-Opus) reference per question.
    assert build_fixture_reference_set(rt, tmp / "sets", ["Q01", "Q02"]) \
        == 6
    args = ["--suite", str(sp), "--runtime-dir", str(rt), "--run",
            "--confirm-model-calls", "--reference-set",
            str(tmp / "sets" / "OPUS_REFERENCE_SET_V1.json"),
            "--allow-fixture-reference"]
    assert benchmark_suite.main(args) == 0
    cp1 = benchmark_suite.load_checkpoint(rt, suite)
    assert benchmark_suite.main(args) == 0                 # resume
    cp2 = benchmark_suite.load_checkpoint(rt, suite)
    return suite, rt, cp1, cp2


def test_blocked_models_are_skipped_and_the_suite_continues(mini_run):
    suite, rt, cp, _ = mini_run
    assert cp["models"]["minicpm5-2b-runpod"]["status"] == "SKIPPED"
    assert cp["models"]["qwen3.8-27b-runpod"]["status"] == "SKIPPED"
    assert cp["models"]["fixture-reference"]["status"] == "COMPLETED"
    done = [k for k, v in cp["cells"].items() if v["state"] == "DONE"]
    assert sorted(done) == sorted(
        f"fixture-reference|{lane}|{q}" for lane in benchmark_suite.LANE_ORDER
        for q in ("Q01", "Q02"))


def test_checkpoint_resume_does_not_rerun_done_cells(mini_run):
    _, _, cp1, cp2 = mini_run
    assert {k: v["comparison_id"] for k, v in cp1["cells"].items()} == \
        {k: v["comparison_id"] for k, v in cp2["cells"].items()}


def test_every_result_is_exported_with_its_trace(mini_run):
    import zipfile
    _, _, cp, _ = mini_run
    for v in cp["cells"].values():
        names = zipfile.ZipFile(v["export"]).namelist()
        assert "MODEL_IO_TRACE.html" in names
        assert any(n.startswith("model_io/call_") for n in names)


def test_report_with_a_partial_and_blocked_suite(mini_run):
    suite, rt, _, _ = mini_run
    out = suite_report.write(rt, suite)
    rep = json.loads((out / "report.json").read_text())
    models = {m["MODEL_VARIANT"]: m for m in rep["models"]}
    assert models["minicpm5-2b-runpod"]["RUN_STATUS"] == "SKIPPED"
    assert models["qwen3.8-27b-runpod"]["RUN_STATUS"] == "SKIPPED"
    for k in ("PARAMETERS", "QUANTIZATION", "EXACT_REVISION",
              "LICENSE_STATUS", "RUNTIME", "CONTEXT", "VRAM_PEAK_MIB"):
        assert k in models["fixture-reference"]
    cells = {(c["profile_id"], c["lane"], c["question_id"]): c
             for c in rep["cells"]}
    assert len(cells) == 3 * 2 * 2
    blocked = cells[("minicpm5-2b-runpod", "FROZEN_BASELINE", "Q01")]
    assert blocked["state"] == "SKIPPED" and blocked["reason"]
    a = cells[("fixture-reference", "ASSISTED_V1", "Q02")]
    b = cells[("fixture-reference", "FROZEN_BASELINE", "Q02")]
    assert a["assistance_packet"]["sha256"] and b["assistance_packet"] is None
    assert set(a["vs_baseline"]) == {"S1", "S2", "S3", "S4", "correctness"}
    assert b["stages"] and b["correctness"] and b["answer"]
    assert b["trace"].endswith("/model-io")
    assert (out / "report.html").exists() and (out / "cells.csv").exists()
    assert "winner" not in (out / "report.html").read_text().lower().replace(
        "no overall winner", "")


def test_runner_refusals(tmp_path, monkeypatch, capsys):
    args = ["--runtime-dir", str(tmp_path)]
    assert benchmark_suite.main(args) == 0
    assert "no model was called" in capsys.readouterr().out
    assert benchmark_suite.main(args + ["--run"]) == 2
    assert "--confirm-model-calls" in capsys.readouterr().out
    monkeypatch.setenv("MODEL_LAB_FULL_IO_TRACE", "false")
    assert benchmark_suite.main(args + ["--run",
                                        "--confirm-model-calls"]) == 2
    assert "Model I/O Trace" in capsys.readouterr().out
