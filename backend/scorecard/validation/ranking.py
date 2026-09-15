"""§14.4: rank ordering, the bins it is measured on, and local inversions.

What was wrong with the previous banding
-----------------------------------------
Twelve equal-width bands across the model's DECLARED score range — 300 to
900 for a behavioural scorecard whose population actually occupies 555 to
707. Two thirds of the bands were empty, the populated ones were wide enough
to average a local inversion away, and the bounds moved with the declared
range rather than with anything measured. DISC-RANK read PASS on all eight
registered scorecards, which is a statement about the banding.

What it does now, and why each choice
--------------------------------------
**Bounds come from the development population, not from this month's.**
Cutting each cohort at its own quantiles compares every cohort to itself: a
band means a different score in January and in August, and a rank ordering
measured that way cannot be compared across cohorts at all — which is
exactly what §14.4's persistence question needs. So the edges are fixed once,
from the reference population's support, and every cohort is cut on the same
numbers. They are reported on the result.

**Equal width, never quantiles.** §14.4 is explicit: a large group of
identical scores must not be split into apparently different-risk deciles.
A quantile cut does precisely that — it puts a tie group's first half in one
decile and its second half in the next, and the two then differ by whatever
the row order happened to be. An equal-width band cannot: every identical
score falls in the same band by construction, whatever order the rows
arrive in. The largest tie group in each band is reported anyway, because a
band that is 40% one repeated score is a band whose rate is about that
score rather than about the range.

**Open tails.** The lowest and highest bands are unbounded, so a score
outside the development support is graded rather than dropped. A dropped row
is a row no test ever reports on.

An inversion is reported with what makes it readable
-----------------------------------------------------
Size, both absolute and relative. Support on both sides. Whether the two
confidence intervals overlap — an inversion inside the noise is still worth
naming and is not worth acting on, and the difference has to be visible.
Which segment concentrates in the inverting band. And persistence: the same
adjacent pair, cohort by cohort, over the cohorts where both bands carry
enough accounts to say anything.

What it will not claim
-----------------------
That an inversion caused a weak KS, or that a weak KS caused the inversion.
The result reports both and says they accompany each other. A scorecard can
invert locally with a strong KS and can rank perfectly with a weak one; the
two are different measurements and asserting a direction between them from
one run is not something the evidence supports.
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
from backend.scorecard.validation.runner import (
    Population,
    PopulationError,
    _period_label,
    _verdict,
    handles,
    population,
    reference_population,
)

#: Interior bands. Ten, plus the two open tails, so a reader counts twelve
#: rows and the middle ten are directly comparable in width.
INTERIOR_BANDS = 10

#: The reference quantiles the interior range spans. Not the min and max: one
#: mis-scored row at 42 would stretch every band and put the whole book in
#: one of them.
LOW_TAIL, HIGH_TAIL = 0.001, 0.999

#: A band thinner than this is shown and is excluded from the ordering test.
#: Twelve accounts carrying four defaults is a 33% default rate and it is not
#: a rank inversion.
BAND_SUPPORT = 200

#: And for a cohort to count towards persistence.
COHORT_SUPPORT = 100

#: How a scorecard type is said in a sentence. The registry enum is
#: BEHAVIORAL, and a result that reads "3 sibling behavioral scorecards" in a
#: product whose every other sentence is British is a result that looks
#: machine-assembled, which is the one impression a validation record cannot
#: afford.
SAID_AS: dict[str, str] = {
    "APPLICATION": "application",
    "BEHAVIORAL": "behavioural",
    "BEHAVIOURAL": "behavioural",
}


def _kind(model: model_registry.Model) -> str:
    return SAID_AS.get(model.scorecard_type,
                       model.scorecard_type.lower().replace("_", " "))


#: z for a 95% interval. Declared rather than inlined, because an interval
#: whose width nobody can trace is decoration.
Z = 1.959963985


def wilson(events: int, observations: int) -> tuple[float, float]:
    """A 95% interval on a rate, by the Wilson score method.

    Not the normal approximation. At the rates a good scorecard produces in
    its safest bands — fifteen defaults in eleven hundred accounts — the
    normal interval reaches below zero, and an interval with a negative
    default rate in it is one a reader stops believing.
    """
    if observations <= 0:
        return 0.0, 0.0
    share = events / observations
    denominator = 1.0 + Z * Z / observations
    centre = (share + Z * Z / (2 * observations)) / denominator
    half = Z * math.sqrt(
        share * (1.0 - share) / observations
        + Z * Z / (4.0 * observations * observations)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def band_edges(model: model_registry.Model,
               fallback: pd.DataFrame | None = None) -> list[float]:
    """The fixed cut points, taken from the development population.

    Falls back to the population being measured where no reference exists,
    and says so through `band_source`. A model with no development extract
    still gets stable bands WITHIN a run; what it does not get is bands
    comparable to a run made before the book moved.
    """
    scores: pd.Series | None = None
    try:
        reference = reference_population(model)
        scores = pd.to_numeric(reference.frame[model.score_column],
                               errors="coerce").dropna()
    except (PopulationError, KeyError):
        scores = None
    if scores is None or len(scores) < INTERIOR_BANDS:
        if fallback is None or model.score_column not in fallback.columns:
            low, high = model.score_range
            inner = list(np.linspace(low, high, INTERIOR_BANDS + 1))
            return [-math.inf, *inner, math.inf]
        scores = pd.to_numeric(fallback[model.score_column],
                               errors="coerce").dropna()
    low = float(scores.quantile(LOW_TAIL))
    high = float(scores.quantile(HIGH_TAIL))
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        low, high = model.score_range
    # The interior bands span the reference support; the two open tails sit
    # outside it. Twelve bands in all, and every row is graded — a score
    # below the development support is in the bottom band rather than in no
    # band, because a row no test reports on is a row nobody looks at.
    inner = list(np.linspace(low, high, INTERIOR_BANDS + 1))
    return [-math.inf, *inner, math.inf]


def band_source(model: model_registry.Model) -> str:
    try:
        reference = reference_population(model)
    except PopulationError:
        return "the population being measured (no development extract exists)"
    return (f"the development population, {_period_label(reference)}, "
            f"between its {LOW_TAIL:.1%} and {HIGH_TAIL:.1%} quantiles")


def _label(low: float, high: float) -> str:
    if low == -math.inf:
        return f"below {high:,.0f}"
    if high == math.inf:
        return f"{low:,.0f} and above"
    return f"{low:,.0f} – {high:,.0f}"


def band_evidence(frame: pd.DataFrame, model: model_registry.Model,
                  edges: list[float]) -> list[dict[str, Any]]:
    """One row per band, carrying everything §14.4 asks a reader to see."""
    scores = pd.to_numeric(frame[model.score_column], errors="coerce")
    cut = pd.cut(scores, bins=edges)
    outcome = (pd.to_numeric(frame[model.outcome_column], errors="coerce")
               if model.outcome_column in frame.columns else None)
    predicted = (pd.to_numeric(frame[model.pd_column], errors="coerce")
                 if model.pd_column and model.pd_column in frame.columns
                 else None)

    rows: list[dict[str, Any]] = []
    for at, interval in enumerate(cut.cat.categories):
        inside = cut == interval
        accounts = int(inside.sum())
        if not accounts:
            continue
        part = frame[inside]
        events = (int(outcome[inside].fillna(0).sum())
                  if outcome is not None else 0)
        rate = events / accounts
        low, high = wilson(events, accounts)
        held = pd.to_numeric(part[model.score_column], errors="coerce")
        rows.append({
            "band": _label(float(interval.left), float(interval.right)),
            "band_order": at,
            "score_from": (None if interval.left == -math.inf
                           else round(float(interval.left), 2)),
            "score_to": (None if interval.right == math.inf
                         else round(float(interval.right), 2)),
            "lowest_score_present": round(float(held.min()), 2),
            "highest_score_present": round(float(held.max()), 2),
            "accounts": accounts,
            "customers": (int(part[model.subject_key].nunique())
                          if model.subject_key in part.columns else None),
            "events": events,
            "observed_rate": round(rate, 6),
            "interval_low": round(low, 6),
            "interval_high": round(high, 6),
            "mean_predicted_pd": (round(float(predicted[inside].mean()), 6)
                                  if predicted is not None
                                  and predicted[inside].notna().any()
                                  else None),
            # §14.4's tie question, answered with a number rather than a
            # claim: what share of this band is a single repeated score.
            "largest_tied_share": round(
                float(held.value_counts(normalize=True).max()), 6)
            if len(held) else 0.0,
            "supported": accounts >= BAND_SUPPORT,
        })
    return rows


def _risk_order(rows: list[dict[str, Any]],
                model: model_registry.Model) -> list[dict[str, Any]]:
    """Bands from safest to riskiest, whichever way the score runs.

    §14.4: honour the model's orientation. A behavioural score is
    higher-is-safer and an early-warning score is higher-is-worse, and a
    monotonicity test that assumes one of them reports every model of the
    other kind as entirely inverted.
    """
    ordered = sorted(rows, key=lambda row: row["band_order"])
    if model.score_direction == "HIGHER_SCORE_IS_BETTER":
        return ordered            # safest last
    return list(reversed(ordered))


def _concentration(frame: pd.DataFrame, inside: pd.Series,
                   model: model_registry.Model) -> dict[str, Any]:
    """Which segment is over-represented in the inverting band.

    §14.4 calls it sub-product concentration. On a book with no sub-product
    column the same question is asked of the segmentation fields, because
    the point is not the column name — it is whether the inversion is the
    whole band or one population inside it.
    """
    best: dict[str, Any] = {}
    fields = [f for f in (model.segmentation_fields or ())
              if f in frame.columns]
    part = frame[inside]
    if not len(part):
        return best
    for field in fields:
        here = part[field].astype(str).value_counts(normalize=True)
        book = frame[field].astype(str).value_counts(normalize=True)
        for level, share in here.items():
            lift = float(share) - float(book.get(level, 0.0))
            if lift > float(best.get("over_represented_by", 0.0)):
                best = {
                    "field": field, "level": str(level),
                    "share_in_band": round(float(share), 6),
                    "share_in_book": round(float(book.get(level, 0.0)), 6),
                    "over_represented_by": round(lift, 6),
                }
    return best


def _persistence(model: model_registry.Model, edges: list[float],
                 riskier: dict[str, Any], safer: dict[str, Any],
                 ) -> dict[str, Any]:
    """The same adjacent pair, cohort by cohort, on the real cohorts.

    A pooled inversion over cohorts whose score distributions have moved is
    a pooling artefact before it is a scorecard defect, and the only way to
    tell the two apart is to look at the cohorts one at a time.

    It reloads each closed cohort rather than grouping the pool by its
    period column, and that is not fussiness. On a repeated-snapshot book
    the pool holds ONE ROW PER SUBJECT, at that subject's most recent
    matured observation — deliberately, so a Gini is not computed over the
    same facility thirteen times. Grouping that frame by month therefore
    groups facilities by when they last matured, not into cohorts: it
    reported twelve months of fifty accounts and one of four thousand, and
    read as "no cohort is thick enough to assess" on a book with thirteen
    closed cohorts of fifteen thousand.

    Cohorts where either band is too thin are counted as NOT ASSESSABLE
    rather than as not inverting. The difference decides whether "1 of 13"
    means the inversion is rare or means twelve cohorts could not be read.
    """
    from backend.scorecard.validation.runner import matured_periods

    closed = matured_periods(model)
    if not closed:
        return {"assessable": 0, "inverted": 0, "cohorts": 0,
                "why": "no cohort has a closed performance window"}

    assessable = inverted = 0
    per: list[dict[str, Any]] = []
    for period in closed:
        try:
            cohort = population(model, periods=(period,), matured_only=False)
        except PopulationError:
            continue
        frame = cohort.frame
        if model.matured_column in frame.columns:
            frame = frame[frame[model.matured_column].fillna(False).astype(bool)]
        if not len(frame):
            continue
        scores = pd.to_numeric(frame[model.score_column], errors="coerce")
        cut = pd.cut(scores, bins=edges)
        categories = list(cut.cat.categories)
        low_side = frame[cut == categories[riskier["band_order"]]]
        high_side = frame[cut == categories[safer["band_order"]]]
        row = {"period": period,
               "accounts_riskier": len(low_side),
               "accounts_safer": len(high_side)}
        if len(low_side) < COHORT_SUPPORT or len(high_side) < COHORT_SUPPORT:
            row["assessable"] = False
            per.append(row)
            continue
        rate_low = float(pd.to_numeric(low_side[model.outcome_column],
                                       errors="coerce").fillna(0).mean())
        rate_high = float(pd.to_numeric(high_side[model.outcome_column],
                                        errors="coerce").fillna(0).mean())
        this = rate_high > rate_low
        assessable += 1
        inverted += int(this)
        row.update({"assessable": True,
                    "rate_riskier": round(rate_low, 6),
                    "rate_safer": round(rate_high, 6),
                    "inverted": this})
        per.append(row)
    return {"assessable": assessable, "inverted": inverted,
            "cohorts": len(per), "by_period": per}


def inversions(frame: pd.DataFrame, model: model_registry.Model,
               edges: list[float], rows: list[dict[str, Any]]
               ) -> list[dict[str, Any]]:
    """Every adjacent pair where risk rises as the score gets safer."""
    ordered = [row for row in _risk_order(rows, model) if row["supported"]]
    scores = pd.to_numeric(frame[model.score_column], errors="coerce")
    cut = pd.cut(scores, bins=edges)
    categories = list(cut.cat.categories)

    found: list[dict[str, Any]] = []
    for riskier, safer in zip(ordered, ordered[1:], strict=False):
        # `ordered` runs riskiest to safest, so the next band should default
        # LESS. It defaulting more is the inversion.
        if safer["observed_rate"] <= riskier["observed_rate"]:
            continue
        gap = safer["observed_rate"] - riskier["observed_rate"]
        overlap = (safer["interval_low"] <= riskier["interval_high"]
                   and riskier["interval_low"] <= safer["interval_high"])
        inside = cut == categories[safer["band_order"]]
        found.append({
            "safer_band": safer["band"],
            "riskier_band": riskier["band"],
            "safer_rate": safer["observed_rate"],
            "riskier_rate": riskier["observed_rate"],
            "size": round(gap, 6),
            "relative_size": (round(gap / riskier["observed_rate"], 6)
                              if riskier["observed_rate"] else None),
            "accounts_safer": safer["accounts"],
            "accounts_riskier": riskier["accounts"],
            "events_safer": safer["events"],
            "events_riskier": riskier["events"],
            "intervals_overlap": overlap,
            "separated_by_the_evidence": not overlap,
            "concentration": _concentration(frame, inside, model),
            "persistence": _persistence(model, edges, riskier, safer),
        })
    found.sort(key=lambda one: -one["size"])
    return found


def _says(one: dict[str, Any]) -> str:
    """One inversion, in a sentence a validator can file unedited."""
    persistence = one["persistence"]
    said = (f"{one['safer_band']} defaults at {one['safer_rate']:.3%} "
            f"against {one['riskier_rate']:.3%} in the riskier band below it "
            f"({one['riskier_band']}) — {one['size']:.3%} the wrong way, on "
            f"{one['accounts_safer']:,} and {one['accounts_riskier']:,} "
            f"accounts carrying {one['events_safer']} and "
            f"{one['events_riskier']} defaults.")
    said += (" The two 95% intervals do not overlap, so the evidence "
             "separates them."
             if one["separated_by_the_evidence"] else
             " The two 95% intervals overlap, so the ordering is not "
             "separated by the evidence on this population alone.")
    if persistence.get("assessable"):
        said += (f" It inverts in {persistence['inverted']} of the "
                 f"{persistence['assessable']} closed cohort(s) where both "
                 f"bands carry enough accounts to read, out of "
                 f"{persistence.get('cohorts', 0)} closed cohort(s) in all.")
    else:
        said += (f" Persistence could not be assessed: of the "
                 f"{persistence.get('cohorts', 0)} closed cohort(s), none "
                 f"carries {COHORT_SUPPORT} accounts in both bands.")
    spot = one.get("concentration") or {}
    if spot.get("over_represented_by", 0.0) >= 0.05:
        said += (f" {spot['field']}={spot['level']} is "
                 f"{spot['share_in_band']:.0%} of the inverting band against "
                 f"{spot['share_in_book']:.0%} of the book, so the inversion "
                 "is concentrated rather than spread across it.")
    return said


@handles("DISC-RANK", "SEG-RANK")
def _rank_ordering(test: test_registry.Test, model: model_registry.Model,
                   pool: Population, **kw: Any) -> states.Result:
    edges = band_edges(model, pool.frame)
    rows = band_evidence(pool.frame, model, edges)
    if not rows:
        return states.unavailable(
            test.test_id, what="a score on any row of this population",
            model_id=model.model_id, model_version=model.version,
            dataset=pool.dataset, period=_period_label(pool),
            method=test.method, **kw)

    found = inversions(pool.frame, model, edges, rows)
    supported = [row for row in rows if row["supported"]]
    thin = len(rows) - len(supported)
    separated = [one for one in found if one["separated_by_the_evidence"]]

    if not found:
        said = (f"The observed default rate falls monotonically across all "
                f"{len(supported)} bands with support.")
    else:
        said = (f"{len(found)} adjacent band(s) invert. " + _says(found[0]))
        if len(found) > 1:
            said += f" {len(found) - 1} further inversion(s) are tabled below."
    if thin:
        said += (f" {thin} band(s) carry fewer than {BAND_SUPPORT} accounts "
                 "and are shown without being tested for ordering.")

    state = (states.PASS if not found
             else states.FAIL if separated
             else states.WARNING)
    return states.measured(
        test.test_id, state, float(len(found)),
        detail=said,
        remedy=("" if not found else
                "Read the inverting bands against the concentration and the "
                "cohort table before proposing a change: an inversion that "
                "is one segment is a segmentation question, and one that "
                "appears in a single cohort is a sample question."),
        table=rows,
        chart={"kind": test_registry.CHART_BAND_RATE, "bands": rows,
               "caption": (
                   "The realised default rate in each band, against the "
                   "predicted PD. The bands are fixed cut points taken from "
                   + band_source(model)
                   + ", so a band means the same score in every cohort. What "
                   "matters is the ORDER: a band that defaults more than the "
                   "riskier band below it is a rank inversion.")},
        observations=len(pool.frame),
        events=sum(row["events"] for row in rows),
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=_period_label(pool),
        method=test.method, score_direction=model.score_direction,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations,
        lineage={
            "band_edges": [None if not math.isfinite(e) else round(e, 2)
                           for e in edges],
            "band_source": band_source(model),
            "interior_bands": INTERIOR_BANDS,
            "band_support_floor": BAND_SUPPORT,
            "cohort_support_floor": COHORT_SUPPORT,
            "ties": ("Equal-width bands over fixed cut points. Every "
                     "identical score falls in the same band whatever order "
                     "the rows arrive in, so no tie group is split across "
                     "two bands and no band's rate depends on row order. "
                     "`largest_tied_share` reports how much of each band is "
                     "a single repeated score."),
            "inversions": found,
            "panels": ([{"title": "Adjacent inversions",
                         "table": [{k: v for k, v in one.items()
                                    if not isinstance(v, dict)}
                                   for one in found]},
                        {"title": "The inverting pair, cohort by cohort",
                         "table": found[0]["persistence"].get("by_period", [])}]
                       if found else []),
        }, **kw)


# ================================================ the comparison scorecard


@handles("DISC-RANK-PEER")
def _peer_ranking(test: test_registry.Test, model: model_registry.Model,
                  pool: Population, **kw: Any) -> states.Result:
    """The same test on the other scorecards of this kind.

    §14.4 asks for a useful comparison that does not have the same issue,
    and the useful comparison for a product scorecard is the same design on
    another product: same bands, same method, same book, different
    portfolio. An inversion that appears on one product and not on its three
    siblings is a finding about that product; one that appears on all four
    is a finding about the design.
    """
    shared = dict(
        model_id=model.model_id, model_version=model.version,
        dataset=pool.dataset, period=_period_label(pool),
        method=test.method, score_direction=model.score_direction,
        calculation_version=kernels.METRICS_VERSION,
        limitations=test.limitations, **kw)

    peers = [one for one in model_registry.all_models()
             if one.model_id != model.model_id
             and one.scorecard_type == model.scorecard_type
             and one.domain == model.domain]
    if not peers:
        return states.not_applicable(
            test.test_id,
            why=(f"{model.name} is the only {_kind(model)} "
                 "scorecard registered, so there is no comparable model to "
                 "set beside it. A comparison invented from the same model's "
                 "own predictions would not be one."),
            **shared)

    def count_for(one: model_registry.Model,
                  frame: pd.DataFrame) -> dict[str, Any]:
        edges = band_edges(one, frame)
        rows = band_evidence(frame, one, edges)
        found = inversions(frame, one, edges, rows)
        return {
            "model_id": one.model_id, "model": one.name,
            "portfolio": one.scope_value or one.portfolio,
            "bands_with_support": sum(1 for r in rows if r["supported"]),
            "inversions": len(found),
            "separated_by_the_evidence": sum(
                1 for f in found if f["separated_by_the_evidence"]),
            "largest_inversion": (round(found[0]["size"], 6)
                                  if found else 0.0),
            "accounts": len(frame),
        }

    rows = [count_for(model, pool.frame)]
    rows[0]["model"] = f"{model.name} (this one)"
    for one in peers:
        try:
            theirs = population(one)
        except PopulationError as e:
            rows.append({"model_id": one.model_id, "model": one.name,
                         "portfolio": one.scope_value or one.portfolio,
                         "bands_with_support": 0, "inversions": None,
                         "separated_by_the_evidence": None,
                         "largest_inversion": None, "accounts": 0,
                         "not_measured": str(e)})
            continue
        rows.append(count_for(one, theirs.frame))

    measured_rows = [row for row in rows if row.get("inversions") is not None]
    siblings = measured_rows[1:]
    clean = [row for row in siblings if row["inversions"] == 0]
    inverting = [row for row in siblings if row["inversions"]]
    mine = rows[0]["inversions"]
    kind = _kind(model)
    if not siblings:
        said = ("No sibling scorecard could be measured, so this result "
                "stands on its own.")
    elif mine == 0:
        said = (f"This scorecard ranks monotonically across every band with "
                f"support. Of its {len(siblings)} sibling {kind} "
                f"scorecard(s), {len(inverting)} do not"
                + (": " + ", ".join(row["model"] for row in inverting[:3])
                   if inverting else "")
                + ".")
    elif not clean:
        said = (f"This scorecard has {mine} adjacent inversion(s), and so "
                f"does every one of its {len(siblings)} sibling {kind} "
                "scorecard(s) on the same bands and the same method. A "
                "defect every product shares is a question about the design "
                "rather than about this portfolio.")
    elif len(clean) >= len(inverting):
        said = (f"This scorecard has {mine} adjacent inversion(s), where "
                f"{len(clean)} of its {len(siblings)} sibling {kind} "
                "scorecard(s) rank monotonically on the same bands and the "
                "same method — "
                + ", ".join(row["model"] for row in clean[:3])
                + ". A defect that most comparable products do not share is "
                  "a question about this portfolio.")
    else:
        said = (f"This scorecard has {mine} adjacent inversion(s), as do "
                f"{len(inverting)} of its {len(siblings)} sibling {kind} "
                f"scorecard(s). Only {len(clean)} rank monotonically — "
                + ", ".join(row["model"] for row in clean[:3])
                + " — so this is more a question about the design these "
                  "products share than about this portfolio alone.")

    return states.measured(
        test.test_id, states.NO_LIMIT, float(len(clean)),
        detail=said, table=rows,
        chart={"kind": test_registry.CHART_RANKING, "rows": rows,
               "label_key": "model", "value_key": "inversions",
               "caption": ("Adjacent rank inversions on each registered "
                           "scorecard of this kind, measured on each one's "
                           "own development-anchored bands.")},
        observations=len(pool.frame),
        lineage={"peers": [one.model_id for one in peers],
                 "panels": [{"title": "The same test on every sibling "
                                      "scorecard", "table": rows}]},
        **shared)
