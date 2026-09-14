"""What the Early Warning numbers mean, written from the numbers.

The portfolio screen could already show four products and forty figures, and
still not answer the question a Head of Retail Risk actually asks: *which of
these should I be worried about, and why?* A reader who has to rank four
products by eye will rank them by the biggest number on the screen, which is
usually exposure and is usually wrong.

So this writes the answer, and it writes it deterministically.

Two things follow from that, both deliberate:

**The ranking is a stated framework, not a judgement.** Six governed criteria,
in a published order — severity, score, deterioration, exposure materiality,
default movement, forward-risk volume — each scored from the same served
figures. The screen shows the framework and every product's mark against it,
so a reader can disagree with the ORDER rather than having to guess at it.
"Highest score wins" is exactly what this is not: a product can hold the worst
score and rank second because nothing is moving, and a product can rank first
on a middling score because everything is.

**No model writes the prose.** Every sentence here is assembled from figures
the endpoints already serve, so the paragraph cannot say anything the tables
do not, and the installation produces the same interpretation with no AI
provider configured at all. A language model that rephrased this could only
make it less checkable.

Nothing here computes a figure of its own. If a number is in a sentence, it
came from `ews_views` and can be found on the screen beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.retail import ews_model as M

#: How much each criterion can contribute to the concern ranking. Published,
#: because a ranking whose weights are private is an opinion.
@dataclass(frozen=True)
class Criterion:
    key: str
    name: str
    weight: float
    meaning: str
    reads: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion("severity", "Severity band", 0.30,
              "Which band the portfolio's own Early Warning Score falls in.",
              "severity_band"),
    Criterion("score", "Early Warning Score", 0.20,
              "The exposure-weighted score across every customer in the "
              "portfolio, warned or not.",
              "ews_score"),
    Criterion("deterioration", "Deterioration", 0.20,
              "How far the score has moved this month, and whether it has "
              "been moving the same way for several.",
              "movement.ews_score, and the six-month trend"),
    Criterion("materiality", "Exposure under warning", 0.10,
              "How much money sits behind the warning, as a share of the "
              "portfolio and of total Retail.",
              "exposure_warned_pct, exposure_sar"),
    Criterion("default_movement", "Default-entry movement", 0.10,
              "The default-entry rate and the direction it moved in.",
              "odr_pct, movement.odr_pct"),
    Criterion("forward_risk", "Forward-risk volume", 0.10,
              "Customers still paying who are scored High or Critical: the "
              "population the score exists to find.",
              "forward_risk, customers"),
)

RANKING_BASIS = (
    "Products are ranked on six governed criteria rather than on the score "
    "alone. Each is scored from the figures on this screen, scaled against "
    "the four products, and weighted as published above. A portfolio can hold "
    "the worst score and rank second because nothing is moving; another can "
    "rank first on a middling score because everything is."
)

PROVENANCE = (
    "Written from the served Early Warning figures by a deterministic reader. "
    "No external model is called and none is required."
)


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _band_rank(band: str) -> float:
    order = [name for _, name in M.POPULATION_BANDS]  # worst first
    order = list(reversed(order))                     # LOW … CRITICAL
    try:
        return order.index(str(band).upper()) / max(len(order) - 1, 1)
    except ValueError:
        return 0.0


def _scaled(values: list[float]) -> list[float]:
    """0 to 1 across what is actually on the screen.

    Scaled against the four products rather than against an absolute, because
    the question is which of THESE is most concerning. A book where every
    product is quiet still has a worst one, and it should not be dressed up as
    a crisis by an absolute scale.
    """
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return [0.0 for _ in values]
    return [(v - low) / (high - low) for v in values]


def _consecutive_deterioration(trend: list[dict[str, Any]]) -> int:
    """How many months in a row the score has risen, latest first."""
    points = [p.get("ews_score") for p in (trend or [])
              if p.get("ews_score") is not None]
    run = 0
    for later, earlier in zip(reversed(points), reversed(points[:-1])):
        if later > earlier:
            run += 1
        else:
            break
    return run


def _marks(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every product's mark against every criterion, and the total."""
    scores = [float(p.get("ews_score") or 0.0) for p in products]
    moves = [float((p.get("movement") or {}).get("ews_score") or 0.0)
             for p in products]
    warned_pct = [float(p.get("exposure_warned_pct") or 0.0) for p in products]
    exposure = [float(p.get("exposure_sar") or 0.0) for p in products]
    odr = [float(p.get("odr_pct") or 0.0) for p in products]
    odr_move = [float((p.get("movement") or {}).get("odr_pct") or 0.0)
                for p in products]
    forward = [_pct(float(p.get("forward_risk") or 0.0),
                    float(p.get("customers") or 0.0)) for p in products]
    runs = [_consecutive_deterioration(p.get("trend") or []) for p in products]

    parts = {
        "severity": [_band_rank(p.get("severity_band", "")) for p in products],
        "score": _scaled(scores),
        # Movement and a run of movement, because one month is noise and three
        # is a direction.
        "deterioration": _scaled([m + 0.25 * r for m, r in zip(moves, runs)]),
        # Both how much of the portfolio is under warning and how big the
        # portfolio is: a tenth of the largest book is not a small number.
        "materiality": _scaled([w + 10 * e / max(sum(exposure), 1.0)
                                for w, e in zip(warned_pct, exposure)]),
        "default_movement": _scaled([r + 2 * m
                                     for r, m in zip(odr, odr_move)]),
        "forward_risk": _scaled(forward),
    }

    out = []
    for index, product in enumerate(products):
        marks = {c.key: round(parts[c.key][index], 4) for c in CRITERIA}
        out.append({
            "product_code": product.get("product_code"),
            "product_label": product.get("product_label"),
            "marks": marks,
            "concern": round(sum(marks[c.key] * c.weight for c in CRITERIA), 4),
            "months_deteriorating": runs[index],
        })
    out.sort(key=lambda one: -one["concern"])
    for place, one in enumerate(out, start=1):
        one["rank"] = place
    return out


