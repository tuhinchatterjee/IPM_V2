"""
§90-§94 — selection, escalation policy, the investigation DAG, completion
rules and the presentability rubric.

What these five have in common
-------------------------------
Each one refuses something a system without it does silently. A click that
means nothing in particular. An escalation to the expensive model before the
cheap engine ran. Two runs of the same analysis producing two numbers. A
polished answer from an investigation that half-failed. A repetitive answer
withheld and an ungrounded one shown, because one threshold governed both.
"""

from __future__ import annotations

import pytest

from backend.judgment import judgment_policy as jp
from backend.judgment import presentability as pb
from backend.judgment import selection as se
from backend.judgment import task_dag as td
from backend.judgment import visual_grammar as vg
from backend.llm import roles as rl
from backend.orchestration import scope as sc


def _source(**over) -> se.Source:
    base = dict(run_id="run-1", chart=vg.HORIZONTAL_BAR,
                entities=["cust-1", "cust-2"],
                categories=["Contracting", "Real Estate"],
                periods=["Q1 2026", "Q2 2026"],
                metrics=["expected credit loss", "EAD"],
                series=["Stage 2", "Stage 3"], entity_key="customer_id")
    base.update(over)
    return se.Source(**base)


# =========================================== §90 interactive selection


def test_a_selection_carries_all_nine_fields_section_90_names():
    assert len(se.FIELDS) == 9
    payload = se.Selection().to_dict()
    for name in se.FIELDS:
        assert name in payload


def test_a_click_records_the_period_and_the_measure_not_only_the_category():
    """A selection that recorded "Contracting" and lost the period produces a
    follow-up about the right sector in the wrong quarter, which reads as a
    data error and is not one."""
    chosen = se.capture(_source(), category="Contracting", period="Q2 2026",
                        metric="expected credit loss",
                        category_field="sector")

    assert chosen.selected_category == "Contracting"
    assert chosen.selected_period == "Q2 2026"
    assert chosen.selected_metric == "expected credit loss"
    assert chosen.source_run_id == "run-1"
    assert chosen.selected_filters == [{"field": "sector",
                                        "value": "Contracting"}]


def test_a_selection_cannot_name_something_the_run_did_not_return():
    """A click that names an entity the chart did not show is a filter
    invented at the browser and applied to data the reader was not looking
    at."""
    with pytest.raises(se.OutsideRun):
        se.capture(_source(), category="Aviation")
    with pytest.raises(se.OutsideRun):
        se.capture(_source(), entities=["cust-99"])
    with pytest.raises(se.OutsideRun):
        se.capture(_source(), period="Q4 2019")


def test_a_dragged_region_becomes_a_range_in_the_measures_units():
    chosen = se.capture(_source(chart=vg.SCATTER), metric="EAD", low=100.0,
                        high=500.0)

    assert chosen.selected_range.metric == "EAD"
    assert chosen.selected_range.low == 100.0
    assert "EAD between 100.0 and 500.0" in chosen.line()


def test_a_selection_narrows_through_the_same_scope_machinery_as_a_sentence():
    """Two paths to the same scope change would drift, and the one that
    drifted would be the one nobody typed."""
    before = sc.ScopeFrame(population="the whole portfolio",
                           metrics=["expected credit loss"], period="Q1 2026")
    chosen = se.capture(_source(), category="Contracting", period="Q2 2026",
                        category_field="sector")

    change = se.delta(before, chosen, _source())

    assert isinstance(change, sc.Delta)
    assert change.kind == sc.NARROW
    assert change.after.filters == [{"field": "sector",
                                     "value": "Contracting"}]


def test_a_selected_period_replaces_the_window_rather_than_extending_it():
    """The reader clicked one quarter. Carrying the old opening date forward
    would answer about a span they did not select."""
    before = sc.ScopeFrame(opening="Q1 2025", closing="Q1 2026")
    chosen = se.capture(_source(), period="Q2 2026")

    after = se.narrow(before, chosen, _source())

    assert after.period == "Q2 2026"
    assert after.opening == "" and after.closing == ""


def test_selected_entities_replace_the_carried_population():
    before = sc.ScopeFrame(entity_key="customer_id",
                           entity_ids=["a", "b", "c"], top_n=10)
    chosen = se.capture(_source(), entities=["cust-1"])

    after = se.narrow(before, chosen, _source())

    assert after.entity_ids == ["cust-1"]
    assert after.entity_key == "customer_id"
    assert after.top_n == 0


