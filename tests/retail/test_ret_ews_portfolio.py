"""
Early Warning as a management portfolio: the arithmetic, and the five defects
that had to be found in a browser before they could be fixed here.

What the screen was
-------------------
`/early-warning` answered one question — which alerts fired? — as a flat list
of five hundred cards under a headline that read **ALERTS 500** while the rule
chips beneath it added up to **5,952**. Five hundred was the page size. There
was no portfolio, no product, no subsegment, no customer list, no methodology,
and no way to tell a customer who is already thirty days down from one who is
still paying and about to stop.

The five defects this file holds the line on
--------------------------------------------
Each was visible on a real screen before it was a failing test here.

1.  **1,934 alerts vanished.** `evaluate_snapshot` returns no product code for
    a CUSTOMER-scope alert, because it is about the customer rather than one
    facility — salary interruption, affordability, bureau. Merged on
    (customer, product) they were dropped: the whole affordability and bureau
    story disappeared from the portfolio while still showing on the alert
    list.

2.  **Every product reported the whole book's alerts.** The fix for (1) fans
    a customer-scope alert out to each product the customer holds, so summing
    the per-row counts double-counts. Patching it with the month's total made
    the portfolio right and made every product report 5,952 alerts.

3.  **Sixteen already-bad customers could not be opened.** The headline
    counted 391 customers already bad; the list showed 375, because it filtered
    to customers with an EWS signal first. Being thirty days down is not a
    prediction that needs a signal to support it.

4.  **A customer was banded twice, two ways.** The detail page scored one
    customer with the POPULATION band table, so a customer at 53 read CRITICAL
    on their own page and HIGH in the list they were opened from.

5.  **A clean mortgage hid a bad card.** The detail's score was the
    exposure-weighted mean across a customer's products, so RC-0000134 scored
    52.5 on a card eighty-six days down and 19.4 on their own page.

Every figure here is SYNTHETIC demonstration data. No threshold or band below
is an ANB policy or a SAMA requirement.
"""

from __future__ import annotations

import pytest

from backend.retail import ews as rules_mod
from backend.retail import ews_layers as layers_mod
from backend.retail import ews_portfolio as portfolio_mod
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")


@pytest.fixture(scope="module")
def months() -> list[str]:
    found = portfolio_mod._panel_months()
    if not found:
        pytest.skip("the early-warning panel has not been built")
    return found


@pytest.fixture(scope="module")
def latest(months: list[str]) -> str:
    return months[-1]


# ---------------------------------------------------------------- the layers

def test_every_rulebook_family_rolls_up_into_a_layer() -> None:
    """A family nobody mapped is a family invisible on the portfolio."""
    assert layers_mod.check() == []


def test_the_scored_layers_weigh_exactly_one() -> None:
    total = sum(layer.weight for layer in layers_mod.scored())
    assert round(total, 6) == 1.0


def test_the_sixth_layer_is_declared_empty_rather_than_omitted() -> None:
    """Cycle sensitivity carries no rule in this rulebook, and says so."""
    empty = [layer for layer in layers_mod.LAYERS if not layer.has_rules]
    assert empty, "the methodology claims six layers and five have rules"
    for layer in empty:
        assert layer.weight == 0.0
        assert layer.absent_because, f"{layer.name} is empty and unexplained"


def test_a_population_and_a_customer_do_not_share_a_band_table() -> None:
    """A product at 60 would mean its average warned customer is critical.

    The four products on this book run between 9 and 19. Against the customer
    bands all four read LOW for ever and the severity badge says nothing at
    all, which is why there are two tables.
    """
    assert layers_mod.BANDS != layers_mod.POPULATION_BANDS
    assert layers_mod.band_of(25.0) == "MEDIUM"
    assert layers_mod.population_band_of(25.0) == "HIGH"


# ------------------------------------------------------- the variable dictionary

def test_every_rule_input_is_documented() -> None:
    """§9 asks for ten facts per input, and a rule may not add an undocumented
    one without this failing."""
    documented = {entry["name"] for entry in layers_mod.variables()}
    used = {name for rule in rules_mod.RULES for name in rule.features}
    assert used - documented == set()


