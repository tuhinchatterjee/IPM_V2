"""Real Global Volume (fuse.geesefs) behaviour for pinned HF metadata, and the
targeted single-profile probe.

Live evidence for Qwen/Qwen3.5-4B @851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a:
snapshots/<rev>/config.json is a symlink to ../../blobs/557d961b...; the blob
is 3161 bytes of valid JSON; reading through the link works; but geesefs
reports the SYMLINK's own lstat size as 0. The same snapshot also held
zero-byte REGULAR files (chat_template.jinja, model.safetensors.index.json,
preprocessor_config.json, tokenizer.json, tokenizer_config.json,
video_preprocessor_config.json).

Offline: the geesefs lstat behaviour is reproduced by reporting st_size 0
for symlinks; downloads go to a fake staging Hub. No model, no Opus.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest
from conftest import ROOT

RUNPOD = ROOT / "scripts" / "model_lab" / "runpod"
sys.path.insert(0, str(RUNPOD))
import hardware  # noqa: E402
import hf_metadata as hm  # noqa: E402

REPO, REV = "Qwen/Qwen3.5-4B", "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
LIVE_BLOB = "557d961b205319c6a7da5f757f565b69b3967b7d"
LIVE_ZERO = ("chat_template.jinja", "model.safetensors.index.json",
             "preprocessor_config.json", "tokenizer.json",
             "tokenizer_config.json", "video_preprocessor_config.json")


def _config_3161() -> bytes:
    """A valid Qwen3.5 config of exactly 3161 bytes."""
    base = {"model_type": "qwen3_5",
            "architectures": ["Qwen3_5ForConditionalGeneration"],
            "text_config": {"num_hidden_layers": 32}, "pad": ""}
    raw = json.dumps(base, indent=2).encode()
    base["pad"] = "x" * (3161 - len(raw))
    raw = json.dumps(base, indent=2).encode()
    assert len(raw) == 3161
    return raw


CONFIG = _config_3161()


@pytest.fixture()
def geesefs_lstat(monkeypatch):
    """geesefs: a symlink's own lstat reports st_size 0."""
    real = os.lstat

    def lstat(p, *a, **k):
        st = real(p, *a, **k)
        if stat.S_ISLNK(st.st_mode):
            vals = list(st)
            vals[6] = 0
            return os.stat_result(vals)
        return st
    monkeypatch.setattr(os, "lstat", lstat)


def _live_snapshot(cache: Path, *, zero_files=LIVE_ZERO) -> Path:
    root = cache / f"models--{REPO.replace('/', '--')}"
    snap, blobs = root / "snapshots" / REV, root / "blobs"
    snap.mkdir(parents=True)
    blobs.mkdir(parents=True)
    (blobs / LIVE_BLOB).write_bytes(CONFIG)
    (snap / "config.json").symlink_to(f"../../blobs/{LIVE_BLOB}")
    for name in zero_files:
        (snap / name).write_bytes(b"")                  # zero-byte regular
    w = blobs / ("e" * 64)
    w.write_bytes(b"\x01" * 8192)
    (snap / "model.safetensors-00001-of-00002.safetensors").symlink_to(
        f"../../blobs/{'e' * 64}")
    return snap


# ---- the live geesefs symlink --------------------------------------------------------

def test_geesefs_symlink_with_zero_lstat_size_is_valid_by_content(
        tmp_path, geesefs_lstat):
    snap = _live_snapshot(tmp_path / "hub", zero_files=())
    entry = snap / "config.json"
    assert os.lstat(entry).st_size == 0               # the geesefs symptom
    r = hm.validate_file(entry, repo_root=snap.parents[1])
    assert r["ok"] is True
    assert r["kind"] == "symlink"
    assert r["link_target"] == f"../../blobs/{LIVE_BLOB}"
    assert r["link_metadata_size"] == 0
    assert r["resolved_content_size"] == 3161
    c = hm.check(REPO, REV, [tmp_path / "hub"])
    assert c["status"] == "VALID"
    calls = []
    res = hm.ensure("qwen3.5-4b-runpod", REPO, REV, [tmp_path / "hub"],
                    downloader=lambda *a: calls.append(a))
    assert res["status"] == "VALID" and calls == []    # never "repaired"


