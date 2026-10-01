"""RunPod: persistent DATA on the Global Volume, Pod-local EXECUTABLES.

The live Global Volume is fuse.geesefs and refuses chmod ("Operation not
permitted"). Here that is simulated faithfully: a sitecustomize makes every
Python chmod/copystat on the volume fail with EPERM, and a `chmod` shim on
PATH does the same for the shell, logging every call. The real
RUNPOD_BOOTSTRAP.sh then runs (--prepare-only: storage, deployment copy, app
rebuild, executable bits; no installs, no GPU, no model) against a small
bundle with launchers, a profile and a manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import ROOT

RUNPOD = ROOT / "scripts" / "model_lab" / "runpod"
sys.path.insert(0, str(RUNPOD))
import runpod_storage as rs  # noqa: E402

CANARY = "sk-" + "ant-api03-EXEC-STORAGE-CANARY-" + "R" * 30

SITECUSTOMIZE = r'''
import os
_DENY = [os.path.realpath(r) for r in
         os.environ.get("SIM_NOCHMOD_ROOTS", "").split(":") if r]
_LOG = os.environ.get("SIM_CHMOD_LOG")
_real = os.chmod


def _path(p):
    return "" if isinstance(p, int) else os.path.realpath(os.fspath(p))


def chmod(path, mode, *a, **k):
    p = _path(path)
    if _LOG:
        with open(_LOG, "a") as f:
            f.write(p + "\n")
    if any(p == r or p.startswith(r + "/") for r in _DENY):
        raise PermissionError(1, "Operation not permitted "
                                 "(simulated fuse.geesefs)", p)
    return _real(path, mode, *a, **k)


os.chmod = chmod
'''

CHMOD_SHIM = r'''#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in -*|[0-7]*|+*|u*|g*|o*|a*) continue ;; esac
  p="$(realpath -m "$a")"
  [ -n "${SIM_CHMOD_LOG:-}" ] && echo "$p" >> "$SIM_CHMOD_LOG"
  IFS=: read -ra roots <<< "${SIM_NOCHMOD_ROOTS:-}"
  for r in "${roots[@]}"; do
    r="$(realpath -m "$r")"
    case "$p" in "$r"|"$r"/*) echo "chmod: $a: Operation not permitted" >&2; exit 1 ;; esac
  done
done
exec /bin/chmod "$@"
'''


def _bundle(d: Path, *, flavour: str = "v1") -> Path:
    """A small but real-shaped deployment: zip + bootstrap + storage
    script + manifest + checksums."""
    d.mkdir(parents=True, exist_ok=True)
    files = {
        "launchers/START_MODEL_LAB.command": (b"#!/bin/sh\necho start\n",
                                              0o755),
        "scripts/model_lab/runpod/serve.sh": (b"#!/bin/sh\necho serve\n",
                                              0o755),
        "profiles/m-runpod.json": (json.dumps({
            "profile_id": "m-runpod", "status": "NOT_INSTALLED",
            "artifact": {"repository": None, "revision": None},
            "runpod": {}}).encode(), 0o644),
        "README.txt": (f"bundle {flavour}\n".encode(), 0o644),
    }
    manifest = {"source_commit": hashlib.sha1(flavour.encode()).hexdigest(),
                "files": {p: {"sha256": hashlib.sha256(b).hexdigest()}
                          for p, (b, _) in files.items()}}
    mbytes = json.dumps(manifest).encode()
    with zipfile.ZipFile(d / rs.ZIP_NAME, "w") as z:
        for p, (b, mode) in list(files.items()) + [
                ("DEPLOYMENT_MANIFEST.json", (mbytes, 0o644))]:
            info = zipfile.ZipInfo("creditprobe-model-lab/" + p)
            info.external_attr = (0o100000 | mode) << 16
            z.writestr(info, b)
    (d / "DEPLOYMENT_MANIFEST.json").write_bytes(mbytes)
    shutil.copyfile(RUNPOD / "RUNPOD_BOOTSTRAP.sh", d / "RUNPOD_BOOTSTRAP.sh")
    shutil.copyfile(RUNPOD / "runpod_storage.py", d / "runpod_storage.py")
    (d / "checksums.sha256").write_text("".join(
        f"{hashlib.sha256((d / n).read_bytes()).hexdigest()}  {n}\n"
        for n in rs.DEPLOY_FILES if n != "checksums.sha256"))
    return d


class Pod:
    """One simulated RunPod: a geesefs-like Global Volume (chmod refused)
    and a Pod-local /workspace for executables."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.g = tmp / "workspace-global"          # the Global Volume mount
        self.w = tmp / "workspace"                 # Pod-local disk
        self.g.mkdir(exist_ok=True)
        self.w.mkdir(exist_ok=True)
        self.app = self.w / "creditprobe-model-lab"
        self.home = self.g / "creditprobe-model-lab"
        self.sim = tmp / "sim"
        (self.sim / "bin").mkdir(parents=True, exist_ok=True)
        (self.sim / "sitecustomize.py").write_text(SITECUSTOMIZE)
        shim = self.sim / "bin" / "chmod"
        shim.write_text(CHMOD_SHIM)
        shim.chmod(0o755)
        self.log = tmp / "chmod.log"
        self.mountinfo = tmp / "mountinfo"
        self.mountinfo.write_text(
            "28 1 0:31 / / rw,relatime - overlay overlay rw\n"
            f"40 28 0:50 / {self.g} rw,relatime - fuse.geesefs "
            f"creditprobe-model-lab rw\n")

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("MODEL_LAB_", "CREDITPROBE_", "HF_",
                                    "MODEL_CACHE", "VLLM_", "LAB_EVIDENCE"))}
        env |= {
            "CREDITPROBE_STORAGE_TEST_ARGS":
                f"--mountinfo {self.mountinfo} --candidate "
                f"{self.g}=GLOBAL_VOLUME --candidate {self.w}=NETWORK_VOLUME",
            "CREDITPROBE_APP_ROOT": str(self.app),
            "PYTHONPATH": str(self.sim),
            "PATH": f"{self.sim / 'bin'}:{os.environ['PATH']}",
            "SIM_NOCHMOD_ROOTS": str(self.g),
            "SIM_CHMOD_LOG": str(self.log),
            "COCKPIT_ANTHROPIC_API_KEY": CANARY,
        }
        return env | extra

    def boot(self, script: Path, *flags: str, **extra: str
             ) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(script), *flags],
                              capture_output=True, text=True,
                              env=self.env(**extra), timeout=180)

    def chmodded(self) -> list[str]:
        return self.log.read_text().split() if self.log.exists() else []


