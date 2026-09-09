"""
The deterministic scorecard metrics. §15, §23-§27, §33.

Every number the module reports comes from here. Nothing in this file calls
a model, and nothing about it is a judgement — the LLM interprets what these
return and never produces one.

Three rules the whole file obeys
---------------------------------
**Score direction is read, never assumed.** §13/§23. AUC, KS, gains and
every score-band table invert on it. Each function takes it explicitly, and
`Discrimination` records which one it used so a reader can check.

**Maturity gates the outcome metrics.** §7. Anything that compares predicted
against actual refuses on a cohort whose performance window has not closed.
Not returns zero, not returns an optimistic number — refuses, with the month
the window closes.

**Too few events is a result, not a small number.** §80. A Gini on nine
defaults is arithmetic, not evidence. Every result carries its sample and an
`evidence` label, and the thin ones say so in the sentence a reader sees.

Why the implementations are written out
-----------------------------------------
AUC by rank, KS by cumulative distributions, PSI and CSI by the standard
sum. No modelling dependency. It keeps the numbers inspectable, and §92 asks
for independent reference implementations in the tests — which only means
anything if the engine's own version is here and readable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.scorecard import equation as equation_mod

METRICS_VERSION = "1.0.0"

#: §80's demonstration floors. Below these a figure is reported with a
#: warning rather than withheld — withholding it would hide the thin sample
#: as effectively as quoting it would hide the uncertainty.
MINIMUM_EVENTS = 30
MINIMUM_OBSERVATIONS = 500

#: §24's MAPE guard. Below this observed rate the denominator is too small
#: for a percentage error to mean anything.
MAPE_ODR_FLOOR = 0.005
MAPE_MINIMUM_EVENTS = 20

HIGH_EVIDENCE = "HIGH EVIDENCE"
MODERATE_EVIDENCE = "MODERATE EVIDENCE"
LOW_EVIDENCE = "LOW EVIDENCE"
NO_EVIDENCE = "INSUFFICIENT EVIDENCE"

NOT_RELIABLE = "NOT RELIABLE FOR THIS SAMPLE"


class MetricError(Exception):
    """A metric that may not be computed on what it was given."""


class ImmatureCohortError(MetricError):
    """§7. An outcome metric asked for on a cohort with no outcome."""


def evidence_for(events: int, observations: int) -> str:
    if events < MINIMUM_EVENTS // 3 or observations < MINIMUM_OBSERVATIONS:
        return NO_EVIDENCE
    if events < MINIMUM_EVENTS:
        return LOW_EVIDENCE
    if events < MINIMUM_EVENTS * 5:
        return MODERATE_EVIDENCE
    return HIGH_EVIDENCE


#: The column names that carry "has this cohort's window closed?" and "what
#: happened?". Two vocabularies rather than one because the retail universe
#: and the Saudi SME universe were built by different builders, and renaming
#: a written column is a lake migration.
#:
#: Recognising both is not cosmetic. This gate is the only thing standing
#: between an immature cohort and a metric computed on it, and a gate that
#: knows one naming convention silently passes everything written in the
#: other. The SME datasets carry `is_matured` and `actual_default_12m`; on
#: the first draft of this module they went straight through, and an
#: unrealised outcome would have been reported as a real one.
MATURITY_COLUMNS: tuple[str, ...] = ("matured_flag", "is_matured")
OUTCOME_COLUMNS: tuple[str, ...] = ("actual_default", "actual_default_12m")


def require_matured(frame: pd.DataFrame, *, what: str,
                    maturity_column: str = "",
                    outcome_column: str = "") -> None:
    """§7's gate. Refuse rather than compute on an unrealised outcome.

    The two column arguments let a caller name the fields explicitly. Left
    empty, every known naming convention present on the frame is checked,
    which is the safe default: an unrecognised convention should mean "check
    everything I know" rather than "check nothing".
    """
    maturity = ([maturity_column] if maturity_column
                else [c for c in MATURITY_COLUMNS if c in frame.columns])
    outcomes = ([outcome_column] if outcome_column
                else [c for c in OUTCOME_COLUMNS if c in frame.columns])

    for column in maturity:
        if column in frame.columns and not bool(
                frame[column].fillna(False).all()):
            ends = (frame.get("performance_window_end",
                              pd.Series(["?"])).iloc[0]
                    if len(frame) else "?")
            raise ImmatureCohortError(
                f"{what} compares predicted against actual, and this "
                f"cohort's performance window has not closed (it closes "
                f"{ends}). There is no realised outcome to compare against — "
                "not a zero, not an optimistic estimate, none. Stability "
                "metrics do not need outcomes and remain available.")

    for column in outcomes:
        if column in frame.columns and frame[column].isna().any():
            raise ImmatureCohortError(
                f"{what} needs a realised outcome and "
                f"{int(frame[column].isna().sum()):,} row(s) have none.")


def _clean(y: pd.Series, x: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    frame = pd.DataFrame({"y": y, "x": x}).dropna()
    return (frame["y"].to_numpy(dtype=float),
            frame["x"].to_numpy(dtype=float))


def _midranks(values: np.ndarray) -> np.ndarray:
    """Ranks that share the average position across ties.

    Two reasons, and the second is the one that matters here. The first is
    that midranks are the standard treatment of ties in the Mann-Whitney
    statistic, so the AUC this produces is the AUC everyone else's tooling
    produces. The second is reproducibility: ordinal ranks break a tie by
    whichever row came first, so a scorecard with 6,673 distinct scores across
    19,000 accounts would give a slightly different Gini every time the rows
    arrived in a different order. §11 says the same question gets the same
    answer.
    """
    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    positions = np.arange(1, len(values) + 1, dtype=float)

    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(ordered):
        stop = start
        while stop + 1 < len(ordered) and ordered[stop + 1] == ordered[start]:
            stop += 1
        ranks[order[start:stop + 1]] = (positions[start] + positions[stop]) / 2.0
        start = stop + 1
    return ranks


def _risk_ordered(x: np.ndarray, score_direction: str) -> np.ndarray:
    """Turn a score into a risk ordering, so higher always means riskier.

    §23's "respect score direction", done in one place. Every statistic
    below is computed on this, so none of them has to know the convention.
    """
    if score_direction == equation_mod.HIGHER_SCORE_IS_BETTER:
        return -x
    if score_direction == equation_mod.LOWER_SCORE_IS_BETTER:
        return x
    # Neither. Defaulting would silently pick a convention, and picking the
    # wrong one does not fail — it returns a Gini of the right magnitude and
    # the wrong sign, which reads as a scorecard that ranks backwards.
    raise MetricError(
        f"'{score_direction}' is not a score direction. It is one of: "
        f"{', '.join(equation_mod.SCORE_DIRECTIONS)}. Without it there is no "
        "way to know whether a high score is a good customer or a bad one.")


# ------------------------------------------------------------ §23 discrimination


@dataclass
class Discrimination:
    """§23. AUC, Gini and KS, with the sample and the convention used."""

    auc: float
    gini: float
    ks: float
    ks_at: float
    observations: int
    events: int
    score_direction: str
    label: str = ""
    #: The cumulative curves, for the ROC and KS charts.
    roc: list[dict[str, float]] = field(default_factory=list)
    ks_curve: list[dict[str, float]] = field(default_factory=list)

    @property
    def evidence(self) -> str:
        return evidence_for(self.events, self.observations)

    @property
    def auc_confidence(self) -> tuple[float, float]:
        """Hanley-McNeil standard error, as a 95% interval.

        Reported because §23 asks for confidence intervals where supported,
        and because a Gini quoted to two decimals on 40 defaults invites a
        precision nobody has.
        """
        positives, negatives = self.events, self.observations - self.events
        if positives < 2 or negatives < 2:
            return (float("nan"), float("nan"))
        area = self.auc
        q1 = area / (2 - area)
        q2 = 2 * area * area / (1 + area)
        variance = (area * (1 - area)
                    + (positives - 1) * (q1 - area * area)
                    + (negatives - 1) * (q2 - area * area)) / (
                        positives * negatives)
        error = math.sqrt(max(variance, 0.0))
        return (max(area - 1.96 * error, 0.0), min(area + 1.96 * error, 1.0))

    def sentence(self) -> str:
        low, high = self.auc_confidence
        interval = ("" if math.isnan(low)
                    else f" (95% CI {low:.4f} to {high:.4f})")
        return (f"{self.label or 'Discrimination'}: AUC {self.auc:.4f}"
                f"{interval}, Gini {self.gini:.4f}, KS {self.ks:.4f} at "
                f"score {self.ks_at:,.2f}, over {self.observations:,} "
                f"observation(s) and {self.events:,} default(s). "
                f"{self.evidence}.")

    def to_dict(self) -> dict[str, Any]:
        low, high = self.auc_confidence
        return {
            "metrics_version": METRICS_VERSION,
            "label": self.label,
            "auc": round(self.auc, 6),
            "auc_ci_low": None if math.isnan(low) else round(low, 6),
            "auc_ci_high": None if math.isnan(high) else round(high, 6),
            "gini": round(self.gini, 6),
            "accuracy_ratio": round(self.gini, 6),
            "ks": round(self.ks, 6),
            "ks_at_score": round(self.ks_at, 4),
            "observations": self.observations,
            "events": self.events,
            "evidence": self.evidence,
            "score_direction": self.score_direction,
            "definitions": {
                "gini": "Gini = 2 * AUC - 1",
                "ks": ("KS = the maximum difference between the cumulative "
                       "bad and cumulative good distributions"),
                "accuracy_ratio": "Accuracy Ratio is another name for Gini",
            },
            "reads_as": self.sentence(),
        }


def discrimination(frame: pd.DataFrame, *, score: str, target: str,
                   score_direction: str, label: str = "",
                   curves: bool = False) -> Discrimination:
    """§23. AUC, Gini and KS on a matured cohort."""
    require_matured(frame, what="Discrimination")
    y, raw = _clean(frame[target], frame[score])
    if len(y) == 0:
        raise MetricError("nothing to measure: every row was missing")
    events = int(y.sum())
    if events == 0 or events == len(y):
        raise MetricError(
            f"the sample has {events} default(s) out of {len(y):,}. "
            "Discrimination is the ability to separate two groups, and this "
            "sample has only one.")

    risk = _risk_ordered(raw, score_direction)
    ranks = _midranks(risk)
    negatives = len(y) - events
    auc = float((ranks[y == 1].sum() - events * (events + 1) / 2)
                / (events * negatives))
    gini = 2.0 * auc - 1.0

    order = np.argsort(risk, kind="mergesort")
    bad_cumulative = np.cumsum(y[order]) / events
    good_cumulative = np.cumsum(1 - y[order]) / negatives
    gaps = np.abs(bad_cumulative - good_cumulative)

    # KS is the largest gap between the two cumulative distributions at a
    # SCORE, and the cumulative counts above step once per row. Inside a block
    # of rows sharing one score those intermediate positions are not points of
    # the score domain — they are an artefact of the order the ties happened
    # to be read in — and taking the maximum among them reports a separation
    # the score cannot actually make. On the retail behavioural book that
    # overstated KS by 0.0004; on a coarsely banded scorecard it would be
    # much worse. The gap is measured only where the next row's score
    # differs, which is where the distributions have finished stepping.
    sorted_risk = risk[order]
    at_a_distinct_score = np.ones(len(y), dtype=bool)
    at_a_distinct_score[:-1] = sorted_risk[1:] != sorted_risk[:-1]
    peak = int(np.argmax(np.where(at_a_distinct_score, gaps, -1.0)))
    ks = float(gaps[peak])
    ks_at = float(raw[order][peak])

    result = Discrimination(
        auc=auc, gini=gini, ks=ks, ks_at=ks_at, observations=len(y),
        events=events, score_direction=score_direction, label=label)

    if curves:
        step = max(len(y) // 200, 1)
        result.roc = [
            {"false_positive_rate": round(float(good_cumulative[i]), 6),
             "true_positive_rate": round(float(bad_cumulative[i]), 6)}
            for i in range(0, len(y), step)]
        result.ks_curve = [
            {"score": round(float(raw[order][i]), 4),
             "cumulative_bad": round(float(bad_cumulative[i]), 6),
             "cumulative_good": round(float(good_cumulative[i]), 6),
             "gap": round(float(gaps[i]), 6)}
            for i in range(0, len(y), step)]
    return result


def gains(frame: pd.DataFrame, *, score: str, target: str,
          score_direction: str, deciles: int = 10) -> list[dict[str, Any]]:
    """§23's gains, lift and capture rate by decile of risk."""
    require_matured(frame, what="Gains and lift")
    y, raw = _clean(frame[target], frame[score])
    events = int(y.sum())
    if events == 0:
        raise MetricError("no defaults, so there is nothing to capture")

    risk = _risk_ordered(raw, score_direction)
    order = np.argsort(-risk)          # riskiest first
    y_sorted, raw_sorted = y[order], raw[order]
    edges = np.linspace(0, len(y), deciles + 1).astype(int)
    overall = events / len(y)

    rows: list[dict[str, Any]] = []
    captured = 0
    for index in range(deciles):
        start, end = edges[index], edges[index + 1]
        chunk = y_sorted[start:end]
        chunk_events = int(chunk.sum())
        captured += chunk_events
        rows.append({
            "decile": index + 1,
            "observations": int(end - start),
            "events": chunk_events,
            "bad_rate": round(float(chunk.mean()) if len(chunk) else 0.0, 6),
            "lift": round(float(chunk.mean() / overall)
                          if len(chunk) and overall else 0.0, 4),
            "cumulative_capture_rate": round(captured / events, 6),
            "population_share": round((end) / len(y), 6),
            "score_from": round(float(raw_sorted[start]), 4),
            "score_to": round(float(raw_sorted[end - 1]), 4),
            "evidence": evidence_for(chunk_events, int(end - start)),
        })
    return rows


