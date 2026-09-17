"""One version of the whole book, and the refusal to join two of them.

The defect this exists for
--------------------------
The retail installation publishes six datasets: the canonical facility-month
book, the Early Warning panel, the Early Warning score, and three governed
views read by the Cockpit, the scorecard screens and What-If. They were built
one after another, each idempotent and each skipping what it already had.

That is correct while the book underneath is the same book. Regenerating it
changes every period WITHOUT changing their names, so an incremental build of
the views has nothing to do and they go on serving the previous book's figures
— reconciled against a canonical total they no longer match. The bootstrap
noticed this and rebuilt them, which fixed the symptom for the case where the
reconciliation happened to be checked, and left the general one: a build that
fails halfway publishes a new Cockpit book beside yesterday's Early Warning.

So a publication is a BUNDLE. Everything is built into a staging directory,
validated together, and swapped in one move. Until the swap, readers see the
previous complete bundle; after it, they see this one; there is no moment at
which they see half of each.

What a bundle id is
-------------------
A short hash over the things that decide what the numbers are: the generator's
manifest hash, the configuration version, the episode configuration, and the
per-dataset content hashes. Every dataset written in a bundle carries it, and
every cohort snapshot records the bundle it was measured on.

Joining across bundles is an ERROR, not a discrepancy to reconcile. Two sets of
figures from two builds are not two measurements of the same thing that happen
to differ; averaging them produces a number that was never true.

Everything here describes SYNTHETIC demonstration data.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VERSION = "retail-bundle-1.0.0"

BUNDLE_FILENAME = "retail_bundle.json"

#: The datasets a complete bundle holds. A publication that produced fewer is
#: incomplete and is never swapped in.
CANONICAL = "retail_facility_month"
REQUIRED: tuple[str, ...] = (
    CANONICAL,
    "retail_ews_panel",
    "retail_ews_score",
    "retail_early_warning",
    "retail_credit_scorecard",
    "retail_whatif",
)


class StaleBundle(RuntimeError):
    """Two datasets from two different builds, about to be joined.

    Raised rather than reconciled, and raised with both ids in the message,
    because the useful thing to know is which two builds were mixed.
    """


class IncompleteBundle(RuntimeError):
    """A publication that did not produce everything a bundle holds."""


@dataclass
class Bundle:
    """The identity of one complete publication."""

    bundle_id: str
    created_at: str
    #: Which month the bundle's book ends at.
    as_of: str
    #: The configuration and code that produced it.
    config_version: str
    generator_version: str
    episode_config_version: str
    seed: int
    #: {dataset: content hash over its published months}
    dataset_hashes: dict[str, str] = field(default_factory=dict)
    #: {dataset: number of published periods}
    dataset_periods: dict[str, int] = field(default_factory=dict)
    #: What the validation found before the swap.
    checks: list[dict[str, Any]] = field(default_factory=list)
    #: The bundle this replaced, kept so a rollback has a name.
    replaced: str = ""
    disclosure: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VERSION,
            "bundle_id": self.bundle_id,
            "created_at": self.created_at,
            "as_of": self.as_of,
            "config_version": self.config_version,
            "generator_version": self.generator_version,
            "episode_config_version": self.episode_config_version,
            "seed": self.seed,
            "dataset_hashes": dict(self.dataset_hashes),
            "dataset_periods": dict(self.dataset_periods),
            "checks": list(self.checks),
            "replaced": self.replaced,
            "disclosure": self.disclosure,
        }

    @property
    def complete(self) -> bool:
        return all(name in self.dataset_hashes for name in REQUIRED)

    def missing(self) -> list[str]:
        return [n for n in REQUIRED if n not in self.dataset_hashes]


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def dataset_hash(root: Path, dataset: str) -> tuple[str, int]:
    """A content hash over one dataset's published parquet files.

    Hashes the FILES rather than a summary of them: the question a stale-join
    check has to answer is "is this the same data", and a row count and a
    total can both match across two genuinely different builds.
    """
    directory = Path(root) / dataset
    if not directory.exists():
        return "", 0
    digest = hashlib.sha256()
    periods = 0
    for part in sorted(directory.rglob("*.parquet")):
        periods += 1
        digest.update(part.relative_to(directory).as_posix().encode())
        with part.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
    return digest.hexdigest(), periods


def new_id(*parts: str) -> str:
    raw = "|".join([VERSION, *[p or "" for p in parts]])
    return "RB-" + hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


def describe(root: Path, *, config: Any, as_of: str,
             episode_config_version: str = "") -> Bundle:
    """Measure a staged or published tree, without moving anything."""
    hashes: dict[str, str] = {}
    periods: dict[str, int] = {}
    for dataset in REQUIRED:
        digest, count = dataset_hash(Path(root), dataset)
        if digest:
            hashes[dataset] = digest
            periods[dataset] = count
    return Bundle(
        bundle_id=new_id(config.config_version, str(config.seed), as_of,
                         *[hashes.get(d, "") for d in REQUIRED]),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        as_of=as_of,
        config_version=config.config_version,
        generator_version=config.generator_version,
        episode_config_version=episode_config_version,
        seed=int(config.seed),
        dataset_hashes=hashes,
        dataset_periods=periods,
        disclosure=config.disclosure,
    )


# ---------------------------------------------------------------------------
# Reading and writing
# ---------------------------------------------------------------------------


def path(metadata_dir: str | Path | None = None) -> Path:
    if metadata_dir is None:
        from backend.config import settings

        metadata_dir = settings.metadata_dir
    return Path(metadata_dir) / BUNDLE_FILENAME


def write(bundle: Bundle, metadata_dir: str | Path | None = None) -> Path:
    target = path(metadata_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
    return target


def read(metadata_dir: str | Path | None = None) -> Bundle | None:
    target = path(metadata_dir)
    if not target.exists():
        return None
    raw = json.loads(target.read_text(encoding="utf-8"))
    return Bundle(
        bundle_id=raw.get("bundle_id", ""),
        created_at=raw.get("created_at", ""),
        as_of=raw.get("as_of", ""),
        config_version=raw.get("config_version", ""),
        generator_version=raw.get("generator_version", ""),
        episode_config_version=raw.get("episode_config_version", ""),
        seed=int(raw.get("seed") or 0),
        dataset_hashes=dict(raw.get("dataset_hashes") or {}),
        dataset_periods=dict(raw.get("dataset_periods") or {}),
        checks=list(raw.get("checks") or []),
        replaced=raw.get("replaced", ""),
        disclosure=raw.get("disclosure", ""),
    )


def current_id(metadata_dir: str | Path | None = None) -> str:
    """The published bundle's id, or "" when nothing has been published.

    Empty rather than an exception: a build that predates bundles is a real
    state, and a cohort measured on it records an empty bundle and is refused
    a cross-bundle join for the honest reason that nobody knows which build it
    came from.
    """
    published = read(metadata_dir)
    return published.bundle_id if published else ""


def require_same(*ids: str) -> str:
    """Refuse a join across builds. Returns the single id when they agree.

    An empty id is a dataset that does not know which build it came from, and
    that is treated as a mismatch rather than as a wildcard: joining a figure
    of unknown provenance to one of known provenance produces a figure of
    unknown provenance.
    """
    seen = [i or "" for i in ids]
    distinct = sorted(set(seen))
    if len(distinct) == 1 and distinct[0]:
        return distinct[0]
    if "" in distinct:
        raise StaleBundle(
            f"One of these figures does not record which build it came from "
            f"({distinct}). It cannot be joined to one that does: the result "
            f"would carry a provenance it does not have. Republish the book "
            f"so every dataset carries a bundle id.")
    raise StaleBundle(
        f"These figures come from different builds of the book ({distinct}). "
        f"They are not two measurements of one thing that happen to differ, "
        f"so they are not reconciled here. Refresh the investigation against "
        f"the current bundle, which creates a new version and leaves the "
        f"saved one intact.")
