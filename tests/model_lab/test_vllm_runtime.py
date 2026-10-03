"""vLLM runtime layer on RunPod: driver/CUDA gate, environment provenance,
parser registry verification, model-import preflight, failure taxonomy.

The real introspection script runs against a FAKE vLLM environment (tiny
`vllm`, `torch`, `transformers` packages with dist-info) so the exact code
the Pod runs is exercised offline: no GPU, no weights, no model server, no
model call and no Opus call.
"""

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
import vllm_runtime as vr  # noqa: E402

A40_570 = {"gpu": "NVIDIA A40", "driver_version": "570.211.01",
           "host_cuda": "12.8", "gpu_count": 1, "gpu_memory": "46068 MiB"}
A40_580 = A40_570 | {"driver_version": "580.65.06", "host_cuda": "13.0"}

LIVE_HEADER = """
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 570.211.01             Driver Version: 570.211.01     CUDA Version: 12.8     |
|-----------------------------------------+------------------------+----------------------+
"""
LIVE_ERROR = ("RuntimeError: The NVIDIA driver on your system is too old "
              "(found version 12080). Please update your GPU driver")
MINISTRAL_ERROR = ("ImportError: cannot import name 'PixtralRotaryEmbedding' "
                   "from 'transformers.models.pixtral.modeling_pixtral'")


# ---- 1. driver / CUDA gate ------------------------------------------------------

def test_live_driver_570_with_cuda13_runtime_is_blocked_before_probe():
    host = vr.parse_nvidia_smi(LIVE_HEADER,
                               "NVIDIA A40, 570.211.01, 46068 MiB\n")
    assert host == A40_570
    v = vr.host_verdict(host)
    assert v["status"] == "VLLM_HOST_DRIVER_INCOMPATIBLE"
    block = vr.verdict_block(v)
    for line in ("VLLM_HOST_DRIVER_INCOMPATIBLE", "driver_version: 570.211.01",
                 "host_cuda: 12.8", "vllm_version: 0.30.0", "vllm_cuda: 13.0",
                 "minimum_required_driver: 580.65.06", "remediation:",
                 "redeploy the Pod on a RunPod host with a compatible driver"):
        assert line in block, line


@pytest.mark.parametrize("driver,cuda,ok", [
    ("580.65.06", "13.0", True), ("580.95.05", "13.0", True),
    ("590.44.01", "13.1", True), ("580.40.01", "13.0", False),
    ("575.57.08", "12.9", False), (None, None, False)])
def test_driver_threshold(driver, cuda, ok):
    v = vr.host_verdict({"driver_version": driver, "host_cuda": cuda})
    assert (v["status"] == "COMPATIBLE") is ok
    assert v["minimum_required_driver"] == "580.65.06"


def test_host_command_writes_the_manifest_and_exits_7(tmp_path, monkeypatch,
                                                      capsys):
    monkeypatch.setattr(vr, "read_host", lambda: A40_570)
    assert vr.main(["host", "--runtime-dir", str(tmp_path)]) == 7
    man = vr.load_manifest(tmp_path)
    assert man["verdict"]["status"] == "VLLM_HOST_DRIVER_INCOMPATIBLE"
    assert man["requested"]["vllm"] == "0.30.0"
    assert man["requested"]["wheel"]["sha256"].startswith("ef52ee58")
    assert all(r["status"] == "HOST_DRIVER_INCOMPATIBLE"
               for r in man["profiles"].values())
    assert "VLLM_HOST_DRIVER_INCOMPATIBLE" in capsys.readouterr().out
    monkeypatch.setattr(vr, "read_host", lambda: A40_580)
    assert vr.main(["host", "--runtime-dir", str(tmp_path)]) == 0
    assert vr.main(["show", "--runtime-dir", str(tmp_path)]) == 0


