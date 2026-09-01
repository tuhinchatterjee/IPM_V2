"""
Which build of CreditProbe is actually running.

Why this exists
---------------
A forensic investigation into nine wrong answers spent its first hour on a
question the product could not answer about itself: *is the container running
the code that was just pulled?* `.git` is excluded from the Docker build context
and the version string was a constant last edited in an earlier phase, so there
was no way to tell a fresh image from a stale one — and a stale image is the
first thing to rule out when the behaviour does not match the source.

So the running application now reports three things:

``version``     the semantic version, edited by a human at release time
``image``       what was baked in when the image was built — SHA and timestamp
``source``      what the checked-out working tree says right now

When ``source`` and ``image`` disagree, the image is stale: somebody pulled new
code and started the old container. That is reported as a first-class warning
rather than left for somebody to deduce.

Nothing here fails. A missing `.git`, an unset build argument and a read-only
filesystem all degrade to "unknown", because a build-metadata lookup that raises
would take down the health endpoint that exists to diagnose it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Edited by a human at release time. The SHA says exactly what is running; this
#: says what it is meant to be.
VERSION = "0.3.0"

#: Written into the image by docker/backend.Dockerfile. Outside Docker it does
#: not exist, and the source tree answers instead.
STAMP_PATH = Path(os.environ.get("BUILD_STAMP_PATH", "/app/BUILD_STAMP"))

#: The repository root, as seen from this file.
ROOT = Path(__file__).resolve().parent.parent

UNKNOWN = "unknown"


@dataclass(frozen=True)
class BuildInfo:
    """What is running, where it came from, and whether that is consistent."""

    version: str
    image_sha: str = UNKNOWN
    image_built_at: str = ""
    source_sha: str = UNKNOWN
    source_branch: str = ""
    source_committed_at: str = ""
    #: True when the working tree has uncommitted changes — a developer's
    #: machine rather than a deployment.
    source_dirty: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        """Whether the image was built from different code than is checked out.

        Only asserted when both SHAs are actually known. Unknown is not stale —
        claiming a mismatch on missing evidence would send somebody rebuilding
        an image that was fine.
        """
        return (self.image_sha != UNKNOWN and self.source_sha != UNKNOWN
                and self.image_sha != self.source_sha)

    @property
    def sha(self) -> str:
        """The single SHA to show when only one fits.

        The image's, when there is one: what is executing matters more than what
        is on disk beside it.
        """
        return self.image_sha if self.image_sha != UNKNOWN else self.source_sha

    @property
    def short_sha(self) -> str:
        return self.sha[:8] if self.sha != UNKNOWN else UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sha": self.sha,
            "short_sha": self.short_sha,
            "image_sha": self.image_sha,
            "image_built_at": self.image_built_at,
            "source_sha": self.source_sha,
            "source_branch": self.source_branch,
            "source_committed_at": self.source_committed_at,
            "source_dirty": self.source_dirty,
            "stale": self.stale,
            "stale_detail": (
                "This container was built from a different commit than the "
                "code currently checked out. Run `docker compose up --build` "
                "to rebuild it." if self.stale else ""),
            "notes": list(self.notes),
        }

    def fingerprint(self) -> str:
        """One string that changes whenever the running code changes.

        Stamped onto validation runs, so a score can be marked stale when the
        build it was earned on is no longer the build that is running.
        """
        return f"{self.version}+{self.short_sha}"


def _read_stamp() -> dict[str, Any]:
    """What the Dockerfile baked in, if anything did."""
    try:
        if STAMP_PATH.is_file():
            return json.loads(STAMP_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - build metadata never breaks startup
        logger.info("Could not read the build stamp: %s", e)
    return {}


def _read_git(root: Path) -> dict[str, Any]:
    """The working tree's commit, read without requiring the git binary.

    Parsing `.git` by hand rather than shelling out, because the slim runtime
    image has no git installed and the directory is mounted read-only. Falls
    back to the binary where the plumbing is unusual (a worktree, a packed
    symbolic ref), which is the case on a developer's machine where git exists.
    """
    git = root / ".git"
    if not git.exists():
        return {}

    out: dict[str, Any] = {}
    try:
        if git.is_file():
            # A worktree: `.git` is a file pointing at the real directory.
            pointer = git.read_text(encoding="utf-8").strip()
            if pointer.startswith("gitdir:"):
                git = Path(pointer.split(":", 1)[1].strip())

        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            out["branch"] = ref.rsplit("/", 1)[-1]
            loose = git / ref
            if loose.is_file():
                out["sha"] = loose.read_text(encoding="utf-8").strip()
            else:
                out["sha"] = _packed_ref(git, ref)
        else:
            out["sha"] = head
            out["branch"] = "(detached)"
    except Exception as e:  # noqa: BLE001
        logger.info("Could not read .git directly: %s", e)

    if not out.get("sha"):
        out.update(_git_binary(root))
    return {k: v for k, v in out.items() if v}


def _packed_ref(git: Path, ref: str) -> str:
    try:
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or " " not in line:
                continue
            sha, name = line.split(" ", 1)
            if name.strip() == ref:
                return sha.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _git_binary(root: Path) -> dict[str, Any]:
    """Ask git, where git exists. Never on the container's happy path."""
    def run(*args: str) -> str:
        try:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", *args], cwd=root, capture_output=True, text=True,
                timeout=5, check=False).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""

    sha = run("rev-parse", "HEAD")
    if not sha:
        return {}
    return {
        "sha": sha,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "committed_at": run("show", "-s", "--format=%cI", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


@lru_cache(maxsize=1)
def build_info() -> BuildInfo:
    """What is running. Read once — none of it changes while the process lives."""
    stamp = _read_stamp()
    git = _read_git(ROOT)
    notes: list[str] = []

    image_sha = str(stamp.get("git_sha") or os.environ.get("GIT_SHA") or "").strip()
    image_built = str(stamp.get("built_at")
                      or os.environ.get("BUILD_TIMESTAMP") or "").strip()

    if not image_sha and not git:
        notes.append(
            "Neither a build stamp nor a .git directory is available, so the "
            "running commit cannot be identified. In Docker, mount ./.git "
            "read-only or pass GIT_SHA as a build argument.")
    if image_sha and not git:
        notes.append(
            "The checked-out source is not visible from the container, so a "
            "stale image cannot be detected. Mount ./.git read-only to enable "
            "that check.")

    info = BuildInfo(
        version=str(stamp.get("version") or VERSION),
        image_sha=image_sha or UNKNOWN,
        image_built_at=image_built,
        source_sha=str(git.get("sha") or UNKNOWN),
        source_branch=str(git.get("branch") or ""),
        source_committed_at=str(git.get("committed_at") or ""),
        source_dirty=bool(git.get("dirty")),
        notes=notes,
    )
    if info.stale:
        logger.warning(
            "This container was built from %s but the checked-out source is "
            "%s. Rebuild with `docker compose up --build`.",
            info.image_sha[:8], info.source_sha[:8])
    return info


def started_at() -> str:
    return _STARTED


_STARTED = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


__all__ = ["UNKNOWN", "VERSION", "BuildInfo", "build_info", "started_at"]
