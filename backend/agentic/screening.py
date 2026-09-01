"""
Deterministic pre-screening. §36, §56.

    "Do not make unrestricted model calls over the entire raw book.
     Use deterministic pre-screening and aggregation first."

The funnel §56 asks for, in one module:

    the whole book
      → deterministic screening        (this module, no model at all)
      → material segments              (governed thresholds, not judgement)
      → material borrowers             (top contributors to those segments)
      → specialist analysis            (agents, on a bounded population)
      → LLM synthesis                  (only on validated findings)

Everything here is a DuckDB aggregate over published Parquet. No model is
called, nothing is judged, and the output is a compact evidence package —
figures with the movement that produced them — that a specialist can act on and
a Risk Case can be built from.

Why this is worth building rather than "just ask the model"
-----------------------------------------------------------
The demonstration book is 20 datasets over 15 quarters. Handing a model even a
sector-level extract of that is tens of thousands of rows per period, per
domain, and it would be asked to notice which numbers moved — which is
arithmetic, is not what a model is good at, and cannot be reproduced. Doing the
arithmetic first turns a review that would cost hundreds of model calls into one
that costs a handful, and turns "the model said Contracting deteriorated" into
"Stage 2 share in Contracting rose from 11.4% to 18.9%".

Thresholds
----------
Every threshold is a named constant with a stated reason, and each is a *policy*
value an administrator can override (`agent_policies`, key `screening`). None of
them is a model's opinion, and none is a magic number in the middle of a
comparison.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

VERSION = "1.0"

# ---------------------------------------------------------------------------
# Thresholds — what "material" means, stated
# ---------------------------------------------------------------------------

#: A portfolio-level ratio that moves by this much in relative terms is worth a
#: person's attention. 10% relative rather than an absolute number of basis
#: points, because the same absolute move means very different things at a
#: coverage of 0.9% and at 9%.
PORTFOLIO_MOVE = 0.10

#: A segment has to move more than the portfolio to be interesting — a sector
#: that rose with everything else has not told anybody anything.
SEGMENT_MOVE = 0.15

#: …and it has to be big enough to matter. A 40% move on 0.3% of the book is
#: noise with a large percentage attached.
SEGMENT_MIN_SHARE = 0.02

#: A borrower is a contributor when it accounts for this much of a segment's
#: movement.
BORROWER_CONTRIBUTION = 0.05

#: How many of each to carry forward. The funnel exists to make the next stage
#: cheap; carrying two hundred borrowers forward defeats it.
MAX_SEGMENTS = 6
MAX_BORROWERS = 12

# -- what counts as a borrower-level signal ---------------------------------
#
# §1 asks the review to produce cases across the categories a credit committee
# actually works through - rating movement, Stage 2 migration, delinquency,
# covenant pressure, collateral deterioration, concentration, ECL movement -
# rather than only the two the screen used to look at. Every threshold below
# is a comparison of two PUBLISHED figures at the customer grain, on columns
# the screen already reads; none of them adds a query and none of them is a
# judgement about what the change means.
#
# They are deliberately not tight. A signal is a reason to LOOK, and the
# severity model downstream decides what is worth a case; a threshold set so
# high that only a crisis trips it produces a review that finds nothing and
# reads as though nobody ran it.

#: A relative rise in a borrower's expected credit loss. 25% on a small number
#: is still a large move in the thing the whole IFRS 9 book is about.
ECL_RISE = 0.25

#: …but not on a rounding error. Below this the percentage is arithmetic on
#: noise, in the currency the book is published in.
ECL_FLOOR = 100_000.0

#: A rise in facility utilisation, in percentage points. A borrower drawing
#: down its committed lines is the classic early sign of liquidity pressure,
#: and it moves before the rating does.
UTILISATION_RISE = 5.0

#: Utilisation this high is worth reporting even where it did not move, because
#: a borrower with no headroom left has no room to absorb anything.
UTILISATION_HIGH = 95.0

#: Datasets the screen reads. Every one is governed and published; the screen
#: never reaches for anything else.
FACILITIES = "portfolio_facility"
STAGING = "ifrs9_staging"
DELINQUENCY = "facility_delinquency"
RATINGS = "customer_ratings"
COVENANTS = "covenant_tests"
APPETITE = "risk_appetite_limits"


def thresholds() -> dict[str, float | int]:
    return {
        "portfolio_move": PORTFOLIO_MOVE,
        "segment_move": SEGMENT_MOVE,
        "segment_min_share": SEGMENT_MIN_SHARE,
        "borrower_contribution": BORROWER_CONTRIBUTION,
        "max_segments": MAX_SEGMENTS,
        "max_borrowers": MAX_BORROWERS,
    }


# ---------------------------------------------------------------------------
# What comes out
# ---------------------------------------------------------------------------


@dataclass
class Indicator:
    """One measured figure and how it moved."""

    key: str
    label: str
    unit: str
    now: float | None
    before: float | None = None
    #: True where a higher number is worse, from the semantic ontology.
    higher_is_worse: bool = True
    dataset: str = ""

    @property
    def change(self) -> float | None:
        if self.now is None or self.before is None:
            return None
        return self.now - self.before

    @property
    def relative(self) -> float | None:
        """The movement as a proportion of where it started."""
        if self.now is None or self.before in (None, 0):
            return None
        return (self.now - self.before) / abs(self.before)

    @property
    def adverse(self) -> bool:
        move = self.change
        if move is None or move == 0:
            return False
        return move > 0 if self.higher_is_worse else move < 0

    @property
    def material(self) -> bool:
        rel = self.relative
        return bool(self.adverse and rel is not None
                    and abs(rel) >= PORTFOLIO_MOVE)

    def sentence(self) -> str:
        if self.now is None:
            return f"{self.label} could not be measured."
        if self.before is None:
            return f"{self.label} is {_fmt(self.now, self.unit)}."
        direction = "rose" if (self.change or 0) > 0 else "fell"
        rel = self.relative
        tail = f" ({rel:+.1%})" if rel is not None else ""
        return (f"{self.label} {direction} from {_fmt(self.before, self.unit)} "
                f"to {_fmt(self.now, self.unit)}{tail}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "unit": self.unit,
            "now": self.now, "before": self.before, "change": self.change,
            "relative": self.relative, "adverse": self.adverse,
            "material": self.material, "dataset": self.dataset,
            "higher_is_worse": self.higher_is_worse,
            "sentence": self.sentence(),
        }


@dataclass
class Segment:
    """One sector, region or product, and what moved in it."""

    name: str
    kind: str = "sector"
    exposure: float | None = None
    share_of_book: float | None = None
    indicators: list[Indicator] = field(default_factory=list)

    @property
    def adverse(self) -> list[Indicator]:
        return [i for i in self.indicators if i.adverse]

    @property
    def worst(self) -> Indicator | None:
        moved = [i for i in self.adverse if i.relative is not None]
        return max(moved, key=lambda i: abs(i.relative or 0)) if moved else None

    @property
    def material(self) -> bool:
        """Big enough to matter, and moving more than the book."""
        if (self.share_of_book or 0) < SEGMENT_MIN_SHARE:
            return False
        worst = self.worst
        return bool(worst and abs(worst.relative or 0) >= SEGMENT_MOVE)

    def to_dict(self) -> dict[str, Any]:
        worst = self.worst
        return {
            "name": self.name, "kind": self.kind, "exposure": self.exposure,
            "share_of_book": self.share_of_book, "material": self.material,
            "worst": worst.to_dict() if worst else None,
            "adverse_count": len(self.adverse),
            "indicators": [i.to_dict() for i in self.indicators],
        }


@dataclass
class Borrower:
    """One customer contributing to a segment's movement."""

    customer_id: str
    name: str
    sector: str = ""
    exposure: float | None = None
    ecl_now: float | None = None
    ecl_before: float | None = None
    ecl_change: float | None = None
    stage_now: str = ""
    stage_before: str = ""
    rating_now: str = ""
    rating_before: str = ""
    dpd: int | None = None
    contribution: float | None = None
    signals: list[str] = field(default_factory=list)

    @property
    def ecl_relative(self) -> float | None:
        """The ECL movement against where it started.

        The right magnitude for a borrower case. Measuring it against EXPOSURE
        instead makes a doubling of a small provision look like a rounding
        error, because provisions are a fraction of exposure by construction —
        every borrower then scored LOW however badly it deteriorated.
        """
        if self.ecl_change is None or not self.ecl_before:
            return None
        return self.ecl_change / abs(self.ecl_before)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id, "name": self.name,
            "sector": self.sector, "exposure": self.exposure,
            "ecl_now": self.ecl_now, "ecl_before": self.ecl_before,
            "ecl_change": self.ecl_change,
            "ecl_relative": self.ecl_relative, "stage_now": self.stage_now,
            "stage_before": self.stage_before, "rating_now": self.rating_now,
            "rating_before": self.rating_before, "dpd": self.dpd,
            "contribution": self.contribution, "signals": list(self.signals),
        }


