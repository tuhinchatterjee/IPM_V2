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


class TestThreeBooksAfterTheGraph:
    """The corporate graph must not steal a retail or credit-book question.

    Twenty-two BORROWER_360 datasets now sit in the same catalogue as
    twenty-four CREDIT_BOOK ones, and they share almost every word: both have
    customers, exposure, a stage and a covenant. The failure this pins is not
    hypothetical - it happened once already, when twenty new corporate
    datasets pushed the facility book out of the retrieval window and turned
    a working question into a clarification.

    The assertion is on the LEAD dataset rather than on the whole window. A
    lower-ranked candidate from the other book is harmless; the lead is what
    the planner builds on.
    """

    RETAIL = (
        "What is the application scorecard AUC this month?",
        "Show me the behavioural scorecard PSI by segment.",
        "Which retail variables have the highest information value?",
        "What is the observed default rate by score band?",
    )
    CREDIT_BOOK = (
        "What is the IFRS 9 stage distribution?",
        "Who are our largest exposures?",
        "Show me the arrears position.",
        "What is the ECL coverage by stage?",
        "Which borrowers are approaching the SICR threshold?",
    )
    CORPORATE = (
        "Which connected groups carry the most exposure?",
        "Who are the ultimate beneficial owners?",
        "Show me the supply chain relationships.",
        "Which borrowers are most central in the network?",
    )

    def _lead(self, question: str) -> str:
        from backend.orchestration import context as ctx_mod

        found = ctx_mod.retrieve(question)
        assert found.datasets, f"nothing retrieved for {question!r}"
        return found.datasets[0].name

    def test_a_retail_question_leads_with_a_retail_dataset(self):
        for question in self.RETAIL:
            lead = self._lead(question)
            assert lead.startswith("retail_"), f"{question!r} -> {lead}"

    def test_a_credit_book_question_leads_with_the_credit_book(self):
        from backend.data_access.catalog import CREDIT_BOOK_SCOPE, get_catalog

        catalog = get_catalog()
        for question in self.CREDIT_BOOK:
            lead = self._lead(question)
            assert not lead.startswith("corporate_"), (
                f"{question!r} led with {lead}, a Borrower 360 dataset")
            assert catalog.dataset(lead).portfolio_scope == CREDIT_BOOK_SCOPE

    def test_a_corporate_question_leads_with_the_corporate_book(self):
        from backend.data_access.catalog import BORROWER_360_SCOPE, get_catalog

        catalog = get_catalog()
        for question in self.CORPORATE:
            lead = self._lead(question)
            assert catalog.dataset(lead).portfolio_scope == BORROWER_360_SCOPE, (
                f"{question!r} led with {lead}")

    def test_the_catalogue_holds_both_books(self):
        from backend.data_access.catalog import (
            BORROWER_360_SCOPE,
            CREDIT_BOOK_SCOPE,
            get_catalog,
        )

        scopes: dict[str, int] = {}
        for dataset in get_catalog().all():
            scopes[dataset.portfolio_scope] = (
                scopes.get(dataset.portfolio_scope, 0) + 1)
        assert scopes.get(CREDIT_BOOK_SCOPE, 0) >= 20
        assert scopes.get(BORROWER_360_SCOPE, 0) >= 20
        assert set(scopes) == {CREDIT_BOOK_SCOPE, BORROWER_360_SCOPE}
