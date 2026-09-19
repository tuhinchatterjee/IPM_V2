"""Fixtures for the retail Cockpit integration's own tests.

Deliberately not `tests/cockpit_v4/conftest.py`: that one is part of the
ported suite and binds every fixture to the legacy `v4-saudi-20q-v1` release,
which this deployment does not publish. Nothing here touches that release.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def runtime_dir(tmp_path, monkeypatch) -> Path:
    """A V4 runtime directory of this test's own."""
    directory = tmp_path / "cockpit_v4"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COCKPIT_V4_RUNTIME_DIR", str(directory))
    monkeypatch.delenv("COCKPIT_V4_SQL_MEMORY_LIMIT", raising=False)
    monkeypatch.delenv("COCKPIT_V4_SQL_TEMP_DIR", raising=False)
    return directory


@pytest.fixture()
def published_release() -> str:
    """The projected release, or skip: it is 400 MB and is not committed."""
    from backend.cockpit_v4 import domains as dom
    from backend.cockpit_v4 import lake

    release_id = dom.DEFAULT_RELEASES[dom.RETAIL]
    if not lake.exists(release_id):
        pytest.skip(
            f"{release_id} is not published in this runtime. Publish it with "
            f"scripts/retail_cockpit/publish_release.py")
    return release_id


@pytest.fixture()
def source_commit() -> str:
    """The frozen source, or skip when the ref has not been fetched."""
    import subprocess

    ref = "19dc143c433eff190de7d304e53b7e941c96735b"
    done = subprocess.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"],
                          cwd=str(ROOT), capture_output=True)
    if done.returncode != 0:
        pytest.skip("the frozen source commit is not in this clone")
    return ref


@pytest.fixture(autouse=True)
def _no_inherited_session_settings(monkeypatch, request):
    """A test must not read the developer's own environment by accident."""
    if "runtime_dir" in request.fixturenames:
        return
    for name in ("COCKPIT_V4_SQL_MEMORY_LIMIT", "COCKPIT_V4_SQL_TEMP_DIR"):
        if name in os.environ:
            monkeypatch.delenv(name, raising=False)
