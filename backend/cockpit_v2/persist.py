"""
Writing the demo to the Parquet lake, behind the guard. Brief §3.4.

`write_lake` is idempotent: the same generated build produces the same files,
and re-running it replaces only the directories it owns. It calls
`guard.check_targets()` first and every time, so there is no route from a
caller to the filesystem that skips the check.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from backend.cockpit_v2 import DATA_VERSION
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import catalogue as catalogue_mod
from backend.cockpit_v2 import guard
from backend.cockpit_v2.generate import Build

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "cockpit_v2_manifest.json"


def _write(frame: pd.DataFrame, directory: Path) -> int:
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(directory / "part-0.parquet", index=False)
    return len(frame)


def write_lake(build: Build, *, require_flag: bool = True) -> dict[str, Any]:
    """Write every frame, register the catalogue, and record the manifest."""
    from backend.config import settings

    targets = guard.check_targets(require_flag=require_flag)
    root = Path(settings.analytics_dir)
    written: dict[str, int] = {}

    for label, frame in build.per_quarter.items():
        written[cal.dataset_name(label)] = _write(
            frame, root / cal.dataset_name(label))
    for name, frame in build.frames.items():
        if frame.empty:
            logger.info("Cockpit V2: %s is empty and was not written", name)
            continue
        written[name] = _write(frame, root / name)

    registration = catalogue_mod.merge_into_catalogue(
        per_quarter=build.per_quarter, frames=build.frames)

    manifest = {**build.manifest, "written_rows": written,
                "analytics_dir": str(root), "registration": registration,
                "guard": targets.to_dict()}
    manifest_path = Path(settings.metadata_dir) / MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    from backend.data_access.catalog import reload_catalog
    reload_catalog()

    return {**manifest, "manifest_path": str(manifest_path),
            "data_version": DATA_VERSION}


def read_manifest() -> dict[str, Any]:
    """The manifest of the demo currently in the lake, or an empty dict."""
    from backend.config import settings

    path = Path(settings.metadata_dir) / MANIFEST_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt manifest is not a crash
        logger.warning("The Cockpit V2 manifest could not be read")
        return {}


__all__ = ["MANIFEST_FILENAME", "read_manifest", "write_lake"]
