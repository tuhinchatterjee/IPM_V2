"""
The Early Warning book as one row per obligor per month, flat.

Why a wide view exists at all
-----------------------------
The governed model is normalised, and it has to be: the signal catalogue, the
observations, the sub-category outputs and the lineage are separate things
with separate audit lives, and collapsing them would make the score
unauditable. But a question like "which sub-category is driving the High
population this month?" should not require a reader — or a planner writing
code against this domain — to unpack three nested dictionaries and join two
frames before it can start.

So the normalised model stays exactly as it is, and this is a projection of
it: every nested structure the borrower-month row carries — the twenty-two
sub-category scores, the six layer/dimension outputs, the five notches, the
overrides — lifted into named columns, with the names a person would use.

And every one of the 123 signals in the inventory, joined from the signal
observations onto the same grain: what the trigger saw, what it was measured
against, the five accelerator bands, the decay applied, the score it produced
and the reason it carries. That is what makes "which obligors have a covenant
breach, and what was the reading behind it?" a question this domain can be
asked, rather than one a reader has to know a second dataset to answer.

The governed outputs come with it — the escalation route the matrix produces
for this band and exposure, and the action the library holds for the driver
that fired — because a planner asking "who owns the high-risk names and by
when" is asking about a deterministic function of fields already here.

What it is not
--------------
Not a second source of truth. Every column here is read from the published
borrower-month rows, never recomputed, so the wide view cannot disagree with
the model: if it did, this module would be the thing that is wrong. Nothing
is derived here that the model does not already state, with two exceptions
that are explicitly labelled as derived — the dominant layer, and the
one-month and twelve-month movement — because both are read off the same
published rows and both are the questions the screen asks most.
"""

from __future__ import annotations

import functools
from typing import Any

import pandas as pd

from backend.early_warning import aggregation as agg
from backend.early_warning import classifiers_v2 as clf
from backend.early_warning import actions as actions_mod
from backend.early_warning import escalation as esc
from backend.early_warning import notches as notch_mod
from backend.early_warning import reasons
from backend.early_warning import signal_fields as sigf
from backend.early_warning import v2_service as svc

#: The twenty-two sub-category nodes, trigger-and-accelerator first.
SUBCATEGORY_CODES: tuple[str, ...] = (
    tuple(agg.TA_SUBCATEGORIES) + tuple(clf.SUBCATEGORIES))

#: The six layer/dimension outputs, in the order the model produces them.
LAYER_KEYS: tuple[str, ...] = ("l1_ta", "l2_ta", "l3_ta", "l4_ta",
                               "l2_c", "l4_c")

#: The five notches, in the order they are applied.
NOTCH_KEYS: tuple[str, ...] = tuple(notch_mod.NOTCH_KEYS)

#: Which dimension each sub-category belongs to.
TA_CODES = frozenset(agg.TA_SUBCATEGORIES)
CLASSIFIER_CODES = frozenset(clf.SUBCATEGORIES)


#: What each sub-category node exposes beyond its score. The band and the
#: reason are what a reader acts on; the worst signal is what they check.
SUBCATEGORY_MEASURES: tuple[str, ...] = ("score", "band", "worst_signal",
                                          "reason")


def subcategory_column(code: str, measure: str = "score") -> str:
    """`L2.1` becomes `sub_l2_1_score`, which is a column name a person can type."""
    return f"sub_{code.lower().replace('.', '_')}_{measure}"


def notch_column(key: str) -> str:
    return f"notch_{key}"


def _as_list(value: Any) -> list[str]:
    """Overrides arrive comma-separated. Splitting them here stops a caller
    iterating the string one character at a time."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _subcategory_name(code: Any) -> str:
    """The node's business name, or nothing when there is no node."""
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return ""
    text = str(code).strip()
    if not text or text.lower() == "nan":
        return ""
    try:
        return reasons.subcategory_name(text)
    except KeyError:
        return text


