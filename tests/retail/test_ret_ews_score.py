"""
The Retail Early Warning Score: the model, the domain, and the arithmetic.

What this replaces
------------------
The previous implementation carried SIX layers over the rulebook's eleven
families, with no classifier/trigger separation and no action dimensions. The
agreed model has FOUR layers, nineteen sublayers, classifier and trigger
variables kept apart inside each, and six action dimensions computed on every
dynamic trigger. The rulebook's own rules were not discarded: each one that
carries risk survives as a trigger, and `ews_model.check()` fails if one is
dropped.

The defects this file holds the line on
---------------------------------------
Each was visible in a payload or on a screen before it was fixed.

1.  **A serious signal read LOW.** The first roll-up was a weighted mean, so
    one HIGH trigger in delinquency scored 65 x 0.40 = 26 in its layer and
    26 x 0.40 = 10 overall. The top half of a 0-100 scale was unreachable.

2.  **Then five per cent of the book pinned at exactly 100.** The fix for (1)
    — a weighted sum rescaled by the largest weight — overshoots as soon as
    three parts fire, and 126 customers sat at the ceiling with no ordering
    between them. Both are replaced by `_combine`, which is monotone and
    bounded.

3.  **One critical trigger reached the ceiling on its own.** With CRITICAL
    worth 100 points, a lone early-life payment failure carried a customer to
    100.0. A single trigger may now contribute at most
    `TRIGGER_CONTRIBUTION_CAP`.

4.  **The behavioural LAYER score overwrote the behavioural SCORECARD score.**
    Both were called `behavioural_score`, so every customer card showed their
    layer score where their scorecard score belonged.

5.  **The list and the customer's own page disagreed about their layers.** The
    list read them off the customer's worst-OVERALL facility; the page took
    the worst per layer. RC-0025457 read bureau 0.0 in one and 42.4 in the
    other.

6.  **Every product read CRITICAL.** A population score averaged over the
    warned customers only measures their severity and says nothing about how
    many there are, so all four products came out between 49 and 65.

Every figure here is SYNTHETIC demonstration data and a synthetic
demonstration model. Not an ANB model, not an ANB policy, not a SAMA
requirement, not independently validated.
"""

from __future__ import annotations

import pytest

from backend.retail import ews_model as M
from backend.retail import ews_score as S
from backend.retail import ews_views as V
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")


@pytest.fixture(scope="module")
def months() -> list[str]:
    found = S.panel_months()
    if not found:
        pytest.skip("the Early Warning Score domain has not been built")
    return found


@pytest.fixture(scope="module")
def latest(months: list[str]) -> str:
    return months[-1]


@pytest.fixture(scope="module")
def frame(latest: str):
    return S.read(latest)


# =========================================================== the model =====

def test_the_model_configuration_is_consistent() -> None:
    assert M.check() == []


def test_there_are_exactly_four_layers() -> None:
    assert [one.name for one in M.LAYERS] == [
        "Behavioural Intelligence",
        "Affordability & Cash Flow Intelligence",
        "Bureau & External Credit Intelligence",
        "Facility & Exposure Intelligence",
    ]


def test_the_layer_weights_sum_to_one() -> None:
    assert round(sum(one.weight for one in M.LAYERS), 6) == 1.0


def test_every_product_carries_its_own_weights() -> None:
    assert set(M.PRODUCT_WEIGHTS) == set(M.ALL_PRODUCTS)
    for product, weights in M.PRODUCT_WEIGHTS.items():
        assert round(sum(weights.values()), 6) == 1.0, product
    shapes = {tuple(sorted(w.items())) for w in M.PRODUCT_WEIGHTS.values()}
    assert len(shapes) == 4, (
        "the four products are weighted identically, so the product-specific "
        "configuration says nothing")


def test_classifiers_and_triggers_are_kept_apart() -> None:
    assert len(M.all_classifiers()) >= 30
    assert len(M.all_triggers()) >= 30
    overlap = ({one.key for one in M.all_classifiers()}
               & {one.key for one in M.all_triggers()})
    assert overlap == set(), overlap


def test_there_are_exactly_six_action_dimensions() -> None:
    assert [one.key for one in M.ACTION_DIMENSIONS] == [
        "direction", "magnitude", "velocity", "momentum", "persistence",
        "recency"]
    assert round(sum(M.ACTION_WEIGHTS.values()), 6) == 1.0