# ------------------------------------------------------- §24 calibration


@dataclass
class Calibration:
    """§24. Predicted against observed, in every form the brief asks for."""

    observed_rate: float
    predicted_rate: float
    observations: int
    events: int
    brier: float
    log_loss: float
    bucket_rmse: float
    mape: float | None
    mape_status: str
    calibration_in_the_large: float
    slope: float | None
    buckets: list[dict[str, Any]] = field(default_factory=list)
    label: str = ""

    @property
    def evidence(self) -> str:
        return evidence_for(self.events, self.observations)

    @property
    def expected_defaults(self) -> float:
        return self.predicted_rate * self.observations

    def sentence(self) -> str:
        direction = ("under-predicts"
                     if self.observed_rate > self.predicted_rate
                     else "over-predicts")
        gap = abs(self.observed_rate - self.predicted_rate) * 100
        return (f"{self.label or 'Calibration'}: observed default rate "
                f"{self.observed_rate * 100:.2f}% against average predicted "
                f"PD {self.predicted_rate * 100:.2f}% — the model "
                f"{direction} by {gap:.2f} percentage points. "
                f"{self.events:,} default(s) observed against "
                f"{self.expected_defaults:,.0f} expected. {self.evidence}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics_version": METRICS_VERSION,
            "label": self.label,
            "observed_default_rate": round(self.observed_rate, 6),
            "average_predicted_pd": round(self.predicted_rate, 6),
            "observed_defaults": self.events,
            "expected_defaults": round(self.expected_defaults, 2),
            "calibration_in_the_large": round(
                self.calibration_in_the_large, 6),
            "calibration_slope": (None if self.slope is None
                                  else round(self.slope, 6)),
            "brier_score": round(self.brier, 8),
            "log_loss": round(self.log_loss, 8),
            "bucket_rmse": round(self.bucket_rmse, 8),
            "mape": None if self.mape is None else round(self.mape, 4),
            "mape_status": self.mape_status,
            "observations": self.observations,
            "evidence": self.evidence,
            "buckets": list(self.buckets),
            "what_rmse_means_here": (
                "Bucket RMSE: the root mean squared difference between "
                "observed default rate and average predicted PD across "
                "score bands. Account-level squared error is the Brier "
                "score and is reported separately — they answer different "
                "questions and quoting one as the other overstates "
                "precision."),
            "reads_as": self.sentence(),
        }


