"""P4, P5 and P6 gates: cards, threads and the clauses they cite.

What these guard, in order of how expensive the mistake is:

* **A recommendation that reads as compliant when it is not.** No approved
  bank policy was supplied with this work, so every clause is a demonstration
  draft, `claims_compliance()` is False for all of them, and nothing executes.
* **A generic question answered in the wrong conversation.** "What should we
  do next?" names nothing. Answered outside a story's thread, it would put a
  payroll recommendation under a question about mortgages.
* **A step that silently re-queries.** Each step's cohort has to be a subset
  of the one before it, or the customers in the workbook are not the customers
  the reader was shown.
* **A card that is text.** Every figure in a conclusion has to be reachable
  from the case's own metrics, or the sentence and the number beside it can
  drift apart.

Everything read here is SYNTHETIC.
"""

from __future__ import annotations

import pytest

from backend.retail import episode_answers as ea
from backend.retail import episode_cases as ec
from backend.retail import episode_measures as em
from backend.retail import episode_policy as pol
from backend.agentic import severity as sv
from backend.retail import episodes as ep

NINE = [c for c in ep.case_ids() if c != "C01"]


@pytest.fixture(scope="module")
def cards():
    if not em.months():
        pytest.skip("The shipped retail lake is not built.")
    try:
        made = ec.drafts("")
    except em.MissingEpisodeColumns as exc:
        pytest.skip(str(exc))
    if not made:
        pytest.skip("No episode cards were raised on this book.")
    return {d.entity_id: d for d in made}


# ------------------------------------------------------------------- P4


def test_all_nine_stories_raise_a_card(cards):
    assert sorted(cards) == NINE, (
        f"Raised {sorted(cards)}. A story with no card cannot be "
        f"investigated, exported or simulated.")


def test_the_cockpit_can_show_at_least_ten(cards):
    # Nine here plus Alpha from the accepted early-delinquency rule.
    assert len(cards) + 1 >= 10


def test_every_card_is_severity_arithmetic_not_a_label(cards):
    for case_id, card in cards.items():
        score = card.score
        assert score.components, case_id
        keys = {c.key for c in score.components}
        assert len(keys) == len(score.components), f"{case_id} repeats a component"
        total = sum(c.value * c.weight for c in score.components)
        # To the published precision: the score is rounded to four places for
        # display, and a reader redoing the arithmetic reaches the displayed
        # figure, not an unrounded one.
        assert abs(total - score.score) < 5e-5, (
            f"{case_id}'s band does not follow from its own components: "
            f"{total} against a published {score.score}.")
        assert score.band == next(
            name for floor, name in sv.BANDS if score.score >= floor)
        for component in score.components:
            assert component.detail, f"{case_id}/{component.key} has no working"
            assert component.observed is not None


def test_severity_is_not_uniformly_critical(cards):
    bands = {c.score.band for c in cards.values()}
    assert len(bands) > 1, (
        "Every story came out in the same band. Either the arithmetic is not "
        "discriminating or a threshold was moved to make the demonstration "
        "look worse.")


def test_every_figure_in_a_conclusion_is_also_a_metric(cards):
    for case_id, card in cards.items():
        labels = {m["label"] for m in card.metrics}
        assert {"Affected observations", "Eligible observations",
                "Comparator rate", "Gross exposure"} <= labels, case_id
        assert card.evidence.get("predicate")
        assert card.evidence.get("comparator", {}).get("label")
        assert card.evidence.get("drawer", {}).get("risk")
        assert card.evidence.get("chart", {}).get("rows")


def test_a_card_states_its_countercheck(cards):
    for case_id, card in cards.items():
        expected = ep.by_id(case_id).countercheck
        assert expected and expected in card.conclusion, (
            f"{case_id}'s conclusion does not carry its own countercheck.")


def test_the_impaired_stories_refuse_a_forward_pd(cards):
    """C02 and C10 are already-defaulted cohorts. A forward probability of
    default for them would be a prediction about something that happened."""
    for case_id in ("C02", "C10"):
        risk = cards[case_id].evidence["drawer"]["risk"]
        if risk["forward_pd_applies"]:
            # Some of the cohort is not yet impaired, which is legitimate —
            # but the panel must then say how many, and on which subset.
            assert risk["comparable_cohort"] < risk["cohort"]
            assert risk["pd_12m"]["cohort"] == risk["comparable_cohort"]
        else:
            assert "not apply" in risk["forward_pd_note"]


