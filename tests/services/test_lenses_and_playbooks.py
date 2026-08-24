"""
Lenses and Playbooks — the two ways CreditProbe does something standing.

Both are governed selectors over the Engine Registry, and both are only safe
because of what they REFUSE. These tests are mostly about the refusals:

  * a lens cannot contain an analysis the registry does not have
  * a request the library has nothing for changes nothing, and says so, rather
    than being approximated with the nearest panel
  * a playbook cannot run an unregistered analysis or scope itself to an
    ungoverned dimension
  * a condition whose metric no analysis produced reports as untestable, which
    is a different thing from being false
  * a run that finds nothing says so
"""

from __future__ import annotations

import pytest

from backend.services import lenses as ln
from backend.services import playbooks as pb
from tests.conftest import database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL not reachable")


# ================================================================== lenses


def test_a_lens_cannot_contain_an_analysis_that_does_not_exist():
    with pytest.raises(ln.InvalidLens) as e:
        ln.validate([ln.Panel(analysis_id="invented_analysis")])
    assert "not a registered analysis" in str(e.value)


def test_a_lens_cannot_pass_a_parameter_the_analysis_does_not_declare():
    with pytest.raises(ln.InvalidLens) as e:
        ln.validate([ln.Panel(analysis_id="portfolio_summary",
                              params={"colour": "blue"})])
    # And it says what the analysis DOES accept.
    assert "colour" in str(e.value)
    assert "period" in str(e.value)


def test_a_lens_cannot_be_drawn_a_way_that_does_not_exist():
    with pytest.raises(ln.InvalidLens) as e:
        ln.validate([ln.Panel(analysis_id="portfolio_summary", visual="hologram")])
    assert "hologram" in str(e.value)


def test_a_lens_needs_at_least_one_panel():
    with pytest.raises(ln.InvalidLens):
        ln.validate([])


def test_a_request_resolves_only_to_analyses_that_exist():
    proposal = ln.propose("show me IFRS 9 staging and ECL coverage")
    assert proposal.panels
    from backend.engine.registry import get_registry

    known = {c.id for c in get_registry().contracts()}
    assert all(p.analysis_id in known for p in proposal.panels)


def test_a_request_the_library_cannot_serve_changes_nothing_and_says_so():
    """The failure this whole design exists to prevent: a request nobody can
    honour quietly becoming the nearest available panel."""
    existing = [ln.Panel(analysis_id="portfolio_summary")]
    proposal = ln.propose("show me the borrower's astrological sign", existing=existing)
    assert proposal.change_summary == ""
    assert proposal.refusals
    assert [p.analysis_id for p in proposal.panels] == ["portfolio_summary"]


def test_one_word_in_common_is_not_a_match():
    """"Borrower" appears in an analysis name. A question about a borrower's
    lunch is not a request for it."""
    proposal = ln.propose("what did the borrower have for lunch")
    assert proposal.refusals
    assert not proposal.change_summary


def test_a_removal_removes_only_what_was_named():
    existing = [
        ln.Panel(analysis_id="ecl_coverage_by_stage"),
        ln.Panel(analysis_id="collateral_coverage"),
        ln.Panel(analysis_id="portfolio_summary"),
    ]
    proposal = ln.propose("remove ecl coverage by stage", existing=existing)
    remaining = [p.analysis_id for p in proposal.panels]
    assert "ecl_coverage_by_stage" not in remaining
    assert "collateral_coverage" in remaining
    assert "portfolio_summary" in remaining


def test_adding_something_already_present_is_refused_rather_than_duplicated():
    existing = [ln.Panel(analysis_id="obligor_concentration")]
    proposal = ln.propose("add obligor concentration", existing=existing)
    assert proposal.change_summary == ""
    assert proposal.refusals
    assert len(proposal.panels) == 1


@pytest.fixture
def lens() -> ln.LensView:
    return ln.create(
        name="Test lens",
        panels=[ln.Panel(analysis_id="portfolio_summary", title="Position")],
    )


def test_revising_keeps_the_previous_version(lens):
    revised = ln.revise(
        lens.id,
        [ln.Panel(analysis_id="portfolio_summary"),
         ln.Panel(analysis_id="stage_distribution")],
        request="add stage distribution",
        change_summary="Added 1 panel: Stage Distribution.",
    )
    assert revised.version == 2
    assert {r["version"] for r in revised.revisions} == {1, 2}


