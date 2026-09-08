"""
Every figure an Early Warning answer is allowed to state.

Why the facts are assembled before anything is written
------------------------------------------------------
Fabricating a plausible score in a credit conversation is the single worst
failure this product can have: an invented number reads exactly like the
true ones beside it, and the reader has no way to tell them apart. So the
prose is never allowed to reach for a figure. It is handed a `FactPack`
first — computed here, from the Early Warning domain, and nothing else — and
may only quote what the pack already carries. If the pack does not hold a
figure, the honest answer is that the figure is not available, which is why
several of the derived measures below return `None` rather than a best
guess.

The same pack is what a live model is grounded on when one is configured.
`backend/orchestration/interpretation.py` already discards any prose
containing a figure the result does not carry, so the pack is both the
source for the deterministic reading and the fence around the generated one.

What is derived here rather than read
-------------------------------------
Four measures the brief asks the assistant to be able to state, none of
which exists in the stored data:

* **contribution** — how much of a portfolio or segment move each layer
  accounts for, from the published layer weights applied to the change in
  each layer-dimension mean. This is what turns "risk increased" into
  "Layer 3 contributed 4.2 of the 8-point rise".
* **concentration** — what share of the population's High-or-worse exposure
  a handful of names carry, so "concentrated rather than systemic" is a
  measurement rather than an impression.
* **live vs structural** — the T&A band read against the classifier band. A
  structurally weak obligor with nothing moving and a sound obligor in acute
  distress are different problems with different responses, and the two
  dimensions are kept apart precisely so the difference can be stated.
* **score movement attribution** — how much of a change in the final score
  came from the anchor and how much from the notches. A fall produced by
  notches is not an improvement in the obligor, and the only way to say so
  without hedging is to have measured both parts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.early_warning import aggregation as agg
from backend.early_warning import classifiers_v2 as clf
from backend.early_warning import reasons
from backend.early_warning import v2_service as svc

def json_safe(value: Any) -> Any:
    """The value with every NaN replaced by null, all the way down.

    NaN is a float, it is TRUTHY, and `json.dumps` emits it as the bare
    token `NaN` — which is valid JavaScript, invalid JSON, and rejected by a
    Postgres JSONB column. Every one of those three facts has to be wrong at
    once for the bug to be obvious, which is why it has surfaced twice.
    """
    if isinstance(value, float):
        return None if value != value else value
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return json_safe(value.item())
        except Exception:  # noqa: BLE001
            return str(value)
    return value


#: A numeral as it is written anywhere in the pack, including inside a label.
_NUMERAL = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

#: Bands at or above which an obligor counts as high risk.
HIGH_PLUS = ("HIGH", "VERY_HIGH")

BAND_ORDER = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")

#: The published layer weights on the T&A side, used for contribution.
TA_LAYER_WEIGHTS = agg.TA_LAYER_WEIGHTS

#: The columns that can partition the book into a level. The deck is explicit
#: that the grouping field is not fixed: any obligor attribute or classifier
#: can become the level the screen renders at.
LEVEL_FIELDS: dict[str, str] = {
    "segment": "Corporate segment",
    "sector": "Sector",
    "internal_rating": "Internal grade",
    "ifrs9_stage": "IFRS 9 stage",
    "region": "Region",
    "relationship_manager": "Relationship manager",
    "ews_band": "Early warning severity",
    "dominant_layer": "Dominant layer",
    "utilisation_band": "Utilisation band",
}

LAYER_NAMES = {
    "L1": "Layer 1, internal behavioural",
    "L2": "Layer 2, credit and financial fundamentals",
    "L3": "Layer 3, external intelligence",
    "L4": "Layer 4, network",
}


@dataclass
class FactPack:
    """The figures one answer may use, and where each came from.

    `figures` is flat and JSON-safe so it can be handed to a model as
    grounding, compared against generated prose, and rendered without a
    second shape appearing.
    """

    scope: str
    label: str
    period: str
    figures: dict[str, Any] = field(default_factory=dict)
    #: Rows the answer may show as a table.
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: Which dataset each group of figures came from, for the audit trail.
    provenance: list[str] = field(default_factory=list)
    #: What the reader must be told about the limits of these figures.
    caveats: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Every pack is JSON-safe by construction.

        Sanitising in `to_dict` was not enough: callers read `pack.figures`
        and `pack.rows` directly — the orchestrator does, the API does, the
        investigation payload does — and each of them would have to remember
        on its own. Doing it once, here, means a NaN cannot leave this
        module at all.
        """
        self.figures = json_safe(self.figures)
        self.rows = json_safe(self.rows)
        self.caveats = json_safe(self.caveats)

    def to_dict(self) -> dict[str, Any]:
        """The pack as JSON, with no NaN in it.

        A pack becomes JSON in three places — an API response, an
        investigation message payload, a case's evidence — and two of them
        write to a JSONB column that rejects NaN outright. Most obligors have
        no dominant driver in a given month because no signal fired, so a
        NaN here is the ordinary case rather than an exotic one, and
        sanitising at the boundary means every consumer gets the same
        treatment rather than each discovering it separately.
        """
        return json_safe({
            "scope": self.scope, "label": self.label, "period": self.period,
            "figures": self.figures, "rows": self.rows,
            "provenance": self.provenance, "caveats": self.caveats})

    def numbers(self) -> list[float]:
        """Every numeric value the pack carries, for grounding checks.

        Numerals written inside the pack's own strings count. A driver-tree
        split arrives as the label "Days past due >= 90", and a reading that
        quotes that threshold is quoting the pack, not inventing a number —
        a check that could not see it would report correct prose as a defect,
        which is how a check stops being read.
        """
        found: list[float] = []

        def walk(value: Any) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                found.append(float(value))
            elif isinstance(value, str):
                for raw in _NUMERAL.findall(value):
                    try:
                        found.append(float(raw.replace(",", "")))
                    except ValueError:
                        continue
            elif isinstance(value, dict):
                for v in value.values():
                    walk(v)
            elif isinstance(value, (list, tuple)):
                for v in value:
                    walk(v)

        walk(self.figures)
        walk(self.rows)
        walk(self.caveats)
        return found