def _state_hashes(home: Path) -> dict[str, str]:
    """Every durable file except the bundle copy, logs, env.sh and marker
    (which a rerun legitimately refreshes)."""
    skip = ("deployment/", "logs/", "env.sh", ".persist-marker.json")
    return {str(f.relative_to(home)): hashlib.sha256(f.read_bytes())
            .hexdigest() for f in sorted(home.rglob("*"))
            if f.is_file() and not str(f.relative_to(home)).startswith(skip)}


@pytest.fixture()
def pod(tmp_path):
    return Pod(tmp_path)


# ---- the simulation itself is faithful ---------------------------------------------

def test_simulated_geesefs_refuses_chmod(pod):
    f = pod.g / "x"
    f.write_text("x")
    py = subprocess.run([sys.executable, "-c",
                         f"import os; os.chmod({str(f)!r}, 0o755)"],
                        env=pod.env(), capture_output=True, text=True)
    assert py.returncode != 0 and "Operation not permitted" in py.stderr
    sh = subprocess.run(["chmod", "+x", str(f)], env=pod.env(),
                        capture_output=True, text=True)
    assert sh.returncode != 0 and "Operation not permitted" in sh.stderr
    ok = pod.w / "y"
    ok.write_text("y")
    assert subprocess.run(["chmod", "+x", str(ok)], env=pod.env()
                          ).returncode == 0


# ---- first run on a fresh Global Volume -----------------------------------------------

