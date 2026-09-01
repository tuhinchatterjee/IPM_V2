"""Sixty-two questions about the data, none of which may reach the engine. §14.

The acceptance run asked three of these and got three wrong answers:

    "How many datasets are in the IFRS 9 data domain? List them."
        → "20,500 count of connected group size at Q2 2026."
    "What data do you have about borrower liquidity risk…"
        → "Climate Risk Assessment (climate_risk) is the governed source…"
    "Before answering anything, tell me which data domains and datasets you
     would need…"
        → "CreditProbe could not complete that request."

None of them was a hard question. Each was routed to the analytical planner,
which is not for questions about the catalogue and has no way to answer one.
So the corpus below is a routing test first and a content test second: every
question must be READ as a metadata question, and the answer must then say
something true and specific rather than something generic.

The negative half matters as much. A router that catches metadata questions by
catching everything has replaced one defect with a worse one, so the analytical
questions here must NOT be captured.
"""

from __future__ import annotations

import pytest

from backend import metadata as md
from backend.metadata import answers as ma
from backend.metadata import questions as mq
from backend.metadata.questions import Kind

# ---------------------------------------------------------------- the corpus
# (question, expected kind). Written the way a credit officer types, including
# the ones that end without a question mark.

CORPUS: tuple[tuple[str, str], ...] = (
    # -- what domains exist (8)
    ("Which data domains exist in CreditProbe?", Kind.DOMAIN_LIST),
    ("How many data domains do you have?", Kind.DOMAIN_LIST),
    ("List the data domains.", Kind.DOMAIN_LIST),
    ("What business domains are set up here?", Kind.DOMAIN_LIST),
    ("Show me the domains.", Kind.DOMAIN_LIST),
    ("Tell me what data domains are available", Kind.DOMAIN_LIST),
    ("Name the data domains in this deployment.", Kind.DOMAIN_LIST),
    ("How many business domains are there?", Kind.DOMAIN_LIST),

    # -- one named domain (8)
    ("How many datasets are in the IFRS 9 data domain? List them.",
     Kind.DOMAIN_DETAIL),
    ("What is in the Corporate Ratings domain?", Kind.DOMAIN_DETAIL),
    ("List the datasets in the Core Portfolio / Facility domain.",
     Kind.DOMAIN_DETAIL),
    ("Which datasets sit under IFRS 9 / ECL?", Kind.DOMAIN_DETAIL),
    ("Show me what is installed in the Retail / SME Scorecards domain.",
     Kind.DOMAIN_DETAIL),
    ("What datasets are in the Documents domain?", Kind.DOMAIN_DETAIL),
    ("How many datasets are under Corporate Ratings?", Kind.DOMAIN_DETAIL),
    ("Tell me about the Policies / Knowledge domain.", Kind.DOMAIN_DETAIL),

    # -- every dataset (6)
    ("What datasets do you have?", Kind.DATASET_LIST),
    ("How many governed datasets are there?", Kind.DATASET_LIST),
    ("List all the datasets.", Kind.DATASET_LIST),
    ("Which datasets are authoritative for exposure?", Kind.DATASET_LIST),
    ("What tables can you read?", Kind.DATASET_LIST),
    ("Show me every dataset in the catalogue.", Kind.DATASET_LIST),

    # -- one dataset (7)
    ("What is the grain of the covenant_tests dataset?", Kind.DATASET_DETAIL),
    ("What does one row of portfolio_facility represent?", Kind.DATASET_DETAIL),
    ("What are the primary keys of customer_ratings?", Kind.DATASET_DETAIL),
    ("Tell me about the ifrs9_staging dataset.", Kind.DATASET_DETAIL),
    ("What is the unit of analysis in facility_delinquency?",
     Kind.DATASET_DETAIL),
    ("Describe the collateral_register dataset.", Kind.DATASET_DETAIL),
    ("What is the grain of corporate_covenants?", Kind.DATASET_DETAIL),

    # -- fields (6)
    ("What fields does the ifrs9_staging dataset have?", Kind.FIELD_LIST),
    ("Which columns are in customer_ratings?", Kind.FIELD_LIST),
    ("List the fields of portfolio_facility.", Kind.FIELD_LIST),
    ("What attributes does covenant_tests carry?", Kind.FIELD_LIST),
    ("Show me the fields in collateral_register.", Kind.FIELD_LIST),
    ("What columns does facility_delinquency have?", Kind.FIELD_LIST),

    # -- what a term means (5)
    ("What does DSCR mean?", Kind.FIELD_MEANING),
    ("What is the definition of headroom_pct?", Kind.FIELD_MEANING),
    ("What is meant by ead?", Kind.FIELD_MEANING),
    ("What does lgd mean?", Kind.FIELD_MEANING),
    ("What does dpd_bucket mean?", Kind.FIELD_MEANING),

    # -- periods and history (7)
    ("What periods does the IFRS 9 data cover?", Kind.PERIODS),
    ("How many quarters of DPD history are there?", Kind.PERIODS),
    ("How much history does customer_ratings have?", Kind.PERIODS),
    ("What is the latest period in portfolio_facility?", Kind.PERIODS),
    ("How far back does the covenant data go?", Kind.PERIODS),
    ("Which periods are published for corporate_ratings?", Kind.PERIODS),
    ("How many periods does the catalogue cover?", Kind.PERIODS),

    # -- how much data (4)
    ("How many rows are in the customer_ratings dataset?", Kind.ROW_COUNT),
    ("How many records does portfolio_facility hold?", Kind.ROW_COUNT),
    ("How big is the covenant_tests dataset?", Kind.ROW_COUNT),
    ("How many rows are in the Corporate Ratings domain?", Kind.ROW_COUNT),

    # -- how things join (4)
    ("How is customer_ratings connected to corporate_ratings?",
     Kind.RELATIONSHIP),
    ("What is the join key between portfolio_facility and covenant_tests?",
     Kind.RELATIONSHIP),
    ("How would you join collateral_register to portfolio_facility?",
     Kind.RELATIONSHIP),
    ("What is the relationship between customer_ratings and ifrs9_staging?",
     Kind.RELATIONSHIP),

    # -- what data exists about a subject (5)
    ("What data do you have about borrower liquidity risk?", Kind.SUBJECT),
    ("What data do you have about covenant breaches?", Kind.SUBJECT),
    ("Is there any data about collateral valuations?", Kind.SUBJECT),
    ("What data do you have about external ratings?", Kind.SUBJECT),
    ("What information do you hold on delinquency?", Kind.SUBJECT),

    # -- what would be needed (5)
    ("Before answering anything, tell me which data domains and datasets you "
     "would need to assess a borrower's credit risk.", Kind.PLANNING),
    ("What data would you need to assess liquidity risk?", Kind.PLANNING),
    ("Which datasets are required to compute ECL?", Kind.PLANNING),
    ("What domains would you need to evaluate covenant compliance?",
     Kind.PLANNING),
    ("Which data would you need to review collateral coverage?",
     Kind.PLANNING),

    # -- the catalogue at a glance (2)
    ("What data do you have?", Kind.TOTALS),
    ("What data is installed?", Kind.TOTALS),
)

