"""
§3-§6 — whether the agentic layer is real, and whether Projects get it too.

    §3: "A different officer badge is not proof of a different execution
         path."

These are the slowest tests in the suite and the most important ones in this
phase. Each drives `agentic.run` — the function the Cockpit and a Project
Investigation both reach — and asserts against what was PERSISTED. A probe
that read the in-memory object would pass while the orchestrator dropped
everything on the floor, which is the exact failure the baseline found.

Nothing here calls a provider: every probe runs inside
`assert_no_provider_calls`, which makes an attempt raise.
"""

from __future__ import annotations

import pytest

from backend.proof import divergence as dv
from backend.proof.probe import run_probe
from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="the agentic proof needs the platform database")


def _lake() -> bool:
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    try:
        return FACILITY in get_data_source().datasets()
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def _needs_the_lake():
    if not _lake():
        pytest.skip("the agentic proof needs the analytical lake")


@pytest.fixture(scope="module")
def metadata_probe():
    probe, _ = run_probe("What ratings data do you have?", label="metadata")
    return probe


@pytest.fixture(scope="module")
def simple_probe():
    probe, _ = run_probe("Show IFRS 9 EAD by sector for the latest quarter.",
                         label="simple")
    return probe


@pytest.fixture(scope="module")
def multi_domain_probe():
    probe, _ = run_probe(
        "Which customers had a rating downgrade and an increase in ECL over "
        "the latest year?", label="multi-domain")
    return probe


@pytest.fixture(scope="module")
def portfolio_probe():
    probe, _ = run_probe(
        "Review the latest portfolio and tell me everything that genuinely "
        "requires CRO attention.", label="portfolio review")
    return probe


@pytest.fixture(scope="module")
def segment_probe():
    probe, _ = run_probe("Something seems wrong with Contracting. "
                         "Investigate it.", label="segment investigation")
    return probe


# ============================================ §3 the badge must mean something


def test_a_broad_investigation_actually_orchestrates(portfolio_probe):
    """The finding that started this phase.

    The portfolio review selected a Chief Orchestrator and then ran no
    orchestrator, no specialist and no task — because the broad-investigation
    summary was read from a field that is empty on the path the Cockpit
    takes, so the reading had no concepts and `agents_for()` returned
    nothing.
    """
    assert portfolio_probe.ok, portfolio_probe.error
    assert portfolio_probe.orchestrated is True
    assert portfolio_probe.coordinated is True
    assert len(portfolio_probe.specialists) >= 3, portfolio_probe.specialists
    assert portfolio_probe.task_count >= 3


def test_a_segment_investigation_also_orchestrates(segment_probe):
    assert segment_probe.ok, segment_probe.error
    assert segment_probe.orchestrated is True
    assert len(segment_probe.specialists) >= 3


def test_a_metadata_question_does_not_summon_a_swarm(metadata_probe):
    """§4's Credit Analyst route. The other half of the same rule: an agentic
    layer that engages for everything is as wrong as one that never does."""
    assert metadata_probe.ok, metadata_probe.error
    assert metadata_probe.officer_level == 1
    assert metadata_probe.coordinated is False
    assert len(metadata_probe.specialists) == 0


def test_a_simple_analysis_does_not_summon_a_swarm(simple_probe):
    assert simple_probe.ok, simple_probe.error
    assert simple_probe.officer_level == 1
    assert simple_probe.coordinated is False


def test_two_domains_are_a_comparison_not_a_swarm(multi_domain_probe):
    """§4's Senior Credit Officer: "appropriate two-domain specialists where
    needed; no broad portfolio agent swarm"."""
    assert multi_domain_probe.ok, multi_domain_probe.error
    assert multi_domain_probe.executed is True
    assert multi_domain_probe.coordinated is False
    assert len(multi_domain_probe.datasets) >= 2


def test_the_officer_ladder_is_not_decorative(simple_probe, portfolio_probe):
    """§3's assertion, as a property.

    Two runs at different officer levels that differ in NO expensive axis
    are DECORATIVE, and that fails. Trace-node count does not count: a run
    that wrote more down did not do more work.
    """
    comparison = dv.compare(simple_probe, portfolio_probe)

    assert comparison.verdict == dv.MATERIAL, comparison.to_dict()
    assert comparison.expensive_differences


def test_escalation_buys_more_work_rather_than_less(simple_probe,
                                                    portfolio_probe):
    """A run that escalated to a Chief Orchestrator and did LESS on an axis
    both runs report did not escalate — it took a different, smaller route
    and put a bigger badge on it."""
    comparison = dv.compare(simple_probe, portfolio_probe)

    assert comparison.regressions == [], comparison.to_dict()


def test_the_coordinated_run_reports_what_its_specialists_touched(
        simple_probe, portfolio_probe):
    """D19, closed.

    This test used to assert the opposite. A coordinated review reported
    zero datasets and zero tool calls — not because it read less than a
    single-dataset query, but because its Investigation threw away every
    sub-analysis it ran except for the headline sentence. The Trace for a
    portfolio review could not say which data it read.

    The composition record fixed that, and the old test failed loudly when
    it did, which is what it was for. What is asserted now is the closed
    state: a review reads MORE than a single-dataset query, and says so.
    """
    comparison = dv.compare(simple_probe, portfolio_probe)

    assert "dataset_count" not in comparison.unmeasured_axes, (
        "the coordinated Investigation has stopped reporting its datasets")
    assert portfolio_probe.datasets, (
        "a coordinated review that ran governed analyses reports no dataset")
    assert len(portfolio_probe.datasets) >= len(simple_probe.datasets), (
        "a portfolio review read fewer datasets than a single query: "
        f"{portfolio_probe.datasets} vs {simple_probe.datasets}")
    assert portfolio_probe.executed is True
    assert comparison.regressions == [], comparison.regressions


