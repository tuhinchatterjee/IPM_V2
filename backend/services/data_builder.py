"""
Data Builder — self-service dataset onboarding for admins and data stewards.

The workflow this implements:

    Domain -> Dataset -> Upload -> Inspect -> Map -> Dictionary
           -> Relationships -> Validate -> Publish

The point is that a data steward can bring a file into CreditProbe without a developer
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


DOMAIN_ACTIVE = "ACTIVE"
DOMAIN_ARCHIVED = "ARCHIVED"


def domain_overview(session: Session) -> list[dict[str, Any]]:
    """Every data domain, with enough to decide what to do about it.

    Read from `backend.metadata`, which is the one authority for what a domain
    is and what is installed under it. §12.

    This screen used to enumerate rows in the `data_domains` table, and there
    were forty-five of them: seven business headings plus thirty-eight
    leftovers from an earlier generator taxonomy, every one of them empty. So
    the screen said "45 domains" while the analyst's own discovery tool said
    "5" and the domain map said "7" — three answers to one question about one
    deployment. Whether a stale row still sits in the table is a housekeeping
    matter; it is not a statement about the bank's data, and it no longer
    reaches a reader.

    The steward's own edits — description, owner, status, ordering — still
    come from the database, because those are the fields a steward owns. What
    is IN a domain comes from the catalogue and the lake.
    """
    from backend import metadata as md

    stored = {domain.name: domain for domain in list_domains(session)}
    published: dict[str, str] = {}
    for dataset in session.execute(select(DatasetDefinition)).scalars():
        published[dataset.name] = dataset.lifecycle

    out: list[dict[str, Any]] = []
    for heading in md.domains():
        found = [md.dataset(name) for name in heading.datasets]
        datasets = [d for d in found if d is not None]
        edits = stored.get(heading.name)
        out.append({
            "name": heading.name,
            "description": (edits.description if edits and edits.description
                            else heading.description),
            "owner": edits.owner if edits and edits.owner else heading.owner,
            "status": edits.status if edits else DOMAIN_ACTIVE,
            "sort_order": edits.sort_order if edits else 0,
            "dataset_count": len(datasets),
            "published_count": sum(
                1 for d in datasets
                if published.get(d.name) == DS_PUBLISHED),
            "row_count": heading.row_count,
            "period_count": len(heading.periods),
            "first_period": heading.periods[0] if heading.periods else None,
            "last_period": heading.periods[-1] if heading.periods else None,
            "datasets": [
                {
                    "name": d.name,
                    "business_name": d.business_name,
                    "lifecycle": published.get(d.name, DS_PUBLISHED),
                    "is_synthetic": d.is_synthetic,
                    "readable": d.readable,
                }
                for d in datasets
            ],
        })
    return out


def _ordered_periods(periods: set[str]) -> list[str]:
    """Periods in time order, not alphabetical order.

    "Q1 2026" sorts before "Q4 2025" alphabetically, which would report a
    coverage range backwards. Sorting on (year, quarter) fixes that, and
    anything that does not parse falls to the end rather than raising.
    """
    def key(period: str) -> tuple[int, int, str]:
        match = re.fullmatch(r"Q([1-4])\s+(\d{4})", period.strip())
        if match:
            return (int(match.group(2)), int(match.group(1)), period)
        if period.strip().isdigit():
            return (int(period.strip()), 0, period)
        return (9999, 9, period)

    return sorted(periods, key=key)


def rename_domain(session: Session, name: str, new_name: str) -> DataDomain:
    """Rename a domain, taking its datasets with it.

    A domain name is a foreign key in all but declaration — every dataset
    carries it as text. Renaming without moving them would orphan the lot, so
    both happen here or neither does.
    """
    new_name = (new_name or "").strip()
    if not new_name:
        raise DataBuilderError("A domain needs a name.")
    domain = session.execute(
        select(DataDomain).where(DataDomain.name == name)).scalar_one_or_none()
    if domain is None:
        raise DataBuilderError(f"There is no data domain called '{name}'.")
    if new_name == name:
        return domain
    clash = session.execute(
        select(DataDomain).where(DataDomain.name == new_name)).scalar_one_or_none()
    if clash is not None:
        raise DataBuilderError(
            f"A domain called '{new_name}' already exists. Two domains with one "
            "name would make every dataset in them ambiguous."
        )

    for dataset in session.execute(
        select(DatasetDefinition).where(DatasetDefinition.domain == name)
    ).scalars():
        dataset.domain = new_name
    domain.name = new_name
    session.flush()
    return domain


def get_grid_preferences(session: Session, *, user_id: int,
                         dataset: str) -> dict[str, Any]:
    """How this person has arranged this dataset's grid. Empty if never."""
    from backend.models.platform import GridPreference

    row = session.execute(
        select(GridPreference)
        .where(GridPreference.user_id == user_id,
               GridPreference.dataset == dataset)
    ).scalar_one_or_none()
    return dict(row.preferences or {}) if row else {}