def test_broken_target_broken_symlink_and_escaping_symlink(tmp_path):
    snap = _live_snapshot(tmp_path / "hub", zero_files=())
    root = snap.parents[1]
    (root / "blobs" / "bad0").write_bytes(b"")
    (snap / "generation_config.json").symlink_to("../../blobs/bad0")
    (root / "blobs" / "bad1").write_bytes(b"<html>gateway timeout</html>")
    (snap / "tokenizer_config.json").symlink_to("../../blobs/bad1")
    (snap / "special_tokens_map.json").symlink_to("../../blobs/missing")
    outside = tmp_path / "elsewhere.json"
    outside.write_text('{"looks": "valid"}')
    (snap / "preprocessor_config.json").symlink_to(outside)
    bad = {Path(b["path"]).name: b for b in
           hm.check(REPO, REV, [tmp_path / "hub"])["bad"]}
    assert bad["generation_config.json"]["failure"] == \
        "empty content (0 bytes read)"
    assert "invalid JSON" in bad["tokenizer_config.json"]["failure"]
    assert "dangling symlink" in bad["special_tokens_map.json"]["failure"]
    assert "escapes the repository cache" in \
        bad["preprocessor_config.json"]["failure"]
    assert "config.json" not in bad


def test_zero_byte_regular_files_from_the_live_snapshot_are_flagged(
        tmp_path):
    _live_snapshot(tmp_path / "hub")
    c = hm.check(REPO, REV, [tmp_path / "hub"])
    flagged = {b["file"]: b for b in c["bad"]}
    assert set(flagged) == set(LIVE_ZERO)
    for b in flagged.values():
        assert b["kind"] == "regular"
        assert b["resolved_content_size"] == 0
    names = {f["file"] for f in c["files"]}
    assert "config.json" in names
    assert not any(n.endswith(".safetensors") for n in names)  # never read


# ---- exact-revision repair ---------------------------------------------------------

LIVE_CONTENT = {
    "chat_template.jinja": b"{% for m in messages %}{{ m.content }}{% endfor %}",
    "model.safetensors.index.json": b'{"metadata": {}, "weight_map": {}}',
    "preprocessor_config.json": b'{"image_processor_type": "Qwen2VL"}',
    "tokenizer.json": b'{"version": "1.0", "model": {"type": "BPE"}}',
    "tokenizer_config.json": b'{"model_max_length": 262144}',
    "video_preprocessor_config.json": b'{"fps": 2}'}


class StagingHub:
    """hf_hub_download(revision=<pin>) into the staging cache: the standard
    layout, blobs/<git blob id>, snapshot entry linked to it."""

    def __init__(self, content=LIVE_CONTENT, wrong_rev=None):
        self.content, self.wrong_rev, self.calls = content, wrong_rev, []

    def __call__(self, repo, revision, filename, cache):
        self.calls.append((repo, revision, filename))
        data = self.content[filename]
        snap = hm.snapshot(Path(cache), repo, self.wrong_rev or revision)
        blob = snap.parents[1] / "blobs" / hm.git_blob_sha1(data)
        blob.parent.mkdir(parents=True, exist_ok=True)
        snap.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        e = snap / filename
        if e.exists() or e.is_symlink():
            e.unlink()
        e.symlink_to(os.path.relpath(blob, e.parent))
        return str(e)


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes())
            .hexdigest() for p in root.rglob("*")
            if p.is_file() and not p.is_symlink()}


def test_live_snapshot_is_repaired_at_the_exact_revision(tmp_path,
                                                         geesefs_lstat):
    hub = tmp_path / "hub"
    snap = _live_snapshot(hub)
    root = snap.parents[1]
    weights = root / "blobs" / ("e" * 64)
    w_before = hashlib.sha256(weights.read_bytes()).hexdigest()
    cfg_before = (root / "blobs" / LIVE_BLOB).read_bytes()
    stage = tmp_path / "stage"
    hub_dl = StagingHub()
    res = hm.ensure("qwen3.5-4b-runpod", REPO, REV, [hub], downloader=hub_dl,
                    staging=stage, runtime=tmp_path / "rt")
    assert res["status"] == "CACHE_METADATA_REPAIRED"
    assert sorted(c[2] for c in hub_dl.calls) == sorted(LIVE_ZERO)
    assert {c[1] for c in hub_dl.calls} == {REV}        # exact revision only
    assert {c[0] for c in hub_dl.calls} == {REPO}
    for name in LIVE_ZERO:                              # read back by content
        e = snap / name
        assert e.is_symlink() and e.read_bytes() == LIVE_CONTENT[name]
        assert os.readlink(e) == f"../../blobs/{hm.git_blob_sha1(LIVE_CONTENT[name])}"
    # the valid config blob and the weights are untouched
    assert (root / "blobs" / LIVE_BLOB).read_bytes() == cfg_before
    assert os.readlink(snap / "config.json") == f"../../blobs/{LIVE_BLOB}"
    assert hashlib.sha256(weights.read_bytes()).hexdigest() == w_before
    assert hm.check(REPO, REV, [hub])["status"] == "VALID"
    rec = json.loads((tmp_path / "rt/cache_integrity/qwen3.5-4b-runpod.json")
                     .read_text())[-1]
    corrupt = [e for e in rec["events"] if e["event"] ==
               "CACHE_METADATA_CORRUPT"]
    assert {e["kind"] for e in corrupt} == {"regular"}
    assert all(e["resolved_content_size"] == 0 for e in corrupt)
    assert any(e["event"] == "CACHE_METADATA_REPAIRED" and
               e["revision_unchanged"] for e in rec["events"])


