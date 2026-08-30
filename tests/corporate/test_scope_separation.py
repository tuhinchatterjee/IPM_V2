"""Two books in one catalogue. B44.

The corporate Borrower 360 universe is a DIFFERENT PORTFOLIO from the credit
book CreditProbe has always carried, and they share almost all of their
vocabulary: both have customers, exposure at default, an IFRS 9 stage, a
covenant. Registering the twenty corporate datasets without saying so broke
questions that had always worked, in three separate ways, and each of the
three is pinned here.

None of these failures announced itself as a failure. Retrieval returned a
different eight datasets, the planner said "which figure should CreditProbe
measure?", and the metadata assistant answered a question about swallows.
"""

from __future__ import annotations

import pytest

from backend.data_access.catalog import (
    BORROWER_360_SCOPE,
    CREDIT_BOOK_SCOPE,
    get_catalog,
)
from backend.orchestration import context as governed_context
from backend.services import assistant as assistant_mod


class TestScopeIsDeclared:
    def test_the_credit_book_is_the_default(self):
        """A dataset that says nothing keeps the behaviour it had."""
        catalogue = get_catalog()
        assert catalogue.dataset(
            "portfolio_facility").portfolio_scope == CREDIT_BOOK_SCOPE
        assert catalogue.dataset(
            "ifrs9_staging").portfolio_scope == CREDIT_BOOK_SCOPE

    def test_every_corporate_dataset_declares_the_other_book(self):
        catalogue = get_catalog()
        corporate = [d for d in catalogue.all()
                     if d.name.startswith("corporate_")]
        assert len(corporate) >= 20
        assert all(d.portfolio_scope == BORROWER_360_SCOPE
                   for d in corporate), [
            d.name for d in corporate
            if d.portfolio_scope != BORROWER_360_SCOPE]

    def test_the_scope_survives_the_data_builder_round_trip(self):
        """A database row overrides the bundled entry FIELD BY FIELD.

        Anything the Data Builder entry omits is not merely missing - it is
        erased. That is how `authoritative_for` was lost once before, and the
        scope would have gone the same way: the corporate datasets came back
        from the database indistinguishable from the credit book.
        """
        scopes = {d.name: d.portfolio_scope
                  for d in governed_context.all_datasets()}
        assert scopes.get("corporate_ifrs9") == BORROWER_360_SCOPE
        assert scopes.get("ifrs9_staging") == CREDIT_BOOK_SCOPE


class TestRetrievalPrefersTheRightBook:
    def test_an_unqualified_question_stays_on_the_credit_book(self):
        found = governed_context.retrieve(
            "Show me the ten largest customers by exposure at default.")
        scopes = {d.portfolio_scope for d in found.datasets}
        assert BORROWER_360_SCOPE not in scopes, [
            d.name for d in found.datasets]

    def test_a_relationship_question_reaches_the_borrower_360_book(self):
        found = governed_context.retrieve(
            "Which borrowers are in the same connected counterparty group?")
        names = [d.name for d in found.datasets]
        assert any(n.startswith("corporate_") for n in names), names

    def test_an_ifrs9_question_still_leads_with_the_credit_book(self):
        found = governed_context.retrieve("What IFRS 9 data do you have?")
        assert found.datasets[0].name == "ifrs9_staging"

    def test_a_technical_name_match_does_not_cross_books(self):
        """`corporate_customer_master` carries "customer" in its NAME.

        A dataset the question names is force-retrieved whatever it scores,
        which is right - but without a scope that rule pulled the corporate
        master into every question about customers and displaced the dataset
        that answers them.
        """
        found = governed_context.retrieve(
            "Which customers were downgraded last quarter?")
        assert "corporate_customer_master" not in {
            d.name for d in found.datasets}

    @pytest.mark.parametrize("question", [
        "Who is the ultimate beneficial owner of this borrower?",
        "Show the ownership structure of the group.",
        "Which suppliers does this borrower depend on?",
        "What is the network risk score?",
    ])
    def test_graph_questions_select_the_borrower_360_book(self, question):
        found = governed_context.retrieve(question)
        assert any(d.portfolio_scope == BORROWER_360_SCOPE
                   for d in found.datasets), [
            d.name for d in found.datasets]


class TestRetrievalCapIsNotTheVocabulary:
    def test_the_planner_sees_every_dataset_not_only_the_retrieved_eight(self):
        """A prompt budget must not decide what the product knows.

        `context.datasets` is capped at eight for relevance. The planner used
        that cap as its field universe, so twenty new datasets pushed
        `portfolio_facility` out of the top eight and the concept map's
        resolved candidate was judged unavailable - turning a question the
        product had always answered into a clarification.
        """
        from backend.data_access import get_catalog as catalogue_of

        known = {d.name for d in governed_context.all_datasets()}
        published = {d.name for d in catalogue_of().all()}
        assert known == published
        assert len(known) > governed_context.MAX_DATASETS

    def test_the_question_that_regressed_is_answered_again(self):
        from backend.orchestration import executor

        answer = executor.run_investigation(
            "Show me the ten largest customers by exposure at default.")
        assert answer.status == "succeeded", answer.narrative.direct_answer


class TestMetadataAssistantWordBoundaries:
    def test_a_short_field_name_does_not_match_inside_a_word(self):
        """`city` is inside "airspeed velo-CITY".

        A substring test answered a question about swallows with the
        definition of a city column, instead of the refusal it deserved. The
        field only became reachable when the corporate master added it - the
        defect was always there.
        """
        answer = assistant_mod.ask(
            "What is the airspeed velocity of an unladen swallow?")
        assert answer.unanswered_reason == "not_in_metadata"

    def test_a_field_that_is_actually_named_still_resolves(self):
        answer = assistant_mod.ask("What is ead?")
        assert answer.unanswered_reason == ""
        assert "ead" in answer.text.lower()

    def test_the_longest_matching_name_still_wins(self):
        answer = assistant_mod.ask("What does ecl coverage mean?")
        assert "ecl_coverage" in answer.text
