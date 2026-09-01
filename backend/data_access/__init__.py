"""
Data Access Layer — the boundary between analytics and physical storage.

Import `get_data_source()` to obtain the configured source. Everything above this
package works in governed dataset and field names and never knows, or needs to
know, whether the data is in Parquet, PostgreSQL or a lakehouse.

    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext

    source = get_data_source()
    ctx = AnalysisContext(period="Q1 2026", filters={"sector": "Real Estate"})
    by_stage = source.aggregate(
        "portfolio_facility", context=ctx, group_by=["ifrs9_stage"], measures={"ead": "sum"}
    )

Which backend is used is a configuration decision (`IPM_DATA_SOURCE`), not a code
decision. Today only "duckdb" exists; Phase 2+ may add others, and a lakehouse
adapter is the anticipated production choice.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from backend.data_access.catalog import Catalog, get_catalog, reload_catalog
from backend.data_access.context import AnalysisContext
from backend.data_access.protocol import (
    DataAccessError,
    DataSource,
    UnknownDatasetError,
    UnknownFieldError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AnalysisContext",
    "Catalog",
    "DataAccessError",
    "DataSource",
    "UnknownDatasetError",
    "UnknownFieldError",
    "get_catalog",
    "get_data_source",
    "reload_catalog",
    "reset_data_source",
]


@lru_cache(maxsize=1)
def get_data_source() -> DataSource:
    """The configured analytical data source, created once per process."""
    kind = os.environ.get("IPM_DATA_SOURCE", "duckdb").strip().lower()
    if kind == "duckdb":
        # Imported lazily so that nothing outside this package pulls in duckdb.
        from backend.data_access.duckdb_source import DuckDBSource

        logger.info("Analytical data source: DuckDB over Parquet")
        return DuckDBSource()
    raise DataAccessError(
        f"Unknown IPM_DATA_SOURCE={kind!r}. Supported values: 'duckdb'. "
        "A lakehouse adapter (Databricks / Snowflake) implements the same "
        "DataSource protocol and is selected here — see docs/ARCHITECTURE.md §3."
    )


def reset_data_source() -> None:
    """Drop the cached source — used by tests and after rebuilding the lake."""
    get_data_source.cache_clear()
