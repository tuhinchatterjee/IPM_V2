#!/usr/bin/env python3
"""Turn the worked workbook and the specification into the episode config.

Why this is a script and not a hand-typed file
----------------------------------------------
`config/retail_episodes.json` holds the *structure* of the ten stories: their
titles, the exact five prompts per case, the scope each step narrows to, the
chart each step draws, the policy clauses each cites and the countercheck each
must state. All of that is written down in two attachments that are now in the
repository, and retyping it would mean the config and the specification could
drift apart with nobody noticing.

So the config is generated, and regenerating it is the check: if this script
produces a different file from the one committed, either the specification
changed or somebody edited the config by hand, and both are things a reviewer
should be told about rather than left to discover.

What is NOT copied out
----------------------
The fixture numbers are carried across as `fixture`, clearly labelled, and they
are used for exactly one thing: proving that the generated 59,000-facility book
reproduces the *relationships* the miniature 100-per-case example demonstrates
— the rate ratios, the ordering, the score movements, the concentration. They
are never rendered to a user. Every figure a reader sees is computed from the
active book at the active date, which is the difference between an implemented
story and ten hardcoded answer strings.

    .venv/bin/python scripts/build_episode_config.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "docs/anb-ten-journeys/CreditProbe_10_Saudi_Retail_Worked_Cases.xlsx"
SPEC = ROOT / "docs/anb-ten-journeys/SPECIFICATION.txt"
OUT = ROOT / "config/retail_episodes.json"

CASES = [f"C{i:02d}" for i in range(1, 11)]

#: The chip label a reader clicks, per step. The full prompt is the workbook's
#: own question; the label is what fits on a chip above the composer.
CHIP_LABELS = {
    "S1": "Break the issue apart",
    "S2": "Connect customer characteristics",
    "S3": "Challenge and decompose",
    "S4": "Locate the responsible pocket",
    "S5": "Sequence policy actions",
}

#: Which measures each step is allowed to quote. Cited by id from
#: backend/retail/metrics_contract.py so an undefined figure cannot be drawn.
STEP_METRICS = {
    "S0": ["affected_population", "concentration", "pd_12m", "behaviour_score",
           "application_score", "ecl", "ead", "current_bad", "forward_risk",
           "severity", "missingness"],
    "S1": ["affected_population", "roll_rate", "observed_default_rate",
           "missingness"],
    "S2": ["behaviour_score", "application_score", "missingness"],
    "S3": ["behaviour_score", "ecl", "ead", "pd_12m", "missingness"],
    "S4": ["concentration", "affected_population", "missingness"],
    "S5": ["ead", "ecl", "pd_12m", "missingness"],
}


def _rows(ws):
    return list(ws.iter_rows(values_only=True))


def _table(ws, key0, key1=None):
    header = None
    out = []
    for row in _rows(ws):
        if row and row[0] == key0 and (key1 is None or
                                       (len(row) > 1 and row[1] == key1)):
            header = list(row)
            continue
        if header and row and row[0]:
            out.append(dict(zip(header, row)))
    return out


def _spec_headers() -> dict[str, dict]:
    """Card measure, severity, product, pocket and policy, from the prompt."""
    text = SPEC.read_text(encoding="utf-8").replace("–", "-").replace(
        "•", "|")
    out: dict[str, dict] = {}
    for case in CASES:
        block = re.search(
            rf"^{case} \| (.+?)\nCard: (.+?)\nPocket: (.+?)\nPolicy context: (.+?)$",
            text, re.M)
        if not block:
            raise SystemExit(f"{case}: no card header found in the specification")
        title, card, pocket, policy = (g.strip() for g in block.groups())
        measure, severity, product = [p.strip() for p in card.split("|")]
        pol = re.match(r"([A-Z0-9-]+) (v\d+), clauses (.+?);", policy)
        research = re.search(r"Public research: ([R0-9, ]+)\.", policy)
        out[case] = {
            "title": title,
            "card_measure": measure,
            "severity": severity,
            "product_family": product,
            "pocket_label": pocket,
            "policy_id": pol.group(1) if pol else "",
            "policy_version": pol.group(2) if pol else "v1",
            "policy_clauses": [c.strip() for c in
                               (pol.group(3).split("/") if pol else [])],
            "research": [r.strip() for r in
                         (research.group(1).split(",") if research else [])],
        }
    return out


def build() -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(XLSX, data_only=True)
    steps = _table(wb["Step_Catalogue"], "Case", "Step")
    policy = _table(wb["Policy_Actions"], "Case", "Policy")
    events = _table(wb["Event_History"], "Case", "Window")
    features = _table(wb["Feature_History"], "Case", "Month")
    headers = _spec_headers()

    episodes = []
    for case in CASES:
        sheet = wb[case]
        rows = _rows(sheet)

        drawer = {}
        for row in rows:
            if row and row[0] in ("Issue count", "PD12, non-impaired",
                                  "Behavioral score",
                                  "Original application score",
                                  "Affected ECL (SAR)", "Affected GCA (SAR)",
                                  "LGD", "ODR / redefault",
                                  "Forward-risk customers"):
                vals = [c for c in row[1:] if c is not None]
                drawer[row[0]] = {
                    "comparator": vals[0] if len(vals) > 0 else None,
                    "current": vals[1] if len(vals) > 1 else None,
                    "meaning": vals[2] if len(vals) > 2 else None,
                }

        # Both model families appear here, and which one a case uses is the
        # diagnosis. C02 and the other vintage stories decompose the ORIGINAL
        # application score; the post-origination stories decompose the
        # behavioural one. Reading only one family silently drops the
        # underwriting-quality cases' entire evidence.
        drivers = [{"driver": r[6], "points": r[7], "model": r[8]} for r in rows
                   if r and len(r) > 9 and r[8] in ("Behavior", "Application")
                   and isinstance(r[7], (int, float))]
        pocket = {r[6]: {"eligible": r[7], "issue": r[8], "incidence": r[9]}
                  for r in rows if r and len(r) > 9 and r[6] in ("Pocket", "Other")}
        feature_line = next(
            (r[0] for r in rows
             if r and isinstance(r[0], str) and "→" in r[0]
             and "Feature reference" in r[0]), "")

        case_steps = []
        for rec in [s for s in steps if s["Case"] == case]:
            step = rec["Step"]
            case_steps.append({
                "step": step,
                "chip_label": CHIP_LABELS.get(step, "Open card"),
                "prompt": rec["Exact question / action"],
                "scope_label": rec["Scope predicate"],
                "chart": rec["Chart specification"],
                "metric_ids": STEP_METRICS[step],
                "fixture_customer_n": rec["Customer N"],
                "fixture_expectation": rec["Expected output"],
                "fixture_snapshot_id": rec["Snapshot ID"],
            })

        episodes.append({
            **headers[case],
            "case_id": case,
            "countercheck": next(
                (str(r[6]).split(":", 1)[1].strip().split("\n")[0]
                 for r in rows
                 if r and len(r) > 6 and isinstance(r[6], str)
                 and r[6].startswith("Alternative explanation:")), ""),
            "steps": case_steps,
            "policy_actions": [
                {"clause": p["Clause"], "status": p["Status"],
                 "effective_from": str(p["Effective from"])[:10],
                 "action": p["Draft clause / action"], "owner": p["Owner"],
                 "timing": p["Timing"], "safeguard": p["Safeguard"],
                 "research": [r.strip() for r in
                              str(p["Research context"]).split(",")]}
                for p in policy if p["Case"] == case],
            "fixture": {
                "note": ("A 100-observation engineering example. Used to check "
                         "that the generated book reproduces these "
                         "relationships; never rendered to a reader."),
                "eligible": 100,
                "drawer": drawer,
                "score_drivers": drivers,
                "pocket": pocket,
                "feature_line": feature_line,
                "events": [{"window": e["Window"], "eligible": e["Eligible"],
                            "events": e["Events"], "rate": e["Rate"],
                            "basis": e["Basis"]}
                           for e in events if e["Case"] == case],
                "feature_history": [
                    {"month": f["Month"], "behaviour_score": f["Behavior score"],
                     "feature_1": f["Feature 1"], "unit_1": f["Unit 1"],
                     "feature_2": f["Feature 2"], "unit_2": f["Unit 2"],
                     "cohort_n": f["Cohort N"]}
                    for f in features if f["Case"] == case],
            },
        })

    return {
        "config_version": "retail-episodes-1.0.0",
        "generated_from": {
            "specification": "docs/anb-ten-journeys/SPECIFICATION.txt",
            "workbook": ("docs/anb-ten-journeys/"
                         "CreditProbe_10_Saudi_Retail_Worked_Cases.xlsx"),
            "script": "scripts/build_episode_config.py",
        },
        "disclosure": (
            "Every customer, employer, project, score, rate, exposure and "
            "policy clause here is synthetic. Nothing represents Arab "
            "National Bank data, actual distress or approved policy."),
        "reference_as_of": "2026-08-31",
        "episodes": episodes,
    }


def main() -> int:
    config = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(config, indent=1, ensure_ascii=False) + "\n"
    if OUT.exists() and OUT.read_text(encoding="utf-8") == text:
        print(f"{OUT.relative_to(ROOT)} is already current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: "
          f"{len(config['episodes'])} episodes, "
          f"{sum(len(e['steps']) for e in config['episodes'])} steps, "
          f"{sum(len(e['policy_actions']) for e in config['episodes'])} actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