def test_the_bureau_layer_is_a_classifier_layer() -> None:
    assert M.BUREAU.kind == "classifier"
    firing = [one for one in M.BUREAU.sublayers
              for one in one.triggers if one.needs_new_observation]
    assert firing, "no bureau trigger requires a new observation"
    # Recency is the exception: staleness accrues without a new pull.
    recency = M.sublayer("bureau_recency")
    assert recency is not None
    assert all(not one.needs_new_observation for one in recency.triggers)


def test_every_governed_rulebook_rule_survives_as_a_trigger() -> None:
    """The useful rules are mapped in, not discarded."""
    from backend.retail import ews as rulebook

    carried = {one.rule_id for one in M.all_triggers() if one.rule_id}
    governed = {one.rule_id for one in rulebook.RULES
                if one.family != "DATA_QUALITY"}
    assert governed - carried == set()


def test_a_trigger_the_book_cannot_support_says_why() -> None:
    absent = [one for one in M.all_triggers() if one.absent_because]
    assert absent, "nothing is declared absent, which is unlikely"
    for one in absent:
        assert len(one.absent_because) > 60, one.key


def test_no_meaning_is_invented_for_unsourced_shorthand() -> None:
    assert M.UNSOURCED_SHORTHAND == ("T", "A", "C")
    assert "T, A and C" in M.NO_SUCH_SHORTHAND
    assert "written out in full" in M.NO_SUCH_SHORTHAND


def test_every_product_has_sub_products_with_a_written_derivation() -> None:
    for product in M.ALL_PRODUCTS:
        subs = M.sub_products_of(product)
        assert subs, product
        for one in subs:
            assert one.derivation, one.code
            assert one.meaning, one.code


# ======================================================== the arithmetic ===

def test_a_single_trigger_cannot_reach_the_ceiling(frame) -> None:
    """Defect 3: one critical trigger pinned a customer at exactly 100."""
    import pandas as pd

    single = frame[frame["triggers_fired"] == 1]
    assert len(single), "no customer-facility fires exactly one trigger"
    worst = float(pd.to_numeric(single["ews_score"]).max())
    assert worst < M.SCALE.maximum, (
        f"one trigger reaches {worst}, the top of the scale")


def test_nobody_piles_up_on_the_ceiling(frame) -> None:
    """Defect 2: five per cent of the book sat at exactly 100."""
    at_ceiling = int((frame["ews_score"] >= M.SCALE.maximum - 0.001).sum())
    assert at_ceiling / max(1, len(frame)) < 0.01, (
        f"{at_ceiling} of {len(frame)} rows sit at the ceiling, so the worst "
        "customers cannot be ordered")


def test_a_serious_single_signal_is_not_reported_as_low(frame) -> None:
    """Defect 1: a HIGH trigger scored 10 out of 100."""
    for trigger in M.evaluated_triggers():
        if trigger.severity not in ("HIGH", "CRITICAL"):
            continue
        alone = frame[(frame[f"trg_{trigger.key}_fired"].fillna(False))
                      & (frame["triggers_fired"] == 1)]
        if not len(alone):
            continue
        assert float(alone["ews_score"].max()) >= M.SCALE.warning_cutoff, (
            f"{trigger.key} fires alone and does not reach the warning "
            f"cutoff: {float(alone['ews_score'].max())}")


def test_the_whole_scale_is_used(frame) -> None:
    per_customer = frame.groupby("customer_id")["ews_score"].max()
    bands = per_customer.map(M.band_of).value_counts()
    for _, band in M.SEVERITY_BANDS:
        assert bands.get(band, 0) > 0, (
            f"no customer is {band}; the band table does not fit the score")


def test_more_triggers_never_score_less(frame) -> None:
    """`_combine` has to be monotone or the score is not a ranking."""
    import numpy as np

    rows = len(frame)
    one = S._combine([(1.0, np.full(rows, 40.0))], rows)
    two = S._combine([(1.0, np.full(rows, 40.0)),
                      (0.5, np.full(rows, 30.0))], rows)
    assert (two >= one).all()
    assert (two <= M.SCALE.maximum).all()
    lone = S._combine([(1.0, np.full(rows, 65.0))], rows)
    assert abs(float(lone[0]) - 65.0) < 1e-9, (
        "a single part at the heaviest weight must reach its own value")