def test_restoring_moves_forward_rather_than_rewinding(lens):
    """Rewinding would lose the history of what was tried."""
    ln.revise(lens.id, [ln.Panel(analysis_id="stage_distribution")],
              change_summary="Replaced everything.")
    restored = ln.restore(lens.id, 1)
    assert restored.version == 3
    assert [p["analysis_id"] for p in restored.panels] == ["portfolio_summary"]
    assert len(restored.revisions) == 3


def test_a_lens_is_rendered_live_with_a_trace_per_panel(lens):
    body = ln.render(lens.id)
    assert body["failed"] == 0
    panel = body["panels"][0]
    assert panel["status"] == "succeeded"
    assert panel["result"] is not None
    # A panel on a dashboard is as much of a claim as an answer, so it carries
    # the same lineage.
    assert panel["analysis_run_id"] is not None


# =============================================================== playbooks


def test_a_playbook_cannot_run_an_analysis_that_does_not_exist():
    with pytest.raises(pb.InvalidPlaybook) as e:
        pb.validate(analyses=[{"analysis_id": "invented"}], conditions=[],
                    scope={}, trigger="manual")
    assert "not a registered analysis" in str(e.value)


def test_a_playbook_cannot_scope_itself_to_an_ungoverned_dimension():
    with pytest.raises(pb.InvalidPlaybook) as e:
        pb.validate(analyses=[{"analysis_id": "portfolio_summary"}], conditions=[],
                    scope={"borrower_name": "Anything"}, trigger="manual")
    assert "governed dimension" in str(e.value)


def test_a_condition_can_only_make_a_comparison_from_the_closed_list():
    with pytest.raises(pb.InvalidPlaybook) as e:
        pb.validate(
            analyses=[{"analysis_id": "portfolio_summary"}],
            conditions=[{"metric": "stage2_pct", "operator": "LIKE", "threshold": 1}],
            scope={}, trigger="manual",
        )
    assert "LIKE" in str(e.value)


def test_a_playbook_must_run_something():
    with pytest.raises(pb.InvalidPlaybook):
        pb.validate(analyses=[], conditions=[], scope={}, trigger="manual")


@pytest.fixture
def playbook() -> pb.PlaybookView:
    return pb.create(
        name="Test appetite check",
        analyses=[{"analysis_id": "portfolio_summary"}],
        conditions=[
            {"metric": "stage2_pct", "label": "Stage 2 share", "operator": ">",
             "threshold": 0.0, "unit": "%", "severity": "warning"},
            {"metric": "stage2_pct", "label": "Stage 2 share", "operator": ">",
             "threshold": 99.0, "unit": "%", "severity": "critical"},
            {"metric": "no_such_metric", "label": "Nonexistent", "operator": ">",
             "threshold": 1.0, "severity": "info"},
        ],
    )


def test_a_run_tests_every_condition_against_an_engine_figure(playbook):
    result = pb.run(playbook.id)
    assert result.status == "succeeded"
    assert len(result.evaluations) == 3
    met = [e for e in result.evaluations if e["met"]]
    assert len(met) == 1, "Only the reachable threshold should be met."


def test_a_metric_no_analysis_produced_is_untestable_not_false(playbook):
    """These are different facts, and reporting the first as the second is how a
    condition that never fires looks like a condition that is being satisfied."""
    result = pb.run(playbook.id)
    missing = next(e for e in result.evaluations if e["metric"] == "no_such_metric")
    assert missing["testable"] is False
    assert missing["met"] is False
    assert "could not be tested" in missing["sentence"]


def test_every_figure_a_playbook_reports_carries_a_trace(playbook):
    result = pb.run(playbook.id)
    assert result.results
    assert all(r["analysis_run_id"] is not None for r in result.results)


def test_a_run_that_finds_nothing_says_so():
    quiet = pb.create(
        name="Nothing to find",
        analyses=[{"analysis_id": "portfolio_summary"}],
        conditions=[{"metric": "stage2_pct", "operator": ">", "threshold": 99.0}],
    )
    result = pb.run(quiet.id)
    assert result.alerted is False
    assert "Nothing here needs attention" in result.summary


def test_the_run_is_recorded(playbook):
    pb.run(playbook.id)
    history = pb.runs(playbook.id)
    assert len(history) >= 1
    assert history[0]["summary"]
