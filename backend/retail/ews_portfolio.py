"""Early warning as a portfolio, not as a list of alerts.

What was wrong
--------------
The Early Warning screens answered one question — *which alerts fired?* — and
answered it as a flat list of five hundred cards. A Head of Retail Risk opens
Early Warning to ask a different question: *where is the book going wrong, how
badly, and who is it?* That question has a shape, and the shape is a hierarchy:

    PORTFOLIO -> PRODUCT -> SUBSEGMENT -> CUSTOMER -> FACILITY / SIGNAL

Nothing here replaces the rulebook. The eleven governed rule families in
`backend.retail.ews` remain exactly as they are and remain the detailed signal
layer underneath; this rolls them up into the six layers of
`backend.retail.ews_layers` and scores each level from the signals that
actually fired.

The grain, and why
------------------
One row per **month, customer and product**. A customer who holds a card and a
mortgage appears under both, because the product view exists to answer "what
is happening to the card book" and a customer counted once in the wrong place
would make every product total wrong. Portfolio counts de-duplicate the
customer; product counts do not need to.

How a score is built
--------------------
Every figure below is computed from governed rule hits and stated arithmetic.
Nothing is judged.

* A **layer score** for one customer-product is the worst signal that fired in
  that layer — CRITICAL 100, HIGH 60, MEDIUM 30, LOW 10 — plus ten points for
  each ADDITIONAL signal that fired with it, capped at 100.
* The **overall EWS score** is the weighted mean of the five scored layer
  scores, using the weights declared on each layer, which sum to one.
* **Severity** is a band on the overall score.
* **Current bad** is 30+ days past due, or flagged in default, or Stage 3 —
  already in trouble, not a prediction.
* **Forward risk** is NOT current bad AND overall severity HIGH or CRITICAL —
  a prediction about a customer who is still paying.

A product's score is the **exposure-weighted** mean of its customers' scores,
recomputed at that level rather than averaged from subsegment averages.

Everything here is synthetic demonstration material. No threshold is a bank
policy and nothing in it has been approved by anybody.
"""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.retail import ews as rules_mod
from backend.retail import ews_layers as L

logger = logging.getLogger(__name__)

PANEL = "retail_ews_panel"
BOOK = "retail_facility_month"

#: Bumped when the panel's columns or arithmetic change.
EWS_PANEL_VERSION = "1.0.0"

#: The layers that carry a score, in display order.
SCORED = tuple(layer.key for layer in L.scored())

#: What makes a customer CURRENT BAD. Stated here once and shown on screen.
CURRENT_BAD_RULE = (
    "30 or more days past due on any facility, or flagged in default, or in "
    "IFRS 9 Stage 3 at this month-end.")
FORWARD_RISK_RULE = (
    "Not currently bad, and an overall EWS score in the HIGH or CRITICAL "
    "band. A prediction about a customer who is still paying.")

#: The subsegment dimensions each product is broken down by, in display order.
#:
#: Every one is a real, populated column of the canonical book. A dimension a
#: product does not carry is absent rather than shown empty: credit cards have
#: no LTV band and home finance has no card behaviour segment.
SUBSEGMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "CREDIT_CARD": (
        ("card_behaviour_segment", "Card behaviour"),
        ("utilisation_band", "Utilisation band"),
        ("behavioural_score_band", "Behavioural score band"),
        ("salary_transfer_flag", "Salary transfer"),
        ("new_to_bank_at_origination_flag", "New to bank at origination"),
        ("origination_channel", "Origination channel"),
    ),
    "PERSONAL_LOAN": (
        ("salary_transfer_flag", "Salary transfer"),
        ("indebtedness_band", "Affordability band"),
        ("behavioural_score_band", "Behavioural score band"),
        ("new_to_bank_at_origination_flag", "New to bank at origination"),
        ("origination_channel", "Origination channel"),
    ),
    "AUTO_LOAN": (
        ("ltv_band", "LTV band"),
        ("balloon_band", "Balloon profile"),
        ("indebtedness_band", "Affordability band"),
        ("behavioural_score_band", "Behavioural score band"),
        ("salary_transfer_flag", "Salary transfer"),
    ),
    "HOME_LOAN": (
        ("ltv_band", "LTV band"),
        ("salary_transfer_flag", "Salary transfer"),
        ("indebtedness_band", "Affordability band"),
        ("behavioural_score_band", "Behavioural score band"),
    ),
}

#: Columns carried through to the panel so a customer list and a subsegment
#: view can be served without re-reading the book.
CARRIED: tuple[str, ...] = (
    "dpd", "ifrs9_stage", "current_default_flag", "credit_impaired_flag",
    "behavioural_score", "behavioural_score_previous_month",
    "behavioural_score_change_3m", "behavioural_score_band",
    "application_score_at_origination", "application_score_band",
    "gross_carrying_amount_sar", "utilisation_band", "card_behaviour_segment",
    "salary_transfer_flag", "new_to_bank_at_origination_flag",
    "origination_channel", "indebtedness_band", "ltv_band", "balloon_band",
    "customer_segment", "region_label",
)


# ------------------------------------------------------------------ scoring

def _possible_points() -> dict[str, dict[str, float]]:
    """Per product, the severity points every layer COULD score.

    Not the scale a layer is scored on — see `_one_month` for that — but the
    ceiling a methodology page shows so a reader can see how much of each
    layer a product is even exposed to. A home loan has no card behaviour
    rules, and its facility-structure layer is a shorter list as a result.
    """
    out: dict[str, dict[str, float]] = {}
    for rule in rules_mod.RULES:
        layer = L.layer_of(rule.family)
        if not layer:
            continue
        points = L.SEVERITY_POINTS.get(str(rule.severity).upper(), 0.0)
        for product in rule.products:
            out.setdefault(product, {}).setdefault(layer, 0.0)
            out[product][layer] += points
    return out


def _months(analytics_dir: str | Path | None = None) -> list[str]:
    from backend.config import settings

    root = Path(analytics_dir or settings.analytics_dir) / BOOK
    if not root.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in root.iterdir()
                  if p.is_dir() and "=" in p.name)


def _read(month: str, analytics_dir: str | Path | None = None) -> Any:
    import pandas as pd

    from backend.config import settings

    root = Path(analytics_dir or settings.analytics_dir)
    paths = sorted(glob.glob(
        str(root / BOOK / f"reporting_month={month}" / "*.parquet")))
    if not paths:
        raise FileNotFoundError(f"{BOOK} has no {month}")
    return pd.read_parquet(paths[0])


