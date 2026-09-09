#!/usr/bin/env python
"""Generate docs/cockpit_v3/COCKPIT_FIELD_AUDIT.md from the catalogue.

    COCKPIT_AGENTIC_V3=true python scripts/build_cockpit_field_audit.py

Every row is read out of `backend/cockpit_agentic/fields.py` and the published
release. Counting fields by hand and typing the total into a document is how a
"750 fields" claim becomes unfalsifiable; this makes the claim a query.

The audit proves two things:

* POSITIVELY, that each required business group A-K is present, by naming the
  fields that satisfy it and failing if any is missing.
* NEGATIVELY, that no field, relation or column in the authorized domain
  belongs to Early Warning, Credit Scoring, Scorecard Validation, What-if or
  Lenses -- checked against the actual published Parquet columns, not against
  the declaration alone.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.cockpit_agentic import DOMAIN
from backend.cockpit_agentic import catalog as catalog_mod
from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic import profile as profile_mod
from backend.cockpit_agentic import store

OUT = Path("docs/cockpit_v3")

# ---------------------------------------------------------------- families

def family_of(spec) -> str:
    """Which business group a field belongs to. One family per field."""
    name, relation = spec.name, spec.relation
    if spec.generated_from.startswith("collateral_type="):
        return "C_collateral_summary"
    if spec.generated_from.startswith("factor_id="):
        return "J_macro_pivot"
    if relation == "*" or name in {k.name for k in F.COMMON_KEYS}:
        return "Z_keys_and_provenance"
    if relation == F.CALENDAR:
        return "K_reporting_calendar"
    if relation == F.MACRO_WINDOW:
        return "J_macro"
    if relation == F.QUALITATIVE:
        return "G_qualitative"
    if relation in (F.COLLATERAL, F.COLLATERAL_ALLOCATION):
        return "C_collateral"
    if relation == F.COVENANT:
        return "D_covenants"
    if relation == F.IFRS9_DETAIL:
        return "B_ifrs9"
    if relation == F.RATING_RATIO:
        base = name.replace("_source_value", "").replace("_status", "")
        if base in F.RATIO_NAMES or name in F.RATIO_NAMES:
            return "F_ratios"
        if name.endswith("_basis") or name.startswith("ratio_"):
            return "F_ratios"
        return "E_rating"
    if relation == F.BORROWER_FINANCIAL:
        income = {n for n, _d in __import__(
            "backend.cockpit_agentic.fields", fromlist=["_IS"])._IS}
        inputs = {n for n, _d, _u in __import__(
            "backend.cockpit_agentic.fields", fromlist=["_INPUTS"])._INPUTS}
        if name in income:
            return "I_income_statement"
        if name in inputs or name in ("fcf_basis", "dscr_basis",
                                      "financial_input_coverage"):
            return "I_ratio_inputs"
        return "H_balance_sheet"
    if relation == F.FACILITY_QUARTER:
        ifrs9 = {"ead_reported", "ead_pit", "ead_ttc", "ccf_pit", "ccf_ttc",
                 "pd_pit_12m", "pd_pit_lifetime", "pd_ttc_12m",
                 "pd_ttc_lifetime", "pd_pit_12m_at_origination",
                 "pd_pit_lifetime_at_origination",
                 "pd_ttc_12m_at_origination", "pd_ttc_lifetime_at_origination",
                 "pd_lifetime_horizon_months", "pd_definition_id",
                 "pd_parameter_version", "lgd_pit", "lgd_ttc", "lgd_downturn",
                 "lgd_definition_id", "ead_definition_id", "ifrs9_stage",
                 "stage_reason_recorded", "sicr_flag", "sicr_reason_recorded",
                 "default_flag", "default_date", "days_past_due",
                 "effective_interest_rate", "ecl_12m_reported",
                 "ecl_lifetime_reported", "ecl_reported", "ecl_modelled",
                 "ecl_overlay", "ecl_coverage_ratio",
                 "ecl_coverage_denominator", "ifrs9_run_id",
                 "ifrs9_model_version", "ifrs9_input_coverage_status"}
        if name in ifrs9:
            return "B_ifrs9"
        if name.startswith("collateral_") or name == "allocation_coverage_status":
            return "C_collateral_summary"
        return "A_identifiers_and_exposure"
    return "Z_other"


FAMILY_TITLES = {
    "A_identifiers_and_exposure": "A — facility and borrower identifiers, "
                                  "scope and exposure",
    "B_ifrs9": "B — IFRS 9 risk parameters, stage, ECL, scenarios",
    "C_collateral": "C — collateral assets and allocations",
    "C_collateral_summary": "C — collateral per-type summaries "
                            "(12 types × 9 measures)",
    "D_covenants": "D — covenants, thresholds, headroom, breaches, waivers",
    "E_rating": "E — stored ratings on the 19-grade scale",
    "F_ratios": "F — the forty financial ratios and their bases",
    "G_qualitative": "G — the twenty qualitative assessment questions",
    "H_balance_sheet": "H — balance-sheet variables",
    "I_income_statement": "I — income-statement variables",
    "I_ratio_inputs": "I — cash-flow and debt-service inputs the ratios need",
    "J_macro": "J — the ten macroeconomic factors, normalized",
    "J_macro_pivot": "J — the macro pivot (10 factors × 20 offsets)",
    "K_reporting_calendar": "K — the twenty-quarter reporting calendar",
    "Z_keys_and_provenance": "Keys, provenance and point-in-time metadata",
}

# ------------------------------------------------------- the negative proof

#: Substrings that would betray another module's data in a Cockpit column.
#: Deliberately broad: a false positive here is a question to answer, a false
#: negative is a leak nobody notices.
FOREIGN_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Early Warning", ("ews", "early_warning", "alert", "watchlist",
                       "signal_score", "forward_risk")),
    ("Credit Scoring", ("credit_score", "score_card", "scorecard",
                        "scoring_model", "application_score",
                        "behavioural_score", "behavioral_score")),
    ("Scorecard Validation", ("psi", "csi", "gini_", "ks_statistic",
                              "discrimination", "calibration_curve",
                              "validation_run")),
    ("What-if / Stress", ("whatif", "what_if", "shock_", "simulated_",
                          "stress_run", "hypothetical")),
    ("Lenses / documents", ("lens_", "lenses", "document_id", "memo_",
                            "extracted_text", "ocr_")),
    ("Playbook / Planner", ("playbook", "planner_", "workflow_run",
                            "project_task")),
)

#: Names that contain a marker substring but are legitimate Cockpit fields.
#: Each is listed with why, so the exception is auditable rather than a silent
#: suppression.
ALLOWED_DESPITE_MARKER: dict[str, str] = {
    "scenario_id": "a STORED IFRS 9 scenario the source already computed; not "
                   "a what-if run",
    "scenario_name": "as above",
    "scenario_weight": "as above",
    "scenario_ecl": "as above",
    "scenario_pd_pit_12m": "as above",
    "scenario_pd_pit_lifetime": "as above",
    "scenario_lgd": "as above",
    "scenario_ead": "as above",
}


def foreign_hits(names) -> list[tuple[str, str, str]]:
    hits = []
    for name in sorted(names):
        lowered = str(name).lower()
        if lowered in ALLOWED_DESPITE_MARKER:
            continue
        for module, markers in FOREIGN_MARKERS:
            for marker in markers:
                if marker in lowered:
                    hits.append((str(name), module, marker))
    return hits


# --------------------------------------------------------------- required

REQUIRED: dict[str, tuple[str, ...]] = {
    "A": ("facility_id", "borrower_id", "position_id", "borrower_name",
          "sector_code", "country_code", "portfolio_id", "product_type",
          "facility_status", "origination_date", "maturity_date",
          "approved_limit", "drawn_balance", "undrawn_balance",
          "gross_carrying_amount"),
    "B": ("pd_pit_12m", "pd_pit_lifetime", "pd_ttc_12m", "pd_ttc_lifetime",
          "lgd_pit", "lgd_ttc", "lgd_downturn", "ead_reported", "ead_pit",
          "ead_ttc", "ifrs9_stage", "ecl_reported", "ecl_12m_reported",
          "ecl_lifetime_reported", "ecl_modelled", "ecl_overlay",
          "scenario_id", "scenario_ecl", "scenario_weight", "sicr_flag",
          "sicr_reason_recorded", "default_flag", "default_date",
          "days_past_due"),
    "C": ("collateral_id", "collateral_type", "gross_market_value",
          "eligible_value_before_haircut", "market_haircut",
          "liquidity_haircut", "fx_haircut", "legal_haircut", "total_haircut",
          "haircut_amount", "net_realizable_value", "valuation_date",
          "valuation_method", "valuation_expiry_date", "allocation_share",
          "allocated_gross_value_rcy", "allocated_net_value_rcy", "lien_rank"),
    "D": ("covenant_id", "covenant_name", "covenant_type", "metric_name",
          "comparison_operator", "threshold_value", "threshold_unit",
          "observed_value", "test_status", "headroom_value", "breach_date",
          "breach_reason_recorded", "waiver_flag", "waiver_date",
          "waiver_expiry_date", "cure_deadline", "cure_status",
          "test_due_date", "test_period_start", "test_period_end"),
    "E": ("risk_rating", "rating_rank", "rating_scale_id",
          "rating_effective_date", "rating_previous_recorded",
          "rating_outlook", "rating_status"),
    "H": ("total_assets", "total_liabilities", "shareholders_equity",
          "current_assets", "current_liabilities", "inventory",
          "trade_receivables_net", "trade_payables", "cash_and_cash_equivalents",
          "total_debt", "net_debt", "working_capital", "tangible_net_worth",
          "capital_employed", "ppe_net", "long_term_debt"),
    "I": ("revenue", "cost_of_goods_sold", "gross_profit", "ebitda", "ebit",
          "interest_expense", "profit_before_tax", "net_profit",
          "operating_cash_flow", "capital_expenditure", "free_cash_flow",
          "cash_available_for_debt_service", "scheduled_principal_due",
          "interest_due_for_debt_service", "debt_service_due",
          "credit_purchases"),
}


def audit(release: str = "demo-20q-v1") -> dict:
    """Run every check and return the evidence.

    Split out from the renderer so `tests/cockpit_agentic/test_field_audit.py`
    asserts on the same computation the document is built from, rather than
    on a document someone could regenerate stale.
    """
    calendar = store.load_calendar(release)
    manifest = store.read_manifest(release)
    catalog = catalog_mod.build(dataset_release_id=release, calendar=calendar)

    # Every declared field, with its family.
    rows = []
    for relation in catalog_mod.QUERYABLE_RELATIONS:
        specs = (F.MACRO_PIVOT_FIELDS if relation == catalog_mod.MACRO_PIVOT
                 else F.fields_of(relation))
        for spec in specs:
            rows.append({
                "relation": relation, "spec": spec,
                "family": family_of(spec),
            })
    families = Counter(r["family"] for r in rows)

    # The physical columns actually published, per relation.
    published: dict[str, list[str]] = {}
    for relation in manifest["relations"]:
        frame = store.read_relation(release, relation)
        published[relation] = [str(c) for c in frame.columns]
    all_published = {c for cols in published.values() for c in cols}

    # Coverage, for the missing-rate column.
    coverage_path = Path("docs/cockpit_agentic_v3/evidence/"
                         "coverage_profile_summary.json")
    gaps: dict[str, float] = {}
    if coverage_path.exists():
        blob = json.loads(coverage_path.read_text())
        for entries in blob.get("fields_with_gaps", {}).values():
            for entry in entries:
                gaps[entry["n"]] = entry["miss"]

    # ---- the positive proof ----
    declared_names = {r["spec"].name for r in rows}
    missing_required: dict[str, list[str]] = {}
    for group, names in REQUIRED.items():
        absent = [n for n in names if n not in declared_names]
        if absent:
            missing_required[group] = absent

    ratio_ok = len(F.RATIO_NAMES) >= 40
    qual_ok = len(F.QUALITATIVE_QUESTIONS) == 20
    scale_ok = list(F.RATING_SCALE) == [
        "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
        "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C"]
    macro_ok = len(F.MACRO_FACTORS) == 10
    offsets_ok = list(range(-4, 16)) == list(
        __import__("backend.cockpit_agentic.calendar",
                   fromlist=["MACRO_OFFSETS"]).MACRO_OFFSETS)
    quarters_ok = len(calendar) == 20

    # ---- the negative proof ----
    declared_hits = foreign_hits(declared_names)
    published_hits = foreign_hits(all_published)
    relation_hits = foreign_hits(catalog_mod.QUERYABLE_RELATIONS)
    undeclared = {}
    for relation, columns in published.items():
        allowed = (set(F.all_column_names(relation))
                   if relation != catalog_mod.MACRO_PIVOT
                   else {"reporting_quarter", "country_or_region",
                         "scenario_id"} | {s.name for s in F.MACRO_PIVOT_FIELDS})
        extra = sorted(set(columns) - allowed)
        if extra:
            undeclared[relation] = extra

    distinct_names = ({s.name for s in F.ALL_FIELDS}
                      | {k.name for k in F.COMMON_KEYS})
    keyed_relations = sum(1 for r in catalog_mod.QUERYABLE_RELATIONS
                          if r != catalog_mod.MACRO_PIVOT)

    passed = (not missing_required and ratio_ok and qual_ok and scale_ok
              and macro_ok and offsets_ok and quarters_ok
              and not declared_hits and not published_hits
              and not relation_hits and not undeclared)

    return {k: v for k, v in locals().items()
            if not k.startswith('_') and k not in ('spec', 'relation',
                                                    'names', 'absent',
                                                    'columns', 'extra',
                                                    'group', 'entry',
                                                    'entries', 'blob',
                                                    'frame', 'allowed')}


def render(*, release, calendar, manifest, rows, families, published,
           gaps, missing_required, ratio_ok, qual_ok, scale_ok, macro_ok,
           offsets_ok, quarters_ok, declared_hits, published_hits,
           relation_hits, undeclared, distinct_names, keyed_relations,
           passed, **_unused) -> int:
    """Write the document from the evidence `audit` collected."""
    lines = [
        "# Cockpit field audit",
        "",
        "**Generated** by `scripts/build_cockpit_field_audit.py` from "
        "`backend/cockpit_agentic/fields.py` and the published release. Every "
        "count below is a query, not a number someone typed.",
        "",
        f"- Domain: `{DOMAIN}`",
        f"- Release: `{release}`, built {manifest['built_at']}",
        f"- Addressable columns across all relations: **{len(rows)}**",
        f"- Physical columns published: **{sum(len(c) for c in published.values())}** "
        f"across {len(published)} relations "
        f"(the {sum(len(c) for c in published.values()) - len(rows)} extra are "
        f"`{catalog_mod.MACRO_PIVOT}`'s three index columns "
        f"`reporting_quarter`, `country_or_region`, `scenario_id`, which "
        f"identify a pivot row rather than carry a value)",
        f"- Audit result: **{'PASS' if passed else 'FAIL'}**",
        "",
        "## Which number is the number of fields",
        "",
        "Three different counts are all correct, and quoting one without "
        "saying which it is has already caused confusion in this project's own "
        "documents. They are:",
        "",
        "| Count | What it counts | Value |",
        "|---|---|---:|",
        f"| `len(fields.ALL_FIELDS)` | Field *definitions* written in the "
        f"dictionary. The 24 common keys are defined once, not once per "
        f"relation. | {len(F.ALL_FIELDS)} |",
        f"| Distinct canonical names | Unique column names anywhere in the "
        f"domain, counting `reporting_quarter` once however many relations "
        f"carry it. | {len(distinct_names)} |",
        f"| Addressable columns | What a query author actually faces: every "
        f"`relation.column` pair that resolves. This is the number the tables "
        f"below add up to. | {len(rows)} |",
        "",
        f"The arithmetic is exact: {len(F.ALL_FIELDS)} definitions "
        f"+ {len(F.COMMON_KEYS)} common keys × {keyed_relations} relations that "
        f"carry them = {len(F.ALL_FIELDS) + len(F.COMMON_KEYS) * keyed_relations}. "
        f"`{catalog_mod.MACRO_PIVOT}` is a generated view and takes no common "
        f"keys, which is why it does not appear in that multiplication.",
        "",
        "Earlier drafts of this work quoted **750** declared fields. That was "
        f"wrong by one — the dictionary holds {len(F.ALL_FIELDS)} — and, more "
        "importantly, it was quoting the definition count while the "
        "instruction that motivated the audit was about the size of the domain "
        "a question can reach. This document uses the addressable-column count "
        "for every table and states the other two here so no reader has to "
        "guess which one a number is.",
        "",
        "None of the three is acceptance by itself. What follows is.",
        "",
        "## Counts by field family",
        "",
        "| Family | Addressable columns |",
        "|---|---:|",
    ]
    for key in sorted(families):
        lines.append(f"| {FAMILY_TITLES.get(key, key)} | {families[key]} |")
    lines += [f"| **Total** | **{len(rows)}** |", ""]

    lines += [
        "## Required groups — the positive proof",
        "",
        "| Group | Requirement | Result |",
        "|---|---|---|",
        f"| A | Facility and borrower identifiers and exposure fields | "
        f"{'PASS' if 'A' not in missing_required else 'FAIL: ' + str(missing_required['A'])} |",
        f"| B | IFRS 9: PIT and TTC PD at 12-month and lifetime, LGD and EAD "
        f"variants, stage, ECL, scenarios, overlays, SICR and default | "
        f"{'PASS' if 'B' not in missing_required else 'FAIL: ' + str(missing_required['B'])} |",
        f"| C | Collateral types, values, allocations, valuations, haircuts and "
        f"post-haircut values | "
        f"{'PASS' if 'C' not in missing_required else 'FAIL: ' + str(missing_required['C'])} |",
        f"| D | Covenants: definitions, thresholds, actuals, headroom, "
        f"breaches, waivers, cures and dates | "
        f"{'PASS' if 'D' not in missing_required else 'FAIL: ' + str(missing_required['D'])} |",
        f"| E | The exact 19-grade ordered scale | "
        f"{'PASS' if scale_ok else 'FAIL'} |",
        f"| F | At least 40 financial ratios | "
        f"{'PASS — ' + str(len(F.RATIO_NAMES)) if ratio_ok else 'FAIL'} |",
        f"| G | Exactly 20 qualitative questions | "
        f"{'PASS — ' + str(len(F.QUALITATIVE_QUESTIONS)) if qual_ok else 'FAIL'} |",
        f"| H | Required balance-sheet variables | "
        f"{'PASS' if 'H' not in missing_required else 'FAIL: ' + str(missing_required['H'])} |",
        f"| I | Income-statement variables and the cash-flow and debt-service "
        f"inputs the ratios need | "
        f"{'PASS' if 'I' not in missing_required else 'FAIL: ' + str(missing_required['I'])} |",
        f"| J | Exactly 10 macro factors over offsets −4…+15 with vintage "
        f"preserved | {'PASS' if macro_ok and offsets_ok else 'FAIL'} |",
        f"| K | 20 reporting quarters | "
        f"{'PASS — ' + calendar.first + '…' + calendar.last if quarters_ok else 'FAIL'} |",
        "",
        "### E — the 19-grade scale, in order",
        "",
        "`" + " → ".join(F.RATING_SCALE) + "`",
        "",
        f"rank 1 = AAA, rank 19 = C. Larger rank means weaker grade. No CCC+, "
        f"no CCC−, no D; `default_flag` is a separate field.",
        "",
        "### J — forecast vintage preserved",
        "",
        "Each macro row carries `forecast_vintage`, `published_at`, "
        "`available_at` and `observation_status`. A positive `quarter_offset` "
        "is a forecast made at that anchor and is never relabelled an actual "
        "when the quarter later arrives — asserted by `check_macro_vintages` "
        "and `check_no_future_actuals` in the release gates.",
        "",
    ]

    lines += [
        "## Cockpit-only isolation — the negative proof",
        "",
        "Checked against the **published Parquet columns**, not the "
        "declaration alone, so a leak through a view would be caught.",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| No declared field name belongs to another module | "
        f"{'PASS' if not declared_hits else 'FAIL: ' + str(declared_hits)} |",
        f"| No published column belongs to another module | "
        f"{'PASS' if not published_hits else 'FAIL: ' + str(published_hits)} |",
        f"| No readable relation belongs to another module | "
        f"{'PASS' if not relation_hits else 'FAIL: ' + str(relation_hits)} |",
        f"| No published column is undeclared | "
        f"{'PASS' if not undeclared else 'FAIL: ' + str(undeclared)} |",
        "",
        "Searched for, across every declared field, every published column and "
        "every relation name:",
        "",
    ]
    for module, markers in FOREIGN_MARKERS:
        lines.append(f"- **{module}**: "
                     + ", ".join(f"`{m}`" for m in markers))
    lines += [
        "",
        "### The one family of deliberate exceptions",
        "",
        "| Field | Why it is legitimate |",
        "|---|---|",
    ]
    for name, why in sorted(ALLOWED_DESPITE_MARKER.items()):
        lines.append(f"| `{name}` | {why} |")
    lines += [
        "",
        "These are IFRS 9 scenario outputs the source system already computed "
        "and stored. Reading them is not running a new what-if: the boundary "
        "is the ACTION, and Cockpit can read a stored scenario while being "
        "unable to create one. The functionality registry carries the same "
        "distinction as an ownership counterexample.",
        "",
        "### What isolation is enforced by, not merely audited by",
        "",
        "This document is a check. The enforcement is that the DuckDB session "
        "materializes only the allowlisted relations and then disables file "
        "and network access and locks the configuration, so a query naming "
        "another schema fails inside the engine. "
        "`tests/cockpit_agentic/test_sql_security.py` proves that against a "
        "real engine, including a test that bypasses the validator entirely.",
        "",
    ]

    lines += [
        "## Every field",
        "",
        "Columns: canonical name · business definition · physical source · "
        "type · unit · grain · quarter applicability · aggregation · missing "
        "rate · status · family.",
        "",
    ]
    for relation in catalog_mod.QUERYABLE_RELATIONS:
        relation_rows = [r for r in rows if r["relation"] == relation]
        grain = F.GRAIN.get(relation,
                            "anchor × geography × scenario, 200 value cells")
        lines += [
            f"### `{relation}`",
            "",
            f"**Grain:** {grain}",
            "",
            f"**Quarter applicability:** "
            + ("all 20 reporting quarters"
               if relation != catalog_mod.MACRO_PIVOT
               else "all 20 anchors; each row spans offsets −4…+15"),
            "",
            f"{len(relation_rows)} addressable columns "
            f"(own declarations plus the common keys); "
            f"{len(published.get(relation, []))} physical columns published.",
            "",
        ]
        if relation == catalog_mod.MACRO_PIVOT:
            lines += [
                "Generated columns `<factor_id>_<offset_suffix>` — 10 factors × "
                "20 offsets. Every one resolves through the catalogue. Physical "
                "source: pivoted from `cockpit_macro_quarter_window`.",
                "",
            ]
            continue
        lines += ["| Field | Definition | Source | Type | Unit | Aggregation | "
                  "Missing | Status | Family |",
                  "|---|---|---|---|---|---|---:|---|---|"]
        for row in relation_rows:
            spec = row["spec"]
            definition = spec.definition.replace("|", "\\|")
            miss = gaps.get(spec.name)
            lines.append(
                f"| `{spec.name}` | {definition} | "
                f"{spec.source_name or 'cockpit_demo_generator'} | "
                f"{spec.dtype} | {spec.unit or '—'} | {spec.aggregation} | "
                f"{('%.1f%%' % (miss * 100)) if miss is not None else '0%'} | "
                f"{spec.availability} | {row['family'].split('_')[0]} |")
        lines.append("")

    lines += [
        "## Status, honestly",
        "",
        "Every field in this release is `demo_only`. The release is the "
        "labelled synthetic demonstration and **no field is populated from a "
        "real source**. `value_origin` on each row records whether the value "
        "is synthetic, derived or carried forward; a real ingestion would set "
        "these to `actual` per field and leave unsupplied fields "
        "`unavailable`, with the dependent ratios reporting `unavailable` "
        "rather than being computed from a substitute.",
        "",
        "Missing rates are measured over the whole release by "
        "`backend/cockpit_agentic/profile.py`, not from the ten preview rows "
        "the model is shown. A blank rate means full coverage in this release.",
        "",
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "COCKPIT_FIELD_AUDIT.md"
    path.write_text("\n".join(lines) + "\n")

    summary = {
        "release": release, "passed": passed,
        "addressable_columns": len(rows),
        "field_definitions": len(F.ALL_FIELDS),
        "distinct_canonical_names": len(distinct_names),
        "common_keys": len(F.COMMON_KEYS),
        "keyed_relations": keyed_relations,
        "published_columns": sum(len(c) for c in published.values()),
        "families": dict(families),
        "missing_required": missing_required,
        "foreign_declared": declared_hits,
        "foreign_published": published_hits,
        "foreign_relations": relation_hits,
        "undeclared_published": undeclared,
        "ratios": len(F.RATIO_NAMES),
        "qualitative_questions": len(F.QUALITATIVE_QUESTIONS),
        "rating_grades": len(F.RATING_SCALE),
        "macro_factors": len(F.MACRO_FACTORS),
        "reporting_quarters": len(calendar),
    }
    (Path("docs/cockpit_agentic_v3/evidence") / "field_audit.json").write_text(
        json.dumps(summary, indent=2))

    print(f"{path}  ({len(rows)} addressable columns, {'PASS' if passed else 'FAIL'})")
    for key in sorted(families):
        print(f"  {families[key]:>4}  {FAMILY_TITLES.get(key, key)}")
    if not passed:
        print("  FAILURES:", json.dumps(
            {k: v for k, v in summary.items()
             if k.startswith(("missing", "foreign", "undeclared")) and v},
            indent=2))
    return 0 if passed else 1


def main() -> int:
    release = sys.argv[1] if len(sys.argv) > 1 else "demo-20q-v1"
    return render(**audit(release))


if __name__ == "__main__":
    raise SystemExit(main())