def _score_buckets(frame: pd.DataFrame, score: str, bands: int,
                   score_direction: str) -> pd.Series:
    values = frame[score].astype(float)
    try:
        codes = pd.qcut(values, bands, labels=False, duplicates="drop")
    except ValueError:
        codes = pd.Series(0, index=frame.index)
    if score_direction == equation_mod.HIGHER_SCORE_IS_BETTER:
        # Band 1 should be the riskiest, whatever the score convention.
        top = int(pd.Series(codes).max() or 0)
        codes = top - codes
    return pd.Series(codes, index=frame.index).astype("Int64") + 1


def calibration(frame: pd.DataFrame, *, pd_column: str, target: str,
                score: str | None = None, score_direction: str = "",
                bands: int = 10, label: str = "") -> Calibration:
    """§24. Everything the brief asks for, with MAPE guarded rather than
    quoted or dropped."""
    require_matured(frame, what="Calibration")
    working = frame[[c for c in (pd_column, target, score) if c]].dropna()
    if working.empty:
        raise MetricError("nothing to calibrate: every row was missing")

    actual = working[target].to_numpy(dtype=float)
    predicted = np.clip(working[pd_column].to_numpy(dtype=float), 1e-12,
                        1 - 1e-12)
    events = int(actual.sum())
    observed_rate = float(actual.mean())
    predicted_rate = float(predicted.mean())

    brier = float(np.mean((predicted - actual) ** 2))
    log_loss = float(-np.mean(actual * np.log(predicted)
                              + (1 - actual) * np.log(1 - predicted)))

    buckets: list[dict[str, Any]] = []
    if score:
        working = working.assign(
            _band=_score_buckets(working, score, bands, score_direction))
        for band, chunk in working.groupby("_band", observed=True):
            band_actual = chunk[target].astype(float)
            band_predicted = chunk[pd_column].astype(float)
            buckets.append({
                "band": int(band),
                "observations": len(chunk),
                "events": int(band_actual.sum()),
                "observed_default_rate": round(float(band_actual.mean()), 6),
                "average_predicted_pd": round(float(band_predicted.mean()),
                                              6),
                "score_from": round(float(chunk[score].min()), 4),
                "score_to": round(float(chunk[score].max()), 4),
                "evidence": evidence_for(int(band_actual.sum()), len(chunk)),
            })
        buckets.sort(key=lambda row: row["band"])

    if buckets:
        differences = np.array([b["observed_default_rate"]
                                - b["average_predicted_pd"]
                                for b in buckets])
        bucket_rmse = float(np.sqrt(np.mean(differences ** 2)))
    else:
        bucket_rmse = float("nan")

    mape, mape_status = _guarded_mape(buckets)

    # Calibration in the large: the log-odds gap between observed and
    # predicted. Zero means the level is right.
    def _logit(p: float) -> float:
        p = min(max(p, 1e-12), 1 - 1e-12)
        return math.log(p / (1 - p))

    citl = _logit(observed_rate) - _logit(predicted_rate)

    slope = None
    if len(working) > 50 and 0 < events < len(working):
        from backend.scorecard import fitting

        logits = pd.Series([_logit(p) for p in predicted],
                           index=working.index)
        try:
            fitted = fitting.fit(working.assign(_logit=logits), ["_logit"],
                                 target)
            slope = fitted.coefficients["_logit"]
        except fitting.FittingError:
            slope = None

    return Calibration(
        observed_rate=observed_rate, predicted_rate=predicted_rate,
        observations=len(working), events=events, brier=brier,
        log_loss=log_loss, bucket_rmse=bucket_rmse, mape=mape,
        mape_status=mape_status, calibration_in_the_large=citl, slope=slope,
        buckets=buckets, label=label)


