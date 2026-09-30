#!/usr/bin/env python3
"""
RunPod persistent storage for the CreditProbe Model Lab.

    python3 runpod_storage.py            # human report; exit 0 or 3
    python3 runpod_storage.py --shell    # `export ...` lines for eval

Detects the persistent root in this order and never falls back to the
container overlay / root disk:

  1. /workspace-global  - a RunPod Global Volume (e.g. creditprobe-model-lab)
  2. /workspace         - a RunPod Network Volume
  otherwise             - PERSISTENT_STORAGE_NOT_FOUND (exit 3)

A candidate counts only when ALL hold:
  - it is itself a mount point (/proc/self/mountinfo), not a directory on
    the container's root filesystem;
  - its filesystem is not ephemeral (overlay, tmpfs, ramfs, ...);
  - its device is not the root filesystem's device (a bind mount of the
    container disk is refused);
  - it is mounted read-write and a write + fsync + read-back probe works;
  - /workspace only: the filesystem is a network filesystem (a local block
    "pod volume disk" does not survive pod termination and is refused
    unless CREDITPROBE_ACCEPT_POD_VOLUME=1 is set by the operator).

Every piece of benchmark state then lives under
<persistent_root>/creditprobe-model-lab/ (see LAYOUT). Standard library
only: it runs before the bundle is unpacked. It reads no credential.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any

CANDIDATES = (("/workspace-global", "GLOBAL_VOLUME"),
              ("/workspace", "NETWORK_VOLUME"))
APP_DIR = "creditprobe-model-lab"
EPHEMERAL_FS = {"overlay", "overlayfs", "aufs", "tmpfs", "ramfs", "devtmpfs",
                "squashfs", "proc", "sysfs", "cgroup", "cgroup2", "devpts",
                "mqueue", "shm", "rootfs"}
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "ceph", "glusterfs",
              "lustre", "9p", "virtiofs", "fuse", "mfs", "gpfs", "beegfs",
              "weka", "wekafs", "juicefs", "s3fs"}
NOT_FOUND = "PERSISTENT_STORAGE_NOT_FOUND"
MIN_FREE_GB = 60

#: Everything the benchmark writes, relative to <root>/creditprobe-model-lab.
LAYOUT = {
    "CREDITPROBE_HOME": "",
    "CREDITPROBE_SOURCE_DIR": "source",
    "MODEL_LAB_RUNTIME_DIR": "runtime",            # store, traces, exports,
                                                   # oracles, checkpoints,
                                                   # reports, pins, run logs
    "MODEL_LAB_REFERENCE_SET_DIR": "reference_sets",
    "LAB_EVIDENCE_DIR": "results/screenshots",
    "CREDITPROBE_RESULTS_DIR": "results",
    "CREDITPROBE_LOG_DIR": "logs",
    "CREDITPROBE_VENV_DIR": "venvs",
    "MODEL_CACHE_DIR": "cache/models",             # vLLM --download-dir
    "HF_HOME": "cache/huggingface",
    "HF_HUB_CACHE": "cache/huggingface/hub",
    "HF_XET_CACHE": "cache/huggingface/xet",
    "TRANSFORMERS_CACHE": "cache/huggingface/hub",
    "VLLM_CACHE_ROOT": "cache/vllm",
    "VLLM_CONFIG_ROOT": "cache/vllm/config",
    "TORCH_HOME": "cache/torch",
    "TRITON_CACHE_DIR": "cache/triton",
    "XDG_CACHE_HOME": "cache/xdg",
    "PIP_CACHE_DIR": "cache/pip",
    "UV_CACHE_DIR": "cache/uv",
    "npm_config_cache": "cache/npm",
    "PLAYWRIGHT_BROWSERS_PATH": "cache/ms-playwright",
}


def _unescape(s: str) -> str:
    return (s.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def parse_mountinfo(text: str) -> list[dict[str, str]]:
    out = []
    for line in text.splitlines():
        parts = line.split()
        if "-" not in parts or len(parts) < 7:
            continue
        sep = parts.index("-")
        if len(parts) < sep + 3:
            continue
        out.append({"device": parts[2], "mount_point": _unescape(parts[4]),
                    "options": parts[5], "fstype": parts[sep + 1],
                    "source": _unescape(parts[sep + 2])})
    return out


def mount_at(mounts: list[dict], path: str) -> dict | None:
    """The mount whose mount point IS this path (the last one wins when
    something is mounted over it)."""
    hits = [m for m in mounts if m["mount_point"] == path]
    return hits[-1] if hits else None


def _base_fs(fstype: str) -> str:
    return fstype.split(".")[0]


def classify(path: str, kind: str, mounts: list[dict], *,
             accept_pod_volume: bool = False) -> dict[str, Any]:
    res: dict[str, Any] = {"path": path, "kind": kind, "ok": False}
    m = mount_at(mounts, path)
    root = mount_at(mounts, "/")
    if m is None:
        res["reason"] = (f"{path} is not a mount point: it would be the "
                         f"container overlay/root disk")
        return res
    res |= {"fstype": m["fstype"], "source": m["source"],
            "device": m["device"], "options": m["options"]}
    fs = _base_fs(m["fstype"])
    if fs in EPHEMERAL_FS or m["fstype"] in EPHEMERAL_FS:
        res["reason"] = f"{path} is {m['fstype']} (ephemeral, not persistent)"
        return res
    if root is not None and m["device"] == root["device"]:
        res["reason"] = (f"{path} is on the container root device "
                         f"{root['device']} (bind mount of the root disk)")
        return res
    if "rw" not in m["options"].split(","):
        res["reason"] = f"{path} is mounted read-only"
        return res
    network = fs in NETWORK_FS or m["fstype"] in NETWORK_FS
    res["network_filesystem"] = network
    if kind == "NETWORK_VOLUME" and not network and not accept_pod_volume:
        res["reason"] = (f"{path} is a local {m['fstype']} volume disk, not "
                         f"a Network Volume (it does not survive pod "
                         f"termination); set CREDITPROBE_ACCEPT_POD_VOLUME=1 "
                         f"only if that is intended")
        return res
    res["ok"] = True
    return res


def probe_write(path: Path) -> tuple[bool, str]:
    """Write, fsync, read back and remove a probe file."""
    token = uuid.uuid4().hex
    p = path / f".creditprobe-write-probe-{token}"
    try:
        with open(p, "w") as f:
            f.write(token)
            f.flush()
            os.fsync(f.fileno())
        ok = p.read_text() == token
        p.unlink()
        return ok, "" if ok else "read-back mismatch"
    except OSError as exc:
        try:
            p.unlink()
        except OSError:
            pass
        return False, f"{type(exc).__name__}: {exc}"


def detect(*, mountinfo_text: str | None = None,
           candidates: tuple[tuple[str, str], ...] = CANDIDATES,
           accept_pod_volume: bool | None = None) -> dict[str, Any]:
    if mountinfo_text is None:
        try:
            mountinfo_text = Path("/proc/self/mountinfo").read_text()
        except OSError:
            mountinfo_text = ""
    if accept_pod_volume is None:
        accept_pod_volume = os.environ.get(
            "CREDITPROBE_ACCEPT_POD_VOLUME") == "1"
    mounts = parse_mountinfo(mountinfo_text)
    tried = []
    for path, kind in candidates:
        c = classify(path, kind, mounts, accept_pod_volume=accept_pod_volume)
        if c["ok"]:
            ok, why = probe_write(Path(path))
            if not ok:
                c |= {"ok": False, "reason": f"write probe failed: {why}"}
        tried.append(c)
        if c["ok"]:
            return {"status": "OK", "persist_root": path, "kind": kind,
                    "mount": c, "rejected": tried[:-1]}
    return {"status": NOT_FOUND, "persist_root": None, "rejected": tried}


def paths_for(persist_root: str) -> dict[str, str]:
    home = Path(persist_root) / APP_DIR
    return {k: str(home / v) if v else str(home) for k, v in LAYOUT.items()}


def prepare(res: dict[str, Any]) -> dict[str, Any]:
    """Create the layout and the persistence marker on the chosen root."""
    paths = paths_for(res["persist_root"])
    for p in paths.values():                 # every LAYOUT entry is a dir
        Path(p).mkdir(parents=True, exist_ok=True)
    home = Path(paths["CREDITPROBE_HOME"])
    marker = home / ".persist-marker.json"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if marker.exists():
        m = json.loads(marker.read_text())
        m["seen"] = (m.get("seen") or [])[-19:] + [
            {"at": now, "host": socket.gethostname()}]
        res["marker"] = {"new": False, "volume_id": m["volume_id"],
                         "created_at": m["created_at"],
                         "created_by_host": m["created_by_host"]}
    else:
        m = {"volume_id": uuid.uuid4().hex, "created_at": now,
             "created_by_host": socket.gethostname(),
             "persist_root": res["persist_root"], "kind": res["kind"],
             "seen": [{"at": now, "host": socket.gethostname()}]}
        res["marker"] = {"new": True, "volume_id": m["volume_id"],
                         "created_at": now,
                         "created_by_host": m["created_by_host"]}
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1))
    tmp.replace(marker)
    du = shutil.disk_usage(res["persist_root"])
    res |= {"paths": paths, "free_bytes": du.free, "total_bytes": du.total}
    return res


def report(res: dict[str, Any]) -> str:
    if res["status"] != "OK":
        lines = [NOT_FOUND]
        for c in res["rejected"]:
            lines.append(f"  {c['path']}: {c['reason']}")
        lines.append("  Attach the RunPod Global Volume (mounted at "
                     "/workspace-global) or a Network Volume (/workspace). "
                     "Nothing is written to the container disk.")
        return "\n".join(lines)
    m = res["mount"]
    gb = res["free_bytes"] / 1e9
    lines = [
        f"PERSIST_ROOT: {res['persist_root']} ({res['kind']})",
        f"filesystem: {m['fstype']} source={m['source']} "
        f"device={m['device']}",
        f"free_space: {gb:.1f} GB of {res['total_bytes'] / 1e9:.1f} GB"
        + ("" if gb >= MIN_FREE_GB else
           f"  WARN below {MIN_FREE_GB} GB needed for the model weights"),
        "persistence_verified: YES (own mount point; not overlay/tmpfs; "
        "not the container root device; read-write; write+fsync+read-back "
        "probe ok)",
        f"volume_marker: {res['marker']['volume_id']} "
        + ("created now" if res["marker"]["new"] else
           f"first written {res['marker']['created_at']} by "
           f"{res['marker']['created_by_host']} (state survived)"),
        f"CREDITPROBE_HOME: {res['paths']['CREDITPROBE_HOME']}",
    ]
    for c in res["rejected"]:
        lines.append(f"  (skipped {c['path']}: {c['reason']})")
    return "\n".join(lines)


def shell_exports(res: dict[str, Any]) -> str:
    env = {"PERSIST_ROOT": res["persist_root"],
           "PERSIST_KIND": res["kind"]} | res["paths"]
    return "".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--shell", action="store_true",
                    help="print export lines (report goes to stderr)")
    ap.add_argument("--no-prepare", action="store_true",
                    help="detect only; create nothing")
    ap.add_argument("--mountinfo", help=argparse.SUPPRESS)      # tests
    ap.add_argument("--candidate", action="append", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    text = Path(args.mountinfo).read_text() if args.mountinfo else None
    cands = CANDIDATES
    if args.candidate:
        cands = tuple(tuple(c.split("=", 1)) for c in args.candidate)
    res = detect(mountinfo_text=text, candidates=cands)
    if res["status"] == "OK" and not args.no_prepare:
        prepare(res)
    elif res["status"] == "OK":
        du = shutil.disk_usage(res["persist_root"])
        res |= {"paths": paths_for(res["persist_root"]),
                "free_bytes": du.free, "total_bytes": du.total,
                "marker": {"new": True, "volume_id": "(not written)",
                           "created_at": "", "created_by_host": ""}}
    out = sys.stderr if args.shell else sys.stdout
    print(report(res), file=out)
    if res["status"] != "OK":
        return 3
    if args.shell:
        print(shell_exports(res), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
