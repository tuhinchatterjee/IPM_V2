"""Hardware-specific fit: historical A40 evidence is kept unchanged, the
current host (RTX PRO 6000 Blackwell 96 GB on the live Pod) is computed
independently from its detected VRAM, and only the CURRENT host decides
probe eligibility. Offline: the host record and the Hub are synthetic; no
nvidia-smi, no weights, no server, no model and no Opus call."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from conftest import ROOT

RUNPOD = ROOT / "scripts" / "model_lab" / "runpod"
sys.path.insert(0, str(RUNPOD))
import hardware  # noqa: E402
import vllm_runtime as vr  # noqa: E402

from backend.model_lab import registry  # noqa: E402

LIVE_RTX = vr.parse_nvidia_smi(
    "| NVIDIA-SMI 580.159.04   Driver Version: 580.159.04   CUDA Version: 13.0 |",
    "NVIDIA RTX PRO 6000 Blackwell Server Edition, 580.159.04, 97887 MiB\n")
RTX = hardware.from_host(LIVE_RTX)
A40_LIVE = hardware.from_host(vr.parse_nvidia_smi(
    "Driver Version: 580.95.05 CUDA Version: 13.0",
    "NVIDIA A40, 580.95.05, 46068 MiB\n"))

#: Fit inputs shaped like the pinned records (bf16 / "full precision").
QWEN27 = {"weights_bytes": 55_000_000_000, "native_context": 262144,
          "config": {"num_hidden_layers": 64, "num_attention_heads": 40,
                     "num_key_value_heads": 8, "head_dim": 128}}
GPTOSS = {"weights_bytes": 41_800_000_000, "native_context": 131072,
          "config": {"num_hidden_layers": 24, "num_attention_heads": 64,
                     "num_key_value_heads": 8, "head_dim": 64}}


def _pp():
    spec = importlib.util.spec_from_file_location(
        "pin_and_probe_hw", RUNPOD / "pin_and_probe_models.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- detection -------------------------------------------------------------------

def test_live_rtx_pro_6000_is_detected_from_nvidia_smi():
    assert RTX["hardware_id"] == "RTX_PRO_6000_BLACKWELL_96GB"
    assert RTX["memory_total_mib"] == 97887
    assert RTX["vram_gb_for_fit"] == pytest.approx(102.64, abs=0.01)
    assert RTX["usable_budget_gb"] == pytest.approx(92.38, abs=0.01)
    assert RTX["driver_version"] == "580.159.04" and RTX["host_cuda"] == "13.0"
    assert "fit-v2" in RTX["fit_method"]
    assert A40_LIVE["hardware_id"] == "A40_48GB"
    assert hardware.hardware_id("NVIDIA H200 NVL", 143771) == "H200_NVL_140GB"


def test_detected_host_is_persisted_with_history(tmp_path):
    hardware.save_current(tmp_path, RTX)
    assert hardware.current(tmp_path)["hardware_id"] == \
        "RTX_PRO_6000_BLACKWELL_96GB"
    assert len(list((tmp_path / "hardware" / "history").glob("*.json"))) == 1
    assert hardware.current(tmp_path / "none")["assumed"] is True


# ---- historical A40 evidence is preserved ----------------------------------------

@pytest.mark.parametrize("inputs,name", [(QWEN27, "qwen27"),
                                         (GPTOSS, "gpt-oss-20b")])
def test_a40_evidence_unchanged_and_96gb_computed_independently(inputs,
                                                                name):
    pp = _pp()
    a40 = hardware.fit(inputs, context=32768, max_output=8192)
    assert a40["resource_status"] == "RESOURCE_BLOCKED_A40"
    raw = {"status": "BLOCKED_RESOURCE", "max_output_tokens": 8192,
           "status_reason": "RESOURCE_BLOCKED_A40",
           "artifact": {"fit_inputs": inputs},
           "runpod": {"max_model_len": 32768, "fit": a40,
                      "resource_status": "RESOURCE_BLOCKED_A40"}}
    before = json.dumps(raw["runpod"]["fit"], sort_keys=True)
    cur = pp.apply_fits(raw, inputs, RTX)
    rp = raw["runpod"]
    # the A40 record is untouched and kept as labelled evidence
    assert json.dumps(rp["fit"], sort_keys=True) == before
    assert rp["resource_status"] == "RESOURCE_BLOCKED_A40"
    assert rp["fit_by_hardware"]["A40_48GB"]["resource_status"] == \
        "RESOURCE_BLOCKED_A40"
    assert "historical" in rp["fit_by_hardware"]["A40_48GB"]["source"]
    # the 96 GB result is its own computation from detected VRAM
    assert cur["resource_status"] == "FITS_RTX_PRO_6000_BLACKWELL_96GB"
    assert cur["budget_gb"] == pytest.approx(92.38, abs=0.01)
    assert rp["fit_by_hardware"]["RTX_PRO_6000_BLACKWELL_96GB"] == cur
    assert raw["status"] == "NOT_INSTALLED"
    assert "historical RESOURCE_BLOCKED_A40" in raw["status_reason"]
    # a later A40 run does not rewrite either record
    pp.apply_fits(raw, inputs, hardware.HISTORICAL_A40)
    assert json.dumps(rp["fit"], sort_keys=True) == before
    assert rp["fit_by_hardware"]["RTX_PRO_6000_BLACKWELL_96GB"] == cur


def test_too_big_for_96gb_is_blocked_on_the_current_host():
    pp = _pp()
    huge = QWEN27 | {"weights_bytes": 95_000_000_000}
    raw = {"artifact": {}, "runpod": {"max_model_len": 32768}}
    cur = pp.apply_fits(raw, huge, RTX)
    assert cur["resource_status"] == \
        "RESOURCE_BLOCKED_RTX_PRO_6000_BLACKWELL_96GB"
    assert raw["status"] == "BLOCKED_RESOURCE"


def test_readiness_follows_the_current_host_not_the_a40():
    base = json.loads((ROOT / "profiles/qwen3.8-27b-runpod.json").read_text())
    base["status"] = "NOT_INSTALLED"
    base["artifact"] |= {"repository": "Qwen/Qwen3.8-27B", "revision": "c" * 40,
                         "pin_status": "PINNED", "license_status": "LICENSE_OK"}
    base["runpod"] |= {"resource_status": "RESOURCE_BLOCKED_A40",
                       "suggested_tool_call_parser": "hermes"}
    probe = {"qwen3.8-27b-runpod": {
        "runtime_reachable": True, "model_present": True,
        "resolved_model": "Qwen/Qwen3.8-27B",
        "controls": {"tools": True, "forced_tool_use": True,
                     "tool_result_roundtrip": True,
                     "stop_reason_mapping": True}}}

    def ready(rp_extra):
        raw = json.loads(json.dumps(base))
        raw["runpod"] |= rp_extra
        prof = registry._validate(raw, Path("qwen3.8-27b-runpod.json"))
        return registry.readiness(prof, approvals={}, probes=probe).status
    # no current-host assessment: the A40 result applies (unchanged)
    assert ready({}) == "BLOCKED_RESOURCE"
    assert ready({"current_host": {
        "resource_status": "FITS_RTX_PRO_6000_BLACKWELL_96GB",
        "hardware_id": "RTX_PRO_6000_BLACKWELL_96GB"}}) == "READY_E2E"
    assert ready({"current_host": {
        "resource_status": "RESOURCE_BLOCKED_RTX_PRO_6000_BLACKWELL_96GB",
        "hardware_id": "RTX_PRO_6000_BLACKWELL_96GB"}}) == "BLOCKED_RESOURCE"


# ---- the pin step on a 96 GB host vs the A40 ----------------------------------------

@pytest.fixture()
def suite_env(tmp_path, monkeypatch):
    import test_runpod_suite as trs
    pp = _pp()
    prof = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", prof)
    monkeypatch.setattr(pp, "PROFILES", prof)
    monkeypatch.setattr(pp, "SUITE", prof / "_runpod_suite.json")

    def no_live_gpu():
        raise AssertionError("the pin step must not read nvidia-smi")
    monkeypatch.setattr(vr, "read_host", no_live_gpu)
    probed: list[str] = []

    def fake_probe(pid, runtime, keep=False):
        probed.append(pid)               # records eligibility only
        return {"probe_status": "READY_E2E"}
    monkeypatch.setattr(pp, "serve_and_probe", fake_probe)
    return pp, prof, trs.fake_fetch, probed


def test_on_96gb_eligible_models_proceed_to_probe(suite_env, tmp_path):
    pp, prof, fetch, probed = suite_env
    rt = tmp_path / "rt96"
    hardware.save_current(rt, RTX)
    roster = {r["profile_id"]: r for r in pp.run(
        pp.suite_profiles(), fetch, rt, do_probe=True, overrides={})}
    q27 = roster["qwen3.8-27b-runpod"]
    assert q27["resource_status"] == "FITS_RTX_PRO_6000_BLACKWELL_96GB"
    assert q27["historical_a40_status"] == "RESOURCE_BLOCKED_A40"
    assert "qwen3.8-27b-runpod" in probed
    raw = json.loads((prof / "qwen3.8-27b-runpod.json").read_text())
    assert raw["runpod"]["resource_status"] == "RESOURCE_BLOCKED_A40"
    assert set(raw["runpod"]["fit_by_hardware"]) == {
        "A40_48GB", "RTX_PRO_6000_BLACKWELL_96GB"}
    assert raw["status"] == "NOT_INSTALLED"
    assert raw["artifact"]["fit_inputs"]["weights_bytes"] == 55_000_000_000


def test_on_the_a40_the_same_models_stay_resource_blocked(suite_env,
                                                         tmp_path):
    pp, prof, fetch, probed = suite_env
    rt = tmp_path / "rt48"
    hardware.save_current(rt, A40_LIVE)
    roster = {r["profile_id"]: r for r in pp.run(
        pp.suite_profiles(), fetch, rt, do_probe=True, overrides={})}
    assert roster["qwen3.8-27b-runpod"]["resource_status"] == \
        "RESOURCE_BLOCKED_A40"
    assert roster["qwen3.8-27b-runpod"]["probe_status"] == "RESOURCE_BLOCKED"
    assert "qwen3.8-27b-runpod" not in probed
    assert "qwen3.5-4b-runpod" in probed


def test_resumed_pin_on_a_new_host_keeps_revision_and_a40_evidence(
        suite_env, tmp_path):
    pp, prof, fetch, probed = suite_env
    rt = tmp_path / "rt"
    hardware.save_current(rt, A40_LIVE)
    pp.run(["qwen3.8-27b-runpod"], fetch, rt, do_probe=False, overrides={})
    first = json.loads((prof / "qwen3.8-27b-runpod.json").read_text())
    a40_before = json.dumps(first["runpod"]["fit"], sort_keys=True)
    hardware.save_current(rt, RTX)                     # new Pod, new GPU

    def no_network(url):
        raise AssertionError(f"re-resolved an existing pin: {url}")
    (rec,) = pp.run(["qwen3.8-27b-runpod"], no_network, rt, do_probe=False,
                    overrides={})
    assert rec["kept_existing_pin"] is True
    assert rec["revision"] == first["artifact"]["revision"]
    assert rec["resource_status"] == "FITS_RTX_PRO_6000_BLACKWELL_96GB"
    again = json.loads((prof / "qwen3.8-27b-runpod.json").read_text())
    assert json.dumps(again["runpod"]["fit"], sort_keys=True) == a40_before
    assert again["runpod"]["fit_by_hardware"]["A40_48GB"]["resource_status"] \
        == "RESOURCE_BLOCKED_A40"
    pins = json.loads((rt / "pins" / "qwen3.8-27b-runpod.json").read_text())
    assert pins["pin"]["revision"] == first["artifact"]["revision"]


def test_bootstrap_no_longer_assumes_48gb():
    boot = (RUNPOD / "RUNPOD_BOOTSTRAP.sh").read_text()
    assert "assumes 48 GB" not in boot
    assert "hardware.py detect" in boot
    assert boot.index("hardware.py detect") < boot.index(
        "pin_and_probe_models.py --runtime-dir")
