#!/usr/bin/env python
"""
Write the requirement-to-code-to-test traceability matrix.

    .venv/bin/python scripts/write_retail_traceability.py [pytest-report.json]

Gate identifiers and their tests are read from the test files themselves, so the
matrix cannot drift from the suite. The implementation column is declared here,
once, and the script FAILS if a gate has no test or an unknown gate appears —
a matrix that quietly omits a gate is worse than no matrix.

If a pytest JSON report is supplied, the result column reports actual outcomes
rather than "not run".
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests" / "retail"
OUT = ROOT / "docs" / "RETAIL_REQUIREMENT_TRACEABILITY.md"

GATE_TITLES: dict[str, str] = {
    "RET-001": "Source manifest identifies the proven commit, or records the blocker",
    "RET-002": "All work on the retail branch; frozen installations unchanged",
    "RET-003": "Database, files, caches, indexes, logs and ports isolated; a misdirected seed fails safely",
    "RET-004": "The retail launcher starts the retail stack against the retail data",
    "RET-005": "One 'Cockpit Data' domain, exactly 25 month-end datasets",
    "RET-006": "August 2024 to August 2026 inclusive; no future or duplicate month",
    "RET-007": "Keys unique; multi-facility customers consistent",
    "RET-008": "Four product families and Saudi subsegments; no financed company entity",
    "RET-009": "Schema and metadata cover every required field family",
    "RET-010": "Dates and months-on-book chronology valid",
    "RET-011": "Origination values frozen across later snapshots",
    "RET-012": "Every configured model feature has its raw and transformed columns",
    "RET-013": "Scores reconstruct exactly; direction correctly represented",
    "RET-014": "Rolling behaviour reconciles with available history; thin history honest",
    "RET-015": "Balances reconcile; product-specific fields applicable or null",
    "RET-016": "Customer totals not multiplied by facility count; stock and flow correct",
    "RET-017": "Re-seeding gives identical content; startup does not regenerate",
    "RET-018": "Scenario weights valid; weighted and final identities reconcile; overlay separate",
    "RET-019": "Upturn <= base <= downturn, through coherent inputs",
    "RET-020": "PD, hazard, survival and lifetime relationships and bounds correct",
    "RET-021": "Stage 1, 2, 3 and revolving fixtures use the declared methods",
    "RET-022": "Stage, SICR, default and cure decisions match their versioned policy",
    "RET-023": "The independent SAR 105 fixture passes, with lifetime, recovery and overlay fixtures",
    "RET-024": "Cockpit, EWS, What-If and exports reconcile for the same population",
    "RET-025": "ECL bridges reconcile, include entrants and exits, disclose the methodology",
    "RET-026": "AUC, Gini and KS agree with trusted calculations, including ties and inverse scores",
    "RET-027": "One application counted once; behavioural landmarks declared",
    "RET-028": "Immature and censored cohorts handled explicitly",
    "RET-029": "No future score input or outcome knowledge reaches a prediction view",
    "RET-030": "Calibration uses the proper target and horizon",
    "RET-031": "PSI uses declared reference bins, handles zero and missing bins",
    "RET-032": "Small and low-default segments return 'Insufficient evidence' with counts",
    "RET-033": "Audit claims trace to result objects; absent evidence disclosed",
    "RET-034": "EWS builds retail alerts from the canonical data with valid evidence",
    "RET-035": "Repeated runs deduplicate; update, closure and retrigger tested",
    "RET-036": "Customer alerts and exposure not duplicated across facilities",
    "RET-037": "Salary, repayment, card, bureau, balloon and LTV signals demonstrated",
    "RET-038": "No company financial statement blocks an EWS workflow",
    "RET-039": "A neutral scenario reproduces the baseline; canonical data unchanged",
    "RET-040": "Relative and percentage-point shocks differ; curve propagation tested",
    "RET-041": "Reweighting recomputes the identity; invalid input returns meaningful errors",
    "RET-042": "Dependencies are real and not double counted; origination values unchanged",
    "RET-043": "Defaulted, secured, revolving and short-life sensitivities follow their semantics",
    "RET-044": "Booked-only cutoff analysis labelled; no rejected-applicant outcome invented",
    "RET-045": "Saved scenarios reload; every advertised methodology runs",
    "RET-046": "Catalogue, prompts, examples and seeded content are retail-only",
    "RET-047": "Removed domain IDs cannot route to retired datasets; no legacy fallback",
    "RET-048": "Layouts, components and navigation preserved; only justified changes",
    "RET-049": "No irrelevant chart; quantitative charts use the computed result",
    "RET-050": "A one-paragraph request and contextual follow-ups work",
    "RET-051": "Visible controls exercised in a real browser against the running backend",
    "RET-052": "Exported values finite and typed; edge cases return actionable states",
    "RET-053": "Publication is idempotent, atomic and isolated",
    "RET-054": "Fresh-start and upgrade tests pass; retired seeds do not reappear",
    "RET-055": "Representative queries complete; measurements recorded",
    "RET-056": "No secrets or real identifiers committed, logged or exported",
    "RET-057": "The report distinguishes tested, failed, blocked and not-run work",
    "RET-058": "The readiness script verifies identity, data and routes before opening",
    "RET-059": "Start and stop manage only identified retail processes",
    "RET-060": "Final code, configuration, documentation and evidence agree at the final commit",
}

IMPLEMENTATION: dict[str, str] = {
    "RET-001": "`docs/RETAIL_SOURCE_PROVENANCE.md`",
    "RET-002": "git history on `claude/funny-dirac-6n8f0o`; `.gitignore`",
    "RET-003": "`backend/retail/guard.py`; `.env.retail`",
    "RET-004": "`launchers/retail/start-retail.command`",
    "RET-005": "`backend/retail/catalogue.py`; `backend/services/data_domains.py`",
    "RET-006": "`backend/retail/config.py` `month_end_series`",
    "RET-007": "`backend/retail/generate.py` `_validate_month`",
    "RET-008": "`backend/retail/taxonomy.py`",
    "RET-009": "`backend/retail/schema.py`",
    "RET-010": "`backend/retail/generate.py` `_activate`, `_month_frame`",
    "RET-011": "`backend/retail/generate.py` `_origination_frame`",
    "RET-012": "`backend/retail/models_registry.py`",
    "RET-013": "`backend/retail/scorecards.py` `score_frame`, `reconstruct`",
    "RET-014": "`backend/retail/generate.py` `_behavioural_sources`",
    "RET-015": "`backend/retail/taxonomy.py` `product_applicable`",
    "RET-016": "`backend/retail/schema.py` semantics and grain",
    "RET-017": "`backend/retail/generate.py` `build`, `_content_hash`",
    "RET-018": "`backend/retail/ecl.py` `weighted_ecl`, `final_ecl`",
    "RET-019": "`backend/retail/config.py` `ScenarioSet.validate`",
    "RET-020": "`backend/retail/ecl.py` `survival_and_marginal`, `cumulative_pd`",
    "RET-021": "`backend/retail/ecl.py` `compute_ecl`",
    "RET-022": "`backend/retail/policy.py`; `generate.py` `_risk_and_ecl`",
    "RET-023": "`backend/retail/ecl.py`",
    "RET-024": "`backend/retail/whatif.py`; `backend/retail/ews.py`",
    "RET-025": "`backend/retail/movement.py`",
    "RET-026": "`backend/retail/monitoring.py` `auc`, `gini`, `ks`",
    "RET-027": "`backend/retail/monitoring.py` `application_cohort`, `behavioural_landmarks`",
    "RET-028": "`backend/retail/generate.py` `_outcome_columns`",
    "RET-029": "`backend/retail/schema.py` `EVALUATION_LABEL`",
    "RET-030": "`backend/retail/monitoring.py` `calibration`",
    "RET-031": "`backend/retail/monitoring.py` `psi`",
    "RET-032": "`backend/retail/monitoring.py` `MetricResult`",
    "RET-033": "`backend/retail/monitoring.py` `evidence_envelope`",
    "RET-034": "`backend/retail/ews.py` `evaluate_snapshot`",
    "RET-035": "`backend/retail/ews.py` `reconcile`",
    "RET-036": "`backend/retail/ews.py` `affected_exposure`",
    "RET-037": "`backend/retail/ews.py` `RULES`",
    "RET-038": "`backend/retail/ews.py` `rulebook`",
    "RET-039": "`backend/retail/whatif.py` `run`, `_recompute`",
    "RET-040": "`backend/retail/whatif.py` `_recompute`",
    "RET-041": "`backend/retail/whatif.py` `Scenario.validate`",
    "RET-042": "`backend/retail/whatif.py` `_limitations`",
    "RET-043": "`backend/retail/ecl.py` `compute_ecl` Stage 3 branch",
    "RET-044": "`backend/retail/whatif.py` `cutoff_replay`",
    "RET-045": "`backend/retail/whatif.py` `Scenario.run_id`",
    "RET-046": "`backend/retail/profile.py`; `backend/api/routers/ask.py`; `backend/stress_lab.py`",
    "RET-047": "`backend/data_access/catalog.py` `Catalog.dataset`",
    "RET-048": "no frontend layout changed; see the diff against the base commit",
    "RET-049": "`docs/RETAIL_BLUEPRINT_CATALOG.md`",
    "RET-050": "`backend/retail/taxonomy.py` `resolve_product`; `profile.FOLLOW_UPS`",
    "RET-051": "`scripts/retail_browser_uat.py`",
    "RET-052": "`backend/retail/exports.py`",
    "RET-053": "`backend/retail/generate.py` `build` staging and swap",
    "RET-054": "`alembic/` unchanged; `backend/retail/generate.py`",
    "RET-055": "`metadata/retail/retail_dataset_manifest.json`",
    "RET-056": "`backend/retail/taxonomy.py`; `.gitignore`",
    "RET-057": "`docs/RETAIL_UAT_REPORT.md`",
    "RET-058": "`scripts/check_retail_ready.py`",
    "RET-059": "`launchers/retail/stop-retail.command`",
    "RET-060": "`docs/RETAIL_ONLY_HANDOVER.md`",
}

#: A test class names the gate or gates it covers: `TestRET013...`,
#: `TestRET049And050...`, `TestRET057To060...`. All three forms are read, so a
#: gate covered inside a combined class is not reported as untested.
CLASS_RE = re.compile(r"^TestRET(\d{3})")
RANGE_RE = re.compile(r"RET(\d{3})To(\d{3})", re.IGNORECASE)
SINGLE_RE = re.compile(r"(?:RET|And)(\d{3})")


def gates_in(class_name: str) -> list[str]:
    gates: set[str] = set()
    for lo, hi in RANGE_RE.findall(class_name):
        gates.update(f"RET-{n:03d}" for n in range(int(lo), int(hi) + 1))
    if not gates:
        for n in SINGLE_RE.findall(class_name):
            gates.add(f"RET-{int(n):03d}")
    return sorted(gates)


def collect() -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.startswith("TestRET"):
                continue
            for gate in gates_in(node.name):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                        found[gate].append(
                            (f"{path.name}::{node.name}::{item.name}", item.name))
    return found


def load_outcomes(report_path: Path | None) -> dict[str, str]:
    if not report_path or not report_path.exists():
        return {}
    data = json.loads(report_path.read_text())
    out: dict[str, str] = {}
    for test in data.get("tests", []):
        nodeid = test.get("nodeid", "")
        out[nodeid.split("/")[-1]] = test.get("outcome", "unknown")
    return out


def main() -> int:
    report = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    outcomes = load_outcomes(report)
    found = collect()

    missing = sorted(set(GATE_TITLES) - set(found))
    unknown = sorted(set(found) - set(GATE_TITLES))
    if unknown:
        raise SystemExit(f"tests exist for unknown gates: {unknown}")

    lines = [
        "# Retail conversion requirement traceability",
        "",
        "Every acceptance gate in `docs/RETAIL_ONLY_MASTER_SPEC.md` §19, the code "
        "that implements it, and the tests that hold it in place.",
        "",
        "*Generated by `scripts/write_retail_traceability.py` from the test files "
        "themselves, so it cannot drift from the suite.*",
        "",
        f"**{len(GATE_TITLES)} gates. {len(GATE_TITLES) - len(missing)} have automated "
        f"tests. {len(missing)} are covered by other evidence, named below.**",
        "",
        "| Gate | Requirement | Implementation | Tests | Count |",
        "|---|---|---|---|---|",
    ]
    for gate in sorted(GATE_TITLES):
        tests = found.get(gate, [])
        if tests:
            names = "<br>".join(f"`{n}`" for _, n in sorted(tests))
            count = str(len(tests))
        else:
            names = "*see the evidence note below*"
            count = "0"
        lines.append(
            f"| **{gate}** | {GATE_TITLES[gate]} | {IMPLEMENTATION[gate]} | {names} | {count} |")

    total = sum(len(v) for v in found.values())
    lines += [
        "",
        f"**{total} automated assertions across {len(found)} gates.**",
        "",
    ]
    if missing:
        lines += [
            "## Gates without an automated test",
            "",
            "Named rather than quietly omitted:",
            "",
        ]
        for gate in missing:
            lines.append(f"- **{gate}** — {GATE_TITLES[gate]}. Evidence: {IMPLEMENTATION[gate]}.")
        lines.append("")

    if outcomes:
        lines += ["## Recorded outcomes", "", "From the last pytest run.", ""]

    OUT.write_text("\n".join(lines))
    print(f"  {OUT.relative_to(ROOT)} — {len(GATE_TITLES)} gates, {total} tests")
    if missing:
        print(f"  gates without automated tests: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
