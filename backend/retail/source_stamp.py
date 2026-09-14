"""
Which book a derived domain was built from, remembered.

The defect this exists for
--------------------------
Every derived build is incremental: it writes the months it is missing and
skips the ones already on disk. That is right while the book underneath is the
same book, and it saves a great deal of time.

Regenerating the book breaks the assumption without breaking the appearance.
The periods have the same names — `reporting_month=2026-08` is still
`reporting_month=2026-08` — so every marker file the builder looks for is
still there, and it skips all of them. The screens then serve a scoring
domain, an early-warning panel and three governed views computed from a book
that no longer exists, reconciled against totals they no longer match. A
bootstrap run after a regeneration reported "25 already present" and finished
successfully.

Nothing in the file names can catch this, because nothing in the file names
changed. What changed is the manifest hash of the book, which the generator
already computes and writes. So each derived domain records the hash it was
built from, and a build against a different hash is a rebuild whatever the
markers say.

This is deliberately dumb: one file per domain, holding one string. A derived
domain either knows which book it came from or it does not, and if the stamp
is missing — an installation built before this existed — the build proceeds as
it always did rather than forcing a rebuild nobody asked for.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Where the generator records what it built.
MANIFEST = "retail_dataset_manifest.json"


def book_hash(metadata_dir: str | Path | None = None) -> str:
    """The manifest hash of the published book, or "" if it cannot be read."""
    from backend.config import settings

    root = Path(metadata_dir or settings.metadata_dir)
    try:
        held = json.loads((root / MANIFEST).read_text())
    except Exception:  # noqa: BLE001 - an unstamped installation still builds
        return ""
    return str(held.get("manifest_hash") or "")


def _stamp_path(analytics_dir: str | Path, domain: str) -> Path:
    return Path(analytics_dir) / domain / "_built_from.json"


def stale(analytics_dir: str | Path, domain: str,
          metadata_dir: str | Path | None = None) -> bool:
    """True when `domain` was built from a different book than the current one.

    False when either side is unknown. An installation that has never stamped
    is not evidence of staleness, and forcing a full rebuild on the strength of
    a missing file would make the first run after an upgrade needlessly slow.
    """
    current = book_hash(metadata_dir)
    if not current:
        return False
    path = _stamp_path(analytics_dir, domain)
    try:
        held = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - never stamped, or unreadable
        return False
    was = str(held.get("manifest_hash") or "")
    return bool(was) and was != current


def record(analytics_dir: str | Path, domain: str,
           metadata_dir: str | Path | None = None) -> str:
    """Remember the book this domain has just been built from."""
    current = book_hash(metadata_dir)
    if not current:
        return ""
    path = _stamp_path(analytics_dir, domain)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"manifest_hash": current}, indent=1) + "\n")
    return current