@dataclass
class Screen:
    """The whole pre-screen: the funnel, measured."""

    period: str
    prior_period: str = ""
    portfolio: list[Indicator] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    borrowers: list[Borrower] = field(default_factory=list)
    data_issues: list[dict[str, Any]] = field(default_factory=list)
    #: §56's funnel figures, for the cost record.
    rows_screened: int = 0
    segments_reviewed: int = 0
    borrowers_escalated: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def material_portfolio(self) -> list[Indicator]:
        return [i for i in self.portfolio if i.material]

    @property
    def material_segments(self) -> list[Segment]:
        found = [s for s in self.segments if s.material]
        found.sort(key=lambda s: -abs((s.worst.relative if s.worst else 0) or 0))
        return found[:MAX_SEGMENTS]

    @property
    def empty(self) -> bool:
        return not (self.material_portfolio or self.material_segments
                    or self.borrowers or self.data_issues)

    def funnel(self) -> dict[str, Any]:
        """§56: what the screen cost and how much it removed."""
        return {
            "rows_screened": self.rows_screened,
            "segments_reviewed": self.segments_reviewed,
            "segments_material": len(self.material_segments),
            "borrowers_escalated": self.borrowers_escalated,
            "portfolio_indicators": len(self.portfolio),
            "portfolio_material": len(self.material_portfolio),
            "model_calls": 0,
            "reduction": _reduction(self.rows_screened,
                                    self.borrowers_escalated),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "period": self.period,
            "prior_period": self.prior_period,
            "thresholds": thresholds(),
            "portfolio": [i.to_dict() for i in self.portfolio],
            "segments": [s.to_dict() for s in self.segments],
            "material_segments": [s.name for s in self.material_segments],
            "borrowers": [b.to_dict() for b in self.borrowers],
            "data_issues": list(self.data_issues),
            "funnel": self.funnel(),
            "notes": list(self.notes),
        }


