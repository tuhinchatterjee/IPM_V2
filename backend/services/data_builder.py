"""
Data Builder — self-service dataset onboarding for admins and data stewards.

The workflow this implements:

    Domain -> Dataset -> Upload -> Inspect -> Map -> Dictionary
           -> Relationships -> Validate -> Publish

The point is that a data steward can bring a file into IPM without a developer
putting it in a folder. Everything below is the backend for that.

Two rules the whole module is built around:

1. **The raw file is never modified.** It is written once to the RAW layer and
   kept, byte for byte. Any published figure must be re-derivable from exactly
   what the source system sent.

2. **Only PUBLISHED datasets are visible to the analytical engine.** A draft or
   half-mapped dataset cannot leak into an analysis. Publishing is the single
   gate, and it writes an immutable DataVersion.

The existing scripts/build_data_lake.py path keeps working untouched: it
produces `bundled` datasets, and this module produces `upload` ones. Both land
in the same analytics layer and are read through the same Data Access Layer.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.platform import (
    DS_DRAFT,
    DS_MAPPED,
    DS_PUBLISHED,
    DS_VALIDATED,
    MAP_IGNORED,
    MAP_MAPPED,
    MAP_PROPOSED,
    MAP_UNMAPPED,
    DataDomain,
    DatasetDefinition,
    DatasetRelationship,
    DatasetUpload,
    DataVersion,
    FieldDefinition,
    FieldMapping,
)

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {"csv", "xlsx", "xls", "parquet"}
PROFILE_SAMPLE_VALUES = 12
MAX_PREVIEW_ROWS = 20

# A governed field name must be a safe SQL identifier: the Data Access Layer
# interpolates it into queries (values are always bound, identifiers are not).
GOVERNED_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class DataBuilderError(RuntimeError):
    """Something the steward can fix. The message is written to be shown in the UI."""


# ============================================================== naming helpers


def slugify(text: str) -> str:
    """Turn a human label into a safe governed name: "Final ECL (USD)" -> final_ecl_usd."""
    out = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    out = re.sub(r"_+", "_", out)
    if not out:
        out = "field"
    if out[0].isdigit():
        out = f"f_{out}"
    return out[:63]


def validate_governed_name(name: str) -> str:
    if not GOVERNED_NAME_RE.match(name):
        raise DataBuilderError(
            f"'{name}' is not a valid governed field name. Use lower-case letters, "
            "numbers and underscores, starting with a letter."
        )
    return name


# =================================================================== profiling


def _infer_type(series: pd.Series) -> str:
    """Map a pandas dtype to the governed type vocabulary."""
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    # Text that is really a date or a number is common in bank extracts, so try
    # before settling for "string" — otherwise every numeric column from a CSV
    # would be typed as text and no arithmetic would work.
    non_null = series.dropna().astype(str).head(200)
    if len(non_null) == 0:
        return "string"
    numeric = pd.to_numeric(non_null, errors="coerce")
    if numeric.notna().mean() > 0.95:
        return "integer" if (numeric.dropna() % 1 == 0).all() else "number"
    dates = pd.to_datetime(non_null, errors="coerce", format="mixed")
    if dates.notna().mean() > 0.95:
        return "date"
    return "string"


def profile_column(series: pd.Series, name: str, row_count: int | None = None) -> dict[str, Any]:
    """Everything the mapping screen needs to know about one column."""
    total = int(len(series))
    nulls = int(series.isna().sum())
    inferred = _infer_type(series)
    info: dict[str, Any] = {
        "name": name,
        "inferred_type": inferred,
        "pandas_dtype": str(series.dtype),
        "null_count": nulls,
        "null_pct": round(nulls / total * 100, 2) if total else 0.0,
        "unique_count": int(series.nunique(dropna=True)),
        "suggested_governed_name": slugify(name),
    }

    non_null = series.dropna()
    if inferred in ("number", "integer"):
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if len(numeric):
            info["min"] = float(numeric.min())
            info["max"] = float(numeric.max())
            info["mean"] = float(numeric.mean())
            info["negative_count"] = int((numeric < 0).sum())
    elif inferred == "date":
        dates = pd.to_datetime(non_null, errors="coerce").dropna()
        if len(dates):
            info["min"] = dates.min().isoformat()
            info["max"] = dates.max().isoformat()
    else:
        unique = info["unique_count"]
        if 0 < unique <= 50:
            info["sample_values"] = [str(v) for v in non_null.unique()[:PROFILE_SAMPLE_VALUES]]
            # `is_categorical` drives whether the dictionary proposes an
            # allowed-values list, so it has to be strict on two counts:
            #
            #  * the sample must be COMPLETE. A truncated sample presented as the
            #    allowed set makes validation reject every value it left out.
            #  * an identifier is not a category. In a small file every
            #    customer_id is distinct, which looks low-cardinality by count
            #    alone; comparing against the row count tells them apart.
            rows = row_count if row_count else total
            info["is_categorical"] = (
                unique <= PROFILE_SAMPLE_VALUES and (rows == 0 or unique <= rows * 0.5)
            )
    return info


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Automatic inspection of an uploaded file."""
    columns = [profile_column(df[c], str(c), row_count=len(df)) for c in df.columns]

    # A "reporting period" is the single most important thing to identify, because
    # it decides how the analytics layer is partitioned.
    period_candidates = [
        c["name"]
        for c in columns
        if c["inferred_type"] == "date"
        or re.search(r"(period|quarter|month|reporting|snapshot|as_?of)", c["name"], re.I)
    ]

    date_range: dict[str, Any] = {}
    for c in columns:
        if c["inferred_type"] == "date" and "min" in c:
            date_range[c["name"]] = {"min": c["min"], "max": c["max"]}

    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": columns,
        "period_candidates": period_candidates,
        "date_range": date_range,
        "preview": df.head(MAX_PREVIEW_ROWS).astype(str).to_dict(orient="records"),
        "profiled_at": datetime.now(UTC).isoformat(),
    }


