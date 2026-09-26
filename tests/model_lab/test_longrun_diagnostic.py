"""Long-run hardware/quality diagnostic: relaxed frozen time limits, applied
only inside an isolated child process.

Offline only. A FIXTURE profile carrying `diagnostic_limits` runs through the
real subprocess and the real frozen engine, so these tests prove where the
override applies and where it does not; they say nothing about how long any
real model takes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT, child, make_service, run
from test_request_controls import _git, _wire

from backend.model_lab import diagnostic_limits as dl
from backend.model_lab import registry
from backend.model_lab.adapters import build_provider

LONGRUN = "qwen3.5-4b-nothink-longrun"
NOTHINK = "qwen3.5-4b-nothink"
#: The commit that introduced qwen3.5-4b-nothink (before this change).
PRE_LONGRUN = "0a09d3395f910582c7d2c6aecb221168d06a9b96"
LIMITS = {"deadline_seconds": 3600, "action_call_seconds": 900,
          "answer_call_seconds": 900}
DIAG = "LONG_RUN_DIAGNOSTIC"


def _fixture_diag(pid: str = "fixture-longrun") -> registry.Profile:
    base = registry.load_profiles()["fixture-reference"]
    raw = base.raw | {"profile_id": pid, "display_name": "Fixture long-run",
                      "diagnostic_limits": LIMITS, "sla_comparable": False,
                      "diagnostic_label": dl.LABEL}
    return registry._validate(raw, Path(f"{pid}.json"))


def _frozen_constants():
    from backend.cockpit_v4 import config as config_mod
    return {n: getattr(config_mod, n) for n in dl.FAMILIES}


@pytest.fixture(scope="module")
def mixed(tmp_path_factory):
    """One ordinary child and one diagnostic child in the same group."""
    before = _frozen_constants()
    svc = make_service(tmp_path_factory.mktemp("lab"),
                       profiles=registry.load_profiles()
                       | {"fixture-longrun": _fixture_diag()})
    cid, ev = run(svc, ["fixture-reference", "fixture-longrun"],
                  execution_mode=DIAG)
    return svc, cid, ev, before


def _action_timeouts(k):
    return [c["call_timeout_seconds"] for c in k["calls"]
            if c.get("phase") != "answer"]


# ---- 1. ordinary profiles keep the frozen limits --------------------------

def test_1_ordinary_child_keeps_the_frozen_limits(mixed):
    _, _, ev, before = mixed
    k = child(ev, "fixture-reference")
    assert k["execution_state"] == "COMPLETED"
    assert k["diagnostic"] is None and k["sla_comparable"] is True
    assert [a["message"] for a in k["frozen_allowances"]] == \
        ["Allowance: 180s, $1.50."]
    assert _action_timeouts(k) and max(_action_timeouts(k)) <= 30.0
    assert max(c["call_timeout_seconds"] for c in k["calls"]) <= 55.0
    # The lab server's frozen values were never replaced, not even briefly
    # (identity, not equality).
    after = _frozen_constants()
    assert all(after[n] is before[n] for n in dl.FAMILIES)


def test_1_the_real_profiles_carry_no_override():
    for p in registry.load_profiles().values():
        if p.profile_id != LONGRUN:
            assert "diagnostic_limits" not in p.raw, p.profile_id
            assert p.raw.get("sla_comparable") is not False, p.profile_id


# ---- 2. only the diagnostic child is extended -----------------------------

def test_2_only_the_diagnostic_child_gets_extended_limits(mixed):
    _, _, ev, _ = mixed
    k = child(ev, "fixture-longrun")
    assert k["execution_state"] == "COMPLETED"
    assert [a["message"] for a in k["frozen_allowances"]] == \
        ["Allowance: 3600s, $1.50."]
    assert all(30.0 < t <= 900.0 for t in _action_timeouts(k))
    d = k["diagnostic"]
    assert d["label"] == dl.LABEL and d["sla_comparable"] is False
    assert k["sla_comparable"] is False
    frozen = d["frozen_policy"]["ANALYTICAL_STANDARD_LIMITS"]
    eff = d["effective_policy"]["ANALYTICAL_STANDARD_LIMITS"]
    assert frozen == {"deadline_seconds": 180.0, "action_call_seconds": 30.0,
                      "answer_call_seconds": 55.0}
    assert eff == {k2: float(v) for k2, v in LIMITS.items()}
    # Applied in another process, restored there, never in this one.
    assert d["isolated_process"] is True
    assert d["child_pid"] != os.getpid() and d["parent_pid"] == os.getpid()
    assert d["restored_policy"] == d["frozen_policy"]
    assert d["parent_policy_after"] == d["frozen_policy"]
    assert d["process_returncode"] == 0 and d["killed_at_cap"] is False
    assert "LONG_RUN_HARDWARE_QUALITY_DIAGNOSTIC" in ev["comparison_class"]
    assert "SLA_NOT_COMPARABLE" in ev["comparison_class"]
    assert "SEMANTIC_BASELINE_COMPARISON" not in ev["comparison_class"]


def test_2_same_tools_and_checks_as_the_ordinary_child(mixed):
    """Only time changed: same tool sequence and same verified outcome."""
    _, _, ev, _ = mixed
    a, b = child(ev, "fixture-reference"), child(ev, "fixture-longrun")
    assert [c["tool_names"] for c in a["calls"]] == \
        [c["tool_names"] for c in b["calls"]]
    assert [(c["check_id"], c["outcome"]) for c in a["checks"]] == \
        [(c["check_id"], c["outcome"]) for c in b["checks"]]


def test_2_export_carries_the_label_and_both_policies(mixed):
    from backend.model_lab import export
    _, _, ev, _ = mixed
    t = export.rows(ev)
    row = next(r for r in t["summary"] if r["profile_id"] == "fixture-longrun")
    assert row["diagnostic_label"] == dl.LABEL
    assert row["sla_comparable"] is False
    assert json.loads(row["frozen_timeout_policy"])[
        "ANALYTICAL_STANDARD_LIMITS"]["action_call_seconds"] == 30.0
    assert json.loads(row["effective_timeout_policy"])[
        "ANALYTICAL_STANDARD_LIMITS"]["action_call_seconds"] == 900.0
    plain = next(r for r in t["summary"]
                 if r["profile_id"] == "fixture-reference")
    assert plain["diagnostic_label"] == "" and plain["sla_comparable"] is True
    assert all(c["call_timeout_seconds"] is not None for c in t["calls"])


# ---- 3. the override cannot leak ------------------------------------------

def test_3_a_later_ordinary_run_is_unaffected(mixed):
    svc, _, _, before = mixed
    cid, ev = run(svc, ["fixture-reference"])
    k = child(ev, "fixture-reference")
    assert [a["message"] for a in k["frozen_allowances"]] == \
        ["Allowance: 180s, $1.50."]
    assert max(_action_timeouts(k)) <= 30.0
    assert all(_frozen_constants()[n] is before[n] for n in dl.FAMILIES)


def test_3_the_override_refuses_to_run_in_this_process():
    with pytest.raises(dl.DiagnosticLimitsError):
        with dl.applied(LIMITS):
            pass
    with pytest.raises(dl.DiagnosticLimitsError):
        dl.arm()                               # no MODEL_LAB_DIAGNOSTIC_CHILD
    assert dl.frozen_policy()["ANALYTICAL_STANDARD_LIMITS"][
        "action_call_seconds"] == 30.0


def test_3_the_override_is_restored_even_on_an_exception():
    code = (
        "import json\n"
        "from backend.model_lab import diagnostic_limits as dl\n"
        "dl.arm()\n"
        "before = dl.frozen_policy()\n"
        "try:\n"
        "    with dl.applied({'deadline_seconds': 3600,"
        " 'action_call_seconds': 900}) as info:\n"
        "        inside = dl.frozen_policy()\n"
        "        raise RuntimeError('boom')\n"
        "except RuntimeError:\n"
        "    pass\n"
        "print(json.dumps([before, inside, dl.frozen_policy()]))\n")
    env = dict(os.environ) | {dl.ENV_FLAG: "1", "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True)
    before, inside, after = json.loads(out.stdout.strip().splitlines()[-1])
    assert inside["ANALYTICAL_STANDARD_LIMITS"]["action_call_seconds"] == 900
    assert after == before


@pytest.mark.parametrize("limits", [
    {"deadline_seconds": float("inf")}, {"deadline_seconds": 0},
    {"deadline_seconds": 7200}, {"action_call_seconds": 901},
    {"step_seconds": 60}, {},
])
def test_3_unsafe_limits_are_refused_at_load(tmp_path, limits):
    raw = json.loads((ROOT / "profiles" / f"{LONGRUN}.json").read_text())
    raw["diagnostic_limits"] = limits
    (tmp_path / "bad.json").write_text(json.dumps(raw))
    with pytest.raises(registry.RegistryError):
        registry.load_profiles(tmp_path)


@pytest.mark.parametrize("field,value", [
    ("sla_comparable", True), ("diagnostic_label", "diagnostic")])
def test_3_a_diagnostic_profile_must_be_labelled(tmp_path, field, value):
    raw = json.loads((ROOT / "profiles" / f"{LONGRUN}.json").read_text())
    raw[field] = value
    (tmp_path / "bad.json").write_text(json.dumps(raw))
    with pytest.raises(registry.RegistryError, match="sla_comparable"):
        registry.load_profiles(tmp_path)


def test_3_modes_never_mix_baseline_and_diagnostic(tmp_path):
    svc = make_service(tmp_path, profiles=registry.load_profiles()
                       | {"fixture-longrun": _fixture_diag()})
    q = "What is Stage 2 exposure by sector for the latest quarter?"
    pre = svc.coord.preflight({"question": q,
                               "profile_ids": ["fixture-longrun"]})
    assert not pre["ok"] and "LONG_RUN_DIAGNOSTIC" in " ".join(pre["errors"])
    pre = svc.coord.preflight({"question": q, "execution_mode": DIAG,
                               "profile_ids": ["fixture-reference"]})
    assert not pre["ok"]


def test_3_a_crashed_diagnostic_process_fails_the_child(tmp_path,
                                                        monkeypatch):
    svc = make_service(tmp_path, profiles=registry.load_profiles()
                       | {"fixture-longrun": _fixture_diag()})
    monkeypatch.setattr(sys, "executable", "/bin/false")
    cid, ev = run(svc, ["fixture-longrun"], comparator="",
                  execution_mode=DIAG)
    k = child(ev, "fixture-longrun")
    assert k["execution_state"] == "FAILED"
    assert "diagnostic subprocess exited" in k["reason"]


# ---- 4. frozen files unchanged --------------------------------------------

def test_4_protected_frozen_files_are_unchanged(mixed):
    out = subprocess.run(
        [sys.executable, "scripts/model_lab/protected_manifest.py",
         "--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "protected manifest OK" in out.stdout


# ---- 5. saved results are not overwritten ---------------------------------

def test_5_saved_comparisons_are_read_not_rewritten(tmp_path):
    svc = make_service(tmp_path, profiles=registry.load_profiles()
                       | {"fixture-longrun": _fixture_diag()})
    base_cid, _ = run(svc, ["fixture-reference"])
    tenant = svc.cfg.tenant_id
    hist = json.dumps(svc.coord.store.evaluation_history(base_cid, tenant),
                      sort_keys=True, default=str)
    base_events = len(svc.coord.store.events(base_cid, tenant, 0, 100000))
    cid, ev = run(svc, ["fixture-longrun"], comparator="",
                  execution_mode=DIAG, reference_comparison_id=base_cid)
    assert cid != base_cid
    assert json.dumps(svc.coord.store.evaluation_history(base_cid, tenant),
                      sort_keys=True, default=str) == hist
    assert len(svc.coord.store.events(base_cid, tenant, 0, 100000)) == \
        base_events
    ref = ev["reference_baseline"]
    assert ref["comparison_id"] == base_cid and ref["status"] == "READY"
    assert ref["read_only"] is True and "never latency" in ref["note"]
    k = child(ev, "fixture-longrun")
    assert k["opus_match"]["S1"]["display"] == "N/A"      # no own comparator
    assert k["reference_match"]["S2"]["pct"] == 100.0


def test_5_parent_profile_files_are_unchanged():
    for name in ("qwen3.5-4b.json", "qwen3.5-4b-nothink.json"):
        old = _git("rev-parse", f"{PRE_LONGRUN}:profiles/{name}")
        if old is None:
            pytest.skip("pre-change commit not in this checkout's history")
        assert _git("hash-object", f"profiles/{name}").strip() == \
            old.strip(), name


# ---- the real profile -----------------------------------------------------

DIAG_FIELDS = {"profile_id", "display_name", "parent_profile_id",
               "variant_kind", "variant_note", "sla_comparable",
               "diagnostic_label", "diagnostic_limits", "allowed_modes",
               "deployment_profiles", "recovery", "limitations",
               "status_reason", "runtime_context_tokens_expected",
               "runtime_context_note"}


def test_longrun_profile_is_the_nothink_model_with_only_time_changed():
    ps = registry.load_profiles()
    lr, nt = ps[LONGRUN].raw, ps[NOTHINK].raw
    assert lr["parent_profile_id"] == NOTHINK
    assert lr["diagnostic_limits"] == LIMITS
    assert lr["deployment_profiles"] == ["same_model_hardware_diagnostic"]
    assert lr["runtime_context_tokens_expected"] == 65536
    for key in set(nt) | set(lr):
        if key not in DIAG_FIELDS:
            assert lr.get(key) == nt.get(key), key
    # Byte-identical requests: messages, tools, forcing, budget, control.
    assert _wire(build_provider(ps[LONGRUN], env={})) == \
        _wire(build_provider(ps[NOTHINK], env={}))