def test_the_hard_triggers_floor_the_score(frame) -> None:
    import pandas as pd

    dpd = pd.to_numeric(frame["dpd"], errors="coerce").fillna(0.0)
    deep = frame[dpd >= 90]
    assert len(deep), "nobody is ninety days down"
    floor = next(h.floor_score for h in M.HARD_TRIGGERS if h.key == "dpd_90")
    assert float(deep["ews_score"].min()) >= floor
    assert (deep["ews_severity"] == "CRITICAL").all()


def test_the_layer_score_column_does_not_collide_with_the_scorecard(frame) -> None:
    """Defect 4: `behavioural_score` was both the layer and the scorecard."""
    assert M.BEHAVIOURAL.score_column == "layer_behavioural_score"
    assert "behavioural_score" in frame.columns
    assert "layer_behavioural_score" in frame.columns
    scored = frame[frame["behavioural_score"].notna()]
    assert len(scored)
    # The scorecard runs in the hundreds; the layer is 0-100.
    assert float(scored["behavioural_score"].max()) > 100.0


# ============================================================ the domain ===

def test_the_domain_holds_exactly_twenty_months(months: list[str]) -> None:
    assert len(months) == S.MONTHS_KEPT == 20
    assert months == S.scored_months()
    assert S.check() == []


def test_the_grain_is_customer_facility_month(frame) -> None:
    assert not frame.duplicated(["customer_id", "facility_id"]).any()
    assert frame["reporting_month"].nunique() == 1


def test_the_domain_holds_no_customer_the_book_does_not(latest: str,
                                                        frame) -> None:
    book = S._read_book(latest)
    assert set(frame["customer_id"]) == set(book["customer_id"])
    assert set(frame["facility_id"]) == set(book["facility_id"])
    assert float(frame["gross_carrying_amount_sar"].sum()) == pytest.approx(
        float(book["gross_carrying_amount_sar"].sum()), rel=1e-9)


def test_the_field_contract_is_complete() -> None:
    served = V.field_contract()
    assert served["available"]
    assert served["month_count"] == 20
    every = {field for group in served["groups"] for field in group["fields"]}
    for required in (
        "reporting_month", "customer_id", "customer_name", "facility_id",
        "product_code", "sub_product", "segment", "months_on_book",
        "employment_status", "salary_transfer_flag",
        "gross_carrying_amount_sar", "current_credit_limit_sar",
        "utilisation_ratio", "secured_flag", "collateral_value_current_sar",
        "ltv_current_ratio", "balloon_flag",
        "dpd", "previous_month_dpd", "dpd_change", "dpd_bucket",
        "ifrs9_stage", "previous_month_stage", "stage_change",
        "current_bad_flag", "current_default_flag",
        "default_entry_this_month", "eligible_for_default_this_month",
        "cure_flag", "forbearance_flag", "restructured_flag",
        "application_score", "application_score_band", "behavioural_score",
        "prior_behavioural_score", "behavioural_score_change",
        "behavioural_score_band",
        "bureau_score_at_origination", "latest_bureau_score",
        "bureau_last_observed_date", "bureau_recency_months",
        "bureau_risk_band", "external_delinquency_flag",
        "external_default_flag", "bureau_enquiry_count",
        "synthetic_bureau_proxy_flag",
        "verified_income", "salary_credit_missing_flag",
        "salary_change_3m_ratio", "salary_volatility_6m", "dbr", "prior_dbr",
        "dbr_change", "disposable_income_sar", "disposable_income_change",
        "account_inflows_1m_sar", "account_outflows_1m_sar",
        "missed_payment_count_3m", "returned_payment_count_3m",
        "autopay_failure_count_3m", "broken_promise_count_3m",
        "minimum_payment_only_months_3m", "overlimit_days_3m",
        "utilisation_change_3m_pp", "months_to_balloon",
        "ews_score", "ews_severity", "ews_threshold", "ews_alert_flag",
        "forward_risk_flag", "top_reason_code_1", "top_reason_code_2",
        "top_reason_code_3", "primary_deteriorating_layer",
        "model_version", "rulebook_version",
    ):
        assert required in every, required


def test_every_sublayer_and_layer_has_a_column(frame) -> None:
    for sub in M.all_sublayers():
        assert sub.score_column in frame.columns, sub.key
    for layer in M.LAYERS:
        assert layer.score_column in frame.columns, layer.key