# --------------------------------------------------------------- helpers


def _as_list(value: Any) -> list[str]:
    """Overrides are stored as one comma-separated string. A caller that
    treats that as a list gets one entry per character, which is how an
    override line came out reading `c, l, a, s, s, i, f, i, e, r`."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _band_of(score: float) -> str:
    if score >= 80:
        return "VERY_HIGH"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 20:
        return "LOW"
    return "VERY_LOW"


def _dominant_layer(layer_scores: dict[str, float]) -> str | None:
    """Which layer is carrying this obligor's trigger-side risk.

    Read from the T&A side only: the classifier side describes standing
    vulnerability and does not tell a reader where deterioration is being
    detected.
    """
    ta = {"L1": layer_scores.get("l1_ta", 0.0), "L2": layer_scores.get("l2_ta", 0.0),
          "L3": layer_scores.get("l3_ta", 0.0), "L4": layer_scores.get("l4_ta", 0.0)}
    best = max(ta, key=lambda k: ta[k])
    return best if ta[best] > 0 else None


def _with_derived(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the level columns that are derived rather than stored."""
    out = frame.copy()
    if "layer_dimension_scores" in out.columns:
        out["dominant_layer"] = out["layer_dimension_scores"].apply(
            lambda s: _dominant_layer(s or {}) or "none")
    if "utilisation_pct" in out.columns:
        out["utilisation_band"] = pd.cut(
            out["utilisation_pct"], bins=[-0.01, 50, 75, 90, 100, 1e9],
            labels=["under 50%", "50-75%", "75-90%", "90-100%", "over limit"])
        out["utilisation_band"] = out["utilisation_band"].astype(str)
    return out


def _population_figures(pop: pd.DataFrame) -> dict[str, Any]:
    """The measures every population-level answer needs."""
    if pop.empty:
        return {"obligors": 0, "exposure": 0.0, "portfolio_ews": 0.0,
                "high_plus_count": 0, "high_plus_exposure": 0.0}
    exposure = float(pop["exposure"].sum())
    weighted = (float((pop["ews_score"] * pop["exposure"]).sum() / exposure)
                if exposure else float(pop["ews_score"].mean()))
    high = pop[pop["ews_band"].isin(HIGH_PLUS)]
    return {
        "obligors": int(len(pop)),
        "exposure": round(exposure, 2),
        "portfolio_ews": round(weighted, 2),
        "mean_ews": round(float(pop["ews_score"].mean()), 2),
        "high_plus_count": int(len(high)),
        "high_plus_exposure": round(float(high["exposure"].sum()), 2),
        "high_plus_exposure_pct": (round(100.0 * float(high["exposure"].sum()) / exposure, 1)
                                    if exposure else 0.0),
        "band": _band_of(weighted),
    }