def set_grid_preferences(session: Session, *, user_id: int, dataset: str,
                         preferences: dict[str, Any]) -> None:
    """Record it, replacing whatever was there.

    Replaces rather than merges: the grid always sends its whole arrangement, so
    merging would make un-hiding a column impossible — the absence of a key
    would be indistinguishable from not mentioning it.
    """
    from backend.models.platform import GridPreference

    row = session.execute(
        select(GridPreference)
        .where(GridPreference.user_id == user_id,
               GridPreference.dataset == dataset)
    ).scalar_one_or_none()

    if row is None:
        session.add(GridPreference(user_id=user_id, dataset=dataset,
                                   preferences=dict(preferences)))
    else:
        row.preferences = dict(preferences)
    session.flush()


def _forget_archived_domain_cache() -> None:
    """The engine holds this set; a change here has to reach it now."""
    from backend.services.domain_status import forget

    forget()


def archived_domain_names(session: Session) -> frozenset[str]:
    """The domains the data office has retired.

    Read by the engine's authority layer, through the provider the API
    registers at start-up, to decide what it may resolve. Kept here because
    this is where domain status is written.
    """
    return frozenset(
        row.name for row in session.execute(
            select(DataDomain).where(DataDomain.status == DOMAIN_ARCHIVED)
        ).scalars()
    )


def set_domain_status(session: Session, name: str, status: str) -> DataDomain:
    """Archive a domain, or bring it back.

    Archiving deletes nothing. Every dataset in the domain stays on disk and
    stays readable in the viewer for anybody authorised to look, and restoring
    the domain puts it straight back.

    What archiving DOES do is take the domain out of engine resolution: an
    analysis will no longer reach for a dataset in a retired domain on its own.
    That is the point of retiring one — an analysis quietly going on reading a
    book the data office has withdrawn, and somebody finding out nine months
    later, is exactly the audit finding this product exists to prevent.
    """
    status = (status or "").strip().upper()
    if status not in {DOMAIN_ACTIVE, DOMAIN_ARCHIVED}:
        raise DataBuilderError(
            f"'{status}' is not a domain status. Use ACTIVE or ARCHIVED."
        )
    domain = session.execute(
        select(DataDomain).where(DataDomain.name == name)).scalar_one_or_none()
    if domain is None:
        raise DataBuilderError(f"There is no data domain called '{name}'.")
    domain.status = status
    session.flush()
    # The engine caches which domains are archived; this decision has to reach
    # it now rather than at the next restart.
    _forget_archived_domain_cache()
    return domain


