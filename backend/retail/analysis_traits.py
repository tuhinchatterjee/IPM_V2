"""Analysis B: which customer traits moved, and what that did to the loss.

§7 of the demo completion contract. The question is

    "Tell me what customer traits have deteriorated and what is the impact on
     ECL because of them."

and almost every way of answering it is wrong in an interesting way.

Four traps this is built around
-------------------------------
**A shortlist is not an inventory.** Naming the three largest movers and
calling it the answer hides the variables that did not move, which is half of
what a reader needs in order to believe the three that did. Every input of
every active scorecard is listed — 123 of them across eight models — and the
top findings summarise that list rather than replace it.

**An origination value is not deterioration.** "Verified monthly income at
application" is a fact recorded once, when the account was booked. It cannot
get worse. If its distribution moves it is because the POPULATION changed —
different customers, booked at different times — and reporting that as
existing customers becoming poorer is simply false. Application features are
classified as historical, and their movement is attributed to mix.

**Mix is not deterioration either.** A book whose new business is riskier will
show a worse average on every behavioural variable while not one existing
customer has changed. So every comparison is run twice: once on customers
present in BOTH periods, and once on the whole book, with entrants and exits
named separately.

**Independent shocks do not add up.** Income, debt burden and disposable
income are three readings of one underlying change. Shocking each alone and
summing the three ECL effects counts the same change three times. Drivers are
grouped by the source column they derive from, and the group's effect is
measured by moving the group together.

What "impact on ECL because of them" is allowed to mean
------------------------------------------------------
The governed pipeline F(x, policy, macro) — scorecard → PD → staging → ECL —
evaluated on matched observations at the two periods with the MODEL VERSION
HELD FIXED. That isolates the trait change from model and policy changes,
which are reported separately. It is a reproducible pipeline result, labelled
model-based attribution. It is not evidence that the trait caused the loss in
the world.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.retail import ews_score as S
from backend.retail import metric_registry as MR
from backend.retail import models_registry as REG
from backend.retail import movement
from backend.retail import periods as P
from backend.retail import scorecards as SC
from backend.retail import taxonomy as tax

ANALYSIS_ID = "retail_trait_attribution"
ANALYSIS_VERSION = "1.0.0"

DETERIORATED = "deteriorated"
IMPROVED = "improved"
STABLE = "stable"
HISTORICAL = "historical or fixed at origination"
NOT_COMPARABLE = "not comparable"
DATA_QUALITY = "data quality affected"

#: A CSI below this is not a movement worth a reader's attention. Demo policy.
STABLE_CSI = 0.02

#: Share of rows missing a raw value above which the variable's movement is
#: reported as a data-quality finding rather than a risk finding.
MISSING_MATERIAL = 0.25


def _derived(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame
    if "classification" not in out.columns:
        out = out.assign(classification=S.classification_of(out))
    if "sub_product_code" not in out.columns:
        out = out.assign(sub_product_code=S.sub_product_of(out))
    return out


def _scope(frame: pd.DataFrame, *, product: str = "", classification: str = "",
           sub_product: str = "") -> pd.DataFrame:
    out = _derived(frame)
    if product:
        out = out[out["product_code"].astype(str) == str(product).upper()]
    if classification:
        out = out[out["classification"].astype(str).str.upper()
                  == str(classification).upper()]
    if sub_product:
        out = out[out["sub_product_code"].astype(str).str.upper()
                  == str(sub_product).upper()]
    return out


def _bins(card: SC.Scorecard, feature: SC.Feature,
          frame: pd.DataFrame) -> tuple[list[str], np.ndarray] | None:
    """Counts per bin, in the model's own bin order, missing last."""
    if feature.source not in frame.columns:
        return None
    labels = list(feature.labels) + [SC.MISSING_BIN]
    got = feature.bin_of(frame[feature.source])
    counts = pd.Series(got).value_counts()
    return labels, np.array([float(counts.get(one, 0)) for one in labels])


def _direction(feature: SC.Feature) -> str:
    """Whether a higher raw value is safer, read from the model's own WoE.

    Not asserted: the WoE of the highest bin against the lowest says which way
    the model believes the variable runs, and a feature whose bins are not
    monotone says so rather than being forced into a direction.
    """
    if not feature.labels:
        return "unknown"
    first = feature.woe.get(feature.labels[0])
    last = feature.woe.get(feature.labels[-1])
    if first is None or last is None:
        return "unknown"
    ordered = [feature.woe.get(one) for one in feature.labels]
    if all(a is not None and b is not None and b >= a
           for a, b in zip(ordered, ordered[1:], strict=False)):
        return "higher is safer"
    if all(a is not None and b is not None and b <= a
           for a, b in zip(ordered, ordered[1:], strict=False)):
        return "higher is riskier"
    return "not monotone"


