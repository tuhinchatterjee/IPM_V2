"""
What actually moved between two quarters — ratings, and Stages.

Why this is a matched-entity problem, not a difference of two tables
--------------------------------------------------------------------
"How did ratings migrate over the year?" sounds like subtracting one
distribution from another. It is not. A book whose BBB count fell by forty did
not necessarily downgrade forty names: some were repaid, some are new, and some
moved in both directions and cancelled out. A migration matrix is only
meaningful for borrowers present in BOTH quarters, matched by identity.

So this module matches on `borrower_id`, and reports the three populations it
finds separately:

  * **continuing** — in both quarters. These are the only rows in the matrix.
  * **exited** — in the opening quarter and gone by the closing one.
  * **new** — in the closing quarter and absent from the opening one.

Exits and arrivals are never folded into a matrix cell. A cell that quietly
contained "BBB names that left" would be read as "BBB names that stayed BBB",
which is the one thing a migration table exists to distinguish.

Grain
-----
Corporate IFRS 9 is one row per borrower per quarter, so a borrower cannot be
double-counted by having several facilities. The matcher asserts that rather
than assuming it: if a period ever produced two rows for one borrower the
counts would silently inflate, so duplicates are collapsed and reported.

Shape
-----
Fourteen governed grades plus a Total row and a Total column — a 15 x 15
displayed matrix. Stages are 1, 2, 3 plus Total, so 4 x 4 displayed for a 3 x 3
of substance.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.whatif import domain as dm
from backend.whatif.profiles import GRADES, STAGES, TOTAL

#: The views a migration table offers.
COUNT = "count"
COUNT_PCT = "count_pct"
EXPOSURE = "exposure"
EXPOSURE_PCT = "exposure_pct"
VIEWS: tuple[str, ...] = (COUNT, COUNT_PCT, EXPOSURE, EXPOSURE_PCT)


class MigrationError(dm.DomainError):
    """A migration that cannot be built, stated rather than approximated."""


def _dedupe(frame: pd.DataFrame, period: str) -> tuple[pd.DataFrame, int]:
    """One row per borrower, and how many duplicates had to be collapsed."""
    if "borrower_id" not in frame.columns:
        raise MigrationError(dm.field_refusal("borrower_id"))
    before = len(frame)
    out = frame.drop_duplicates(subset=["borrower_id"], keep="last")
    return out, before - len(out)


def matched(opening_period: str, closing_period: str, *,
            source: Any = None) -> dict[str, Any]:
    """The two quarters joined on borrower identity.

    Returns the continuing population as one frame carrying both quarters'
    values, plus the exited and new populations as their own frames.
    """
    opening_frame, opening = dm.book(opening_period, source=source)
    closing_frame, closing = dm.book(closing_period, source=source)
    if opening == closing:
        raise MigrationError(
            f"A migration needs two different quarters; '{opening}' was given "
            "for both.")
    opening_frame, opening_dupes = _dedupe(opening_frame, opening)
    closing_frame, closing_dupes = _dedupe(closing_frame, closing)

    carried = ["borrower_id", "internal_rating", "internal_rating_numeric",
               "stage", "ead", "final_ecl", "pd_12m", "pd_lifetime", "lgd",
               "sector", "segment", "display_name"]
    left = opening_frame[[c for c in carried if c in opening_frame.columns]]
    right = closing_frame[[c for c in carried if c in closing_frame.columns]]

    both = left.merge(right, on="borrower_id", how="inner",
                      suffixes=("_opening", "_closing"))
    exited = left[~left["borrower_id"].isin(right["borrower_id"])]
    arrived = right[~right["borrower_id"].isin(left["borrower_id"])]
    return {"opening_period": opening, "closing_period": closing,
            "continuing": both, "exited": exited, "new": arrived,
            "duplicates_collapsed": int(opening_dupes + closing_dupes)}


def _matrix(both: pd.DataFrame, opening_key: str, closing_key: str,
            labels: list[str], weight: str) -> list[list[float]]:
    """The raw grid: rows are the opening state, columns the closing one."""
    index = {label: i for i, label in enumerate(labels)}
    grid = [[0.0 for _ in labels] for _ in labels]
    if both.empty:
        return grid
    weights = (pd.to_numeric(both[weight], errors="coerce").fillna(0.0)
               if weight and weight in both.columns
               else pd.Series(np.ones(len(both)), index=both.index))
    for (start, end), part in both.groupby([opening_key, closing_key], observed=True):
        row, column = index.get(str(start)), index.get(str(end))
        if row is None or column is None:
            continue
        grid[row][column] = float(weights.reindex(part.index).sum())
    return grid


def _with_totals(grid: list[list[float]], labels: list[str]) -> dict[str, Any]:
    """The grid plus its margins — the fifteenth row and column."""
    rows = []
    for label, line in zip(labels, grid, strict=False):
        rows.append({"label": label, "cells": [round(v, 4) for v in line],
                     "total": round(float(sum(line)), 4)})
    columns = [round(float(sum(grid[r][c] for r in range(len(labels)))), 4)
               for c in range(len(labels))]
    return {"labels": labels, "rows": rows, "column_totals": columns,
            "grand_total": round(float(sum(columns)), 4)}


def _as_row_shares(body: dict[str, Any],
                   labels: list[str]) -> dict[str, Any]:
    """A percentage view, normalised ALONG EACH ROW.

    This is the only normalisation a migration matrix should offer, and it was
    the defect: dividing every cell by the GRAND total answers "what share of
    the whole book made this particular move", which is a number nobody reads
    and which makes a small origin grade look like nothing happened in it.

    The question a credit officer actually asks is "of the BBB names we had,
    where did they end up?" — so the denominator is the ORIGIN row's own
    population, every populated row sums to 100%, and the column totals are a
    share of the whole because a column has no single origin to divide by.

    A row whose opening population was empty is all zeros rather than a
    division by nothing.
    """
    rows = []
    for row in body["rows"]:
        total = row["total"]
        rows.append({
            "label": row["label"],
            "cells": [round(v / total * 100.0, 4) if total else 0.0
                      for v in row["cells"]],
            "total": 100.0 if total else 0.0,
            "population": total,
        })
    grand = body["grand_total"]
    return {
        "labels": labels,
        "rows": rows,
        "column_totals": [round(v / grand * 100.0, 4) if grand else 0.0
                          for v in body["column_totals"]],
        "grand_total": 100.0 if grand else 0.0,
        "normalisation": "row",
        "denominator": "the origin grade's own matched population",
        "reads_as": "% of origin rating",
    }


def _row_normalised(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Each row as percentages of its own opening population.

    This is the view a credit officer reads: "of the BBB names we had, where
    did they end up?" A row whose opening population was empty is all zeros
    rather than a division by nothing.
    """
    out = []
    for row in body["rows"]:
        total = row["total"]
        cells = [round(v / total * 100.0, 4) if total else 0.0 for v in row["cells"]]
        out.append({"label": row["label"], "cells": cells,
                    "total": 100.0 if total else 0.0})
    return out


