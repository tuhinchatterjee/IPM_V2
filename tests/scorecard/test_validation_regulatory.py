"""The supervisory evidence map, and the claim it must never make.

The whole risk in this module is one word. A coverage table that says
"COMPLIANT" is a regulatory conclusion the software has no standing to
reach, and it takes one screenshot pasted into a committee pack for that to
become the bank's position. The tests below are mostly about making sure
that word cannot appear, and that the disclaimer cannot be separated from
the table.
"""

from __future__ import annotations

import pytest

from backend.scorecard.validation import (
    models,
    registry,
    regulatory,
    runner,
    states,
)


@pytest.fixture(scope="module")
def results() -> list[states.Result]:
    model = models.get("sme_champion")
    out: list[states.Result] = []
    for category in registry.CATEGORIES:
        out.extend(runner.run_category(category, model))
    return out


# ------------------------------------------------- what it must never say


def test_no_status_claims_compliance() -> None:
    for status in regulatory.STATUSES:
        assert "COMPLIAN" not in status.upper()
        assert "APPROVED" not in status.upper()
    joined = " ".join(regulatory.STATUS_MEANING.values()).upper()
    assert "IS COMPLIANT" not in joined


def test_the_disclaimer_travels_with_every_response(
        results: list[states.Result]) -> None:
    """A coverage table separated from its disclaimer is a compliance claim."""
    for payload in (regulatory.catalogue(), regulatory.coverage(results)):
        assert payload["disclaimer"] == regulatory.DISCLAIMER
        assert payload["this_is_not_a_compliance_assessment"] is True
        assert "not a compliance assessment" in payload["disclaimer"]


def test_the_summaries_say_they_are_not_quotations() -> None:
    payload = regulatory.catalogue()
    assert "not quotations" in payload["summary_is_a_reading_aid"]
    for row in payload["requirements"]:
        assert row["summary_is_a_reading_aid"]


# --------------------------------------------------- the map is consistent


def test_every_test_maps_to_a_reference_in_the_catalogue() -> None:
    """Otherwise a test evidences something nobody can look up."""
    assert regulatory.catalogue()["unmapped_tests"] == []


def test_references_are_read_from_the_registry_not_restated() -> None:
    for requirement in regulatory.REQUIREMENTS:
        expected = [t.test_id for t in registry.TESTS
                    if requirement.reference in t.cbuae]
        assert list(requirement.tests()) == expected


def test_every_reference_is_evidenced_by_at_least_one_test() -> None:
    for requirement in regulatory.REQUIREMENTS:
        assert requirement.tests(), (
            f"{requirement.reference} is in the catalogue and no test "
            "evidences it, so it can never be anything but NOT EVIDENCED")


# --------------------------------------------------- the gaps are the point


def test_coverage_names_which_tests_did_not_produce_a_result(
        results: list[states.Result]) -> None:
    payload = regulatory.coverage(results)
    for row in payload["requirements"]:
        if row["status"] != regulatory.EVIDENCED:
            gaps = row["not_measured"] + row["not_run"]
            assert gaps, (
                f"{row['reference']} is {row['status']} and names no gap")
        for gap in row["not_measured"]:
            assert gap["why"], "a gap with no explanation is a blank cell"


def test_an_inapplicable_test_is_not_counted_as_a_gap() -> None:
    """A model with no challenger has no comparison evidence to be missing."""
    absent = [
        states.not_applicable(t.test_id, why="no challenger on this model")
        for t in registry.in_category(registry.CHAMPION_CHALLENGER)]
    payload = regulatory.coverage(absent)
    rows = {r["reference"]: r for r in payload["requirements"]}
    # MMG 2.9 is evidenced by CC-SWAPSET among others; with only the
    # champion-challenger family present and all of it inapplicable, the
    # reference reads NOT APPLICABLE rather than NOT EVIDENCED.
    assert rows["MMG 2.9"]["status"] == regulatory.NOT_APPLICABLE


def test_a_run_that_measured_nothing_is_not_evidenced() -> None:
    nothing = [states.not_matured(t.test_id, period="2026-01",
                                 closes="2027-01")
               for t in registry.TESTS]
    payload = regulatory.coverage(nothing)
    assert all(row["status"] == regulatory.NOT_EVIDENCED
               for row in payload["requirements"])
    assert payload["by_status"][regulatory.EVIDENCED] == 0


def test_a_reference_whose_tests_all_measured_is_evidenced(
        results: list[states.Result]) -> None:
    payload = regulatory.coverage(results)
    for row in payload["requirements"]:
        if row["status"] != regulatory.EVIDENCED:
            continue
        assert row["tests_measured"] > 0
        assert not row["not_run"]
        assert all(g["state"] == states.NOT_APPLICABLE
                   for g in row["not_measured"])


def test_adverse_results_are_surfaced_against_their_reference(
        results: list[states.Result]) -> None:
    """A reference evidenced entirely by breaches is still EVIDENCED.

    That is the point of separating the two questions. "Was it tested?" and
    "did it pass?" are different, and a coverage table that conflates them
    reports a well-evidenced failing model as a coverage gap.
    """
    payload = regulatory.coverage(results)
    breached = {r.test_id for r in results if r.adverse}
    surfaced = {t for row in payload["requirements"]
                for t in row["adverse_test_ids"]}
    assert breached <= surfaced


def test_the_status_tally_counts_every_requirement(
        results: list[states.Result]) -> None:
    payload = regulatory.coverage(results)
    assert sum(payload["by_status"].values()) == len(regulatory.REQUIREMENTS)
    assert set(payload["by_status"]) == set(regulatory.STATUSES)
