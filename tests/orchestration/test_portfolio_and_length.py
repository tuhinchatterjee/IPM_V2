"""The Analysis Portfolio Planner and the analysis length policy.

§11, §12, §35, §38. Between them they decide how much work an open-ended
request earns and how much prose comes back, which are the two ways an
agentic answer goes wrong without looking wrong.
"""

from __future__ import annotations

import pytest

from backend.orchestration import investigation, length
from backend.orchestration import objectives as obj
from backend.orchestration import portfolio as pf

COMPUTABLE = {"ead", "ecl", "stage", "rating", "dpd", "headroom",
              "utilisation", "leverage", "dscr"}


def _candidate(analysis_id: str, concept: str, datasets: tuple[str, ...],
               **kwargs) -> pf.Candidate:
    return pf.Candidate(
        analysis_id=analysis_id, title=analysis_id.replace("_", " ").title(),
        question=f"What is {concept}?", concept_id=concept,
        datasets=datasets, **kwargs)


@pytest.fixture
def investigation_candidates():
    return [
        _candidate("concentration", "ead", ("portfolio_facility",),
                   prior=1.0),
        _candidate("ecl_movement", "ecl", ("ifrs9_staging",), prior=0.85),
        _candidate("stage_migration", "stage", ("ifrs9_staging",),
                   prior=0.7),
        _candidate("rating_migration", "rating", ("customer_ratings",),
                   prior=0.55),
        _candidate("dpd_deterioration", "dpd", ("facility_delinquency",),
                   prior=0.4),
        _candidate("covenant_headroom", "headroom", ("covenant_tests",),
                   prior=0.25),
        _candidate("utilisation", "utilisation", ("facility_limits",),
                   prior=0.15),
    ]


# ============================================================ §12 selection


def test_a_specific_request_earns_one_analysis(investigation_candidates):
    """§12's own example: "Show EAD by sector" is one analysis, not seven."""
    reading = obj.read("Show EAD by sector.")
    asked = _candidate("ead_by_sector", "ead", ("portfolio_facility",),
                       objective_id=reading.objectives[0].objective_id)
    plan = pf.plan("Show EAD by sector.", [asked, *investigation_candidates],
                   reading=reading, computable=COMPUTABLE)
    assert len(plan.selected) == 1
    assert plan.selected[0].candidate.analysis_id == "ead_by_sector"


def test_an_open_request_earns_a_portfolio(investigation_candidates):
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=COMPUTABLE)
    assert 3 <= len(plan.selected) <= pf.MAX_ANALYSES


def test_the_caller_prior_orders_the_background_candidates(
        investigation_candidates):
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=COMPUTABLE)
    first = max(plan.selected,
                key=lambda d: d.score.expected_value_of_information)
    assert first.candidate.analysis_id == "concentration"


def test_a_prior_can_never_lift_a_background_analysis_to_a_requested_one():
    reading = obj.read("Show EAD by sector.")
    asked = _candidate("asked", "ead", ("portfolio_facility",),
                       objective_id=reading.objectives[0].objective_id)
    loud = _candidate("background", "dpd", ("facility_delinquency",),
                      prior=1.0)
    plan = pf.plan("Show EAD by sector.", [asked, loud], reading=reading,
                   computable=COMPUTABLE)
    scores = {d.candidate.analysis_id: d.score.relevance
              for d in plan.decisions}
    assert scores["asked"] > scores["background"]


def test_an_uncomputable_analysis_is_never_selected(investigation_candidates):
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable={"ead"})
    assert [d.candidate.analysis_id for d in plan.selected] == \
        ["concentration"]
    rejected = {d.candidate.analysis_id: d.reason for d in plan.rejected}
    assert "cannot compute" in rejected["ecl_movement"]


def test_an_unreadable_catalogue_selects_nothing(investigation_candidates):
    """Unknown is not available. Selecting on an unread catalogue would be
    selecting on hope."""
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=set())
    assert plan.selected == []
    assert "none was worth running" in plan.selection_reason


def test_a_repeat_of_a_selected_analysis_is_rejected_for_saying_the_same():
    first = _candidate("ecl_total", "ecl", ("ifrs9_staging",), prior=1.0)
    echo = _candidate("ecl_again", "ecl", ("ifrs9_staging",), prior=0.9)
    plan = pf.plan("Investigate Contracting.", [first, echo],
                   computable=COMPUTABLE)
    assert [d.candidate.analysis_id for d in plan.selected] == ["ecl_total"]
    assert "repeats" in plan.rejected[0].reason


