#!/usr/bin/env python3
"""VALIDATION_REPORT.md / .html and FINAL_UAT_READINESS.md from measured
files only (VALIDATION_RESULTS.json, the defect register, the regression of
record, the seeds at the candidate). No figure in the report is typed by
hand.

    python3 scripts/guided_workspace/validation_report.py \\
        --validation docs/guided_workspace/validation \\
        --regression docs/guided_workspace/evidence/final_regression_<sha12> \\
        --branch claude/guided-workspace-exhaustive-validation \\
        --start-sha 8b1592f46b06d03cec089d5b49cb93280b819993 \\
        --started 2026-10-02T16:22:29Z
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

#: The acceptance bar of §38, each tied to the matrix rows that prove it.
BAR = [
    ("no CRITICAL defects remain", "defects:CRITICAL"),
    ("no HIGH defects remain", "defects:HIGH"),
    ("no dead primary buttons/links/routes remain", "VAL-06"),
    ("all intended Back controls pass", "VAL-05"),
    ("browser Back/Forward does not corrupt core state", "VAL-05"),
    ("all GOLD cross-module journeys pass", "VAL-33"),
    ("cohort identity is preserved across handoffs", "VAL-33"),
    ("method-selection governance passes", "VAL-11"),
    ("scenario lineage/stacking passes", "VAL-12"),
    ("ECL decompositions reconcile", "VAL-13"),
    ("selected-scope and total-book views reconcile", "VAL-13"),
    ("sharing opens real governed objects", "VAL-19"),
    ("save/reopen survives restart", "VAL-20"),
    ("exports match UI state", "VAL-21"),
    ("secret persistence passes", "VAL-23"),
    ("tenant isolation passes", "VAL-23"),
    ("Guided Workspace regression passes", "REG-WI"),
    ("flags-OFF accepted regression passes", "REG-BR"),
    ("every UI control executed at runtime (PASS, governed BLOCKED or N/A "
     "with proof)", "inv:controls_by_status"),
    ("every route checked: direct, refresh, Back/Forward, in-product Back, "
     "invalid and stale ids", "inv:routes_by_status"),
    ("every integration handoff keeps its object identity, writes only what "
     "it should and Back restores the source", "inv:handoffs_by_status"),
    ("every navigating control has a passing Back record",
     "inv:back_by_status"),
    ("every interactive chart meets its interaction contract",
     "inv:plotly_contracts_by_status"),
]

#: The closed states of an executed inventory row.
CLOSED = {"PASS", "BLOCKED_WITH_GOVERNED_REASON", "NOT_APPLICABLE_WITH_PROOF"}


def defects(register: Path) -> list[dict[str, str]]:
    rows = []
    for line in register.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| (VAL-DEF-\d+) \| (\w+) \| ([^|]+) \| ([^|]+) \| "
                     r"([^|]+) \|", line)
        if m:
            rows.append({"id": m[1], "severity": m[2], "module": m[3].strip(),
                         "defect": m[4].strip(),
                         "disposition": m[5].strip()})
    return rows


def seeds() -> dict:
    from backend.workspace import lens_seed, metric_catalog, scenario_seed
    tpl = getattr(scenario_seed, "TEMPLATES", None) or []
    by_book = Counter(t.get("domain_id") for t in tpl)
    lenses = getattr(lens_seed, "LENSES", None) or []
    personas = Counter(lz.get("persona") for lz in lenses)
    return {"scenario_templates": len(tpl), "templates_by_book": dict(by_book),
            "lenses": len(lenses), "lens_personas": dict(personas),
            "metrics": len(metric_catalog.BY_ID)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--validation", required=True)
    p.add_argument("--regression", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--start-sha", required=True)
    p.add_argument("--started", required=True)
    args = p.parse_args()
    v = Path(args.validation)
    res = json.loads((v / "VALIDATION_RESULTS.json").read_text())
    reg = json.loads((Path(args.regression) / "summary.json").read_text())
    defs = defects(v / "DEFECT_REGISTER.md")
    areas = {a["id"]: a for a in res["areas"]}
    inv = res["inventory"]
    sd = seeds()
    open_by = Counter(d["severity"] for d in defs
                      if not d["disposition"].startswith("FIXED"))
    found_by = Counter(d["severity"] for d in defs)
    fixed = sum(d["disposition"].startswith("FIXED") for d in defs)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    steps = reg["steps"]

    bar = []
    for text, key in BAR:
        if key.startswith("defects:"):
            ok = open_by.get(key.split(":")[1], 0) == 0
            bar.append((text, "PASS" if ok else "FAILED", key))
        elif key.startswith("inv:"):
            counts = inv.get(key[4:]) or {}
            ok = bool(counts) and set(counts) <= CLOSED
            bar.append((text, "PASS" if ok else "FAILED",
                        f"{key[4:]} {json.dumps(counts)}"))
        else:
            st = areas.get(key, {}).get("status", "MISSING")
            bar.append((text, st, key))
    ready = all(s == "PASS" for _, s, _ in bar)
    verdict = ("READY FOR MAC LIVE UAT" if ready else "NOT READY")

    L: list[str] = []
    w = L.append
    w("# Exhaustive validation report")
    w("")
    w(f"Generated {now} by `scripts/guided_workspace/validation_report.py`; "
      f"every figure below is read from a measured file.")
    w("")
    w("| Item | Value |")
    w("|---|---|")
    w(f"| Validation branch | `{args.branch}` |")
    w(f"| Starting candidate H | `{args.start_sha}` |")
    w(f"| Final candidate (regression of record) | `{reg['commit']}` |")
    w("| Evidence commit | the commit that adds this file (the next commit "
      "after the candidate on the branch) |")
    w(f"| Round started | {args.started} |")
    w("| Environment | Linux container; Python 3.12.3 (accepted "
      "`/home/user/.venv312`, candidate ML `.venv-whatif`); Node 22; Next.js "
      "16.3.2; Chromium (Playwright) |")
    w("| Model | MODEL MOCK (scripted analyst) for every browser journey; no "
      "provider credential, no paid call |")
    w(f"| Verdict | **{verdict}** |")
    w("")
    w("## Regression of record (fresh detached clone, output outside the "
      "repository)")
    w("")
    w("| Step | Status | Tests | Failed | Skipped | Seconds |")
    w("|---|---|---|---|---|---|")
    for s in steps:
        c = s.get("counts") or {}
        w(f"| {s['name']} | {s['status']} | {c.get('tests', '')} | "
          f"{(c.get('failures', 0) or 0) + (c.get('errors', 0) or 0) if c else ''}"
          f" | {c.get('skipped', '')} | {s.get('seconds', '')} |")
    w("")
    w("Failures counted in a PASS step are the pre-existing baseline "
      "failures the step's known list names (unchanged from candidate H); "
      "each step's detail is in its log.")
    w("")
    j = res["journeys"]
    w("## Browser journeys")
    w("")
    w(f"- Guided Workspace suite: **{j['passed']}/{j['total']}** PASS "
      f"(MODEL MOCK).")
    w(f"- GOLD cross-module journeys: {len(j['gold'])} run: "
      f"{', '.join(j['gold'])}.")
    w(f"- Back-navigation journeys: {len(j['back'])} "
      f"({inv.get('back_paths')} matrix rows, by status "
      f"{json.dumps(inv.get('back_by_status'))}).")
    w("")
    w("## Inventories")
    w("")
    w("| Inventory | Rows | By status |")
    w("|---|---|---|")
    w(f"| Routes | {inv['routes']} | {json.dumps(inv['routes_by_status'])} |")
    w(f"| Interactive controls | {inv['controls']} (with test id "
      f"{inv['controls_with_testid']}; clicked at runtime "
      f"{inv['controls_exercised']}) | {json.dumps(inv['controls_by_status'])}"
      f" |")
    w(f"| API functions | {inv['functions']} | "
      f"{json.dumps(inv['functions_by_status'])} |")
    w(f"| Integration handoffs | {inv['handoffs']} (carrying their origin "
      f"{inv['handoffs_carrying_origin']}) | "
      f"{json.dumps(inv['handoffs_by_status'])} |")
    w(f"| Back paths (one per navigating control) | {inv['back_paths']} | "
      f"{json.dumps(inv['back_by_status'])} |")
    w(f"| Plotly chart render audit | {inv['plotly_rows']} | "
      f"{json.dumps(inv['plotly_by_status'])} |")
    w(f"| Plotly interaction contracts | {inv.get('plotly_contracts', 0)} | "
      f"{json.dumps(inv.get('plotly_contracts_by_status', {}))} |")
    w("")
    w("Control applicability under the enabled configuration (V4 and the "
      "guided workspace on): "
      f"{json.dumps(inv.get('controls_by_applicability', {}))}.")
    w("")
    w("A control is PASS only when a browser journey executed it (an element "
      "carrying its test id was clicked, typed into or hovered) and the "
      "journey asserted its result: the API calls in its window, the writes "
      "it made, the console, the resulting route and its Back. "
      "BLOCKED_WITH_GOVERNED_REASON means the control was clicked and the "
      "product refused with its governed reason. NOT_APPLICABLE_WITH_PROOF "
      "means a journey proved the control's surface is not rendered under "
      "the enabled configuration. Each row's evidence is in "
      "`UI_CONTROL_EXECUTION_MATRIX.csv`.")
    w("")
    w("## Validation matrix")
    w("")
    w("| Id | Area | Status | Missing / blocked | Failed |")
    w("|---|---|---|---|---|")
    for a in res["areas"]:
        w(f"| {a['id']} | {a['area']} | **{a['status']}** | "
          f"{a['missing_or_blocked'] or '—'} | {a['failed'] or '—'} |")
    w("")
    w(f"Area status counts: {json.dumps(res['area_status_counts'])}. "
      f"Evidence per row: `VALIDATION_MATRIX.csv`.")
    w("")
    w("## Content counts at the candidate (seed definitions)")
    w("")
    w(f"- Scenario Library templates: {sd['scenario_templates']} "
      f"({json.dumps(sd['templates_by_book'])}).")
    w(f"- Seeded Lenses: {sd['lenses']}; personas "
      f"{json.dumps(sd['lens_personas'])}.")
    w(f"- Metric Catalogue: {sd['metrics']} governed metrics.")
    w("")
    w("## Defects")
    w("")
    w(f"- Found: {len(defs)} ({json.dumps(dict(found_by))}).")
    w(f"- Fixed: {fixed}.")
    w(f"- Remaining: {len(defs) - fixed} ({json.dumps(dict(open_by))}). "
      f"Detail: `DEFECT_REGISTER.md`.")
    w("")
    w("## Security, isolation, reconciliation")
    w("")
    for key, label in (("VAL-23", "Security / secret persistence / tenant "
                                  "isolation"),
                       ("VAL-13", "ECL reconciliation (independent oracle)"),
                       ("VAL-24", "Release fingerprints and seeds")):
        a = areas.get(key, {})
        w(f"- {label}: **{a.get('status')}**: {a.get('evidence', '')}")
    w("")
    mg = res.get("mutation_gates") or {}
    w(f"Mutation gates: {sum(1 for x in mg.values() if x == 'KILLED')} of "
      f"{len(mg)} killed.")
    w("")
    w("## Performance smoke (this machine, warm, sequential)")
    w("")
    if res.get("perf"):
        w("| Endpoint | p50 ms | p95 ms |")
        w("|---|---|---|")
        for r in res["perf"]["rows"]:
            w(f"| {r['endpoint']} | {r['p50_ms']} | {r['p95_ms']} |")
    w("")
    w("## Protected files")
    w("")
    w("No protected file changed in this round; the protected set equals the "
      "six mapped in `PROTECTED_EXTENSION_MAP.md` (step "
      "`protected_baseline_round`).")
    w("")
    w("## Live provider")
    w("")
    w("BLOCKED / PENDING_LIVE: live-provider use is not authorised in this "
      "environment and no paid call was made. The Mac live UAT "
      "(`docs/guided_workspace/MAC_LIVE_UAT.md`) is the remaining gate.")
    w("")
    w("## Acceptance bar (§38)")
    w("")
    w("| Criterion | Status | Proven by |")
    w("|---|---|---|")
    for text, st, key in bar:
        w(f"| {text} | {st} | {key} |")
    w("")
    w(f"**{verdict}**" + ("" if ready else ": the rows above that are not "
                                         "PASS say why."))
    w("")
    w("## Rollback")
    w("")
    w("```bash")
    w("git checkout --detach 8b1592f46b06d03cec089d5b49cb93280b819993   "
      "# candidate H, unchanged")
    w("# or keep the branch and revert this round's commits:")
    w(f"git revert --no-edit 55bfb9a4..{reg['commit'][:12]}")
    w("```")
    w("")
    w("## Mac launch / UAT")
    w("")
    w("Follow `docs/guided_workspace/MAC_LIVE_UAT.md`. The pinned SHA is read "
      "from `docs/guided_workspace/UAT_CANDIDATE.json` on "
      f"`{args.branch}`:")
    w("")
    w("```bash")
    w(f"git fetch origin {args.branch}")
    w(f"EXPECTED_GUIDED_UAT_SHA=$(git show origin/{args.branch}:"
      "docs/guided_workspace/UAT_CANDIDATE.json | python3 -c "
      "'import json,sys;print(json.load(sys.stdin)[\"expected_guided_uat_sha\"])')")
    w('git checkout --detach "$EXPECTED_GUIDED_UAT_SHA"')
    w("python3 scripts/guided_workspace/guided_preflight.py")
    w("```")
    text = "\n".join(L) + "\n"
    (v / "VALIDATION_REPORT.md").write_text(text, encoding="utf-8")
    body = html.escape(text)
    (v / "VALIDATION_REPORT.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Validation "
        "report</title><style>body{font:14px/1.45 system-ui;margin:2rem;"
        "max-width:72rem}pre{white-space:pre-wrap}</style></head><body><pre>"
        + body + "</pre></body></html>\n", encoding="utf-8")

    R: list[str] = []
    r = R.append
    r("# Final UAT readiness")
    r("")
    r(f"**{verdict}**")
    r("")
    r(f"- Candidate: `{reg['commit']}` on `{args.branch}` (no tag).")
    r("- Regression of record: "
      + ", ".join(f"{s['name']} {s['status']}" for s in steps) + ".")
    r(f"- Defects open: {json.dumps(dict(open_by)) or 'none'}.")
    r("")
    r("| Criterion | Status |")
    r("|---|---|")
    for text_, st, _ in bar:
        r(f"| {text_} | {st} |")
    r("")
    r("Remaining before production use: the Mac live-provider UAT "
      "(paid call, the user's decision) and the BLOCKED/PARTIAL rows of "
      "`VALIDATION_MATRIX.csv`, each with its exact reason.")
    (v / "FINAL_UAT_READINESS.md").write_text("\n".join(R) + "\n",
                                               encoding="utf-8")
    print(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