def delete_domain(session: Session, name: str) -> None:
    """Delete a domain — only when nothing depends on it.

    A domain that still holds datasets cannot be deleted, and the refusal names
    them. This is the one place in Data Builder where something is genuinely
    destroyed, so it refuses in every case where a person might mean archive.
    """
    domain = session.execute(
        select(DataDomain).where(DataDomain.name == name)).scalar_one_or_none()
    if domain is None:
        raise DataBuilderError(f"There is no data domain called '{name}'.")

    datasets = list(session.execute(
        select(DatasetDefinition).where(DatasetDefinition.domain == name)
    ).scalars())
    if datasets:
        listed = ", ".join(d.name for d in datasets[:5])
        more = f" and {len(datasets) - 5} more" if len(datasets) > 5 else ""
        raise DataBuilderError(
            f"'{name}' still holds {len(datasets)} dataset"
            f"{'' if len(datasets) == 1 else 's'} ({listed}{more}). Move or "
            "archive them first, or archive the domain instead — deleting it "
            "would leave them without one."
        )

    session.delete(domain)
    session.flush()


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
    from backend import metadata as md
    from backend.data_access import reload_catalog, reset_data_source
    from backend.orchestration import context as governed_context
    from backend.orchestration.vocabulary import reset_vocabulary

    reset_data_source()
    reload_catalog()
    # The planner's vocabulary of real sectors, regions and periods is read from
    # the governed layer, so publishing new data must invalidate it too.
    reset_vocabulary()
    # And so is the metadata service, which every surface now reads for the
    # domain, dataset, field, period and row-count picture. A publish that
    # left it cached would put the Data Builder screen and the AI back into
    # disagreement — the exact defect §12 exists to end.
    md.invalidate()
    governed_context.invalidate()


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
        # Governance metadata, carried through explicitly. A database entry
        # overrides the bundled catalogue entry of the same name, so anything
        # omitted here is not merely missing — it is ERASED. Leaving
        # authoritative_for out meant a published dataset silently stopped
        # serving the purpose it was published for.
        "origin": dataset.origin,
        "dataset_family": dataset.dataset_family or dataset.name,
        "authoritative_for": list(dataset.authoritative_for or []),
        # B44. Omitting this erases it exactly as omitting authoritative_for
        # did: a published corporate dataset would come back as part of the
        # credit book and be ranked against it on word overlap.
        "portfolio_scope": dataset.portfolio_scope or "CREDIT_BOOK",
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


# ================================================================ the viewer


#: The only comparisons the viewer will make. A filter arrives as
#: "field:op:value" and the operator must be one of these, so the set of things
#: a filter can express is fixed here rather than by whatever a caller sends.
FILTER_OPS: dict[str, str] = {
    "eq": "is",
    "ne": "is not",
    "contains": "contains",
    "gt": "greater than",
    "gte": "at least",
    "lt": "less than",
    "lte": "at most",
    "blank": "is blank",
    "present": "is not blank",
}


def parse_filter(text: str) -> tuple[str, str, str]:
    """"ifrs9_stage:eq:2" -> ("ifrs9_stage", "eq", "2").

    Raises rather than guessing. A filter that cannot be read is a bug in the
    caller, and silently dropping it would show the user a filtered-looking grid
    that is not filtered.
    """
    parts = text.split(":", 2)
    if len(parts) == 2:
        field, op, value = parts[0], parts[1], ""
    elif len(parts) == 3:
        field, op, value = parts
    else:
        raise ValueError(
            f"'{text}' is not a filter. Write it as field:operator:value, "
            f"for example ifrs9_stage:eq:2."
        )
    if op not in FILTER_OPS:
        raise ValueError(
            f"'{op}' is not a comparison the viewer offers. "
            f"Use one of: {', '.join(sorted(FILTER_OPS))}."
        )
    return field.strip(), op, value


def _apply_filter(frame: pd.DataFrame, field: str, op: str, value: str) -> pd.DataFrame:
    """One governed comparison, applied in pandas.

    Deliberately not pushed down as SQL text. The column has already been
    checked against the dictionary, but the *value* is whatever somebody typed,
    and the only safe thing to do with it is compare it — never concatenate it.
    """
    column = frame[field]
    if op == "blank":
        return frame[column.isna()]
    if op == "present":
        return frame[column.notna()]
    if op == "contains":
        return frame[column.astype("string").str.contains(value, case=False, na=False,
                                                          regex=False)]
    if op in {"gt", "gte", "lt", "lte"}:
        numeric = pd.to_numeric(column, errors="coerce")
        try:
            threshold = float(value)
        except ValueError as e:
            raise ValueError(
                f"'{value}' is not a number, and {FILTER_OPS[op]} compares numbers."
            ) from e
        comparison = {
            "gt": numeric > threshold, "gte": numeric >= threshold,
            "lt": numeric < threshold, "lte": numeric <= threshold,
        }[op]
        return frame[comparison.fillna(False)]

    # eq / ne, compared as text so "2" matches an integer 2 and a string "2".
    as_text = column.astype("string").str.strip()
    matches = as_text.str.casefold() == value.strip().casefold()
    return frame[matches.fillna(False)] if op == "eq" else frame[(~matches).fillna(True)]


