"""
REAL PROCESS. No model.

The launcher's one job beyond starting V4 is never touching anything else.
These tests use real processes and real ports, because that is the only way
to check a guard whose failure mode is "it stopped the wrong thing".
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.cockpit_v4._common import (Owned, pick_port, port_free,
                                        process_command, process_cwd,
                                        process_start_time, record, records,
                                        still_ours)


def test_a_busy_port_is_reported_and_never_freed():
    """V4-AT-004, V4-AT-098. The occupant survives, and an alternative is chosen."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        busy = holder.getsockname()[1]

        assert port_free(busy) is False
        chosen, notes = pick_port(busy)
        assert chosen != busy
        assert chosen > busy
        assert any("NOT stopped" in note for note in notes)

        # The holder is still listening. Nothing freed the port.
        assert port_free(busy) is False


def test_a_reused_pid_is_refused(tmp_path):
    """V4-AT-005. A pid whose process V4 did not start is left alone."""
    other = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(30)"],
                             start_new_session=True)
    try:
        time.sleep(0.3)
        # A record that CLAIMS this pid but describes a different process.
        stale = Owned(name="api", pid=other.pid,
                      started_at=time.time() - 3600,
                      command="uvicorn backend.cockpit_v4.app:create_app",
                      cwd=str(Path.cwd()), port=8414)
        mine, why = still_ours(stale)
        assert mine is False
        assert "Refusing to stop it" in why
    finally:
        other.terminate()
        other.wait(timeout=10)


def test_a_process_in_another_directory_is_refused(tmp_path):
    """V4-AT-005. The V4 worktree is part of the identity."""
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=str(tmp_path), start_new_session=True)
    try:
        time.sleep(0.3)
        stale = Owned(name="api", pid=other.pid,
                      started_at=process_start_time(other.pid),
                      command=process_command(other.pid),
                      cwd="/some/other/v4/worktree", port=8414)
        mine, why = still_ours(stale)
        # Either the command or the cwd check refuses it; both are correct.
        assert mine is False
    finally:
        other.terminate()
        other.wait(timeout=10)


def test_a_dead_pid_is_reported_not_stopped(tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=10)
    stale = Owned(name="api", pid=dead.pid, started_at=time.time(),
                  command="x", cwd=str(tmp_path))
    mine, why = still_ours(stale)
    assert mine is False
    assert why == "not running"


def test_records_round_trip(tmp_path):
    owned = Owned(name="api", pid=1234, started_at=1.0, command="c",
                  cwd=str(tmp_path), port=8414, url="http://127.0.0.1:8414")
    record(tmp_path, owned)
    loaded = records(tmp_path)
    assert len(loaded) == 1 and loaded[0].pid == 1234


def test_the_stop_script_contains_no_broad_kill():
    """V4-AT-014 (launcher half). No pkill, no lsof-derived pid, no tail -1."""
    import ast
    import io
    import tokenize

    source = Path("scripts/cockpit_v4/stop.py").read_text(encoding="utf-8")
    # Strip comments and docstrings: the module docstring NAMES the things it
    # refuses to do, and a test that cannot tell an explanation from a call
    # would fail on good documentation.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                source = source.replace(doc, "")
    stripped = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            stripped.append(token.string)
    code = "".join(stripped)

    for forbidden in ("pkill", "killall", "lsof -ti", "tail -1",
                      "kill -9 $("):
        assert forbidden not in code, (
            f"{forbidden!r} in the stop script would risk another instance")


def test_the_seed_script_refuses_the_v3_namespace():
    """V4-AT-003, V4-AT-006. A published release is never overwritten by accident."""
    out = subprocess.run(
        [sys.executable, "scripts/cockpit_v4/seed_release.py",
         "--namespace", "cockpit_agentic_v3", "--release", "x"],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 2
    assert "Refusing to seed into the V3 namespace" in out.stderr


def test_seeding_an_existing_release_does_not_overwrite_it(tmp_path):
    """V4-AT-006. Immutability, checked rather than assumed."""
    out = subprocess.run(
        [sys.executable, "scripts/cockpit_v4/seed_release.py",
         "--release", os.environ.get("COCKPIT_V4_TEST_RELEASE",
                                     "v4-uat-20q-v1")],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4"})
    assert out.returncode == 0
    assert "already exists" in out.stdout
    assert "immutable" in out.stdout