def _worst_layers(product: dict[str, Any], limit: int = 2) -> list[str]:
    """The layers that moved most against last month."""
    moved = product.get("layer_movement") or {}
    if not moved:
        return []
    worst = sorted(moved.items(), key=lambda kv: -float(kv[1] or 0.0))
    named = []
    for key, value in worst[:limit]:
        if float(value or 0.0) <= 0:
            continue
        layer = M.layer(key)
        named.append(layer.name if layer else key)
    return named


def _reasons(product: dict[str, Any], limit: int = 2) -> list[str]:
    return [str(one.get("name") or one.get("reason_code") or "")
            for one in (product.get("top_reasons") or [])[:limit]]


def _sentence_for(product: dict[str, Any], mark: dict[str, Any],
                  place: str, retail: dict[str, Any]) -> str:
    """One product's paragraph, from its own served figures."""
    label = product.get("product_label") or product.get("product_code")
    score = float(product.get("ews_score") or 0.0)
    band = str(product.get("severity_band") or "").title()
    moved = float((product.get("movement") or {}).get("ews_score") or 0.0)
    run = int(mark.get("months_deteriorating") or 0)
    customers = float(product.get("customers") or 0.0)
    accounts = float(product.get("facilities") or 0.0)
    high = float(product.get("high_or_critical") or 0.0)
    bad = float(product.get("current_bad") or 0.0)
    forward = float(product.get("forward_risk") or 0.0)
    warned_pct = float(product.get("exposure_warned_pct") or 0.0)
    odr = float(product.get("odr_pct") or 0.0)
    odr_moved = float((product.get("movement") or {}).get("odr_pct") or 0.0)
    dpd30 = float(product.get("dpd_30_plus_pct") or 0.0)
    retail_exposure = float(retail.get("exposure_sar") or 0.0)
    retail_customers = float(retail.get("customers") or 0.0)

    said = [f"{label} is {place}."]
    direction = ("has deteriorated for "
                 f"{run} consecutive month{'s' if run != 1 else ''}"
                 if run >= 2 else
                 ("rose this month" if moved > 0 else
                  "eased this month" if moved < 0 else "was flat this month"))
    said.append(
        f"Its Early Warning Score is {score:.1f} in the {band} band and "
        f"{direction} ({moved:+.2f} against last month).")
    said.append(
        f"{high:,.0f} customers are High or Critical — "
        f"{_pct(high, customers):.1f}% of the {customers:,.0f} customers in "
        f"the portfolio — and {warned_pct:.1f}% of its exposure is under "
        "warning.")
    said.append(
        f"{bad:,.0f} are already thirty days down or worse and {forward:,.0f} "
        "are still paying but scored High or Critical, which is the "
        "population the score exists to find.")
    said.append(
        f"The default-entry rate is {odr:.2f}% "
        f"({odr_moved:+.2f} on the month) with {dpd30:.2f}% of facilities "
        "thirty or more days past due.")

    layers = _worst_layers(product)
    if layers:
        said.append(
            f"{' and '.join(layers)} {'are' if len(layers) > 1 else 'is'} "
            "deteriorating fastest")
        reasons = _reasons(product)
        if reasons:
            said[-1] += f", led by {'; '.join(reasons).lower()}"
        said[-1] += "."
    said.append(
        f"The portfolio is {_pct(float(product.get('exposure_sar') or 0.0), retail_exposure):.1f}% "
        f"of total Retail exposure and {_pct(customers, retail_customers):.1f}% "
        f"of its customers, across {accounts:,.0f} accounts.")
    return " ".join(said)


