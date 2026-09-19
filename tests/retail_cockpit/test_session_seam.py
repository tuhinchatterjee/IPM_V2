"""The one thing the session seam must do: nothing, until it is configured.

The seam exists because this deployment's book is twice the size the engine's
fixed limit was measured for. It was approved on the condition that it changes
nothing for anybody who does not set it, that a session's spill stays inside
the runtime directory, and that no larger limit is ever hard-coded. Those are
the three things asserted here, in that order.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.cockpit_v4 import catalog as cat
from backend.cockpit_v4 import config as config_mod

ROOT = Path(__file__).resolve().parents[2]

#: The value the engine used before the seam, and the value it must still use
#: when nothing is configured. Written here as a literal on purpose: if the
#: default ever moves, this test is the thing that says so.
UNCONFIGURED = "1536MB"


def test_the_default_is_exactly_what_it_was(runtime_dir):
    assert cat._sql_memory_limit() == UNCONFIGURED
    assert cat.DEFAULT_SQL_MEMORY_LIMIT == UNCONFIGURED


def test_a_deployment_may_state_its_own(runtime_dir, monkeypatch):
    monkeypatch.setenv(cat.SQL_MEMORY_LIMIT_VAR, "3072MB")
    assert cat._sql_memory_limit() == "3072MB"


@pytest.mark.parametrize("stated", [
    "lots", "2560", "2560 megabytes", "1536MB; DROP TABLE retail_account_month",
    "'; SET enable_external_access = true; --", "-1GB", "",
])
def test_a_limit_that_is_not_a_size_is_refused(runtime_dir, monkeypatch,
                                               stated):
    """It reaches SQL as text, so it is proved to be a size before it does.

    The empty string is in the list deliberately: it means "said nothing",
    and saying nothing gets the default rather than an empty statement.
    """
    monkeypatch.setenv(cat.SQL_MEMORY_LIMIT_VAR, stated)
    if not stated.strip():
        assert cat._sql_memory_limit() == UNCONFIGURED
        return
    with pytest.raises(config_mod.ConfigurationInvalid) as raised:
        cat._sql_memory_limit()
    assert cat.SQL_MEMORY_LIMIT_VAR in str(raised.value)


def test_spill_goes_inside_the_runtime_directory(runtime_dir):
    target = Path(cat._sql_temp_directory())
    assert target.is_dir()
    assert runtime_dir.resolve() in target.resolve().parents
    # The engine's own guard agrees, which is the point: this is not a second
    # opinion about containment, it is the same one.
    assert config_mod.check_write_target(target, config_mod.load()) == \
        target.resolve()


def test_a_temp_directory_outside_the_runtime_is_refused(runtime_dir,
                                                         monkeypatch, tmp_path):
    monkeypatch.setenv(cat.SQL_TEMP_DIR_VAR, str(tmp_path / "somewhere-else"))
    with pytest.raises(config_mod.ConfigurationInvalid):
        cat._sql_temp_directory()


def test_a_quoted_temp_directory_is_refused_rather_than_escaped(
        runtime_dir, monkeypatch):
    monkeypatch.setenv(cat.SQL_TEMP_DIR_VAR,
                       str(runtime_dir / "it's-here"))
    with pytest.raises(config_mod.ConfigurationInvalid) as raised:
        cat._sql_temp_directory()
    assert "quote" in str(raised.value)


def test_no_other_memory_figure_is_written_into_the_engine():
    """Condition 4, as a property of the file rather than a promise.

    One memory literal in `catalog.py`, and it is the default. A future edit
    that raises the engine's own figure — for every deployment, not just the
    one that asked — fails here.
    """
    source = (ROOT / "backend" / "cockpit_v4" / "catalog.py").read_text()
    literals = [line for line in source.splitlines()
                if "memory_limit" in line and "MB'" in line
                and "DEFAULT_SQL_MEMORY_LIMIT" not in line]
    assert literals == [], literals
    assert source.count(f'"{UNCONFIGURED}"') == 1


def test_the_core_diff_is_the_two_approved_files(source_commit):
    """Nothing else in the engine moved, and a third file cannot join quietly."""
    done = subprocess.run(
        ["git", "diff", "--name-only", source_commit, "--",
         "backend/cockpit_v4", "backend/cockpit_agentic"],
        cwd=str(ROOT), capture_output=True, text=True, check=True)
    changed = sorted(x for x in done.stdout.split() if x)
    assert changed == ["backend/cockpit_v4/catalog.py",
                       "backend/cockpit_v4/domains.py"], changed


@pytest.mark.slow
def test_a_built_session_reports_what_it_was_configured_with(
        runtime_dir, monkeypatch, published_release):
    """The whole point, end to end: 400 MB of parquet and about a minute."""
    monkeypatch.setenv(cat.SQL_MEMORY_LIMIT_VAR, "2048MB")
    cat.reset_sessions()
    catalog = cat.build(domain_id="retail", tenant_id="demo-tenant")
    session = cat.open_session(catalog=catalog, reuse=False)
    try:
        limit = session.connection.execute(
            "SELECT current_setting('memory_limit')").fetchone()[0]
        temp = session.connection.execute(
            "SELECT current_setting('temp_directory')").fetchone()[0]
        assert limit == "1.9 GiB", limit
        assert runtime_dir.resolve() in Path(temp).resolve().parents
    finally:
        session.close()
        cat.reset_sessions()
