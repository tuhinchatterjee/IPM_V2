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
from backend.early_warning import executable as ex
from backend.early_warning import layers as lay
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
#: The levels the book can be cut by, read from the one capability registry.
#:
#: This used to be a second list beside `grain.GROUPINGS`, and the two
#: disagreed on four entries. Nothing checked, so a plan grouping by
#: `dominant_subcategory` — advertised there, absent here — passed validation
#: and raised KeyError in `level()`, taking the whole turn with it. Both now
#: read `executable.GROUPINGS`, so a level that cannot be executed cannot be
#: advertised either.
LEVEL_FIELDS: dict[str, str] = dict(ex.GROUPINGS)

#: One copy of the layer names, read from the registry that owns them. This
#: used to be a second literal beside the API router's own and the two
#: disagreed on L2 and L4.
LAYER_NAMES: dict[str, str] = {code: lay.described(code) for code in lay.CODES}


class UnsupportedLevel(KeyError):
    """A level this domain cannot partition the book by.

    A KeyError subclass so nothing that already caught KeyError stops
    catching it, and a named type so the conversational executor can turn it
    into a repair packet rather than letting it end the turn. The message is
    written for the person reading the trace.
    """

    def __init__(self, field_name: str, message: str = "") -> None:
        self.field_name = field_name
        self.message = message or (
            f"{field_name!r} is not a level the Early Warning book can be "
            f"partitioned by. The levels are: "
            f"{', '.join(sorted(ex.GROUPINGS))}.")
        super().__init__(self.message)

    def __str__(self) -> str:  # KeyError repr quotes its argument
        return self.message


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
    """Add the level columns that are derived, and fill the ones that are
    absent for part of the book.

    Both halves matter. A derived level nobody derives is a KeyError; a
    nullable level nobody fills is worse, because `groupby` drops those rows
    silently and the answer reports a partition of the book that is not the
    book. Most obligors have no fired signal in a quiet month, so
    `dominant_subcategory` is empty for most of them, and a table that
    quietly excluded them would understate the population it claims to
    describe.
    """
    out = frame.copy()
    if "layer_dimension_scores" in out.columns:
        out["dominant_layer"] = out["layer_dimension_scores"].apply(
            lambda s: _dominant_layer(s or {}) or ex.NO_VALUE)
        # The per-layer "this layer fired" flags, from the same roll-up the
        # dominant layer is read from. A question that names a layer needs
        # the layer's own population, not the layer that happens to lead.
        for column, values in lay.activity(
                list(out["layer_dimension_scores"])).items():
            out[column] = values
    if "utilisation_pct" in out.columns:
        out["utilisation_band"] = pd.cut(
            out["utilisation_pct"], bins=[-0.01, 50, 75, 90, 100, 1e9],
            labels=["under 50%", "50-75%", "75-90%", "90-100%", "over limit"])
        out["utilisation_band"] = out["utilisation_band"].astype(str)
    for column in ex.NULLABLE_GROUPINGS:
        if column in out.columns:
            filled = out[column].astype("object").where(
                out[column].notna(), ex.NO_VALUE)
            out[column] = [ex.NO_VALUE if str(v).strip() in ("", "nan")
                           else str(v) for v in filled]
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
        # The same narrowing every other scope uses, so a filter this
        # function does not store as a column — `high_plus` is derived — is
        # applied rather than treated as a missing period.
        #
        # It used to `return None` for any column it did not recognise, and
        # the caller then told the reader "one of those periods is not
        # published". Both periods were published. A thread that had asked
        # about High and Very High obligors carried that filter into the next
        # question, and the answer blamed the data.
        start, end = _narrow(start, where), _narrow(end, where)
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


