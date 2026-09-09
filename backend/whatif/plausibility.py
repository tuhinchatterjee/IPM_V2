"""
Has this ever happened, and to how much of the book?

Why this exists
---------------
A What-If produces a number. The next question a credit committee asks is not
"is that arithmetic right" — the engine settles that — but "is a shock this
size a thing that happens?" Without an answer, a 20% PD increase and a 200%
one are presented identically, and the reader supplies their own sense of
severity, which is the one part of the analysis nobody can audit.

So every scenario is compared against what the book has ACTUALLY DONE across
the sixteen quarters it carries. Not a forecast, and not a probability: a
comparison against observed experience.

What it is NOT
--------------
It is not a likelihood. There is no model here that says a scenario has a 3%
chance of occurring, because nothing in this data supports such a statement and
a number like that would be believed. The output is one of six controlled
labels and the evidence that produced it.

The six labels, and what earns each
-----------------------------------
    Consistent with recent experience   the shock is inside the ordinary
                                        quarter-to-quarter movement of this
                                        book
    Historically plausible              a move of this size has happened, and
                                        to a comparable share of the book
    Plausible for selected pockets      it has happened, but only to a small
                                        or concentrated part of the book
    Severe but historically observed    it has happened, at the extreme of
                                        what the window contains
    Severe relative to recent history   larger than anything in the window,
                                        but within reach of its worst quarter
    Outside observed history            nothing in the window approaches it

A severe scenario is never refused. It is calculated, and it is labelled.

Where the evidence comes from
-----------------------------
The book itself, at obligor grain, quarter by quarter. Every borrower's own
movement between consecutive quarters and between the same quarter a year
apart, so "a 20% PD rise" is measured against how often a REAL borrower's PD
rose 20% — not against a portfolio average, which smooths away exactly the
thing being asked about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PLAUSIBILITY_VERSION = "1.0.0"

CONSISTENT = "Consistent with recent experience"
PLAUSIBLE = "Historically plausible"
POCKETS = "Plausible for selected pockets"
SEVERE_OBSERVED = "Severe but historically observed"
SEVERE_RECENT = "Severe relative to recent history"
OUTSIDE = "Outside observed history"

LABELS: tuple[str, ...] = (CONSISTENT, PLAUSIBLE, POCKETS, SEVERE_OBSERVED,
                           SEVERE_RECENT, OUTSIDE)

#: A movement this share of the book has seen is "the ordinary experience of
#: this book" rather than an event. Chosen, stated, and used consistently.
COMMON_SHARE = 0.20
#: Below this, a move that HAS happened happened to a pocket rather than to the
#: book.
POCKET_SHARE = 0.05
#: How many quarters have to contain the move before it is "observed" rather
#: than "a thing that happened once".
REPEATED_QUARTERS = 2


@dataclass
class Evidence:
    """What the book did, for one measure, over the whole window."""

    measure: str
    label: str
    #: The proposed move, in the measure's own terms.
    proposed: float
    unit: str
    #: Share of borrower-quarters that saw at least this move, quarter on
    #: quarter and year on year.
    qoq_share: float = 0.0
    yoy_share: float = 0.0
    #: The same, weighted by exposure and by reported ECL — because a move that
    #: touched two per cent of names and forty per cent of the exposure is a
    #: different fact.
    qoq_exposure_share: float = 0.0
    qoq_ecl_share: float = 0.0
    #: Quarters in which the move was seen at all, and the worst quarter.
    quarters_seen: list[str] = field(default_factory=list)
    worst_quarter: str = ""
    worst_share: float = 0.0
    #: The distribution of the observed move, so a reader can place the shock.
    percentiles: dict[str, float] = field(default_factory=dict)
    #: Where the move concentrated, when it happened.
    by_sector: list[dict[str, Any]] = field(default_factory=list)
    by_rating: list[dict[str, Any]] = field(default_factory=list)
    by_stage: list[dict[str, Any]] = field(default_factory=list)
    observations: int = 0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "measure": self.measure, "label": self.label,
            "proposed": round(float(self.proposed), 4), "unit": self.unit,
            "qoq_share_pct": round(self.qoq_share * 100.0, 3),
            "yoy_share_pct": round(self.yoy_share * 100.0, 3),
            "qoq_exposure_share_pct": round(self.qoq_exposure_share * 100.0, 3),
            "qoq_ecl_share_pct": round(self.qoq_ecl_share * 100.0, 3),
            "quarters_seen": list(self.quarters_seen),
            "quarters_seen_count": len(self.quarters_seen),
            "worst_quarter": self.worst_quarter,
            "worst_quarter_share_pct": round(self.worst_share * 100.0, 3),
            "percentiles": {k: round(float(v), 4)
                            for k, v in self.percentiles.items()},
            "by_sector": self.by_sector, "by_rating": self.by_rating,
            "by_stage": self.by_stage,
            "observations": self.observations, "note": self.note,
        }


def _ordered(periods: list[str]) -> list[str]:
    return sorted(periods, key=lambda p: (p.split()[-1], p.split()[0]))


#: The panel, held once. Sixteen quarters of a three-thousand-borrower book is
#: fifty thousand rows — small enough to keep, and reading it per question
#: would make every plausibility answer cost a full pass over the lake. The
#: lake does not change while the process runs; `reset_cache` is for the tests
#: that rebuild it.
_HELD: dict[str, pd.DataFrame] = {}


def reset_cache() -> None:
    _HELD.clear()


def _panel(columns: tuple[str, ...], source: Any = None) -> pd.DataFrame:
    """Every borrower, every quarter, in the columns a comparison needs.

    Read once and cached by the domain layer. Sixteen quarters of a
    three-thousand-borrower book is fifty thousand rows: small enough to hold,
    and reading it per question would make every plausibility answer cost a
    full pass over the lake.
    """
    from backend.whatif import domain as dm

    key = "|".join(columns)
    if source is None and key in _HELD:
        return _HELD[key]

    frames = []
    for period in _ordered(dm.periods(source)):
        frame, _ = dm.book(period, source=source)
        keep = [c for c in columns if c in frame.columns]
        if not keep or "borrower_id" not in frame.columns:
            continue
        part = frame[["borrower_id", *[c for c in keep if c != "borrower_id"]]].copy()
        part["period"] = period
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    if source is None:
        _HELD[key] = panel
    return panel


def _movements(panel: pd.DataFrame, column: str, *, lag: int) -> pd.DataFrame:
    """Each borrower's own move in `column`, `lag` quarters apart.

    The borrower's OWN move, not the portfolio's. "A 20% PD rise" is a claim
    about borrowers, and measuring it against a portfolio average smooths away
    exactly the thing being asked about: an average can be flat while a third
    of the book doubles.
    """
    if panel.empty or column not in panel.columns:
        return pd.DataFrame()
    order = {p: i for i, p in enumerate(_ordered(panel["period"].unique()))}
    work = panel.copy()
    work["_t"] = work["period"].map(order)
    work = work.sort_values(["borrower_id", "_t"])
    grouped = work.groupby("borrower_id", sort=False)
    work["_before"] = grouped[column].shift(lag)
    work["_before_t"] = grouped["_t"].shift(lag)
    work = work[work["_before_t"] == work["_t"] - lag]
    work = work.dropna(subset=["_before", column])
    before = pd.to_numeric(work["_before"], errors="coerce")
    after = pd.to_numeric(work[column], errors="coerce")
    work["_absolute"] = after - before
    work["_relative_pct"] = np.where(
        before.abs() > 1e-9, (after / before.where(before.abs() > 1e-9) - 1.0) * 100.0,
        np.nan)
    return work


def _cuts(moved: pd.DataFrame, hit: pd.Series) -> dict[str, list[dict[str, Any]]]:
    """Where the move concentrated, when it happened."""
    out: dict[str, list[dict[str, Any]]] = {}
    for key, column in (("by_sector", "sector"),
                        ("by_rating", "internal_rating"),
                        ("by_stage", "stage")):
        if column not in moved.columns:
            out[key] = []
            continue
        grouped = (moved.assign(_hit=hit.astype(float))
                   .groupby(moved[column].astype(str))["_hit"]
                   .agg(["mean", "sum", "size"]).reset_index())
        grouped.columns = [column, "share", "hits", "observations"]
        grouped = grouped[grouped["observations"] >= 20]
        grouped = grouped.sort_values("share", ascending=False)
        out[key] = [{"label": str(r[column]),
                     "share_pct": round(float(r["share"]) * 100.0, 3),
                     "observations": int(r["observations"])}
                    for _, r in grouped.head(10).iterrows()]
    return out


def measure(panel: pd.DataFrame, column: str, *, proposed: float,
            relative: bool, label: str, unit: str) -> Evidence:
    """How often the book has moved `column` by at least the proposed amount.

    Direction matters: a proposed WORSENING is compared against observed
    worsenings. Counting improvements as evidence that a deterioration is
    ordinary would be the wrong comparison entirely.
    """
    body = Evidence(measure=column, label=label, proposed=proposed, unit=unit)
    if panel.empty or column not in panel.columns:
        body.note = (f"The book does not carry {column}, so there is no "
                     "historical comparison for this shock.")
        return body

    qoq = _movements(panel, column, lag=1)
    yoy = _movements(panel, column, lag=4)
    if qoq.empty:
        body.note = "Not enough consecutive quarters to compare against."
        return body

    field_name = "_relative_pct" if relative else "_absolute"
    observed = pd.to_numeric(qoq[field_name], errors="coerce")
    body.observations = int(observed.notna().sum())

    worsening = proposed >= 0
    hit = observed >= proposed if worsening else observed <= proposed
    hit = hit.fillna(False)
    body.qoq_share = float(hit.mean()) if len(hit) else 0.0

    if not yoy.empty:
        annual = pd.to_numeric(yoy[field_name], errors="coerce")
        annual_hit = (annual >= proposed if worsening else annual <= proposed)
        body.yoy_share = float(annual_hit.fillna(False).mean())

    for weight, target in (("ead", "qoq_exposure_share"),
                           ("final_ecl", "qoq_ecl_share")):
        if weight not in qoq.columns:
            continue
        w = pd.to_numeric(qoq[weight], errors="coerce").fillna(0.0)
        total = float(w.sum())
        setattr(body, target,
                float(w[hit].sum() / total) if total > 0 else 0.0)

    by_quarter = (qoq.assign(_hit=hit.astype(float))
                  .groupby("period")["_hit"].mean())
    body.quarters_seen = [str(p) for p in
                          _ordered(list(by_quarter[by_quarter > 0].index))]
    if len(by_quarter):
        body.worst_quarter = str(by_quarter.idxmax())
        body.worst_share = float(by_quarter.max())

    clean = observed.dropna()
    if len(clean):
        wanted = ([0.50, 0.75, 0.90, 0.95, 0.99] if worsening
                  else [0.50, 0.25, 0.10, 0.05, 0.01])
        body.percentiles = {f"p{int(q * 100)}": float(clean.quantile(q))
                            for q in wanted}

    cuts = _cuts(qoq, hit)
    body.by_sector, body.by_rating, body.by_stage = (
        cuts["by_sector"], cuts["by_rating"], cuts["by_stage"])
    return body


def verdict(body: Evidence) -> tuple[str, str]:
    """The label this evidence earns, and the sentence that justifies it."""
    if not body.observations:
        return (OUTSIDE,
                f"There is no historical movement in {body.label} to compare "
                "this against, so the shock cannot be placed in the book's own "
                "experience.")

    seen = len(body.quarters_seen)
    share, annual = body.qoq_share, body.yoy_share
    exposure = body.qoq_exposure_share

    if share >= COMMON_SHARE:
        return (CONSISTENT,
                f"{share * 100:.1f}% of borrower-quarters in this book saw a "
                f"{body.label} move of at least this size from one quarter to "
                "the next. It is ordinary experience rather than an event.")
    if share >= POCKET_SHARE and seen >= REPEATED_QUARTERS:
        return (PLAUSIBLE,
                f"{share * 100:.1f}% of borrower-quarters saw a move this "
                f"large, in {seen} of the quarters this book covers, and "
                f"{exposure * 100:.1f}% of exposure. A move of this size has "
                "happened, and to a comparable share of the book.")
    if share > 0 and seen >= REPEATED_QUARTERS:
        return (POCKETS,
                f"It has happened, but to {share * 100:.2f}% of "
                f"borrower-quarters and {exposure * 100:.2f}% of exposure. "
                "Applying it across the population asks for something the book "
                "has only done in pockets.")
    if share > 0:
        return (SEVERE_OBSERVED,
                f"It reached this size in {body.worst_quarter}, touching "
                f"{body.worst_share * 100:.2f}% of borrowers that quarter, and "
                "in no other quarter in the window. It sits at the extreme of "
                "what this book has done.")
    if annual > 0:
        return (SEVERE_RECENT,
                "No single quarter contains a move this large, but "
                f"{annual * 100:.2f}% of borrowers moved this far over a year. "
                "It is severe relative to quarterly experience and within "
                "reach of the window's worst run.")
    worst = body.percentiles.get("p99") or body.percentiles.get("p01")
    return (OUTSIDE,
            f"Nothing in the sixteen quarters approaches it: the most extreme "
            f"one per cent of moves reach {worst:,.2f}{body.unit} against the "
            f"{body.proposed:,.2f}{body.unit} proposed. It can still be "
            "calculated, as a tail scenario.")


#: Which measure a shock is compared against, and how the magnitude is read.
_MEASURES: dict[str, tuple[str, str, str]] = {
    "pd": ("pd_12m", "twelve-month PD", "%"),
    "lgd": ("lgd", "loss given default", "pp"),
    "ead": ("ead", "exposure at default", "%"),
    "ccf": ("credit_conversion_factor", "credit conversion factor", ""),
    "collateral": ("collateral_market_value", "collateral value", "%"),
    "rating": ("internal_rating_numeric", "rating notches", " notches"),
    "stage": ("stage", "Stage", " stages"),
}

_COLUMNS: tuple[str, ...] = (
    "borrower_id", "sector", "segment", "internal_rating",
    "internal_rating_numeric", "stage", "pd_12m", "pd_lifetime", "lgd", "ead",
    "final_ecl", "credit_conversion_factor", "collateral_market_value",
)


def assess(state: Any, *, source: Any = None) -> dict[str, Any]:
    """Place a scenario in the book's own experience.

    One assessment per shock, and an overall label that is the WORST of them —
    a scenario is as unusual as its most unusual component, and averaging them
    would let three ordinary shocks hide one that has never happened.
    """
    from backend.whatif import scenarios as sc

    steps = list(getattr(state, "active", ()) or ())
    shocks = [shock for step in steps for shock in getattr(step, "shocks", ())]
    if not shocks:
        return {"available": False,
                "why": "There is no shock to compare against history."}

    try:
        panel = _panel(_COLUMNS, source=source)
    except Exception as e:  # noqa: BLE001 - a missing history is said, not raised
        logger.warning("Could not read the history panel: %s", e)
        return {"available": False,
                "why": f"The historical book could not be read: {e}"}
    if panel.empty:
        return {"available": False,
                "why": "The historical book carries no comparable movement."}

    quarters = _ordered(list(panel["period"].unique()))
    assessed: list[dict[str, Any]] = []
    for shock in shocks:
        kind = str(getattr(shock, "kind", ""))
        magnitude = float(getattr(shock, "magnitude", 0.0))
        unit = str(getattr(shock, "unit", ""))
        found = _MEASURES.get(kind)
        if found is None:
            continue
        column, label, shown = found

        # A rating shock is stated in notches and compared against notches; a
        # macro shock reaches the book through PD and is compared there.
        relative = unit == sc.RELATIVE and kind not in ("rating", "stage")
        proposed = magnitude
        if kind == "rating":
            relative, shown = False, " notches"
        elif unit == sc.ABSOLUTE_PP and kind in ("pd", "lgd"):
            relative, shown = False, "pp"
        elif unit == sc.BASIS_POINTS:
            relative, proposed, shown = False, magnitude / 100.0, "pp"

        body = measure(panel, column, proposed=proposed, relative=relative,
                       label=label, unit=shown)
        label_given, because = verdict(body)
        assessed.append({
            "shock": (shock.describe() if hasattr(shock, "describe") else kind),
            "kind": kind,
            "verdict": label_given,
            "because": because,
            "evidence": body.to_dict(),
        })

    if not assessed:
        return {"available": False,
                "why": "None of these shocks has a comparable historical "
                       "movement in this book."}

    worst = max(assessed, key=lambda a: LABELS.index(a["verdict"]))
    return {
        "available": True,
        "version": PLAUSIBILITY_VERSION,
        "verdict": worst["verdict"],
        "because": worst["because"],
        "driven_by": worst["shock"],
        "shocks": assessed,
        "window": {"quarters": len(quarters),
                   "from": quarters[0] if quarters else "",
                   "to": quarters[-1] if quarters else ""},
        "labels": list(LABELS),
        "statement": (
            "This is NOT a forecast and NOT a probability. It compares the "
            "proposed shock against what this book has actually done across "
            f"{len(quarters)} quarters. A scenario outside that experience is "
            "still calculated; it is labelled, not refused."),
        "limitation": (
            f"{len(quarters)} quarters is a short window. It is enough to say "
            "whether a move of this size has been seen and how widely, and it "
            "is not enough to estimate how likely one is."),
    }


def describe() -> dict[str, Any]:
    """The plausibility method, for the configuration screen."""
    return {
        "version": PLAUSIBILITY_VERSION,
        "labels": [
            {"label": CONSISTENT,
             "earned_by": f"at least {COMMON_SHARE:.0%} of borrower-quarters "
                          "saw a move this large"},
            {"label": PLAUSIBLE,
             "earned_by": f"at least {POCKET_SHARE:.0%} of borrower-quarters, "
                          f"in {REPEATED_QUARTERS} or more quarters"},
            {"label": POCKETS,
             "earned_by": "seen repeatedly, but in a small or concentrated "
                          "part of the book"},
            {"label": SEVERE_OBSERVED,
             "earned_by": "reached in one quarter of the window and no other"},
            {"label": SEVERE_RECENT,
             "earned_by": "not reached in any quarter, but reached over a year"},
            {"label": OUTSIDE,
             "earned_by": "nothing in the window approaches it"},
        ],
        "not_a_probability": (
            "There is no likelihood here. Nothing in sixteen quarters of one "
            "synthetic book supports a statement of the form 'this has a 3% "
            "chance of occurring', and a number like that would be believed."),
        "measured_on": "each borrower's own movement, quarter on quarter and "
                       "year on year — not the portfolio average, which can be "
                       "flat while a third of the book doubles",
    }


__all__ = [
    "CONSISTENT", "Evidence", "LABELS", "OUTSIDE", "PLAUSIBILITY_VERSION",
    "PLAUSIBLE", "POCKETS", "SEVERE_OBSERVED", "SEVERE_RECENT", "assess",
    "describe", "measure", "reset_cache", "verdict",
]