def test_nothing_is_worked_around():
    """No CUDA-compat package, driver change, other vLLM build or engine."""
    boot = (RUNPOD / "RUNPOD_BOOTSTRAP.sh").read_text()
    code = "\n".join(ln for ln in boot.splitlines()
                     if not ln.lstrip().startswith(("#", "echo")))
    for banned in ("cuda-compat", "cuda_compat", "apt-get install",
                   "nvidia-driver", "vllm==0.2", "--extra-index-url",
                   "wheels.vllm.ai", "sglang", "llama.cpp", "ollama"):
        assert banned not in code, banned
    assert "vllm_runtime.py host" in boot
    assert boot.index("vllm_runtime.py host") < boot.index("uv pip install -q -p \"$VENV_VLLM")
    assert "vllm-0.30.0-constraints.txt" in boot


# ---- 2. provenance -----------------------------------------------------------------

def test_constraints_are_the_vllm_ci_lock():
    lines = dict(ln.split("==") for ln in
                 vr.CONSTRAINTS.read_text().splitlines()
                 if ln and not ln.startswith("#"))
    for k in ("torch", "transformers", "tokenizers", "huggingface-hub",
              "mistral-common", "xgrammar"):
        assert lines[k] == vr.LOCK[k], k
    assert lines["transformers"] == "5.16.1"


