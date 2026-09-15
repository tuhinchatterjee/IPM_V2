"""Analysis A: the whole answer to "why has this delinquency rate risen?".

§6 of the demo completion contract. The attention card states a fact; this
states the reasons, in the order a credit officer would want them:

  1. what the rate is, both ways of weighting it, and against what;
  2. where facilities actually moved — including the ones that got better;
  3. how those movements add up to the change in the rate;
  4. which segments the change sits in, mix separated from within-rate;
  5. separately, what the loss allowance did, and why;
  6. which pockets and which customers carry it.

Steps 2-5 are observations. Step 5 is a model output and is kept apart from
the others for the reason the contract insists on: a revision to modelled PD
cannot be the reason a customer missed a payment. It is a consequence
measured on the same population, not a cause of the arrears.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.retail import decomposition as D
from backend.retail import ews_score as S
from backend.retail import metric_registry as MR
from backend.retail import movement
from backend.retail import periods as P
from backend.retail import taxonomy as tax

ANALYSIS_ID = "retail_delinquency_decomposition"
ANALYSIS_VERSION = "1.0.0"

#: How far back the trend behind an attention card is drawn.
TREND_MONTHS = 6


def _derived(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the two dimensions the canonical book does not carry.

    Salaried / non-salaried and the Saudi sub-product tier are DERIVED — the
    Early Warning scoring domain computes them and the book does not hold
    them. A mix bridge that silently skipped them because the column was
    absent reported "Product" as the only cut a reader could make, which is
    not what the screen offers.
    """
    out = frame
    if "classification" not in out.columns:
        out = out.assign(classification=S.classification_of(out))
    if "sub_product_code" not in out.columns:
        out = out.assign(sub_product_code=S.sub_product_of(out))
    return out


def _scope(frame: pd.DataFrame, *, product: str = "",
           classification: str = "", sub_product: str = "") -> pd.DataFrame:
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


def _rate(frame: pd.DataFrame, weighting: str) -> float:
    late = [one.upper() for one in D.THIRTY_PLUS]
    bucket = frame["dpd_bucket"].astype(str).str.upper()
    mask = bucket.isin(late)
    if weighting == "exposure":
        total = pd.to_numeric(frame["gross_carrying_amount_sar"],
                              errors="coerce").fillna(0.0)
        return float(total[mask].sum()) / float(total.sum()) * 100 \
            if float(total.sum()) else 0.0
    return float(mask.sum()) / len(frame) * 100 if len(frame) else 0.0


def trend(months: list[str], *, product: str = "", classification: str = "",
          sub_product: str = "") -> list[dict[str, Any]]:
    """The series the attention card was raised on, both weightings."""
    out: list[dict[str, Any]] = []
    for month in months:
        frame = _scope(S._read_book(month), product=product,
                       classification=classification, sub_product=sub_product)
        if not len(frame):
            continue
        out.append({
            "month": month,
            "exposure_weighted_pct": round(_rate(frame, "exposure"), 4),
            "account_weighted_pct": round(_rate(frame, "accounts"), 4),
            "facilities": int(len(frame)),
            "customers": int(frame["customer_id"].nunique()),
            "exposure_sar": round(float(pd.to_numeric(
                frame["gross_carrying_amount_sar"],
                errors="coerce").fillna(0.0).sum()), 2),
        })
    return out


def _pockets(opening: pd.DataFrame, closing: pd.DataFrame,
             by: str, label: str) -> dict[str, Any]:
    out = D.mix_bridge(opening, closing, by=by)
    if out.get("available"):
        out["label"] = label
    return out


