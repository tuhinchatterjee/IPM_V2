"""Running a validation test, and refusing to when it should not run. §8.

The runner reads a `Test` definition and a `Model`, loads the population,
calls the governed kernels in `backend/scorecard/metrics.py`, and returns a
`Result`. It computes nothing itself — that is the whole design. A second
place that knows how to compute an AUC is a second AUC.

The order of the refusals is the interesting part
---------------------------------------------------
Five gates, and they run in this order because each one makes the next
meaningful:

1. **Authorisation.** Is this domain one of the three? Asked first so that a
   caller with no business here learns nothing about what exists.
2. **Applicability.** Does the model support this test at all? A rank-order
   scorecard has no calibration, and running one to find out is wasted work
   and a confusing error.
3. **Availability.** Is the data there? A field that is not populated in this
   deployment is a data finding, not a model finding.
4. **Maturity.** Has the outcome happened? This is the gate that matters most
   and the one most easily skipped, because skipping it produces a number
   rather than an error, and the number is 0.0%.
5. **Sufficiency.** Is there enough of it? A Gini on forty defaults is not
   wrong, it is unreportable, and the difference between those two is a
   sentence a validator can defend.

Reversing any pair produces a worse product. Checking sufficiency before
maturity, for example, reports "insufficient sample" for a cohort that has
plenty of rows and simply has not matured — true about the events, wrong
about the reason, and it sends somebody to widen a window that will not help.

The verdict is arithmetic
---------------------------
`Limit.verdict` decides PASS, WARNING or FAIL by comparing a number to a
governed threshold. No model is asked. A test with no configured limit comes
back measured with `limit=None`, which the UI renders as "no approved limit"
— a third thing, distinct from a pass and from a failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pandas as pd

from backend.scorecard import binning, domains
from backend.scorecard import metrics as kernels
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import states

logger = logging.getLogger(__name__)

RUNNER_VERSION = "1.0.0"


class PopulationError(RuntimeError):
    """The population could not be loaded."""


# ------------------------------------------------------------- the population


@dataclass(frozen=True)
class Population:
    """The rows a test will run over, and what they are."""

    frame: pd.DataFrame
    dataset: str
    periods: tuple[str, ...]
    matured_periods: tuple[str, ...]
    immature_periods: tuple[str, ...]
    #: When the earliest still-open window closes. What a NOT_MATURED result
    #: tells the user instead of only saying no.
    closes: str = ""

    @property
    def rows(self) -> int:
        return len(self.frame)

    @property
    def fully_matured(self) -> bool:
        return not self.immature_periods


def _analytics_root() -> Any:
    from pathlib import Path

    from backend.config import settings

    return Path(settings.analytics_dir)


def available_periods(model: model_registry.Model, *,
                      dataset: str = "") -> tuple[str, ...]:
    """Every period the dataset has, chronologically.

    Sorted by the partition key parsed into (year, month) rather than
    lexically. "2024-9" sorts after "2024-10" as a string, and a latest-period
    resolver that gets this wrong picks a period nine months stale without
    reporting anything unusual.
    """
    root = _analytics_root() / (dataset or model.dataset)
    if not root.exists():
        return ()
    found = []
    for entry in root.iterdir():
        if entry.is_dir() and "=" in entry.name:
            found.append(entry.name.split("=", 1)[1])

    def key(period: str) -> tuple[int, int]:
        parts = period.split("-")
        try:
            return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        except (ValueError, IndexError):
            return (0, 0)

    return tuple(sorted(found, key=key))


def matured_periods(model: model_registry.Model) -> tuple[str, ...]:
    """The periods with a realised outcome, chronologically.

    Read from the data rather than recomputed from a calendar: the maturity
    flag is written by the builder that knows the horizon, and a second
    opinion computed here could disagree with the rows themselves.
    """
    every = available_periods(model)
    if not every:
        return ()
    out = []
    for period in every:
        frame = _read(model, model.dataset, (period,), columns=[
            model.matured_column])
        if len(frame) and bool(frame[model.matured_column].fillna(False).all()):
            out.append(period)
    return tuple(out)


def latest_matured(model: model_registry.Model) -> str:
    ready = matured_periods(model)
    return ready[-1] if ready else ""


@lru_cache(maxsize=256)
def _read_partition(where: str, mtime_ns: int,
                    columns: tuple[str, ...]) -> pd.DataFrame:
    """One partition, cached on its own modification time.

    A stability trend reads the same thirty-six partitions once per
    characteristic, which without this is thirty-six disk reads multiplied by
    eight variables for one test. The mtime is part of the key so a rebuilt
    dataset invalidates the entry rather than serving the previous universe.
    """
    return pd.read_parquet(where, columns=list(columns) or None)


def _partition(where: str, mtime_ns: int,
               columns: tuple[str, ...]) -> pd.DataFrame:
    """The cached partition, copied.

    The copy is not defensive fussiness. Handlers assign columns onto the
    frames they are given, and a cached frame that one handler mutated is a
    later handler computing a metric over somebody else's working column.
    """
    return _read_partition(where, mtime_ns, columns).copy()


def _read(model: model_registry.Model, dataset: str,
          periods: tuple[str, ...], *,
          columns: list[str] | None = None) -> pd.DataFrame:
    """Read whole partitions. Never a preview, never a head().

    §37 is explicit that a chart may be sampled and a metric may not. The
    simplest way to keep that true is for the loader to have no row limit at
    all: there is no argument to pass and therefore no call site that can
    quietly pass one.
    """
    root = _analytics_root() / dataset
    frames = []
    for period in periods:
        where = root / f"{model.period_field}={period}"
        if not where.exists():
            continue
        try:
            frames.append(_partition(str(where), where.stat().st_mtime_ns,
                                     tuple(columns) if columns else ()))
        except Exception as e:  # noqa: BLE001 - surfaced as a population error
            raise PopulationError(
                f"{dataset} {period} could not be read: {e}") from e
    if not frames:
        raise PopulationError(
            f"{dataset} has no data for {', '.join(periods) or '(no period)'}.")
    return pd.concat(frames, ignore_index=True)


def population(model: model_registry.Model, *, periods: tuple[str, ...] = (),
               dataset: str = "", segment: str = "",
               segment_field: str = "",
               matured_only: bool = True) -> Population:
    """Load the rows for these periods, whole.

    With an empty `periods`, the default window depends on what the test
    needs. A test that compares a prediction against a realised outcome gets
    the matured periods and cannot silently include a cohort whose window is
    still open. A test that reads only the input distribution — PSI, CSI,
    band occupancy — gets every period the dataset has, including the newest.

    That distinction is the point of the parameter. Restricting a stability
    test to matured data measures the drift of a book as it stood a year ago,
    which is the one window in which drift is guaranteed to be old news:
    population movement is visible before its consequences are, and that
    early sight is the entire value of the test. On this build the difference
    is not academic — the same characteristic reads 0.01 on the matured
    window and 0.49 on the current one.
    """
    domains.require_validation_domain(model.domain)
    if periods:
        wanted = periods
    elif matured_only:
        wanted = matured_periods(model)
    else:
        wanted = available_periods(model)
    if not wanted:
        raise PopulationError(
            f"{model.name} has no periods with a realised outcome."
            if matured_only else f"{model.name} has no data.")

    frame = _read(model, dataset or model.dataset, wanted)
    if segment and segment_field:
        if segment_field not in frame.columns:
            raise PopulationError(
                f"{segment_field} is not a field of {model.dataset}.")
        frame = frame[frame[segment_field] == segment]

    ready = tuple(p for p in wanted if p in matured_periods(model))
    open_windows = tuple(p for p in wanted if p not in ready)
    closes = ""
    if open_windows and "performance_window_end" in frame.columns:
        ends = frame.loc[frame[model.matured_column] == False,  # noqa: E712
                         "performance_window_end"]
        if len(ends):
            closes = str(ends.min())

    return Population(
        frame=frame, dataset=dataset or model.dataset, periods=wanted,
        matured_periods=ready, immature_periods=open_windows, closes=closes)


# ------------------------------------------------------------------ the gates


def _refuse(test: test_registry.Test, model: model_registry.Model,
            pool: Population | None, **kw: Any) -> states.Result | None:
    """The five gates, in the order that makes each one meaningful.

    Returns a Result when the test must not run, and None when it may.
    """
    common = dict(model_id=model.model_id, model_version=model.version,
                  dataset=model.dataset, method=test.method,
                  calculation_version=kernels.METRICS_VERSION,
                  score_direction=model.score_direction,
                  limitations=test.limitations, **kw)

    # 1. authorisation
    if not domains.validation_domain_allowed(model.domain):
        return states.not_authorised(test.test_id, **common)

    # 2. applicability
    missing = test.missing_for(model.capabilities())
    if missing:
        return states.not_applicable(
            test.test_id,
            why=(f"{model.name} does not support this test: it needs "
                 f"{' and '.join(missing)}."),
            **common)

    if pool is None:
        return None

    # 3. availability
    for column in (model.score_column, model.outcome_column):
        if (test_registry.NEEDS_OUTCOME in test.requires
                and column and column not in pool.frame.columns):
            return states.unavailable(test.test_id, what=column, **common)

    # 4. maturity — before sufficiency, deliberately
    if test_registry.NEEDS_OUTCOME in test.requires and not pool.fully_matured:
        return states.not_matured(
            test.test_id, period=", ".join(pool.immature_periods),
            closes=pool.closes or "the window close month recorded on the row",
            **{k: v for k, v in common.items() if k != "period"})

    # 5. sufficiency
    events = 0
    if model.outcome_column in pool.frame.columns:
        events = int(pool.frame[model.outcome_column].fillna(0).sum())
    if (test.minimum_observations and pool.rows < test.minimum_observations) \
            or (test.minimum_events and events < test.minimum_events):
        return states.insufficient(
            test.test_id, observations=pool.rows, events=events,
            minimum_observations=test.minimum_observations,
            minimum_events=test.minimum_events,
            **{k: v for k, v in common.items()
               if k not in ("observations", "events")})
    return None


def _verdict(model: model_registry.Model, test_id: str,
             value: float) -> tuple[str, float | None, str]:
    """PASS, WARNING or FAIL, plus the limit and where it came from.

    A test with no configured limit is measured and uncompared — a third
    thing, and the UI says NO APPROVED LIMIT rather than colouring it green.
    """
    limit = model.limit_for(test_id)
    if limit is None:
        return states.PASS, None, ""
    return limit.verdict(value), limit.value, limit.source


# --------------------------------------------------------------- the handlers

#: One handler per test that has a real calculation behind it. A test in the
#: registry with no handler is honestly UNAVAILABLE rather than quietly
#: absent — see `run`, which says so in as many words.
Handler = Any
HANDLERS: dict[str, Handler] = {}


def handles(*test_ids: str) -> Any:
    def wrap(fn: Handler) -> Handler:
        for test_id in test_ids:
            HANDLERS[test_id] = fn
        return fn
    return wrap


@handles("DISC-AUC", "DISC-GINI", "DISC-KS")
def _discrimination(test: test_registry.Test, model: model_registry.Model,
                    pool: Population, **kw: Any) -> states.Result:
    made = kernels.discrimination(
        pool.frame, score=model.score_column, target=model.outcome_column,
        score_direction=model.score_direction, curves=True)
    value = {"DISC-AUC": made.auc, "DISC-GINI": made.gini,
             "DISC-KS": made.ks}[test.test_id]
    state, limit, source = _verdict(model, test.test_id, value)
    low, high = made.auc_confidence
    return states.measured(
        test.test_id, state, value, limit=limit, limit_source=source,
        detail=(f"{test.name} is {value:.4f} on {made.observations:,} "
                f"observations carrying {made.events:,} defaults. "
                f"{made.evidence}."),
        observations=made.observations, matured_observations=made.observations,
        events=made.events, model_id=model.model_id,
        model_version=model.version, dataset=pool.dataset,
        period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        score_direction=model.score_direction, limitations=test.limitations,
        chart={"kind": test.charts[0] if test.charts else "",
               "roc": made.roc, "ks_curve": made.ks_curve,
               "ks_at": made.ks_at},
        lineage={"auc_confidence_95": [low, high],
                 "score_column": model.score_column,
                 "outcome_column": model.outcome_column},
        **kw)


@handles("DISC-LIFT")
def _lift(test: test_registry.Test, model: model_registry.Model,
          pool: Population, **kw: Any) -> states.Result:
    rows = kernels.gains(pool.frame, score=model.score_column,
                         target=model.outcome_column,
                         score_direction=model.score_direction)
    top = float(rows[0].get("lift", 0.0)) if rows else 0.0
    state, limit, source = _verdict(model, test.test_id, top)
    return states.measured(
        test.test_id, state, top, limit=limit, limit_source=source,
        detail=(f"The worst decile carries {top:.2f}x the portfolio default "
                f"rate."),
        table=rows, chart={"kind": test_registry.CHART_LIFT, "deciles": rows},
        observations=len(pool.frame), model_id=model.model_id,
        model_version=model.version, dataset=pool.dataset,
        period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)


@handles("DISC-RANK", "SEG-RANK")
def _rank_ordering(test: test_registry.Test, model: model_registry.Model,
                   pool: Population, **kw: Any) -> states.Result:
    rows = _band_table(pool.frame, model)
    rates = [r["observed_rate"] for r in rows if r["observations"] >= 30]
    monotonic = rates == sorted(rates, reverse=True)
    inversions = sum(1 for a, b in zip(rates, rates[1:], strict=False) if b > a)
    state = states.PASS if monotonic else states.FAIL
    return states.measured(
        test.test_id, state, float(inversions),
        detail=("The observed default rate falls monotonically across every "
                "score band." if monotonic else
                f"{inversions} band(s) invert: the default rate rises as the "
                "score rises, so the score is not ranking risk here."),
        table=rows,
        chart={"kind": test_registry.CHART_BAND_RATE, "bands": rows},
        observations=len(pool.frame), model_id=model.model_id,
        model_version=model.version, dataset=pool.dataset,
        period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)


@handles("CAL-OE", "CAL-BRIER", "CAL-SLOPE", "CAL-BAND")
def _calibration(test: test_registry.Test, model: model_registry.Model,
                 pool: Population, **kw: Any) -> states.Result:
    made = kernels.calibration(
        pool.frame, pd_column=model.pd_column, target=model.outcome_column,
        score=model.score_column, score_direction=model.score_direction)
    if test.test_id == "CAL-OE":
        value = (made.observed_rate / made.predicted_rate
                 if made.predicted_rate else float("inf"))
        said = (f"Observed {made.observed_rate:.3%} against predicted "
                f"{made.predicted_rate:.3%}, an O/E of {value:.3f}.")
    elif test.test_id == "CAL-BRIER":
        value, said = made.brier, f"Brier score {made.brier:.5f}."
    elif test.test_id == "CAL-SLOPE":
        if made.slope is None:
            return states.unavailable(
                test.test_id, what="a fitted calibration slope",
                model_id=model.model_id, model_version=model.version,
                dataset=pool.dataset, period=_period_label(pool),
                method=test.method, **kw)
        value = made.slope
        said = (f"Calibration slope {made.slope:.4f}, intercept "
                f"{made.calibration_in_the_large:+.4f}. A slope near 1 with a "
                "non-zero intercept is a recalibration; a slope far from 1 is "
                "not.")
    else:
        value = made.bucket_rmse
        said = (f"Band-level RMSE {made.bucket_rmse:.5f} across "
                f"{len(made.buckets)} score bands.")
    state, limit, source = _verdict(model, test.test_id, value)
    return states.measured(
        test.test_id, state, value, limit=limit, limit_source=source,
        detail=f"{said} {made.evidence}.",
        comparison_value=made.predicted_rate,
        observations=made.observations, matured_observations=made.observations,
        events=made.events, table=made.buckets,
        chart={"kind": test_registry.CHART_CALIBRATION,
               "buckets": made.buckets},
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations,
        lineage={"mape_status": made.mape_status,
                 "pd_column": model.pd_column}, **kw)


def _stability_series(model: model_registry.Model, reference: pd.DataFrame,
                      index_of: Any) -> list[dict[str, Any]]:
    """One stability index per period, oldest first.

    Each period is compared against the same development reference, so the
    series answers "is it still moving?" rather than "did it move at some
    point in the last three years?" — the second question has the same answer
    for a book that settled two years ago and one that is drifting now.
    """
    series: list[dict[str, Any]] = []
    for period in available_periods(model):
        try:
            pool = population(model, periods=(period,), matured_only=False)
        except PopulationError:
            continue
        if pool.rows == 0:
            continue
        try:
            value = float(index_of(pool.frame))
        except kernels.MetricError:
            continue
        series.append({"period": period, "index": round(value, 6),
                       "observations": pool.rows})
    return series


@handles("STAB-PSI")
def _score_psi(test: test_registry.Test, model: model_registry.Model,
               pool: Population, **kw: Any) -> states.Result:
    """Score PSI, on the newest period, with the whole series behind it.

    Two decisions here are worth stating, because both change the answer.

    The headline compares the *latest* period against development, not the
    pooled window. PSI is a point-in-time measure: pooling three years of
    monthly cohorts averages a drift that grew over those years against the
    months in which it had not yet happened, and reports the average as
    though it were the position today. On this model the pooled figure and
    the current figure differ by a factor of five.

    The table is the whole series, one row per period, because a single index
    cannot distinguish a book that moved once from a book that is still
    moving, and the second is the one that needs a decision.
    """
    reference = population(model, periods=available_periods(
        model, dataset=model.reference_dataset),
        dataset=model.reference_dataset)
    series = _stability_series(
        model, reference.frame,
        lambda frame: kernels.psi(reference.frame, frame,
                                  score=model.score_column).index)
    current = population(model, periods=(pool.periods[-1],),
                         matured_only=False)
    made = kernels.psi(reference.frame, current.frame,
                       score=model.score_column)
    state, limit, source = _verdict(model, test.test_id, made.index)
    return states.measured(
        test.test_id, state, made.index, limit=limit, limit_source=source,
        detail=(f"Score PSI {made.index:.4f} for {pool.periods[-1]} against "
                f"the development population, across {len(series)} periods "
                f"({series[0]['index']:.4f} at the start of the series). A "
                "population shift is not a performance deterioration: it says "
                "the book changed, not that the model failed."),
        observations=made.current_rows, table=series,
        chart={"kind": test_registry.CHART_PSI_TREND, "series": series,
               "bins": made.bins, "limit": limit},
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=pool.periods[-1],
        reference_period=_period_label(reference), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)


@handles("STAB-CSI")
def _variable_csi(test: test_registry.Test, model: model_registry.Model,
                  pool: Population, **kw: Any) -> states.Result:
    """CSI per characteristic, on the newest period. See `_score_psi`.

    The headline is the worst characteristic rather than an average, because
    an average over eight stable variables and one that has moved reports the
    book as stable, and the one that moved is the finding.
    """
    reference = population(model, periods=available_periods(
        model, dataset=model.reference_dataset),
        dataset=model.reference_dataset)
    current = population(model, periods=(pool.periods[-1],),
                         matured_only=False)
    rows: list[dict[str, Any]] = []
    for name in model.binned_variables:
        try:
            made = kernels.csi(reference.frame, current.frame, variable=name)
        except kernels.MetricError:
            continue
        series = _stability_series(
            model, reference.frame,
            lambda frame, _n=name: kernels.csi(
                reference.frame, frame, variable=_n).index)
        rows.append({"variable": name, "csi": round(made.index, 6),
                     "bins": made.bins, "series": series})
    if not rows:
        return states.unavailable(
            test.test_id, what="the approved bin columns",
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, period=_period_label(pool),
            method=test.method, **kw)
    rows.sort(key=lambda r: r["csi"], reverse=True)
    worst = rows[0]
    state, limit, source = _verdict(model, test.test_id, worst["csi"])
    breached = [r["variable"] for r in rows
                if limit is not None and r["csi"] > limit]
    return states.measured(
        test.test_id, state, worst["csi"], limit=limit, limit_source=source,
        detail=(f"{worst['variable']} has moved most, at {worst['csi']:.4f} "
                f"for {pool.periods[-1]}. "
                + (f"{len(breached)} of {len(rows)} characteristics are "
                   f"outside the limit: {', '.join(breached)}."
                   if breached else
                   f"No characteristic is outside the limit; {len(rows)} were "
                   "measured.")),
        table=[{"variable": r["variable"], "csi": r["csi"]} for r in rows],
        chart={"kind": test_registry.CHART_RANKING, "variables": rows,
               "limit": limit},
        observations=len(current.frame), model_id=model.model_id,
        model_version=model.version, dataset=pool.dataset,
        period=pool.periods[-1], reference_period=_period_label(reference),
        method=test.method, calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations,
        lineage={"contributors": breached}, **kw)


#: Below this, a development-time information value is not a signal, so the
#: ratio of "now" to "then" is a ratio of two pieces of noise. It matches the
#: UNPREDICTIVE boundary in `binning.VariableBinning.strength`.
IV_FLOOR = 0.02


@handles("VAR-IV")
def _variable_information(test: test_registry.Test,
                          model: model_registry.Model,
                          pool: Population, **kw: Any) -> states.Result:
    """Information value now, against the information value at approval.

    The single number a validator needs here is not the IV — it is the change
    in the IV. A characteristic that carried 0.31 at development and carries
    0.31 today is working; one that carried 0.31 and carries 0.04 has stopped
    working, and reporting only the 0.04 leaves the reader to guess whether
    it was ever any good. Both are shown, and the verdict is taken on the
    retention ratio rather than on the level, because a level threshold marks
    a legitimately weak-but-stable characteristic as a finding.
    """
    try:
        spec = model.approved_spec()
    except Exception as e:  # noqa: BLE001 - reported as a refusal
        return states.unavailable(
            test.test_id, what=f"the approved binning specification ({e})",
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, period=_period_label(pool),
            method=test.method, **kw)

    rows: list[dict[str, Any]] = []
    for name in model.binned_variables:
        approved = spec.variables.get(name) if hasattr(spec, "variables") \
            else None
        try:
            observed = binning.observed_information_value(
                pool.frame, variable=name, target=model.outcome_column)
        except binning.BinningError:
            continue
        at_approval = (float(approved.information_value)
                       if approved is not None else None)
        now = float(observed["information_value"])
        retained = (round(now / at_approval, 6)
                    if at_approval else None)
        rows.append({
            "variable": name,
            "information_value": round(now, 6),
            "information_value_at_approval": (round(at_approval, 6)
                                              if at_approval else None),
            "retained": retained,
            "strength": (approved.strength if approved is not None else ""),
            "bins": observed["bins"],
        })
    if not rows:
        return states.unavailable(
            test.test_id,
            what=("the approved bin columns, or a matured outcome to measure "
                  "information value against"),
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, period=_period_label(pool),
            method=test.method, **kw)

    # Retention is only meaningful where there was information to retain.
    # A characteristic that carried 0.017 at approval and carries 0.010 now
    # has "lost 41%" of an amount that was never a signal, and ranking on
    # that ratio puts the noisiest variable at the top of the finding every
    # time. The floor is the conventional UNPREDICTIVE boundary that
    # `binning.VariableBinning.strength` already uses, so the two agree.
    material = [r for r in rows
                if (r["information_value_at_approval"] or 0.0) >= IV_FLOOR]
    comparable = [r for r in material if r["retained"] is not None]
    uncompared = [r["variable"] for r in rows if r not in material]
    rows.sort(key=lambda r: r["information_value"], reverse=True)
    worst = (min(comparable, key=lambda r: r["retained"])
             if comparable else None)
    headline = (worst["retained"] if worst is not None
                else rows[0]["information_value"])
    state, limit, source = _verdict(model, test.test_id, headline)
    if worst is not None:
        detail = (
            f"{worst['variable']} retains {worst['retained']:.2f} of the "
            f"information value it carried at approval "
            f"({worst['information_value']:.4f} now against "
            f"{worst['information_value_at_approval']:.4f} then). "
            f"{len(comparable)} of {len(rows)} characteristics carried "
            f"enough information value at approval ({IV_FLOOR}) for decay to "
            f"mean anything; the strongest today is {rows[0]['variable']} at "
            f"{rows[0]['information_value']:.4f}."
            + (f" Not compared, because they were already below that floor "
               f"when the model was approved: {', '.join(uncompared)}."
               if uncompared else ""))
    else:
        detail = (
            f"{rows[0]['variable']} carries the most information value "
            f"today, at {rows[0]['information_value']:.4f}. The approved "
            "specification records no development-time value to compare "
            "against, so decay cannot be measured — only the level.")
    return states.measured(
        test.test_id, state, headline, limit=limit, limit_source=source,
        detail=detail,
        table=[{k: v for k, v in r.items() if k != "bins"} for r in rows],
        chart={"kind": test_registry.CHART_RANKING, "variables": rows},
        observations=len(pool.frame), model_id=model.model_id,
        model_version=model.version, dataset=pool.dataset,
        period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations,
        lineage={"comparison": "observed against approved",
                 "specification": getattr(spec, "spec_version", ""),
                 "information_value_floor": IV_FLOOR,
                 "not_compared": uncompared}, **kw)


@handles("VAR-GINI")
def _variable_power(test: test_registry.Test, model: model_registry.Model,
                    pool: Population, **kw: Any) -> states.Result:
    key = "gini"
    rows: list[dict[str, Any]] = []
    for name in model.binned_variables:
        try:
            made = kernels.variable_discrimination(
                pool.frame, variable=name, target=model.outcome_column)
        except kernels.MetricError:
            continue
        if made.get(key) is None:
            continue
        rows.append({"variable": name, key: round(float(made[key]), 6)})
    if not rows:
        return states.unavailable(
            test.test_id, what="binned variables with a measurable outcome",
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, period=_period_label(pool),
            method=test.method, **kw)
    rows.sort(key=lambda r: r[key], reverse=True)
    best = rows[0]
    state, limit, source = _verdict(model, test.test_id, best[key])
    return states.measured(
        test.test_id, state, best[key], limit=limit, limit_source=source,
        detail=(f"{best['variable']} carries the most, at {best[key]:.4f}. "
                f"{len(rows)} characteristics were measured; the weakest is "
                f"{rows[-1]['variable']} at {rows[-1][key]:.4f}."),
        table=rows, chart={"kind": test_registry.CHART_RANKING,
                           "variables": rows},
        observations=len(pool.frame), model_id=model.model_id,
        model_version=model.version, dataset=pool.dataset,
        period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)


@handles("SEG-DISCRIMINATION", "SEG-CALIBRATION")
def _by_segment(test: test_registry.Test, model: model_registry.Model,
                pool: Population, **kw: Any) -> states.Result:
    field = (kw.pop("segment_field", "") or
             (model.segmentation_fields[0] if model.segmentation_fields
              else ""))
    if not field or field not in pool.frame.columns:
        return states.unavailable(
            test.test_id, what=f"a segmentation field ({field or 'none'})",
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, period=_period_label(pool),
            method=test.method, **kw)

    rows: list[dict[str, Any]] = []
    for value, part in pool.frame.groupby(field, observed=True):
        events = int(part[model.outcome_column].fillna(0).sum())
        if events < test_registry.MIN_EVENTS:
            rows.append({"segment": str(value), "observations": len(part),
                         "events": events, "value": None,
                         "state": states.INSUFFICIENT_SAMPLE})
            continue
        try:
            if test.test_id == "SEG-DISCRIMINATION":
                got = kernels.discrimination(
                    part, score=model.score_column,
                    target=model.outcome_column,
                    score_direction=model.score_direction)
                value_out, key = got.auc, "auc"
            else:
                got = kernels.calibration(
                    part, pd_column=model.pd_column,
                    target=model.outcome_column)
                value_out = (got.observed_rate / got.predicted_rate
                             if got.predicted_rate else float("inf"))
                key = "observed_over_expected"
        except kernels.MetricError as e:
            rows.append({"segment": str(value), "observations": len(part),
                         "events": events, "value": None,
                         "state": states.CALCULATION_ERROR, "why": str(e)})
            continue
        compare_id = ("DISC-AUC" if test.test_id == "SEG-DISCRIMINATION"
                      else "CAL-OE")
        rows.append({"segment": str(value), "observations": len(part),
                     "events": events, key: round(value_out, 6),
                     "value": round(value_out, 6),
                     "state": _verdict(model, compare_id, value_out)[0]})

    adverse = [r for r in rows if r.get("state") in states.ADVERSE]
    worst = min((r for r in rows if r.get("value") is not None),
                key=lambda r: (0 if r["state"] == states.FAIL else 1),
                default=None)
    state = states.FAIL if any(
        r["state"] == states.FAIL for r in rows) else (
        states.WARNING if adverse else states.PASS)
    return states.measured(
        test.test_id, state, float(len(adverse)),
        detail=(f"{len(adverse)} of {len(rows)} segments are outside their "
                f"limit"
                + (f", worst {worst['segment']}." if worst and adverse
                   else ". The aggregate does not conceal a segment here.")),
        table=rows, chart={"kind": test_registry.CHART_RANKING,
                           "segments": rows},
        segment=field, observations=len(pool.frame),
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)


@handles("CC-DISCRIMINATION")
def _champion_challenger(test: test_registry.Test,
                         model: model_registry.Model,
                         pool: Population, **kw: Any) -> states.Result:
    champion = kernels.discrimination(
        pool.frame, score=model.score_column, target=model.outcome_column,
        score_direction=model.score_direction, curves=True, label="Champion")
    challenger = kernels.discrimination(
        pool.frame, score=model.challenger_score_column,
        target=model.outcome_column, score_direction=model.score_direction,
        curves=True, label="Challenger")
    lift = challenger.auc - champion.auc
    low, high = champion.auc_confidence
    material = abs(lift) > (high - low) / 2 if high == high else False
    return states.measured(
        test.test_id, states.PASS, lift,
        comparison_value=champion.auc,
        detail=(f"Challenger AUC {challenger.auc:.4f} against champion "
                f"{champion.auc:.4f}, a difference of {lift:+.4f}. "
                + ("Larger than the champion's own confidence interval, so "
                   "the difference is unlikely to be sampling noise."
                   if material else
                   "Within the champion's own confidence interval, so it may "
                   "be sampling noise.")
                + " A higher AUC is not on its own a reason to replace a "
                  "champion."),
        observations=champion.observations, events=champion.events,
        table=[{"model": "Champion", "auc": round(champion.auc, 6),
                "gini": round(champion.gini, 6), "ks": round(champion.ks, 6)},
               {"model": "Challenger", "auc": round(challenger.auc, 6),
                "gini": round(challenger.gini, 6),
                "ks": round(challenger.ks, 6)}],
        chart={"kind": test_registry.CHART_ROC,
               "champion": champion.roc, "challenger": challenger.roc},
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations,
        lineage={"champion_auc_confidence_95": [low, high],
                 "difference_exceeds_interval": bool(material)}, **kw)


@handles("DATA-MATURITY")
def _maturity(test: test_registry.Test, model: model_registry.Model,
              pool: Population, **kw: Any) -> states.Result:
    every = available_periods(model)
    ready = matured_periods(model)
    share = len(ready) / len(every) if every else 0.0
    return states.measured(
        test.test_id, states.PASS, share,
        detail=(f"{len(ready)} of {len(every)} periods have a realised "
                f"outcome. The remaining {len(every) - len(ready)} have not "
                "matured — which is not the same as having no defaults, and "
                "no outcome-based test may run on them."),
        table=[{"period": p, "matured": p in ready} for p in every],
        chart={"kind": test_registry.CHART_DISTRIBUTION,
               "matured": list(ready),
               "immature": [p for p in every if p not in ready]},
        observations=len(pool.frame), model_id=model.model_id,
        model_version=model.version, dataset=pool.dataset,
        period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)


@handles("DATA-EVENTS")
def _events(test: test_registry.Test, model: model_registry.Model,
            pool: Population, **kw: Any) -> states.Result:
    events = int(pool.frame[model.outcome_column].fillna(0).sum())
    rate = events / len(pool.frame) if len(pool.frame) else 0.0
    return states.measured(
        test.test_id, states.PASS, rate,
        detail=(f"{events:,} defaults in {len(pool.frame):,} matured "
                f"observations, a rate of {rate:.3%}. "
                f"{kernels.evidence_for(events, len(pool.frame))}."),
        observations=len(pool.frame), events=events,
        matured_observations=len(pool.frame),
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION, **kw)


@handles("USE-OVERRIDE-RATE", "USE-OVERRIDE-OUTCOME")
def _overrides(test: test_registry.Test, model: model_registry.Model,
               pool: Population, **kw: Any) -> states.Result:
    decisions = population(model, periods=pool.periods,
                           dataset=model.decisions_dataset)
    frame = decisions.frame
    if "override_flag" not in frame.columns:
        return states.unavailable(
            test.test_id, what="override_flag",
            model_id=model.model_id, model_version=model.version,
            dataset=model.decisions_dataset, period=_period_label(pool),
            method=test.method, **kw)

    if test.test_id == "USE-OVERRIDE-RATE":
        rate = float(frame["override_flag"].fillna(0).mean())
        rows = _band_override_table(frame, model)
        state, limit, source = _verdict(model, test.test_id, rate)
        return states.measured(
            test.test_id, state, rate, limit=limit, limit_source=source,
            detail=(f"{rate:.2%} of decisions departed from the score. A high "
                    "override rate is not automatically wrong — what matters "
                    "is direction, concentration, and how the overridden "
                    "cases performed."),
            table=rows, chart={"kind": test_registry.CHART_BAND_RATE,
                               "bands": rows},
            observations=len(frame), model_id=model.model_id,
            model_version=model.version, dataset=model.decisions_dataset,
            period=_period_label(pool), method=test.method,
            calculation_version=kernels.METRICS_VERSION,
            limitations=test.limitations, **kw)

    up = frame[(frame["override_flag"] == 1)
               & (frame.get("override_direction", "") == "UPWARD")]
    peers = frame[(frame.get("approval_decision", "") == "APPROVE")
                  & (frame["override_flag"] == 0)]
    if len(up) < test_registry.MIN_EVENTS:
        return states.insufficient(
            test.test_id, observations=len(up), events=len(up),
            minimum_observations=test_registry.MIN_EVENTS,
            minimum_events=test_registry.MIN_EVENTS,
            model_id=model.model_id, model_version=model.version,
            dataset=model.decisions_dataset, period=_period_label(pool),
            method=test.method, **kw)
    up_rate = float(up[model.outcome_column].fillna(0).mean())
    peer_rate = float(peers[model.outcome_column].fillna(0).mean())
    ratio = up_rate / peer_rate if peer_rate else float("inf")
    state = states.FAIL if ratio > 1.3 else states.PASS
    return states.measured(
        test.test_id, state, ratio, comparison_value=peer_rate,
        detail=(f"Upward-override approvals defaulted at {up_rate:.2%} "
                f"against {peer_rate:.2%} for approvals that followed the "
                f"score — {ratio:.2f}x."),
        table=[{"group": "Upward override", "observations": len(up),
                "default_rate": round(up_rate, 6)},
               {"group": "Followed the score", "observations": len(peers),
                "default_rate": round(peer_rate, 6)}],
        chart={"kind": test_registry.CHART_BAND_RATE},
        observations=len(frame), model_id=model.model_id,
        model_version=model.version, dataset=model.decisions_dataset,
        period=_period_label(pool), method=test.method,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)


# ------------------------------------------------------------------ helpers


def _period_label(pool: Population) -> str:
    if not pool.periods:
        return ""
    if len(pool.periods) == 1:
        return pool.periods[0]
    return f"{pool.periods[0]}..{pool.periods[-1]}"


def _bands(model: model_registry.Model) -> list[float]:
    low, high = model.score_range
    step = (high - low) / 12.0
    return [low + step * i for i in range(13)]


def _band_table(frame: pd.DataFrame,
                model: model_registry.Model) -> list[dict[str, Any]]:
    cut = pd.cut(frame[model.score_column], bins=_bands(model))
    rows: list[dict[str, Any]] = []
    for band, part in frame.groupby(cut, observed=True):
        events = int(part[model.outcome_column].fillna(0).sum())
        rows.append({
            "band": str(band),
            "observations": len(part),
            "events": events,
            "observed_rate": round(events / len(part), 6) if len(part) else 0.0,
        })
    return rows


def _band_override_table(frame: pd.DataFrame,
                         model: model_registry.Model) -> list[dict[str, Any]]:
    cut = pd.cut(frame[model.score_column], bins=_bands(model))
    rows: list[dict[str, Any]] = []
    for band, part in frame.groupby(cut, observed=True):
        rows.append({
            "band": str(band),
            "observations": len(part),
            "override_rate": round(
                float(part["override_flag"].fillna(0).mean()), 6),
        })
    return rows


# ---------------------------------------------------------------- the entry


def run(test_id: str, model: model_registry.Model, *,
        periods: tuple[str, ...] = (), segment: str = "",
        segment_field: str = "") -> states.Result:
    """Run one test. Never raises for a reason the caller should see."""
    test = test_registry.get(test_id)

    refusal = _refuse(test, model, None)
    if refusal is not None:
        return refusal

    try:
        pool = population(
            model, periods=periods, segment=segment,
            segment_field=segment_field,
            matured_only=test_registry.NEEDS_OUTCOME in test.requires)
    except (PopulationError, domains.DomainRefused) as e:
        return states.unavailable(
            test.test_id, what=str(e), model_id=model.model_id,
            model_version=model.version, dataset=model.dataset,
            method=test.method)

    refusal = _refuse(test, model, pool)
    if refusal is not None:
        return refusal

    handler = HANDLERS.get(test_id)
    if handler is None:
        return states.unavailable(
            test.test_id,
            what=(f"a calculation for {test.name}. It is defined in the "
                  "registry and has no handler in this build"),
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, period=_period_label(pool),
            method=test.method)

    try:
        extra: dict[str, Any] = {}
        if segment_field:
            extra["segment_field"] = segment_field
        return handler(test, model, pool, **extra)
    except kernels.ImmatureCohortError:
        return states.not_matured(
            test.test_id, period=_period_label(pool),
            closes=pool.closes or "the recorded window close month",
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, method=test.method)
    except Exception as e:  # noqa: BLE001 - reported, never swallowed
        logger.exception("[scorecard-validation] %s failed", test_id)
        return states.failed(
            test.test_id, error=e, model_id=model.model_id,
            model_version=model.version, dataset=pool.dataset,
            period=_period_label(pool), method=test.method)


def run_category(category: str, model: model_registry.Model, *,
                 periods: tuple[str, ...] = (),
                 segment_field: str = "") -> list[states.Result]:
    """Every test in a category, including the ones that refuse.

    The refusals are returned rather than filtered out, because a validation
    report has to state its own scope and "not applicable, no score-to-PD
    mapping" is part of it.
    """
    out = []
    for test in test_registry.in_category(category):
        out.append(run(test.test_id, model, periods=periods,
                       segment_field=segment_field))
    return states.rank(out)


__all__ = [
    "HANDLERS", "RUNNER_VERSION", "Population", "PopulationError",
    "available_periods", "latest_matured", "matured_periods", "population",
    "run", "run_category",
]