def _one_month(month: str, frame: Any, previous: Any) -> Any:
    """The customer-product panel for one month."""
    import numpy as np
    import pandas as pd

    alerts = rules_mod.evaluate_snapshot(
        rules_mod.with_prior_month(frame, previous))

    # The customer-product spine: every customer-product in the book, whether
    # or not anything fired. A portfolio view has to be able to say how many
    # customers are NOT warned, which a table of alerts cannot.
    held = [c for c in CARRIED if c in frame.columns]
    spine = frame.groupby(["customer_id", "product_code"], as_index=False).agg(
        product_label=("product_label", "first"),
        exposure_sar=("gross_carrying_amount_sar", "sum"),
        facilities=("facility_id", "nunique"),
        dpd=("dpd", "max"),
        ifrs9_stage=("ifrs9_stage", "max"),
        in_default=("current_default_flag", "max"),
        impaired=("credit_impaired_flag", "max"),
        behavioural_score=("behavioural_score", "mean"),
        behavioural_score_previous=("behavioural_score_previous_month", "mean"),
        application_score=("application_score_at_origination", "mean"),
    )
    # The descriptive bands a subsegment view cuts on: taken from the
    # customer's LARGEST facility in the product, so a customer with two cards
    # lands in one utilisation band rather than in an average of two.
    biggest = (frame.sort_values("gross_carrying_amount_sar", ascending=False)
               .groupby(["customer_id", "product_code"], as_index=False).first())
    bands = [c for c in held if c not in
             ("dpd", "ifrs9_stage", "current_default_flag",
              "credit_impaired_flag", "behavioural_score",
              "behavioural_score_previous_month",
              "application_score_at_origination", "gross_carrying_amount_sar")]
    spine = spine.merge(
        biggest[["customer_id", "product_code", *bands]],
        on=["customer_id", "product_code"], how="left")

    possible = _possible_points()

    # Points fired, per customer-product-layer.
    if len(alerts):
        fired = alerts.copy()
        fired["layer"] = fired["rule_family"].map(L.layer_of)
        fired = fired[fired["layer"].astype(bool)]
        fired["points"] = (fired["severity"].str.upper()
                           .map(L.SEVERITY_POINTS).fillna(0.0))
        # A CUSTOMER-scope alert carries no product code, because it is about
        # the customer rather than about one facility — salary interruption,
        # affordability, bureau. Joined on the product it would be dropped,
        # and 1,934 of the 5,952 alerts on this book are customer-scope: the
        # whole affordability and bureau story would have vanished from the
        # portfolio view while still showing on the alert list. Each one
        # therefore bears on every product that customer holds, which is what
        # a signal about the customer means.
        whole = fired[fired["product_code"].isna()
                      | (fired["product_code"] == "")]
        # Counted BEFORE the fan-out, and kept apart, because the two kinds
        # add up differently. A facility-scope alert belongs to exactly one
        # (customer, product) and may be summed across rows. A customer-scope
        # one belongs to the customer and is carried on every product row they
        # have, so summing it across rows counts it several times — which is
        # how a product ended up reporting the whole month's 5,952 alerts.
        # Any population's true count is therefore its facility alerts summed
        # plus its DISTINCT customers' customer alerts; see `_alert_count`.
        per_facility = fired[fired["product_code"].notna()
                             & (fired["product_code"] != "")]
        facility_counts = (per_facility
                           .groupby(["customer_id", "product_code"])["alert_id"]
                           .nunique().rename("alerts_facility").reset_index())
        customer_counts = (whole.groupby("customer_id")["alert_id"].nunique()
                           .rename("alerts_customer").reset_index())
        if len(whole):
            held = spine[["customer_id", "product_code"]].drop_duplicates()
            spread = (whole.drop(columns=["product_code"])
                      .merge(held, on="customer_id", how="inner"))
            fired = pd.concat(
                [fired[fired["product_code"].notna()
                       & (fired["product_code"] != "")], spread],
                ignore_index=True)
        by_layer = (fired.groupby(["customer_id", "product_code", "layer"])
                    .agg(worst=("points", "max"),
                         hits=("rule_id", "nunique")).reset_index())
        # The worst signal that fired in the layer, plus ten points for each
        # ADDITIONAL signal, capped at 100.
        #
        # The first draft scored a layer as fired points over every point the
        # layer COULD score, which is arithmetically clean and useless: a
        # customer would have to fire every rule in the book to reach
        # CRITICAL, so 17,227 of 17,818 customer-products came out LOW and
        # exactly one was forward risk. A risk analyst reads a layer the way
        # this now scores it — the worst thing that fired, made worse by how
        # many other things fired with it.
        by_layer["value"] = np.minimum(
            by_layer["worst"] + 10.0 * (by_layer["hits"] - 1), 100.0)
        wide = by_layer.pivot_table(
            index=["customer_id", "product_code"], columns="layer",
            values="value", fill_value=0.0).reset_index()
        spine = spine.merge(wide, on=["customer_id", "product_code"],
                            how="left")
        # The rules behind each customer-product, worst first, for the top
        # reason codes and for the primary deteriorating layer.
        order = {name: i for i, name
                 in enumerate(reversed(rules_mod.SEVERITY_ORDER))}
        fired["rank"] = fired["severity"].str.upper().map(order).fillna(99)
        ranked = fired.sort_values(["customer_id", "product_code", "rank",
                                    "rule_id"])
        # One entry per RULE, not per alert. A customer with two cards, both
        # of which worsened a delinquency bucket, fires RET-EWS-001 twice, and
        # the "top three reason codes" came back as RET-EWS-001, RET-EWS-001,
        # RET-EWS-002 — two of the three slots spent saying the same thing,
        # and two React children with the same key on 56 rows of this month.
        # The alert COUNT is taken separately and still counts both.
        distinct = ranked.drop_duplicates(
            subset=["customer_id", "product_code", "rule_id"])
        reasons = (distinct.groupby(["customer_id", "product_code"])
                   .agg(top_rules=("rule_id", lambda s: "|".join(list(s)[:3])),
                        top_rule_names=("rule_name",
                                        lambda s: "|".join(list(s)[:3])),
                        ).reset_index())
        counted = (ranked.groupby(["customer_id", "product_code"])["alert_id"]
                   .nunique().rename("alerts").reset_index())
        reasons = reasons.merge(counted, on=["customer_id", "product_code"],
                                how="left")
        spine = spine.merge(reasons, on=["customer_id", "product_code"],
                            how="left")
        spine = spine.merge(facility_counts, on=["customer_id", "product_code"],
                            how="left")
        spine = spine.merge(customer_counts, on="customer_id", how="left")
    else:
        spine["top_rules"] = ""
        spine["top_rule_names"] = ""
        spine["alerts"] = 0
        spine["alerts_facility"] = 0
        spine["alerts_customer"] = 0

    for key in SCORED:
        if key not in spine.columns:
            spine[key] = 0.0
        spine[key] = spine[key].fillna(0.0)

    for key in SCORED:
        spine[f"layer_{key}"] = spine[key].fillna(0.0).round(4)
        spine = spine.drop(columns=[key])

    weights = {layer.key: layer.weight for layer in L.scored()}
    spine["ews_score"] = sum(
        spine[f"layer_{k}"] * w for k, w in weights.items()).round(4)
    spine["severity"] = spine["ews_score"].map(L.band_of)

    spine["current_bad"] = (
        (spine["dpd"].fillna(0) >= 30)
        | spine["in_default"].fillna(False).astype(bool)
        | (spine["ifrs9_stage"].fillna(0) >= 3))
    spine["forward_risk"] = (~spine["current_bad"]) & spine["severity"].isin(
        ("HIGH", "CRITICAL"))
    spine["warned"] = spine["alerts"].fillna(0) > 0

    # The layer that is worst for this customer, named so a list can say why.
    layer_cols = [f"layer_{k}" for k in SCORED]
    top = spine[layer_cols].to_numpy()
    best = top.argmax(axis=1)
    spine["primary_layer"] = [
        SCORED[i] if top[r, i] > 0 else "" for r, i in enumerate(best)]

    spine["behavioural_score_change"] = (
        spine["behavioural_score"] - spine["behavioural_score_previous"]
    ).round(2)
    spine["reporting_month"] = month
    # The month's TRUE alert count, before a customer-scope alert is spread
    # across the products it bears on. Summing the per-row counts instead
    # reported 6,579 where the rulebook raised 5,952, because a signal about
    # the customer is one alert however many of their products it touches.
    spine["month_alert_total"] = int(len(alerts))
    spine["alerts"] = spine["alerts"].fillna(0).astype(int)
    for column in ("alerts_facility", "alerts_customer"):
        if column not in spine.columns:
            spine[column] = 0
        spine[column] = spine[column].fillna(0).astype(int)
    spine["top_rules"] = spine["top_rules"].fillna("")
    spine["top_rule_names"] = spine["top_rule_names"].fillna("")
    return spine


# ------------------------------------------------------------------ building

@dataclass
class Built:
    months: int = 0
    rows: int = 0
    skipped: int = 0
    notes: list[str] | None = None

    def summary(self) -> str:
        return (f"{self.months} month(s), {self.rows:,} customer-product rows"
                + (f", {self.skipped} already present" if self.skipped else ""))