def _layer_means(pop: pd.DataFrame) -> dict[str, float]:
    """Exposure-weighted mean of each layer-dimension score."""
    if pop.empty:
        return {}
    exposure = float(pop["exposure"].sum()) or 1.0
    keys = ("l1_ta", "l2_ta", "l3_ta", "l4_ta", "l2_c", "l4_c")
    out: dict[str, float] = {}
    for key in keys:
        values = pop["layer_dimension_scores"].apply(lambda s, k=key: float((s or {}).get(k, 0.0)))
        out[key] = round(float((values * pop["exposure"]).sum() / exposure), 2)
    return out


# ------------------------------------------------------- derived measures


def contribution_by_layer(from_period: str, to_period: str,
                           where: dict[str, str] | None = None) -> dict[str, Any] | None:
    """How much of a move each layer accounts for.

    The T&A dimension is a weighted blend of four layer scores at published
    weights, so a change in the dimension decomposes exactly: each layer
    contributes its own change times its weight. That is what lets an answer
    say "Layer 3 contributed 4.2 of the 8-point rise" instead of "Layer 3 is
    high", which is a different and much weaker claim.

    Returns None when either period is missing rather than guessing — an
    invented contribution is worse than an absent one.
    """
    try:
        start = _with_derived(svc.borrower_month(from_period))
        end = _with_derived(svc.borrower_month(to_period))
    except Exception:  # noqa: BLE001 - a period that does not exist
        return None
    if start.empty or end.empty:
        return None
    if where:
        for column, value in where.items():
            if column not in start.columns:
                return None
            start = start[start[column].astype(str) == str(value)]
            end = end[end[column].astype(str) == str(value)]
    if start.empty or end.empty:
        return None

    before, after = _layer_means(start), _layer_means(end)
    layers = []
    for layer, weight in TA_LAYER_WEIGHTS.items():
        key = f"{layer.lower()}_ta"
        moved = after.get(key, 0.0) - before.get(key, 0.0)
        layers.append({
            "layer": layer, "name": LAYER_NAMES[layer], "weight": weight,
            "score_before": before.get(key, 0.0), "score_after": after.get(key, 0.0),
            "score_change": round(moved, 2),
            "points_contributed": round(moved * weight, 2),
        })
    total_ta_move = round(sum(l["points_contributed"] for l in layers), 2)
    ews_before = _population_figures(start)["portfolio_ews"]
    ews_after = _population_figures(end)["portfolio_ews"]
    layers.sort(key=lambda l: abs(l["points_contributed"]), reverse=True)
    return {
        "from_period": from_period, "to_period": to_period,
        "ews_before": ews_before, "ews_after": ews_after,
        "ews_change": round(ews_after - ews_before, 2),
        "ta_change": total_ta_move,
        "layers": layers,
        "leading_layer": layers[0]["layer"] if layers else None,
    }


def concentration(pop: pd.DataFrame, top_n: int = 5) -> dict[str, Any]:
    """Whether the risk sits in a few names or across the population.

    A concentrated problem is a single-name workout; a systemic one is a
    sector decision. Reporting the share the worst few names carry is what
    lets the answer say which, rather than leaving the reader to infer it.
    """
    high = pop[pop["ews_band"].isin(HIGH_PLUS)] if not pop.empty else pop
    if high.empty:
        return {"high_plus_count": 0, "top_n": top_n, "top_n_share_pct": None,
                "is_concentrated": False, "names": []}
    ranked = high.sort_values("exposure", ascending=False)
    head = ranked.head(top_n)
    total = float(high["exposure"].sum())
    share = round(100.0 * float(head["exposure"].sum()) / total, 1) if total else 0.0
    return {
        "high_plus_count": int(len(high)),
        "top_n": min(top_n, len(ranked)),
        "top_n_share_pct": share,
        # A minority of names carrying most of the high-risk exposure is the
        # test the deck applies before recommending a name-level response
        # rather than a sector one.
        "is_concentrated": bool(share >= 60.0 and len(ranked) > 1) or len(ranked) == 1,
        "names": [{"customer_id": r["customer_id"], "customer_name": r["customer_name"],
                   "exposure": round(float(r["exposure"]), 2),
                   "ews_score": round(float(r["ews_score"]), 2),
                   "ews_band": r["ews_band"]}
                  for _, r in head.iterrows()],
    }