def test_a_verified_existing_blob_is_relinked_not_rewritten(tmp_path):
    hub = tmp_path / "hub"
    snap = _live_snapshot(hub, zero_files=("tokenizer_config.json",))
    data = LIVE_CONTENT["tokenizer_config.json"]
    blob = snap.parents[1] / "blobs" / hm.git_blob_sha1(data)
    blob.write_bytes(data)                    # the blob arrived; link did not
    mtime = blob.stat().st_mtime_ns
    res = hm.ensure("q", REPO, REV, [hub], downloader=StagingHub(),
                    staging=tmp_path / "stage")
    assert res["status"] == "CACHE_METADATA_REPAIRED"
    mat = [e for e in res["events"] if e["event"] == "REPAIR_MATERIALISED"]
    assert mat[0]["blob_written"] is False and mat[0]["linked"] == "symlink"
    assert blob.stat().st_mtime_ns == mtime
    assert (snap / "tokenizer_config.json").read_bytes() == data


def test_repair_never_guesses_identity_or_changes_revision(tmp_path):
    hub = tmp_path / "hub"
    _live_snapshot(hub, zero_files=("tokenizer_config.json",))
    # 1. a download that lands on another revision is refused
    r = hm.ensure("q", REPO, REV, [hub], downloader=StagingHub(
        wrong_rev="f" * 40), staging=tmp_path / "s1")
    assert r["status"] == "MODEL_METADATA_CORRUPT"
    assert any(e["event"] == "REPAIR_REFUSED" for e in r["events"])
    # 2. a blob whose name does not match its bytes is refused
    class Lying(StagingHub):
        def __call__(self, repo, revision, filename, cache):
            p = Path(super().__call__(repo, revision, filename, cache))
            p.resolve().write_bytes(b'{"tampered": true}')
            return str(p)
    r = hm.ensure("q", REPO, REV, [hub], downloader=Lying(),
                  staging=tmp_path / "s2")
    assert r["status"] == "MODEL_METADATA_CORRUPT"
    assert "identity not verified" in str(r["events"])
    # 3. the pinned listing's blob id is enforced when known
    r = hm.ensure("q", REPO, REV, [hub], downloader=StagingHub(),
                  staging=tmp_path / "s3",
                  expected={"tokenizer_config.json": "0" * 40})
    assert r["status"] == "MODEL_METADATA_CORRUPT"
    # 4. never from a branch
    calls = []
    r = hm.ensure("q", REPO, "main", [hub], downloader=lambda *a:
                  calls.append(a), staging=tmp_path / "s4")
    assert r["status"] == "MODEL_METADATA_CORRUPT" and calls == []


def test_listing_blob_ids_cover_metadata_only():
    info = {"siblings": [
        {"rfilename": "config.json", "blobId": "a" * 40},
        {"rfilename": "tokenizer.json", "blobId": "b" * 40,
         "lfs": {"sha256": "c" * 64}},
        {"rfilename": "model-00001.safetensors", "blobId": "d" * 40,
         "lfs": {"sha256": "e" * 64}},
        {"rfilename": "README.md", "blobId": "f" * 40}]}
    assert hm.expected_blob_ids(info) == {"config.json": "a" * 40,
                                          "tokenizer.json": "c" * 64}


# ---- targeted single-profile probe ---------------------------------------------------