def test_the_officer_selection_records_why(portfolio_probe, simple_probe):
    """§3: "structured selection reason". A level with no recorded reason is
    a number somebody has to take on trust."""
    for probe in (portfolio_probe, simple_probe):
        assert probe.officer_level is not None
        assert probe.officer_reason, probe.label


def test_the_matrix_over_the_ladder_finds_no_decorative_step(
        metadata_probe, multi_domain_probe, portfolio_probe):
    """Adjacent pairs, not all pairs: the question is whether each STEP up
    buys anything, and a half-implemented ladder is indistinguishable from a
    complete one when only its ends are compared."""
    matrix = dv.matrix([metadata_probe, multi_domain_probe, portfolio_probe])

    assert matrix["decorative"] == 0, matrix
    assert matrix["verdict"] == dv.MATERIAL


# ==================================== §5 the Cockpit path, end to end


def test_the_cockpit_path_produces_evidence_not_just_an_answer(simple_probe):
    """§5's chain, checked at the points that leave a record."""
    assert simple_probe.executed is True
    assert simple_probe.datasets
    assert simple_probe.plan_steps >= 1
    assert simple_probe.trace_nodes
    assert simple_probe.assurance_status
    assert simple_probe.coverage_pct > 0


def test_every_turn_gets_an_assurance_record_with_a_real_verdict(
        simple_probe, metadata_probe, portfolio_probe):
    """§210, which was silently not happening: `trace_summary` raised on a
    `DimensionResult.measured` that did not exist, and the executor's broad
    except swallowed it for every answer."""
    for probe in (simple_probe, metadata_probe, portfolio_probe):
        assert probe.assurance_status, probe.label
        assert probe.checks_by_outcome, probe.label
        assert sum(probe.checks_by_outcome.values()) >= 90, probe.label


def test_no_critical_check_is_left_without_a_signal(
        simple_probe, metadata_probe, multi_domain_probe, portfolio_probe):
    """§21's gate: no critical NOT_AVAILABLE in a tested supported flow."""
    for probe in (simple_probe, metadata_probe, multi_domain_probe,
                  portfolio_probe):
        assert probe.critical_not_available == [], (
            probe.label, probe.critical_not_available)


def test_no_mandatory_check_is_left_unresolved(
        simple_probe, metadata_probe, multi_domain_probe, portfolio_probe):
    for probe in (simple_probe, metadata_probe, multi_domain_probe,
                  portfolio_probe):
        assert probe.mandatory_unresolved == [], (
            probe.label, probe.mandatory_unresolved)


def test_the_evidence_fact_graph_registers_facts(simple_probe):
    """It registered zero for every analysis in the product's history: the
    column filter read `kind`, and the presentation contract calls that field
    `semantic`."""
    assert simple_probe.executed
    assert simple_probe.grounded is not False


# ============================================== §6 Project parity


@pytest.fixture(scope="module")
def proof_project() -> int:
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Project

    name = "Agentic parity test"
    with get_session() as session:
        found = session.execute(
            select(Project).where(Project.name == name)).scalars().first()
        if found is not None:
            return int(found.id)
        made = Project(name=name, description="Created by the agentic proof "
                                              "suite. No client data.")
        session.add(made)
        session.commit()
        return int(made.id)


@pytest.fixture(scope="module")
def project_portfolio_probe(proof_project):
    probe, _ = run_probe(
        "Review the latest portfolio and tell me everything that genuinely "
        "requires CRO attention.", label="project portfolio review",
        project_id=str(proof_project))
    return probe


def test_a_project_investigation_uses_the_same_architecture(
        portfolio_probe, project_portfolio_probe):
    """§6: "The only differences should be governed Project context and
    object scope."

    So the same question inside a Project must orchestrate the same way. A
    Project that quietly took a cheaper path would be the same defect as the
    decorative badge, one level up.
    """
    assert project_portfolio_probe.ok, project_portfolio_probe.error
    assert project_portfolio_probe.orchestrated == portfolio_probe.orchestrated
    assert project_portfolio_probe.coordinated == portfolio_probe.coordinated
    assert (len(project_portfolio_probe.specialists)
            == len(portfolio_probe.specialists))
    assert project_portfolio_probe.officer_level == portfolio_probe.officer_level


def test_a_project_turn_is_classified_as_a_project_flow(
        project_portfolio_probe):
    from backend.proof import flows as fl

    assert project_portfolio_probe.flow == fl.PROJECT


def test_a_project_turn_still_gets_a_full_assurance_record(
        project_portfolio_probe):
    assert project_portfolio_probe.assurance_status
    assert project_portfolio_probe.critical_not_available == []
    assert sum(project_portfolio_probe.checks_by_outcome.values()) >= 90


def test_a_cockpit_turn_records_no_project(portfolio_probe):
    """The isolation half of §7: a global Investigation must not acquire a
    Project by accident."""
    assert portfolio_probe.project_id == ""
    assert portfolio_probe.context == "cockpit"