def _reduction(rows: int, escalated: int) -> str:
    if not rows:
        return "nothing was screened"
    if not escalated:
        return f"{rows:,} rows screened, nothing escalated"
    return (f"{rows:,} rows screened down to {escalated} borrower(s) — "
            f"{escalated / rows:.4%} of the book reached a specialist")


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def run(period: str, *, prior_period: str = "", source: Any = None,
        user_id: int | None = None) -> Screen:
    """Screen the book at a period against the one before it.

    Reads only published, governed datasets through the Data Access Layer. No
    model is called anywhere in this function, and the absence is deliberate
    rather than incidental — see the module note.
    """
    from backend.data_access.context import AnalysisContext
    from backend.data_access.duckdb_source import DuckDBSource

    dal = source or DuckDBSource()
    prior = prior_period or _previous(dal, period)
    screen = Screen(period=period, prior_period=prior)
    if not prior:
        screen.notes.append(
            f"{period} is the earliest published period, so nothing can be "
            f"compared against it.")

    now_ctx = AnalysisContext(period=period, user_id=user_id)
    before_ctx = (AnalysisContext(period=prior, user_id=user_id)
                  if prior else None)

    _portfolio(dal, screen, now_ctx, before_ctx)
    _segments(dal, screen, now_ctx, before_ctx)
    _borrowers(dal, screen, now_ctx, before_ctx)
    _data_quality(dal, screen, period)

    logger.info("pre-screen %s vs %s: %s", period, prior or "—",
                screen.funnel()["reduction"])
    return screen


def _previous(dal: Any, period: str) -> str:
    """The period before this one, from what is actually published."""
    try:
        periods = list(dal.periods(FACILITIES))
    except Exception:  # noqa: BLE001 - an unreadable dataset is reported below
        return ""
    if period not in periods:
        return periods[-2] if len(periods) >= 2 else ""
    index = periods.index(period)
    return periods[index - 1] if index > 0 else ""


# -- portfolio --------------------------------------------------------------