def _population(part: pd.DataFrame, ead_column: str) -> dict[str, Any]:
    ead = (pd.to_numeric(part[ead_column], errors="coerce").fillna(0.0)
           if ead_column in part.columns else pd.Series(dtype=float))
    return {"count": int(len(part)), "exposure": float(ead.sum())}


def rating_migration(closing_period: str = "", opening_period: str = "", *,
                     source: Any = None) -> dict[str, Any]:
    """One year of rating migration, as a 15 x 15 displayed matrix.

    Fourteen governed grades plus a Total row and column. The opening quarter
    defaults to the same quarter one year earlier, which is what "prior-year
    migration" means on this screen.
    """
    closing = dm.resolve_period(closing_period, source)
    opening = opening_period or dm.prior_year(closing, source)
    if not opening:
        raise MigrationError(
            f"Corporate IFRS 9 does not go back a year before {closing}, so a "
            "prior-year rating migration cannot be built. The book starts at "
            f"{dm.periods(source)[0]}.")
    found = matched(opening, closing, source=source)
    both = found["continuing"]
    labels = [*GRADES]

    if not both.empty:
        both = both.assign(
            _open=both["internal_rating_opening"].astype(str).str.strip().str.upper(),
            _close=both["internal_rating_closing"].astype(str).str.strip().str.upper())
    else:  # pragma: no cover - an empty overlap
        both = both.assign(_open=pd.Series(dtype=str), _close=pd.Series(dtype=str))

    views = {
        COUNT: _with_totals(_matrix(both, "_open", "_close", labels, ""), labels),
        EXPOSURE: _with_totals(
            # Weighted by the OPENING exposure: the row denominator has to be
            # "the exposure that STARTED in this grade", or a row of shares
            # does not sum to the exposure that migrated out of it.
            _matrix(both, "_open", "_close", labels, "ead_opening"), labels),
    }
    for base, share in ((COUNT, COUNT_PCT), (EXPOSURE, EXPOSURE_PCT)):
        views[share] = _as_row_shares(views[base], labels)

    moved = int((both["_open"] != both["_close"]).sum()) if not both.empty else 0
    numeric_open = pd.to_numeric(both.get("internal_rating_numeric_opening"),
                                 errors="coerce") if not both.empty else pd.Series(dtype=float)
    numeric_close = pd.to_numeric(both.get("internal_rating_numeric_closing"),
                                  errors="coerce") if not both.empty else pd.Series(dtype=float)
    notches = (numeric_close - numeric_open) if not both.empty else pd.Series(dtype=float)

    return {
        "kind": "rating",
        "opening_period": found["opening_period"],
        "closing_period": found["closing_period"],
        "labels": labels,
        "displayed_shape": f"{len(labels) + 1} x {len(labels) + 1}",
        "total_label": TOTAL,
        "views": views,
        "row_normalised": _row_normalised(views[COUNT]),
        "row_normalised_exposure": _row_normalised(views[EXPOSURE]),
        "continuing": _population(both, "ead_closing"),
        "exited": _population(found["exited"], "ead"),
        "new": _population(found["new"], "ead"),
        "duplicates_collapsed": found["duplicates_collapsed"],
        "moved": moved,
        "downgraded": int((notches > 0).sum()) if len(notches) else 0,
        "upgraded": int((notches < 0).sum()) if len(notches) else 0,
        "unchanged": int(len(both)) - moved,
        "currency": dm.CURRENCY,
        "note": ("Only borrowers present in both quarters appear in the "
                 "matrix. Exits and arrivals are reported separately and are "
                 "never folded into a cell."),
    }