def build(*, analytics_dir: str | Path | None = None,
          replace: bool = False, months: list[str] | None = None) -> Built:
    """Score every month and persist the panel.

    Run once at bootstrap. Evaluating the rulebook over twenty-five months
    takes about a minute, which is fine once and far too slow inside a page
    load — and the presenter must never have to click "fit" to see a screen.
    """
    from backend.config import settings
    from backend.retail import guard

    root = Path(analytics_dir or settings.analytics_dir)
    guard.require_retail_directory(root, what="the early-warning panel")

    every = months or _months(root)
    out = Built(notes=[])
    if not every:
        out.notes.append("the retail book holds no months")
        return out

    target = root / PANEL
    previous_frame = None
    previous_month = ""
    for month in every:
        destination = target / f"reporting_month={month}"
        marker = destination / "part-0.parquet"
        frame = _read(month, root)
        if marker.exists() and not replace:
            out.skipped += 1
            previous_frame, previous_month = frame, month
            continue
        prior = previous_frame if previous_month and previous_frame is not None \
            else None
        panel = _one_month(month, frame, prior)
        destination.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(marker, index=False)
        out.months += 1
        out.rows += int(len(panel))
        previous_frame, previous_month = frame, month
    return out


def _panel_months(analytics_dir: str | Path | None = None) -> list[str]:
    from backend.config import settings

    root = Path(analytics_dir or settings.analytics_dir) / PANEL
    if not root.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in root.iterdir()
                  if p.is_dir() and "=" in p.name)


def _panel(month: str, analytics_dir: str | Path | None = None) -> Any:
    import pandas as pd

    from backend.config import settings

    root = Path(analytics_dir or settings.analytics_dir)
    paths = sorted(glob.glob(
        str(root / PANEL / f"reporting_month={month}" / "*.parquet")))
    if not paths:
        raise FileNotFoundError(
            f"The early-warning panel has no {month}. Run "
            "`scripts/bootstrap_retail_installation.py` to build it.")
    return pd.read_parquet(paths[0])


def available() -> bool:
    return bool(_panel_months())


# ------------------------------------------------------------------ serving

def _severity_counts(frame: Any) -> dict[str, int]:
    """Distinct CUSTOMERS in each band — never alerts, never rows.

    Banded ONCE each, on their worst product. Grouping the rows by severity
    and counting distinct customers inside each group counts a customer who is
    HIGH on a card and LOW on a mortgage twice, which is how the four band
    counts came to add up to 4,018 under a headline that said 3,896 customers
    carry a signal. A customer is as risky as their worst position — the same
    rule `_one_customer_score` applies on their own page.
    """
    out = {band: 0 for _, band in L.BANDS}
    if not len(frame):
        return out
    worst = frame.groupby("customer_id")["ews_score"].max()
    for band, count in worst.map(L.band_of).value_counts().items():
        out[str(band)] = int(count)
    return out


def _money(value: Any) -> float:
    return round(float(value or 0.0), 2)


def _one_customer_score(rows: Any) -> float:
    """ONE customer's EWS score: the worst of the products they hold.

    Not the exposure-weighted mean `_weighted` computes for a population.
    Averaging is right across many customers and wrong across one person's
    products: RC-0000134 scored 52.5 on their card and 19.4 on this page,
    because a large clean mortgage diluted a card that is eighty-six days
    down. A customer is as risky as their worst position, and the list and
    the detail must agree about how risky that is.
    """
    if not len(rows):
        return 0.0
    return round(float(rows["ews_score"].fillna(0.0).max()), 2)


def _one_customer_layers(rows: Any) -> dict[str, float]:
    """One customer's layer scores: the worst of their products, per layer."""
    if not len(rows):
        return {key: 0.0 for key in SCORED}
    return {key: round(float(rows[f"layer_{key}"].fillna(0.0).max()), 2)
            for key in SCORED}


def _weighted(frame: Any) -> float:
    """A population's EWS score: exposure-weighted over its WARNED customers.

    Over the warned ones, deliberately. Averaged across every customer in the
    book the number is arithmetically fine and useless on a screen: 14,251
    customers of whom 3,896 carry a signal drag every product to 2-5 out of
    100, so all four read LOW for ever and the severity band says nothing. Over
    the customers who actually carry a signal it answers the question a Head of
    Retail Risk is asking — how bad are the ones we have flagged — on the same
    0-100 scale, and against the same bands, as a single customer's score. How
    MANY are flagged is a separate figure, reported beside it as the warned
    customer count and the share of exposure under warning.

    Recomputed from the rows rather than averaged from a level above or below,
    so a product score and the sum of its subsegments cannot disagree.
    """
    if not len(frame):
        return 0.0
    if "warned" in frame.columns:
        frame = frame[frame["warned"]]
        if not len(frame):
            return 0.0
    weight = frame["exposure_sar"].fillna(0.0)
    total = float(weight.sum())
    if total <= 0:
        return round(float(frame["ews_score"].mean()), 2)
    return round(float((frame["ews_score"] * weight).sum() / total), 2)


def _alert_count(frame: Any) -> int:
    """The alerts behind one population, each counted exactly once.

    Facility alerts sum across rows; customer alerts are carried on every
    product row the customer has, so they are summed over DISTINCT customers.
    Summing the per-row total instead reported 6,579 alerts at a month the
    rulebook raised 5,952 for, and reported the whole book's 5,952 against
    each individual product.
    """
    if not len(frame):
        return 0
    if "alerts_facility" not in frame.columns:
        # A panel written before the split. Fall back to the month total when
        # the population is the whole month, and to the row sum otherwise —
        # both are what this function replaces, and neither is silently wrong
        # about which it is.
        return (int(frame["month_alert_total"].iloc[0])
                if "month_alert_total" in frame.columns
                else int(frame["alerts"].sum()))
    facility = int(frame["alerts_facility"].fillna(0).sum())
    customer = int(frame.drop_duplicates("customer_id")["alerts_customer"]
                   .fillna(0).sum())
    return facility + customer


def _counts(frame: Any, *, book: Any = None) -> dict[str, Any]:
    """The headline counts for one population. Customers, not alerts."""
    warned = frame[frame["warned"]] if len(frame) else frame
    exposure_warned = _money(warned["exposure_sar"].sum() if len(warned) else 0)
    exposure_all = _money(
        (book if book is not None else frame)["exposure_sar"].sum()
        if len(frame) or book is not None else 0)
    return {
        "customers": int(frame["customer_id"].nunique()) if len(frame) else 0,
        "customers_warned": int(warned["customer_id"].nunique()) if len(warned) else 0,
        "alerts": _alert_count(frame),
        "severity": _severity_counts(warned),
        "current_bad": int(frame[frame["current_bad"]]["customer_id"].nunique())
                       if len(frame) else 0,
        "forward_risk": int(frame[frame["forward_risk"]]["customer_id"].nunique())
                        if len(frame) else 0,
        "exposure_sar": exposure_all,
        "exposure_warned_sar": exposure_warned,
        "exposure_warned_pct": round(exposure_warned / exposure_all * 100, 4)
                               if exposure_all else 0.0,
        "ews_score": _weighted(frame),
        "severity_band": L.population_band_of(_weighted(frame)),
    }


def _layers(frame: Any) -> dict[str, float]:
    """Each layer's exposure-weighted score for one population."""
    if not len(frame):
        return {key: 0.0 for key in SCORED}
    if "warned" in frame.columns:
        frame = frame[frame["warned"]]
        if not len(frame):
            return {key: 0.0 for key in SCORED}
    weight = frame["exposure_sar"].fillna(0.0)
    total = float(weight.sum())
    out: dict[str, float] = {}
    for key in SCORED:
        column = frame[f"layer_{key}"].fillna(0.0)
        out[key] = round(
            float((column * weight).sum() / total) if total > 0
            else float(column.mean()), 4)
    return out