def test_wheel_identity_is_verified(tmp_path):
    import io

    class Fake(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    with pytest.raises(ValueError, match="sha256"):
        vr.fetch_wheel(tmp_path, opener=lambda url, timeout: Fake(b"x"))


# ---- a fake vLLM environment ---------------------------------------------------------

def _dist(site: Path, name: str, version: str, wheel: str = "") -> None:
    d = site / f"{name.replace('-', '_')}-{version}.dist-info"
    d.mkdir(parents=True)
    (d / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\n"
                                f"Version: {version}\n")
    if wheel:
        (d / "WHEEL").write_text(wheel)
        (d / "INSTALLER").write_text("uv\n")


def fake_vllm(tmp: Path, *, transformers: str = "5.16.1",
              pixtral_symbols: bool = True, cuda_error: str | None = None,
              tool_parsers=("hermes", "qwen3_coder", "mistral", "gemma4",
                            "granite4", "minicpm5", "lfm2")) -> Path:
    site = tmp / "site"
    for name, ver in vr.LOCK.items():
        if name == "transformers":
            ver = transformers
        _dist(site, name, ver, "Wheel-Version: 1.0\nTag: cp38-abi3-"
              "manylinux_2_28_x86_64\n" if name == "vllm" else "")
    (site / "torch").mkdir()
    init = f"raise RuntimeError({cuda_error!r})" if cuda_error else "pass"
    (site / "torch" / "__init__.py").write_text(
        "class version:\n    cuda = '13.0'\n"
        "class cuda:\n"
        f"    @staticmethod\n    def init():\n        {init}\n"
        "    @staticmethod\n    def device_count():\n        return 1\n"
        "    @staticmethod\n    def get_device_name(i):\n"
        "        return 'NVIDIA A40'\n")
    pix = site / "transformers" / "models" / "pixtral"
    pix.mkdir(parents=True)
    for d in (site / "transformers", site / "transformers" / "models", pix):
        (d / "__init__.py").write_text("")
    (pix / "modeling_pixtral.py").write_text(
        "def apply_rotary_pos_emb(*a): pass\n" + (
            "class PixtralRotaryEmbedding: pass\n"
            "def position_ids_in_meshgrid(*a): pass\n"
            if pixtral_symbols else ""))
    v = site / "vllm"
    m = v / "model_executor" / "models"
    m.mkdir(parents=True)
    for d in (v, v / "model_executor", m):
        (d / "__init__.py").write_text("")
    mgr = ("class {cls}:\n    lazy_parsers = {names!r}\n"
           "    @classmethod\n    def list_registered(cls):\n"
           "        return list(cls.lazy_parsers)\n"
           "    @classmethod\n    def {get}(cls, n):\n"
           "        if n not in cls.lazy_parsers: raise KeyError(n)\n"
           "        return object\n")
    (v / "tool_parsers").mkdir()
    (v / "tool_parsers" / "__init__.py").write_text(mgr.format(
        cls="ToolParserManager", get="get_tool_parser",
        names={n: ("m", "C") for n in tool_parsers}))
    (v / "reasoning").mkdir()
    (v / "reasoning" / "__init__.py").write_text(mgr.format(
        cls="ReasoningParserManager", get="get_reasoning_parser",
        names={n: ("m", "C") for n in ("qwen3", "gemma4", "mistral")}))
    (m / "registry.py").write_text(
        "_TEXT_GENERATION_MODELS = {'Qwen3_5ForCausalLM': ('qwen3_5', "
        "'Qwen3_5ForCausalLM')}\n"
        "_MULTIMODAL_MODELS = {'PixtralForConditionalGeneration': "
        "('pixtral', 'PixtralForConditionalGeneration'), "
        "'Qwen3_5ForConditionalGeneration': ('qwen3_5', "
        "'Qwen3_5ForConditionalGeneration')}\n")
    (m / "qwen3_5.py").write_text("class Qwen3_5ForCausalLM: pass\n"
                                  "class Qwen3_5ForConditionalGeneration: "
                                  "pass\n")
    (m / "pixtral.py").write_text(
        "from transformers.models.pixtral.modeling_pixtral import (\n"
        "    PixtralRotaryEmbedding, apply_rotary_pos_emb,\n"
        "    position_ids_in_meshgrid)\n"
        "class PixtralForConditionalGeneration: pass\n")
    return site


def _profiles(*, qwen_parser="qwen3_coder", ministral=True):
    out = {"qwen3.5-4b-runpod": {"artifact": {
        "architecture": ["Qwen3_5ForConditionalGeneration"]},
        "runpod": {"tool_call_parser": qwen_parser,
                   "suggested_tool_call_parser": qwen_parser,
                   "reasoning_parser": "qwen3"}}}
    if ministral:
        out["ministral-3-8b-runpod"] = {"artifact": {}, "runpod": {
            "tool_call_parser": "mistral",
            "suggested_tool_call_parser": "mistral",
            "preflight_architectures": ["PixtralForConditionalGeneration"]}}
    return out


def _intro(monkeypatch, site: Path, profiles: dict) -> dict:
    monkeypatch.setenv("PYTHONPATH", str(site))
    archs, tools, reasons = [], [], []
    for raw in profiles.values():
        rp = raw["runpod"]
        archs += rp.get("preflight_architectures") or \
            raw["artifact"].get("architecture") or []
        tools.append(rp["tool_call_parser"])
        if rp.get("reasoning_parser"):
            reasons.append(rp["reasoning_parser"])
    return vr.introspect(sys.executable, archs=archs, tool_parsers=tools,
                         reasoning_parsers=reasons, timeout=120)


# ---- 3. parsers -------------------------------------------------------------------

def test_parser_registry_is_read_from_the_installed_vllm(tmp_path,
                                                         monkeypatch):
    site = fake_vllm(tmp_path)
    intro = _intro(monkeypatch, site, _profiles())
    assert "qwen3_coder" in intro["tool_parsers"]["names"]
    assert intro["tool_parsers"]["loaded"]["qwen3_coder"] == "ok"
    man = vr.build_manifest(A40_580, intro, _profiles())
    assert man["parsers"]["tool"] == sorted(
        ["hermes", "qwen3_coder", "mistral", "gemma4", "granite4",
         "minicpm5", "lfm2"])
    assert man["profiles"]["qwen3.5-4b-runpod"]["status"] == "RUNTIME_READY"
    assert man["installed"]["versions"]["vllm"] == "0.30.0"
    assert man["installed"]["torch_cuda"] == "13.0"
    assert man["installed"]["vllm_wheel"]["WHEEL"].startswith("Wheel-Version")
    assert man["lock_mismatches"] in ([], [f"python {intro['python']} "
                                           f"(expected 3.12.x)"])


def test_unregistered_parser_is_tool_parser_missing(tmp_path, monkeypatch):
    site = fake_vllm(tmp_path, tool_parsers=("hermes",))
    profs = _profiles(ministral=False)
    man = vr.build_manifest(A40_580, _intro(monkeypatch, site, profs), profs)
    r = man["profiles"]["qwen3.5-4b-runpod"]
    assert r["status"] == "TOOL_PARSER_MISSING"
    assert "qwen3_coder" in r["detail"]
    assert vr.profile_gate(man, "qwen3.5-4b-runpod")["probe_status"] == \
        "TOOL_PARSER_MISSING"


def test_parser_plan_uses_registered_candidates_and_template_markers():
    reg, rreg = vr.STATIC_TOOL_PARSERS, vr.STATIC_REASONING_PARSERS
    qwen = {"tool_parser_candidates": ["qwen3_coder", "hermes"],
            "reasoning_parser": "qwen3"}
    xml = vr.parser_plan(qwen, ["<function=", "<parameter=", "<tool_call>"],
                         reg, rreg)
    assert xml["tool_call_parser"] == "qwen3_coder"
    js = vr.parser_plan(qwen, ["<tool_call>"], reg, rreg)
    assert js["tool_call_parser"] == "hermes"
    gemma = vr.parser_plan({"tool_parser_candidates": ["gemma4"],
                            "reasoning_parser": "gemma4"},
                           ["<|tool_call>"], reg, rreg)
    assert gemma["status"] == "ASSIGNED_UNPROVEN"
    ornith = vr.parser_plan({"tool_parser_candidates": []}, ["<tool_call>"],
                            reg, rreg)
    assert ornith["tool_call_parser"] == "hermes"
    assert "detected" in ornith["evidence"]
    none = vr.parser_plan({"tool_parser_candidates": []}, [], reg, rreg)
    assert none["status"] == "TOOL_PARSER_MISSING"
    for fam in ("minicpm5", "gemma4", "granite4", "qwen3_coder", "hermes",
                "mistral", "lfm2"):
        assert fam in vr.STATIC_TOOL_PARSERS, fam
    for fam in ("gemma4", "qwen3"):
        assert fam in vr.STATIC_REASONING_PARSERS, fam


def test_suite_profiles_carry_registered_family_parsers():
    prof = {p.stem: json.loads(p.read_text())
            for p in (ROOT / "profiles").glob("*-runpod*.json")}
    want = {"minicpm5-2b-runpod": ["minicpm5"],
            "gemma-4-12b-runpod": ["gemma4"],
            "granite-4.2-8b-runpod": ["granite4"],
            "qwen3.5-4b-runpod": ["qwen3_coder", "hermes"],
            "qwen3.5-9b-runpod": ["qwen3_coder", "hermes"],
            "ministral-3-8b-runpod": ["mistral"],
            "lfm2.5-vl-3b-runpod": ["lfm2"]}
    for pid, cands in want.items():
        rp = prof[pid]["runpod"]
        assert rp["tool_parser_candidates"] == cands, pid
        assert all(c in vr.STATIC_TOOL_PARSERS for c in cands)
    assert prof["gemma-4-12b-runpod"]["runpod"]["reasoning_parser"] == \
        "gemma4"
    assert "--reasoning-parser" not in prof["qwen3.5-4b-runpod"]["runpod"][
        "extra_args"]                          # serve.sh adds it once


# ---- 4. Ministral / Transformers ----------------------------------------------------

def test_ministral_with_newer_transformers_is_transformers_incompatible(
        tmp_path, monkeypatch):
    site = fake_vllm(tmp_path, transformers="5.17.0", pixtral_symbols=False)
    profs = _profiles()
    man = vr.build_manifest(A40_580, _intro(monkeypatch, site, profs), profs)
    r = man["profiles"]["ministral-3-8b-runpod"]
    assert r["status"] == "TRANSFORMERS_INCOMPATIBLE"
    assert "PixtralRotaryEmbedding" in r["detail"]
    assert any("transformers==5.17.0" in m for m in man["lock_mismatches"])
    # the other model is judged on its own import, not changed for Ministral
    assert man["profiles"]["qwen3.5-4b-runpod"]["status"] in (
        "RUNTIME_READY", "VLLM_RUNTIME_INCOMPATIBLE")
    assert vr.classify_error(MINISTRAL_ERROR) == "TRANSFORMERS_INCOMPATIBLE"


def test_ministral_imports_cleanly_with_the_locked_transformers(tmp_path,
                                                                monkeypatch):
    site = fake_vllm(tmp_path, transformers="5.16.1", pixtral_symbols=True)
    profs = _profiles()
    intro = _intro(monkeypatch, site, profs)
    assert intro["archs"]["PixtralForConditionalGeneration"]["ok"] is True
    man = vr.build_manifest(A40_580, intro, profs)
    assert man["profiles"]["ministral-3-8b-runpod"]["status"] == \
        "RUNTIME_READY"


def test_empirical_cuda_init_failure_blocks_the_host(tmp_path, monkeypatch):
    site = fake_vllm(tmp_path, cuda_error=LIVE_ERROR.split(": ", 1)[1])
    profs = _profiles()
    man = vr.build_manifest(A40_580, _intro(monkeypatch, site, profs), profs)
    assert man["verdict"]["status"] == "VLLM_HOST_DRIVER_INCOMPATIBLE"
    assert "too old" in man["verdict"]["empirical"]
    assert {r["status"] for r in man["profiles"].values()} == \
        {"HOST_DRIVER_INCOMPATIBLE"}


# ---- taxonomy, downloads, geesefs ---------------------------------------------------

def test_server_log_taxonomy_and_geesefs_chmod_noise(tmp_path):
    chmod = ("WARNING huggingface_hub.file_download: Could not set the "
             "permissions on the file '/workspace-global/x/blobs/abc.incomplete'"
             ". Error: [Errno 1] Operation not permitted.\nContinuing without "
             "setting permissions.\n")
    assert vr.classify_server_log(chmod + "RuntimeError: Engine core "
                                  "initialization failed") == \
        "MODEL_SERVER_START_FAILED"
    assert vr.classify_server_log(chmod) == "MODEL_SERVER_START_FAILED"
    assert vr.classify_server_log(LIVE_ERROR) == "HOST_DRIVER_INCOMPATIBLE"
    assert vr.classify_server_log(MINISTRAL_ERROR) == \
        "TRANSFORMERS_INCOMPATIBLE"
    assert vr.classify_server_log("huggingface_hub.errors."
                                  "RepositoryNotFoundError: 404 Client Error"
                                  ) == "MODEL_DOWNLOAD_FAILED"
    # an OOM while starting is CUDA_OOM; RESOURCE_BLOCKED is the fit skip
    assert vr.classify_server_log("torch.OutOfMemoryError: CUDA out of "
                                  "memory") == "CUDA_OOM"
    # the download itself is judged by the files, not by permission bits
    snap = tmp_path / "models--Qwen--Qwen3.5-4B" / "snapshots" / ("a" * 40)
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"x" * 10)
    pin = {"repository": "Qwen/Qwen3.5-4B", "revision": "a" * 40,
           "weights": [{"file": "model.safetensors", "bytes": 10}]}
    assert vr.verify_download(pin, tmp_path)["ok"] is True
    (snap / "model.safetensors").write_bytes(b"x" * 3)
    assert vr.verify_download(pin, tmp_path)["size_mismatch"] == \
        ["model.safetensors"]
    assert set(vr.TAXONOMY) >= {
        "HOST_DRIVER_INCOMPATIBLE", "VLLM_RUNTIME_INCOMPATIBLE",
        "TRANSFORMERS_INCOMPATIBLE", "TOOL_PARSER_MISSING",
        "MODEL_SERVER_START_FAILED", "MODEL_DOWNLOAD_FAILED",
        "MODEL_TOOL_ROUNDTRIP_FAILED", "RESOURCE_BLOCKED",
        "LICENSE_REVIEW_REQUIRED", "PIN_BLOCKED"}


