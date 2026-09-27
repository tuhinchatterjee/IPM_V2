"""
The protected core, and the proof that the harness never changed it.

Three independent checks, because any one alone can be defeated:

1. SHA-256 of every protected file equals the value recorded in the committed
   manifest (`config/opus360/protected_manifest.v1.json`).
2. The git blob id of every protected file's CURRENT bytes equals the blob id
   of that path at the frozen commit. This anchors the manifest to the tag:
   regenerating the manifest after a change cannot make this check pass.
3. `git diff <frozen commit> -- <protected paths>` is empty and no untracked
   (non-ignored) file has appeared inside a protected directory.

The manifest is never regenerated to hide a difference. `build()` refuses to
write a manifest when the working tree already differs from the frozen commit.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cert import FROZEN_COMMIT, FROZEN_TAG
from cert.paths import PROTECTED_MANIFEST, ROOT

#: The directories the brief names, verbatim.
PROTECTED_DIRS: tuple[str, ...] = (
    "backend/cockpit_v4",
    "frontend/src/components/cockpit-v4",
    "frontend/src/app/cockpit",
    "scripts/cockpit_v4",
    "tests/cockpit_v4",
    "config/cockpit_v4",
)
#: Single files the brief names.
PROTECTED_FILES: tuple[str, ...] = (
    "backend/llm/anthropic_provider.py",
)
#: Files OUTSIDE those directories that the frozen runtime actually imports.
#: Established by loading the runtime's entry points and driving a scripted
#: end-to-end run, then collecting every repository module in sys.modules
#: (see `runtime_closure()`); `tests/opus360/test_protected.py` fails if a
#: scripted run ever loads a repository module this list does not cover.
RUNTIME_CLOSURE: tuple[str, ...] = (
    "backend/__init__.py",
    "backend/config.py",
    "backend/llm/__init__.py",
    "backend/llm/base.py",
    "backend/llm/caching.py",
    "backend/llm/telemetry.py",
    "backend/cockpit_agentic/__init__.py",
    "backend/cockpit_agentic/calendar.py",
    "backend/cockpit_agentic/catalog.py",
    "backend/cockpit_agentic/contracts.py",
    "backend/cockpit_agentic/fields.py",
    "backend/cockpit_agentic/generate.py",
    "backend/cockpit_agentic/profile.py",
    "backend/cockpit_agentic/scope.py",
    "backend/cockpit_agentic/store.py",
    "backend/cockpit_agentic/sql.py",
    "backend/cockpit_agentic/values.py",
    "backend/logging_setup.py",
    "requirements.txt",
    "pyproject.toml",
)


def _git(*args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=False)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_paths() -> list[str]:
    """Every path tracked AT THE FROZEN COMMIT inside the protected set."""
    out = _git("ls-tree", "-r", "--name-only", FROZEN_COMMIT, "--",
               *PROTECTED_DIRS)
    tracked = set(line for line in out.splitlines() if line.strip())
    for single in (*PROTECTED_FILES, *RUNTIME_CLOSURE):
        present = _git("ls-tree", "--name-only", FROZEN_COMMIT, "--", single)
        if present.strip():
            tracked.add(single)
    return sorted(tracked)


def frozen_blobs(paths: list[str]) -> dict[str, str]:
    """Blob id of each path at the frozen commit, in one git call."""
    out = _git("ls-tree", "-r", FROZEN_COMMIT, "--", *paths)
    blobs: dict[str, str] = {}
    for line in out.splitlines():
        meta, _, name = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob":
            blobs[name] = parts[2]
    return blobs


def worktree_blobs(paths: list[str]) -> dict[str, str]:
    existing = [p for p in paths if (ROOT / p).exists()]
    if not existing:
        return {}
    done = subprocess.run(["git", "hash-object", "--no-filters", "--stdin-paths"],
                          cwd=ROOT, input="\n".join(existing) + "\n",
                          capture_output=True, text=True, check=True)
    return dict(zip(existing, done.stdout.split(), strict=True))


@dataclass
class Verdict:
    ok: bool
    checked_files: int
    manifest_sha256: str
    problems: list[str] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checked_files": self.checked_files,
                "manifest_sha256": self.manifest_sha256,
                "problems": list(self.problems), "checked_at": self.checked_at}


def build(path: Path = PROTECTED_MANIFEST) -> dict[str, Any]:
    """Write the manifest. Refuses if the tree already differs from the tag."""
    paths = protected_paths()
    frozen = frozen_blobs(paths)
    current = worktree_blobs(paths)
    drift = [p for p in paths if current.get(p) != frozen.get(p)]
    if drift:
        raise RuntimeError(
            f"refusing to build the protected manifest: {len(drift)} protected "
            f"file(s) already differ from {FROZEN_COMMIT[:12]}: {drift[:10]}")
    files = {p: {"sha256": sha256_file(ROOT / p), "git_blob": frozen[p],
                 "bytes": (ROOT / p).stat().st_size} for p in paths}
    manifest = {
        "schema": "opus360.protected_manifest.v1",
        "frozen_tag": FROZEN_TAG,
        "frozen_commit": FROZEN_COMMIT,
        "protected_dirs": list(PROTECTED_DIRS),
        "protected_files": list(PROTECTED_FILES),
        "runtime_closure": list(RUNTIME_CLOSURE),
        "file_count": len(files),
        "built_at": datetime.now(UTC).isoformat(),
        "files": files,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return manifest


def verify(path: Path = PROTECTED_MANIFEST,
           expected_manifest_sha: str = "") -> Verdict:
    """All three checks. Never rewrites anything."""
    now = datetime.now(UTC).isoformat()
    if not path.exists():
        return Verdict(False, 0, "", [f"manifest missing: {path}"], now)
    manifest_sha = sha256_file(path)
    problems: list[str] = []
    if expected_manifest_sha and manifest_sha != expected_manifest_sha:
        problems.append(
            f"protected manifest itself changed: {manifest_sha[:16]} != "
            f"{expected_manifest_sha[:16]} recorded at experiment start")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("frozen_commit") != FROZEN_COMMIT:
        problems.append("manifest names a different frozen commit")
    files: dict[str, dict[str, str]] = manifest.get("files") or {}
    # Check 1: SHA-256 against the committed manifest.
    for rel, rec in sorted(files.items()):
        p = ROOT / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
            continue
        if sha256_file(p) != rec.get("sha256"):
            problems.append(f"sha256 changed: {rel}")
    # Check 2: blob ids against the frozen commit (independent of the manifest).
    paths = protected_paths()
    if set(paths) != set(files):
        extra = sorted(set(paths) - set(files))
        missing = sorted(set(files) - set(paths))
        if extra or missing:
            problems.append(f"manifest coverage differs from frozen tree: "
                            f"+{extra[:5]} -{missing[:5]}")
    frozen = frozen_blobs(paths)
    current = worktree_blobs(paths)
    for p in paths:
        if current.get(p) != frozen.get(p):
            problems.append(f"differs from frozen commit: {p}")
    # Check 3: git diff and untracked additions inside protected dirs.
    diff = _git("diff", "--name-only", FROZEN_COMMIT, "--", *PROTECTED_DIRS,
                *PROTECTED_FILES, *RUNTIME_CLOSURE, check=False)
    for line in diff.splitlines():
        if line.strip():
            problems.append(f"git diff vs frozen commit: {line.strip()}")
    untracked = _git("ls-files", "--others", "--exclude-standard", "--",
                     *PROTECTED_DIRS, check=False)
    for line in untracked.splitlines():
        if line.strip():
            problems.append(f"new untracked file in protected dir: {line.strip()}")
    # de-duplicate while keeping order
    seen: set[str] = set()
    unique = [p for p in problems if not (p in seen or seen.add(p))]
    return Verdict(not unique, len(files), manifest_sha, unique, now)


def runtime_closure() -> list[str]:
    """Repository files currently loaded in this interpreter (for the test)."""
    import sys

    out: set[str] = set()
    root = str(ROOT.resolve())
    for module in list(sys.modules.values()):
        f = getattr(module, "__file__", None)
        if not f:
            continue
        try:
            rp = str(Path(f).resolve())
        except OSError:
            continue
        if rp.startswith(root) and "/.venv/" not in rp:
            out.add(str(Path(rp).relative_to(root)))
    return sorted(out)
