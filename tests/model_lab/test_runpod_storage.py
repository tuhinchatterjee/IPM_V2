"""RunPod persistent storage: /workspace-global (Global Volume) first, then
/workspace (Network Volume), otherwise PERSISTENT_STORAGE_NOT_FOUND. The
container overlay / root disk is never used.

Offline: the mount table is a synthetic /proc/self/mountinfo and the
"volumes" are temporary directories; the bootstrap is exercised end to end
up to its storage verdict (--storage-check), before any GPU, install or
model step.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

RUNPOD = ROOT / "scripts" / "model_lab" / "runpod"
spec = importlib.util.spec_from_file_location(
    "runpod_storage", RUNPOD / "runpod_storage.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

ROOT_OVERLAY = ("28 1 0:31 / / rw,relatime - overlay overlay "
                "rw,lowerdir=/l,upperdir=/u,workdir=/w")
CANARY = "sk-" + "ant-api03-STORAGE-CANARY-" + "Q" * 30


def _mi(*extra: str, root: str = ROOT_OVERLAY) -> str:
    return "\n".join([root, "30 28 0:40 / /proc rw - proc proc rw", *extra]
                     ) + "\n"


def _mount(n: int, path: Path, fstype: str, dev: str = "0:77",
           source: str = "vol", opts: str = "rw,relatime") -> str:
    return f"{n} 28 {dev} / {path} {opts} - {fstype} {source} rw"


@pytest.fixture()
def vols(tmp_path):
    g, w = tmp_path / "workspace-global", tmp_path / "workspace"
    g.mkdir()
    w.mkdir()
    cands = ((str(g), "GLOBAL_VOLUME"), (str(w), "NETWORK_VOLUME"))
    return g, w, cands


# ---- detection -------------------------------------------------------------------

def test_global_volume_at_workspace_global_is_chosen_first(vols):
    g, w, cands = vols
    mi = _mi(_mount(40, g, "fuse", "0:50", "creditprobe-model-lab"),
             _mount(41, w, "nfs4", "0:51"))
    r = rs.detect(mountinfo_text=mi, candidates=cands)
    assert r["status"] == "OK"
    assert r["persist_root"] == str(g) and r["kind"] == "GLOBAL_VOLUME"
    assert r["mount"]["fstype"] == "fuse"


def test_network_volume_at_workspace(vols):
    g, w, cands = vols
    mi = _mi(_mount(41, w, "fuse.mfs", "0:51", "mfs#runpod"))
    r = rs.detect(mountinfo_text=mi, candidates=cands)
    assert r["status"] == "OK"
    assert r["persist_root"] == str(w) and r["kind"] == "NETWORK_VOLUME"
    assert "not a mount point" in r["rejected"][0]["reason"]   # global absent


@pytest.mark.parametrize("case", ["overlay", "not_mounted", "tmpfs",
                                  "root_bind", "local_disk"])
def test_overlay_only_workspace_is_refused(vols, case):
    g, w, cands = vols
    mounts = {
        "overlay": [_mount(41, w, "overlay", "0:31", "overlay")],
        "not_mounted": [],
        "tmpfs": [_mount(41, w, "tmpfs", "0:60", "tmpfs")],
        "root_bind": [],
        "local_disk": [_mount(41, w, "ext4", "259:1", "/dev/nvme0n1")],
    }[case]
    root = ROOT_OVERLAY
    if case == "root_bind":                   # /workspace on the root disk
        root = "28 1 259:0 / / rw,relatime - ext4 /dev/vda rw"
        mounts = [_mount(41, w, "ext4", "259:0", "/dev/vda")]
    r = rs.detect(mountinfo_text=_mi(*mounts, root=root), candidates=cands,
                  accept_pod_volume=False)
    assert r["status"] == rs.NOT_FOUND and r["persist_root"] is None
    why = r["rejected"][1]["reason"]
    assert {"overlay": "ephemeral", "not_mounted": "not a mount point",
            "tmpfs": "ephemeral", "root_bind": "root device",
            "local_disk": "not a Network Volume"}[case] in why


def test_local_volume_disk_only_with_explicit_operator_opt_in(vols):
    g, w, cands = vols
    mi = _mi(_mount(41, w, "ext4", "259:1", "/dev/nvme0n1"))
    r = rs.detect(mountinfo_text=mi, candidates=cands, accept_pod_volume=True)
    assert r["status"] == "OK" and r["persist_root"] == str(w)


def test_no_persistent_volume_is_refused(vols, capsys):
    g, w, cands = vols
    mi_file = g.parent / "mountinfo"
    mi_file.write_text(_mi())
    rc = rs.main(["--mountinfo", str(mi_file), "--candidate",
                  f"{g}=GLOBAL_VOLUME", "--candidate", f"{w}=NETWORK_VOLUME"])
    out = capsys.readouterr().out
    assert rc == 3 and out.startswith("PERSISTENT_STORAGE_NOT_FOUND")
    assert list(g.iterdir()) == [] and list(w.iterdir()) == []


def test_read_only_or_unwritable_volume_is_refused(vols):
    g, w, cands = vols
    ro = _mi(_mount(40, g, "fuse", "0:50", opts="ro,relatime"))
    assert rs.detect(mountinfo_text=ro, candidates=cands)["status"] == \
        rs.NOT_FOUND
    gone = g.parent / "missing-mount"
    mi = _mi(_mount(40, gone, "fuse", "0:50"))
    r = rs.detect(mountinfo_text=mi, candidates=((str(gone),
                                                  "GLOBAL_VOLUME"),))
    assert r["status"] == rs.NOT_FOUND
    assert "write probe failed" in r["rejected"][0]["reason"]


def test_every_state_path_lives_under_the_persistent_app_dir(vols):
    g, w, cands = vols
    r = rs.prepare(rs.detect(mountinfo_text=_mi(_mount(40, g, "fuse")),
                             candidates=cands))
    home = g / "creditprobe-model-lab"
    assert r["paths"]["CREDITPROBE_HOME"] == str(home)
    for k in ("CREDITPROBE_SOURCE_DIR", "MODEL_LAB_RUNTIME_DIR",
              "MODEL_LAB_REFERENCE_SET_DIR", "LAB_EVIDENCE_DIR",
              "CREDITPROBE_RESULTS_DIR", "CREDITPROBE_LOG_DIR",
              "MODEL_CACHE_DIR", "HF_HOME", "HF_HUB_CACHE",
              "VLLM_CACHE_ROOT", "TORCH_HOME", "PIP_CACHE_DIR",
              "UV_CACHE_DIR", "npm_config_cache", "PLAYWRIGHT_BROWSERS_PATH",
              "CREDITPROBE_VENV_DIR"):
        p = Path(r["paths"][k])
        assert p.is_dir() and home in (p, *p.parents), k
    assert r["marker"]["new"] is True
    again = rs.prepare(rs.detect(mountinfo_text=_mi(_mount(40, g, "fuse")),
                                 candidates=cands))
    assert again["marker"]["new"] is False            # state survived
    assert again["marker"]["volume_id"] == r["marker"]["volume_id"]
    ex = rs.shell_exports(again)
    assert f"export HF_HOME={home}/cache/huggingface" in ex
    assert f"export MODEL_LAB_RUNTIME_DIR={home}/runtime" in ex


# ---- the bootstrap, end to end up to its storage verdict ---------------------------

def _boot(tmp: Path, mountinfo: str, cands) -> subprocess.CompletedProcess:
    d = tmp / "deploy"
    d.mkdir(exist_ok=True)
    shutil.copy(RUNPOD / "RUNPOD_BOOTSTRAP.sh", d)
    shutil.copy(RUNPOD / "runpod_storage.py", d)
    mi = tmp / "mountinfo"
    mi.write_text(mountinfo)
    args = f"--mountinfo {mi} " + " ".join(f"--candidate {p}={k}"
                                           for p, k in cands)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MODEL_LAB_", "CREDITPROBE_", "HF_"))}
    env |= {"CREDITPROBE_STORAGE_TEST_ARGS": args,
            "COCKPIT_ANTHROPIC_API_KEY": CANARY}
    return subprocess.run(["bash", str(d / "RUNPOD_BOOTSTRAP.sh"),
                           "--storage-check"], capture_output=True,
                          text=True, env=env, timeout=60)


@pytest.mark.parametrize("scenario", ["global", "network"])
def test_bootstrap_prints_the_verified_persistent_root(vols, scenario):
    g, w, cands = vols
    mi = (_mi(_mount(40, g, "fuse", "0:50", "creditprobe-model-lab"))
          if scenario == "global" else _mi(_mount(41, w, "nfs4", "0:51")))
    p = _boot(g.parent, mi, cands)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    root = g if scenario == "global" else w
    assert f"PERSIST_ROOT: {root}" in out
    assert "filesystem: " in out and "free_space: " in out
    assert "persistence_verified: YES" in out
    env_sh = (root / "creditprobe-model-lab" / "env.sh").read_text()
    for k in ("HF_HOME", "MODEL_CACHE_DIR", "VLLM_CACHE_ROOT",
              "MODEL_LAB_RUNTIME_DIR", "MODEL_LAB_REFERENCE_SET_DIR",
              "LAB_EVIDENCE_DIR", "CREDITPROBE_LOG_DIR"):
        assert f"export {k}={root}/creditprobe-model-lab" in env_sh, k
    assert CANARY not in env_sh and CANARY not in out   # key never persisted
    other = w if scenario == "global" else g
    assert list(other.iterdir()) == []


@pytest.mark.parametrize("scenario", ["overlay_workspace", "none"])
def test_bootstrap_refuses_without_a_persistent_volume(vols, scenario):
    g, w, cands = vols
    mi = (_mi(_mount(41, w, "overlay", "0:31", "overlay"))
          if scenario == "overlay_workspace" else _mi())
    p = _boot(g.parent, mi, cands)
    out = p.stdout + p.stderr
    assert p.returncode == 3, out
    assert "PERSISTENT_STORAGE_NOT_FOUND" in out
    assert "persistence_verified" not in out
    assert list(g.iterdir()) == [] and list(w.iterdir()) == []


def test_no_hard_coded_workspace_paths_remain():
    boot = (RUNPOD / "RUNPOD_BOOTSTRAP.sh").read_text()
    code = [ln for ln in boot.splitlines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code if "/workspace" in ln]
    assert "WORKSPACE" not in boot
    serve = (RUNPOD / "serve.sh").read_text()
    assert "/workspace" not in serve


def test_serve_refuses_without_the_persistent_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MODEL_LAB_", "CREDITPROBE_", "HF_",
                                "MODEL_CACHE"))}
    p = subprocess.run(["bash", str(RUNPOD / "serve.sh"), "qwen3.5-4b-runpod"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert p.returncode != 0 and "env.sh" in p.stderr


def test_reference_set_follows_the_persistent_volume(tmp_path, monkeypatch):
    import sys

    from backend.model_lab import opus_references as orf
    sys.path.insert(0, str(ROOT / "scripts" / "model_lab"))
    import benchmark_suite

    monkeypatch.setenv("MODEL_LAB_REFERENCE_SET_DIR", str(tmp_path))
    assert orf.set_path() == tmp_path / "OPUS_REFERENCE_SET_V1.json"
    assert benchmark_suite.reference_set_path({}) == \
        tmp_path / "OPUS_REFERENCE_SET_V1.json"
    monkeypatch.delenv("MODEL_LAB_REFERENCE_SET_DIR")
    assert orf.set_path() == orf.DEFAULT_DIR / "OPUS_REFERENCE_SET_V1.json"
