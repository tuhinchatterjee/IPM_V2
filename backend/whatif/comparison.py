"""
The same scenario, priced two ways, and an honest account of the difference.

Why both directions
-------------------
A person who ran the Delta Model wants to know what the ML model would have
said. A person who ran the ML model wants to know how far it moved them from
the governed arithmetic. Those are the same comparison and they must not be two
features: whichever methodology produced the result on screen, the other one is
one question away, and the answer is the same object either way — only the
"from" and "to" labels change.

Why a spread is not an answer
-----------------------------
"The two differ by 9%" is where the useful part starts, not where it ends. The
question a credit committee actually asks is WHERE they differ and WHY, because
a nine per cent gap spread evenly across the book means something quite
different from a nine per cent gap that is entirely one sector, or entirely the
borrowers the model has never seen anything like.

So the comparison carries the split — by sector, by stage, by rating, and the
borrowers the two methodologies disagree about most — and only then asks a
model to read it.

What the explanation may say
----------------------------
Nothing that is not in the evidence. `narrative.check` re-reads the finished
prose for figures the packet does not contain, and prose carrying one is
discarded in favour of the composed reading. A confident sentence explaining a
number that was never computed is the failure this whole module is arranged to
avoid.

And it may not recommend. Neither methodology is "right": the Delta Model is
the governed arithmetic carried onto the reported book, and the ML model is a
fitted estimate anchored to it. Which one belongs in a submission is a
governance decision, not a modelling one, and the product says so rather than
picking.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pandas as pd

from backend.whatif import domain as dm
from backend.whatif import methodology as me

logger = logging.getLogger(__name__)

COMPARISON_VERSION = "1.0.0"

#: How many borrowers and groups reach the evidence. Enough to locate a
#: disagreement; not so many that the packet becomes the book.
TOP_N = 12

#: Below this share of the What-If figure the two methodologies agree for
#: every practical purpose, and saying they "differ" would be a finding
#: manufactured out of arithmetic.
AGREEMENT_PCT = 0.10

_SYSTEM = (
    "You are a senior IFRS 9 credit-risk analyst explaining, to a credit "
    "committee, why two ECL methodologies priced the same scenario "
    "differently.\n\n"
    "THE EVIDENCE PACKET BELOW IS THE ONLY THING YOU KNOW.\n\n"
    "Every number you write must appear in that packet. You may round one and "
    "you may state the difference between two of them. You may NOT estimate, "
    "infer or recall any other number, and you may not name a sector, rating "
    "or borrower the packet does not name.\n\n"
    "Do NOT recommend one methodology over the other, and do not call either "
    "one more accurate, more correct or better. The Delta Model is the "
    "governed arithmetic carried onto the reported book; the ML model is a "
    "fitted estimate anchored to that same book. Which belongs in a "
    "submission is a governance decision, and it is not yours to make.\n\n"
    "Explain, in flowing prose rather than headings: how far apart the two "
    "are and whether that is material; WHERE the difference sits — the "
    "sectors, stages, ratings or individual borrowers the packet shows it "
    "concentrated in; what that pattern suggests about which borrowers the "
    "model is treating differently from the arithmetic; anything in the "
    "packet that limits how far the ML figure should be trusted, including "
    "borrowers outside the range it was trained on; and what a reader should "
    "do with the pair of numbers. If the two agree, say so plainly and "
    "briefly rather than manufacturing a difference."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array", "minItems": 1, "maxItems": 5,
            "items": {"type": "string"},
            "description": "Professional prose. Every figure from the packet.",
        },
        "headline": {
            "type": "string",
            "description": "One sentence stating how far apart the two are "
                           "and where the difference sits.",
        },
        "where_it_sits": {
            "type": "array", "maxItems": 5, "items": {"type": "string"},
            "description": "The concentrations the packet shows, named.",
        },
    },
    "required": ["paragraphs", "headline"],
}


class ComparisonError(ValueError):
    """A comparison that cannot be made, said rather than approximated."""


def _round(value: Any, places: int = 4) -> Any:
    try:
        found = float(value)
    except (TypeError, ValueError):
        return value
    if np.isnan(found) or np.isinf(found):
        return None
    return round(found, places)


def _frame(result: Any) -> pd.DataFrame:
    frame = getattr(result, "borrowers", None)
    if not isinstance(frame, pd.DataFrame):
        return pd.DataFrame()
    return frame


def _disagreement(delta: Any, ml: Any) -> pd.DataFrame:
    """Borrower by borrower, how far the two methodologies are apart.

    An inner join on borrower_id: both runs priced the same shocked book, so
    the populations are the same and a borrower missing from either side is a
    fact worth surfacing rather than silently dropping — which is why the
    packet reports the matched count against each population.
    """
    left, right = _frame(delta), _frame(ml)
    if left.empty or right.empty:
        return pd.DataFrame()
    keep = ["borrower_id", "display_name", "sector", "opening_rating",
            "stage_baseline", "stage_stressed", "ead", "ecl_baseline",
            "ecl_stressed"]
    a = left[[c for c in keep if c in left.columns]].copy()
    b = right[[c for c in ("borrower_id", "ecl_stressed")
               if c in right.columns]].copy()
    joined = a.merge(b, on="borrower_id", how="inner",
                     suffixes=("_delta", "_ml"))
    if "ecl_stressed_delta" not in joined.columns:
        return pd.DataFrame()
    joined["difference"] = (joined["ecl_stressed_ml"]
                            - joined["ecl_stressed_delta"])
    base = joined["ecl_stressed_delta"].abs()
    joined["difference_pct"] = np.where(
        base > 1e-9, joined["difference"] / base.where(base > 1e-9, 1.0) * 100.0,
        0.0)
    return joined


def _grouped(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if frame.empty or column not in frame.columns:
        return []
    grouped = frame.groupby(column, dropna=False).agg(
        borrowers=("borrower_id", "size"),
        delta=("ecl_stressed_delta", "sum"),
        ml=("ecl_stressed_ml", "sum"),
        difference=("difference", "sum")).reset_index()
    grouped["share_of_difference_pct"] = np.where(
        abs(frame["difference"].sum()) > 1e-9,
        grouped["difference"] / frame["difference"].sum() * 100.0, 0.0)
    grouped = grouped.reindex(
        grouped["difference"].abs().sort_values(ascending=False).index)
    return [{"group": str(r[column]), "borrowers": int(r["borrowers"]),
             "delta_ecl": _round(r["delta"], 2), "ml_ecl": _round(r["ml"], 2),
             "difference": _round(r["difference"], 2),
             "share_of_difference_pct": _round(r["share_of_difference_pct"], 2)}
            for r in grouped.head(TOP_N).to_dict(orient="records")]


def compare(state: Any, *, source: Any = None, ran: str = "") -> dict[str, Any]:
    """Both methodologies on one scenario, and where they disagree.

    `ran` is the methodology the person is coming FROM, so the answer can be
    phrased in their direction without changing what is computed. It never
    changes a figure.
    """
    from backend.whatif import run as rn

    results: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for method in me.METHODS:
        try:
            found = rn.execute(state, requested=method, source=source,
                               plausible=False)
        except (rn.RunError, ValueError) as e:
            rows.append({"method": method, "label": me.LABELS[method],
                         "available": False, "because": str(e)})
            continue
        results[method] = found
        rows.append({
            "method": method, "label": me.LABELS[method], "available": True,
            "version": found.choice.version,
            "baseline_ecl": _round(found.summary["baseline_ecl"], 2),
            "whatif_ecl": _round(found.summary["stressed_ecl"], 2),
            "absolute_change": _round(found.summary["incremental_ecl"], 2),
            "percentage_change": _round(found.summary["incremental_ecl_pct"], 3),
            "population": found.population})

    settled = str(ran or state.methodology or "")
    other = next((m for m in me.METHODS if m != settled), "")
    body: dict[str, Any] = {
        "version": COMPARISON_VERSION,
        "scenario": state.describe(),
        "currency": dm.CURRENCY,
        "rows": rows,
        # Both directions, from one object. The phrasing follows whichever
        # methodology the reader arrived on; the figures do not.
        "ran": settled,
        "compared_with": other,
        "direction": (f"{me.LABELS.get(settled, settled)} → "
                      f"{me.LABELS.get(other, other)}") if settled and other
        else "Delta Model ↔ ML Model",
        "statement": (
            "Neither figure is the right one. The Delta Model is the governed "
            "arithmetic carried onto the reported book; the ML model is a "
            "fitted estimate anchored to that same book. Which belongs in a "
            "submission is a governance decision."),
    }

    if len(results) != len(me.METHODS):
        body["available"] = False
        body["why"] = next(
            (r["because"] for r in rows if not r.get("available")),
            "One of the two methodologies could not be run.")
        return body

    delta, ml = results[me.DELTA], results[me.ML]
    spread = (ml.summary["stressed_ecl"] - delta.summary["stressed_ecl"])
    base = abs(delta.summary["stressed_ecl"]) or 1.0
    spread_pct = spread / base * 100.0
    frame = _disagreement(delta, ml)

    body.update({
        "available": True,
        "spread": _round(spread, 2),
        "spread_pct": _round(spread_pct, 3),
        "agree": bool(abs(spread_pct) <= AGREEMENT_PCT),
        "agreement_threshold_pct": AGREEMENT_PCT,
        "matched_borrowers": int(len(frame)),
        "delta_population": delta.population,
        "ml_population": ml.population,
    })
    if body["agree"]:
        body["reading"] = (
            f"The two methodologies priced this scenario within "
            f"{AGREEMENT_PCT}% of each other, which is agreement rather than "
            "a difference worth explaining.")

    if not frame.empty:
        moved = frame.reindex(
            frame["difference"].abs().sort_values(ascending=False).index)
        body["by_sector"] = _grouped(frame, "sector")
        body["by_rating"] = _grouped(frame, "opening_rating")
        body["by_stage"] = _grouped(frame, "stage_stressed")
        body["borrowers"] = [
            {"borrower_id": r.get("borrower_id"),
             "borrower": r.get("display_name"), "sector": r.get("sector"),
             "rating": r.get("opening_rating"),
             "stage": r.get("stage_stressed"),
             "exposure": _round(r.get("ead"), 2),
             "delta_ecl": _round(r.get("ecl_stressed_delta"), 2),
             "ml_ecl": _round(r.get("ecl_stressed_ml"), 2),
             "difference": _round(r.get("difference"), 2),
             "difference_pct": _round(r.get("difference_pct"), 2)}
            for r in moved.head(TOP_N).to_dict(orient="records")]
        higher = int((frame["difference"] > 1e-9).sum())
        lower = int((frame["difference"] < -1e-9).sum())
        body["borrowers_priced_higher_by_ml"] = higher
        body["borrowers_priced_lower_by_ml"] = lower
        body["borrowers_priced_the_same"] = int(len(frame) - higher - lower)

    body["boundary"] = _boundary(delta, frame)

    ml_body = dict(getattr(ml, "ml", {}) or {})
    body["ml"] = {k: v for k, v in ml_body.items()
                  if k in ("model_version", "mean_factor",
                           "fell_back_to_delta", "in_distribution")}
    outside = ml_body.get("out_of_distribution") or []
    body["out_of_distribution"] = [
        {"feature": o.get("feature"), "message": o.get("message")}
        for o in outside][:TOP_N]
    body["warnings"] = list(getattr(ml, "warnings", []) or [])
    return body


def _boundary(delta: Any, frame: pd.DataFrame) -> dict[str, Any]:
    """How the two price the borrowers whose measurement basis just changed.

    The one place a fitted model and the governed arithmetic are expected to
    part company, and the reason is structural rather than a defect: the Stage
    1 to Stage 2 step is a change of MEASUREMENT BASIS — twelve-month to
    lifetime — which is a discontinuity in the arithmetic, not something a
    borrower's features cause. A gradient-boosted model fits a continuous
    surface and smooths across it, so it under-prices a crossing.

    A reader comparing two figures on a migration scenario deserves to be told
    that, on THIS scenario, rather than to find it in a model card.
    """
    if frame.empty or not isinstance(getattr(delta, "borrowers", None),
                                     pd.DataFrame):
        return {"available": False}
    moved = delta.borrowers
    if not {"stage_baseline", "stage_stressed"} <= set(moved.columns):
        return {"available": False}
    crossed = set(moved.loc[moved["stage_stressed"] != moved["stage_baseline"],
                            "borrower_id"].astype(str))
    if not crossed:
        return {"available": True, "crossings": 0,
                "note": "No borrower changed stage under this scenario, so "
                        "there is no measurement-basis crossing for the two "
                        "methodologies to disagree about."}

    base = frame["ecl_stressed_delta"]
    usable = base.abs() > 1e-9
    ratio = (frame["ecl_stressed_ml"][usable] / base[usable])
    is_crossed = frame["borrower_id"].astype(str).isin(crossed)[usable]
    if not is_crossed.any() or is_crossed.all():
        return {"available": True, "crossings": len(crossed)}

    crossing = float(ratio[is_crossed].median())
    holding = float(ratio[~is_crossed].median())
    gap = crossing - holding
    return {
        "available": True,
        "crossings": len(crossed),
        "ml_over_delta_for_crossings": _round(crossing, 4),
        "ml_over_delta_for_the_rest": _round(holding, 4),
        "gap": _round(gap, 4),
        "note": (
            f"The model prices the {len(crossed):,} borrower(s) that changed "
            f"stage at {crossing:.2f} times the Delta figure, against "
            f"{holding:.2f} for those that did not."
            + (" It therefore UNDER-prices the crossings relative to the "
               "governed arithmetic. That is structural: the Stage 1 to "
               "Stage 2 step is a change of measurement basis from a "
               "twelve-month to a lifetime PD, which is a discontinuity, and "
               "a model fitting a continuous surface smooths across it."
               if gap < -0.05 else
               " It therefore OVER-prices the crossings relative to the "
               "governed arithmetic, which is worth understanding before "
               "either figure is used."
               if gap > 0.05 else
               " The two treat a crossing and a non-crossing alike.")),
    }


def packet(body: dict[str, Any]) -> dict[str, Any]:
    """Everything the explanation may state, and nothing else."""
    return {
        "SCENARIO": body.get("scenario"),
        "CURRENCY": body.get("currency"),
        "DIRECTION": body.get("direction"),
        "METHODOLOGIES": [
            {k: v for k, v in row.items()
             if k in ("label", "version", "whatif_ecl", "absolute_change",
                      "percentage_change", "population")}
            for row in (body.get("rows") or []) if row.get("available")],
        "SPREAD": {"absolute": body.get("spread"),
                   "percent": body.get("spread_pct"),
                   "they_agree": body.get("agree"),
                   "agreement_threshold_pct":
                       body.get("agreement_threshold_pct")},
        "WHERE_IT_SITS": {
            "by_sector": body.get("by_sector") or [],
            "by_rating": body.get("by_rating") or [],
            "by_stage": body.get("by_stage") or [],
        },
        "BORROWERS_MOST_APART": body.get("borrowers") or [],
        "HOW_MANY_MOVED": {
            "priced_higher_by_ml": body.get("borrowers_priced_higher_by_ml"),
            "priced_lower_by_ml": body.get("borrowers_priced_lower_by_ml"),
            "priced_the_same": body.get("borrowers_priced_the_same"),
            "matched": body.get("matched_borrowers"),
        },
        "ML_MODEL": body.get("ml") or {},
        "AT_THE_STAGE_BOUNDARY": body.get("boundary") or {},
        "OUTSIDE_WHAT_THE_MODEL_SAW": body.get("out_of_distribution") or [],
        "WARNINGS": body.get("warnings") or [],
        "WHAT_NEITHER_FIGURE_IS": body.get("statement"),
    }


def compose(body: dict[str, Any]) -> dict[str, Any]:
    """The same account, without a model. Shorter, flatter, true."""
    currency = body.get("currency", "SAR")
    if body.get("agree"):
        lines = [body.get("reading", "")]
    else:
        lines = [
            f"The two methodologies priced this scenario "
            f"{currency} {abs(_f(body.get('spread'))):,.1f}m apart, or "
            f"{_f(body.get('spread_pct')):+,.2f}% of the Delta figure."]
        sectors = body.get("by_sector") or []
        if sectors:
            top = sectors[0]
            lines.append(
                f"The largest single concentration is {top['group']}, which "
                f"carries {_f(top.get('share_of_difference_pct')):,.1f}% of "
                "the difference.")
        higher = body.get("borrowers_priced_higher_by_ml")
        lower = body.get("borrowers_priced_lower_by_ml")
        if higher is not None and lower is not None:
            lines.append(
                f"The model priced {higher:,} borrowers above the Delta "
                f"figure and {lower:,} below it.")
    boundary = body.get("boundary") or {}
    if boundary.get("note") and boundary.get("crossings"):
        lines.append(str(boundary["note"]))
    outside = body.get("out_of_distribution") or []
    if outside:
        lines.append(
            f"{len(outside)} feature(s) in this population fall outside the "
            "range the model was trained on, which is a limit on how far the "
            "ML figure should be carried.")
    return {"paragraphs": [" ".join(x for x in lines if x)],
            "headline": lines[0] if lines else "",
            "written_by": "composed from the comparison"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        found = float(value)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(found) else found


def explain(body: dict[str, Any]) -> dict[str, Any]:
    """Why the two differ, written from evidence it cannot exceed."""
    from backend.whatif import narrative as nr

    evidence = packet(body)
    composed = compose(body)
    out: dict[str, Any] = {
        "version": COMPARISON_VERSION,
        "evidence": evidence,
        "statement": (
            "The engine priced this scenario twice. This reading was written "
            "from those two figures and the split between them, and from "
            "nothing else. It does not recommend a methodology: which one "
            "belongs in a submission is a governance decision."),
    }
    if not body.get("available"):
        out.update({"paragraphs": [str(body.get("why", ""))],
                    "headline": "The comparison could not be made.",
                    "written_by": "composed from the comparison",
                    "verified": True})
        return out

    try:
        from backend.llm import get_provider
        from backend.llm import roles as rl

        chosen = rl.role(rl.INTERPRETATION)
        outcome = get_provider().structured(
            system=_SYSTEM,
            prompt=("Explain the difference between these two methodologies "
                    "on this scenario.\n\nEVIDENCE PACKET:\n"
                    + json.dumps(evidence, indent=2, default=str)),
            schema=_SCHEMA,
            tool_name="explain_the_difference",
            tool_description="Explain why two ECL methodologies priced one "
                             "scenario differently, using only the evidence "
                             "packet supplied.",
            max_tokens=2000, purpose="interpretation",
            role=rl.INTERPRETATION, model=chosen.model, effort=chosen.effort)
        paragraphs = [str(p).strip() for p in outcome.data.get("paragraphs", [])
                      if str(p).strip()]
        headline = str(outcome.data.get("headline") or "").strip()
        invented = nr.check([*paragraphs, headline], evidence)
        if paragraphs and not invented:
            out.update({
                "paragraphs": paragraphs,
                "headline": headline or composed["headline"],
                "where_it_sits": [str(x) for x in
                                  (outcome.data.get("where_it_sits") or [])][:5],
                "written_by": outcome.model, "verified": True})
            return out
        if invented:
            logger.warning(
                "The comparison explanation stated figures the evidence does "
                "not contain (%s); using the composed reading instead.",
                ", ".join(invented[:8]))
            out["rejected_because"] = (
                "The written explanation stated figures the evidence did not "
                "contain: " + ", ".join(invented[:8]) + ". It was discarded "
                "rather than shown.")
    except Exception as e:  # noqa: BLE001 - a reading never costs the answer
        # A provider that is off or unreachable is an ordinary state, not an
        # incident. The reason is logged; the traceback would be noise, and it
        # never reaches a reader either way.
        logger.info("Composing the comparison without a model: %s", e)

    out.update({**composed, "verified": True})
    return out


def describe() -> dict[str, Any]:
    """How the comparison is made, for the configuration screen."""
    return {
        "version": COMPARISON_VERSION,
        "methods": [{"method": m, "label": me.LABELS[m]} for m in me.METHODS],
        "agreement_threshold_pct": AGREEMENT_PCT,
        "both_directions": (
            "Whichever methodology produced the result on screen, the other "
            "is one question away. The comparison is the same object either "
            "way — only the direction it is phrased in changes."),
        "statement": (
            "Both methodologies price the SAME shocked book: the engine "
            "applies the scenario once, and the methodology decides only how "
            "the reported ECL is moved from there. That is what makes the two "
            "figures comparable, and it is why a difference between them is a "
            "difference of pricing rather than of scenario."),
    }


__all__ = ["AGREEMENT_PCT", "COMPARISON_VERSION", "ComparisonError", "TOP_N",
           "compare", "compose", "describe", "explain", "packet"]
