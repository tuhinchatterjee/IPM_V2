"""Changing a lens by asking, now that a lens can hold metric tiles.

The property that matters is the same one the analysis matcher has: the only
thing being searched IS the list of things that exist, so a request can never
resolve to something the platform cannot calculate. The AI selects; it does not
invent a metric, write a formula, or set a figure.

The second thing tested here is quieter and would have shipped unnoticed: a
lens's sections hold panel INDICES, so a revision that removes a tile shifts
every index after it and a lens that had four clean bands comes back scrambled.
"""

from __future__ import annotations

import pytest

from backend.metrics import lenses as shipped
from backend.services import lenses as service


def kinds(proposal) -> list[tuple[str, str]]:
    return [(p.kind, p.metric_id or p.analysis_id) for p in proposal.panels]


def ids(proposal) -> set[str]:
    return {p.metric_id for p in proposal.panels if p.kind == "metric"}


# ------------------------------------------------------------- what it adds


def test_a_request_for_a_metric_adds_a_metric_tile():
    proposal = service.propose("show me the 30 day delinquency rate")
    assert proposal.change_summary
    assert "retail.dpd_30_count" in ids(proposal)
    for panel in proposal.panels:
        assert panel.kind == service.KIND_METRIC


def test_the_analysis_library_is_tried_first():
    """A registered analysis is a richer answer than a single tile."""
    proposal = service.propose("add ecl coverage")
    assert proposal.change_summary
    assert any(kind == service.KIND_ANALYSIS for kind, _ in kinds(proposal))


def test_the_words_people_use_reach_the_metric():
    for phrasing in ("add ifrs 9 staging", "add the staging profile"):
        proposal = service.propose(phrasing)
        assert proposal.change_summary, phrasing
        assert ids(proposal) == {
            "corporate.ifrs9.stage1_share",
            "corporate.ifrs9.stage2_share",
            "corporate.ifrs9.stage3_share"}, phrasing


def test_instruction_words_are_not_searched_for():
    """"Add the roll rate" is a request about a roll rate.

    Leaving "add" and "the" in the query makes every word have to match
    something, and nothing in the catalogue is called "add" — so a request
    naming an unavailable metric came back with the generic refusal instead of
    the reason.
    """
    bare = service.propose("roll rate")
    dressed = service.propose("please add the roll rate to this lens")
    assert bare.refusals and dressed.refusals
    assert "cannot be calculated" in dressed.refusals[0]


# ---------------------------------------------------------- what it refuses


def test_a_metric_this_deployment_cannot_calculate_gets_its_reason():
    proposal = service.propose("add the roll rate")
    assert proposal.panels == []
    assert proposal.refusals
    assert "Delinquency Roll Rate" in proposal.refusals[0]
    assert "movement" in proposal.refusals[0]


def test_a_request_for_something_that_does_not_exist_is_refused():
    proposal = service.propose("add the kangaroo index")
    assert proposal.panels == []
    assert proposal.refusals
    assert "metric catalogue" in proposal.refusals[0]


def test_a_request_never_produces_a_tile_for_an_unknown_metric():
    """The catalogue is the only thing searched, so this cannot happen —

    which is exactly why it is worth asserting: the day somebody replaces the
    search with something generative, this fails.
    """
    for request in ("add the kangaroo index", "add sales pipeline conversion",
                    "add anything at all", "add a metric I just made up"):
        proposal = service.propose(request)
        for panel in proposal.panels:
            if panel.kind == service.KIND_METRIC:
                service.validate([panel])  # refuses an unknown metric


def test_adding_what_is_already_there_says_so():
    first = service.propose("add retail utilisation")
    again = service.propose("add retail utilisation", existing=first.panels)
    assert again.change_summary == ""
    assert "already on this lens" in again.refusals[0]


def test_removing_a_tile_that_is_not_there_says_so():
    proposal = service.propose("remove the 30 day delinquency rate")
    assert proposal.change_summary == ""
    assert "nothing to remove" in proposal.refusals[0]


def test_a_tile_can_be_removed_by_asking():
    added = service.propose("add the 30 day delinquency rate")
    assert added.panels
    removed = service.propose("remove the 30 day delinquency rate",
                              existing=added.panels)
    assert removed.change_summary.startswith("Removed")
    assert removed.panels == []


# ------------------------------------------------- keeping a lens coherent


def _sectioned() -> tuple[list, list[dict]]:
    spec = shipped.CORPORATE_IFRS9
    panels = [service.Panel.metric(tile.metric_id, title=tile.title,
                                   visual=tile.visual)
              for tile in spec.tiles]
    return panels, spec.layout()


def test_sections_survive_a_change_that_removes_a_tile():
    panels, sections = _sectioned()
    kept = [p for p in panels if p.metric_id != "corporate.ifrs9.stage2_ead"]

    remapped = service.resection(panels, sections, kept)
    covered = [i for section in remapped for i in section["panels"]]
    assert sorted(covered) == list(range(len(kept)))
    assert [s["title"] for s in remapped] == [s["title"] for s in sections]

    # Every panel is still in the band it was in, by identity rather than
    # by position.
    for section in remapped:
        for index in section["panels"]:
            original = next(
                s for s in sections
                if any(panels[i].metric_id == kept[index].metric_id
                       for i in s["panels"]))
            assert original["title"] == section["title"]


def test_a_new_tile_lands_in_its_own_band_not_somebody_elses():
    panels, sections = _sectioned()
    grown = [*panels, service.Panel.metric("retail.utilisation")]

    remapped = service.resection(panels, sections, grown)
    assert remapped[-1]["title"] == "Added by request"
    assert remapped[-1]["panels"] == [len(grown) - 1]
    assert [s["title"] for s in remapped[:-1]] == [s["title"]
                                                   for s in sections]


def test_a_band_that_loses_every_tile_disappears():
    panels, sections = _sectioned()
    doomed = {panels[i].metric_id for i in sections[0]["panels"]}
    kept = [p for p in panels if p.metric_id not in doomed]

    remapped = service.resection(panels, sections, kept)
    assert sections[0]["title"] not in [s["title"] for s in remapped]
    assert len(remapped) == len(sections) - 1


def test_an_unsectioned_lens_stays_unsectioned():
    panels, _ = _sectioned()
    assert service.resection(panels, [], panels[:3]) == []


@pytest.mark.parametrize("request_text", [
    "add the 30 day delinquency rate",
    "add retail utilisation",
    "add ifrs 9 staging",
])
def test_every_proposed_tile_passes_validation(request_text):
    """A proposal the platform would then refuse to store is worse than none."""
    proposal = service.propose(request_text)
    assert proposal.panels
    service.validate(proposal.panels)