def _search(frame: pd.DataFrame, term: str) -> pd.DataFrame:
    """Rows where any shown column contains the term.

    A plain substring match, never a regex: a user typing "(" into a search box
    should get no rows, not a traceback.
    """
    if not term.strip():
        return frame
    hit = pd.Series(False, index=frame.index)
    for column in frame.columns:
        hit |= frame[column].astype("string").str.contains(
            term, case=False, na=False, regex=False)
    return frame[hit]


def browse_dataset(name: str, *, period: str | None = None, offset: int = 0,
                   limit: int = 50, fields: list[str] | None = None,
                   sort: str | None = None, descending: bool = False,
                   search: str = "",
                   filters: list[str] | None = None) -> dict[str, Any]:
    """One page of a governed dataset, for a person to look at.

    Why this is not "just a SELECT"
    -------------------------------
    Everything goes through the Data Access Layer: the dataset name is resolved
    against the catalogue, every requested field is checked against the governed
    dictionary, and the sort column must be one of them. A viewer that accepted
    a column name and interpolated it would be an unrestricted query surface
    wearing a table's clothes — which is exactly what this product promises
    nobody has.

    The schema travels with the page, so the interface can show what a column
    means and how it is classified rather than only its name.
    """
    from backend.data_access.catalog import get_catalog
    from backend.data_access.context import AnalysisContext
    from backend.data_access.duckdb_source import DuckDBSource

    source = DuckDBSource()
    spec = get_catalog().dataset(name)  # raises with a helpful message if unknown

    periods = source.periods(name)
    effective = period or (periods[-1] if periods else None)

    known = set(spec.fields)
    chosen = [f for f in (fields or []) if f in known] or _default_columns(spec)
    if sort and sort not in known:
        raise ValueError(
            f"'{sort}' is not a field of {name}. Sorting is offered only on the "
            "governed fields, so a column name cannot become a query."
        )

    parsed = [parse_filter(text) for text in (filters or [])]
    for field, _, _ in parsed:
        if field not in known:
            raise ValueError(
                f"'{field}' is not a field of {name}. Filtering is offered only "
                "on the governed fields, so a column name cannot become a query."
            )

    context = AnalysisContext(period=effective or "")
    frame = source.fetch(name, context=context, fields=chosen, period=effective)

    #: Rows in the period, before the viewer's own narrowing. Shown alongside the
    #: filtered count so "12 of 15,400" reads as a filter rather than an empty
    #: dataset.
    total_in_period = len(frame)
    for field, op, value in parsed:
        frame = _apply_filter(frame, field, op, value)
    frame = _search(frame, search)

    total = len(frame)
    if sort:
        frame = frame.sort_values(sort, ascending=not descending, kind="mergesort")
    page = frame.iloc[offset:offset + limit]

    return {
        "dataset": name,
        "business_name": spec.business_name,
        "domain": spec.domain,
        "family": spec.family,
        "origin": spec.origin,
        "is_synthetic": spec.is_synthetic,
        "grain": spec.grain,
        "period": effective,
        "periods": periods,
        "total_rows": total,
        "total_in_period": total_in_period,
        "filtered": total != total_in_period,
        "offset": offset,
        "limit": limit,
        "returned": int(len(page)),
        # In `chosen` order, not alphabetical: this list IS the column order the
        # grid renders, and the first columns are the ones it keeps on screen
        # while you scroll sideways.
        "fields": [
            {
                "name": field_name,
                "business_name": spec.fields[field_name].business_name,
                "definition": spec.fields[field_name].definition,
                "data_type": spec.fields[field_name].data_type,
                "unit": spec.fields[field_name].unit,
                "sensitivity": spec.fields[field_name].sensitivity,
                "nullable": spec.fields[field_name].nullable,
            }
            for field_name in chosen
        ],
        #: Every governed field, so the grid can offer columns it is not
        #: currently showing without a second request.
        "all_fields": sorted(known),
        "rows": [
            {k: (None if _is_null(v) else v) for k, v in record.items()}
            for record in page.to_dict(orient="records")
        ],
    }