def live_versus_structural(ta_score: float, ta_band: str,
                            classifier_score: float, classifier_band: str) -> dict[str, Any]:
    """Which of the two dimensions is carrying this obligor.

    The dimensions are deliberately never added together, so this reads them
    apart: live deterioration is the trigger and accelerator side; standing
    vulnerability is the classifier side. Where they diverge, the divergence
    is the finding.
    """
    gap = BAND_ORDER.index(ta_band) - BAND_ORDER.index(classifier_band)
    if gap >= 2:
        reading = "live"
    elif gap <= -2:
        reading = "structural"
    else:
        reading = "both"
    return {
        "ta_score": round(float(ta_score), 2), "ta_band": ta_band,
        "classifier_score": round(float(classifier_score), 2),
        "classifier_band": classifier_band,
        "band_gap": gap, "reading": reading,
        "diverges": abs(gap) >= 2,
    }


def movement_attribution(history: pd.DataFrame, months: int = 1) -> dict[str, Any] | None:
    """How much of a score change was the anchor and how much was notching.

    The final score is the matrix anchor plus eight points a notch. A fall
    that came entirely from notches is not an improvement in the obligor's
    condition, and this is the measurement that lets the answer say so
    instead of hedging.
    """
    if history is None or len(history) < months + 1:
        return None
    now = history.iloc[-1]
    then = history.iloc[-(months + 1)]
    anchor_move = float(now["anchor_score"]) - float(then["anchor_score"])
    notch_move = (float(now["net_notches"]) - float(then["net_notches"])) * 8.0
    total = float(now["ews_score"]) - float(then["ews_score"])
    return {
        "from_period": then["snapshot_month"], "to_period": now["snapshot_month"],
        "ews_before": round(float(then["ews_score"]), 2),
        "ews_after": round(float(now["ews_score"]), 2),
        "ews_change": round(total, 2),
        "anchor_before": round(float(then["anchor_score"]), 2),
        "anchor_after": round(float(now["anchor_score"]), 2),
        "anchor_change": round(anchor_move, 2),
        "net_notches_before": int(then["net_notches"]),
        "net_notches_after": int(now["net_notches"]),
        "notch_change_points": round(notch_move, 2),
        # The claim the reader most needs, decided rather than implied.
        "driven_by_notches": bool(abs(notch_move) > abs(anchor_move) and notch_move != 0),
        "condition_improved": bool(anchor_move < 0),
    }


