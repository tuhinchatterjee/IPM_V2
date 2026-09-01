"""
Natural-language learning questions. §84.

§84's rule is "do not let an LLM invent performance numbers". These tests
check the two halves of that: every number that comes out is traceable to a
stored snapshot, and a question with nothing behind it produces a refusal
rather than a plausible number.
"""

from __future__ import annotations

from backend.continuous import measurement, questions


def _change(before: float, after: float, cases: int = 200,
            **kwargs) -> measurement.Change:
    return measurement.Change(label="d", before=before, after=after,
                              cases=cases, **kwargs)


def _dimension(name: str, dev: tuple[float, float],
               val: tuple[float, float], **kwargs) -> measurement.DimensionResult:
    return measurement.DimensionResult(
        dimension=name, development=_change(*dev), validation=_change(*val),
        **kwargs)


def _facts(**kwargs) -> questions.Facts:
    defaults = dict(
        dimensions=[
            _dimension("Analytical Design", (0.80, 0.86), (0.81, 0.85)),
            _dimension("Judgment & Presentation", (0.75, 0.78), (0.74, 0.76)),
        ],
        quantity={"new_cases": 40, "new_regulatory": 3},
        window_label="since last month",
        baseline_snapshot_id="snap_base", current_snapshot_id="snap_now")
    defaults.update(kwargs)
    return questions.Facts(**defaults)


# --------------------------------------------------------------- the shapes


def test_the_brief_lists_nine_questions_and_nine_are_implemented():
    assert len(questions.SHAPES) == questions.EXPECTED_QUESTIONS == 9
    assert all(shape.builder is not None for shape in questions.SHAPES)


def test_every_canonical_question_matches_its_own_shape():
    for shape in questions.SHAPES:
        matched = questions.match(shape.canonical)
        assert matched is not None, shape.canonical
        assert matched.question_id == shape.question_id


def test_a_question_nobody_planned_for_is_refused_not_approximated():
    """The failure this prevents: a confident paragraph from a near miss."""
    answer = questions.ask("what is the capital of France?", _facts())
    assert answer.answerable is False
    assert "not one of the questions" in answer.headline
    assert len(answer.detail) == 9
    assert "no stored evaluation supports" in answer.caveats[0]


def test_an_empty_question_matches_nothing():
    assert questions.match("") is None
    assert questions.match("   ") is None


def test_the_catalogue_is_what_an_empty_state_can_offer():
    entries = questions.catalogue()
    assert len(entries) == 9
    assert all(e["question"] and e["question_id"] for e in entries)


# ------------------------------------------------------- numbers and sources


def test_every_number_in_an_answer_names_the_snapshot_it_came_from():
    """§84's rule, checked structurally rather than trusted."""
    for shape in questions.SHAPES:
        answer = questions.ask(shape.canonical, _facts(
            brain_lift={"Riyadh": {"validation_points": 1.4,
                                   "verdict": measurement.IMPROVED,
                                   "isolated": True,
                                   "evaluation_id": "eval_7"}},
            pending_activation=[{"id": "L-1", "description": "a fix"}],
            feedback_attribution={"submitted": 12, "became_cases": 4,
                                  "activated": 2}))
        for number in answer.numbers:
            assert number["source"], (shape.question_id, number["label"])


def test_the_answer_says_no_model_produced_any_number_on_it():
    body = questions.ask("How much has CreditProbe improved since last "
                         "month?", _facts()).to_dict()
    assert body["source"] == "persisted snapshots and evaluations"
    assert "no model produced any number" in body["not_generated"]


# --------------------------------------------------- the nine, individually


def test_improvement_since_reports_the_validation_movement():
    answer = questions.ask("How much has CreditProbe improved since last "
                           "month?", _facts())
    assert answer.answerable is True
    assert answer.numbers[0]["unit"] == "percentage points"
    assert answer.basis == ["snap_base", "snap_now"]
    assert "not claim CreditProbe learned" in answer.caveats[0]


def test_improvement_since_refuses_when_nothing_was_measured():
    """A zero here would read as "no improvement", not "never measured"."""
    too_few = measurement.DimensionResult(
        dimension="Analytical Design",
        development=_change(0.8, 0.86, cases=4),
        validation=_change(0.8, 0.86, cases=4))
    answer = questions.ask(
        "How much has CreditProbe improved since last month?",
        _facts(dimensions=[too_few]))
    assert answer.answerable is False
    assert "no improvement" in answer.caveats[0]
    assert answer.missing == ["a validation evaluation in this window"]


def test_what_learned_separates_quantity_from_quality():
    answer = questions.ask("What did CreditProbe learn this week?", _facts())
    assert answer.answerable is True
    assert any("new cases: 40" in line for line in answer.detail)
    assert "Adding cases is not improving" in answer.caveats[0]