def test_every_evaluated_trigger_has_its_six_action_dimensions(frame) -> None:
    for trigger in M.evaluated_triggers():
        for suffix in ("fired", "value", "comparator", "contribution"):
            assert f"trg_{trigger.key}_{suffix}" in frame.columns, trigger.key
        for dimension in M.ACTION_DIMENSIONS:
            assert f"trg_{trigger.key}_{dimension.key}" in frame.columns, (
                f"{trigger.key} has no {dimension.key}")


def test_odr_is_never_a_property_of_one_customer(frame) -> None:
    named = [c for c in frame.columns if "odr" in c.lower()]
    assert named == [], named
    assert "default_entry_this_month" in frame.columns
    assert "eligible_for_default_this_month" in frame.columns


def test_the_default_entry_rate_has_a_real_denominator(latest: str) -> None:
    served = V.portfolio(latest)["headline"]
    expected = (round(served["default_entries"] / served["default_eligible"]
                      * 100, 4) if served["default_eligible"] else 0.0)
    assert served["odr_pct"] == pytest.approx(expected)
    assert 0 < served["default_eligible"] <= served["facilities"]


# ============================================================= the bureau ==

def test_the_bureau_is_not_observed_every_month(frame) -> None:
    """§17's locked rule, checked against the data rather than the prose."""
    observed = int(frame["bureau_observed"].fillna(False).sum())
    assert 0 < observed < len(frame) * 0.5, (
        f"{observed} of {len(frame)} rows claim a new bureau observation")


def test_bureau_recency_is_real(frame) -> None:
    import pandas as pd

    recency = pd.to_numeric(frame["bureau_recency_months"],
                            errors="coerce").fillna(0.0)
    assert float(recency.max()) > 6, (
        "nobody's bureau position is more than six months old, which means "
        "the pull schedule is not being applied")
    assert float(recency.min()) == 0.0


def test_a_bureau_trigger_cannot_fire_without_a_new_observation(frame) -> None:
    for trigger in M.evaluated_triggers():
        if not trigger.needs_new_observation:
            continue
        fired = frame[frame[f"trg_{trigger.key}_fired"].fillna(False)]
        if not len(fired):
            continue
        assert fired["bureau_observed"].fillna(False).all(), (
            f"{trigger.key} fired in a month with no new bureau observation")


def test_the_bureau_value_is_carried_forward_unchanged(months: list[str]
                                                       ) -> None:
    """Between pulls, last month's value is used again — not a new one."""
    import pandas as pd

    now = S.read(months[-1]).set_index("facility_id")
    was = S.read(months[-2]).set_index("facility_id")
    shared = now.index.intersection(was.index)
    quiet = now.loc[shared][~now.loc[shared, "bureau_observed"].fillna(False)]
    assert len(quiet), "every row claims a new observation"
    moved = (pd.to_numeric(quiet["latest_bureau_score"], errors="coerce")
             != pd.to_numeric(was.loc[quiet.index, "latest_bureau_score"],
                              errors="coerce"))
    assert not moved.any(), (
        f"{int(moved.sum())} bureau scores moved in a month with no new "
        "observation")


def test_the_bureau_is_labelled_a_synthetic_proxy(frame) -> None:
    assert frame["synthetic_bureau_proxy_flag"].all()
    assert "SYNTHETIC" in M.BUREAU_RULE.proxy_label.upper()
    assert "no live bureau connection" in M.BUREAU_RULE.no_agreement.lower() \
        or "no bureau agreement" in M.BUREAU_RULE.no_agreement.lower()


# ============================================================= the views ===

def test_the_portfolio_reconciles_with_its_products(latest: str) -> None:
    served = V.portfolio(latest)
    head = served["headline"]
    assert sum(p["facilities"] for p in served["products"]) == head["facilities"]
    assert sum(p["exposure_sar"] for p in served["products"]) == pytest.approx(
        head["exposure_sar"], abs=1.0)
    # Customers may overlap across products; they may not fall short.
    assert sum(p["customers"] for p in served["products"]) >= head["customers"]


