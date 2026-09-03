"""A composed review arrives as several analyses, through the real path.

`tests/orchestration/test_response_package.py` proves the shape rules. This
proves the thing they were written for: that a question CreditProbe answers
with five governed analyses reaches the reader as five, with their rows.

Everything here runs through `answer_investigation`, which is the function the
Ask endpoint calls. No fixtures stand in for the runtime, and no expected row
count is written down — the assertions are about the CONTRACT (every analysis
that produced rows is a block; every block points at the step holding those
rows; no block claims figures the step does not have), so they keep holding
when the investigation planner chooses differently or the published book moves.
"""

from __future__ import annotations

import pytest

from backend.orchestration.executor import answer_investigation


@pytest.fixture(scope="module")
def review():
    """One broad investigation, answered once for the whole module."""
    investigation, _ = answer_investigation(
        "Investigate the Shipping sector.", persist=False)
    return investigation


class TestTheAnalysesSurvive:

    def test_a_review_runs_more_than_one_governed_analysis(self, review) -> None:
        assert len(review.steps) > 1, (
            "A broad investigation that produced one step has either stopped "
            "probing or gone back to flattening its probes into a summary.")

    def test_every_analysis_that_ran_carries_its_own_rows(self, review) -> None:
        """The defect, stated directly.

        Four analyses used to be rendered as four SENTENCES about them. A step
        whose result has no rows is an analysis whose figures were thrown away
        between running it and showing it.
        """
        empty = [s.title for s in review.steps
                 if not ((s.result or {}).get("rows") or [])]
        assert not empty, f"analyses reached the answer with no rows: {empty}"

    def test_the_sub_analyses_are_not_all_the_same_result(self, review) -> None:
        """Five copies of one table is not five analyses."""
        shapes = {tuple(sorted(str(c.get("name"))
                               for c in ((s.result or {}).get("columns") or [])))
                  for s in review.steps}
        assert len(shapes) > 1


class TestThePackageDescribesWhatIsThere:

    def test_there_is_a_block_for_every_analysis(self, review) -> None:
        package = review.to_dict()["package"]
        assert package["counts"]["analyses"] == len(review.steps)

    def test_no_block_promises_rows_its_step_does_not_have(self, review) -> None:
        """A package that drifted from its steps is worse than none: the
        reader is told there is a stage distribution and finds an empty panel
        where it should be."""
        by_index = {s.index: s for s in review.steps}
        for block in review.to_dict()["package"]["blocks"]:
            if block["step_index"] < 0:
                continue
            step = by_index[block["step_index"]]
            assert block["row_count"] == len((step.result or {}).get("rows") or [])

    def test_a_drawn_block_names_the_shape_it_is_drawn_as(self, review) -> None:
        for block in review.to_dict()["package"]["blocks"]:
            if block["drawn"]:
                assert block["visual"], (
                    f"{block['title']!r} is marked drawn with no shape")

    def test_every_block_says_why_it_is_that_shape(self, review) -> None:
        assert all(block["why"]
                   for block in review.to_dict()["package"]["blocks"])


class TestOneQuestionCanStillBeOneAnswer:

    def test_a_single_figure_question_is_one_block(self) -> None:
        """The rule cuts both ways. A question with one figure behind it is
        made worse, not better, by four analyses around it."""
        investigation, _ = answer_investigation("What is total ECL?",
                                                persist=False)
        package = investigation.to_dict()["package"]
        assert package["counts"]["blocks"] == 1
        assert package["counts"]["drawn"] == 0

    def test_a_single_figure_is_a_figure_rather_than_a_chart(self) -> None:
        investigation, _ = answer_investigation("What is total ECL?",
                                                persist=False)
        block = investigation.to_dict()["package"]["blocks"][0]
        assert "kpi" in block["kinds"]


class TestTheDeteriorationBlueprintThroughTheRealPath:
    """"Shipping has deteriorated. Show me everything." — the Case 50 shape.

    The blueprint decides the analyses; nothing here asserts a number. What is
    asserted is that a request for a COMPLETE review comes back complete, that
    the figures in it reconcile with an independent read of the same dataset,
    and that anything the blueprint wanted and could not get is said out loud
    rather than dropped.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def review(cls):
        investigation, _ = answer_investigation(
            "Shipping has deteriorated. Show me everything.", persist=False)
        return investigation

    def test_a_complete_review_is_ten_analyses_or_more(self, review) -> None:
        package = review.to_dict()["package"]
        assert package["counts"]["analyses"] >= 10, (
            "A complete segment deterioration review is the named set of "
            "analyses, not the five highest-scoring of them.")

    def test_it_draws_several_of_them(self, review) -> None:
        """Multi-analysis is not multi-visual on its own. A review of a
        deteriorating segment is mostly movements, and a movement over an
        ordered period axis is a picture."""
        assert review.to_dict()["package"]["counts"]["drawn"] >= 3

    def test_nothing_it_could_not_read_is_silently_dropped(self, review) -> None:
        """Every asked analysis is either a block or a stated caveat."""
        from backend.orchestration import deterioration as dt

        asked = {item["label"] for item in dt.questions("Shipping")}
        shown = {block["title"]
                 for block in review.to_dict()["package"]["blocks"]}
        said = " ".join(review.narrative.caveats)
        missing = [label for label in asked
                   if label not in shown and label not in said]
        assert not missing, f"asked for and never accounted for: {missing}"

    def test_the_exposure_block_reconciles_with_an_independent_read(
            self, review) -> None:
        """The Ask path and the blueprint's own read are one book.

        Computed twice, deliberately: `deterioration.review` reads
        `ifrs9_staging` directly, and the block below came through the
        semantic reader, the validator and the runtime. A disagreement means a
        review is quoting a figure nobody can reproduce.
        """
        from backend.orchestration import deterioration as dt

        independent = dt.review("Shipping", window=dt.QOQ)
        expected = next(m for m in independent.movements
                        if m.lens.key == "exposure")

        step = next((s for s in review.steps
                     if s.title == "Exposure at default"), None)
        assert step is not None, "the exposure analysis is not in the review"
        values = [float(row[name])
                  for row in (step.result or {}).get("rows") or []
                  for name in row
                  if name == "ead"]
        assert values, "the exposure block carries no exposure figure"
        assert round(max(values), 3) == round(
            max(expected.opening, expected.closing), 3)
