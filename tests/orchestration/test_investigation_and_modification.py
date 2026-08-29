"""
End-to-end orchestration: run a question, then change it.

The claims under test are the ones the product rests on:

  * an investigation's figures come from executing real engine analyses
  * the narrative quotes only figures those analyses returned
  * a modification is previewed before it runs, and refuses what it cannot do
  * applying one re-runs only what changed and keeps the original intact
"""

from __future__ import annotations

import pytest

from backend.orchestration import modification as mod
from backend.orchestration.executor import (
    assemble,
    build_reasoning_map,
    execute_plan,
    run_investigation,
)
from backend.orchestration.interpreter import build_narrative
from backend.orchestration.planner import DemoPlanner
from backend.orchestration.schema import AnalysisPlan, PlanStep
from backend.orchestration.validator import validate_plan
from backend.orchestration.vocabulary import get_vocabulary
from backend.trace.model import GOVERNED_NODE_TYPES, NodeType


@pytest.fixture(scope="module")
def vocab():
    return get_vocabulary()


@pytest.fixture(scope="module")
def investigation():
    """One real investigation, executed once and shared by the tests below.

    A composed analysis rather than a registry selection: since the capability
    router became the front door, composing is the normal route and the
    registry is an emergency fallback, so a fixture that exercised the registry
    would be testing the path the product no longer takes.
    """
    return run_investigation(
        "Which customers had a rating downgrade and an increase in ECL over "
        "the latest year?", persist=False)


@pytest.fixture(scope="module")
def unreadable():
    """A question the composer cannot read and no methodology is named for.

    "What deteriorated this period?" names no governed measure at all.
    """
    return run_investigation("What deteriorated this period?", persist=False)


def test_an_investigation_runs_real_analyses(investigation):
    assert investigation.status == "succeeded"
    assert investigation.steps
    for step in investigation.steps:
        assert step.status == "succeeded"
        assert step.result is not None
        # A real execution consumed real rows.
        assert step.result["input_row_count"] > 0


def test_composing_is_the_normal_route(investigation):
    """Composition is the front door, and there is no longer a back one."""
    assert investigation.mode.get("fallback") is not True
    assert investigation.steps[0].analysis_id == "dynamic_analysis"


def test_a_question_the_composer_cannot_read_is_asked_about_not_substituted(
        unreadable):
    """The most important guarantee in this release.

    This used to run whichever registered analysis best matched the question's
    wording and label the answer a fallback. That produced certified, reconciled,
    completely wrong answers — a request for the five largest Real Estate
    customers came back as a sector concentration reading 100% of a book already
    filtered to Real Estate. A confident answer to a question nobody asked is
    worse than no answer, so the substitution has been removed rather than
    labelled.
    """
    assert unreadable.status == "needs_clarification"
    assert unreadable.steps == [], "nothing may run for a question not read"
    assert unreadable.mode.get("fallback") is not True

    clarification = unreadable.clarification
    assert clarification is not None
    # It still leaves something to click — built from governed CONCEPTS, so
    # every offer is a question the composer can actually answer.
    assert clarification.options
    for option in clarification.options:
        assert option["question"]
    assert "registered" not in (clarification.detail or "").lower()


def test_the_reasoning_map_separates_judgement_from_arithmetic(investigation):
    graph = investigation.graph
    kinds = {n.type for n in graph.nodes.values()}
    assert NodeType.USER_PROMPT in kinds
    # How the request was read — structured now, not a prose "reading" node.
    assert NodeType.CAPABILITY in kinds
    assert NodeType.LLM_EXPLANATION in kinds
    # What actually computed the figures.
    assert NodeType.SQL_QUERY in kinds
    assert NodeType.MATHEMATICAL_QUERY in kinds

    # No interpretive node may carry a row count: those come from reading data.
    for node in graph.nodes.values():
        if node.is_interpretive:
            assert node.rows_out is None


