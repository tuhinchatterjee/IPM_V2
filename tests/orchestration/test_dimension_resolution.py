"""The noun the question asks for decides what one row IS. §D1, §D2.

The defects
-----------
    "Which sectors concern you most?"   → twenty-five borrowers
    "Show rating distribution."         → one number, 10.00

Both sentences name the thing they want one row of. Neither was read that way.
The planner resolved a breakdown only from an explicit "by X", so a question
whose dimension is its SUBJECT arrived with no dimension at all and fell
through to whatever grain the source dataset happened to be keyed on. And
"rating" was resolved as the MEASURE as well as the grouping, so the plan asked
for the average rating of each rating and returned a scalar.

What holds now
--------------
`dimensions.read` answers one question — what does the answer have one row of —
from the governed vocabulary, in three rules: an explicit breakdown, a
dimension modifying a shape word, and the head noun of the request. A concept
resolved as the dimension is never also counted as the measure. A head
dimension outranks an entity noun later in the sentence. And where the head
noun and an explicit breakdown want different tables, the product asks.
"""

from __future__ import annotations

import pytest

from backend.orchestration import dimensions as dm
from backend.orchestration import grain as gr

#: The installation's governed dimensions, as `context.dimensions` carries them.
GOVERNED = {"sector": [], "region": [], "segment": [], "product_type": [],
            "rating_bucket": [], "country": [], "ifrs9_stage": []}


class TestTheThreeRules:
    @pytest.mark.parametrize("question,dimension,rule", [
        # 1. an explicit breakdown
        ("Show ECL by sector.", "sector", "breakdown"),
        ("Show total exposure at default per region.", "region", "breakdown"),
        ("Show ECL for each segment.", "segment", "breakdown"),
        ("Show ECL grouped by product type.", "product_type", "breakdown"),
        ("How is the corporate portfolio distributed by sector?", "sector",
         "breakdown"),
        # 2. the dimension modifying a shape word
        ("Show rating distribution.", "internal_grade", "named"),
        ("Show sector distribution.", "sector", "named"),
        ("Show Stage distribution.", "ifrs9_stage", "named"),
        ("Show the region breakdown.", "region", "named"),
        ("Show the segment mix.", "segment", "named"),
        # 3. the head noun of the request
        ("Which sectors concern you most?", "sector", "requested"),
        ("Which ratings concern you most?", "internal_grade", "requested"),
        ("Which regions have the highest ECL?", "region", "requested"),
        ("Which rating grades saw the largest increase in exposure?",
         "internal_grade", "requested"),
        ("Which sectors deteriorated most this quarter?", "sector",
         "requested"),
        ("Show me the five largest sectors by exposure at default.", "sector",
         "requested"),
    ])
    def test_the_dimension_and_the_rule_that_found_it(self, question: str,
                                                     dimension: str,
                                                     rule: str):
        found = dm.read(question, GOVERNED)
        assert (found.dimension, found.rule) == (dimension, rule)

    @pytest.mark.parametrize("question", [
        "Which borrowers concern you most?",
        "Which borrowers in Shipping concern you most?",
        "Show me the ten largest customers by exposure at default.",
        "Which customers were downgraded and had expected credit loss rise?",
        "What fields are available in the ratings data?",
        "How has expected credit loss changed?",
        "Who has both rising utilisation and weak debt service?",
    ])
    def test_a_question_about_entities_names_no_dimension(self, question: str):
        assert not dm.read(question, GOVERNED).found


class TestTheHeadNounOutranksAnEntityNounLaterOn:
    def test_which_sectors_have_borrowers_is_a_question_about_sectors(self):
        """The borrowers are the condition; the sectors are the answer."""
        found = dm.read("Which sectors have borrowers with rising PD?",
                        GOVERNED)
        assert (found.dimension, found.rule) == ("sector", "requested")
        assert not found.entity, "the later noun was read as the head"

    def test_the_grain_follows_the_head_dimension(self):
        want = gr.requested("Which sectors have borrowers with rising PD?",
                            dimension="sector", dimension_is_head=True)
        assert want.grain == gr.SEGMENT
        assert want.dimension == "sector"

    def test_a_breakdown_does_not_outrank_an_entity_noun(self):
        """"The ten largest customers by sector" is about customers."""
        want = gr.requested("Show the ten largest customers by sector.",
                            dimension="sector", dimension_is_head=False)
        assert want.grain == gr.CUSTOMER


class TestWhereTheTwoDisagreeItAsks:
    def test_a_head_entity_and_a_breakdown_conflict(self):
        found = dm.read(
            "Show the five largest borrowers by exposure, grouped by sector",
            GOVERNED)
        assert found.conflicts
        assert found.entity == "customer"
        assert found.dimension == "sector"

    def test_the_clarification_offers_both_tables(self):
        found = dm.read(
            "Show the five largest borrowers by exposure, grouped by sector",
            GOVERNED)
        asked = dm.clarification(found)
        assert "one row per borrower" in asked
        assert "one row per sector" in asked

    def test_a_head_dimension_alone_is_not_a_conflict(self):
        assert not dm.read("Which sectors concern you most?",
                           GOVERNED).conflicts


class TestGovernedMetadataRatherThanASynonymTable:
    @pytest.mark.parametrize("phrase,dimension", [
        ("industry", "sector"),
        ("industries", "sector"),
        ("geography", "region"),
        ("stage", "ifrs9_stage"),
        ("ifrs 9 stage", "ifrs9_stage"),
        ("product", "product_type"),
        ("countries", "country"),
        ("rating bands", "rating_bucket"),
    ])
    def test_an_alias_resolves_to_the_governed_name(self, phrase: str,
                                                    dimension: str):
        assert dm.read(f"Show ECL by {phrase}.", GOVERNED).dimension == (
            dimension)

    def test_the_installations_own_field_names_resolve_without_an_alias(self):
        for name in GOVERNED:
            readable = name.replace("_", " ")
            assert dm.read(f"Show ECL by {readable}.",
                           GOVERNED).dimension == name

    def test_a_dimension_the_installation_does_not_govern_is_not_one(self):
        assert not dm.read("Show ECL by sector.", {"region": []}).found

    def test_a_measure_is_never_read_as_a_dimension(self):
        """A continuous amount grouped by itself is the raw table."""
        for question in ("Show ECL by expected credit loss.",
                         "Show exposure by exposure at default."):
            assert not dm.read(question, GOVERNED).found


class TestPhrasesThatMustNotBeReadAsADimension:
    @pytest.mark.parametrize("question", [
        "Show ECL by quarter.",
        "Show the movement between Q1 2026 and Q2 2026.",
        "Which borrowers were downgraded in the last year?",
        "Show me the first five borrowers by exposure at default.",
    ])
    def test_a_period_or_a_count_is_not_a_breakdown(self, question: str):
        found = dm.read(question, GOVERNED)
        assert found.dimension in ("", "sector") or not found.found, (
            f"{question!r} resolved a dimension it does not name")