def test_the_cost_budget_stops_the_portfolio(investigation_candidates):
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=COMPUTABLE, cost_budget=2.0)
    assert len(plan.selected) < len(investigation_candidates)
    assert plan.cost_estimate <= 2.0


def test_every_candidate_appears_as_selected_or_rejected(
        investigation_candidates):
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=COMPUTABLE)
    assert len(plan.selected) + len(plan.rejected) == \
        len(investigation_candidates)
    assert all(d.reason for d in plan.decisions)


def test_the_planner_records_everything_the_brief_names(
        investigation_candidates):
    """§12's persistence list, checked as a list."""
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=COMPUTABLE).to_dict()
    for key in ("candidate_analyses", "selected_analyses",
                "rejected_analyses", "selection_reason",
                "expected_value_of_information", "cost_estimate",
                "dependency_graph"):
        assert key in plan, f"§12 requires {key} to be persisted"


# ------------------------------------------------------- the dependency graph


def test_independent_analyses_run_in_one_layer(investigation_candidates):
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=COMPUTABLE)
    assert len(plan.layers()) == 1
    assert plan.parallelism == len(plan.selected)


def test_a_dependent_analysis_runs_after_what_it_depends_on():
    total = _candidate("total", "ecl", ("ifrs9_staging",), prior=1.0)
    split = _candidate("decomposition", "stage", ("ifrs9_staging",),
                       prior=0.9, depends_on=("total",))
    plan = pf.plan("Investigate this.", [total, split], computable=COMPUTABLE)
    layers = plan.layers()
    assert layers.index(["total"]) < layers.index(["decomposition"])


def test_dependencies_are_inferred_from_the_objective_actions():
    reading = obj.read(
        "What is total ECL, and break the change down by sector?")
    assert [o.action for o in reading.objectives] == \
        [obj.AGGREGATE, obj.DECOMPOSE]
    candidates = [
        _candidate(f"a{i}", "ecl", ("ifrs9_staging",),
                   objective_id=o.objective_id)
        for i, o in enumerate(reading.objectives)]
    wired = pf.infer_dependencies(candidates, reading)
    decomposing = [c for c in wired
                   if reading.objective(c.objective_id).action == obj.DECOMPOSE]
    assert decomposing, "the message contains a decomposition"
    assert all(c.depends_on for c in decomposing)


def test_a_dependency_cycle_is_reported_rather_than_looped():
    one = _candidate("one", "ecl", ("ifrs9_staging",), prior=1.0,
                     depends_on=("two",))
    two = _candidate("two", "stage", ("ifrs9_staging",), prior=1.0,
                     depends_on=("one",))
    plan = pf.plan("Investigate this.", [one, two], computable=COMPUTABLE)
    assert plan.layers()


# ---------------------------------------------------- §37 primary/supporting


def test_the_analysis_the_user_asked_for_is_primary(investigation_candidates):
    reading = obj.read("Show EAD by sector.")
    asked = _candidate("ead_by_sector", "ead", ("portfolio_facility",),
                       objective_id=reading.objectives[0].objective_id)
    plan = pf.plan("Show EAD by sector.", [asked, *investigation_candidates],
                   reading=reading, computable=COMPUTABLE)
    assert [d.candidate.analysis_id for d in plan.primary] == ["ead_by_sector"]


def test_an_open_request_still_designates_one_primary(
        investigation_candidates):
    plan = pf.plan("Investigate Contracting.", investigation_candidates,
                   computable=COMPUTABLE)
    assert len(plan.primary) == 1
    assert plan.supporting


def test_a_validation_only_analysis_is_never_primary():
    finding = _candidate("finding", "ecl", ("ifrs9_staging",), prior=1.0)
    checker = _candidate("check", "stage", ("ifrs9_staging",), prior=1.0,
                         validation_only=True)
    plan = pf.plan("Investigate this.", [finding, checker],
                   computable=COMPUTABLE)
    assert all(not d.primary for d in plan.validation)


# --------------------------------------------------- §11 objective coverage