def test_ask_about_this_stays_in_the_same_investigation():
    before = sc.ScopeFrame(population="the whole portfolio")
    chosen = se.capture(_source(), category="Contracting")

    followed = se.ask("why did this move?", "inv-9", chosen, before,
                      _source())

    assert followed.investigation_id == "inv-9"
    assert followed.to_dict()["same_investigation"] is True

    with pytest.raises(ValueError):
        se.ask("why?", "", chosen, before, _source())


def test_the_selection_and_the_scope_delta_are_traced_together():
    """A reader who sees that the scope narrowed and cannot see what was
    clicked has been told that something happened."""
    before = sc.ScopeFrame(population="the whole portfolio")
    chosen = se.capture(_source(), category="Contracting",
                        category_field="sector")

    node = se.ask("why?", "inv-9", chosen, before, _source()).trace_node()

    assert node["type"] == "interactive_selection"
    assert node["selection"]["selected_category"] == "Contracting"
    assert node["scope_delta"]["kind"] == sc.NARROW
    assert node["source_run_id"] == "run-1"


def test_every_chart_says_what_a_click_on_it_means():
    """It differs: a bar is one category, a heatmap cell is a category AND a
    period, a scatter drag is a range of two measures."""
    for chart in vg.CHARTS:
        assert se.MEANS[chart].strip(), chart


# ============================================= §91 the judgment policy


def test_the_ten_situations_section_91_names_all_have_a_role_and_a_reason():
    assert len(jp.SITUATIONS) == 10
    for situation in jp.SITUATIONS:
        assert jp.ROLE_FOR[situation] in rl.ROLES, situation
        assert len(jp.BECAUSE[situation]) > 40, situation
        assert situation in jp.REQUIRES_FIRST


def test_no_model_id_is_decided_here():
    """§91: do not hard-code model IDs. The role is named; the model behind
    it is configuration, and a module that named one would be wrong the week
    after the next model ships."""
    source = jp.policy()
    assert source["roles_named_not_models"] is True
    for situation in jp.SITUATIONS:
        role = jp.ROLE_FOR[situation]
        assert "claude" not in role.lower()
        assert "opus" not in role.lower()
        assert "sonnet" not in role.lower()


def test_escalation_before_the_deterministic_engine_ran_is_refused():
    """A model asked to work out whether a movement is broad will answer,
    plausibly, from nothing."""
    with pytest.raises(jp.EngineFirst):
        jp.escalate(jp.ECL_SYNTHESIS, engines_run=[])
    with pytest.raises(jp.EngineFirst):
        jp.escalate(jp.CONTRADICTION_SYNTHESIS, engines_run=["breadth"])

    ok = jp.escalate(jp.CONTRADICTION_SYNTHESIS,
                     engines_run=["contradiction_diagnostics"],
                     fact_ids=["f1"])
    assert ok.role == rl.COMPLEX_PLANNER


def test_raw_rows_are_refused_rather_than_trimmed():
    """A package silently stripped of its rows would let a caller go on
    sending them."""
    with pytest.raises(jp.RawData):
        jp.escalate(jp.CHALLENGE_PASS, engines_run=["hypothesis_tree"],
                    rows=[{"customer_id": i} for i in range(5000)])


def test_a_package_larger_than_a_summary_is_refused():
    with pytest.raises(jp.RawData):
        jp.escalate(jp.CHALLENGE_PASS, engines_run=["hypothesis_tree"],
                    fact_ids=[f"f{i}" for i in range(jp.MAX_FACTS + 1)])


def test_an_unknown_situation_does_not_escalate():
    """The alternative — any string escalating — makes the policy a list of
    examples rather than a policy."""
    assert jp.applies("something_that_feels_important") is False
    with pytest.raises(KeyError):
        jp.escalate("something_that_feels_important", engines_run=[])


def test_the_challenge_pass_and_the_rubric_repair_go_to_the_critic():
    """The challenge pass exists to find what the analysis assumed, and a
    model that shares the assumption will not find it."""
    assert jp.ROLE_FOR[jp.CHALLENGE_PASS] == rl.CRITIC
    assert jp.ROLE_FOR[jp.RUBRIC_REPAIR] == rl.CRITIC


# =============================================== §92 the investigation DAG


