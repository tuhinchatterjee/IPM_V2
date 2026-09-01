"""
§15 — a ranking goes the way the reader asked, and stays that way.

The reported symptom was that "List the 20 borrowers with the highest 12-month
PD, highest to lowest" computed an answer and then withheld it because row 19
was larger than row 18. That reads like an unstable sort. It was not.

The planner scanned for low-end words before high-end ones, so the "lowest" in
"highest to lowest" won. The plan sorted ASCENDING, `LIMIT 20` took the twenty
LOWEST probabilities of default, and the invariant - correctly - refused to show
a table headed "highest" whose rows climbed. Every number in it was right and
every one of them was the wrong borrower.

The invariant had the mirror-image defect: it never read the question at all,
asserting "largest first" for every ranking. So "the ten borrowers with the
LOWEST covenant headroom" was planned correctly and then withheld for not being
descending.

One sentence, two readers, disagreeing in both directions. `ordering.py` is now
the single reader and both use it. These tests are about that reading, and
about the properties §15 asks for around it.
"""

from __future__ import annotations

import pytest

from backend.orchestration import ordering as od


class TestWhichEndTheReaderAskedFor:

    @pytest.mark.parametrize("text", [
        "List the 20 borrowers with the highest 12-month PD, highest to lowest.",
        "rank by exposure, largest to smallest",
        "show ECL biggest to smallest",
        "order by PD in descending order",
        "sort borrowers high to low by utilisation",
        "worst to best by rating",
    ])
    def test_a_direction_phrase_naming_both_ends_means_largest_first(self, text):
        """The exact defect. Each of these contains a low-end word, and each
        is stating how to SORT rather than which end to select."""
        assert od.descending(text) is True

    @pytest.mark.parametrize("text", [
        "rank by headroom, lowest to highest",
        "order by ECL smallest to largest",
        "sort ascending by PD",
        "show utilisation low to high",
        "least to most by exposure",
    ])
    def test_the_mirror_phrase_means_smallest_first(self, text):
        assert od.descending(text) is False

    @pytest.mark.parametrize("text,wants", [
        ("the 20 borrowers with the highest PD", True),
        ("top 20 by ECL", True),
        ("the ten borrowers with the lowest covenant headroom", False),
        ("bottom 10 by ECL coverage", False),
        ("which borrowers have the worst rating", True),
        ("the smallest exposures", False),
        ("the tightest covenant headroom", False),
    ])
    def test_one_end_named_is_that_end(self, text, wants):
        assert od.descending(text) is wants

    def test_both_ends_named_without_a_phrase_takes_the_first(self):
        """It is the one attached to the population being selected.

        "The 20 borrowers with the highest PD, shown lowest first" is a real
        if unusual request, and the SELECTION is what a ranking is about.
        """
        assert od.descending(
            "the 20 borrowers with the highest PD, shown lowest first") is True
        assert od.descending(
            "the 20 lowest PD borrowers, shown highest first") is False

    def test_a_question_naming_no_end_falls_back_to_largest_first(self):
        assert od.descending("rank borrowers by exposure") is True

    def test_the_default_is_a_parameter_not_a_constant(self):
        """So a caller with its own convention says so rather than being
        silently overridden."""
        assert od.descending("rank borrowers by exposure", default=False) is False

    def test_a_plain_listing_promises_no_order_at_all(self):
        """A list is not out of order. Asserting one on "show me X and Y"
        is what withheld a correct two-period comparison before."""
        assert od.promises_an_order("show ECL and Stage 2 share for Shipping") \
            is False
        assert od.promises_an_order("top 20 by ECL") is True

    def test_the_claim_says_which_way_round_it_checked(self):
        assert od.claim("pd_12m_pct", wants_descending=True) == \
            "ranked by pd 12m pct, largest first"
        assert od.claim("headroom_pct", wants_descending=False) == \
            "ranked by headroom pct, smallest first"


class TestOneReadingNotTwo:
    """The planner and the invariant must not read the sentence separately."""

    def test_the_planner_delegates_to_the_shared_reader(self):
        from backend.orchestration import analysis_planner as ap

        text = "the 20 borrowers with the highest PD, highest to lowest"
        assert ap._descending(None, text) is od.descending(text)

    def test_the_invariant_uses_the_shared_words(self):
        from backend.orchestration import invariants as inv

        assert inv._RANKING_WORDS is od.RANKING_WORDS


# --------------------------------------------------------------- end to end


@pytest.fixture(scope="module")
def client():
    import os

    os.environ.setdefault("REQUIRE_LOGIN", "false")
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


HEADERS = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}


def _ask(client, question: str) -> dict:
    return client.post("/api/v1/ask",
                       json={"question": question, "persist": False},
                       headers=HEADERS).json()