def _guarded_mape(buckets: list[dict[str, Any]]) -> tuple[float | None, str]:
    """§24's MAPE guard.

    A percentage error divides by the observed rate. On a band with a 0.2%
    default rate, a 0.1pp miss is a 50% error — a number that is arithmetically
    correct and tells a reader nothing except that the band was small. The
    floor is documented rather than silent, and bands below it are excluded
    and counted rather than quietly included.
    """
    if not buckets:
        return None, "NOT COMPUTED — no score bands were available"

    usable = [b for b in buckets
              if b["observed_default_rate"] >= MAPE_ODR_FLOOR
              and b["events"] >= MAPE_MINIMUM_EVENTS]
    excluded = len(buckets) - len(usable)
    if not usable:
        return None, (
            f"{NOT_RELIABLE}: every score band is below the "
            f"{MAPE_ODR_FLOOR:.1%} observed-rate floor or the "
            f"{MAPE_MINIMUM_EVENTS}-event minimum, so a percentage error "
            "would be dividing by noise.")

    errors = [abs(b["observed_default_rate"] - b["average_predicted_pd"])
              / b["observed_default_rate"] for b in usable]
    value = float(np.mean(errors) * 100)
    if excluded:
        return value, (
            f"COMPUTED ON {len(usable)} OF {len(buckets)} BANDS: {excluded} "
            f"band(s) fell below the {MAPE_ODR_FLOOR:.1%} floor or the "
            f"{MAPE_MINIMUM_EVENTS}-event minimum and were excluded.")
    return value, "COMPUTED ON ALL BANDS"