def _top_customers(opening: pd.DataFrame, closing: pd.DataFrame,
                   limit: int = 10) -> list[dict[str, Any]]:
    """Who carries the movement into 30+, by exposure that crossed."""
    left, right = D._side(opening), D._side(closing)
    joined = left.merge(right, on="facility_id", how="inner",
                        suffixes=("_open", "_close"))
    late = [one.upper() for one in D.THIRTY_PLUS]
    crossed = joined[(~joined["bucket_open"].str.upper().isin(late))
                     & (joined["bucket_close"].str.upper().isin(late))]
    if not len(crossed):
        return []
    grouped = crossed.groupby(crossed["customer_id_close"].astype(str))
    rows = []
    for customer, part in grouped:
        rows.append({
            "customer_id": customer,
            "customer_name": S.display_name(customer),
            "facilities_crossing": int(len(part)),
            "exposure_crossing_sar": round(float(part["gca_close"].sum()), 2),
            "from_buckets": sorted({D._canonical(one)
                                    for one in part["bucket_open"]}),
            "to_buckets": sorted({D._canonical(one)
                                  for one in part["bucket_close"]}),
        })
    rows.sort(key=lambda one: -one["exposure_crossing_sar"])
    return rows[:limit]


def _findings(rate: dict[str, Any], moves: D.Transitions,
              bridge: dict[str, Any], ecl: dict[str, Any],
              label: str) -> list[dict[str, Any]]:
    """Four short findings, each tied to a number that is on the page."""
    drivers = [one for one in ecl.get("contributions", [])
               if one.get("kind") == "driver"]
    biggest = max(drivers, key=lambda one: abs(one["amount_sar"])) \
        if drivers else None
    arrears = next((one for one in bridge["parts"]
                    if one["part"] == "Arrears moved"), None)
    book = next((one for one in bridge["parts"]
                 if one["part"] == "The book moved"), None)
    cures = next((one for one in bridge["numerator_flows"]
                  if one["flow"] == "Cures"), None)
    new = next((one for one in bridge["numerator_flows"]
                if one["flow"] == "New arrears"), None)
    out = [
        {"label": "What moved",
         "text": (f"{label} 30+ DPD rose from "
                  f"{bridge['opening']['rate_pct']}% to "
                  f"{bridge['closing']['rate_pct']}% of exposure, "
                  f"{bridge['change_pp']:+} percentage points. By account "
                  f"count the same book moved from "
                  f"{rate['account_weighted_prior_pct']}% to "
                  f"{rate['account_weighted_pct']}%."),
         "evidence": "rate_bridge"},
        {"label": "Why",
         "text": (f"{new['facilities']:,} facilities that were not 30+ last "
                  f"month are now, carrying SAR {new['amount']:,.0f}. That is "
                  f"{arrears['contribution_pp']:+} pp on its own; the book "
                  f"growing took {book['contribution_pp']:+} pp back off."
                  if new and arrears and book else "—"),
         "evidence": "transitions"},
        {"label": "What offset it",
         "text": (f"{abs(cures['facilities']):,} facilities cured out of 30+, "
                  f"removing SAR {abs(cures['amount']):,.0f} from the "
                  f"numerator, and {moves.cured['facilities']:,} facilities "
                  f"improved bucket overall. The aggregate still rose."
                  if cures else "—"),
         "evidence": "transitions"},
        {"label": "Materiality",
         "text": (f"The loss allowance on the same population moved from SAR "
                  f"{ecl['opening_ecl_sar']:,.0f} to SAR "
                  f"{ecl['closing_ecl_sar']:,.0f}"
                  + (f", of which SAR {biggest['amount_sar']:,.0f} is "
                     f"{biggest['driver'].lower()}." if biggest else ".")),
         "evidence": "ecl_bridge"},
    ]
    return out


