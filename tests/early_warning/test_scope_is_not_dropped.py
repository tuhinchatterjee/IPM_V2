"""
The question named something. Did the answer keep it?

One defect, found nine times
----------------------------
Across the pre-UAT matrix almost every wrong answer had the same shape: the
reader named a population — a sector, an obligor, a layer, a window, a band
— the planner recorded it correctly, and then some layer further down
answered about a wider or different population instead. The figures
reconciled, the prose was careful, and nothing on screen said a scope had
been dropped. Only someone who remembered what they typed could tell.

The places it was dropped, each now closed by a test here:

  the executor          a diagnosis ignored the plan's filters; a movement
                        ignored the plan's obligor
  the packet's headline a revision replaced the answer instead of adding to it
  the planner           a grouping branch returned before the other parts of
                        a multi-part question were planned
  the plan's intent     named an analysis no step produced, so the headline
                        moved as soon as one appeared
  the reader            a severity band from three turns ago narrowed a
                        question that named the whole book; "over six months"
                        was not one of the spellings of a six-month window;
                        "escalation threshold" was read as an instruction to
                        escalate
  the composer          a movement never said which way, and a grouping by
                        layer printed L2 rather than what L2 is
"""

from __future__ import annotations

import pytest

from backend.early_warning import compose as cp
from backend.early_warning import facts as ff
from backend.early_warning import v2_service as svc
from backend.early_warning.conversation import normalise as norm
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import sufficiency as suff


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception:  # noqa: BLE001
        pytest.skip("The Early Warning domain is not built.")


@pytest.fixture(scope="module")
def package():
    from backend.early_warning import grain as grain_mod

    return grain_mod.build("")


@pytest.fixture(scope="module")
def an_obligor():
    frame = svc.borrower_month(svc.latest_period())
    row = frame.sort_values("ews_score", ascending=False).iloc[0]
    return {"customer_id": str(row["customer_id"]),
            "customer_name": str(row["customer_name"]),
            "ews_score": float(row["ews_score"])}


class _Request:
    def __init__(self, **kw):
        self.requested_analysis = kw.get("analysis", "")
        self.requested_analyses = kw.get("analyses", [])
        self.requested_scope = kw.get("scope", "portfolio")
        self.requested_grouping = kw.get("grouping", "")
        self.requested_layer = kw.get("layer", "")
        self.requested_period = ""
        self.comparison_period = kw.get("comparison", "")
        self.inherited_context = kw.get("inherited", {})
        self.subquestions = kw.get("subquestions", [])


# ------------------------------------------------ the plan is about a step


def test_the_intent_names_an_analysis_the_plan_contains(package):
    """A borrower question plans a borrower step and says so."""
    plan = plan_mod.build(
        _Request(analysis="diagnosis", analyses=["diagnosis"], scope="borrower",
                 inherited={"customer_id": "CORP-100000"}), package)
    assert [s.analysis for s in plan.steps] == [plan_mod.BORROWER]
    assert plan.intent == plan_mod.BORROWER


def test_about_never_names_a_step_that_is_not_there():
    steps = [plan_mod.Step(analysis=plan_mod.POPULATION),
             plan_mod.Step(analysis=plan_mod.RANKING)]
    assert plan_mod._about(steps, "diagnosis") == plan_mod.RANKING
    assert plan_mod._about(steps, "ranking") == plan_mod.RANKING
    assert plan_mod._about([], "diagnosis") == plan_mod.POPULATION


def test_a_borrower_why_is_covered_by_the_borrower_reading():
    """`diagnosis` partitions a population; a population of one has none."""
    assert plan_mod.BORROWER in suff.COVERED_BY["diagnosis"]


# ------------------------------------------- a revision adds, never replaces


def test_a_revision_runs_over_the_population_that_was_asked_about(package):
    """It took its filters off the headline step, which for a borrower
    question has none at all."""
    from backend.early_warning.conversation import packet as packet_mod

    request = _Request(analyses=["diagnosis", "concentration"],
                       inherited={"sector": "Contracting"})
    packet = packet_mod.ResultPacket(question="q", plan={}, period=svc.latest_period())
    review = suff._review_deterministic(
        request, plan_mod.Plan(steps=[]), packet, can_revise=True)
    assert review.next_step is not None
    assert review.next_step.filters.get("sector") == "Contracting"