# ---- pin script: identity, licence, blocked-model continuation ---------------------

def _pp():
    spec = importlib.util.spec_from_file_location(
        "pin_and_probe_x", RUNPOD / "pin_and_probe_models.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hub(repo="ornith-ai/Ornith-1.5-9B", *, author="ornith-ai",
         card="# Ornith-1.5-9B\n", base=None, listed=True):
    hf = "https://huggingface.co"

    def fetch(url):
        if url.startswith(f"{hf}/api/models?author="):
            return [{"id": repo}] if listed else []
        if url.startswith(f"{hf}/api/models/"):
            return {"id": repo, "sha": "e" * 40, "author": author,
                    "cardData": {"base_model": base} if base else {}}
        if url.endswith("/README.md"):
            if card is None:
                raise OSError("404")
            return card
        raise OSError(url)
    return fetch


def test_ornith_identity_is_verified_live_never_assumed():
    pp = _pp()
    src = {"org": "ornith-ai", "name_pattern": r"^Ornith-1\.5-9B$",
           "expected_repository": "ornith-ai/Ornith-1.5-9B",
           "identity_required": True}
    repo = "ornith-ai/Ornith-1.5-9B"
    ok, why, ev = pp.verify_identity(repo, _hub()(
        f"https://huggingface.co/api/models/{repo}"), _hub(), src)
    assert ok and ev["verdict"] == "VERIFIED" and ev["model_card_sha256"]
    for kw, needle in ((dict(author="someone-else"), "Hub author"),
                       (dict(card=None), "no model card"),
                       (dict(card="# A different model\n"), "does not name"),
                       (dict(listed=False), "not listed"),
                       (dict(base="mirror-org/Ornith-1.5-9B"), "re-upload")):
        f = _hub(**kw)
        ok, why, _ = pp.verify_identity(
            repo, f(f"https://huggingface.co/api/models/{repo}"), f, src)
        assert not ok and needle in why, (kw, why)
    prof = json.loads((ROOT / "profiles/ornith-1.5-9b-runpod.json")
                      .read_text())
    assert prof["artifact"]["revision"] is None        # not pinned from here
    assert prof["artifact"]["source"]["identity_required"] is True


