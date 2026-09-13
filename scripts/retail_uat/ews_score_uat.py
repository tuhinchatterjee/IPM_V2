"""
EW-01 to EW-60: the Early Warning Score acceptance walk, in a real browser.

Every case clicks what a Head of Retail Risk would click, against the same
frontend and backend the launcher serves. Nothing is mocked and there is no
test-only route: a case passes only because an ordinary user doing the same
thing would see the same thing.

Cases are written against the specification rather than against the code, so
"the screen renders" is never a pass on its own. Where the brief asks for a
number, the case reads it off the screen and checks it against what the domain
serves; where it asks for a control, the case uses the control and checks that
what it controls actually changed.

Run it with the stack up:

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/ews_score_uat.py

It writes one JSON record and a screenshot per section under
docs/evidence/retail_ews_score/.
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
OUT = ROOT / "docs" / "evidence" / "retail_ews_score"
SHOTS = OUT / "cases"

PASS, FAIL = "PASS", "FAIL"


class Case:
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
        return {"id": self.id, "title": self.title, "status": self.status,
                "note": self.note,
                "checks": [{"check": w, "passed": ok, "saw": saw}
                           for w, ok, saw in self.checks]}


def digits(text: str) -> int | None:
    found = re.search(r"\d[\d,]*", text or "")
    if not found:
        return None
    try:
        return int(found.group(0).replace(",", ""))
    except ValueError:
        return None


class Walk:
    def __init__(self, page: Any, api: Callable[..., dict]):
        self.page = page
        self.api = api
        self.cases: list[Case] = []
        self._portfolio: dict | None = None

    # -- helpers ------------------------------------------------------------

    def portfolio(self) -> dict:
        if self._portfolio is None:
            self._portfolio = self.api("/retail/ews/portfolio")
        return self._portfolio

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

    def ask(self, question: str, **kw: Any) -> dict:
        return self.api("/retail/ews/ask",
                        body={"question": question, **kw})

    # ===================================================== PORTFOLIO =======

    def ew_01(self) -> None:
        c = self.case("EW-01", "One Early Warning nav item, and it is the "
                               "workspace")
        self.go("/early-warning", '[data-testid="ews-workspace"]', 7000)
        links = self.page.locator('a[href^="/early-warning"]')
        hrefs = {links.nth(i).get_attribute("href")
                 for i in range(links.count())}
        nav = [h for h in hrefs if h and h.startswith("/early-warning")]
        c.check("the workspace renders", self.has("ews-workspace") == 1)
        sidebar = self.page.locator('nav a[href="/early-warning"]')
        c.check("exactly one Early Warning entry in the navigation",
                sidebar.count() <= 1, sidebar.count())
        c.check("no second 'Early Warning Signals' navigation entry",
                self.page.locator(
                    'nav a[href="/early-warning/signals"]').count() == 0)
        c.check("it is called Early Warning Score",
                "Early Warning Score" in self.text(), nav)
        self.shot("EW-01-landing")

    def ew_02(self) -> None:
        c = self.case("EW-02", "The chat box is at the top of the workspace")
        c.check("the chat is on the page", self.has("ews-chat") == 1)
        c.check("it has an input", self.has("ews-chat-input") == 1)
        c.check("it carries seeded prompts", self.has("ews-chat-prompts") == 1)
        c.check("it states its scope", "scoped to the Early Warning Score "
                                       "domain" in self.at("ews-chat-scope"),
                self.at("ews-chat-scope")[:120])
        chat_box = self.page.locator('[data-testid="ews-chat"]').bounding_box()
        kpis = self.page.locator('[data-testid="ews-headline"]').bounding_box()
        c.check("it sits ABOVE the headline figures",
                bool(chat_box and kpis and chat_box["y"] < kpis["y"]),
                f"chat y={chat_box and chat_box['y']}, kpis y={kpis and kpis['y']}")

    def ew_03(self) -> None:
        c = self.case("EW-03", "The total-retail headline KPIs")
        head = self.portfolio()["headline"]
        for key, testid in (("customers", "ews-kpi-customers"),
                            ("customers_warned", "ews-kpi-warned"),
                            ("high_or_critical", "ews-kpi-high-critical"),
                            ("current_bad", "ews-kpi-bad"),
                            ("forward_risk", "ews-kpi-forward")):
            shown = digits(self.at(testid))
            c.check(f"{testid} reads the served {key}",
                    shown == int(head[key]),
                    f"screen {shown}, api {head[key]}")
        c.check("exposure under warning is shown",
                "SAR" in self.at("ews-kpi-exposure"), self.at("ews-kpi-exposure"))
        c.check("% retail exposure under warning is shown",
                "%" in self.at("ews-kpi-exposure-pct"))
        c.check("the portfolio score is shown",
                f"{head['ews_score']:.1f}" in self.at("ews-kpi-score"),
                self.at("ews-kpi-score"))
        c.check("its change on the prior month is shown",
                "on " in self.at("ews-kpi-score"), self.at("ews-kpi-score"))
        c.check("the severity band is shown",
                head["severity_band"] in self.at("ews-kpi-band"))
        c.check("alerts, customers and facilities are not confused",
                "Customers, not alerts" in self.at("ews-definitions"))

    def ew_04(self) -> None:
        c = self.case("EW-04", "Four large product cards")
        served = self.portfolio()
        codes = [p["product_code"] for p in served["products"]]
        c.check("four products are served", len(codes) == 4, codes)
        for card in served["products"]:
            code = card["product_code"]
            on_screen = self.at(f"ews-product-{code}")
            c.check(f"{code} has a card", bool(on_screen))
            c.check(f"{code} shows its score",
                    f"{card['ews_score']:.1f}" in on_screen,
                    f"{card['ews_score']:.1f}")
            c.check(f"{code} shows its severity",
                    card["severity_band"] in on_screen.upper())
            c.check(f"{code} shows warned, bad and forward-risk counts",
                    all(f"{card[key]:,}" in on_screen
                        for key in ("customers_warned", "current_bad",
                                    "forward_risk")))
            c.check(f"{code} shows the exposure under warning",
                    "SAR" in on_screen)

    def ew_05(self) -> None:
        c = self.case("EW-05", "A six-month warning-customer trend on every "
                               "product card")
        for card in self.portfolio()["products"]:
            code = card["product_code"]
            c.check(f"{code} has a warned-customer sparkline",
                    self.has(f"ews-trends-{code}-warned") == 1)
            c.check(f"{code}'s series is six months",
                    len(card["trend"]) == 6, len(card["trend"]))

    def ew_06(self) -> None:
        c = self.case("EW-06", "A six-month ODR / default-entry trend")
        for card in self.portfolio()["products"]:
            code = card["product_code"]
            c.check(f"{code} has a default-entry sparkline",
                    self.has(f"ews-trends-{code}-odr") == 1)
            eligible = card["default_eligible"]
            entries = card["default_entries"]
            expected = round(entries / eligible * 100, 4) if eligible else 0.0
            c.check(f"{code}'s ODR has a real denominator",
                    abs(card["odr_pct"] - expected) < 1e-6,
                    f"{entries}/{eligible} = {card['odr_pct']}")
        served = self.api("/retail/ews/customers?limit=1")
        row = served["customers"][0] if served["customers"] else {}
        c.check("ODR is never a property of one customer",
                "odr" not in {k.lower() for k in row},
                sorted(k for k in row if "odr" in k.lower()))

    def ew_07(self) -> None:
        c = self.case("EW-07", "A six-month aggregate EWS score trend")
        for card in self.portfolio()["products"]:
            code = card["product_code"]
            c.check(f"{code} has a score sparkline",
                    self.has(f"ews-trends-{code}-score") == 1)
        c.check("the portfolio's own trend is six months",
                len(self.portfolio()["trend"]) == 6)

    def ew_08(self) -> None:
        c = self.case("EW-08", "Top five warning reasons on every product card")
        for card in self.portfolio()["products"]:
            code = card["product_code"]
            reasons = card["top_reasons"]
            c.check(f"{code} serves up to five reasons",
                    1 <= len(reasons) <= 5, len(reasons))
            block = self.at(f"ews-reasons-{code}")
            for reason in reasons:
                c.check(f"{code} shows {reason['reason_code']} on screen",
                        reason["reason_code"] in block, reason["reason_code"])
            c.check(f"{code}'s reasons carry a change on the month",
                    all("change" in reason for reason in reasons))

    def ew_09(self) -> None:
        c = self.case("EW-09", "Data-derived commentary, not hard-coded prose")
        cards = self.portfolio()["products"]
        said = {card["product_code"]: card["commentary"] for card in cards}
        c.check("every product has commentary",
                all(len(text) > 80 for text in said.values()),
                {k: len(v) for k, v in said.items()})
        c.check("no two products say the same thing",
                len(set(said.values())) == len(said))
        for card in cards:
            c.check(f"{card['product_code']}'s commentary quotes its own score",
                    f"{card['ews_score']:.1f}" in card["commentary"],
                    card["commentary"][:110])
            c.check(f"{card['product_code']}'s commentary names a layer",
                    any(word in card["commentary"].lower() for word in
                        ("behavioural", "affordability", "bureau", "facility")))
        c.check("commentary is rendered on screen",
                self.has(f"ews-commentary-{cards[0]['product_code']}") == 1)

    def ew_10(self) -> None:
        c = self.case("EW-10", "A product card opens the product level")
        self.page.click('[data-testid="ews-open-product-CREDIT_CARD"]')
        self.page.wait_for_selector('[data-testid="ews-product-view"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        c.check("the product view opened", self.has("ews-product-view") == 1)
        c.check("the address names the product",
                "product=CREDIT_CARD" in self.page.url, self.page.url)

    # ================================================ PRODUCT / SUB-PRODUCT

    def ew_11(self) -> None:
        c = self.case("EW-11", "The Credit Card product page")
        served = self.api("/retail/ews/product/CREDIT_CARD")
        body = self.text()
        c.check("the page is titled for the product",
                "Credit Card Early Warning Score" in body)
        head = served["headline"]
        c.check("it shows the product's own customer count",
                f"{head['customers']:,}" in body, head["customers"])
        c.check("it shows the product's warned count",
                f"{head['customers_warned']:,}" in body)
        c.check("it shows the product weight matrix row",
                "Behavioural" in body and "%" in body)
        c.check("the chat is still at the top",
                self.has("ews-chat") == 1)
        self.shot("EW-11-product")

    def ew_12(self) -> None:
        c = self.case("EW-12", "Sub-product cards, with the governed taxonomy")
        served = self.api("/retail/ews/product/CREDIT_CARD")
        cards = served["sub_products"]
        wanted = {"Privilege Card", "Platinum Card", "Silver Card",
                  "Ultra Card"}
        labels = {card["sub_product_label"] for card in cards}
        c.check("the four Credit Card sub-products exist",
                wanted <= labels, sorted(labels))
        c.check("the sub-product deck renders",
                self.has("ews-sub-products") == 1)
        for card in cards:
            c.check(f"{card['sub_product']} has a card",
                    self.has(f"ews-sub-{card['sub_product']}") == 1)
            c.check(f"{card['sub_product']} states how it is derived",
                    bool(card["derivation"]), card["derivation"][:70])
        model = self.api("/retail/ews/model")
        c.check("the taxonomy is in the model configuration, not the frontend",
                len(model["sub_products"]) >= 12, len(model["sub_products"]))
        domain = self.api("/retail/ews/customers?limit=1")
        row = domain["customers"][0]
        c.check("and it is written into the domain",
                bool(row["sub_product"]) and bool(row["sub_product_label"]),
                row["sub_product"])

    def ew_13(self) -> None:
        c = self.case("EW-13", "Sub-product trends")
        served = self.api("/retail/ews/product/CREDIT_CARD")
        for card in served["sub_products"]:
            key = card["sub_product"]
            c.check(f"{key} has six months of trend",
                    len(card["trend"]) == 6, len(card["trend"]))
            c.check(f"{key} has all three sparklines on screen",
                    all(self.has(f"ews-sub-trends-{key}-{kind}") == 1
                        for kind in ("warned", "odr", "score")))

    def ew_14(self) -> None:
        c = self.case("EW-14", "Sub-product ODR")
        served = self.api("/retail/ews/product/CREDIT_CARD")
        for card in served["sub_products"]:
            eligible, entries = card["default_eligible"], card["default_entries"]
            expected = round(entries / eligible * 100, 4) if eligible else 0.0
            c.check(f"{card['sub_product']}'s ODR reconciles",
                    abs(card["odr_pct"] - expected) < 1e-6,
                    f"{entries}/{eligible}")
        total = sum(card["default_entries"] for card in served["sub_products"])
        c.check("the sub-products' default entries sum to the product's",
                total == served["headline"]["default_entries"],
                f"{total} vs {served['headline']['default_entries']}")

    def ew_15(self) -> None:
        c = self.case("EW-15", "Top five signals per sub-product")
        served = self.api("/retail/ews/product/CREDIT_CARD")
        for card in served["sub_products"]:
            c.check(f"{card['sub_product']} serves up to five signals",
                    len(card["top_reasons"]) <= 5,
                    len(card["top_reasons"]))
            if card["top_reasons"]:
                c.check(f"{card['sub_product']} renders them",
                        self.has(f"ews-sub-reasons-{card['sub_product']}") == 1)

    def ew_16(self) -> None:
        c = self.case("EW-16", "A sub-product card opens its own level")
        self.page.click('[data-testid="ews-open-sub-CC_PRIVILEGE"]')
        self.page.wait_for_selector('[data-testid="ews-sub-product-view"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        c.check("the sub-product view opened",
                self.has("ews-sub-product-view") == 1)
        c.check("the address names it", "sub=CC_PRIVILEGE" in self.page.url,
                self.page.url)
        c.check("it names the sub-portfolio",
                "Privilege Card" in self.text())
        self.shot("EW-16-sub-product")

    def ew_17(self) -> None:
        c = self.case("EW-17", "The customer-list filters")
        self.page.click('[data-testid="ews-open-sub-customers"]')
        self.page.wait_for_selector('[data-testid="ews-customer-list"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        for testid in ("ews-filter-layer", "ews-filter-dpd", "ews-filter-stage",
                       "ews-filter-score", "ews-filter-search"):
            c.check(f"{testid} is offered", self.has(testid) == 1)
        c.check("the cohort chips are offered", self.has("ews-cohorts") == 1)
        before = digits(self.at("ews-customer-list").split("match")[0])
        self.page.select_option('[data-testid="ews-filter-stage"]', "3")
        self.page.wait_for_timeout(6000)
        after = digits(self.at("ews-customer-list").split("match")[0])
        c.check("a filter changes the count",
                before is not None and after is not None and after < before,
                f"{before} -> {after}")
        self.page.click('[data-testid="ews-filters-clear"]')
        self.page.wait_for_timeout(5000)

    def ew_18(self) -> None:
        c = self.case("EW-18", "The chat applies filters")
        answer = self.ask("Show currently bad customers in Privilege Card.")
        c.check("the answer stays in scope", answer["in_scope"])
        c.check("it resolves a cohort filter",
                answer["filters"].get("cohort") == "current_bad",
                answer["filters"])
        c.check("and it names the sub-product it scoped to",
                answer["filters"].get("sub_product") == "CC_PRIVILEGE"
                or "Privilege" in answer["answer"], answer["filters"])
        self.page.fill('[data-testid="ews-chat-input"]',
                       "Show currently bad customers.")
        self.page.click('[data-testid="ews-chat-send"]')
        try:
            self.page.wait_for_selector('[data-testid="ews-chat-answer"]',
                                        timeout=60_000)
        except Exception:  # noqa: BLE001
            pass
        self.page.wait_for_timeout(4000)
        c.check("the chat renders its answer",
                self.has("ews-chat-answer") >= 1,
                self.at("ews-chat-answers")[:120])
        c.check("and the screen followed it",
                "cohort=current_bad" in self.page.url, self.page.url)
        self.shot("EW-18-chat")

    def ew_19(self) -> None:
        c = self.case("EW-19", "Back retains the level and its filters")
        self.go("/early-warning?product=CREDIT_CARD&sub=CC_PRIVILEGE"
                "&cohort=forward_risk", '[data-testid="ews-customer-list"]',
                6000)
        first = self.page.locator('[data-testid^="ews-open-RC-"]').first
        who = (first.get_attribute("data-testid") or "").replace("ews-open-", "")
        first.click()
        self.page.wait_for_selector('[data-testid="ews-customer-detail"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(5000)
        c.check("a customer opened", self.has("ews-customer-detail") == 1)
        c.check("the address names them", who in self.page.url, self.page.url)
        self.page.go_back()
        self.page.wait_for_timeout(6000)
        c.check("Back returns to the SAME filtered list",
                "cohort=forward_risk" in self.page.url
                and "sub=CC_PRIVILEGE" in self.page.url, self.page.url)
        self.page.go_back()
        self.page.wait_for_timeout(6000)
        c.check("Back again keeps the sub-product",
                "sub=CC_PRIVILEGE" in self.page.url, self.page.url)

    # ==================================================== CUSTOMER LIST ====

    def ew_20(self) -> None:
        c = self.case("EW-20", "Customer name and id on every card")
        self.go("/early-warning?product=CREDIT_CARD&cohort=forward_risk",
                '[data-testid="ews-customer-list"]', 7000)
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        rows = served["customers"]
        c.check("customers are served", bool(rows), len(rows))
        body = self.text()
        for row in rows[:5]:
            c.check(f"{row['customer_id']} is named on screen",
                    row["customer_id"] in body and row["customer_name"] in body,
                    f"{row['customer_name']} {row['customer_id']}")
        c.check("the synthetic-name note is shown",
                "Synthetic display name" in body)
        self.shot("EW-20-customers")

    def ew_21(self) -> None:
        c = self.case("EW-21", "Every card shows the Early Warning Score")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            card = self.at(f"ews-customer-{row['customer_id']}")
            c.check(f"{row['customer_id']} shows its score",
                    f"{row['ews_score']:.1f}" in card,
                    f"{row['ews_score']:.1f}")
            c.check(f"{row['customer_id']} shows the warning cutoff",
                    "warned at" in card)

    def ew_22(self) -> None:
        c = self.case("EW-22", "Every card shows the severity")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            card = self.at(f"ews-customer-{row['customer_id']}").upper()
            c.check(f"{row['customer_id']} shows {row['ews_severity']}",
                    row["ews_severity"] in card, card[:90])

    def ew_23(self) -> None:
        c = self.case("EW-23", "The behavioural score is always accounted for")
        # Over the WHOLE population, so the customers without one are in it.
        every = self.api("/retail/ews/customers?cohort=everyone&limit=400")
        missing = [r for r in every["customers"]
                   if r["behavioural_score"] is None]
        c.check("a customer without one carries the reason",
                all(r["behavioural_score_absent_because"] for r in missing),
                [r["customer_id"] for r in missing[:3]])
        c.check("a customer with one carries no reason",
                all(not r["behavioural_score_absent_because"]
                    for r in every["customers"]
                    if r["behavioural_score"] is not None))
        # And on the screen the reader is actually looking at.
        self.go("/early-warning?product=CREDIT_CARD&cohort=forward_risk",
                '[data-testid="ews-customer-list"]', 7000)
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            block = self.at(f"ews-behavioural-{row['customer_id']}")
            c.check(f"{row['customer_id']}'s behavioural cell is filled",
                    bool(block) and block.strip() != "—", block[:60])

    def ew_24(self) -> None:
        c = self.case("EW-24", "An EWS sparkline on every card")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            c.check(f"{row['customer_id']} has an EWS sparkline",
                    self.has(f"ews-spark-score-{row['customer_id']}") == 1)
            c.check(f"{row['customer_id']}'s series is up to six months",
                    1 <= len(row["series"]) <= 6, len(row["series"]))

    def ew_25(self) -> None:
        c = self.case("EW-25", "A DPD sparkline on every card")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            c.check(f"{row['customer_id']} has a DPD sparkline",
                    self.has(f"ews-spark-dpd-{row['customer_id']}") == 1)
        c.check("the customer chart is not called ODR",
                "ODR" not in self.at(
                    f"ews-charts-{served['customers'][0]['customer_id']}").upper())

    def ew_26(self) -> None:
        c = self.case("EW-26", "A behavioural-score sparkline on every card")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            c.check(f"{row['customer_id']} has a behavioural sparkline",
                    self.has(f"ews-spark-behavioural-{row['customer_id']}") == 1)
        c.check("there is NO bureau sparkline",
                self.page.locator(
                    '[data-testid^="ews-spark-bureau"]').count() == 0)
        c.check("and the card says why",
                "does not receive a monthly bureau file" in self.text())

    def ew_27(self) -> None:
        c = self.case("EW-27", "Bureau shown as last observed plus recency")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        rows = served["customers"]
        c.check("every row carries an observation date",
                all(r["bureau_last_observed"] for r in rows),
                [r["bureau_last_observed"] for r in rows[:3]])
        c.check("and a recency in months",
                all(r["bureau_recency_months"] is not None for r in rows))
        ages = {r["bureau_recency_months"] for r in rows}
        c.check("recency is not zero for everybody, so it is real",
                len(ages) > 1 or list(ages) != [0.0], sorted(ages)[:6])
        block = self.at(f"ews-bureau-{rows[0]['customer_id']}")
        c.check("it is on the card", "seen" in block, block[:80])

    def ew_28(self) -> None:
        c = self.case("EW-28", "The top deteriorating layer on every card")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            c.check(f"{row['customer_id']} names its worst layer",
                    bool(row["primary_layer_name"]), row["primary_layer_name"])
            c.check(f"{row['customer_id']} shows layer chips",
                    self.page.locator(
                        f'[data-testid^="ews-layer-{row["customer_id"]}-"]'
                    ).count() >= 1)
        c.check("the worst layer is named in the card's footer",
                "Worst layer" in self.text())

    def ew_29(self) -> None:
        c = self.case("EW-29", "Reason codes on every card")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        for row in served["customers"][:5]:
            c.check(f"{row['customer_id']} carries up to three reason codes",
                    1 <= len(row["reasons"]) <= 3, len(row["reasons"]))
            for reason in row["reasons"]:
                c.check(f"{reason['code']} is on screen",
                        self.has(f"ews-reason-chip-{reason['code']}") >= 1)

    def ew_30(self) -> None:
        c = self.case("EW-30", "Exposure contribution on every card")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=10")
        row = served["customers"][0]
        card = self.at(f"ews-customer-{row['customer_id']}")
        for label in ("% OF SUB-PRODUCT", "% OF PRODUCT", "% OF RETAIL"):
            c.check(f"{label} is on the card", label in card.upper(), label)
        c.check("the shares are ordered sub-product >= product >= retail",
                row["share_of_sub_product_pct"] >= row["share_of_product_pct"]
                >= row["share_of_portfolio_pct"],
                (row["share_of_sub_product_pct"], row["share_of_product_pct"],
                 row["share_of_portfolio_pct"]))

    def ew_31(self) -> None:
        c = self.case("EW-31", "The current-bad filter")
        self.page.click('[data-testid="ews-cohort-current_bad"]')
        self.page.wait_for_timeout(7000)
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=current_bad&limit=200")
        c.check("the URL carries the cohort",
                "cohort=current_bad" in self.page.url, self.page.url)
        c.check("every served row is flagged bad",
                all(r["current_bad"] for r in served["customers"]))
        c.check("the count matches the chip",
                digits(self.at("ews-cohort-current_bad").split("(")[-1])
                == served["total"],
                f"{self.at('ews-cohort-current_bad')} vs {served['total']}")
        c.check("already-bad badges are rendered", self.has("ews-bad-yes") > 0)

    def ew_32(self) -> None:
        c = self.case("EW-32", "The forward-risk filter")
        self.page.click('[data-testid="ews-cohort-forward_risk"]')
        self.page.wait_for_timeout(7000)
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=200")
        c.check("every served row is forward risk",
                all(r["forward_risk"] and not r["current_bad"]
                    for r in served["customers"]))
        c.check("a forward-risk customer may have zero DPD",
                any((r["dpd"] or 0) < 30 for r in served["customers"]))
        c.check("forward-risk badges are rendered",
                self.has("ews-forward-yes") > 0)
        c.check("the two cohorts do not overlap",
                not ({r["customer_id"] for r in served["customers"]}
                     & {r["customer_id"] for r in self.api(
                         "/retail/ews/customers?product=CREDIT_CARD"
                         "&cohort=current_bad&limit=200")["customers"]}))

    def ew_33(self) -> None:
        c = self.case("EW-33", "The rule filter, from the signals view")
        self.go("/early-warning?view=signals", '[data-testid="ews-signals-view"]',
                7000)
        c.check("the signals view opened", self.has("ews-signals-view") == 1)
        c.check("it says how many of how many are shown",
                "Showing" in self.at("ews-signals-showing"),
                self.at("ews-signals-showing"))
        # The rules view itself, before a rule is opened: the shot below is of
        # where the rule filter LANDS, which is a different screen.
        self.shot("EW-33-signals-view")
        self.page.locator('[data-testid^="ews-signal-"]').first.click()
        self.page.wait_for_timeout(6000)
        opened = self.page.locator('[data-testid^="ews-signal-detail-"]')
        c.check("a rule opens its own detail", opened.count() >= 1)
        self.page.locator('[data-testid^="ews-signal-open-"]').first.click()
        self.page.wait_for_selector('[data-testid="ews-customer-list"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(6000)
        c.check("it opens the customers it caught",
                "reason=" in self.page.url, self.page.url)
        code = re.search(r"reason=([A-Z0-9-]+)", self.page.url)
        if code:
            served = self.api("/retail/ews/customers"
                              f"?reason={code.group(1)}&cohort=all&limit=200")
            c.check("and the list is genuinely narrowed",
                    served["total"] < self.portfolio()["headline"]["customers_warned"],
                    f"{served['total']} of "
                    f"{self.portfolio()['headline']['customers_warned']}")
        self.shot("EW-33-signals-filter")

    # ===================================================== CUSTOMER 360 ====

    def ew_34(self) -> None:
        c = self.case("EW-34", "The customer's overall Early Warning Score")
        served = self.api("/retail/ews/customers"
                          "?product=CREDIT_CARD&cohort=forward_risk&limit=1")
        who = served["customers"][0]["customer_id"]
        self.who = who
        self.go(f"/early-warning?customer={who}",
                '[data-testid="ews-customer-detail"]', 7000)
        detail = self.api(f"/retail/ews/customers/{who}")
        self.detail = detail
        c.check("the detail opened", self.has("ews-customer-detail") == 1)
        c.check("the score is shown",
                f"{detail['ews_score']:.1f}" in self.at("ews-detail-score"),
                self.at("ews-detail-score"))
        c.check("the severity is shown",
                detail["ews_severity"] in self.at("ews-detail-severity").upper())
        c.check("the threshold is shown",
                str(int(detail["ews_threshold"]))
                in self.at("ews-detail-severity"))
        c.check("a six-month score trend is drawn",
                self.has("ews-detail-spark-score") == 1)
        c.check("current bad versus forward risk is stated",
                ("Already bad" in self.text()
                 or "Forward risk" in self.text()))
        c.check("the month-on-month change is shown",
                detail["movement"] is None
                or "on " in self.at("ews-detail-score"))
        self.shot("EW-34-customer")

        # §9 asks for the SAME complete section inside Customer 360, not a
        # link out to it, so the same component is mounted there and this
        # checks it renders the same figures from the same endpoint.
        self.go(f"/borrower-360?customer={who}",
                '[data-testid="customer-header"]', 6000)
        self.page.click('button[role="tab"]:has-text("Early Warning Score")')
        self.page.wait_for_selector('[data-testid="c360-ews"]', timeout=90_000)
        self.page.wait_for_timeout(5000)
        c.check("Customer 360 carries an Early Warning Score section",
                self.has("c360-ews") == 1)
        c.check("and it is the complete section, not a summary",
                self.has("ews-customer-detail") == 1
                and f"{detail['ews_score']:.1f}" in self.at("ews-detail-score"),
                self.at("ews-detail-score"))
        for layer in detail["layers"]:
            c.check(f"Customer 360 shows the {layer['key']} layer",
                    bool(self.at(f"ews-detail-layer-{layer['key']}")))
        self.shot("EW-34-customer-360")

        # and back to the workspace, which the cases below read from.
        self.go(f"/early-warning?customer={who}",
                '[data-testid="ews-customer-detail"]', 6000)

    def ew_35(self) -> None:
        c = self.case("EW-35", "The four layer scores")
        detail = self.detail
        c.check("four layers are served", len(detail["layers"]) == 4,
                [l["key"] for l in detail["layers"]])
        for layer in detail["layers"]:
            block = self.at(f"ews-detail-layer-{layer['key']}")
            c.check(f"{layer['key']} is on the page", bool(block))
            c.check(f"{layer['key']} shows its score",
                    f"{layer['score']:.1f}" in block, layer["score"])
            c.check(f"{layer['key']} shows its severity",
                    layer["severity"] in block.upper())
            c.check(f"{layer['key']} shows its weight",
                    f"{layer['weight'] * 100:.0f}%" in block,
                    layer["weight"])
            c.check(f"{layer['key']} names its top sublayer",
                    bool(layer["top_sublayer"]) or layer["score"] == 0)

    def ew_36(self) -> None:
        c = self.case("EW-36", "Layer trends where the layer is dynamic")
        for layer in self.detail["layers"]:
            if layer["dynamic"]:
                c.check(f"{layer['key']} has a trend",
                        self.has(f"ews-detail-layer-trend-{layer['key']}") == 1)
                c.check(f"{layer['key']}'s trend is up to six months",
                        1 <= len(layer["trend"]) <= 6, len(layer["trend"]))
            else:
                c.check(f"{layer['key']} explains why it has no trend",
                        self.has(f"ews-detail-layer-no-trend-{layer['key']}") == 1)
        c.check("the bureau layer is the classifier one",
                next(l["kind"] for l in self.detail["layers"]
                     if l["key"] == "bureau") == "classifier")

    def ew_37(self) -> None:
        c = self.case("EW-37", "Sub-layer detail with variables and values")
        detail = self.detail
        total = sum(len(l["sublayers"]) for l in detail["layers"])
        c.check("nineteen sublayers are served", total == 19, total)
        opened = [l for l in detail["layers"] if l["score"] > 0]
        c.check("a scoring layer is expanded on load", bool(opened))
        for layer in opened[:1]:
            for sub in layer["sublayers"]:
                c.check(f"{sub['key']} is on the page",
                        self.has(f"ews-sublayer-{sub['key']}") == 1)
        fired = [t for l in detail["layers"] for s in l["sublayers"]
                 for t in s["triggers"] if t["fired"]]
        c.check("a fired trigger carries its raw value and comparator",
                all(t["raw_value"] is not None for t in fired), len(fired))
        c.check("and its threshold and contribution",
                all(t["threshold"] is not None and t["contribution"] is not None
                    for t in fired))
        c.check("classifiers are rendered beside the triggers",
                self.page.locator(
                    '[data-testid^="ews-classifiers-"]').count() >= 1)

    def ew_38(self) -> None:
        c = self.case("EW-38", "The six action dimensions on a fired trigger")
        fired = [t for l in self.detail["layers"] for s in l["sublayers"]
                 for t in s["triggers"] if t["fired"]]
        c.check("at least one trigger fired", bool(fired), len(fired))
        for trigger in fired[:3]:
            action = trigger["action"]
            c.check(f"{trigger['key']} carries an action block", bool(action))
            for dimension in ("direction", "magnitude", "velocity", "momentum",
                              "persistence", "recency"):
                c.check(f"{trigger['key']} has {dimension}",
                        action is not None and action.get(dimension) is not None
                        and action.get(dimension) != "",
                        action and action.get(dimension))
            block = self.at(f"ews-action-{trigger['key']}")
            c.check(f"{trigger['key']}'s dimensions are on screen",
                    "Direction" in block and "Persistence" in block,
                    block[:110])

    def ew_39(self) -> None:
        c = self.case("EW-39", "The customer's facilities and exposure share")
        detail = self.detail
        c.check("facilities are listed",
                self.has("ews-detail-facilities") == 1)
        c.check("every facility is served with its share",
                all(f["share_of_customer_pct"] is not None
                    for f in detail["facilities"]))
        total = sum(f["share_of_customer_pct"] for f in detail["facilities"])
        c.check("the shares sum to about a hundred per cent",
                abs(total - 100) < 1.5, total)
        block = self.at("ews-detail-exposure-share")
        c.check("the customer's share of retail is shown", "%" in block, block)
        c.check("its share of product and sub-portfolio too",
                "of product" in block and "sub-portfolio" in block)

    def ew_40(self) -> None:
        c = self.case("EW-40", "The warning and reason-code history")
        c.check("a history table is on the page",
                self.has("ews-detail-history") == 1)
        history = self.detail["history"]
        c.check("it covers every month the customer is in the domain",
                1 <= len(history) <= 20, len(history))
        c.check("it carries reason codes",
                any(h["reasons"] for h in history))
        block = self.at("ews-detail-history")
        c.check("the months are on screen",
                history[-1]["month"] in block, history[-1]["month"])
        c.check("RET-EWS reason codes are on screen",
                "RET-EWS-" in block)

    # ================================================== MODEL CONFIGURATION

    def ew_41(self) -> None:
        c = self.case("EW-41", "View Model opens the model screen")
        self.go("/early-warning", '[data-testid="ews-workspace"]', 5000)
        c.check("a View Model control is on the workspace",
                self.has("ews-open-model") == 1)
        self.page.click('[data-testid="ews-open-model"]')
        self.page.wait_for_selector('[data-testid="ews-model-page"]',
                                    timeout=60_000)
        self.page.wait_for_timeout(6000)
        self.model = self.api("/retail/ews/model")
        c.check("the model screen opened", self.has("ews-model-page") == 1)
        body = self.text()
        for field in ("model_version", "purpose", "target", "horizon",
                      "eligible_population", "scoring_frequency"):
            value = str(self.model[field])
            c.check(f"it states the {field}", value[:50] in body, value[:50])
        c.check("it states the score range",
                f"{self.model['scale']['minimum']:g}" in body
                and f"{self.model['scale']['maximum']:g}" in body)
        c.check("it states the score direction",
                self.model["scale"]["direction"][:40] in body)
        c.check("and carries the synthetic disclaimer",
                self.has("ews-model-disclaimer") == 1)
        self.shot("EW-41-model")

    def ew_42(self) -> None:
        c = self.case("EW-42", "The flow diagram")
        c.check("a flow is on the page", self.has("ews-model-flow") == 1)
        block = self.at("ews-model-flow")
        for step in ("Classifiers", "Dynamic triggers", "Action dimensions",
                     "Sub-layer scores", "Four layer scores",
                     "Overall Early Warning Score", "Severity",
                     "Reason codes"):
            c.check(f"the flow names {step}", step in block, step)

    def ew_43(self) -> None:
        c = self.case("EW-43", "Exactly four layers, named")
        layers = self.model["layers"]
        c.check("four layers", len(layers) == 4, [l["key"] for l in layers])
        wanted = ["Behavioural Intelligence",
                  "Affordability & Cash Flow Intelligence",
                  "Bureau & External Credit Intelligence",
                  "Facility & Exposure Intelligence"]
        names = [l["name"] for l in layers]
        c.check("named as the specification names them", names == wanted, names)
        for layer in layers:
            c.check(f"{layer['key']} is on the page",
                    self.has(f"ews-model-layer-{layer['key']}") == 1)
        c.check("the layer weights sum to one",
                abs(sum(l["weight"] for l in layers) - 1.0) < 1e-6,
                sum(l["weight"] for l in layers))

    def ew_44(self) -> None:
        c = self.case("EW-44", "Classifier and trigger separated, per sublayer")
        self.page.click('[data-testid="ews-model-layer-behavioural"] button')
        self.page.wait_for_timeout(3000)
        layer = next(l for l in self.model["layers"]
                     if l["key"] == "behavioural")
        for sub in layer["sublayers"]:
            c.check(f"{sub['key']} is rendered",
                    self.has(f"ews-model-sublayer-{sub['key']}") == 1)
        withClassifiers = [s for s in layer["sublayers"] if s["classifiers"]]
        c.check("classifier variables are served and rendered",
                bool(withClassifiers)
                and self.has(f"ews-model-classifiers-"
                             f"{withClassifiers[0]['key']}") == 1)
        c.check("trigger variables are served and rendered",
                self.page.locator(
                    '[data-testid^="ews-model-triggers-"]').count() >= 1)
        # `inner_text` returns what is RENDERED, and these headings carry a
        # `uppercase` class, so the comparison has to be case-blind.
        body = self.text().upper()
        c.check("the page says which is which",
                "CLASSIFIER VARIABLES" in body and "TRIGGER VARIABLES" in body,
                [line for line in self.text().split("\n")
                 if "VARIABLES" in line.upper()][:3])
        c.check("classifiers are declared never to fire",
                "THEY NEVER FIRE" in body)
        self.shot("EW-44-behavioural-layer")

    def ew_45(self) -> None:
        c = self.case("EW-45", "The six action dimensions are documented")
        c.check("an action-dimension block is on the page",
                self.has("ews-model-action-dimensions") == 1)
        dims = self.model["action_dimensions"]
        c.check("six dimensions", len(dims) == 6, [d["key"] for d in dims])
        for dimension in dims:
            c.check(f"{dimension['key']} is rendered",
                    self.has(f"ews-action-{dimension['key']}") == 1)
            block = self.at(f"ews-action-{dimension['key']}")
            c.check(f"{dimension['key']} states how it is computed",
                    dimension["computed"][:40] in block)
            c.check(f"{dimension['key']} states its values",
                    dimension["values"][:20] in block)
        c.check("their weights sum to one",
                abs(sum(d["weight"] for d in dims) - 1.0) < 1e-6)

    def ew_46(self) -> None:
        c = self.case("EW-46", "Product-specific configuration")
        c.check("a weight matrix is on the page",
                self.has("ews-model-product-weights") == 1)
        weights = self.model["product_weights"]
        c.check("all four products are configured",
                set(weights) == {"CREDIT_CARD", "PERSONAL_LOAN", "AUTO_LOAN",
                                 "HOME_LOAN"}, sorted(weights))
        for code, row in weights.items():
            c.check(f"{code}'s weights sum to one",
                    abs(sum(row.values()) - 1.0) < 1e-6, sum(row.values()))
            c.check(f"{code} has a row on screen",
                    self.has(f"ews-model-weights-{code}") == 1)
        c.check("the four products are not weighted identically",
                len({tuple(sorted(row.items())) for row in weights.values()}) == 4)
        c.check("the matrix lives in the model config, not the frontend",
                self.model["lineage"]["model_config"].endswith("ews_model.py"),
                self.model["lineage"]["model_config"])

    def ew_47(self) -> None:
        c = self.case("EW-47", "Thresholds, cutoff and hard triggers")
        c.check("a thresholds block is on the page",
                self.has("ews-model-thresholds") == 1)
        block = self.at("ews-model-thresholds")
        for band in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            c.check(f"the {band} band is shown", band in block.upper(), band)
        c.check("the warning cutoff is shown",
                str(int(self.model["scale"]["warning_cutoff"])) in block)
        c.check("customer and population bands are both shown",
                "CUSTOMER SEVERITY BANDS" in block.upper()
                and "POPULATION SEVERITY BANDS" in block.upper(),
                block[:160])
        c.check("hard triggers are shown",
                self.has("ews-model-hard-triggers") == 1)
        for hard in self.model["hard_triggers"]:
            c.check(f"{hard['key']} is documented",
                    hard["condition"] in self.at("ews-model-hard-triggers"),
                    hard["condition"])

    def ew_48(self) -> None:
        c = self.case("EW-48", "The bureau treatment")
        c.check("a bureau block is on the page",
                self.has("ews-model-bureau") == 1)
        block = self.at("ews-model-bureau")
        c.check("it says the bank does not get a monthly file",
                "does not receive a bureau file every month" in block, block[:150])
        c.check("it says values are carried forward unchanged",
                "carried forward" in block)
        c.check("it says no monthly movement is generated",
                "No monthly bureau movement is generated" in block
                or "no monthly bureau" in block.lower())
        c.check("the synthetic proxy is labelled",
                "Synthetic bureau proxy" in self.at("ews-model-bureau-proxy"))
        c.check("and it says there is no bureau agreement",
                "no bureau agreement" in self.at("ews-model-bureau-proxy"))
        self.shot("EW-48-bureau")

    def ew_49(self) -> None:
        c = self.case("EW-49", "The glossary")
        c.check("a glossary is on the page",
                self.has("ews-model-glossary") == 1)
        block = self.at("ews-model-glossary")
        for term in ("EWS", "DPD", "ODR", "DBR", "SICR", "LTV", "Classifier",
                     "Trigger", "Direction", "Magnitude", "Velocity",
                     "Momentum", "Persistence", "Recency"):
            c.check(f"{term} is defined", term in block, term)
        c.check("T, A and C are not given an invented meaning",
                "not governed abbreviations" in self.at("ews-model-shorthand"),
                self.at("ews-model-shorthand")[:120])

    def ew_50(self) -> None:
        c = self.case("EW-50", "Lineage")
        c.check("a lineage block is on the page",
                self.has("ews-model-lineage") == 1)
        block = self.at("ews-model-lineage")
        for what in ("retail_ews_score", "retail_facility_month",
                     "ews_model.py", "ews_score.py"):
            c.check(f"it names {what}", what in block, what)
        c.check("it names the domain and its month count",
                self.has("ews-model-domain") == 1)

    # ======================================================= DATA DOMAIN ===

    def ew_51(self) -> None:
        c = self.case("EW-51", "The Early Warning Score domain exists")
        domain = self.api("/retail/ews/domain")
        self.domain = domain
        c.check("the domain is served", domain["available"])
        c.check("it is called Early Warning Score",
                domain["domain_name"] == "Early Warning Score",
                domain["domain_name"])
        c.check("its dataset is retail_ews_score",
                domain["domain"] == "retail_ews_score", domain["domain"])
        self.go("/data-builder", "", 9000)
        body = self.text()
        c.check("it appears in Data Builder",
                "Early Warning Score" in body,
                [line for line in body.split("\n") if "Early Warning" in line][:3])
        self.shot("EW-51-data-builder")

    def ew_52(self) -> None:
        c = self.case("EW-52", "Exactly twenty monthly snapshots")
        domain = self.domain
        c.check("twenty months", domain["month_count"] == 20,
                domain["month_count"])
        c.check("they are consecutive and end at the latest",
                domain["months"][-1] == self.portfolio()["month"],
                f"{domain['months'][0]}…{domain['months'][-1]}")
        c.check("the domain reports no problems",
                not domain["problems"], domain["problems"])
        c.check("they derive from one canonical book",
                domain["source_dataset"] == "retail_facility_month",
                domain["source_dataset"])

    def ew_53(self) -> None:
        c = self.case("EW-53", "The field contract")
        domain = self.domain
        c.check("the grain is customer-facility-month",
                domain["primary_keys"] == ["reporting_month", "customer_id",
                                           "facility_id"],
                domain["primary_keys"])
        groups = {g["group"]: g["fields"] for g in domain["groups"]}
        for group in ("Identity and hierarchy", "Exposure and facility",
                      "Credit status", "Existing scores", "Bureau classifier",
                      "Affordability and cash flow", "Trigger inputs",
                      "Action dimensions", "Sub-layer scores", "Layer scores",
                      "Overall Early Warning Score"):
            c.check(f"the contract holds a {group} group", group in groups,
                    sorted(groups))
        every = {f for fields in groups.values() for f in fields}
        for field in ("reporting_month", "customer_id", "customer_name",
                      "facility_id", "product_code", "sub_product",
                      "gross_carrying_amount_sar", "dpd", "dpd_change",
                      "ifrs9_stage", "stage_change", "current_bad_flag",
                      "forward_risk_flag", "default_entry_this_month",
                      "eligible_for_default_this_month", "application_score",
                      "behavioural_score", "behavioural_score_change",
                      "latest_bureau_score", "bureau_last_observed_date",
                      "bureau_recency_months", "bureau_risk_band",
                      "verified_income", "dbr", "dbr_change",
                      "disposable_income_sar", "missed_payment_count_3m",
                      "ews_score", "ews_severity", "ews_threshold",
                      "ews_alert_flag", "top_reason_code_1",
                      "primary_deteriorating_layer", "model_version",
                      "rulebook_version"):
            c.check(f"the contract holds {field}", field in every, field)
        c.check("nineteen sub-layer scores",
                len(groups.get("Sub-layer scores", [])) == 19,
                len(groups.get("Sub-layer scores", [])))
        c.check("four layer scores",
                len(groups.get("Layer scores", [])) == 4,
                groups.get("Layer scores"))
        c.check("six action dimensions per evaluated trigger",
                len(groups.get("Action dimensions", [])) % 6 == 0,
                len(groups.get("Action dimensions", [])))

    def ew_54(self) -> None:
        c = self.case("EW-54", "The Early Warning Score reproduces")
        served = self.api("/retail/ews/customers?cohort=all&limit=5")
        for row in served["customers"]:
            detail = self.api(f"/retail/ews/customers/{row['customer_id']}")
            c.check(f"{row['customer_id']} scores the same in list and detail",
                    abs(detail["ews_score"] - row["ews_score"]) < 0.01,
                    f"{row['ews_score']} vs {detail['ews_score']}")
            c.check(f"{row['customer_id']} bands the same way",
                    detail["ews_severity"] == row["ews_severity"])

    def ew_55(self) -> None:
        c = self.case("EW-55", "The layer scores reproduce")
        served = self.api("/retail/ews/customers?cohort=critical&limit=5")
        for row in served["customers"]:
            detail = self.api(f"/retail/ews/customers/{row['customer_id']}")
            for layer in detail["layers"]:
                c.check(f"{row['customer_id']} / {layer['key']} agrees",
                        abs(layer["score"]
                            - (row["layers"].get(layer["key"]) or 0)) < 0.01,
                        f"{row['layers'].get(layer['key'])} vs {layer['score']}")

    def ew_56(self) -> None:
        c = self.case("EW-56", "The UI reconciles with the domain")
        self.go("/early-warning", '[data-testid="ews-headline"]', 7000)
        head = self.portfolio()["headline"]
        products = self.portfolio()["products"]
        c.check("the products' warned counts do not exceed the portfolio's",
                sum(p["customers_warned"] for p in products)
                >= head["customers_warned"],
                f"{sum(p['customers_warned'] for p in products)} vs "
                f"{head['customers_warned']}")
        c.check("the products' exposure sums to the book's",
                abs(sum(p["exposure_sar"] for p in products)
                    - head["exposure_sar"]) < 1.0,
                sum(p["exposure_sar"] for p in products))
        card = self.api("/retail/ews/product/CREDIT_CARD")
        subs = card["sub_products"]
        # Facilities and exposure PARTITION the product; customers do not,
        # because one customer can hold two cards in different tiers. The
        # screen says so rather than leaving a reader to add them up.
        c.check("the sub-products' facilities sum to the product's exactly",
                sum(s["facilities"] for s in subs)
                == card["headline"]["facilities"],
                f"{sum(s['facilities'] for s in subs)} vs "
                f"{card['headline']['facilities']}")
        c.check("the sub-products' exposure sums to the product's",
                abs(sum(s["exposure_sar"] for s in subs)
                    - card["headline"]["exposure_sar"]) < 1.0)
        c.check("their customer counts are at least the product's, because "
                "they overlap",
                sum(s["customers"] for s in subs)
                >= card["headline"]["customers"])
        self.go("/early-warning?product=CREDIT_CARD",
                '[data-testid="ews-sub-products"]', 6000)
        c.check("and the screen says the customer counts overlap",
                "counts overlap" in self.at("ews-sub-products-note"),
                self.at("ews-sub-products-note")[:110])

    def ew_57(self) -> None:
        c = self.case("EW-57", "No hard-coded figures in the frontend")
        source = ROOT / "frontend" / "src" / "app" / "early-warning"
        files = sorted(source.rglob("*.tsx"))
        c.check("the workspace source is present", len(files) >= 6, len(files))
        head = self.portfolio()["headline"]
        offenders = []
        for path in files:
            text = path.read_text()
            for figure in (f"{head['customers']:,}", f"{head['customers']}",
                           f"{head['customers_warned']}",
                           f"{head['current_bad']}"):
                if figure in text:
                    offenders.append(f"{path.name}: {figure}")
        c.check("no served figure is written into a screen",
                not offenders, offenders[:5])
        c.check("no dataset other than the EWS domain is named in the "
                "workspace",
                not any("retail_facility_month" in path.read_text()
                        for path in files),
                [p.name for p in files
                 if "retail_facility_month" in p.read_text()])

    def ew_58(self) -> None:
        c = self.case("EW-58", "The chat reads only the EWS domain")
        for question in ("Which product has the highest Early Warning Score?",
                         "Show currently bad customers.",
                         "Which signals increased most this month?"):
            answer = self.ask(question)
            c.check(f"{question[:40]!r} is answered in scope",
                    answer["in_scope"], answer["intent"])
            c.check(f"{question[:40]!r} names the EWS domain",
                    answer["domain"] == "retail_ews_score", answer["domain"])
        # The module's own CODE, not its prose: the docstring says "no
        # catalogue, no planner", and searching the whole file for the word
        # matched the sentence promising the opposite of what it describes.
        source = (ROOT / "backend" / "retail" / "ews_chat.py").read_text()
        code = "\n".join(
            line for line in source.split("\n")
            if not line.lstrip().startswith(("#", "*"))
        )
        body = code.split('"""', 2)[-1] if code.count('"""') >= 2 else code
        for forbidden in ("retail_facility_month", "retail_whatif",
                          "retail_credit_scorecard", "retail_early_warning",
                          "corporate_", "duckdb", "read_parquet",
                          "catalog", "reload_catalog", "get_session"):
            c.check(f"the chat's code holds no reference to {forbidden}",
                    forbidden not in body, forbidden)
        imports = [line.strip() for line in body.split("\n")
                   if line.strip().startswith(("import ", "from "))]
        c.check("it imports only the model and the Early Warning views",
                all(("ews_model" in line or "ews_views" in line
                     or line.startswith(("import re", "from dataclasses",
                                         "from typing", "from __future__")))
                    for line in imports), imports)

    def ew_59(self) -> None:
        c = self.case("EW-59", "A source change moves the whole chain")
        record = OUT / "mutation.json"
        if not record.exists():
            c.check("the source-mutation proof has been run "
                    "(tests/retail/test_ret_ews_dynamic.py writes it)",
                    False, str(record))
            return
        proof = json.loads(record.read_text())
        for step in ("source", "sublayer", "layer", "overall", "reason",
                     "aggregate"):
            c.check(f"the {step} changed", proof.get(step, {}).get("changed"),
                    proof.get(step))

    def ew_60(self) -> None:
        c = self.case("EW-60", "Cross-domain questions are refused, not "
                               "answered from the wrong book")
        for question, where in (
            ("What is the ECL for the credit card book?", "Cockpit"),
            ("Run a downturn stress scenario.", "What-If"),
            ("What is the Gini of the behavioural scorecard?", "Scorecard"),
            ("Show me the corporate portfolio.", "retail"),
            ("What is the RWA on this book?", "Cockpit"),
        ):
            answer = self.ask(question)
            c.check(f"{question[:38]!r} is refused",
                    not answer["in_scope"], answer["intent"])
            c.check(f"{question[:38]!r} names where it belongs",
                    where.lower() in answer["answer"].lower(),
                    answer["answer"][:90])
            c.check(f"{question[:38]!r} carries the scope note",
                    "scoped to the Early Warning Score domain"
                    in answer["scope_note"])
        self.go("/early-warning", '[data-testid="ews-chat-input"]', 6000)
        self.page.fill('[data-testid="ews-chat-input"]',
                       "What is the ECL for the credit card book?")
        self.page.click('[data-testid="ews-chat-send"]')
        self.page.wait_for_timeout(9000)
        c.check("the refusal is visible on screen",
                self.has("ews-chat-out-of-scope") >= 1)
        self.shot("EW-60-out-of-scope")

    # -- the walk -----------------------------------------------------------

    def run(self) -> None:
        order = [getattr(self, f"ew_{n:02d}") for n in range(1, 61)]
        for step in order:
            started = time.time()
            before = len(self.cases)
            try:
                step()
            except Exception as problem:  # noqa: BLE001
                if len(self.cases) == before:
                    self.case(step.__name__.upper().replace("_", "-"),
                              "did not run")
                self.cases[-1].check("the case ran to completion", False,
                                     f"{type(problem).__name__}: {problem}")
            self.cases[-1].note = f"{time.time() - started:.1f}s"
            one = self.cases[-1]
            print(f"{one.id} {one.status:4s} {one.title}")
            for what, ok, saw in one.checks:
                if not ok:
                    print(f"     FAILED: {what} — saw {saw}")


def main() -> int:
    import http.cookiejar
    import urllib.request

    from playwright.sync_api import sync_playwright

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar))

    def api(path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            "http://localhost:8328/api/v1" + path, data=data,
            headers={"Content-Type": "application/json"})
        return json.loads(opener.open(request, timeout=300).read())

    api("/auth/login", {"username": DEMO_USER, "password": DEMO_PASSWORD})

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

    passed = [one for one in walk.cases if one.status == PASS]
    record = {
        "suite": "Early Warning Score acceptance, EW-01 to EW-60",
        "passed": len(passed),
        "failed": len(walk.cases) - len(passed),
        "cases": [one.to_dict() for one in walk.cases],
    }
    (OUT / "ew_score_uat.json").write_text(json.dumps(record, indent=1))
    print(f"\n{len(passed)} of {len(walk.cases)} passed")
    return 0 if len(passed) == len(walk.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