def _narrow(frame, only: dict[str, Any] | None):
    """The slice a question asked for, applied to a borrower-month frame.

    Unknown keys are ignored rather than raising: the validator has already
    refused a field this domain does not have, and a filter that survives to
    here and does not match a column is a filter on a derived flag that this
    frame does not carry.
    """
    if not only:
        return frame
    out = frame
    for key, value in only.items():
        if key == "high_plus":
            # Derived here rather than assumed: `_with_derived` adds the
            # grouping columns, not the severity flag, so asking for a column
            # that is not there would drop the filter silently — which is the
            # defect this whole path exists to close.
            if value and "ews_band" in out.columns:
                bands = out["ews_band"].astype(str).str.upper().str.replace(
                    " ", "_")
                out = out[bands.isin(("HIGH", "VERY_HIGH"))]
            continue
        if key in out.columns:
            out = out[out[key].astype(str).str.upper()
                      == str(value).upper()] if out[key].dtype == object \
                else out[out[key] == value]
    return out


def level(field_name: str, period: str | None = None, *,
          only: dict[str, Any] | None = None,
          rank_by: str = "") -> FactPack:
    """The book grouped by one field — segment, grade, stage, region, and so on.

    The grouping is not fixed to segment. Any attribute that partitions the
    book can become the level, which is what lets the same screen answer
    "how does this look by grade?" without a second screen existing.

    `only` narrows the population BEFORE grouping, so "exposure by sector for
    obligors at High or Very High" groups the high-risk names rather than the
    whole book. Without it the filter in the question was silently dropped and
    the answer described a wider population than the one that was asked about
    — arithmetically right, and about a different question.
    """
    period = period or svc.latest_period()
    if field_name not in LEVEL_FIELDS:
        raise UnsupportedLevel(field_name)
    bm = _with_derived(svc.borrower_month(period))
    bm = _narrow(bm, only)
    if field_name not in bm.columns:
        # The registry says this level exists and the frame does not have it.
        # That is a build or a derivation problem rather than a bad request,
        # and it is worth saying so plainly rather than raising a KeyError a
        # caller will read as "the planner asked for something silly".
        raise UnsupportedLevel(
            field_name,
            f"{field_name!r} is a governed level but the published rows do "
            f"not carry it. The domain may need rebuilding.")
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
    # What the reader asked the groups to be ordered BY. "Which sectors have
    # the highest external-intelligence score?" is the same partition as
    # "which sectors are weakest" and a different ranking, and answering the
    # first with the second names the wrong sector with the right arithmetic.
    ordering = "portfolio_ews"
    if rank_by:
        code = lay.of_field(rank_by)
        column = code.lower() if code else ""
        if column and rows and column in rows[0]:
            ordering = column
        elif rank_by in (rows[0] if rows else {}):
            ordering = rank_by
    rows.sort(key=lambda r: (r.get(ordering) or 0.0), reverse=True)
    figures = _population_figures(bm)
    figures["level_field"] = field_name
    figures["level_label"] = LEVEL_FIELDS[field_name]
    figures["ranked_by"] = ordering
    figures["ranked_by_label"] = (
        f"{lay.described(lay.of_field(rank_by))} score"
        if rank_by and lay.of_field(rank_by)
        else "exposure-weighted Early Warning score")
    figures["groups"] = len(rows)
    figures["weakest_group"] = rows[0][field_name] if rows else None
    figures["leading_group"] = rows[0][field_name] if rows else None
    figures["leading_value"] = (round(float(rows[0].get(ordering) or 0.0), 2)
                                if rows else None)
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
    if rank_by and lay.of_field(rank_by) == "L3":
        caveats.append(_LAYER_3_SYNTHETIC)
    elif rank_by and lay.of_field(rank_by) == "L4":
        caveats.append(_LAYER_4_EDGES)
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