def rating_divergence(period: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Where the early warning score and the internal grade disagree.

    The grade is a classifier and moves on a review cycle; the score is
    trigger-led and moves monthly. They are not supposed to track each other,
    and where they diverge materially either the grade is stale or the
    trigger is a false positive. Either way the divergence is the alert.
    """
    bm = _with_derived(svc.borrower_month(period))
    if bm.empty or "internal_rating" not in bm.columns:
        return {"period": period or svc.latest_period(), "rows": []}
    grades = sorted(bm["internal_rating"].dropna().unique())
    grade_rank = {g: i for i, g in enumerate(grades)}
    band_rank = {b: i for i, b in enumerate(BAND_ORDER)}
    scale = (len(grades) - 1) or 1
    rows = []
    for _, r in bm.iterrows():
        grade = r.get("internal_rating")
        if grade not in grade_rank:
            continue
        # Both onto 0-1 so a five-band severity and an n-grade scale compare.
        grade_pos = grade_rank[grade] / scale
        band_pos = band_rank.get(r["ews_band"], 0) / (len(BAND_ORDER) - 1)
        rows.append({
            "customer_id": r["customer_id"], "customer_name": r["customer_name"],
            "internal_rating": grade, "ews_score": round(float(r["ews_score"]), 2),
            "ews_band": r["ews_band"],
            "divergence": round(band_pos - grade_pos, 3),
        })
    rows.sort(key=lambda x: abs(x["divergence"]), reverse=True)
    return {"period": period or svc.latest_period(), "rows": rows[:limit],
            "grades": grades}


# --------------------------------------------------------------- scopes


def portfolio(period: str | None = None) -> FactPack:
    """The whole book, at one period."""
    period = period or svc.latest_period()
    bm = _with_derived(svc.borrower_month(period))
    figures = _population_figures(bm)
    figures["layers"] = _layer_means(bm)
    figures["severity_distribution"] = [
        {"band": band, "obligors": int((bm["ews_band"] == band).sum()),
         "exposure": round(float(bm[bm["ews_band"] == band]["exposure"].sum()), 2)}
        for band in reversed(BAND_ORDER)
    ]
    figures["concentration"] = concentration(bm)
    figures["dominant_layer_mix"] = [
        {"layer": layer, "obligors": int((bm["dominant_layer"] == layer).sum())}
        for layer in ("L1", "L2", "L3", "L4", "none")
        if int((bm["dominant_layer"] == layer).sum()) > 0
    ]
    periods = svc.periods()
    if len(periods) >= 2:
        figures["movement"] = contribution_by_layer(periods[0], period)
    trend = svc.portfolio_trend()
    figures["trend"] = trend
    rows = svc.top_high_risk(period, limit=10)
    return FactPack(
        scope="portfolio", label="the corporate portfolio", period=period,
        figures=figures, rows=rows,
        provenance=["early_warning_borrower_month"],
        caveats=[_NOT_CALIBRATED],
    )


def level(field_name: str, period: str | None = None) -> FactPack:
    """The book grouped by one field — segment, grade, stage, region, and so on.

    The grouping is not fixed to segment. Any attribute that partitions the
    book can become the level, which is what lets the same screen answer
    "how does this look by grade?" without a second screen existing.
    """
    period = period or svc.latest_period()
    if field_name not in LEVEL_FIELDS:
        raise KeyError(field_name)
    bm = _with_derived(svc.borrower_month(period))
    rows = []
    for value, group in bm.groupby(field_name):
        stats = _population_figures(group)
        layers = _layer_means(group)
        weakest = group.sort_values("ews_score", ascending=False).iloc[0]
        rows.append({
            field_name: str(value), **stats,
            "l1": layers.get("l1_ta"), "l2": layers.get("l2_ta"),
            "l3": layers.get("l3_ta"), "l4": layers.get("l4_ta"),
            "weakest_obligor": weakest["customer_name"],
            "weakest_customer_id": weakest["customer_id"],
        })
    rows.sort(key=lambda r: r["portfolio_ews"], reverse=True)
    figures = _population_figures(bm)
    figures["level_field"] = field_name
    figures["level_label"] = LEVEL_FIELDS[field_name]
    figures["groups"] = len(rows)
    figures["weakest_group"] = rows[0][field_name] if rows else None
    # The exposure the three weakest groups carry between them. It is derived
    # here rather than in the sentence that states it, because a figure a
    # composer adds up on its way to the page is a figure the pack cannot
    # vouch for, and the grounding check is right to refuse it.
    figures["top_three_exposure"] = round(
        sum(r["exposure"] for r in rows[:3]), 4)
    caveats = [_NOT_CALIBRATED]
    if field_name == "internal_rating":
        caveats.append(_GRADE_IS_NOT_EWS)
        figures["divergence"] = rating_divergence(period)
    return FactPack(
        scope="level", label=f"the book by {LEVEL_FIELDS[field_name].lower()}",
        period=period, figures=figures, rows=rows,
        provenance=["early_warning_borrower_month"], caveats=caveats,
    )


def group(field_name: str, value: str, period: str | None = None) -> FactPack:
    """One slice of the book: a named segment, grade band or region."""
    period = period or svc.latest_period()
    if field_name not in LEVEL_FIELDS:
        raise KeyError(field_name)
    bm = _with_derived(svc.borrower_month(period))
    pop = bm[bm[field_name].astype(str) == str(value)]
    if pop.empty:
        raise KeyError(value)
    figures = _population_figures(pop)
    figures["layers"] = _layer_means(pop)
    figures["concentration"] = concentration(pop)
    figures["level_field"] = field_name
    figures["level_value"] = str(value)
    figures["share_of_book_exposure_pct"] = round(
        100.0 * figures["exposure"] / float(bm["exposure"].sum()), 1) if len(bm) else 0.0
    periods = svc.periods()
    if len(periods) >= 2:
        figures["movement"] = contribution_by_layer(
            periods[0], period, where={field_name: str(value)})
    rows = [{"customer_id": r["customer_id"], "customer_name": r["customer_name"],
             "exposure": round(float(r["exposure"]), 2), "dpd": int(r["dpd"]),
             "utilisation_pct": round(float(r["utilisation_pct"]), 1),
             "ews_score": round(float(r["ews_score"]), 2), "ews_band": r["ews_band"],
             "ta_score": round(float(r["ta_score"]), 2),
             "classifier_score": round(float(r["classifier_score"]), 2),
             "dominant_driver": r.get("dominant_driver")}
            for _, r in pop.sort_values("ews_score", ascending=False).iterrows()]
    return FactPack(
        scope="group", label=str(value), period=period, figures=figures,
        rows=rows[:25], provenance=["early_warning_borrower_month"],
        caveats=[_NOT_CALIBRATED],
    )


def borrower(customer_id: str) -> FactPack:
    """One obligor, with everything an answer about it may state."""
    detail = svc.borrower_detail(customer_id)
    latest = detail["latest"]
    history = svc.borrower_history(customer_id)
    layers = latest.get("layer_dimension_scores") or {}
    subcats = latest.get("subcategory_scores") or {}

    ranked = sorted(subcats.items(), key=lambda kv: kv[1], reverse=True)
    drivers = [{
        "code": code, "name": reasons.subcategory_name(code),
        "score": round(float(score), 2), "band": _band_of(float(score)),
        "reason": reasons.subcategory_reason(code, _band_of(float(score))),
        "dimension": "C" if code in clf.SUBCATEGORIES else "T&A",
    } for code, score in ranked if score > 0][:6]

    figures: dict[str, Any] = {
        "customer_id": latest["customer_id"],
        "customer_name": latest["customer_name"],
        "segment": latest.get("segment"), "sector": latest.get("sector"),
        "exposure": round(float(latest["exposure"]), 2),
        "limit": round(float(latest.get("limit") or 0.0), 2),
        "utilisation_pct": round(float(latest.get("utilisation_pct") or 0.0), 1),
        "dpd": int(latest.get("dpd") or 0),
        "ifrs9_stage": int(latest.get("ifrs9_stage") or 1),
        "internal_rating": latest.get("internal_rating"),
        "ews_score": round(float(latest["ews_score"]), 2),
        "ews_band": latest["ews_band"],
        "anchor_score": round(float(latest["anchor_score"]), 2),
        "net_notches": int(latest["net_notches"]),
        "notches": latest.get("notches") or {},
        "layers": {k: round(float(v), 2) for k, v in layers.items()},
        "dominant_layer": _dominant_layer(layers),
        "dominant_subcategory": latest.get("dominant_subcategory"),
        "signal_count_fired": int(latest.get("signal_count_fired") or 0),
        # Stored comma-separated. Split here so a caller listing them does not
        # iterate the string a character at a time.
        "overrides_applied": _as_list(latest.get("overrides_applied")),
        "drivers": drivers,
        "live_versus_structural": live_versus_structural(
            latest["ta_score"], latest["ta_band"],
            latest["classifier_score"], latest["classifier_band"]),
        "movement_1m": movement_attribution(history, months=1),
        "movement_12m": movement_attribution(history, months=12),
        "history": detail["history"],
    }
    # The governed actions this obligor's drivers select, carried on the pack
    # rather than fetched again by whoever writes the sentence. A timeframe
    # the library defines is a figure the answer is entitled to quote, and it
    # can only be quoted safely if the pack is the thing that carries it.
    from backend.early_warning import actions as _act
    recommended = _act.for_drivers([d["code"] for d in drivers])
    figures["actions"] = [a.to_dict() for a in recommended]
    first = _act.single_highest_value(recommended)
    figures["single_highest_value"] = first.to_dict() if first else None
    caveats = [_NOT_CALIBRATED]
    if any(d["code"].startswith("L4") for d in drivers):
        caveats.append(_LAYER_4_EDGES)
    if any(d["code"].startswith("L3") for d in drivers):
        caveats.append(_LAYER_3_SYNTHETIC)
    return FactPack(
        scope="borrower", label=str(latest["customer_name"]),
        period=str(latest["snapshot_month"]), figures=figures,
        rows=detail.get("fired_signals", []),
        provenance=["early_warning_borrower_month",
                    "early_warning_signal_observation"],
        caveats=caveats,
    )


def layer(customer_id: str, layer_code: str) -> FactPack:
    """One layer of one obligor, and the nodes inside it."""
    pack = borrower(customer_id)
    subcats = [d for d in pack.figures["drivers"] if d["code"].startswith(layer_code)]
    tree = svc.layer_tree(customer_id)
    node = next((n for n in tree["tree"] if n["layer"] == layer_code), None)
    figures = {
        "customer_id": customer_id,
        "customer_name": pack.figures["customer_name"],
        "layer": layer_code, "layer_name": LAYER_NAMES.get(layer_code, layer_code),
        "ta_score": (node or {}).get("ta_score"),
        "c_score": (node or {}).get("c_score"),
        "sub_categories": (node or {}).get("sub_categories", []),
        "worst_node": max(subcats, key=lambda d: d["score"]) if subcats else None,
    }
    # The action for this layer's worst node, carried here for the same
    # reason the borrower pack carries its own: the reading quotes the
    # owner and the timeframe, and a figure the pack does not hold is a
    # figure the pack cannot vouch for.
    from backend.early_warning import actions as _act
    within = _act.for_drivers([d["code"] for d in subcats])
    figures["actions"] = [a.to_dict() for a in within]
    first = _act.single_highest_value(within)
    figures["single_highest_value"] = first.to_dict() if first else None
    # Every scope carries the calibration limit. One stated on the portfolio
    # and dropped on the layer is a limit the reader stops seeing exactly
    # where they have drilled far enough to act on what they are reading.
    caveats = [_NOT_CALIBRATED]
    if layer_code == "L3":
        caveats.append(_LAYER_3_SYNTHETIC)
    elif layer_code == "L4":
        caveats.append(_LAYER_4_EDGES)
    return FactPack(
        scope="layer", label=f"{pack.label} — {LAYER_NAMES.get(layer_code, layer_code)}",
        period=pack.period, figures=figures,
        rows=(node or {}).get("sub_categories", []),
        provenance=pack.provenance, caveats=caveats,
    )


def signal_evidence(customer_id: str, signal_key: str,
                     period: str | None = None) -> FactPack | None:
    """One signal's own reading: severity, accelerator, decay and source."""
    found = svc.signal_evidence(customer_id, signal_key, period)
    if found is None:
        return None
    caveats = []
    if found.get("is_synthetic"):
        caveats.append(_LAYER_3_SYNTHETIC)
    if found.get("source_tier") and int(found["source_tier"]) >= 3:
        caveats.append(
            "This reading rests on a single tier-3 source. Corroborate it "
            "before relying on it.")
    return FactPack(
        scope="evidence", label=str(signal_key),
        period=str(found.get("snapshot_month") or ""), figures=found,
        provenance=["early_warning_signal_observation"], caveats=caveats,
    )


def movement(period_from: str | None = None, period_to: str | None = None,
             where: dict[str, str] | None = None) -> FactPack:
    """What moved, and which layer accounts for it."""
    periods = svc.periods()
    period_from = period_from or (periods[0] if periods else "")
    period_to = period_to or svc.latest_period()
    found = contribution_by_layer(period_from, period_to, where=where)
    figures: dict[str, Any] = found or {
        "from_period": period_from, "to_period": period_to,
        "unavailable": "One of those periods is not published, so the "
                       "contribution cannot be decomposed.",
    }
    return FactPack(
        scope="movement",
        label=f"the move from {period_from} to {period_to}",
        period=period_to, figures=figures,
        rows=found["layers"] if found else [],
        provenance=["early_warning_borrower_month"],
        caveats=[_NOT_CALIBRATED],
    )


#: The parts of the model a reader asks about by name. A question about
#: double-counting is not answered by an explanation of the notch model,
#: and being told how the framework works in general when you asked whether
#: a supplier event is being counted twice reads like reassurance.
METHODOLOGY_ASPECTS = ("deduplication", "network", "limits", "reliability",
                       "notches")


def methodology(aspect: str | None = None) -> FactPack:
    """How the score is built, from the model itself rather than from prose.

    Every number here is read from the modules that actually compute the
    score, so a change to the model changes the explanation of it. A
    methodology page maintained by hand drifts from the engine and is worse
    than none.
    """
    from backend.early_warning import catalog, matrix, network, notches
    from backend.early_warning import triggers_v2

    counts = catalog.status_counts()
    return FactPack(
        scope="methodology", label="the Early Warning framework",
        period=svc.latest_period(),
        figures={
            "aspect": aspect if aspect in METHODOLOGY_ASPECTS else None,
            "max_propagation_hops": network.MAX_PROPAGATION_HOPS_DEFAULT,
            "max_propagation_hops_with_approval":
                network.MAX_PROPAGATION_HOPS_WITH_APPROVAL,
            "min_edge_confidence_band": network.MIN_EDGE_CONFIDENCE_BAND,
            "edge_revalidation_months": network.EDGE_REVALIDATION_MONTHS,
            "signals_total": len(catalog.SIGNAL_INVENTORY),
            "signals_scored": counts.get("SCORED", 0),
            "signals_removed": sum(v for k, v in counts.items() if k != "SCORED"),
            "classifiers": len(clf.CLASSIFIER_DEFINITIONS),
            "triggers": len(triggers_v2.TRIGGER_DEFINITIONS),
            "sub_categories": len(agg.TA_SUBCATEGORIES) + len(clf.SUBCATEGORIES),
            "ta_layer_weights": TA_LAYER_WEIGHTS,
            "classifier_layer_weights": clf.CLASSIFIER_LAYER_WEIGHTS,
            "anchor_matrix": matrix.ANCHOR_MATRIX,
            "notches": list(notches.NOTCH_KEYS),
            "points_per_notch": notches.POINTS_PER_NOTCH,
            "net_notch_cap": notches.NET_NOTCH_CAP,
        },
        provenance=["backend.early_warning (the scoring modules themselves)"],
        caveats=[_NOT_CALIBRATED],
    )


def diagnosis(period: str | None = None, *, band: str | None = None,
               segment: str | None = None) -> FactPack:
    """What the selected population has in common, as a driver tree."""
    from backend.early_warning import diagnosis as dg

    found = dg.tree(period, band=band, segment=segment)
    return FactPack(
        scope="diagnosis", label=found["population"],
        period=found["period"], figures=found,
        rows=found.get("leaves") or [],
        provenance=["early_warning_borrower_month"],
        caveats=found["caveats"],
    )


def comparison(field_name: str, left: str, right: str,
                period: str | None = None) -> FactPack:
    """Two groups, read against each other."""
    a, b = group(field_name, left, period), group(field_name, right, period)
    figures = {
        "left": {"label": a.label, **{k: v for k, v in a.figures.items()
                                       if not isinstance(v, (dict, list))}},
        "right": {"label": b.label, **{k: v for k, v in b.figures.items()
                                        if not isinstance(v, (dict, list))}},
        "ews_gap": round(a.figures["portfolio_ews"] - b.figures["portfolio_ews"], 2),
        "weaker": a.label if a.figures["portfolio_ews"] >= b.figures["portfolio_ews"] else b.label,
    }
    return FactPack(
        scope="comparison", label=f"{a.label} against {b.label}",
        period=a.period, figures=figures,
        provenance=["early_warning_borrower_month"], caveats=[_NOT_CALIBRATED],
    )


# ------------------------------------------------------------- caveats

_NOT_CALIBRATED = (
    "The model is not calibrated: every weight, band and multiplier is a "
    "documented starting calibration rather than an estimate fitted to "
    "default data.")

_GRADE_IS_NOT_EWS = (
    "The internal grade is a classifier and moves on a review cycle; the "
    "early warning score is trigger-led and moves monthly. They are not "
    "expected to track each other, and where they diverge materially either "
    "the grade is stale or the trigger is a false positive.")

_LAYER_3_SYNTHETIC = (
    "Layer 3 readings in this deployment are governed synthetic "
    "demonstration data, not a live external intelligence feed.")

_LAYER_4_EDGES = (
    "Layer 4 depends on relationship data. Check edge confidence before "
    "relying on a network driver.")



class PackRuntime:
    """A fact pack in the shape the interpretation seam already reads.

    The seam that offers a result to a live model, checks the prose it gets
    back against what the result establishes, and discards anything
    ungrounded is not specific to a query engine — it wants rows, columns
    and a summary. A pack has all three under different names, so it is
    adapted here rather than the seam being taught a second shape.

    Nothing here changes what a deployment without a provider sees: the
    deterministic reading is written first and stands unless the model
    returns prose that clears the same grounding check.
    """

    def __init__(self, pack: FactPack) -> None:
        self._pack = pack
        self.rows = list(pack.rows)
        self.row_count = len(self.rows)
        names: list[str] = []
        for row in self.rows[:20]:
            for key in row:
                if key not in names:
                    names.append(str(key))
        self.columns = [{"name": n} for n in names]
        # The pack's own figures, which is what most of an Early Warning
        # reading actually quotes — a portfolio answer has no rows at all.
        self.summary = {k: v for k, v in pack.figures.items()
                        if isinstance(v, (int, float, str))
                        and not isinstance(v, bool)}
        self.truncated = 0
        self.warnings = list(pack.caveats)

    @property
    def pack(self) -> FactPack:
        return self._pack


__all__ = [
    "json_safe", "HIGH_PLUS", "BAND_ORDER", "LEVEL_FIELDS", "LAYER_NAMES",
    "METHODOLOGY_ASPECTS", "FactPack", "PackRuntime",
    "contribution_by_layer", "concentration", "live_versus_structural",
    "movement_attribution", "rating_divergence",
    "portfolio", "level", "group", "borrower", "layer", "signal_evidence",
    "movement", "comparison", "methodology", "diagnosis",
]
