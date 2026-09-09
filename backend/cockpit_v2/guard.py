"""
The seed and reset destination guard. Brief §1.3.

A branch is not runtime isolation, and neither is an intention. Before this
package writes a single Parquet file or touches the catalogue, `check_targets`
resolves every destination it is about to write to and refuses unless all of
them sit inside the V2 namespace.

It FAILS CLOSED. An unreadable setting, a database URL it cannot parse, a
metadata directory that turns out to be the repository's own — all of these
raise rather than warn, because a guard that logs and continues is a guard that
seeds the shared demo database on a Friday.

Nothing here prints a connection string, a password or a key. The report names
directories and a database NAME, never credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The token every V2 destination must carry.
DEFAULT_NAMESPACE = "cockpit_v2"

#: Directory names this package must never write into, whatever the settings
#: say. These are the repository's own shared locations.
FORBIDDEN_DIRECTORIES = ("data/analytics", "data/curated", "metadata")


class UnsafeTarget(RuntimeError):
    """A destination outside the V2 namespace. Never downgraded to a warning."""


@dataclass(frozen=True)
class Targets:
    analytics_dir: str
    metadata_dir: str
    database_name: str
    namespace: str
    flag_on: bool

    def to_dict(self) -> dict[str, Any]:
        return {"analytics_dir": self.analytics_dir,
                "metadata_dir": self.metadata_dir,
                "database_name": self.database_name,
                "namespace": self.namespace,
                "cockpit_intelligence_v2": self.flag_on}


def _database_name(url: str) -> str:
    """The database name from a SQLAlchemy URL, with credentials discarded.

    The regex takes only what follows the last `/` and stops at a `?`, so a URL
    carrying a password never reaches the return value or a message built from
    it.
    """
    if not url:
        return ""
    match = re.search(r"/([^/?#]+)(?:\?|$)", url)
    return match.group(1) if match else ""


def resolve_targets() -> Targets:
    from backend.config import settings

    return Targets(
        analytics_dir=str(Path(settings.analytics_dir).resolve()),
        metadata_dir=str(Path(settings.metadata_dir).resolve()),
        database_name=_database_name(settings.database_url),
        namespace=str(settings.cockpit_v2_namespace or DEFAULT_NAMESPACE),
        flag_on=bool(settings.cockpit_intelligence_v2),
    )


def _looks_isolated(value: str, namespace: str) -> bool:
    """Whether a destination carries the namespace token, in any spelling.

    `cockpit_v2`, `cockpit-v2` and `cockpitv2` all count, because a path is
    written by a person and a hyphen is not a security boundary.
    """
    if not value:
        return False
    flattened = re.sub(r"[^a-z0-9]", "", value.lower())
    token = re.sub(r"[^a-z0-9]", "", namespace.lower())
    return bool(token) and token in flattened


def check_targets(*, require_flag: bool = True) -> Targets:
    """Resolve and validate every destination. Raises rather than returns False.

    Called by `scripts/build_cockpit_v2_demo.py` before it generates anything
    and by `backend.cockpit_v2.persist.write_lake` before it writes anything,
    so a caller cannot reach the filesystem without passing it.
    """
    targets = resolve_targets()
    problems: list[str] = []

    if require_flag and not targets.flag_on:
        problems.append(
            "COCKPIT_INTELLIGENCE_V2 is not set. The V2 seed refuses to run "
            "in a runtime where the feature switch is off, because that "
            "runtime is by definition not the isolated one.")

    repository_root = Path(__file__).resolve().parents[2]
    for label, value in (("analytics directory", targets.analytics_dir),
                         ("metadata directory", targets.metadata_dir)):
        path = Path(value)
        for forbidden in FORBIDDEN_DIRECTORIES:
            shared = (repository_root / forbidden).resolve()
            if path == shared or shared in path.parents:
                problems.append(
                    f"the {label} resolves inside the repository's shared "
                    f"{forbidden}/. The V2 build must write to its own runtime "
                    f"directory, not to the checkout.")
        if not _looks_isolated(value, targets.namespace):
            problems.append(
                f"the {label} ({value}) does not carry the "
                f"{targets.namespace!r} namespace, so it cannot be shown to be "
                f"a V2-only destination.")

    if not targets.database_name:
        problems.append(
            "no database is configured, so the guard cannot confirm that the "
            "V2 build is not pointed at a shared one.")
    elif not _looks_isolated(targets.database_name, targets.namespace):
        problems.append(
            f"the database name ({targets.database_name}) does not carry the "
            f"{targets.namespace!r} namespace. Point DATABASE_URL at the V2 "
            f"database before seeding.")

    if problems:
        raise UnsafeTarget(
            "The Cockpit V2 seed refuses to run: "
            + "; ".join(problems)
            + ". Checked destinations: "
            + ", ".join(f"{k}={v}" for k, v in targets.to_dict().items()
                        if k != "cockpit_intelligence_v2"))
    return targets


def report() -> dict[str, Any]:
    """What the guard would check, without raising. For the diagnostic badge."""
    targets = resolve_targets()
    try:
        check_targets()
        return {**targets.to_dict(), "safe": True, "reason": ""}
    except UnsafeTarget as e:
        return {**targets.to_dict(), "safe": False, "reason": str(e)}


__all__ = ["DEFAULT_NAMESPACE", "FORBIDDEN_DIRECTORIES", "Targets",
           "UnsafeTarget", "check_targets", "report", "resolve_targets"]