def layer_population(layer_code: str, period: str | None = None, *,
                     only: dict[str, Any] | None = None,
                     limit: int = 25) -> FactPack:
    """The obligors one detection layer has actually fired for.

    This is the pack behind "which obligors carry external-intelligence
    warning signals?" — a question about WHERE the risk was detected, not
    about how severe the score is. Answering it from the severity ranking
    gives the biggest high-risk names, which is a correct answer to a
    question nobody asked: an obligor can carry a live external event and
    still sit at LOW overall, and that obligor is precisely who is being
    asked after.

    It also carries the corroboration the question after this one always
    turns out to be: how many of these names have something INTERNAL moving
    as well, and how many rest on this layer alone. A single-layer external
    reading is the one a credit officer is right to verify before acting on,
    and the pack says so rather than leaving the reader to infer it.
    """
    entry = lay.BY_CODE.get(str(layer_code).upper())
    if entry is None:
        raise KeyError(layer_code)
    period = period or svc.latest_period()
    book = _with_derived(svc.borrower_month(period))
    narrowed = _narrow(book, only)
    pop = narrowed[narrowed[entry.active_field]]

    figures = _population_figures(pop)
    figures["layer"] = entry.code
    figures["layer_name"] = entry.name
    figures["layer_described"] = lay.described(entry.code)
    figures["book_obligors"] = int(len(book))
    figures["book_exposure"] = round(float(book["exposure"].sum()), 2)
    figures["considered_obligors"] = int(len(narrowed))
    figures["share_of_book_obligors_pct"] = (
        round(100.0 * len(pop) / len(book), 1) if len(book) else 0.0)
    figures["share_of_book_exposure_pct"] = (
        round(100.0 * float(pop["exposure"].sum())
              / float(book["exposure"].sum()), 1)
        if float(book["exposure"].sum()) else 0.0)

    scores = pop["layer_dimension_scores"].apply(
        lambda row, k=entry.ta_key: float((row or {}).get(k) or 0.0)) \
        if len(pop) else None
    figures["layer_score_mean"] = (round(float(scores.mean()), 2)
                                   if scores is not None and len(pop) else 0.0)
    figures["layer_score_max"] = (round(float(scores.max()), 2)
                                  if scores is not None and len(pop) else 0.0)

    # Band mix inside the layer's own population, which is the figure that
    # says whether these names are already on the watchlist or not.
    figures["band_mix"] = [
        {"band": band, "obligors": int((pop["ews_band"] == band).sum())}
        for band in reversed(BAND_ORDER)
        if int((pop["ews_band"] == band).sum()) > 0]

    others = [e for e in lay.LAYERS if e.code != entry.code]
    corroborated = 0
    alone = 0
    for _, row in pop.iterrows():
        elsewhere = any(bool(row.get(e.active_field)) for e in others)
        corroborated += 1 if elsewhere else 0
        alone += 0 if elsewhere else 1
    figures["corroborated_elsewhere"] = corroborated
    figures["this_layer_alone"] = alone
    figures["corroboration_note"] = (
        f"{alone} of {len(pop)} rest on {lay.described(entry.code)} with no "
        f"other layer firing." if len(pop) else "")

    rows = []
    ordered = pop.assign(_layer_score=scores).sort_values(
        "_layer_score", ascending=False) if len(pop) else pop
    for _, row in ordered.head(limit).iterrows():
        scored = row.get("layer_dimension_scores") or {}
        rows.append({
            "customer_id": row["customer_id"],
            "customer_name": row["customer_name"],
            entry.ta_key: round(float(scored.get(entry.ta_key) or 0.0), 2),
            "ews_score": round(float(row["ews_score"]), 2),
            "ews_band": row["ews_band"],
            "exposure": round(float(row["exposure"]), 2),
            "sector": row.get("sector"),
            "dominant_driver": row.get("dominant_driver"),
            "corroborated": any(bool(row.get(e.active_field)) for e in others),
            **{e.ta_key: round(float(scored.get(e.ta_key) or 0.0), 2)
               for e in others},
        })

    caveats = [_NOT_CALIBRATED]
    if entry.code == "L3":
        caveats.append(_LAYER_3_SYNTHETIC)
    elif entry.code == "L4":
        caveats.append(_LAYER_4_EDGES)
    label = f"obligors carrying {entry.name.lower()} signals"
    said: list[str] = []
    for key, value in (only or {}).items():
        if key in lay.ACTIVE_FIELDS or key == lay.FIRING_COUNT_FIELD:
            continue
        if key == lay.CORROBORATED_FIELD:
            said.append("corroborated by another layer" if value
                        else "with no other layer firing")
        elif key == "high_plus":
            said.append("at high severity or above")
        else:
            said.append(f"{key} {value}")
    if said:
        label = f"{label}, {', '.join(said)}"
    return FactPack(
        scope="layer_population", label=label, period=period,
        figures=figures, rows=rows,
        provenance=["early_warning_borrower_month",
                    "early_warning_signal_observation"],
        caveats=caveats)