def _portfolio(dal: Any, screen: Screen, now: Any, before: Any) -> None:
    """The book-level indicators. §41's list, measured."""
    current = _book(dal, now)
    prior = _book(dal, before) if before is not None else {}
    screen.rows_screened += int(current.get("_rows", 0)) + int(
        prior.get("_rows", 0))

    for key, label, unit, worse in (
        ("ead", "Exposure at default", "SAR mn", False),
        ("ecl", "Expected credit loss", "SAR mn", True),
        ("ecl_coverage", "ECL coverage", "%", True),
        ("stage2_share", "Stage 2 share of exposure", "%", True),
        ("stage3_share", "Stage 3 share of exposure", "%", True),
        ("npl_ratio", "NPL ratio", "%", True),
        ("watchlist_share", "Watchlisted share of accounts", "%", True),
        ("appetite_breaches", "Sectors breaching risk appetite", "", True),
    ):
        screen.portfolio.append(Indicator(
            key=key, label=label, unit=unit,
            now=current.get(key), before=prior.get(key) if prior else None,
            higher_is_worse=worse, dataset=FACILITIES))

    downgrades = _downgrade_rate(dal, now, before)
    if downgrades is not None:
        screen.portfolio.append(downgrades)


def _book(dal: Any, context: Any) -> dict[str, Any]:
    """Book totals at one period, in one grouped scan."""
    if context is None:
        return {}
    try:
        frame = dal.aggregate(
            FACILITIES, context=context,
            group_by=["ifrs9_stage"],
            measures={"ead": "sum", "total_ecl": "sum", "npl": "sum",
                      "watchlist": "sum", "account_id": "count"})
    except Exception:  # noqa: BLE001 - a missing period is a finding, not a crash
        logger.warning("portfolio screen could not read %s",
                       getattr(context, "period", "?"), exc_info=True)
        return {}

    rows = frame.to_dict("records")
    total_ead = sum(float(r.get("ead") or 0) for r in rows)
    total_ecl = sum(float(r.get("total_ecl") or 0) for r in rows)
    npl_ead = sum(float(r.get("ead") or 0) for r in rows
                  if _truthy(r.get("npl")))
    by_stage = {str(r.get("ifrs9_stage") or ""): float(r.get("ead") or 0)
                for r in rows}
    watch = sum(float(r.get("watchlist") or 0) for r in rows)
    count = sum(int(r.get("account_id") or 0) for r in rows)

    found: dict[str, Any] = {
        "_rows": count,
        "ead": round(total_ead, 3),
        "ecl": round(total_ecl, 3),
        "ecl_coverage": _pct(total_ecl, total_ead),
        "stage2_share": _pct(by_stage.get("2", by_stage.get("Stage 2", 0.0)),
                             total_ead),
        "stage3_share": _pct(by_stage.get("3", by_stage.get("Stage 3", 0.0)),
                             total_ead),
        "npl_ratio": _pct(npl_ead, total_ead),
        # A share of ACCOUNTS. `watchlist` is a per-facility flag and the
        # scan groups by stage, so watchlisted EAD is not recoverable from
        # this frame; reporting it as an exposure share would be a label that
        # does not describe the arithmetic under it.
        "watchlist_share": _pct(watch, count) if count else None,
    }
    found["appetite_breaches"] = _appetite_breaches(dal, context)
    return found


def _appetite_breaches(dal: Any, context: Any) -> float | None:
    """How many sectors are outside the bank's stated risk appetite."""
    try:
        frame = dal.aggregate(
            APPETITE, context=context, group_by=["status"],
            measures={"sector": "nunique"})
    except Exception:  # noqa: BLE001
        return None
    breached = 0
    for row in frame.to_dict("records"):
        status = str(row.get("status") or "").strip().lower()
        if status in {"breach", "breached", "over", "exceeded"}:
            breached += int(row.get("sector") or 0)
    return float(breached)


