"""The corpus itself is checkable, whatever the product scores against it.

Two different things are tested here and they must not be confused.

`TestTheCorpusIsWellFormed` checks the CASES: fifty of them, numbered, each
with every field, no case that both requires and prohibits the same concept,
no two cases asking the same question. That is about the corpus and it must
always pass.

`TestTheProductAgainstTheCorpus` runs the questions and asserts a floor rather
than perfection. The floor is what the product actually does on this HEAD, and
`docs/MULTI_ANALYSIS_CORPUS.md` lists every case that does not clear it, with
its root cause. A floor set at fifty out of fifty would have to be met by
tuning the corpus to the product, which is the one thing an evaluation corpus
must never be.
"""

from __future__ import annotations

import json
import pathlib

import pytest

CORPUS = pathlib.Path(__file__).parent / "multi_analysis_cases.json"

#: What the product scores today, per check. Raise these when a defect in
#: docs/MULTI_ANALYSIS_CORPUS.md is fixed; never lower one to make a run pass.
FLOOR = {"ANSWERED": 47, "BLOCKS": 46, "KINDS": 42, "CLEAN": 50}
FLOOR_ALL_FOUR = 41

REQUIRED_FIELDS = (
    "id", "family", "question", "intent", "required_concepts",
    "optional_concepts", "prohibited_concepts", "period_behaviour", "grain",
    "expected_blocks", "expected_kinds", "visualisation",
    "interpretation_themes", "prohibited_claims",
)


@pytest.fixture(scope="module")
def corpus() -> list[dict]:
    return json.loads(CORPUS.read_text())["cases"]


class TestTheCorpusIsWellFormed:

    def test_there_are_fifty_of_them(self, corpus) -> None:
        assert len(corpus) == 50
        assert [c["id"] for c in corpus] == list(range(1, 51))

    def test_every_case_carries_every_field(self, corpus) -> None:
        for case in corpus:
            missing = [f for f in REQUIRED_FIELDS if f not in case]
            assert not missing, f"case {case['id']} is missing {missing}"

    def test_no_case_both_requires_and_prohibits_a_concept(self, corpus) -> None:
        for case in corpus:
            clash = set(case["required_concepts"]) & set(
                case["prohibited_concepts"])
            assert not clash, f"case {case['id']} contradicts itself on {clash}"

    def test_no_two_cases_ask_the_same_question(self, corpus) -> None:
        asked = [c["question"] for c in corpus]
        assert len(set(asked)) == len(asked)

    def test_the_block_ranges_are_ranges(self, corpus) -> None:
        for case in corpus:
            low, high = case["expected_blocks"]
            assert 0 <= low <= high, f"case {case['id']}: [{low}, {high}]"

    def test_every_expected_kind_is_a_kind_the_package_knows(self, corpus) -> None:
        from backend.orchestration import package as pk

        for case in corpus:
            unknown = set(case["expected_kinds"]) - set(pk.KINDS)
            assert not unknown, f"case {case['id']} expects {unknown}"

    def test_a_clarification_is_only_correct_where_the_case_says_why(
            self, corpus) -> None:
        for case in corpus:
            if case.get("clarification_is_correct"):
                assert case.get("why_clarify"), (
                    f"case {case['id']} accepts a clarification without "
                    "saying why one is right")

    def test_the_complete_deterioration_case_asks_for_the_whole_review(
            self, corpus) -> None:
        case = next(c for c in corpus if c["id"] == 50)
        assert case["family"] == "complete_deterioration"
        assert case["expected_blocks"][0] >= 10
        assert "chart" in case["expected_kinds"]


class TestTheProductAgainstTheCorpus:
    """Slow: fifty questions through the runtime. Roughly twenty seconds."""

    @pytest.fixture(scope="class")
    @classmethod
    def scored(cls):
        import sys

        root = str(pathlib.Path(__file__).resolve().parents[2])
        if root not in sys.path:
            sys.path.insert(0, root)
        from scripts.evaluate_multi_analysis import CHECKS, load, run_one

        results = [run_one(case) for case in load()]
        return {
            "per_check": {c: sum(1 for r in results if r["checks"].get(c))
                          for c in CHECKS},
            "all_four": sum(1 for r in results if all(r["checks"].values())),
            "results": results,
        }

    @pytest.mark.parametrize("check", sorted(FLOOR))
    def test_the_check_has_not_gone_backwards(self, scored, check) -> None:
        got = scored["per_check"][check]
        assert got >= FLOOR[check], (
            f"{check} scored {got}, was {FLOOR[check]}. "
            "A case that used to pass no longer does.")

    def test_the_whole_score_has_not_gone_backwards(self, scored) -> None:
        assert scored["all_four"] >= FLOOR_ALL_FOUR

    def test_nothing_raises(self, scored) -> None:
        """A question may be refused, clarified or answered. It may not crash."""
        crashed = [r["id"] for r in scored["results"] if r["status"] == "raised"]
        assert not crashed, f"cases raised: {crashed}"

    def test_no_answer_names_a_concept_the_case_calls_padding(self, scored) -> None:
        """The negative expectation, which is the half that catches chart spam
        and the half a corpus written to the product would leave out."""
        dirty = [r["id"] for r in scored["results"] if not r["checks"]["CLEAN"]]
        assert not dirty, f"unasked-for concepts named in cases {dirty}"

    def test_the_complete_review_is_the_biggest_package(self, scored) -> None:
        by_id = {r["id"]: r for r in scored["results"]}
        biggest = max(r["analyses"] for r in scored["results"])
        assert by_id[50]["analyses"] == biggest
        assert by_id[50]["analyses"] >= 10

    def test_a_single_figure_question_stays_a_single_block(self, scored) -> None:
        """The rule cuts both ways, and this is the direction nobody tests."""
        by_id = {r["id"]: r for r in scored["results"]}
        for case_id in (1, 2, 5, 9, 10):
            assert by_id[case_id]["analyses"] <= 1, (
                f"case {case_id} grew supporting analyses nobody asked for")
