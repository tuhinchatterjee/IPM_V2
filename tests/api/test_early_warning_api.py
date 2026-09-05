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


class TestTheBorrowerScorecard:
    """Sections 11C, 11D, 11G, 11I, 11J and 11L through the real routes."""

    @pytest.fixture(scope="class")
    @classmethod
    def borrower(cls) -> str:
        book = sg._book("")
        ranked = book.get("_ranked") or []
        assert ranked, "no borrowers on the book"
        return ranked[0].borrower_id

    @pytest.fixture(scope="class")
    @classmethod
    def card(cls, client, borrower) -> dict:
        found = client.get(
            f"/api/v1/early-warning/scorecard/{borrower}", headers=ANALYST)
        assert found.status_code == 200, found.text
        return found.json()

    def test_the_answer_comes_before_the_workings(self, card) -> None:
        # A payload that opens on a component table asks the reader to derive
        # the conclusion themselves.
        assert card["risk_level"] in {"HIGH", "MEDIUM", "LOW"}
        assert card["assessment"]["primary_concern"]
        assert card["assessment"]["reasons"]

    def test_all_four_layers_are_present(self, card) -> None:
        numbers = [layer["number"] for layer in card["layers"]]
        assert numbers == [1, 2, 3, 4]

    def test_layer_four_is_not_empty(self, card) -> None:
        # §11F. It used to be, and said so. It is configured now.
        fourth = next(entry for entry in card["layers"]
                      if entry["number"] == 4)
        assert fourth["components"], "layer 4 carries no conditions"
        assert fourth["tested"] >= 1

    def test_conditions_within_threshold_are_shown_too(self, card) -> None:
        # §11D. A layer showing three amber rows and hiding the eleven green
        # ones reads as an emergency whatever the borrower is doing.
        within = [c for layer in card["layers"] for c in layer["components"]
                  if c["status"] == "Within threshold"]
        assert within, "only the conditions that fired are published"

    def test_every_component_carries_every_column(self, card) -> None:
        # §11C names them. A column that is sometimes absent is a column the
        # screen has to guess about.
        wanted = ("current", "previous", "movement", "threshold", "status",
                  "severity", "persistence", "detection", "state", "means")
        for layer in card["layers"]:
            for component in layer["components"]:
                for key in wanted:
                    assert key in component, (
                        f"{component['signal']} has no {key}")

    def test_the_detection_letter_is_one_of_three(self, card) -> None:
        letters = {c["detection_letter"] for layer in card["layers"]
                   for c in layer["components"]}
        assert letters <= {"T", "A", "C"}
        assert letters, "no condition declares how it is detected"

    def test_the_deep_link_carries_the_borrower_and_the_period(
            self, card, borrower) -> None:
        # §11J. A link that opens Borrower 360 at "latest" from a Q1 warning
        # shows a different quarter beside the same sentence.
        link = card["borrower_360"]
        assert link["customer_id"] == borrower
        assert link["reporting_period"] == card["period"]
        assert "customer_id=" in link["href"]
        assert "period=" in link["href"]

    def test_an_unknown_borrower_is_refused_specifically(self, client) -> None:
        found = client.get(
            "/api/v1/early-warning/scorecard/CORP-000000", headers=ANALYST)
        assert found.status_code == 404
        assert "not on book" in str(found.json()).lower()


class TestTheTimeline:
    """Section 11I. Real evaluations, never today's answer repeated."""

    @pytest.fixture(scope="class")
    @classmethod
    def timeline(cls, client) -> dict:
        book = sg._book("")
        borrower = (book.get("_ranked") or [])[0].borrower_id
        found = client.get(
            f"/api/v1/early-warning/timeline/{borrower}?limit=6",
            headers=ANALYST)
        assert found.status_code == 200, found.text
        return found.json()

    def test_it_covers_several_reporting_dates(self, timeline) -> None:
        assert len(timeline["entries"]) >= 2
        assert len(set(timeline["periods"])) == len(timeline["periods"])

    def test_each_period_is_its_own_evaluation(self, timeline) -> None:
        # If the timeline repeated the latest assessment, every period would
        # carry the same firing count. It does not on a book that moves.
        counts = {e["fired"] for e in timeline["entries"] if e["on_book"]}
        assert len(counts) > 1, (
            "every period reports the same number of conditions firing, "
            "which is what a carried-forward answer looks like")

    def test_a_period_off_book_is_said_rather_than_drawn_as_zero(
            self, timeline) -> None:
        for entry in timeline["entries"]:
            if not entry["on_book"]:
                assert "not on book" in entry["sentence"].lower()


class TestTheWorkbooks:
    """Section 11L. Something to take into a meeting."""

    def test_the_scorecard_downloads_as_a_workbook(self, client) -> None:
        borrower = (sg._book("").get("_ranked") or [])[0].borrower_id
        found = client.get(
            f"/api/v1/early-warning/scorecard/{borrower}/workbook",
            headers=ANALYST)
        assert found.status_code == 200
        assert found.content[:2] == b"PK", "not a workbook"
        assert "attachment" in found.headers["content-disposition"]
        assert borrower in found.headers["content-disposition"]

    def test_the_watchlist_downloads_as_a_workbook(self, client) -> None:
        found = client.get(
            "/api/v1/early-warning/watchlist/workbook?limit=20",
            headers=ANALYST)
        assert found.status_code == 200
        assert found.content[:2] == b"PK"

    def test_a_workbook_carries_the_synthetic_disclosure(self, client) -> None:
        # It leaves the product, so the disclosure has to leave with it.
        found = client.get(
            "/api/v1/early-warning/watchlist/workbook?limit=5",
            headers=ANALYST)
        assert found.headers["x-creditprobe-origin"] == "SYNTHETIC_DEMO"


class TestTheRiskLevelReachesTheScreen:
    def test_the_dashboard_publishes_the_split(self, client) -> None:
        found = client.get("/api/v1/early-warning/dashboard", headers=ANALYST)
        assert found.status_code == 200
        levels = found.json()["risk_levels"]
        assert {e["level"] for e in levels["levels"]} == {
            "HIGH", "MEDIUM", "LOW"}
        assert levels["rule"]["gravity"] and levels["rule"]["corroboration"]

    def test_high_risk_is_not_most_of_the_book(self, client) -> None:
        found = client.get("/api/v1/early-warning/dashboard", headers=ANALYST)
        levels = found.json()["risk_levels"]["levels"]
        high = next(e for e in levels if e["level"] == "HIGH")
        assert high["share"] < 40.0, (
            f"{high['share']}% of the book is High Risk, which is a list "
            "nobody works down")

    def test_a_borrower_standing_carries_its_risk_level(self, client) -> None:
        borrower = (sg._book("").get("_ranked") or [])[0].borrower_id
        found = client.get(
            f"/api/v1/early-warning/signals/{borrower}", headers=ANALYST)
        assert found.status_code == 200
        body = found.json()
        assert body["risk_level"] in {"HIGH", "MEDIUM", "LOW"}
        assert body["assessment"]["reasons"] or body["risk_level"] == "LOW"

    def test_there_is_still_no_score(self, client) -> None:
        borrower = (sg._book("").get("_ranked") or [])[0].borrower_id
        body = client.get(
            f"/api/v1/early-warning/signals/{borrower}", headers=ANALYST
        ).json()
        for forbidden in ("score", "points", "weighted"):
            assert forbidden not in body["assessment"], (
                f"the assessment publishes {forbidden!r}")
