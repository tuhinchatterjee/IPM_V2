"""A small governed measure engine over the retail book.

Why this exists beside the story engines
-----------------------------------------
`analysis_delinquency` and `analysis_traits` answer one big question each and
take thirty seconds to do it. That is right for the question they answer and
wrong for the hundred saved analyses §18 asks for, most of which are the
ordinary shape of bank analysis: one measure, one population, one cut, one
period. "Thirty-plus delinquency by sub-product, Credit Card, August." A
reader wants the table and the number, not a decomposition.

So this is the cheap half: a declared set of measures, a declared set of
cuts, and one pass over one month of the book. Sub-second, because the book
is already cached by `ews_score._read_book`.

What makes it GOVERNED rather than convenient
-----------------------------------------------
Three things, and each closes a way a demo number goes wrong.

**A measure names its own column and its own arithmetic.** There is no
"sum whatever column the caller passed", so a chart cannot end up showing
the mean of a balance and the sum of a rate under the same heading.

**A measure states what it CANNOT be cut by.** Loan-to-value means nothing
on a credit card, and a dashboard that renders it as 0.0% for the card book
has invented a fact. Asking for an inapplicable pair returns a refusal with
the reason, which is the same contract the validation engine holds itself to.

**Every result carries the month, the population and the source stamp it was
measured over.** §24's recurring defect is a derived number that outlived
the data it came from; a measure result that cannot say which snapshot it
read is one nobody can check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

MEASURES_VERSION = "retail-measures-1.0.0"

#: The four products, as the book spells them.
PRODUCTS: tuple[str, ...] = ("CREDIT_CARD", "PERSONAL_LOAN", "AUTO_LOAN",
                             "HOME_LOAN")

PRODUCT_LABEL: dict[str, str] = {
    "CREDIT_CARD": "Credit Card",
    "PERSONAL_LOAN": "Personal Finance",
    "AUTO_LOAN": "Auto Finance",
    "HOME_LOAN": "Home Finance",
}


class MeasureRefused(ValueError):
    """The measure cannot be computed over the population it was asked for."""


@dataclass(frozen=True)
class Measure:
    """One number, and everything needed to defend it."""

    key: str
    label: str
    #: How it reads: "money", "rate", "count", "ratio", "years".
    unit: str
    #: What it means, in the sentence a chart caption would use.
    meaning: str
    #: Computed from a frame. Returns the value, or None where the
    #: population carries nothing to measure — never zero, because zero is a
    #: measurement and "there is nothing here" is not.
    compute: Callable[[pd.DataFrame], float | None]
    #: Products this measure is meaningful for. Empty means all four.
    only_for: tuple[str, ...] = ()
    #: Why it is meaningless elsewhere, said rather than implied.
    why_limited: str = ""

    def applies_to(self, product: str) -> bool:
        return not self.only_for or not product or product in self.only_for


def _sum(column: str) -> Callable[[pd.DataFrame], float | None]:
    def run(frame: pd.DataFrame) -> float | None:
        if column not in frame.columns or not len(frame):
            return None
        got = pd.to_numeric(frame[column], errors="coerce").dropna()
        return float(got.sum()) if len(got) else None
    return run


def _mean(column: str) -> Callable[[pd.DataFrame], float | None]:
    def run(frame: pd.DataFrame) -> float | None:
        if column not in frame.columns or not len(frame):
            return None
        got = pd.to_numeric(frame[column], errors="coerce").dropna()
        return float(got.mean()) if len(got) else None
    return run


def _share(test: Callable[[pd.DataFrame], pd.Series]
           ) -> Callable[[pd.DataFrame], float | None]:
    def run(frame: pd.DataFrame) -> float | None:
        if not len(frame):
            return None
        mask = test(frame)
        return float(mask.mean()) if mask is not None else None
    return run


def _weighted_share(test: Callable[[pd.DataFrame], pd.Series], column: str
                    ) -> Callable[[pd.DataFrame], float | None]:
    """A share of EXPOSURE rather than of accounts.

    The two answer different questions and a screen that shows one labelled
    as the other is the most common way a portfolio number misleads: five per
    cent of accounts can be twenty per cent of the money.
    """
    def run(frame: pd.DataFrame) -> float | None:
        if not len(frame) or column not in frame.columns:
            return None
        weight = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        total = float(weight.sum())
        if total <= 0:
            return None
        return float(weight[test(frame)].sum() / total)
    return run


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame.get(column), errors="coerce")


MEASURES: tuple[Measure, ...] = (
    Measure("facilities", "Facilities", "count",
            "How many facility records the population holds at this month.",
            lambda frame: float(len(frame)) if len(frame) else None),
    Measure("customers", "Distinct customers", "count",
            "How many people hold them. A facility count is not a customer "
            "count, and the two diverge most in the card book.",
            lambda frame: (float(frame["customer_id"].nunique())
                           if "customer_id" in frame.columns and len(frame)
                           else None)),
    Measure("exposure", "Gross carrying amount", "money",
            "The book's balance sheet exposure, before impairment.",
            _sum("gross_carrying_amount_sar")),
    Measure("ecl", "Expected credit loss", "money",
            "Probability-weighted expected credit loss under the approved "
            "scenario weights.",
            _sum("ecl_weighted_sar")),
    Measure("coverage", "ECL coverage", "rate",
            "Expected credit loss over gross carrying amount. The ratio a "
            "committee reads first, and the one a change in mix moves "
            "without anything getting worse.",
            lambda frame: _coverage(frame)),
    Measure("stage2_share", "Stage 2 share of accounts", "rate",
            "The share of facilities in IFRS 9 stage 2 — a significant "
            "increase in credit risk since origination.",
            _share(lambda f: _numeric(f, "ifrs9_stage").fillna(1) == 2)),
    Measure("stage2_exposure_share", "Stage 2 share of exposure", "rate",
            "The same population measured by money rather than by count.",
            _weighted_share(
                lambda f: _numeric(f, "ifrs9_stage").fillna(1) == 2,
                "gross_carrying_amount_sar")),
    Measure("stage3_share", "Stage 3 share of accounts", "rate",
            "Credit-impaired facilities as a share of the population.",
            _share(lambda f: _numeric(f, "ifrs9_stage").fillna(1) == 3)),
    Measure("dpd30_share", "30+ DPD share of accounts", "rate",
            "Facilities thirty or more days past due. The lagging measure "
            "the attention case is raised on.",
            _share(lambda f: _numeric(f, "dpd").fillna(0) >= 30)),
    Measure("dpd30_exposure_share", "30+ DPD share of exposure", "rate",
            "The same delinquency weighted by balance. Where this exceeds "
            "the account share, the larger accounts are the ones in arrears.",
            _weighted_share(lambda f: _numeric(f, "dpd").fillna(0) >= 30,
                            "gross_carrying_amount_sar")),
    Measure("dpd90_share", "90+ DPD share of accounts", "rate",
            "Facilities ninety or more days past due.",
            _share(lambda f: _numeric(f, "dpd").fillna(0) >= 90)),
    Measure("dpd1_29_share", "1-29 DPD share of accounts", "rate",
            "Early arrears — the bucket a deterioration passes through "
            "before it reaches thirty.",
            _share(lambda f: (_numeric(f, "dpd").fillna(0) >= 1)
                   & (_numeric(f, "dpd").fillna(0) <= 29))),
    Measure("mean_dpd", "Mean days past due", "count",
            "Averaged over every facility including the current ones, so it "
            "moves with the share in arrears as well as with their depth.",
            _mean("dpd")),
    Measure("salary_transfer_share", "Salary-transferred share", "rate",
            "Customers whose salary is paid into the bank. The single "
            "strongest affordability control in this book.",
            _share(lambda f: f.get("salary_transfer_flag",
                                   pd.Series(dtype=bool)).fillna(False)
                   .astype(bool))),
    Measure("mean_income", "Mean verified monthly income", "money",
            "Verified total monthly income, averaged over the population.",
            _mean("verified_total_monthly_income_sar")),
    Measure("mean_disposable", "Mean disposable income", "money",
            "What remains after recorded obligations.",
            _mean("disposable_income_sar")),
    Measure("mean_dbr", "Mean debt-burden ratio", "ratio",
            "Recorded obligations over verified income, as the application "
            "scorecard reads it.",
            _mean("app_dbr_raw")),
    Measure("mean_utilisation", "Mean utilisation", "rate",
            "Drawn balance over the credit limit.",
            _mean("utilisation_ratio"),
            only_for=("CREDIT_CARD",),
            why_limited="Utilisation needs a revolving limit. A term loan "
                        "has an amortising balance and no limit to be a "
                        "share of, so the ratio would be a different "
                        "quantity under the same name."),
    Measure("overlimit_share", "Over-limit share", "rate",
            "Cards drawn beyond their approved limit.",
            _share(lambda f: _numeric(f, "utilisation_ratio").fillna(0) > 1.0),
            only_for=("CREDIT_CARD",),
            why_limited="The same reason utilisation is card-only."),
    Measure("mean_ltv", "Mean current loan-to-value", "rate",
            "Outstanding balance over current collateral value.",
            _mean("ltv_current_ratio"),
            only_for=("HOME_LOAN", "AUTO_LOAN"),
            why_limited="Loan-to-value needs collateral. On an unsecured "
                        "card or personal loan there is no value to be a "
                        "share of, and rendering it as zero would state "
                        "that the collateral is worthless rather than "
                        "absent."),
    Measure("high_ltv_share", "Share above 80% LTV", "rate",
            "Secured facilities with thin equity cover.",
            _share(lambda f: _numeric(f, "ltv_current_ratio").fillna(0) > 0.8),
            only_for=("HOME_LOAN", "AUTO_LOAN"),
            why_limited="As for mean LTV."),
    Measure("balloon_exposure", "Balloon payments due", "money",
            "Contractual balloon amounts outstanding on the population.",
            _sum("balloon_payment_sar"),
            only_for=("AUTO_LOAN",),
            why_limited="Only the auto book is written with balloon "
                        "structures in this installation."),
    Measure("balloon_within_year_share", "Balloon due within a year", "rate",
            "Facilities whose balloon falls due inside twelve months — the "
            "population a refinancing failure would surface in first.",
            _share(lambda f: (_numeric(f, "months_to_balloon").fillna(999)
                              <= 12)),
            only_for=("AUTO_LOAN",),
            why_limited="As for balloon exposure."),
    Measure("collateral_cover", "Collateral cover", "ratio",
            "Current collateral value over gross carrying amount.",
            lambda frame: _cover(frame),
            only_for=("HOME_LOAN", "AUTO_LOAN"),
            why_limited="Unsecured products have no collateral to cover "
                        "the exposure."),
    Measure("mean_behaviour_score", "Mean behavioural score", "count",
            "The behavioural scorecard's output, averaged. Higher is safer.",
            _mean("beh_score_value")),
    Measure("mean_pd", "Mean predicted 12-month PD", "rate",
            "The behavioural scorecard's probability of default over the "
            "next twelve months.",
            _mean("beh_predicted_pd_12m")),
    Measure("mean_lgd", "Mean loss given default", "rate",
            "The base-scenario loss severity applied in the ECL.",
            _mean("lgd_base")),
)

BY_KEY: dict[str, Measure] = {one.key: one for one in MEASURES}


def _coverage(frame: pd.DataFrame) -> float | None:
    if not len(frame):
        return None
    exposure = _numeric(frame, "gross_carrying_amount_sar").fillna(0.0).sum()
    ecl = _numeric(frame, "ecl_weighted_sar").fillna(0.0).sum()
    return float(ecl / exposure) if exposure else None


def _cover(frame: pd.DataFrame) -> float | None:
    if not len(frame):
        return None
    value = _numeric(frame, "collateral_value_current_sar").fillna(0.0).sum()
    exposure = _numeric(frame, "gross_carrying_amount_sar").fillna(0.0).sum()
    return float(value / exposure) if exposure else None


# ------------------------------------------------------------------- cuts


@dataclass(frozen=True)
class Cut:
    """A dimension a measure can be broken down by."""

    key: str
    label: str
    column: str
    #: Products the cut is meaningful for. Empty means all four.
    only_for: tuple[str, ...] = ()
    #: How to order the levels where the natural order is not alphabetical.
    order: tuple[str, ...] = ()
    #: Which governed view the column lives in. "" is the canonical book.
    #:
    #: Sub-product and classification are DERIVED dimensions: the taxonomy
    #: that produces them is versioned and lives with the Early Warning
    #: score view, not in the facility-month book. Cutting by them means
    #: joining that view on facility_id — which is a join onto a governed
    #: derived dataset, not a dimension this module invents. The alternative
    #: was to drop the cut, and §22's demonstration drills product to
    #: classification to sub-product to customer, so dropping it would have
    #: removed a required capability rather than served it.
    source: str = ""


CUTS: tuple[Cut, ...] = (
    Cut("product", "Product", "product_code",
        order=PRODUCTS),
    Cut("salary_transfer", "Salary transfer", "salary_transfer_flag"),
    Cut("segment", "Customer segment", "customer_segment"),
    Cut("stage", "IFRS 9 stage", "ifrs9_stage", order=("1", "2", "3")),
    Cut("dpd_bucket", "Delinquency bucket", "dpd_bucket",
        order=("0", "1-29", "30-59", "60-89", "90+")),
    Cut("income_band", "Income band", "income_band"),
    Cut("indebtedness_band", "Indebtedness band", "indebtedness_band"),
    Cut("region", "Region", "region"),
    Cut("employment", "Employment status", "employment_status"),
    Cut("channel", "Origination channel", "origination_channel"),
    Cut("vintage", "Origination vintage", "origination_vintage"),
    Cut("utilisation_band", "Utilisation band", "utilisation_band",
        only_for=("CREDIT_CARD",)),
    Cut("ltv_band", "Loan-to-value band", "ltv_band",
        only_for=("HOME_LOAN", "AUTO_LOAN")),
    Cut("balloon_band", "Balloon band", "balloon_band",
        only_for=("AUTO_LOAN",)),
    Cut("collateral_type", "Collateral type", "collateral_type",
        only_for=("HOME_LOAN", "AUTO_LOAN")),
    Cut("application_band", "Application score band", "application_score_band"),
    Cut("sub_product", "Sub-product", "sub_product", source="ews"),
    Cut("classification", "Classification", "classification", source="ews"),
)

CUT_BY_KEY: dict[str, Cut] = {one.key: one for one in CUTS}


# --------------------------------------------------------------- the pass


def book(month: str) -> pd.DataFrame:
    """One month of the canonical book, from the reader that caches it."""
    from backend.retail import ews_score

    return ews_score._read_book(month)


def months() -> list[str]:
    from backend.retail import ews_score

    return list(ews_score.book_months())


#: The derived columns this module will join, and where they come from.
#: Named explicitly rather than joining whatever the view happens to hold:
#: a wildcard join would quietly shadow a book column with a derived one of
#: the same name, and the two are not the same quantity.
DERIVED: dict[str, tuple[str, ...]] = {
    "ews": ("sub_product", "sub_product_label", "classification",
            "classification_label"),
}


def _with_derived(frame: pd.DataFrame, month: str,
                  columns: tuple[str, ...]) -> pd.DataFrame:
    """Join the derived dimensions the cut needs, on facility_id."""
    from backend.retail import ews_score

    wanted = [one for one in columns if one not in frame.columns]
    if not wanted:
        return frame
    view = ews_score.read(month)
    keep = [one for one in wanted if one in view.columns]
    if not keep or "facility_id" not in view.columns \
            or "facility_id" not in frame.columns:
        raise MeasureRefused(
            f"{', '.join(wanted)} is not available for {month}. It is a "
            "derived dimension and its view has not been built for this "
            "month.")
    return frame.merge(view[["facility_id", *keep]], on="facility_id",
                       how="left")


def population(month: str, *, product: str = "",
               where: dict[str, Any] | None = None,
               derived: tuple[str, ...] = ()) -> pd.DataFrame:
    frame = book(month)
    if derived:
        frame = _with_derived(frame, month, derived)
    if product:
        frame = frame[frame["product_code"].astype(str) == product]
    for column, value in (where or {}).items():
        if column not in frame.columns:
            raise MeasureRefused(
                f"{column} is not a column of the retail book, so the "
                "population cannot be restricted by it.")
        if isinstance(value, (list, tuple, set)):
            frame = frame[frame[column].astype(str).isin(
                {str(one) for one in value})]
        else:
            frame = frame[frame[column].astype(str) == str(value)]
    return frame


def stamp(month: str) -> dict[str, Any]:
    """Which snapshot this was measured over. §24's whole point.

    The book hash rather than a build timestamp. §24's recurring defect was
    a 59,449-facility book and a 19,745-facility derived domain both
    labelled version 3.0.0 — a version string proved nothing, and the hash
    of what was actually read is the thing that does.
    """
    from backend.retail import source_stamp

    try:
        book_hash = source_stamp.book_hash()
    except Exception:  # noqa: BLE001 - an unstamped lake is a real state
        book_hash = ""
    return {
        "month": month,
        "measures_version": MEASURES_VERSION,
        "dataset": "retail_facility_month",
        "source_hash": book_hash,
    }


def value(month: str, measure: str, *, product: str = "",
          where: dict[str, Any] | None = None) -> dict[str, Any]:
    """One measure over one population at one month."""
    one = BY_KEY.get(measure)
    if one is None:
        raise MeasureRefused(
            f"{measure!r} is not a governed measure. They are: "
            + ", ".join(sorted(BY_KEY)))
    if not one.applies_to(product):
        raise MeasureRefused(
            f"{one.label} is not meaningful for "
            f"{PRODUCT_LABEL.get(product, product)}. {one.why_limited}")
    frame = population(month, product=product, where=where)
    got = one.compute(frame)
    return {
        "measure": one.key, "label": one.label, "unit": one.unit,
        "meaning": one.meaning,
        "value": None if got is None else round(float(got), 8),
        "facilities": int(len(frame)),
        "product": product, "where": dict(where or {}),
        **stamp(month),
    }


def table(month: str, measures: list[str], cut: str, *, product: str = "",
          where: dict[str, Any] | None = None, top: int = 0
          ) -> dict[str, Any]:
    """Several measures broken down by one dimension.

    The shape a saved analysis keeps: a table a reader can read, the levels
    in their natural order where one exists, and the population each row was
    measured over so a thin level cannot be mistaken for a small number.
    """
    dimension = CUT_BY_KEY.get(cut)
    if dimension is None:
        raise MeasureRefused(
            f"{cut!r} is not a governed cut. They are: "
            + ", ".join(sorted(CUT_BY_KEY)))
    if dimension.only_for and product and product not in dimension.only_for:
        raise MeasureRefused(
            f"{dimension.label} is not a dimension of the "
            f"{PRODUCT_LABEL.get(product, product)} book.")
    wanted = []
    refused = []
    for key in measures:
        one = BY_KEY.get(key)
        if one is None:
            raise MeasureRefused(f"{key!r} is not a governed measure.")
        if one.applies_to(product):
            wanted.append(one)
        else:
            refused.append({"measure": one.key, "label": one.label,
                            "why": one.why_limited})

    frame = population(month, product=product, where=where,
                       derived=DERIVED.get(dimension.source, ()))
    if dimension.column not in frame.columns:
        raise MeasureRefused(
            f"{dimension.column} is not a column of the retail book, and is "
            "not published by a derived view this module can read.")

    rows: list[dict[str, Any]] = []
    levels = frame[dimension.column].astype(str)
    for level, part in frame.groupby(levels, observed=True):
        row: dict[str, Any] = {dimension.key: str(level),
                               "facilities": int(len(part))}
        for one in wanted:
            got = one.compute(part)
            row[one.key] = None if got is None else round(float(got), 8)
        rows.append(row)

    if dimension.order:
        rank = {name: at for at, name in enumerate(dimension.order)}
        rows.sort(key=lambda r: (rank.get(r[dimension.key], 999),
                                 r[dimension.key]))
    else:
        rows.sort(key=lambda r: -r["facilities"])
    if top:
        rows = rows[:top]

    return {
        "cut": dimension.key, "cut_label": dimension.label,
        "measures": [{"measure": one.key, "label": one.label,
                      "unit": one.unit, "meaning": one.meaning}
                     for one in wanted],
        # Named rather than dropped. A measure silently missing from a table
        # is a measure a reader assumes was zero.
        "not_applicable": refused,
        "rows": rows,
        "facilities": int(len(frame)),
        "product": product, "where": dict(where or {}),
        **stamp(month),
    }


def trend(measures: list[str], *, product: str = "",
          where: dict[str, Any] | None = None,
          over: list[str] | None = None) -> dict[str, Any]:
    """The same measures month by month.

    The months are read from the lake rather than generated from a calendar:
    a trend that plots a month the book does not hold draws a gap as a zero.
    """
    every = over or months()
    wanted = [BY_KEY[key] for key in measures if key in BY_KEY
              and BY_KEY[key].applies_to(product)]
    rows: list[dict[str, Any]] = []
    for month in every:
        frame = population(month, product=product, where=where)
        row: dict[str, Any] = {"month": month, "facilities": int(len(frame))}
        for one in wanted:
            got = one.compute(frame)
            row[one.key] = None if got is None else round(float(got), 8)
        rows.append(row)
    return {
        "measures": [{"measure": one.key, "label": one.label,
                      "unit": one.unit, "meaning": one.meaning}
                     for one in wanted],
        "rows": rows, "product": product, "where": dict(where or {}),
        **stamp(every[-1] if every else ""),
    }


def catalogue() -> dict[str, Any]:
    """What a lens editor and a natural-language request can choose from."""
    return {
        "measures_version": MEASURES_VERSION,
        "measures": [{
            "measure": one.key, "label": one.label, "unit": one.unit,
            "meaning": one.meaning,
            "only_for": list(one.only_for),
            "why_limited": one.why_limited,
        } for one in MEASURES],
        "cuts": [{"cut": one.key, "label": one.label,
                  "only_for": list(one.only_for)} for one in CUTS],
        "products": [{"product": one, "label": PRODUCT_LABEL[one]}
                     for one in PRODUCTS],
    }


__all__ = [
    "BY_KEY", "CUTS", "CUT_BY_KEY", "MEASURES", "MEASURES_VERSION",
    "MeasureRefused", "PRODUCTS", "PRODUCT_LABEL", "book", "catalogue",
    "months", "population", "stamp", "table", "trend", "value",
]
