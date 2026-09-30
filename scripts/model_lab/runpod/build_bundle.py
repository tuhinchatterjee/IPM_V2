"""
Build the RunPod deployment bundle for the Model Lab (full Model I/O Trace).

    python scripts/model_lab/runpod/build_bundle.py            # build + verify

Writes artifacts/model_comparison/deployment/ (gitignored):

    CreditProbe_Model_Lab_RunPod_FullTrace.zip
    RUNPOD_BOOTSTRAP.sh
    DEPLOYMENT_MANIFEST.json
    checksums.sha256

What goes in is DERIVED, not guessed. A closure run imports the lab app,
runs an offline fixture comparison with export and trace, and verifies the
seeded data, recording every repository file Python imported or opened
(`sys.addaudithook`). The backend packages it touched are shipped whole;
other backend applications are not. File bytes come from the committed HEAD
(`git show`), never from an unsaved working tree.

Excluded: .git, .venv, node_modules, .env*, credentials, model weights,
generated data (the lake is re-seeded on the pod), runtime state, and every
backend package outside the closure. A secret scan fails the build on any
key-like content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts" / "model_comparison" / "deployment"
ZIP_NAME = "CreditProbe_Model_Lab_RunPod_FullTrace.zip"
BOOTSTRAP = ROOT / "scripts" / "model_lab" / "runpod" / "RUNPOD_BOOTSTRAP.sh"
FROZEN_COMMIT = "245c50e45786c6e0c866b281f9dd74da17d160b5"
PREFIX = "creditprobe-model-lab/"

#: Always shipped (tracked files under these paths).
ALWAYS = ("scripts/model_lab/", "scripts/cockpit_v4/", "tests/model_lab/",
          "frontend/", "profiles/", "launchers/", "docs/model_comparison/",
          "config/cockpit_v4/", "requirements.txt", "pyproject.toml",
          "backend/__init__.py")
#: Never shipped, whatever the closure says.
NEVER = re.compile(r"(^|/)(\.env[^/]*|\.git/|node_modules/|\.venv/|"
                   r"__pycache__/|artifacts/|.*\.(gguf|safetensors|bin|pt|"
                   r"pth|onnx))$|(^|/)(\.env[^/]*)$")
SECRETS = re.compile(rb"(sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|"
                     rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
                     rb"hf_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})")

CLOSURE_SCRIPT = r'''
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(sys.argv[1]); out = sys.argv[2]
seen = set()
def hook(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        try:
            p = Path(os.fsdecode(args[0])).resolve()
        except Exception:
            return
        if str(p).startswith(str(ROOT)):
            seen.add(str(p.relative_to(ROOT)))
sys.addaudithook(hook)
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests" / "model_lab"))
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
from backend.model_lab.app import create_lab_app
create_lab_app()
from conftest import make_service, run
svc = make_service(Path(tempfile.mkdtemp()))
cid, _ = run(svc, ["fixture-repair", "fixture-reference"])
svc.export(cid)
from backend.model_lab import model_io
model_io.build(svc.coord, cid, include_bodies=True)
from backend.cockpit_v4.generate import corporate, retail  # seeding code
from backend.cockpit_v4 import domains, invariants, lake
for m in list(sys.modules.values()):
    f = getattr(m, "__file__", None)
    if f and str(Path(f).resolve()).startswith(str(ROOT)):
        seen.add(str(Path(f).resolve().relative_to(ROOT)))
json.dump(sorted(seen), open(out, "w"))
'''


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                          capture_output=True, text=True).stdout


def git_bytes(path: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{path}"],
                          check=True, capture_output=True).stdout


def closure() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "closure.py"
        script.write_text(CLOSURE_SCRIPT)
        out = Path(tmp) / "closure.json"
        subprocess.run([sys.executable, str(script), str(ROOT), str(out)],
                       check=True, cwd=ROOT, capture_output=True,
                       env=dict(os.environ, MODEL_LAB_FULL_IO_TRACE="true"))
        return json.loads(out.read_text())


def select(tracked: list[str], touched: list[str]) -> tuple[list[str], dict]:
    packages = sorted({"/".join(p.split("/")[:2]) + "/" for p in touched
                       if p.startswith("backend/") and p.count("/") >= 2})
    top_backend = sorted(p for p in touched if p.startswith("backend/")
                         and p.count("/") == 1)
    data_read = sorted(p for p in touched if p.startswith(("data/",
                                                            "config/")))
    keep = []
    for p in tracked:
        if NEVER.search(p):
            continue
        if p.startswith(ALWAYS) or p in top_backend or p in data_read or \
                any(p.startswith(pkg) for pkg in packages):
            keep.append(p)
    return sorted(set(keep)), {"backend_packages": packages,
                               "backend_modules": top_backend,
                               "data_and_config_read": data_read}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    dirty = git("status", "--porcelain", "--", "backend/model_lab",
                "scripts/model_lab", "profiles", "frontend/src/components/"
                "model-lab", "tests/model_lab").strip()
    if dirty:
        print("refusing: lab-owned files have uncommitted changes; the "
              "bundle must equal a commit\n" + dirty)
        return 2
    head = git("rev-parse", "HEAD").strip()
    tracked = git("ls-files").splitlines()
    touched = closure()
    files, scope = select(tracked, touched)
    protected = json.loads((ROOT / "docs/model_comparison/"
                            "PROTECTED_MANIFEST.json").read_text())["files"]
    entries, listing, leaks = {}, {}, []
    for p in files:
        data = git_bytes(p)
        if SECRETS.search(data):
            leaks.append(p)
        entries[p] = data
        listing[p] = {"bytes": len(data), "sha256": sha(data)}
    if leaks:
        print("refusing: key-like content in " + ", ".join(leaks))
        return 2
    manifest = {
        "bundle": ZIP_NAME, "built_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "source_commit": head, "frozen_commit": FROZEN_COMMIT,
        "purpose": "CreditProbe Model Lab with full Model I/O Trace for the "
                   "RunPod A40 benchmark; no model weights, no credentials",
        "trace_flag": "MODEL_LAB_FULL_IO_TRACE=true (default)",
        "closure": scope | {"method": "audit-hook closure run: lab app, "
                            "offline fixture comparison with export and "
                            "trace, seeding code imports"},
        "excluded": [".git", ".venv", "node_modules", ".env*", "API keys",
                     "model weights", "generated lake data (re-seeded)",
                     "runtime state (artifacts/)",
                     "backend packages outside the closure"],
        "file_count": len(files),
        "protected_files_bundled": sorted(p for p in files
                                          if p in protected),
        "files": listing,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    zpath = OUT / ZIP_NAME
    man_bytes = (json.dumps(manifest, indent=1, sort_keys=True) + "\n"
                 ).encode()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(entries) + ["DEPLOYMENT_MANIFEST.json"]:
            info = zipfile.ZipInfo(PREFIX + p, date_time=(2026, 1, 1, 0, 0,
                                                          0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if p.endswith((".sh", ".command")) else 0o644
            info.external_attr = (0o100000 | mode) << 16
            z.writestr(info, entries.get(p, man_bytes))
    (OUT / "DEPLOYMENT_MANIFEST.json").write_bytes(man_bytes)
    boot = OUT / "RUNPOD_BOOTSTRAP.sh"
    boot.write_bytes(git_bytes("scripts/model_lab/runpod/RUNPOD_BOOTSTRAP.sh"))
    boot.chmod(0o755)
    sums = "".join(f"{sha((OUT / n).read_bytes())}  {n}\n" for n in
                   (ZIP_NAME, "RUNPOD_BOOTSTRAP.sh",
                    "DEPLOYMENT_MANIFEST.json"))
    (OUT / "checksums.sha256").write_text(sums)
    print(f"bundle {zpath} ({zpath.stat().st_size:,} bytes, {len(files)} "
          f"files, {len(manifest['protected_files_bundled'])} protected)")
    print(sums, end="")
    return verify(zpath)


def verify(zpath: Path) -> int:
    """Unpack into a scratch dir and run the git-free manifest check."""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
        root = Path(tmp) / PREFIX.rstrip("/")
        r = subprocess.run([sys.executable, "scripts/model_lab/"
                            "protected_manifest.py", "--check-bundle"],
                           cwd=root, capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        names = z.namelist()
        bad = [n for n in names if NEVER.search(n[len(PREFIX):])]
        if bad:
            print(f"refusing: excluded paths in bundle: {bad[:5]}")
            return 1
        return r.returncode


if __name__ == "__main__":
    sys.exit(main() if "--verify-only" not in sys.argv else verify(
        OUT / ZIP_NAME))
