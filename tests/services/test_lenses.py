"""
Lenses — a standing selector over the Engine Registry.

A lens is only safe because of what it REFUSES, and these tests are mostly
about the refusals:

  * a lens cannot contain an analysis the registry does not have
  * a lens cannot pass a parameter the analysis does not declare
  * a lens cannot be drawn a way that does not exist
  * a request the library has nothing for changes nothing, and says so, rather
    than being approximated with the nearest panel
  * every panel carries the lineage of the run behind it

This file used to cover Playbooks as well. That feature has been removed, and
the name Playbook now belongs to the committee pack intelligence system, whose
tests live under tests/playbook/.
"""

from __future__ import annotations

import pytest

from backend.services import lenses as ln
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
def lens():
    """A lens for one test, removed when the test ends.

    The teardown is the point. These objects live in the same tables the
    product's own seeded workspace does, so a fixture that creates one and
    walks away leaves "Test lens" sitting in a demonstration environment for
    ever — which is exactly what the residue check in
    `tests/demo/test_seeded_projects.py` exists to catch, and what it was
    catching. A test may use the real store; it may not leave anything in it.
    """
    view = ln.create(
        name="Test lens",
        panels=[ln.Panel(analysis_id="portfolio_summary", title="Position")],
    )
    try:
        yield view
    finally:
        try:
            ln.delete(view.id)
        except Exception:  # pragma: no cover - already gone is a clean end
            pass


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