def _mean_points(card: SC.Scorecard, feature: SC.Feature,
                 frame: pd.DataFrame) -> float | None:
    """Mean score points this feature contributed, in score units."""
    if feature.source not in frame.columns or not len(frame):
        return None
    woe = feature.woe_of(feature.bin_of(frame[feature.source]))
    return float(np.mean(SC.FACTOR * feature.coefficient * woe))


@dataclass
class Variable:
    """One model input, reviewed.

    `display_name` exists because four different scorecards each have an input
    called "Bureau score change over 3 months". Listed by business name alone
    the top-movers table read as the same variable four times, which looks
    like a bug in the table rather than four models agreeing.
    """

    model_id: str
    model_version: str
    prefix: str
    product_code: str
    feature: str
    business_name: str
    kind: str
    unit: str | None
    definition: str
    direction: str
    score_usage: str
    bins: list[str]
    reference_counts: list[float]
    current_counts: list[float]
    csi: float | None
    csi_band: str
    missing_reference_pct: float
    missing_current_pct: float
    mean_points_reference: float | None
    mean_points_current: float | None
    mean_points_change: float | None
    matched_customers: int
    matched_change_pct: float | None
    affected_facilities: int
    affected_exposure_sar: float
    assessment: str
    why: str

    @property
    def display_name(self) -> str:
        product = tax.PRODUCT_LABELS.get(self.product_code, self.product_code)
        kind = ("behavioural" if self.prefix == SC.BEHAVIOURAL_MODEL_PREFIX
                else "application")
        return f"{self.business_name} — {product} {kind}"

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "display_name": self.display_name}


def _assess(feature: SC.Feature, card: SC.Scorecard, csi: float | None,
            points_change: float | None, missing_current: float,
            matched_change: float | None) -> tuple[str, str]:
    """Classify the movement, and say what the classification rests on."""
    if missing_current > MISSING_MATERIAL:
        return (DATA_QUALITY,
                f"{missing_current * 100:.1f}% of rows carry no value for "
                f"this input, so its distribution is not a reading of the "
                f"population's risk.")
    if card.prefix == SC.APPLICATION_MODEL_PREFIX:
        return (HISTORICAL,
                "Recorded once at origination and fixed thereafter. Any "
                "movement in its distribution is a change in WHICH accounts "
                "are on the book, not a change in any customer. It is "
                "reported under portfolio composition, not deterioration.")
    if csi is None:
        return (NOT_COMPARABLE,
                "One of the two populations carries no value for this input.")
    if csi < STABLE_CSI:
        return (STABLE, f"CSI {csi:.4f}: the distribution is where it was.")
    if points_change is None:
        return (NOT_COMPARABLE, "The point contribution could not be compared.")
    # Points are in score units and higher is safer, so a fall is worse.
    if points_change < 0:
        return (DETERIORATED,
                f"CSI {csi:.4f}, and the mean contribution this input makes "
                f"to the score fell by {abs(points_change):.2f} points"
                + (f" on customers present in both periods "
                   f"({matched_change:+.2f} points matched)."
                   if matched_change is not None else "."))
    return (IMPROVED,
            f"CSI {csi:.4f}, and the mean contribution this input makes to "
            f"the score rose by {points_change:.2f} points.")