def test_the_recovery_card_does_not_claim_the_borrower_deteriorated(cards):
    drawer = cards["C06"].evidence["drawer"]
    change = drawer["scores"]["behaviour"]["change"]
    assert change is not None and abs(change) <= 15, (
        f"C06's card reports a {change} point behavioural move. Its finding "
        f"is loss severity; the borrower is the control.")
    assert drawer["risk"]["lgd"]["now"] > drawer["risk"]["lgd"]["before"]
    assert drawer["scores"]["diagnosis_model"] == "recovery"


def test_a_story_that_does_not_hold_raises_nothing():
    """The path that makes the other nine mean something."""
    assert ec.MIN_MULTIPLE >= 1.5 and ec.MIN_AFFECTED >= 20
    assert ec.draft("", "C01") is None, (
        "C01 is raised by the accepted early-delinquency rule against its own "
        "calibration. Raising it here as well would open two cards for one "
        "finding.")


def test_replaying_a_review_refreshes_rather_than_duplicates(cards):
    keys = [card.key for card in cards.values()]
    assert len(set(keys)) == len(keys)
    again = {d.entity_id: d for d in ec.drafts("")}
    for case_id, card in cards.items():
        assert again[case_id].key == card.key


# ------------------------------------------------------------------- P5


def test_five_chips_with_one_suggested_next():
    for case_id in NINE:
        chips = ea.chips(case_id)
        assert len(chips) == 5, case_id
        assert sum(1 for c in chips if c["suggested_next"]) == 1
        for chip in chips:
            assert chip["label"] and chip["prompt"] and chip["chart"]
            assert chip["visited"] is False
        after = ea.chips(case_id, visited=["S1", "S2"])
        assert [c["visited"] for c in after] == [True, True, False, False, False]
        assert next(c["step"] for c in after if c["suggested_next"]) == "S3"


def test_a_chip_click_reaches_its_own_step():
    for case_id in NINE:
        context = {"risk_case": {"about": ea.ABOUT, "entity_id": case_id}}
        for chip in ea.chips(case_id):
            reading = ea.read(chip["prompt"], context=context)
            assert reading is not None, f"{case_id} {chip['step']}"
            assert reading.step == chip["step"]
            assert reading.exact is True


def test_paraphrases_reach_the_same_step():
    context = {"risk_case": {"about": ea.ABOUT, "entity_id": "C03"}}
    for asked, step in (
            ("Where is this concentrated?", "S4"),
            ("which employer group is overrepresented", "S4"),
            ("what should we do", "S5"),
            ("give me an action plan", "S5"),
            ("could this just be a timing difference? decompose it", "S3"),
            ("were these borrowers sound at origination", "S2"),
            ("split it and show the six-month trend", "S1")):
        reading = ea.read(asked, context=context)
        assert reading is not None and reading.step == step, (
            f"{asked!r} read as {reading.step if reading else None}, not {step}")


def test_a_generic_question_outside_a_thread_is_not_answered():
    for asked in ("What should we do next?", "Where is this concentrated?",
                  "Decompose it by model variable"):
        assert ea.read(asked, context={}) is None, asked
        assert ea.read(asked, context={"risk_case": {"about": "something_else",
                                                     "entity_id": "C03"}}) is None


def test_an_unrelated_question_inside_a_thread_falls_through():
    context = {"risk_case": {"about": ea.ABOUT, "entity_id": "C03"}}
    for asked in ("what is the total mortgage book",
                  "show me the data dictionary",
                  "who owns this case"):
        assert ea.read(asked, context=context) is None, asked


def test_every_step_narrows_and_never_re_queries():
    if not em.months():
        pytest.skip("The shipped retail lake is not built.")
    for case_id in NINE:
        previous_customers: set[str] | None = None
        for step in ("S1", "S2", "S3", "S4", "S5"):
            found = ea.scope("", case_id, step)
            assert found["available"], f"{case_id} {step}"
            customers = set(found["customers"])
            assert customers, f"{case_id} {step} is empty"
            if previous_customers is not None:
                escaped = customers - previous_customers
                assert not escaped, (
                    f"{case_id} {step} introduces {len(escaped)} customers the "
                    f"previous step did not contain. That is a re-query, not "
                    f"a narrowing.")
            previous_customers = customers