def run(*, month: str = "", prior: str = "", product: str = "",
        classification: str = "", sub_product: str = "",
        question: str = "") -> dict[str, Any]:
    """The full §6 answer for one scope and one month-on-month step."""
    months = S.book_months()
    if not months:
        return {"available": False, "because": "the book holds no months"}
    at = month or months[-1]
    if at not in months:
        return {"available": False, "because": f"the book has no {at}"}
    before = prior or P.shift(at, -1)
    if before not in months:
        return {"available": False,
                "because": f"the book has no {before} to compare {at} with"}

    closing = _scope(S._read_book(at), product=product,
                     classification=classification, sub_product=sub_product)
    opening = _scope(S._read_book(before), product=product,
                     classification=classification, sub_product=sub_product)
    if not len(closing) or not len(opening):
        return {"available": False,
                "because": ("that scope matches nothing in one of the two "
                            "months, so there is no movement to explain")}

    label = (tax.PRODUCT_LABELS.get(product.upper(), product.title())
             if product else "Retail")
    if sub_product:
        label = f"{label} — {sub_product.replace('_', ' ').title()}"
    elif classification:
        label = f"{label} — {classification.replace('_', ' ').title()}"

    moves = D.transitions(opening, closing, month=at, prior=before,
                          scope={"product": product,
                                 "classification": classification,
                                 "sub_product": sub_product})
    by_exposure = D.rate_bridge(opening, closing, weighting="exposure")
    by_account = D.rate_bridge(opening, closing, weighting="accounts")
    ecl = movement.decompose(opening, closing)

    window = [one for one in months if one <= at][-TREND_MONTHS:]
    series = trend(window, product=product, classification=classification,
                   sub_product=sub_product)

    pockets = []
    for by, name in (("product_code", "Product"),
                     ("classification", "Salaried / Non-Salaried"),
                     ("sub_product_code", "Sub-product")):
        if by in closing.columns:
            got = _pockets(opening, closing, by, name)
            if got.get("available"):
                pockets.append(got)

    rate = {
        "exposure_weighted_pct": by_exposure["closing"]["rate_pct"],
        "exposure_weighted_prior_pct": by_exposure["opening"]["rate_pct"],
        "account_weighted_pct": by_account["closing"]["rate_pct"],
        "account_weighted_prior_pct": by_account["opening"]["rate_pct"],
    }

    return {
        "available": True,
        "analysis_id": ANALYSIS_ID,
        "analysis_version": ANALYSIS_VERSION,
        "question": question,
        "interpretation": (
            f"Why the 30+ DPD rate for {label} moved between {before} and "
            f"{at}. Answered on the facilities themselves — where they moved, "
            f"what entered and left — and then, separately, what that did to "
            f"the loss allowance."),
        "scope": {"label": label, "product": product,
                  "classification": classification,
                  "sub_product": sub_product,
                  "month": at, "prior": before,
                  "facilities": int(len(closing)),
                  "customers": int(closing["customer_id"].nunique()),
                  "exposure_sar": round(float(pd.to_numeric(
                      closing["gross_carrying_amount_sar"],
                      errors="coerce").fillna(0.0).sum()), 2)},
        "metrics_used": [MR.get("ret.dpd30.exposure").to_dict(),
                         MR.get("ret.dpd30.accounts").to_dict()],
        "rate": rate,
        "findings": _findings(rate, moves, by_exposure, ecl, label),
        "trend": series,
        "trend_window": f"{window[0]} to {window[-1]}" if window else "",
        "transitions": moves.to_dict(),
        "rate_bridge": by_exposure,
        "rate_bridge_by_account": by_account,
        "mix_bridges": pockets,
        "ecl_bridge": ecl,
        "top_customers": _top_customers(opening, closing),
        "offsets": {
            "cured_facilities": moves.cured["facilities"],
            "cured_exposure_sar": moves.cured["exposure_sar"],
            "out_of_thirty_plus": moves.out_of_thirty_plus,
            "note": ("Improvements are reported beside the deterioration "
                     "rather than netted into it. A book can worsen in "
                     "aggregate while thousands of accounts cure."),
        },
        "follow_ups": [
            "Which sub-products are driving this?",
            "Which customers explain most of it?",
            "What improved and offset the increase?",
            "Compare account-count and exposure-weighted 30+ DPD.",
            "Show the ECL impact separately from the observed movement.",
            "Which currently clean customers show these leading signals?",
        ],
        "limitations": [
            "Observed state changes, on facilities matched across the two "
            "months. Entrants and exits are reported separately and are not "
            "attributed to any migration.",
            "The ECL bridge is a sequential revaluation in a published order. "
            "It is order-dependent: a different order moves amounts between "
            "drivers while the total is unchanged. It is not a Shapley "
            "decomposition.",
            "Synthetic demonstration data. Not ANB customer history and not "
            "an approved model.",
        ],
    }