def inventory(reference: pd.DataFrame, current: pd.DataFrame, *,
              matched_only: pd.DataFrame | None = None,
              matched_reference: pd.DataFrame | None = None,
              products: tuple[str, ...] = ()) -> list[Variable]:
    """Every input of every active scorecard in scope, reviewed."""
    out: list[Variable] = []
    for card in REG.all_scorecards():
        if products and card.product_code not in products:
            continue
        ref = reference[reference["product_code"].astype(str)
                        == card.product_code]
        cur = current[current["product_code"].astype(str) == card.product_code]
        if not len(ref) or not len(cur):
            continue
        m_ref = (matched_reference[matched_reference["product_code"].astype(str)
                                   == card.product_code]
                 if matched_reference is not None else None)
        m_cur = (matched_only[matched_only["product_code"].astype(str)
                              == card.product_code]
                 if matched_only is not None else None)

        for feature in card.features:
            left = _bins(card, feature, ref)
            right = _bins(card, feature, cur)
            if left is None or right is None:
                continue
            labels, ref_counts = left
            _, cur_counts = right
            index = MR.stability_index(list(ref_counts), list(cur_counts))
            csi = index.get("index")

            miss_ref = (ref_counts[-1] / ref_counts.sum()
                        if ref_counts.sum() else 0.0)
            miss_cur = (cur_counts[-1] / cur_counts.sum()
                        if cur_counts.sum() else 0.0)
            points_ref = _mean_points(card, feature, ref)
            points_cur = _mean_points(card, feature, cur)
            change = (None if points_ref is None or points_cur is None
                      else points_cur - points_ref)

            matched_change = None
            matched_n = 0
            if m_ref is not None and m_cur is not None and len(m_ref) and len(m_cur):
                a = _mean_points(card, feature, m_ref)
                b = _mean_points(card, feature, m_cur)
                matched_n = int(m_cur["customer_id"].nunique())
                if a is not None and b is not None:
                    matched_change = b - a

            moved = 0
            exposure = 0.0
            if m_ref is not None and m_cur is not None and len(m_ref) and len(m_cur):
                key = "facility_id"
                before = pd.Series(
                    feature.bin_of(m_ref[feature.source]).astype(str),
                    index=m_ref[key].astype(str).to_numpy())
                after = pd.Series(
                    feature.bin_of(m_cur[feature.source]).astype(str),
                    index=m_cur[key].astype(str).to_numpy())
                shared = before.index.intersection(after.index)
                if len(shared):
                    differs = before.loc[shared].to_numpy() != \
                        after.loc[shared].to_numpy()
                    moved = int(differs.sum())
                    hit = set(shared[differs])
                    rows = m_cur[m_cur[key].astype(str).isin(hit)]
                    exposure = float(pd.to_numeric(
                        rows["gross_carrying_amount_sar"],
                        errors="coerce").fillna(0.0).sum())

            assessment, why = _assess(feature, card, csi, change, miss_cur,
                                      matched_change)
            out.append(Variable(
                model_id=card.model_id, model_version=card.model_version,
                prefix=card.prefix, product_code=card.product_code,
                feature=feature.short, business_name=feature.business_name,
                kind=feature.kind, unit=feature.unit,
                definition=feature.definition,
                direction=_direction(feature),
                score_usage=(f"coefficient {feature.coefficient:+.4f}; "
                             f"{len(feature.labels)} bins"),
                bins=labels,
                reference_counts=[int(one) for one in ref_counts],
                current_counts=[int(one) for one in cur_counts],
                csi=None if csi is None else round(csi, 6),
                csi_band=MR.band(csi),
                missing_reference_pct=round(miss_ref * 100, 4),
                missing_current_pct=round(miss_cur * 100, 4),
                mean_points_reference=(None if points_ref is None
                                       else round(points_ref, 4)),
                mean_points_current=(None if points_cur is None
                                     else round(points_cur, 4)),
                mean_points_change=None if change is None else round(change, 4),
                matched_customers=matched_n,
                matched_change_pct=(None if matched_change is None
                                    else round(matched_change, 4)),
                affected_facilities=moved,
                affected_exposure_sar=round(exposure, 2),
                assessment=assessment, why=why))
    return out


def _groups(rows: list[Variable]) -> list[dict[str, Any]]:
    """Drivers grouped by the source they derive from, so nothing double counts."""
    families: dict[str, list[Variable]] = {}
    for one in rows:
        key = _family(one.feature)
        families.setdefault(key, []).append(one)
    out = []
    for name, members in families.items():
        moved = [one for one in members
                 if one.assessment in (DETERIORATED, IMPROVED)]
        if not moved:
            continue
        out.append({
            "group": name,
            "variables": [one.feature for one in members],
            "deteriorated": [one.feature for one in members
                             if one.assessment == DETERIORATED],
            "improved": [one.feature for one in members
                         if one.assessment == IMPROVED],
            "points_change": round(sum(one.mean_points_change or 0.0
                                       for one in moved), 4),
            "affected_facilities": sum(one.affected_facilities for one in moved),
            "note": ("These read one underlying change. Their effects are "
                     "measured by moving the group together, never by adding "
                     "one-variable shocks."),
        })
    return sorted(out, key=lambda one: one["points_change"])