#: Questions that ask for a FIGURE. A router that catches these has replaced
#: one defect with a worse one.
ANALYTICAL: tuple[str, ...] = (
    "How many customers are in Stage 2?",
    "How many borrowers breached a covenant in Q2 2026?",
    "List the 20 borrowers with the highest 12-month PD in Q2 2026.",
    "Show total exposure by sector for Q2 2026.",
    "Which borrowers were downgraded in the latest quarter?",
    "What is the average ECL coverage by rating grade?",
    "How many facilities are more than 90 days past due?",
    "Rank sectors by Stage 2 exposure share.",
    "Compare ECL between Q1 2026 and Q2 2026.",
    "Which customers have the largest exposure?",
    "What is total EAD for the Contracting sector?",
    "How many accounts are in default?",
    "Show me the ten borrowers with the lowest covenant headroom.",
    "Which sectors deteriorated the most this quarter?",
    "What is the Stage 2 migration rate?",
)


@pytest.fixture(scope="module", autouse=True)
def _fresh_catalogue():
    md.invalidate()
    yield
    md.invalidate()


class TestTheCorpusIsBigEnough:
    def test_at_least_fifty_metadata_questions(self):
        """§14 asks for at least fifty. Counted, not assumed."""
        assert len(CORPUS) >= 50
        assert len({q for q, _ in CORPUS}) == len(CORPUS)

    def test_every_kind_is_exercised(self):
        covered = {kind for _, kind in CORPUS}
        assert covered == set(mq.ALL)


@pytest.mark.parametrize(("question", "kind"), CORPUS,
                         ids=[q[:56] for q, _ in CORPUS])