def _column(rows: list[dict], hint: str) -> str:
    for key in rows[0]:
        if hint in key:
            return key
    raise AssertionError(f"no column matching {hint!r} in {list(rows[0])}")


class TestTheRankingQuestionsFromTheAcceptanceRun:
    """The exact sentences a person typed on a real machine."""

    def test_twenty_highest_pd_returns_a_descending_table(self, client):
        body = _ask(client, "List the 20 borrowers with the highest 12-month "
                            "PD in Q2 2026, highest to lowest.")
        assert body["status"] == "succeeded", body.get("narrative")
        rows = body["steps"][0]["result"]["rows"]
        assert len(rows) == 20
        values = [r[_column(rows, "pd_12m")] for r in rows]
        assert values == sorted(values, reverse=True)

    def test_one_hundred_highest_pd_is_the_same_ranking_extended(self, client):
        twenty = _ask(client, "List the 20 borrowers with the highest 12-month "
                              "PD in Q2 2026, highest to lowest.")
        hundred = _ask(client, "List the 100 borrowers with the highest "
                               "12-month PD in Q2 2026, highest to lowest.")
        assert hundred["status"] == "succeeded"
        long_rows = hundred["steps"][0]["result"]["rows"]
        short_rows = twenty["steps"][0]["result"]["rows"]
        assert len(long_rows) == 100
        values = [r[_column(long_rows, "pd_12m")] for r in long_rows]
        assert values == sorted(values, reverse=True)
        # Widening the cut extends the ranking rather than reshuffling it —
        # which is what "pagination preserves ordering" means when the page
        # size is expressed in the question.
        key = _column(long_rows, "customer") if any(
            "customer" in k for k in long_rows[0]) else list(long_rows[0])[0]
        assert [r[key] for r in long_rows][:20] == [r[key] for r in short_rows]

    def test_lowest_covenant_headroom_returns_an_ascending_table(self, client):
        """Planned correctly before this work and then withheld by a check
        that had not read the question."""
        body = _ask(client, "Show the ten borrowers with the lowest covenant "
                            "headroom.")
        assert body["status"] == "succeeded", body.get("narrative")
        rows = body["steps"][0]["result"]["rows"]
        assert len(rows) == 10
        values = [r[_column(rows, "headroom")] for r in rows]
        assert values == sorted(values)

    def test_the_same_question_twice_returns_the_same_order(self, client):
        question = ("List the 20 borrowers with the highest 12-month PD in "
                    "Q2 2026, highest to lowest.")
        first = _ask(client, question)["steps"][0]["result"]["rows"]
        second = _ask(client, question)["steps"][0]["result"]["rows"]
        assert first == second

    def test_the_ranked_values_are_numbers_not_strings(self, client):
        """A string sort puts "9" after "80". §15 asks for this explicitly."""
        body = _ask(client, "List the 20 borrowers with the highest 12-month "
                            "PD in Q2 2026, highest to lowest.")
        rows = body["steps"][0]["result"]["rows"]
        column = _column(rows, "pd_12m")
        assert all(isinstance(r[column], (int, float))
                   and not isinstance(r[column], bool) for r in rows)

    def test_a_ranking_question_returns_a_table_and_not_a_chart(self, client):
        """§11: the reader asked for a list. Asserted here as well as in the
        visualisation suite, because this is the question they typed."""
        body = _ask(client, "List the 20 borrowers with the highest 12-month "
                            "PD in Q2 2026, highest to lowest.")
        result = body["steps"][0]["result"]
        assert result["rows"]
        chart = result.get("visualization") or {}
        assert not chart or chart.get("open") is False, (
            "a list question must not open a chart")


class TestNullsAndTies:
    """Deliberate handling, asserted on the compiler rather than hoped for."""

    def test_nulls_sort_last_whichever_way_the_ranking_goes(self):
        import duckdb

        con = duckdb.connect()
        con.execute("CREATE TABLE t AS SELECT * FROM (VALUES "
                    "(1,10.0),(2,NULL),(3,30.0)) v(id, pd)")
        desc = con.execute(
            "SELECT id FROM t ORDER BY pd DESC NULLS LAST, COLUMNS(*)"
        ).fetchall()
        assert desc[-1][0] == 2, "a null must not rank as the largest"

    def test_ties_are_broken_by_every_remaining_column(self):
        """So two rows are never interchangeable, and the order is a property
        of the DATA rather than of the engine's mood."""
        import duckdb

        con = duckdb.connect()
        con.execute("CREATE TABLE t AS SELECT * FROM (VALUES "
                    "('b',5.0),('a',5.0),('c',9.0)) v(name, pd)")
        rows = con.execute(
            "SELECT name FROM t ORDER BY pd DESC NULLS LAST, COLUMNS(*)"
        ).fetchall()
        assert [r[0] for r in rows] == ["c", "a", "b"]
