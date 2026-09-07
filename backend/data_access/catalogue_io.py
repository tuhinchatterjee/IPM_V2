"""
Writing the governed catalogue without destroying somebody else's half of it.

Two generators write this installation's analytical layer — the Saudi credit
book and the Corporate IFRS 9 book — and both register their datasets in
`metadata/catalog.json`. One of them merged into what was already there; the
other serialised its own list over the top. So whichever ran LAST decided what
the catalogue contained, and running them in the wrong order silently
unregistered a whole book. The symptom arrived far away and much later, as
`corporate_borrower_360 is not a governed dataset`, or as a DuckDB binder
error naming a column the catalogue promised and the Parquet did not have.

This module is the one way the catalogue is written:

  `merge`      replaces exactly the entries a generator owns and leaves every
               other entry alone, so build ORDER stops being a correctness
               question;
  `reconcile`  compares the catalogue against the Parquet actually on disk and
               removes what is no longer there, so a dataset that has been
               deleted or renamed does not linger as a promise nothing can
               keep.

Between them a rebuild is idempotent: run either generator twice, or both in
either order, and the catalogue that results is the same one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOGUE_FILE = "catalog.json"


def path_for(metadata_dir: Path | str) -> Path:
    return Path(metadata_dir) / CATALOGUE_FILE


def read(metadata_dir: Path | str) -> dict[str, Any]:
    """The catalogue as it stands, or an empty one."""
    target = path_for(metadata_dir)
    if not target.exists():
        return {"version": "1.0.0", "datasets": [], "relationships": []}
    try:
        body = json.loads(target.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "1.0.0", "datasets": [], "relationships": []}
    body.setdefault("datasets", [])
    body.setdefault("relationships", [])
    return body


def merge(metadata_dir: Path | str, *,
          datasets: list[dict[str, Any]],
          relationships: list[dict[str, Any]] | None = None,
          extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write these datasets into the catalogue, leaving the rest of it alone.

    An entry is replaced when its `name` matches one being written. Nothing
    else is touched — not another generator's datasets, not their
    relationships, not any top-level key this generator does not own.
    """
    catalogue = read(metadata_dir)
    owned = {str(d.get("name")) for d in datasets}

    kept = [d for d in catalogue["datasets"] if str(d.get("name")) not in owned]
    catalogue["datasets"] = kept + list(datasets)

    if relationships is not None:
        others = [r for r in catalogue["relationships"]
                  if str(r.get("from_dataset")) not in owned]
        catalogue["relationships"] = others + list(relationships)

    for key, value in (extra or {}).items():
        catalogue[key] = value

    target = path_for(metadata_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Sorted so two runs that register the same datasets produce byte-identical
    # files, which is what makes "rebuild twice, get the same result" checkable
    # rather than merely likely.
    catalogue["datasets"] = sorted(catalogue["datasets"],
                                   key=lambda d: str(d.get("name")))
    target.write_text(json.dumps(catalogue, indent=2, sort_keys=True),
                      encoding="utf-8")
    return catalogue


def reconcile(metadata_dir: Path | str, analytics_dir: Path | str, *,
              curated_dir: Path | str | None = None,
              apply: bool = True) -> dict[str, Any]:
    """Drop catalogue entries whose data is no longer on disk.

    A catalogue entry is a promise that a dataset exists and carries certain
    fields. When the Parquet behind it has been deleted or rebuilt under
    another name the promise cannot be kept, and every reader that trusts the
    catalogue — a query planner naming columns, a relationship graph, a
    schema check — fails somewhere else entirely.

    Returns what it found whether or not it changed anything, so a build can
    report the drift and a test can assert there is none.
    """
    catalogue = read(metadata_dir)
    roots = [Path(analytics_dir)]
    if curated_dir:
        roots.append(Path(curated_dir))

    def present(name: str) -> bool:
        for root in roots:
            directory = root / name
            if directory.is_dir() and any(directory.rglob("*.parquet")):
                return True
            if (root / f"{name}.parquet").exists():
                return True
        return False

    kept, dropped = [], []
    for entry in catalogue["datasets"]:
        name = str(entry.get("name"))
        (kept if present(name) else dropped).append(entry)

    orphaned = [str(d.get("name")) for d in dropped]
    if apply and orphaned:
        catalogue["datasets"] = kept
        names = set(orphaned)
        catalogue["relationships"] = [
            r for r in catalogue["relationships"]
            if str(r.get("from_dataset")) not in names
            and str(r.get("to_dataset")) not in names]
        path_for(metadata_dir).write_text(
            json.dumps(catalogue, indent=2, sort_keys=True), encoding="utf-8")

    on_disk = set()
    for root in roots:
        if root.is_dir():
            for child in root.iterdir():
                if child.is_dir() and any(child.rglob("*.parquet")):
                    on_disk.add(child.name)
                elif child.suffix == ".parquet":
                    on_disk.add(child.stem)

    catalogued = {str(d.get("name")) for d in catalogue["datasets"]}
    return {
        "catalogued": len(catalogued),
        "on_disk": len(on_disk),
        "orphaned": sorted(orphaned),
        "unregistered": sorted(on_disk - catalogued),
        "removed": bool(apply and orphaned),
        "healthy": not orphaned,
    }


__all__ = ["CATALOGUE_FILE", "merge", "path_for", "read", "reconcile"]