def _downgrade_rate(dal: Any, now: Any, before: Any) -> Indicator | None:
    """The share of rated customers downgraded, this period against last."""
    def rate(context: Any) -> float | None:
        if context is None:
            return None
        try:
            frame = dal.aggregate(
                RATINGS, context=context, group_by=["rating_action"],
                measures={"customer_id": "nunique"})
        except Exception:  # noqa: BLE001
            return None
        rows = frame.to_dict("records")
        total = sum(int(r.get("customer_id") or 0) for r in rows)
        down = sum(int(r.get("customer_id") or 0) for r in rows
                   if "downgrade" in str(r.get("rating_action") or "").lower())
        return _pct(down, total)

    current = rate(now)
    if current is None:
        return None
    return Indicator(key="downgrade_rate", label="Downgrade rate", unit="%",
                     now=current, before=rate(before), higher_is_worse=True,
                     dataset=RATINGS)


# -- segments ---------------------------------------------------------------


def _segments(dal: Any, screen: Screen, now: Any, before: Any) -> None:
    """Sector-level indicators, in two scans rather than one per sector."""
    current = _by_sector(dal, now)
    prior = _by_sector(dal, before) if before is not None else {}
    if not current:
        return

    book = sum(float(v.get("ead") or 0) for v in current.values()) or 1.0
    for name, figures in current.items():
        was = prior.get(name, {})
        segment = Segment(
            name=name, kind="sector",
            exposure=figures.get("ead"),
            share_of_book=round(float(figures.get("ead") or 0) / book, 4))
        for key, label, unit, worse in (
            ("ecl", "Expected credit loss", "SAR mn", True),
            ("ecl_coverage", "ECL coverage", "%", True),
            ("stage2_share", "Stage 2 share", "%", True),
            ("npl_ratio", "NPL ratio", "%", True),
            ("ead", "Exposure at default", "SAR mn", False),
        ):
            segment.indicators.append(Indicator(
                key=key, label=label, unit=unit, now=figures.get(key),
                before=was.get(key) if was else None,
                higher_is_worse=worse, dataset=FACILITIES))
        screen.segments.append(segment)

    screen.segments_reviewed = len(screen.segments)


def _by_sector(dal: Any, context: Any) -> dict[str, dict[str, Any]]:
    if context is None:
        return {}
    try:
        frame = dal.aggregate(
            FACILITIES, context=context, group_by=["sector", "ifrs9_stage"],
            measures={"ead": "sum", "total_ecl": "sum", "npl": "sum"})
    except Exception:  # noqa: BLE001
        logger.warning("segment screen could not read %s",
                       getattr(context, "period", "?"), exc_info=True)
        return {}

    found: dict[str, dict[str, float]] = {}
    stages: dict[str, dict[str, float]] = {}
    for row in frame.to_dict("records"):
        sector = str(row.get("sector") or "Unclassified")
        ead = float(row.get("ead") or 0)
        bucket = found.setdefault(sector, {"ead": 0.0, "ecl": 0.0, "npl": 0.0})
        bucket["ead"] += ead
        bucket["ecl"] += float(row.get("total_ecl") or 0)
        if _truthy(row.get("npl")):
            bucket["npl"] += ead
        stage = str(row.get("ifrs9_stage") or "")
        stages.setdefault(sector, {})[stage] = (
            stages.setdefault(sector, {}).get(stage, 0.0) + ead)

    for sector, bucket in found.items():
        total = bucket["ead"]
        by_stage = stages.get(sector, {})
        bucket["ecl_coverage"] = _pct(bucket["ecl"], total) or 0.0
        bucket["stage2_share"] = _pct(
            by_stage.get("2", by_stage.get("Stage 2", 0.0)), total) or 0.0
        bucket["npl_ratio"] = _pct(bucket["npl"], total) or 0.0
        bucket["ead"] = round(total, 3)
        bucket["ecl"] = round(bucket["ecl"], 3)
    return found


# -- borrowers --------------------------------------------------------------