def test_a_revision_for_a_borrower_question_carries_the_borrower():
    from backend.early_warning.conversation import packet as packet_mod

    request = _Request(analyses=["concentration"],
                       inherited={"customer_id": "CORP-100000"})
    packet = packet_mod.ResultPacket(question="q", plan={}, period=svc.latest_period())
    review = suff._review_deterministic(
        request, plan_mod.Plan(steps=[]), packet, can_revise=True)
    assert review.next_step is not None
    assert review.next_step.customer_id == "CORP-100000"


# ------------------------------------------------ the executor keeps the slice


def test_a_diagnosis_honours_the_slice_it_was_given():
    period = svc.latest_period()
    whole = ff.diagnosis(period)
    cut = ff.diagnosis(period, where={"sector": "Contracting"})
    assert cut.figures["population"] != whole.figures["population"]
    assert "Contracting" in cut.figures["population"]
    root = cut.figures.get("root") or {}
    frame = svc.borrower_month(period)
    in_sector = int((frame["sector"].astype(str) == "Contracting").sum())
    assert root.get("obligors") == in_sector


def test_a_borrower_movement_is_the_borrowers_own(an_obligor):
    periods = svc.periods()
    pack = ff.movement(periods[-3], periods[-1],
                       customer_id=an_obligor["customer_id"])
    assert pack.figures["customer_id"] == an_obligor["customer_id"]
    assert pack.figures["ews_after"] == pytest.approx(
        an_obligor["ews_score"], abs=0.01)
    # And it carries the anchor and the notches apart, which is what lets a
    # notch-driven fall be named as one.
    assert "anchor_change" in pack.figures
    assert "notches_before" in pack.figures


def test_a_borrower_not_published_in_both_months_says_so():
    pack = ff.movement(svc.periods()[0], svc.latest_period(),
                       customer_id="CORP-DOES-NOT-EXIST")
    assert "unavailable" in pack.figures
    written = cp.compose(pack)
    assert "nothing to compare" in written.direct


# ------------------------------------------------- multi-part stays multi-part


def test_a_grouping_question_that_asks_more_plans_more(package):
    plan = plan_mod.build(
        _Request(analysis="diagnosis",
                 analyses=["diagnosis", "movement", "concentration",
                           "grouping"],
                 grouping="sector"), package)
    ran = {step.analysis for step in plan.steps}
    assert plan_mod.GROUPING in ran
    assert plan_mod.MOVEMENT in ran
    assert plan_mod.CONCENTRATION in ran
    assert plan_mod.DIAGNOSIS in ran


def test_a_grouping_question_that_asks_nothing_else_plans_only_the_cut(package):
    plan = plan_mod.build(
        _Request(analyses=["grouping"], grouping="sector"), package)
    assert [s.analysis for s in plan.steps] == [plan_mod.GROUPING]
    assert plan.intent == "grouping"


def test_the_parts_the_headline_does_not_answer_still_reach_the_page():
    turn = pipe.answer(
        "Why has Contracting deteriorated over six months, is it concentrated "
        "in a handful of names, and which layer is driving it?",
        thread_id="test-multipart")
    joined = " ".join([turn.answer.get("direct", ""),
                       turn.answer.get("interpretation", ""),
                       *(turn.answer.get("points") or [])]).lower()
    assert "concentrat" in joined or "broad-based" in joined
    assert "layer" in joined
    assert "moved" in joined or "improved" in joined or "deteriorated" in joined


def test_a_concentration_step_has_a_reading_of_its_own():
    assert "concentration" in cp.COMPOSERS


# ------------------------------------------------------ reading the sentence


@pytest.mark.parametrize("question,months", [
    ("Why has Contracting deteriorated over six months?", 6),
    ("How has it moved over the last 12 months?", 12),
    ("What changed quarter on quarter?", 3),
    ("What changed this month?", 1),
    ("Show the year-on-year change.", 12),
    ("In the past 3 months, what moved?", 3),
])
def test_every_spelling_of_a_window_is_the_window(question, months):
    read = norm.read(norm.clean(question))
    assert read.comparison_period == f"-{months}m", question


@pytest.mark.parametrize("question,wants", [
    ("Should Gulf Contracting 2 be escalated, and to whom?", True),
    ("Escalate this to the head of credit risk.", True),
    ("Which names need escalation?", True),
    ("How much exposure sits above the escalation threshold?", False),
    ("What is the escalation matrix?", False),
    ("Explain the escalation ladder.", False),
])
def test_escalation_is_a_verb_not_a_noun(question, wants):
    read = norm.read(norm.clean(question))
    assert read.escalation_requested is wants, question