# ================================================================ file reading


def detect_format(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_FORMATS:
        raise DataBuilderError(
            f"'{filename}' is a .{suffix} file. Supported formats: CSV, Excel (.xlsx/.xls), Parquet."
        )
    return suffix


def read_source(content: bytes, file_format: str, sheet_name: str | None = None) -> pd.DataFrame:
    """Read an uploaded file into a DataFrame, without altering the bytes on disk."""
    buffer = io.BytesIO(content)
    try:
        if file_format == "csv":
            return pd.read_csv(buffer)
        if file_format in ("xlsx", "xls"):
            return pd.read_excel(buffer, sheet_name=sheet_name or 0)
        if file_format == "parquet":
            return pd.read_parquet(buffer)
    except Exception as e:
        raise DataBuilderError(f"Could not read the file: {e}") from e
    raise DataBuilderError(f"Unsupported format: {file_format}")


def excel_sheet_names(content: bytes) -> list[str]:
    with pd.ExcelFile(io.BytesIO(content)) as xl:
        return list(xl.sheet_names)


# ================================================================ domain / dataset


def list_domains(session: Session) -> list[DataDomain]:
    return list(session.execute(select(DataDomain).order_by(DataDomain.sort_order, DataDomain.name)).scalars())


def upsert_domain(session: Session, *, name: str, description: str = "", owner: str = "",
                  sort_order: int = 0) -> DataDomain:
    existing = session.execute(select(DataDomain).where(DataDomain.name == name)).scalar_one_or_none()
    if existing:
        existing.description = description or existing.description
        existing.owner = owner or existing.owner
        existing.sort_order = sort_order or existing.sort_order
        return existing
    domain = DataDomain(name=name, description=description, owner=owner, sort_order=sort_order)
    session.add(domain)
    session.flush()
    return domain


def create_dataset(session: Session, *, name: str, domain: str, business_name: str = "",
                   purpose: str = "", grain: str = "", owner: str = "",
                   period_field: str = "", primary_keys: list[str] | None = None,
                   source_type: str = "upload", is_synthetic: bool = False) -> DatasetDefinition:
    validate_governed_name(name)
    if session.execute(select(DatasetDefinition).where(DatasetDefinition.name == name)).scalar_one_or_none():
        raise DataBuilderError(f"A dataset called '{name}' already exists.")
    if not session.execute(select(DataDomain).where(DataDomain.name == domain)).scalar_one_or_none():
        raise DataBuilderError(
            f"'{domain}' is not a data domain. Create the domain first, or choose an existing one."
        )
    dataset = DatasetDefinition(
        name=name, domain=domain, business_name=business_name or name,
        purpose=purpose, grain=grain, owner=owner, period_field=period_field,
        primary_keys=primary_keys or [], lifecycle=DS_DRAFT, source_type=source_type,
        is_synthetic=is_synthetic,
    )
    session.add(dataset)
    session.flush()
    return dataset


def get_dataset(session: Session, name: str) -> DatasetDefinition:
    dataset = session.execute(
        select(DatasetDefinition).where(DatasetDefinition.name == name)
    ).scalar_one_or_none()
    if dataset is None:
        raise DataBuilderError(f"'{name}' is not a dataset in Data Builder.")
    return dataset


# ====================================================================== upload


def raw_storage_path(dataset_name: str, filename: str, sha256: str) -> Path:
    """Where an uploaded file is kept, forever, unmodified.

    The checksum is in the filename so two uploads of genuinely different files
    never collide, and re-uploading the same file is visibly the same file.
    """
    directory = settings.raw_dir / "uploads" / dataset_name
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{sha256[:12]}_{Path(filename).name}"


def upload_file(session: Session, *, dataset_name: str, content: bytes, filename: str,
                sheet_name: str | None = None, uploaded_by: int | None = None) -> DatasetUpload:
    """Store the file in RAW, inspect it, and record the profile.

    Uploading resets the lifecycle to DRAFT: a new file means the previous
    mapping and validation no longer describe what is there.
    """
    dataset = get_dataset(session, dataset_name)
    if not content:
        raise DataBuilderError("The uploaded file is empty.")

    file_format = detect_format(filename)
    df = read_source(content, file_format, sheet_name)
    if df.empty:
        raise DataBuilderError("The file was read successfully but contains no rows.")

    sha256 = hashlib.sha256(content).hexdigest()
    destination = raw_storage_path(dataset_name, filename, sha256)
    # Write once. If the identical file is uploaded again the bytes are the same,
    # so rewriting is harmless and keeps the path stable.
    destination.write_bytes(content)

    profile = profile_dataframe(df)
    upload = DatasetUpload(
        dataset_id=dataset.id, filename=filename, file_format=file_format,
        sheet_name=sheet_name, raw_path=str(destination), file_sha256=sha256,
        size_bytes=len(content), row_count=profile["row_count"],
        column_count=profile["column_count"], profile=profile, uploaded_by=uploaded_by,
    )
    session.add(upload)
    dataset.lifecycle = DS_DRAFT
    session.flush()

    suggest_mappings(session, dataset, profile)
    logger.info("Uploaded %s (%d rows) for dataset %s", filename, profile["row_count"], dataset_name)
    return upload


def latest_upload(session: Session, dataset: DatasetDefinition) -> DatasetUpload | None:
    return session.execute(
        select(DatasetUpload)
        .where(DatasetUpload.dataset_id == dataset.id)
        .order_by(DatasetUpload.uploaded_at.desc(), DatasetUpload.id.desc())
    ).scalars().first()


# ===================================================================== mapping

# Common source-system spellings for governed fields. This is a starting point
# the steward corrects, never an automatic decision: a wrong guess that nobody
# reviews is worse than no guess at all, which is why suggestions are recorded
# with a confidence and still require the steward to accept the mapping.
_SYNONYMS: dict[str, list[str]] = {
    "customer_id": ["cust_no", "customer_no", "obligor_id", "obligorid", "cif", "cif_no", "counterparty_id"],
    "account_id": ["facility_id", "acct_no", "account_no", "loan_id", "deal_id", "arrangement_id"],
    "borrower_name": ["customer_name", "obligor_name", "counterparty", "client_name"],
    "ead": ["exposure_at_default", "ccf_adjusted_ead", "ead_amount", "exposure_ead"],
    "exposure": ["outstanding", "drawn", "balance", "gross_exposure"],
    "total_ecl": ["final_impairment", "final_ecl", "impairment", "ecl", "provision", "total_provision"],
    "model_ecl": ["modelled_ecl", "model_impairment", "base_ecl"],
    "ifrs9_stage": ["stage", "ifrs_stage", "ifrs9stage", "impairment_stage"],
    "dpd_days": ["dpd", "days_past_due", "arrears_days", "overdue_days"],
    "pd_12m_pct": ["pd", "pd12", "pd_12m", "twelve_month_pd", "pd_1y"],
    "pd_lifetime_pct": ["lifetime_pd", "pd_lifetime", "ltpd"],
    "lgd_pct": ["lgd", "loss_given_default"],
    "period": ["reporting_date", "reporting_period", "quarter", "as_of_date", "snapshot_period"],
    "sector": ["industry", "industry_sector", "economic_sector", "nace"],
    "region": ["geography", "location", "emirate", "country_region"],
    "segment": ["business_segment", "portfolio_segment", "book"],
    "risk_rating": ["rating", "internal_rating", "grade", "risk_grade"],
    "limit_amount": ["limit", "sanctioned_limit", "facility_limit", "approved_limit"],
    "collateral_value": ["collateral", "security_value", "collateral_amount"],
}

_REVERSE_SYNONYMS = {alias: governed for governed, aliases in _SYNONYMS.items() for alias in aliases}


def suggest_governed_field(source_column: str, known_fields: set[str]) -> tuple[str | None, float]:
    """Best guess at the governed field a source column supplies, with confidence."""
    slug = slugify(source_column)
    if slug in known_fields:
        return slug, 1.0
    if slug in _REVERSE_SYNONYMS:
        return _REVERSE_SYNONYMS[slug], 0.8
    # Substring match against a known field, e.g. "ead_usd_mn" -> "ead".
    for field in sorted(known_fields, key=len, reverse=True):
        if len(field) >= 4 and (slug.startswith(field + "_") or slug.endswith("_" + field)):
            return field, 0.6
    return None, 0.0


def known_governed_fields(session: Session) -> set[str]:
    """Every governed field name already in use anywhere in the catalogue.

    Reusing an existing name is what makes datasets join. A steward mapping a new
    ECL extract should land on the same `customer_id` the portfolio uses.
    """
    return set(session.execute(select(FieldDefinition.name)).scalars())


def suggest_mappings(session: Session, dataset: DatasetDefinition, profile: dict) -> list[FieldMapping]:
    """Create a mapping row per source column, pre-filled with a suggestion."""
    session.query(FieldMapping).filter(FieldMapping.dataset_id == dataset.id).delete()
    known = known_governed_fields(session)
    out = []
    for column in profile.get("columns", []):
        governed, confidence = suggest_governed_field(column["name"], known)
        mapping = FieldMapping(
            dataset_id=dataset.id,
            source_column=column["name"],
            governed_field=governed or column["suggested_governed_name"],
            # A suggestion is never "mapped" — the steward has to accept it.
            status=MAP_UNMAPPED,
            confidence=confidence or None,
        )
        session.add(mapping)
        out.append(mapping)
    session.flush()
    return out


def get_mappings(session: Session, dataset: DatasetDefinition) -> list[FieldMapping]:
    return list(session.execute(
        select(FieldMapping).where(FieldMapping.dataset_id == dataset.id).order_by(FieldMapping.id)
    ).scalars())


def set_mappings(session: Session, dataset_name: str, mappings: list[dict]) -> list[FieldMapping]:
    """Apply the steward's mapping decisions.

    Each entry: {source_column, governed_field, status, note}. Status is one of
    mapped | unmapped | ignored | proposed.
    """
    dataset = get_dataset(session, dataset_name)
    existing = {m.source_column: m for m in get_mappings(session, dataset)}

    for entry in mappings:
        source = entry.get("source_column")
        if source not in existing:
            raise DataBuilderError(
                f"'{source}' is not a column of the uploaded file for '{dataset_name}'."
            )
        status = entry.get("status", MAP_UNMAPPED)
        if status not in (MAP_MAPPED, MAP_UNMAPPED, MAP_IGNORED, MAP_PROPOSED):
            raise DataBuilderError(f"'{status}' is not a valid mapping status.")

        record = existing[source]
        record.status = status
        record.note = entry.get("note", record.note)
        if status in (MAP_MAPPED, MAP_PROPOSED):
            governed = entry.get("governed_field") or record.governed_field
            if not governed:
                raise DataBuilderError(f"Column '{source}' is marked {status} but has no governed field.")
            record.governed_field = validate_governed_name(governed)
            record.confidence = None  # decided by a human now, not guessed
        elif status == MAP_IGNORED:
            record.governed_field = None

    # Two source columns feeding the same governed field would silently drop one
    # of them at publish time.
    claimed: dict[str, str] = {}
    for record in get_mappings(session, dataset):
        if record.status in (MAP_MAPPED, MAP_PROPOSED) and record.governed_field:
            if record.governed_field in claimed:
                raise DataBuilderError(
                    f"'{record.governed_field}' is claimed by two columns: "
                    f"'{claimed[record.governed_field]}' and '{record.source_column}'."
                )
            claimed[record.governed_field] = record.source_column

    if claimed:
        dataset.lifecycle = DS_MAPPED
    session.flush()
    return get_mappings(session, dataset)


# ================================================================== dictionary


def upsert_field_definition(session: Session, dataset_name: str, *, name: str,
                            business_name: str = "", definition: str = "",
                            data_type: str = "string", unit: str | None = None,
                            allowed_values: list[str] | None = None,
                            sensitivity: str = "internal", nullable: bool = True,
                            source_system: str = "", source_field: str = "") -> FieldDefinition:
    """Create or update one Data Dictionary entry."""
    dataset = get_dataset(session, dataset_name)
    validate_governed_name(name)
    if data_type not in {"string", "number", "integer", "boolean", "date"}:
        raise DataBuilderError(
            f"'{data_type}' is not a valid data type. Use string, number, integer, boolean or date."
        )

    record = session.execute(
        select(FieldDefinition).where(
            FieldDefinition.dataset_id == dataset.id, FieldDefinition.name == name
        )
    ).scalar_one_or_none()
    if record is None:
        record = FieldDefinition(dataset_id=dataset.id, name=name)
        session.add(record)

    record.business_name = business_name or record.business_name or name
    record.definition = definition or record.definition
    record.data_type = data_type
    record.unit = unit
    record.allowed_values = allowed_values
    record.sensitivity = sensitivity
    record.nullable = nullable
    record.source_system = source_system or record.source_system
    record.source_field = source_field or record.source_field
    session.flush()
    return record


def seed_dictionary_from_mappings(session: Session, dataset_name: str) -> list[FieldDefinition]:
    """Create dictionary entries for every mapped column, using the profile's
    inferred type. The steward then edits definitions and units; this only saves
    them from typing every field name twice."""
    dataset = get_dataset(session, dataset_name)
    upload = latest_upload(session, dataset)
    if upload is None:
        raise DataBuilderError(f"No file has been uploaded for '{dataset_name}' yet.")

    profile_by_column = {c["name"]: c for c in upload.profile.get("columns", [])}
    out = []
    for mapping in get_mappings(session, dataset):
        if mapping.status not in (MAP_MAPPED, MAP_PROPOSED) or not mapping.governed_field:
            continue
        column = profile_by_column.get(mapping.source_column, {})
        allowed = column.get("sample_values") if column.get("is_categorical") else None
        out.append(upsert_field_definition(
            session, dataset_name,
            name=mapping.governed_field,
            business_name=mapping.source_column,
            definition=f"Sourced from '{mapping.source_column}' in {upload.filename}.",
            data_type=column.get("inferred_type", "string"),
            allowed_values=allowed,
            source_system=upload.filename,
            source_field=mapping.source_column,
        ))
    return out


# =============================================================== relationships


def _require_known_dataset(session: Session, name: str) -> None:
    """A dataset is known if Data Builder has it OR the governed catalogue does.

    Bundled datasets (built by scripts/build_data_lake.py) are legitimate targets
    for a relationship — an uploaded ECL extract joining to the bundled portfolio
    is exactly the case Data Builder exists to support — but they have no
    DatasetDefinition row.
    """
    from backend.data_access import get_catalog

    if session.execute(
        select(DatasetDefinition).where(DatasetDefinition.name == name)
    ).scalar_one_or_none() is not None:
        return
    if name in get_catalog().names():
        return
    raise DataBuilderError(
        f"'{name}' is neither a Data Builder dataset nor a published governed dataset."
    )


def add_relationship(session: Session, *, from_dataset: str, from_field: str,
                     to_dataset: str, to_field: str, cardinality: str = "many_to_one",
                     kind: str = "key", description: str = "", name: str = "") -> DatasetRelationship:
    for ds_name in (from_dataset, to_dataset):
        _require_known_dataset(session, ds_name)
    existing = session.execute(
        select(DatasetRelationship).where(
            DatasetRelationship.from_dataset == from_dataset,
            DatasetRelationship.from_field == from_field,
            DatasetRelationship.to_dataset == to_dataset,
            DatasetRelationship.to_field == to_field,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    record = DatasetRelationship(
        name=name or f"{from_dataset}.{from_field} -> {to_dataset}.{to_field}",
        from_dataset=from_dataset, from_field=from_field,
        to_dataset=to_dataset, to_field=to_field,
        cardinality=cardinality, kind=kind, description=description,
    )
    session.add(record)
    session.flush()
    return record


def list_relationships(session: Session, dataset_name: str | None = None) -> list[DatasetRelationship]:
    stmt = select(DatasetRelationship)
    if dataset_name:
        stmt = stmt.where(
            (DatasetRelationship.from_dataset == dataset_name)
            | (DatasetRelationship.to_dataset == dataset_name)
        )
    return list(session.execute(stmt.order_by(DatasetRelationship.id)).scalars())


# =================================================================== validation


def _governed_frame(session: Session, dataset: DatasetDefinition) -> pd.DataFrame:
    """Read the raw upload and rename columns to their governed names.

    This is the curated view: source columns renamed, ignored columns dropped,
    declared types enforced. It is what both validation and publishing operate on.
    """
    upload = latest_upload(session, dataset)
    if upload is None:
        raise DataBuilderError(f"No file has been uploaded for '{dataset.name}' yet.")

    raw = Path(upload.raw_path)
    if not raw.exists():
        raise DataBuilderError(f"The stored source file is missing: {raw}")

    df = read_source(raw.read_bytes(), upload.file_format, upload.sheet_name)
    rename = {
        m.source_column: m.governed_field
        for m in get_mappings(session, dataset)
        if m.status in (MAP_MAPPED, MAP_PROPOSED) and m.governed_field
    }
    if not rename:
        raise DataBuilderError(
            f"No columns of '{dataset.name}' are mapped yet. Map at least one column before validating."
        )
    df = df[[c for c in df.columns if c in rename]].rename(columns=rename)

    # Enforce declared types once, at this boundary, so no calculation downstream
    # has to defend itself against a number arriving as text.
    for field in dataset.fields:
        if field.name not in df.columns:
            continue
        try:
            if field.data_type == "number":
                df[field.name] = pd.to_numeric(df[field.name], errors="coerce")
            elif field.data_type == "integer":
                df[field.name] = pd.to_numeric(df[field.name], errors="coerce").astype("Int64")
            elif field.data_type == "date":
                df[field.name] = pd.to_datetime(df[field.name], errors="coerce")
            elif field.data_type == "boolean":
                df[field.name] = (
                    df[field.name].astype(str).str.strip().str.lower()
                    .map({"yes": True, "no": False, "true": True, "false": False, "1": True, "0": False})
                )
            else:
                df[field.name] = df[field.name].astype("string")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Could not coerce %s to %s: %s", field.name, field.data_type, e)
    return df


def _finding(rule: str, severity: str, detail: str, count: int = 0) -> dict:
    return {"rule": rule, "severity": severity, "detail": detail, "count": count}


def validate_dataset(session: Session, dataset_name: str) -> dict[str, Any]:
    """Run every quality check and return a report.

    Checks: duplicate primary key, missing required fields, invalid IFRS 9 stage,
    invalid dates, negative EAD, values outside the declared allowed set, and
    broken relationships to other published datasets.

    Errors block publication; warnings do not.
    """
    dataset = get_dataset(session, dataset_name)
    df = _governed_frame(session, dataset)
    findings: list[dict] = []

    # -- primary keys -------------------------------------------------------
    keys = list(dataset.primary_keys or [])
    if not keys:
        findings.append(_finding("primary_key_declared", "warning",
                                 "No primary key is declared, so uniqueness cannot be checked."))
    else:
        missing_keys = [k for k in keys if k not in df.columns]
        if missing_keys:
            findings.append(_finding("primary_key_present", "error",
                                     f"Declared primary key column(s) not mapped: {', '.join(missing_keys)}.",
                                     len(missing_keys)))
        else:
            nulls = int(df[keys].isna().any(axis=1).sum())
            if nulls:
                findings.append(_finding("primary_key_not_null", "error",
                                         f"{nulls} rows have a null primary key.", nulls))
            dupes = int(df.duplicated(subset=keys).sum())
            if dupes:
                findings.append(_finding("primary_key_unique", "error",
                                         f"{dupes} duplicate rows on {', '.join(keys)}.", dupes))

    # -- required (non-nullable) fields -------------------------------------
    for field in dataset.fields:
        if field.nullable or field.name not in df.columns:
            continue
        nulls = int(df[field.name].isna().sum())
        if nulls:
            findings.append(_finding("required_field", "error",
                                     f"{nulls} rows have no value for required field '{field.name}'.", nulls))

    # -- IFRS 9 stage -------------------------------------------------------
    if "ifrs9_stage" in df.columns:
        stages = pd.to_numeric(df["ifrs9_stage"], errors="coerce")
        invalid = int((~stages.isin([1, 2, 3]) & stages.notna()).sum() + stages.isna().sum())
        if invalid:
            findings.append(_finding("valid_ifrs9_stage", "error",
                                     f"{invalid} rows have an IFRS 9 stage that is not 1, 2 or 3.", invalid))

    # -- dates --------------------------------------------------------------
    for field in dataset.fields:
        if field.data_type != "date" or field.name not in df.columns:
            continue
        parsed = pd.to_datetime(df[field.name], errors="coerce")
        # Only rows that had a value but could not be parsed are a fault; a
        # genuinely empty optional date is not.
        unparseable = int((parsed.isna() & df[field.name].notna()).sum())
        if unparseable:
            findings.append(_finding("valid_date", "error",
                                     f"{unparseable} rows have an unreadable date in '{field.name}'.",
                                     unparseable))

    # -- non-negative money -------------------------------------------------
    for column in ("ead", "exposure", "limit_amount", "total_ecl", "model_ecl", "collateral_value"):
        if column not in df.columns:
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        negatives = int((numeric < 0).sum())
        if negatives:
            findings.append(_finding("non_negative", "error",
                                     f"{negatives} rows have a negative '{column}'.", negatives))

    # -- allowed values -----------------------------------------------------
    for field in dataset.fields:
        if not field.allowed_values or field.name not in df.columns:
            continue
        allowed = {str(v) for v in field.allowed_values}
        actual = df[field.name].dropna().astype(str)
        offending = int((~actual.isin(allowed)).sum())
        if offending:
            findings.append(_finding("allowed_values", "error",
                                     f"{offending} rows have a value for '{field.name}' outside its allowed list.",
                                     offending))

    # -- relationships ------------------------------------------------------
    for rel in list_relationships(session, dataset.name):
        if rel.from_dataset != dataset.name:
            continue
        if rel.from_field not in df.columns:
            findings.append(_finding("relationship_field", "error",
                                     f"Relationship references '{rel.from_field}', which is not mapped."))
            continue
        try:
            target = get_dataset(session, rel.to_dataset)
        except DataBuilderError:
            continue
        if target.lifecycle != DS_PUBLISHED:
            findings.append(_finding("relationship_target", "warning",
                                     f"'{rel.to_dataset}' is not published yet, so the link cannot be checked."))
            continue
        broken = _count_broken_relationship(df, rel)
        if broken:
            findings.append(_finding("relationship_integrity", "error",
                                     f"{broken} values of '{rel.from_field}' do not exist in "
                                     f"{rel.to_dataset}.{rel.to_field}.", broken))

    errors = [f for f in findings if f["severity"] == "error"]
    report = {
        "dataset": dataset.name,
        "row_count": int(len(df)),
        "field_count": int(len(df.columns)),
        "checked_at": datetime.now(UTC).isoformat(),
        "findings": findings,
        "error_count": len(errors),
        "warning_count": len(findings) - len(errors),
        "passed": not errors,
    }

    if report["passed"] and dataset.lifecycle in (DS_MAPPED, DS_VALIDATED):
        dataset.lifecycle = DS_VALIDATED
    elif not report["passed"] and dataset.lifecycle == DS_VALIDATED:
        # A dataset that used to pass and now does not must lose its validated
        # standing, or a stale VALIDATED could be published.
        dataset.lifecycle = DS_MAPPED
    session.flush()
    return report


def _count_broken_relationship(df: pd.DataFrame, rel: DatasetRelationship) -> int:
    """How many values on the left have no match on the right."""
    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext

    source = get_data_source()
    try:
        periods = source.periods(rel.to_dataset)
        ctx = AnalysisContext(period=periods[-1] if periods else "")
        target = source.fetch(rel.to_dataset, context=ctx, fields=[rel.to_field],
                              period=periods[-1] if periods else None)
    except Exception as e:
        logger.debug("Could not check relationship against %s: %s", rel.to_dataset, e)
        return 0
    valid = set(target[rel.to_field].dropna().astype(str))
    left = df[rel.from_field].dropna().astype(str)
    return int((~left.isin(valid)).sum())


# ==================================================================== publish


def publish_dataset(session: Session, dataset_name: str, *, published_by: int | None = None,
                    force: bool = False) -> DataVersion:
    """Write the curated + analytics Parquet and record an immutable DataVersion.

    This is the single gate between Data Builder and the analytical engine. A
    dataset that has not passed validation cannot be published (and `force` only
    exists for a deliberate, recorded override — it does not skip the checks, it
    records that they failed).
    """
    dataset = get_dataset(session, dataset_name)
    report = validate_dataset(session, dataset_name)
    if not report["passed"] and not force:
        blocking = "; ".join(f["detail"] for f in report["findings"] if f["severity"] == "error")
        raise DataBuilderError(
            f"'{dataset_name}' cannot be published: {report['error_count']} blocking error(s). {blocking}"
        )

    df = _governed_frame(session, dataset)
    upload = latest_upload(session, dataset)

    # -- curated layer: one file, governed names, enforced types -------------
    curated_dir = settings.curated_dir
    curated_dir.mkdir(parents=True, exist_ok=True)
    curated_path = curated_dir / f"{dataset.name}.parquet"
    df.to_parquet(curated_path, index=False)

    # -- analytics layer: partitioned by reporting period if there is one ----
    analytics_dir = settings.analytics_dir / dataset.name
    if analytics_dir.exists():
        shutil.rmtree(analytics_dir)
    analytics_dir.mkdir(parents=True, exist_ok=True)

    period_field = dataset.period_field or ""
    periods: list[str] = []
    if period_field and period_field in df.columns:
        for period, chunk in df.groupby(period_field, observed=True):
            part = analytics_dir / f"{period_field}={period}"
            part.mkdir(parents=True, exist_ok=True)
            chunk.to_parquet(part / "data.parquet", index=False)
            periods.append(str(period))
        periods.sort()
    else:
        df.to_parquet(analytics_dir / "data.parquet", index=False)

    next_version = 1 + (
        session.execute(
            select(DataVersion.version)
            .where(DataVersion.dataset_id == dataset.id)
            .order_by(DataVersion.version.desc())
        ).scalars().first()
        or 0
    )

    version = DataVersion(
        dataset_id=dataset.id, version=next_version,
        upload_id=upload.id if upload else None,
        row_count=int(len(df)), field_count=int(len(df.columns)), periods=periods,
        analytics_path=str(analytics_dir), curated_path=str(curated_path),
        catalog_snapshot=dataset_catalog_entry(session, dataset),
        quality_report=report, published_by=published_by,
    )
    session.add(version)

    dataset.lifecycle = DS_PUBLISHED
    dataset.published_version = next_version
    dataset.published_at = datetime.now(UTC)
    dataset.storage_location = str(analytics_dir)
    session.flush()

    logger.info("Published %s v%d (%d rows, %d periods)", dataset.name, next_version,
                len(df), len(periods))
    return version


def refresh_governed_catalog() -> None:
    """Make a newly published dataset visible to the analytical engine.

    Must be called AFTER the publishing transaction commits: the catalogue reload
    opens its own session, so an uncommitted dataset would be invisible to it and
    the refresh would silently do nothing.
    """
    from backend.data_access import reload_catalog, reset_data_source

    reset_data_source()
    reload_catalog()


def dataset_catalog_entry(session: Session, dataset: DatasetDefinition) -> dict[str, Any]:
    """The catalogue shape the Data Access Layer reads (see data_access/catalog.py)."""
    mapping_by_field = {
        m.governed_field: m.source_column
        for m in get_mappings(session, dataset)
        if m.governed_field
    }
    return {
        "name": dataset.name,
        "domain": dataset.domain,
        "business_name": dataset.business_name or dataset.name,
        "purpose": dataset.purpose,
        "grain": dataset.grain,
        "primary_keys": list(dataset.primary_keys or []),
        "period_field": dataset.period_field or "",
        "owner": dataset.owner,
        "status": dataset.lifecycle,
        "version": str(dataset.published_version or 1),
        "is_synthetic": dataset.is_synthetic,
        "fields": [
            {
                "name": f.name,
                "source_column": f.source_field or mapping_by_field.get(f.name, f.name),
                "business_name": f.business_name or f.name,
                "definition": f.definition,
                "data_type": f.data_type,
                "unit": f.unit,
                "allowed_values": f.allowed_values,
                "sensitivity": f.sensitivity,
                "nullable": f.nullable,
            }
            for f in sorted(dataset.fields, key=lambda x: x.name)
        ],
    }


def published_datasets(session: Session) -> list[DatasetDefinition]:
    """The only datasets the analytical engine may read."""
    return list(session.execute(
        select(DatasetDefinition)
        .where(DatasetDefinition.lifecycle == DS_PUBLISHED)
        .order_by(DatasetDefinition.name)
    ).scalars())


def list_versions(session: Session, dataset_name: str) -> list[DataVersion]:
    dataset = get_dataset(session, dataset_name)
    return list(session.execute(
        select(DataVersion)
        .where(DataVersion.dataset_id == dataset.id)
        .order_by(DataVersion.version.desc())
    ).scalars())