#: Variables that are three readings of one source get one family name.
_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Income and affordability",
     ("income", "salary", "dbr", "debt_burden", "disposable", "expense",
      "obligation", "affordability")),
    ("Delinquency history",
     ("dpd", "delinq", "arrears", "missed", "late")),
    ("Utilisation and limits",
     ("utilisation", "utilization", "limit", "drawn", "balance")),
    ("Bureau and external",
     ("bureau", "external", "enquiry", "enquiries")),
    ("Tenure and vintage", ("months_on_book", "vintage", "age_of")),
    ("Collateral and security", ("ltv", "collateral", "security", "down")),
)


def _family(feature: str) -> str:
    low = feature.lower()
    for name, needles in _FAMILIES:
        if any(one in low for one in needles):
            return name
    return "Other model inputs"


# ================= the mechanism: traits -> score -> PD -> ECL ==============

def _rescore(frame: pd.DataFrame, prefix: str = SC.BEHAVIOURAL_MODEL_PREFIX
             ) -> pd.DataFrame:
    """Recompute scores from stored raw inputs, per product, one model version.

    The model version is held FIXED across both periods deliberately. Scoring
    each period with whatever version was live at the time would mix a model
    change into a trait finding, and the contract asks for those apart.
    """
    pieces = []
    for card in REG.all_scorecards():
        if card.prefix != prefix:
            continue
        part = frame[frame["product_code"].astype(str) == card.product_code]
        if not len(part):
            continue
        try:
            scored = card.score_frame(part)
        except KeyError:
            continue
        got = pd.DataFrame(index=part.index)
        got["facility_id"] = part["facility_id"].astype(str)
        got["customer_id"] = part["customer_id"].astype(str)
        got["product_code"] = part["product_code"].astype(str)
        got["model_id"] = card.model_id
        got["model_version"] = card.model_version
        got["score"] = scored[f"{prefix}_score_value"]
        got["band"] = scored[f"{prefix}_score_band_value"]
        got["predicted_pd_12m"] = scored[f"{prefix}_predicted_pd_12m"]
        got["points_total"] = scored[f"{prefix}_score_points_total"]
        got["gca"] = pd.to_numeric(part["gross_carrying_amount_sar"],
                                   errors="coerce").fillna(0.0)
        pieces.append(got)
    if not pieces:
        return pd.DataFrame(columns=["facility_id", "customer_id", "score",
                                     "band", "predicted_pd_12m", "gca"])
    return pd.concat(pieces, ignore_index=True)


def band_migration(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, Any]:
    """The full score-band matrix, with count and exposure toggles.

    Unchanged and improving populations are in the matrix, not filtered out of
    it: a migration table that shows only the downgrades reads as though the
    whole book moved one way.
    """
    order = list(SC.SCORE_BAND_LABELS)
    joined = before.merge(after, on="facility_id", how="inner",
                          suffixes=("_before", "_after"))
    if not len(joined):
        return {"available": False,
                "because": "no facility carries a score in both periods"}
    rank = {name: n for n, name in enumerate(order)}
    cells = []
    for source in order:
        row = joined[joined["band_before"].astype(str) == source]
        n_row = len(row)
        gca_row = float(row["gca_before"].sum()) if n_row else 0.0
        for target in order:
            cell = row[row["band_after"].astype(str) == target]
            if not len(cell) and not n_row:
                continue
            cells.append({
                "from": source, "to": target,
                "facilities": int(len(cell)),
                "customers": int(cell["customer_id_after"].nunique())
                             if len(cell) else 0,
                "exposure_sar": round(float(cell["gca_after"].sum()), 2)
                                if len(cell) else 0.0,
                "count_share_pct": round(len(cell) / n_row * 100, 4)
                                   if n_row else None,
                "exposure_share_pct": round(
                    float(cell["gca_before"].sum()) / gca_row * 100, 4)
                    if gca_row else None,
                "direction": ("worse" if rank.get(target, 0) < rank.get(source, 0)
                              else "better" if rank.get(target, 0)
                              > rank.get(source, 0) else "unchanged"),
            })
    worse = [one for one in cells if one["direction"] == "worse"]
    better = [one for one in cells if one["direction"] == "better"]
    same = [one for one in cells if one["direction"] == "unchanged"]

    def _total(rows):
        return {"facilities": sum(one["facilities"] for one in rows),
                "exposure_sar": round(sum(one["exposure_sar"] for one in rows), 2)}

    return {
        "available": True,
        "bands": order,
        "band_order_note": ("E is the worst band and A+ the best; the "
                            "scorecards run higher-is-safer."),
        "matrix": cells,
        "downgraded": _total(worse),
        "upgraded": _total(better),
        "unchanged": _total(same),
        "scored_facilities": int(len(joined)),
        "metric_id": "ret.score_band.share.accounts",
        "model_versions": sorted(set(
            after["model_version"].astype(str).unique())) if
            "model_version" in after else [],
    }