def test_each_documented_input_states_all_ten_facts() -> None:
    for entry in layers_mod.variables():
        where = entry["name"]
        assert entry["label"], f"{where} has no business name"
        assert entry["meaning"], f"{where} has no business meaning"
        assert entry["source_class"] in ("Internal", "External", "Derived"), where
        assert entry["raw_input"], f"{where} does not name its raw input"
        assert entry["transformation"] != "Not documented.", where
        assert entry["direction"] != "Not documented.", where
        assert entry["refresh"], f"{where} has no refresh frequency"
        assert entry["products"] or not entry["layers"], where
        assert entry["reason_codes"], f"{where} generates no reason code"


def test_the_bureau_inputs_are_never_called_a_live_feed() -> None:
    bureau = [entry for entry in layers_mod.variables()
              if entry["source_class"] == "External"]
    assert bureau, "no external input is declared, which cannot be right"
    for entry in bureau:
        said = entry["transformation"].upper()
        assert "SYNTHETIC" in said or "PROXY" in said, entry["name"]


def test_no_meaning_is_invented_for_unsourced_shorthand() -> None:
    """T, A and C appear nowhere in the rulebook, taxonomy, schema or signal."""
    assert layers_mod.UNSOURCED_SHORTHAND == ("T", "A", "C")
    said = layers_mod.NO_SUCH_SHORTHAND
    assert "T, A and C" in said
    assert "written out in full" in said


# ------------------------------------------------------------- the arithmetic

def test_the_portfolio_alert_count_is_the_rulebooks_own(latest: str) -> None:
    """Defect 1 and 2. The panel must agree with a fresh evaluation."""
    frame = portfolio_mod._read(latest)
    months = portfolio_mod._months()
    at = months.index(latest)
    previous = portfolio_mod._read(months[at - 1]) if at > 0 else None
    raised = len(rules_mod.evaluate_snapshot(
        rules_mod.with_prior_month(frame, previous)))

    served = portfolio_mod.portfolio(latest)
    assert served["headline"]["alerts"] == raised


def test_no_product_claims_the_whole_books_alerts(latest: str) -> None:
    """Defect 2. Each product's count is its own."""
    served = portfolio_mod.portfolio(latest)
    whole = served["headline"]["alerts"]
    counts = {p["product_code"]: p["alerts"] for p in served["products"]}
    assert counts, "the book publishes no products"
    for code, count in counts.items():
        assert count < whole, f"{code} reports the whole book's alerts"
    # A customer-scope alert bears on every product its customer holds, so the
    # parts legitimately exceed the whole. They must not fall short of it.
    assert sum(counts.values()) >= whole


def test_a_customer_scope_alert_reaches_the_portfolio(latest: str) -> None:
    """Defect 1. Affordability and bureau are customer-scope families."""
    served = portfolio_mod.portfolio(latest)
    layers = served["headline"].get("layers") or served.get("layers") or {}
    if not layers:
        layers = {key: sum(p["layers"].get(key, 0.0)
                           for p in served["products"])
                  for key in portfolio_mod.SCORED}
    for key in ("affordability", "bureau"):
        assert layers.get(key, 0.0) > 0.0, (
            f"the {key} layer scores zero across the whole book, which means "
            "its customer-scope alerts were dropped again")


def test_the_already_bad_cohort_holds_everyone_the_headline_counts(
        latest: str) -> None:
    """Defect 3. Sixteen customers were counted and could not be opened."""
    served = portfolio_mod.portfolio(latest)
    listed = portfolio_mod.customers(latest, cohort="current_bad", limit=1)
    chips = {c["key"]: c["customers"] for c in listed["cohorts"]}
    assert chips["current_bad"] == served["headline"]["current_bad"]
    assert listed["total_customers"] == served["headline"]["current_bad"]


def test_the_forward_risk_cohort_holds_everyone_the_headline_counts(
        latest: str) -> None:
    served = portfolio_mod.portfolio(latest)
    listed = portfolio_mod.customers(latest, cohort="forward_risk", limit=1)
    chips = {c["key"]: c["customers"] for c in listed["cohorts"]}
    assert chips["forward_risk"] == served["headline"]["forward_risk"]


def test_already_bad_and_forward_risk_never_overlap(latest: str) -> None:
    """They are the two halves of one story and a customer is in one of them."""
    bad = portfolio_mod.customers(latest, cohort="current_bad", limit=2000)
    forward = portfolio_mod.customers(latest, cohort="forward_risk", limit=2000)
    in_bad = {row["customer_id"] for row in bad["customers"]}
    in_forward = {row["customer_id"] for row in forward["customers"]}
    assert in_bad & in_forward == set()