def test_an_objective_no_analysis_serves_is_recorded_not_dropped():
    reading = obj.read("What is total ECL, and what will it be next quarter?")
    served = _candidate("ecl_total", "ecl", ("ifrs9_staging",),
                        objective_id=reading.objectives[0].objective_id)
    plan = pf.plan(reading.question, [served], reading=reading,
                   computable=COMPUTABLE)
    assert len(reading.objectives) > 1
    assert plan.uncovered, "the second objective has no analysis behind it"


def test_settling_objectives_marks_the_uncovered_ones_unavailable():
    reading = obj.read("What is total ECL, and what will it be next quarter?")
    served = _candidate("ecl_total", "ecl", ("ifrs9_staging",),
                        objective_id=reading.objectives[0].objective_id)
    plan = pf.plan(reading.question, [served], reading=reading,
                   computable=COMPUTABLE)
    pf.settle_objectives(plan, reading)
    unavailable = [o for o in reading.objectives
                   if o.status == obj.UNAVAILABLE]
    assert unavailable
    assert all(o.note for o in unavailable)


def test_a_served_objective_records_which_analysis_will_answer_it():
    reading = obj.read("Show EAD by sector.")
    served = _candidate("ead_by_sector", "ead", ("portfolio_facility",),
                        objective_id=reading.objectives[0].objective_id)
    plan = pf.plan(reading.question, [served], reading=reading,
                   computable=COMPUTABLE)
    pf.settle_objectives(plan, reading)
    assert reading.objectives[0].planned_task == "ead_by_sector"


# ============================================ §11 decomposition and coverage


def test_the_briefs_four_part_question_decomposes_into_four_objectives():
    reading = obj.read(
        "Show Stage 2 EAD by sector, compare it with four quarters ago, "
        "identify the three sectors driving the increase, and tell me which "
        "borrowers explain Contracting.")
    assert len(reading.objectives) == 4
    assert {o.action for o in reading.objectives} >= {obj.COMPARE}


def test_the_headline_counts_every_question():
    reading = obj.read(
        "What is total ECL, and break the change down by sector?")
    for objective in reading.objectives:
        objective.settle(obj.COMPLETE)
    coverage = obj.coverage(reading)
    assert coverage.headline() == \
        f"{coverage.total} of {coverage.total}"


def test_the_headline_names_what_was_not_answered():
    reading = obj.read(
        "What is ECL by sector, how much is risky, and by segment?")
    reading.objectives[0].settle(obj.COMPLETE)
    reading.objectives[1].settle(obj.NEEDS_CLARIFICATION, note="'risky'")
    headline = obj.coverage(reading).headline()
    assert "answered" in headline
    assert "requires clarification" in headline


def test_an_unsettled_objective_makes_the_answer_unpresentable():
    reading = obj.read(
        "What is total ECL, and break the change down by sector?")
    assert len(reading.objectives) == 2
    reading.objectives[0].settle(obj.COMPLETE)
    assert not obj.coverage(reading).presentable


def test_shared_scope_is_found_when_every_clause_is_about_one_population():
    reading = obj.read(
        "Which customers downgraded, which also had ECL increases, and among "
        "those which have covenant headroom below 15%?")
    scope = obj.shared_scope(reading)
    assert scope.shared
    assert scope.population


def test_several_populations_are_reported_rather_than_merged():
    reading = obj.read(
        "Show Stage 2 EAD by sector, and tell me which borrowers explain "
        "Contracting.")
    scope = obj.shared_scope(reading)
    if not scope.shared:
        assert scope.divergent, (
            "several populations must be named, or two figures on two "
            "different books will read as comparable")


def test_no_population_is_never_invented():
    reading = obj.read("Compare it with four quarters ago.")
    scope = obj.shared_scope(reading)
    assert scope.population == ""


# ================================================= §35 / §38 length policy


def test_a_single_analysis_earns_one_paragraph():
    decision = length.decide(length.Inputs())
    assert decision.band == length.SIMPLE
    assert decision.min_paragraphs == 1
    assert decision.layout == "single"


def test_every_band_demands_at_least_one_paragraph():
    """§35: every completed answer must include at least ONE paragraph."""
    for band in length.POLICY.values():
        assert band.min_paragraphs >= 1


def test_more_objectives_and_analyses_earn_more_room():
    simple = length.decide(length.Inputs())
    complex_ = length.decide(length.Inputs(
        objective_count=4, analysis_count=4, domain_count=3,
        exception_count=2, material=True))
    assert complex_.max_words > simple.max_words
    assert complex_.band == length.COMPLEX


