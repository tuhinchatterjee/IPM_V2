#!/usr/bin/env python3
"""One-off, reviewed curation of the requirement evidence map at P14.

Kept in the repository so the change is auditable:
* the launcher rows (LAUNCH01-12, UAT-07) cite the P14 preflight/launcher
  tests and stay PARTIAL: the Mac execution is the user's live UAT;
* REG12 (the real Mac live-provider UAT) is BLOCKED on the user's approval
  of a paid live run -- it is not run in this round, by instruction;
* each mutation gate is bound to the requirement it protects;
* the claim vocabulary drops PENDING-*: the generator prints only
  PASS / PARTIAL / BLOCKED / FAILED, computed from the final regression;
* stale draft notes are replaced by what the row now cites.
Run once; the generator then verifies every citation.
"""

import json
from pathlib import Path

P = Path("docs/guided_workspace/matrix/requirement_evidence.json")
E = json.loads(P.read_text(encoding="utf-8"))
U = "tests/cockpit_v4/test_gw_uat_preflight.py::"
L = "tests/cockpit_v4/test_launcher_safety.py::"
W = "tests/cockpit_v4/test_whatif_tenancy.py::"
MAC = ("The Mac execution is the user's live-provider UAT "
       "(docs/guided_workspace/MAC_LIVE_UAT.md), not run in this round: the "
       "container has no macOS Keychain, no Mac browser and no approved paid "
       "provider run. The logic is tested here (cited).")


def put(rid, claim, tests, gap, sources=None, note=""):
    e = E[rid]
    e["claim"] = claim
    e["tests"] = tests
    e["gap"] = gap
    e["sources"] = sources or []
    e["note"] = note


LAUNCH = {
    "LAUNCH01": [U + "test_an_old_python_is_refused",
                 W + "test_the_preflight_requires_the_declared_python"],
    "LAUNCH02": [U + "test_a_broken_pip_check_is_refused"],
    "LAUNCH03": [W + "test_the_preflight_refuses_when_the_frontend_is_not_installed",
                 W + "test_the_preflight_accepts_an_installed_frontend"],
    "LAUNCH04": [U + "test_both_books_and_the_compatibility_release_are_checked",
                 U + "test_the_pinned_clean_candidate_is_accepted",
                 U + "test_any_other_head_is_refused_with_the_exact_checkout",
                 U + "test_a_dirty_tree_is_refused",
                 U + "test_no_manifest_is_refused",
                 U + "test_seed_definitions_that_moved_are_refused"],
    "LAUNCH05": [U + "test_both_books_and_the_compatibility_release_are_checked"],
    "LAUNCH06": [U + "test_a_shell_credential_needs_the_explicit_flag",
                 U + "test_the_launcher_drops_a_shell_credential_without_the_flag",
                 U + "test_the_credential_value_is_never_printed"],
    "LAUNCH07": [U + "test_a_price_card_inside_the_checkout_is_refused",
                 U + "test_no_model_is_refused"],
    "LAUNCH08": [U + "test_a_runtime_dir_from_another_build_needs_fresh",
                 U + "test_the_same_build_reuses_its_runtime_dir",
                 U + "test_start_stop_and_status_share_one_dedicated_runtime"],
    "LAUNCH09": [L + "test_a_busy_port_is_reported_and_never_freed",
                 U + "test_start_hands_over_to_the_established_lifecycle"],
    "LAUNCH10": [W + "test_every_launcher_that_starts_a_server_waits_for_health",
                 U + "test_start_hands_over_to_the_established_lifecycle"],
    "LAUNCH11": [L + "test_the_stop_script_contains_no_broad_kill",
                 L + "test_a_reused_pid_is_refused",
                 L + "test_a_process_in_another_directory_is_refused",
                 U + "test_start_stop_and_status_share_one_dedicated_runtime"],
    "LAUNCH12": [U + "test_start_stop_and_status_share_one_dedicated_runtime"],
}
SRC = ["scripts/guided_workspace/guided_preflight.py",
       "scripts/guided_workspace/start_guided_uat.py",
       "docs/guided_workspace/MAC_LIVE_UAT.md"]
for rid, tests in LAUNCH.items():
    put(rid, "PARTIAL", tests, MAC, SRC)
E["LAUNCH05"]["sources"] = SRC + ["scripts/whatif/uat_preflight.py"]
E["LAUNCH12"]["sources"] = SRC + ["scripts/cockpit_v4/status.py"]
put("UAT-07", "PARTIAL",
    [
        U + "test_the_pinned_clean_candidate_is_accepted",
        U + "test_start_hands_over_to_the_established_lifecycle",
        W + "test_every_launcher_that_starts_a_server_waits_for_health",
        U + "test_the_launcher_turns_on_every_round_flag"],
    MAC, SRC + ["scripts/guided_workspace/START_GUIDED_WORKSPACE_UAT.command"])
put("REG12", "BLOCKED", [],
    "APPROVAL: the real Mac live-provider UAT is the user's acceptance gate "
    "and a paid provider run; it was not run in this round by instruction. "
    "The package (pinned-SHA preflight, launchers, evidence collector) is "
    "prepared and dry-run here.",
    SRC + ["scripts/guided_workspace/live_uat_evidence.py"])

GATES = {
    "SEC02": ["tenant isolation (access rule)",
              "tenant isolation (store scope)"],
    "METH16": "method selection (no silent Delta)",
    "SC-06": "scenario lineage",
    "M001": "metric formula",
    "AL-01": "breach evaluation",
    "SEC08": ["LLM Exchange sanitisation",
              "V4 persistence boundary (approved fix)"],
    "GX-10": "cohort identity",
    "MSG-03": "governance ledger",
    "MAC07": "tornado sign preservation",
    "DECOMP21": "selected scope = total book",
}
for rid, gates in GATES.items():
    gates = gates if isinstance(gates, list) else [gates]
    have = [c for c in E[rid].get("checks", [])
            if not c.startswith("mutation:")]
    E[rid]["checks"] = have + [f"mutation:{g}" for g in gates]

NOTES = {
    "REG01": "What-If suite on the candidate interpreter, final regression.",
    "REG02": "V4 backend + frontend-python suite, accepted interpreter, "
             "final regression.",
    "REG03": "V3 suite, final regression.",
    "REG04": "Frontend unit, type-check and lint of new code, final regression.",
    "REG05": "Round journeys (clean store) and the What-If candidate browser "
             "suite, MODEL MOCK, final regression.",
    "REG06": "As REG05, Retail.",
    "REG07": "Accepted browser suite with the round's flags off, final "
             "regression.",
    "REG08": "Sensitivity libraries rebuilt and compared; emulator pickles "
             "refitted and compared, final regression.",
    "REG10": "protected_baseline.py --check: every changed protected file is "
             "in PROTECTED_EXTENSION_MAP.md, final regression.",
    "REG11": "This generator: every cited test, journey, check and file "
             "exists; results bound to the final regression's SHA.",
}
for rid, note in NOTES.items():
    E[rid]["note"] = note
for rid in ("REG02", "REG03", "REG06", "REG07", "REG08"):
    E[rid]["sources"] = [s for s in E[rid].get("sources", [])
                         if s != "docs/guided_workspace/PHASE_LEDGER.md"]

left = [k for k, v in E.items() if v["claim"].startswith("PENDING")]
assert not left, left
P.write_text(json.dumps(E, indent=1, ensure_ascii=False),
             encoding="utf-8")
print("curated", len(E))
