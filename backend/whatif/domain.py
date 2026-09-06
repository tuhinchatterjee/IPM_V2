"""
The Corporate IFRS 9 domain, and the fact that What-If may not leave it.

Why this module is the only door
-------------------------------
What-If answers one question — "if I change a risk assumption, what happens to
ECL?" — and it answers it about ONE book: Corporate IFRS 9, at obligor grain.

Letting the scenario engine reach across the catalogue would cost more than it
bought. The credit book (`portfolio_facility`, `ifrs9_staging`) is a different
grain, a different rating scale and a different staging ruleset; a join across
the two produces a number that is arithmetically fine and means nothing. And a
model asked to find a field anywhere in seventy-three datasets will eventually
find something plausible and wrong.

So every read in the What-If package goes through this module, `DATASETS` is
the whole world, and a field that is not here produces a REFUSAL that names
what the domain does carry. "I cannot see that field in Corporate IFRS 9" is a
better answer than a number assembled from somewhere else.

Grain
-----
`(borrower_id, period)`. Corporate staging is assessed on the counterparty, so
the book is one row per borrower per quarter. Facilities and collateral are
finer and are aggregated UP to that grain here, never joined out to it —
joining the borrower snapshot to a per-test or per-item table multiplies every
exposure figure by the number of rows the borrower happens to have.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

DOMAIN_KEY = "ifrs9"
DOMAIN_NAME = "CORPORATE IFRS 9"
DOMAIN_OWNER = "Impairment"

#: The borrower-grain snapshot the engine reads first.
SNAPSHOT = "corporate_borrower_360"
#: The authoritative staging and measurement dataset.
IFRS9 = "corporate_ifrs9"
#: Finer-grain datasets, aggregated up rather than joined out.
FACILITIES = "corporate_facilities"
COLLATERAL = "corporate_collateral"
#: Aperiodic reference series.
MACRO = "corporate_macro"

#: Everything What-If is allowed to read. There is no other door.
DATASETS: tuple[str, ...] = (SNAPSHOT, IFRS9, FACILITIES, COLLATERAL, MACRO)

CURRENCY = "SAR"
GRAIN = "One row per borrower per quarter (obligor staging)."

#: Columns the IFRS 9 dataset contributes that the snapshot does not carry.
#: `pd_at_origination_pct` is the one that matters: without it the relative
#: SICR trigger cannot be re-evaluated against a hypothetical PD, and the
#: staging question silently degrades to the absolute-PD test alone.
IFRS9_FIELDS: tuple[str, ...] = (
    "borrower_id", "period", "pd_at_origination_pct",
    "sicr_trigger_pd", "sicr_trigger_dpd", "sicr_trigger_watchlist",
    "prior_stage", "stage_moved",
)


class DomainError(ValueError):
    """A read this domain cannot serve, said plainly rather than worked around."""


class PeriodError(DomainError):
    """A period the book does not publish."""


# ------------------------------------------------------------------ reading


def _source(source: Any = None) -> Any:
    if source is not None:
        return source
    from backend.data_access.duckdb_source import DuckDBSource

    return DuckDBSource()


def periods(source: Any = None) -> list[str]:
    """Every period Corporate IFRS 9 publishes, oldest first.

    Read from the IFRS 9 dataset rather than the snapshot: the snapshot COPIES
    stage and ECL and is never authoritative over them, so if the two ever
    disagree about which quarters exist, the measurement dataset is the one to
    believe.
    """
    reader = _source(source)
    found = list(reader.periods(IFRS9))
    return found or list(reader.periods(SNAPSHOT))


def latest_period(source: Any = None) -> str:
    found = periods(source)
    if not found:
        raise PeriodError(
            "The Corporate IFRS 9 book publishes no periods. The analytical "
            "lake has not been built — run scripts/build_corporate_universe.py.")
    return str(found[-1])


def resolve_period(said: str = "", source: Any = None) -> str:
    """The period a person named, including the words they actually use.

    An empty string means the latest, which is what a question with no period
    in it is asking for. `latest`, `earliest` and `previous` are resolved
    against the book rather than assumed, and anything else must be a period
    the book publishes — a period that does not exist is a refusal that lists
    the ones that do, never the nearest match.
    """
    available = periods(source)
    if not available:
        raise PeriodError(
            "The Corporate IFRS 9 book publishes no periods. The analytical "
            "lake has not been built.")
    wanted = str(said or "").strip()
    if not wanted or wanted.lower() == "latest":
        return str(available[-1])
    if wanted.lower() == "earliest":
        return str(available[0])
    if wanted.lower() == "previous":
        return str(available[-2] if len(available) > 1 else available[0])
    for candidate in available:
        if str(candidate).lower() == wanted.lower():
            return str(candidate)
    raise PeriodError(
        f"Corporate IFRS 9 does not publish '{wanted}'. It publishes "
        f"{available[0]} to {available[-1]} — {len(available)} quarters.")


def prior_year(period: str, source: Any = None) -> str | None:
    """The same quarter one year earlier, if the book goes back that far.

    Returned as None rather than raising, because a migration view whose prior
    year is missing is a thing to explain on screen, not an error.
    """
    available = periods(source)
    settled = resolve_period(period, source)
    try:
        at = available.index(settled)
    except ValueError:  # pragma: no cover - resolve_period already checked
        return None
    return str(available[at - 4]) if at >= 4 else None


@functools.lru_cache(maxsize=64)
def _cached(dataset: str, period: str) -> pd.DataFrame:
    """One period of one dataset, read once.

    Cached because a single guided journey asks for the same quarter of the
    same book five or six times — the profile, the migration, the population,
    the baseline and the result all read it — and re-reading Parquet each time
    is the difference between a screen that answers and one that thinks.
    """
    from backend.data_access.duckdb_source import DuckDBSource

    reader = DuckDBSource()
    pattern = reader._require_files(dataset, period or None)
    import duckdb

    return duckdb.sql(f"SELECT * FROM read_parquet('{pattern}')").df()


def reset_cache() -> None:
    """Forget what was read. Called when the lake is rebuilt under a test."""
    _cached.cache_clear()


def read(dataset: str, period: str = "", source: Any = None) -> pd.DataFrame:
    """One dataset, for one period, from inside this domain only."""
    if dataset not in DATASETS:
        raise DomainError(
            f"'{dataset}' is not part of {DOMAIN_NAME}. What-If reads "
            f"{', '.join(DATASETS)} and nothing else.")
    if dataset == MACRO:
        return _cached(MACRO, "").copy()
    settled = resolve_period(period, source)
    return _cached(dataset, settled).copy()


def book(period: str = "", *, columns: tuple[str, ...] = (),
         source: Any = None) -> tuple[pd.DataFrame, str]:
    """The Corporate IFRS 9 book for one period, at obligor grain.

    The snapshot joined to the measurement dataset on `(borrower_id, period)`
    — a one-to-one join at the same grain, so no figure is multiplied. Returns
    the frame and the period actually used, because "which quarter was that?"
    is part of every answer.
    """
    settled = resolve_period(period, source)
    snapshot = _cached(SNAPSHOT, settled)
    measured = _cached(IFRS9, settled)

    keep = [c for c in IFRS9_FIELDS if c in measured.columns]
    frame = snapshot.merge(measured[keep], on=["borrower_id", "period"],
                           how="left", suffixes=("", "_ifrs9"))
    if columns:
        wanted = [c for c in columns if c in frame.columns]
        missing = [c for c in columns if c not in frame.columns]
        if missing:
            raise DomainError(field_refusal(missing))
        frame = frame[wanted]
    return frame.copy(), settled


# ------------------------------------------------------------- aggregation


def facility_ccf(period: str = "", source: Any = None) -> pd.DataFrame:
    """Credit conversion factors, brought up to obligor grain.

    The snapshot does not carry a CCF: it is a facility attribute, and a
    borrower with a revolver and a term loan has two of them. Aggregated as an
    UNDRAWN-WEIGHTED mean, because that is the CCF that reproduces the
    borrower's own EAD — a plain average would weight a tiny facility the same
    as the one the exposure is actually in.
    """
    frame = read(FACILITIES, period, source)
    if frame.empty:
        return pd.DataFrame(columns=["borrower_id", "ccf", "drawn_exposure",
                                     "undrawn_commitment", "facility_count"])
    work = frame.copy()
    for column in ("credit_conversion_factor", "drawn_exposure",
                   "undrawn_commitment", "ifrs9_ead"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)
    work["_weighted"] = work.get("credit_conversion_factor", 0.0) * work.get(
        "undrawn_commitment", 0.0)
    grouped = work.groupby("borrower_id", as_index=False).agg(
        _weighted=("_weighted", "sum"),
        undrawn_commitment=("undrawn_commitment", "sum"),
        drawn_exposure=("drawn_exposure", "sum"),
        ifrs9_ead=("ifrs9_ead", "sum"),
        facility_count=("facility_id", "count"))
    undrawn = grouped["undrawn_commitment"].replace(0, np.nan)
    plain = work.groupby("borrower_id")["credit_conversion_factor"].mean()
    grouped["ccf"] = (grouped["_weighted"] / undrawn).fillna(
        grouped["borrower_id"].map(plain)).fillna(0.0)
    return grouped.drop(columns=["_weighted"])


def collateral_detail(period: str = "", source: Any = None) -> pd.DataFrame:
    """Collateral items with their haircuts, at item grain.

    Deliberately NOT aggregated: the collateral question a person asks is
    "which types, and what haircut?", which is a question about items. Callers
    that need a borrower total use `collateral_by_borrower`.
    """
    return read(COLLATERAL, period, source)


def collateral_by_borrower(period: str = "", source: Any = None) -> pd.DataFrame:
    """Collateral summed to obligor grain, with the implied haircut."""
    frame = read(COLLATERAL, period, source)
    if frame.empty:
        return pd.DataFrame(columns=["borrower_id", "collateral_market_value",
                                     "collateral_eligible_value",
                                     "implied_haircut_pct", "collateral_count"])
    work = frame.copy()
    for column in ("collateral_market_value", "collateral_eligible_value"):
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)
    grouped = work.groupby("borrower_id", as_index=False).agg(
        collateral_market_value=("collateral_market_value", "sum"),
        collateral_eligible_value=("collateral_eligible_value", "sum"),
        collateral_count=("collateral_id", "count"))
    gross = grouped["collateral_market_value"].replace(0, np.nan)
    grouped["implied_haircut_pct"] = (
        (1.0 - grouped["collateral_eligible_value"] / gross) * 100.0).fillna(0.0)
    return grouped


def macro(source: Any = None) -> pd.DataFrame:
    """The observed macro series, oldest first. Aperiodic — every row at once."""
    frame = read(MACRO, "", source)
    if "period_end_date" in frame.columns:
        return frame.sort_values("period_end_date").reset_index(drop=True)
    return frame


# ---------------------------------------------------------------- refusals


@functools.lru_cache(maxsize=1)
def _fields() -> dict[str, tuple[str, ...]]:
    """Every field this domain carries, by dataset. Read once from the lake."""
    out: dict[str, tuple[str, ...]] = {}
    for dataset in DATASETS:
        try:
            frame = read(dataset, "")
        except Exception:  # pragma: no cover - an unbuilt lake
            continue
        out[dataset] = tuple(frame.columns)
    return out


def fields() -> dict[str, tuple[str, ...]]:
    return dict(_fields())


def has_field(name: str) -> bool:
    said = str(name or "").strip().lower()
    return any(said in {c.lower() for c in columns}
               for columns in _fields().values())


def field_refusal(names: list[str] | tuple[str, ...] | str) -> str:
    """Why a field cannot be served, naming the domain rather than guessing.

    This is the sentence that keeps What-If honest. The alternative — quietly
    finding the name in another business domain and joining it in — produces an
    answer that looks complete and describes a book that does not exist.
    """
    wanted = [names] if isinstance(names, str) else list(names)
    known = _fields()
    close: list[str] = []
    for name in wanted:
        said = str(name).lower()
        for dataset, columns in known.items():
            close.extend(f"{c} ({dataset})" for c in columns
                         if said and (said in c.lower() or c.lower() in said))
    head = (f"{DOMAIN_NAME} does not carry "
            f"{', '.join(repr(str(n)) for n in wanted)}.")
    if close:
        return head + " The nearest fields it does carry are: " + \
            ", ".join(sorted(set(close))[:8]) + "."
    return head + (" What-If reads this domain only, and will not join another "
                   "business domain to answer a Corporate IFRS 9 question.")


@dataclass(frozen=True)
class Binding:
    """What a screen shows about where its numbers came from."""

    period: str
    periods: tuple[str, ...]
    rows: int
    borrowers: int

    def to_dict(self) -> dict[str, Any]:
        return {"domain": DOMAIN_NAME, "domain_key": DOMAIN_KEY,
                "owner": DOMAIN_OWNER, "datasets": list(DATASETS),
                "grain": GRAIN, "currency": CURRENCY,
                "period": self.period, "periods": list(self.periods),
                "rows": self.rows, "borrowers": self.borrowers,
                "restriction": (
                    "What-If Analysis reads Corporate IFRS 9 only. A field "
                    "outside this domain is refused rather than sourced "
                    "elsewhere.")}


def binding(period: str = "", source: Any = None) -> Binding:
    """The provenance line every What-If answer carries."""
    frame, settled = book(period, source=source)
    return Binding(period=settled, periods=tuple(periods(source)),
                   rows=int(len(frame)),
                   borrowers=int(frame["borrower_id"].nunique())
                   if "borrower_id" in frame.columns else 0)


__all__ = [
    "Binding", "COLLATERAL", "CURRENCY", "DATASETS", "DOMAIN_KEY",
    "DOMAIN_NAME", "DOMAIN_OWNER", "DomainError", "FACILITIES", "GRAIN",
    "IFRS9", "IFRS9_FIELDS", "MACRO", "PeriodError", "SNAPSHOT", "binding",
    "book", "collateral_by_borrower", "collateral_detail", "facility_ccf",
    "field_refusal", "fields", "has_field", "latest_period", "macro",
    "periods", "prior_year", "read", "reset_cache", "resolve_period",
]