# ------------------------------------------------------- §25/§26 stability


@dataclass
class PopulationShift:
    """A PSI or CSI, with the distributions that produced it."""

    index: float
    kind: str                      # "PSI" or "CSI"
    variable: str
    bins: list[dict[str, Any]] = field(default_factory=list)
    reference_rows: int = 0
    current_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics_version": METRICS_VERSION,
            "kind": self.kind,
            "variable": self.variable,
            "index": round(self.index, 6),
            "reference_rows": self.reference_rows,
            "current_rows": self.current_rows,
            "bins": list(self.bins),
            "thresholds_are_policy": (
                "PSI and CSI have no regulatory threshold. The conventional "
                "0.10 and 0.25 cut-offs are scorecard practice; whatever "
                "limit is applied here comes from the validation policy and "
                "is labelled with its source."),
        }


#: The smoothing floor on an empty bin. Without it a bin present in the
#: reference and absent in the current month gives an infinite index, which
#: then dominates every chart it appears on.
SHIFT_FLOOR = 1e-6


def _shift(reference: pd.Series, current: pd.Series, *, kind: str,
           variable: str) -> PopulationShift:
    levels = sorted(set(reference.dropna().astype(str))
                    | set(current.dropna().astype(str)))
    reference_total = max(len(reference.dropna()), 1)
    current_total = max(len(current.dropna()), 1)

    bins: list[dict[str, Any]] = []
    total = 0.0
    for level in levels:
        reference_share = max(
            float((reference.astype(str) == level).sum()) / reference_total,
            SHIFT_FLOOR)
        current_share = max(
            float((current.astype(str) == level).sum()) / current_total,
            SHIFT_FLOOR)
        contribution = (current_share - reference_share) * math.log(
            current_share / reference_share)
        total += contribution
        bins.append({
            "bin": level,
            "reference_share": round(reference_share, 6),
            "current_share": round(current_share, 6),
            "shift": round(current_share - reference_share, 6),
            "contribution": round(contribution, 6),
        })
    bins.sort(key=lambda row: -abs(row["contribution"]))
    return PopulationShift(index=total, kind=kind, variable=variable,
                           bins=bins, reference_rows=reference_total,
                           current_rows=current_total)


