"""Phase 3: the two analytical story engines, §6 and §7.

Small fixed frames where the answer can be worked out on paper, then
book-scale reconciliation where the point is that the pieces agree. No
expected value here is produced by calling the function under test.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.retail import decomposition as D
from backend.retail import story_router as R
from backend.retail import taxonomy as tax


def _frame(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
    """facility, customer, bucket, exposure — the four columns that matter."""
    return pd.DataFrame({
        "facility_id": [one[0] for one in rows],
        "customer_id": [one[1] for one in rows],
        "dpd_bucket": [one[2] for one in rows],
        "gross_carrying_amount_sar": [one[3] for one in rows],
        "product_code": ["CREDIT_CARD"] * len(rows),
    })


# ===================== TRANSITIONS: worked out on paper =====================

OPENING = _frame([
    ("F1", "C1", "CURRENT", 100.0),
    ("F2", "C2", "1-29", 200.0),
    ("F3", "C3", "30-59", 300.0),
    ("F4", "C4", "90-179", 400.0),
    ("F5", "C5", "CURRENT", 500.0),   # leaves the book
])
CLOSING = _frame([
    ("F1", "C1", "1-29", 110.0),      # worse, still under 30
    ("F2", "C2", "30-59", 220.0),     # INTO 30+
    ("F3", "C3", "CURRENT", 280.0),   # CURED out of 30+
    ("F4", "C4", "90-179", 400.0),    # held
    ("F6", "C6", "30-59", 600.0),     # entrant, already 30+
])


def test_tra_01_migrations_exclude_entrants_and_exits() -> None:
    got = D.transitions(OPENING, CLOSING)
    assert got.matched_facilities == 4            # F1..F4
    assert got.entrants["facilities"] == 1        # F6
    assert got.exits["facilities"] == 1           # F5
    assert got.entrants["in_thirty_plus"] == 1
    assert got.exits["from_thirty_plus"] == 0
    # F6 is an entrant, so it must not appear anywhere in the matrix.
    assert sum(one["facilities"] for one in got.matrix) == 4


def test_tra_02_worse_better_and_held_are_counted_by_rank() -> None:
    got = D.transitions(OPENING, CLOSING)
    assert got.worsened["facilities"] == 2        # F1 and F2
    assert got.cured["facilities"] == 1           # F3
    assert got.held["facilities"] == 1            # F4
    assert got.worsened["exposure_sar"] == pytest.approx(300.0)  # 100 + 200


def test_tra_03_crossing_thirty_is_not_the_same_as_worsening() -> None:
    """F1 got worse and did not cross 30. Conflating the two overstates it."""
    got = D.transitions(OPENING, CLOSING)
    assert got.into_thirty_plus["facilities"] == 1        # F2 only
    assert got.out_of_thirty_plus["facilities"] == 1      # F3 only
    assert got.worsened["facilities"] == 2                # F1 and F2


def test_tra_04_a_cell_reports_its_row_share() -> None:
    got = D.transitions(OPENING, CLOSING)
    cell = next(one for one in got.matrix
                if one["from"] == "1-29" and one["to"] == "30-59")
    assert cell["facilities"] == 1
    assert cell["row_share_pct"] == pytest.approx(100.0)   # F2 is the only 1-29


# =================== RATE BRIDGE: the identity, then the flows ==============

def test_rat_01_the_identity_is_exact() -> None:
    """r1 − r0 = (N1−N0)/D1 + N0(1/D1 − 1/D0), by hand.

    Opening: 30+ exposure 300 + 400 = 700 of 1500 -> 46.6667%
    Closing: 220 + 400 + 600 = 1220 of 1610      -> 75.7764%
    """
    got = D.rate_bridge(OPENING, CLOSING)
    assert got["opening"]["numerator"] == pytest.approx(700.0)
    assert got["opening"]["denominator"] == pytest.approx(1500.0)
    assert got["closing"]["numerator"] == pytest.approx(1220.0)
    assert got["closing"]["denominator"] == pytest.approx(1610.0)
    assert got["opening"]["rate_pct"] == pytest.approx(46.6667, abs=1e-4)
    assert got["closing"]["rate_pct"] == pytest.approx(75.7764, abs=1e-4)

    n0, d0, n1, d1 = 700.0, 1500.0, 1220.0, 1610.0
    numerator = (n1 - n0) / d1 * 100
    denominator = n0 * (1 / d1 - 1 / d0) * 100
    parts = {one["part"]: one["contribution_pp"] for one in got["parts"]}
    assert parts["Arrears moved"] == pytest.approx(numerator, abs=1e-4)
    assert parts["The book moved"] == pytest.approx(denominator, abs=1e-4)
    assert (parts["Arrears moved"] + parts["The book moved"]
            == pytest.approx(got["change_pp"], abs=1e-4))


def test_rat_02_the_five_flows_explain_the_numerator_exactly() -> None:
    got = D.rate_bridge(OPENING, CLOSING)
    named = {one["flow"]: one for one in got["numerator_flows"]}
    assert named["New arrears"]["facilities"] == 1
    assert named["New arrears"]["amount"] == pytest.approx(220.0)   # F2 closing
    assert named["Cures"]["amount"] == pytest.approx(-300.0)        # F3 opening
    assert named["Entrants already 30+"]["amount"] == pytest.approx(600.0)
    assert named["Balance movement on accounts that stayed 30+"]["amount"] \
        == pytest.approx(0.0)                                       # F4 flat
    assert got["numerator_change"] == pytest.approx(520.0)          # 1220 − 700
    assert got["flow_residual"] == pytest.approx(0.0, abs=1e-6)
    assert got["reconciles"] is True


def test_rat_03_by_account_is_a_different_number_and_says_so() -> None:
    weighted = D.rate_bridge(OPENING, CLOSING, weighting="exposure")
    counted = D.rate_bridge(OPENING, CLOSING, weighting="accounts")
    assert weighted["metric_id"] != counted["metric_id"]
    # 2 of 5 open -> 40%;  3 of 5 closed -> 60%
    assert counted["opening"]["rate_pct"] == pytest.approx(40.0)
    assert counted["closing"]["rate_pct"] == pytest.approx(60.0)
    assert counted["change_pp"] != weighted["change_pp"]


def test_rat_04_a_pd_change_is_named_as_not_a_reason() -> None:
    got = D.rate_bridge(OPENING, CLOSING)
    assert "modelled PD" in got["caution"]
    assert "cannot be a reason" in got["caution"]


# ================= MIX BRIDGE: symmetric, and exact ========================

def _two_segment(a_rate, a_weight, b_rate, b_weight, total=1000.0):
    """Build a frame with two products at the given 30+ rates and weights."""
    rows = []
    for name, rate, weight in (("CREDIT_CARD", a_rate, a_weight),
                               ("PERSONAL_LOAN", b_rate, b_weight)):
        exposure = total * weight
        late, good = exposure * rate, exposure * (1 - rate)
        rows.append((f"{name}-late", f"{name}-c1", "90-179", late, name))
        rows.append((f"{name}-ok", f"{name}-c2", "CURRENT", good, name))
    return pd.DataFrame({
        "facility_id": [one[0] for one in rows],
        "customer_id": [one[1] for one in rows],
        "dpd_bucket": [one[2] for one in rows],
        "gross_carrying_amount_sar": [one[3] for one in rows],
        "product_code": [one[4] for one in rows],
    })


def test_mix_01_pure_mix_shift_is_all_mix() -> None:
    """Rates identical in both periods; only the weights move."""
    before = _two_segment(0.10, 0.50, 0.02, 0.50)
    after = _two_segment(0.10, 0.80, 0.02, 0.20)
    got = D.mix_bridge(before, after)
    assert got["within_pp"] == pytest.approx(0.0, abs=1e-9)
    # overall: .5(.10)+.5(.02)=.06 -> .8(.10)+.2(.02)=.084  => +2.4 pp
    assert got["mix_pp"] == pytest.approx(2.4, abs=1e-6)
    assert got["observed_change_pp"] == pytest.approx(2.4, abs=1e-6)
    assert got["reconciles"] is True


def test_mix_02_pure_rate_shift_is_all_within() -> None:
    before = _two_segment(0.10, 0.50, 0.02, 0.50)
    after = _two_segment(0.14, 0.50, 0.02, 0.50)
    got = D.mix_bridge(before, after)
    assert got["mix_pp"] == pytest.approx(0.0, abs=1e-9)
    assert got["within_pp"] == pytest.approx(2.0, abs=1e-6)   # .5 × 4 pp
    assert got["reconciles"] is True


def test_mix_03_the_split_is_symmetric_in_the_two_periods() -> None:
    """Swapping the periods must negate both halves, not reshuffle them."""
    before = _two_segment(0.10, 0.40, 0.03, 0.60)
    after = _two_segment(0.13, 0.70, 0.02, 0.30)
    forward = D.mix_bridge(before, after)
    backward = D.mix_bridge(after, before)
    assert forward["mix_pp"] == pytest.approx(-backward["mix_pp"], abs=1e-9)
    assert forward["within_pp"] == pytest.approx(-backward["within_pp"], abs=1e-9)


def test_mix_04_it_reconciles_to_the_observed_change() -> None:
    before = _two_segment(0.10, 0.40, 0.03, 0.60)
    after = _two_segment(0.13, 0.70, 0.02, 0.30)
    got = D.mix_bridge(before, after)
    assert got["residual_pp"] == pytest.approx(0.0, abs=1e-9)
    assert (got["mix_pp"] + got["within_pp"]
            == pytest.approx(got["observed_change_pp"], abs=1e-6))


def test_mix_05_a_derived_dimension_is_carried_not_dropped() -> None:
    """The defect: `_side` kept a fixed column list, so a bridge asked for by
    sub-product silently answered by product."""
    before = _two_segment(0.10, 0.50, 0.02, 0.50).assign(
        sub_product_code=["CC_CLASSIC", "CC_CLASSIC", "PL_STANDARD",
                          "PL_STANDARD"])
    after = _two_segment(0.14, 0.50, 0.02, 0.50).assign(
        sub_product_code=["CC_CLASSIC", "CC_CLASSIC", "PL_STANDARD",
                          "PL_STANDARD"])
    got = D.mix_bridge(before, after, by="sub_product_code")
    assert got["available"] is True
    assert {one["segment"] for one in got["segments"]} == {"CC_CLASSIC",
                                                           "PL_STANDARD"}


# ======================= ROUTER: scope from the thread ======================

CASE = {"scope": {"period": "2026-08", "compare_period": "2026-07",
                  "sector": "Credit Card"},
        "risk_case": {"entity": "Credit Card", "entity_kind": "product",
                      "level": "SEGMENT", "period": "2026-08",
                      "title": "Credit Card 30+ DPD has risen for 5 "
                               "consecutive months"}}


@pytest.mark.parametrize("said", [
    "what is the reason of this rise?",
    "What are the reasons for this rise?",
    "Why has it gone up?",
    "Break it down into worsening accounts, cures and new accounts.",
    "Which sub-products are driving the increase?",
    "What improved and offset the deterioration?",
    "Compare account-count and exposure-weighted 30+ DPD.",
])
def test_rou_01_every_contract_phrasing_reaches_the_decomposition(said) -> None:
    got = R.read(said, CASE)
    assert got is not None, said
    assert got.analysis == R.DELINQUENCY
    assert got.product == "CREDIT_CARD"
    assert got.month == "2026-08" and got.prior == "2026-07"


def test_rou_02_a_bare_why_with_no_case_is_left_to_the_planner() -> None:
    assert R.read("what is the reason of this rise?", {}) is None


def test_rou_03_the_sentence_beats_the_thread() -> None:
    got = R.read("Why has personal finance gone up?", CASE)
    assert got.product == "PERSONAL_LOAN"
    assert got.scope_source == "the question"


def test_rou_04_a_trait_question_does_not_inherit_the_case_product() -> None:
    """§7.1: a fresh trait question is a RETAIL question until it says
    otherwise. Inheriting silently is the defect the contract names."""
    got = R.read("Tell me what customer traits have deteriorated and what is "
                 "the impact on ECL because of them.", CASE)
    assert got.analysis == R.TRAITS
    assert got.product == ""
    assert got.scope_source == ""


def test_rou_05_ordinary_questions_are_not_intercepted() -> None:
    for said in ("show retail exposure by product",
                 "what is the weighted ECL",
                 "list the top ten customers by exposure"):
        assert R.read(said, CASE) is None, said


# ============ the substring defect that scoped answers to the wrong book ====

@pytest.mark.parametrize("said,want", [
    ("Which customers explain most of it?", None),        # "ex-PL-ain"
    ("Show all behavioural scorecard variables", None),   # "score-CARD"
    ("automatic renewal", None),                          # "AUTO-matic"
    ("homeowners in arrears", None),                      # "HOME-owners"
    ("the credit card book", "CREDIT_CARD"),
    ("show me PL exposure", "PERSONAL_LOAN"),
    ("mortgage book", "HOME_LOAN"),
    ("compare credit card and mortgage", None),           # genuinely ambiguous
])
def test_tax_01_products_are_matched_on_words_not_substrings(said, want) -> None:
    assert tax.resolve_product(said) == want
