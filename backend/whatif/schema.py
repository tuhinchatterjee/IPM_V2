"""
The one schema contract between the Corporate universe and What-If.

Why this module exists
----------------------
What-If names columns in a query. The Corporate universe generator writes
them. In between sit a governed catalogue that *declares* them and a Parquet
lake that *contains* them, and those two can disagree — a catalogue registered
by one build against a lake written by another, or a lake rebuilt in place
where old `period=` partitions survived a schema change.

When they disagreed, the engine asked DuckDB for a column that was not there
and DuckDB answered:

    Referenced column "cash_conversion_cycle_days" not found in FROM clause

which reached a credit officer as "CreditProbe could not complete that
request". A missing working-capital statistic had stopped the entire ECL
calculation, and nothing on the screen said which field, or why, or that the
provision itself was perfectly computable without it.

So this module is the single place that answers three questions, and every
What-If read goes through it:

  * WHAT DOES THE BOOK ACTUALLY CARRY? Resolved from the Parquet schema —
    `DuckDBSource.columns()` — never from the catalogue. The catalogue is the
    contract; the file is the cargo; a SELECT binds against the cargo.

  * WHICH FIELDS ARE LOAD-BEARING? `REQUIRED` is the set without which there
    is no ECL at all. A missing one is a real failure and is raised as a
    `SchemaError` naming the field, the dataset and the command that rebuilds
    it — not swallowed, not defaulted to zero, and not a binder error.

  * WHAT DOES EACH OPTIONAL FIELD BUY? `OPTIONAL` maps a field to the
    capability it enables. A book without `cash_conversion_cycle_days` can
    still price every scenario; it simply cannot shock the cash conversion
    cycle, and the run says exactly that instead of failing or pretending.

What this module will not do
----------------------------
It will not catch the binder error and carry on. Resolving the columns BEFORE
the query is the fix; catching the exception after would leave the caller
unable to say what it lost. It will not invent a column, fill an absent field
with zero, or silently drop a shock somebody asked for — an unanswerable
instruction is refused out loud, because a scenario that quietly does nothing
is indistinguishable on screen from one that did nothing because nothing moved.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "1.0.0"
SCHEMA_OWNER = "Credit Risk Analytics"

SNAPSHOT = "corporate_borrower_360"
IFRS9 = "corporate_ifrs9"

#: Without these there is no What-If. They identify the borrower, place it in
#: the book, and carry the four quantities the governed measurement multiplies
#: together. A book missing any of them is not a Corporate IFRS 9 book.
REQUIRED: tuple[str, ...] = (
    "borrower_id", "period", "sector",
    "internal_rating", "internal_rating_numeric",
    "stage", "pd_12m", "pd_lifetime", "lgd", "ead", "final_ecl",
    "current_dpd", "default_flag",
)

#: Everything else, and what its absence actually costs. The value is written
#: to be read by somebody who is not a developer: it says which part of the
#: product stops working, not which line of code.
OPTIONAL: dict[str, str] = {
    "ttc_pd_pct": "anchoring the lifetime PD on the grade's through-the-cycle "
                  "level, so a stressed borrower is not assumed to stay "
                  "stressed for four years",
    "display_name": "borrower names on the result table",
    "legal_name": "legal names on the result table",
    "segment": "narrowing a scenario by segment",
    "group_id": "grouping borrowers by connected group",
    "group_name": "group names on the result table",
    "watchlist_flag": "narrowing a scenario to the watchlist",
    "ecl_12m": "the 12-month ECL column",
    "ecl_lifetime": "the lifetime ECL column",
    "management_overlay": "showing the overlay apart from the modelled ECL",
    "ecl_coverage": "the reported coverage ratio",
    "collateral_market_value": "collateral shocks and haircuts",
    "collateral_coverage_pct": "collateral shocks and haircuts",
    "collateral_shortfall": "reporting collateral shortfalls",
    "secured_exposure": "mapping a collateral loss onto the secured share only",
    "unsecured_exposure": "mapping a collateral loss onto the secured share only",
    "undrawn_commitment": "CCF and EAD shocks, which cap at the undrawn commitment",
    "total_limit": "reporting utilisation",
    "drawn_exposure": "CCF shocks",
    "covenants_breached": "reporting covenant breaches",
    "minimum_headroom_pct": "reporting covenant headroom",
    "covenant_count": "reporting how many covenants a borrower has",
    "revenue": "shocking revenue",
    "ebitda": "shocking EBITDA",
    "ebitda_margin": "shocking the EBITDA margin",
    "dscr": "carrying an earnings shock into debt service",
    "interest_coverage": "carrying an earnings shock into interest cover",
    "leverage": "reporting leverage",
    "net_leverage": "reporting net leverage",
    "free_cash_flow": "shocking free cash flow",
    "working_capital": "shocking working capital",
    "cash_conversion_cycle_days": "shocking the cash conversion cycle",
}

#: On the IFRS 9 measurement dataset rather than the snapshot. Optional in the
#: same sense: without the origination PD the RELATIVE SICR trigger cannot be
#: re-evaluated, which is a real reduction in the answer and is reported as
#: one — but it is not a reason to refuse to price the scenario.
IFRS9_REQUIRED: tuple[str, ...] = ("borrower_id", "period")
IFRS9_OPTIONAL: dict[str, str] = {
    "pd_at_origination_pct": "re-evaluating the relative SICR trigger, which "
                             "compares the stressed PD against origination",
    "sicr_trigger_pd": "naming which SICR trigger fired",
    "sicr_trigger_dpd": "naming which SICR trigger fired",
    "sicr_trigger_watchlist": "naming which SICR trigger fired",
    "stage_measured": "reproducing the reported book's staging exactly. The "
                      "book's staging has a MEMORY — a borrower whose trigger "
                      "stops firing serves a cure probation before it returns "
                      "to Stage 1 — so a row has to say what its triggers "
                      "measured as well as what stage it is carried at. "
                      "Without it the governed rule set falls back to the "
                      "measured stage, and the baseline column of a What-If "
                      "can differ from the book by the borrowers currently "
                      "serving probation.",
    "sicr_clear_quarters": "the other half of that: how many consecutive "
                           "quarters the borrower has been clear, which is "
                           "what decides whether the probation is served. It "
                           "is also what lets the ML model tell a carried "
                           "Stage 2 borrower from a Stage 1 one with the same "
                           "features.",
}

ALL_SNAPSHOT: tuple[str, ...] = (*REQUIRED, *OPTIONAL)
ALL_IFRS9: tuple[str, ...] = (*IFRS9_REQUIRED, *IFRS9_OPTIONAL)

#: How a person rebuilds the book, named in every refusal so the message is
#: actionable rather than merely accurate.
REBUILD = "uv run python scripts/build_corporate_universe.py"


class SchemaError(ValueError):
    """A field What-If cannot do without, named rather than left to DuckDB."""


@dataclass(frozen=True)
class Resolution:
    """Which of the wanted fields are really there, and what the rest cost."""

    dataset: str
    present: tuple[str, ...]
    absent: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.absent

    def warnings(self) -> list[str]:
        """One sentence per absent field, saying what stopped working.

        Written for the result panel: it names the field, the dataset, the
        capability and the command, because a warning a reader cannot act on
        is decoration.
        """
        out = []
        for field in self.absent:
            lost = OPTIONAL.get(field) or IFRS9_OPTIONAL.get(field) or ""
            out.append(
                f"'{field}' is not in {self.dataset} in this installation"
                + (f", so {lost} is unavailable. " if lost else ". ")
                + "Every other figure below is unaffected. Rebuild the book "
                  f"with `{REBUILD}` to restore it.")
        return out


def _reader(source: Any = None) -> Any:
    if source is not None:
        return source
    from backend.data_access.duckdb_source import DuckDBSource

    return DuckDBSource()


@functools.lru_cache(maxsize=8)
def _columns_cached(dataset: str, marker: str) -> tuple[str, ...]:
    from backend.data_access.duckdb_source import DuckDBSource

    del marker
    return tuple(DuckDBSource().columns(dataset))


def columns(dataset: str, source: Any = None) -> tuple[str, ...]:
    """The columns the dataset ACTUALLY carries, from the Parquet schema.

    Cached: a guided journey resolves the same schema five or six times, and
    the answer cannot change inside one request. `reset_cache` is what a test
    that rebuilds the lake calls.
    """
    if source is not None:
        got = getattr(source, "columns", None)
        if callable(got):
            return tuple(got(dataset))
        # A source that predates `columns()` can still be asked for its
        # catalogue fields; it is a weaker answer and it is not silently
        # treated as an equal one.
        return tuple(source.fields(dataset))
    return _columns_cached(dataset, "")


def reset_cache() -> None:
    """Forget the resolved schema. For a test that rebuilds the lake."""
    _columns_cached.cache_clear()


def resolve(dataset: str, wanted: tuple[str, ...], *,
            required: tuple[str, ...] = (), source: Any = None) -> Resolution:
    """Split the wanted fields into what is there and what is not.

    A missing REQUIRED field raises here, with the field named, rather than
    reaching DuckDB and coming back as a binder error about a FROM clause.
    """
    have = set(columns(dataset, source))
    missing_required = [f for f in required if f not in have]
    if missing_required:
        raise SchemaError(
            f"{dataset} in this installation does not carry "
            f"{', '.join(repr(f) for f in missing_required)}, and What-If "
            "cannot compute an expected credit loss without "
            f"{'them' if len(missing_required) > 1 else 'it'}. This is a "
            "schema mismatch between the book on disk and the governed "
            f"Corporate IFRS 9 contract, not a scenario that failed. Rebuild "
            f"the book with `{REBUILD}`.")
    return Resolution(
        dataset=dataset,
        present=tuple(f for f in wanted if f in have),
        absent=tuple(f for f in wanted if f not in have))


def snapshot_fields(wanted: tuple[str, ...] = (), *,
                    source: Any = None) -> Resolution:
    """Resolve snapshot fields, always including everything load-bearing."""
    asked = tuple(dict.fromkeys((*REQUIRED, *(wanted or OPTIONAL))))
    return resolve(SNAPSHOT, asked, required=REQUIRED, source=source)


def ifrs9_fields(source: Any = None) -> Resolution:
    return resolve(IFRS9, ALL_IFRS9, required=IFRS9_REQUIRED, source=source)


def supports(field: str, source: Any = None) -> bool:
    """Whether the book carries one field. For a shock deciding if it can run."""
    return field in set(columns(SNAPSHOT, source))


def report(source: Any = None) -> dict[str, Any]:
    """What the contract, the catalogue and the data each say.

    The three-way comparison a schema-contract test asserts on, and the body
    `GET /whatif/schema` serves so the divergence is visible on screen rather
    than only in a stack trace.
    """
    reader = _reader(source)
    body: dict[str, Any] = {"version": SCHEMA_VERSION, "owner": SCHEMA_OWNER,
                            "rebuild": REBUILD, "datasets": {}}
    for dataset, req, opt in ((SNAPSHOT, REQUIRED, OPTIONAL),
                              (IFRS9, IFRS9_REQUIRED, IFRS9_OPTIONAL)):
        try:
            on_disk = set(reader.columns(dataset))
        except Exception as e:  # noqa: BLE001 - reported, not raised
            body["datasets"][dataset] = {"readable": False, "why": str(e)[:300]}
            continue
        declared = set(reader.fields(dataset))
        wanted = (*req, *opt)
        body["datasets"][dataset] = {
            "readable": True,
            "required": list(req),
            "optional": sorted(opt),
            "missing_required": sorted(f for f in req if f not in on_disk),
            "missing_optional": sorted(f for f in opt if f not in on_disk),
            "declared_but_absent": sorted(declared - on_disk),
            "present_but_undeclared": sorted(on_disk - declared),
            "unused_by_whatif": sorted(on_disk - set(wanted)),
            "columns_on_disk": len(on_disk),
            "fields_declared": len(declared),
        }
    snapshot = body["datasets"].get(SNAPSHOT, {})
    body["healthy"] = bool(snapshot.get("readable")
                           and not snapshot.get("missing_required")
                           and not snapshot.get("declared_but_absent"))
    return body


def describe() -> dict[str, Any]:
    """The contract itself, without touching the lake."""
    return {
        "version": SCHEMA_VERSION,
        "owner": SCHEMA_OWNER,
        "snapshot": SNAPSHOT,
        "measurement": IFRS9,
        "required": list(REQUIRED),
        "optional": [{"field": k, "enables": v} for k, v in OPTIONAL.items()],
        "measurement_required": list(IFRS9_REQUIRED),
        "measurement_optional": [{"field": k, "enables": v}
                                 for k, v in IFRS9_OPTIONAL.items()],
        "statement": (
            "What-If resolves its columns against the Parquet schema, not the "
            "catalogue. A missing REQUIRED field is refused by name; a missing "
            "OPTIONAL field costs exactly the capability it names and nothing "
            "else."),
    }


__all__ = [
    "ALL_IFRS9", "ALL_SNAPSHOT", "IFRS9", "IFRS9_OPTIONAL", "IFRS9_REQUIRED",
    "OPTIONAL", "REBUILD", "REQUIRED", "SCHEMA_OWNER", "SCHEMA_VERSION",
    "SNAPSHOT", "Resolution", "SchemaError", "columns", "describe",
    "ifrs9_fields", "report", "reset_cache", "resolve", "snapshot_fields",
    "supports",
]
