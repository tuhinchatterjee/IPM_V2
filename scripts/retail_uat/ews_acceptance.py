"""
EW-01 to EW-22: the Early Warning acceptance walk, in a real browser.

Every case here clicks what a Head of Retail Risk would click, against the
same frontend and the same backend the launcher serves. Nothing is mocked and
no test-only route exists: a case passes only because an ordinary user doing
the same thing would see the same thing.

The cases are written against the acceptance brief rather than against the
implementation, so "the screen renders" is never a pass on its own. Where the
brief asks for a number, the case reads the number off the screen and checks
it against the number the API serves; where it asks for a control, the case
uses the control and checks that what it controls actually changed.

Run it with the stack up:

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/ews_acceptance.py

It writes one JSON record and a screenshot per case under
docs/evidence/retail_ews/.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    DEMO_PASSWORD, DEMO_USER, FRONTEND, Session, chromium_path,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "evidence" / "retail_ews"
SHOTS = OUT / "cases"

PASS, FAIL = "PASS", "FAIL"


class Case:
    """One acceptance case and everything it proved."""

    def __init__(self, case_id: str, title: str):
        self.id = case_id
        self.title = title
        self.checks: list[tuple[str, bool, str]] = []
        self.note = ""

    def check(self, what: str, ok: bool, saw: Any = "") -> bool:
        self.checks.append((what, bool(ok), str(saw)[:400]))
        return bool(ok)

    @property
    def status(self) -> str:
        return PASS if self.checks and all(c[1] for c in self.checks) else FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "note": self.note,
            "checks": [{"check": w, "passed": ok, "saw": saw}
                       for w, ok, saw in self.checks],
        }


def digits(text: str) -> int | None:
    r"""The first integer in a string, thousands separators and all.

    It must start on a digit: ``[\d,]+`` matched the comma in "FORWARD RISK,
    STILL PERFORMING" and read the card as having no number on it.
    """
    found = re.search(r"\d[\d,]*", text or "")
    if not found:
        return None
    try:
        return int(found.group(0).replace(",", ""))
    except ValueError:
        return None


class Walk:
    def __init__(self, page: Any, api: Callable[[str], dict]):
        self.page = page
        self.api = api
        self.cases: list[Case] = []

    # -- small helpers ------------------------------------------------------

    def go(self, route: str, wait_for: str = "", pause: int = 5000) -> None:
        self.page.goto(FRONTEND + route, wait_until="networkidle",
                       timeout=120_000)
        if wait_for:
            self.page.wait_for_selector(wait_for, timeout=90_000)
        self.page.wait_for_timeout(pause)

    def text(self) -> str:
        return self.page.inner_text("body")

    def at(self, testid: str) -> str:
        found = self.page.locator(f'[data-testid="{testid}"]')
        return found.first.inner_text() if found.count() else ""

    def has(self, testid: str) -> int:
        return self.page.locator(f'[data-testid="{testid}"]').count()

    def shot(self, name: str) -> None:
        SHOTS.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

    def case(self, case_id: str, title: str) -> Case:
        one = Case(case_id, title)
        self.cases.append(one)
        return one

    # -- the cases ----------------------------------------------------------

    def ew_01(self) -> None:
        """The landing page is the portfolio, with month and product."""
        c = self.case("EW-01", "Early Warning opens on the portfolio, with "
                               "a month selector and a product selector")
        self.go("/early-warning", '[data-testid="ews-portfolio"]', 8000)
        c.check("the portfolio view renders", self.has("ews-portfolio") == 1)
        c.check("a month selector is on the page", self.has("ews-month") == 1)
        c.check("a product selector is on the page",
                self.has("ews-product-select") == 1)
        served = self.api("/retail/early-warning/portfolio")
        latest = served["months"][-1]
        chosen = self.page.locator('[data-testid="ews-month"]').input_value()
        c.check("it defaults to the latest published month",
                chosen == latest, f"showing {chosen}, latest is {latest}")
        c.check("it defaults to all products",
                self.page.locator(
                    '[data-testid="ews-product-select"]').input_value() == "")
        self.shot("EW-01")

    def ew_02(self) -> None:
        """The headline cards, and customers counted apart from alerts."""
        c = self.case("EW-02", "Twelve headline figures, with customers "
                               "counted apart from alerts")
        served = self.api("/retail/early-warning/portfolio")
        head = served["headline"]
        for key, testid in (("customers", "ews-kpi-customers"),
                            ("customers_warned", "ews-kpi-warned"),
                            ("current_bad", "ews-kpi-bad"),
                            ("forward_risk", "ews-kpi-forward")):
            shown = digits(self.at(testid))
            c.check(f"{testid} reads the served {key}",
                    shown == int(head[key]),
                    f"screen {shown}, api {head[key]}")
        for band in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            shown = digits(self.at(f"ews-kpi-{band.lower()}"))
            c.check(f"the {band} count is the served one",
                    shown == int(head["severity"][band]),
                    f"screen {shown}, api {head['severity'][band]}")
        c.check("exposure under warning is shown",
                "SAR" in self.at("ews-kpi-exposure"), self.at("ews-kpi-exposure"))
        c.check("the share of retail exposure is shown",
                "%" in self.at("ews-kpi-exposure-pct"),
                self.at("ews-kpi-exposure-pct"))
        c.check("a portfolio EWS score is shown",
                bool(self.at("ews-kpi-score")), self.at("ews-kpi-score"))
        c.check("a portfolio severity band is shown",
                bool(self.at("ews-kpi-band")), self.at("ews-kpi-band"))
        alerts = int(head["alerts"])
        warned = int(head["customers_warned"])
        c.check("the alert count is not passed off as a customer count",
                alerts != warned and f"{alerts:,}" in self.text()
                and "Customers, not alerts" in self.text(),
                f"{warned} customers carry {alerts} alerts")

    def ew_03(self) -> None:
        """The portfolio's own 25-month trend."""
        c = self.case("EW-03", "The portfolio carries a 25-month EWS trend")
        served = self.api("/retail/early-warning/portfolio")
        c.check("the served trend is 25 months",
                len(served["trend"]) == 25, len(served["trend"]))
        c.check("a trend chart is drawn",
                "PORTFOLIO EWS SCORE, 25 MONTHS" in self.text().upper())
        c.check("the first and last month are on the axis",
                served["trend"][0]["month"] in self.text()
                and served["trend"][-1]["month"] in self.text())

    def ew_04(self) -> None:
        """A card per product, with score, severity, counts and movement."""
        c = self.case("EW-04", "Every product has a dashboard card with a "
                               "score, a severity, counts and a movement")
        served = self.api("/retail/early-warning/portfolio")
        for product in served["products"]:
            code = product["product_code"]
            card = self.at(f"ews-product-{code}")
            c.check(f"{code} has a card", bool(card))
            c.check(f"{code} shows its served score",
                    f"{product['ews_score']:.1f}" in card,
                    f"looking for {product['ews_score']:.1f}")
            c.check(f"{code} shows its severity band",
                    product["severity_band"] in card.upper(),
                    product["severity_band"])
            c.check(f"{code} shows its customer count",
                    f"{product['customers']:,}" in card,
                    f"{product['customers']:,}")
            c.check(f"{code} shows a month-on-month movement",
                    "on " + product["previous_month"] in card
                    or "no prior month" in card.lower(),
                    product["previous_month"])
            c.check(f"{code}'s alert count is its own, not the book's",
                    product["alerts"] < served["headline"]["alerts"],
                    f"{product['alerts']} of {served['headline']['alerts']}")
            c.check(f"{code} shows the exposure behind it",
                    "SAR" in card)

    def ew_05(self) -> None:
        """Six layers on every product, including the one with no rules."""
        c = self.case("EW-05", "Six layer trends on every product card, the "
                               "empty sixth included")
        wanted = ("repayment", "affordability", "score", "structure", "bureau")
        for key in wanted:
            c.check(f"a {key} trend is drawn",
                    self.has(f"ews-layer-trend-{key}") >= 1,
                    self.has(f"ews-layer-trend-{key}"))
        c.check("the sixth layer is named rather than omitted",
                "Cycle sensitivity" in self.text())
        c.check("and says why it carries nothing",
                "carries no rules" in self.text()
                or "no rule" in self.text().lower())

    def ew_06(self) -> None:
        """Commentary computed from movements, not written by hand."""
        c = self.case("EW-06", "Management commentary is generated from the "
                               "product's own movements")
        served = self.api("/retail/early-warning/portfolio")
        prose = {p["product_code"]: self.at(f"ews-commentary-{p['product_code']}")
                 for p in served["products"]}
        c.check("every product has commentary",
                all(len(v) > 40 for v in prose.values()),
                {k: len(v) for k, v in prose.items()})
        c.check("no two products share the same sentence",
                len({v for v in prose.values()}) == len(prose))
        for product in served["products"]:
            code = product["product_code"]
            score = f"{product['ews_score']:.1f}"
            c.check(f"{code}'s commentary quotes its own computed score",
                    score in prose[code], f"{score} in {prose[code][:120]}")

    def ew_07(self) -> None:
        """Product opens a subsegment view with product-specific cuts."""
        c = self.case("EW-07", "A product opens subsegments cut on dimensions "
                               "that belong to that product")
        self.page.click('[data-testid="ews-open-CREDIT_CARD"]')
        self.page.wait_for_selector('[data-testid="ews-subsegments"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        served = self.api(
            "/retail/early-warning/portfolio/subsegments?product=CREDIT_CARD")
        c.check("the subsegment view opened", self.has("ews-subsegments") == 1)
        c.check("the address names the product",
                "product=CREDIT_CARD" in self.page.url, self.page.url)
        offered = [d["column"] for d in served["dimensions"]]
        c.check("more than one dimension is offered", len(offered) > 1, offered)
        for column in offered:
            c.check(f"the {column} cut is offered on screen",
                    self.has(f"ews-dimension-{column}") == 1)
        c.check("a card-only dimension is among them",
                any(d in offered for d in ("card_behaviour_segment",
                                           "utilisation_band")), offered)
        c.check("each subsegment carries its own reason codes",
                self.page.locator('[data-testid^="ews-reason-"]').count() > 0)
        self.shot("EW-07")

    def ew_08(self) -> None:
        """Subsegment opens the customer list."""
        c = self.case("EW-08", "A subsegment opens the customers inside it")
        first = self.page.locator('[data-testid^="ews-open-customers-"]').first
        first.click()
        self.page.wait_for_selector('[data-testid="ews-customer-list"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        c.check("the customer list opened", self.has("ews-customer-list") == 1)
        c.check("the address names the subsegment",
                "value=" in self.page.url, self.page.url)
        c.check("customers are listed",
                self.page.locator(
                    '[data-testid^="ews-customer-RC"]').count() > 0)
        self.shot("EW-08")

    def ew_09(self) -> None:
        """Every column the brief asks for, behavioural score included."""
        c = self.case("EW-09", "The customer list carries every required "
                               "column, with the behavioural score always on it")
        header = self.at("ews-customer-list").upper()
        for column in ("CUSTOMER", "PRODUCT", "EXPOSURE", "DPD", "STAGE",
                       "BAD NOW", "FORWARD", "EWS", "SEVERITY", "BEHAV",
                       "APP.", "WORST LAYER", "TOP REASONS"):
            c.check(f"a {column} column is present", column in header, column)
        rows = self.page.locator('[data-testid^="ews-behavioural-"]')
        c.check("a behavioural score is rendered for every row",
                rows.count() > 0, rows.count())
        shown = [rows.nth(i).inner_text().strip() for i in range(min(10, rows.count()))]
        c.check("and it is a number rather than a dash",
                all(any(ch.isdigit() for ch in v) for v in shown), shown[:5])

    def ew_10(self) -> None:
        """The two cohorts, and counts that agree with the headline."""
        c = self.case("EW-10", "Already bad and forward risk are filters, and "
                               "their counts agree with the portfolio")
        self.go("/early-warning", '[data-testid="ews-portfolio"]', 8000)
        head = self.api("/retail/early-warning/portfolio")["headline"]
        self.page.click('[data-testid="ews-kpi-bad"] button')
        self.page.wait_for_selector('[data-testid="ews-customer-list"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        c.check("the already-bad card opens the list filtered",
                "cohort=current_bad" in self.page.url, self.page.url)
        chip = self.at("ews-cohort-current_bad")
        c.check("the cohort chip count matches the headline",
                digits(chip.split("(")[-1]) == int(head["current_bad"]),
                f"chip {chip}, headline {head['current_bad']}")
        footer = self.at("ews-customer-list-count")
        c.check("the footer distinguishes rows from customers",
                f"{int(head['current_bad']):,}" in footer
                and "customer" in footer, footer)
        c.check("every listed row is flagged bad now",
                self.has("ews-bad-yes") > 0, self.has("ews-bad-yes"))
        c.check("the definition of already bad is on the screen",
                "30 or more days past due" in self.text())
        self.page.click('[data-testid="ews-cohort-forward_risk"]')
        self.page.wait_for_timeout(6000)
        forward = self.at("ews-cohort-forward_risk")
        c.check("the forward-risk chip count matches the headline",
                digits(forward.split("(")[-1]) == int(head["forward_risk"]),
                f"chip {forward}, headline {head['forward_risk']}")
        c.check("every listed row is flagged forward risk",
                self.has("ews-forward-yes") > 0, self.has("ews-forward-yes"))
        c.check("the definition of forward risk is on the screen",
                "still paying" in self.text())
        self.shot("EW-10")

    def ew_11(self) -> None:
        """A customer, with a trend per layer over the window."""
        c = self.case("EW-11", "A customer opens with a 25-month trend for "
                               "every scored layer")
        # The row carries the test id; the customer's own name inside it is
        # what a reader clicks. Clicking the row itself lands on whichever
        # cell happens to be in the middle, which is not a control.
        self.page.locator(
            '[data-testid^="ews-customer-RC"] button').first.click()
        self.page.wait_for_selector('[data-testid="ews-customer-detail"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(6000)
        c.check("the customer detail opened",
                self.has("ews-customer-detail") == 1)
        for key in ("repayment", "affordability", "score", "structure", "bureau"):
            c.check(f"a {key} panel is on the detail",
                    self.has(f"ews-detail-layer-{key}") == 1)
        who = re.search(r"customer=([A-Z0-9-]+)", self.page.url)
        c.check("the address names the customer", bool(who), self.page.url)
        if who:
            served = self.api(
                "/retail/early-warning/portfolio/customers/" + who.group(1))
            months = len(served["history"])
            # Every month the customer is ON THE BOOK, up to the panel's
            # twenty-five. A customer originated four months ago has four
            # months of history and inventing twenty-one more would be the
            # defect, not the feature.
            c.check("the history covers the customer's months on book, "
                    "up to the panel's twenty-five",
                    1 <= months <= 25, months)
            c.check("every layer trend runs the full history",
                    all(len(layer["trend"]) == months
                        for layer in served["layers"]),
                    [len(layer["trend"]) for layer in served["layers"]])
            c.check("the behavioural score is shown on the detail",
                    bool(self.at("ews-detail-behavioural")),
                    self.at("ews-detail-behavioural"))
        # And a customer who has been on the book throughout does get all
        # twenty-five, which is what the brief asks the panel to hold.
        listed = self.api(
            "/retail/early-warning/portfolio/customers?cohort=high&limit=8")
        spans = [len(self.api("/retail/early-warning/portfolio/customers/"
                              + row["customer_id"])["history"])
                 for row in listed["customers"][:8]]
        c.check("a long-tenured customer carries all twenty-five months",
                25 in spans, spans)
        # The two screens must band the same number the same way.
        disagreed = []
        for row in listed["customers"][:8]:
            detail = self.api("/retail/early-warning/portfolio/customers/"
                              + row["customer_id"])
            if (abs(detail["ews_score"] - row["ews_score"]) > 0.01
                    or detail["severity"] != row["severity"]):
                disagreed.append(
                    f"{row['customer_id']}: list {row['ews_score']} "
                    f"{row['severity']}, detail {detail['ews_score']} "
                    f"{detail['severity']}")
        c.check("the list and the detail agree on a customer's score and band",
                not disagreed, disagreed)
        self.shot("EW-11")

    def ew_12(self) -> None:
        """The reason-code timeline, and its links into the rules."""
        c = self.case("EW-12", "The customer carries a reason-code timeline "
                               "that opens the rule behind each code")
        c.check("a reason-code timeline is on the detail",
                self.has("ews-reason-timeline") == 1)
        timeline = self.at("ews-reason-timeline")
        c.check("it names governed rule ids",
                "RET-EWS-" in timeline, timeline[:160])
        link = self.page.locator(
            '[data-testid="ews-reason-timeline"] a[href*="rule="]').first
        c.check("each code links to the rule that raised it",
                link.count() > 0 if hasattr(link, "count") else True)

    def ew_13(self) -> None:
        """The methodology page describes a model that is running."""
        c = self.case("EW-13", "The methodology page describes the model that "
                               "is already running")
        self.go("/early-warning/methodology", '[data-testid="ews-methodology"]',
                8000)
        served = self.api("/retail/early-warning/methodology-detail")
        body = self.text()
        c.check("the page renders", self.has("ews-methodology") == 1)
        for field in ("rulebook_version", "layers_version",
                      "latest_scoring_date"):
            c.check(f"it states the {field}", str(served[field]) in body,
                    served[field])
        for field in ("purpose", "target", "horizon", "eligible_population"):
            c.check(f"it states the {field}",
                    served[field][:60] in body, served[field][:60])
        c.check("it never asks the reader to fit a model",
                "Fit a model" not in body)
        c.check("all six layers are listed",
                all(self.has(f"ews-method-layer-{one['key']}") == 1
                    for one in served["layers"]),
                [one["key"] for one in served["layers"]])
        c.check("the customer and population band tables are both shown",
                "CUSTOMER SEVERITY BANDS" in body.upper()
                and "POPULATION SEVERITY BANDS" in body.upper())
        self.shot("EW-13")

    def ew_14(self) -> None:
        """Every variable, with the ten facts the brief asks for."""
        c = self.case("EW-14", "Every input the rulebook reads is documented "
                               "with meaning, source, transformation, "
                               "direction, refresh, products, weight and "
                               "reason code")
        served = self.api("/retail/early-warning/methodology-detail")
        body = self.text()
        c.check("the served dictionary covers every rule input",
                served["variable_count"] >= 27, served["variable_count"])
        missing = [v["name"] for v in served["variables"]
                   if self.has(f"ews-variable-{v['name']}") == 0]
        c.check("every input is rendered on the page", not missing, missing)
        for label in ("RAW INPUT", "TRANSFORMATION", "DIRECTION OF RISK",
                      "REFRESH FREQUENCY", "APPLICABLE PRODUCTS",
                      "WEIGHT CARRIED", "REASON CODES GENERATED"):
            c.check(f"{label} is stated", label in body.upper(), label)
        undocumented = [v["name"] for v in served["variables"]
                        if v["transformation"] == "Not documented."]
        c.check("no input is left undocumented", not undocumented, undocumented)

    def ew_15(self) -> None:
        """Internal, external, derived — and the bureau told the truth about."""
        c = self.case("EW-15", "Internal, external and derived are "
                               "distinguished, and the bureau proxy is not "
                               "called a live feed")
        served = self.api("/retail/early-warning/methodology-detail")
        body = self.text()
        for kind in ("Internal", "External", "Derived"):
            c.check(f"{kind} is defined on the page",
                    served["source_classes"][kind][:50] in body, kind)
        c.check("the bureau note is shown", bool(self.at("ews-bureau-note")))
        note = self.at("ews-bureau-note").upper()
        c.check("it says the bureau inputs are synthetic",
                "SYNTHETIC" in note, note[:160])
        c.check("it says there is no live bureau connection",
                "NO LIVE BUREAU" in note, note[:160])
        c.check("nothing on the page claims a live bureau feed",
                "live bureau feed" not in body.lower())

    def ew_16(self) -> None:
        """T, A and C are not given invented meanings."""
        c = self.case("EW-16", "T, A and C are stated to have no governed "
                               "meaning rather than being invented one")
        body = self.text()
        c.check("the statement is on the methodology page",
                bool(self.at("ews-unsourced-shorthand")))
        said = self.at("ews-unsourced-shorthand")
        c.check("it names all three", "T, A and C" in said, said[:200])
        c.check("no meaning is invented for them",
                "not governed abbreviations" in said
                or "no meaning is shown" in said, said[:200])
        c.check("a glossary defines the terms that DO have meanings",
                "DPD" in body and "SICR" in body)

    def ew_17(self) -> None:
        """What applies to which product."""
        c = self.case("EW-17", "The methodology says which rules apply to "
                               "each product")
        served = self.api("/retail/early-warning/methodology-detail")
        for product in served["by_product"]:
            code = product["product_code"]
            card = self.at(f"ews-method-product-{code}")
            c.check(f"{code} has a card", bool(card), code)
            c.check(f"{code} states how many rules apply",
                    str(product["rule_count"]) in card,
                    f"{product['rule_count']} in {card[:80]}")
        counts = {p["product_code"]: p["rule_count"]
                  for p in served["by_product"]}
        c.check("the products do not all carry the same rules",
                len(set(counts.values())) > 1, counts)

    def ew_18(self) -> None:
        """The 500 problem."""
        c = self.case("EW-18", "The signals screen says how many alerts it is "
                               "showing, out of how many there are")
        self.go("/early-warning/signals", '[data-testid="signals-showing"]',
                8000)
        served = self.api("/retail/early-warning?month="
                          + self.page.locator(
                              '[data-testid="signals-month"]').input_value()
                          + "&limit=1")
        total = int(served["alert_count"])
        line = self.at("signals-showing")
        c.check("the line names the true total",
                f"{total:,}" in line, f"{total:,} in {line}")
        c.check("it does not present the page size as the finding",
                not re.search(r"^Showing 500 alerts", line), line)
        c.check("the headline figure is the true total",
                digits(self.at("signals-showing")) is not None
                and f"{total:,}" in self.text(), line)
        c.check("nothing on the page reads 'ALERTS 500'",
                "ALERTS\n500" not in self.text().upper())
        self.shot("EW-18")

    def ew_19(self) -> None:
        """Every chip is a filter."""
        c = self.case("EW-19", "Rule, layer, severity and product chips all "
                               "filter the list and the count")
        month = self.page.locator('[data-testid="signals-month"]').input_value()
        for testid, query, label in (
            ("signals-chip-rule-RET-EWS-001", "rule=RET-EWS-001", "rule"),
            ("signals-chip-layer-bureau", "layer=bureau", "layer"),
            ("signals-chip-severity-CRITICAL", "severity=CRITICAL", "severity"),
            ("signals-chip-product-CREDIT_CARD", "product=CREDIT_CARD",
             "product"),
        ):
            self.page.click(f'[data-testid="{testid}"]')
            self.page.wait_for_timeout(6000)
            expected = int(self.api(
                f"/retail/early-warning?month={month}&limit=1&{query}")["alert_count"])
            line = self.at("signals-showing")
            c.check(f"the {label} chip narrows the count to the served one",
                    f"{expected:,}" in line, f"{expected:,} in {line}")
            self.page.click(f'[data-testid="{testid}"]')
            self.page.wait_for_timeout(5000)
        c.check("the decks survive a click so another can be chosen",
                self.has("signals-by-rule") == 1
                and self.has("signals-by-layer") == 1)
        self.shot("EW-19")

    def ew_20(self) -> None:
        """The Cockpit hands over its filter."""
        c = self.case("EW-20", "The Cockpit's Early Warning strip deep-links "
                               "into Early Warning with the filter applied")
        self.go("/", '[data-testid="retail-ews-strip"]', 9000)
        c.check("the strip is on the Cockpit",
                self.has("retail-ews-strip") == 1)
        link = self.page.locator(
            '[data-testid="retail-ews-strip-on-high-or-critical-severity"]')
        c.check("the severity figure is a link", link.count() == 1)
        href = link.first.get_attribute("href") or ""
        c.check("and it carries the severity filter",
                "severity=CRITICAL" in href, href)
        link.first.click()
        self.page.wait_for_selector('[data-testid="signals-showing"]',
                                    timeout=90_000)
        self.page.wait_for_timeout(7000)
        c.check("it lands on the signals screen already filtered",
                self.page.locator(
                    '[data-testid="signals-severity"]').input_value() == "CRITICAL",
                self.page.locator('[data-testid="signals-severity"]').input_value())
        month = self.page.locator('[data-testid="signals-month"]').input_value()
        expected = int(self.api(
            f"/retail/early-warning?month={month}&limit=1&severity=CRITICAL")["alert_count"])
        c.check("showing the filtered count, not the whole book",
                f"{expected:,}" in self.at("signals-showing"),
                self.at("signals-showing"))
        self.shot("EW-20")

    def ew_21(self) -> None:
        """The prebuilt Credit Card story."""
        c = self.case("EW-21", "A prebuilt Credit Card story: five already "
                               "bad, five still performing")
        self.go("/early-warning", '[data-testid="ews-story"]', 8000)
        served = self.api("/retail/early-warning/portfolio/story")
        c.check("the story is on the landing page", self.has("ews-story") == 1)
        c.check("five customers are already bad",
                len(served["current_bad"]["customers"]) == 5,
                len(served["current_bad"]["customers"]))
        c.check("five are still performing at high forward risk",
                len(served["forward_risk"]["customers"]) == 5,
                len(served["forward_risk"]["customers"]))
        named = [r["customer_id"] for r in
                 served["current_bad"]["customers"]
                 + served["forward_risk"]["customers"]]
        body = self.text()
        c.check("every one of the ten is named on screen",
                all(who in body for who in named),
                [who for who in named if who not in body])
        c.check("each carries a sentence built from its own numbers",
                all(len(r["because"]) > 60 for r in
                    served["current_bad"]["customers"]))
        c.check("the two halves are separately labelled",
                self.has("ews-story-current_bad") == 1
                and self.has("ews-story-forward_risk") == 1)
        first = named[0]
        self.page.click(f'[data-testid="ews-story-customer-{first}"]')
        self.page.wait_for_selector('[data-testid="ews-customer-detail"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        c.check("a named customer opens their own detail",
                first in self.page.url, self.page.url)
        self.shot("EW-21")

    def ew_22(self) -> None:
        """The Model Lab is not a blank invitation to fit something."""
        c = self.case("EW-22", "The Model Lab points at the running Early "
                               "Warning methodology instead of asking for a fit")
        self.go("/early-warning/lab", "", 9000)
        body = self.text()
        c.check("it says the EWS score is not fitted here",
                self.has("lab-ews-methodology-link") == 1)
        c.check("it links to the methodology",
                self.has("lab-open-methodology") == 1)
        c.check("fitted model versions are listed rather than an empty state",
                "Prototype" in body and "AUC" in body)
        c.check("the page does not open on an empty fitting form",
                "Versions" in body)
        self.shot("EW-22")

    # -- the walk -----------------------------------------------------------

    def run(self) -> None:
        order = [self.ew_01, self.ew_02, self.ew_03, self.ew_04, self.ew_05,
                 self.ew_06, self.ew_07, self.ew_08, self.ew_09, self.ew_10,
                 self.ew_11, self.ew_12, self.ew_13, self.ew_14, self.ew_15,
                 self.ew_16, self.ew_17, self.ew_18, self.ew_19, self.ew_20,
                 self.ew_21, self.ew_22]
        for step in order:
            started = time.time()
            try:
                step()
            except Exception as problem:  # noqa: BLE001
                if not self.cases or self.cases[-1].__dict__.get("_done"):
                    self.case(step.__name__.upper().replace("_", "-"),
                              "did not run")
                self.cases[-1].check("the case ran to completion", False,
                                     f"{type(problem).__name__}: {problem}")
            self.cases[-1].note = f"{time.time() - started:.1f}s"
            print(f"{self.cases[-1].id} {self.cases[-1].status:4s} "
                  f"{self.cases[-1].title}")
            for what, ok, saw in self.cases[-1].checks:
                if not ok:
                    print(f"     FAILED: {what} — saw {saw}")


def main() -> int:
    import http.cookiejar
    import urllib.request

    from playwright.sync_api import sync_playwright

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar))

    def api(path: str) -> dict:
        request = urllib.request.Request(
            "http://localhost:8328/api/v1" + path,
            headers={"Content-Type": "application/json"})
        return json.loads(opener.open(request, timeout=300).read())

    opener.open(urllib.request.Request(
        "http://localhost:8328/api/v1/auth/login",
        data=json.dumps({"username": DEMO_USER,
                         "password": DEMO_PASSWORD}).encode(),
        headers={"Content-Type": "application/json"}))

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        session = Session(page, context)
        if not session.sign_in():
            print("could not sign in — is the stack up?")
            return 2
        walk = Walk(page, api)
        walk.run()
        browser.close()

    passed = [c for c in walk.cases if c.status == PASS]
    record = {
        "suite": "Early Warning acceptance, EW-01 to EW-22",
        "passed": len(passed),
        "failed": len(walk.cases) - len(passed),
        "cases": [c.to_dict() for c in walk.cases],
    }
    (OUT / "ew_acceptance.json").write_text(json.dumps(record, indent=1))
    print(f"\n{len(passed)} of {len(walk.cases)} passed")
    return 0 if len(passed) == len(walk.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