def test_the_list_and_the_detail_band_a_customer_the_same_way(
        latest: str) -> None:
    """Defects 4 and 5, together: same number, same ruler, both screens."""
    listed = portfolio_mod.customers(latest, cohort="high", limit=8)
    rows = listed["customers"]
    if not rows:
        pytest.skip("no customer is in the HIGH band at this month")
    for row in rows:
        detail = portfolio_mod.customer(row["customer_id"], latest)
        assert detail["available"], row["customer_id"]
        assert detail["ews_score"] == pytest.approx(row["ews_score"], abs=0.01), (
            f"{row['customer_id']}: the list says {row['ews_score']} and the "
            f"detail says {detail['ews_score']}")
        assert detail["severity"] == row["severity"], row["customer_id"]


def test_a_customers_score_is_their_worst_product_not_an_average(
        latest: str) -> None:
    """Defect 5. A large clean mortgage must not dilute a delinquent card."""
    listed = portfolio_mod.customers(latest, cohort="high", limit=40)
    multi = [row for row in listed["customers"]]
    if not multi:
        pytest.skip("no HIGH customer at this month")
    for row in multi[:10]:
        detail = portfolio_mod.customer(row["customer_id"], latest)
        assert detail["ews_score"] >= row["ews_score"] - 0.01


def test_a_customers_severity_uses_the_customer_band_table(
        latest: str) -> None:
    """Defect 4, stated directly rather than by comparison."""
    listed = portfolio_mod.customers(latest, cohort="high", limit=5)
    if not listed["customers"]:
        pytest.skip("no HIGH customer at this month")
    who = listed["customers"][0]["customer_id"]
    detail = portfolio_mod.customer(who, latest)
    assert detail["severity"] == layers_mod.band_of(detail["ews_score"])
    for point in detail["history"]:
        assert point["severity"] == layers_mod.band_of(point["ews_score"])


def test_warned_customers_are_counted_as_people_not_as_alerts(
        latest: str) -> None:
    head = portfolio_mod.portfolio(latest)["headline"]
    assert head["customers_warned"] <= head["customers"]
    assert head["alerts"] > head["customers_warned"], (
        "an alert count equal to a customer count means one of them is the "
        "other wearing the wrong label")


def test_the_severity_counts_add_up_to_the_warned_customers(
        latest: str) -> None:
    head = portfolio_mod.portfolio(latest)["headline"]
    assert sum(head["severity"].values()) == head["customers_warned"]


# --------------------------------------------------------------- the walk down

def test_a_product_offers_dimensions_that_belong_to_it(latest: str) -> None:
    card = portfolio_mod.subsegments("CREDIT_CARD", latest)
    loan = portfolio_mod.subsegments("HOME_LOAN", latest)
    card_cuts = {d["column"] for d in card["dimensions"]}
    loan_cuts = {d["column"] for d in loan["dimensions"]}
    assert card_cuts != loan_cuts, (
        "every product is being cut the same way, which means the dimensions "
        "are not product-specific")
    assert card_cuts - loan_cuts, "the card offers no cut of its own"


def test_a_subsegment_sums_back_to_its_product(latest: str) -> None:
    """A level that does not reconcile with the one above it is a level
    nobody can defend in a meeting."""
    served = portfolio_mod.subsegments("CREDIT_CARD", latest)
    cuts = served["subsegments"]
    if not cuts:
        pytest.skip("the card book has no subsegments at this month")
    product = next(p for p in portfolio_mod.portfolio(latest)["products"]
                   if p["product_code"] == "CREDIT_CARD")
    assert sum(c["customers"] for c in cuts) == product["customers"]


def test_every_customer_row_accounts_for_its_behavioural_score(
        latest: str) -> None:
    """§6: shown on every row, and where there is none, WHY there is none.

    On 926 of the 17,818 customer-products at 2026-08 there is no behavioural
    score: the scorecard needs repayment history and the facility was opened
    this month or last. That is a fact about the facility, and a dash does not
    carry it. A number invented to fill the column would be worse than both.
    """
    listed = portfolio_mod.customers(latest, cohort="all", limit=200)
    rows = listed["customers"]
    assert rows, "no customer carries a signal at this month"
    scored = [r for r in rows if r["behavioural_score"] is not None]
    assert scored, "no customer has a behavioural score at all"
    for row in rows:
        if row["behavioural_score"] is None:
            assert row["behavioural_score_absent_because"], row["customer_id"]
            # And the application score is what stands in its place.
            assert "application score" in (
                row["behavioural_score_absent_because"].lower())
        else:
            assert not row["behavioural_score_absent_because"], row["customer_id"]


