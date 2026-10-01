#!/usr/bin/env python3
"""
P13 mutation gates: break each critical gate on purpose and prove a NAMED
test fails.

For every gate: apply one source mutation (an exact, unique string
replacement), run the named tests, require at least one of them to FAIL,
then restore the file byte-for-byte and verify the restore. A mutation that
does not apply (the source moved) or that every named test survives is a
failure of this script. Nothing is committed; the working tree is checked
clean of mutations at the end.

    python3 scripts/guided_workspace/mutation_gates.py \\
        --out docs/guided_workspace/evidence/regression/mutation_gates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = os.environ.get("GW_PYTHON", "/home/user/.venv312/bin/python")

#: (gate, file, find, replace, named tests)
GATES: list[tuple[str, str, str, str, list[str]]] = [
    ("tenant isolation", "backend/workspace/objects.py",
     'def can_read(obj: dict[str, Any], who: Principal) -> bool:\n'
     '    if obj["tenant_id"] != who.tenant:\n        return False\n',
     'def can_read(obj: dict[str, Any], who: Principal) -> bool:\n'
     '    if False:\n        return False\n',
     ["tests/cockpit_v4/test_gw_objects.py::"
      "test_private_objects_are_invisible_to_colleagues_and_other_tenants",
      "tests/cockpit_v4/test_gw_whatif.py::"
      "test_another_tenants_cohort_cannot_be_named"]),
    ("method selection (no silent Delta)", "backend/workspace/runs.py",
     '    if not wanted:\n        state, why = METHOD_SELECTION, '
     '"no method chosen: nothing runs"',
     '    if not wanted:\n        wanted = [sp.DELTA]\n    if False:\n'
     '        state, why = METHOD_SELECTION, "no method chosen: nothing runs"',
     ["tests/cockpit_v4/test_gw_runs.py::"
      "test_uat01_workspace_confirmed_with_no_method_stops_at_method_selection"
      ]),
    ("scenario lineage", "backend/workspace/runs.py",
     '    chain = [*pb.get("chain", []), _link(parent)]',
     '    chain = [_link(parent)]',
     ["tests/cockpit_v4/test_gw_runs.py::"
      "test_branches_a_b_ab_abc_persist_their_lineage"]),
    ("metric formula", "backend/workspace/metric_catalog.py",
     'ECL = "SUM(ecl_sar_mn)"', 'ECL = "SUM(ecl_sar_mn) * 1.01"',
     ["tests/cockpit_v4/test_gw_metrics.py::"
      "test_book_formulas_reconcile_to_a_python_recomputation"]),
    ("breach evaluation", "backend/workspace/lenses.py",
     '    if op == "gt":\n        return now > th',
     '    if op == "gt":\n        return now >= th',
     ["tests/cockpit_v4/test_gw_monitoring.py::"
      "test_threshold_comparisons_are_exact"]),
    ("LLM Exchange sanitisation", "backend/llm/exchange.py",
     '        if pattern.search(out):\n            out = pattern.sub(REDACTED, out)',
     '        if False:\n            out = pattern.sub(REDACTED, out)',
     ["tests/cockpit_v4/test_gw_llm_exchange.py::"
      "test_no_credential_reaches_the_store",
      "tests/cockpit_v4/test_gw_secret_leak.py::"
      "test_no_canary_reaches_any_store_file"]),
    ("cohort identity", "backend/workspace/cohorts.py",
     '    if expected_hash and frozen.ref.membership_hash != expected_hash:',
     '    if False:',
     ["tests/cockpit_v4/test_gw_whatif.py::"
      "test_adoption_refuses_a_moved_membership"]),
    ("V4 persistence boundary (approved fix)", "backend/cockpit_v4/run_store.py",
     '    if not sql.lstrip()[:7].upper().startswith(_WRITES):',
     '    if True:',
     ["tests/cockpit_v4/test_gw_v4_secret_persistence.py::"
      "test_no_secret_bytes_in_the_database_wal_or_shm"]),
    ("governance ledger", "backend/workspace/store.py",
     '                self._append(tenant_id, kind, record_id, row_hash(stored))\n',
     '                pass\n',
     ["tests/cockpit_v4/test_gw_trace.py::"
      "test_every_governed_write_is_chained_and_verifies"]),
    ("tornado sign preservation", "backend/workspace/macro_sensitivity.py",
     '            up_pp = float(d["value"])',
     '            up_pp = abs(float(d["value"]))',
     ["tests/cockpit_v4/test_gw_macro_tornado.py::"
      "test_signs_are_preserved_as_fitted"]),
    ("selected scope = total book", "backend/workspace/runs.py",
     '            or frozen.ref.entity_count == done.book_rows))',
     '            or False))',
     ["tests/cockpit_v4/test_gw_runs.py::"
      "test_decomp21_selected_scope_equal_to_the_book_is_one_population"]),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests(tests: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [PY, "-m", "pytest", *tests, "-o", "addopts=", "-q",
         "-p", "no:cacheprovider", "-x"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4"})
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    return proc.returncode, tail


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    results, ok = [], True
    for gate, rel, find, replace, tests in GATES:
        path = ROOT / rel
        original = path.read_bytes()
        before = sha(path)
        text = original.decode("utf-8")
        record = {"gate": gate, "file": rel, "named_tests": tests}
        if text.count(find) != 1:
            record.update(result="MUTATION_DID_NOT_APPLY",
                          detail=f"found {text.count(find)} times")
            results.append(record)
            ok = False
            continue
        # Baseline: the named tests pass on the clean tree.
        rc0, tail0 = run_tests(tests)
        try:
            path.write_text(text.replace(find, replace), encoding="utf-8")
            rc, tail = run_tests(tests)
        finally:
            path.write_bytes(original)
        restored = sha(path) == before
        killed = rc0 == 0 and rc != 0
        record.update(clean_run=tail0, mutated_run=tail, restored=restored,
                      result="KILLED" if killed and restored else
                      "SURVIVED" if rc == 0 else
                      "BASELINE_FAILED" if rc0 != 0 else "NOT_RESTORED")
        ok = ok and record["result"] == "KILLED"
        results.append(record)
        print(f"{record['result']:<10} {gate}: clean [{tail0}] "
              f"mutated [{tail}]")
    dirty = subprocess.run(["git", "diff", "--stat", "--", *{g[1] for g in
                                                             GATES}],
                           cwd=ROOT, capture_output=True, text=True).stdout
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "gates": results, "all_killed": ok,
           "tree_clean_of_mutations": dirty.strip() == ""}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"all_killed": ok, "gates": len(results),
                      "tree_clean_of_mutations": out[
                          "tree_clean_of_mutations"]}))
    return 0 if ok and out["tree_clean_of_mutations"] else 1


if __name__ == "__main__":
    sys.exit(main())
