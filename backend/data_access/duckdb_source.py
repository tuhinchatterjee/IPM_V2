"""
DuckDB adapter — Parquet files on disk, queried with SQL.

This is the ONLY module in the backend permitted to import duckdb. Everything
above the Data Access Layer works in governed dataset and field names; the
translation into SQL happens here and nowhere else. Swapping to a bank lakehouse
means writing a sibling of this file, not editing the engine.

Why DuckDB and Parquet
----------------------
Parquet stores a table column by column. Asking for the total exposure of two
million facilities reads one column, not two million rows. DuckDB runs SQL
directly against those files with no server to install and no data to load first.

The important behaviour is *pushdown*: filtering and grouping happen inside
DuckDB, over the files, and only the summarised result crosses into Python. On a
real portfolio that is the difference between moving millions of rows and moving
a few hundred.

Safety note
-----------
Governed identifiers (dataset and field names) come from the catalogue, never
from user input, and are additionally validated against a strict pattern before
being interpolated into SQL. Filter *values* — which can originate from a user or
from the LLM's plan — are always passed as bound parameters, never interpolated.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from backend.config import settings
from backend.data_access.catalog import Catalog, DatasetDef, get_catalog
from backend.data_access.context import AnalysisContext
from backend.data_access.protocol import Aggregation, DataAccessError

logger = logging.getLogger(__name__)

# Governed names are machine-generated and controlled; this is belt-and-braces so
# a malformed catalogue entry can never become a SQL injection vector.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_SUPPORTED_AGGREGATIONS = {"sum", "mean", "min", "max", "count", "nunique"}
_SQL_AGGREGATION = {
    "sum": "SUM",
    "mean": "AVG",
    "min": "MIN",
    "max": "MAX",
    "count": "COUNT",
    "nunique": "COUNT(DISTINCT",  # closed explicitly in _measure_sql
}


def _check_identifier(name: str, kind: str) -> str:
    if not _SAFE_IDENTIFIER.match(name):
        raise DataAccessError(f"Unsafe {kind} name in catalogue: {name!r}")
    return name


class DuckDBSource:
    """Serves governed datasets from Parquet files under the analytics layer.

    Layout on disk, one directory per dataset, one file per reporting period:

        data/analytics/portfolio_facility/period=Q1 2026/data.parquet
        data/analytics/portfolio_facility/period=Q4 2025/data.parquet
    """

    name = "duckdb"

    def __init__(self, root: Path | None = None, catalog: Catalog | None = None):
        self.root = root or settings.analytics_dir
        self._catalog = catalog
        # One connection, guarded by a lock. DuckDB connections are not thread-safe,
        # and FastAPI serves requests on a thread pool.
        self._conn = duckdb.connect(database=":memory:")
        self._lock = threading.Lock()

    @property
    def catalog(self) -> Catalog:
        return self._catalog if self._catalog is not None else get_catalog()

    # ------------------------------------------------------------------ layout

    def _dataset_dir(self, dataset: str) -> Path:
        return self.root / dataset

    def _glob(self, dataset: str, period: str | None) -> str:
        """The Parquet path pattern for a dataset, optionally one period."""
        base = self._dataset_dir(dataset)
        if period:
            # Period values contain a space ("Q1 2026"); DuckDB handles that fine
            # inside a quoted path string.
            return str(base / f"period={period}" / "*.parquet")
        return str(base / "**" / "*.parquet")

    def _require_files(self, dataset: str, period: str | None) -> str:
        pattern = self._glob(dataset, period)
        directory = self._dataset_dir(dataset)
        if not directory.exists():
            raise DataAccessError(
                f"No data on disk for dataset '{dataset}'. Expected {directory}. "
                "Run `python scripts/build_data_lake.py` to build the analytical layer."
            )
        if period and not (directory / f"period={period}").exists():
            available = ", ".join(self.periods(dataset)) or "(none)"
            raise DataAccessError(
                f"Dataset '{dataset}' has no data for period '{period}'. Available: {available}"
            )
        return pattern

    # ------------------------------------------------------------- discovery

    def datasets(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith("."))

    def fields(self, dataset: str) -> list[str]:
        return sorted(self.catalog.dataset(dataset).fields)

    def periods(self, dataset: str) -> list[str]:
        directory = self._dataset_dir(dataset)
        if not directory.exists():
            return []
        found = [p.name.split("=", 1)[1] for p in directory.iterdir() if p.is_dir() and "=" in p.name]
        return sorted(found, key=_period_sort_key)

    # ------------------------------------------------------------------ query

    def _where(self, spec: DatasetDef, context: AnalysisContext) -> tuple[str, list[Any]]:
        """Build the WHERE clause from the context's active filters.

        Values are bound parameters (`?`), never interpolated — filter values may
        come from a user or from an LLM-produced plan, so they are treated as
        untrusted input throughout.
        """
        clauses: list[str] = []
        params: list[Any] = []
        for field_name, value in context.active_filters.items():
            if field_name not in spec.fields:
                # A filter naming a field this dataset does not have is ignored
                # rather than fatal: the cockpit applies a global filter set across
                # several datasets, and not every dataset carries every dimension.
                logger.debug("Ignoring filter %r — not a field of %s", field_name, spec.name)
                continue
            column = _check_identifier(field_name, "field")
            if isinstance(value, list):
                if not value:
                    continue
                placeholders = ", ".join("?" for _ in value)
                clauses.append(f'"{column}" IN ({placeholders})')
                params.extend(value)
            else:
                clauses.append(f'"{column}" = ?')
                params.append(value)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params

    def _run(self, sql: str, params: list[Any]) -> pd.DataFrame:
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetch_df()
            except duckdb.Error as e:
                logger.exception("DuckDB query failed: %s", sql)
                raise DataAccessError(f"Query failed against the analytical store: {e}") from e

    def fetch(
        self,
        dataset: str,
        *,
        context: AnalysisContext,
        fields: list[str] | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        spec = self.catalog.dataset(dataset)
        effective_period = period or context.period
        pattern = self._require_files(dataset, effective_period)

        if fields:
            for f in fields:
                spec.field(f)  # raises UnknownFieldError with a helpful message
            select = ", ".join(f'"{_check_identifier(f, "field")}"' for f in fields)
        else:
            select = "*"

        where, params = self._where(spec, context)
        sql = f"SELECT {select} FROM read_parquet(?, hive_partitioning = true){where}"
        return self._run(sql, [pattern, *params])

    def _measure_sql(self, column: str, how: Aggregation, alias: str) -> str:
        if how not in _SUPPORTED_AGGREGATIONS:
            raise DataAccessError(
                f"Unsupported aggregation {how!r}. Supported: {', '.join(sorted(_SUPPORTED_AGGREGATIONS))}"
            )
        col = _check_identifier(column, "field")
        out = _check_identifier(alias, "measure alias")
        if how == "nunique":
            return f'COUNT(DISTINCT "{col}") AS "{out}"'
        return f'{_SQL_AGGREGATION[how]}("{col}") AS "{out}"'

    def aggregate(
        self,
        dataset: str,
        *,
        context: AnalysisContext,
        group_by: list[str],
        measures: dict[str, Aggregation],
        period: str | None = None,
    ) -> pd.DataFrame:
        """Grouped aggregation pushed down into DuckDB.

        `measures` maps a field name to how it should be reduced, e.g.
        {"ead": "sum", "customer_id": "nunique"}. The output column takes the
        field's name.
        """
        spec = self.catalog.dataset(dataset)
        effective_period = period or context.period
        pattern = self._require_files(dataset, effective_period)

        for f in [*group_by, *measures]:
            spec.field(f)

        selects = [f'"{_check_identifier(g, "field")}"' for g in group_by]
        selects += [self._measure_sql(col, how, col) for col, how in measures.items()]

        where, params = self._where(spec, context)
        group_clause = ""
        if group_by:
            group_clause = " GROUP BY " + ", ".join(f'"{g}"' for g in group_by)
            group_clause += " ORDER BY " + ", ".join(f'"{g}"' for g in group_by)

        sql = (
            f"SELECT {', '.join(selects)} "
            f"FROM read_parquet(?, hive_partitioning = true)"
            f"{where}{group_clause}"
        )
        return self._run(sql, [pattern, *params])

    # ----------------------------------------------------------------- health

    def health(self) -> dict[str, Any]:
        datasets = self.datasets()
        detail: dict[str, Any] = {
            "source": self.name,
            "root": str(self.root),
            "root_exists": self.root.exists(),
            "dataset_count": len(datasets),
            "datasets": datasets,
        }
        if datasets:
            first = datasets[0]
            detail["periods_sample"] = {first: self.periods(first)}
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            detail["status"] = "ok" if datasets else "empty"
        except duckdb.Error as e:  # pragma: no cover - defensive
            detail["status"] = "error"
            detail["error"] = str(e)
        return detail


def _period_sort_key(period: str) -> tuple[int, int]:
    """Sort "Q1 2026" chronologically rather than alphabetically.

    Alphabetical ordering puts "Q1 2024" before "Q4 2023", which would silently
    reverse every trend chart in the product.
    """
    m = re.match(r"^Q([1-4])\s+(\d{4})$", period.strip())
    if not m:
        return (9999, 9)
    return (int(m.group(2)), int(m.group(1)))
