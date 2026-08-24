"""
Early Warning, end to end: build the panel, fit, backtest, score, version.

The panel
---------
Everything starts with one table: for each facility, in each quarter, the
factors as they were observable AT THAT QUARTER END, and whether the facility
migrated in the NEXT one. The two halves come from different periods on purpose.
Building it any other way — using this quarter's outcome alongside this
quarter's factors — is target leakage, it produces a model that appears to
predict the present perfectly, and it is the mistake that most often survives
into production because the numbers look wonderful.

Versioning
----------
A fitted specification is stored whole, as a value. Refitting produces a NEW
version rather than editing one, so a score quoted last month can still be
reproduced. Only one version per target is active at a time, and switching is a
recorded act.

Nothing here calls anything validated. See `lifecycle.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.config import settings
from backend.data_access.context import AnalysisContext
from backend.data_access.duckdb_source import DuckDBSource
from backend.early_warning import backtest as bt
from backend.early_warning import lifecycle as lc
from backend.early_warning.factors import (
    FACTOR_FAMILIES,
    FACTORS,
    REQUIRED_FIELDS,
    compute_factors,
)
from backend.early_warning.model import (
    SignalSpecification,
    fit_specification,
    probabilities,
    score_frame,
)
from backend.early_warning.targets import TARGETS, TargetDef, target

logger = logging.getLogger(__name__)

FACILITY = "portfolio_facility"
STAGING = "ifrs9_staging"
MACRO = "macro_saudi"

#: Quarters held back from fitting and used only for testing. Three is enough to
#: see whether performance holds up across a turn in the cycle rather than in
#: one lucky quarter.
DEFAULT_TEST_QUARTERS = 3


class EarlyWarningError(RuntimeError):
    pass


class ModelNotFound(LookupError):
    pass


class StorageUnavailable(RuntimeError):
    """Versioning needs PostgreSQL. Fitting and scoring do not."""


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Storing a model version needs PostgreSQL. The signal can still be "
            "fitted and scored without it; the version just is not kept."
        )


# ============================================================== the panel


def cycle_exposure_by_sector(source: DuckDBSource, period: str) -> dict[str, float]:
    """Each sector's cycle exposure at one quarter: its beta times the cycle.

    The betas are the sectors' realised sensitivities, estimated once from the
    macro series and the book rather than asserted. Where the macro series is
    unavailable the exposure is zero for every sector, which leaves the factor
    carrying no information rather than carrying a guess.
    """
    if MACRO not in source.datasets():
        return {}
    try:
        macro = source.fetch(
            MACRO, context=AnalysisContext(period=period), period=period,
            fields=["credit_cycle_factor"],
        )
    except Exception:  # pragma: no cover - a period the macro series lacks
        return {}
    if macro.empty:
        return {}
    factor = float(macro["credit_cycle_factor"].iloc[0])

    # Sector sensitivity, read off the book: the sectors whose average PD moves
    # most against the cycle are the ones the cycle moves. Estimated from the
    # data rather than hard-coded, so it stays true if the book changes.
    # beta is d(mean PD)/d(cycle factor), so it is NEGATIVE for a cyclical
    # sector: a supportive quarter lowers its PDs. Multiplying the two gives a
    # POSITIVE number exactly when the cycle is currently working against that
    # sector, which is what the factor is supposed to mean. Negating it here —
    # the obvious-looking thing to do — would invert the factor for every
    # sector in the book.
    betas = _sector_betas(source)
    return {sector: beta * factor for sector, beta in betas.items()}


_BETA_CACHE: dict[str, float] | None = None


def _sector_betas(source: DuckDBSource) -> dict[str, float]:
    """How strongly each sector's average PD responds to the credit cycle.

    A simple slope of mean PD on the cycle factor, per sector, across the whole
    book. Cached because it is a property of the published data, not of a
    request.
    """
    global _BETA_CACHE
    if _BETA_CACHE is not None:
        return _BETA_CACHE
    if MACRO not in source.datasets():
        _BETA_CACHE = {}
        return _BETA_CACHE

    rows = []
    for period in source.periods(FACILITY):
        try:
            macro = source.fetch(MACRO, context=AnalysisContext(period=period),
                                 period=period, fields=["credit_cycle_factor"])
            book = source.fetch(FACILITY, context=AnalysisContext(period=period),
                                period=period, fields=["sector", "pd_12m_pct"])
        except Exception:  # pragma: no cover - a period one dataset lacks
            continue
        if macro.empty or book.empty:
            continue
        cycle = float(macro["credit_cycle_factor"].iloc[0])
        mean_pd = book.groupby("sector")["pd_12m_pct"].mean()
        for sector, value in mean_pd.items():
            rows.append((sector, cycle, float(value)))

    if not rows:
        _BETA_CACHE = {}
        return _BETA_CACHE

    frame = pd.DataFrame(rows, columns=["sector", "cycle", "pd"])
    betas: dict[str, float] = {}
    for sector, group in frame.groupby("sector"):
        variance = float(group["cycle"].var())
        if variance < 1e-9 or len(group) < 3:
            betas[str(sector)] = 0.0
            continue
        covariance = float(
            ((group["cycle"] - group["cycle"].mean())
             * (group["pd"] - group["pd"].mean())).mean()
        )
        betas[str(sector)] = covariance / variance
    _BETA_CACHE = betas
    return betas


def _book_with_origination(source: DuckDBSource, period: str) -> pd.DataFrame:
    """One quarter of the book, with the origination PD alongside it.

    The PD a facility was written at lives in the IFRS 9 staging table rather
    than in the facility snapshot, and it is what the significant-increase test
    is measured against — so a signal that ignores it is ignoring the rule it is
    trying to anticipate. Where the staging table is not published the column is
    simply absent and the factor that needs it carries no information; it is
    never filled in with a guess.
    """
    book = source.fetch(FACILITY, context=AnalysisContext(period=period),
                        period=period, fields=list(REQUIRED_FIELDS))
    if STAGING not in source.datasets():
        return book
    try:
        staging = source.fetch(
            STAGING, context=AnalysisContext(period=period), period=period,
            fields=["account_id", "pd_at_origination_pct"],
        )
    except Exception:  # pragma: no cover - a period the staging table lacks
        return book
    return book.merge(staging, on="account_id", how="left")


@dataclass
class Panel:
    """The fitting table: factors at t, outcome at t+1."""

    factors: pd.DataFrame
    outcome: pd.Series
    periods: pd.Series
    frame: pd.DataFrame

    def slice_periods(self, periods: set[str]) -> Panel:
        mask = self.periods.isin(periods)
        return Panel(
            factors=self.factors[mask].reset_index(drop=True),
            outcome=self.outcome[mask].reset_index(drop=True),
            periods=self.periods[mask].reset_index(drop=True),
            frame=self.frame[mask].reset_index(drop=True),
        )

    def __len__(self) -> int:
        return len(self.outcome)


def build_panel(definition: TargetDef, *, source: DuckDBSource | None = None) -> Panel:
    """Factors as observed at each quarter end, with next quarter's outcome.

    Only facilities eligible for the transition are included — scoring a Stage 2
    facility for the chance of moving from Stage 1 would be meaningless, and
    including it would dilute the base rate with rows that could never be events.
    """
    source = source or DuckDBSource()
    periods = source.periods(FACILITY)
    if len(periods) < 3:
        raise EarlyWarningError(
            "The Forward Risk Signal needs at least three reporting periods: "
            "two to fit on and one to test against."
        )

    factor_blocks, outcome_blocks, period_blocks, frame_blocks = [], [], [], []
    for now, later in zip(periods, periods[1:], strict=False):
        book = _book_with_origination(source, now)
        after = source.fetch(FACILITY, context=AnalysisContext(period=later),
                             period=later, fields=["account_id", "ifrs9_stage"])
        eligible = book[book["ifrs9_stage"] == definition.from_stage]
        if eligible.empty:
            continue

        next_stage = after.set_index("account_id")["ifrs9_stage"]
        aligned = eligible.set_index("account_id")
        # A facility that is not in the next quarter has no outcome — it was
        # repaid, sold or written off. Dropping it is right: labelling it "did
        # not migrate" would teach the model that disappearing is good news.
        common = aligned.index.intersection(next_stage.index)
        aligned = aligned.loc[common]
        if aligned.empty:
            continue

        outcome = (next_stage.loc[common] == definition.to_stage).astype(float)
        aligned = aligned.reset_index()
        factors = compute_factors(aligned, cycle_exposure_by_sector(source, now))

        factor_blocks.append(factors)
        outcome_blocks.append(outcome.reset_index(drop=True))
        period_blocks.append(pd.Series([now] * len(aligned)))
        frame_blocks.append(aligned)

    if not factor_blocks:
        raise EarlyWarningError(
            f"No facility in the book is eligible for {definition.label}."
        )

    return Panel(
        factors=pd.concat(factor_blocks, ignore_index=True),
        outcome=pd.concat(outcome_blocks, ignore_index=True),
        periods=pd.concat(period_blocks, ignore_index=True),
        frame=pd.concat(frame_blocks, ignore_index=True),
    )


# ================================================================ fit + test


@dataclass
class FitResult:
    specification: SignalSpecification
    backtest: bt.BacktestResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "specification": self.specification.to_dict(),
            "backtest": self.backtest.to_dict(),
        }


def fit_and_backtest(target_id: str, *, test_quarters: int = DEFAULT_TEST_QUARTERS,
                     source: DuckDBSource | None = None,
                     notes: str = "") -> FitResult:
    """Fit on the early quarters, test on the ones held back.

    The split is by TIME, never at random. A random split would let the model
    see facility A in Q1 2025 while being tested on facility A in Q2 2025, and
    the same borrower's persistence would then be measured as predictive skill.
    """
    definition = target(target_id)
    source = source or DuckDBSource()
    panel = build_panel(definition, source=source)

    ordered = sorted(set(panel.periods), key=lambda p: (int(p.split()[1]), int(p[1])))
    if len(ordered) <= test_quarters:
        raise EarlyWarningError(
            f"Only {len(ordered)} quarters have an outcome, which is not enough "
            f"to hold {test_quarters} back for testing."
        )
    fit_periods = set(ordered[:-test_quarters])
    test_periods = set(ordered[-test_quarters:])

    training = panel.slice_periods(fit_periods)
    testing = panel.slice_periods(test_periods)

    spec = fit_specification(
        training.factors, training.outcome,
        target_id=target_id,
        periods=tuple(ordered[:-test_quarters]),
        cycle_by_sector=_sector_betas(source),
        notes=notes,
    )

    predicted = probabilities(spec, testing.factors)
    observed = testing.outcome.to_numpy(dtype=float)
    by_period = []
    for period in sorted(test_periods, key=lambda p: (int(p.split()[1]), int(p[1]))):
        mask = (testing.periods == period).to_numpy()
        if mask.sum() < 10:
            continue
        rows = bt.deciles(predicted[mask], observed[mask])
        by_period.append(bt.PeriodResult(
            period=period,
            facilities=int(mask.sum()),
            events=int(observed[mask].sum()),
            auc=bt.auc(predicted[mask], observed[mask]),
            ks=bt.ks(predicted[mask], observed[mask]),
            top_decile_capture_pct=rows[0].cumulative_capture_pct if rows else 0.0,
        ))

    result = bt.BacktestResult(
        target_id=target_id,
        fitted_periods=ordered[:-test_quarters],
        tested_periods=ordered[-test_quarters:],
        facilities=len(testing),
        events=int(observed.sum()),
        base_rate_pct=100.0 * float(observed.mean()) if len(observed) else 0.0,
        auc=bt.auc(predicted, observed),
        ks=bt.ks(predicted, observed),
        deciles=bt.deciles(predicted, observed),
        calibration=bt.calibration(predicted, observed),
        by_period=by_period,
    )
    return FitResult(specification=spec, backtest=result)


# ================================================================== scoring


def score_book(spec: SignalSpecification, *, period: str | None = None,
               source: DuckDBSource | None = None,
               limit: int | None = None) -> dict[str, Any]:
    """Score the current book with one specification.

    Returns the full decomposition for each facility, so a screen can show why
    a facility scored what it scored without asking the model again.
    """
    definition = target(spec.target_id)
    source = source or DuckDBSource()
    period = period or source.periods(FACILITY)[-1]

    book = _book_with_origination(source, period)
    eligible = book[book["ifrs9_stage"] == definition.from_stage].reset_index(drop=True)
    if eligible.empty:
        return {
            "period": period,
            "target": definition.to_dict(),
            "facilities": 0,
            "scored": [],
            "bands": [],
            "message": f"No facility is in Stage {definition.from_stage} this period.",
        }

    factors = compute_factors(eligible, spec.cycle_by_sector and
                              cycle_exposure_by_sector(source, period))
    scored = score_frame(spec, eligible, factors)
    scored.sort(key=lambda s: -s.probability)

    bands: dict[str, dict[str, float]] = {}
    for facility in scored:
        entry = bands.setdefault(facility.band, {"facilities": 0, "ead": 0.0})
        entry["facilities"] += 1
        entry["ead"] += facility.ead

    return {
        "period": period,
        "target": definition.to_dict(),
        "facilities": len(scored),
        "total_ead": round(sum(s.ead for s in scored), 2),
        "scored": [s.to_dict() for s in (scored[:limit] if limit else scored)],
        "bands": [
            {"band": band, "facilities": int(v["facilities"]), "ead": round(v["ead"], 2)}
            for band, v in bands.items()
        ],
        "families": [f.to_dict() for f in FACTOR_FAMILIES],
        "factors": [f.to_dict() for f in FACTORS],
    }


# ================================================================ versioning


def _row_to_dict(row: Any) -> dict[str, Any]:
    validation = dict(row.validation or {})
    definition = target(row.target)
    return {
        "id": row.id,
        "target": row.target,
        "target_label": definition.label,
        "name": row.name,
        "version": row.version,
        "lifecycle": lc.effective_lifecycle(row.lifecycle, validation),
        "lifecycle_stored": row.lifecycle,
        "lifecycle_label": lc.label_for(row.lifecycle, validation),
        "display_name": lc.display_name(definition.label, row.lifecycle, validation),
        "notice": lc.notice_for(row.lifecycle, validation),
        "is_active": row.is_active,
        "change_note": row.change_note,
        "specification": dict(row.specification or {}),
        "validation": validation,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def save_version(result: FitResult, *, name: str = "", change_note: str = "",
                 user_id: int | None = None, activate: bool = True) -> dict[str, Any]:
    """Store a fitted specification as a new version.

    Never edits an existing one. A score quoted from version 3 must still be
    reproducible after version 4 exists, and the only way to guarantee that is
    for a fit to be append-only.
    """
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import EarlyWarningModel

    definition = target(result.specification.target_id)
    with get_session() as session:
        highest = session.execute(
            select(EarlyWarningModel.version)
            .where(EarlyWarningModel.target == definition.id)
            .order_by(EarlyWarningModel.version.desc())
        ).scalars().first()
        version = (highest or 0) + 1

        if activate:
            for other in session.execute(
                select(EarlyWarningModel).where(
                    EarlyWarningModel.target == definition.id,
                    EarlyWarningModel.is_active.is_(True),
                )
            ).scalars().all():
                other.is_active = False

        row = EarlyWarningModel(
            target=definition.id,
            name=name or f"{definition.label} v{version}",
            version=version,
            lifecycle=lc.PROTOTYPE,
            is_active=activate,
            specification={
                **result.specification.to_dict(),
                "backtest": result.backtest.to_dict(),
            },
            change_note=change_note,
            validation={},
            created_by=user_id,
        )
        session.add(row)
        session.flush()
        session.commit()
        return _row_to_dict(row)


def versions(target_id: str | None = None) -> list[dict[str, Any]]:
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import EarlyWarningModel

    with get_session() as session:
        query = select(EarlyWarningModel).order_by(
            EarlyWarningModel.target, EarlyWarningModel.version.desc()
        )
        if target_id:
            query = query.where(EarlyWarningModel.target == target_id)
        return [_row_to_dict(r) for r in session.execute(query).scalars().all()]


def get_version(model_id: int) -> dict[str, Any]:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import EarlyWarningModel

    with get_session() as session:
        row = session.get(EarlyWarningModel, model_id)
        if row is None:
            raise ModelNotFound(f"Early warning model {model_id} does not exist.")
        return _row_to_dict(row)


def active_specification(target_id: str) -> SignalSpecification | None:
    """The specification currently in use for a target, if one is stored."""
    if not settings.has_database:
        return None
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import EarlyWarningModel

    with get_session() as session:
        row = session.execute(
            select(EarlyWarningModel).where(
                EarlyWarningModel.target == target_id,
                EarlyWarningModel.is_active.is_(True),
            )
        ).scalars().first()
        if row is None:
            return None
        return SignalSpecification.from_dict(dict(row.specification or {}))


def activate(model_id: int, *, user_id: int | None = None) -> dict[str, Any]:
    """Make one version the one in use. A recorded act, not a silent switch."""
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import EarlyWarningModel

    with get_session() as session:
        row = session.get(EarlyWarningModel, model_id)
        if row is None:
            raise ModelNotFound(f"Early warning model {model_id} does not exist.")
        for other in session.execute(
            select(EarlyWarningModel).where(
                EarlyWarningModel.target == row.target,
                EarlyWarningModel.is_active.is_(True),
            )
        ).scalars().all():
            other.is_active = False
        row.is_active = True
        session.commit()
        return _row_to_dict(row)


# ============================================================ impact analysis


def compare_versions(model_id_a: int, model_id_b: int, *,
                     period: str | None = None,
                     source: DuckDBSource | None = None) -> dict[str, Any]:
    """What changing the model would actually do to the book.

    Not a comparison of coefficients — a comparison of consequences. Both
    specifications are run over the same facilities in the same period, and the
    answer is how many facilities change band, which direction they move, and
    how much exposure moves with them. "The AUC improved by 0.02" is not an
    answer a credit committee can act on; "eleven facilities carrying 340
    million move into High" is.
    """
    a, b = get_version(model_id_a), get_version(model_id_b)
    if a["target"] != b["target"]:
        raise EarlyWarningError(
            "These two models predict different things "
            f"({a['target_label']} and {b['target_label']}), so comparing their "
            "scores would compare nothing."
        )

    spec_a = SignalSpecification.from_dict(a["specification"])
    spec_b = SignalSpecification.from_dict(b["specification"])
    source = source or DuckDBSource()
    period = period or source.periods(FACILITY)[-1]

    scored_a = {s["account_id"]: s for s in score_book(spec_a, period=period,
                                                       source=source)["scored"]}
    scored_b = {s["account_id"]: s for s in score_book(spec_b, period=period,
                                                       source=source)["scored"]}
    shared = sorted(set(scored_a) & set(scored_b))

    moved_up, moved_down, unchanged = [], [], 0
    ead_up = ead_down = 0.0
    for account in shared:
        before, after = scored_a[account], scored_b[account]
        if before["band"] == after["band"]:
            unchanged += 1
            continue
        entry = {
            "account_id": account,
            "borrower_name": after["borrower_name"],
            "sector": after["sector"],
            "ead": after["ead"],
            "from_band": before["band"],
            "to_band": after["band"],
            "from_pct": before["probability_pct"],
            "to_pct": after["probability_pct"],
        }
        if after["probability_pct"] > before["probability_pct"]:
            moved_up.append(entry)
            ead_up += after["ead"]
        else:
            moved_down.append(entry)
            ead_down += after["ead"]

    moved_up.sort(key=lambda e: -e["ead"])
    moved_down.sort(key=lambda e: -e["ead"])

    return {
        "period": period,
        "target": target(a["target"]).to_dict(),
        "from_model": {"id": a["id"], "name": a["name"], "version": a["version"]},
        "to_model": {"id": b["id"], "name": b["name"], "version": b["version"]},
        "facilities_compared": len(shared),
        "unchanged": unchanged,
        "moved_to_worse_band": len(moved_up),
        "moved_to_better_band": len(moved_down),
        "ead_to_worse_band": round(ead_up, 2),
        "ead_to_better_band": round(ead_down, 2),
        "biggest_increases": moved_up[:20],
        "biggest_decreases": moved_down[:20],
        "weight_changes": _weight_changes(spec_a, spec_b),
        "summary": (
            f"Against {len(shared):,} facilities in {period}, moving from "
            f"{a['name']} to {b['name']} would put {len(moved_up)} facilities "
            f"carrying {ead_up:,.0f} USD mn into a worse band and take "
            f"{len(moved_down)} carrying {ead_down:,.0f} USD mn into a better "
            f"one. {unchanged:,} would not move."
        ),
    }


def _weight_changes(a: SignalSpecification, b: SignalSpecification) -> list[dict[str, Any]]:
    rows = []
    for definition in FACTORS:
        wa, wb = a.weight_for(definition.id), b.weight_for(definition.id)
        before = wa.weight if wa else 0.0
        after = wb.weight if wb else 0.0
        rows.append({
            "factor_id": definition.id,
            "label": definition.label,
            "family": definition.family,
            "before": round(before, 5),
            "after": round(after, 5),
            "change": round(after - before, 5),
        })
    rows.sort(key=lambda r: -abs(r["change"]))
    return rows


def overview(*, source: DuckDBSource | None = None) -> dict[str, Any]:
    """What the Early Warning module has, for the screen that introduces it."""
    stored = versions()
    by_target = {t.id: [] for t in TARGETS}
    for row in stored:
        by_target.setdefault(row["target"], []).append(row)

    return {
        "capability": lc.CAPABILITY_LABEL,
        "notice": lc.CAPABILITY_NOTICE,
        "targets": [
            {
                **definition.to_dict(),
                "versions": len(by_target.get(definition.id, [])),
                "active": next(
                    (r for r in by_target.get(definition.id, []) if r["is_active"]),
                    None,
                ),
            }
            for definition in TARGETS
        ],
        "families": [f.to_dict() for f in FACTOR_FAMILIES],
        "factors": [f.to_dict() for f in FACTORS],
        "methodology": "docs/EARLY_WARNING_METHODOLOGY.md",
    }


__all__ = [
    "EarlyWarningError",
    "FitResult",
    "ModelNotFound",
    "Panel",
    "StorageUnavailable",
    "activate",
    "active_specification",
    "build_panel",
    "compare_versions",
    "cycle_exposure_by_sector",
    "fit_and_backtest",
    "get_version",
    "overview",
    "save_version",
    "score_book",
    "versions",
]
