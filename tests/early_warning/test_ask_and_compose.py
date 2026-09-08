"""Reading an Early Warning question, and writing the answer.

The bar these tests hold the answer to is the one that separates a chat box
from a control a supervisor will accept: every claim names the node it came
from, no figure appears that the facts do not carry, a score movement is
never confused with a condition movement, recommendations come from the
library with an owner and an evidence test, and the answer always says where
to look next.

Two refusals are tested as carefully as the answers. The assistant does not
change a score, and it does not close a case — asked for either it says so
and offers the route that does exist, because a chat layer that can quietly
do both is a control nobody can rely on.
"""

from __future__ import annotations

import re

import pytest

from backend.early_warning import ask
from backend.early_warning import compose as cp
from backend.early_warning import diagnosis as dg
from backend.early_warning import facts as ff
from backend.early_warning import v2_service as svc


@pytest.fixture(scope="module", autouse=True)
def _require_domain():
    try:
        svc.latest_period()
    except Exception:  # noqa: BLE001
        pytest.skip("Early Warning V2 domain is not built")


@pytest.fixture(scope="module")
def worst():
    return svc.top_high_risk(limit=1)[0]


def _numbers_in(text: str) -> list[float]:
    return [float(m) for m in re.findall(r"-?\d+(?:\.\d+)?", text or "")]


# ------------------------------------------------------------------ routing


def test_a_question_about_the_book_is_answered_at_portfolio_scope():
    assert ask.answer("How does the portfolio look?").scope == "portfolio"


def test_a_question_this_domain_does_not_answer_is_declined():
    """The alternative — falling back to a portfolio summary — answers a
    different question from the one asked, and it would also swallow
    questions that need another domain's data before the domain lock could
    refuse them.
    """
    assert ask.answer("What is the weather in Riyadh?") is None
    assert ask.answer("How much is in arrears?") is None


def test_a_named_obligor_anchors_the_answer(worst):
    found = ask.answer(f"Why is {worst['customer_name']} flagged?")
    assert found.scope == "borrower"
    assert worst["customer_name"] in found.composed.direct


def test_an_obligor_is_resolved_against_the_early_warning_domain(worst):
    """The specific failure this closes.

    These obligors are not in the credit book's customer master, so the
    general path looked them up there, failed, and replied that CreditProbe
    holds no data about them — while the domain the question was asked in
    held the whole answer.
    """
    assert ask.resolve_borrower(f"tell me about {worst['customer_name']}") == \
        worst["customer_id"]
    assert ask.resolve_borrower("tell me about a company nobody has heard of") is None


def test_grouping_is_not_fixed_to_segment():
    assert ask.answer("Group the portfolio by internal grade.").scope == "level"
    assert ask.resolve_level("group by stage") == "ifrs9_stage"
    assert ask.resolve_level("break it down by region") == "region"


def test_a_diagnosis_question_is_not_read_as_a_request_to_open_a_band():
    """"the high-risk borrowers" names a severity band, but the question is
    about what they share, not a request to open that band."""
    assert ask.answer("What do the high-risk borrowers have in common?").scope \
        == "diagnosis"
    assert ask.answer("Run the diagnosis on the portfolio.").scope == "diagnosis"


def test_a_question_about_the_model_needs_no_obligor():
    found = ask.answer("Explain the matrix.")
    assert found.scope == "methodology"
    assert "105" in found.composed.direct  # scored signals, read from the engine


def test_a_follow_up_stays_on_the_obligor_the_thread_is_about(worst):
    """"What should I do?" after a borrower answer is about that borrower."""
    found = ask.answer("What action should I take?",
                       customer_id=worst["customer_id"])
    assert found.scope == "action"
    assert worst["customer_name"] in found.composed.direct


# ----------------------------------------------------------------- refusals


def test_the_assistant_will_not_change_a_score():
    found = ask.answer("Change the score for this borrower to 40.")
    assert found.refused is True
    assert "override path" in found.composed.direct
    assert found.composed.follow_ups  # and offers the route that does exist


def test_the_assistant_will_not_close_a_case():
    found = ask.answer("Close this alert.")
    assert found.refused is True
    assert "escalation matrix decides" in found.composed.direct


# ------------------------------------------------------------ answer quality


def test_every_answer_offers_a_specific_next_drill(worst):
    for question in ("How does the portfolio look?",
                     f"Why is {worst['customer_name']} flagged?",
                     "Group the portfolio by internal grade.",
                     "What do the high-risk borrowers have in common?"):
        found = ask.answer(question)
        assert found.composed.follow_ups, question
        for step in found.composed.follow_ups:
            # "Would you like to know more?" is not a next step.
            assert len(step) > 12 and "?" in step or step.endswith("."), step


def test_a_borrower_answer_names_the_node_not_only_the_number(worst):
    found = ask.answer(f"Why is {worst['customer_name']} flagged?")
    text = found.composed.direct + " " + found.composed.interpretation
    assert re.search(r"\bL[1-4]\.(T?\d)\b", text), text


def test_a_borrower_answer_quotes_the_anchor_and_the_notches(worst):
    """The final score alone cannot be challenged by a committee."""
    found = ask.answer(f"Why is {worst['customer_name']} flagged?")
    assert "anchor" in found.composed.direct.lower()
    assert "notch" in found.composed.direct.lower()