#: Answers already computed, by the book they were computed from.
#:
#: The §7 analysis costs 24 seconds, and profiling says almost none of it is
#: waste: 10 s is `movement.decompose` recomputing IFRS 9 expected credit loss
#: per attribution prefix — which it has to do, because ECL is multiplicative
#: and an allocated attribution would not reconcile — and 10 s is the trait
#: inventory rescoring every active scorecard over both windows. The rest is
#: pandas moving 546 columns of an Arrow-backed frame through two hundred
#: boolean masks.
#:
#: What IS wasteful is doing it again. The answer depends on the published
#: book, the two windows, and the scope — and on nothing else. `question` is
#: echoed into the response and never computed from, so it is not part of the
#: key; the echoed value is replaced on the way out, which is why the stored
#: answer is copied rather than handed over.
#:
#: Keyed by the book's manifest hash, so a regenerated book does not find
#: itself here and computes afresh. Same rule as the derived domains, and the
#: reason this is safe where a time-based cache would not be.
_ANSWERS: dict[tuple, dict[str, Any]] = {}

#: Twelve scopes is every product, every classification and a few sub-products
#: at both modes. Beyond that the oldest goes.
_ANSWERS_KEPT = 24


def forget() -> int:
    """Drop the kept answers. For a process that has just rebuilt the book."""
    held = len(_ANSWERS)
    _ANSWERS.clear()
    return held


