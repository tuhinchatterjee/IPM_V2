"""I01-I12: the frozen original stays frozen; the lab stays in its lane."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import QUESTION, ROOT, child

MANIFEST = ROOT / "docs/model_comparison/PROTECTED_MANIFEST.json"


def test_I01_frozen_identity_is_pinned_to_the_tag():
    m = json.loads(MANIFEST.read_text())
    assert m["frozen_commit"].startswith("245c50e")
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse",
                          "cockpit-round-h-live-pass-2026-09-23^{commit}"],
                         capture_output=True, text=True)
    if out.returncode == 0:      # the tag is present in this clone
        assert out.stdout.strip() == m["frozen_commit"]


def test_I02_lab_is_not_a_linked_worktree_and_has_no_symlinks():
    wt = subprocess.run(["git", "-C", str(ROOT), "worktree", "list"],
                        capture_output=True, text=True).stdout.splitlines()
    assert len(wt) == 1
    assert not (ROOT / ".git" / "objects" / "info" / "alternates").exists()
    frozen = json.loads(MANIFEST.read_text())["frozen_commit"]
    tree = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", frozen],
                          capture_output=True, text=True).stdout
    assert not [line for line in tree.splitlines()
                if line.startswith("120000")]


def test_I04_I09_protected_manifest_matches():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pm", ROOT / "scripts/model_lab/protected_manifest.py")
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    diffs = pm.check(json.loads(MANIFEST.read_text()))
    assert diffs == [], diffs[:5]


def test_I03_J12_no_what_if_code_is_imported_by_the_lab():
    lab = list((ROOT / "backend/model_lab").rglob("*.py"))
    text = "\n".join(p.read_text() for p in lab).lower()
    for marker in ("advanced-cockpit-whatif", "what_if", "whatif"):
        assert marker not in text


def test_I06_runtime_escape_is_refused(tmp_path, monkeypatch):
    from backend.model_lab.app import _guard_runtime_dir
    with pytest.raises(RuntimeError):
        _guard_runtime_dir(ROOT / "data" / "lab")
    with pytest.raises(RuntimeError):
        _guard_runtime_dir(ROOT / "backend" / "x")
    monkeypatch.setenv("COCKPIT_V4_STATE_DATABASE", "postgres://x/y")
    with pytest.raises(RuntimeError):
        _guard_runtime_dir(tmp_path / "ok")


def test_I07_lab_state_is_written_only_under_its_runtime(demo):
    svc, cid, _ = demo
    root = svc.cfg.runtime_dir
    assert Path(svc.coord.store.db_path).is_relative_to(root)
    assert Path(svc.coord.store.runs_db_path).is_relative_to(root)
    exp = svc.coord.store.latest_export(cid, svc.cfg.tenant_id)
    assert Path(exp["path"]).is_relative_to(root)


def test_I08_new_launchers_are_lab_owned_and_frozen_ones_untouched():
    assert (ROOT / "launchers/START_MODEL_LAB.command").exists()
    for f in ("START_COCKPIT_V4.command", "STOP_COCKPIT_V4.command"):
        assert (ROOT / "scripts/cockpit_v4" / f).exists()
    text = (ROOT / "scripts/model_lab/start.py").read_text()
    assert "record(" in text and "pick_port" in text
    assert "kill" not in text.lower()


def test_I11_every_child_reaches_the_frozen_validators_and_executor(demo):
    """Real path: validator refusal, DuckDB execution and Finalizer
    publication all show up in the FROZEN event stream of fixture children."""
    svc, cid, ev = demo
    runs = svc.coord.runs
    rep = child(ev, "fixture-repair")
    events = [e.event_type for t in rep["turns"]
              for e in runs.events_since(t["run_id"])]
    assert "tool.validated" in events and "tool.started" in events
    assert "answer.validated" in events
    assert rep["repair"]["chains"][0]["error_code"] == "SQL_VALIDATION"
    subs = runs.submissions_for_run(rep["turns"][0]["run_id"])
    assert len(subs) == 2         # the refused one and the repaired one


def test_I12_a_changed_profile_after_freeze_blocks_the_child(tmp_path):
    from conftest import make_service
    svc = make_service(tmp_path)
    st = svc.coord.create({"question": QUESTION,
                           "profile_ids": ["fixture-reference"],
                           "comparator_id": "fixture-reference"},
                          start=False)
    import dataclasses
    p = svc.coord.profiles["fixture-reference"]
    svc.coord.profiles["fixture-reference"] = dataclasses.replace(
        p, raw=p.raw | {"display_name": "tampered"})
    svc.coord.start(st["comparison_id"])
    st = svc.coord.wait(st["comparison_id"])
    c = st["children"][0]
    assert c["state"] == "BLOCKED" and "profile changed" in c["reason"]