def test_first_run_needs_no_chmod_on_the_global_volume(pod):
    dep = _bundle(pod.tmp / "upload")
    p = pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only")
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    for line in (f"PERSIST_ROOT: {pod.g}", "filesystem: fuse.geesefs",
                 "free_space:", "persistence_verified: YES",
                 "sqlite_on_persistent: OK", "app_root_executable: YES",
                 f"CREDITPROBE_APP_ROOT: {pod.app}"):
        assert line in out, line
    # every chmod happened on the Pod-local app root, none on the volume
    calls = pod.chmodded()
    assert calls, "launchers must be made executable"
    assert all(c.startswith(str(pod.app) + "/") for c in calls), calls
    assert not [c for c in calls if c.startswith(str(pod.g))]
    src = pod.app / "source"
    for exe in ("launchers/START_MODEL_LAB.command",
                "scripts/model_lab/runpod/serve.sh"):
        assert os.access(src / exe, os.X_OK), exe
    assert not os.access(src / "README.txt", os.X_OK)
    # the bundle is on the volume, verified, byte-identical
    d = pod.home / "deployment"
    for n in rs.DEPLOY_FILES:
        assert (d / n).read_bytes() == (dep / n).read_bytes(), n
    assert rs.verify_dir(d) == []
    # no source, venv or executable on the persistent volume
    assert not (pod.home / "source").exists()
    assert not list(pod.home.rglob("*.command"))


def test_env_sh_exports_both_areas_and_never_a_secret(pod):
    dep = _bundle(pod.tmp / "upload")
    assert pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only"
                    ).returncode == 0
    env_sh = (pod.home / "env.sh").read_text()
    for k, root in (("CREDITPROBE_PERSIST_ROOT", pod.home),
                    ("MODEL_LAB_RUNTIME_DIR", pod.home),
                    ("MODEL_LAB_REFERENCE_SET_DIR", pod.home),
                    ("MODEL_CACHE_DIR", pod.home), ("HF_HOME", pod.home),
                    ("LAB_EVIDENCE_DIR", pod.home),
                    ("CREDITPROBE_APP_ROOT", pod.app),
                    ("CREDITPROBE_SOURCE_ROOT", pod.app),
                    ("CREDITPROBE_VENV_DIR", pod.app),
                    ("VLLM_CACHE_ROOT", pod.app),
                    ("PLAYWRIGHT_BROWSERS_PATH", pod.app)):
        assert f"export {k}={root}" in env_sh, k
    assert CANARY not in env_sh
    for f in pod.tmp.rglob("*"):
        if f.is_file() and f.suffix != ".py":
            assert CANARY.encode() not in f.read_bytes(), f


def test_state_is_persistent_and_executables_are_pod_local():
    p = rs.paths_for("/workspace-global")
    home, app = "/workspace-global/creditprobe-model-lab", \
        "/workspace/creditprobe-model-lab"
    for k in rs.PERSIST_LAYOUT:
        assert p[k].startswith(home), k
    for k in rs.APP_LAYOUT:
        assert p[k].startswith(app), k
    for k in ("MODEL_CACHE_DIR", "HF_HOME", "HF_HUB_CACHE",
              "MODEL_LAB_RUNTIME_DIR", "CREDITPROBE_RESULTS_DIR",
              "MODEL_LAB_REFERENCE_SET_DIR", "MODEL_LAB_PINNED_PROFILES_DIR"):
        assert k in rs.PERSIST_LAYOUT, k            # downloads + state
    for k in ("CREDITPROBE_SOURCE_ROOT", "CREDITPROBE_VENV_DIR",
              "PLAYWRIGHT_BROWSERS_PATH"):
        assert k in rs.APP_LAYOUT, k                # executables only
    assert rs.check_separation(p) is None
    # the /workspace Network Volume case keeps them apart too
    n = rs.paths_for("/workspace")
    assert n["CREDITPROBE_APP_ROOT"] == \
        "/workspace/creditprobe-model-lab/app"
    assert rs.check_separation(n) is None


# ---- a new Pod, same Global Volume ----------------------------------------------------