def _pp():
    spec = importlib.util.spec_from_file_location(
        "pin_and_probe_geese", RUNPOD / "pin_and_probe_models.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_targeted_probe_touches_only_the_requested_profile(tmp_path,
                                                           monkeypatch,
                                                           capsys):
    import anthropic

    import backend.model_lab.adapters as adapters
    from backend.model_lab import probe

    def boom(*a, **k):
        raise AssertionError("a model / provider was called")
    monkeypatch.setattr(adapters, "build_provider", boom)
    monkeypatch.setattr(anthropic, "Anthropic", boom)
    pp = _pp()
    prof = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", prof)
    monkeypatch.setattr(pp, "PROFILES", prof)
    monkeypatch.setattr(pp, "SUITE", prof / "_runpod_suite.json")
    rt = tmp_path / "rt"
    hardware.save_current(rt, hardware.from_host({
        "gpu": "NVIDIA RTX PRO 6000 Blackwell Server Edition",
        "gpu_memory": "97887 MiB", "driver_version": "595.91.07",
        "host_cuda": "13.2", "compute_capability": "12.0", "gpu_count": 1}))
    # the live pin of Qwen3.5-4B, already on the volume
    q = json.loads((prof / "qwen3.5-4b-runpod.json").read_text())
    q["status"] = "NOT_INSTALLED"
    q["artifact"] |= {"repository": REPO, "revision": REV,
                      "pin_status": "PINNED", "license_status": "LICENSE_OK",
                      "fit_inputs": {"weights_bytes": 9_300_000_000,
                                     "native_context": 262144, "config": {
                                         "num_hidden_layers": 32,
                                         "num_attention_heads": 16,
                                         "num_key_value_heads": 4,
                                         "head_dim": 256}}}
    q["endpoint"]["model"] = REPO
    q["runpod"] |= {"suggested_tool_call_parser": "qwen3_coder",
                    "tool_call_parser": "qwen3_coder",
                    "chat_template_markers": ["<function=", "<parameter=",
                                              "<tool_call>"]}
    (prof / "qwen3.5-4b-runpod.json").write_text(json.dumps(q))
    # other models' evidence from earlier runs
    (rt / "pins").mkdir(parents=True)
    others = [{"profile_id": "gemma-4-12b-runpod",
               "probe_status": "LICENSE_REVIEW_REQUIRED"},
              {"profile_id": "qwen3.8-27b-runpod",
               "probe_status": "BLACKWELL_FLASHINFER_SAMPLER_INCOMPATIBLE"}]
    (rt / "pins" / "ROSTER.json").write_text(json.dumps({"roster": others}))
    probe.save(rt, {"profile_id": "qwen3.8-27b-runpod", "keep": "me"})
    before = {p.name: p.read_bytes() for p in prof.glob("*.json")
              if p.name != "qwen3.5-4b-runpod.json"}

    def fake_serve_and_probe(pid, runtime, keep=False):
        assert pid == "qwen3.5-4b-runpod"
        probe.save(runtime, {"profile_id": pid, "runtime_reachable": True,
                             "model_present": True, "resolved_model": REPO,
                             "controls": {"tools": True,
                                          "forced_tool_use": True,
                                          "tool_result_roundtrip": True,
                                          "stop_reason_mapping": True}})
        return {"probe_status": "READY_E2E", "repository": REPO,
                "revision": REV, "server_env": {
                    "VLLM_USE_FLASHINFER_SAMPLER": "0"},
                "metadata": {"status": "VALID"}}
    monkeypatch.setattr(pp, "serve_and_probe", fake_serve_and_probe)

    def no_network(url):
        raise AssertionError(f"re-resolved the pinned revision: {url}")
    (rec,) = pp.run(["qwen3.5-4b-runpod"], no_network, rt, do_probe=True,
                    overrides={})
    out = capsys.readouterr().out
    assert rec["revision"] == REV and rec["kept_existing_pin"] is True
    assert rec["probe_status"] == "READY_E2E"
    assert "FINAL READINESS qwen3.5-4b-runpod: READY_E2E" in out
    # nothing else changed
    assert {p.name: p.read_bytes() for p in prof.glob("*.json")
            if p.name != "qwen3.5-4b-runpod.json"} == before
    ros = json.loads((rt / "pins" / "ROSTER.json").read_text())
    by = {r["profile_id"]: r for r in ros["roster"]}
    assert by["gemma-4-12b-runpod"] == others[0]
    assert by["qwen3.8-27b-runpod"] == others[1]
    assert by["qwen3.5-4b-runpod"]["probe_status"] == "READY_E2E"
    assert ros["last_run_profiles"] == ["qwen3.5-4b-runpod"]
    assert json.loads((rt / "probes.json").read_text())[
        "qwen3.8-27b-runpod"] == {"profile_id": "qwen3.8-27b-runpod",
                                  "keep": "me"}
    # the one-profile summary
    assert pp.main(["--runtime-dir", str(rt), "--profile",
                    "qwen3.5-4b-runpod", "--summary"]) == 0
    out = capsys.readouterr().out
    assert f"{REPO}@{REV}" in out
    assert "FINAL READINESS qwen3.5-4b-runpod: READY_E2E" in out
    assert "gemma" not in out and "qwen3.8" not in out


def test_bootstrap_can_target_one_profile():
    boot = (RUNPOD / "RUNPOD_BOOTSTRAP.sh").read_text()
    assert "--probe-profile=*" in boot
    assert '"${PROBE_PROFILES[@]}"' in boot
    assert "--profile qwen3.5-4b-runpod --probe" in boot
