#!/usr/bin/env python3
"""Browser mutation gates: a guard that only a browser journey can prove.

Each gate edits one frontend file back to its pre-fix behaviour, lets the
running dev server reload it, runs the journey that must catch it (up to
`--attempts` times: the defects are races), restores the file byte for byte
and records the outcome. KILLED = the journey failed on the mutated code and
passes on the restored code.

    python3 scripts/guided_workspace/browser_mutation_gates.py \\
        --ui http://127.0.0.1:5444 --api http://127.0.0.1:8444 --out OUT.json

Needs the guided-workspace UI and API already running (browser_evidence.py
--keep-up). EVIDENCE LABEL: MODEL MOCK (scripted analyst); no paid call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WS = "frontend/src/components/whatif/whatif-workspace.tsx"

#: (name, file, exact fixed text, pre-fix text, journey regex)
GATES = [
    ("the address sync never writes stale state onto a navigated entry "
     "(VAL-DEF-038)", WS,
     '''    if (pending || openingRun.current || leaving.current) return;
    // Back/Forward moves the browser's address before React's view of it:
    // in between, writing would put this page's state on the entry being
    // navigated to.
    if ((new URLSearchParams(window.location.search).get("run") ?? "") !== urlRun) return;
    if (urlRun !== (runId || "") && urlRun !== wroteRun.current) return;
    const f = filters.length ? JSON.stringify(filters) : "";
    const want = {
      domain,
      f: f.length <= 1200 ? f : null,
      cohort: cohort?.object_id ?? null,
      scenario: scenario?.object_id ?? null,
      run: runId || null,
    };
    // Only a change of this page's state is written: an unchanged state has
    // nothing to say, and writing it again could land on an entry Back or
    // Forward just moved to.
    const key = JSON.stringify(want);
    if (key === wroteState.current) return;
    wroteState.current = key;
    wroteRun.current = runId || "";
    address.replace(want);
''',
     # The pre-fix sync (candidate K): it wrote the page's state whenever
     # its inputs changed, whatever the address said.
     '''    if (pending || leaving.current) return;
    const f = filters.length ? JSON.stringify(filters) : "";
    address.replace({
      domain,
      f: f.length <= 1200 ? f : null,
      cohort: cohort?.object_id ?? null,
      scenario: scenario?.object_id ?? null,
      run: runId || null,
    });
''', "^GW-CTL-HISTORY$"),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def journey(ui: str, api: str, only: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GW_UI_URL": ui, "GW_API_URL": api,
               "GW_SHOTS": f"{tmp}/shots", "GW_EVIDENCE": f"{tmp}/ev.json",
               "GW_ONLY": only}
        r = subprocess.run(["node", "tests/guided_workspace/browser/gw.browser.mjs"],
                           cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=1800)
        tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-6:]
        passed = "1/1 journeys passed" in r.stdout
        return passed, " | ".join(t.strip()[:300] for t in tail)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ui", required=True)
    p.add_argument("--api", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--attempts", type=int, default=3)
    args = p.parse_args()
    results = []
    for name, rel, fixed, prefix, only in GATES:
        path = ROOT / rel
        original = path.read_bytes()
        before = sha(path)
        text = original.decode("utf-8")
        assert text.count(fixed) == 1, f"{name}: fixed text not found once"
        clean_ok, clean_tail = journey(args.ui, args.api, only)
        mutated_runs = []
        try:
            path.write_text(text.replace(fixed, prefix), encoding="utf-8")
            time.sleep(8)  # the dev server recompiles the page
            for _ in range(args.attempts):
                ok, tail = journey(args.ui, args.api, only)
                mutated_runs.append({"passed": ok, "tail": tail})
                if not ok:
                    break
        finally:
            path.write_bytes(original)
            time.sleep(8)
        restored = sha(path) == before
        after_ok, after_tail = journey(args.ui, args.api, only)
        killed = clean_ok and after_ok and any(not m["passed"]
                                               for m in mutated_runs)
        results.append({"gate": name, "file": rel, "journey": only,
                        "clean_run": {"passed": clean_ok, "tail": clean_tail},
                        "mutated_runs": mutated_runs,
                        "restored": restored,
                        "restored_run": {"passed": after_ok,
                                         "tail": after_tail},
                        "result": "KILLED" if killed and restored else
                        "SURVIVED" if clean_ok and after_ok else "ERROR"})
        print(f"{results[-1]['result']:10} {name}")
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "gates": results,
           "all_killed": all(r["result"] == "KILLED" for r in results)}
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"all_killed": out["all_killed"], "gates": len(results)}))
    return 0 if out["all_killed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