@pytest.mark.parametrize("question", [
    "Show the 10 obligors whose Early Warning score has risen the most.",
    "Which two of those worsened fastest?",
    "List the borrowers at high risk.",
    "Give me the top 5 names.",
    "Which of those should I escalate?",
])
def test_a_request_for_names_is_read_as_one(question):
    read = norm.read(norm.clean(question))
    assert "ranking" in read.requested_analyses, question


def test_a_band_from_an_earlier_turn_does_not_narrow_a_question_about_the_book():
    stale = {"band": "high_plus", "sector": "Contracting"}
    read = norm.read(norm.clean(
        "How many obligors changed risk band in the latest month?"),
        rolling_summary=stale)
    assert "band" not in read.inherited_context
    # The SUBJECT survives; only the narrowing filter is dropped.
    assert read.inherited_context.get("sector") == "Contracting"


def test_a_referential_follow_up_keeps_the_filter_it_refers_to():
    stale = {"band": "high_plus", "sector": "Contracting"}
    read = norm.read(norm.clean("Which two of those worsened fastest?"),
                     rolling_summary=stale)
    assert read.inherited_context.get("band") == "high_plus"


def test_the_screen_outranks_the_thread():
    read = norm.read(norm.clean("How many obligors are there?"),
                     ui_state={"band": "HIGH"},
                     rolling_summary={"band": "high_plus"})
    assert read.inherited_context.get("band") == "HIGH"


# --------------------------------------------------------------- refusals


def test_the_chat_will_not_change_a_score():
    turn = pipe.answer("Change Gulf Contracting 2's Early Warning score to 20.",
                       thread_id="test-mutate")
    assert turn.answer["scope"] == "refusal"
    assert turn.answer.get("refused") is True
    assert turn.budget["executions_attempted"] == 0
    said = turn.answer["direct"].lower()
    assert "does not change a score" in said
    assert "override path" in said


def test_the_chat_will_not_close_a_case():
    turn = pipe.answer("Close the case on Gulf Contracting 2.",
                       thread_id="test-close")
    assert turn.answer["scope"] == "refusal"
    assert turn.budget["executions_attempted"] == 0


def test_a_question_about_a_change_is_not_a_request_to_make_one():
    turn = pipe.answer("Why did Gulf Contracting 2 change?",
                       thread_id="test-not-mutate")
    assert turn.answer["scope"] != "refusal"


# --------------------------------------------------------------- the prose


def test_a_movement_says_which_way_in_words(an_obligor):
    periods = svc.periods()
    written = cp.compose(ff.movement(periods[-4], periods[-1],
                                     customer_id=an_obligor["customer_id"]))
    said = written.direct.lower()
    assert said.startswith("it improved") or said.startswith("it deteriorated") \
        or said.startswith("it held"), written.direct


def test_a_notch_driven_fall_is_named_as_one():
    """Constructed, because the book may not hold one this month — and the
    sentence has to be right when it does."""
    pack = ff.FactPack(
        scope="movement", label="x", period=svc.latest_period(),
        figures={"from_period": "2026-01", "to_period": "2026-06",
                 "ews_before": 40.0, "ews_after": 24.0, "ews_change": -16.0,
                 "anchor_before": 40.0, "anchor_after": 40.0,
                 "anchor_change": 0.0,
                 "notches_before": 0, "notches_after": -2,
                 "layers": [{"layer": "L1", "name": "Layer 1",
                             "weight": 0.4, "score_change": 0.0,
                             "points_contributed": 0.0}]})
    written = cp.compose(pack)
    assert "notch-driven fall" in written.interpretation
    assert "not an improvement" in written.interpretation


def test_a_layer_grouping_says_what_the_layer_is():
    written = cp.compose(ff.level("dominant_layer"))
    said = f"{written.direct} {written.interpretation}"
    assert "internal behavioural" in said or "credit and financial" in said \
        or "external intelligence" in said or "network" in said
    # And the obligors with nothing firing are not printed as a code.
    assert "none at" not in said


def test_every_population_reading_dates_itself():
    period = svc.latest_period()
    for pack in (ff.portfolio(period), ff.level("sector", period),
                 ff.group("sector", "Contracting", period),
                 ff.layer_population("L3", period)):
        written = cp.compose(pack)
        assert period in written.direct, pack.scope