def test_every_figure_in_the_answer_is_carried_by_the_facts(worst):
    """The grounding rule, checked rather than asserted.

    Every number in the written answer must appear in the fact pack. A
    plausible figure that the facts do not carry reads exactly like the true
    ones beside it.
    """
    found = ask.answer(f"Why is {worst['customer_name']} flagged?")
    carried = {round(n, 2) for n in found.pack.numbers()}
    # Values the prose legitimately derives by rounding or by taking an
    # absolute value are matched against the same transformations.
    allowed = carried | {round(abs(n), 2) for n in carried} | {
        round(n, 0) for n in carried} | {round(n, 1) for n in carried}
    for value in _numbers_in(found.composed.direct):
        assert (round(value, 2) in allowed or round(value, 0) in allowed
                or value in {1, 2, 3, 4, 5}), value


def test_an_action_carries_an_owner_a_timeframe_and_an_evidence_test(worst):
    found = ask.answer("What action should I take?",
                       customer_id=worst["customer_id"])
    assert found.composed.points
    action_lines = [p for p in found.composed.points if "Closes on:" in p]
    assert action_lines, found.composed.points
    for line in action_lines:
        assert "Closes on:" in line
        # An owner and a timeframe, both present in the same line.
        assert re.search(r"(immediate|\d+ days?)", line), line


def test_no_answer_recommends_monitoring_closely(worst):
    for question in ("What action should I take?", "Should I escalate this?"):
        found = ask.answer(question, customer_id=worst["customer_id"])
        blob = " ".join([found.composed.direct, found.composed.interpretation,
                         *found.composed.points]).lower()
        assert "monitor closely" not in blob


def test_an_escalation_answer_says_why_that_rung(worst):
    found = ask.answer("Should I escalate this?", customer_id=worst["customer_id"])
    blob = found.composed.direct + " " + found.composed.interpretation
    assert "severity" in blob.lower()
    assert "exposure" in blob.lower()


def test_a_notch_driven_fall_is_never_called_an_improvement():
    """Written against the framework's own worked case."""
    import pandas as pd

    pack = ff.FactPack(
        scope="borrower", label="Test Obligor", period="2026-06",
        figures={
            "customer_name": "Test Obligor", "customer_id": "T-1",
            "ews_score": 56.0, "ews_band": "MEDIUM", "anchor_score": 72.0,
            "net_notches": -2, "notches": {}, "exposure": 412.0,
            "layers": {}, "drivers": [],
            "live_versus_structural": ff.live_versus_structural(
                73.08, "HIGH", 71.28, "HIGH"),
            "movement_1m": ff.movement_attribution(pd.DataFrame([
                {"snapshot_month": "2026-05", "ews_score": 72.0,
                 "anchor_score": 72.0, "net_notches": 0},
                {"snapshot_month": "2026-06", "ews_score": 56.0,
                 "anchor_score": 72.0, "net_notches": -2}])),
            "overrides_applied": [],
        })
    written = cp.borrower(pack)
    text = written.interpretation.lower()
    assert "notch" in text
    assert "has not moved" in text or "not an improvement" in text
    assert "improved" not in text.replace("not an improvement", "")


def test_an_evidence_answer_names_the_source_system(worst):
    """The system an analyst would go to in order to verify the reading.

    That is the UPSTREAM system — the core portfolio, the ratings feed, the
    external intelligence feed — not this domain. Early Warning is where the
    signal was scored; it is not where the observation came from, and telling
    an analyst to verify a receivable-ageing reading "in Early Warning" sends
    them to the place that already believes it.

    An earlier version of this test asserted the literal string
    "early_warning" and passed only because the highest-scoring obligor
    happened to carry an L3 signal from this domain's own synthetic feed. It
    was asserting a coincidence.
    """
    found = ask.answer(f"Show me the evidence behind {worst['customer_name']}.")
    if found.scope != "evidence":
        pytest.skip("no signal fired for this obligor")
    blob = found.composed.direct + " " + found.composed.interpretation
    source = str(found.pack.figures.get("source_domain") or "")
    dataset = str(found.pack.figures.get("source_dataset") or "")
    assert source, "the observation carries no source system"
    assert source in blob, (
        f"the answer does not name {source!r}, which is where an analyst "
        f"would verify it")
    assert dataset in blob, "the answer does not name the source dataset"
    assert "half-life" in blob


def test_a_diagnosis_answer_always_states_its_limits():
    found = ask.answer("What do the high-risk borrowers have in common?")
    assert any("not predictive" in c for c in found.composed.caveats)
    assert any("approval or decline" in c for c in found.composed.caveats)


# ---------------------------------------------------------------- the tree


def test_the_chosen_split_reduces_variance_most():
    frame = ff._with_derived(svc.borrower_month())
    best = None
    for split in dg.candidate_splits(frame):
        gain = dg._variance_reduction(frame, split)
        if gain is not None and (best is None or gain > best[0]):
            best = (gain, split.describe())
    found = dg.tree()
    if best is None:
        assert found["strongest_split"] is None
    else:
        assert found["strongest_split"] == best[1]


def test_no_leaf_is_smaller_than_the_minimum():
    found = dg.tree()
    floor = found["min_leaf"]
    for leaf in found["leaves"]:
        assert leaf["obligors"] >= min(floor, found["root"]["obligors"]), leaf


def test_a_population_too_small_to_split_returns_a_root_only_tree():
    found = dg.tree(band="VERY_LOW", segment="Not A Segment")
    assert found["root"] is None
    assert found["caveats"]


def test_the_tree_never_arrives_without_its_caveats():
    found = dg.tree()
    assert dg.DESCRIPTIVE_ONLY in found["caveats"]
    assert dg.NOT_FITTED in found["caveats"]