def test_new_pod_rebuilds_the_app_and_keeps_every_result(pod):
    dep = _bundle(pod.tmp / "upload")
    assert pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only"
                    ).returncode == 0
    # benchmark work done on the first Pod, all on the volume
    h = pod.home
    files = {
        "runtime/benchmark/suite-v2/checkpoint.json": '{"cells": {"a": 1}}',
        "runtime/lab_index.sqlite3": "db-bytes",
        "runtime/exports/cmp-1/pack.zip": "zip-bytes",
        "runtime/probes.json": '{"m-runpod": {"ok": true}}',
        "reference_sets/OPUS_REFERENCE_SET_V1.json": '{"questions": {}}',
        "results/screenshots/lab_desktop.png": "png",
        "cache/models/models--org--m/blobs/abc": "weights",
        "state/pinned_profiles/m-runpod.json": json.dumps({
            "profile_id": "m-runpod", "status": "NOT_INSTALLED",
            "artifact": {"repository": "org/m", "revision": "a" * 40,
                         "pin_status": "PINNED"}, "runpod": {"fit": 1}}),
    }
    for rel, body in files.items():
        (h / rel).parent.mkdir(parents=True, exist_ok=True)
        (h / rel).write_text(body)
    before = _state_hashes(h)
    # the Pod is replaced: /workspace is empty again, upload dir is gone
    shutil.rmtree(pod.app)
    shutil.rmtree(dep)
    pod.log.unlink()
    p = pod.boot(h / "deployment" / "RUNPOD_BOOTSTRAP.sh", "--prepare-only")
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "already the persistent deployment" in out
    assert "state survived" in out
    assert _state_hashes(h) == before                 # nothing overwritten
    src = pod.app / "source"
    assert os.access(src / "launchers/START_MODEL_LAB.command", os.X_OK)
    prof = json.loads((src / "profiles/m-runpod.json").read_text())
    assert prof["artifact"]["revision"] == "a" * 40   # same exact pin
    assert all(c.startswith(str(pod.app) + "/") for c in pod.chmodded())


def test_same_pod_rerun_keeps_venv_and_node_modules(pod):
    dep = _bundle(pod.tmp / "upload")
    assert pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only"
                    ).returncode == 0
    venv = pod.app / "source" / ".venv" / "bin" / "python"
    nm = pod.app / "source" / "frontend" / "node_modules" / "x.js"
    for f in (venv, nm):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("kept")
    assert pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only"
                    ).returncode == 0
    assert venv.read_text() == "kept" and nm.read_text() == "kept"
    assert not (pod.app / "source.new").exists()
    assert not (pod.app / "source.old").exists()


def test_new_bundle_archives_the_previous_one_and_keeps_results(pod):
    assert pod.boot(_bundle(pod.tmp / "v1") / "RUNPOD_BOOTSTRAP.sh",
                    "--prepare-only").returncode == 0
    ck = pod.home / "runtime" / "benchmark" / "s" / "checkpoint.json"
    ck.parent.mkdir(parents=True)
    ck.write_text('{"done": 7}')
    v2 = _bundle(pod.tmp / "v2", flavour="v2")
    p = pod.boot(v2 / "RUNPOD_BOOTSTRAP.sh", "--prepare-only")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "previous bundle archived" in p.stdout + p.stderr
    archived = list((pod.home / "deployment" / "archive").glob("*/"
                                                              + rs.ZIP_NAME))
    assert len(archived) == 1
    assert (pod.home / "deployment" / rs.ZIP_NAME).read_bytes() == \
        (v2 / rs.ZIP_NAME).read_bytes()
    assert (pod.app / "source" / "README.txt").read_text() == "bundle v2\n"
    assert ck.read_text() == '{"done": 7}'


# ---- refusals ---------------------------------------------------------------------------

def test_container_root_is_never_mistaken_for_persistent_state(pod):
    pod.mountinfo.write_text(
        "28 1 0:31 / / rw,relatime - overlay overlay rw\n"
        f"41 28 0:31 / {pod.w} rw,relatime - overlay overlay rw\n")
    dep = _bundle(pod.tmp / "upload")
    p = pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only")
    assert p.returncode == 3, p.stdout + p.stderr
    assert "PERSISTENT_STORAGE_NOT_FOUND" in p.stdout + p.stderr
    assert list(pod.g.iterdir()) == [] and not pod.app.exists()


