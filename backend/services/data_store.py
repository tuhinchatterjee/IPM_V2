"""
Postgres-backed dataset store + versioned in-process cache.

Postgres is the source of truth for portfolio data. Each uploaded (or the bundled)
workbook is one `DatasetVersion`; its sheets are stored as dtype-faithful Parquet
blobs. Exactly one version is `active`.

The ~70 aggregation functions in data_loader.py still operate on the module-level
DataFrame globals. This module keeps those globals in sync with the active DB
version: `ensure_current()` runs cheaply before each request and, only when the
active version actually changes, rebuilds the DataFrames from Postgres and hands
them to `data_loader.apply_dataset_frames()`. So the compute layer is untouched and
every Waitress thread converges on the same active dataset.
"""

import hashlib
import io
import logging
import threading
import time

import pandas as pd
from sqlalchemy import select, update

from backend import data_loader as dl
from backend.db.engine import get_session
from backend.db.models import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_STAGED,
    DatasetSheet,
    DatasetVersion,
)

logger = logging.getLogger(__name__)

# Short TTL so a version switch (e.g. an activation on another thread) is picked up
# within a couple of seconds, without hitting the DB on literally every request.
_ACTIVE_ID_TTL_SECONDS = 2.0

_lock = threading.Lock()
_cached_version_id: int | None = None
_active_id_cache: dict = {"value": None, "at": 0.0}


# --------------------------------------------------------------- parquet codec

def df_to_parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def parquet_to_df(blob: bytes) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(blob))


# ------------------------------------------------------------- workbook -> sheets

def read_workbook_sheets(excel_source) -> tuple[dict, list]:
    """Read a workbook (path or BytesIO) into ({sheet_name: raw DataFrame}, quarter_sheets).
    Stores the quarterly sheets plus the supplementary sheet, each as read (no index
    set), so reconstruction mirrors data_loader's own parsing exactly."""
    with pd.ExcelFile(excel_source) as xl:
        quarter_sheets = dl.detect_quarter_sheets(xl.sheet_names)
        if not quarter_sheets:
            raise ValueError("No quarterly snapshot sheets found in the workbook.")
        sheets = {q: pd.read_excel(xl, sheet_name=q) for q in quarter_sheets}
        sheets[dl.SUPP_SHEET] = pd.read_excel(xl, sheet_name=dl.SUPP_SHEET)
    return sheets, quarter_sheets


def sheets_to_frames(sheets: dict, quarter_sheets: list) -> tuple:
    """Rebuild data_loader's (DF, SUPP_DF) exactly from stored raw sheets:
    concat the quarterly frames with the ordered Quarter categorical, and index the
    supplementary frame by Customer ID."""
    frames = [sheets[q] for q in quarter_sheets]
    df = pd.concat(frames, ignore_index=True)
    df["Quarter"] = pd.Categorical(df["Quarter"], categories=quarter_sheets, ordered=True)
    supp = sheets[dl.SUPP_SHEET].set_index("Customer ID")
    return df, supp


# ------------------------------------------------------------------ write path

def create_version(sheets: dict, quarter_sheets: list, *, source_filename: str, origin: str,
                    validation_report: dict, status: str, file_sha256: str,
                    uploaded_by: int | None = None) -> int:
    """Persist a new dataset version (+ its sheet blobs) and return its id.
    `status` is 'staged' (upload awaiting activation) or 'active' (initial seed)."""
    row_counts = {name: int(len(df)) for name, df in sheets.items()}
    with get_session() as s:
        version = DatasetVersion(
            status=status, source_filename=source_filename, origin=origin,
            file_sha256=file_sha256, uploaded_by=uploaded_by,
            validation_report=validation_report, quarter_sheets=list(quarter_sheets),
            sheet_row_counts=row_counts,
        )
        s.add(version)
        s.flush()  # assigns version.id
        for name, df in sheets.items():
            s.add(DatasetSheet(dataset_version_id=version.id, sheet_name=name,
                               row_count=int(len(df)), parquet=df_to_parquet(df)))
        vid = version.id
    logger.info("Stored dataset version %s (status=%s, origin=%s, file=%s, %d sheets)",
                vid, status, origin, source_filename, len(sheets))
    return vid


def activate_version(version_id: int) -> None:
    """Make `version_id` the sole active version: archive the current active one,
    then activate this one, in a single transaction (so the one-active index never
    sees two)."""
    with get_session() as s:
        s.execute(update(DatasetVersion)
                  .where(DatasetVersion.status == STATUS_ACTIVE)
                  .values(status=STATUS_ARCHIVED))
        s.execute(update(DatasetVersion)
                  .where(DatasetVersion.id == version_id)
                  .values(status=STATUS_ACTIVE, activated_at=pd.Timestamp.now(tz="UTC")))
    logger.info("Activated dataset version %s", version_id)
    invalidate_cache()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ------------------------------------------------------------------- read path

