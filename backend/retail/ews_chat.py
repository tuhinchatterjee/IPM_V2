"""
The Early Warning chat: scoped to one domain, and provably so.

The scope is structural, not a promise
--------------------------------------
This module imports `ews_views` and `ews_model` and nothing else. It has no
catalogue, no planner, no SQL, no dataset name other than the one
`ews_views` reads. There is therefore no code path from a question asked here
to Cockpit Data, What-If Data, Scorecard Data or any corporate dataset — not
because it chooses not to look, but because it holds nothing to look with.
`SCOPE` below lists what it may reach and a test asserts the module's imports
against it.

A question outside Early Warning is answered with a scope notice naming the
module that does own it, rather than being silently answered from the wrong
book.

Deterministic, and it says what it read
---------------------------------------
Every answer is computed from the domain by the same functions the screens
call, so a figure in the chat and the same figure on the card cannot disagree.
Each answer carries its interpretation, the figures behind it, a table where
one helps, a chart where one helps, and three to five follow-up questions that
are themselves askable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.retail import ews_model as M
from backend.retail import ews_views as V

#: What this chat is allowed to reach. Checked by a test against the module's
#: own imports, so widening the scope means changing this line first.
SCOPE: tuple[str, ...] = ("retail_ews_score",)

#: Modules that own the questions this one refuses, so a redirect names the
#: right place rather than just declining.
ELSEWHERE: dict[str, tuple[str, str]] = {
    "ecl": ("Cockpit", "Expected credit loss, provisions and staging "
                       "movements are answered on the Cockpit."),
    "provision": ("Cockpit", "Provisions are answered on the Cockpit."),
    "impairment": ("Cockpit", "Impairment is answered on the Cockpit."),
    "scenario": ("What-If Analysis", "Scenarios and stress are run in What-If "
                                     "Analysis."),
    "stress": ("What-If Analysis", "Stress testing is run in What-If "
                                   "Analysis."),
    "what-if": ("What-If Analysis", "What-If questions are run in What-If "
                                    "Analysis."),
    "gini": ("Scorecard Validation", "Discrimination, calibration and "
                                     "stability are in Scorecard Validation."),
    "ks statistic": ("Scorecard Validation", "Scorecard diagnostics are in "
                                             "Scorecard Validation."),
    "psi": ("Scorecard Validation", "Population stability is in Scorecard "
                                    "Validation."),
    "calibration": ("Scorecard Validation", "Calibration is in Scorecard "
                                            "Validation."),
    "corporate": ("", "This installation serves the Saudi retail book only. "
                      "There is no corporate portfolio here."),
    "wholesale": ("", "This installation serves the Saudi retail book only."),
    "sme": ("", "This installation serves the Saudi retail book only."),
    "covenant": ("", "Covenants belong to a corporate book and are out of "
                     "scope here. This installation serves retail."),
    "rwa": ("Cockpit", "Capital measures are not part of the Early Warning "
                       "Score domain."),
    "capital": ("Cockpit", "Capital measures are not part of the Early "
                           "Warning Score domain."),
}

OUT_OF_SCOPE_NOTE = (
    "This chat is scoped to the Early Warning Score domain. It can only read "
    f"{SCOPE[0]} and the Early Warning model configuration, so it cannot "
    "answer from any other dataset.")


@dataclass
class Answer:
    interpretation: str
    answer: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    table: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    follow_ups: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    in_scope: bool = True
    scope_note: str = ""
    intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "interpretation": self.interpretation,
            "answer": self.answer,
            "evidence": self.evidence,
            "table": self.table,
            "chart": self.chart,
            "follow_ups": self.follow_ups,
            "filters": self.filters,
            "in_scope": self.in_scope,
            "scope_note": self.scope_note,
            "intent": self.intent,
            "domain": SCOPE[0],
            "domain_name": V.S.DOMAIN_NAME,
            "model_version": M.EWS_MODEL_VERSION,
            "synthetic": True,
        }


# ------------------------------------------------------------ seed prompts

PORTFOLIO_CHIPS: tuple[str, ...] = (
    "Which product has the highest Early Warning Score?",
    "Which product deteriorated most this month?",
    "Show current bad versus forward-risk customers by product.",
    "Which product has the highest exposure under warning?",
    "Show the six-month Early Warning Score trend by product.",
    "Which signals increased most this month?",
    "Show the top five warning reasons across Retail.",
    "Show the top ten Early Warning customers across Retail.",
    "Which currently performing customers are most likely to deteriorate?",
    "Which products have worsening DPD and Early Warning Score at the "
    "same time?",
    "Which portfolios have the most critical Early Warning customers?",
    "Which product has the most customers crossing the warning threshold?",
)

PRODUCT_CHIPS: tuple[str, ...] = (
    "Which sub-product is deteriorating fastest?",
    "Which sub-product has the highest Early Warning Score?",
    "Which sub-product has the highest ODR?",
    "What are the top five warning signals this month?",
    "Show the highest-risk currently performing customers.",
    "Show currently bad customers.",
    "Which customers have worsening behavioural scores?",
    "Show customers above the High threshold.",
)

CUSTOMER_CHIPS: tuple[str, ...] = (
    "Why is this customer flagged?",
    "Which layer is driving the Early Warning Score?",
    "What changed since last month?",
    "Which trigger is most severe?",
    "Which trigger has persisted longest?",
    "Is the customer already delinquent or only forward-risk?",
    "How has the behavioural score changed?",
    "How old is the bureau information?",
    "Which facility contributes most to the warning?",
    "Show the full warning history.",
)


def chips(level: str = "portfolio") -> list[str]:
    if level == "product":
        return list(PRODUCT_CHIPS)
    if level == "customer":
        return list(CUSTOMER_CHIPS)
    return list(PORTFOLIO_CHIPS)


# ------------------------------------------------------------ reading it

_PRODUCTS = {
    "credit card": "CREDIT_CARD", "card": "CREDIT_CARD",
    "cards": "CREDIT_CARD", "credit cards": "CREDIT_CARD",
    "personal finance": "PERSONAL_LOAN", "personal loan": "PERSONAL_LOAN",
    "personal": "PERSONAL_LOAN",
    "auto finance": "AUTO_LOAN", "auto loan": "AUTO_LOAN",
    "car loan": "AUTO_LOAN", "auto": "AUTO_LOAN", "vehicle": "AUTO_LOAN",
    "home finance": "HOME_LOAN", "home loan": "HOME_LOAN",
    "mortgage": "HOME_LOAN", "home": "HOME_LOAN",
}

_MONTH = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")
_CUSTOMER = re.compile(r"\b(RC-\d{4,})\b", re.IGNORECASE)


def _read_product(said: str) -> str:
    for phrase in sorted(_PRODUCTS, key=len, reverse=True):
        if phrase in said:
            return _PRODUCTS[phrase]
    return ""


def _read_sub_product(said: str) -> str:
    for sub in M.SUB_PRODUCTS:
        if sub.label.lower() in said:
            return sub.code
        first = sub.label.split()[0].lower()
        if len(first) > 4 and re.search(rf"\b{re.escape(first)}\b", said):
            return sub.code
    return ""


def _read_severity(said: str) -> str:
    for band in ("critical", "high", "medium", "low"):
        if re.search(rf"\b{band}\b", said):
            return band.upper()
    return ""


def _out_of_scope(said: str) -> tuple[str, str] | None:
    """Whether the question belongs to another module.

    Matched on WORD BOUNDARIES. Plain substring matching refused "show current
    bad versus forward-risk customers" as a capital question, because
    "fo-RWA-rd" contains "rwa".
    """
    for word, (where, why) in ELSEWHERE.items():
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", said):
            return where, why
    return None


# --------------------------------------------------------------- answering

def ask(question: str, *, month: str = "", product: str = "",
        sub_product: str = "", customer: str = "") -> dict[str, Any]:
    """Answer one Early Warning question, or explain why it is out of scope."""
    said = (question or "").strip().lower()
    if not said:
        return Answer(
            interpretation="Nothing was asked.",
            answer="Ask about the Early Warning Score — a product, a "
                   "sub-product, a customer, a signal or the model behind it.",
            follow_ups=chips("portfolio"),
            intent="empty").to_dict()

    outside = _out_of_scope(said)
    if outside:
        where, why = outside
        return Answer(
            interpretation="This question is outside the Early Warning Score "
                           "domain.",
            answer=why + (f" Open {where} for it." if where else ""),
            follow_ups=chips("portfolio"),
            in_scope=False,
            scope_note=OUT_OF_SCOPE_NOTE,
            intent="out_of_scope").to_dict()

    at = month or V.latest_month()
    found_month = _MONTH.search(said)
    if found_month:
        at = found_month.group(0)
    who = customer
    found_customer = _CUSTOMER.search(question or "")
    if found_customer:
        who = found_customer.group(1).upper()
    code = _read_product(said) or product
    sub = _read_sub_product(said) or sub_product

    for matches, handler in _ROUTES:
        if matches(said, who):
            return handler(said, at, code, sub, who).to_dict()

    return _fallback(said, at, code, sub, who).to_dict()


def _kpi(label: str, value: Any, note: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "note": note}


def _money(value: float) -> str:
    if abs(value) >= 1e9:
        return f"SAR {value / 1e9:.2f}bn"
    if abs(value) >= 1e6:
        return f"SAR {value / 1e6:.1f}mn"
    return f"SAR {value:,.0f}"


# --- highest score / worst product ----------------------------------------

def _worst_product(said: str, at: str, code: str, sub: str,
                   who: str) -> Answer:
    served = V.portfolio(at)
    # "Which portfolio has the most critical customers" is a count question,
    # not a score question, and ranking it by score answered a different one.
    by_count = _has(said, "most critical", "critical customers",
                    "most customers", "crossing the warning threshold",
                    "most warned")
    if by_count:
        cards = sorted(served["products"],
                       key=lambda c: -c["high_or_critical"])
        top = cards[0]
        headline = (
            f"{top['product_label']} carries the most High and Critical "
            f"customers: {top['high_or_critical']:,} of its "
            f"{top['customers_warned']:,} warned, against "
            f"{served['headline']['high_or_critical']:,} across retail.")
    else:
        cards = sorted(served["products"], key=lambda c: -c["ews_score"])
        top = cards[0]
        headline = (
            f"{top['product_label']} carries the highest Early Warning "
            f"Score at {top['ews_score']:.1f} ({top['severity_band']}), "
            f"with {top['customers_warned']:,} customers warned and "
            f"{_money(top['exposure_warned_sar'])} of exposure under "
            "warning.")
    return Answer(
        interpretation=(
            f"Ranking the four retail products at {at} by "
            + ("how many High and Critical customers each carries."
               if by_count else "their Early Warning Score.")),
        answer=headline,
        evidence=[_kpi(c["product_label"],
                       f"{c['high_or_critical']:,}" if by_count
                       else f"{c['ews_score']:.1f}",
                       f"{c['customers_warned']:,} warned" if by_count
                       else c["severity_band"]) for c in cards],
        table={
            "columns": ["Product", "EWS score", "Severity", "Warned",
                        "High or critical",
                        "Current bad", "Forward risk", "Exposure warned"],
            "rows": [[c["product_label"], f"{c['ews_score']:.1f}",
                      c["severity_band"], f"{c['customers_warned']:,}",
                      f"{c['high_or_critical']:,}",
                      f"{c['current_bad']:,}", f"{c['forward_risk']:,}",
                      _money(c["exposure_warned_sar"])] for c in cards],
        },
        chart={"kind": "bar", "x": "Product",
               "y": "High and critical customers" if by_count
                    else "EWS score",
               "points": [{"label": c["product_label"],
                           "value": (c["high_or_critical"] if by_count
                                     else c["ews_score"])} for c in cards]},
        follow_ups=[
            f"Which sub-product of {top['product_label']} is deteriorating "
            "fastest?",
            "Which product deteriorated most this month?",
            "Show the top five warning reasons across Retail.",
            "Show current bad versus forward-risk customers by product."],
        filters={"month": at},
        intent="worst_product")


# --- biggest movement ------------------------------------------------------

def _deteriorated_most(said: str, at: str, code: str, sub: str,
                       who: str) -> Answer:
    served = V.portfolio(at)
    moved = [c for c in served["products"] if c.get("movement")]
    if not moved:
        return Answer(
            interpretation="Comparing each product against the month before.",
            answer=f"There is no month before {at} in the domain to compare "
                   "against.",
            follow_ups=chips("portfolio"), intent="deteriorated_most")
    moved.sort(key=lambda c: -c["movement"]["ews_score"])
    top = moved[0]
    return Answer(
        interpretation=f"Comparing each product's Early Warning Score at {at} "
                       f"against {served['previous_month']}.",
        answer=(f"{top['product_label']} moved most: "
                f"{top['movement']['ews_score']:+.2f}, from "
                f"{top['previous']['ews_score']:.1f} to "
                f"{top['ews_score']:.1f}. " + top["commentary"]),
        evidence=[_kpi(c["product_label"],
                       f"{c['movement']['ews_score']:+.2f}",
                       f"now {c['ews_score']:.1f}") for c in moved],
        table={
            "columns": ["Product", "Last month", "This month", "Move",
                        "Warned move", "Forward-risk move"],
            "rows": [[c["product_label"], f"{c['previous']['ews_score']:.1f}",
                      f"{c['ews_score']:.1f}",
                      f"{c['movement']['ews_score']:+.2f}",
                      f"{c['movement']['customers_warned']:+,}",
                      f"{c['movement']['forward_risk']:+,}"] for c in moved],
        },
        follow_ups=[
            f"Which sub-product of {top['product_label']} is deteriorating "
            "fastest?",
            "Which signals increased most this month?",
            "Which product has the highest Early Warning Score?",
            f"Show the top five warning signals for "
            f"{top['product_label']}."],
        filters={"month": at},
        intent="deteriorated_most")


# --- exposure --------------------------------------------------------------

def _exposure(said: str, at: str, code: str, sub: str, who: str) -> Answer:
    served = V.portfolio(at)
    cards = sorted(served["products"],
                   key=lambda c: -c["exposure_warned_sar"])
    top = cards[0]
    head = served["headline"]
    return Answer(
        interpretation=f"Exposure under warning by product at {at}. Exposure "
                       "under warning is the gross carrying amount of every "
                       "facility held by a warned customer.",
        answer=(f"{top['product_label']} carries the most exposure under "
                f"warning at {_money(top['exposure_warned_sar'])}, "
                f"{top['exposure_warned_pct']:.1f}% of that product's book. "
                f"Across retail it is {_money(head['exposure_warned_sar'])}, "
                f"{head['exposure_warned_pct']:.1f}% of the book."),
        evidence=[_kpi(c["product_label"], _money(c["exposure_warned_sar"]),
                       f"{c['exposure_warned_pct']:.1f}% of the product")
                  for c in cards],
        table={
            "columns": ["Product", "Exposure under warning",
                        "% of product", "Total exposure", "Warned customers"],
            "rows": [[c["product_label"], _money(c["exposure_warned_sar"]),
                      f"{c['exposure_warned_pct']:.1f}%",
                      _money(c["exposure_sar"]), f"{c['customers_warned']:,}"]
                     for c in cards],
        },
        chart={"kind": "bar", "x": "Product", "y": "Exposure under warning",
               "points": [{"label": c["product_label"],
                           "value": c["exposure_warned_sar"]} for c in cards]},
        follow_ups=["Which product has the highest Early Warning Score?",
                    f"Show currently bad customers in "
                    f"{top['product_label']}.",
                    "Show current bad versus forward-risk customers by "
                    "product.",
                    "Show the top five warning reasons across Retail."],
        filters={"month": at},
        intent="exposure")


# --- cohorts ---------------------------------------------------------------

def _cohorts(said: str, at: str, code: str, sub: str, who: str) -> Answer:
    served = V.portfolio(at)
    cards = served["products"]
    head = served["headline"]
    return Answer(
        interpretation=(
            "Splitting warned customers into the two halves that need "
            "different actions. " + V.S.CURRENT_BAD_RULE + " "
            + V.S.FORWARD_RISK_RULE),
        answer=(f"At {at}, {head['current_bad']:,} retail customers are "
                f"already bad and {head['forward_risk']:,} are still "
                "performing on a HIGH or CRITICAL Early Warning Score. The "
                "first group is collections and provisioning work that has "
                "already happened; the second is the only half whose outcome "
                "can still be changed."),
        evidence=[_kpi("Already bad", f"{head['current_bad']:,}"),
                  _kpi("Forward risk, performing",
                       f"{head['forward_risk']:,}"),
                  _kpi("Warned customers", f"{head['customers_warned']:,}"),
                  _kpi("High or critical", f"{head['high_or_critical']:,}")],
        table={
            "columns": ["Product", "Customers", "Warned", "Already bad",
                        "Forward risk", "High or critical"],
            "rows": [[c["product_label"], f"{c['customers']:,}",
                      f"{c['customers_warned']:,}", f"{c['current_bad']:,}",
                      f"{c['forward_risk']:,}", f"{c['high_or_critical']:,}"]
                     for c in cards],
        },
        follow_ups=["Which currently performing customers are most likely to "
                    "deteriorate?",
                    "Show the top ten Early Warning customers across Retail.",
                    "Which product has the highest Early Warning Score?",
                    "Show the top five warning reasons across Retail."],
        filters={"month": at, "cohort": "forward_risk"},
        intent="cohorts")


# --- trend -----------------------------------------------------------------

def _trend(said: str, at: str, code: str, sub: str, who: str) -> Answer:
    served = V.portfolio(at)
    if code:
        card = next(c for c in served["products"]
                    if c["product_code"] == code)
        points = card["trend"]
        label = card["product_label"]
    else:
        points = served["trend"]
        label = "Total retail"
    first, last = (points[0], points[-1]) if points else ({}, {})
    moved = (last.get("ews_score", 0) - first.get("ews_score", 0))
    return Answer(
        interpretation=f"The Early Warning Score for {label.lower()} over the "
                       f"{len(points)} months to {at}.",
        answer=(f"{label} moved from {first.get('ews_score', 0):.1f} in "
                f"{first.get('month', '')} to {last.get('ews_score', 0):.1f} "
                f"at {at}, a change of {moved:+.1f}. Warned customers went "
                f"from {first.get('customers_warned', 0):,} to "
                f"{last.get('customers_warned', 0):,}."),
        evidence=[_kpi(p["month"], f"{p['ews_score']:.1f}",
                       f"{p['customers_warned']:,} warned") for p in points],
        chart={"kind": "line", "x": "Month", "y": "EWS score",
               "points": [{"label": p["month"], "value": p["ews_score"]}
                          for p in points]},
        table={
            "columns": ["Month", "EWS score", "Severity", "Warned",
                        "Current bad", "Forward risk", "ODR %"],
            "rows": [[p["month"], f"{p['ews_score']:.1f}", p["severity"],
                      f"{p['customers_warned']:,}", f"{p['current_bad']:,}",
                      f"{p['forward_risk']:,}", f"{p['odr_pct']:.2f}%"]
                     for p in points],
        },
        follow_ups=["Which product deteriorated most this month?",
                    "Which signals increased most this month?",
                    "Which product has the highest Early Warning Score?",
                    "Show current bad versus forward-risk customers by "
                    "product."],
        filters={"month": at, "product": code},
        intent="trend")


# --- signals ---------------------------------------------------------------

def _signals(said: str, at: str, code: str, sub: str, who: str) -> Answer:
    rising = "increase" in said or "increased" in said or "rose" in said
    served = V.signals(at, product=code, sub_product=sub)
    rows = served["signals"]
    if rising:
        rows = sorted(rows, key=lambda r: -r["change"])
    where = ""
    if sub:
        where = f" in {M.SUB_PRODUCT_LABELS.get(sub, sub)}"
    elif code:
        where = f" in {code.replace('_', ' ').title()}"
    top = rows[0] if rows else None
    if top is None:
        return Answer(interpretation="No signal fired.",
                      answer=f"Nothing fired{where} at {at}.",
                      follow_ups=chips("product"), intent="signals")
    return Answer(
        interpretation=("The governed triggers that fired" + where
                        + f" at {at}, "
                        + ("ordered by how much they grew on last month."
                           if rising else "ordered by how many customers they "
                                          "caught.")),
        answer=(f"{top['name']} is the largest{where}: "
                f"{top['customers']:,} customers, "
                f"{_money(top['exposure_sar'])} of exposure, "
                f"{top['change']:+,} on last month. It sits in "
                f"{top['layer_name']} / {top['sublayer_name']}."),
        evidence=[_kpi(r["name"], f"{r['customers']:,}",
                       f"{r['change']:+,} on last month") for r in rows[:5]],
        table={
            "columns": ["Reason code", "Signal", "Severity", "Layer",
                        "Customers", "Change", "Exposure", "Already bad",
                        "Forward risk"],
            "rows": [[r["reason_code"], r["name"], r["severity"],
                      r["layer_name"], f"{r['customers']:,}",
                      f"{r['change']:+,}", _money(r["exposure_sar"]),
                      f"{r['current_bad']:,}", f"{r['forward_risk']:,}"]
                     for r in rows[:10]],
        },
        chart={"kind": "bar", "x": "Signal", "y": "Customers",
               "points": [{"label": r["name"], "value": r["customers"]}
                          for r in rows[:5]]},
        follow_ups=[f"Show customers flagged by {top['name'].lower()}.",
                    "Which product deteriorated most this month?",
                    "Which layer is driving the score?",
                    "Show current bad versus forward-risk customers by "
                    "product."],
        filters={"month": at, "product": code, "sub_product": sub,
                 "reason": top["reason_code"]},
        intent="signals")


# --- sub-products ----------------------------------------------------------

def _sub_products(said: str, at: str, code: str, sub: str, who: str) -> Answer:
    if not code:
        code = "CREDIT_CARD"
    served = V.product(code, at)
    if not served.get("available"):
        return Answer(interpretation="No such product.",
                      answer=served.get("because", ""),
                      follow_ups=chips("portfolio"), intent="sub_products")
    cards = served["sub_products"]
    fastest = "fastest" in said or "deteriorat" in said
    odr = "odr" in said or "default" in said
    if fastest:
        moving = [c for c in cards if c.get("movement")]
        if moving:
            cards = sorted(moving, key=lambda c: -c["movement"]["ews_score"])
    elif odr:
        cards = sorted(cards, key=lambda c: -c["odr_pct"])
    top = cards[0]
    if fastest and top.get("movement"):
        headline = (f"{top['sub_product_label']} is moving fastest: "
                    f"{top['movement']['ews_score']:+.2f} on the month, to "
                    f"{top['ews_score']:.1f} ({top['severity_band']}).")
    elif odr:
        headline = (f"{top['sub_product_label']} has the highest "
                    f"default-entry rate at {top['odr_pct']:.2f}%, from "
                    f"{top['default_entries']:,} facilities entering default "
                    f"out of {top['default_eligible']:,} eligible.")
    else:
        headline = (f"{top['sub_product_label']} carries the highest Early "
                    f"Warning Score at {top['ews_score']:.1f} "
                    f"({top['severity_band']}).")
    return Answer(
        interpretation=(f"The {len(cards)} governed sub-portfolios of "
                        f"{served['product_label']} at {at}."),
        answer=headline + " " + top["commentary"],
        evidence=[_kpi(c["sub_product_label"], f"{c['ews_score']:.1f}",
                       f"{c['customers_warned']:,} warned") for c in cards],
        table={
            "columns": ["Sub-product", "EWS score", "Severity", "Customers",
                        "Warned", "Already bad", "Forward risk", "ODR %",
                        "Exposure warned"],
            "rows": [[c["sub_product_label"], f"{c['ews_score']:.1f}",
                      c["severity_band"], f"{c['customers']:,}",
                      f"{c['customers_warned']:,}", f"{c['current_bad']:,}",
                      f"{c['forward_risk']:,}", f"{c['odr_pct']:.2f}%",
                      _money(c["exposure_warned_sar"])] for c in cards],
        },
        chart={"kind": "bar", "x": "Sub-product", "y": "EWS score",
               "points": [{"label": c["sub_product_label"],
                           "value": c["ews_score"]} for c in cards]},
        follow_ups=[f"Show the top five signals for "
                    f"{top['sub_product_label']}.",
                    f"Show High and Critical {top['sub_product_label']} "
                    "customers.",
                    f"Show currently bad customers in "
                    f"{top['sub_product_label']}.",
                    "Which sub-product has the highest ODR?"],
        filters={"month": at, "product": code,
                 "sub_product": top["sub_product"]},
        intent="sub_products")


# --- customer lists --------------------------------------------------------

def _customer_list(said: str, at: str, code: str, sub: str,
                   who: str) -> Answer:
    cohort = "all"
    if "currently bad" in said or "current bad" in said \
            or "delinquent" in said:
        cohort = "current_bad"
    elif ("performing" in said and ("deteriorate" in said or "risk" in said)) \
            or "forward" in said:
        cohort = "forward_risk"
    severity = _read_severity(said)
    if severity in ("HIGH", "CRITICAL") and cohort == "all":
        cohort = severity.lower()

    score_min = None
    if "above" in said and "threshold" in said:
        score_min = M.SCALE.warning_cutoff
    dpd_zero = bool(re.search(r"dpd\s*(=|is|of)?\s*0\b", said)
                    or "dpd = 0" in said or "no arrears" in said)
    behavioural = "behavioural score" in said and (
        "worsen" in said or "falling" in said or "declin" in said)

    # A "DPD = 0" question is a DPD-bucket filter, applied by the domain so
    # the COUNT is filtered too. Trimming the page in the browser reported the
    # whole cohort's size above a filtered list.
    served = V.customers(
        at, product=code, sub_product=sub, cohort=cohort,
        reason="behavioural_fall" if behavioural else "",
        dpd_bucket="CURRENT" if dpd_zero else "",
        score_min=score_min, limit=10)
    rows = served["customers"]

    where = ""
    if sub:
        where = f" in {M.SUB_PRODUCT_LABELS.get(sub, sub)}"
    elif code:
        where = f" in {code.replace('_', ' ').title()}"
    label = next((c["label"] for c in served["cohorts"]
                  if c["key"] == cohort), cohort)
    # What actually matched after every filter, not the cohort's own size.
    size = served["total"]
    if dpd_zero:
        label += ", nothing past due"
    if behavioural:
        label += ", behavioural score falling"

    if not rows:
        return Answer(
            interpretation=f"{label}{where} at {at}.",
            answer=f"No customer matches{where} at {at}.",
            follow_ups=chips("product"), filters={"month": at,
                                                  "product": code,
                                                  "sub_product": sub,
                                                  "cohort": cohort},
            intent="customer_list")

    top = rows[0]
    return Answer(
        interpretation=(f"{label}{where} at {at}, worst first. "
                        + next((c["definition"] for c in served["cohorts"]
                                if c["key"] == cohort), "")),
        answer=(f"{size:,} customers match{where}. The worst is "
                f"{top['customer_name']} ({top['customer_id']}) at "
                f"{top['ews_score']:.1f} ({top['ews_severity']}), "
                f"{_money(top['exposure_sar'])} across "
                f"{top['facilities']} facilit"
                f"{'y' if top['facilities'] == 1 else 'ies'}, driven by "
                f"{top['primary_layer_name'].lower()}."),
        evidence=[_kpi(f"{r['customer_name']} ({r['customer_id']})",
                       f"{r['ews_score']:.1f}", r["ews_severity"])
                  for r in rows[:5]],
        table={
            "columns": ["Customer", "ID", "Sub-product", "EWS", "Severity",
                        "Behavioural", "DPD", "Stage", "Exposure",
                        "Bad now", "Forward", "Top layer", "Reasons"],
            "rows": [[r["customer_name"], r["customer_id"],
                      r["sub_product_label"], f"{r['ews_score']:.1f}",
                      r["ews_severity"],
                      (f"{r['behavioural_score']:.0f}"
                       if r["behavioural_score"] is not None
                       else "not yet scored"),
                      f"{r['dpd']:.0f}" if r["dpd"] is not None else "—",
                      f"{r['ifrs9_stage']:.0f}"
                      if r["ifrs9_stage"] is not None else "—",
                      _money(r["exposure_sar"]),
                      "Yes" if r["current_bad"] else "No",
                      "Yes" if r["forward_risk"] else "No",
                      r["primary_layer_name"],
                      ", ".join(x["code"] for x in r["reasons"])]
                     for r in rows],
        },
        follow_ups=[f"Why is {top['customer_id']} flagged?",
                    f"Which layer is driving {top['customer_id']}'s score?",
                    "Show currently bad customers.",
                    "Which currently performing customers are most likely to "
                    "deteriorate?"],
        filters={"month": at, "product": code, "sub_product": sub,
                 "cohort": cohort},
        intent="customer_list")


# --- one customer ----------------------------------------------------------

def _one_customer(said: str, at: str, code: str, sub: str,
                  who: str) -> Answer:
    served = V.customer(who, at)
    if not served.get("available"):
        return Answer(
            interpretation="Looking that customer up in the Early Warning "
                           "Score domain.",
            answer=served.get("because", f"{who} is not in the domain."),
            follow_ups=chips("portfolio"), intent="one_customer")

    layers = sorted(served["layers"], key=lambda l: -l["score"])
    worst = layers[0]
    fired = [t for layer in served["layers"] for sub_layer in layer["sublayers"]
             for t in sub_layer["triggers"] if t["fired"]]
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    by_severity = sorted(fired, key=lambda t: order.get(t["severity"], 9))
    by_persistence = sorted(
        fired, key=lambda t: -(t["action"] or {}).get("persistence", 0) or 0)

    if "bureau" in said:
        bureau = served["bureau"]
        recency = bureau["recency_months"]
        return Answer(
            interpretation=f"The bureau position held for {who}. "
                           + bureau["rule"],
            answer=(f"The last dated bureau observation for {who} is "
                    f"{bureau['last_observed']}, which is "
                    f"{recency:.0f} month{'' if recency == 1 else 's'} old. "
                    f"The score at that observation was "
                    f"{bureau['score']:.0f} (band {bureau['band']}). "
                    + bureau["no_trend_because"]),
            evidence=[_kpi("Last observed bureau score",
                           f"{bureau['score']:.0f}"),
                      _kpi("Observation date", bureau["last_observed"]),
                      _kpi("Recency", f"{recency:.0f} months"),
                      _kpi("Bureau band", bureau["band"] or "—"),
                      _kpi("Source", bureau["proxy_label"])],
            follow_ups=[f"Why is {who} flagged?",
                        f"Which layer is driving {who}'s score?",
                        f"What changed for {who} since last month?",
                        f"Show {who}'s full warning history."],
            filters={"month": at, "customer": who},
            intent="customer_bureau")

    if "persist" in said or "longest" in said:
        if by_persistence and by_persistence[0]["action"]:
            top = by_persistence[0]
            action = top["action"]
            return Answer(
                interpretation=f"The triggers firing against {who}, ordered "
                               "by how many consecutive months each has "
                               "fired.",
                answer=(f"{top['name']} has persisted longest: "
                        f"{action['persistence']:.0f} consecutive months, "
                        f"{action['direction'].lower()} and "
                        f"{action['momentum'].lower()}."),
                evidence=[_kpi(t["name"],
                               f"{(t['action'] or {}).get('persistence', 0):.0f} months",
                               (t["action"] or {}).get("direction", ""))
                          for t in by_persistence[:5]],
                table=_trigger_table(by_persistence),
                follow_ups=[f"Which trigger against {who} is most severe?",
                            f"What changed for {who} since last month?",
                            f"Which layer is driving {who}'s score?",
                            f"Show {who}'s full warning history."],
                filters={"month": at, "customer": who},
                intent="customer_persistence")

    if "severe" in said or "most severe" in said:
        if by_severity:
            top = by_severity[0]
            return Answer(
                interpretation=f"The triggers firing against {who}, worst "
                               "severity first.",
                answer=(f"{top['name']} is the most severe: "
                        f"{top['severity']}, contributing "
                        f"{top['contribution']:.0f} points to "
                        f"{M.sublayer_of_trigger(top['key']).name}. "
                        f"{top['meaning']}"),
                evidence=[_kpi(t["name"], t["severity"],
                               f"contributes {t['contribution']:.0f}")
                          for t in by_severity[:5]],
                table=_trigger_table(by_severity),
                follow_ups=[f"Which trigger against {who} has persisted "
                            "longest?",
                            f"Why is {who} flagged?",
                            f"What changed for {who} since last month?",
                            f"Which facility of {who}'s contributes most?"],
                filters={"month": at, "customer": who},
                intent="customer_severity")

    if "changed" in said or "since last month" in said:
        moved = served["movement"]
        history = served["history"]
        return Answer(
            interpretation=f"Comparing {who} at {at} against "
                           f"{served['previous_month'] or 'the month before'}.",
            answer=(f"{who}'s Early Warning Score moved {moved:+.1f} to "
                    f"{served['ews_score']:.1f} ({served['ews_severity']}). "
                    "The layer that moved most is "
                    + max(served["layers"],
                          key=lambda l: abs(l["movement"] or 0))["name"]
                    + ".") if moved is not None else
                   (f"{who} has no prior month in the domain."),
            evidence=[_kpi(l["name"], f"{l['score']:.1f}",
                           f"{l['movement']:+.1f}" if l["movement"] is not None
                           else "no prior month") for l in served["layers"]],
            chart={"kind": "line", "x": "Month", "y": "EWS score",
                   "points": [{"label": h["month"], "value": h["ews_score"]}
                              for h in history[-6:]]},
            follow_ups=[f"Why is {who} flagged?",
                        f"Which trigger against {who} is most severe?",
                        f"How old is the bureau information for {who}?",
                        f"Show {who}'s full warning history."],
            filters={"month": at, "customer": who},
            intent="customer_change")

    if "history" in said:
        history = served["history"]
        return Answer(
            interpretation=f"Every month {who} appears in the Early Warning "
                           "Score domain.",
            answer=(f"{who} has {len(history)} months in the domain, from "
                    f"{history[0]['month']} to {history[-1]['month']}. Their "
                    f"score moved from {history[0]['ews_score']:.1f} to "
                    f"{history[-1]['ews_score']:.1f}."),
            chart={"kind": "line", "x": "Month", "y": "EWS score",
                   "points": [{"label": h["month"], "value": h["ews_score"]}
                              for h in history]},
            table={
                "columns": ["Month", "EWS", "Severity", "DPD", "Stage",
                            "Behavioural", "Triggers", "Reasons"],
                "rows": [[h["month"], f"{h['ews_score']:.1f}", h["severity"],
                          f"{h['dpd']:.0f}" if h["dpd"] is not None else "—",
                          f"{h['ifrs9_stage']:.0f}"
                          if h["ifrs9_stage"] is not None else "—",
                          f"{h['behavioural_score']:.0f}"
                          if h["behavioural_score"] is not None
                          else "not yet scored",
                          f"{h['triggers_fired']}", ", ".join(h["reasons"])]
                         for h in history],
            },
            follow_ups=[f"Why is {who} flagged?",
                        f"Which layer is driving {who}'s score?",
                        f"What changed for {who} since last month?",
                        f"How old is the bureau information for {who}?"],
            filters={"month": at, "customer": who},
            intent="customer_history")

    if "facility" in said:
        facilities = sorted(served["facilities"],
                            key=lambda f: -f["ews_score"])
        top = facilities[0] if facilities else None
        return Answer(
            interpretation=f"The facilities {who} holds, worst first.",
            answer=(f"{top['facility_id']} contributes most: "
                    f"{top['product_label']} at {top['ews_score']:.1f} "
                    f"({top['ews_severity']}), "
                    f"{_money(top['exposure_sar'])}, "
                    f"{top['share_of_customer_pct']:.0f}% of this customer's "
                    "exposure.") if top else f"{who} holds no facility.",
            table={
                "columns": ["Facility", "Product", "Sub-product", "EWS",
                            "Severity", "Exposure", "% of customer", "DPD",
                            "Triggers"],
                "rows": [[f["facility_id"], f["product_label"],
                          f["sub_product_label"], f"{f['ews_score']:.1f}",
                          f["ews_severity"], _money(f["exposure_sar"]),
                          f"{f['share_of_customer_pct']:.0f}%",
                          f"{f['dpd']:.0f}" if f["dpd"] is not None else "—",
                          f"{f['triggers_fired']}"] for f in facilities],
            },
            follow_ups=[f"Why is {who} flagged?",
                        f"Which layer is driving {who}'s score?",
                        f"Show {who}'s full warning history.",
                        f"What changed for {who} since last month?"],
            filters={"month": at, "customer": who},
            intent="customer_facilities")

    if "already delinquent" in said or "only forward" in said \
            or "delinquent or" in said:
        return Answer(
            interpretation=f"Which half of the story {who} is in. "
                           + V.S.CURRENT_BAD_RULE,
            answer=(f"{who} is already bad: they are "
                    + (f"{served['history'][-1]['dpd']:.0f} days past due"
                       if served["history"][-1]["dpd"] else "flagged in "
                                                            "default")
                    + " at this month-end. This is a position, not a "
                      "prediction."
                    if served["current_bad"] else
                    f"{who} is still performing — they are not thirty days "
                    "past due, not in default and not in Stage 3 — and their "
                    f"Early Warning Score of {served['ews_score']:.1f} puts "
                    f"them in the {served['ews_severity']} band. They are a "
                    "forward-risk customer: the outcome can still change."),
            evidence=[_kpi("Already bad",
                           "Yes" if served["current_bad"] else "No"),
                      _kpi("Forward risk",
                           "Yes" if served["forward_risk"] else "No"),
                      _kpi("Days past due",
                           f"{served['history'][-1]['dpd']:.0f}"
                           if served["history"][-1]["dpd"] is not None
                           else "—"),
                      _kpi("IFRS 9 stage",
                           f"{served['history'][-1]['ifrs9_stage']:.0f}"
                           if served["history"][-1]["ifrs9_stage"] is not None
                           else "—")],
            follow_ups=[f"Why is {who} flagged?",
                        f"Which trigger against {who} is most severe?",
                        f"What changed for {who} since last month?",
                        f"Which facility of {who}'s contributes most?"],
            filters={"month": at, "customer": who},
            intent="customer_cohort")

    if "behavioural" in said:
        history = served["history"]
        return Answer(
            interpretation=f"The bank's own behavioural score for {who} over "
                           "the months the domain holds.",
            answer=(f"{who}'s behavioural score is "
                    + (f"{served['behavioural_score']:.0f}"
                       if served["behavioural_score"] is not None
                       else "not yet scored")
                    + (f", against {served['behavioural_score_previous']:.0f} "
                       "last month."
                       if served["behavioural_score_previous"] is not None
                       else ". " + served["behavioural_score_absent_because"])),
            chart={"kind": "line", "x": "Month", "y": "Behavioural score",
                   "points": [{"label": h["month"],
                               "value": h["behavioural_score"] or 0}
                              for h in history[-6:]]},
            follow_ups=[f"Why is {who} flagged?",
                        f"Which layer is driving {who}'s score?",
                        f"How old is the bureau information for {who}?",
                        f"What changed for {who} since last month?"],
            filters={"month": at, "customer": who},
            intent="customer_behavioural")

    # "why is this customer flagged" / "which layer is driving it"
    return Answer(
        interpretation=(f"Everything the Early Warning Score domain holds "
                        f"about why {who} is flagged at {at}."),
        answer=(f"{served['customer_name']} ({who}) scores "
                f"{served['ews_score']:.1f} ({served['ews_severity']}) on "
                f"{served['product_label']} / "
                f"{served['sub_product_label']}. "
                f"The layer driving it is {worst['name']} at "
                f"{worst['score']:.1f}. "
                + (f"{len(fired)} triggers are firing: "
                   + "; ".join(t["name"].lower() for t in by_severity[:3])
                   + "." if fired else "No trigger is firing.")
                + (f" A hard trigger applies: "
                   f"{served['hard_trigger_applied']}."
                   if served["hard_trigger_applied"] else "")),
        evidence=[_kpi(l["name"], f"{l['score']:.1f}", l["severity"])
                  for l in served["layers"]]
                 + [_kpi("Already bad",
                         "Yes" if served["current_bad"] else "No"),
                    _kpi("Forward risk",
                         "Yes" if served["forward_risk"] else "No")],
        table=_trigger_table(by_severity),
        chart={"kind": "line", "x": "Month", "y": "EWS score",
               "points": [{"label": h["month"], "value": h["ews_score"]}
                          for h in served["history"][-6:]]},
        follow_ups=[f"What changed for {who} since last month?",
                    f"Which trigger against {who} has persisted longest?",
                    f"How old is the bureau information for {who}?",
                    f"Which facility of {who}'s contributes most?"],
        filters={"month": at, "customer": who},
        intent="customer_why")


def _trigger_table(triggers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not triggers:
        return None
    return {
        "columns": ["Reason", "Trigger", "Severity", "Layer", "Value",
                    "Threshold", "Direction", "Magnitude", "Velocity",
                    "Momentum", "Persistence", "Recency", "Contribution"],
        "rows": [[t["reason_code"], t["name"], t["severity"],
                  (M.layer(t["layer"]).name if M.layer(t["layer"]) else ""),
                  f"{t['raw_value']:.2f}" if t["raw_value"] is not None else "—",
                  f"{t['threshold']:g}",
                  (t["action"] or {}).get("direction", ""),
                  f"{(t['action'] or {}).get('magnitude', 0):.2f}",
                  f"{(t['action'] or {}).get('velocity', 0):.2f}",
                  (t["action"] or {}).get("momentum", ""),
                  f"{(t['action'] or {}).get('persistence', 0):.0f}",
                  f"{(t['action'] or {}).get('recency', 0):.0f}",
                  f"{t['contribution']:.0f}" if t["contribution"] is not None
                  else "—"] for t in triggers],
    }


# --- the model -------------------------------------------------------------

def _about_model(said: str, at: str, code: str, sub: str, who: str) -> Answer:
    served = V.model(at)
    return Answer(
        interpretation="What the Early Warning Score is and how it is "
                       "calculated.",
        answer=(f"{served['name']} version {served['model_version']}: "
                f"{served['counts']['layers']} layers, "
                f"{served['counts']['sublayers']} sublayers, "
                f"{served['counts']['classifiers']} classifier variables and "
                f"{served['counts']['triggers_evaluated']} evaluated triggers "
                f"on a {served['scale']['minimum']:g}–"
                f"{served['scale']['maximum']:g} scale where higher is worse. "
                f"A customer is warned at {served['scale']['warning_cutoff']:g}."),
        evidence=[_kpi(l["name"], f"{l['weight'] * 100:.0f}%",
                       f"{l['sublayer_count']} sublayers, "
                       f"{l['trigger_count']} triggers")
                  for l in served["layers"]],
        table={
            "columns": ["Layer", "Kind", "Weight", "Sublayers", "Classifiers",
                        "Triggers", "Customers firing"],
            "rows": [[l["name"], l["kind"], f"{l['weight'] * 100:.0f}%",
                      f"{l['sublayer_count']}", f"{l['classifier_count']}",
                      f"{l['trigger_count']}", f"{l.get('customers', 0):,}"]
                     for l in served["layers"]],
        },
        follow_ups=["Which product has the highest Early Warning Score?",
                    "Show the top five warning reasons across Retail.",
                    "Which signals increased most this month?",
                    "Show the six-month Early Warning Score trend by product."],
        filters={"month": at},
        intent="model")


# --- fallback --------------------------------------------------------------

def _fallback(said: str, at: str, code: str, sub: str, who: str) -> Answer:
    if who:
        return _one_customer(said, at, code, sub, who)
    if sub or code:
        return _sub_products(said, at, code, sub, who)
    return _worst_product(said, at, code, sub, who)


# --------------------------------------------------------------- the router

def _has(said: str, *words: str) -> bool:
    return any(word in said for word in words)


#: In priority order. A question naming a sub-product AND asking for signals
#: is a signals question scoped to that sub-product, not a sub-product
#: question — the first router matched the sub-product name and answered the
#: wrong thing, twice.
_ROUTES: tuple[tuple[Any, Any], ...] = (
    # A customer id settles it outright.
    (lambda s, who: bool(who), _one_customer),
    (lambda s, who: _has(s, "how is the score calculated", "how does the "
                            "model", "what is the model", "model "
                            "configuration", "explain the model",
                            "how is it scored", "how does the score work"),
     _about_model),
    # "Which product/portfolio has the most ..." is a ranking, whatever noun
    # follows it.
    (lambda s, who: _has(s, "which portfolio", "which product",
                         "which products", "which book")
     and not _has(s, "sub-product", "sub product"), _worst_product),
    (lambda s, who: _has(s, "deteriorated most", "moved most", "worsened most",
                         "biggest move", "deteriorated the most"),
     _deteriorated_most),
    # Signals, before sub-products: "the top five signals for Privilege Card"
    # is a signals question.
    (lambda s, who: _has(s, "signal", "reason", "trigger", "warning reason",
                         "rule"), _signals),
    # "Current bad VERSUS forward risk" asks for both halves at once, which
    # is the cohort split rather than one list.
    (lambda s, who: (_has(s, "versus", " vs ", "compared with")
                     and _has(s, "current bad", "currently bad",
                              "forward risk", "forward-risk"))
     or _has(s, "current bad and forward", "bad vs forward"), _cohorts),
    # Then the customer list, also before sub-products, for the same reason.
    (lambda s, who: _has(s, "customer", "current bad", "currently bad",
                         "forward risk", "forward-risk", "delinquent",
                         "dpd", "threshold", "top ten", "top 10",
                         "highest-risk", "highest risk"), _customer_list),
    (lambda s, who: _has(s, "sub-product", "sub product", "subproduct",
                         "sub-portfolio", "privilege", "platinum", "silver",
                         "ultra", "first home", "second property",
                         "top-up", "buyout", "refinance"), _sub_products),
    (lambda s, who: _has(s, "trend", "six-month", "6-month", "over time",
                         "last six months", "history"), _trend),
    (lambda s, who: _has(s, "exposure"), _exposure),
    (lambda s, who: _has(s, "odr", "default rate", "default-entry"),
     _sub_products),
    (lambda s, who: _has(s, "highest", "worst", "most critical", "top"),
     _worst_product),
)