def stage_migration(closing_period: str = "", opening_period: str = "", *,
                    source: Any = None) -> dict[str, Any]:
    """One year of Stage migration — the 3 x 3, with curing as well as decay."""
    closing = dm.resolve_period(closing_period, source)
    opening = opening_period or dm.prior_year(closing, source)
    if not opening:
        raise MigrationError(
            f"Corporate IFRS 9 does not go back a year before {closing}, so a "
            "prior-year Stage migration cannot be built. The book starts at "
            f"{dm.periods(source)[0]}.")
    found = matched(opening, closing, source=source)
    both = found["continuing"]
    labels = [f"Stage {n}" for n in STAGES]

    if not both.empty:
        both = both.assign(
            _open="Stage " + pd.to_numeric(both["stage_opening"], errors="coerce")
            .fillna(0).astype(int).astype(str),
            _close="Stage " + pd.to_numeric(both["stage_closing"], errors="coerce")
            .fillna(0).astype(int).astype(str))
    else:  # pragma: no cover
        both = both.assign(_open=pd.Series(dtype=str), _close=pd.Series(dtype=str))

    views = {
        COUNT: _with_totals(_matrix(both, "_open", "_close", labels, ""), labels),
        EXPOSURE: _with_totals(
            # Weighted by the OPENING exposure: the row denominator has to be
            # "the exposure that STARTED in this grade", or a row of shares
            # does not sum to the exposure that migrated out of it.
            _matrix(both, "_open", "_close", labels, "ead_opening"), labels),
    }
    for base, share in ((COUNT, COUNT_PCT), (EXPOSURE, EXPOSURE_PCT)):
        views[share] = _as_row_shares(views[base], labels)

    def cell(start: int, end: int) -> int:
        if both.empty:
            return 0
        return int(((both["_open"] == f"Stage {start}")
                    & (both["_close"] == f"Stage {end}")).sum())

    return {
        "kind": "stage",
        "opening_period": found["opening_period"],
        "closing_period": found["closing_period"],
        "labels": labels,
        "displayed_shape": f"{len(labels) + 1} x {len(labels) + 1}",
        "total_label": TOTAL,
        "views": views,
        "row_normalised": _row_normalised(views[COUNT]),
        "row_normalised_exposure": _row_normalised(views[EXPOSURE]),
        "continuing": _population(both, "ead_closing"),
        "exited": _population(found["exited"], "ead"),
        "new": _population(found["new"], "ead"),
        "duplicates_collapsed": found["duplicates_collapsed"],
        "transitions": {
            "s1_to_s2": cell(1, 2), "s2_to_s3": cell(2, 3),
            "s2_to_s1": cell(2, 1), "s3_to_s2": cell(3, 2),
            "s1_to_s3": cell(1, 3), "s3_to_s1": cell(3, 1),
        },
        "deteriorated": cell(1, 2) + cell(2, 3) + cell(1, 3),
        "cured": cell(2, 1) + cell(3, 2) + cell(3, 1),
        "unchanged": sum(cell(n, n) for n in STAGES),
        "currency": dm.CURRENCY,
        "note": ("Only borrowers present in both quarters appear in the "
                 "matrix. Curing and deterioration are both shown."),
    }


__all__ = [
    "COUNT", "COUNT_PCT", "EXPOSURE", "EXPOSURE_PCT", "MigrationError",
    "VIEWS", "matched", "rating_migration", "stage_migration",
]