def _dominant_layer(layers: dict[str, Any]) -> str:
    """The layer carrying the most trigger-side risk, or empty when none is."""
    ta = {k: float(v or 0.0) for k, v in (layers or {}).items()
          if k.endswith("_ta")}
    if not ta or max(ta.values()) <= 0:
        return ""
    return max(ta, key=lambda k: ta[k]).split("_")[0].upper()


def _observations_for(frame: pd.DataFrame) -> pd.DataFrame:
    """Every signal observation behind the rows in this frame.

    Read once for the whole frame rather than per obligor: the join is what
    makes the signal columns cheap enough to exist, and a per-row lookup
    would make the wide view something nobody would call.
    """
    months = set(frame["snapshot_month"].astype(str))
    customers = set(frame["customer_id"].astype(str))
    try:
        observations = svc.observations()
    except svc.EarlyWarningDataNotBuilt:
        return pd.DataFrame()
    if observations.empty:
        return observations
    return observations[
        observations["snapshot_month"].astype(str).isin(months)
        & observations["customer_id"].astype(str).isin(customers)].copy()


def _best_by_signal(observations: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """One row per obligor per trigger key: the highest-scoring occurrence.

    A trigger can fire more than once in a month — an L3 event signal fires
    per event. The wide view is one row per obligor-month, so it carries the
    worst occurrence and says so; the normalised observations still hold
    every one of them.
    """
    if observations.empty:
        return {}
    ranked = observations.sort_values("signal_score", ascending=False)
    out: dict[str, pd.DataFrame] = {}
    for key, chunk in ranked.groupby("signal_key"):
        out[str(key)] = chunk.drop_duplicates(
            subset=["customer_id"]).set_index("customer_id")
    return out


#: Which observation column answers which signal column. The ones not here
#: are computed — `fired`, `freshness`, and the four that come from the
#: inventory row rather than from the reading.
_FROM_OBSERVATION: dict[str, str] = {
    "observed_value": "observed_value",
    "baseline_value": "baseline_value",
    "normalised_value": "normalised_value",
    "observed_unit": "observed_unit",
    "trigger_severity_band": "trigger_severity_band",
    "trigger_score": "trigger_severity_score",
    "magnitude_band": "magnitude_band",
    "velocity_band": "velocity_band",
    "persistence_band": "persistence_band",
    "repetition_band": "repetition_band",
    "corroboration_band": "corroboration_band",
    "accelerator_multiplier": "accelerator_multiplier",
    "decay_class": "decay_class",
    "decay_factor": "decay_factor",
    "score": "signal_score",
    "reason_code": "reason_code",
    "reason": "reason",
    "evidence_age_days": "age_days",
}


def _signal_block(out: pd.DataFrame,
                  observations: pd.DataFrame) -> dict[str, Any]:
    """All 123 inventory rows, projected onto the obligor-month grain.

    Returned as a block for one concatenation rather than assigned column by
    column: two thousand individual inserts into a DataFrame is two thousand
    reallocations, and this is called on every request.
    """
    best = _best_by_signal(observations)
    index = out.index
    ids = out["customer_id"].astype(str)
    block: dict[str, Any] = {}

    for entry in sigf.fields():
        block[entry.column("status")] = entry.status
        if not entry.scored:
            block[entry.column("status_detail")] = entry.status_detail
            block[entry.column("source_system")] = entry.source_system
            continue

        rows = best.get(entry.trigger_key) if entry.trigger_key else None
        fired = (ids.isin(rows.index) if rows is not None
                 else pd.Series(False, index=index))
        block[entry.column("fired")] = fired.to_numpy()
        block[entry.column("source_system")] = entry.source_system

        for suffix, dtype, *_ in sigf.SCORED_MEASURES:
            column = _FROM_OBSERVATION.get(suffix)
            if column is None:
                continue
            if rows is None or column not in rows.columns:
                # A signal with no feed is absent rather than zero, and the
                # column says so in every row: a NaN a planner can see is a
                # different fact from a nought it would average.
                block[entry.column(suffix)] = (
                    [float("nan")] * len(out) if dtype == "number"
                    else [""] * len(out))
                continue
            values = ids.map(rows[column])
            block[entry.column(suffix)] = (
                values.to_numpy() if dtype == "number"
                else values.fillna("").astype(str).to_numpy())

        ages = block.get(entry.column("evidence_age_days"))
        block[entry.column("freshness")] = [
            "" if v is None or pd.isna(v) else sigf.freshness(v)
            for v in (ages if ages is not None else [None] * len(out))]

    return block


def _subcategory_block(out: pd.DataFrame,
                       observations: pd.DataFrame) -> dict[str, Any]:
    """Each node's band, its worst signal and the reason it carries.

    The score on its own is a number a reader cannot act on. The band is
    what the model bands it at, the worst signal is what they would open,
    and the reason is the workbook's own text for that node at that band —
    not a sentence composed here, which would be a second opinion.
    """
    worst: dict[str, dict[str, str]] = {}
    if not observations.empty and "sub_category" in observations.columns:
        ranked = observations.sort_values("signal_score", ascending=False)
        for code, chunk in ranked.groupby("sub_category"):
            first = chunk.drop_duplicates(subset=["customer_id"])
            worst[str(code)] = dict(zip(first["customer_id"].astype(str),
                                         first["signal_key"].astype(str)))

    ids = out["customer_id"].astype(str)
    block: dict[str, Any] = {}
    for code in SUBCATEGORY_CODES:
        scores = out[subcategory_column(code)]
        bands = [agg.ta_verdict_band(float(v or 0.0)) for v in scores]
        block[subcategory_column(code, "band")] = bands
        block[subcategory_column(code, "worst_signal")] = [
            worst.get(code, {}).get(customer, "") for customer in ids]
        block[subcategory_column(code, "reason")] = [
            _subcategory_reason(code, band) for band in bands]
    return block


def _subcategory_reason(code: str, band: str) -> str:
    try:
        return reasons.subcategory_reason(code, band)
    except KeyError:
        return ""


def _governed_block(out: pd.DataFrame) -> dict[str, Any]:
    """The escalation route and the governed action, at the same grain.

    Both are deterministic functions of fields already on the row — the band
    and the exposure for the route, the dominant node for the action — so
    exposing them here is exposing what the product already decides, not
    deciding it again. A planner asking "who owns the high-risk names, and
    by when" is asking a data question, and without these it would have to
    reimplement the matrix to answer it.
    """
    routes = [esc.route_for(str(band), float(exposure or 0.0))
              for band, exposure in zip(out["ews_band"], out["exposure"])]
    library = [actions_mod.for_subcategory(str(code))
               if code is not None and str(code) != "nan" else None
               for code in out.get("dominant_subcategory", [None] * len(out))]
    return {
        "escalation_rung": [", ".join(r.get("escalated_to") or [])
                            for r in routes],
        "escalation_role": [
            ", ".join(esc.role_of(level)
                      for level in (r.get("escalated_to") or []))
            for r in routes],
        "escalation_notified": [", ".join(r.get("notified") or [])
                                for r in routes],
        "escalation_exposure_tier": [str(r.get("exposure_tier") or "")
                                     for r in routes],
        "escalation_ack_sla_days": [int(r.get("ack_sla_days") or 0)
                                    for r in routes],
        "escalation_decision_sla_days": [int(r.get("decision_sla_days") or 0)
                                         for r in routes],
        "expected_action": [
            reasons.ews_expected_action(str(band))
            if str(band) in reasons.EWS_BAND_EXPECTED_ACTION else ""
            for band in out["ews_band"]],
        "recommended_action": [a.action if a else "" for a in library],
        "action_owner_role": [a.owner_role if a else "" for a in library],
        "action_owner": [esc.role_of(a.owner_role) if a else ""
                         for a in library],
        "action_timeframe_days": [a.timeframe_days if a else -1
                                  for a in library],
        "evidence_to_close": [a.evidence_to_close if a else ""
                              for a in library],
        "action_reversibility_rank": [a.reversibility_rank if a else -1
                                      for a in library],
        "action_cost_rank": [a.cost_rank if a else -1 for a in library],
    }


def flatten(frame: pd.DataFrame) -> pd.DataFrame:
    """One published borrower-month frame, with every nested field named.

    Read rather than recomputed. A column that disagreed with the model would
    be this module's defect, so there is nothing here for it to disagree
    about.
    """
    if frame is None or frame.empty:
        return pd.DataFrame()

    out = frame.copy()

    subcats = out.get("subcategory_scores")
    layers = out.get("layer_dimension_scores")
    notch_values = out.get("notches")

    for code in SUBCATEGORY_CODES:
        column = subcategory_column(code)
        out[column] = [
            float((row or {}).get(code) or 0.0)
            for row in (subcats if subcats is not None else [{}] * len(out))
        ]

    for key in LAYER_KEYS:
        out[key] = [
            float((row or {}).get(key) or 0.0)
            for row in (layers if layers is not None else [{}] * len(out))
        ]

    for key in NOTCH_KEYS:
        out[notch_column(key)] = [
            int((row or {}).get(key) or 0)
            for row in (notch_values if notch_values is not None else [{}] * len(out))
        ]

    overrides = [_as_list(v) for v in out.get("overrides_applied", [None] * len(out))]
    out["override_applied"] = [bool(v) for v in overrides]
    out["override_count"] = [len(v) for v in overrides]
    out["override_types"] = [", ".join(v) for v in overrides]

    # Derived, and labelled as such in the dictionary: read off the same
    # published row, not recomputed from the signals.
    out["dominant_layer"] = [
        _dominant_layer(row or {})
        for row in (layers if layers is not None else [{}] * len(out))
    ]
    # An obligor with no scoring node has no dominant sub-category, and the
    # column arrives as NaN rather than as an empty string.
    out["dominant_subcategory_name"] = [
        _subcategory_name(code)
        for code in out.get("dominant_subcategory", [None] * len(out))
    ]
    out["ta_minus_classifier"] = out["ta_score"] - out["classifier_score"]
    out["notch_points"] = out["net_notches"] * notch_mod.POINTS_PER_NOTCH
    out["high_plus"] = out["ews_band"].isin(("HIGH", "VERY_HIGH"))
    out["matrix_cell"] = (out["ta_band"].astype(str) + " / "
                          + out["classifier_band"].astype(str))
    out["override_reasons"] = [
        "; ".join(reasons.override_reason(code) for code in codes)
        for codes in overrides]

    # Two thousand columns arrive in one concatenation. Assigning them one
    # at a time reallocates the frame on every insert, which turns a
    # projection into something nobody would call twice.
    observations = _observations_for(out)
    block: dict[str, Any] = {}
    block.update(_signal_block(out, observations))
    block.update(_subcategory_block(out, observations))
    block.update(_governed_block(out))
    out = pd.concat([out, pd.DataFrame(block, index=out.index)], axis=1)

    # The nested originals are dropped from the wide view: keeping both would
    # give a planner two ways to ask the same question and one of them would
    # be wrong sooner or later. `overrides_applied` goes with them — the three
    # named columns above say the same thing without a comma-separated string
    # to parse. The normalised frame still carries every one of them.
    return out.drop(columns=[c for c in ("subcategory_scores",
                                          "layer_dimension_scores", "notches",
                                          "classifier_overrides",
                                          "overrides_applied")
                              if c in out.columns])


#: How many months of the projection are kept in memory. The frame is two
#: and a half thousand columns wide and every screen, every plan step and
#: every dictionary profile asks for the same one, so building it per call
#: turned a request into fourteen seconds of arithmetic that had already been
#: done. Copy-on-write means a caller can add a column to what it is handed
#: without reaching the cached frame.
CACHED_MONTHS = 4


@functools.lru_cache(maxsize=CACHED_MONTHS)
def _projected(period: str | None) -> pd.DataFrame:
    return flatten(svc.borrower_month(period))


@functools.lru_cache(maxsize=CACHED_MONTHS)
def _projected_with_movement(period: str | None) -> pd.DataFrame:
    return _with_movement(period)


def reset() -> None:
    """Forget the cached projections. Called when the domain is rebuilt."""
    _projected.cache_clear()
    _projected_with_movement.cache_clear()
    columns.cache_clear()


def customer_month(period: str | None = None) -> pd.DataFrame:
    """The wide view for one published month, or the latest."""
    return _projected(period).copy(deep=False)


def with_movement(period: str | None = None) -> pd.DataFrame:
    """The wide view plus how each obligor moved, one month and twelve back."""
    return _projected_with_movement(period).copy(deep=False)


def _with_movement(period: str | None = None) -> pd.DataFrame:
    """The projection and the movement, computed.

    Derived here rather than in the model because it is a comparison of two
    published rows rather than a score: the anchor and the notch movements
    are carried separately, because a score that fell while its anchor rose
    has not improved and the two have to be readable apart.
    """
    period = period or svc.latest_period()
    periods = svc.periods()
    current = customer_month(period)
    if current.empty:
        return current
    here = periods.index(period) if period in periods else len(periods) - 1

    for label, back in (("1m", 1), ("12m", 12)):
        prior_period = periods[here - back] if here - back >= 0 else None
        if prior_period is None:
            current[f"ews_change_{label}"] = float("nan")
            current[f"anchor_change_{label}"] = float("nan")
            current[f"prior_period_{label}"] = ""
            continue
        prior = svc.borrower_month(prior_period).set_index("customer_id")
        current[f"prior_period_{label}"] = prior_period
        current[f"ews_change_{label}"] = [
            round(float(row.ews_score) - float(prior.loc[row.customer_id, "ews_score"]), 2)
            if row.customer_id in prior.index else float("nan")
            for row in current.itertuples()
        ]
        current[f"anchor_change_{label}"] = [
            round(float(row.anchor_score) - float(prior.loc[row.customer_id, "anchor_score"]), 2)
            if row.customer_id in prior.index else float("nan")
            for row in current.itertuples()
        ]

    # Which way the obligor is going, and whether the score is going that way
    # for the same reason the condition is. A score that fell while its anchor
    # rose has not improved: the notches moved, and reading that as recovery
    # is the specific mistake this pair of columns exists to prevent.
    current["direction_of_travel"] = [
        _direction(value) for value in current["ews_change_12m"]]
    current["movement_is_notch_driven"] = [
        bool(score == score and anchor == anchor
             and (score < 0 < anchor or anchor < 0 < score))
        for score, anchor in zip(current["ews_change_12m"],
                                  current["anchor_change_12m"])]
    return current


#: What counts as a move rather than noise, in score points over twelve
#: months. Below it the obligor is stable, and calling a two-point drift an
#: improvement would put a direction on arithmetic.
MOVEMENT_THRESHOLD = 3.0


def _direction(change: Any) -> str:
    if change is None or change != change:
        return "unknown"
    value = float(change)
    if value >= MOVEMENT_THRESHOLD:
        return "deteriorating"
    if value <= -MOVEMENT_THRESHOLD:
        return "improving"
    return "stable"


@functools.lru_cache(maxsize=1)
def columns() -> tuple[str, ...]:
    """Every column the wide view exposes, for the dictionary to describe."""
    return tuple(with_movement().columns)


__all__ = ["CLASSIFIER_CODES", "LAYER_KEYS", "MOVEMENT_THRESHOLD",
           "NOTCH_KEYS",
           "SUBCATEGORY_CODES", "SUBCATEGORY_MEASURES", "TA_CODES",
           "CACHED_MONTHS", "columns", "customer_month", "flatten",
           "notch_column", "reset", "subcategory_column", "with_movement"]