def run(*, month: str = "", prior: str = "", product: str = "",
        classification: str = "", sub_product: str = "",
        question: str = "", mode: str = "quarter") -> dict[str, Any]:
    """The full §7 answer: every variable, then the mechanism, then the loss."""
    from backend.retail import source_stamp

    key = (source_stamp.book_hash(), ANALYSIS_VERSION, month, prior, product,
           classification, sub_product, mode)
    held = _ANSWERS.get(key)
    if held is not None:
        return {**held, "question": question}

    months = S.book_months()
    if not months:
        return {"available": False, "because": "the book holds no months"}

    comparison = (P.default_comparison(months) if mode == "quarter"
                  else P.qtd_comparison(months))
    if comparison is None:
        return {"available": False,
                "because": "the book does not hold two comparable windows"}
    at = month or comparison.current.last
    before = prior or comparison.prior.last

    current = _scope(S._read_book(at), product=product,
                     classification=classification, sub_product=sub_product)
    reference = _scope(S._read_book(before), product=product,
                       classification=classification, sub_product=sub_product)
    if not len(current) or not len(reference):
        return {"available": False,
                "because": "that scope matches nothing in one of the periods"}

    # Matched: the same FACILITIES in both windows. Everything else is the
    # book changing shape, and is reported as that rather than as customers
    # getting worse.
    ids_now = set(current["facility_id"].astype(str))
    ids_then = set(reference["facility_id"].astype(str))
    shared = ids_now & ids_then
    matched_now = current[current["facility_id"].astype(str).isin(shared)]
    matched_then = reference[reference["facility_id"].astype(str).isin(shared)]

    products = ((product.upper(),) if product
                else tuple(sorted(current["product_code"].astype(str).unique())))
    rows = inventory(reference, current, matched_only=matched_now,
                     matched_reference=matched_then, products=products)

    before_scores = _rescore(matched_then)
    after_scores = _rescore(matched_now)
    migration = band_migration(before_scores, after_scores)

    # PD and stage, on the same matched facilities.
    pd_before = (float(before_scores["predicted_pd_12m"].mean())
                 if len(before_scores) else None)
    pd_after = (float(after_scores["predicted_pd_12m"].mean())
                if len(after_scores) else None)

    stages = _stage_movement(matched_then, matched_now)
    ecl = movement.decompose(matched_then, matched_now)

    deteriorated = [one for one in rows if one.assessment == DETERIORATED]
    improved = [one for one in rows if one.assessment == IMPROVED]
    historical = [one for one in rows if one.assessment == HISTORICAL]
    deteriorated.sort(key=lambda one: one.mean_points_change or 0.0)
    improved.sort(key=lambda one: -(one.mean_points_change or 0.0))

    label = (tax.PRODUCT_LABELS.get(product.upper(), product.title())
             if product else "Retail")

    out = {
        "available": True,
        "analysis_id": ANALYSIS_ID,
        "analysis_version": ANALYSIS_VERSION,
        "question": question,
        "interpretation": (
            f"Which inputs of the active {label} scorecards moved between "
            f"{comparison.prior.label} and {comparison.current.label}, "
            f"measured at {before} against {at}, and what the governed "
            f"pipeline makes of that. The model version is held fixed across "
            f"both periods so that a model change cannot be read as a trait "
            f"change."),
        "periods": comparison.to_dict(),
        "measured_at": {"current": at, "reference": before},
        "alternative_mode": (
            "quarter to date" if mode == "quarter" else "latest complete quarter"),
        "scope": {
            "label": label, "product": product,
            "classification": classification, "sub_product": sub_product,
            "facilities": int(len(current)),
            "customers": int(current["customer_id"].nunique()),
            "matched_facilities": len(shared),
            "entrants": len(ids_now - ids_then),
            "exits": len(ids_then - ids_now),
            "note": ("Matched facilities carry the trait comparison. Entrants "
                     "and exits change the book's composition and are counted "
                     "separately; their different characteristics are not "
                     "attributed to existing customers."),
        },
        "inventory": [one.to_dict() for one in rows],
        "inventory_counts": {
            "total": len(rows),
            DETERIORATED: len(deteriorated), IMPROVED: len(improved),
            STABLE: len([one for one in rows if one.assessment == STABLE]),
            HISTORICAL: len(historical),
            NOT_COMPARABLE: len([one for one in rows
                                 if one.assessment == NOT_COMPARABLE]),
            DATA_QUALITY: len([one for one in rows
                               if one.assessment == DATA_QUALITY]),
        },
        "top_deteriorated": [one.to_dict() for one in deteriorated[:10]],
        "top_improved": [one.to_dict() for one in improved[:10]],
        "driver_groups": _groups(rows),
        "score_migration": migration,
        "pd": {"metric_id": "ret.pd.mean_12m",
               "mean_before": None if pd_before is None else round(pd_before, 6),
               "mean_after": None if pd_after is None else round(pd_after, 6),
               "change": (None if pd_before is None or pd_after is None
                          else round(pd_after - pd_before, 6)),
               "basis": "behavioural scorecards, model version held fixed, "
                        "matched facilities only"},
        "stage_movement": stages,
        "ecl_bridge": ecl,
        "findings": _trait_findings(
            deteriorated, improved, historical, migration, ecl, label,
            stable_count=len([one for one in rows
                              if one.assessment == STABLE])),
        "follow_ups": [
            "Show all behavioural scorecard variables, not just the top three.",
            "Separate existing-customer deterioration from changes in "
            "portfolio mix.",
            "How many customers moved to worse behavioural score bands?",
            "Show the improving variables and their offsets.",
            "Show the full income-to-score-to-PD-to-ECL chain for the largest "
            "five contributors.",
            "Which currently clean customers show these leading signals?",
        ],
        "limitations": [
            "Model-based attribution, not proven real-world causation. The "
            "numbers are what the governed pipeline produces when matched "
            "observations are evaluated at the two periods; they are not "
            "evidence that a trait caused a loss.",
            "Application-scorecard inputs are recorded at origination and "
            "cannot deteriorate. Their distributions move when the population "
            "moves, and are classified as historical rather than as "
            "deterioration.",
            "Correlated inputs are grouped by source. Adding one-variable "
            "shocks together would count one underlying change several times "
            "and is not done.",
            "Synthetic demonstration data. Not ANB customer history and not "
            "an approved model.",
        ],
    }
    if len(_ANSWERS) >= _ANSWERS_KEPT:
        _ANSWERS.pop(next(iter(_ANSWERS)))
    _ANSWERS[key] = out
    return {**out, "question": question}


