"""
Protected manifest for the frozen AdvancedCockpit baseline.

Every file tracked at the frozen commit, outside the lab-owned allowlist, is
hashed (SHA-256 of the working-tree bytes) and compared against the bytes Git
holds for that commit. `--write` records the manifest; `--check` proves that
nothing protected has changed since.

Read-only against the frozen tree: it reads blobs through `git cat-file` and
files from disk. It never runs, sources or imports frozen code.

Usage:
    python scripts/model_lab/protected_manifest.py --write
    python scripts/model_lab/protected_manifest.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN_TAG = "cockpit-round-h-live-pass-2026-09-23"
FROZEN_COMMIT = "245c50e45786c6e0c866b281f9dd74da17d160b5"
MANIFEST = ROOT / "docs" / "model_comparison" / "PROTECTED_MANIFEST.json"

#: The only paths this lab may add or change. Everything else tracked at the
#: frozen commit is protected.
LAB_OWNED: tuple[str, ...] = (
    "backend/model_lab/",
    "scripts/model_lab/",
    "tests/model_lab/",
    "frontend/src/app/cockpit/lab/",
    "frontend/src/components/model-lab/",
    "docs/model_comparison/",
    "profiles/",
    "launchers/",
    "artifacts/model_comparison/",
)

#: Hashed separately because they pin the dependency environment.
LOCKFILES: tuple[str, ...] = (
    "requirements.txt", "pyproject.toml", "frontend/package.json",
    "frontend/package-lock.json",
)

#: The core analytical surface, reported as its own group so a reader can see
#: at a glance that the engine, not just "the repository", is unchanged.
CORE_PREFIXES: tuple[str, ...] = (
    "backend/cockpit_v4/", "backend/llm/", "backend/cockpit_agentic/",
    "frontend/src/components/cockpit-v4/", "frontend/src/app/cockpit/",
    "scripts/cockpit_v4/", "tests/cockpit_v4/", "config/cockpit_v4/",
)


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                          capture_output=True, text=True).stdout


def lab_owned(path: str) -> bool:
    return any(path.startswith(p) for p in LAB_OWNED)


def frozen_files() -> list[str]:
    out = _git("ls-tree", "-r", "--name-only", "-z", FROZEN_COMMIT)
    return sorted(p for p in out.split("\0") if p and not lab_owned(p))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frozen_blob_hashes(paths: list[str]) -> dict[str, str]:
    """SHA-256 of each file's bytes AS COMMITTED at the frozen commit."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        input="".join(f"{FROZEN_COMMIT}:{p}\n" for p in paths).encode(),
        capture_output=True, check=True)
    buf, out, i = proc.stdout, {}, 0
    for p in paths:
        nl = buf.index(b"\n", i)
        header = buf[i:nl].decode().split()
        if header[-1] == "missing":
            out[p] = "MISSING"
            i = nl + 1
            continue
        size = int(header[2])
        out[p] = _sha256(buf[nl + 1: nl + 1 + size])
        i = nl + 1 + size + 1
    return out


def frozen_blob_ids() -> dict[str, str]:
    """Git blob ids at the frozen commit (content after Git's clean filter)."""
    out = _git("ls-tree", "-r", "-z", FROZEN_COMMIT)
    ids = {}
    for rec in out.split("\0"):
        if rec:
            meta, path = rec.split("\t", 1)
            ids[path] = meta.split()[2]
    return ids


def worktree_blob_ids(paths: list[str]) -> dict[str, str]:
    """Blob ids of the working-tree files, through the same clean filters
    (e.g. .gitattributes eol=crlf) Git applies, so a checkout's line-ending
    conversion is not mistaken for an edit."""
    present = [p for p in paths if (ROOT / p).exists() or (ROOT / p).is_symlink()]
    out = subprocess.run(
        ["git", "-C", str(ROOT), "hash-object", "--stdin-paths"],
        input="\n".join(present) + "\n", capture_output=True, text=True,
        check=True).stdout.split()
    ids = dict(zip(present, out, strict=True))
    return {p: ids.get(p, "ABSENT") for p in paths}


def build() -> dict:
    paths = frozen_files()
    committed = frozen_blob_hashes(paths)
    files = {p: committed[p] for p in paths}
    blobs = frozen_blob_ids()
    core = {p: h for p, h in files.items()
            if any(p.startswith(c) for c in CORE_PREFIXES)}
    agg = _sha256("\n".join(f"{h}  {p}" for p, h in files.items()).encode())
    core_agg = _sha256("\n".join(f"{h}  {p}" for p, h in core.items()).encode())
    return {
        "schema_version": 1,
        "frozen_tag": FROZEN_TAG,
        "frozen_commit": FROZEN_COMMIT,
        "hash": "sha256 of committed file bytes at the frozen commit",
        "lab_owned_allowlist": list(LAB_OWNED),
        "file_count": len(files),
        "core_file_count": len(core),
        "aggregate_sha256": agg,
        "core_aggregate_sha256": core_agg,
        "lockfiles": {p: files.get(p, "ABSENT") for p in LOCKFILES},
        "files": files,
        "blob_ids": {p: blobs[p] for p in paths},
    }


def check(manifest: dict) -> list[dict]:
    """Every protected path whose working-tree bytes differ from the record."""
    diffs = []
    recorded_ids = manifest["blob_ids"]
    now_ids = worktree_blob_ids(list(recorded_ids))
    for path, recorded in recorded_ids.items():
        if now_ids[path] != recorded:
            diffs.append({"path": path, "recorded": recorded,
                          "now": now_ids[path]})
    # A protected directory that gained a file the frozen commit never had.
    tracked_now = set(_git("ls-files", "-z").split("\0")) - {""}
    for path in sorted(tracked_now - set(manifest["files"])):
        if not lab_owned(path):
            diffs.append({"path": path, "recorded": "ABSENT",
                          "now": "NEW_TRACKED_FILE"})
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        m = build()
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
        print(f"wrote {MANIFEST.relative_to(ROOT)}: {m['file_count']} "
              f"protected files, core {m['core_file_count']}, "
              f"aggregate {m['aggregate_sha256'][:16]}")
        return 0
    m = json.loads(MANIFEST.read_text())
    diffs = check(m)
    if diffs:
        print(f"PROTECTED MANIFEST FAILED: {len(diffs)} change(s)")
        for d in diffs[:50]:
            print(f"  {d['path']}: {d['recorded'][:12]} -> {d['now'][:12]}")
        return 1
    print(f"protected manifest OK: {m['file_count']} files match "
          f"{m['frozen_tag']} ({m['frozen_commit'][:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