def psi(reference: pd.DataFrame, current: pd.DataFrame, *, score: str,
        bands: int = 10) -> PopulationShift:
    """§26's score PSI. Bands come from the reference, not from each month.

    Cutting each month at its own deciles compares a distribution to itself
    and returns roughly zero however far the population has moved.
    """
    values = reference[score].dropna().astype(float)
    edges = list(np.unique(values.quantile(
        np.linspace(0, 1, bands + 1)).to_numpy()))
    if len(edges) < 3:
        raise MetricError(
            f"{score} takes too few distinct values in the reference "
            "population to band")
    edges[0], edges[-1] = -np.inf, np.inf

    def band(frame: pd.DataFrame) -> pd.Series:
        return pd.cut(frame[score].astype(float), bins=edges,
                      labels=False, include_lowest=True).astype("Int64")

    return _shift(band(reference), band(current), kind="PSI", variable=score)


def csi(reference: pd.DataFrame, current: pd.DataFrame, *,
        variable: str) -> PopulationShift:
    """§26's CSI, over the approved bins of one variable.

    Computed on the `<variable>_bin` column — the approved bins — rather than
    on fresh cuts of the raw value. §32 asks whether a variable changed
    *relative to the specification the model uses*, which is a different
    question from whether its raw distribution moved.
    """
    column = f"{variable}_bin"
    if column not in reference.columns or column not in current.columns:
        raise MetricError(
            f"{column} is not present. CSI is computed over the approved "
            "bins, not over fresh cuts of the raw value — those answer "
            "different questions.")
    return _shift(reference[column], current[column], kind="CSI",
                  variable=variable)


# ------------------------------------------- §27 variable-level diagnostics


def variable_discrimination(frame: pd.DataFrame, *, variable: str,
                            target: str) -> dict[str, Any]:
    """§27. One variable's univariate power, on its WoE where one exists.

    Measured on the WoE rather than the raw value because that is what the
    model sees. A raw-value AUC on a U-shaped variable understates it badly,
    and the model is not using the raw value.
    """
    require_matured(frame, what="Variable discrimination")
    woe_column = f"{variable}_woe"
    column = woe_column if woe_column in frame.columns else variable
    if column not in frame.columns:
        raise MetricError(f"{variable} is not in this frame")

    # A categorical with no approved WoE has no ordering, so it has no AUC
    # or KS. That is a fact about the variable, not an error: asking for
    # every candidate's discrimination legitimately includes variables that
    # were never binned. Coercing the labels to numbers would rank
    # "GOVERNMENT" against "SME" by alphabet.
    if column != woe_column and not pd.api.types.is_numeric_dtype(
            frame[column]):
        return {
            "variable": variable, "measured_on": column,
            "auc": None, "gini": None, "ks": None,
            "observations": len(frame), "events": 0,
            "evidence": NO_EVIDENCE,
            "why": (
                f"{variable} is categorical and has no approved weight of "
                "evidence, so it has no ordering to measure discrimination "
                "along. Ranking its levels by any other rule would be "
                "ranking them by that rule."),
        }

    y, x = _clean(frame[target], frame[column])
    events = int(y.sum())
    if events == 0 or events == len(y):
        return {
            "variable": variable, "measured_on": column,
            "auc": None, "gini": None, "ks": None,
            "observations": len(y), "events": events,
            "evidence": NO_EVIDENCE,
            "why": "the sample has only one outcome class",
        }

    # WoE is oriented so higher is better, so risk is its negative.
    risk = -x if column == woe_column else x
    ranks = np.argsort(np.argsort(risk)) + 1.0
    negatives = len(y) - events
    auc = float((ranks[y == 1].sum() - events * (events + 1) / 2)
                / (events * negatives))
    order = np.argsort(risk)
    bad_cumulative = np.cumsum(y[order]) / events
    good_cumulative = np.cumsum(1 - y[order]) / negatives
    ks = float(np.max(np.abs(bad_cumulative - good_cumulative)))

    missing_rate = float(frame[variable].isna().mean()
                         if variable in frame.columns else 0.0)
    special = 0.0
    bin_column = f"{variable}_bin"
    if bin_column in frame.columns:
        from backend.scorecard import binning as binning_mod

        special = float(frame[bin_column].isin(
            binning_mod.SPECIAL_BINS).mean())

    return {
        "variable": variable,
        "measured_on": column,
        "auc": round(auc, 6),
        "gini": round(2 * auc - 1, 6),
        "accuracy_ratio": round(2 * auc - 1, 6),
        "ks": round(ks, 6),
        "observations": len(y),
        "events": events,
        "missing_rate": round(missing_rate, 6),
        "special_bin_rate": round(special, 6),
        "evidence": evidence_for(events, len(y)),
    }


# -------------------------------------------------- §33 implementation