def get_active_version_id() -> int | None:
    now = time.monotonic()
    if now - _active_id_cache["at"] < _ACTIVE_ID_TTL_SECONDS:
        return _active_id_cache["value"]
    with get_session() as s:
        vid = s.execute(
            select(DatasetVersion.id).where(DatasetVersion.status == STATUS_ACTIVE)
        ).scalar_one_or_none()
    _active_id_cache["value"] = vid
    _active_id_cache["at"] = now
    return vid


def load_version_frames(version_id: int) -> tuple:
    """Load one version's sheets from Postgres and rebuild (df, supp, quarter_sheets,
    origin, source_filename, uploaded_at)."""
    with get_session() as s:
        version = s.get(DatasetVersion, version_id)
        if version is None:
            raise ValueError(f"Dataset version {version_id} not found.")
        quarter_sheets = list(version.quarter_sheets)
        origin, source_filename, uploaded_at = version.origin, version.source_filename, version.uploaded_at
        sheet_rows = s.execute(
            select(DatasetSheet.sheet_name, DatasetSheet.parquet)
            .where(DatasetSheet.dataset_version_id == version_id)
        ).all()
    sheets = {name: parquet_to_df(blob) for name, blob in sheet_rows}
    df, supp = sheets_to_frames(sheets, quarter_sheets)
    return df, supp, quarter_sheets, origin, source_filename, uploaded_at


def invalidate_cache() -> None:
    """Force the next ensure_current() to reload (used right after an activation)."""
    _active_id_cache["at"] = 0.0


def current_version_id() -> int | None:
    """The version currently loaded into data_loader's globals (may briefly lag the
    DB's active version until the next ensure_current)."""
    return _cached_version_id


def stage_upload(content: bytes, filename: str, validation_report: dict,
                 uploaded_by: int | None = None) -> int:
    """Validate-passed upload: parse the workbook bytes and persist a new *staged*
    version (not yet active). Returns the staged version id."""
    sheets, quarter_sheets = read_workbook_sheets(io.BytesIO(content))
    return create_version(
        sheets, quarter_sheets,
        source_filename=filename or "upload.xlsx", origin="uploaded",
        validation_report=validation_report, status=STATUS_STAGED,
        file_sha256=sha256_bytes(content), uploaded_by=uploaded_by,
    )


def bundled_version_id() -> int | None:
    """The seeded bundled version, used by 'Revert to Bundled'."""
    with get_session() as s:
        return s.execute(
            select(DatasetVersion.id).where(DatasetVersion.origin == "bundled").order_by(DatasetVersion.id)
        ).scalars().first()


def active_version_info() -> dict | None:
    with get_session() as s:
        v = s.execute(
            select(DatasetVersion).where(DatasetVersion.status == STATUS_ACTIVE)
        ).scalar_one_or_none()
        if v is None:
            return None
        return {"id": v.id, "source_filename": v.source_filename, "origin": v.origin,
                "uploaded_at": v.uploaded_at, "activated_at": v.activated_at}


def upload_history(limit: int = 10) -> list[dict]:
    """Recent dataset versions for the Data Hub audit table (newest first)."""
    with get_session() as s:
        rows = s.execute(
            select(DatasetVersion).order_by(DatasetVersion.uploaded_at.desc()).limit(limit)
        ).scalars().all()
        return [{
            "id": v.id, "source_filename": v.source_filename, "origin": v.origin,
            "status": v.status, "uploaded_at": v.uploaded_at,
            "quarters": len(v.quarter_sheets or []),
            "rows_total": sum((v.sheet_row_counts or {}).values()),
        } for v in rows]


def ensure_current() -> None:
    """Cheap per-request check: if the DB's active dataset version differs from the
    one loaded in memory, rebuild the DataFrame globals from Postgres. A DB blip is
    logged and tolerated — the app keeps serving whatever is already loaded."""
    global _cached_version_id
    try:
        active_id = get_active_version_id()
    except Exception as e:
        logger.warning("Could not read active dataset version (serving cached): %s", e)
        return
    if active_id is None or active_id == _cached_version_id:
        return
    with _lock:
        if active_id == _cached_version_id:
            return
        try:
            df, supp, quarter_sheets, origin, source_filename, uploaded_at = load_version_frames(active_id)
        except Exception as e:
            logger.exception("Failed to load dataset version %s from Postgres: %s", active_id, e)
            return
        dl.apply_dataset_frames(df, supp, quarter_sheets, source=origin,
                                loaded_at=uploaded_at, path=None)
        _cached_version_id = active_id
        logger.info("Dataset globals now serving version %s (origin=%s, file=%s)",
                    active_id, origin, source_filename)
