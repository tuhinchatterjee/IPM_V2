#!/usr/bin/env python3
"""
RunPod storage for the CreditProbe Model Lab: a PERSISTENT state root and a
Pod-local EXECUTABLE app root, never mixed.

    python3 runpod_storage.py [detect] [--shell]      # exit 0 / 3 / 4 / 5
    python3 runpod_storage.py deploy --from DIR       # bundle -> persistent
    python3 runpod_storage.py unpack                  # zip -> Pod-local app
    python3 runpod_storage.py restore-pins            # volume pins -> profiles

PERSISTENT ROOT (durable data only), detected in this order and never the
container overlay / root disk:

  1. /workspace-global  - a RunPod Global Volume (live: fuse.geesefs)
  2. /workspace         - a RunPod Network Volume
  otherwise             - PERSISTENT_STORAGE_NOT_FOUND (exit 3)

A candidate counts only when ALL hold: it is itself a mount point
(/proc/self/mountinfo); not an ephemeral filesystem (overlay, tmpfs, ...);
not on the container root device; mounted read-write; a write + fsync +
read-back probe works; and for /workspace only, a network filesystem (a
local pod volume disk needs CREDITPROBE_ACCEPT_POD_VOLUME=1).

  <persist>/creditprobe-model-lab/   = CREDITPROBE_PERSIST_ROOT
    deployment/   the bundle, bootstrap, this script, manifest, checksums
    runtime/      lab store + frozen run DB, Model I/O traces, exports,
                  answers, SQL/Python, tables/charts, oracles, checkpoints,
                  reports, pins/probes, resource samples, run + vLLM logs
    reference_sets/ OPUS_REFERENCE_SET_V1 + answer snapshots
    results/      results and screenshots
    logs/         bootstrap logs
    state/pinned_profiles/  pinned model identities (survive Pod loss)
    cache/models, cache/huggingface   model weights / HF downloads

Nothing on the persistent root ever needs chmod: the Global Volume
(fuse.geesefs) refuses it, and every file there is data.

APP ROOT (executables; may vanish with the Pod; rebuilt from deployment/):

  /workspace/creditprobe-model-lab   = CREDITPROBE_APP_ROOT
    (or <persist>/creditprobe-model-lab/app when the persistent root is the
    /workspace Network Volume itself; CREDITPROBE_APP_ROOT overrides)
    source/   unpacked lab (+ .venv, frontend/node_modules), launchers
    venvs/vllm, cache/{pip,uv,npm,ms-playwright,vllm,torch,triton,xdg}, tmp/

The app root must pass an executable probe (write, chmod +x, run) or
APP_ROOT_NOT_EXECUTABLE (exit 4); it may never contain the persistent root.
SQLite (WAL) must work on the persistent runtime or
PERSISTENT_SQLITE_UNSUPPORTED (exit 5). Standard library only; reads no
credential and writes none.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
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

#: Durable state, relative to <persist>/creditprobe-model-lab.
PERSIST_LAYOUT = {
    "CREDITPROBE_PERSIST_ROOT": "",
    "CREDITPROBE_HOME": "",                        # alias
    "CREDITPROBE_DEPLOYMENT_DIR": "deployment",
    "MODEL_LAB_RUNTIME_DIR": "runtime",
    "MODEL_LAB_REFERENCE_SET_DIR": "reference_sets",
    "CREDITPROBE_RESULTS_DIR": "results",
    "LAB_EVIDENCE_DIR": "results/screenshots",
    "CREDITPROBE_LOG_DIR": "logs",
    "MODEL_LAB_PINNED_PROFILES_DIR": "state/pinned_profiles",
    "MODEL_CACHE_DIR": "cache/models",             # vLLM --download-dir
    "HF_HOME": "cache/huggingface",
    "HF_HUB_CACHE": "cache/huggingface/hub",
    "HF_XET_CACHE": "cache/huggingface/xet",
    "TRANSFORMERS_CACHE": "cache/huggingface/hub",
}
#: Executable software and build/compile caches, relative to the app root.
APP_LAYOUT = {
    "CREDITPROBE_APP_ROOT": "",
    "CREDITPROBE_SOURCE_ROOT": "source",
    "CREDITPROBE_SOURCE_DIR": "source",            # alias
    "CREDITPROBE_VENV_DIR": "venvs",
    "VLLM_CACHE_ROOT": "cache/vllm",               # compiled kernels (exec)
    "VLLM_CONFIG_ROOT": "cache/vllm/config",
    "TORCH_HOME": "cache/torch",
    "TRITON_CACHE_DIR": "cache/triton",
    "XDG_CACHE_HOME": "cache/xdg",
    "PIP_CACHE_DIR": "cache/pip",
    "UV_CACHE_DIR": "cache/uv",
    "npm_config_cache": "cache/npm",
    "PLAYWRIGHT_BROWSERS_PATH": "cache/ms-playwright",
    "TMPDIR": "tmp",
}
DEPLOY_FILES = ("CreditProbe_Model_Lab_RunPod_FullTrace.zip",
                "RUNPOD_BOOTSTRAP.sh", "runpod_storage.py",
                "DEPLOYMENT_MANIFEST.json", "checksums.sha256")
ZIP_NAME = DEPLOY_FILES[0]
#: Profile fields a pin owns (same set the suite generator keeps). Of
#: `runpod` and `endpoint` only the identity/fit parts are restored: parser
#: and serving settings always come from the current bundle.
PIN_KEYS = ("registry_id", "artifact", "status", "status_reason", "licence",
            "provenance_status", "identity_source", "context_tokens")
RUNPOD_PIN_KEYS = ("served_model_name", "fit", "resource_status", "runtime",
                   "chat_template_present", "chat_template_mentions_tools",
                   "chat_template_markers", "chat_template_sha256",
                   "chat_template_source")
#: Kept across an app rebuild on the same Pod (rebuilt if absent).
PRESERVE_IN_SOURCE = (".venv", "frontend/node_modules")
NOT_EXECUTABLE = "APP_ROOT_NOT_EXECUTABLE"
SQLITE_UNSUPPORTED = "PERSISTENT_SQLITE_UNSUPPORTED"
MIN_APP_FREE_GB = 30


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


def default_app_root(persist_root: str) -> str:
    env = os.environ.get("CREDITPROBE_APP_ROOT")
    if env:
        return env
    if persist_root == "/workspace":       # the Network Volume itself
        return str(Path(persist_root) / APP_DIR / "app")
    return f"/workspace/{APP_DIR}"


def paths_for(persist_root: str, app_root: str | None = None
              ) -> dict[str, str]:
    home = Path(persist_root) / APP_DIR
    app = Path(app_root or default_app_root(persist_root))
    out = {k: str(home / v) if v else str(home)
           for k, v in PERSIST_LAYOUT.items()}
    out |= {k: str(app / v) if v else str(app) for k, v in APP_LAYOUT.items()}
    return out


def _inside(child: Path, parent: Path) -> bool:
    c, p = child.resolve(), parent.resolve()
    return c == p or p in c.parents


def check_separation(paths: dict[str, str]) -> str | None:
    """The app root may be rebuilt (deleted) at any time, so no durable
    path may live inside it, and it may not contain the persistent root."""
    app = Path(paths["CREDITPROBE_APP_ROOT"])
    if str(app.resolve()) in ("/", "/workspace", "/workspace-global"):
        return f"app root {app} is a volume or system root"
    home = Path(paths["CREDITPROBE_PERSIST_ROOT"])
    if _inside(home, app):
        return f"app root {app} contains the persistent root {home}"
    for k in PERSIST_LAYOUT:
        if _inside(Path(paths[k]), app):
            return f"persistent path {k}={paths[k]} lies inside app root {app}"
    return None


def prepare(res: dict[str, Any], app_root: str | None = None
            ) -> dict[str, Any]:
    """Create the persistent layout and the persistence marker. Never chmod
    anything on the persistent root."""
    paths = paths_for(res["persist_root"], app_root)
    for k in PERSIST_LAYOUT:
        Path(paths[k]).mkdir(parents=True, exist_ok=True)
    home = Path(paths["CREDITPROBE_PERSIST_ROOT"])
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


def probe_exec(app_root: Path) -> tuple[bool, str]:
    """Write a script, chmod +x, run it: what launchers, venvs and vLLM
    need. Only ever called on the app root."""
    p = app_root / f".creditprobe-exec-probe-{uuid.uuid4().hex}.sh"
    try:
        p.write_text("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)
        rc = subprocess.run([str(p)], timeout=30).returncode
        return rc == 0, "" if rc == 0 else f"probe exited {rc}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            p.unlink()
        except OSError:
            pass


def prepare_app(res: dict[str, Any]) -> dict[str, Any]:
    paths = res["paths"]
    why = check_separation(paths)
    if why:
        res["app"] = {"ok": False, "reason": why}
        return res
    app = Path(paths["CREDITPROBE_APP_ROOT"])
    try:
        for k in APP_LAYOUT:
            Path(paths[k]).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        res["app"] = {"ok": False, "reason": f"cannot create {app}: {exc}"}
        return res
    ok, why = probe_exec(app)
    du = shutil.disk_usage(app)
    res["app"] = {"ok": ok, "reason": why, "free_bytes": du.free}
    return res


def probe_sqlite(directory: Path) -> tuple[bool, str]:
    """The lab store and the frozen run store use SQLite in WAL mode with
    synchronous=FULL on the persistent runtime: prove it works there."""
    import sqlite3
    db = directory / f".creditprobe-sqlite-probe-{uuid.uuid4().hex}.db"
    try:
        c = sqlite3.connect(db)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        c.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)")
        with c:
            c.execute("INSERT INTO t VALUES ('k', 'v')")
        c.close()
        c = sqlite3.connect(db)
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        got = c.execute("SELECT v FROM t WHERE k='k'").fetchone()
        c.close()
        if got != ("v",):
            return False, "read-back mismatch"
        return True, f"journal_mode={mode}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        for sfx in ("", "-wal", "-shm", "-journal"):
            try:
                Path(f"{db}{sfx}").unlink()
            except OSError:
                pass


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
        f"CREDITPROBE_PERSIST_ROOT: {res['paths']['CREDITPROBE_PERSIST_ROOT']}"
        " (data only; never chmod)",
    ]
    if "sqlite" in res:
        lines.append(f"sqlite_on_persistent: "
                     f"{'OK ' if res['sqlite'][0] else 'FAILED '}"
                     f"{res['sqlite'][1]}")
    if "app" in res:
        a = res["app"]
        lines.append(f"CREDITPROBE_APP_ROOT: {res['paths']['CREDITPROBE_APP_ROOT']}"
                     " (executables; Pod-local, rebuilt from deployment/)")
        if a["ok"]:
            agb = a["free_bytes"] / 1e9
            lines.append(f"app_root_executable: YES ({agb:.1f} GB free)"
                         + ("" if agb >= MIN_APP_FREE_GB else
                            f"  WARN below {MIN_APP_FREE_GB} GB for the "
                            f"venvs"))
        else:
            lines.append(f"{NOT_EXECUTABLE}: {a['reason']}")
    for c in res["rejected"]:
        lines.append(f"  (skipped {c['path']}: {c['reason']})")
    return "\n".join(lines)


def shell_exports(res: dict[str, Any]) -> str:
    env = {"PERSIST_ROOT": res["persist_root"],
           "PERSIST_KIND": res["kind"]} | res["paths"]
    return "".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items())


# ---- deployment: bundle -> persistent deployment/ (copy, never chmod) ---------

def _sums(directory: Path) -> dict[str, str]:
    out = {}
    for line in (directory / "checksums.sha256").read_text().splitlines():
        if line.strip():
            h, name = line.split(None, 1)
            out[name.strip()] = h
    return out


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_dir(directory: Path) -> list[str]:
    """Names whose sha256 does not match checksums.sha256 (or missing)."""
    sums = _sums(directory)
    return [n for n, h in sums.items()
            if not (directory / n).exists() or _sha(directory / n) != h]


def install_deployment(src: Path, dest: Path) -> dict[str, Any]:
    """Copy the verified bundle into the persistent deployment/ dir.
    Byte copies only (shutil.copyfile: no chmod, no copystat). A different
    earlier bundle is archived, never silently overwritten."""
    src, dest = src.resolve(), dest.resolve()
    bad = verify_dir(src)
    if bad:
        return {"ok": False, "reason": f"checksum mismatch in {src}: {bad}"}
    dest.mkdir(parents=True, exist_ok=True)
    if src == dest:
        return {"ok": True, "action": "already the persistent deployment"}
    action = "installed"
    if (dest / "checksums.sha256").exists():
        if (dest / "checksums.sha256").read_bytes() == \
                (src / "checksums.sha256").read_bytes() and \
                not verify_dir(dest):
            return {"ok": True, "action": "identical bundle already installed"}
        arch = dest / "archive" / time.strftime("%Y%m%dT%H%M%SZ",
                                                time.gmtime())
        arch.mkdir(parents=True, exist_ok=True)
        for n in DEPLOY_FILES:
            if (dest / n).exists():
                shutil.copyfile(dest / n, arch / n)
        action = f"installed; previous bundle archived to {arch}"
    for n in DEPLOY_FILES:
        tmp = dest / f".{n}.part"
        shutil.copyfile(src / n, tmp)
        os.replace(tmp, dest / n)
    bad = verify_dir(dest)
    if bad:
        return {"ok": False, "reason": f"copy verification failed: {bad}"}
    return {"ok": True, "action": action}


# ---- the Pod-local app: unpack, mark executables, restore pins ------------------

def unpack(zip_path: Path, paths: dict[str, str]) -> dict[str, Any]:
    """(Re)create <app>/source from the zip: unpack into source.new, carry
    over a same-Pod .venv / node_modules, swap atomically, then restore the
    executable bit ONLY under the app root (from the zip's recorded modes).
    Refuses to touch anything outside the app root."""
    import zipfile

    why = check_separation(paths)
    if why:
        return {"ok": False, "reason": why}
    app = Path(paths["CREDITPROBE_APP_ROOT"]).resolve()
    source = Path(paths["CREDITPROBE_SOURCE_ROOT"]).resolve()
    if not _inside(source, app) or source == app:
        return {"ok": False, "reason": f"source {source} is not inside {app}"}
    new, old = source.with_name("source.new"), source.with_name("source.old")
    for d in (new, old):
        if d.exists():
            shutil.rmtree(d)
    executables = []
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            name = m.filename.split("/", 1)[1] if "/" in m.filename else ""
            if not name or m.is_dir():
                continue
            out = (new / name).resolve()
            if not _inside(out, new):
                return {"ok": False, "reason": f"unsafe path in zip: {name}"}
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(m))
            mode = (m.external_attr >> 16) & 0o777
            if mode & 0o111 or name.endswith((".sh", ".command")):
                executables.append(out)
    kept = []
    if source.exists():
        for rel in PRESERVE_IN_SOURCE:
            if (source / rel).exists() and not (new / rel).exists():
                (new / rel).parent.mkdir(parents=True, exist_ok=True)
                os.replace(source / rel, new / rel)
                kept.append(rel)
        os.replace(source, old)
    os.replace(new, source)
    if old.exists():
        shutil.rmtree(old)
    chmodded = []
    for f in executables:
        target = source / f.relative_to(new)
        assert _inside(target, app), target            # never off the app root
        os.chmod(target, 0o755)
        chmodded.append(str(target))
    return {"ok": True, "source": str(source), "kept": kept,
            "chmodded": chmodded}


def restore_pins(paths: dict[str, str]) -> list[str]:
    """Merge pinned identities saved on the persistent volume back into the
    freshly unpacked profiles, so a new Pod resumes with the same exact
    revisions instead of re-resolving them."""
    src = Path(paths["MODEL_LAB_PINNED_PROFILES_DIR"])
    dst = Path(paths["CREDITPROBE_SOURCE_ROOT"]) / "profiles"
    restored = []
    for f in sorted(src.glob("*.json")) if src.exists() else []:
        target = dst / f.name
        if not target.exists():
            continue
        saved = json.loads(f.read_text())
        if not (saved.get("artifact") or {}).get("revision"):
            continue
        cur = json.loads(target.read_text())
        for k in PIN_KEYS:
            if k in saved:
                cur[k] = saved[k]
        if (saved.get("endpoint") or {}).get("model"):
            cur.setdefault("endpoint", {})["model"] = saved["endpoint"]["model"]
        for k in RUNPOD_PIN_KEYS:
            if k in (saved.get("runpod") or {}):
                cur.setdefault("runpod", {})[k] = saved["runpod"][k]
        target.write_text(json.dumps(cur, indent=1, ensure_ascii=False)
                          + "\n")
        restored.append(f.stem)
    return restored


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("action", nargs="?", default="detect",
                    choices=("detect", "deploy", "unpack", "restore-pins"))
    ap.add_argument("--shell", action="store_true",
                    help="print export lines (report goes to stderr)")
    ap.add_argument("--no-prepare", action="store_true",
                    help="detect only; create nothing")
    ap.add_argument("--from", dest="from_dir",
                    help="deploy: directory holding the bundle files")
    ap.add_argument("--mountinfo", help=argparse.SUPPRESS)      # tests
    ap.add_argument("--candidate", action="append", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    text = Path(args.mountinfo).read_text() if args.mountinfo else None
    cands = CANDIDATES
    if args.candidate:
        cands = tuple(tuple(c.split("=", 1)) for c in args.candidate)
    res = detect(mountinfo_text=text, candidates=cands)
    out = sys.stderr if args.shell else sys.stdout
    if res["status"] != "OK":
        print(report(res), file=out)
        return 3
    if args.no_prepare:
        du = shutil.disk_usage(res["persist_root"])
        res |= {"paths": paths_for(res["persist_root"]),
                "free_bytes": du.free, "total_bytes": du.total,
                "marker": {"new": True, "volume_id": "(not written)",
                           "created_at": "", "created_by_host": ""}}
        print(report(res), file=out)
        return 0
    prepare(res)
    paths = res["paths"]
    if args.action == "deploy":
        r = install_deployment(Path(args.from_dir or "."),
                               Path(paths["CREDITPROBE_DEPLOYMENT_DIR"]))
        print(f"deployment: {r.get('action') or r.get('reason')}")
        return 0 if r["ok"] else 6
    if args.action == "unpack":
        r = unpack(Path(paths["CREDITPROBE_DEPLOYMENT_DIR"]) / ZIP_NAME, paths)
        if not r["ok"]:
            print(f"unpack refused: {r['reason']}")
            return 6
        print(f"unpacked to {r['source']} (kept {r['kept'] or 'nothing'}); "
              f"executable bit set on {len(r['chmodded'])} files, all under "
              f"{paths['CREDITPROBE_APP_ROOT']}")
        return 0
    if args.action == "restore-pins":       # after the manifest check
        pins = restore_pins(paths)
        print(f"pinned identities restored from the volume: "
              f"{', '.join(pins) or 'none'}")
        return 0
    res["sqlite"] = probe_sqlite(Path(paths["MODEL_LAB_RUNTIME_DIR"]))
    prepare_app(res)
    print(report(res), file=out)
    if not res["app"]["ok"]:
        return 4
    if not res["sqlite"][0]:
        print(f"{SQLITE_UNSUPPORTED}: {res['sqlite'][1]}", file=out)
        return 5
    if args.shell:
        print(shell_exports(res), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