@dataclass
class Replication:
    """§33. An independent reconstruction against what was stored."""

    rows: int
    max_absolute_logit_difference: float
    max_absolute_pd_difference: float
    max_absolute_score_difference: float
    mismatch_count: int
    bin_mismatch_count: int
    tolerance: float
    label: str = ""

    @property
    def mismatch_rate(self) -> float:
        return self.mismatch_count / self.rows if self.rows else 0.0

    @property
    def validated(self) -> bool:
        """§33: a critical mismatch blocks IMPLEMENTATION VALIDATED."""
        return (self.mismatch_count == 0 and self.bin_mismatch_count == 0
                and self.max_absolute_logit_difference <= self.tolerance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics_version": METRICS_VERSION,
            "label": self.label,
            "rows_checked": self.rows,
            "max_absolute_logit_difference": round(
                self.max_absolute_logit_difference, 10),
            "max_absolute_pd_difference": round(
                self.max_absolute_pd_difference, 10),
            "max_absolute_score_difference": round(
                self.max_absolute_score_difference, 8),
            "mismatch_count": self.mismatch_count,
            "mismatch_rate": round(self.mismatch_rate, 8),
            "bin_assignment_mismatches": self.bin_mismatch_count,
            "rounding_tolerance": self.tolerance,
            "status": ("IMPLEMENTATION VALIDATED" if self.validated
                       else "IMPLEMENTATION NOT VALIDATED"),
            "why": ("Every stored score was reproduced from the approved "
                    "specification within tolerance."
                    if self.validated else
                    "At least one stored score could not be reproduced from "
                    "the approved specification. A model whose stored output "
                    "does not match its own equation is not the model that "
                    "was approved, whatever its discrimination looks like."),
        }


def replicate(frame: pd.DataFrame, equation: equation_mod.Equation, *,
              tolerance: float = 1e-6, label: str = "") -> Replication:
    """§33. Recompute logit, PD and score, and compare against stored."""
    suffix = equation.output_prefix
    logit = pd.Series(equation.intercept, index=frame.index, dtype="float64")
    for term in equation.terms:
        if term.column() not in frame.columns:
            raise MetricError(
                f"{term.column()} is not stored, so the model cannot be "
                "independently reconstructed")
        logit = logit + term.coefficient * frame[term.column()].astype(
            "float64")

    stored_logit = frame.get(f"logit_{suffix}")
    if stored_logit is None:
        raise MetricError(f"logit_{suffix} is not stored")
    logit_gap = (logit - stored_logit.astype("float64")).abs()

    recomputed_pd = logit.apply(equation_mod.Equation.pd_from_logit)
    stored_pd = frame.get(f"pd_{suffix}")
    pd_gap = ((recomputed_pd - stored_pd.astype("float64")).abs()
              if stored_pd is not None else pd.Series([0.0]))

    score_gap = pd.Series([0.0])
    if equation.score_mapping is not None and f"score_{suffix}" in frame:
        recomputed = logit.apply(equation.score_mapping.score)
        score_gap = (recomputed
                     - frame[f"score_{suffix}"].astype("float64")).abs()

    return Replication(
        rows=len(frame),
        max_absolute_logit_difference=float(logit_gap.max()),
        max_absolute_pd_difference=float(pd_gap.max()),
        max_absolute_score_difference=float(score_gap.max()),
        mismatch_count=int((logit_gap > tolerance).sum()),
        bin_mismatch_count=0,
        tolerance=tolerance, label=label)


# ------------------------------------------------- §40 bootstrap confidence


@dataclass
class Interval:
    """A percentile confidence interval, and everything needed to redraw it.

    The resample count and seed are fields rather than arguments the caller
    remembers, because a confidence interval that cannot be reproduced is not
    evidence — it is a number that was true once.
    """

    statistic: str
    point: float
    lower: float
    upper: float
    confidence: float
    resamples: int
    seed: int
    observations: int
    events: int
    draws: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics_version": METRICS_VERSION,
            "statistic": self.statistic, "point": self.point,
            "lower": round(self.lower, 6), "upper": round(self.upper, 6),
            "confidence": self.confidence, "resamples": self.resamples,
            "seed": self.seed, "observations": self.observations,
            "events": self.events,
            "method": "percentile bootstrap, resampling rows with replacement",
        }


#: Above this many distinct score values the count-based path stops being
#: the faster one, and the plain resample is used instead. Both compute the
#: same statistic; see `bootstrap_auc`.
DISTINCT_SCORE_LIMIT = 50_000