def test_best_area_will_not_name_a_winner_when_nothing_went_up():
    answer = questions.ask("Which area improved the most?", _facts(
        dimensions=[_dimension("Analytical Design", (0.86, 0.80),
                               (0.85, 0.80))]))
    assert answer.answerable is True
    assert "No area improved" in answer.headline
    assert answer.numbers == []


def test_best_area_names_the_one_that_moved_furthest_on_validation():
    answer = questions.ask("Which area improved the most?", _facts())
    assert "Analytical Design" in answer.headline


def test_the_imported_brain_question_needs_a_lift_lab_measurement():
    answer = questions.ask("Did the imported Riyadh Brain make us better?",
                           _facts())
    assert answer.answerable is False
    assert "Lift Lab" in answer.missing[0]


def test_the_imported_brain_answer_flags_a_non_isolated_activation():
    answer = questions.ask("Did the imported Riyadh Brain make us better?",
                           _facts(brain_lift={"Riyadh": {
                               "validation_points": 1.4,
                               "verdict": measurement.IMPROVED,
                               "isolated": False}}))
    assert answer.answerable is True
    assert "not attributable to the import alone" in answer.caveats[0]


def test_asking_about_one_dimension_returns_both_partitions():
    answer = questions.ask("Has Judgment & Presentation improved?", _facts())
    assert answer.answerable is True
    labels = [n["label"] for n in answer.numbers]
    assert any("validation" in label for label in labels)
    assert any("development" in label for label in labels)
    assert "the one to believe" in answer.caveats[0]


def test_validation_or_development_reports_the_gap_between_them():
    answer = questions.ask("Did validation improve or only development?",
                           _facts())
    assert answer.answerable is True
    gap = next(n for n in answer.numbers if n["label"] == "Gap")
    assert "overfitting signal" in gap["reads_as"]


def test_cause_of_regression_will_not_claim_a_cause_it_did_not_isolate():
    facts = _facts(dimensions=[
        measurement.DimensionResult(
            dimension="Analytical Design",
            development=_change(0.86, 0.80),
            validation=_change(0.85, 0.79),
            learning_items=("L-12", "L-14"), releases=("rel-9",))])
    answer = questions.ask("What caused Analytical Design to regress?", facts)
    assert answer.answerable is True
    assert "L-12" in answer.detail[0]
    assert "not a proven cause" in answer.caveats[0]
    assert "change-isolation experiment" in answer.caveats[0]


def test_cause_of_regression_says_so_when_nothing_regressed():
    answer = questions.ask("What caused Analytical Design to regress?",
                           _facts())
    assert answer.answerable is True
    assert "did not regress" in answer.headline


def test_cause_of_regression_admits_when_nothing_recorded_the_cause():
    facts = _facts(dimensions=[
        measurement.DimensionResult(
            dimension="Analytical Design",
            development=_change(0.86, 0.80),
            validation=_change(0.85, 0.79))])
    answer = questions.ask("What caused Analytical Design to regress?", facts)
    assert answer.answerable is False
    assert "nothing recorded which learning was responsible" in answer.headline


def test_not_activated_distinguishes_approved_from_live():
    answer = questions.ask("What learning has not yet been activated?",
                           _facts(pending_activation=[
                               {"id": "L-1", "description": "an ECL fix"}]))
    assert answer.answerable is True
    assert "Approved is not activated" in answer.caveats[0]


def test_not_activated_reports_an_empty_queue_as_an_answer():
    answer = questions.ask("What learning has not yet been activated?",
                           _facts())
    assert answer.answerable is True
    assert "Nothing approved is waiting" in answer.headline


def test_my_feedback_reports_capture_without_claiming_improvement():
    answer = questions.ask("How much did my feedback improve CreditProbe?",
                           _facts(feedback_attribution={
                               "submitted": 12, "became_cases": 4,
                               "activated": 2}))
    assert answer.answerable is True
    assert "no measured movement has been attributed" in answer.headline
    assert "Capture is not improvement" in answer.caveats[0]


def test_my_feedback_reports_the_attributed_movement_when_there_is_one():
    answer = questions.ask(
        "How much did my feedback improve CreditProbe?",
        _facts(feedback_attribution={"submitted": 12, "became_cases": 4,
                                     "activated": 2},
               contributions=[measurement.Contribution(
                   source="Feedback fixes", points=1.2, isolated=True,
                   evidence="exp_1")]))
    assert "1.20 pp" in answer.headline
    assert answer.caveats == []


def test_my_feedback_flags_a_share_of_a_joint_effect():
    answer = questions.ask(
        "How much did my feedback improve CreditProbe?",
        _facts(feedback_attribution={"submitted": 12},
               contributions=[measurement.Contribution(
                   source="Feedback fixes", points=1.2, isolated=False)]))
    assert "share of a joint effect" in answer.caveats[0]
