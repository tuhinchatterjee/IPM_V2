"""One filtered population, and every measure on the screen computed from it.

The defect this closes
----------------------
The dashboard's tiles read the whole book, its band distribution read the
whole book, its trend chart read the whole book, and its table read the twenty
rows the overview endpoint happened to return -- then filtered those twenty in
the browser. A reader who narrowed to one segment saw a segment table under
portfolio tiles, with nothing on the screen saying the two were about
different populations. Every number was individually true and the screen as a
whole was not.

So there is one filtered frame per request, and the tiles, the distribution,
the trend, the table and the export are all projections of it. They cannot
disagree, because there is only one of them.

The trend, and what "the same population" means over time
----------------------------------------------------------
A filtered trend has two honest readings and they answer different questions.

  * Re-filter every month. "How have obligors matching this description
    fared?" -- but membership changes underneath: an obligor that fell into
    HIGH last month and out of it this month leaves the line, and the line
    moves because the population moved, not because anything got better.

  * Anchor the cohort at the as-of month and track those same obligors
    backwards. "How did THIS set of obligors get here?" -- membership is
    fixed, so a movement in the line is a movement in the obligors.

This uses the second, because the dashboard's question is about the obligors
in front of the reader. It is stated on the chart rather than assumed:
`trend.basis` and `trend.note` travel with the data, and the export writes
them into its metadata sheet. A cohort trend presented as a portfolio trend
would be a survivorship claim nobody made.

A band filter is the one that has to be treated differently even so, and it is
handled by the anchoring: filtering "HIGH now" and then reading those obligors
in earlier months shows how they arrived at HIGH, which is the question. It
does NOT show how many obligors were HIGH in each month -- that is the
unfiltered trend, and it is what the chart shows when nothing is filtered.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.early_warning import filterspec as fsp
from backend.early_warning import v2_service as svc

#: The columns the borrower table shows. Not the whole 2,527-field surface:
#: a screen that shipped the model surface to draw eight columns would move
#: fifteen million values to render three hundred rows. §33.
TABLE_COLUMNS: tuple[str, ...] = (
    "customer_id", "customer_name", "segment", "exposure", "dpd",
    "ifrs9_stage", "internal_rating", "ews_score", "ews_band", "ta_score",
    "ta_band", "classifier_score", "classifier_band", "dominant_driver",
    "signal_count_fired", "overrides_applied",
)

#: The bands, worst first, which is the order a reader reads a distribution in.
BANDS_WORST_FIRST: tuple[str, ...] = tuple(reversed(fsp.BANDS))

HIGH_PLUS: tuple[str, ...] = ("HIGH", "VERY_HIGH")

COHORT = "current_snapshot_cohort"
WHOLE_BOOK = "whole_book"

_COHORT_NOTE = (
    "The same obligors, tracked back through earlier months. Membership is "
    "fixed at the as-of month, so a movement in this line is a movement in "
    "these obligors rather than a change in who is being counted.")
_BOOK_NOTE = "Every obligor published in each month."


def _weighted(frame: pd.DataFrame) -> float:
    """Exposure-weighted Early Warning score, or the plain mean with no
    exposure. A book with no exposure is still a book."""
    if frame.empty:
        return 0.0
    exposure = pd.to_numeric(frame["exposure"], errors="coerce").fillna(0.0)
    total = float(exposure.sum())
    if total <= 0:
        return round(float(pd.to_numeric(frame["ews_score"],
                                         errors="coerce").mean() or 0.0), 2)
    score = pd.to_numeric(frame["ews_score"], errors="coerce").fillna(0.0)
    return round(float((score * exposure).sum() / total), 2)


def kpis(frame: pd.DataFrame, *, period: str) -> dict[str, Any]:
    """The headline measures, over the filtered population and nothing else."""
    exposure = pd.to_numeric(frame.get("exposure"), errors="coerce") \
        if "exposure" in frame.columns else pd.Series(dtype=float)
    high_plus = (frame[frame["ews_band"].isin(HIGH_PLUS)]
                 if "ews_band" in frame.columns else frame.iloc[0:0])
    high_exposure = (pd.to_numeric(high_plus["exposure"], errors="coerce")
                     if "exposure" in high_plus.columns
                     else pd.Series(dtype=float))
    return {
        "period": period,
        "portfolio_ews": _weighted(frame),
        "borrower_count": int(len(frame)),
        "total_exposure": round(float(exposure.fillna(0.0).sum()), 2),
        "high_plus_count": int(len(high_plus)),
        "high_plus_exposure": round(float(high_exposure.fillna(0.0).sum()), 2),
    }


def distribution(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """The band mix of the filtered population.

    Percentages are of the FILTERED population, which is the only denominator
    that makes the tile above and the bar below the same statement. A band a
    filter has excluded is reported at zero rather than dropped: a reader who
    filtered to HIGH should see the other four bands empty, not a chart that
    silently became one bar.
    """
    total = len(frame)
    exposure = (pd.to_numeric(frame["exposure"], errors="coerce").fillna(0.0)
                if "exposure" in frame.columns else pd.Series(dtype=float))
    book = float(exposure.sum())
    out: list[dict[str, Any]] = []
    for band in BANDS_WORST_FIRST:
        subset = (frame[frame["ews_band"] == band]
                  if "ews_band" in frame.columns else frame.iloc[0:0])
        held = (pd.to_numeric(subset["exposure"], errors="coerce").fillna(0.0)
                .sum() if "exposure" in subset.columns else 0.0)
        out.append({
            "band": band,
            "borrower_count": int(len(subset)),
            "borrower_pct": round(100.0 * len(subset) / total, 2) if total else 0.0,
            "exposure": round(float(held), 2),
            "exposure_pct": round(100.0 * float(held) / book, 2) if book else 0.0,
        })
    return out


def trend(frame: pd.DataFrame, *, spec: fsp.FilterSpec,
          period: str) -> dict[str, Any]:
    """The filtered population's history, on stated cohort semantics.

    With no filter this is the portfolio trend, every obligor in every month.
    With a filter it is the obligors in front of the reader, tracked back --
    and the reply says which of the two it is, because the chart is otherwise
    indistinguishable from a claim it does not support.
    """
    months = svc.periods()
    if not months:
        return {"basis": WHOLE_BOOK, "note": _BOOK_NOTE, "points": [],
                "cohort_size": 0, "as_of": period}

    if not spec.active:
        points = [{"period": p, **{k: v for k, v in
                                   kpis(svc.borrower_month(p), period=p).items()
                                   if k != "period"}}
                  for p in months]
        return {"basis": WHOLE_BOOK, "note": _BOOK_NOTE, "points": points,
                "cohort_size": int(len(frame)), "as_of": period}

    cohort = set(frame["customer_id"].astype(str)) if not frame.empty else set()
    points: list[dict[str, Any]] = []
    for month in months:
        if month > period:
            # The anchor is the as-of month. A cohort defined by what is true
            # now cannot be carried forward into months it was not defined in.
            continue
        book = svc.borrower_month(month)
        held = book[book["customer_id"].astype(str).isin(cohort)]
        measured = kpis(held, period=month)
        points.append({"period": month,
                       **{k: v for k, v in measured.items() if k != "period"},
                       "in_cohort": int(len(held))})
    return {"basis": COHORT, "note": _COHORT_NOTE, "points": points,
            "cohort_size": len(cohort), "as_of": period}


def rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """The table, in the columns a reader is shown."""
    present = [c for c in TABLE_COLUMNS if c in frame.columns]
    if not present:
        return []
    return frame[present].to_dict(orient="records")


def view(spec: fsp.FilterSpec) -> dict[str, Any]:
    """Everything the dashboard shows, from one filter.

    The order matters and is the whole point: read the month, narrow it ONCE,
    and compute every measure from the result. A measure computed from
    anything else is a measure that can disagree with the rest of the screen.
    """
    period = spec.period or svc.latest_period()
    book = svc.borrower_month(period)
    narrowed = spec.apply(book)
    ordered = spec.sort(narrowed)

    return {
        "period": period,
        "available_periods": svc.periods(),
        "scope": {
            **spec.to_dict(),
            "chips": spec.describe(),
            "sentence": spec.sentence(),
            "active": spec.active,
            "matched": int(len(narrowed)),
            "population": int(len(book)),
        },
        "kpis": kpis(narrowed, period=period),
        "distribution": distribution(narrowed),
        "trend": trend(narrowed, spec=spec, period=period),
        "rows": rows(spec.page(ordered)),
        "row_count": int(len(narrowed)),
        "returned": int(min(spec.limit, max(0, len(narrowed) - spec.offset))),
        "offset": spec.offset,
        "facets": fsp.facets(book),
        "contract": fsp.contract(),
    }


def complete(spec: fsp.FilterSpec) -> tuple[pd.DataFrame, dict[str, Any]]:
    """The whole filtered result, for the export. Not a page of it.

    The export exists because a screen shows a page. Handing it the same
    paged frame would make the button a slower way of copying what is
    already visible.
    """
    period = spec.period or svc.latest_period()
    book = svc.borrower_month(period)
    narrowed = spec.sort(spec.apply(book))
    present = [c for c in TABLE_COLUMNS if c in narrowed.columns]
    return narrowed[present].copy(), {
        "period": period,
        "matched": int(len(narrowed)),
        "population": int(len(book)),
        "scope": spec.sentence(),
        "chips": spec.describe(),
        "sort_by": spec.sort_by,
        "descending": spec.descending,
    }


__all__ = ["BANDS_WORST_FIRST", "COHORT", "HIGH_PLUS", "TABLE_COLUMNS",
           "WHOLE_BOOK", "complete", "distribution", "kpis", "rows", "trend",
           "view"]
