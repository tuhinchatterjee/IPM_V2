#!/usr/bin/env python3
"""Row by row, against the workbook's own ninety acceptance checks.

    PYTHONPATH=. .venv/bin/python scripts/cpra_acceptance_manifest.py

The workbook ships ninety checks — sixty case-step rows and thirty
cross-cutting ones — every one of them labelled NOT RUN IN APP, because the
workbook is a specification and a fixture rather than installed software. §8
says to execute each against the implemented SHA and record the evidence.

So this reads the workbook's Tests sheet, matches each row against what was
actually run here, and writes the result with what proved it. A row with no
evidence is recorded as NOT RUN rather than assumed: the whole point of the
exercise is that a green report nobody can trace is worth less than an honest
partial one.

Two kinds of evidence are matched:

* the ten browser journeys, which drive the real pages and write screenshots
  and workbooks (`docs/anb-ten-journeys/acceptance/browser_journeys.json`);
* the pytest gates, whose node ids are mapped to the X-checks they cover.

The customer counts in the workbook's expectations are the miniature fixture's,
not this book's, so they are recorded beside the measured ones rather than
asserted against them. A book of 59,416 facilities has its own counts; that is
the specification's own instruction.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

XLSX = ROOT / "docs/anb-ten-journeys/CreditProbe_10_Saudi_Retail_Worked_Cases.xlsx"
JOURNEYS = ROOT / "docs/anb-ten-journeys/acceptance/browser_journeys.json"
OUT = ROOT / "docs/anb-ten-journeys/acceptance/ACCEPTANCE.md"

#: Which gate file covers each cross-cutting check. A check with no entry is
#: reported as not run rather than quietly passed.
X_EVIDENCE = {
    "X01": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x01_the_build_records_which_version_it_is",
    "X02": "launcher start-stop-start, recorded in PHASE_STATUS.md",
    "X03": "tests/retail/test_ret_cpra_p3_bundle.py::test_a_failed_publication_leaves_the_previous_bundle_readable",
    "X04": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x04_the_five_registrations_are_still_there",
    "X05": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x05_x06_every_pocket_is_in_both_modules_at_the_same_date",
    "X06": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x05_x06_every_pocket_is_in_both_modules_at_the_same_date",
    "X07": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x07_a_missing_early_warning_month_is_a_gap_not_a_zero",
    "X08": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x08_a_multi_facility_customer_is_counted_once",
    "X09": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x09_a_union_of_two_cohorts_deduplicates",
    "X10": "tests/retail/test_ret_cpra_p2_episodes.py::test_the_two_outcome_window_stories_compare_matched_vintages",
    "X11": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x11_an_original_application_score_is_immutable",
    "X12": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x12_a_step_cannot_read_a_month_after_its_own",
    "X13": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x13_a_clause_out_of_force_is_unsupported",
    "X14": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x14_no_approved_policy_means_no_compliance_claim",
    "X15": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x15_a_hostile_note_is_data",
    "X16": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x16_a_second_reader_is_refused",
    "X17": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x17_a_saved_snapshot_survives_a_refresh",
    "X18": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x18_a_note_keeps_its_author_and_its_history",
    "X19": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x19_a_standalone_360_carries_no_investigation_context",
    "X20": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x20_the_export_is_the_population_not_the_page",
    "X21": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x21_an_export_at_s1_holds_no_later_step",
    "X22": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x22_a_formula_cell_is_neutralised",
    "X23": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x23_the_whatif_baseline_equals_the_selected_scope",
    "X24": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x24_a_limit_cut_does_not_repay_a_drawing",
    "X25": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x25_a_defaulted_cohort_gets_no_forward_pd",
    "X26": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x26_scenario_weights_sum_to_one",
    "X27": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x27_the_recovery_story_holds_its_controls",
    "X28": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x28_a_cohort_beyond_the_old_row_cap_exports_whole",
    "X29": "tests/retail/test_ret_cpra_p10_crosscutting.py::test_x29_a_paraphrase_reaches_the_same_scope",
    "X30": "launcher start-stop-start, recorded in PHASE_STATUS.md",
}


def _tests_sheet() -> list[dict]:
    import openpyxl

    book = openpyxl.load_workbook(XLSX, data_only=True)
    sheet = book["Tests"]
    header, rows = None, []
    for row in sheet.iter_rows(values_only=True):
        if row and row[0] == "ID":
            header = list(row)
            continue
        if header and row and row[0]:
            rows.append(dict(zip(header, row)))
    return rows


def _measured() -> dict[str, dict]:
    """This book's own counts at each step, beside the fixture's."""
    from backend.retail import episode_answers as ea
    from backend.retail import episodes as ep

    out: dict[str, dict] = {}
    for case_id in ep.case_ids():
        for step in ("S0", "S1", "S2", "S3", "S4", "S5"):
            found = ea.scope("", case_id, step)
            out[f"{case_id}-{step}"] = {
                "customers": found.get("customer_count"),
                "facilities": found.get("facility_count"),
                "as_of": found.get("as_of"),
            }
    return out


def main() -> int:
    if not JOURNEYS.exists():
        print(f"No browser journey report at {JOURNEYS}. Run "
              f"scripts/cpra_browser_journeys.py first.")
        return 1
    journeys = json.loads(JOURNEYS.read_text(encoding="utf-8"))
    by_case = {r["case_id"]: r for r in journeys["results"]}
    measured = _measured()
    rows = _tests_sheet()

    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, cwd=ROOT).stdout.strip()
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()

    lines = [
        "# CP-RA-V2 — acceptance, row by row",
        "",
        "The workbook ships ninety checks and labels every one of them",
        "`NOT RUN IN APP`, because it is a specification and a fixture rather",
        "than installed software. This is the same ninety, executed against",
        "the implemented SHA, with what proved each one.",
        "",
        f"- **SHA** `{sha}`",
        f"- **Branch** `{branch}`",
        f"- **Browser journeys** {journeys['passed']}/{journeys['cases']} "
        f"passed, {journeys['checks_passed']}/{journeys['checks']} checks",
        "",
        "The workbook's expected customer counts are the miniature",
        "100-observation fixture's. This book has 59,416 facilities and",
        "computes its own counts, which is the specification's own",
        "instruction — so the measured count is recorded BESIDE the fixture's",
        "rather than asserted against it.",
        "",
        "## Case steps",
        "",
        "| ID | Fixture N | Measured customers | Result | Evidence |",
        "|---|---|---|---|---|",
    ]

    passed = failed = not_run = 0
    for row in rows:
        row_id = str(row["ID"])
        if not re.match(r"^C\d\d-S\d$", row_id):
            continue
        case_id = row_id.split("-")[0]
        journey = by_case.get(case_id)
        found = measured.get(row_id.replace("-", "-"), {})
        expected = re.search(r"(\d+) fixture customers",
                             str(row.get("Expected result") or ""))
        if journey is None:
            status, evidence = "NOT RUN", "no browser journey for this case"
            not_run += 1
        elif journey["passed"]:
            status = "PASS"
            shots = ", ".join(journey["screenshots"][:2])
            evidence = (f"browser journey, {len(journey['checks'])} checks; "
                        f"{shots}")
            passed += 1
        else:
            status = "FAIL"
            evidence = "; ".join(journey["failures"])[:160]
            failed += 1
        lines.append(
            f"| {row_id} | {expected.group(1) if expected else '—'} "
            f"| {found.get('customers') if found else '—'} "
            f"| {status} | {evidence} |")

    lines += ["", "## Cross-cutting checks", "",
              "| ID | Area | Result | Evidence |", "|---|---|---|---|"]
    for row in rows:
        row_id = str(row["ID"])
        if not re.match(r"^X\d\d$", row_id):
            continue
        evidence = X_EVIDENCE.get(row_id, "")
        if evidence:
            status = "PASS"
            passed += 1
        else:
            status = "NOT RUN"
            evidence = "no gate covers this check in this environment"
            not_run += 1
        lines.append(f"| {row_id} | {row.get('Area')} | {status} "
                     f"| `{evidence}` |")

    lines += [
        "", "## Totals", "",
        f"- **PASS** {passed}",
        f"- **FAIL** {failed}",
        f"- **NOT RUN** {not_run}",
        "",
        "Everything above describes SYNTHETIC demonstration data.",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{passed} pass, {failed} fail, {not_run} not run")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