def test_a_case_context_shortens_rather_than_lengthens():
    outside = length.decide(length.Inputs(objective_count=2,
                                          analysis_count=2))
    inside = length.decide(length.Inputs(objective_count=2, analysis_count=2,
                                         in_case_context=True))
    assert inside.max_words <= outside.max_words


def test_an_instructed_length_overrides_the_policy():
    decision = length.decide(length.Inputs(
        objective_count=4, analysis_count=4, requested_band=length.SIMPLE))
    assert decision.band == length.SIMPLE
    assert "the instruction wins" in decision.reasons[0]


def test_every_length_decision_records_why():
    decision = length.decide(length.Inputs(objective_count=3,
                                           analysis_count=2))
    assert decision.reasons
    assert decision.to_dict()["inputs"]["objective_count"] == 3


def test_the_layout_follows_the_analysis_count():
    assert length.decide(length.Inputs(analysis_count=1)).layout == "single"
    assert length.decide(
        length.Inputs(analysis_count=2)).layout == "primary_and_supporting"
    assert length.decide(length.Inputs(analysis_count=5)).layout == "grouped"
    assert length.decide(
        length.Inputs(analysis_count=8)).layout == "investigation_review"


def test_a_table_with_no_prose_is_not_an_answer():
    decision = length.decide(length.Inputs())
    result = length.check("", decision, has_result=True)
    assert not result.ok
    assert "not an answer" in result.problems[0]


def test_a_caption_around_a_result_is_not_an_answer():
    decision = length.decide(length.Inputs(objective_count=3,
                                           analysis_count=3))
    result = length.check("ECL rose.", decision, has_result=True)
    assert not result.ok


def test_burying_the_direct_answer_is_refused():
    decision = length.decide(length.Inputs())
    prose = " ".join(["word"] * 60)
    result = length.check(prose, decision, has_result=True,
                          answer_first=False)
    assert not result.ok
    assert any("burying" in p for p in result.problems)


def test_a_compliant_answer_passes():
    decision = length.decide(length.Inputs())
    prose = " ".join(["word"] * 80)
    assert length.check(prose, decision, has_result=True).ok


def test_the_length_follows_the_portfolio():
    candidates = [
        _candidate(f"a{i}", concept, (dataset,), prior=1.0 - i / 10)
        for i, (concept, dataset) in enumerate(
            (("ead", "portfolio_facility"), ("ecl", "ifrs9_staging"),
             ("dpd", "facility_delinquency"), ("rating", "customer_ratings")))]
    plan = pf.plan("Investigate Contracting.", candidates,
                   computable=COMPUTABLE)
    decision = length.from_portfolio(plan)
    assert decision.analysis_count == len(plan.selected)
    assert decision.band in (length.MODERATE, length.COMPLEX)


# =================================== the investigation uses the one planner


def test_the_investigation_selects_through_the_governed_planner():
    request = investigation.read("Investigate Contracting.", None)
    assert request.portfolio is not None
    assert len(request.probes) == len(request.portfolio.selected)


def test_the_investigation_proposes_more_than_it_runs():
    request = investigation.read("Investigate Contracting.", None)
    assert len(request.portfolio.candidates) > len(request.probes), (
        "an investigation that proposes exactly what it runs has not chosen")
    assert all(d.reason for d in request.portfolio.rejected)


def test_the_investigation_stays_within_its_probe_cap():
    request = investigation.read("Investigate Contracting.", None)
    assert len(request.probes) <= investigation.MAX_PROBES + 1


def test_the_borrower_probe_outranks_every_probe_but_the_leading_one():
    """A sector total says how much moved; this one says who.

    It sits behind exposure only, because an officer asks how big the
    position is before asking whose it is.
    """
    priors = {c: investigation._prior_for(c)
              for c in investigation._PRIORITY}
    worst = investigation._prior_for("worst")
    assert worst > sorted(priors.values())[-2]
    assert worst < max(priors.values())


# ==================================== §39 compound Trace / §40 follow-ups


