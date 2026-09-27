"""The 64K long-run diagnostic declares the context Ollama actually serves.

The first long-run run failed with INPUT_CONTEXT_LIMIT because its profile
declared no context, so the lab told the frozen engine 32,768 while Ollama
served 65,536. These tests prove the fix is a DECLARATION, not a bypass: the
frozen fits() check is untouched, the older profiles still declare what they
declared, and a request that genuinely exceeds 65,536 is still refused.
Offline; no model is called.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from conftest import ROOT, child, make_service, run
from test_request_controls import _git, _wire

from backend.model_lab import registry
from backend.model_lab.adapters import build_provider
from backend.model_lab.child_runtime import DEFAULT_CONTEXT_TOKENS, capability_for

NEW = "qwen3.5-4b-nothink-longrun-64k"
PARENT = "qwen3.5-4b-nothink-longrun"
OLD = ("qwen3.5-4b", "qwen3.5-4b-nothink", PARENT)
#: The commit before this change, and the frozen engine's commit.
PRE_64K = "16d1c889c2aedbfcdd38313a88b81bd777906ace"
FROZEN = "245c50e45786c6e0c866b281f9dd74da17d160b5"
LABEL = "Qwen3.5-4B no-thinking — LONG-RUN 64K DIAGNOSTIC — SLA NOT COMPARABLE"


def _analyst(context_tokens: int, text_chars: int):
    """The real frozen Analyst, with the local conservative estimate."""
    from backend.cockpit_v4.capability import Capability
    from backend.cockpit_v4.provider import Analyst

    cap = capability_for(registry.load_profiles()[NEW])
    cap = Capability(**{**cap.__dict__, "context_tokens": context_tokens})
    return Analyst(provider=object(), capability=cap, ledger=None,
                   system="", tools=[],
                   messages=[{"role": "user", "content": "x" * text_chars}])


def _chars_for(tokens: int) -> int:
    """Characters whose estimate is about `tokens` (frozen: len/2.2 + 1)."""
    return int(tokens * 2.2)


# ---- old declarations kept -------------------------------------------------

def test_old_profiles_keep_their_context_declarations():
    ps = registry.load_profiles()
    for pid in OLD:
        assert ps[pid].raw.get("context_tokens") is None, pid
        assert capability_for(ps[pid]).context_tokens == \
            DEFAULT_CONTEXT_TOKENS == 32_768, pid


def test_old_profile_files_are_byte_identical():
    for pid in OLD:
        old = _git("rev-parse", f"{PRE_64K}:profiles/{pid}.json")
        if old is None:
            pytest.skip("pre-change commit not in this checkout's history")
        assert _git("hash-object", f"profiles/{pid}.json").strip() == \
            old.strip(), pid


# ---- the new profile ------------------------------------------------------

def test_new_profile_declares_the_served_64k_context():
    p = registry.load_profiles()[NEW]
    assert p.raw["context_tokens"] == 65536
    assert capability_for(p).context_tokens == 65536
    assert p.raw["parent_profile_id"] == PARENT
    assert p.raw["diagnostic_label"] == LABEL


def test_new_profile_differs_from_its_parent_only_in_context_and_identity():
    ps = registry.load_profiles()
    new, par = ps[NEW].raw, ps[PARENT].raw
    changed = {k for k in set(new) | set(par) if new.get(k) != par.get(k)}
    assert changed == {"profile_id", "display_name", "parent_profile_id",
                       "diagnostic_label", "variant_note", "context_tokens",
                       "context_tokens_source", "runtime_context_note",
                       "recovery", "limitations"}
    for key in ("endpoint", "request_controls", "diagnostic_limits",
                "artifact", "max_output_tokens", "sla_comparable",
                "allowed_modes", "deployment_profiles"):
        assert new[key] == par[key], key
    assert _wire(build_provider(ps[NEW], env={})) == \
        _wire(build_provider(ps[PARENT], env={}))


# ---- the frozen fits() check is unchanged ---------------------------------

def test_frozen_fits_is_the_frozen_source():
    from backend.cockpit_v4.provider import Analyst

    frozen = _git("show", f"{FROZEN}:backend/cockpit_v4/provider.py")
    if frozen is None:
        pytest.skip("frozen commit not in this checkout's history")
    for fn in (Analyst.fits, Analyst.count_input):
        assert inspect.getsource(fn) in frozen, fn.__name__


# ---- no limit fabricated or bypassed --------------------------------------

def test_the_mac_failure_reproduces_at_32k_and_fits_at_64k():
    """About 40K input tokens: refused at the old 32,768 declaration (the
    saved INPUT_CONTEXT_LIMIT run), accepted at the served 65,536."""
    n = _chars_for(40_000)
    ok32, counted, method = _analyst(32_768, n).fits(reserved_output=3_072)
    ok64, _, _ = _analyst(65_536, n).fits(reserved_output=3_072)
    assert method == "local_conservative_estimate"
    assert 39_000 < counted < 41_000
    assert ok32 is False and ok64 is True


def test_a_request_genuinely_over_65536_is_refused_at_64k():
    ok, counted, _ = _analyst(65_536, _chars_for(63_000)).fits(
        reserved_output=3_072)
    assert counted + 3_072 + max(1024, int(counted * 0.02)) > 65_536
    assert ok is False
    ok, counted, _ = _analyst(65_536, _chars_for(70_000)).fits(
        reserved_output=1_024)
    assert counted > 65_536 and ok is False


@pytest.mark.parametrize("tokens", [55_000, 60_000, 61_500, 62_000, 64_000])
def test_the_boundary_is_exactly_the_frozen_formula(tokens):
    ok, counted, _ = _analyst(65_536, _chars_for(tokens)).fits(
        reserved_output=3_072)
    assert ok == (counted + 3_072 + max(1024, int(counted * 0.02))
                  <= 65_536)


@pytest.mark.parametrize("bad", [0, -1, "64k", 65536.5, True])
def test_a_fabricated_context_declaration_is_refused(tmp_path, bad):
    raw = json.loads((ROOT / "profiles" / f"{NEW}.json").read_text())
    raw["context_tokens"] = bad
    (tmp_path / "bad.json").write_text(json.dumps(raw))
    with pytest.raises(registry.RegistryError, match="context_tokens"):
        registry.load_profiles(tmp_path)


def _with_context(pid: str, ctx: int) -> registry.Profile:
    base = registry.load_profiles()["fixture-reference"]
    return registry._validate(base.raw | {"profile_id": pid,
                                          "context_tokens": ctx},
                              Path(f"{pid}.json"))


def test_the_engine_still_refuses_an_oversized_request(tmp_path):
    """Through the real frozen Worker: a declared capacity smaller than the
    assembled request ends INPUT_CONTEXT_LIMIT and sends nothing; the same
    question at 65,536 completes. Nothing in the lab skips the check."""
    small, big = _with_context("fx-4k", 4_000), _with_context("fx-64k", 65_536)
    svc = make_service(tmp_path, profiles=registry.load_profiles()
                       | {"fx-4k": small, "fx-64k": big})
    cid, ev = run(svc, ["fx-4k", "fx-64k"], comparator="")
    refused, ok = child(ev, "fx-4k"), child(ev, "fx-64k")
    assert refused["execution_state"] == "FAILED"
    assert refused["error_code"] == "INPUT_CONTEXT_LIMIT"
    assert not any(c.get("outcome") == "sent" for c in refused["calls"])
    assert refused["declared_context_tokens"] == 4_000
    assert ok["execution_state"] == "COMPLETED"
    assert ok["declared_context_tokens"] == 65_536


# ---- evidence and labels --------------------------------------------------

def test_evidence_records_the_declared_context_and_its_source():
    from backend.model_lab.evaluate import _declared_context

    ps = registry.load_profiles()
    assert _declared_context(ps[NEW].raw) == {
        "declared_context_tokens": 65_536, "context_tokens_source": "profile"}
    old = _declared_context(ps[PARENT].raw)
    assert old["declared_context_tokens"] == 32_768
    assert "lab default" in old["context_tokens_source"]


def test_preset_uses_the_new_profile_and_the_saved_opus_reference():
    presets = registry.load_presets()
    p = presets["qwen4b-longrun-64k-diagnostic"]
    assert p["profiles"] == [NEW]
    assert p["reference_comparison_id"] == "cmp-f364d8b6901a"
    assert p["execution_mode"] == "LONG_RUN_DIAGNOSTIC"
    assert p["group_wall_clock_s"] == 3600 and p["group_spend_cap_usd"] == 0
    # The first long-run preset is unchanged and still points at its profile.
    assert presets["qwen4b-longrun-diagnostic"]["profiles"] == [PARENT]