def _dag() -> td.Dag:
    dag = td.Dag(investigation_id="inv-1", blueprint_id="bp-segment")
    dag.add(td.Task("t1", td.SCOPE, objective="pin the population",
                    method="scope"))
    dag.add(td.Task("t2", td.ANALYSIS, objective="ecl by sector",
                    method="aggregate", dependencies=["t1"]))
    dag.add(td.Task("t3", td.DRIVER, objective="decompose the ecl movement",
                    method="decomposition", dependencies=["t2"]))
    dag.add(td.Task("t4", td.CHALLENGE, objective="decompose the ecl movement",
                    method="decomposition", dependencies=["t3"],
                    differs_because="decomposed in the reverse order, which "
                                    "must give the same answer"))
    dag.add(td.Task("t5", td.SYNTHESIS, objective="say what it means",
                    method="synthesis", dependencies=["t3", "t4"]))
    return dag.seal()


def test_the_twelve_task_types_section_92_names_all_have_a_meaning():
    assert len(td.TASK_TYPES) == 12
    for task_type in td.TASK_TYPES:
        assert td.TYPE_MEANS[task_type].strip(), task_type


def test_a_task_persists_everything_section_92_lists():
    dag = _dag()
    dag.record("t1", td.COMPLETED, result={"rows": 8}, facts=["f1"],
               observations=["o1"], duration_ms=120, validation="PASSED")

    payload = dag.get("t1").to_dict()
    for key in ("task_id", "task_type", "objective", "method", "dependencies",
                "result", "fact_ids", "observations" if False else
                "observation_ids", "status", "duration_ms", "budget_ms",
                "validation"):
        assert key in payload, key


def test_a_task_is_not_handed_out_before_its_inputs_exist():
    """The whole reason this is a graph: a breadth verdict computed before
    the decomposition ran is a breadth verdict over nothing, and a list of
    steps executed in the wrong order looks identical afterwards."""
    dag = _dag()

    assert [t.task_id for t in dag.ready()] == ["t1"]
    dag.record("t1", td.COMPLETED)
    assert [t.task_id for t in dag.ready()] == ["t2"]
    dag.record("t2", td.COMPLETED)
    assert [t.task_id for t in dag.ready()] == ["t3"]


def test_a_duplicate_analysis_is_refused():
    """Two runs of the same analysis can DISAGREE, and then two numbers are
    on screen with nothing saying which is the answer."""
    dag = td.Dag()
    dag.add(td.Task("a", td.ANALYSIS, objective="ecl by sector",
                    method="aggregate"))

    with pytest.raises(td.Duplicate):
        dag.add(td.Task("b", td.ANALYSIS, objective="ecl by sector",
                        method="aggregate"))


def test_a_challenge_method_may_repeat_one_and_must_say_how_it_differs():
    """The challenge pass exists to compute the same thing another way, and
    refusing it would refuse the control."""
    dag = td.Dag()
    dag.add(td.Task("a", td.ANALYSIS, objective="ecl by sector",
                    method="aggregate"))

    with pytest.raises(td.Duplicate):
        dag.add(td.Task("b", td.CHALLENGE, objective="ecl by sector",
                        method="aggregate", dependencies=["a"]))

    dag.add(td.Task("c", td.CHALLENGE, objective="ecl by sector",
                    method="aggregate", dependencies=["a"],
                    differs_because="aggregated from facility level rather "
                                    "than from the sector rollup"))
    assert dag.get("c").differs_because


def test_a_task_that_needs_input_cannot_have_none():
    """A DAG permitting a SYNTHESIS with no inputs permits an investigation
    that concluded before it analysed."""
    dag = td.Dag()
    with pytest.raises(td.UnknownDependency):
        dag.add(td.Task("s", td.SYNTHESIS, objective="conclude",
                        method="synthesis"))


def test_a_dependency_on_something_absent_is_refused():
    dag = td.Dag()
    with pytest.raises(td.UnknownDependency):
        dag.add(td.Task("a", td.ANALYSIS, objective="o", method="m",
                        dependencies=["nowhere"]))


def test_a_cycle_is_refused_at_seal():
    dag = td.Dag()
    dag.add(td.Task("a", td.SCOPE, objective="a", method="m"))
    dag.add(td.Task("b", td.ANALYSIS, objective="b", method="m",
                    dependencies=["a"]))
    dag.get("a").dependencies = ["b"]

    with pytest.raises(td.Cycle):
        dag.seal()


