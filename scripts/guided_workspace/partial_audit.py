#!/usr/bin/env python3
"""Write PARTIAL_CLOSURE_AUDIT.md: every requirement that was PARTIAL in the
matrix of candidate F, classified, with the action taken in P16 and -- when
`--after` names the final matrix JSON -- its MEASURED status after.

The "before" rows are read from candidate F's evidence commit with
`git show`, never retyped. The classification and action per id are the
reviewed table below; a PARTIAL id missing from it, or an id in it that was
not PARTIAL, fails the script.

    python3 scripts/guided_workspace/partial_audit.py \\
        --after docs/guided_workspace/REQUIREMENT_MATRIX.json \\
        --out docs/guided_workspace/PARTIAL_CLOSURE_AUDIT.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BEFORE_COMMIT = "57e4cf4f691073a00e1b75877e4731fb08bcd1c0"
CATEGORIES = {
    "A": "IMPLEMENTATION_GAP", "B": "TEST_GAP", "C": "BROWSER_EVIDENCE_GAP",
    "D": "PERSISTENCE_REOPEN_GAP", "E": "EXPORT_TRACE_GAP",
    "F": "DATA_LIMITATION", "G": "MODEL_LIMITATION",
    "H": "ENVIRONMENT_LIMITATION", "I": "LIVE_PROVIDER_REQUIRED",
    "J": "SPEC_CONFLICT",
    "K": "INTENTIONALLY_PARTIAL_WITH_GOVERNED_REASON",
}

ORACLE = ("Python oracle in test_gw_metric_oracles.py recomputes it from the "
          "governed rows on four cuts per book (latest, prior, the stress "
          "period with the most Stage 3, a filtered cut) and asserts "
          "equality; a non-vacuity test requires a non-zero cut.")
MAC = ("Logic tested in the container (test_gw_uat_preflight.py, "
       "test_launcher_safety.py); execution on the Mac is the user's UAT.")
NO_MAP = ("No governed translation exists for this component; it runs "
          "only as User-defined. Inventing a mapping would be fake.")

#: id -> (category, closable now?, action)
TABLE: dict[str, tuple[str, str, str]] = {
    "UAT-03": ("J", "no", "The 2x2 lives in the protected Cockpit renderer "
               "(components/cockpit-v4/visuals.tsx); replacing it needs a "
               "protected-core decision. The guided What-If explorer already "
               "augments it with an interactive stage-migration Sankey "
               "(GW-P11-01). Scenario-induced migration is DECOMP12 (data)."),
    "UAT-05": ("J", "no", "Governed surfaces use moneyCol; the protected "
               "Cockpit thread renderer and flags-off pages keep their own "
               "formatting. Changing them needs a protected-core decision."),
    "UAT-07": ("H", "no", MAC),
    "SCEN07": ("G", "no", "Application-score stress is parsed and kept "
               "separate, TRANSLATION_ONLY: no governed score-to-PD mapping. "
               + NO_MAP),
    "DECOMP02": ("B", "yes", "test_gw_ml_decomposition.py runs a real "
                 "Corporate Method 2 result on the candidate interpreter: "
                 "booked and raw model baselines both published, gap = their "
                 "difference."),
    "DECOMP03": ("B", "yes", "Same suite: the ML change is scenario minus the "
                 "BOOKED baseline; the gap is N/A in the decomposition with "
                 "its reason, never inside a component."),
    **{f"LAUNCH{n:02d}": ("H" if n not in (6, 7) else "I", "no", MAC)
       for n in range(1, 13)},
    "GX-08": ("C", "yes", "Browser journey GW-P16-01 completes Issue → "
              "Investigate → driver chip → stress-test chip → What-If on the "
              "same cohort → Ask (pre-filled) → confirm button → Delta "
              "button → reconciling decomposition with zero keystrokes."),
    "CORP-03": ("K", "no", "The collateral translation keeps its fitted sign "
                "(LGD falls when collateral falls) with SIGN_REVIEW, as "
                "instructed; it is shown, not corrected."),
    "RET-02": ("F", "no", "The Retail book publishes no CCF field (EAD = "
               "balance on 6,702 of 6,702 accounts); the CCF component is "
               "UNSUPPORTED and the template BLOCKED. Synthesising CCF would "
               "be fake data."),
    "RET-04": ("G", "no", NO_MAP),
    "RET-05": ("G", "no", "Delinquency-band shift NEEDS_USER_MAPPING; Delta "
               "is BLOCKED by name. " + NO_MAP),
    "RET-07": ("K", "no", "Property-value translation keeps its fitted sign "
               "with SIGN_REVIEW (RET-07 instruction); not corrected."),
    "RET-08": ("G", "no", "Vehicle-collateral NEEDS_USER_MAPPING. " + NO_MAP),
    "RET-14": ("G", "no", NO_MAP),
    "RET-17": ("G", "no", NO_MAP),
    "LENS-04": ("A", "yes", "Governed metrics M065 (management overlay) and "
                "M066 (overlay share) on the published IFRS 9 overlay; KPI "
                "and breakdown visuals; oracle tests."),
    "LENS-05": ("A", "yes", "New governed evaluator M069 (one group per EWS "
                "rule, the rule's own SQL) and a `groups` visual; per-rule "
                "Python oracle."),
    "LENS-06": ("A", "yes", "Booked ECL KPI and ECL-by-sector breakdown, "
                "rating downgrade rate; oracle test."),
    "LENS-08": ("A", "yes", "Top warning reasons (M069) under the card "
                "filter; test proves the Lens filter narrows them."),
    "LENS-09": ("F", "partly", "Warning reasons including the governed "
                "salary-interruption PROXY shown and labelled; no "
                "salary-credit feed exists in the data."),
    "LENS-12": ("A", "yes", "Recovery and write-off columns exposed from "
                "the published base tables; M067/M068; KPI, 12-period trend "
                "and breakdown; per-period oracle."),
    "LENS-16": ("A", "partly", "Method comparison (M073), concentration "
                "Pareto (M074) and ECL change by stage (M075) of the latest "
                "result. Stage MIGRATION remains unmodelled (DECOMP12)."),
    "LENS-18": ("A", "yes", "Alerts by state (M070), active breaches by "
                "metric (M071) and by owner (M072); M050 now computed per "
                "Lens; tests against the alert store."),
    "M042": ("B", "yes", "test_gw_ml_decomposition.py: M042 equals each ML "
             "result's published gap."),
    "M049": ("B", "yes", "A material move is made and counted; equality "
             "with the observations."),
    "M050": ("A", "yes", "The evaluator returned no value ('per Lens'); it "
             "now computes hours since each Lens' last SUCCESSFUL refresh, "
             "oldest as headline; a refresh resets that Lens' age."),
    "M038": ("B", "yes", ORACLE + " Measured: no account exceeds its limit "
             "in any period of either book (max 97.9%), so the formula is "
             "also proven on synthetic rows that do."),
    "M027": ("B", "yes", ORACLE + " Per band, distinct customers."),
    "M043": ("B", "yes", "Read straight from the published sensitivity "
             "parquet and compared per factor·parameter."),
    "M044": ("B", "yes", "Same, sign stability."),
    "M046": ("B", "yes", "Hours since the release's built_at, recomputed."),
}
for _mid in ("M004", "M008", "M009", "M010", "M011", "M012", "M013", "M014",
             "M019", "M022", "M023", "M024", "M025", "M026", "M030", "M031",
             "M032", "M033", "M034", "M035", "M036", "M037", "M045", "M047"):
    TABLE[_mid] = ("B", "yes", ORACLE)


def spec_text() -> dict[str, str]:
    rows = (ROOT / "docs/guided_workspace/matrix/spec_requirement_rows.txt"
            ).read_text(encoding="utf-8")
    out = {}
    for line in rows.splitlines():
        m = re.match(r"^\| ?([A-Z][A-Z0-9]{1,8}-?[0-9]{2,3}) \|(.*)\|\s*$",
                     line)
        if m:
            out[m.group(1)] = " | ".join(
                c.strip() for c in m.group(2).split("|") if c.strip())
    return out


def cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--after", default="")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    before = json.loads(subprocess.run(
        ["git", "show", f"{BEFORE_COMMIT}:docs/guided_workspace/"
                        f"REQUIREMENT_MATRIX.json"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout)
    after = (json.loads(Path(args.after).read_text())["rows"]
             if args.after else {})
    after_sha = (json.loads(Path(args.after).read_text()).get(
        "candidate_sha", "") if args.after else "")
    partial = [k for k, v in before["rows"].items()
               if v["status"] == "PARTIAL"]
    missing = [k for k in partial if k not in TABLE]
    extra = [k for k in TABLE if k not in partial]
    if missing or extra:
        print(f"unclassified PARTIAL: {missing}; not PARTIAL at F: {extra}",
              file=sys.stderr)
        return 1
    spec = spec_text()
    counts: dict[str, int] = {}
    moved: dict[str, int] = {}
    lines = []
    for rid in partial:
        cat, closable, action = TABLE[rid]
        b = before["rows"][rid]
        a = after.get(rid, {})
        final = a.get("status", "pending the final regression")
        counts[cat] = counts.get(cat, 0) + 1
        moved[final] = moved.get(final, 0) + 1
        evidence = "; ".join(f"`{c.split('::')[-1]}` {o}"
                             for c, o in b["evidence"]) or "—"
        lines.append(
            f"| {rid} | {cell(spec.get(rid, ''))} | {b['status']} | "
            f"{cat} {CATEGORIES[cat]} | {cell(evidence)} | "
            f"{cell(b['reason'])} | {closable} | {cell(action)} | "
            f"**{final}** |")
    head = [
        "# PARTIAL closure audit (P16)",
        "",
        f"Generated by `scripts/guided_workspace/partial_audit.py`. "
        f"\"Before\" is the matrix of candidate F, read from commit "
        f"`{BEFORE_COMMIT[:12]}` with `git show`; \"final measured status\" "
        f"is the matrix of the final regression"
        + (f" on candidate `{after_sha}`." if after_sha else
           " (not yet run).") + " Nothing here is typed by hand except the "
        "classification and action per id, which the script checks covers "
        "exactly the PARTIAL set.",
        "",
        f"* PARTIAL at F: **{len(partial)}**.",
        "* By category: " + ", ".join(
            f"{c} {CATEGORIES[c]} {n}" for c, n in sorted(counts.items())) +
        ".",
        "* Final measured status of these ids: " + ", ".join(
            f"{k} {v}" for k, v in sorted(moved.items())) + ".",
        "",
        "| ID | Requirement (spec text) | Status at F | Category | Evidence "
        "at F (result) | Missing at F | Closable in P16 | Action | Final "
        "measured status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    Path(args.out).write_text("\n".join(head + lines) + "\n",
                              encoding="utf-8")
    print(json.dumps({"partial_at_F": len(partial), "by_category": counts,
                      "final": moved}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