#: "High or Very High" as one name. It is the watchlist threshold, and it is
#: what a reader means by "moved into High or Very High" — reading it as one
#: band answers about a fifth of the question.
BAND_SET = "HIGH_PLUS"


def _bands_named(said: Any) -> tuple[str, ...]:
    """The band or bands a from/to name stands for."""
    text = str(said or "").upper().replace(" ", "_")
    if not text:
        return ()
    if text == BAND_SET:
        return tuple(HIGH_PLUS)
    return (text,) if text in BAND_ORDER else ()


def transitions(period_from: str | None = None, period_to: str | None = None,
                *, only: dict[str, Any] | None = None,
                from_band: str | None = None, to_band: str | None = None,
                direction: str = "", group_by: str = "",
                limit: int = 25) -> FactPack:
    """Who changed severity band between two published months.

    A band transition is not a score movement, and answering one with the
    other is the defect this exists to close. "How many obligors changed risk
    band this month?" came back as a twenty-month decomposition of the
    portfolio score by layer: correct arithmetic about a real thing, and not
    the thing that was asked. A band change is discrete, it is per obligor,
    and it is what the watchlist and the escalation matrix actually key on —
    a name that crossed into HIGH is a case to open whether its score moved
    two points or twenty.

    Everything here is recomputed from the two published months. Nothing is
    stored, nothing is cached and no figure in this pack was written down by
    anybody: rerun it after a rebuild and it changes with the data, which is
    the only way a transition count stays true.

    The population is the obligors present in BOTH months. An obligor that
    appears or disappears has not changed band — it has entered or left the
    book, which is a different fact and is counted separately rather than
    folded in as a deterioration.
    """
    published = list(svc.periods())
    if not published:
        raise KeyError("no published periods")
    period_to = period_to or published[-1]
    if period_from is None:
        earlier = [p for p in published if p < period_to]
        period_from = earlier[-1] if earlier else period_to
    if period_from not in published or period_to not in published:
        raise KeyError(f"{period_from} -> {period_to}")

    before = _narrow(_with_derived(svc.borrower_month(period_from)), only)
    after = _narrow(_with_derived(svc.borrower_month(period_to)), only)
    before_by = {str(r["customer_id"]): r for r in before.to_dict("records")}
    after_by = {str(r["customer_id"]): r for r in after.to_dict("records")}
    both = [cid for cid in after_by if cid in before_by]

    def rank(band: Any) -> int:
        text = str(band or "").upper().replace(" ", "_")
        return BAND_ORDER.index(text) if text in BAND_ORDER else -1

    moves: list[dict[str, Any]] = []
    matrix: dict[tuple[str, str], dict[str, Any]] = {}
    improved = deteriorated = unchanged = 0
    into_high = out_of_high = 0
    exposure_worse = exposure_better = 0.0

    for cid in both:
        was, now = before_by[cid], after_by[cid]
        old_band = str(was["ews_band"])
        new_band = str(now["ews_band"])
        step = rank(new_band) - rank(old_band)
        way = ("deteriorated" if step > 0 else
               "improved" if step < 0 else "unchanged")
        exposure = float(now["exposure"])
        if way == "deteriorated":
            deteriorated += 1
            exposure_worse += exposure
        elif way == "improved":
            improved += 1
            exposure_better += exposure
        else:
            unchanged += 1
        was_high = old_band in HIGH_PLUS
        now_high = new_band in HIGH_PLUS
        into_high += 1 if (now_high and not was_high) else 0
        out_of_high += 1 if (was_high and not now_high) else 0

        cell = matrix.setdefault((old_band, new_band),
                                 {"from_band": old_band, "to_band": new_band,
                                  "obligors": 0, "exposure": 0.0})
        cell["obligors"] += 1
        cell["exposure"] = round(cell["exposure"] + exposure, 2)

        if step == 0:
            continue
        moves.append({
            "customer_id": cid,
            "customer_name": now.get("customer_name"),
            "from_band": old_band, "to_band": new_band,
            "bands_moved": abs(step), "direction": way,
            "ews_score_before": round(float(was["ews_score"]), 2),
            "ews_score_after": round(float(now["ews_score"]), 2),
            "score_change": round(float(now["ews_score"])
                                  - float(was["ews_score"]), 2),
            "exposure": round(exposure, 2),
            "sector": now.get("sector"),
            "dominant_driver": now.get("dominant_driver"),
            "crossed_into_high_plus": bool(now_high and not was_high),
        })

    # The drill-down the question asked for, applied AFTER the counts so the
    # population figures still describe the whole move and the rows describe
    # the slice. A reader who asks "who went from High to Very High" needs
    # both: the four names, and the fact that thirty-one others moved too.
    drill = list(moves)
    wanted_from = _bands_named(from_band)
    wanted_to = _bands_named(to_band)
    if from_band and not wanted_from:
        raise KeyError(from_band)
    if to_band and not wanted_to:
        raise KeyError(to_band)
    if wanted_from:
        # A move that started AND ended inside the named set has not left it.
        # "Who came out of High or Very High?" must not return a name that
        # went from HIGH to VERY_HIGH — it deteriorated, inside the set.
        drill = [m for m in drill if m["from_band"] in wanted_from
                 and (len(wanted_from) == 1 or m["to_band"] not in wanted_from)]
    if wanted_to:
        drill = [m for m in drill if m["to_band"] in wanted_to
                 and (len(wanted_to) == 1 or m["from_band"] not in wanted_to)]
    if direction in ("improved", "deteriorated"):
        drill = [m for m in drill if m["direction"] == direction]
    drill.sort(key=lambda m: (-m["bands_moved"], -m["exposure"]))

    figures: dict[str, Any] = {
        "from_period": period_from, "to_period": period_to,
        "obligors_in_both": len(both),
        "entered_the_book": len([c for c in after_by if c not in before_by]),
        "left_the_book": len([c for c in before_by if c not in after_by]),
        "changed": improved + deteriorated,
        "improved": improved,
        "deteriorated": deteriorated,
        "unchanged": unchanged,
        "crossed_into_high_plus": into_high,
        "left_high_plus": out_of_high,
        "exposure_deteriorated": round(exposure_worse, 2),
        "exposure_improved": round(exposure_better, 2),
        "matrix": sorted(
            (cell for cell in matrix.values()),
            key=lambda c: (-c["obligors"], c["from_band"], c["to_band"])),
        "band_counts_before": {
            band: int((before["ews_band"] == band).sum())
            for band in reversed(BAND_ORDER)},
        "band_counts_after": {
            band: int((after["ews_band"] == band).sum())
            for band in reversed(BAND_ORDER)},
        "drilled": len(drill),
        "drill_filter": {k: v for k, v in
                         (("from_band", from_band), ("to_band", to_band),
                          ("direction", direction)) if v},
        "drill_exposure": round(sum(m["exposure"] for m in drill), 2),
    }

    # "Which sectors had the most adverse band migrations?" is the same
    # transition read one level up. Grouped here rather than by the caller,
    # because a count a composer adds up on its way to the page is a figure
    # the pack cannot vouch for.
    if group_by:
        if group_by not in LEVEL_FIELDS:
            raise UnsupportedLevel(group_by)
        if group_by not in after.columns:
            raise UnsupportedLevel(
                group_by,
                f"{group_by!r} is a governed level but the published rows do "
                f"not carry it.")
        buckets: dict[str, dict[str, Any]] = {}
        for cid in both:
            value = str(after_by[cid].get(group_by) or ex.NO_VALUE)
            cell = buckets.setdefault(value, {
                group_by: value, "obligors": 0, "deteriorated": 0,
                "improved": 0, "unchanged": 0, "changed": 0,
                "exposure_deteriorated": 0.0, "exposure_improved": 0.0,
                "crossed_into_high_plus": 0})
            cell["obligors"] += 1
        for move in moves:
            value = str(after_by[move["customer_id"]].get(group_by)
                        or ex.NO_VALUE)
            cell = buckets[value]
            cell["changed"] += 1
            cell[move["direction"]] += 1
            key = ("exposure_deteriorated" if move["direction"] == "deteriorated"
                   else "exposure_improved")
            cell[key] = round(cell[key] + move["exposure"], 2)
            cell["crossed_into_high_plus"] += (
                1 if move["crossed_into_high_plus"] else 0)
        for cell in buckets.values():
            cell["unchanged"] = cell["obligors"] - cell["changed"]
            cell["net_adverse"] = cell["deteriorated"] - cell["improved"]
        grouped = sorted(
            buckets.values(),
            key=lambda c: (-c["deteriorated"], -c["net_adverse"],
                           -c["exposure_deteriorated"], c[group_by]))
        figures["grouped_by"] = group_by
        figures["grouped_label"] = LEVEL_FIELDS[group_by]
        figures["groups"] = len(grouped)
        figures["groups_with_adverse_moves"] = sum(
            1 for c in grouped if c["deteriorated"])
        figures["worst_group"] = grouped[0][group_by] if grouped else None
        figures["group_rows"] = grouped
    if period_from == period_to:
        figures["single_period"] = True

    label = f"band transitions from {period_from} to {period_to}"
    rows = (figures["group_rows"][:limit] if group_by
            else drill[:limit])
    return FactPack(
        scope="transitions", label=label, period=period_to,
        figures=figures, rows=rows,
        provenance=["early_warning_borrower_month"],
        caveats=[_NOT_CALIBRATED])