def test_a_product_reconciles_with_its_sub_products(latest: str) -> None:
    served = V.product("CREDIT_CARD", latest)
    head = served["headline"]
    subs = served["sub_products"]
    assert sum(s["facilities"] for s in subs) == head["facilities"]
    assert sum(s["exposure_sar"] for s in subs) == pytest.approx(
        head["exposure_sar"], abs=1.0)
    assert sum(s["default_entries"] for s in subs) == head["default_entries"]


def test_the_population_score_discriminates(latest: str) -> None:
    """Defect 6: every product wore a CRITICAL badge."""
    served = V.portfolio(latest)
    bands = {p["severity_band"] for p in served["products"]}
    assert len(bands) > 1, (
        f"all four products are {bands}; the population band table says "
        "nothing")


def test_the_list_and_the_detail_agree(latest: str) -> None:
    """Defect 5: the two screens banded a customer's layers differently."""
    listed = V.customers(latest, cohort="critical", limit=8)
    assert listed["customers"]
    for row in listed["customers"]:
        detail = V.customer(row["customer_id"], latest)
        assert detail["available"], row["customer_id"]
        assert detail["ews_score"] == pytest.approx(row["ews_score"], abs=0.01)
        assert detail["ews_severity"] == row["ews_severity"]
        for layer in detail["layers"]:
            assert layer["score"] == pytest.approx(
                row["layers"].get(layer["key"], 0.0), abs=0.01), (
                f"{row['customer_id']} / {layer['key']}")


def test_current_bad_and_forward_risk_never_overlap(latest: str) -> None:
    bad = V.customers(latest, cohort="current_bad", limit=500)
    forward = V.customers(latest, cohort="forward_risk", limit=500)
    assert ({r["customer_id"] for r in bad["customers"]}
            & {r["customer_id"] for r in forward["customers"]}) == set()


def test_a_forward_risk_customer_is_still_paying(latest: str) -> None:
    served = V.customers(latest, cohort="forward_risk", limit=100)
    for row in served["customers"]:
        assert not row["current_bad"], row["customer_id"]
        assert row["ews_severity"] in ("HIGH", "CRITICAL"), row["customer_id"]


def test_every_customer_row_accounts_for_its_behavioural_score(
        latest: str) -> None:
    served = V.customers(latest, cohort="everyone", limit=400)
    for row in served["customers"]:
        if row["behavioural_score"] is None:
            assert row["behavioural_score_absent_because"], row["customer_id"]
            assert "application score" in (
                row["behavioural_score_absent_because"].lower())
        else:
            assert not row["behavioural_score_absent_because"]


def test_every_customer_row_carries_six_months_of_series(latest: str) -> None:
    served = V.customers(latest, cohort="all", limit=20)
    for row in served["customers"]:
        assert 1 <= len(row["series"]) <= S.TREND_MONTHS, row["customer_id"]
        assert all("ews_score" in point for point in row["series"])


def test_a_customer_detail_carries_the_whole_model(latest: str) -> None:
    listed = V.customers(latest, cohort="critical", limit=1)
    who = listed["customers"][0]["customer_id"]
    detail = V.customer(who, latest)
    assert len(detail["layers"]) == 4
    assert sum(len(l["sublayers"]) for l in detail["layers"]) == 19
    fired = [t for l in detail["layers"] for s in l["sublayers"]
             for t in s["triggers"] if t["fired"]]
    assert fired, who
    for trigger in fired:
        action = trigger["action"]
        assert action is not None
        for dimension in M.ACTION_DIMENSIONS:
            assert action.get(dimension.key) is not None, (
                f"{trigger['key']} has no {dimension.key}")
    assert detail["facilities"]
    assert sum(f["share_of_customer_pct"]
               for f in detail["facilities"]) == pytest.approx(100.0, abs=1.5)


def test_the_commentary_is_generated(latest: str) -> None:
    served = V.portfolio(latest)
    said = {p["product_code"]: p["commentary"] for p in served["products"]}
    assert len(set(said.values())) == len(said)
    for card in served["products"]:
        assert f"{card['ews_score']:.1f}" in card["commentary"], (
            card["product_code"])


def test_every_trend_is_six_months(latest: str) -> None:
    served = V.portfolio(latest)
    assert len(served["trend"]) == S.TREND_MONTHS
    for card in served["products"]:
        assert len(card["trend"]) == S.TREND_MONTHS, card["product_code"]
    product = V.product("CREDIT_CARD", latest)
    for card in product["sub_products"]:
        assert len(card["trend"]) == S.TREND_MONTHS, card["sub_product"]