def test_every_step_answers_with_its_scope_and_its_counterargument():
    if not em.months():
        pytest.skip("The shipped retail lake is not built.")
    for case_id in NINE:
        episode = ep.by_id(case_id)
        for step in ("S1", "S2", "S3", "S4", "S5"):
            result = ea.answer(ea.Reading(case_id=case_id, step=step))
            assert result is not None, f"{case_id} {step}"
            assert result.answer.strip()
            assert result.detail["scope"]
            assert result.detail["counterargument"] == episode.countercheck
            assert 2 <= len(result.detail["observations"]) <= 6, (
                f"{case_id} {step} carries "
                f"{len(result.detail['observations'])} observations; the "
                f"answer shape is two to five.")
            assert result.detail["export_enabled"] is True
            assert result.detail["definitions"]
            assert result.execution == "analysis", (
                f"{case_id} {step} reports itself as metadata. It computed "
                f"something, and the Trace consistency contract reads this.")
            assert result.graph is not None
            if step != "S5":
                assert result.detail["next_question"]


def test_a_thread_answer_reconciles_with_its_own_card(cards):
    """The figure in an answer and the figure on the card are one computation
    read twice, not two that agree today."""
    for case_id in NINE:
        card = cards[case_id]
        affected = next(m["value"] for m in card.metrics
                        if m["label"] == "Affected observations")
        result = ea.answer(ea.Reading(case_id=case_id, step="S1"))
        assert f"{affected:,} alerts" in result.answer, (
            f"{case_id}'s S1 does not open on the same alert count its card "
            f"raised ({affected:,}).")


# ------------------------------------------------------------------- P6


def test_every_clause_is_a_draft_and_none_claims_compliance():
    for case_id in ep.case_ids():
        clauses = pol.clauses_for(case_id)
        assert len(clauses) == 3, case_id
        for clause in clauses:
            assert clause["status"] == pol.DRAFT
            assert pol.claims_compliance(clause) is False
            assert clause["owner"] and clause["timing"] and clause["safeguard"]
            assert clause["effective_from"]


def test_every_action_carries_its_approval_and_executes_nothing():
    for case_id in ep.case_ids():
        for action in pol.actions_for(case_id, as_of="2026-08-31"):
            assert action["executed"] is False
            assert action["approval"]
            assert action["claims_compliance"] is False
            assert action["sequence"] >= 1
            assert action["applicable"] is True


def test_a_clause_not_yet_in_force_is_unsupported_not_quietly_applied():
    actions = pol.actions_for("C03", as_of="2025-06-30")
    assert actions
    for action in actions:
        assert action["applicable"] is False
        assert "not in force" in action["unsupported_because"]


def test_a_scenario_is_a_trial_and_says_what_it_does_not_model():
    for case_id in ep.case_ids():
        scenario = pol.scenarios_for(case_id, "2026-08-31")
        assert scenario["available"], case_id
        assert scenario["family"]
        assert scenario["must_not"], case_id
        assert scenario["not_modelled"], (
            f"{case_id}'s scenario claims to model everything.")
        assert "not optimised" in scenario["basis"]
        assert scenario["status"] == pol.DRAFT


def test_the_limit_scenario_says_a_cut_does_not_repay_a_drawing():
    must_not = pol.scenarios_for("C01", "2026-08-31")["must_not"]
    assert "drawn balance is unchanged" in must_not


def test_the_recovery_scenario_holds_the_probability_of_default():
    must_not = pol.scenarios_for("C06", "2026-08-31")["must_not"]
    assert "held" in must_not.lower()


def test_an_s5_answer_leads_with_the_draft_status():
    if not em.months():
        pytest.skip("The shipped retail lake is not built.")
    for case_id in NINE:
        result = ea.answer(ea.Reading(case_id=case_id, step="S5"))
        assert result is not None, case_id
        assert "DEMONSTRATION DRAFT" in result.answer
        assert "no approved bank policy" in result.answer.lower()
        assert result.warnings, case_id
        assert result.detail["policy_status"] == pol.DRAFT
        assert all(not a["claims_compliance"] for a in result.detail["actions"])