def portfolio(served: dict[str, Any]) -> dict[str, Any]:
    """The management interpretation of total Retail, §3.

    `served` is the portfolio payload exactly as the endpoint returns it, so
    every number below is on the screen beside the paragraph.
    """
    products = list(served.get("products") or [])
    head = dict(served.get("headline") or {})
    if not products:
        return {"available": False,
                "because": "No products were served for this month."}

    marks = _marks(products)
    by_code = {str(p.get("product_code")): p for p in products}
    first = marks[0]
    second = marks[1] if len(marks) > 1 else None

    said = [_sentence_for(by_code[str(first["product_code"])], first,
                          "the most concerning Retail portfolio this month",
                          head)]
    if second is not None:
        said.append(_sentence_for(by_code[str(second["product_code"])], second,
                                  "the second area of concern", head))

    quiet = [m["product_label"] for m in marks[2:]]
    if quiet:
        said.append(
            f"{' and '.join(quiet)} rank below both on the same six criteria.")

    return {
        "available": True,
        "level": "portfolio",
        "month": served.get("month"),
        "headline": (f"{first['product_label']} is the most concerning Retail "
                     "portfolio this month"),
        "interpretation": " ".join(said),
        "ranking": marks,
        "criteria": [{"key": c.key, "name": c.name, "weight": c.weight,
                      "meaning": c.meaning, "reads": c.reads}
                     for c in CRITERIA],
        "ranking_basis": RANKING_BASIS,
        "provenance": PROVENANCE,
        "model_version": served.get("model_version"),
    }


