#!/usr/bin/env python
"""
Build the analytical data lake from the raw source workbook.

    python scripts/build_data_lake.py

What this does, in plain English
--------------------------------
The bank's data arrives as a spreadsheet. Spreadsheets are a fine way to *receive*
data and a terrible way to *analyse* it at scale. This script turns that workbook
into the three-layer analytical store described in docs/ARCHITECTURE.md §4.2:

  data/raw/         the original workbook, untouched — never modified, so any
                    number can always be re-derived from exactly what was received
  data/curated/     the same data with the bank's own column names mapped to
                    governed CreditProbe field names, types enforced, and validation run
  data/analytics/   business-ready Parquet, one folder per dataset and one file
                    per reporting period, which is what the engine actually reads

It also writes `metadata/catalog.json` — the governed data dictionary. That file
records, for every field, its governed name, the source column it came from, what
a risk officer calls it, what it means, its type, its unit and its sensitivity.
The Data Access Layer reads it to translate names, and Data Builder will edit it
in Phase 5.

Re-running is safe: the analytics layer is rebuilt from scratch each time.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402

SOURCE_WORKBOOK = "Portfolio_Monitoring_Dataset.xlsx"
SUPP_SHEET = "Borrower Supplementary"
DICT_SHEET = "Field Dictionary"
QUARTER_RE = re.compile(r"^Q([1-4])\s+(\d{4})$")

FACILITY_DATASET = "portfolio_facility"
BORROWER_DATASET = "borrower_financials"

# --------------------------------------------------------------------------
# Source column -> governed field name.
#
# Governed names are lower_snake_case, unit-free and stable. The unit lives in
# the catalogue, not in the name, so a later switch from USD mn to AED mn is a
# metadata change rather than a rename across the whole codebase.
# --------------------------------------------------------------------------

FACILITY_FIELDS: dict[str, str] = {
    "Snapshot Date": "snapshot_date",
    "Quarter": "period",
    "Customer ID": "customer_id",
    "Account ID": "account_id",
    "Borrower": "borrower_name",
    "Obligor Group": "obligor_group",
    "Segment": "segment",
    "Sector": "sector",
    "Region": "region",
    "Country": "country",
    "Product Type": "product_type",
    "Owner / Analyst": "owner_analyst",
    "Limit (USD mn)": "limit_amount",
    "Exposure (USD mn)": "exposure",
    "Undrawn (USD mn)": "undrawn",
    "CCF (%)": "ccf_pct",
    "CCF-Adjusted EAD (USD mn)": "ead",
    "Utilisation (%)": "utilisation_pct",
    "Prev. Utilisation (%)": "prev_utilisation_pct",
    "Collateral (USD mn)": "collateral_value",
    "Collateral Type": "collateral_type",
    "Internal Grade (1-10)": "internal_grade",
    "Risk Rating": "risk_rating",
    "Prev. Risk Rating": "prev_risk_rating",
    "Rating Bucket": "rating_bucket",
    "Grade Band": "grade_band",
    "IFRS 9 Stage": "ifrs9_stage",
    "Exposure Grade": "exposure_grade",
    "DPD (days)": "dpd_days",
    "PD 12-Month (%)": "pd_12m_pct",
    "PD Lifetime (%)": "pd_lifetime_pct",
    "LGD (%)": "lgd_pct",
    "Model ECL (USD mn)": "model_ecl",
    "Macro Overlay (USD mn)": "macro_overlay",
    "Total ECL (USD mn)": "total_ecl",
    "ECL Coverage (%)": "ecl_coverage_pct",
    "EIR (%)": "eir_pct",
    "RAROC (%)": "raroc_pct",
    "AI Risk Score": "ai_risk_score",
    "Severity": "severity",
    "Trigger": "trigger_type",
    "Reason Code": "reason_code",
    "Recommended Action": "recommended_action",
    "Trend": "trend",
    "SICR Trigger": "sicr_trigger",
    "DSCR (x)": "dscr",
    "Covenant Headroom (%)": "covenant_headroom_pct",
    "Downgrade Prob. (%)": "downgrade_prob_pct",
    "News Sentiment": "news_sentiment",
    "Rollover Count": "rollover_count",
    "Watchlist": "watchlist",
    "NPL": "npl",
    "Appetite Breach": "appetite_breach",
}

BORROWER_FIELDS: dict[str, str] = {
    "Customer ID": "customer_id",
    "Borrower": "borrower_name",
    "Net Leverage FY24 (x)": "net_leverage_fy24",
    "Net Leverage FY25 (x)": "net_leverage_fy25",
    "Interest Coverage FY24 (x)": "interest_coverage_fy24",
    "Interest Coverage FY25 (x)": "interest_coverage_fy25",
    "DSCR FY24 (x)": "dscr_fy24",
    "DSCR FY25 (x)": "dscr_fy25",
    "Current Ratio FY24 (x)": "current_ratio_fy24",
    "Current Ratio FY25 (x)": "current_ratio_fy25",
    "External Rating": "external_rating",
    "External Rating As Of": "external_rating_as_of",
    "Rating Notch Gap": "rating_notch_gap",
    "Last Collateral Valuation Date": "last_collateral_valuation_date",
}

# Definitions for the two columns the workbook's own dictionary omits.
EXTRA_DEFINITIONS = {
    "DSCR FY24 (x)": (
        "x",
        "Debt service coverage ratio at the prior fiscal year end: EBITDA "
        "divided by total debt service, interest plus scheduled principal. "
        "Below 1.0x the borrower cannot cover its obligations from earnings.",
    ),
    "DSCR FY25 (x)": (
        "x",
        "Debt service coverage ratio at the latest fiscal year end: EBITDA "
        "divided by total debt service, interest plus scheduled principal. "
        "Below 1.0x the borrower cannot cover its obligations from earnings.",
    ),
    "Model ECL (USD mn)": (
        "USD mn",
        "Expected credit loss produced by the IFRS 9 model, before any management "
        "or macroeconomic overlay is applied.",
    ),
    "Macro Overlay (USD mn)": (
        "USD mn",
        "Management/macroeconomic overlay added to the model ECL to reflect "
        "conditions the model does not yet capture.",
    ),
}

# Source columns whose header says "(%)" but whose values are stored as
# FRACTIONS (0-1) rather than true percentages. Audited against the actual value
# ranges in the workbook: ccf, utilisation and LGD top out at 1.0, while PD,
# EIR and RAROC genuinely run to 100.
#
# These are multiplied by 100 at the CURATED boundary so a governed field always
# means exactly what the catalogue says its unit is. Doing it here, once, is the
# whole reason the curated layer exists: otherwise every calculation would have
# to remember which "percentage" is really a fraction, and one that forgot would
# report an LGD of 0.39% instead of 39%.
FRACTION_TO_PERCENT = {
    "CCF (%)",
    "Utilisation (%)",
    "Prev. Utilisation (%)",
    "LGD (%)",
    "ECL Coverage (%)",
}

# Fields carrying borrower-identifying information. Classified so the DAL and the
# permission layer can restrict them independently of the numbers.
CONFIDENTIAL_FIELDS = {"borrower_name", "customer_id", "account_id", "obligor_group", "owner_analyst"}

# Source "Type / Units" -> (governed data type, unit)
TYPE_MAP: dict[str, tuple[str, str | None]] = {
    "Date": ("date", None),
    "Text": ("string", None),
    "USD mn": ("number", "USD mn"),
    "%": ("number", "%"),
    "days": ("integer", "days"),
    "x": ("number", "x"),
    "count": ("integer", "count"),
    "Notches": ("integer", "notches"),
    "1-10": ("integer", "grade"),
    "1-3": ("integer", "stage"),
    "0-1": ("number", "score"),
    "-1 to 1": ("number", "score"),
    "Yes/No": ("boolean", None),
}


def log(msg: str) -> None:
    print(f"  {msg}")


# ----------------------------------------------------------------- dictionary


def read_source_dictionary(xl: pd.ExcelFile) -> dict[str, tuple[str, str]]:
    """Read the workbook's own Field Dictionary tab.

    Returns {source column header: (type/units, definition)}. Using the bank's own
    published definitions rather than inventing our own is the whole point: the
    Data Dictionary in CreditProbe must say what the data owner says it says.
    """
    if DICT_SHEET not in xl.sheet_names:
        return {}
    raw = pd.read_excel(xl, sheet_name=DICT_SHEET, header=None)
    out: dict[str, tuple[str, str]] = {}
    for _, row in raw.iterrows():
        header, _key, units, definition = row.get(1), row.get(2), row.get(3), row.get(4)
        if not isinstance(header, str) or header.strip() in ("", "Column header"):
            continue
        # A row with a blank Definition cell still carries its Type/Units, and the
        # units drive the governed data type. Skipping such rows silently typed
        # "CCF-Adjusted EAD (USD mn)" as text, so the whole EAD column arrived as
        # strings. Keep the row; fall back to a generated definition later.
        out[header.strip()] = (
            units.strip() if isinstance(units, str) else "Text",
            definition.strip() if isinstance(definition, str) else "",
        )
    return out


def build_field_defs(
    mapping: dict[str, str], dictionary: dict[str, tuple[str, str]], present: set[str]
) -> list[dict]:
    """Turn the column mapping plus the source dictionary into catalogue entries."""
    fields = []
    for source_col, governed in mapping.items():
        if source_col not in present:
            continue
        units, definition = dictionary.get(source_col, EXTRA_DEFINITIONS.get(source_col, ("Text", "")))
        data_type, unit = TYPE_MAP.get(units, ("string", None))
        if not definition:
            definition = f"{source_col} as supplied by the source system."
        fields.append(
            {
                "name": governed,
                "source_column": source_col,
                "business_name": re.sub(r"\s*\([^)]*\)$", "", source_col).strip(),
                "definition": definition,
                "data_type": data_type,
                "unit": unit,
                "sensitivity": "confidential" if governed in CONFIDENTIAL_FIELDS else "internal",
                "nullable": True,
            }
        )
    return fields


# ---------------------------------------------------------------- conversion


def normalise_scales(df: pd.DataFrame, fields: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    """Convert fraction-valued percentage columns to true percentages.

    Verified rather than assumed: a column is only rescaled if it is on the list
    AND its observed maximum is at most 1.5. If a future extract already supplies
    true percentages, this silently does nothing rather than dividing the book by
    a hundred.
    """
    rescaled = []
    by_governed = {f["name"]: f for f in fields}
    for source_col in FRACTION_TO_PERCENT:
        governed = FACILITY_FIELDS.get(source_col)
        if governed is None or governed not in df.columns or governed not in by_governed:
            continue
        values = pd.to_numeric(df[governed], errors="coerce")
        if values.notna().any() and float(values.max()) <= 1.5:
            df[governed] = values * 100.0
            rescaled.append(f"{governed} (from {source_col})")
    return df, rescaled


def coerce_types(df: pd.DataFrame, fields: list[dict]) -> pd.DataFrame:
    """Enforce the declared type of every governed field.

    Types are enforced here, once, at the curated boundary — not inside each
    calculation. An engine function should never have to defend itself against a
    number arriving as text.
    """
    for f in fields:
        col = f["name"]
        if col not in df.columns:
            continue
        try:
            if f["data_type"] in ("number",):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            elif f["data_type"] == "integer":
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
            elif f["data_type"] == "date":
                df[col] = pd.to_datetime(df[col], errors="coerce")
            elif f["data_type"] == "boolean":
                df[col] = (
                    df[col].astype(str).str.strip().str.lower().map({"yes": True, "no": False,
                                                                     "true": True, "false": False})
                )
            else:
                df[col] = df[col].astype("string")
        except Exception as e:  # pragma: no cover - defensive
            log(f"WARNING could not coerce {col} to {f['data_type']}: {e}")
    return df


def validate(df: pd.DataFrame, dataset: str, keys: list[str]) -> list[dict]:
    """Quality checks run at the curated boundary. Findings are recorded in the
    catalogue so Data Builder can display them rather than hiding them."""
    findings: list[dict] = []
    if df.empty:
        findings.append({"dataset": dataset, "rule": "non_empty", "severity": "error",
                         "detail": "Dataset is empty."})
        return findings
    for k in keys:
        if k in df.columns and df[k].isna().any():
            findings.append({"dataset": dataset, "rule": "key_not_null", "severity": "error",
                             "detail": f"{int(df[k].isna().sum())} rows have a null {k}."})
    if all(k in df.columns for k in keys) and keys:
        dupes = int(df.duplicated(subset=keys).sum())
        if dupes:
            findings.append({"dataset": dataset, "rule": "key_unique", "severity": "error",
                             "detail": f"{dupes} duplicate rows on {', '.join(keys)}."})
    for col in ("ead", "exposure", "limit_amount", "total_ecl"):
        if col not in df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            # A money column that did not arrive as a number is a mapping fault,
            # not a data fault — report it rather than crashing the build.
            findings.append({"dataset": dataset, "rule": "numeric_type", "severity": "error",
                             "detail": f"{col} is {df[col].dtype}, expected a numeric type."})
            continue
        if (df[col] < 0).any():
            findings.append({"dataset": dataset, "rule": "non_negative", "severity": "warning",
                             "detail": f"{int((df[col] < 0).sum())} rows have a negative {col}."})
    return findings


def write_partitioned(df: pd.DataFrame, dataset_dir: Path, period_field: str | None) -> int:
    """Write Parquet — one folder per period when the dataset has one.

    Partitioning by period is what makes "give me Q1 2026" read one small file
    instead of scanning ten years of history.
    """
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    if period_field is None:
        out = dataset_dir / "data.parquet"
        df.to_parquet(out, index=False)
        return 1
    written = 0
    for period, chunk in df.groupby(period_field, observed=True):
        part = dataset_dir / f"{period_field}={period}"
        part.mkdir(parents=True, exist_ok=True)
        # The partition column is kept in the file as well as the path so that a
        # direct read of one file is still self-describing.
        chunk.to_parquet(part / "data.parquet", index=False)
        written += 1
    return written


def main() -> int:
    source = settings.raw_dir / SOURCE_WORKBOOK
    if not source.exists():
        print(f"ERROR: source workbook not found at {source}")
        return 1

    print(f"Building the CreditProbe analytical data lake from {source.name}")
    print()

    with pd.ExcelFile(source) as xl:
        dictionary = read_source_dictionary(xl)
        quarter_sheets = [s for s in xl.sheet_names if QUARTER_RE.match(s)]
        quarter_sheets.sort(key=lambda q: (int(QUARTER_RE.match(q).group(2)), int(QUARTER_RE.match(q).group(1))))
        log(f"Field Dictionary: {len(dictionary)} published definitions")
        log(f"Reporting periods: {len(quarter_sheets)} ({quarter_sheets[0]} to {quarter_sheets[-1]})")

        frames = [pd.read_excel(xl, sheet_name=s) for s in quarter_sheets]
        facility_raw = pd.concat(frames, ignore_index=True)
        borrower_raw = pd.read_excel(xl, sheet_name=SUPP_SHEET)

    print()
    print("CURATED layer — mapping source columns to governed field names")

    fac_present = set(facility_raw.columns)
    bor_present = set(borrower_raw.columns)
    unmapped = fac_present - set(FACILITY_FIELDS)
    if unmapped:
        log(f"NOTE {len(unmapped)} source columns are not mapped and will be dropped: {sorted(unmapped)}")

    facility_fields = build_field_defs(FACILITY_FIELDS, dictionary, fac_present)
    borrower_fields = build_field_defs(BORROWER_FIELDS, dictionary, bor_present)

    facility = facility_raw.rename(columns=FACILITY_FIELDS)[[f["name"] for f in facility_fields]]
    borrower = borrower_raw.rename(columns=BORROWER_FIELDS)[[f["name"] for f in borrower_fields]]

    facility = coerce_types(facility, facility_fields)
    borrower = coerce_types(borrower, borrower_fields)

    facility, rescaled = normalise_scales(facility, facility_fields)
    if rescaled:
        log(f"Rescaled {len(rescaled)} fraction-valued percentage field(s) to true percentages:")
        for name in sorted(rescaled):
            log(f"    {name}")
    log(f"{FACILITY_DATASET}: {len(facility):,} rows x {len(facility.columns)} governed fields")
    log(f"{BORROWER_DATASET}: {len(borrower):,} rows x {len(borrower.columns)} governed fields")

    findings = validate(facility, FACILITY_DATASET, ["period", "account_id"])
    findings += validate(borrower, BORROWER_DATASET, ["customer_id"])
    errors = [f for f in findings if f["severity"] == "error"]
    for f in findings:
        log(f"{f['severity'].upper()} [{f['rule']}] {f['detail']}")
    if not findings:
        log("All quality checks passed.")

    settings.curated_dir.mkdir(parents=True, exist_ok=True)
    facility.to_parquet(settings.curated_dir / f"{FACILITY_DATASET}.parquet", index=False)
    borrower.to_parquet(settings.curated_dir / f"{BORROWER_DATASET}.parquet", index=False)
    log(f"Written to {settings.curated_dir}")

    print()
    print("ANALYTICS layer — business-ready Parquet, partitioned by reporting period")
    n_parts = write_partitioned(facility, settings.analytics_dir / FACILITY_DATASET, "period")
    log(f"{FACILITY_DATASET}: {n_parts} period partitions")
    write_partitioned(borrower, settings.analytics_dir / BORROWER_DATASET, None)
    log(f"{BORROWER_DATASET}: 1 file (no period dimension — one row per borrower)")

    print()
    print("METADATA — governed catalogue (the Data Dictionary)")
    catalog = {
        "version": "1.0.0",
        "generated_from": SOURCE_WORKBOOK,
        "datasets": [
            {
                "name": FACILITY_DATASET,
                "domain": "Core Portfolio / Facility",
                "business_name": "Portfolio Facility Snapshot",
                "purpose": (
                    "Quarter-end position of every credit facility: exposure, limits, "
                    "collateral, rating, IFRS 9 staging, PD/LGD/ECL and early-warning signals."
                ),
                "grain": "One row per facility (account) per reporting period.",
                "primary_keys": ["period", "account_id"],
                "period_field": "period",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "1.0.0",
                "is_synthetic": True,
                # Governance. This is CreditProbe's bundled demonstration book: it is
                # labelled DEMO in Data Builder, and the moment a client dataset
                # is published and marked authoritative for the same purpose,
                # the engine reads that one instead (see data_access/authority.py).
                "origin": "demo",
                "dataset_family": FACILITY_DATASET,
                "authoritative_for": ["credit_facility_position"],
                "fields": facility_fields,
            },
            {
                "name": BORROWER_DATASET,
                "domain": "Corporate Ratings",
                "business_name": "Borrower Financials & External Ratings",
                "purpose": (
                    "Borrower-level financial ratios across two fiscal years plus the "
                    "external agency rating and its gap to the internal rating."
                ),
                "grain": "One row per borrower (customer).",
                "primary_keys": ["customer_id"],
                "period_field": "",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "1.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": BORROWER_DATASET,
                "authoritative_for": ["borrower_financials"],
                "fields": borrower_fields,
            },
        ],
        "quality_findings": findings,
        "lineage": [
            {"step": "raw", "detail": f"data/raw/{SOURCE_WORKBOOK} — original file as received, never modified"},
            {"step": "curated", "detail": "Source columns mapped to governed names; declared types enforced; "
                                          "fraction-valued percentage columns (CCF, utilisation, LGD, ECL coverage) "
                                          "rescaled to true percentages; quality rules run"},
            {"step": "analytics", "detail": "Parquet partitioned by reporting period; read by DuckDB through the Data Access Layer"},
        ],
    }
    settings.metadata_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = settings.metadata_dir / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2))
    total_fields = len(facility_fields) + len(borrower_fields)
    log(f"{len(catalog['datasets'])} datasets, {total_fields} governed fields -> {catalog_path}")

    print()
    if errors:
        print(f"FAILED — {len(errors)} blocking quality error(s). The lake was written but is not clean.")
        return 1
    print("Data lake built successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
