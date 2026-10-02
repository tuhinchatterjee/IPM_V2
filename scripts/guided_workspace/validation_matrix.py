#!/usr/bin/env python3
"""The exhaustive-validation matrix, from MEASURED results only.

    python3 scripts/guided_workspace/validation_matrix.py \\
        --regression docs/guided_workspace/evidence/final_regression_<sha12> \\
        --inventory docs/guided_workspace/validation \\
        --perf docs/guided_workspace/validation/perf_smoke.json \\
        --mutation docs/guided_workspace/evidence/mutation_gates_val.json \\
        --out docs/guided_workspace/validation

Every validation area of the master prompt (§4–§33) is one row. Its evidence
is a list of: pytest FILES (read from the regression's junit, per file),
browser JOURNEY id prefixes (read from the regression's journeys.json),
regression STEPS (read from summary.json), inventory summaries and
mutation gates. A row is PASS when all of its evidence passed, FAILED when
any did, PARTIAL when some evidence is missing from the run, and BLOCKED
when the area depends on something this environment does not have (stated).

Writes VALIDATION_MATRIX.csv and VALIDATION_RESULTS.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: (id, area, pytest files, journey prefixes, regression steps, extra keys)
AREAS: list[tuple] = [
    ("VAL-04", "Routes and navigation (direct, refresh, deep link, params)",
     [], ["GW-BACK-", "GW-GOLD-10"], [], ["routes"]),
    ("VAL-05", "Back-button master matrix (in-app + browser Back/Forward)",
     [], ["GW-BACK-"], [], ["back"]),
    ("VAL-06", "Dead button / link / action audit",
     ["test_gw_validation_endpoints.py", "test_gw_p16_wiring.py"],
     ["GW-P16-02"], [], ["controls", "handoffs"]),
    ("VAL-07", "Guided Cockpit (Corporate and Retail journeys)",
     ["test_gw_guided.py"], ["GW-P3-", "GW-P16-", "GW-GOLD-01", "GW-GOLD-02"],
     [], []),
    ("VAL-08", "Early Warning integration",
     ["test_gw_guided.py"], ["GW-P3-04", "GW-P11-04", "GW-GOLD-06"], [], []),
    ("VAL-09", "What-If workspace (scopes, grid, selection, cohort)",
     ["test_gw_whatif.py", "test_gw_grid.py"],
     ["GW-P5-", "GW-P13-01", "GW-P13-02", "GW-BACK-06"], [], []),
    ("VAL-10", "Scenario Library — every verb",
     ["test_gw_scenarios.py", "test_gw_p16_libraries.py",
      "test_gw_validation_defects.py"],
     ["GW-P4-", "GW-BACK-07", "GW-BACK-08", "GW-BACK-09", "GW-GOLD-03"], [],
     []),
    ("VAL-11", "Method-selection governance (incl. Retail ML unavailable, "
     "no fallback)", ["test_gw_method_gate.py", "test_gw_runs.py"],
     ["GW-P6-01", "GW-P6-02", "GW-P6-04", "GW-GOLD-02"], [],
     ["gate:method selection"]),
    ("VAL-12", "Scenario stacking / baseline lineage (A, B, A+B, A+B+C, A+D)",
     ["test_gw_decomposition.py", "test_gw_runs.py"],
     ["GW-P6-03", "GW-P7-03", "GW-GOLD-03"], [], []),
    ("VAL-13", "ECL calculation and decomposition (independent oracle)",
     ["test_gw_ecl_reconciliation.py", "test_gw_decomposition.py",
      "test_gw_ml_decomposition.py"], ["GW-P6-01", "GW-P13-04"], [], []),
    ("VAL-14", "Plotly interactivity / reactivity audit",
     ["test_gw_charts.py"], ["GW-P11-", "GW-VAL-PLOTLY"], [], ["plotly"]),
    ("VAL-15", "Macro-sensitivity tornado", ["test_gw_macro_tornado.py"],
     ["GW-P13-03"], [], []),
    ("VAL-16", "Lenses (every seeded Lens)",
     ["test_gw_lenses.py", "test_gw_lens_content.py"],
     ["GW-P9-", "GW-BACK-13", "GW-BACK-14", "GW-BACK-15", "GW-GOLD-04"], [],
     []),
    ("VAL-17", "Metric Catalogue (formula and metadata)",
     ["test_gw_metrics.py", "test_gw_metric_oracles.py"], ["GW-P8-"], [], []),
    ("VAL-18", "Monitoring Centre / breach lifecycle",
     ["test_gw_monitoring.py"],
     ["GW-P10-", "GW-BACK-18", "GW-BACK-19", "GW-BACK-20", "GW-GOLD-05"], [],
     []),
    ("VAL-19", "Messages / sharing (sender and recipient)",
     ["test_gw_messages.py"],
     ["GW-P7-", "GW-BACK-11", "GW-BACK-12", "GW-BACK-13", "GW-GOLD-07"], [],
     []),
    ("VAL-20", "Persistence / reopen / restart (no model call)",
     ["test_gw_validation_defects.py", "test_gw_objects.py"],
     ["GW-GOLD-08", "GW-P1-02"], [], []),
    ("VAL-21", "Exports (incl. conversation cohort never the whole book)",
     ["test_gw_trace.py", "test_gw_grid.py"], ["GW-P12-", "GW-GOLD-06"], [],
     []),
    ("VAL-22", "Full LLM Exchange Trace", ["test_gw_llm_exchange.py"],
     ["GW-P1-", "GW-P12-03", "GW-BACK-21", "GW-BACK-22", "GW-GOLD-09"], [],
     []),
    ("VAL-23", "Security / secrets / tenant isolation",
     ["test_gw_secret_leak.py", "test_gw_v4_secret_persistence.py",
      "test_gw_objects.py"], ["GW-GOLD-09"], [],
     ["gate:tenant isolation"]),
    ("VAL-24", "Data / domain / release integrity", ["test_gw_uat_preflight.py"],
     [], ["release_fingerprints", "release_report_digests",
          "sensitivity_libraries_reproduce", "protected_baseline_round"], []),
    ("VAL-25", "Responsive / accessibility (1440, 390)", [],
     ["GW-P13-05", "GW-VAL-PLOTLY"], [], []),
    ("VAL-26", "Frontend console / network cleanliness", [],
     ["GW-BACK-", "GW-GOLD-", "GW-VAL-"], [], ["console"]),
    ("VAL-27", "Negative / error states",
     ["test_gw_validation_defects.py", "test_gw_validation_endpoints.py"], [],
     [], []),
    ("VAL-28", "Concurrency / idempotency / duplication",
     ["test_gw_validation_defects.py"], ["GW-BACK-", "GW-GOLD-06"], [],
     ["gate:binding is idempotent"]),
    ("VAL-29", "Performance smoke (p50/p95)", [], [], [], ["perf"]),
    ("VAL-33", "GOLD cross-module journeys (10)", [], ["GW-GOLD-"], [],
     ["gold10"]),
    ("REG-V4", "V4 backend + frontend-python (accepted interpreter)", [], [],
     ["v4_backend_and_frontend_py_accepted"], []),
    ("REG-WI", "What-If + Guided Workspace suite (candidate interpreter)", [],
     [], ["whatif_suite_whatif_venv"], []),
    ("REG-V3", "V3 Cockpit regression", [], [], ["v3_cockpit_agentic"], []),
    ("REG-FE", "Frontend unit, TypeScript, lint", [], [],
     ["frontend_unit", "frontend_typecheck", "frontend_lint_new_code",
      "python_lint_round_code"], []),
    ("REG-BR", "Browser suites (guided, What-If candidate, flags-OFF)", [], [],
     ["gw_browser_journeys_clean_store", "whatif_candidate_browser",
      "accepted_browser_suite_flags_off", "validation_inventory_runtime"], []),
    ("REG-EM", "Emulator artifact reproducibility", [], [],
     ["emulator_artifacts_reproduce"], []),
]

LIVE = ("VAL-30", "Live model validation",
        "BLOCKED", "Live-provider use is not authorised in this environment; "
        "no paid call was made. PENDING_LIVE: run docs/guided_workspace/"
        "MAC_LIVE_UAT.md on the Mac.")


def junit_by_file(folder: Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for name in ("v4_accepted.xml", "whatif_venv.xml"):
        f = folder / name
        if not f.exists():
            continue
        for case in ET.parse(f).getroot().iter("testcase"):
            cls = case.get("classname", "")
            file = cls.split(".")[-1] + ".py" if cls else ""
            if not file.startswith("test_"):
                parts = [p for p in cls.split(".") if p.startswith("test_")]
                file = parts[0] + ".py" if parts else file
            key = f"{name}:{file}"
            out[key]["tests"] += 1
            if case.find("failure") is not None or \
                    case.find("error") is not None:
                out[key]["failed"] += 1
            elif case.find("skipped") is not None:
                out[key]["skipped"] += 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regression", required=True)
    p.add_argument("--inventory", required=True)
    p.add_argument("--perf", default="")
    p.add_argument("--mutation", default="")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    reg = Path(args.regression)
    summary = json.loads((reg / "summary.json").read_text())
    steps = {s["name"]: s for s in summary["steps"]}
    jfile = reg / "suite_outputs/docs/guided_workspace/evidence/journeys.json"
    journeys = json.loads(jfile.read_text())["journeys"] if jfile.exists() \
        else []
    junit = junit_by_file(reg)
    inv = json.loads((Path(args.inventory) / "inventory_summary.json")
                     .read_text())
    perf = json.loads(Path(args.perf).read_text()) if args.perf and \
        Path(args.perf).exists() else None
    gates = json.loads(Path(args.mutation).read_text()) if args.mutation and \
        Path(args.mutation).exists() else None

    rows = []
    for aid, area, files, prefixes, stepnames, extra in AREAS:
        ev, bad, missing = [], [], []
        for f in files:
            hits = {k: v for k, v in junit.items() if k.endswith(":" + f)}
            if not hits:
                missing.append(f"pytest {f}")
                continue
            for k, v in hits.items():
                ev.append(f"{k} {v['tests']} tests, {v['failed']} failed, "
                          f"{v['skipped']} skipped")
                if v["failed"]:
                    bad.append(k)
        for pre in prefixes:
            js = [j for j in journeys if j["journey"].startswith(pre)]
            if not js:
                missing.append(f"journey {pre}*")
                continue
            failed = [j["journey"] for j in js if j["status"] != "PASS"]
            ev.append(f"{pre}*: {len(js) - len(failed)}/{len(js)} PASS")
            bad += failed
        for s in stepnames:
            st = steps.get(s)
            if not st:
                missing.append(f"step {s}")
                continue
            ev.append(f"step {s}: {st['status']}")
            if st["status"] == "FAIL":
                bad.append(s)
            elif st["status"] == "BLOCKED_ENV":
                missing.append(f"{s} BLOCKED_ENV: {st.get('detail', '')}")
        for x in extra:
            if x in ("routes", "controls", "handoffs", "back", "plotly"):
                key = {"back": "back_paths", "plotly": "plotly_rows"}.get(x, x)
                by = inv.get(f"{'back' if x == 'back' else x}_by_status", {})
                ev.append(f"{x}: {inv.get(key)} rows {json.dumps(by)}")
                if by.get("FAILED"):
                    bad.append(f"{x} FAILED {by['FAILED']}")
            elif x == "console":
                errs = sum(len(j.get("console_errors", [])) for j in journeys
                           if j["journey"].startswith(("GW-BACK", "GW-GOLD",
                                                       "GW-VAL")))
                ev.append(f"validation journeys' console errors: {errs}")
                if errs:
                    bad.append("console errors")
            elif x == "perf":
                if not perf:
                    missing.append("perf_smoke.json")
                else:
                    worst = max(perf["rows"], key=lambda r: r["p95_ms"])
                    ev.append(f"{len(perf['rows'])} endpoints; worst p95 "
                              f"{worst['p95_ms']} ms ({worst['endpoint']})")
            elif x == "gold10":
                n = len({j["journey"] for j in journeys
                         if j["journey"].startswith("GW-GOLD-")})
                ev.append(f"GOLD journeys run: {n}")
                if n < 10:
                    missing.append(f"only {n} of 10 GOLD journeys ran")
            elif x.startswith("gate:"):
                if not gates:
                    missing.append("mutation gates file")
                    continue
                name = x[5:]
                hit = [g for g in gates.get("gates", []) if
                       g.get("gate", "").startswith(name)]
                ok = hit and all(g.get("result") == "KILLED" for g in hit)
                ev.append(f"mutation gate '{name}': "
                          f"{'PASS' if ok else 'not proven'}")
                if hit and not ok:
                    bad.append(f"gate {name}")
        status = ("FAILED" if bad else
                  "BLOCKED" if any("BLOCKED_ENV" in m for m in missing)
                  and not ev else
                  "PARTIAL" if missing else "PASS")
        rows.append({"id": aid, "area": area, "status": status,
                     "evidence": " | ".join(ev),
                     "missing_or_blocked": " | ".join(missing),
                     "failed": " | ".join(bad)})
    rows.append({"id": LIVE[0], "area": LIVE[1], "status": LIVE[2],
                 "evidence": "", "missing_or_blocked": LIVE[3], "failed": ""})
    out = Path(args.out)
    with (out / "VALIDATION_MATRIX.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    results = {
        "candidate_sha": summary["commit"],
        "regression": {s["name"]: {"status": s["status"],
                                   "counts": s.get("counts"),
                                   "seconds": s.get("seconds")}
                       for s in summary["steps"]},
        "journeys": {"total": len(journeys),
                     "passed": sum(j["status"] == "PASS" for j in journeys),
                     "gold": sorted(j["journey"] for j in journeys
                                    if j["journey"].startswith("GW-GOLD-")),
                     "back": sorted(j["journey"] for j in journeys
                                    if j["journey"].startswith("GW-BACK-"))},
        "inventory": inv, "perf": perf,
        "mutation_gates": {g["gate"]: g.get("result") for g in
                           (gates or {}).get("gates", [])},
        "areas": rows, "area_status_counts": dict(counts)}
    (out / "VALIDATION_RESULTS.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(dict(counts)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
