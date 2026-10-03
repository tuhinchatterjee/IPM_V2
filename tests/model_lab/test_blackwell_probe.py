"""RTX PRO 6000 Blackwell startup repair, from live Pod evidence.

1. SM 12.x: vLLM 0.30.0's FlashInfer top-k/top-p sampler fails its JIT
   architecture check ("FlashInfer requires GPUs with sm75 or higher"). The
   recorded workaround launches the server with VLLM_USE_FLASHINFER_SAMPLER=0
   (vLLM's own control); A40 and other hardware keep vLLM's defaults.
2. Pinned snapshots whose config.json does not parse are detected BEFORE any
   server start and only that metadata is re-downloaded, at the exact pinned
   revision; otherwise MODEL_METADATA_CORRUPT and the roster continues.

Offline: fake vLLM/torch packages, fake caches, fake downloader, a fake
server process. No model server, no model call, no Opus call.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT

RUNPOD = ROOT / "scripts" / "model_lab" / "runpod"
sys.path.insert(0, str(RUNPOD))
import hardware  # noqa: E402
import hf_metadata as hm  # noqa: E402
import vllm_runtime as vr  # noqa: E402

LIVE_STACK = """INFO 10-03 12:00:01 [gpu_model_runner.py] Compiling the sampler
Traceback (most recent call last):
  File "/workspace/creditprobe-model-lab/venvs/vllm/lib/python3.12/site-packages/vllm/v1/worker/gpu/sample/sampler.py", line 331, in sample
    sampled = flashinfer_sample(processed_logits, top_k, top_p).to(torch.int64)
  File "/workspace/creditprobe-model-lab/venvs/vllm/lib/python3.12/site-packages/flashinfer/sampling.py", line 812, in top_k_top_p_sampling_from_logits
  File "/workspace/creditprobe-model-lab/venvs/vllm/lib/python3.12/site-packages/flashinfer/jit/core.py", line 88, in check_cuda_arch
    raise RuntimeError("FlashInfer requires GPUs with sm75 or higher")