def population_actions(period: str | None = None, *,
                       only: dict[str, Any] | None = None,
                       limit: int = 10) -> FactPack:
    """What the matrix and the library say for a POPULATION, not one name.

    "Should either be escalated?" and "what should I do about these names?"
    are ordinary questions and had no reading at all: the action executor
    could only read one obligor, so a population-scoped action step produced
    nothing, and the answer fell back to whatever else the plan had run — a
    sector summary in place of an escalation decision.

    Routing an average would be meaningless, so nothing here averages: each
    obligor at high severity or above is routed individually by the governed
    matrix and the rungs are then counted. What the reader gets is how many
    cases go where, and which names are behind each.
    """
    from backend.early_warning import actions as act
    from backend.early_warning import escalation as esc

    period = period or svc.latest_period()
    book = _with_derived(svc.borrower_month(period))
    pop = _narrow(book, only)
    high = pop[pop["ews_band"].isin(HIGH_PLUS)].sort_values(
        "exposure", ascending=False)

    figures: dict[str, Any] = _population_figures(pop)
    figures["period"] = period
    figures["considered"] = int(len(pop))

    rungs: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for _, row in high.iterrows():
        route = esc.route_for(str(row["ews_band"]), float(row["exposure"]))
        # The rung's TITLE, not its code. "L2" is a ladder level and also a
        # layer name, and a reader told a case is "decided by L2" cannot
        # tell which of the two they are being told.
        titles = []
        for level in (route.get("escalated_to") or []):
            rung = next((r for r in esc.LADDER if r["level"] == level), None)
            titles.append(str(rung["role"]) if rung else str(level))
        if not titles:
            titles = [str(t) for t in (route.get("escalated_to_roles") or [])]
        where = ", ".join(titles) or "no escalation required"
        cell = rungs.setdefault(where, {
            "decided_by": where, "obligors": 0, "exposure": 0.0,
            "ack_sla_days": route.get("ack_sla_days"),
            "decision_sla_days": route.get("decision_sla_days"),
            "names": []})
        cell["obligors"] += 1
        cell["exposure"] = round(cell["exposure"] + float(row["exposure"]), 2)
        if len(cell["names"]) < 5:
            cell["names"].append(str(row["customer_name"]))
        rows.append({
            "customer_id": row["customer_id"],
            "customer_name": row["customer_name"],
            "ews_score": round(float(row["ews_score"]), 2),
            "ews_band": str(row["ews_band"]),
            "exposure": round(float(row["exposure"]), 2),
            "decided_by": where,
            "ack_sla_days": route.get("ack_sla_days"),
            "decision_sla_days": route.get("decision_sla_days"),
            "dominant_subcategory": row.get("dominant_subcategory"),
        })

    figures["routes"] = sorted(rungs.values(),
                               key=lambda c: (-c["obligors"], c["decided_by"]))
    figures["cases"] = int(len(high))

    # The actions the library selects for the nodes these names are actually
    # driven by — governed, not composed at answer time.
    nodes = [str(n) for n in high.get("dominant_subcategory", []) if n]
    selected = act.for_drivers(nodes) if nodes else []
    figures["actions"] = [a.to_dict() for a in selected][:limit]
    first = act.single_highest_value(selected) if selected else None
    figures["single_highest_value"] = first.to_dict() if first else None
    figures["common_node"] = (max(set(nodes), key=nodes.count)
                              if nodes else None)

    label = "the corporate portfolio"
    named = [str(v) for k, v in (only or {}).items()
             if not isinstance(v, bool)]
    if named:
        label = ", ".join(named)
    return FactPack(
        scope="population_action", label=label, period=period,
        figures=figures, rows=rows[:limit],
        provenance=["early_warning_borrower_month",
                    "escalation matrix", "governed action library"],
        caveats=[_NOT_CALIBRATED])


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