def test_every_map_node_belongs_to_a_step_or_the_interpretive_frame(investigation):
    # The interpretive frame around the governed subgraphs: the question, CreditProbe's
    # reading of it, the plan, CreditProbe's reading of the result, and the chart chosen
    # from the answer's shape.
    frame = {"question", "intent", "plan", "narrative", "visual",
             "mathematical_query", "interpretation", "invariants", "routing",
             "scope", "evidence", "presentability",
             # Part B's judgment layer, recorded beside the presentability
             # gate it reads rather than repeats.
             "analytical_judgment",
             # Part F's assurance summary, recorded last because it reads
             # every other verdict rather than forming its own.
             "assurance_summary"}
    for node_id in investigation.graph.nodes:
        if node_id in frame:
            continue
        # A composed analysis records its lineage under one run rather than
        # numbering steps: every other node came from the runtime's own graph.
        assert node_id.startswith("run__"), node_id


def test_the_map_is_acyclic_and_hashable(investigation):
    order = investigation.graph.topological_order()
    assert len(order) == len(investigation.graph.nodes)
    assert len(investigation.node_hashes) == len(investigation.graph.nodes)


def test_the_narrative_quotes_only_figures_the_engine_returned(investigation):
    """Every headline metric must be findable in some step's result values.

    This is the mechanical version of "the model never invents a number".
    """
    reported: set[float] = set()
    for step in investigation.steps:
        values = (step.result or {}).get("values") or {}
        for value in values.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                reported.add(round(float(value), 6))
            elif isinstance(value, dict):
                for inner in value.values():
                    if isinstance(inner, (int, float)) and not isinstance(inner, bool):
                        reported.add(round(float(inner), 6))
        for row in (step.result or {}).get("rows") or []:
            for value in row.values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    reported.add(round(float(value), 6))

    assert investigation.narrative.metrics
    for metric in investigation.narrative.metrics:
        if isinstance(metric.value, (int, float)) and not isinstance(metric.value, bool):
            assert round(float(metric.value), 6) in reported, metric.label
        if metric.change is not None:
            assert round(float(metric.change), 6) in reported, f"{metric.label} change"


def test_a_narrative_without_results_says_so_rather_than_inventing_one():
    narrative = build_narrative("anything", "intent", [])
    assert narrative.metrics == []
    assert "no figures" in narrative.summary.lower()


def test_an_empty_plan_produces_a_map_with_no_governed_nodes():
    plan = AnalysisPlan(question="q", intent="i", steps=[])
    graph = build_reasoning_map(plan, [], build_narrative("q", "i", []))
    assert not any(n.type in GOVERNED_NODE_TYPES for n in graph.nodes.values())


# ------------------------------------------------------------- modification


@pytest.fixture(scope="module")
def base(vocab):
    """A small two-step plan, executed, for the modification tests."""
    plan = validate_plan(DemoPlanner().plan("Show me the rating transition matrix.", vocab), vocab)
    steps = execute_plan(plan)
    return plan, steps, assemble(plan, steps, duration_ms=0)


MODIFICATIONS = [
    ("Exclude Real Estate.", "exclude"),
    ("Only show Real Estate.", "only"),
    ("Use EAD instead of borrower count.", "set_basis"),
    ("Use borrower count instead of EAD.", "set_basis"),
    ("Compare against a different reporting period.", "set_period"),
    ("Add ECL Movement.", "add_analysis"),
    ("Add Sector Concentration.", "add_analysis"),
    ("Remove this filter.", "clear_filters"),
]


@pytest.mark.parametrize("request_text,kind", MODIFICATIONS)
def test_every_supported_modification_is_understood(base, vocab, request_text, kind):
    plan, _steps, inv = base
    change = mod.preview(request_text, plan, inv.graph.to_dict(), vocab)
    assert change.understood, request_text
    assert change.operation is not None
    assert change.operation.kind == kind


def test_an_unsupported_modification_is_refused_and_explained(base, vocab):
    plan, _steps, inv = base
    change = mod.preview("Delete the database.", plan, inv.graph.to_dict(), vocab)
    assert not change.understood
    assert not change.applicable
    assert change.supported, "the user must be told what CreditProbe can do instead"