def test_the_dag_is_bounded_and_cannot_grow_while_running():
    """An investigation that can add work while running can run forever, and
    the version that runs forever in front of a client is the one that
    matters."""
    dag = _dag()

    with pytest.raises(ValueError):
        dag.add(td.Task("t6", td.ANALYSIS, objective="one more thing",
                        method="aggregate", dependencies=["t1"]))


def test_a_failed_task_blocks_everything_downstream():
    """The alternative is a synthesis over a hole."""
    dag = _dag()
    dag.record("t1", td.COMPLETED)
    dag.record("t2", td.FAILED)

    assert dag.get("t3").status == td.BLOCKED
    assert dag.get("t5").status == td.BLOCKED
    assert dag.ready() == []


def test_unavailable_is_not_failed_and_must_say_what_was_missing():
    """A missing covenant dataset is not a defect in CreditProbe, and §93
    lets an objective be "explicitly unavailable" — 'explicitly' being the
    whole of it."""
    dag = _dag()
    with pytest.raises(ValueError):
        dag.record("t1", td.UNAVAILABLE)

    dag.record("t1", td.UNAVAILABLE,
               note="the covenant dataset has no data after Q4 2025")
    assert dag.get("t1").satisfied is True
    assert [t.task_id for t in dag.ready()] == ["t2"]


def test_over_budget_tasks_are_visible():
    dag = _dag()
    dag.get("t1").budget_ms = 100
    dag.record("t1", td.COMPLETED, duration_ms=900)

    assert dag.get("t1").over_budget is True
    assert dag.to_dict()["over_budget"] == ["t1"]


# ================================================ §93 completion rules


def _complete(dag: td.Dag) -> td.Completion:
    for task in dag.tasks:
        if task.status != td.COMPLETED:
            dag.record(task.task_id, td.COMPLETED)
    return td.completion(dag, hypotheses_recorded=True,
                         validations_passed=True, facts=6, grounded=True,
                         visual_approved=True, limitations=2,
                         trace_consistent=True)


def test_the_nine_conditions_section_93_names_are_all_checked():
    assert len(td.CONDITIONS) == 9
    for condition in td.CONDITIONS:
        assert td.CONDITION_ASKS[condition].endswith("?")


def test_an_investigation_that_did_everything_may_be_presented():
    result = _complete(_dag())

    assert result.complete is True
    assert result.unmet == []
    assert "may be presented" in result.sentence()


def test_nothing_defaults_to_true():
    """An unchecked condition is an unmet one, which is the rule the whole
    assurance machinery runs on."""
    dag = _dag()
    for task in dag.tasks:
        dag.record(task.task_id, td.COMPLETED)

    result = td.completion(dag)

    assert result.complete is False
    assert set(result.unmet) == set(td.CONDITIONS) - {td.OBJECTIVES,
                                                      td.CHALLENGED}


def test_no_polished_answer_from_a_half_failed_investigation():
    """The tempting behaviour is to show what did work and quietly omit what
    did not, and it is tempting because the partial answer is often genuinely
    useful. It is still an answer whose gaps are invisible."""
    dag = _dag()
    dag.record("t1", td.COMPLETED)
    dag.record("t2", td.FAILED)

    result = td.completion(dag, hypotheses_recorded=True,
                           validations_passed=True, facts=6, grounded=True,
                           visual_approved=True, limitations=2,
                           trace_consistent=True)

    assert result.complete is False
    assert td.OBJECTIVES in result.unmet
    assert "did not finish" in result.sentence()
    assert "findings rather than as an answer" in result.sentence()


def test_a_missing_challenge_pass_blocks_completion():
    dag = td.Dag()
    dag.add(td.Task("a", td.SCOPE, objective="scope", method="m"))
    dag.add(td.Task("b", td.ANALYSIS, objective="run", method="m",
                    dependencies=["a"]))
    dag.seal()
    for task in dag.tasks:
        dag.record(task.task_id, td.COMPLETED)

    result = td.completion(dag, hypotheses_recorded=True,
                           validations_passed=True, facts=3, grounded=True,
                           visual_approved=True, limitations=1,
                           trace_consistent=True)

    assert td.CHALLENGED in result.unmet
    assert result.complete is False


def test_an_unavailable_objective_does_not_block_completion():
    dag = _dag()
    dag.record("t1", td.UNAVAILABLE, note="no covenant data after Q4 2025")
    for task in dag.tasks[1:]:
        dag.record(task.task_id, td.COMPLETED)

    result = td.completion(dag, hypotheses_recorded=True,
                           validations_passed=True, facts=3, grounded=True,
                           visual_approved=True, limitations=1,
                           trace_consistent=True)

    assert result.complete is True


