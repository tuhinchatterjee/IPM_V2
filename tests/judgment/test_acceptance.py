"""
§97, §98, §99 — the mandatory acceptance cases.

What is accepted here
----------------------
The Investigation Factory: the Part B engines composed into one run, driven by
the three broad prompts §97 names, the two contradiction prompts §98 names,
and the six visual shapes §99 names. Each case asserts on what a reader would
see — the blueprint, the objectives, the challenge, the facts, the
materiality, the limitations, the chart, the Trace — rather than on the
phrasing of any of it.

Why the factory rather than the HTTP route
-------------------------------------------
These run the pipeline directly and offline. Every engine is handed its inputs
and returns a structure, so the whole thing executes with no provider, no
lake, and no key — which is the only way an acceptance suite this size runs in
CI at all. Wiring the factory behind `/api/v1/investigations` is the
integration Part D covers; when it lands, these are the cases it has to keep
passing, and a route-level suite is a thin wrapper over this one rather than a
second implementation of it.

The negative cases are the point
---------------------------------
Each section's happy path is one test. The rest are the ways a plausible
investigation is a wrong one: a challenge pass that did not run, a
contradiction reported as explained by a check that never fired, a chart whose
bars do not add up to its table, a narrative with a figure nothing computed.
"""

from __future__ import annotations

import pytest

from backend.judgment import blueprints as bp
from backend.judgment import contradictions as cd
from backend.judgment import evidence as ev
from backend.judgment import factory as fc
from backend.judgment import hypotheses as hy
from backend.judgment import materiality as mt
from backend.judgment import observations as ob
from backend.judgment import presentability as pb
from backend.judgment import task_dag as td
from backend.judgment import visual_critic as vc
from backend.judgment import visual_grammar as vg

# --------------------------------------------------------------- fixtures


def _fact(fact_id: str, **over) -> ev.Fact:
    base = dict(
        fact_id=fact_id, fact_type=ev.CHANGE, metric="expected credit loss",
        entity_type="sector", entity_id="contracting",
        entity_name="Contracting", opening_period="Q3 2025",
        closing_period="Q2 2026", opening_value=210.0, closing_value=222.0,
        change=12.0, unit="SAR", source_run_id="run-1",
        validation_status=ev.VALIDATED, evidence_quality=ev.COMPLETE,
        direction=ev.WORSE)
    base.update(over)
    return ev.Fact(**base)


def _graph(*facts: ev.Fact) -> ev.Graph:
    graph = ev.Graph()
    for fact in facts:
        graph.add(fact)
    assert not graph.refused, graph.refused
    return graph


