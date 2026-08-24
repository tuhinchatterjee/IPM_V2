"""
The Data Access Layer contract.

This is the single most important boundary in the backend. Everything above it
(the CreditProbe Engine, the orchestration layer, the API) asks for *governed datasets by
name*. Everything below it (DuckDB over Parquet today; Databricks, Snowflake or
another bank lakehouse later) decides how that request is physically satisfied.

The rule:

    The CreditProbe Engine never writes SQL, never opens a file, and never imports duckdb.
    It calls fetch() / aggregate() with governed names and gets a DataFrame back.

That is what makes the storage swappable. When the bank moves its analytical data
to a lakehouse, a new class implements this Protocol and one configuration line
changes. Not a single line of credit-risk maths is touched.

`Protocol` here is Python's structural typing: any class providing these methods
satisfies the contract without needing to inherit from anything.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd

from backend.data_access.context import AnalysisContext

# How a column should be reduced when aggregating.
Aggregation = str  # "sum" | "mean" | "min" | "max" | "count" | "nunique"


class DataAccessError(RuntimeError):
    """Raised when a request cannot be satisfied — unknown dataset, unknown field,
    missing period, or an unreadable source. Always carries a message a
    non-developer can act on, because these surface in the UI."""


class UnknownDatasetError(DataAccessError):
    pass


class UnknownFieldError(DataAccessError):
    pass


@runtime_checkable
class DataSource(Protocol):
    """The interface every physical storage backend must satisfy."""

    name: str

    def datasets(self) -> list[str]:
        """Governed dataset names this source can serve."""
        ...

    def fields(self, dataset: str) -> list[str]:
        """Governed field names available on a dataset."""
        ...

    def periods(self, dataset: str) -> list[str]:
        """Reporting periods present, oldest first, e.g. ["Q4 2023", ...]."""
        ...

    def fetch(
        self,
        dataset: str,
        *,
        context: AnalysisContext,
        fields: list[str] | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """Row-level read of one dataset for one period, with the context's
        filters applied. `fields=None` means all fields.

        `period` overrides `context.period` — needed by comparison analyses that
        read the prior period within the same context.
        """
        ...

    def aggregate(
        self,
        dataset: str,
        *,
        context: AnalysisContext,
        group_by: list[str],
        measures: dict[str, Aggregation],
        period: str | None = None,
    ) -> pd.DataFrame:
        """Grouped aggregation, pushed down to the storage engine.

        This is the method that makes the platform scale. `fetch()` brings rows
        back into Python; `aggregate()` asks the storage engine to do the
        summing and returns only the summary. On a real bank portfolio that is
        the difference between moving millions of rows and moving a few hundred.

        `measures` maps output column name -> aggregation, e.g. {"ead": "sum"}.
        """
        ...

    def health(self) -> dict[str, Any]:
        """Whether this source is usable right now, for the /health endpoint."""
        ...