def test_app_root_on_the_global_volume_is_refused(pod):
    dep = _bundle(pod.tmp / "upload")
    p = pod.boot(dep / "RUNPOD_BOOTSTRAP.sh", "--prepare-only",
                 CREDITPROBE_APP_ROOT=str(pod.home / "app"))
    out = p.stdout + p.stderr
    assert p.returncode == 4, out
    assert "APP_ROOT_NOT_EXECUTABLE" in out and "Operation not permitted" \
        in out
    assert not (pod.home / "deployment" / rs.ZIP_NAME).exists()


def test_app_root_containing_the_volume_is_refused(pod):
    p = pod.boot(_bundle(pod.tmp / "upload") / "RUNPOD_BOOTSTRAP.sh",
                 "--prepare-only", CREDITPROBE_APP_ROOT=str(pod.tmp))
    assert p.returncode == 4
    assert "contains the persistent root" in p.stdout + p.stderr


def test_unpack_refuses_paths_outside_the_app_root(tmp_path):
    z = tmp_path / rs.ZIP_NAME
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("creditprobe-model-lab/../../escape.txt", "x")
    paths = rs.paths_for(str(tmp_path / "g"), str(tmp_path / "app"))
    r = rs.unpack(z, paths)
    assert r["ok"] is False and "unsafe path" in r["reason"]
    assert not (tmp_path / "escape.txt").exists()


# ---- lab tools that used to chmod on the runtime --------------------------------------

def test_approvals_and_runtime_import_need_no_chmod(tmp_path, monkeypatch,
                                                    capsys):
    sys.path.insert(0, str(ROOT / "scripts" / "model_lab"))
    import approve
    import opus_reference_set

    def eperm(*a, **k):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "chmod", eperm)
    monkeypatch.setattr(shutil, "copystat", eperm)
    rt = tmp_path / "rt"
    assert approve.main(["grant", "opus_spend", "--cap-usd", "3",
                         "--runtime-dir", str(rt)]) == 0
    assert json.loads((rt / "approvals.json").read_text())["opus_spend"][
        "cap_usd"] == 3
    from backend.model_lab.store import LabStore
    src = tmp_path / "mac"
    LabStore(src)
    (src / "blobs" / "ab").mkdir(parents=True)
    (src / "blobs" / "ab" / "abcd").write_text("blob")
    dst = tmp_path / "pod-rt"
    assert opus_reference_set.main(["import-runtime", "--runtime-dir",
                                    str(dst), "--from", str(src)]) == 0
    assert (dst / "blobs" / "ab" / "abcd").read_text() == "blob"


def test_existing_pins_are_kept_and_mirrored_to_the_volume(tmp_path,
                                                           monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pin_and_probe", RUNPOD / "pin_and_probe_models.py")
    pp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pp)
    prof = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", prof)
    monkeypatch.setattr(pp, "PROFILES", prof)
    keep = tmp_path / "volume" / "state" / "pinned_profiles"
    monkeypatch.setenv("MODEL_LAB_PINNED_PROFILES_DIR", str(keep))
    raw = json.loads((prof / "qwen3.5-4b-runpod.json").read_text())
    raw["artifact"] |= {"repository": "Qwen/Qwen3.5-4B",
                        "revision": "b" * 40, "pin_status": "PINNED"}
    (prof / "qwen3.5-4b-runpod.json").write_text(json.dumps(raw))

    def no_network(url):
        raise AssertionError(f"re-resolved an existing pin: {url}")
    rec = pp.qualify("qwen3.5-4b-runpod", no_network)
    assert rec["kept_existing_pin"] is True and rec["revision"] == "b" * 40
    mirrored = json.loads((keep / "qwen3.5-4b-runpod.json").read_text())
    assert mirrored["artifact"]["revision"] == "b" * 40