def months() -> list[str]:
    return _panel_months()


def _window(month: str, back: int) -> list[str]:
    every = _panel_months()
    if month not in every:
        return every[-back:]
    at = every.index(month)
    return every[max(0, at - back + 1): at + 1]


def _trend(months_wanted: list[str], *, product: str = "",
           where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Overall and per-layer scores across a window, one point per month."""
    points: list[dict[str, Any]] = []
    for month in months_wanted:
        try:
            frame = _panel(month)
        except FileNotFoundError:
            continue
        if product:
            frame = frame[frame["product_code"] == product]
        for column, value in (where or {}).items():
            if column in frame.columns:
                frame = frame[frame[column].astype(str) == str(value)]
        points.append({
            "month": month,
            "ews_score": _weighted(frame),
            "severity": L.population_band_of(_weighted(frame)),
            "customers_warned": int(frame[frame["warned"]]["customer_id"].nunique())
                                if len(frame) else 0,
            "current_bad": int(frame[frame["current_bad"]]["customer_id"].nunique())
                           if len(frame) else 0,
            "forward_risk": int(frame[frame["forward_risk"]]["customer_id"].nunique())
                            if len(frame) else 0,
            "exposure_warned_sar": _money(
                frame[frame["warned"]]["exposure_sar"].sum() if len(frame) else 0),
            "layers": _layers(frame),
        })
    return points


def portfolio(month: str = "", *, product: str = "",
              trend_months: int = 25) -> dict[str, Any]:
    """The management view at one month-end, for the whole book or one product.

    The product selector has to move the headline. It did not: choosing Credit
    Card left the twelve figures reading 14,251 customers and SAR 422.9mn —
    the whole book — above a Credit Card breakdown, so the two halves of one
    screen answered about two different populations.
    """
    every = _panel_months()
    if not every:
        return {"available": False,
                "because": ("The early-warning panel has not been built. Run "
                            "scripts/bootstrap_retail_installation.py.")}
    at = month if month in every else every[-1]
    whole = _panel(at)
    prior_whole = (_panel(every[every.index(at) - 1])
                   if every.index(at) > 0 else None)
    code = str(product or "").upper()
    frame = whole[whole["product_code"] == code] if code else whole
    prior = (prior_whole[prior_whole["product_code"] == code]
             if prior_whole is not None and code else prior_whole)
    # What the exposure percentage is OF, in words, so the card can say it.
    population = (str(frame["product_label"].iloc[0]).lower()
                  if code and len(frame) else "retail")

    # Based on the population the reader has selected, and LABELLED as that.
    #
    # The alternative — always dividing by the whole retail book — makes the
    # headline disagree with the product card directly beneath it: Credit Card
    # would read 1.0% under "% of retail exposure" while its own card read
    # 35.3% under "share warned", for the same money. The screen says which
    # population the percentage is of, so the two now agree.
    head = _counts(frame)
    before = (_counts(prior) if prior is not None and len(prior) else None)
    return {
        "available": True,
        "month": at,
        "product_code": code,
        "product_label": (str(frame["product_label"].iloc[0])
                          if code and len(frame) else ""),
        "population_label": population,
        "previous_month": every[every.index(at) - 1] if every.index(at) else "",
        "months": every,
        "rulebook_version": rules_mod.RULEBOOK_VERSION,
        "panel_version": EWS_PANEL_VERSION,
        "layers_version": L.EWS_LAYERS_VERSION,
        "definitions": {"current_bad": CURRENT_BAD_RULE,
                        "forward_risk": FORWARD_RISK_RULE},
        "headline": head,
        "previous": before,
        "movement": {
            "ews_score": round(head["ews_score"] - before["ews_score"], 4)
                         if before else 0.0,
            "customers_warned": head["customers_warned"] - before["customers_warned"]
                                if before else 0,
            "current_bad": head["current_bad"] - before["current_bad"]
                           if before else 0,
            "forward_risk": head["forward_risk"] - before["forward_risk"]
                            if before else 0,
        } if before else None,
        "layers": _layers(frame),
        "trend": _trend(_window(at, trend_months), product=code),
        "products": products(at, trend_months=trend_months),
        "synthetic": True,
    }


def products(month: str = "", *, trend_months: int = 25) -> list[dict[str, Any]]:
    """One card per product: score, severity, counts, exposure, trend, prose."""
    every = _panel_months()
    if not every:
        return []
    at = month if month in every else every[-1]
    frame = _panel(at)
    earlier = every[every.index(at) - 1] if every.index(at) > 0 else ""
    prior = _panel(earlier) if earlier else None
    window = _window(at, trend_months)

    out: list[dict[str, Any]] = []
    for code, rows in frame.groupby("product_code"):
        before = prior[prior["product_code"] == code] if prior is not None else None
        head = _counts(rows)
        was = _counts(before) if before is not None and len(before) else None
        now_layers, then_layers = _layers(rows), (
            _layers(before) if before is not None and len(before) else {})
        out.append({
            "product_code": str(code),
            "product_label": str(rows["product_label"].iloc[0]),
            "month": at,
            "previous_month": earlier,
            **head,
            "previous": was,
            "movement": {
                "ews_score": round(head["ews_score"] - was["ews_score"], 4),
                "customers_warned": head["customers_warned"] - was["customers_warned"],
                "current_bad": head["current_bad"] - was["current_bad"],
                "forward_risk": head["forward_risk"] - was["forward_risk"],
                "severity_from": was["severity_band"],
                "severity_to": head["severity_band"],
            } if was else None,
            "layers": now_layers,
            "layer_movement": {
                key: round(now_layers[key] - then_layers.get(key, 0.0), 4)
                for key in SCORED} if then_layers else {},
            "trend": _trend(window, product=str(code)),
            "commentary": commentary(
                str(rows["product_label"].iloc[0]), head, was,
                now_layers, then_layers, rows, before),
            "subsegment_dimensions": [
                {"column": column, "label": label}
                for column, label in SUBSEGMENTS.get(str(code), ())
                if column in frame.columns],
        })
    return sorted(out, key=lambda p: -p["ews_score"])


def commentary(product: str, now: dict[str, Any], was: dict[str, Any] | None,
               layers_now: dict[str, float], layers_was: dict[str, float],
               rows: Any, before: Any) -> str:
    """What changed this month, said in English and derived from the figures.

    Every clause is generated from a computed movement. There is no template
    with a product name dropped into it: a product that did not move says so,
    and the layers named as drivers are the layers that actually moved most.
    """
    if was is None:
        return (f"{product} is at {now['ews_score']:.1f} "
                f"({now['severity_band'].title()}) with "
                f"{now['customers_warned']:,} customers warned. There is no "
                "prior month in the panel to compare it with.")

    moved = now["ews_score"] - was["ews_score"]
    parts: list[str] = []

    if was["severity_band"] != now["severity_band"]:
        parts.append(
            f"{product} moved from {was['severity_band'].title()} to "
            f"{now['severity_band'].title()}, with the overall early-warning "
            f"score at {now['ews_score']:.1f} against {was['ews_score']:.1f} "
            "last month")
    elif abs(moved) < 0.05:
        parts.append(
            f"{product} is unchanged at {now['ews_score']:.1f} "
            f"({now['severity_band'].title()})")
    else:
        parts.append(
            f"{product} {'rose' if moved > 0 else 'fell'} from "
            f"{was['ews_score']:.1f} to {now['ews_score']:.1f} "
            f"({now['severity_band'].title()}), a move of {moved:+.1f}")

    # Which layers actually drove it.
    #
    # A layer only DRIVES a move it went the same way as. Naming the two
    # biggest movers whichever way they went produced "Credit Card fell from
    # 11.9 to 11.6 ... driven by affordability & income (-1.5) and repayment
    # behaviour (+0.2)" — repayment rose while the score fell, so it drove
    # nothing, and it was named first on a product where it pulled the other
    # way. What pulled the other way is worth saying too, and is said as that.
    movements = sorted(
        ((key, round(layers_now.get(key, 0.0) - layers_was.get(key, 0.0), 2))
         for key in SCORED),
        key=lambda pair: -abs(pair[1]))
    material = [(key, delta) for key, delta in movements if abs(delta) >= 0.05]

    def named(key: str) -> str:
        found = L.get(key)
        return found.name.lower() if found else key

    if material and abs(moved) >= 0.05:
        same = [(k, d) for k, d in material if (d > 0) == (moved > 0)][:2]
        against = [(k, d) for k, d in material if (d > 0) != (moved > 0)][:1]
        if same:
            parts.append(
                ("driven by "
                 + " and ".join(f"{named(k)} ({d:+.1f})" for k, d in same)))
        if against:
            key, delta = against[0]
            parts.append(
                f"{named(key)} moved the other way ({delta:+.1f})")

    # Broad or concentrated: is the deterioration spread across the product or
    # sitting in one pocket? Measured, not asserted.
    pocket = _worst_pocket(rows, str(now.get("product_code") or ""))
    if pocket:
        parts.append(
            f"the deterioration is concentrated in {pocket['label']} "
            f"{pocket['value']}, which carries {pocket['warned']:,} of the "
            f"{now['customers_warned']:,} warned customers "
            f"({pocket['share']:.0f}%)")

    counts: list[str] = []
    if now["current_bad"] != was["current_bad"]:
        counts.append(
            f"customers already bad went from {was['current_bad']:,} to "
            f"{now['current_bad']:,}")
    if now["forward_risk"] != was["forward_risk"]:
        counts.append(
            f"customers still performing but at high forward risk went from "
            f"{was['forward_risk']:,} to {now['forward_risk']:,}")
    if counts:
        parts.append("; ".join(counts))

    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def _worst_pocket(rows: Any, product_code: str) -> dict[str, Any] | None:
    """The subsegment value carrying the largest share of warned customers.

    Returned only when it is genuinely concentrated — more than a third of the
    warned customers in one value — so the commentary does not claim a pocket
    on a product where the deterioration is spread evenly.
    """
    if rows is None or not len(rows):
        return None
    warned = rows[rows["warned"]]
    if not len(warned):
        return None
    total = int(warned["customer_id"].nunique())
    if not total:
        return None
    best = None
    for column, label in SUBSEGMENTS.get(product_code, ()):
        if column not in warned.columns:
            continue
        grouped = warned.groupby(warned[column].astype(str))["customer_id"].nunique()
        if grouped.empty or len(grouped) < 2:
            continue
        value = grouped.idxmax()
        share = float(grouped.max()) / total * 100.0
        if share > 33.0 and (best is None or share > best["share"]):
            best = {"column": column, "label": label, "value": str(value),
                    "warned": int(grouped.max()), "share": share}
    return best


def subsegments(product: str, month: str = "", *, dimension: str = "",
                trend_months: int = 25) -> dict[str, Any]:
    """One product broken into the pockets its own data supports."""
    every = _panel_months()
    if not every:
        return {"available": False}
    at = month if month in every else every[-1]
    frame = _panel(at)
    code = str(product).upper()
    rows = frame[frame["product_code"] == code]
    earlier = every[every.index(at) - 1] if every.index(at) > 0 else ""
    prior = _panel(earlier) if earlier else None
    before_all = prior[prior["product_code"] == code] if prior is not None else None

    offered = [(column, label) for column, label
               in SUBSEGMENTS.get(code, ()) if column in frame.columns]
    chosen = dimension or (offered[0][0] if offered else "")

    cuts: list[dict[str, Any]] = []
    if chosen and chosen in rows.columns:
        for value, group in rows.groupby(rows[chosen].astype(str)):
            was = (before_all[before_all[chosen].astype(str) == str(value)]
                   if before_all is not None and chosen in before_all.columns
                   else None)
            head = _counts(group)
            then = _counts(was) if was is not None and len(was) else None
            now_layers = _layers(group)
            then_layers = (_layers(was) if was is not None and len(was) else {})
            worst = max(SCORED, key=lambda k: now_layers.get(k, 0.0))
            cuts.append({
                "value": str(value),
                **head,
                "previous": then,
                "movement": {
                    "ews_score": round(head["ews_score"] - then["ews_score"], 4),
                    "current_bad": head["current_bad"] - then["current_bad"],
                    "forward_risk": head["forward_risk"] - then["forward_risk"],
                } if then else None,
                "layers": now_layers,
                "primary_layer": worst,
                "primary_layer_name": (L.get(worst).name if L.get(worst)
                                       else worst),
                "top_reasons": _top_reasons(group),
                "trend": _trend(_window(at, trend_months), product=code,
                                where={chosen: value}),
            })
    return {
        "available": True,
        "month": at,
        "previous_month": earlier,
        "product_code": code,
        "product_label": str(rows["product_label"].iloc[0]) if len(rows) else code,
        "dimension": chosen,
        "dimension_label": next(
            (label for column, label in offered if column == chosen), chosen),
        "dimensions": [{"column": c, "label": v} for c, v in offered],
        "subsegments": sorted(cuts, key=lambda s: -s["ews_score"]),
        "definitions": {"current_bad": CURRENT_BAD_RULE,
                        "forward_risk": FORWARD_RISK_RULE},
    }


def _top_reasons(frame: Any, limit: int = 5) -> list[dict[str, Any]]:
    """The rules behind a population, most-hit first."""
    if not len(frame):
        return []
    counted: dict[str, int] = {}
    names: dict[str, str] = {}
    for rules_text, names_text in zip(frame["top_rules"].fillna(""),
                                      frame["top_rule_names"].fillna(""),
                                      strict=False):
        ids = [r for r in str(rules_text).split("|") if r]
        labels = [n for n in str(names_text).split("|") if n]
        for index, rule_id in enumerate(ids):
            counted[rule_id] = counted.get(rule_id, 0) + 1
            if index < len(labels):
                names.setdefault(rule_id, labels[index])
    ranked = sorted(counted.items(), key=lambda pair: (-pair[1], pair[0]))
    return [{"rule_id": rule_id, "rule_name": names.get(rule_id, rule_id),
             "customers": count} for rule_id, count in ranked[:limit]]


#: The filters the customer list offers. Each is a governed classification,
#: not a search: "already bad" and "still performing but at high forward risk"
#: are the two halves of the story a Head of Retail Risk tells.
COHORTS: tuple[tuple[str, str, str], ...] = (
    ("all", "All EWS customers",
     "Every customer with at least one governed signal firing this month."),
    ("current_bad", "Currently bad / delinquent",
     CURRENT_BAD_RULE + " Listed whether or not a governed signal also fired "
     "against them."),
    ("forward_risk", "Performing — high forward risk", FORWARD_RISK_RULE),
    ("critical", "Critical", "Overall EWS score in the CRITICAL band."),
    ("high", "High", "Overall EWS score in the HIGH band."),
)


def _cohort(frame: Any, cohort: str) -> Any:
    warned = frame[frame["warned"]] if len(frame) else frame
    if cohort == "current_bad":
        # Over the WHOLE population, not over the warned part of it.
        #
        # The headline counted 391 customers already bad and this list showed
        # 375 of them, because it had first thrown away everyone with no EWS
        # signal firing. Sixteen customers were thirty days down or in Stage 3
        # and could not be opened from the card that counted them. Being
        # already bad is not a prediction that needs a signal to support it;
        # it is the condition itself, and it belongs in the list whether or
        # not a rule also fired.
        return frame[frame["current_bad"]] if len(frame) else frame
    if cohort == "forward_risk":
        return warned[warned["forward_risk"]]
    if cohort == "critical":
        return warned[warned["severity"] == "CRITICAL"]
    if cohort == "high":
        return warned[warned["severity"] == "HIGH"]
    return warned


def customers(month: str = "", *, product: str = "", dimension: str = "",
              value: str = "", cohort: str = "all", limit: int = 200,
              offset: int = 0) -> dict[str, Any]:
    """The customer list. Behavioural score is always on it where available."""
    every = _panel_months()
    if not every:
        return {"available": False, "customers": []}
    at = month if month in every else every[-1]
    frame = _panel(at)

    portfolio_exposure = _money(frame["exposure_sar"].sum())
    if product:
        frame = frame[frame["product_code"] == str(product).upper()]
    product_exposure = _money(frame["exposure_sar"].sum())
    if dimension and value and dimension in frame.columns:
        frame = frame[frame[dimension].astype(str) == str(value)]
    subsegment_exposure = _money(frame["exposure_sar"].sum())

    # Every cohort's size, so the filter chips carry their own counts and
    # cannot disagree with the list they filter.
    sizes = {key: int(_cohort(frame, key)["customer_id"].nunique())
             for key, _, _ in COHORTS}

    rows = _cohort(frame, cohort).sort_values(
        ["ews_score", "exposure_sar"], ascending=False)
    # Two different totals, because the list is at customer-PRODUCT grain: a
    # customer who is bad on both a card and a personal loan is two rows and
    # one customer. The cohort chips count customers, so the footer must say
    # which of the two it is printing or the screen contradicts itself.
    total = int(len(rows))
    total_customers = int(rows["customer_id"].nunique()) if len(rows) else 0
    page = rows.iloc[offset: offset + max(1, min(int(limit), 2000))]

    listed: list[dict[str, Any]] = []
    for _, row in page.iterrows():
        exposure = float(row.get("exposure_sar") or 0.0)
        listed.append({
            "customer_id": str(row["customer_id"]),
            "product_code": str(row["product_code"]),
            "product_label": str(row.get("product_label") or ""),
            "facilities": int(row.get("facilities") or 0),
            "exposure_sar": round(exposure, 2),
            "share_of_subsegment_pct": round(
                exposure / subsegment_exposure * 100, 4)
                if subsegment_exposure else 0.0,
            "share_of_product_pct": round(exposure / product_exposure * 100, 4)
                if product_exposure else 0.0,
            "share_of_portfolio_pct": round(
                exposure / portfolio_exposure * 100, 4)
                if portfolio_exposure else 0.0,
            "dpd": _int_or_none(row.get("dpd")),
            "ifrs9_stage": _int_or_none(row.get("ifrs9_stage")),
            "current_bad": bool(row.get("current_bad")),
            "forward_risk": bool(row.get("forward_risk")),
            "ews_score": round(float(row.get("ews_score") or 0.0), 2),
            "severity": str(row.get("severity") or "LOW"),
            "behavioural_score": _num_or_none(row.get("behavioural_score")),
            "behavioural_score_previous": _num_or_none(
                row.get("behavioural_score_previous")),
            "behavioural_score_change": _num_or_none(
                row.get("behavioural_score_change")),
            "behavioural_score_band": _text(row.get("behavioural_score_band")),
            "behavioural_score_absent_because": (
                "" if _num_or_none(row.get("behavioural_score")) is not None
                else NO_BEHAVIOURAL_SCORE),
            "application_score": _num_or_none(row.get("application_score")),
            "application_score_band": _text(row.get("application_score_band")),
            "primary_layer": str(row.get("primary_layer") or ""),
            "primary_layer_name": (
                L.get(str(row.get("primary_layer") or "")).name
                if L.get(str(row.get("primary_layer") or "")) else ""),
            "top_rules": [r for r in str(row.get("top_rules") or "").split("|") if r],
            "top_rule_names": [n for n in
                               str(row.get("top_rule_names") or "").split("|") if n],
            "layers": {key: round(float(row.get(f"layer_{key}") or 0.0), 2)
                       for key in SCORED},
            "alerts": int(row.get("alerts") or 0),
        })

    return {
        "available": True,
        "month": at,
        "product_code": str(product).upper() if product else "",
        "dimension": dimension,
        "value": value,
        "cohort": cohort,
        "cohorts": [{"key": key, "label": label, "definition": rule,
                     "customers": sizes.get(key, 0)}
                    for key, label, rule in COHORTS],
        "total": total,
        "total_customers": total_customers,
        "shown": len(listed),
        "limit": limit,
        "offset": offset,
        "customers": listed,
        "definitions": {"current_bad": CURRENT_BAD_RULE,
                        "forward_risk": FORWARD_RISK_RULE},
    }


def _int_or_none(value: Any) -> int | None:
    try:
        import math

        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _num_or_none(value: Any) -> float | None:
    try:
        import math

        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


#: Why a customer can have no behavioural score, said rather than dashed.
#:
#: §6 asks for the behavioural score to be shown on every row. On 926 of the
#: 17,818 customer-products at 2026-08 there is none to show, and there is a
#: reason: the scorecard needs a month of repayment history and these
#: facilities were opened this month or last. A dash is not that reason, and a
#: number invented to fill the column would be worse than either.
NO_BEHAVIOURAL_SCORE = (
    "No behavioural score yet. The behavioural scorecard needs repayment "
    "history the facility does not have; it scores from the second month on "
    "book. The application score is shown instead.")


def _text(value: Any) -> str:
    text = str(value if value is not None else "")
    return "" if text.lower() in ("nan", "none", "<na>") else text


def customer(customer_id: str, month: str = "", *,
             trend_months: int = 25) -> dict[str, Any]:
    """One customer, across every month the panel holds."""
    every = _panel_months()
    if not every:
        return {"available": False}
    at = month if month in every else every[-1]
    wanted = str(customer_id).strip().upper()
    window = _window(at, trend_months)

    history: list[dict[str, Any]] = []
    for period in window:
        try:
            frame = _panel(period)
        except FileNotFoundError:
            continue
        rows = frame[frame["customer_id"].astype(str).str.upper() == wanted]
        if not len(rows):
            continue
        score = _one_customer_score(rows)
        history.append({
            "month": period,
            "ews_score": score,
            # The CUSTOMER band table, not the population one. Banded as a
            # population, a customer at 53 read CRITICAL on this page and HIGH
            # in the list they were opened from — two different rulers for the
            # same number, on two screens one click apart.
            "severity": L.band_of(score),
            "layers": _one_customer_layers(rows),
            "behavioural_score": _num_or_none(rows["behavioural_score"].mean()),
            "dpd": _int_or_none(rows["dpd"].max()),
            "ifrs9_stage": _int_or_none(rows["ifrs9_stage"].max()),
            "exposure_sar": _money(rows["exposure_sar"].sum()),
            "current_bad": bool(rows["current_bad"].any()),
            "forward_risk": bool(rows["forward_risk"].any()),
            "alerts": int(rows["alerts"].sum()),
            "top_rules": [r for r in "|".join(
                rows["top_rules"].fillna("")).split("|") if r][:3],
        })

    if not history:
        return {"available": False, "customer_id": wanted,
                "because": f"{wanted} is not in the early-warning panel."}

    now = history[-1]
    was = history[-2] if len(history) > 1 else None
    frame = _panel(at)
    rows = frame[frame["customer_id"].astype(str).str.upper() == wanted]

    layer_detail = []
    for key in SCORED:
        layer = L.get(key)
        layer_detail.append({
            "key": key,
            "name": layer.name if layer else key,
            "purpose": layer.purpose if layer else "",
            "source_class": layer.source_class if layer else "",
            "weight": layer.weight if layer else 0.0,
            "value": now["layers"].get(key, 0.0),
            "previous": (was or {}).get("layers", {}).get(key),
            "movement": round(now["layers"].get(key, 0.0)
                              - (was or {}).get("layers", {}).get(key, 0.0), 4)
                        if was else None,
            "trend": [{"month": h["month"], "value": h["layers"].get(key, 0.0)}
                      for h in history],
            "families": list(layer.families) if layer else [],
        })
    empty = [layer.to_dict() for layer in L.LAYERS if not layer.has_rules]

    return {
        "available": True,
        "customer_id": wanted,
        "month": at,
        "products": sorted({str(p) for p in rows["product_label"]}),
        "exposure_sar": _money(rows["exposure_sar"].sum()),
        "facilities": int(rows["facilities"].sum()),
        "ews_score": now["ews_score"],
        "severity": now["severity"],
        "current_bad": now["current_bad"],
        "forward_risk": now["forward_risk"],
        "behavioural_score": now["behavioural_score"],
        "behavioural_score_previous": (was or {}).get("behavioural_score"),
        "behavioural_score_absent_because": (
            "" if now["behavioural_score"] is not None
            else NO_BEHAVIOURAL_SCORE),
        "history": history,
        "layers": layer_detail,
        "layers_without_rules": empty,
        "definitions": {"current_bad": CURRENT_BAD_RULE,
                        "forward_risk": FORWARD_RISK_RULE},
    }


# -------------------------------------------------------------- methodology

#: What a rule's inputs are, by family. Internal is this bank's own record of
#: the customer; External is anything sourced outside it; Derived is computed
#: from one or both. The bureau feed in this deployment is a SYNTHETIC PROXY
#: and is labelled as one everywhere it appears — it is not a live bureau
#: connection and must never be described as one.
SOURCE_CLASS: dict[str, str] = {
    "REPAYMENT": "Internal", "COLLECTIONS": "Internal",
    "INCOME": "Internal", "AFFORDABILITY": "Internal",
    "SCORE": "Derived", "CARD_BEHAVIOUR": "Internal",
    "PRODUCT_STRUCTURE": "Internal", "COLLATERAL": "Internal",
    "FORBEARANCE": "Internal", "BUREAU": "External",
    "DATA_QUALITY": "Derived",
}

BUREAU_NOTE = (
    "The bureau inputs in this deployment are a SYNTHETIC PROXY generated with "
    "the rest of the demonstration book. There is no live bureau connection "
    "and no bureau agreement behind them.")


def _rule_view(rule: Any) -> dict[str, Any]:
    layer_key = L.layer_of(rule.family)
    layer = L.get(layer_key)
    return {
        "rule_id": rule.rule_id,
        "version": rule.version,
        "name": rule.name,
        "family": rule.family,
        "layer": layer_key,
        "layer_name": layer.name if layer else "",
        "scope": rule.scope,
        "products": list(rule.products),
        "variables": list(rule.features),
        "lookback_months": rule.lookback_months,
        "unit": rule.unit,
        "threshold": rule.threshold,
        "threshold_source": rule.threshold_source,
        "expression": rule.trigger_expression,
        "severity": rule.severity,
        "source_class": SOURCE_CLASS.get(rule.family, "Derived"),
        "reason_code": rule.rule_id,
        "reason_template": rule.reason_template,
        "recommended_review": rule.recommended_review,
        "is_risk_layer": bool(layer_key),
    }


def methodology() -> dict[str, Any]:
    """The current EWS methodology, in full. Nothing here asks to be fitted."""
    every = _panel_months()
    latest = every[-1] if every else ""
    possible = _possible_points()
    by_layer: dict[str, list[dict[str, Any]]] = {}
    for rule in rules_mod.RULES:
        by_layer.setdefault(L.layer_of(rule.family) or "other", []).append(
            _rule_view(rule))

    dictionary = L.variables()
    by_name = {entry["name"]: entry for entry in dictionary}

    layers = []
    for layer in L.LAYERS:
        rules_here = by_layer.get(layer.key, [])
        names = sorted({v for r in rules_here for v in r["variables"]})
        layers.append({
            **layer.to_dict(),
            "rules": sorted(rules_here, key=lambda r: r["rule_id"]),
            "rule_count": len(rules_here),
            "variables": names,
            "variable_detail": [by_name[n] for n in names if n in by_name],
            "products": sorted({p for r in rules_here for p in r["products"]}),
            "ceiling_by_product": {
                product: round(points.get(layer.key, 0.0), 2)
                for product, points in sorted(possible.items())},
        })

    return {
        "name": "Retail Early Warning — governed rulebook and layer roll-up",
        "rulebook_version": rules_mod.RULEBOOK_VERSION,
        "layers_version": L.EWS_LAYERS_VERSION,
        "panel_version": EWS_PANEL_VERSION,
        "purpose": (
            "To identify retail customers whose position is deteriorating "
            "before it reaches arrears, and to separate those who are already "
            "in trouble from those who are still paying but are likely to "
            "deteriorate."),
        "target": (
            "A governed signal firing against the customer at a month-end. "
            "Each of the 20 rules is its own test; the layer and overall "
            "scores roll them up."),
        "horizon": (
            "One reporting month. Every rule is evaluated at a month-end "
            "against that month's book and, where the rule needs a movement, "
            "the month before it."),
        "eligible_population": (
            "Every open retail facility in the published book at the scoring "
            "month, and every customer holding one."),
        "latest_scoring_date": latest,
        "months_scored": len(every),
        "scoring": {
            "layer_score": (
                "The worst signal that fired in the layer — CRITICAL 100, "
                "HIGH 60, MEDIUM 30, LOW 10 — plus ten points for each "
                "additional signal that fired with it, capped at 100."),
            "overall_score": (
                "The weighted mean of the five scored layer scores, using the "
                "weights on each layer, which sum to one."),
            "population_score": (
                "Exposure-weighted mean over the WARNED customers in the "
                "population, on the same 0-100 scale."),
            "customer_bands": [{"from": floor, "band": name}
                               for floor, name in L.BANDS],
            "population_bands": [{"from": floor, "band": name}
                                 for floor, name in L.POPULATION_BANDS],
            "severity_points": dict(L.SEVERITY_POINTS),
        },
        "definitions": {"current_bad": CURRENT_BAD_RULE,
                        "forward_risk": FORWARD_RISK_RULE},
        "layers": layers,
        "variables": dictionary,
        "variable_count": len(dictionary),
        "not_a_risk_layer": [
            {"family": family,
             "because": ("A missing input is a statement about the FILE, not "
                         "about the customer. Folding it into a risk score "
                         "would let a broken feed read as a deteriorating "
                         "borrower."),
             "rules": sorted(by_layer.get("other", []),
                             key=lambda r: r["rule_id"])}
            for family in L.NOT_A_RISK_LAYER],
        "source_classes": {
            "Internal": ("This bank's own record of the customer: repayment, "
                         "utilisation, missed payments, salary credits, "
                         "verified income, obligations, collateral."),
            "External": ("Sourced outside the bank. " + BUREAU_NOTE),
            "Derived": ("Computed from internal or external inputs: trends, "
                        "movements, ratios, scorecard output, rule flags and "
                        "layer scores."),
        },
        "bureau_note": BUREAU_NOTE,
        "glossary": L.glossary(),
        "unsourced_shorthand": L.NO_SUCH_SHORTHAND,
        "by_product": product_methodology(),
        "synthetic": True,
        "disclaimer": (
            "Synthetic demonstration material. Not a production or regulatory "
            "model, not independently validated, and no credit decision "
            "should rest on it."),
    }


def product_methodology() -> list[dict[str, Any]]:
    """How the methodology differs by product — from the rules themselves."""
    from backend.retail import taxonomy as tax

    out = []
    labels = dict(tax.PRODUCT_LABELS)
    for code in tax.PRODUCT_CODES:
        rules_here = [_rule_view(r) for r in rules_mod.RULES
                      if code in r.products]
        by_layer: dict[str, list[str]] = {}
        for rule in rules_here:
            if rule["layer"]:
                by_layer.setdefault(rule["layer"], []).append(rule["name"])
        only_here = [r["name"] for r in rules_here
                     if len(r["products"]) < len(tax.PRODUCT_CODES)]
        out.append({
            "product_code": code,
            "product_label": labels.get(code, code.replace("_", " ").title()),
            "rule_count": len(rules_here),
            "rules": sorted(rules_here, key=lambda r: r["rule_id"]),
            "by_layer": {k: sorted(v) for k, v in sorted(by_layer.items())},
            "specific_to_this_product": sorted(only_here),
        })
    return out


def rule_detail(rule_id: str, month: str = "") -> dict[str, Any]:
    """One rule, with what it actually did to the book this month."""
    rule = next((r for r in rules_mod.RULES
                 if r.rule_id.upper() == str(rule_id).upper()), None)
    if rule is None:
        return {"available": False, "rule_id": rule_id,
                "because": f"{rule_id} is not a rule in "
                           f"{rules_mod.RULEBOOK_VERSION}."}
    every = _panel_months()
    at = month if month in every else (every[-1] if every else "")
    view = _rule_view(rule)

    hits: dict[str, Any] = {"customers": 0, "alerts": 0, "exposure_sar": 0.0,
                            "current_bad": 0, "forward_risk": 0,
                            "by_product": []}
    if at:
        frame = _panel(at)
        fired = frame[frame["top_rules"].fillna("").str.contains(
            rule.rule_id, regex=False)]
        hits["customers"] = int(fired["customer_id"].nunique()) if len(fired) else 0
        hits["exposure_sar"] = _money(fired["exposure_sar"].sum()
                                      if len(fired) else 0)
        hits["current_bad"] = int(
            fired[fired["current_bad"]]["customer_id"].nunique()) if len(fired) else 0
        hits["forward_risk"] = int(
            fired[fired["forward_risk"]]["customer_id"].nunique()) if len(fired) else 0
        hits["by_product"] = [
            {"product_code": str(code),
             "product_label": str(rows["product_label"].iloc[0]),
             "customers": int(rows["customer_id"].nunique()),
             "exposure_sar": _money(rows["exposure_sar"].sum())}
            for code, rows in fired.groupby("product_code")] if len(fired) else []

    trend = []
    for period in _window(at, 25) if at else []:
        try:
            frame = _panel(period)
        except FileNotFoundError:
            continue
        fired = frame[frame["top_rules"].fillna("").str.contains(
            rule.rule_id, regex=False)]
        trend.append({"month": period,
                      "customers": int(fired["customer_id"].nunique())
                                   if len(fired) else 0})

    return {"available": True, "month": at, **view, "hits": hits,
            "trend": trend,
            "note": ("Counts are the customers for whom this rule is among "
                     "their three worst signals this month. A customer with "
                     "three more severe signals is not counted here.")}


def rules_index(month: str = "") -> dict[str, Any]:
    """Every rule, grouped by layer, with this month's hit counts."""
    every = _panel_months()
    at = month if month in every else (every[-1] if every else "")
    listed = [_rule_view(r) for r in rules_mod.RULES]
    return {
        "month": at,
        "rulebook_version": rules_mod.RULEBOOK_VERSION,
        "layers": [layer.to_dict() for layer in L.LAYERS],
        "rules": sorted(listed, key=lambda r: r["rule_id"]),
        "bureau_note": BUREAU_NOTE,
    }


# --------------------------------------------------------------------------
# §17: the prebuilt Credit Card story
#
# A demonstration needs a walk somebody can rehearse: not "click around the
# card book and see what turns up", but ten named customers, five who are
# already in trouble and five who are still paying every month and should not
# be. Nothing here is curated by hand — the ten are the worst of each cohort
# by EWS score, read from the same panel as every other screen — so the story
# stays true when the book is regenerated, and the sentence under each name is
# built from that customer's own numbers.
# --------------------------------------------------------------------------

#: The product the story is told about, and how many of each half.
STORY_PRODUCT = "CREDIT_CARD"
STORY_SIZE = 5


def _story_line(row: dict[str, Any]) -> str:
    """Why this customer is in this half of the story, from their numbers."""
    parts: list[str] = []
    dpd = row.get("dpd")
    stage = row.get("ifrs9_stage")
    if row.get("current_bad"):
        if dpd is not None and dpd >= 30:
            parts.append(f"{dpd} days past due")
        if stage == 3:
            parts.append("in IFRS 9 Stage 3")
        if not parts:
            parts.append("flagged in default")
    else:
        parts.append("still paying")
        if dpd is not None:
            parts.append(f"{dpd} days past due" if dpd
                         else "nothing past due")
        if stage is not None:
            parts.append(f"IFRS 9 Stage {stage}")
    move = row.get("behavioural_score_change")
    score = row.get("behavioural_score")
    if score is not None:
        if move is not None and abs(move) >= 1:
            direction = "fell" if move < 0 else "rose"
            parts.append(f"behavioural score {score:.0f}, {direction} "
                         f"{abs(move):.0f} on the month")
        else:
            parts.append(f"behavioural score {score:.0f}")
    layer = row.get("primary_layer_name")
    if layer:
        parts.append(f"worst layer {layer.lower()}")
    names = row.get("top_rule_names") or []
    if names:
        parts.append("signals: " + "; ".join(names[:3]).lower())
    exposure = row.get("exposure_sar") or 0.0
    facilities = row.get("facilities") or 0
    head = (f"SAR {exposure:,.0f} over "
            f"{facilities} facilit{'y' if facilities == 1 else 'ies'}")
    # Only the first letter — `str.capitalize` lower-cases everything after
    # it, which turned "in IFRS 9 Stage 3" into "in ifrs 9 stage 3".
    tail = ", ".join(parts)
    return head + ". " + (tail[:1].upper() + tail[1:] if tail else "") + "."


def story(month: str = "", *, product: str = STORY_PRODUCT) -> dict[str, Any]:
    """Five customers who are already bad, and five who are about to be."""
    every = _panel_months()
    if not every:
        return {"available": False, "because": "The EWS panel has not been built."}
    at = month if month in every else every[-1]
    code = str(product or STORY_PRODUCT).upper()

    halves: dict[str, dict[str, Any]] = {}
    for cohort in ("current_bad", "forward_risk"):
        found = customers(at, product=code, cohort=cohort, limit=STORY_SIZE)
        rows = found.get("customers", [])
        for row in rows:
            row["because"] = _story_line(row)
        halves[cohort] = {"customers": rows,
                          "total": int(found.get("total") or 0)}

    label = ""
    for row in (halves["current_bad"]["customers"]
                + halves["forward_risk"]["customers"]):
        label = row.get("product_label") or label
    if not label:
        from backend.retail import taxonomy as tax
        label = dict(tax.PRODUCT_LABELS).get(code, code)

    bad = halves["current_bad"]["total"]
    forward = halves["forward_risk"]["total"]
    return {
        "available": True,
        "month": at,
        "product_code": code,
        "product_label": label,
        "title": f"{label} at {at}: who is already bad, and who is next",
        "narrative": (
            f"At {at} the {label.lower()} book carries {bad:,} customers who "
            f"are already bad and {forward:,} who are still performing on an "
            "EWS score in the HIGH or CRITICAL band. The two halves need "
            "different actions: the first is collections and provisioning "
            "work that has already happened to the bank, the second is the "
            "only half that can still be changed."),
        "current_bad": halves["current_bad"],
        "forward_risk": halves["forward_risk"],
        "definitions": {"current_bad": CURRENT_BAD_RULE,
                        "forward_risk": FORWARD_RISK_RULE},
        "note": ("Chosen by EWS score from the same panel every other screen "
                 "reads. Nothing on this page is hand-picked."),
    }
