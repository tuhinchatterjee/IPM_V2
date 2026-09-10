"""
The identity guard: a retail build command refuses a target that is not the
retail installation's.

A separate Git worktree isolates source code and nothing else. The database,
the analytics lake, the uploads and the caches are all reached through
configuration, and configuration is exactly the thing that gets copied from a
working installation and then half-edited. So every destructive retail command —
seed, rebuild, reset, publish — asks this module whether the target it is about
to overwrite is the retail one, and refuses if it cannot prove that it is.

Refusal is the default. An unrecognised target is not assumed safe.
"""

from __future__ import annotations

import os
from pathlib import Path

#: A directory belongs to the retail installation if this marker sits at its
#: root, or if `retail` names one of its path segments.
MARKER_FILENAME = ".retail-installation"
MARKER_TEXT = (
    "This directory belongs to the CreditProbe Saudi retail-only installation.\n"
    "It is written by scripts/build_retail_demo.py and by nothing else.\n"
    "Deleting this file makes every retail build command refuse to touch the\n"
    "directory, which is the intended failure mode.\n"
)

#: Names that identify a frozen source demo. A retail command pointed at one of
#: these fails immediately, before it opens anything.
PROTECTED_PATH_SEGMENTS = ("5318", "5308", "whatif_5318", "whatif5318")
PROTECTED_DB_TOKENS = ("5318", "5308", "creditprobe_demo", "ipm_demo", "portfolio_demo")


class RetailTargetRefused(RuntimeError):
    """Raised instead of overwriting something that is not the retail target."""


def mark(directory: Path) -> Path:
    """Claim a directory for the retail installation."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / MARKER_FILENAME
    if not marker.exists():
        marker.write_text(MARKER_TEXT)
    return marker


def is_retail_directory(directory: Path) -> bool:
    directory = Path(directory)
    if (directory / MARKER_FILENAME).exists():
        return True
    return "retail" in {part.lower() for part in directory.parts}


def require_retail_directory(directory: Path, *, what: str) -> Path:
    """Prove a directory is the retail installation's, or refuse."""
    directory = Path(directory)
    lowered = {part.lower() for part in directory.parts}
    clash = sorted(lowered & set(PROTECTED_PATH_SEGMENTS))
    if clash:
        raise RetailTargetRefused(
            f"Refusing to {what} in {directory}: its path names a frozen source "
            f"installation ({', '.join(clash)}). Point the retail build at the "
            "retail data directory instead — nothing here will be touched."
        )
    if not is_retail_directory(directory):
        raise RetailTargetRefused(
            f"Refusing to {what} in {directory}: it carries no retail marker. "
            f"A retail directory has a '{MARKER_FILENAME}' file at its root, or "
            "'retail' as one of its path segments. Create the directory with the "
            "retail build command rather than pointing this one at an existing "
            "demo lake."
        )
    return directory


def require_retail_database(url: str | None, *, what: str) -> str | None:
    """Prove a database URL is the retail installation's, or refuse.

    An empty URL is allowed: the product runs with no database at all, and the
    file-backed lake is then the only store. What is not allowed is a URL that
    names one of the frozen demos.
    """
    if not url:
        return url
    lowered = url.lower()
    hit = [t for t in PROTECTED_DB_TOKENS if t in lowered]
    if hit:
        raise RetailTargetRefused(
            f"Refusing to {what} against the configured database: its URL names "
            f"a protected source demo ({', '.join(hit)}). Set DATABASE_URL to the "
            "retail database before running a retail seed, migration or reset."
        )
    if "retail" not in lowered:
        raise RetailTargetRefused(
            f"Refusing to {what} against the configured database: its URL does "
            "not name a retail database. The retail installation uses its own "
            "database; it never seeds into the one a source demo is serving."
        )
    return url


def guard_environment(*, what: str) -> None:
    """Check every mutable target the current environment points at."""
    from backend.config import settings

    for directory in (settings.analytics_dir, settings.metadata_dir):
        require_retail_directory(Path(directory), what=what)
    require_retail_database(os.environ.get("DATABASE_URL") or "", what=what)