def test_a_preview_runs_nothing_and_names_the_affected_nodes(base, vocab):
    plan, _steps, inv = base
    change = mod.preview("Only show Real Estate.", plan, inv.graph.to_dict(), vocab)
    assert change.applicable
    assert change.changed_steps
    assert change.affected_nodes
    # The plan and the narrative always re-derive.
    assert set(change.downstream_nodes) == {"plan", "narrative"}
    # And the original plan is untouched.
    assert plan.steps[0].filters == {}


def test_an_exclusion_becomes_an_include_list_of_real_values(base, vocab):
    plan, _steps, inv = base
    change = mod.preview("Exclude Real Estate.", plan, inv.graph.to_dict(), vocab)
    kept = change.proposed_plan.steps[0].filters["sector"]
    assert "Real Estate" not in kept
    assert set(kept) <= set(vocab.dimensions["sector"])
    assert len(kept) == len(vocab.dimensions["sector"]) - 1


def test_applying_a_modification_reuses_the_steps_that_did_not_change(base, vocab):
    plan, steps, inv = base
    change = mod.preview("Add ECL Movement.", plan, inv.graph.to_dict(), vocab)
    assert change.applicable
    applied = mod.apply_modification(plan, steps, change)

    assert len(applied.steps) == len(steps) + 1
    # The original step is reused; only the new analysis actually ran.
    assert applied.steps[0].reused is True
    assert applied.steps[-1].reused is False
    assert applied.steps[-1].analysis_id == "ecl_movement"


def test_a_changed_step_is_re_executed_and_returns_different_figures(base, vocab):
    plan, steps, inv = base
    change = mod.preview("Only show Real Estate.", plan, inv.graph.to_dict(), vocab)
    applied = mod.apply_modification(plan, steps, change)

    assert applied.steps[0].reused is False
    before = (steps[0].result or {}).get("values", {}).get("movement", {})
    after = (applied.steps[0].result or {}).get("values", {}).get("movement", {})
    assert before and after
    assert before != after, "filtering to one sector must change the answer"


def test_the_original_investigation_is_not_mutated_by_a_modification(base, vocab):
    plan, steps, inv = base
    before_hashes = dict(inv.node_hashes)
    change = mod.preview("Use borrower count instead of EAD.", plan, inv.graph.to_dict(), vocab)
    mod.apply_modification(plan, steps, change)
    assert inv.node_hashes == before_hashes
    assert plan.steps[0].params.get("basis") == "ead"


def test_a_modification_that_changes_nothing_is_reported_as_such(base, vocab):
    plan, _steps, inv = base
    # The plan already measures on exposure.
    change = mod.preview("Use EAD instead of borrower count.", plan, inv.graph.to_dict(), vocab)
    assert change.understood
    assert not change.applicable
    assert "already use that setting" in change.description


def test_a_change_no_analysis_here_supports_says_which_and_why(base, vocab):
    plan, _steps, inv = base
    # Nothing in a rating-transition plan applies a stress scenario.
    change = mod.preview("Use the severe scenario.", plan, inv.graph.to_dict(), vocab)
    assert change.understood
    assert not change.applicable
    assert "None of the analyses" in change.description


def test_a_modification_cannot_introduce_an_unregistered_analysis(base, vocab):
    plan, _steps, inv = base
    change = mod.preview("Add a bespoke ECL model.", plan, inv.graph.to_dict(), vocab)
    assert not change.applicable


def test_the_hash_diff_identifies_exactly_the_re_run_nodes(base, vocab):
    plan, steps, inv = base
    change = mod.preview("Only show Real Estate.", plan, inv.graph.to_dict(), vocab)
    applied = mod.apply_modification(plan, steps, change)
    diff = applied.graph.diff_hashes(inv.node_hashes)
    assert diff["changed"], "a filtered re-run must change content hashes"
    assert not diff["removed"]


def test_step_signatures_drive_reuse():
    """Two steps with the same analysis, parameters and filters are the same
    work, and the second must not re-run."""
    step = PlanStep("portfolio_summary", params={"period": "latest"})
    plan = AnalysisPlan(question="q", intent="i", steps=[step])
    first = execute_plan(plan)
    second = execute_plan(plan, previous=first)
    assert second[0].reused is True
    assert second[0].result == first[0].result
