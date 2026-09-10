"""Gates RET-001 to RET-004 — source provenance, branch discipline, isolation."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from backend.retail import guard

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ROOT / "docs" / "RETAIL_SOURCE_PROVENANCE.md"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class TestRET001SourceManifest:
    """The source manifest identifies the proven commit, or records the blocker."""

    def test_provenance_document_exists(self):
        assert PROVENANCE.exists(), "docs/RETAIL_SOURCE_PROVENANCE.md is required by RET-001"

    def test_records_a_full_source_commit(self):
        text = PROVENANCE.read_text()
        assert re.search(r"\b80e74a4e1e5552e73c532849b72329008335b09f\b", text), \
            "the base commit must be recorded in full, not abbreviated"

    def test_records_the_whatif_recovery_tag(self):
        text = PROVENANCE.read_text()
        assert "recovered-sep8-whatif" in text
        assert "0558f267b1c9d0eb3583cf329aed817d3aa0e15d" in text

    def test_records_the_unresolved_access_blocker_rather_than_guessing(self):
        text = PROVENANCE.read_text().lower()
        # The gate allows either a proven running build or a recorded blocker.
        # What it does not allow is silence.
        assert "cannot be closed from this container" in text or "running build" in text
        assert "launcher" in text, "the missing launcher evidence must be named"

    def test_base_commit_contains_the_recovery_tag(self):
        out = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor",
             "0558f267b1c9d0eb3583cf329aed817d3aa0e15d", "80e74a4e1e5552e73c532849b72329008335b09f"],
            capture_output=True)
        assert out.returncode == 0, \
            "the retail base must contain the proven What-If recovery commit"


class TestRET002BranchDiscipline:
    """Implementation commits are on the retail branch; the frozen tags are untouched."""

    RECOVERY_TAGS = {
        "recovered-sep8-whatif": "0558f267b1c9d0eb3583cf329aed817d3aa0e15d",
        "recovered-sep8-integrated": "ffad3519ee46de7af518c65ebd5e4f1d94e7760e",
        "recovered-sep8-cockpit-v2": "83b39a602eb430444f46d08aca4e595522f3b53f",
    }

    def test_on_the_retail_branch(self):
        assert _git("rev-parse", "--abbrev-ref", "HEAD") == "claude/funny-dirac-6n8f0o"

    @pytest.mark.parametrize("tag,sha", sorted(RECOVERY_TAGS.items()))
    def test_frozen_recovery_tags_have_not_moved(self, tag: str, sha: str):
        try:
            actual = _git("rev-list", "-n1", tag)
        except subprocess.CalledProcessError:
            pytest.skip(f"tag {tag} is not present in this clone")
        assert actual == sha, (
            f"{tag} points at {actual}, not {sha}. A freeze tag must never be moved."
        )

    def test_retail_work_does_not_touch_the_source_lake(self):
        """The retail build writes under data/retail, never over data/analytics."""
        from backend.retail.catalogue import DATASET_NAME
        source_lake = ROOT / "data" / "analytics" / DATASET_NAME
        assert not source_lake.exists(), (
            "the retail dataset must not be published into the source demo's lake"
        )


class TestRET003StateIsolation:
    """Seed, reset and migration refuse a target that is not the retail one."""

    def test_unmarked_directory_is_refused(self, tmp_path):
        with pytest.raises(guard.RetailTargetRefused):
            guard.require_retail_directory(tmp_path / "some_demo", what="seed")

    @pytest.mark.parametrize("path", [
        "/srv/creditprobe_5318/data", "/opt/demo-5308/analytics", "/x/WHATIF_5318/lake",
    ])
    def test_frozen_installation_paths_are_refused(self, path: str):
        with pytest.raises(guard.RetailTargetRefused, match="frozen source installation"):
            guard.require_retail_directory(Path(path), what="seed")

    @pytest.mark.parametrize("url", [
        "postgresql://h/creditprobe_demo", "postgresql://h/app_5318",
        "postgresql://h/ipm_demo", "postgresql://h/unrelated",
    ])
    def test_non_retail_databases_are_refused(self, url: str):
        with pytest.raises(guard.RetailTargetRefused):
            guard.require_retail_database(url, what="seed")

    def test_retail_database_is_accepted(self):
        assert guard.require_retail_database(
            "postgresql://h/creditprobe_retail", what="seed").endswith("retail")

    def test_marked_retail_directory_is_accepted(self, tmp_path):
        d = tmp_path / "lake"
        guard.mark(d)
        assert guard.require_retail_directory(d, what="seed") == d

    def test_shipped_paths_are_namespaced_away_from_the_source(self):
        from tests.retail.conftest import SHIPPED_ANALYTICS, SHIPPED_METADATA
        assert "retail" in SHIPPED_ANALYTICS.parts
        assert "retail" in SHIPPED_METADATA.parts

    def test_no_symlink_from_retail_state_to_a_source_path(self):
        for base in (ROOT / "data" / "retail", ROOT / "metadata" / "retail"):
            if not base.exists():
                continue
            for p in base.rglob("*"):
                assert not p.is_symlink(), f"{p} is a symlink; retail state must be its own"


class TestRET004Launcher:
    """The retail launcher starts the retail backend against the retail data."""

    LAUNCHER = ROOT / "launchers" / "retail" / "start-retail.command"
    STOPPER = ROOT / "launchers" / "retail" / "stop-retail.command"
    READY = ROOT / "scripts" / "check_retail_ready.py"

    def test_launcher_exists_and_is_executable(self):
        assert self.LAUNCHER.exists(), "RET-004 needs a retail launcher"
        assert self.LAUNCHER.stat().st_mode & 0o111, "the launcher must be executable"

    def test_launcher_uses_the_retail_ports_not_the_source_ones(self):
        text = self.LAUNCHER.read_text()
        assert "5328" in text and "8328" in text
        for forbidden in ("5318", "5308"):
            assert forbidden not in text, (
                f"the retail launcher must not mention port {forbidden}"
            )

    def test_launcher_resolves_its_own_directory(self):
        text = self.LAUNCHER.read_text()
        assert "BASH_SOURCE" in text or "dirname" in text, (
            "the launcher must resolve its own directory rather than trusting the "
            "terminal's working directory"
        )

    def test_stop_script_does_not_kill_by_broad_pattern(self):
        text = self.STOPPER.read_text()
        for forbidden in ("pkill python", "killall node", "pkill -f node", "killall python"):
            assert forbidden not in text, (
                f"'{forbidden}' could stop the frozen 5318/5308 processes"
            )

    def test_readiness_check_exists(self):
        assert self.READY.exists(), "RET-058 needs a check_retail_ready command"