def _both_published(*periods: str) -> bool:
    published = set(svc.periods())
    return all(p in published for p in periods if p)


def movement(period_from: str | None = None, period_to: str | None = None,
             where: dict[str, str] | None = None, *,
             customer_id: str = "") -> FactPack:
    """What moved, and which layer accounts for it.

    `customer_id` narrows the whole reading to ONE obligor. Without it, "did
    Tihama Projects 3 improve over the last six months?" was planned
    correctly — a movement step carrying the obligor — and then decomposed
    over the entire portfolio, because this function had nowhere to put the
    obligor and the executor quietly dropped it. The answer named a change
    of -1.8 points that belonged to the book, for a name whose own score is
    zero.
    """
    if customer_id:
        return _borrower_movement(customer_id, period_from, period_to)
    periods = svc.periods()
    period_from = period_from or (periods[0] if periods else "")
    period_to = period_to or svc.latest_period()
    found = contribution_by_layer(period_from, period_to, where=where)
    figures: dict[str, Any] = found or {
        "from_period": period_from, "to_period": period_to,
        # Say which of the two things went wrong. "One of those periods is
        # not published" was printed for an unpublished period AND for a
        # population that the filter emptied, and a reader told the data is
        # missing when their filter matched nobody goes looking in the wrong
        # place.
        "unavailable": (
            "One of those periods is not published, so the contribution "
            "cannot be decomposed."
            if not _both_published(period_from, period_to) else
            "No obligor matches that filter in both periods, so there is "
            "nothing to decompose between them."),
    }
    return FactPack(
        scope="movement",
        label=f"the move from {period_from} to {period_to}",
        period=period_to, figures=figures,
        rows=found["layers"] if found else [],
        provenance=["early_warning_borrower_month"],
        caveats=[_NOT_CALIBRATED],
    )