@pytest.mark.parametrize("card,status", [
    ({"license": "apache-2.0"}, "LICENSE_OK"),
    ({"license": "other", "license_name": "lfm1.0",
      "license_link": "LICENSE"}, "LICENSE_REVIEW_REQUIRED"),
    ({}, "LICENSE_REVIEW_REQUIRED")])
def test_licence_is_classified_from_the_source_with_evidence(card, status):
    pp = _pp()
    repo = "LiquidAI/LFM2.5-VL-3B"

    def fetch(url):
        if "/api/models/" in url:
            return {"id": repo, "sha": "f" * 40, "author": "LiquidAI",
                    "cardData": card, "tags": [],
                    "siblings": [{"rfilename": "LICENSE"},
                                 {"rfilename": "model.safetensors",
                                  "size": 10, "lfs": {"sha256": "0" * 64}}]}
        raise OSError(url)
    p = pp.pin(repo, fetch)
    assert p["license_status"] == status
    ev = p["license_evidence"]
    assert ev["licence_files"] == [
        f"https://huggingface.co/{repo}/blob/{'f' * 40}/LICENSE"]
    assert ev["card_license"] == card.get("license")
    assert ev["license_name"] == card.get("license_name")


def test_a_blocked_host_blocks_every_probe_and_the_roster_continues(
        tmp_path, monkeypatch):
    import test_runpod_suite as trs
    pp = _pp()
    prof_dir = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", prof_dir)
    monkeypatch.setattr(pp, "PROFILES", prof_dir)
    monkeypatch.setattr(pp, "SUITE", prof_dir / "_runpod_suite.json")
    rt = tmp_path / "rt"
    vr.save_manifest(rt, vr.build_manifest(A40_570, None, {}))

    def no_server(*a, **k):
        raise AssertionError("a model server was started")
    monkeypatch.setattr(pp, "start_server", no_server)
    roster = {r["profile_id"]: r for r in pp.run(
        pp.suite_profiles(), trs.fake_fetch, rt, do_probe=True,
        overrides={})}
    assert len(roster) == 12
    assert roster["qwen3.5-4b-runpod"]["probe_status"] == \
        "HOST_DRIVER_INCOMPATIBLE"
    assert roster["qwen3.8-27b-runpod"]["probe_status"] == "RESOURCE_BLOCKED"
    assert roster["minicpm5-2b-runpod"]["probe_status"] == "PIN_BLOCKED"
    assert roster["gemma-4-12b-runpod"]["probe_status"] == \
        "LICENSE_REVIEW_REQUIRED"
    assert "PROBE_FAILED" not in {r.get("probe_status")
                                  for r in roster.values()}