# =============================================================== the chat ==

def test_the_chat_reaches_only_the_early_warning_domain() -> None:
    """The scope is structural: the module holds nothing else to read with."""
    from pathlib import Path

    from backend.retail import ews_chat as chat

    assert chat.SCOPE == (S.DOMAIN,)
    source = Path(chat.__file__).read_text()
    body = source.split('"""', 2)[-1]
    for forbidden in ("retail_facility_month", "retail_whatif",
                      "retail_credit_scorecard", "retail_early_warning",
                      "duckdb", "read_parquet", "reload_catalog",
                      "get_session", "corporate_"):
        assert forbidden not in body, forbidden
    imports = [line.strip() for line in body.split("\n")
               if line.strip().startswith(("import ", "from "))]
    for line in imports:
        assert ("ews_model" in line or "ews_views" in line
                or line.startswith(("import re", "from dataclasses",
                                    "from typing", "from __future__"))), line


@pytest.mark.parametrize("question", [
    "Which portfolios have the most critical Early Warning customers?",
    "Which product deteriorated most this month?",
    "Show the six-month Early Warning Score trend by product.",
    "Which product has the highest exposure under warning?",
    "Show current bad versus forward-risk customers.",
    "Which Credit Card sub-product is deteriorating fastest?",
    "Show the top five signals for Privilege Card.",
    "Show High and Critical Privilege Card customers.",
    "Only customers with DPD = 0.",
    "Which currently performing customers are most likely to deteriorate?",
])
def test_the_chat_answers_every_seeded_question(question: str) -> None:
    from backend.retail import ews_chat as chat

    answer = chat.ask(question)
    assert answer["in_scope"], question
    assert len(answer["answer"]) > 40, question
    assert 3 <= len(answer["follow_ups"]) <= 5, question
    assert answer["domain"] == S.DOMAIN


@pytest.mark.parametrize("question,where", [
    ("What is the ECL for the credit card book?", "Cockpit"),
    ("Run a downturn stress scenario.", "What-If"),
    ("What is the Gini of the behavioural scorecard?", "Scorecard"),
    ("Show me the corporate portfolio.", "retail"),
    ("What is the RWA on this book?", "Cockpit"),
])
def test_the_chat_refuses_what_belongs_elsewhere(question: str,
                                                 where: str) -> None:
    from backend.retail import ews_chat as chat

    answer = chat.ask(question)
    assert not answer["in_scope"], question
    assert where.lower() in answer["answer"].lower(), answer["answer"]
    assert "scoped to the Early Warning Score domain" in answer["scope_note"]


def test_a_customer_question_answers_from_the_customer(latest: str) -> None:
    from backend.retail import ews_chat as chat

    who = V.customers(latest, cohort="critical",
                      limit=1)["customers"][0]["customer_id"]
    answer = chat.ask(f"Why is {who} flagged?")
    assert answer["in_scope"]
    assert who in answer["answer"]
    assert answer["intent"].startswith("customer")
    bureau = chat.ask(f"How old is the bureau information for {who}?")
    assert bureau["intent"] == "customer_bureau"
    assert "observation" in bureau["answer"].lower()


# ============================================================== the model ==

def test_the_served_model_carries_everything_the_screen_needs(
        latest: str) -> None:
    served = V.model(latest)
    assert served["counts"]["layers"] == 4
    assert served["counts"]["sublayers"] == 19
    assert len(served["flow"]) >= 8
    assert len(served["action_dimensions"]) == 6
    assert len(served["hard_triggers"]) == len(M.HARD_TRIGGERS)
    assert len(served["glossary"]) >= 14
    assert served["lineage"]["domain"] == S.DOMAIN
    # Live counts, so a trigger that never fires cannot hide on the screen.
    for layer in served["layers"]:
        for sub in layer["sublayers"]:
            for trigger in sub["triggers"]:
                assert "customers" in trigger, trigger["key"]


def test_the_glossary_defines_the_action_dimensions() -> None:
    terms = {one.term for one in M.GLOSSARY}
    for word in ("Direction", "Magnitude", "Velocity", "Momentum",
                 "Persistence", "Recency", "Classifier", "Trigger", "ODR"):
        assert word in terms, word
