"""The rest of the validation calculations.

Split from `runner` for one reason only: the runner is the contract — five
gates, one registry, one entry point — and it stays readable at a sitting.
These are the individual tests. They register into the same `HANDLERS`
dictionary through the same decorator, so there is still exactly one place
that maps a test id to a calculation.

Every handler here obeys the same rule as the ones in `runner`: it assembles
arguments, calls a governed kernel or reads a field, and returns a `Result`.
Where a number is compared against a threshold, the threshold is a governed
`Limit` and the comparison is `Limit.verdict`. Nothing here decides anything.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.scorecard import binning
from backend.scorecard import metrics as kernels
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import states
from backend.scorecard.validation.runner import (
    Population,
    PopulationError,
    _bands,
    _period_label,
    _verdict,
    available_periods,
    handles,
    matured_periods,
    population,
)

#: How many matured cohorts a rolling window covers. Three months is short
#: enough to see a turn and long enough that one bad month does not make one.
ROLLING_WINDOW = 3

#: Resamples and seed for the bootstrap. Both are declared rather than
#: chosen at run time, because a confidence interval that moves between runs
#: is not a confidence interval.
BOOTSTRAP_RESAMPLES = 500
BOOTSTRAP_SEED = 20240101

#: A bin holding less than this share of the book has stopped being a bin.
SPARSE_BIN_SHARE = 0.01


def _common(test: test_registry.Test, model: model_registry.Model,
            pool: Population, **kw: Any) -> dict[str, Any]:
    """The provenance every result carries, assembled once."""
    return dict(
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=_period_label(pool),
        method=test.method, calculation_version=kernels.METRICS_VERSION,
        score_direction=model.score_direction,
        limitations=test.limitations, **kw)


def _measured(test: test_registry.Test, model: model_registry.Model,
              pool: Population, value: float, detail: str,
              **extra: Any) -> states.Result:
    state, limit, source = _verdict(model, test.test_id, value)
    # `extra` wins over the assembled provenance, so a handler that knows
    # better than the default — a single-period stability result, a
    # limitation only this test carries — states it once rather than
    # colliding with it.
    return states.measured(
        test.test_id, state, value, limit=limit, limit_source=source,
        detail=detail, **{**_common(test, model, pool), **extra})


# ============================================================ data quality


@handles("DATA-ROWS")
def _rows(test: test_registry.Test, model: model_registry.Model,
          pool: Population, **kw: Any) -> states.Result:
    """The population, and what each filter removes from it.

    A validation result that quotes 24,119 observations is quoting a number
    that survived several silent filters. This states them, in order, so the
    reader can see where the other thirty thousand rows went.
    """
    frame = pool.frame
    steps: list[dict[str, Any]] = [
        {"step": "rows read", "rows": len(frame), "removed": 0}]
    remaining = len(frame)

    matured = frame
    if model.matured_column in frame.columns:
        matured = frame[frame[model.matured_column].fillna(False).astype(bool)]
        steps.append({"step": "performance window closed",
                      "rows": len(matured),
                      "removed": remaining - len(matured)})
        remaining = len(matured)

    if model.outcome_column in matured.columns:
        with_outcome = matured[matured[model.outcome_column].notna()]
        steps.append({"step": "outcome recorded", "rows": len(with_outcome),
                      "removed": remaining - len(with_outcome)})
        remaining = len(with_outcome)
        matured = with_outcome

    if model.score_column and model.score_column in matured.columns:
        scored = matured[matured[model.score_column].notna()]
        steps.append({"step": "score present", "rows": len(scored),
                      "removed": remaining - len(scored)})
        remaining = len(scored)

    retained = remaining / len(frame) if len(frame) else 0.0
    return _measured(
        test, model, pool, retained,
        detail=(f"{remaining:,} of {len(frame):,} rows survive every filter, "
                f"{retained:.1%}. "
                + (", ".join(f"{s['step']} removed {s['removed']:,}"
                             for s in steps[1:] if s["removed"])
                   or "No filter removed anything.")),
        observations=len(frame), table=steps,
        chart={"kind": test_registry.CHART_WATERFALL, "steps": steps}, **kw)


@handles("DATA-MISSING")
def _missing(test: test_registry.Test, model: model_registry.Model,
             pool: Population, **kw: Any) -> states.Result:
    """Missingness per characteristic, and per period.

    Reported per period rather than pooled, because a variable that stopped
    arriving in March reads as 8% missing over three years and 100% missing
    in the month a decision is being taken on.
    """
    columns = list(model.binned_variables) or [
        c for c in pool.frame.columns
        if pd.api.types.is_numeric_dtype(pool.frame[c])][:20]
    if not columns:
        return states.unavailable(
            test.test_id, what="any characteristic to measure",
            **_common(test, model, pool, **kw))

    rows: list[dict[str, Any]] = []
    heat: list[dict[str, Any]] = []
    for name in columns:
        if name not in pool.frame.columns:
            continue
        overall = float(pool.frame[name].isna().mean())
        special = 0.0
        bin_column = f"{name}_bin"
        if bin_column in pool.frame.columns:
            special = float(
                pool.frame[bin_column].isin(binning.SPECIAL_BINS).mean())
        rows.append({"variable": name, "missing_rate": round(overall, 6),
                     "special_bin_rate": round(special, 6)})
        for period in pool.periods:
            part = _period_slice(model, pool, period)
            if part is None or name not in part.columns:
                continue
            heat.append({"variable": name, "period": period,
                         "missing_rate": round(
                             float(part[name].isna().mean()), 6)})
    if not rows:
        return states.unavailable(
            test.test_id, what="any characteristic to measure",
            **_common(test, model, pool, **kw))

    rows.sort(key=lambda r: r["missing_rate"], reverse=True)
    worst = rows[0]
    return _measured(
        test, model, pool, worst["missing_rate"],
        detail=(f"{worst['variable']} is missing on "
                f"{worst['missing_rate']:.2%} of rows, the highest of "
                f"{len(rows)} characteristics. "
                + (f"{sum(1 for r in rows if r['missing_rate'] > 0.05)} are "
                   "missing on more than 5%."
                   if any(r["missing_rate"] > 0.05 for r in rows)
                   else "No characteristic is missing on more than 5%.")),
        observations=len(pool.frame), table=rows,
        chart={"kind": test_registry.CHART_HEATMAP, "cells": heat}, **kw)


@handles("DATA-DUPLICATES")
def _duplicates(test: test_registry.Test, model: model_registry.Model,
                pool: Population, **kw: Any) -> states.Result:
    """Whether the declared grain holds.

    A duplicated key is not a cosmetic problem. Every rate in this report is
    a count divided by a row count, so a book with 2% duplicate keys has
    every one of those rates wrong by an unknown amount in an unknown
    direction.
    """
    keys = [c for c in pool.frame.columns
            if c.endswith("_id") or c == model.period_field]
    grain = [c for c in keys if c.endswith("_id")][:1] + [model.period_field]
    grain = [c for c in grain if c in pool.frame.columns]
    if not grain:
        return states.unavailable(
            test.test_id, what="a declared primary key to test the grain on",
            **_common(test, model, pool, **kw))

    duplicated = pool.frame.duplicated(subset=grain, keep=False)
    count = int(duplicated.sum())
    rate = count / len(pool.frame) if len(pool.frame) else 0.0
    examples: list[dict[str, Any]] = []
    if count:
        offenders = (pool.frame.loc[duplicated, grain]
                     .value_counts().head(20).reset_index())
        examples = offenders.to_dict("records")
    return _measured(
        test, model, pool, rate,
        detail=(f"{count:,} of {len(pool.frame):,} rows share a "
                f"({', '.join(grain)}) key, {rate:.4%}. "
                + ("The declared grain does not hold, so every rate computed "
                   "on this population is wrong by an unknown amount."
                   if count else "The declared grain holds.")),
        observations=len(pool.frame), table=examples,
        lineage={"grain": grain}, **kw)


@handles("DATA-REPRESENTATIVE")
def _representative(test: test_registry.Test, model: model_registry.Model,
                    pool: Population, **kw: Any) -> states.Result:
    """Whether the book being scored still resembles the one fitted on.

    Measured across the segmentation variables rather than the model inputs,
    because CSI already covers the inputs. This asks a different question:
    is the model being applied to a population it never saw?
    """
    try:
        reference = population(
            model, periods=available_periods(
                model, dataset=model.reference_dataset),
            dataset=model.reference_dataset)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    rows: list[dict[str, Any]] = []
    for field in model.segmentation_fields:
        if field not in pool.frame.columns or \
                field not in reference.frame.columns:
            continue
        then = reference.frame[field].value_counts(normalize=True)
        now = pool.frame[field].value_counts(normalize=True)
        for level in sorted(set(then.index) | set(now.index)):
            before = float(then.get(level, 0.0))
            after = float(now.get(level, 0.0))
            rows.append({
                "variable": field, "level": str(level),
                "development_share": round(before, 6),
                "current_share": round(after, 6),
                "change": round(after - before, 6),
                "unseen_at_development": before == 0.0 and after > 0.0,
            })
    if not rows:
        return states.unavailable(
            test.test_id,
            what="a segmentation variable present in both populations",
            **_common(test, model, pool, **kw))

    worst = max(rows, key=lambda r: abs(r["change"]))
    unseen = [r for r in rows if r["unseen_at_development"]]
    return _measured(
        test, model, pool, abs(worst["change"]),
        detail=(f"{worst['variable']}={worst['level']} has moved most, from "
                f"{worst['development_share']:.1%} of the development "
                f"population to {worst['current_share']:.1%} of the current "
                f"one. "
                + (f"{len(unseen)} level(s) appear now that did not exist at "
                   f"development: "
                   f"{', '.join(r['level'] for r in unseen[:5])} — the model "
                   "has no fitted evidence for them."
                   if unseen else
                   "Every level present now was present at development.")),
        observations=len(pool.frame),
        reference_period=_period_label(reference),
        table=sorted(rows, key=lambda r: abs(r["change"]), reverse=True),
        chart={"kind": test_registry.CHART_DISTRIBUTION, "levels": rows},
        **kw)


@handles("DATA-COVERAGE")
def _coverage(test: test_registry.Test, model: model_registry.Model,
              pool: Population, **kw: Any) -> states.Result:
    """Which periods and segments carry enough data to be assessed at all.

    The headline is the share of period-and-segment cells that clear the
    minimums, because a validation that quotes one portfolio number over a
    book where two thirds of the cells are too small to measure has not
    validated those cells — it has averaged over them.
    """
    ready = set(matured_periods(model))
    field = model.segmentation_fields[0] \
        if model.segmentation_fields else ""
    cells: list[dict[str, Any]] = []
    for period in pool.periods:
        part = _period_slice(model, pool, period)
        if part is None:
            continue
        groups = ([(str(level), block)
                   for level, block in part.groupby(field, observed=True)]
                  if field and field in part.columns
                  else [("ALL", part)])
        for level, block in groups:
            events = (int(block[model.outcome_column].fillna(0).sum())
                      if model.outcome_column in block.columns else 0)
            cells.append({
                "period": period, "segment": level,
                "observations": len(block), "events": events,
                "matured": period in ready,
                "assessable": (period in ready
                               and len(block) >= test_registry.MIN_OBS
                               and events >= test_registry.MIN_EVENTS),
            })
    if not cells:
        return states.unavailable(test.test_id, what="any period to assess",
                                  **_common(test, model, pool, **kw))

    assessable = sum(1 for c in cells if c["assessable"])
    share = assessable / len(cells)
    return _measured(
        test, model, pool, share,
        detail=(f"{assessable} of {len(cells)} period-and-segment cells "
                f"carry enough matured data to be measured, {share:.1%}. "
                f"The rest are reported as not matured or insufficient "
                f"sample, never as a result."),
        observations=len(pool.frame), table=cells,
        chart={"kind": test_registry.CHART_HEATMAP, "cells": cells},
        lineage={"minimum_observations": test_registry.MIN_OBS,
                 "minimum_events": test_registry.MIN_EVENTS}, **kw)


def _period_slice(model: model_registry.Model, pool: Population,
                  period: str) -> pd.DataFrame | None:
    """One period out of a loaded pool.

    The partition column is consumed by the reader, so the pool is re-read
    per period. The partition cache in `runner` makes that a dictionary
    lookup rather than a disk read.
    """
    try:
        return population(model, periods=(period,), dataset=pool.dataset,
                          matured_only=False).frame
    except PopulationError:
        return None


# ==================================================== conceptual soundness


#: What a validator must be able to read before a quantitative result means
#: anything. Each entry is a field on the model record and the question it
#: answers. Absence is recorded as NOT RECORDED — never inferred, never
#: filled in from a plausible default, because a default here is a
#: fabricated governance record.
CONCEPTUAL_EVIDENCE: dict[str, tuple[tuple[str, str], ...]] = {
    "CONC-PURPOSE": (
        ("intended_use", "what the model is for"),
        ("portfolio", "which book it is applied to"),
        ("owner", "who owns it"),
        ("validation_owner", "who validates it"),
        ("materiality", "how much rides on it"),
        ("tier", "what governance tier it sits in"),
    ),
    "CONC-DEFAULT": (
        ("default_definition", "what counts as a default"),
        ("outcome_column", "which field records that it happened"),
        ("performance_window_months", "over what horizon"),
    ),
    "CONC-WINDOWS": (
        ("observation_window", "when the characteristics are measured"),
        ("performance_window_months", "how long the outcome window runs"),
        ("development_population", "which cohorts it was fitted on"),
    ),
    "CONC-DIRECTION": (
        ("score_direction", "which way is good"),
        ("score_range", "what the scale is"),
    ),
    "CONC-DOCUMENTATION": (
        ("reference_number", "the model's registry reference"),
        ("version", "the approved version"),
        ("development_population", "the development sample"),
        ("default_definition", "the target definition"),
        ("known_limitations", "the limitations already accepted"),
        ("registry_key", "the governance record this points at"),
    ),
}


@handles(*CONCEPTUAL_EVIDENCE)
def _conceptual(test: test_registry.Test, model: model_registry.Model,
                pool: Population, **kw: Any) -> states.Result:
    """Conceptual soundness as an evidence checklist, not an opinion.

    These tests are qualitative, and the honest machine contribution to a
    qualitative test is not a judgement — it is the evidence, assembled, with
    everything absent marked absent. A validator reads the checklist and
    forms the opinion. What this must never do is produce a green tick
    because nothing contradicted it.

    Two of the five carry a real quantitative check as well, because two of
    the five can be wrong in a way arithmetic can see: a declared score
    direction that the data contradicts, and a declared performance window
    that the data does not run long enough to support. Those are computed
    and reported alongside the checklist.
    """
    items: list[dict[str, Any]] = []
    for field, question in CONCEPTUAL_EVIDENCE[test.test_id]:
        value = getattr(model, field, None)
        recorded = value not in (None, "", (), [], 0)
        items.append({
            "evidence": field, "answers": question,
            "recorded": recorded,
            "value": (str(value) if recorded else "NOT RECORDED"),
        })

    contradiction = _conceptual_check(test.test_id, model, pool)
    if contradiction:
        items.append(contradiction)

    recorded = sum(1 for i in items if i["recorded"])
    share = recorded / len(items)
    missing = [i["evidence"] for i in items if not i["recorded"]]
    detail = (
        f"{recorded} of {len(items)} pieces of evidence are recorded. "
        + (f"Not recorded: {', '.join(missing)}. Each is marked NOT RECORDED "
           "rather than assumed — a validator supplies these, this does not."
           if missing else
           "Everything this test looks for is on the record. Whether it is "
           "*right* is a judgement for the validator; this establishes only "
           "that there is something to judge."))
    if contradiction and not contradiction["recorded"]:
        detail = f"{contradiction['value']} {detail}"

    return _measured(
        test, model, pool, share, detail=detail,
        observations=len(pool.frame), table=items,
        remedy=("Record the missing evidence on the model registry entry "
                "before relying on the quantitative results below it."
                if missing else ""),
        lineage={"assessment": "evidence completeness, not an opinion",
                 "judgement_belongs_to": model.validation_owner
                 or "the validation owner"}, **kw)


def _conceptual_check(test_id: str, model: model_registry.Model,
                      pool: Population) -> dict[str, Any] | None:
    """The part of a qualitative test that arithmetic can settle."""
    if test_id == "CONC-DIRECTION":
        if model.score_column not in pool.frame.columns or \
                model.outcome_column not in pool.frame.columns:
            return None
        # On the matured window specifically. This test needs no outcome, so
        # its population is every period the book has — and asking a metric
        # that compares prediction against outcome to run on cohorts with no
        # outcome yet makes it raise, which would drop the one part of this
        # qualitative test that arithmetic can settle.
        try:
            ready = population(model, periods=matured_periods(model))
            made = kernels.discrimination(
                ready.frame, score=model.score_column,
                target=model.outcome_column,
                score_direction=model.score_direction)
        except (PopulationError, kernels.MetricError,
                kernels.ImmatureCohortError):
            return None
        agrees = made.auc >= 0.5
        return {
            "evidence": "declared direction against the data",
            "answers": "whether the sign convention is the one the data shows",
            "recorded": agrees,
            "value": (f"The declared direction "
                      f"{model.score_direction} gives an AUC of "
                      f"{made.auc:.4f}. "
                      + ("The data agrees with the declaration."
                         if agrees else
                         "An AUC below 0.5 means the declared direction is "
                         "inverted: every metric in this report is being "
                         "computed against the wrong sign, and the ordering "
                         "is better than it appears, not worse.")),
        }
    if test_id == "CONC-WINDOWS":
        horizon = model.performance_window_months
        matured = len(matured_periods(model))
        total = len(available_periods(model))
        enough = matured > 0
        return {
            "evidence": "declared horizon against the data",
            "answers": "whether the outcome window has closed on anything",
            "recorded": enough,
            "value": (f"A {horizon}-month performance window over {total} "
                      f"periods leaves {matured} matured and "
                      f"{total - matured} still open. "
                      + ("" if enough else
                         "Nothing has matured, so nothing in this report "
                         "compares a prediction against an outcome.")),
        }
    return None


# ============================================================ through time


@handles("DISC-TREND")
def _discrimination_trend(test: test_registry.Test,
                          model: model_registry.Model, pool: Population,
                          **kw: Any) -> states.Result:
    """AUC and KS per matured cohort, with the evidence behind each point.

    Points computed on too little data are carried but flagged rather than
    dropped, because a trend line that silently omits its thin months is a
    trend line with a hole in it exactly where the book was smallest.
    """
    series = _per_period(
        model, pool,
        lambda frame: _discrimination_point(model, frame))
    usable = [p for p in series if p.get("auc") is not None
              and p["events"] >= test_registry.MIN_EVENTS]
    if len(usable) < 2:
        return states.insufficient(
            test.test_id, observations=pool.rows,
            events=sum(p["events"] for p in series),
            minimum_observations=test_registry.MIN_OBS,
            minimum_events=test_registry.MIN_EVENTS * 2,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    first, last = usable[0], usable[-1]
    change = last["auc"] - first["auc"]
    return _measured(
        test, model, pool, change,
        detail=(f"AUC moved from {first['auc']:.4f} in {first['period']} to "
                f"{last['auc']:.4f} in {last['period']}, a change of "
                f"{change:+.4f} across {len(usable)} measurable cohorts. "
                + (f"{len(series) - len(usable)} cohort(s) carried too few "
                   "events to measure and are shown without a value."
                   if len(series) > len(usable) else "")),
        observations=pool.rows, table=series,
        chart={"kind": test_registry.CHART_TREND, "series": series,
               "measures": ["auc", "ks"]}, **kw)


@handles("CAL-DRIFT")
def _calibration_trend(test: test_registry.Test, model: model_registry.Model,
                       pool: Population, **kw: Any) -> states.Result:
    """O/E per matured cohort. Where a recalibration becomes visible."""
    series = _per_period(model, pool,
                         lambda frame: _calibration_point(model, frame))
    usable = [p for p in series if p.get("observed_over_expected") is not None
              and p["events"] >= test_registry.MIN_EVENTS]
    if len(usable) < 2:
        return states.insufficient(
            test.test_id, observations=pool.rows,
            events=sum(p["events"] for p in series),
            minimum_observations=test_registry.MIN_OBS,
            minimum_events=test_registry.MIN_EVENTS * 2,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    first, last = usable[0], usable[-1]
    change = last["observed_over_expected"] - first["observed_over_expected"]
    return _measured(
        test, model, pool, change,
        detail=(f"O/E moved from {first['observed_over_expected']:.3f} in "
                f"{first['period']} to {last['observed_over_expected']:.3f} "
                f"in {last['period']}, a change of {change:+.3f} across "
                f"{len(usable)} measurable cohorts. A drifting O/E is a "
                "recalibration question; a stable one that is not 1.0 is a "
                "level question. They have different answers."),
        observations=pool.rows, table=series,
        chart={"kind": test_registry.CHART_TREND, "series": series,
               "measures": ["observed_over_expected"]}, **kw)


@handles("STAB-ROLLING")
def _rolling(test: test_registry.Test, model: model_registry.Model,
             pool: Population, **kw: Any) -> states.Result:
    """Discrimination over a rolling window rather than a single cohort.

    A single month of this book carries a few dozen defaults, and an AUC on
    a few dozen defaults moves several points on noise alone. Rolling three
    cohorts together answers the question the single-cohort series cannot:
    is this trending, or is it varying?
    """
    ready = [p for p in pool.periods if p in set(matured_periods(model))]
    if len(ready) < ROLLING_WINDOW + 1:
        return states.insufficient(
            test.test_id, observations=pool.rows, events=0,
            minimum_observations=test_registry.MIN_OBS,
            minimum_events=test_registry.MIN_EVENTS,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    series: list[dict[str, Any]] = []
    for end in range(ROLLING_WINDOW, len(ready) + 1):
        window = tuple(ready[end - ROLLING_WINDOW:end])
        try:
            block = population(model, periods=window).frame
        except PopulationError:
            continue
        point = _discrimination_point(model, block)
        point.update(_calibration_point(model, block))
        point["period"] = f"{window[0]}..{window[-1]}"
        series.append(point)

    usable = [p for p in series if p.get("auc") is not None]
    if len(usable) < 2:
        return states.insufficient(
            test.test_id, observations=pool.rows, events=0,
            minimum_observations=test_registry.MIN_OBS,
            minimum_events=test_registry.MIN_EVENTS,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    values = [p["auc"] for p in usable]
    slope = _slope(values)
    spread = max(values) - min(values)
    return _measured(
        test, model, pool, slope,
        detail=(f"Rolling {ROLLING_WINDOW}-cohort AUC runs from "
                f"{values[0]:.4f} to {values[-1]:.4f} across "
                f"{len(usable)} windows, a least-squares slope of "
                f"{slope:+.5f} per window against a spread of {spread:.4f}. "
                + ("The movement is larger than the trend, which reads as "
                   "variation rather than deterioration."
                   if abs(slope) * len(values) < spread / 2 else
                   "The trend accounts for most of the movement, which reads "
                   "as deterioration rather than noise.")),
        observations=pool.rows, table=series,
        chart={"kind": test_registry.CHART_TREND, "series": series,
               "measures": ["auc", "observed_over_expected"]},
        lineage={"window_cohorts": ROLLING_WINDOW}, **kw)


def _per_period(model: model_registry.Model, pool: Population,
                point_of: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for period in pool.periods:
        frame = _period_slice(model, pool, period)
        if frame is None or not len(frame):
            continue
        row: dict[str, Any] = {"period": period}
        row.update(point_of(frame))
        out.append(row)
    return out


def _discrimination_point(model: model_registry.Model,
                          frame: pd.DataFrame) -> dict[str, Any]:
    events = (int(frame[model.outcome_column].fillna(0).sum())
              if model.outcome_column in frame.columns else 0)
    base = {"observations": len(frame), "events": events,
            "auc": None, "ks": None}
    try:
        made = kernels.discrimination(
            frame, score=model.score_column, target=model.outcome_column,
            score_direction=model.score_direction)
    except (kernels.MetricError, kernels.ImmatureCohortError):
        return base
    return {**base, "auc": round(made.auc, 6), "ks": round(made.ks, 6),
            "evidence": made.evidence}


def _calibration_point(model: model_registry.Model,
                       frame: pd.DataFrame) -> dict[str, Any]:
    events = (int(frame[model.outcome_column].fillna(0).sum())
              if model.outcome_column in frame.columns else 0)
    base = {"observations": len(frame), "events": events,
            "observed_over_expected": None}
    if not model.pd_column or model.pd_column not in frame.columns:
        return base
    try:
        made = kernels.calibration(
            frame, pd_column=model.pd_column, target=model.outcome_column)
    except (kernels.MetricError, kernels.ImmatureCohortError):
        return base
    ratio = (made.observed_rate / made.predicted_rate
             if made.predicted_rate else None)
    return {**base,
            "observed_rate": round(made.observed_rate, 6),
            "predicted_rate": round(made.predicted_rate, 6),
            "observed_over_expected": (round(ratio, 6) if ratio else None)}


def _slope(values: list[float]) -> float:
    """Least-squares slope. The one piece of arithmetic that is not a kernel.

    It is a line fit over a series this module produced, not a credit-risk
    measure, and putting it in the metrics kernel would suggest otherwise.
    """
    n = len(values)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype="float64")
    y = np.asarray(values, dtype="float64")
    return float(((x - x.mean()) * (y - y.mean())).sum()
                 / ((x - x.mean()) ** 2).sum())


# ============================================================== stability


@handles("STAB-BAND")
def _band_stability(test: test_registry.Test, model: model_registry.Model,
                    pool: Population, **kw: Any) -> states.Result:
    """Whether the shape of the grade distribution has changed.

    Close to PSI and deliberately separate from it. PSI answers "how much has
    it moved", in one number that says nothing about direction. This answers
    "which grades" and "which way", which is what a limit-management or
    staging decision actually turns on.
    """
    try:
        reference = population(
            model, periods=available_periods(
                model, dataset=model.reference_dataset),
            dataset=model.reference_dataset)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    edges = _bands(model)
    then = pd.cut(reference.frame[model.score_column], bins=edges)
    now = pd.cut(pool.frame[model.score_column], bins=edges)
    before = then.value_counts(normalize=True, sort=False)
    after = now.value_counts(normalize=True, sort=False)
    rows = [{
        "band": str(band),
        "development_share": round(float(before.get(band, 0.0)), 6),
        "current_share": round(float(after.get(band, 0.0)), 6),
        "change": round(float(after.get(band, 0.0))
                        - float(before.get(band, 0.0)), 6),
    } for band in before.index]

    worst = max(rows, key=lambda r: abs(r["change"]))
    downward = sum(r["change"] for r in rows[:len(rows) // 2])
    return _measured(
        test, model, pool, abs(worst["change"]),
        detail=(f"The largest shift is in band {worst['band']}, from "
                f"{worst['development_share']:.1%} to "
                f"{worst['current_share']:.1%}, "
                f"{worst['change']:+.1%}. The lower half of the scale holds "
                f"{downward:+.1%} of the book relative to development — "
                + ("a migration toward the weaker grades."
                   if downward > 0.005 else
                   "a migration toward the stronger grades."
                   if downward < -0.005 else
                   "no material migration between halves of the scale.")),
        observations=len(pool.frame),
        reference_period=_period_label(reference), table=rows,
        chart={"kind": test_registry.CHART_DISTRIBUTION, "bands": rows},
        **kw)


# ============================================================== variables


def _matured(model: model_registry.Model,
             pool: Population) -> pd.DataFrame | None:
    """The matured rows of this pool, or None if there are none.

    For the tests that run on the whole book because they need no outcome to
    *exist*, but still compare something against one where it does. Reading
    the outcome straight off `pool.frame` would divide the defaults of the
    matured cohorts by the rows of all of them.
    """
    if pool.periods and set(pool.periods) <= set(matured_periods(model)):
        return pool.frame
    ready = tuple(p for p in pool.periods if p in set(matured_periods(model)))
    if not ready:
        return None
    try:
        return population(model, periods=ready, dataset=pool.dataset).frame
    except PopulationError:
        return None


@handles("VAR-WOE")
def _woe_shape(test: test_registry.Test, model: model_registry.Model,
               pool: Population, **kw: Any) -> states.Result:
    """Whether each variable's bins still run the way credit sense expects.

    Monotonicity is checked on the *observed* bad rate against the approved
    weight of evidence. A binning that was monotonic at development and is
    not monotonic now has a bin whose risk has reversed, and the model is
    still scoring it with the old sign.
    """
    try:
        spec = model.approved_spec()
    except Exception as e:  # noqa: BLE001 - reported as a refusal
        return states.unavailable(
            test.test_id, what=f"the approved binning specification ({e})",
            **_common(test, model, pool, **kw))

    # The observed bad rate has to come from cohorts whose window has closed.
    # This test needs no outcome to *run* — the bins are there either way —
    # so its population is the whole book, and a bad rate taken over that
    # would divide the defaults of sixteen matured cohorts by the rows of
    # thirty-six.
    ready = _matured(model, pool)
    if ready is None:
        return states.not_matured(
            test.test_id, period=_period_label(pool),
            closes=pool.closes or "the recorded window close month",
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k != "period"})

    rows: list[dict[str, Any]] = []
    for name in model.binned_variables:
        approved = spec.variables.get(name)
        bin_column = f"{name}_bin"
        if approved is None or bin_column not in ready.columns:
            continue
        if model.outcome_column not in ready.columns:
            continue
        bins: list[dict[str, Any]] = []
        for one in approved.bins:
            part = ready[ready[bin_column] == one.bin_id]
            outcome = part[model.outcome_column].dropna()
            bins.append({
                "bin_id": one.bin_id, "label": one.label,
                "approved_woe": round(one.woe, 6),
                "approved_bad_rate": round(one.bad_rate, 6),
                "observations": len(part),
                "matured_observations": len(outcome),
                "observed_bad_rate": (round(float(outcome.mean()), 6)
                                      if len(outcome) else None),
                "special": one.special,
            })
        ordered = [b for b in bins
                   if not b["special"] and b["observed_bad_rate"] is not None]
        ordered.sort(key=lambda b: b["approved_woe"], reverse=True)
        observed = [b["observed_bad_rate"] for b in ordered]
        inversions = sum(1 for a, b in zip(observed, observed[1:], strict=False)
                         if b < a)
        rows.append({
            "variable": name,
            "monotonic_at_approval": approved.monotonic,
            "bins_compared": len(ordered),
            "inversions": inversions,
            "still_monotonic": inversions == 0,
            "bins": bins,
        })

    if not rows:
        return states.unavailable(
            test.test_id,
            what=("approved bins with a matured outcome to check the "
                  "direction against"),
            **_common(test, model, pool, **kw))

    broken = [r for r in rows
              if r["monotonic_at_approval"] and not r["still_monotonic"]]
    return _measured(
        test, model, pool, float(len(broken)),
        detail=(f"{len(broken)} of {len(rows)} characteristics were monotonic "
                f"at approval and are not monotonic now"
                + (f": {', '.join(r['variable'] for r in broken)}. Each has "
                   "at least one bin whose risk has reversed while the model "
                   "still scores it with the approved sign."
                   if broken else
                   ". Every approved ordering still holds on the data.")),
        observations=len(pool.frame),
        table=[{k: v for k, v in r.items() if k != "bins"} for r in rows],
        chart={"kind": test_registry.CHART_WOE, "variables": rows}, **kw)


@handles("VAR-OCCUPANCY")
def _occupancy(test: test_registry.Test, model: model_registry.Model,
               pool: Population, **kw: Any) -> states.Result:
    """Whether any approved bin has emptied out.

    An empty bin is not harmless. Its weight of evidence is still in the
    equation, so the model still carries a fitted opinion about a population
    it no longer sees — and the first time that population returns, it will
    be scored on evidence from a book that no longer exists.
    """
    rows: list[dict[str, Any]] = []
    for name in model.binned_variables:
        bin_column = f"{name}_bin"
        if bin_column not in pool.frame.columns:
            continue
        shares = pool.frame[bin_column].value_counts(normalize=True)
        counts = pool.frame[bin_column].value_counts()
        for bin_id, share in shares.items():
            events = 0
            if model.outcome_column in pool.frame.columns:
                events = int(pool.frame.loc[
                    pool.frame[bin_column] == bin_id,
                    model.outcome_column].fillna(0).sum())
            rows.append({
                "variable": name, "bin_id": str(bin_id),
                "share": round(float(share), 6),
                "observations": int(counts.get(bin_id, 0)),
                "events": events,
                "sparse": float(share) < SPARSE_BIN_SHARE,
                "special": str(bin_id) in binning.SPECIAL_BINS,
            })
    if not rows:
        return states.unavailable(test.test_id, what="the approved bin columns",
                                  **_common(test, model, pool, **kw))

    sparse = [r for r in rows if r["sparse"] and not r["special"]]
    share = len(sparse) / len(rows)
    return _measured(
        test, model, pool, share,
        detail=(f"{len(sparse)} of {len(rows)} approved bins now hold less "
                f"than {SPARSE_BIN_SHARE:.0%} of the book"
                + (f", the emptiest being "
                   f"{sparse[0]['variable']}/{sparse[0]['bin_id']} at "
                   f"{min(r['share'] for r in sparse):.3%}. Their fitted "
                   "weights are still in the equation."
                   if sparse else
                   ". Every approved bin still carries a usable population.")),
        observations=len(pool.frame),
        table=sorted(rows, key=lambda r: r["share"]),
        chart={"kind": test_registry.CHART_DISTRIBUTION, "bins": rows},
        lineage={"sparse_below": SPARSE_BIN_SHARE}, **kw)


@handles("VAR-SIGN")
def _sign(test: test_registry.Test, model: model_registry.Model,
          pool: Population, **kw: Any) -> states.Result:
    """Whether any variable is scored against its credit sense.

    A coefficient with the wrong sign is not a calibration issue. It means
    the model is rewarding the thing that predicts default, and it will keep
    doing so consistently and confidently on every application it sees.

    The check is a comparison, not an opinion: the fitted coefficient's sign
    against the sign the univariate relationship in the data implies. A
    disagreement is reported with both numbers so the reader can see which
    one they disbelieve.
    """
    try:
        equation = model.approved_equation()
    except model_registry.ModelError as e:
        return states.not_applicable(test.test_id, why=str(e),
                                     **_common(test, model, pool, **kw))

    ready = _matured(model, pool)
    if ready is None:
        return states.not_matured(
            test.test_id, period=_period_label(pool),
            closes=pool.closes or "the recorded window close month",
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k != "period"})

    rows: list[dict[str, Any]] = []
    for term in equation.terms:
        column = term.column()
        if column not in ready.columns or \
                model.outcome_column not in ready.columns:
            continue
        try:
            made = kernels.variable_discrimination(
                ready, variable=term.variable, target=model.outcome_column)
        except (kernels.MetricError, kernels.ImmatureCohortError):
            continue
        if made.get("auc") is None:
            continue
        # The kernel measures on WoE, oriented so higher is better; risk is
        # its negative. A WoE term in a bad-outcome logit should therefore
        # carry a negative coefficient. The data's own sign comes from
        # whether the WoE separates in the direction the fit assumed.
        implied = -1.0 if made["auc"] >= 0.5 else 1.0
        fitted = -1.0 if term.coefficient < 0 else 1.0
        rows.append({
            "variable": term.variable,
            "column": column,
            "coefficient": round(float(term.coefficient), 8),
            "fitted_sign": "negative" if fitted < 0 else "positive",
            "univariate_auc": made["auc"],
            "implied_sign": "negative" if implied < 0 else "positive",
            "agrees": fitted == implied,
        })
    if not rows:
        return states.unavailable(
            test.test_id,
            what="the fitted columns and a matured outcome to check them on",
            **_common(test, model, pool, **kw))

    against = [r for r in rows if not r["agrees"]]
    return _measured(
        test, model, pool, float(len(against)),
        detail=(f"{len(against)} of {len(rows)} fitted terms carry a sign the "
                f"data does not support"
                + (f": {', '.join(r['variable'] for r in against)}. Each is "
                   "scored against its own univariate relationship, which "
                   "means the model is rewarding what predicts default."
                   if against else
                   ". Every fitted sign agrees with the univariate "
                   "relationship in the validation population.")),
        observations=len(pool.frame), table=rows,
        lineage={"equation": getattr(equation, "model_name", ""),
                 "specification": getattr(
                     equation, "binning_spec_version", ""),
                 "measured_on": "weight of evidence"}, **kw)


# ========================================================= usage/overrides


@handles("USE-MATRIX")
def _override_matrix(test: test_registry.Test, model: model_registry.Model,
                     pool: Population, **kw: Any) -> states.Result:
    """Where the overrides cluster, in which direction, and on what reason.

    The cross-tabulation is the finding here, not the total. A 10% override
    rate spread evenly across the scale is a policy; the same 10% sitting on
    the two bands either side of the cut-off is a cut-off nobody believes.
    """
    try:
        decisions = population(model, periods=pool.periods,
                               dataset=model.decisions_dataset,
                               matured_only=False)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    frame = decisions.frame
    for column in ("override_flag", "override_direction"):
        if column not in frame.columns:
            return states.unavailable(test.test_id, what=column,
                                      **_common(test, model, pool, **kw))

    cut = pd.cut(frame[model.score_column], bins=_bands(model))
    cells: list[dict[str, Any]] = []
    for band, part in frame.groupby(cut, observed=True):
        overridden = part[part["override_flag"].fillna(0).astype(bool)]
        for direction in ("UPWARD", "DOWNWARD"):
            block = overridden[overridden["override_direction"] == direction]
            cells.append({
                "band": str(band), "direction": direction,
                "observations": len(part), "overrides": len(block),
                "rate": round(len(block) / len(part), 6) if len(part) else 0.0,
            })

    reasons: list[dict[str, Any]] = []
    if "override_reason_code" in frame.columns:
        overridden = frame[frame["override_flag"].fillna(0).astype(bool)]
        counts = overridden["override_reason_code"].value_counts()
        reasons = [{"reason_code": str(code) or "NOT RECORDED",
                    "overrides": int(n),
                    "share": round(float(n) / max(len(overridden), 1), 6)}
                   for code, n in counts.items()]

    hottest = max(cells, key=lambda c: c["rate"]) if cells else None
    concentration = hottest["rate"] if hottest else 0.0
    unrecorded = next((r["share"] for r in reasons
                       if r["reason_code"] == "NOT RECORDED"), 0.0)
    return _measured(
        test, model, pool, concentration,
        detail=((f"Overrides concentrate in band {hottest['band']} "
                 f"{hottest['direction'].lower()}, at {concentration:.2%} of "
                 f"that band. " if hottest else "")
                + (f"{len(reasons)} reason codes are in use; "
                   f"{unrecorded:.1%} of overrides record no reason."
                   if reasons else
                   "No reason code is recorded against any override.")),
        observations=len(frame), table=cells + reasons,
        chart={"kind": test_registry.CHART_MATRIX, "cells": cells,
               "reasons": reasons}, **kw)


@handles("USE-CUTOFF")
def _cutoff(test: test_registry.Test, model: model_registry.Model,
            pool: Population, **kw: Any) -> states.Result:
    """The approval and bad-rate profile across candidate cut-offs.

    Exploratory, and labelled as such on the result: this recomputes what
    the book would have looked like at other cut-offs. It does not change,
    recommend or approve a policy cut-off, and the production cut-off is
    read from the model record rather than chosen here.
    """
    frame = pool.frame
    if model.score_column not in frame.columns or \
            model.outcome_column not in frame.columns:
        return states.unavailable(
            test.test_id, what="a score and a matured outcome",
            **_common(test, model, pool, **kw))

    outcome = frame[model.outcome_column]
    usable = frame[outcome.notna()]
    if not len(usable):
        return states.unavailable(test.test_id, what="a matured outcome",
                                  **_common(test, model, pool, **kw))

    total_events = float(usable[model.outcome_column].sum())
    rows: list[dict[str, Any]] = []
    for edge in _bands(model)[1:-1]:
        approved = usable[usable[model.score_column] >= edge]
        declined = usable[usable[model.score_column] < edge]
        approved_bad = (float(approved[model.outcome_column].mean())
                        if len(approved) else 0.0)
        rows.append({
            "cut_off": round(float(edge), 2),
            "approval_rate": round(len(approved) / len(usable), 6),
            "bad_rate_among_approvals": round(approved_bad, 6),
            "events_approved": int(approved[model.outcome_column].sum()),
            "events_declined": int(declined[model.outcome_column].sum()),
            "event_capture": round(
                float(declined[model.outcome_column].sum()) / total_events, 6)
            if total_events else 0.0,
            "is_current_policy": (model.cut_off is not None
                                  and abs(edge - model.cut_off) < 1e-9),
        })

    current = next((r for r in rows if r["is_current_policy"]), None)
    headline = (current["bad_rate_among_approvals"] if current
                else rows[len(rows) // 2]["bad_rate_among_approvals"])
    return _measured(
        test, model, pool, headline,
        detail=((f"At the recorded policy cut-off of {model.cut_off:.0f}, "
                 f"{current['approval_rate']:.1%} of the book is approved "
                 f"and {current['bad_rate_among_approvals']:.2%} of those "
                 f"approvals default, capturing "
                 f"{current['event_capture']:.1%} of all defaults in the "
                 "declines. " if current else
                 "No policy cut-off is recorded on this model, so the "
                 "profile is shown without one marked. ")
                + "The other rows are exploratory and change no policy."),
        observations=len(usable), table=rows,
        chart={"kind": test_registry.CHART_TREND, "series": rows,
               "measures": ["approval_rate", "bad_rate_among_approvals"]},
        limitations=(*test.limitations,
                     "Exploratory. Recomputing the book at another cut-off "
                     "does not propose one."), **kw)


# ========================================================= implementation


@handles("IMPL-REPLICATE")
def _replicate(test: test_registry.Test, model: model_registry.Model,
               pool: Population, **kw: Any) -> states.Result:
    """Recompute the score from the approved specification, row by row.

    The one test that asks whether the thing running in production is the
    thing that was approved. Everything else in this report validates the
    approved model; this validates that the approved model is what scored
    the book.
    """
    try:
        equation = model.approved_equation()
    except model_registry.ModelError as e:
        return states.not_applicable(test.test_id, why=str(e),
                                     **_common(test, model, pool, **kw))
    try:
        made = kernels.replicate(pool.frame, equation)
    except kernels.MetricError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    rate = made.mismatch_count / made.rows if made.rows else 0.0
    return _measured(
        test, model, pool, rate,
        detail=(f"{made.mismatch_count:,} of {made.rows:,} rows do not "
                f"reproduce from the approved specification within "
                f"{made.tolerance:g}, {rate:.4%}. Largest logit difference "
                f"{made.max_absolute_logit_difference:.3g}, largest score "
                f"difference {made.max_absolute_score_difference:.3g}. "
                + ("The production score is the score the specification "
                   "describes." if not made.mismatch_count else
                   "The production score is not the score the specification "
                   "describes, which makes every other result in this report "
                   "a result about a different model.")),
        observations=made.rows, table=[{
            "rows": made.rows,
            "mismatches": made.mismatch_count,
            "bin_mismatches": made.bin_mismatch_count,
            "max_logit_difference": made.max_absolute_logit_difference,
            "max_pd_difference": made.max_absolute_pd_difference,
            "max_score_difference": made.max_absolute_score_difference,
            "tolerance": made.tolerance,
        }],
        lineage={"equation": getattr(equation, "model_name", ""),
                 "specification": getattr(
                     equation, "binning_spec_version", "")}, **kw)


@handles("IMPL-VERSION")
def _version(test: test_registry.Test, model: model_registry.Model,
             pool: Population, **kw: Any) -> states.Result:
    """Whether the version that scored the book is the version approved."""
    columns = [c for c in pool.frame.columns
               if "model_version" in c or c == "scorecard_version"]
    if not columns:
        return states.unavailable(
            test.test_id, what="a model version stamped on the scored rows",
            remedy=("Stamp the approved version on every scored row. Until "
                    "then there is no evidence about which version produced "
                    "these scores, which is itself the finding."),
            **_common(test, model, pool, **kw))

    column = columns[0]
    counts = pool.frame[column].value_counts()
    rows = [{"version": str(v), "rows": int(n),
             "share": round(float(n) / len(pool.frame), 6),
             "is_approved": str(v) == model.version}
            for v, n in counts.items()]
    approved = sum(r["share"] for r in rows if r["is_approved"])
    return _measured(
        test, model, pool, approved,
        detail=(f"{approved:.1%} of rows were scored by the approved version "
                f"{model.version}. "
                + (f"The others carry: "
                   f"{', '.join(r['version'] for r in rows if not r['is_approved'])}."
                   if approved < 1.0 else
                   "No other version appears on the book.")),
        observations=len(pool.frame), table=rows, **kw)


# ===================================================== champion/challenger


@handles("CC-CALIBRATION")
def _cc_calibration(test: test_registry.Test, model: model_registry.Model,
                    pool: Population, **kw: Any) -> states.Result:
    """O/E and Brier for both models on the identical population.

    Identical is the word that matters. A challenger compared on a different
    window, or after a filter the champion did not get, is not a comparison.
    """
    if model.challenger_pd_column not in pool.frame.columns:
        return states.unavailable(
            test.test_id, what=model.challenger_pd_column,
            **_common(test, model, pool, **kw))
    champion = kernels.calibration(
        pool.frame, pd_column=model.pd_column, target=model.outcome_column,
        label="champion")
    challenger = kernels.calibration(
        pool.frame, pd_column=model.challenger_pd_column,
        target=model.outcome_column, label="challenger")

    champion_oe = (champion.observed_rate / champion.predicted_rate
                   if champion.predicted_rate else float("nan"))
    challenger_oe = (challenger.observed_rate / challenger.predicted_rate
                     if challenger.predicted_rate else float("nan"))
    improvement = champion.brier - challenger.brier
    return _measured(
        test, model, pool, improvement,
        detail=(f"Brier {champion.brier:.5f} for the champion against "
                f"{challenger.brier:.5f} for the challenger, an improvement "
                f"of {improvement:+.5f}. O/E {champion_oe:.3f} against "
                f"{challenger_oe:.3f}, on the same "
                f"{champion.observations:,} observations and "
                f"{champion.events:,} defaults. A better Brier with a worse "
                "O/E is a challenger that orders better and is calibrated "
                "worse — two decisions, not one."),
        observations=champion.observations, events=champion.events,
        table=[
            {"model": "champion", "brier": champion.brier,
             "observed_rate": champion.observed_rate,
             "predicted_rate": champion.predicted_rate,
             "observed_over_expected": round(champion_oe, 6),
             "slope": champion.slope},
            {"model": "challenger", "brier": challenger.brier,
             "observed_rate": challenger.observed_rate,
             "predicted_rate": challenger.predicted_rate,
             "observed_over_expected": round(challenger_oe, 6),
             "slope": challenger.slope},
        ],
        chart={"kind": test_registry.CHART_CALIBRATION,
               "champion": champion.buckets, "challenger": challenger.buckets},
        **kw)


@handles("CC-STABILITY")
def _cc_stability(test: test_registry.Test, model: model_registry.Model,
                  pool: Population, **kw: Any) -> states.Result:
    """Score PSI for both models against the same reference."""
    try:
        reference = population(
            model, periods=available_periods(
                model, dataset=model.reference_dataset),
            dataset=model.reference_dataset)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))
    if model.challenger_score_column not in reference.frame.columns:
        return states.unavailable(
            test.test_id,
            what=f"{model.challenger_score_column} on the reference population",
            **_common(test, model, pool, **kw))

    # The latest period, for the same reason STAB-PSI uses it: a pooled
    # three-year index averages the drift against the months before it
    # happened. Two stability tests on one screen reading 0.002 and 0.015
    # for the same model would be a defect in one of them.
    try:
        current = population(model, periods=(pool.periods[-1],),
                             matured_only=False)
    except PopulationError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))
    champion = kernels.psi(reference.frame, current.frame,
                           score=model.score_column)
    challenger = kernels.psi(reference.frame, current.frame,
                             score=model.challenger_score_column)
    difference = challenger.index - champion.index
    return _measured(
        test, model, pool, difference,
        detail=(f"Score PSI {champion.index:.4f} for the champion against "
                f"{challenger.index:.4f} for the challenger, a difference of "
                f"{difference:+.4f}. A challenger whose distribution has "
                "moved further than the champion's has an advantage measured "
                "on a book it is drifting away from."),
        observations=champion.current_rows, period=pool.periods[-1],
        reference_period=_period_label(reference),
        table=[{"model": "champion", "psi": champion.index},
               {"model": "challenger", "psi": challenger.index}],
        chart={"kind": test_registry.CHART_PSI_TREND,
               "champion": champion.bins, "challenger": challenger.bins},
        **kw)


@handles("CC-SWAPSET")
def _swapset(test: test_registry.Test, model: model_registry.Model,
             pool: Population, **kw: Any) -> states.Result:
    """Who changes side, and how they performed.

    Held at the same approval rate rather than the same score, because the
    two scores are on different scales and a comparison at the same number
    would be comparing a strict cut-off against a loose one and calling the
    difference a model improvement.
    """
    frame = pool.frame
    for column in (model.score_column, model.challenger_score_column,
                   model.outcome_column):
        if column not in frame.columns:
            return states.unavailable(test.test_id, what=column,
                                      **_common(test, model, pool, **kw))
    usable = frame[frame[model.outcome_column].notna()]
    if not len(usable):
        return states.unavailable(test.test_id, what="a matured outcome",
                                  **_common(test, model, pool, **kw))

    rate = 0.5
    if model.cut_off is not None:
        rate = float((usable[model.score_column] >= model.cut_off).mean())
    champion_cut = usable[model.score_column].quantile(1 - rate)
    challenger_cut = usable[model.challenger_score_column].quantile(1 - rate)

    champion_in = usable[model.score_column] >= champion_cut
    challenger_in = usable[model.challenger_score_column] >= challenger_cut

    cells: list[dict[str, Any]] = []
    for name, mask in (
            ("approved by both", champion_in & challenger_in),
            ("swap in — challenger only", ~champion_in & challenger_in),
            ("swap out — champion only", champion_in & ~challenger_in),
            ("declined by both", ~champion_in & ~challenger_in)):
        block = usable[mask]
        events = int(block[model.outcome_column].sum())
        cells.append({
            "set": name, "observations": len(block), "events": events,
            "bad_rate": round(events / len(block), 6) if len(block) else None,
        })

    swap_in = next(c for c in cells if c["set"].startswith("swap in"))
    swap_out = next(c for c in cells if c["set"].startswith("swap out"))
    if swap_in["bad_rate"] is None or swap_out["bad_rate"] is None:
        return states.insufficient(
            test.test_id, observations=len(usable), events=0,
            minimum_observations=test_registry.MIN_OBS,
            minimum_events=test.minimum_events,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    gain = swap_out["bad_rate"] - swap_in["bad_rate"]
    return _measured(
        test, model, pool, gain,
        detail=(f"At an equal approval rate of {rate:.1%}, the challenger "
                f"takes in {swap_in['observations']:,} accounts the champion "
                f"declined, defaulting at {swap_in['bad_rate']:.2%}, and "
                f"declines {swap_out['observations']:,} the champion "
                f"approved, defaulting at {swap_out['bad_rate']:.2%}. The "
                f"swap is worth {gain:+.2%} in bad rate on the accounts that "
                "change side."),
        observations=len(usable), table=cells,
        chart={"kind": test_registry.CHART_MATRIX, "cells": cells},
        lineage={"held_at": "equal approval rate",
                 "approval_rate": round(rate, 6),
                 "champion_cut_off": round(float(champion_cut), 4),
                 "challenger_cut_off": round(float(challenger_cut), 4)},
        **kw)


# ============================================================== robustness


@handles("ROB-BOOTSTRAP")
def _bootstrap(test: test_registry.Test, model: model_registry.Model,
               pool: Population, **kw: Any) -> states.Result:
    """How much of the measured AUC is sampling noise.

    A point estimate invites a comparison against a threshold as though the
    estimate were exact. The interval is what says whether the model is
    below its limit or merely might be, and those carry different decisions.

    The resample count and seed are module constants rather than arguments,
    because an interval that moves between runs cannot be filed as evidence.
    """
    frame = pool.frame[[model.score_column, model.outcome_column]].dropna()
    if len(frame) < test.minimum_observations:
        return states.insufficient(
            test.test_id, observations=len(frame),
            events=int(frame[model.outcome_column].sum()),
            minimum_observations=test.minimum_observations,
            minimum_events=test.minimum_events,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    point = kernels.discrimination(
        frame, score=model.score_column, target=model.outcome_column,
        score_direction=model.score_direction)
    try:
        interval = kernels.bootstrap_auc(
            frame, score=model.score_column, target=model.outcome_column,
            score_direction=model.score_direction,
            resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED)
    except kernels.MetricError as e:
        return states.unavailable(test.test_id, what=str(e),
                                  **_common(test, model, pool, **kw))

    point, draws = interval.point, interval.draws
    low, high = interval.lower, interval.upper
    width = high - low
    limit = model.limit_for("DISC-AUC")
    straddles = (limit is not None and low < limit.value < high)
    return _measured(
        test, model, pool, width,
        detail=(f"AUC {point:.4f}, 95% interval "
                f"[{low:.4f}, {high:.4f}] from {interval.resamples} "
                f"resamples at "
                f"seed {BOOTSTRAP_SEED}. Width {width:.4f}. "
                + (f"The interval straddles the {limit.value:.2f} limit, so "
                   "the measured result does not settle whether this model "
                   "is inside it."
                   if straddles else
                   "The interval does not cross the discrimination limit."
                   if limit is not None else
                   "No discrimination limit is configured to compare it "
                   "against.")),
        observations=interval.observations, events=interval.events,
        comparison_value=point,
        table=[interval.to_dict()],
        chart={"kind": test_registry.CHART_DISTRIBUTION, "draws": draws},
        lineage={"resamples": interval.resamples, "seed": BOOTSTRAP_SEED,
                 "interval": "percentile",
                 "confidence": interval.confidence}, **kw)


@handles("ROB-SEGMENT-EXCLUSION")
def _segment_exclusion(test: test_registry.Test, model: model_registry.Model,
                       pool: Population, **kw: Any) -> states.Result:
    """Whether one segment is carrying the headline result."""
    field = (kw.pop("segment_field", "")
             or (model.segmentation_fields[0]
                 if model.segmentation_fields else ""))
    if not field or field not in pool.frame.columns:
        return states.unavailable(
            test.test_id, what=f"a segmentation field ({field or 'none'})",
            **_common(test, model, pool, **kw))

    whole = kernels.discrimination(
        pool.frame, score=model.score_column, target=model.outcome_column,
        score_direction=model.score_direction)
    rows: list[dict[str, Any]] = []
    for level in sorted(pool.frame[field].dropna().unique()):
        rest = pool.frame[pool.frame[field] != level]
        try:
            made = kernels.discrimination(
                rest, score=model.score_column, target=model.outcome_column,
                score_direction=model.score_direction)
        except (kernels.MetricError, kernels.ImmatureCohortError):
            continue
        rows.append({
            "excluded": str(level),
            "share_of_book": round(
                float((pool.frame[field] == level).mean()), 6),
            "auc_without": round(made.auc, 6),
            "change": round(made.auc - whole.auc, 6),
        })
    if not rows:
        return states.unavailable(
            test.test_id, what=f"measurable subsets of {field}",
            **_common(test, model, pool, **kw))

    worst = max(rows, key=lambda r: abs(r["change"]))
    return _measured(
        test, model, pool, abs(worst["change"]),
        detail=(f"Excluding {worst['excluded']}, which is "
                f"{worst['share_of_book']:.1%} of the book, moves AUC from "
                f"{whole.auc:.4f} to {worst['auc_without']:.4f}, "
                f"{worst['change']:+.4f}. "
                + ("No single segment moves the headline by more than 0.02, "
                   "so the result is not resting on one part of the book."
                   if abs(worst["change"]) < 0.02 else
                   "The headline depends materially on this segment.")),
        observations=pool.rows, comparison_value=whole.auc, table=rows,
        chart={"kind": test_registry.CHART_TORNADO, "bars": rows,
               "baseline": whole.auc},
        segment=field, **kw)


@handles("ROB-WINDOW")
def _window(test: test_registry.Test, model: model_registry.Model,
            pool: Population, **kw: Any) -> states.Result:
    """Whether the result depends on where the observation window was drawn.

    Alternative contiguous windows of matured cohorts, not random subsets. A
    validator's question is not "would a different sample give this", it is
    "would last year's window have given this", and only contiguous windows
    answer that.
    """
    ready = [p for p in pool.periods if p in set(matured_periods(model))]
    if len(ready) < 4:
        return states.insufficient(
            test.test_id, observations=pool.rows, events=0,
            minimum_observations=test_registry.MIN_OBS,
            minimum_events=test_registry.MIN_EVENTS,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    whole = kernels.discrimination(
        pool.frame, score=model.score_column, target=model.outcome_column,
        score_direction=model.score_direction)
    half = max(len(ready) // 2, 2)
    windows = {
        "full window": tuple(ready),
        "first half": tuple(ready[:half]),
        "second half": tuple(ready[half:]),
        "most recent half": tuple(ready[-half:]),
    }
    rows: list[dict[str, Any]] = []
    for name, periods in windows.items():
        if not periods:
            continue
        try:
            frame = population(model, periods=periods).frame
            made = kernels.discrimination(
                frame, score=model.score_column, target=model.outcome_column,
                score_direction=model.score_direction)
        except (PopulationError, kernels.MetricError,
                kernels.ImmatureCohortError):
            continue
        rows.append({
            "window": name,
            "periods": f"{periods[0]}..{periods[-1]}",
            "observations": made.observations, "events": made.events,
            "auc": round(made.auc, 6),
            "change": round(made.auc - whole.auc, 6),
        })
    if len(rows) < 2:
        return states.insufficient(
            test.test_id, observations=pool.rows, events=whole.events,
            minimum_observations=test_registry.MIN_OBS,
            minimum_events=test_registry.MIN_EVENTS,
            **{k: v for k, v in _common(test, model, pool, **kw).items()
               if k not in ("observations", "events")})

    spread = max(r["auc"] for r in rows) - min(r["auc"] for r in rows)
    return _measured(
        test, model, pool, spread,
        detail=(f"AUC ranges over {spread:.4f} across {len(rows)} "
                f"contiguous windows, from "
                f"{min(r['auc'] for r in rows):.4f} to "
                f"{max(r['auc'] for r in rows):.4f}. "
                + ("The headline does not depend on where the window was "
                   "drawn." if spread < 0.03 else
                   "The headline depends materially on where the window was "
                   "drawn, so a single-window result should not be quoted "
                   "without it.")),
        observations=pool.rows, comparison_value=whole.auc, table=rows,
        chart={"kind": test_registry.CHART_TORNADO, "bars": rows,
               "baseline": whole.auc}, **kw)


__all__ = ["BOOTSTRAP_RESAMPLES", "BOOTSTRAP_SEED", "CONCEPTUAL_EVIDENCE",
           "ROLLING_WINDOW", "SPARSE_BIN_SHARE"]