def test_preflight_makes_no_model_and_no_opus_call(tmp_path, monkeypatch):
    import anthropic

    import backend.model_lab.adapters as adapters
    from backend.model_lab import probe as lab_probe

    def boom(*a, **k):
        raise AssertionError("a model / provider was called")
    for mod, name in ((adapters, "build_provider"), (anthropic, "Anthropic"),
                      (lab_probe, "probe_profile")):
        monkeypatch.setattr(mod, name, boom)
    import subprocess
    real = subprocess.Popen

    def popen(args, *a, **k):
        cmd = " ".join(map(str, args)) if isinstance(args, list) else args
        assert "serve" not in cmd and "vllm" not in cmd.split()[0], cmd
        return real(args, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", popen)
    site = fake_vllm(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(site))
    monkeypatch.setattr(vr, "read_host", lambda: A40_580)
    prof_dir = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", prof_dir)
    rc = vr.main(["preflight", "--runtime-dir", str(tmp_path / "rt"),
                  "--venv-python", sys.executable, "--profiles-dir",
                  str(prof_dir)])
    assert rc in (0, 9)                    # 9 only for the local python
    man = vr.load_manifest(tmp_path / "rt")
    assert man["stage"].startswith("runtime preflight")
    assert man["verdict"]["status"] == "COMPATIBLE"


def test_restored_pins_never_overwrite_new_parser_settings(tmp_path):
    import runpod_storage as rs
    paths = rs.paths_for(str(tmp_path / "g"), str(tmp_path / "app"))
    src = Path(paths["CREDITPROBE_SOURCE_ROOT"]) / "profiles"
    keep = Path(paths["MODEL_LAB_PINNED_PROFILES_DIR"])
    src.mkdir(parents=True)
    keep.mkdir(parents=True)
    new = json.loads((ROOT / "profiles/gemma-4-12b-runpod.json").read_text())
    (src / "gemma-4-12b-runpod.json").write_text(json.dumps(new))
    old = json.loads(json.dumps(new))
    old["artifact"] |= {"revision": "d" * 40, "pin_status": "PINNED",
                        "repository": "google/gemma-4-12B-it"}
    old["runpod"] |= {"suggested_tool_call_parser": None,
                      "tool_parser_candidates": [], "extra_args": ["--old"],
                      "fit": {"fits": True}, "resource_status": "FITS_A40"}
    (keep / "gemma-4-12b-runpod.json").write_text(json.dumps(old))
    assert rs.restore_pins(paths) == ["gemma-4-12b-runpod"]
    got = json.loads((src / "gemma-4-12b-runpod.json").read_text())
    assert got["artifact"]["revision"] == "d" * 40          # identity kept
    assert got["runpod"]["fit"] == {"fits": True}
    assert got["runpod"]["tool_parser_candidates"] == ["gemma4"]  # new
    assert got["runpod"]["extra_args"] == []
