"""
§20, §26, §27, §28 — Early Warning through the real routes.

The unit suites prove the taxonomy fires correctly and the review writes what
it should. What only a route can prove is what the PRODUCT receives: that the
signal reaches a screen without a score attached, that reading is separated
from writing by permission rather than by convention, and that the preview
which lets somebody check the rule before running it changes nothing.
"""

from __future__ import annotations

import pytest

from backend.early_warning import cases as ec
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx
from tests.conftest import database_available


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


ANALYST = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}
VIEWER = {"X-IPM-Role": "VIEWER", "X-IPM-User-Id": "2"}


class TestTheTaxonomyIsPublished:

    def test_every_signal_says_who_owns_its_threshold(self, client):
        body = client.get("/api/v1/early-warning/taxonomy").json()
        assert body["signals"]
        for signal in body["signals"]:
            assert signal["owner"] == tx.THRESHOLD_OWNER
            assert signal["version"] == tx.TAXONOMY_VERSION
            assert signal["dataset"]
            assert signal["field"]

    def test_the_flat_list_and_the_families_agree(self, client):
        """Two views of one taxonomy, and they cannot disagree about it.

        A screen groups by family; a search reads the flat list. Deriving
        either from the other at each call site is how two callers end up
        publishing different signal counts.
        """
        body = client.get("/api/v1/early-warning/taxonomy").json()
        grouped = [s["key"] for f in body["families"] for s in f["signals"]]
        assert sorted(grouped) == sorted(s["key"] for s in body["signals"])
        assert body["signal_count"] == len(body["signals"])

    def test_what_cannot_be_watched_for_is_named(self, client):
        """§7. A watchlist quietly missing a family is worse than one that
        says which family it is missing."""
        body = client.get("/api/v1/early-warning/taxonomy").json()
        assert body["unavailable"]
        for missing in body["unavailable"]:
            assert missing["means"]
            assert missing["family"] in tx.FAMILIES


class TestTheSignalReachesAScreenWithoutAScore:

    def test_the_book_comes_back_ranked_and_unscored(self, client):
        body = client.get(
            "/api/v1/early-warning/signals?limit=5").json()
        assert body["returned"] == 5
        assert body["evaluated"] > len(body["borrowers"])
        for borrower in body["borrowers"]:
            assert "score" not in borrower
            assert borrower["breadth"] >= 1
            assert borrower["sentence"]

    def test_the_ranking_bounds_what_is_returned_not_what_is_read(self,
                                                                  client):
        """The reporting lie this route must not tell.

        A 'worst five' assembled from five rows loaded is indefensible. Every
        borrower is evaluated; five are returned; the response says both.
        """
        five = client.get("/api/v1/early-warning/signals?limit=5").json()
        twenty = client.get("/api/v1/early-warning/signals?limit=20").json()
        assert five["evaluated"] == twenty["evaluated"]
        assert [b["borrower_id"] for b in twenty["borrowers"]][:5] == \
               [b["borrower_id"] for b in five["borrowers"]]

    def test_one_borrower_gets_fired_cured_and_untested(self, client):
        """Three lists, because 'nothing fires' and 'nothing could be
        tested' are different answers and only one is reassuring."""
        book = client.get("/api/v1/early-warning/signals?limit=1").json()
        who = book["borrowers"][0]["borrower_id"]
        body = client.get(f"/api/v1/early-warning/signals/{who}").json()
        assert set(body) >= {"fired", "cured", "untested", "sentence"}
        assert "score" not in body

    def test_a_borrower_not_on_book_is_a_404_with_a_sentence(self, client):
        response = client.get("/api/v1/early-warning/signals/NOT-A-BORROWER")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error"] == "not_found"
        assert "not on book" in detail["message"]

    def test_the_headline_counts_situations_not_raw_signals(self, client):
        body = client.get("/api/v1/early-warning/signals?limit=1").json()
        headline = body["headline"]
        assert headline["borrowers"] == body["evaluated"]
        assert headline["with_a_new_signal"] <= headline["borrowers"]
        assert headline["means"]["booked_stage_2_or_worse"]


class TestThePreviewChangesNothing:

    def test_it_reports_the_rule_and_what_it_would_raise(self, client):
        body = client.get(
            "/api/v1/early-warning/review/preview?limit=10").json()
        assert body["evaluated"] > 1_000
        assert body["qualified"] > 0
        assert body["returned"] == 10
        assert body["below_the_limit"] == body["qualified"] - 10
        assert set(body["rules"]) <= set(body["rule_meanings"])
        for row in body["would_raise"]:
            assert row["rule"] in body["rule_meanings"]
            assert row["why"]

    def test_every_rule_it_reports_is_explained(self, client):
        body = client.get("/api/v1/early-warning/review/preview").json()
        for rule in body["rules"]:
            assert body["rule_meanings"][rule]

    def test_a_viewer_may_check_the_rule_before_anyone_runs_it(self, client):
        assert client.get("/api/v1/early-warning/review/preview",
                          headers=VIEWER).status_code == 200

    def test_it_matches_what_the_review_would_do(self, client):
        body = client.get(
            "/api/v1/early-warning/review/preview?limit=7").json()
        book = ec.standings_for()
        expected = [s.borrower_id for s in sg.rank(
            [s for s in book["standings"] if ec.worth_a_case(s).raise_it])][:7]
        assert [r["borrower_id"] for r in body["would_raise"]] == expected


@pytest.mark.skipif(not database_available(),
                    reason="PostgreSQL is not reachable")
class TestWritingFindingsIsAPermission:

    def test_a_viewer_may_not_write_findings_onto_a_queue(self, client):
        response = client.post("/api/v1/early-warning/review",
                               json={"budget": 1}, headers=VIEWER)
        assert response.status_code == 403

    def test_an_analyst_may_run_it_and_gets_the_counts_back(self, client):
        """Runs against the real database and leaves it as it found it.

        Deliberately does NOT empty `risk_cases`: the bootstrap's Q2 2026
        review lives in this table and the readiness gate checks it is there.
        The cases this test opens are removed by id afterwards; everything
        else is left alone.
        """
        from sqlalchemy import text

        from backend.db.engine import SessionLocal

        session = SessionLocal()
        before = {row[0] for row in
                  session.execute(text("SELECT id FROM risk_cases")).all()}
        session.execute(
            text("DELETE FROM risk_cases WHERE evidence ? 'review_version'"))
        session.commit()
        try:
            response = client.post("/api/v1/early-warning/review",
                                   json={"budget": 3}, headers=ANALYST)
            assert response.status_code == 200
            body = response.json()
            assert body["opened"] == 3
            assert body["review_version"] == ec.REVIEW_VERSION
            assert body["taxonomy_version"] == tx.TAXONOMY_VERSION
            assert body["not_opened"] > 0
            assert body["sentence"].endswith(".")

            again = client.post("/api/v1/early-warning/review",
                                json={"budget": 3}, headers=ANALYST).json()
            assert again["opened"] == 0
            assert again["refreshed"] == 3
            assert again["case_ids"] == body["case_ids"]
        finally:
            session.rollback()
            if before:
                session.execute(
                    text("DELETE FROM risk_cases WHERE id <> ALL(:keep)"),
                    {"keep": list(before)})
            else:
                session.execute(text("DELETE FROM risk_cases"))
            session.commit()
            session.close()

    def test_the_budget_is_bounded_by_the_route_not_by_the_caller(self,
                                                                  client):
        response = client.post("/api/v1/early-warning/review",
                               json={"budget": 100_000}, headers=ANALYST)
        assert response.status_code == 422