def _borrowers(dal: Any, screen: Screen, now: Any, before: Any) -> None:
    """Which customers drive the material segments' movement.

    Scoped to the material segments rather than run over the book. That is the
    funnel: a scan of every borrower would be the thing §36 asks us not to do,
    only in SQL rather than in tokens.
    """
    material = screen.material_segments
    if not material or before is None:
        return

    sectors = [s.name for s in material]
    current = _by_customer(dal, now, sectors)
    prior = _by_customer(dal, before, sectors)
    if not current:
        return

    moves: list[Borrower] = []
    for key, figures in current.items():
        was = prior.get(key, {})
        ecl_now = float(figures.get("ecl") or 0)
        ecl_before = float(was.get("ecl") or 0) if was else 0.0
        change = ecl_now - ecl_before
        if change <= 0:
            continue
        moves.append(Borrower(
            customer_id=str(figures.get("customer_id") or key),
            name=str(figures.get("name") or key),
            sector=str(figures.get("sector") or ""),
            exposure=round(float(figures.get("ead") or 0), 3),
            ecl_now=round(ecl_now, 4),
            ecl_before=round(ecl_before, 4),
            ecl_change=round(change, 4),
            stage_now=str(figures.get("stage") or ""),
            stage_before=str(was.get("stage") or "") if was else "",
            rating_now=str(figures.get("rating") or ""),
            rating_before=str(was.get("rating") or "") if was else "",
            dpd=int(figures.get("dpd") or 0) or None,
            signals=_signals(figures, was)))

    total = sum(b.ecl_change or 0 for b in moves) or 1.0
    for borrower in moves:
        borrower.contribution = round((borrower.ecl_change or 0) / total, 4)

    moves.sort(key=lambda b: -(b.ecl_change or 0))
    kept = [b for b in moves
            if (b.contribution or 0) >= BORROWER_CONTRIBUTION][:MAX_BORROWERS]
    screen.borrowers = kept or moves[:min(3, len(moves))]
    screen.borrowers_escalated = len(screen.borrowers)


def _by_customer(dal: Any, context: Any,
                 sectors: list[str]) -> dict[str, dict[str, Any]]:
    if context is None or not sectors:
        return {}
    scoped = context.with_filters(sector=sectors)
    try:
        frame = dal.aggregate(
            FACILITIES, context=scoped,
            group_by=["customer_id", "borrower_name", "sector",
                      "ifrs9_stage", "risk_rating"],
            # `max` on the flags and the ratio: a relationship is on the
            # watchlist if any facility is, is non-performing if any facility
            # is, and is as drawn as its most-drawn line. Summing a percentage
            # across facilities would produce a number with no meaning.
            measures={"ead": "sum", "total_ecl": "sum", "dpd_days": "max",
                      "utilisation_pct": "max", "watchlist": "max",
                      "npl": "max"})
    except Exception:  # noqa: BLE001
        logger.warning("borrower screen could not read %s",
                       getattr(context, "period", "?"), exc_info=True)
        return {}

    found: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        key = str(row.get("customer_id") or "")
        if not key:
            continue
        bucket = found.setdefault(key, {
            "customer_id": key, "name": row.get("borrower_name") or key,
            "sector": row.get("sector") or "", "ead": 0.0, "ecl": 0.0,
            "stage": "", "rating": row.get("risk_rating") or "", "dpd": 0,
            "utilisation": 0.0, "watchlist": False, "npl": False})
        bucket["ead"] += float(row.get("ead") or 0)
        bucket["ecl"] += float(row.get("total_ecl") or 0)
        bucket["dpd"] = max(int(bucket["dpd"] or 0),
                            int(row.get("dpd_days") or 0))
        bucket["utilisation"] = max(float(bucket["utilisation"] or 0.0),
                                    float(row.get("utilisation_pct") or 0.0))
        bucket["watchlist"] = bucket["watchlist"] or _truthy(
            row.get("watchlist"))
        bucket["npl"] = bucket["npl"] or _truthy(row.get("npl"))
        # Worst stage wins: a customer with one Stage 3 facility is a Stage 3
        # customer, whatever the rest of the relationship looks like.
        stage = str(row.get("ifrs9_stage") or "")
        if stage > str(bucket["stage"]):
            bucket["stage"] = stage
    return found


