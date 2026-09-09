"""
Forty-eight things a person asks a What-If thread before configuring a shock,
and the table each one must actually produce.

The defect this corpus exists for
---------------------------------
A UAT tester typed:

    "Can you give me the rating-wise PDs, getting rid of stages?"

and was told the profile views answer it. That is a redirect, not an answer,
and it arrives at exactly the wrong moment: the reader is deciding what to
stress, and the size of a sensible PD shock depends entirely on what the PD
currently is. So every case here asserts that the product COMPUTED something,
and the assertions are on the reading — the dimension, the metrics, the
filters — rather than on a message.

The last group asserts the other half of the contract. "Increase PD for Stage 1
BB rating by 10%" is a scenario, and reading it as a breakdown would answer a
question nobody asked while the shock they wanted went unconfigured. A reader
that says yes to everything is not a reader.

Runs without a language model: the analysis reader is regular expressions over
a governed vocabulary, so the same sentence always produces the same request.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from backend.whatif import analysis as an

_CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "whatif_analysis_cases.json").read_text())
CASES = _CORPUS["cases"]

_LAKE: bool
try:
    from backend.whatif import domain as dm
    dm.book("")
    _LAKE = True
except Exception:  # pragma: no cover - the lake is not built here
    _LAKE = False

needs_lake = pytest.mark.skipif(not _LAKE, reason="the Corporate book is not built")


def _id(case: dict) -> str:
    return case["q"][:58]


def _request(case: dict) -> an.Request | None:
    """The request a case produces, in the thread state the case describes."""
    previous = None
    if case.get("follows"):
        previous = an.read(case["follows"])
        assert previous is not None, (
            f"the setup question {case['follows']!r} must itself read as an "
            "analysis, or the follow-up is not being tested")
    return an.read(case["q"], previous=previous)


class TestTheCorpusItself:

    def test_it_is_large_enough_to_measure_something(self):
        assert len(CASES) >= 30, (
            "the product requirement asks for at least thirty quick-analysis "
            f"questions; this corpus has {len(CASES)}")

    def test_no_question_appears_twice(self):
        asked = [c["q"] for c in CASES]
        assert len(asked) == len(set(asked))

    def test_it_contains_both_halves_of_the_contract(self):
        assert sum(1 for c in CASES if c.get("none")) >= 5, (
            "a corpus of only questions that should be answered cannot catch "
            "a reader that answers everything")
        assert sum(1 for c in CASES if c.get("suggests")) >= 3


@pytest.mark.parametrize("case", CASES, ids=_id)
class TestEveryCase:

    def test_it_is_read_as_the_right_kind_of_thing(self, case):
        if case.get("suggests"):
            assert an.wants_a_suggestion(case["q"]), (
                "this asks how far to move something, not what it currently is")
            return
        request = _request(case)
        if case.get("none"):
            assert request is None, (
                "this is a scenario; reading it as a breakdown answers a "
                f"question nobody asked. Read as: {request}")
            return
        assert request is not None, "this must produce a table, not a redirect"

    def test_it_reads_the_dimension_the_question_named(self, case):
        if case.get("none") or case.get("suggests") or "dim" not in case:
            return
        request = _request(case)
        assert request.dimension == case["dim"]

    def test_every_metric_the_question_named_is_a_column(self, case):
        if case.get("none") or case.get("suggests"):
            return
        request = _request(case)
        for key in case.get("has", []):
            assert key in request.metrics, (
                f"{key} was named and is not in {request.metrics}")
        for key in case.get("hasnt", []):
            assert key not in request.metrics, (
                f"{key} was not named and should not be a column")

    def test_every_filter_survives_the_reading(self, case):
        """A filter that parsed and was then dropped prices the whole book."""
        if case.get("none"):
            return
        request = (an.read(case["q"]) if case.get("suggests")
                   else _request(case))
        if case.get("suggests"):
            # A suggestion narrows from the sentence directly, so the
            # population is asserted on the suggestion itself below.
            return
        if "stages" in case:
            assert list(request.stages) == case["stages"]
        if "grades" in case:
            assert list(request.grades) == case["grades"]
        if "sectors" in case:
            assert list(request.sectors) == case["sectors"]
        if "threshold" in case:
            assert list(request.threshold or []) == case["threshold"]
        if "limit" in case:
            assert request.limit == case["limit"]
        if "by_stage" in case:
            assert request.by_stage == case["by_stage"]
        if "superlative" in case:
            assert request.superlative == case["superlative"]

    @needs_lake
    def test_it_actually_computes(self, case):
        """The whole point: a table with figures in it, not a message."""
        if case.get("none"):
            return
        if case.get("suggests"):
            body = an.suggest(case["q"])
            assert body["kind"] == "suggestion"
            assert body["measure"] == case["measure"]
            request = an.Request.from_dict(body["request"])
            if "grades" in case:
                assert list(request.grades) == case["grades"]
            if "sectors" in case:
                assert list(request.sectors) == case["sectors"]
            if "stages" in case:
                assert list(request.stages) == case["stages"]
            assert body["options"], (
                "a suggestion with no magnitudes hands the question back")
            for option in body["options"]:
                assert option["magnitude"] > 0
                assert option["instruction"]
            assert body["borrowers"] > 0
            return
        body = an.run(_request(case))
        assert body["period"]
        assert body["kind"] in ("breakdown", "borrowers")
        if body["kind"] == "borrowers":
            assert body["rows"], "a borrower list with no borrowers is not an answer"
            assert all(r["borrower_id"] for r in body["rows"])
            return
        assert body["rows"], "a breakdown with no rows is not an answer"
        assert body["total"]
        populated = [r for r in body["rows"]
                     if (r["cells"]["borrowers"]["value"] or 0) > 0]
        assert populated, "every row is empty; the filter removed the book"

    @needs_lake
    def test_a_reading_is_written_over_it(self, case):
        if case.get("none") or case.get("suggests"):
            return
        from backend.whatif import narrative as nr

        body = an.run(_request(case))
        reading = nr.interpret_analysis(body)
        assert reading["paragraphs"] and reading["paragraphs"][0].strip()
        assert reading["headline"].strip()
        assert reading["verified"] is True
        # Whoever wrote it, every figure in it is in the table.
        assert not nr.check([*reading["paragraphs"], reading["headline"]],
                            reading["evidence"])


@needs_lake
class TestTheTableItself:
    """Properties every quick-analysis table has, whatever was asked."""

    def test_a_rating_table_is_in_the_governed_order_and_never_sorted(self):
        from backend.corporate import ratingscale as rs

        body = an.run(an.read("Show rating-wise PDs."))
        labels = [r["label"] for r in body["rows"]]
        assert labels == list(rs.ALL_STATES)
        assert labels[:19] == list(rs.PERFORMING)
        assert labels[18] == "C" and labels[19] == "D"
        assert labels != sorted(labels)

    def test_every_grade_appears_even_where_the_book_holds_none(self):
        body = an.run(an.read("Show rating-wise PDs."))
        assert len(body["rows"]) == 20
        empty = [r["label"] for r in body["rows"]
                 if not r["cells"]["borrowers"]["value"]]
        assert empty, "this book has grades nothing is rated; they must show"

    def test_stage_three_is_measured_at_one_hundred_per_cent(self):
        body = an.run(an.read("Show applicable PD by stage."))
        row = next(r for r in body["rows"] if r["label"] == "Stage 3")
        assert row["cells"]["applicable_pd"]["value"] == 100.0
        assert row["cells"]["applicable_pd"]["weighted"] == 100.0

    def test_a_rate_is_reported_both_plainly_and_exposure_weighted(self):
        body = an.run(an.read("Show LGD by sector."))
        for row in body["rows"]:
            if row["cells"]["borrowers"]["value"]:
                assert row["cells"]["lgd"]["value"] is not None
                assert row["cells"]["lgd"]["weighted"] is not None

    def test_coverage_is_summed_over_summed_and_not_a_mean_of_ratios(self):
        body = an.run(an.read("Show ECL coverage by rating."))
        total = body["total"]["cells"]
        expected = total["ecl"]["value"] / total["exposure"]["value"] * 100.0
        # Rounded to four places for display; the identity is what is asserted,
        # not the last digit of it.
        assert total["ecl_coverage"]["value"] == pytest.approx(expected, abs=5e-5)
        # And it is NOT the mean of the rows' own ratios, which is the mistake
        # this test exists to catch.
        rows = [r["cells"]["ecl_coverage"]["value"] for r in body["rows"]
                if r["cells"]["borrowers"]["value"]]
        assert total["ecl_coverage"]["value"] != pytest.approx(
            sum(rows) / len(rows), abs=1e-3)

    def test_the_total_reconciles_to_the_rows(self):
        body = an.run(an.read("Show ECL by rating."))
        assert body["total"]["cells"]["ecl"]["value"] == pytest.approx(
            sum(r["cells"]["ecl"]["value"] for r in body["rows"]), rel=1e-9)
        assert body["total"]["cells"]["borrowers"]["value"] == sum(
            r["cells"]["borrowers"]["value"] for r in body["rows"])

    def test_a_breakdown_never_touches_the_scenario(self):
        """It is a read. The state it was given comes back untouched."""
        request = an.read("Show LGD by sector.")
        assert request.to_dict()["dimension"] == "sector"
        body = an.run(request)
        assert "state" not in body
        assert body["request"] == request.to_dict()

    def test_a_follow_up_keeps_what_it_did_not_mention(self):
        first = an.read("Show lifetime PD by rating.")
        second = an.read("Only show BBB- and weaker.", previous=first)
        assert second.dimension == first.dimension
        assert second.metrics == first.metrics
        assert second.grades and "BBB-" in second.grades and "AAA" not in second.grades
        third = an.read("Show exposure too.", previous=second)
        assert third.grades == second.grades
        assert "exposure" in third.metrics
        assert "lifetime_pd" in third.metrics, (
            "a follow-up that ADDS a column must not throw away the table")

    def test_a_suggestion_is_measured_rather_than_chosen(self):
        body = an.suggest("What would be a sensible PD shock for BB borrowers?")
        assert body["history"]["observations"] > 0
        assert [o["severity"] for o in body["options"]] == [
            name for _, name, _ in an.LADDER]
        magnitudes = [o["magnitude"] for o in body["options"]]
        assert magnitudes == sorted(magnitudes), (
            "a severity ladder whose magnitudes are not increasing is not a "
            "ladder")
        assert body["question"].endswith("?")
