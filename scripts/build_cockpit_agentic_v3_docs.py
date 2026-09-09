#!/usr/bin/env python
"""Generate the Cockpit Agentic V3 reference documents from the code.

    COCKPIT_AGENTIC_V3=true python scripts/build_cockpit_agentic_v3_docs.py

The data dictionary, the machine-readable catalogue and the domain mapping are
GENERATED rather than written, so they cannot drift from what the runtime
actually exposes. A hand-written dictionary that disagrees with the catalogue
is worse than none: it is a document someone will trust.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.cockpit_agentic import CATALOG_VERSION, DATA_VERSION, DOMAIN, NOT_CLIENT_DATA, registry, store
from backend.cockpit_agentic import catalog as catalog_mod
from backend.cockpit_agentic import fields as F

DOCS = Path("docs")
OUT = DOCS / "cockpit_agentic_v3"

RELATION_TITLES = {
    F.CALENDAR: "Reporting calendar",
    F.FACILITY_QUARTER: "Facility position × reporting quarter (the wide view)",
    F.IFRS9_DETAIL: "Stored IFRS 9 scenario and term detail",
    F.BORROWER_FINANCIAL: "Borrower financial statements",
    F.RATING_RATIO: "Stored ratings and the forty ratios",
    F.QUALITATIVE: "The twenty qualitative questions",
    F.COLLATERAL: "Collateral assets",
    F.COLLATERAL_ALLOCATION: "Collateral allocation to positions",
    F.COVENANT: "Covenants and their tests",
    F.MACRO_WINDOW: "Macroeconomic window (the second time axis)",
    catalog_mod.MACRO_PIVOT: "Macroeconomic convenience pivot",
}


def dictionary(release: str) -> str:
    calendar = store.load_calendar(release)
    catalog = catalog_mod.build(dataset_release_id=release, calendar=calendar)
    summary = F.summary()

    lines = [
        "# The twenty-quarter Cockpit data dictionary",
        "",
        "**Generated** from `backend/cockpit_agentic/fields.py` by "
        "`scripts/build_cockpit_agentic_v3_docs.py`. Do not edit by hand: a "
        "dictionary that disagrees with the catalogue is a document someone "
        "will trust.",
        "",
        f"- Domain: `{DOMAIN}` — the only runtime business domain the Cockpit "
        f"can reach.",
        f"- Catalogue version: `{CATALOG_VERSION}`; data version "
        f"`{DATA_VERSION}`.",
        f"- Reporting quarters: **{len(calendar)}**, "
        f"{calendar.first} through {calendar.last}.",
        f"- Declared fields: **{summary['declared_fields']}**, of which "
        f"{summary['collateral_generated_columns']} are the twelve collateral "
        f"types × nine summary measures and "
        f"{summary['macro_pivot_cells']} are the ten macro factors × twenty "
        f"offsets.",
        f"- Unexpanded placeholders: **{summary['unexpanded_placeholders']}**. "
        f"Every generated name is a real column that resolves.",
        "",
        NOT_CLIENT_DATA,
        "",
        "## What the counts are",
        "",
        "| | |",
        "|---|---:|",
        f"| Relations | {summary['relations']} |",
        f"| Common keys (on every relation) | {summary['common_keys']} |",
        f"| Columns on the wide facility view | "
        f"{summary['facility_quarter_columns']} |",
        f"| Financial ratios | {summary['ratios']} |",
        f"| Rating grades | {summary['rating_grades']} |",
        f"| Qualitative questions | {summary['qualitative_questions']} |",
        f"| Collateral types | {summary['collateral_types']} |",
        f"| Macro factors | {summary['macro_factors']} |",
        "",
        "## The two time axes",
        "",
        "The twenty reporting quarters are historical or current observations "
        "of the book, and they are the only reporting periods reachable. "
        "Separately, for EACH reporting quarter, the macro block has its own "
        "window of twenty positions from `quarter_offset` −4 to +15. That is "
        "a second axis, not fifteen more observed quarters.",
        "",
        f"At the {calendar.last} anchor the macro window runs "
        f"{calendar.macro_window(calendar.last)[0][1]} through "
        f"{calendar.macro_window(calendar.last)[-1][1]}. Across all twenty "
        f"anchors the union is {len(calendar.macro_targets())} distinct target "
        f"quarters — and the reporting calendar is still twenty. A positive "
        f"offset is a FORECAST made at that anchor, never observed future "
        f"data.",
        "",
        "## The rating scale",
        "",
        "Nineteen grades. `rating_rank` 1 is AAA and 19 is C; a LARGER rank is "
        "a WEAKER grade, so an improving rating is a falling rank. There is no "
        "CCC+, no CCC− and no D. `default_flag` is a separate field and grade "
        "C is not mechanically default.",
        "",
        "`" + " → ".join(F.RATING_SCALE) + "`",
        "",
        "## The forty ratios",
        "",
        "These are DATA SEMANTICS — what a stored or derived number means, so "
        "a reader can tell whether two of them are comparable. They are not an "
        "analysis anything is required to perform, and no code in the answer "
        "path consumes them as formulas. Each has a `<name>_source_value` "
        "holding the source's own figure where it differs, and a "
        "`<name>_status` saying whether it is source, derived, unavailable, "
        "invalid because the denominator is zero or negative, or incomparable "
        "because the period bases differ.",
        "",
        "| # | Field | Definition | Unit |",
        "|---:|---|---|---|",
    ]
    for number, name, definition, unit in F.RATIO_DEFINITIONS:
        lines.append(f"| {number} | `{name}` | {definition} | {unit} |")

    lines += [
        "",
        "## The twenty qualitative questions",
        "",
        "Observed assessment data. Neither model invents an answer, and the "
        "Cockpit does not turn them into a credit score.",
        "",
        "| ID | Field | Question |",
        "|---|---|---|",
    ]
    for qid, field_name, question in F.QUALITATIVE_QUESTIONS:
        lines.append(f"| {qid} | `{field_name}` | {question} |")

    lines += [
        "",
        "## The ten macro factors",
        "",
        "| # | Factor | Meaning | Unit |",
        "|---:|---|---|---|",
    ]
    for i, (fid, meaning, unit) in enumerate(F.MACRO_FACTORS, start=1):
        lines.append(f"| {i} | `{fid}` | {meaning} | {unit} |")

    lines += [
        "",
        "## Joins, and what they multiply",
        "",
        "| From | To | On | Cardinality | Warning |",
        "|---|---|---|---|---|",
    ]
    for join in F.JOINS:
        lines.append(
            f"| `{join['left']}` | `{join['right']}` | "
            f"{', '.join('`%s`' % o for o in join['on'])} | "
            f"{join['cardinality']} | {join['warning']} |")

    lines += ["", "## Every relation, field by field", ""]
    for relation in catalog_mod.QUERYABLE_RELATIONS:
        specs = (F.MACRO_PIVOT_FIELDS
                 if relation == catalog_mod.MACRO_PIVOT
                 else F.fields_of(relation))
        lines += [
            f"### `{relation}` — {RELATION_TITLES.get(relation, '')}",
            "",
            f"**Grain:** {F.GRAIN.get(relation, 'one row per anchor, geography and scenario')}",
            "",
            f"{len(specs)} columns.",
            "",
        ]
        if relation == catalog_mod.MACRO_PIVOT:
            lines += [
                "Generated as `<factor_id>_<offset_suffix>` for each of the ten "
                "factors and each of the twenty offsets `lag4`…`lag1`, "
                "`current`, `lead1`…`lead15`. Two hundred value CELLS per row, "
                "not two hundred factors, and they add no reporting quarter. "
                "Every one resolves through the catalogue.",
                "",
            ]
            continue
        lines += ["| Column | Type | Unit | Aggregation | Definition |",
                  "|---|---|---|---|---|"]
        for spec in specs:
            definition = spec.definition.replace("|", "\\|")
            lines.append(
                f"| `{spec.name}` | {spec.dtype} | {spec.unit or '—'} | "
                f"{spec.aggregation} | {definition} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def mapping(release: str) -> str:
    calendar = store.load_calendar(release)
    manifest = store.read_manifest(release)
    coverage_path = OUT / "evidence/coverage_profile_summary.json"
    coverage = (json.loads(coverage_path.read_text())
                if coverage_path.exists() else {})

    lines = [
        "# Cockpit data domain mapping — actual, demo and unavailable",
        "",
        "**Generated** by `scripts/build_cockpit_agentic_v3_docs.py`.",
        "",
        "Every field in this domain is currently `demo_only`: this release is "
        "the labelled synthetic demonstration and **no field is populated "
        "from a real source**. That is the honest statement of where this "
        "stands, and it is what the availability column in the catalogue says "
        "too. Schema existence is not population.",
        "",
        NOT_CLIENT_DATA,
        "",
        "## The release",
        "",
        f"- Release: `{release}`, built {manifest['built_at']}.",
        f"- Origin: `{manifest['origin']}`.",
        f"- Reporting quarters: {len(calendar)} "
        f"({calendar.first}…{calendar.last}).",
        f"- Populated: {len(calendar.populated)}. "
        f"Missing: {len(calendar.missing) or 'none'}.",
        "",
        "## Rows per relation",
        "",
        "| Relation | Rows | Columns |",
        "|---|---:|---:|",
    ]
    for name, block in manifest["relations"].items():
        lines.append(f"| `{name}` | {block['rows']:,} | {block['columns']} |")

    lines += [
        "",
        "## Coverage, measured over the whole release",
        "",
        "Measured by `backend/cockpit_agentic/profile.py` from every row, not "
        "from the ten preview rows the model is shown. Both denominators are "
        "kept apart, and any field entirely absent from a quarter is surfaced "
        "whatever its overall rate — that is the case a low global rate would "
        "otherwise hide.",
        "",
    ]
    if coverage:
        lines += [
            f"- Fields with full coverage: "
            f"{coverage.get('fields_with_full_coverage', '—')}",
            f"- Fields with some missingness: "
            f"{sum(len(v) for v in coverage.get('fields_with_gaps', {}).values())}",
            "",
            "The complete profile is rebuilt with the release; "
            "`docs/cockpit_agentic_v3/evidence/coverage_profile_summary.json` "
            "carries the bounded form.",
            "",
        ]

    lines += [
        "## What a real ingestion would have to supply",
        "",
        "Every field in the dictionary carries `source_name`, `lineage`, "
        "`availability` and `missing_reason`. To ingest real data, each "
        "declared field needs a source relation and column, a transformation, "
        "its unit, its source timing, and the quarters it actually populates. "
        "Fields no source supplies stay `unavailable` and the ratios that "
        "depend on them report `unavailable` rather than being computed from "
        "a substitute.",
        "",
        "Ingestion admits only this domain's declared target fields. An extra "
        "uploaded column is not exposed: `generate.conform` removes any column "
        "the dictionary does not declare, and there is a test that asserts no "
        "relation exposes an undeclared column.",
        "",
    ]
    return "\n".join(lines) + "\n"


def boundaries() -> str:
    verification = registry.verify_routes()
    lines = [
        "# Cockpit functionality boundaries — verified",
        "",
        "**Generated** by `scripts/build_cockpit_agentic_v3_docs.py` from "
        "`backend/cockpit_agentic/registry.py`, whose routes are asserted "
        "against `frontend/src/lib/navigation.ts` rather than claimed.",
        "",
        f"Routes verified: **{verification['verified']}**.",
        "",
        "| Functionality | Label a user sees | Route | Enabled |",
        "|---|---|---|---|",
    ]
    for item in registry.ENTRIES:
        result = verification["results"][item.functionality_id]
        route = f"`{item.route}`" if item.enabled else "— none —"
        lines.append(
            f"| `{item.functionality_id}` | {item.ui_label} | {route} | "
            f"{'yes' if item.enabled else 'NO'} |")

    lines += [
        "",
        "## Two places the product differs from the specification's names",
        "",
        "**Credit Scoring has no module in this deployment.** There is no "
        "`/credit-scoring` route and nothing that assigns a borrower a new "
        "score. `backend/scorecard/` builds and fits scorecards and "
        "`/scorecard-validation` monitors them; neither originates a score. "
        "The registry keeps the ownership exclusion — the Cockpit still "
        "refuses to generate a score — and says honestly that the owning "
        "workflow is unavailable rather than routing score generation to a "
        "validation-only screen.",
        "",
        "**What-if Analysis ships as \"Stress Testing\" at `/stress`.** The "
        "registry uses the label a user will actually find in the menu. "
        "Referring someone to \"What-if Analysis\" would send them looking "
        "for something that is not there.",
        "",
        "## Ownership, entry by entry",
        "",
    ]
    for item in registry.ENTRIES:
        lines += [
            f"### {item.ui_label} (`{item.functionality_id}`)",
            "",
            item.description,
            "",
            "**Owns:**",
            "",
        ]
        lines += [f"- {x}" for x in item.owns]
        lines += ["", "**Does not own:**", ""]
        lines += [f"- {x}" for x in item.excludes]
        if item.examples:
            lines += ["", "**Belongs here:**", ""]
            lines += [f"- “{x}”" for x in item.examples]
        if item.counterexamples:
            lines += ["", "**Does not belong here:**", ""]
            lines += [f"- “{x}”" for x in item.counterexamples]
        if not item.enabled:
            lines += ["", f"**Unavailable:** {item.unavailable_reason}"]
        lines.append("")

    lines += [
        "## The rules the gate applies",
        "",
        f"- {registry.compact()['rule']}",
        f"- {registry.compact()['coverage_rule']}",
        f"- {registry.compact()['referral_rule']}",
        f"- {registry.compact()['mixed_scope_rule']}",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    release = sys.argv[1] if len(sys.argv) > 1 else "demo-20q-v1"
    OUT.mkdir(parents=True, exist_ok=True)

    calendar = store.load_calendar(release)
    catalog = catalog_mod.build(dataset_release_id=release, calendar=calendar)

    written = {
        DOCS / "COCKPIT_20_QUARTER_DATA_DICTIONARY.md": dictionary(release),
        DOCS / "COCKPIT_DATA_DOMAIN_MAPPING.md": mapping(release),
        DOCS / "COCKPIT_FUNCTIONALITY_BOUNDARIES.md": boundaries(),
    }
    for path, text in written.items():
        path.write_text(text)
        print(f"  {path} ({len(text):,} characters)")

    machine = OUT / "field_catalogue.json"
    machine.write_text(json.dumps(catalog.to_dict(), indent=2, default=str))
    print(f"  {machine} ({machine.stat().st_size:,} bytes)")

    compact = OUT / "field_catalogue_compact.json"
    compact.write_text(json.dumps(catalog.compact(), indent=2, default=str))
    print(f"  {compact} ({compact.stat().st_size:,} bytes) — what Opus is sent")

    sizes = OUT / "context_sizes.json"
    sizes.write_text(json.dumps(
        {"catalogue": catalog.sizes(), "summary": F.summary()}, indent=2))
    print(f"  {sizes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