def _borrower_movement(customer_id: str, period_from: str | None,
                       period_to: str | None) -> FactPack:
    """One obligor's own move, decomposed the same way the portfolio's is.

    The same shape as the population reading — `from_period`, `to_period`,
    `ews_before`, `ews_after`, `ews_change`, `layers` — so one composer
    writes both and the two answers cannot drift into different sentences
    for the same kind of fact.
    """
    periods = list(svc.periods())
    period_to = period_to or (periods[-1] if periods else "")
    period_from = period_from or (periods[0] if periods else period_to)
    label = f"{customer_id}"

    def read(period: str) -> dict[str, Any] | None:
        frame = svc.borrower_month(period)
        hit = frame[frame["customer_id"].astype(str) == str(customer_id)]
        return hit.iloc[0].to_dict() if len(hit) else None

    before, after = read(period_from), read(period_to)
    if before is None or after is None:
        return FactPack(
            scope="movement", label=label, period=period_to,
            figures={"from_period": period_from, "to_period": period_to,
                     "unavailable": (
                         f"{customer_id} is not published in both "
                         f"{period_from} and {period_to}, so there is "
                         f"nothing to compare.")},
            provenance=["early_warning_borrower_month"],
            caveats=[_NOT_CALIBRATED])

    def scores(row: dict[str, Any]) -> dict[str, float]:
        raw = row.get("layer_dimension_scores") or {}
        if isinstance(raw, str):
            import json as _json

            raw = _json.loads(raw)
        return {k: float(v or 0.0) for k, v in dict(raw).items()}

    was, now = scores(before), scores(after)
    layers = []
    for code, weight in TA_LAYER_WEIGHTS.items():
        key = f"{code.lower()}_ta"
        change = now.get(key, 0.0) - was.get(key, 0.0)
        layers.append({
            "layer": code, "name": LAYER_NAMES[code], "weight": weight,
            "score_before": round(was.get(key, 0.0), 2),
            "score_after": round(now.get(key, 0.0), 2),
            "score_change": round(change, 2),
            "points_contributed": round(change * weight, 2),
        })
    layers.sort(key=lambda entry: abs(entry["points_contributed"]), reverse=True)

    figures: dict[str, Any] = {
        "customer_id": customer_id,
        "customer_name": after.get("customer_name"),
        "from_period": period_from, "to_period": period_to,
        "ews_before": round(float(before["ews_score"]), 2),
        "ews_after": round(float(after["ews_score"]), 2),
        "ews_change": round(float(after["ews_score"])
                            - float(before["ews_score"]), 2),
        "band_before": str(before["ews_band"]),
        "band_after": str(after["ews_band"]),
        # The anchor and the notches apart, because a score that fell while
        # its anchor held has not improved — the notch model moved, and the
        # condition underneath it did not.
        "anchor_before": round(float(before["anchor_score"]), 2),
        "anchor_after": round(float(after["anchor_score"]), 2),
        "anchor_change": round(float(after["anchor_score"])
                               - float(before["anchor_score"]), 2),
        "notches_before": int(before["net_notches"]),
        "notches_after": int(after["net_notches"]),
        "layers": layers,
    }
    return FactPack(
        scope="movement",
        label=f"{after.get('customer_name') or customer_id}, "
              f"{period_from} to {period_to}",
        period=period_to, figures=figures, rows=layers,
        provenance=["early_warning_borrower_month"],
        caveats=[_NOT_CALIBRATED])


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
               segment: str | None = None,
               where: dict[str, Any] | None = None) -> FactPack:
    """What the selected population has in common, as a driver tree."""
    from backend.early_warning import diagnosis as dg

    found = dg.tree(period, band=band, segment=segment, where=where)
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
    "layer_population", "population_actions", "transitions",
    "METHODOLOGY_ASPECTS", "FactPack", "PackRuntime",
    "contribution_by_layer", "concentration", "live_versus_structural",
    "movement_attribution", "rating_divergence",
    "portfolio", "level", "group", "borrower", "layer", "signal_evidence",
    "movement", "comparison", "methodology", "diagnosis",
]
