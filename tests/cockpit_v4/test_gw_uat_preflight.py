"""P14 Mac UAT launcher: the preflight refuses anything but the pinned
candidate, and the launcher never silently takes a shell credential.

Runs the real preflight functions with git, the runtime directory and the
Keychain replaced by test doubles; no server starts, no port is taken.

EVIDENCE LABEL: REAL CODE (launcher preflight); NO MODEL; NO PROVIDER CALL.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "guided_workspace"))

import guided_preflight as g  # noqa: E402
import start_guided_uat as s  # noqa: E402

SHA = "a" * 40


@pytest.fixture
def pinned(monkeypatch):
    def fake_git(*args):
        if args[:1] == ("rev-parse",):
            return SHA
        if args[:1] == ("status",):
            return ""
        return ""
    monkeypatch.setattr(g, "git", fake_git)
    manifest = {"expected_guided_uat_sha": SHA,
                "seed_digests": g.seed_digests(),
                "regression_status": "PASS"}
    monkeypatch.setattr(g, "manifest", lambda: manifest)
    return manifest


def test_the_pinned_clean_candidate_is_accepted(pinned):
    assert g.revision() == []
    assert g.seeds() == []


def test_any_other_head_is_refused_with_the_exact_checkout(pinned,
                                                            monkeypatch):
    pinned["expected_guided_uat_sha"] = "b" * 40
    out = g.revision()
    assert out and "is not the pinned candidate" in out[0]
    assert f"git checkout --detach {'b' * 40}" in out[0]


def test_a_dirty_tree_is_refused(pinned, monkeypatch):
    monkeypatch.setattr(g, "git", lambda *a: SHA if a[0] == "rev-parse"
                        else " M backend/workspace/runs.py")
    out = g.revision()
    assert out and "working tree has changes" in out[0]


def test_no_manifest_is_refused(monkeypatch):
    monkeypatch.setattr(g, "manifest", lambda: None)
    out = g.revision()
    assert out and "no candidate manifest" in out[0]


def test_there_is_no_any_revision_escape():
    src = (ROOT / "scripts/guided_workspace/guided_preflight.py").read_text()
    assert "--any-revision" not in src.replace(
        "There is no `--any-revision`", "")


def test_seed_definitions_that_moved_are_refused(pinned):
    pinned["seed_digests"] = {**pinned["seed_digests"], "lenses": "0" * 64}
    out = g.seeds()
    assert out and "lenses" in out[0]


def test_a_runtime_dir_from_another_build_needs_fresh(pinned, monkeypatch,
                                                      tmp_path):
    rt = tmp_path / "guided_workspace_uat"
    rt.mkdir()
    (rt / ".candidate_sha").write_text("c" * 40)
    (rt / "state").mkdir()
    monkeypatch.setattr(g, "RUNTIME_DIR", rt)
    out = g.runtime_dir(fresh=False)
    assert out and "--fresh" in out[0]
    assert (rt / "state").exists()
    assert g.runtime_dir(fresh=True) == []
    assert (rt / ".candidate_sha").read_text().strip() == SHA
    assert not (rt / "state").exists()
    moved = [p for p in tmp_path.iterdir() if p.name.startswith(
        "guided_workspace_uat.")]
    assert len(moved) == 1 and (moved[0] / "state").exists()


def test_the_same_build_reuses_its_runtime_dir(pinned, monkeypatch,
                                               tmp_path):
    rt = tmp_path / "rt"
    rt.mkdir()
    (rt / ".candidate_sha").write_text(SHA)
    (rt / "keep").write_text("x")
    monkeypatch.setattr(g, "RUNTIME_DIR", rt)
    assert g.runtime_dir(fresh=False) == []
    assert (rt / "keep").exists()


def test_a_shell_credential_needs_the_explicit_flag(monkeypatch):
    monkeypatch.setattr(g.platform, "system", lambda: "Linux")
    monkeypatch.setenv("COCKPIT_ANTHROPIC_API_KEY", "fake-not-a-key")
    out = g.credential(from_shell=False)
    assert out and "approved Keychain item" in out[0]
    assert "fake-not-a-key" not in out[0]
    assert g.credential(from_shell=True) == []


def test_the_launcher_drops_a_shell_credential_without_the_flag():
    env = {"COCKPIT_ANTHROPIC_API_KEY": "from-shell"}
    got, source = s.child_credential(dict(env), False, read=lambda: "")
    assert "COCKPIT_ANTHROPIC_API_KEY" not in got and "Keychain" in source
    got, _ = s.child_credential(dict(env), False, read=lambda: "from-kc")
    assert got["COCKPIT_ANTHROPIC_API_KEY"] == "from-kc"
    got, source = s.child_credential(dict(env), True, read=lambda: "from-kc")
    assert got["COCKPIT_ANTHROPIC_API_KEY"] == "from-shell"
    assert "SHELL" in source


def test_a_price_card_inside_the_checkout_is_refused(monkeypatch):
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "some-model")
    monkeypatch.setattr(g, "PRICE_CARD",
                        ROOT / "config/cockpit_v4/price_card.json")
    out = g.model_and_price()
    assert out and "inside the checkout" in out[0]


def test_no_model_is_refused(monkeypatch):
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    out = g.model_and_price()
    assert out and "AI_COCKPIT_REASONING_MODEL" in out[0]


def test_both_books_and_the_compatibility_release_are_checked():
    assert g.guided_books() == []
    assert g.compat_release() == []


def test_the_launcher_turns_on_every_round_flag():
    for k in ("COCKPIT_V4_WHATIF_CORPORATE", "COCKPIT_V4_WHATIF_RETAIL",
              "COCKPIT_V4_GUIDED_WORKSPACE", "NEXT_PUBLIC_GUIDED_WORKSPACE",
              "COCKPIT_V4_LLM_EXCHANGE_TRACE"):
        assert s.FLAGS[k] == "1"
    assert s.RUNTIME_DIR == g.RUNTIME_DIR
    assert json.dumps(s.FLAGS)


def test_an_old_python_is_refused(monkeypatch):
    monkeypatch.setattr(g.sys, "version_info", (3, 11, 9))
    out = g.python_and_pip()
    assert out and "3.12 or newer" in out[0]


def test_a_broken_pip_check_is_refused(monkeypatch):
    class Done:
        returncode, stdout = 1, "foo 1.0 has requirement bar>=2"
    monkeypatch.setattr(g.subprocess, "run", lambda *a, **k: Done())
    out = g.python_and_pip()
    assert out and "pip check" in out[0]


def test_start_hands_over_to_the_established_lifecycle():
    """Port stepping without killing (LAUNCH09), health before ready
    (LAUNCH10) and owned-pid stop (LAUNCH11) are start.py's, tested in
    test_launcher_safety; this launcher must reach it with its own runtime,
    the external price card and no interactive key prompt."""
    src = (ROOT / "scripts/guided_workspace/start_guided_uat.py").read_text()
    call = src[src.index('"scripts/cockpit_v4/start.py"'):]
    for arg in ('"--runtime-dir"', '"--price-card"', '"--no-prompt"',
                '"--release"', '"--api-port"', '"--ui-port"'):
        assert arg in call, arg
    assert "guided_preflight.py" in src
    assert "--skip-preflight" not in src


def test_start_stop_and_status_share_one_dedicated_runtime():
    rt = "$HOME/.creditprobe/guided_workspace_uat"
    for name in ("STOP", "STATUS"):
        text = (ROOT / f"scripts/guided_workspace/{name}_GUIDED_WORKSPACE_"
                       f"UAT.command").read_text()
        assert rt in text, name
    assert "start_guided_uat.py" in (
        ROOT / "scripts/guided_workspace/START_GUIDED_WORKSPACE_UAT.command"
    ).read_text()
    assert s.RUNTIME_DIR.parts[-2:] == (".creditprobe", "guided_workspace_uat")
    assert s.RUNTIME_DIR != Path.home() / ".creditprobe" / "cockpit_v4"


def test_the_credential_value_is_never_printed():
    for name in ("guided_preflight.py", "start_guided_uat.py",
                 "live_uat_evidence.py"):
        src = (ROOT / "scripts/guided_workspace" / name).read_text()
        assert "print(secret" not in src and "print(value" not in src
        assert "print(env[CREDENTIAL_VAR]" not in src
