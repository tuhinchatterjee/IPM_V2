"""§14.3: what the model was fitted on, and how today's book differs from it.

Why these four tests exist beside the ones already in `extra`
-------------------------------------------------------------
The Data & Representativeness category already counted rows, measured
missingness, and compared the segmentation mix. That is a category about
*data quality*. §14.3 asks for something else: a category about
*representativeness*, which is a claim with two halves — what the model was
developed on, and whether the population it is being applied to is still that
population. Neither half can be read off a row count.

So:

  DATA-PROVENANCE    the development sample itself: window, size, events,
                     eligibility, exclusions, outcome definition, horizon,
                     product/channel/classification mix and score shape.
  DATA-INPUT-DRIFT   every model input, development against current, on the
                     approved bins, with missingness, unseen bins and
                     out-of-range values.
  DATA-ODR           the development event rate and mean PD, the latest
                     CLOSED monitoring cohort's, and the current month —
                     with the current month's horizon stated rather than
                     silently compared against the other two.
  DATA-MIXADJ        how much of the movement is the book changing shape.

The one rule that shapes all four
----------------------------------
A comparison between two populations is only a finding if the two are
comparable. Every number here carries the window it was measured over, and
the current month — which has no realised outcome — is never placed in the
same column as a matured default rate. That is the specific mistake §14.3
names, and it is the one that makes a book look like it is deteriorating
when what has actually happened is that the newest cohorts cannot default
yet.

CSI here means what CSI means everywhere else in this product: feature-level
distribution shift over the APPROVED bins, against the development
population as the fixed reference. `backend.scorecard.metrics.csi` is the
only implementation, and this module calls it rather than re-deriving it.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from backend.scorecard import metrics as kernels
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import states
from backend.scorecard.validation.extra import _common, _measured
from backend.scorecard.validation.runner import (
    Population,
    PopulationError,
    _period_label,
    handles,
    matured_periods,
    population,
    reference_population,
)

#: A stratum thinner than this on either side is not compared. Direct
#: standardisation over a cell holding nine accounts produces a rate with a
#: confidence interval wider than the effect it is being used to explain.
MIN_STRATUM = 200

#: How many bins the development score is cut into for the shape panel.
SCORE_BINS = 10

#: The sentence under the three-population chart. Written here rather than
#: in the renderer because the renderer's own caption is about rank
#: inversion, which is a statement about score bands and says nothing at all
#: about three populations on three horizons.
_ODR_CAPTION = (
    "Three populations, and only the first two share a horizon. The "
    "development sample and the latest closed cohort both carry a realised "
    "outcome and can be compared; the current month has no closed window, "
    "so it carries a predicted PD and a delinquency stock and no default "
    "rate. A chart that gave it a bar in the same series would show a book "
    "that had stopped defaulting.")

#: A standardisation has to be a standardisation OF THE BOOK. Below this
#: share of the current matured population the strata with support are a
#: rump, and a composition effect measured over a rump is a statement about
#: the rump.
MIN_COVERAGE = 0.50


def _share_table(frame: pd.DataFrame, fields: tuple[str, ...]
                 ) -> list[dict[str, Any]]:
    """The mix of a population across the fields that are actually present."""
    rows: list[dict[str, Any]] = []
    for field in fields:
        if field not in frame.columns:
            continue
        shares = frame[field].astype(str).value_counts(normalize=True)
        counts = frame[field].astype(str).value_counts()
        for level, share in shares.items():
            rows.append({"dimension": field, "level": str(level),
                         "rows": int(counts.get(level, 0)),
                         "share": round(float(share), 6)})
    return rows


#: What one row of this model's population IS, singular and plural. Derived
#: from the subject key rather than by appending an "s", which produced
#: "14,767 distinct facilitys" on the face of a governance record.
_SUBJECTS: dict[str, tuple[str, str]] = {
    "facility_id": ("facility", "facilities"),
    "customer_id": ("customer", "customers"),
    "account_id": ("account", "accounts"),
    "application_id": ("application", "applications"),
    "loan_id": ("loan", "loans"),
}


def _subject(model: model_registry.Model) -> tuple[str, str]:
    stem = model.subject_key.removesuffix("_id").replace("_", " ")
    return _SUBJECTS.get(model.subject_key, (stem, f"{stem} records"))


def _mix_fields(model: model_registry.Model) -> tuple[str, ...]:
    """Product, channel and classification, in that order of interest."""
    wanted = [model.scope_field] if model.scope_field else []
    wanted += [f for f in model.segmentation_fields if f not in wanted]
    return tuple(wanted)


def _moved_by(then: pd.DataFrame, now: pd.DataFrame, field: str) -> float:
    """Total variation distance between one field's two distributions.

    Half the sum of absolute share changes: 0 when the mix is identical, 1
    when the two populations share no level. Used to choose what to
    standardise over, never reported as a finding.
    """
    a = then[field].astype(str).value_counts(normalize=True)
    b = now[field].astype(str).value_counts(normalize=True)
    levels = set(a.index) | set(b.index)
    return 0.5 * sum(abs(float(b.get(k, 0.0)) - float(a.get(k, 0.0)))
                     for k in levels)


def _rate(frame: pd.DataFrame, model: model_registry.Model
          ) -> tuple[int, int, float | None]:
    """Events, observations and the realised rate over a MATURED frame."""
    if model.outcome_column not in frame.columns or not len(frame):
        return 0, len(frame), None
    outcome = frame[model.outcome_column]
    known = frame[outcome.notna()]
    if not len(known):
        return 0, 0, None
    events = int(known[model.outcome_column].fillna(0).astype(float).sum())
    return events, len(known), events / len(known)


def _matured_only(frame: pd.DataFrame,
                  model: model_registry.Model) -> pd.DataFrame:
    if model.matured_column not in frame.columns:
        return frame
    return frame[frame[model.matured_column].fillna(False).astype(bool)]


# ====================================================== DATA-PROVENANCE


@handles("DATA-PROVENANCE")
def _provenance(test: test_registry.Test, model: model_registry.Model,
                pool: Population, **kw: Any) -> states.Result:
    """The development sample, stated rather than assumed.

    The headline number is the development event rate, because that is the
    single figure every later comparison is made against, and a validation
    that quotes a current default rate without it has quoted half a
    comparison.
    """
    try:
        reference = reference_population(model)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    frame = reference.frame
    matured = _matured_only(frame, model)
    events, observations, rate = _rate(matured, model)
    if rate is None:
        return states.unavailable(
            test.test_id,
            what=("a realised outcome anywhere in the development window — "
                  f"{_period_label(reference)} carries no closed performance "
                  "window, so the sample the model was fitted on cannot be "
                  "described here"),
            **_common(test, model, pool, **kw))

    # The filter waterfall over the DEVELOPMENT window, so the exclusions are
    # the development exclusions rather than today's.
    steps: list[dict[str, Any]] = [
        {"step": "rows in the development window", "rows": len(frame),
         "removed": 0}]
    for rule, value in model.eligibility:
        if rule not in frame.columns:
            continue
        kept = frame[frame[rule] == value]
        steps.append({"step": f"{rule} = {value}", "rows": len(kept),
                      "removed": len(frame) - len(kept)})
    steps.append({"step": "performance window closed", "rows": len(matured),
                  "removed": len(frame) - len(matured)})
    steps.append({"step": "outcome recorded", "rows": observations,
                  "removed": len(matured) - observations})

    subjects = (int(frame[model.subject_key].nunique())
                if model.subject_key in frame.columns else 0)

    score = (pd.to_numeric(matured[model.score_column], errors="coerce")
             .dropna()
             if model.score_column in matured.columns else pd.Series(dtype=float))
    shape: list[dict[str, Any]] = []
    if len(score):
        edges = np.unique(np.quantile(
            score.to_numpy(), np.linspace(0, 1, SCORE_BINS + 1)))
        if len(edges) >= 3:
            cut = pd.cut(score, bins=edges, include_lowest=True)
            counts = cut.value_counts().sort_index()
            for interval, n in counts.items():
                shape.append({
                    "band": f"{interval.left:.0f}–{interval.right:.0f}",
                    "accounts": int(n),
                    "share": round(float(n) / len(score), 6)})

    facts = [
        ("Development window", _period_label(reference)),
        ("Months in the window", str(len(reference.periods))),
        ("Rows", f"{len(frame):,}"),
        (f"Unique {_subject(model)[1]}",
         f"{subjects:,}" if subjects else "not recorded"),
        ("Rows with a closed outcome", f"{observations:,}"),
        ("Defaults", f"{events:,}"),
        ("Development event rate", f"{rate:.3%}"),
        ("Outcome definition", model.default_definition),
        ("Performance window", f"{model.performance_window_months} months"),
        ("Observation window", model.observation_window),
        ("Eligibility", ", ".join(f"{k} = {v}" for k, v in model.eligibility)
         or "no eligibility rule is recorded"),
        ("Scope", f"{model.scope_field} = {model.scope_value}"
         if model.scope_field else "the whole book"),
        ("Score range", f"{model.score_range[0]:.0f}–{model.score_range[1]:.0f}, "
         f"{model.score_direction.lower().replace('_', ' ')}"),
        ("Scaling", f"{model.base_score:.0f} points at {model.base_odds:.0f}:1, "
         f"{model.points_to_double_odds:.0f} points to double the odds"),
        ("Development population, as recorded", model.development_population),
    ]

    mix = _share_table(frame, _mix_fields(model))
    return _measured(
        test, model, pool, rate,
        detail=(f"The model was fitted on {_period_label(reference)}: "
                f"{len(frame):,} rows, {subjects:,} distinct "
                f"{_subject(model)[1]}, of which "
                f"{observations:,} carry a closed {model.performance_window_months}"
                f"-month outcome and {events:,} defaulted — a development "
                f"event rate of {rate:.3%}. Every representativeness "
                f"comparison in this category is made against that sample."),
        observations=len(frame), matured_observations=observations,
        events=events, reference_period=_period_label(reference),
        table=mix,
        chart={"kind": test_registry.CHART_DISTRIBUTION, "bands": shape,
               "value_key": "share", "label_key": "band",
               "caption": ("The development score distribution. A current "
                           "book whose scores sit to one side of this is "
                           "being graded by a model that saw few like it.")},
        lineage={
            "development_window": list(reference.periods),
            "development_rows": len(frame),
            "development_subjects": subjects,
            "development_events": events,
            "development_event_rate": round(rate, 6),
            "outcome_definition": model.default_definition,
            "performance_window_months": model.performance_window_months,
            "panels": [
                {"title": "What the model was developed on", "facts": [
                    {"label": label, "value": value} for label, value in facts]},
                {"title": "Exclusions, in order",
                 "table": steps},
                {"title": "Development score distribution",
                 "table": shape},
            ],
        }, **kw)


# ==================================================== DATA-INPUT-DRIFT


@handles("DATA-INPUT-DRIFT")
def _input_drift(test: test_registry.Test, model: model_registry.Model,
                 pool: Population, **kw: Any) -> states.Result:
    """Every model input, development against current.

    DATA-REPRESENTATIVE asks the same question of the SEGMENTATION variables
    — is this the same kind of book. This asks it of the variables the model
    actually reads, which is the question that decides whether the score
    means what it meant.
    """
    try:
        reference = reference_population(model)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))
    if not model.binned_variables:
        return states.not_applicable(
            test.test_id,
            why=(f"{model.name} does not declare binned characteristics, so "
                 "there is no per-input specification to compare against."),
            **_common(test, model, pool, **kw))

    then, now = reference.frame, pool.frame
    rows: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []
    unmeasurable: list[str] = []

    for variable in model.binned_variables:
        try:
            shift = kernels.csi(then, now, variable=variable)
        except Exception:  # noqa: BLE001 - a missing bin column is a state
            unmeasurable.append(variable)
            continue

        flag = f"{variable}_missing_flag"
        then_missing = (float(then[flag].fillna(0).astype(float).mean())
                        if flag in then.columns else None)
        now_missing = (float(now[flag].fillna(0).astype(float).mean())
                       if flag in now.columns else None)

        unseen = [b["bin"] for b in shift.bins
                  if b["reference_share"] <= kernels.SHIFT_FLOOR
                  and b["current_share"] > kernels.SHIFT_FLOOR]
        lost = [b["bin"] for b in shift.bins
                if b["current_share"] <= kernels.SHIFT_FLOOR
                and b["reference_share"] > kernels.SHIFT_FLOOR]

        raw = f"{variable}_raw"
        outside, then_mean, now_mean = None, None, None
        if raw in then.columns and raw in now.columns:
            a = pd.to_numeric(then[raw], errors="coerce").dropna()
            b = pd.to_numeric(now[raw], errors="coerce").dropna()
            if len(a) and len(b):
                low, high = float(a.min()), float(a.max())
                outside = float(((b < low) | (b > high)).mean())
                then_mean, now_mean = float(a.mean()), float(b.mean())

        rows.append({
            "variable": variable,
            "csi": round(shift.index, 6),
            "development_missing": (round(then_missing, 6)
                                    if then_missing is not None else None),
            "current_missing": (round(now_missing, 6)
                                if now_missing is not None else None),
            "bins_unseen_at_development": len(unseen),
            "bins_no_longer_used": len(lost),
            "outside_development_range": (round(outside, 6)
                                          if outside is not None else None),
            "development_mean": (round(then_mean, 4)
                                 if then_mean is not None else None),
            "current_mean": (round(now_mean, 4)
                             if now_mean is not None else None),
        })
        # The top-drift grid: one cell per (input, bin), carrying that bin's
        # contribution to the input's CSI. A row that lights up in one bin is
        # a feed that changed a cut-off; a row lit across every bin is a
        # population that moved.
        for one in shift.bins:
            cells.append({"variable": variable,
                          "period": str(one["bin"]),
                          "value": abs(float(one["contribution"]))})
            levels.append({
                "variable": variable, "level": str(one["bin"]),
                "development_share": one["reference_share"],
                "current_share": one["current_share"],
                "change": one["shift"],
                "unseen_at_development": str(one["bin"]) in unseen,
            })

    if not rows:
        return states.unavailable(
            test.test_id,
            what=("the approved bin columns for any characteristic. CSI is "
                  "computed over the approved bins, and without them there "
                  "is no specification to compare a distribution against"),
            **_common(test, model, pool, **kw))

    rows.sort(key=lambda r: -r["csi"])
    worst = rows[0]
    unseen_total = sum(r["bins_unseen_at_development"] for r in rows)
    drifted = [r for r in rows if r["csi"] >= 0.10]
    # Keep the grid readable: the eight inputs that moved most.
    keep = {r["variable"] for r in rows[:8]}

    return _measured(
        test, model, pool, worst["csi"],
        detail=(f"{worst['variable']} has moved most of the "
                f"{len(rows)} model inputs, CSI {worst['csi']:.4f}. "
                f"{len(drifted)} of {len(rows)} inputs have a CSI of 0.10 or "
                f"more against the development sample. "
                + (f"{unseen_total} bin(s) are in use now that the model saw "
                   "no development evidence for."
                   if unseen_total else
                   "Every bin in use now was populated at development.")
                + (f" {len(unmeasurable)} input(s) could not be compared: "
                   f"{', '.join(unmeasurable[:4])}."
                   if unmeasurable else "")),
        observations=len(now),
        reference_period=_period_label(reference),
        table=rows,
        chart={"kind": test_registry.CHART_HEATMAP,
               "cells": [c for c in cells if c["variable"] in keep],
               "metric": "CSI contribution",
               "caption": ("Each input against its approved bins. The number "
                           "is that bin's contribution to the "
                           "characteristic's CSI, so a single bright cell is "
                           "one bin that moved rather than a whole "
                           "characteristic that did.")},
        lineage={
            "reference_bins": "the approved bins, fixed at development",
            "zero_bin_smoothing": kernels.SHIFT_FLOOR,
            "formula": ("CSI = sum over bins of (current share - reference "
                        "share) * ln(current share / reference share)"),
            "inputs_compared": len(rows),
            "inputs_not_compared": unmeasurable,
            "panels": [
                {"title": "Development against current, by bin",
                 "levels": [one for one in levels
                            if one["variable"] in keep]},
            ],
        }, **kw)


# ============================================================ DATA-ODR


@handles("DATA-ODR")
def _odr(test: test_registry.Test, model: model_registry.Model,
         pool: Population, **kw: Any) -> states.Result:
    """Development, latest closed monitoring cohort, and the book today.

    Three rows, and the third one is the reason this test exists. The
    current month has no realised outcome, so it carries a predicted PD and
    a point-in-time delinquency stock and never an ODR. Putting a current
    month in the same column as two matured default rates is how a book with
    twelve open cohorts comes to look like a book that has stopped
    defaulting.
    """
    try:
        reference = reference_population(model)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    def mean_pd(frame: pd.DataFrame) -> float | None:
        if not model.pd_column or model.pd_column not in frame.columns:
            return None
        got = pd.to_numeric(frame[model.pd_column], errors="coerce").dropna()
        return float(got.mean()) if len(got) else None

    dev = _matured_only(reference.frame, model)
    dev_events, dev_obs, dev_rate = _rate(dev, model)
    if dev_rate is None:
        return states.unavailable(
            test.test_id,
            what=("a closed outcome in the development window, without "
                  "which there is no development ODR to compare against"),
            **_common(test, model, pool, **kw))

    closed = [p for p in matured_periods(model)
              if p not in set(reference.periods)]
    rows: list[dict[str, Any]] = [{
        "population": "Development sample",
        "window": _period_label(reference),
        "horizon": f"{model.performance_window_months}-month realised outcome",
        "observations": dev_obs, "events": dev_events,
        "observed_rate": round(dev_rate, 6),
        "mean_predicted_pd": (round(mean_pd(dev), 6)
                              if mean_pd(dev) is not None else None),
    }]

    monitoring_rate = None
    if closed:
        latest = closed[-1]
        try:
            watch = population(model, periods=(latest,), matured_only=False)
        except PopulationError:
            watch = None
        if watch is not None:
            part = _matured_only(watch.frame, model)
            events, obs, monitoring_rate = _rate(part, model)
            if monitoring_rate is not None:
                rows.append({
                    "population": "Latest closed monitoring cohort",
                    "window": latest,
                    "horizon": (f"{model.performance_window_months}-month "
                                "realised outcome"),
                    "observations": obs, "events": events,
                    "observed_rate": round(monitoring_rate, 6),
                    "mean_predicted_pd": (round(mean_pd(part), 6)
                                          if mean_pd(part) is not None
                                          else None),
                })

    # The book as it stands. No outcome, and the row says so.
    today = pool.frame
    dpd = None
    for candidate in ("beh_dpd_raw", "dpd_days", "days_past_due"):
        if candidate in today.columns:
            dpd = pd.to_numeric(today[candidate], errors="coerce")
            break
    rows.append({
        "population": "The book as it stands",
        "window": _period_label(pool),
        "horizon": "no realised outcome — the window has not closed",
        "observations": len(today), "events": None,
        "observed_rate": None,
        "mean_predicted_pd": (round(mean_pd(today), 6)
                              if mean_pd(today) is not None else None),
        "delinquency_stock_30_plus": (round(float((dpd >= 30).mean()), 6)
                                      if dpd is not None and len(dpd) else None),
    })

    if monitoring_rate is None:
        return _measured(
            test, model, pool, dev_rate,
            detail=(f"The development sample defaulted at {dev_rate:.3%} over "
                    f"{model.performance_window_months} months. No monitoring "
                    "cohort outside the development window has closed yet, so "
                    "there is nothing comparable to set against it. The "
                    "current month carries a predicted PD and a delinquency "
                    "stock, neither of which is a default rate."),
            observations=dev_obs, matured_observations=dev_obs,
            events=dev_events, reference_period=_period_label(reference),
            table=rows,
            chart={"kind": test_registry.CHART_BAND_RATE, "bands": rows,
                   "label_key": "population",
                   "caption": _ODR_CAPTION},
            lineage={"horizons_are_distinguished": True, "panels": [
                {"title": "Three populations, three horizons",
                 "table": rows}]}, **kw)

    gap = monitoring_rate - dev_rate
    return _measured(
        test, model, pool, gap,
        detail=(f"The development sample defaulted at {dev_rate:.3%}; the "
                f"latest closed monitoring cohort ({rows[1]['window']}) at "
                f"{monitoring_rate:.3%} — "
                f"{'up' if gap >= 0 else 'down'} {abs(gap):.3%} on the same "
                f"{model.performance_window_months}-month horizon. The "
                "current month is shown beside them with its horizon named "
                "and no default rate, because its window has not closed."),
        observations=dev_obs + int(rows[1]["observations"]),
        matured_observations=dev_obs + int(rows[1]["observations"]),
        events=dev_events + int(rows[1]["events"]),
        comparison_value=round(dev_rate, 6),
        reference_period=_period_label(reference),
        table=rows,
        chart={"kind": test_registry.CHART_BAND_RATE, "bands": rows,
               "label_key": "population", "caption": _ODR_CAPTION},
        lineage={
            "development_rate": round(dev_rate, 6),
            "monitoring_rate": round(monitoring_rate, 6),
            "horizons_are_distinguished": True,
            "panels": [{"title": "Three populations, three horizons",
                        "table": rows}],
        }, **kw)


# ========================================================= DATA-MIXADJ


@handles("DATA-MIXADJ")
def _mix_adjusted(test: test_registry.Test, model: model_registry.Model,
                  pool: Population, **kw: Any) -> states.Result:
    """How much of the movement is the book changing shape.

    Direct standardisation: the current stratum-level rates re-weighted onto
    the development mix. If the standardised rate equals the development
    rate, the whole move is composition; if it equals the crude current
    rate, none of it is.
    """
    try:
        reference = reference_population(model)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    candidates = [f for f in _mix_fields(model)
                  if f != model.scope_field
                  and f in reference.frame.columns
                  and f in pool.frame.columns]
    if not candidates:
        return states.unavailable(
            test.test_id,
            what="a segmentation field present in both populations to "
                 "stratify on", **_common(test, model, pool, **kw))
    # Standardise over the dimensions that MOVED.
    #
    # Taking the first two segmentation fields in registry order stratified
    # this by customer segment and salary transfer — two dimensions whose mix
    # barely changed — and duly reported that composition explains none of
    # the movement. That is true of those two fields and reads as a statement
    # about the book. Ranking by total variation distance puts the
    # standardisation on the dimensions a validator would have chosen, and
    # the ones it is computed over are named in the result.
    # Ranked by movement, but only among the fields whose strata still
    # COVER the book: origination vintage moves most of all, because
    # vintages that did not exist at development have no development
    # counterpart, and standardising over it compares nine per cent of the
    # book to nine per cent of the book.
    closed = [p for p in matured_periods(model)
              if p not in set(reference.periods)]
    if not closed:
        shared = _common(test, model, pool, **kw)
        return states.not_matured(
            test.test_id, period=shared.pop("period", _period_label(pool)),
            closes=("the first month outside the development window closes "
                    "its performance window"),
            **shared)
    latest = closed[-1]
    try:
        watch = population(model, periods=(latest,), matured_only=False)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    then = _matured_only(reference.frame, model)
    now = _matured_only(watch.frame, model)
    if model.outcome_column not in then.columns \
            or model.outcome_column not in now.columns:
        return states.unavailable(
            test.test_id, what="a realised outcome on both populations",
            **_common(test, model, pool, **kw))

    def strata(frame: pd.DataFrame, over: list[str]) -> pd.DataFrame:
        key = frame[over[0]].astype(str)
        for extra_field in over[1:]:
            key = key + " · " + frame[extra_field].astype(str)
        grouped = frame.assign(_stratum=key).groupby("_stratum", observed=True)
        return pd.DataFrame({
            "observations": grouped.size(),
            "events": grouped[model.outcome_column].apply(
                lambda s: float(pd.to_numeric(s, errors="coerce")
                                .fillna(0).sum())),
        })

    def supported(over: list[str]) -> pd.DataFrame:
        joined = strata(then, over).join(strata(now, over), how="inner",
                                         lsuffix="_dev", rsuffix="_now")
        return joined[(joined["observations_dev"] >= MIN_STRATUM)
                      & (joined["observations_now"] >= MIN_STRATUM)]

    def usable(over: list[str]) -> tuple[pd.DataFrame, float]:
        got = supported(over)
        share = (float(got["observations_now"].sum()) / len(now)
                 if len(now) else 0.0)
        return got, share

    # Every one-way cut, scored on how much of the book it keeps and how far
    # its mix has moved. A cut that keeps less than MIN_COVERAGE of the
    # current book is not a standardisation of this book.
    ranked: list[tuple[float, str, pd.DataFrame, float]] = []
    for field in candidates:
        got, share = usable([field])
        if len(got) >= 2 and share >= MIN_COVERAGE:
            ranked.append((_moved_by(then, now, field), field, got, share))
    if not ranked:
        fields, joined, covered_share = candidates[:1], supported(
            candidates[:1]), 0.0
        joined = joined
    else:
        ranked.sort(key=lambda one: -one[0])
        _, best, joined, covered_share = ranked[0]
        fields = [best]
        # A second dimension only if it survives the same two conditions.
        for _, second, _, _ in ranked[1:]:
            pair = [best, second]
            got, share = usable(pair)
            if len(got) >= 4 and share >= MIN_COVERAGE:
                fields, joined, covered_share = pair, got, share
            break
    if not len(joined):
        return states.Result(
            test_id=test.test_id, state=states.INSUFFICIENT_SAMPLE,
            detail=(f"Stratified by {' and '.join(fields)}, no cell carries "
                    f"{MIN_STRATUM} accounts on BOTH the development window "
                    f"and {latest}. Standardising over strata that thin "
                    "produces a composition effect with a wider interval "
                    "than the movement it is meant to explain."),
            remedy=("Standardise over one field rather than two, or widen "
                    "the monitoring window to several closed cohorts."),
            **_common(test, model, pool, **kw))

    dev_total = float(joined["observations_dev"].sum())
    now_total = float(joined["observations_now"].sum())
    dev_rate = float(joined["events_dev"].sum()) / dev_total
    now_rate = float(joined["events_now"].sum()) / now_total
    dev_weight = joined["observations_dev"] / dev_total
    now_weight = joined["observations_now"] / now_total
    now_stratum_rate = joined["events_now"] / joined["observations_now"]
    dev_stratum_rate = joined["events_dev"] / joined["observations_dev"]
    standardised = float((dev_weight * now_stratum_rate).sum())

    covered = covered_share or (now_total / max(len(now), 1))
    crude_move = now_rate - dev_rate
    risk_move = standardised - dev_rate
    mix_move = now_rate - standardised
    explained = (mix_move / crude_move) if crude_move else 0.0

    rows: list[dict[str, Any]] = []
    for stratum in joined.index:
        w0 = float(dev_weight.loc[stratum])
        w1 = float(now_weight.loc[stratum])
        r0 = float(dev_stratum_rate.loc[stratum])
        r1 = float(now_stratum_rate.loc[stratum])
        rows.append({
            "stratum": str(stratum),
            "development_accounts": int(joined.loc[stratum, "observations_dev"]),
            "current_accounts": int(joined.loc[stratum, "observations_now"]),
            "development_weight": round(w0, 6),
            "current_weight": round(w1, 6),
            "development_rate": round(r0, 6),
            "current_rate": round(r1, 6),
            # The symmetric split, so the two contributions sum to the move
            # without a residual anybody has to explain away.
            "mix_contribution": round((w1 - w0) * (r0 + r1) / 2.0, 6),
            "rate_contribution": round((r1 - r0) * (w0 + w1) / 2.0, 6),
        })
    rows.sort(key=lambda r: -abs(r["mix_contribution"] + r["rate_contribution"]))

    steps = [
        {"step": f"Development rate, matched strata ({_period_label(reference)})",
         "rate": round(dev_rate, 6), "moved_by": 0.0},
        {"step": "Same customers, changed behaviour",
         "rate": round(standardised, 6), "moved_by": round(risk_move, 6)},
        {"step": f"Plus the book changing shape ({latest})",
         "rate": round(now_rate, 6), "moved_by": round(mix_move, 6)},
    ]

    return _measured(
        test, model, pool, explained,
        detail=(f"Over the {len(joined)} strata with support on both sides "
                f"({covered:.0%} of the current matured book), the default "
                f"rate moved from {dev_rate:.3%} to {now_rate:.3%}, "
                f"{crude_move:+.3%}. Holding the development mix fixed it "
                f"would have been {standardised:.3%}. So {mix_move:+.3%} of "
                f"the move is the book changing shape and {risk_move:+.3%} "
                f"is the same kind of customer behaving differently — "
                f"composition accounts for {abs(explained):.1%} of it. "
                f"Stratified by {' and '.join(fields)}; strata thinner than "
                f"{MIN_STRATUM} accounts on either side are excluded."),
        observations=int(now_total), matured_observations=int(now_total),
        events=int(joined["events_now"].sum()),
        comparison_value=round(now_rate, 6),
        reference_period=_period_label(reference),
        table=rows,
        chart={"kind": test_registry.CHART_WATERFALL, "steps": steps,
               "value_key": "rate", "value_label": "Default rate",
               "caption": (
                   "The move from the development default rate to the "
                   "current one, split into the part that is the book "
                   "changing shape and the part that is the same kind of "
                   "customer behaving differently. The two sum to the move "
                   "with no residual.")},
        lineage={
            "stratified_by": fields,
            "minimum_stratum": MIN_STRATUM,
            "strata_compared": len(joined),
            "current_book_covered": round(covered, 6),
            "dimensions_ranked_by": "total variation distance of the mix",
            "matched_development_rate": round(dev_rate, 6),
            "matched_current_rate": round(now_rate, 6),
            "mix_adjusted_rate": round(standardised, 6),
            "composition_effect": round(mix_move, 6),
            "conditional_risk_effect": round(risk_move, 6),
            "method": ("Direct standardisation. The mix-adjusted rate is "
                       "sum over strata of (development weight x current "
                       "stratum rate)."),
            "panels": [
                {"title": "Matched, mix-adjusted and crude",
                 "facts": [
                     {"label": "Development rate (matched strata)",
                      "value": f"{dev_rate:.3%}"},
                     {"label": "Current rate (matched strata)",
                      "value": f"{now_rate:.3%}"},
                     {"label": "Current rate on the development mix",
                      "value": f"{standardised:.3%}"},
                     {"label": "Composition effect",
                      "value": f"{mix_move:+.3%}"},
                     {"label": "Conditional-risk effect",
                      "value": f"{risk_move:+.3%}"},
                 ]},
            ],
        }, **kw)