def column_profile(name: str, field: str, *, period: str | None = None,
                   top: int = 12) -> dict[str, Any]:
    """What is actually in one column.

    The question a data steward asks before trusting a field — how much of it is
    missing, what values it takes, how it is distributed — answered from the
    governed data rather than from the dictionary's description of it. A
    dictionary says what a column is supposed to contain; this says what it does.

    Read through the Data Access Layer like everything else, and only for a field
    the dictionary knows about.
    """
    from backend.data_access.catalog import get_catalog
    from backend.data_access.context import AnalysisContext
    from backend.data_access.duckdb_source import DuckDBSource

    source = DuckDBSource()
    spec = get_catalog().dataset(name)
    if field not in spec.fields:
        raise ValueError(
            f"'{field}' is not a field of {name}. A profile is offered only for "
            "the governed fields."
        )

    periods = source.periods(name)
    effective = period or (periods[-1] if periods else None)
    definition = spec.fields[field]

    frame = source.fetch(name, context=AnalysisContext(period=effective or ""),
                         fields=[field], period=effective)
    column = frame[field]
    rows = int(len(column))
    missing = int(column.isna().sum())

    out: dict[str, Any] = {
        "dataset": name,
        "field": field,
        "business_name": definition.business_name,
        "definition": definition.definition,
        "data_type": definition.data_type,
        "unit": definition.unit,
        "sensitivity": definition.sensitivity,
        "allowed_values": list(definition.allowed_values or []),
        "period": effective,
        "rows": rows,
        "missing": missing,
        "missing_pct": round(100.0 * missing / rows, 2) if rows else 0.0,
        "distinct": int(column.nunique(dropna=True)),
        "statistics": None,
        "top_values": [],
    }

    present = column.dropna()
    if present.empty:
        return out

    numeric = pd.to_numeric(present, errors="coerce").dropna()
    # "Mostly numbers" rather than "declared numeric": a column typed as text in
    # the dictionary but holding numbers still deserves the numeric summary.
    if len(numeric) >= max(1, int(0.9 * len(present))):
        out["statistics"] = {
            "min": float(numeric.min()),
            "p25": float(numeric.quantile(0.25)),
            "median": float(numeric.median()),
            "p75": float(numeric.quantile(0.75)),
            "max": float(numeric.max()),
            "mean": float(numeric.mean()),
            "sum": float(numeric.sum()),
        }

    counts = present.astype("string").value_counts().head(top)
    out["top_values"] = [
        {"value": str(value), "count": int(count),
         "share_pct": round(100.0 * int(count) / rows, 2) if rows else 0.0}
        for value, count in counts.items()
    ]
    return out


def schema_across_periods(name: str) -> dict[str, Any]:
    """Which columns each published period actually carries.

    A dataset's schema is not a fixed thing once it is loaded period by period: a
    field appears when a source system starts sending it and disappears when it
    stops. Somebody comparing Q1 with Q4 needs to know that before they wonder
    why a number moved.

    "Present" means the column exists and is not entirely empty. A column of
    nothing but nulls is, for the purpose of comparing periods, absent — and
    saying so is more useful than reporting it as there.
    """
    from backend.data_access.catalog import get_catalog
    from backend.data_access.context import AnalysisContext
    from backend.data_access.duckdb_source import DuckDBSource

    source = DuckDBSource()
    spec = get_catalog().dataset(name)
    periods = source.periods(name)
    governed = sorted(spec.fields)

    presence: dict[str, dict[str, Any]] = {}
    for period in periods:
        frame = source.fetch(name, context=AnalysisContext(period=period),
                             fields=governed, period=period)
        presence[period] = {
            "rows": int(len(frame)),
            "fields": {
                field: bool(field in frame.columns and frame[field].notna().any())
                for field in governed
            },
        }

    changes: list[dict[str, str]] = []
    for earlier, later in zip(periods, periods[1:], strict=False):
        for field in governed:
            was = presence[earlier]["fields"][field]
            now = presence[later]["fields"][field]
            if was != now:
                changes.append({
                    "field": field,
                    "period": later,
                    "change": "appeared" if now else "disappeared",
                    "from_period": earlier,
                })

    return {
        "dataset": name,
        "business_name": spec.business_name,
        "periods": periods,
        "fields": governed,
        "presence": presence,
        "changes": changes,
        "stable": not changes,
    }


#: An export is a copy of governed data leaving the product. It is capped rather
#: than unbounded so a mis-click cannot pull the whole book onto a laptop, and
#: the cap is stated in the response headers so nobody mistakes a truncated file
#: for the full one.
EXPORT_ROW_CAP = 50_000