# =============================================== §94 the presentability rubric


def _all(outcome: str = pb.PASS) -> dict[str, str]:
    return {d: outcome for d in pb.DIMENSIONS}


def test_the_eighteen_dimensions_section_94_names_are_all_scored():
    assert len(pb.DIMENSIONS) == 18
    for dimension in pb.DIMENSIONS:
        assert pb.ASKS[dimension].endswith("?"), dimension
    assert pb.SAFETY | pb.QUALITY == set(pb.DIMENSIONS)
    assert not (pb.SAFETY & pb.QUALITY)


def test_every_safety_dimension_says_why_it_is_one():
    """"Safety" is the word every dimension's owner will want applied to
    theirs."""
    for dimension in pb.SAFETY:
        assert len(pb.SAFETY_BECAUSE[dimension]) > 40, dimension


def test_a_clean_answer_is_shown():
    assert pb.score(_all()).verdict() == pb.SHOW


def test_a_safety_failure_blocks_display():
    """There is no version of showing an ungrounded figure that is better
    than not showing it."""
    scored = pb.score({**_all(), pb.GROUNDING: pb.FAIL},
                      details={pb.GROUNDING: "17.4% traces to no fact"})

    assert scored.verdict() == pb.BLOCK
    assert scored.blocking[0].dimension == pb.GROUNDING
    assert "17.4% traces to no fact" in scored.sentence()


def test_a_quality_failure_triggers_one_repair_then_a_deterministic_summary():
    """A second repair is a model arguing with a rubric."""
    outcomes = {**_all(), pb.NO_REPETITION: pb.FAIL}

    assert pb.score(outcomes).verdict() == pb.REPAIR
    assert pb.score(outcomes, repairs_attempted=1).verdict() == \
        pb.DETERMINISTIC_SUMMARY


def test_a_high_pass_rate_does_not_rescue_a_blocking_failure():
    """A high average with a blocking failure under it is exactly the shape
    §94 refuses, and the shape the assurance rules refuse everywhere else."""
    scored = pb.score({**_all(), pb.VISUAL_VALIDITY: pb.FAIL})

    assert scored.rate > 0.9
    assert scored.verdict() == pb.BLOCK


def test_an_unchecked_safety_dimension_blocks_as_hard_as_a_failed_one():
    """A grounding check nobody ran is not evidence that the answer is
    grounded."""
    scored = pb.score({**_all(), pb.GROUNDING: pb.UNCHECKED})

    assert scored.get(pb.GROUNDING).blocks is True
    assert scored.verdict() == pb.BLOCK


def test_an_unchecked_quality_dimension_does_not_block():
    scored = pb.score({**_all(), pb.CONCISION: pb.UNCHECKED})

    assert scored.get(pb.CONCISION).blocks is False
    assert scored.verdict() == pb.SHOW


def test_a_rubric_run_with_nothing_supplied_blocks():
    """The permissive default would make a caller that forgot to run the
    grounding check produce a perfect score."""
    assert pb.score({}).verdict() == pb.BLOCK


def test_an_unknown_outcome_is_refused():
    with pytest.raises(ValueError):
        pb.score({**_all(), pb.CONCISION: "PROBABLY_FINE"})


def test_not_applicable_dimensions_leave_the_rate_honest():
    scored = pb.score({**_all(), pb.PERSISTENCE: pb.NOT_APPLICABLE})

    assert len(scored.applicable) == 17
    assert scored.rate == 1.0
    assert scored.verdict() == pb.SHOW


def test_the_deterministic_summary_cannot_introduce_a_new_defect():
    """It is built by rendering observation templates, which cannot assert
    more than their slots — the entire reason the fallback is this and not
    another model call."""
    from backend.judgment import observations as ob

    made = [ob.make("o1", ob.CHANGE,
                    slots={"metric": "ECL", "entity": "Contracting",
                           "change": 40, "opening": "Q1 2026",
                           "closing": "Q2 2026"})]

    text = pb.summarise(made, limitations=["covenant data is 40% missing"])

    assert "ECL for Contracting moved 40" in text
    assert "Not established: covenant data is 40% missing" in text


def test_the_summary_says_so_when_there_is_nothing_to_say():
    assert "Nothing could be established" in pb.summarise([])