def _signals(now: dict[str, Any], before: dict[str, Any]) -> list[str]:
    """The governed signals that changed for this borrower.

    Every one is a comparison of two published figures. Nothing here is a
    judgement about what the change means.
    """
    found: list[str] = []
    if before:
        if str(now.get("stage") or "") > str(before.get("stage") or ""):
            found.append(
                f"Stage moved from {before.get('stage') or '—'} to "
                f"{now.get('stage')}")
        if (now.get("rating") and before.get("rating")
                and now["rating"] != before["rating"]):
            found.append(
                f"Rating moved from {before['rating']} to {now['rating']}")

        # ECL movement. The book's own headline measure, and the one a
        # committee asks about first; reported as the move rather than the
        # level, because a large ECL that has not moved is last quarter's
        # conversation.
        was, is_now = float(before.get("ecl") or 0.0), float(now.get("ecl") or 0.0)
        if was >= ECL_FLOOR and is_now > was * (1.0 + ECL_RISE):
            found.append(
                f"Expected credit loss rose {_pct(is_now - was, was):.0%} "
                f"from {was:,.0f} to {is_now:,.0f}"
                if _pct(is_now - was, was) is not None else
                f"Expected credit loss rose from {was:,.0f} to {is_now:,.0f}")

        # Liquidity pressure, which shows up in the drawing behaviour before it
        # shows up in the rating.
        drawn = float(now.get("utilisation") or 0.0)
        drawn_before = float(before.get("utilisation") or 0.0)
        if drawn_before and drawn - drawn_before >= UTILISATION_RISE:
            found.append(
                f"Utilisation rose from {drawn_before:.1f}% to {drawn:.1f}%")
        elif drawn >= UTILISATION_HIGH:
            found.append(f"Utilisation at {drawn:.1f}% leaves no headroom")

        # Entering the watchlist is a decision somebody recorded, not a
        # measurement, and it is worth a case precisely because a human already
        # thought so. Leaving it is not a signal to escalate.
        if _truthy(now.get("watchlist")) and not _truthy(before.get("watchlist")):
            found.append("Added to the watchlist this period")
        if _truthy(now.get("npl")) and not _truthy(before.get("npl")):
            found.append("Classified non-performing this period")

    if int(now.get("dpd") or 0) > 0:
        found.append(f"{int(now['dpd'])} days past due")
    return found


# -- data quality -----------------------------------------------------------


def _data_quality(dal: Any, screen: Screen, period: str) -> None:
    """Datasets that are not there, at a period the review needs.

    §44's data attention items start here: a review that quietly proceeded
    without covenant data would report a covenant picture nobody measured.
    """
    for dataset in (FACILITIES, STAGING, DELINQUENCY, RATINGS, COVENANTS,
                    APPETITE):
        try:
            periods = list(dal.periods(dataset))
        except Exception as exc:  # noqa: BLE001
            screen.data_issues.append({
                "dataset": dataset, "period": period, "issue": "unreadable",
                "detail": f"{dataset} could not be read: {exc}"})
            continue
        # A dataset with no period dimension (a reference table) publishes one
        # partition and is not missing anything.
        if not periods or period in periods:
            continue
        # Nor is an ANNUAL dataset missing a quarter. `customer_ratings`
        # publishes "2025", and flagging it as absent at "Q2 2026" reported a
        # data-quality issue on a dataset that is exactly where it should be —
        # which is worse than saying nothing, because it teaches a reader to
        # ignore the data issues.
        if not _same_calendar(period, periods):
            screen.notes.append(
                f"{dataset} is published on a different calendar "
                f"({periods[-1]}) and was read at its own latest period.")
            continue
        screen.data_issues.append({
            "dataset": dataset, "period": period,
            "issue": "not_published",
            "detail": (f"{dataset} has no data for {period}. The most "
                       f"recent published period is {periods[-1]}.")})


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _same_calendar(period: str, published: list[str]) -> bool:
    """Whether a dataset is published on the same calendar as the review.

    A quarterly review period is "Q2 2026"; an annual dataset publishes
    "2025". Comparing the two as strings makes every annual reference table
    look permanently out of date.
    """
    quarterly = "q" in period.strip().lower()[:2]
    return any(("q" in str(p).strip().lower()[:2]) == quarterly
               for p in published)


def _pct(part: float, whole: float) -> float | None:
    if not whole:
        return None
    return round(part / whole * 100.0, 4)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "1"}
    return bool(value)


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "%":
        return f"{value:,.2f}%"
    if unit:
        return f"{value:,.1f} {unit}"
    return f"{value:,.0f}"


__all__ = [
    "APPETITE",
    "BORROWER_CONTRIBUTION",
    "COVENANTS",
    "DELINQUENCY",
    "FACILITIES",
    "MAX_BORROWERS",
    "MAX_SEGMENTS",
    "PORTFOLIO_MOVE",
    "RATINGS",
    "SEGMENT_MIN_SHARE",
    "SEGMENT_MOVE",
    "STAGING",
    "VERSION",
    "Borrower",
    "Indicator",
    "Screen",
    "Segment",
    "run",
    "thresholds",
]