def export_rows(name: str, *, period: str | None = None,
                fields: list[str] | None = None,
                search: str = "", filters: list[str] | None = None,
                sort: str | None = None, descending: bool = False,
                limit: int = EXPORT_ROW_CAP) -> tuple[str, dict[str, Any]]:
    """The current view, as CSV, with what it was.

    Exactly the rows the viewer is showing — same governed fields, same filters,
    same order — so the file matches the screen it came from. Returns the CSV
    text and a description of what went into it, which the caller records.
    """
    capped = max(1, min(int(limit), EXPORT_ROW_CAP))
    page = browse_dataset(name, period=period, offset=0, limit=capped,
                          fields=fields, sort=sort, descending=descending,
                          search=search, filters=filters)

    columns = [f["name"] for f in page["fields"]]
    frame = pd.DataFrame(page["rows"], columns=columns)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)

    return buffer.getvalue(), {
        "dataset": name,
        "period": page["period"],
        "columns": columns,
        "rows": int(len(frame)),
        "matched_rows": page["total_rows"],
        "truncated": page["total_rows"] > len(frame),
        "cap": capped,
        "filters": list(filters or []),
        "search": search,
        "is_synthetic": page["is_synthetic"],
        "origin": page["origin"],
    }


#: Columns that identify a row rather than describe it. Shown first whatever
#: the dataset, because a grid whose first columns are "AI Risk Score" and
#: "Appetite Breach" makes the reader hunt for which facility they are looking
#: at — and those are the columns the grid keeps on screen while you scroll.
_IDENTIFYING = ("account_id", "customer_id", "memo_id", "borrower_name")

#: Not promoted, even when they are primary keys. Every row on a page carries
#: the same period — the toolbar already says which — so spending the first and
#: most visible column on a constant is a waste of the one place the reader
#: looks first.
_CONSTANT_PER_PAGE = ("period", "period_end_date")


def _default_columns(spec) -> list[str]:
    """Every governed field, with the ones that identify a row first.

    Alphabetical order is not an order — it is the absence of one, and it puts
    "AI Risk Score" before "Borrower". The declared primary keys and the names
    a person reads a row by come first, in that order; everything else follows
    alphabetically, which at least makes a column findable.
    """
    known = set(spec.fields)
    skip = {*_CONSTANT_PER_PAGE, spec.period_field}
    leading: list[str] = []
    for name in (*spec.primary_keys, *_IDENTIFYING):
        if name in known and name not in leading and name not in skip:
            leading.append(name)
    return leading + sorted(known - set(leading))


def _is_null(value: Any) -> bool:
    """NaN is not JSON. A missing value should reach the browser as null."""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):  # pragma: no cover - arrays and the like
        return False


def dataset_tree() -> dict[str, Any]:
    """Every governed dataset, arranged domain to family to dataset to period.

    The shape a person navigates in, rather than the flat list the engine reads.
    Someone looking for "the IFRS 9 numbers for Q1" thinks in that order, and
    making them scan an alphabetical list of table names is making them do the
    grouping in their head.
    """
    from backend.data_access.catalog import get_catalog
    from backend.data_access.duckdb_source import DuckDBSource

    catalog = get_catalog()
    source = DuckDBSource()
    available = set(source.datasets())

    domains: dict[str, dict[str, Any]] = {}
    for spec in catalog.all():
        domain = domains.setdefault(
            spec.domain or "Ungrouped",
            {"domain": spec.domain or "Ungrouped", "families": {}},
        )
        family = domain["families"].setdefault(
            spec.family, {"family": spec.family, "datasets": []}
        )
        periods = source.periods(spec.name) if spec.name in available else []
        family["datasets"].append({
            "name": spec.name,
            "business_name": spec.business_name,
            "purpose": spec.purpose,
            "grain": spec.grain,
            "origin": spec.origin,
            "is_synthetic": spec.is_synthetic,
            "authoritative_for": list(spec.authoritative_for),
            "field_count": len(spec.fields),
            "periods": periods,
            "period_count": len(periods),
            "readable": spec.name in available,
        })

    return {
        "domains": [
            {
                "domain": d["domain"],
                "families": sorted(
                    (
                        {**f, "datasets": sorted(f["datasets"], key=lambda x: x["name"])}
                        for f in d["families"].values()
                    ),
                    key=lambda f: f["family"],
                ),
            }
            for d in sorted(domains.values(), key=lambda d: d["domain"])
        ],
    }