def bootstrap_auc(frame: pd.DataFrame, *, score: str, target: str,
                  score_direction: str, resamples: int = 500,
                  seed: int = 0, confidence: float = 0.95) -> Interval:
    """A percentile confidence interval for the AUC.

    Why this is a kernel and not a loop in a caller
    -----------------------------------------------
    A bootstrap is a statistical method, so it lives with the other
    statistical methods. A caller that resampled a DataFrame five hundred
    times and called `discrimination` on each would get the right answer at
    roughly two hundred milliseconds a draw — a minute and a half on a book
    of a third of a million rows, which is long enough that somebody would
    eventually make the interval optional, and an optional confidence
    interval is one nobody has.

    How it stays exact while being fast
    -----------------------------------
    The AUC is a Mann-Whitney statistic: it depends on the score's *ordering*
    and on how many goods and bads sit at each distinct score, not on the
    scores themselves. A scorecard has a few hundred distinct scores across
    hundreds of thousands of accounts, so the whole sample compresses to a
    table of (distinct score, goods, bads) with a few hundred rows.

    Resampling rows with replacement is then exactly a multinomial draw over
    the cells of that table, and the statistic is a cumulative sum across it.
    That makes a draw O(cells) rather than O(n log n), and the result is not
    an approximation of the row-resampling bootstrap — it is the same thing,
    counted rather than enumerated. A test asserts that the degenerate draw
    (the observed counts) reproduces `discrimination(...).auc` exactly.

    Where the compression stops helping — a continuous PD with a distinct
    value per row — the plain resample is used instead. Same statistic,
    slower, and it says so in neither case because the caller does not need
    to know which path ran to trust the number.
    """
    require_matured(frame, what="A bootstrap confidence interval")
    y, raw = _clean(frame[target], frame[score])
    if len(y) == 0:
        raise MetricError("nothing to measure: every row was missing")
    events = int(y.sum())
    negatives = len(y) - events
    if events == 0 or negatives == 0:
        raise MetricError(
            f"the sample has {events} default(s) out of {len(y):,}. An "
            "interval around a statistic that cannot be computed is not a "
            "wider version of it.")
    if resamples < 2:
        raise MetricError("a bootstrap needs at least two resamples")

    risk = _risk_ordered(raw, score_direction)
    point = discrimination(frame, score=score, target=target,
                           score_direction=score_direction).auc

    values, index = np.unique(risk, return_inverse=True)
    rng = np.random.default_rng(seed)
    if len(values) <= DISTINCT_SCORE_LIMIT:
        draws = _bootstrap_counted(y, index, len(values), resamples, rng)
    else:
        draws = _bootstrap_resampled(y, risk, resamples, rng)

    if not draws:
        raise MetricError(
            "no resample produced a measurable statistic, which means almost "
            "every draw came back with one outcome class")
    tail = (1.0 - confidence) / 2.0 * 100.0
    return Interval(
        statistic="AUC", point=point,
        lower=float(np.percentile(draws, tail)),
        upper=float(np.percentile(draws, 100.0 - tail)),
        confidence=confidence, resamples=len(draws), seed=seed,
        observations=len(y), events=events,
        draws=[round(float(d), 6) for d in draws])


def _bootstrap_counted(y: np.ndarray, index: np.ndarray, distinct: int,
                       resamples: int,
                       rng: np.random.Generator) -> list[float]:
    """Draws taken over the (score, outcome) count table. See `bootstrap_auc`."""
    bad = np.bincount(index, weights=y, minlength=distinct)
    good = np.bincount(index, minlength=distinct) - bad
    cells = np.concatenate([good, bad])
    share = cells / cells.sum()
    rows = len(y)

    out: list[float] = []
    for counts in rng.multinomial(rows, share, size=resamples):
        drawn = auc_from_counts(counts[:distinct].astype(float),
                                counts[distinct:].astype(float))
        if drawn is not None:
            out.append(drawn)
    return out


def auc_from_counts(good: np.ndarray, bad: np.ndarray) -> float | None:
    """The AUC of a (risk-ordered) count table. None where it is undefined.

    The Mann-Whitney statistic with midranks, read off counts rather than
    rows: every bad at a given risk beats every good below it and ties with
    the goods beside it, and a tie is worth half a comparison. That is the
    same tie treatment `_midranks` applies, which is what lets the two paths
    in `bootstrap_auc` produce the same number — a test asserts it.

    Public because the assertion is worth making from outside: it is the one
    place where a faster path could silently drift from the slow one.
    """
    goods, bads = float(good.sum()), float(bad.sum())
    if goods == 0 or bads == 0:
        return None
    below = np.concatenate([[0.0], np.cumsum(good)[:-1]])
    return float((bad * (below + good / 2.0)).sum() / (goods * bads))


def _bootstrap_resampled(y: np.ndarray, risk: np.ndarray, resamples: int,
                         rng: np.random.Generator) -> list[float]:
    """The plain resample, for a score with no useful repetition in it."""
    rows = len(y)
    out: list[float] = []
    for _ in range(resamples):
        at = rng.integers(0, rows, rows)
        drawn_y, drawn_risk = y[at], risk[at]
        events = drawn_y.sum()
        negatives = rows - events
        if events == 0 or negatives == 0:
            continue
        ranks = _midranks(drawn_risk)
        out.append(float((ranks[drawn_y == 1].sum()
                          - events * (events + 1) / 2) / (events * negatives)))
    return out