def test_every_warned_customer_row_names_its_reason_codes(latest: str) -> None:
    listed = portfolio_mod.customers(latest, cohort="all", limit=100)
    for row in listed["customers"]:
        assert row["top_rules"], row["customer_id"]
        assert len(row["top_rules"]) <= 3, row["customer_id"]
        assert row["primary_layer"], row["customer_id"]


def test_a_customers_history_runs_to_the_panels_window(latest: str) -> None:
    listed = portfolio_mod.customers(latest, cohort="all", limit=40)
    spans = [len(portfolio_mod.customer(r["customer_id"], latest)["history"])
             for r in listed["customers"][:20]]
    assert spans, "no customer to read"
    assert max(spans) == len(portfolio_mod._panel_months()[-25:])
    for span in spans:
        assert 1 <= span <= 25


# -------------------------------------------------------------- the commentary

def test_the_commentary_is_generated_from_computed_movements(
        latest: str) -> None:
    """§4: not hard-coded prose. Every product's sentence quotes its own
    score, and no two products say the same thing."""
    served = portfolio_mod.portfolio(latest)
    said = {p["product_code"]: p["commentary"] for p in served["products"]}
    assert len(set(said.values())) == len(said)
    for product in served["products"]:
        assert f"{product['ews_score']:.1f}" in product["commentary"], (
            product["product_code"])


# --------------------------------------------------------------- the story

def test_the_product_story_has_five_of_each_half(latest: str) -> None:
    told = portfolio_mod.story(latest)
    assert told["available"]
    assert len(told["current_bad"]["customers"]) == portfolio_mod.STORY_SIZE
    assert len(told["forward_risk"]["customers"]) == portfolio_mod.STORY_SIZE


def test_every_customer_in_the_story_is_in_the_half_it_claims(
        latest: str) -> None:
    told = portfolio_mod.story(latest)
    for row in told["current_bad"]["customers"]:
        assert row["current_bad"] and not row["forward_risk"], row["customer_id"]
    for row in told["forward_risk"]["customers"]:
        assert row["forward_risk"] and not row["current_bad"], row["customer_id"]


def test_the_story_line_is_built_from_the_customers_own_numbers(
        latest: str) -> None:
    told = portfolio_mod.story(latest)
    for row in (told["current_bad"]["customers"]
                + told["forward_risk"]["customers"]):
        said = row["because"]
        assert "SAR" in said, row["customer_id"]
        assert f"{row['behavioural_score']:.0f}" in said, row["customer_id"]
        assert row["primary_layer_name"].lower() in said.lower(), row["customer_id"]


# ------------------------------------------------------------- the methodology

def test_the_methodology_describes_a_model_that_is_running() -> None:
    served = portfolio_mod.methodology()
    for field in ("name", "purpose", "target", "horizon", "eligible_population",
                  "latest_scoring_date", "rulebook_version"):
        assert served[field], field
    assert served["months_scored"] >= 1
    assert len(served["layers"]) == len(layers_mod.LAYERS)
    assert served["variable_count"] == len(layers_mod.variables())


def test_the_methodology_says_which_rules_apply_to_each_product() -> None:
    served = portfolio_mod.methodology()
    counts = {p["product_code"]: p["rule_count"] for p in served["by_product"]}
    assert len(counts) >= 4
    assert len(set(counts.values())) > 1, (
        "every product carries the same rules, so there is nothing "
        "product-specific to show")


def test_the_methodology_classifies_every_source() -> None:
    served = portfolio_mod.methodology()
    assert set(served["source_classes"]) == {"Internal", "External", "Derived"}
    assert "SYNTHETIC PROXY" in served["source_classes"]["External"]
    assert "no live bureau connection" in served["bureau_note"].lower()


def test_data_quality_is_not_a_risk_layer() -> None:
    """A missing input is a statement about the file, not about a customer."""
    served = portfolio_mod.methodology()
    families = {entry["family"] for entry in served["not_a_risk_layer"]}
    assert "DATA_QUALITY" in families
    for family in families:
        assert layers_mod.layer_of(family) == ""