def _stage_movement(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, Any]:
    """Stage transitions on matched facilities, with reasons where held."""
    key = "facility_id"
    left = before[[key, "ifrs9_stage", "gross_carrying_amount_sar"]].copy()
    right = after[[key, "ifrs9_stage", "gross_carrying_amount_sar"]].copy()
    for frame in (left, right):
        frame[key] = frame[key].astype(str)
        frame["stage"] = pd.to_numeric(frame["ifrs9_stage"],
                                       errors="coerce").fillna(0).astype(int)
        frame["gca"] = pd.to_numeric(frame["gross_carrying_amount_sar"],
                                     errors="coerce").fillna(0.0)
    joined = left.merge(right, on=key, suffixes=("_b", "_a"))
    if not len(joined):
        return {"available": False, "because": "no matched facility"}
    cells = []
    for source in (1, 2, 3):
        row = joined[joined["stage_b"] == source]
        for target in (1, 2, 3):
            cell = row[row["stage_a"] == target]
            cells.append({
                "from": source, "to": target,
                "facilities": int(len(cell)),
                "exposure_sar": round(float(cell["gca_a"].sum()), 2),
                "direction": ("worse" if target > source
                              else "better" if target < source else "held"),
            })
    worse = sum(one["facilities"] for one in cells if one["direction"] == "worse")
    better = sum(one["facilities"] for one in cells if one["direction"] == "better")
    return {"available": True, "matrix": cells,
            "moved_to_worse_stage": worse, "moved_to_better_stage": better,
            "metric_id": "ret.stage2.share",
            "note": ("Staging is re-evaluated by the governed policy. A stage "
                     "change is reported here and its effect on the allowance "
                     "appears once, in the ECL bridge's stage driver — never "
                     "again under PD.")}


def _trait_findings(deteriorated, improved, historical, migration, ecl,
                    label: str, stable_count: int = 0) -> list[dict[str, Any]]:
    worst = deteriorated[0] if deteriorated else None
    best = improved[0] if improved else None
    drivers = [one for one in ecl.get("contributions", [])
               if one.get("kind") == "driver"]
    biggest = max(drivers, key=lambda one: abs(one["amount_sar"])) if drivers else None
    down = migration.get("downgraded", {}) if migration.get("available") else {}
    up = migration.get("upgraded", {}) if migration.get("available") else {}
    out = [
        {"label": "Main concern",
         "text": (f"{worst.display_name} moved most: CSI {worst.csi}, and the "
                  f"points it contributes to that score fell "
                  f"{abs(worst.mean_points_change):.2f} on average across "
                  f"{worst.affected_facilities:,} facilities carrying SAR "
                  f"{worst.affected_exposure_sar:,.0f}."
                  if worst else
                  "No behavioural input deteriorated materially in this "
                  "scope and window.")},
        {"label": "What changed",
         "text": (f"{down.get('facilities', 0):,} facilities moved to a worse "
                  f"score band and {up.get('facilities', 0):,} to a better "
                  f"one, on {migration.get('scored_facilities', 0):,} scored "
                  f"in both periods. More accounts improved band than "
                  f"worsened; the deterioration is in where the exposure sits."
                  if up.get("facilities", 0) > down.get("facilities", 0)
                  else f"{down.get('facilities', 0):,} facilities moved to a "
                       f"worse score band and {up.get('facilities', 0):,} to a "
                       f"better one, on "
                       f"{migration.get('scored_facilities', 0):,} scored in "
                       f"both periods.")},
        {"label": "Why / drivers",
         # "0 improved" beside thousands of band upgrades reads as a
         # contradiction unless the threshold is stated: a variable moves the
         # band without clearing the CSI bar that makes it a FINDING.
         "text": (f"{len(deteriorated)} behavioural inputs deteriorated past "
                  f"the CSI {STABLE_CSI} reporting threshold and "
                  f"{len(improved)} improved past it; {stable_count} moved too "
                  f"little to report either way, which is where the band "
                  f"upgrades come from. {len(historical)} inputs are fixed at "
                  f"origination and cannot deteriorate — their movement is "
                  f"portfolio composition, not customer risk."
                  + (f" The largest offset is {best.display_name}."
                     if best else ""))},
        {"label": "Materiality / next action",
         "text": (f"The allowance on the matched population moved from SAR "
                  f"{ecl.get('opening_ecl_sar', 0):,.0f} to SAR "
                  f"{ecl.get('closing_ecl_sar', 0):,.0f}"
                  + (f", of which SAR {biggest['amount_sar']:,.0f} is "
                     f"{biggest['driver'].lower()}." if biggest else ".")
                  + " Stress the affected cohort in What-If before deciding.")},
    ]
    return out