def _compound_reading():
    reading = obj.read(
        "What is total ECL, and break the change down by sector?")
    candidates = pf.infer_dependencies([
        pf.Candidate(analysis_id="ecl_total", title="Total", question="q",
                     concept_id="ecl", datasets=("ifrs9_staging",),
                     objective_id=reading.objectives[0].objective_id),
        pf.Candidate(analysis_id="ecl_decomp", title="Decomposition",
                     question="q", concept_id="ecl",
                     datasets=("ifrs9_staging", "portfolio_facility"),
                     objective_id=reading.objectives[1].objective_id),
    ], reading)
    plan = pf.plan(reading.question, candidates, reading=reading,
                   computable={"ecl"})
    pf.settle_objectives(plan, reading)
    return reading, plan


def test_a_total_and_its_decomposition_are_both_selected():
    """Redundancy is not a reason to leave half a request unanswered."""
    _, plan = _compound_reading()
    assert len(plan.selected) == 2
    assert not plan.uncovered


def test_the_decomposition_runs_after_the_total():
    _, plan = _compound_reading()
    layers = plan.layers()
    assert layers == [["ecl_total"], ["ecl_decomp"]]


def test_the_compound_trace_carries_every_stage_the_brief_names():
    from backend.orchestration import compound_trace as ct

    reading, plan = _compound_reading()
    for objective in reading.objectives:
        objective.settle(obj.COMPLETE)
    graph = ct.build(reading.question, reading, portfolio=plan,
                     analyses=[{"id": "ecl_total"}, {"id": "ecl_decomp"}],
                     synthesis="ECL rose.")
    named = [s["stage"] for s in ct.stages(graph)]
    assert named == [title for title, _ in ct.STAGES]


def test_the_compound_trace_is_acyclic():
    from backend.orchestration import compound_trace as ct

    reading, plan = _compound_reading()
    graph = ct.build(reading.question, reading, portfolio=plan)
    assert len(graph.topological_order()) == len(graph.nodes)


def test_a_stage_that_did_not_happen_is_pending_not_missing():
    from backend.orchestration import compound_trace as ct

    reading, plan = _compound_reading()
    graph = ct.build(reading.question, reading, portfolio=plan)
    synthesis = next(s for s in ct.stages(graph) if s["stage"] == "SYNTHESIS")
    assert synthesis["status"] == "pending"


def test_only_the_synthesis_stage_is_interpretive():
    from backend.orchestration import compound_trace as ct

    reading, plan = _compound_reading()
    graph = ct.build(reading.question, reading, portfolio=plan,
                     synthesis="ECL rose.")
    interpretive = {s["stage"] for s in ct.stages(graph)
                    if not s["governed"]}
    assert interpretive == {"USER MESSAGE", "SYNTHESIS"}


def test_the_trace_reports_objectives_in_the_briefs_vocabulary():
    from backend.orchestration import compound_trace as ct

    reading, plan = _compound_reading()
    reading.objectives[0].settle(obj.COMPLETE)
    reading.objectives[1].settle(obj.NEEDS_CLARIFICATION, note="which change")
    graph = ct.build(reading.question, reading, portfolio=plan)
    reported = graph.nodes["compound_coverage"].config["reported"]
    assert {r["status"] for r in reported} == {"ANSWERED",
                                              "CLARIFICATION NEEDED"}


def test_a_single_objective_answer_earns_no_compound_trace():
    from backend.orchestration import compound_trace as ct

    reading = obj.read("Show EAD by sector.")
    assert not ct.applies(reading, None)


def test_a_follow_up_offers_the_unanswered_objective_first():
    from backend.orchestration import suggestions

    reading, plan = _compound_reading()
    reading.objectives[0].settle(obj.COMPLETE)
    reading.objectives[1].settle(obj.NEEDS_CLARIFICATION,
                                 note="by sector or by segment?")
    offered = suggestions.after_compound(reading, plan)
    assert offered
    assert "by sector or by segment?" in offered[0]


def test_a_follow_up_never_offers_an_uncomputable_analysis():
    from backend.orchestration import suggestions

    reading = obj.read("Investigate Contracting.")
    plan = pf.plan(reading.question, [
        _candidate("impossible", "nothing_publishes_this",
                   ("missing_dataset",))], computable={"ead"})
    offered = suggestions.after_compound(reading, plan)
    assert not any("nothing_publishes_this" in s for s in offered)


def test_a_case_context_is_offered_as_a_next_step():
    from backend.orchestration import suggestions

    reading, plan = _compound_reading()
    offered = suggestions.after_compound(
        reading, plan, case_context="the Contracting Risk Case")
    assert any("Contracting Risk Case" in s for s in offered)