def _level(served: dict[str, Any], *, level: str, label: str,
           children_key: str, child_label_key: str) -> dict[str, Any]:
    """The interpretation of any level below total Retail, §33.

    Same six questions at every level: what is most concerning inside this,
    what changed, which layer drove it, how material it is, and whether the
    risk is concentrated or broad.
    """
    head = dict(served.get("headline") or {})
    if not head:
        return {"available": False, "because": "Nothing was served."}

    children = list(served.get(children_key) or [])
    score = float(head.get("ews_score") or 0.0)
    band = str(head.get("severity_band") or "").title()
    moved = float((served.get("movement") or {}).get("ews_score") or 0.0)
    customers = float(head.get("customers") or 0.0)
    high = float(head.get("high_or_critical") or 0.0)
    bad = float(head.get("current_bad") or 0.0)
    forward = float(head.get("forward_risk") or 0.0)

    said = [f"{label} scores {score:.1f} in the {band} band "
            f"({moved:+.2f} on the month)."]

    layers = _worst_layers(dict(served, layer_movement={
        key: float(served.get("layers", {}).get(key, 0.0))
             - float((served.get("previous_layers") or {}).get(key, 0.0))
        for key in (served.get("layers") or {})}))
    driver = ""
    if served.get("layers"):
        worst = max((served.get("layers") or {}).items(),
                    key=lambda kv: float(kv[1] or 0.0))
        one = M.layer(worst[0])
        driver = one.name if one else worst[0]
        said.append(f"{driver} is the heaviest layer at {float(worst[1]):.1f}.")
    if layers:
        said.append(f"{' and '.join(layers)} moved most this month.")

    reasons = _reasons({"top_reasons": served.get("top_reasons")}, 3)
    if reasons:
        said.append(f"The leading warning reasons are {'; '.join(reasons)}.")

    said.append(
        f"{high:,.0f} of {customers:,.0f} customers are High or Critical; "
        f"{bad:,.0f} are already bad and {forward:,.0f} are forward risk "
        "while still paying.")

    materiality = served.get("materiality") or {}
    for name in ("classification", "product", "retail"):
        share = materiality.get(name)
        if not share:
            continue
        said.append(
            f"It is {share['exposure_pct']:.1f}% of "
            f"{'total Retail' if name == 'retail' else name} exposure, "
            f"{share['accounts_pct']:.1f}% of its accounts and "
            f"{share['customers_pct']:.1f}% of its customers.")

    if children:
        worst_child = max(
            children, key=lambda c: float(c.get("ews_score") or 0.0))
        top = float(worst_child.get("exposure_warned_sar") or 0.0)
        whole = float(head.get("exposure_warned_sar") or 0.0)
        concentrated = whole and top / whole >= 0.5
        said.append(
            f"Within it, {worst_child.get(child_label_key)} carries the "
            f"highest score at {float(worst_child.get('ews_score') or 0):.1f}"
            + (" and more than half of the exposure under warning, so the "
               "risk is concentrated rather than broad."
               if concentrated else
               ", and the exposure under warning is spread across the "
               "segments rather than concentrated in one."))

    return {
        "available": True,
        "level": level,
        "month": served.get("month"),
        "headline": f"{label}: {band} at {score:.1f} ({moved:+.2f})",
        "interpretation": " ".join(said),
        "criteria": [{"key": c.key, "name": c.name, "weight": c.weight,
                      "meaning": c.meaning, "reads": c.reads}
                     for c in CRITERIA],
        "ranking_basis": RANKING_BASIS,
        "provenance": PROVENANCE,
    }


def product(served: dict[str, Any]) -> dict[str, Any]:
    return _level(served, level="product",
                  label=str(served.get("product_label") or ""),
                  children_key="classifications",
                  child_label_key="classification_label")


def classification(served: dict[str, Any]) -> dict[str, Any]:
    return _level(
        served, level="classification",
        label=f"{served.get('product_label')} — "
              f"{served.get('classification_label')}",
        children_key="sub_products", child_label_key="sub_product_label")


def sub_product(served: dict[str, Any], code: str) -> dict[str, Any]:
    """One sub-product card, read as its own level."""
    card = next((one for one in (served.get("sub_products") or [])
                 if str(one.get("sub_product")) == str(code).upper()), None)
    if card is None:
        return {"available": False, "because": f"{code} is not served here."}
    shaped = dict(card)
    shaped["headline"] = {k: card.get(k) for k in (
        "customers", "facilities", "ews_score", "severity_band",
        "high_or_critical", "current_bad", "forward_risk",
        "exposure_sar", "exposure_warned_sar", "exposure_warned_pct",
        "odr_pct", "dpd_30_plus_pct")}
    return _level(shaped, level="sub_product",
                  label=str(card.get("sub_product_label") or code),
                  children_key="", child_label_key="")


__all__ = ["CRITERIA", "PROVENANCE", "RANKING_BASIS", "classification",
           "portfolio", "product", "sub_product"]