class TestEveryMetadataQuestionIsReadAsOne:
    def test_it_is_recognised(self, question: str, kind: str):
        request = mq.read(question)
        assert request is not None, (
            f"{question!r} was not recognised as a question about the data, "
            f"so it would reach the analytical planner")
        assert request.kind == kind

    def test_it_is_answered_from_the_catalogue(self, question: str, kind: str):
        del kind
        request = mq.read(question)
        answer = ma.respond(request)
        assert answer["answer"].strip()
        assert answer["execution"] == "metadata"

    def test_it_produces_a_table_and_never_a_chart(self, question: str,
                                                   kind: str):
        """§11 and §13. A list of datasets is not a distribution."""
        del kind
        answer = ma.respond(mq.read(question))
        assert answer["chart"] == {}
        assert answer["visualization"]["kind"] == "table"
        assert answer["columns"], "a metadata answer is prose AND a table"

    def test_the_answer_is_specific_rather_than_a_shrug(self, question: str,
                                                        kind: str):
        del kind
        said = ma.respond(mq.read(question))["answer"]
        assert "could not complete" not in said.lower()
        assert "unable to" not in said.lower()
        # Something countable, or a specific statement that there is nothing.
        # A metadata answer that is neither has not answered anything. "The
        # Documents domain exists but has no data installed in this
        # deployment" is a real answer and carries no digit.
        assert (any(ch.isdigit() for ch in said)
                or "no governed" in said.lower()
                or "no data installed" in said.lower())


@pytest.mark.parametrize("question", ANALYTICAL, ids=[q[:56] for q in ANALYTICAL])
def test_a_question_about_the_book_is_left_to_the_engine(question: str):
    """The counting nouns are the difference, not the counting verbs.

    "How many datasets are in IFRS 9" and "how many borrowers are in Stage 2"
    are the same English shape and completely different requests.
    """
    assert mq.read(question) is None, (
        f"{question!r} asks for a figure and was captured by the metadata "
        f"reader, which cannot compute one")


class TestTheThreeThatFailedAcceptance:
    def test_the_ifrs9_dataset_count(self):
        answer = ma.respond(mq.read(
            "How many datasets are in the IFRS 9 data domain? List them."))
        heading = md.domain("IFRS 9")
        assert heading is not None
        assert f"{heading.dataset_count:,} datasets" in answer["answer"]
        assert len(answer["rows"]) == heading.dataset_count
        assert {r["dataset"] for r in answer["rows"]} == set(heading.datasets)
        # And not the answer it used to give.
        assert "connected group size" not in answer["answer"]

    def test_the_liquidity_question_does_not_answer_with_climate(self):
        answer = ma.respond(mq.read(
            "What data do you have about borrower liquidity risk?"))
        named = [r["dataset"] for r in answer["rows"]]
        assert named, "it named nothing at all"
        assert named[0] != "climate_risk", (
            "the climate dataset led the answer again — it matched on the "
            "word 'risk', which in a credit-risk platform separates nothing")

    def test_the_planning_question_is_answered_rather_than_refused(self):
        answer = ma.respond(mq.read(
            "Before answering anything, tell me which data domains and "
            "datasets you would need to assess a borrower's credit risk."))
        assert "could not complete" not in answer["answer"].lower()
        assert answer["rows"]
        assert answer["detail"]["domains"]


class TestTheWholeRouteHoldsEndToEnd:
    """Through `orchestrator.answer`, which is what the API calls."""

    @pytest.mark.parametrize("question", [
        "How many datasets are in the IFRS 9 data domain? List them.",
        "What data do you have about borrower liquidity risk?",
        "Which data domains exist in CreditProbe?",
        "What is the grain of the covenant_tests dataset?",
    ])
    def test_it_answers_from_the_catalogue_with_no_engine_run(self,
                                                             question: str):
        from backend.orchestration import orchestrator as orc

        answered = orc.answer(question)
        assert answered.result is not None
        assert answered.result.answer.strip()
        assert answered.result.chart == {}
        assert answered.reading.source == "catalogue"
        # Nothing was computed. The Trace consistency contract reads this.
        assert answered.build is None
        assert answered.runtime is None

    def test_the_same_question_twice_gives_the_same_answer(self):
        from backend.orchestration import orchestrator as orc

        question = "How many data domains do you have?"
        first = orc.answer(question).result
        second = orc.answer(question).result
        assert first.answer == second.answer
        assert first.rows == second.rows
