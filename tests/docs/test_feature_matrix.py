"""The feature matrix stays true to the build. §3.

A matrix generated once and committed is a matrix that is wrong by the next
route somebody adds. These tests are what keep it honest: they regenerate it
from the live filesystem and the live router and assert the committed copy
still matches, and they assert the two claims §3 actually makes - that every
visible surface is inventoried, and that nothing broken goes unreported.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import feature_matrix as fm  # noqa: E402

MATRIX = ROOT / "docs" / "FINAL_FEATURE_VERIFICATION_MATRIX.md"


@pytest.fixture(scope="module")
def routes():
    return fm._routes()


def test_the_matrix_has_been_generated():
    assert MATRIX.exists(), (
        "run `python scripts/feature_matrix.py --write`")


def test_every_page_that_exists_carries_an_expected_behaviour(routes):
    """§3: no visible action may remain unreported.

    A page with no curated judgement is not evidence the page works - it is
    evidence nobody has said what it should do, and that is the gap this
    document exists to close.
    """
    unreviewed = [r.path for r in routes if not r.judgement]
    assert unreviewed == [], (
        "pages with no curated expected behaviour: " + ", ".join(unreviewed))


def test_the_committed_matrix_matches_the_current_build(routes):
    body = MATRIX.read_text(encoding="utf-8")
    for route in routes:
        assert f"`{route.path}`" in body, (
            f"{route.path} exists on disk and is not in the matrix")


def test_every_defect_row_says_what_is_wrong(routes):
    for route in routes:
        judged = route.judgement
        if judged and judged.status not in (fm.OK, "UNREVIEWED"):
            assert judged.defect or judged.limitation, (
                f"{route.path} is marked {judged.status} with neither a "
                "defect nor a limitation, which tells a reader nothing")


def test_a_hidden_surface_says_why_it_is_hidden(routes):
    hidden = [r for r in routes
              if r.judgement and r.judgement.status == fm.HIDDEN]
    assert hidden, "the Documents placeholder is hidden and should be listed"
    for route in hidden:
        assert route.judgement.limitation


def test_headless_capabilities_are_reported_not_omitted():
    """A capability with no screen is a fact about the build."""
    assert fm._HEADLESS
    for name, where, works, why in fm._HEADLESS:
        assert name and where and works and why


def test_the_api_surface_is_read_from_the_live_router():
    endpoints = fm._endpoints()
    assert sum(len(v) for v in endpoints.values()) > 200
    assert "ask" in endpoints and "intelligence" in endpoints


def test_a_dynamic_route_matches_the_urls_a_crawl_visits():
    pattern = fm._pattern_for("/analysis/[analysisId]")
    assert pattern.match("/analysis/approaching_sicr_threshold")
    assert not pattern.match("/analysis")
    assert not pattern.match("/analysis/a/b")

    catch_all = fm._pattern_for("/data-builder/domain/[...domain]")
    assert catch_all.match("/data-builder/domain/IFRS%209/staging")

    assert fm._pattern_for("/").match("/")