def _observations(graph: ev.Graph, **kinds) -> ob.Set:
    """A realistic observation set: an answer, breadth, drivers, limits."""
    found = ob.Set()
    fact_ids = sorted(graph.facts)
    found.add(ob.make("o-change", ob.CHANGE, facts=fact_ids[:1],
                      slots={"metric": "expected credit loss",
                             "entity": "Contracting", "change": 12,
                             "opening": "Q3 2025", "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)
    found.add(ob.make("o-driver", ob.DRIVER, facts=fact_ids[:1],
                      slots={"entity": "Al Rajhi Contracting",
                             "contribution": 8,
                             "metric": "expected credit loss"},
                      materiality=mt.HIGH), graph)
    found.add(ob.make("o-breadth", ob.BREADTH, facts=fact_ids[:1],
                      slots={"verdict": "Concentrated.",
                             "detail": "three names carry 71% of the "
                                       "movement"},
                      materiality=mt.HIGH), graph)
    found.add(ob.make("o-limit", ob.LIMITATION,
                      slots={"detail": "covenant data is missing for 40% of "
                                       "the segment"},
                      materiality=mt.MODERATE), graph)
    for observation in kinds.get("extra", []):
        found.add(observation, graph)
    return found


def _challenge_pass() -> hy.Pass:
    """A challenge pass with every challenge answered."""
    attempted = hy.Pass()
    for challenge in hy.CHALLENGES:
        attempted.record(challenge.id, hy.PASSED,
                         detail=f"checked: {challenge.question}")
    return attempted


def _chart(**over) -> vc.Chart:
    base = dict(
        chart=vg.HORIZONTAL_BAR,
        bindings={"category": "sector", "value": "ecl"},
        roles={"category": vg.CATEGORY, "value": vg.MEASURE},
        labels=["Contracting", "Real Estate"],
        series={"ecl": [222.0, 140.0]}, units={"ecl": "SAR"},
        decimals=1, has_accessible_table=True)
    base.update(over)
    return vc.Chart(**base)


def _table(**over) -> vc.Table:
    base = dict(values={"ecl": [222.0, 140.0]},
                labels=["Contracting", "Real Estate"], units={"ecl": "SAR"})
    base.update(over)
    return vc.Table(**base)


def _complete_inputs(question: str, request: bp.Request,
                     **over) -> fc.Inputs:
    """Everything a complete, presentable investigation needs.

    Built once so each negative case can remove exactly one thing and show
    that removing it is what changes the verdict.
    """
    graph = _graph(_fact("f1"), _fact("f2",
                                      entity_id="real_estate",
                                      entity_name="Real Estate",
                                      opening_value=150.0, closing_value=140.0,
                                      change=-10.0, direction=ev.BETTER))
    found = _observations(graph)
    base = dict(
        question=question, request=request, graph=graph, observations=found,
        hypotheses=hy.standard_tree(
            "expected credit loss rose in Contracting"), challenge=_challenge_pass(),
        built_charts=[_chart()], table=_table(),
        periods=4, trace_consistent=True, validations_passed=True,
        narrative=("Expected credit loss for Contracting moved 12 between "
                   "Q3 2025 and Q2 2026. Al Rajhi Contracting contributed 8. "
                   "Concentrated: three names carry 71% of the movement. "
                   "Covenant data is missing for 40% of the segment."),
        rubric={pb.CONCISION: pb.PASS, pb.NO_REPETITION: pb.PASS,
                pb.ACTIONABILITY: pb.PASS,
                pb.NUMBER_FORMATTING: pb.PASS,
                pb.PERIOD_POPULATION_ACCURACY: pb.PASS,
                pb.NON_CAUSAL_LANGUAGE: pb.PASS})
    base.update(over)
    return fc.Inputs(**base)


# ================================================ §97 broad investigations
#
# The three prompts the brief names, verbatim.

THREAD_A = ("Something seems wrong with Contracting. Investigate it across "
            "exposure, ratings, IFRS 9, delinquency, financial performance, "
            "covenants and collateral over the latest four quarters.")
THREAD_B = ("The portfolio's Stage 2 share increased. Determine whether the "
            "movement is broad or concentrated and identify the sectors and "
            "customers responsible.")
THREAD_C = ("Review the latest portfolio period for the CRO and identify the "
            "five most material validated risk developments.")

_REQUESTS = {
    THREAD_A: bp.Request(
        question=THREAD_A, subject="segment", broad=True, periods=4,
        concepts=("exposure at default", "internal rating",
                  "expected credit loss", "days past due"),
        high_materiality=True, officer_level=3),
    THREAD_B: bp.Request(
        question=THREAD_B, subject="portfolio", broad=True, periods=2,
        concepts=("ifrs 9 stage", "expected credit loss"),
        high_materiality=True, officer_level=3),
    THREAD_C: bp.Request(
        question=THREAD_C, subject="portfolio", broad=True, periods=2,
        concepts=("expected credit loss", "exposure at default"),
        high_materiality=True, officer_level=3),
}


@pytest.mark.parametrize("question", [THREAD_A, THREAD_B, THREAD_C])
def test_a_broad_investigation_shows_everything_section_97_requires(question):
    """§97's list, item by item: blueprint, objective coverage, hypothesis
    tree, specialist tasks, deterministic results, challenge, facts,
    materiality, limitations, visualization, grounded answer, complete
    Trace."""
    run = fc.investigate(_complete_inputs(question, _REQUESTS[question]))
    shown = run.to_dict()

    # blueprint, with the losers kept
    assert run.blueprint.selected_blueprint_id
    assert run.blueprint.considered

    # objective coverage — every task finished or is explicitly unavailable
    assert run.dag is not None
    assert run.dag.outstanding == []

    # hypothesis tree and the challenge
    assert run.challenge is not None
    assert run.challenge.complete
    assert run.dag.get("challenge").satisfied

    # specialist tasks: the deterministic engines each have their own node
    types = {t.task_type for t in run.dag.tasks}
    assert {td.DRIVER, td.BREADTH, td.PERSISTENCE, td.CONTRADICTION,
            td.VALIDATION, td.SYNTHESIS, td.VISUALIZATION} <= types

    # facts, materiality, limitations
    assert run.contract is not None
    assert run.contract.get(fc.it.MATERIALITY).state == fc.it.PRESENT
    assert run.contract.get(fc.it.LIMITATIONS).state == fc.it.PRESENT

    # visualization passed the critic
    assert run.visual is not None
    assert run.visual.verdict.approved

    # a grounded answer, and a complete Trace
    assert run.presentability.get(pb.GROUNDING).outcome == pb.PASS
    assert run.completion.complete
    assert run.shown_as_answer is True
    assert shown["stopped_at"] == ""
    assert shown["ran"] == list(fc.STAGES)


@pytest.mark.parametrize("question", [THREAD_A, THREAD_B, THREAD_C])
def test_every_broad_investigation_compiles_a_real_graph(question):
    run = fc.investigate(_complete_inputs(question, _REQUESTS[question]))

    assert len(run.dag.tasks) >= 8
    # The synthesis depends on the challenge, not the other way round.
    synthesis = run.dag.get("synthesis")
    assert "challenge" in synthesis.dependencies
    assert run.dag.sealed is True


def test_a_broad_investigation_without_a_challenge_pass_is_not_an_answer():
    """§93. The tempting behaviour is to show what worked and omit the
    challenge, and it is tempting because the rest of the analysis is
    genuinely useful."""
    run = fc.investigate(
        _complete_inputs(THREAD_A, _REQUESTS[THREAD_A], challenge=None))

    assert run.shown_as_answer is False
    # The challenge is a task in the graph, so its absence fails there rather
    # than at the later stage that reports it — and everything downstream of
    # it is blocked rather than run on an unchallenged conclusion.
    assert run.dag.get("challenge").status == td.FAILED
    assert run.dag.get("synthesis").status == td.BLOCKED
    assert run.stage(fc.CHALLENGE).ran is False
    assert "challenge" in run.sentence().lower()


def test_a_failed_objective_blocks_the_polish_and_keeps_the_work():
    """A failure stops the polish, not the analysis. Abandoning it would throw
    away work that was correct."""
    inputs = _complete_inputs(THREAD_A, _REQUESTS[THREAD_A])
    inputs.objective_results = {"obj-00": td.FAILED}

    run = fc.investigate(inputs)

    assert run.shown_as_answer is False
    assert run.dag.get("obj-00").status == td.FAILED
    # The stages after it still ran; the investigation was not abandoned.
    assert fc.DIAGNOSE in run.ran
    assert fc.INTERPRET in run.ran
    assert "did not finish" in run.completion.sentence()


def test_an_unavailable_objective_is_not_a_failure():
    """A missing covenant dataset is not a defect in CreditProbe, and §93
    lets an objective be explicitly unavailable."""
    inputs = _complete_inputs(THREAD_A, _REQUESTS[THREAD_A])
    inputs.unavailable = {
        "obj-01": "the covenant dataset has no data after Q4 2025"}

    run = fc.investigate(inputs)

    assert run.dag.get("obj-01").status == td.UNAVAILABLE
    assert run.dag.get("obj-01").note
    assert run.completion.complete is True
    assert run.shown_as_answer is True


def test_an_ungrounded_narrative_blocks_the_answer():
    inputs = _complete_inputs(THREAD_A, _REQUESTS[THREAD_A])
    inputs.narrative += " Coverage now stands at 17.4%."

    run = fc.investigate(inputs)

    assert run.presentability.get(pb.GROUNDING).outcome == pb.FAIL
    assert run.presentability.verdict() == pb.BLOCK
    assert run.shown_as_answer is False


def test_a_question_no_blueprint_matches_stops_at_selection():
    """Rather than compiling a graph for a blueprint nothing chose."""
    run = fc.investigate(fc.Inputs(
        question="what is the weather",
        request=bp.Request(question="what is the weather")))

    assert run.stopped_at == fc.SELECT
    assert "no blueprint" in run.stage(fc.SELECT).detail
    assert run.shown_as_answer is False


# ============================================== §98 contradiction acceptance

THREAD_D = ("Find customers where financial performance improved but risk "
            "indicators deteriorated.")
THREAD_E = ("Find customers whose financial metrics deteriorated but rating "
            "and Stage did not.")


def _signals() -> list[cd.Signal]:
    common = dict(entity="Al Rajhi Contracting", population="matched",
                  opening_period="Q1 2026", closing_period="Q2 2026",
                  grain="customer", evidence_quality=ev.COMPLETE,
                  validation=ev.VALIDATED)
    return [
        cd.Signal(signal_id="ecl", metric="expected credit loss",
                  movement=12.0, direction=ev.WORSE,
                  timing_frequency="monthly", **common),
        cd.Signal(signal_id="rating", metric="internal rating",
                  movement=-1.0, direction=ev.BETTER,
                  timing_frequency="annual", **common),
    ]


def _all_checks(fired: dict[str, str] | None = None
                ) -> dict[str, tuple[str, str]]:
    fired = fired or {}
    return {check: ((cd.FIRED, fired[check]) if check in fired
                    else (cd.CLEAR, ""))
            for check in cd.CHECK_IDS}


@pytest.mark.parametrize("question", [THREAD_D, THREAD_E])
def test_a_contradiction_thread_does_everything_section_98_requires(question):
    """Align periods, population and grain; build a signal matrix; classify;
    test lag, threshold, mix, concentration and data quality; return
    explained, partially explained or unresolved."""
    inputs = _complete_inputs(
        question,
        bp.Request(question=question, subject="borrower", broad=True,
                   periods=2,
                   concepts=("expected credit loss", "internal rating")))
    inputs.signals = _signals()
    inputs.diagnostics = _all_checks(
        {"update_frequency": "the rating is reviewed annually and was last "
                             "reviewed 11 months ago"})

    run = fc.investigate(inputs)

    assert len(run.contradictions) == 1
    diagnosis = run.contradictions[0]

    # periods, population and grain were checked, not assumed
    for check in ("period_alignment", "population_alignment",
                  "grain_alignment"):
        assert check in diagnosis.run

    # the signal matrix: both sides, with what each movement MEANS
    assert diagnosis.pair.left.direction == ev.WORSE
    assert diagnosis.pair.right.direction == ev.BETTER

    # lag, threshold, mix, concentration and data quality were all tested
    for check in ("update_frequency", "threshold_crossings", "portfolio_mix",
                  "concentration", "data_quality"):
        assert check in diagnosis.run

    assert diagnosis.outcome in cd.OUTCOMES
    assert diagnosis.outcome == cd.EXPLAINED
    assert diagnosis.explanations == [cd.TIMING_LAG]
    assert "15 of 15 diagnostic checks ran" in diagnosis.statement()


def test_a_contradiction_nothing_explains_comes_back_unresolved():
    """§84's sentence, end to end. Fifteen clear diagnostics have a plausible
    narrative available — lag is always available — and the right answer is
    that somebody needs to look."""
    inputs = _complete_inputs(
        THREAD_D, bp.Request(question=THREAD_D, subject="borrower",
                             periods=2, broad=True))
    inputs.signals = _signals()
    inputs.diagnostics = _all_checks()

    run = fc.investigate(inputs)

    diagnosis = run.contradictions[0]
    assert diagnosis.outcome == cd.UNRESOLVED
    assert diagnosis.explanations == [cd.TRUE_CONTRADICTION]
    assert diagnosis.review_candidates
    assert "needs somebody to look" in diagnosis.statement()


def test_creditprobe_does_not_claim_the_classification_is_wrong():
    """§98's last line. "The rating is wrong" is a finding about the bank's
    own governed process, and an unresolved contradiction is not evidence for
    it."""
    inputs = _complete_inputs(
        THREAD_E, bp.Request(question=THREAD_E, subject="borrower",
                             periods=2, broad=True))
    inputs.signals = _signals()
    inputs.diagnostics = _all_checks()

    run = fc.investigate(inputs)
    statement = run.contradictions[0].statement().lower()

    for claim in ("rating is wrong", "incorrectly rated", "misclassified",
                  "should be stage"):
        assert claim not in statement


def test_a_contradiction_diagnosed_from_too_few_checks_is_data_insufficient():
    inputs = _complete_inputs(
        THREAD_D, bp.Request(question=THREAD_D, subject="borrower",
                             periods=2, broad=True))
    inputs.signals = _signals()
    inputs.diagnostics = {c: (cd.CLEAR, "") for c in cd.CHECK_IDS[:5]}

    run = fc.investigate(inputs)

    assert run.contradictions[0].outcome == cd.DATA_INSUFFICIENT
    assert run.contradictions[0].next_analysis


def test_an_undiagnosed_contradiction_fails_the_presentability_rubric():
    """Netting a disagreement away hides the one thing that needed a person
    to look."""
    inputs = _complete_inputs(
        THREAD_D, bp.Request(question=THREAD_D, subject="borrower",
                             periods=2, broad=True))
    inputs.signals = _signals()
    inputs.diagnostics = {"period_alignment": (cd.CLEAR, "")}

    run = fc.investigate(inputs)

    assert run.presentability.get(pb.CONTRADICTIONS).outcome == pb.FAIL
    assert run.presentability.verdict() == pb.BLOCK


def test_signals_that_agree_are_not_reported_as_a_contradiction():
    """Rising ECL and falling DSCR both mean deterioration."""
    inputs = _complete_inputs(
        THREAD_D, bp.Request(question=THREAD_D, subject="borrower",
                             periods=2, broad=True))
    inputs.signals = [
        cd.Signal(signal_id="ecl", metric="expected credit loss",
                  direction=ev.WORSE, validation=ev.VALIDATED),
        cd.Signal(signal_id="dscr", metric="DSCR", direction=ev.WORSE,
                  validation=ev.VALIDATED)]

    run = fc.investigate(inputs)

    assert run.contradictions == []
    assert run.shown_as_answer is True


# ================================================= §99 visual acceptance
#
# The six shapes the brief names, each asserted against the real grammar.

_VISUAL_CASES: tuple[tuple[str, str, dict[str, str], dict, str], ...] = (
    ("ECL decomposition", vg.CHANGE_DECOMPOSITION,
     {"category": vg.ENTITY, "value": vg.DECOMPOSITION_COMPONENT},
     {"categories": 9, "measures": 1, "cardinality": 9}, vg.WATERFALL),
    ("rating migration", vg.MIGRATION_PATHS,
     {"source": vg.FLOW_SOURCE, "destination": vg.FLOW_DESTINATION,
      "value": vg.MEASURE},
     {"categories": 8, "measures": 1, "cardinality": 8}, vg.SANKEY),
    ("two-period sector shares", vg.TWO_PERIOD_CATEGORY,
     {"category": vg.CATEGORY, "value": vg.PERCENTAGE},
     {"categories": 10, "periods": 2, "measures": 1, "cardinality": 10},
     vg.DUMBBELL),
    ("sector by period", vg.CATEGORY_PERIOD_MEASURE,
     {"category": vg.CATEGORY, "series": vg.TIME, "value": vg.MEASURE},
     {"categories": 12, "periods": 8, "measures": 1, "cardinality": 12},
     vg.HEATMAP),
    ("borrower multi-measure", vg.THREE_MEASURE,
     {"value": vg.MEASURE, "second_value": vg.MEASURE, "size": vg.MEASURE},
     {"categories": 200, "measures": 3, "cardinality": 200}, vg.BUBBLE),
    ("heterogeneous records", vg.RECORD_LEVEL,
     {"category": vg.ENTITY, "value": vg.MEASURE},
     {"categories": 300, "measures": 7, "cardinality": 300,
      "wants_records": True}, vg.TABLE),
)


@pytest.mark.parametrize("name,shape,roles,tweaks,expected", _VISUAL_CASES,
                         ids=[c[0] for c in _VISUAL_CASES])
def test_section_99s_six_shapes_map_to_the_charts_it_names(
        name, shape, roles, tweaks, expected):
    selection = vg.select(shape, vg.Inputs(roles=roles, **tweaks))

    assert selection.chosen == expected, (name, selection.reason())


def test_a_borrower_multimeasure_falls_back_when_the_third_measure_is_not_one():
    """§99: scatter or bubble ONLY when valid. A bubble whose size restates
    its y-value shows two numbers and appears to show three."""
    selection = vg.select(vg.THREE_MEASURE, vg.Inputs(
        roles={"value": vg.MEASURE, "second_value": vg.MEASURE,
               "size": vg.MEASURE},
        categories=200, measures=2, cardinality=200))

    assert selection.chosen == vg.TABLE
    assert selection.fell_back is True


def test_no_raw_numeric_category_headers():
    """§99. A quantity on the category axis produces one bar per distinct
    value ordered by magnitude, which looks like a ranking of things and is a
    ranking of numbers."""
    scored = vg.score(vg.BAR, vg.Inputs(
        roles={"category": vg.MEASURE, "value": vg.MEASURE}, categories=30,
        measures=1))

    assert scored.accepted is False
    assert "does not label a category" in scored.rejections[0]


def test_no_user_facing_value_above_two_decimals():
    """§99, checked in both places it can be broken: the chooser refuses a
    chart that cannot show the precision, and the critic refuses one that
    shows too much."""
    inputs = vg.Inputs(roles={"category": vg.CATEGORY, "value": vg.MEASURE},
                       categories=8, measures=1, precision_required=4)
    assert vg.select(vg.CATEGORY_RANKING, inputs).chosen == vg.TABLE

    verdict = vc.review(_chart(decimals=3), _table())
    assert verdict.get(vc.PRECISION).outcome == vc.FAIL
    assert verdict.approved is False


def test_a_chart_that_does_not_reconcile_never_reaches_the_reader():
    """End to end: the critic refuses it and the pipeline falls to the
    table, rather than the chart being shown with a warning."""
    inputs = _complete_inputs(THREAD_A, _REQUESTS[THREAD_A])
    inputs.built_charts = [_chart(series={"ecl": [222.0, 999.0]})]

    run = fc.investigate(inputs)

    assert run.visual.chart == vg.TABLE
    assert run.visual.fell_back_to_table is True
    assert run.visual.refused
    assert run.presentability.get(pb.VISUAL_VALIDITY).outcome == pb.PASS


def test_every_refused_chart_is_kept_where_a_reader_can_see_it():
    inputs = _complete_inputs(THREAD_A, _REQUESTS[THREAD_A])
    inputs.built_charts = [_chart(decimals=6), _chart()]

    run = fc.investigate(inputs)

    assert run.visual.chart == vg.HORIZONTAL_BAR
    assert len(run.visual.refused) == 1
    assert run.visual.refused[0].to_dict()["failed"] == [vc.PRECISION]


# ================================================ the pipeline's own honesty


def test_every_stage_is_recorded_whether_it_ran_or_not():
    """A pipeline where a stage can be omitted and the completion check told
    it ran is a pipeline with no completion check."""
    run = fc.investigate(_complete_inputs(THREAD_B, _REQUESTS[THREAD_B]))

    assert [s.stage for s in run.stages] == list(fc.STAGES)
    for stage in fc.STAGES:
        assert fc.STAGE_DOES[stage].strip()


def test_the_completion_check_reads_the_run_rather_than_being_told():
    inputs = _complete_inputs(THREAD_B, _REQUESTS[THREAD_B])
    inputs.hypotheses = None

    run = fc.investigate(inputs)

    assert td.HYPOTHESES in run.completion.unmet
    assert run.shown_as_answer is False


def test_both_the_completion_rules_and_the_rubric_must_agree():
    """A complete investigation whose narrative asserts an ungrounded figure
    is not presentable, and a presentable narrative over a half-failed
    investigation is the polished answer §93 forbids."""
    complete_but_unpresentable = _complete_inputs(
        THREAD_B, _REQUESTS[THREAD_B])
    complete_but_unpresentable.rubric = {
        **complete_but_unpresentable.rubric, pb.NON_CAUSAL_LANGUAGE: pb.FAIL}

    run = fc.investigate(complete_but_unpresentable)

    assert run.completion.complete is True
    assert run.presentability.verdict() == pb.BLOCK
    assert run.shown_as_answer is False


def test_a_rubric_dimension_nobody_scored_is_never_a_pass():
    inputs = _complete_inputs(THREAD_B, _REQUESTS[THREAD_B])
    inputs.rubric = {}

    run = fc.investigate(inputs)

    unchecked = [f.dimension for f in run.presentability.findings
                 if f.outcome == pb.UNCHECKED]
    assert pb.NUMBER_FORMATTING in unchecked or \
        pb.NON_CAUSAL_LANGUAGE in unchecked
    assert run.shown_as_answer is False


def test_the_run_serialises_with_everything_a_trace_needs():
    run = fc.investigate(_complete_inputs(THREAD_A, _REQUESTS[THREAD_A]))
    payload = run.to_dict()

    for key in ("stages", "blueprint", "dag", "contradictions", "challenge",
                "contract", "visual", "presentability", "completion",
                "shown_as_answer", "sentence"):
        assert key in payload, key
    assert payload["dag"]["tasks"]
    assert payload["version"] == fc.FACTORY_VERSION