RuntimeError: FlashInfer requires GPUs with sm75 or higher
WARNING huggingface_hub.file_download: Could not set the permissions on the file '/workspace-global/x'. Error: [Errno 1] Operation not permitted.
"""
LIVE_JSON = """OSError: It looks like the config file at '/workspace-global/creditprobe-model-lab/cache/huggingface/hub/models--Qwen--Qwen3.5-4B/snapshots/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/config.json' is not a valid JSON file.
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
"""
RTX = {"gpu": "NVIDIA RTX PRO 6000 Blackwell Server Edition",
       "driver_version": "595.91.07", "host_cuda": "13.2",
       "gpu_memory": "97887 MiB", "gpu_count": 1, "compute_capability": "12.0"}
A40 = {"gpu": "NVIDIA A40", "driver_version": "580.95.05",
       "host_cuda": "13.0", "gpu_memory": "46068 MiB", "gpu_count": 1,
       "compute_capability": "8.6"}
QREV = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"


def _pp():
    spec = importlib.util.spec_from_file_location(
        "pin_and_probe_bw", RUNPOD / "pin_and_probe_models.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _no_model_no_opus(monkeypatch):
    import anthropic

    import backend.model_lab.adapters as adapters
    from backend.model_lab import probe

    def boom(*a, **k):
        raise AssertionError("a model / provider was called")
    for mod, name in ((adapters, "build_provider"), (anthropic, "Anthropic"),
                      (probe, "probe_profile")):
        monkeypatch.setattr(mod, name, boom)
    monkeypatch.delenv("VLLM_USE_FLASHINFER_SAMPLER", raising=False)


# ---- 1. Blackwell sampler workaround ----------------------------------------------

def _intro_with_capability(tmp_path, monkeypatch, cap):
    import test_vllm_runtime as tvr
    site = tvr.fake_vllm(tmp_path)
    with open(site / "torch" / "__init__.py", "a") as f:
        f.write(f"cuda.get_device_capability = staticmethod(lambda i: {cap!r})\n")
    monkeypatch.setenv("PYTHONPATH", str(site))
    return vr.introspect(sys.executable, archs=[], tool_parsers=[],
                         reasoning_parsers=[], timeout=120)


def test_sm120_generates_the_recorded_sampler_workaround(tmp_path,
                                                         monkeypatch):
    intro = _intro_with_capability(tmp_path, monkeypatch, (12, 0))
    assert intro["cuda_capability"] == "12.0"
    man = vr.build_manifest(RTX, intro, {})
    gc = man["gpu_compute"]
    assert gc["compute_capability"] == "12.0"
    assert gc["compute_capability_source"] == "torch.cuda.get_device_capability"
    assert gc["flashinfer"] == "0.6.18.post1" and gc["vllm"] == "0.30.0"
    assert gc["driver_version"] == "595.91.07" and gc["host_cuda"] == "13.2"
    assert gc["torch_cuda"] == "13.0"
    se = man["server_env"]
    assert se["env"] == {"VLLM_USE_FLASHINFER_SAMPLER": "0"}
    sb = se["sampling_backend"]
    assert sb["flashinfer_sampler"] == "disabled"
    assert sb["reason"] == "BLACKWELL_SM120_FLASHINFER_ARCH_CHECK_WORKAROUND"
    assert sb["fallback"] == "vllm_native"
    assert "sm75" in sb["evidence"]


def test_a40_does_not_inherit_the_blackwell_workaround(tmp_path,
                                                       monkeypatch):
    intro = _intro_with_capability(tmp_path, monkeypatch, (8, 6))
    se = vr.build_manifest(A40, intro, {})["server_env"]
    assert se["env"] == {}
    assert se["sampling_backend"]["flashinfer_sampler"] == "vllm default"
    # nvidia-smi capability alone also decides; unknown keeps defaults
    assert vr.server_env(vr.gpu_compute(RTX, None))["env"] == \
        {"VLLM_USE_FLASHINFER_SAMPLER": "0"}
    assert vr.server_env(vr.gpu_compute({"gpu": "?"}, None))["env"] == {}
    for cap in ("9.0", "10.0", "8.9", "7.5"):
        assert vr.server_env({"compute_capability": cap})["env"] == {}, cap


def test_compute_capability_is_detected_and_persisted(tmp_path):
    host = vr.parse_nvidia_smi(
        "Driver Version: 595.91.07   CUDA Version: 13.2",
        "NVIDIA RTX PRO 6000 Blackwell Server Edition, 595.91.07, 97887 MiB",
        "12.0\n")
    assert host["compute_capability"] == "12.0"
    rec = hardware.from_host(host)
    assert rec["compute_capability"] == "12.0"
    assert rec["hardware_id"] == "RTX_PRO_6000_BLACKWELL_96GB"
    hardware.save_current(tmp_path, rec)
    assert hardware.current(tmp_path)["compute_capability"] == "12.0"
    assert "compute_capability" not in vr.parse_nvidia_smi(
        "", "NVIDIA A40, 1, 1 MiB", "Field \"compute_cap\" is not valid")


def test_generated_server_environment_contains_the_override(tmp_path,
                                                            monkeypatch):
    pp = _pp()
    captured = {}

    class P:
        pid, returncode = 999999, None

    def popen(args, **kw):
        captured.update(kw)
        return P()
    monkeypatch.setattr(pp.subprocess, "Popen", popen)
    se = vr.server_env(vr.gpu_compute(RTX, None))
    pp.start_server("qwen3.5-4b-runpod", tmp_path, se)
    assert captured["env"]["VLLM_USE_FLASHINFER_SAMPLER"] == "0"
    head = (tmp_path / "logs" / "vllm_qwen3.5-4b-runpod.log").read_text()
    assert "# env VLLM_USE_FLASHINFER_SAMPLER=0" in head
    assert "BLACKWELL_SM120_FLASHINFER_ARCH_CHECK_WORKAROUND" in head
    pp.start_server("qwen3.5-4b-runpod", tmp_path,
                    vr.server_env(vr.gpu_compute(A40, None)))
    assert "VLLM_USE_FLASHINFER_SAMPLER" not in captured["env"]


@pytest.mark.parametrize("host,expect", [(RTX, "0"), (A40, "")])
def test_serve_sh_launches_vllm_with_the_recorded_env(tmp_path, host,
                                                      expect):
    root = tmp_path / "app"
    (root / "scripts/model_lab/runpod").mkdir(parents=True)
    shutil.copy(RUNPOD / "serve.sh", root / "scripts/model_lab/runpod")
    (root / "profiles").mkdir()
    (root / "profiles/m.json").write_text(json.dumps({
        "status": "NOT_INSTALLED", "context_tokens": 32768,
        "artifact": {"repository": "Qwen/Qwen3.5-4B", "revision": QREV},
        "runpod": {"suggested_tool_call_parser": "qwen3_coder",
                   "reasoning_parser": "qwen3", "extra_args": []}}))
    rt = tmp_path / "rt"
    vr.save_manifest(rt, {"verdict": {"status": "COMPATIBLE"},
                          "server_env": vr.server_env(vr.gpu_compute(
                              host, None))})
    fake = tmp_path / "vllm"
    fake.write_text("#!/bin/sh\necho \"SAMPLER=$VLLM_USE_FLASHINFER_SAMPLER\"\n"
                    "echo \"ARGS=$*\"\n")
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("VLLM_", "MODEL_", "CREDITPROBE_", "HF_"))}
    env |= {"MODEL_LAB_PYTHON": sys.executable, "VLLM_BIN": str(fake),
            "CREDITPROBE_HOME": str(tmp_path), "CREDITPROBE_VENV_DIR":
            str(tmp_path), "MODEL_CACHE_DIR": str(tmp_path / "cache"),
            "MODEL_LAB_RUNTIME_DIR": str(rt), "HF_HOME": str(tmp_path / "hf")}
    p = subprocess.run(["bash", str(root / "scripts/model_lab/runpod/serve.sh"),
                        "m"], capture_output=True, text=True, env=env,
                       timeout=60)
    assert p.returncode == 0, p.stderr
    assert f"SAMPLER={expect}\n" in p.stdout
    assert f"--revision {QREV}" in p.stdout
    assert ("workaround: FlashInfer sampler disabled" in p.stdout) == \
        (expect == "0")


def test_live_flashinfer_error_maps_to_its_own_class():
    assert vr.classify_server_log(LIVE_STACK) == \
        "BLACKWELL_FLASHINFER_SAMPLER_INCOMPATIBLE"
    assert vr.concise_cause(LIVE_STACK) == \
        "RuntimeError: FlashInfer requires GPUs with sm75 or higher"
    assert vr.classify_server_log(LIVE_JSON) == "MODEL_METADATA_CORRUPT"
    assert "is not a valid JSON file" in vr.concise_cause(LIVE_JSON)
    assert vr.classify_server_log("RuntimeError: CUDA error: out of memory\n"
                                  "torch.OutOfMemoryError: CUDA out of "
                                  "memory") == "CUDA_OOM"
    assert vr.classify_server_log("ValueError: something else") == \
        "MODEL_SERVER_START_FAILED"
    for c in ("BLACKWELL_FLASHINFER_SAMPLER_INCOMPATIBLE",
              "MODEL_METADATA_CORRUPT", "MODEL_SERVER_START_TIMEOUT",
              "CUDA_OOM", "MODEL_DOWNLOAD_FAILED", "TOOL_PARSER_MISSING",
              "LICENSE_REVIEW_REQUIRED", "PIN_BLOCKED",
              "MODEL_SERVER_START_FAILED"):
        assert c in vr.TAXONOMY, c


# ---- 2. pinned metadata integrity ----------------------------------------------------

def _snapshot(cache: Path, repo=("Qwen/Qwen3.5-4B"), rev=QREV,
              config: bytes = b"", with_weights=True) -> Path:
    base = cache / f"models--{repo.replace('/', '--')}"
    snap = base / "snapshots" / rev
    blobs = base / "blobs"
    snap.mkdir(parents=True)
    blobs.mkdir(parents=True)
    (blobs / "cfg0").write_bytes(config)
    (snap / "config.json").symlink_to(blobs / "cfg0")
    (snap / "tokenizer_config.json").write_text('{"model_max_length": 1}')
    if with_weights:
        (blobs / ("w" * 8)).write_bytes(b"\x00" * 4096)
        (snap / "model.safetensors").symlink_to(blobs / ("w" * 8))
    return snap


class Downloader:
    """Stands in for hf_hub_download(revision=<pin>, force_download=True)
    into the Pod-local STAGING cache it is given: the standard HF layout,
    blobs/<etag> (etag = git blob id of the bytes) and a snapshot link.
    Records calls."""

    def __init__(self, content=b'{"architectures": ["X"]}', other_rev=None,
                 fail=False):
        self.calls, self.content = [], content
        self.other_rev, self.fail = other_rev, fail

    def __call__(self, repo, revision, filename, cache):
        self.calls.append((repo, revision, filename, str(cache)))
        if self.fail:
            raise RuntimeError("HTTP 503 from the Hub")
        rev = self.other_rev or revision
        snap = hm.snapshot(Path(cache), repo, rev)
        snap.mkdir(parents=True, exist_ok=True)
        blob = snap.parents[1] / "blobs" / hm.git_blob_sha1(self.content)
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(self.content)
        target = snap / filename
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(os.path.relpath(blob, target.parent))
        return str(target)


def test_invalid_config_is_detected_and_recorded(tmp_path):
    _snapshot(tmp_path / "hub", config=b"")
    r = hm.ensure("q", "Qwen/Qwen3.5-4B", QREV, [tmp_path / "hub"],
                  downloader=Downloader(fail=True), runtime=tmp_path / "rt")
    assert r["status"] == "MODEL_METADATA_CORRUPT"
    ev = r["events"][0]
    assert ev["event"] == "CACHE_METADATA_CORRUPT"
    assert ev["repository"] == "Qwen/Qwen3.5-4B" and ev["revision"] == QREV
    assert ev["path"].endswith(f"snapshots/{QREV}/config.json")
    assert ev["bytes"] == 0 and ev["failure"] == "empty content (0 bytes read)"
    assert ev["kind"] == "symlink" and ev["resolved_content_size"] == 0
    rec = json.loads((tmp_path / "rt/cache_integrity/q.json").read_text())
    assert rec[-1]["status"] == "MODEL_METADATA_CORRUPT"
    for bad, why in ((b"<html>error</html>", "invalid JSON"),
                     (b"\xff\xfe\x00", "not UTF-8"), (b"[1, 2]", "not an object")):
        d = tmp_path / f"c{len(why)}"
        _snapshot(d, config=bad)
        assert why in hm.check("Qwen/Qwen3.5-4B", QREV, [d])["bad"][0][
            "failure"]


def test_exact_revision_metadata_is_force_refreshed_and_weights_kept(
        tmp_path):
    snap = _snapshot(tmp_path / "hub", config=b"")
    w = (snap / "model.safetensors").resolve()
    w_sha = hashlib.sha256(w.read_bytes()).hexdigest()
    dl = Downloader()
    r = hm.ensure("q", "Qwen/Qwen3.5-4B", QREV, [tmp_path / "hub"],
                  downloader=dl, staging=tmp_path / "stage")
    assert r["status"] == "CACHE_METADATA_REPAIRED"
    assert dl.calls == [("Qwen/Qwen3.5-4B", QREV, "config.json",
                         str(tmp_path / "stage"))]    # only the bad file,
    #                                                   staged Pod-locally
    rep = [e for e in r["events"] if e["event"] == "CACHE_METADATA_REPAIRED"]
    assert rep[0]["old_status"] == "CACHE_METADATA_CORRUPT"
    assert rep[0]["new_status"] == "VALID"
    assert rep[0]["revision_unchanged"] is True
    assert json.loads((snap / "config.json").read_text())
    assert hashlib.sha256(w.read_bytes()).hexdigest() == w_sha
    assert (snap / "model.safetensors").resolve() == w


def test_the_revision_cannot_change_during_repair(tmp_path):
    _snapshot(tmp_path / "hub", config=b"")
    dl = Downloader(other_rev="f" * 40)
    r = hm.ensure("q", "Qwen/Qwen3.5-4B", QREV, [tmp_path / "hub"],
                  downloader=dl)
    assert r["status"] == "MODEL_METADATA_CORRUPT"
    assert any(e["event"] == "REPAIR_REFUSED" for e in r["events"])
    assert all(c[1] == QREV for c in dl.calls)
    for rev in ("main", "latest", "", None):
        dl2 = Downloader()
        r = hm.ensure("q", "Qwen/Qwen3.5-4B", rev, [tmp_path / "hub"],
                      downloader=dl2)
        assert r["status"] == "MODEL_METADATA_CORRUPT" and dl2.calls == []


def test_valid_cache_is_not_downloaded_again(tmp_path):
    _snapshot(tmp_path / "hub", config=b'{"model_type": "qwen3_5"}')
    dl = Downloader()
    r = hm.ensure("q", "Qwen/Qwen3.5-4B", QREV, [tmp_path / "hub"],
                  downloader=dl)
    assert r["status"] == "VALID" and dl.calls == []
    r = hm.ensure("q", "Qwen/Qwen3.5-4B", QREV, [tmp_path / "empty"],
                  downloader=dl)
    assert r["status"] == "ABSENT" and dl.calls == []


def test_content_from_another_revision_is_caught_by_blob_id(tmp_path):
    good = b'{"model_type": "qwen3_5"}'
    _snapshot(tmp_path / "hub", config=b'{"model_type": "old"}')
    r = hm.check("Qwen/Qwen3.5-4B", QREV, [tmp_path / "hub"],
                 {"config.json": hm.git_blob_sha1(good)})
    assert r["status"] == "CACHE_METADATA_CORRUPT"
    assert "blob id mismatch" in r["bad"][0]["failure"]
    info = {"siblings": [
        {"rfilename": "config.json", "blobId": "abc"},
        {"rfilename": "model.safetensors", "blobId": "x", "lfs": {"sha256": "y"}},
        {"rfilename": "README.md", "blobId": "z"}]}
    assert hm.expected_blob_ids(info) == {"config.json": "abc"}


# ---- 3. the probe path and the roster -------------------------------------------------

@pytest.fixture()
def probe_env(tmp_path, monkeypatch):
    """A suite pinned offline on a simulated 96 GB host, a compatible
    runtime manifest, persistent HF caches, a fake server process."""
    import test_runpod_suite as trs
    pp = _pp()
    prof = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", prof)
    monkeypatch.setattr(pp, "PROFILES", prof)
    monkeypatch.setattr(pp, "SUITE", prof / "_runpod_suite.json")
    rt = tmp_path / "rt"
    hardware.save_current(rt, hardware.from_host(RTX))
    hub, models = tmp_path / "hf" / "hub", tmp_path / "models"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    monkeypatch.setenv("MODEL_CACHE_DIR", str(models))
    monkeypatch.setattr(pp, "METADATA_FETCH",
                        lambda url: (_ for _ in ()).throw(OSError("offline")))
    started: list[str] = []

    class FakeSrv:
        returncode = 1

        def __init__(self, log):
            self.log_path, self.pid = log, 0

        def poll(self):
            return 1

    def fake_start(pid, runtime, server_env=None):
        started.append(pid)
        log = runtime / "logs" / f"vllm_{pid}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("# env " + json.dumps((server_env or {}).get("env"))
                       + "\n" + LIVE_STACK)
        assert (server_env or {}).get("env") == \
            {"VLLM_USE_FLASHINFER_SAMPLER": "0"}
        return FakeSrv(str(log))
    monkeypatch.setattr(pp, "start_server", fake_start)
    monkeypatch.setattr(pp, "stop_server", lambda srv: None)
    ids = ["qwen3.5-4b-runpod", "qwen3.8-27b-runpod"]
    pp.run(ids, trs.fake_fetch, rt, do_probe=False, overrides={})
    gc = vr.gpu_compute(RTX, {"cuda_capability": "12.0", "torch_cuda": "13.0",
                              "versions": {"vllm": "0.30.0",
                                           "flashinfer-python": "0.6.18.post1"}})
    vr.save_manifest(rt, {"verdict": vr.host_verdict(RTX), "gpu_compute": gc,
                          "server_env": vr.server_env(gc),
                          "parsers": {"tool": list(vr.STATIC_TOOL_PARSERS),
                                      "reasoning": list(
                                          vr.STATIC_REASONING_PARSERS)},
                          "profiles": {i: {"status": "RUNTIME_READY"}
                                       for i in ids}})
    return pp, rt, hub, ids, started, trs.fake_fetch


def test_corrupt_metadata_stops_one_model_and_the_roster_continues(
        probe_env, capsys):
    pp, rt, hub, ids, started, fetch = probe_env
    _snapshot(hub, repo="Qwen/Qwen3.5-4B", rev="a" * 40, config=b"")
    monkeypatch_dl = Downloader(fail=True)
    pp.METADATA_DOWNLOADER = monkeypatch_dl
    roster = {r["profile_id"]: r for r in pp.run(
        ids, fetch, rt, do_probe=True, overrides={})}
    q4, q27 = roster["qwen3.5-4b-runpod"], roster["qwen3.8-27b-runpod"]
    assert q4["probe_status"] == "MODEL_METADATA_CORRUPT"
    assert "config.json" in q4["root_cause"]
    assert q4["repository"] == "Qwen/Qwen3.5-4B" and q4["revision"] == "a" * 40
    assert "qwen3.5-4b-runpod" not in started          # never served
    # the next model went on, and its Blackwell failure is specific
    assert started == ["qwen3.8-27b-runpod"]
    assert q27["probe_status"] == "BLACKWELL_FLASHINFER_SAMPLER_INCOMPATIBLE"
    assert q27["log_path"].endswith("logs/vllm_qwen3.8-27b-runpod.log")
    assert q27["returncode"] == 1
    assert q27["root_cause"] == \
        "RuntimeError: FlashInfer requires GPUs with sm75 or higher"
    assert q27["sampling_backend"]["reason"] == \
        "BLACKWELL_SM120_FLASHINFER_ARCH_CHECK_WORKAROUND"
    out = capsys.readouterr().out
    assert "models not READY_E2E" in out
    assert "log " + q27["log_path"] in out and "(rc 1)" in out
    assert "workaround applied: BLACKWELL_SM120" in out
    ros = json.loads((rt / "pins" / "ROSTER.json").read_text())["roster"]
    assert {r["profile_id"]: r["probe_status"] for r in ros} == {
        "qwen3.5-4b-runpod": "MODEL_METADATA_CORRUPT",
        "qwen3.8-27b-runpod": "BLACKWELL_FLASHINFER_SAMPLER_INCOMPATIBLE"}
    assert pp.main(["--runtime-dir", str(rt), "--summary"]) == 0
    assert "MODEL_METADATA_CORRUPT" in capsys.readouterr().out
    # the full server log is kept, never replaced by the summary
    assert "Traceback" in Path(q27["log_path"]).read_text()


def test_a_successful_repair_proceeds_to_server_start(probe_env):
    pp, rt, hub, ids, started, fetch = probe_env
    snap = _snapshot(hub, repo="Qwen/Qwen3.5-4B", rev="a" * 40, config=b"")
    w = (snap / "model.safetensors").resolve()
    pp.METADATA_DOWNLOADER = Downloader()
    res = pp.serve_and_probe("qwen3.5-4b-runpod", rt)
    assert started == ["qwen3.5-4b-runpod"]            # after the repair
    assert res["metadata"]["status"] == "CACHE_METADATA_REPAIRED"
    assert "CACHE_METADATA_CORRUPT" in res["metadata"]["events"]
    assert w.exists()                                  # weights untouched
    rec = json.loads((rt / "cache_integrity" / "qwen3.5-4b-runpod.json")
                     .read_text())
    assert rec[-1]["status"] == "CACHE_METADATA_REPAIRED"


def test_server_start_timeout_is_its_own_class(probe_env, monkeypatch):
    pp, rt, hub, ids, started, fetch = probe_env
    pp.METADATA_DOWNLOADER = Downloader()
    monkeypatch.setattr(pp, "wait_ready", lambda srv: (
        f"vLLM not ready after 1800s; see {srv.log_path}", "timeout"))
    res = pp.serve_and_probe("qwen3.8-27b-runpod", rt)
    assert res["probe_status"] == "MODEL_SERVER_START_TIMEOUT"
    assert res["log_path"] and res["root_cause"]


# ---- 4. --smoke-only on a fresh Pod ---------------------------------------------------

def test_smoke_only_on_a_fresh_pod_builds_its_own_offline_env(tmp_path):
    import test_runpod_execution_storage as tes
    pod = tes.Pod(tmp_path)
    dep = tes._bundle(pod.tmp / "upload", extra={
        "tests/test_pristine.py": tes.SMOKE_TEST.encode(),
        "requirements.txt": b"pytest\n"})
    assert pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only"
                    ).returncode == 0
    tes._populated_volume(pod)
    shutil.rmtree(pod.app)                       # fresh Pod: no .venv at all
    uv_log = tmp_path / "uv.log"
    uv = pod.sim / "bin" / "uv"
    uv.write_text(f"""#!/bin/sh
echo "uv $*" >> {uv_log}
if [ "$1" = venv ]; then
  for last; do :; done
  mkdir -p "$last/bin"
  printf '#!/bin/sh\\nexec %s "$@"\\n' {sys.executable} > "$last/bin/python"
  chmod +x "$last/bin/python"
fi
exit 0
""")
    uv.chmod(0o755)
    p = pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--smoke-only",
                 CREDITPROBE_SMOKE_TARGETS="tests")    # no SMOKE_PYTHON
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "fresh Pod: installing the Pod-local offline Python environment" \
        in out
    calls = uv_log.read_text()
    assert "uv venv" in calls and "pip install" in calls
    venv = pod.app / "source" / ".venv"
    assert venv.is_dir() and str(venv).startswith(str(pod.app))
    assert out.index("offline smoke tests passed") < \
        out.index("pinned identities restored")
    prof = json.loads((pod.app / "source/profiles/m-runpod.json").read_text())
    assert prof["artifact"]["revision"] == tes.REAL_PIN
