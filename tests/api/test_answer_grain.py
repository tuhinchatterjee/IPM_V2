"""What one row IS, for the twelve live questions. §D1, §D2.

Driven through `POST /api/v1/ask` — the route the product answers on — and
asserting the things a reader can check: which dimension was asked for, which
dimension the answer is actually grouped by, the measure, the period, the row
grain, the row count and the ordering.

`persist` is false throughout. A grain test that leaves an Investigation behind
per question makes the next person's workspace report a mess it did not cause.
"""

from __future__ import annotations

import pytest

from backend.orchestration import dimensions as dm
from tests.conftest import database_available

HEADERS = {"X-IPM-Role": "ANALYST"}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_everything():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if not database_available():
        pytest.skip("Ask needs a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


def ask(client, question: str) -> dict:
    response = client.post("/api/v1/ask",
                           json={"question": question, "persist": False},
                           headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def scope_of(body: dict) -> dict:
    return dict((body.get("plan") or {}).get("scope") or {})


def rows_of(body: dict) -> list[dict]:
    rows: list[dict] = []
    for step in body.get("steps") or []:
        found = (step.get("result") or {}).get("rows") or []
        if found:
            rows = found
    return rows


def answer_of(body: dict) -> str:
    return str((body.get("narrative") or {}).get("direct_answer") or "")


#: question → the dimension the answer must have one row of.
AT_DIMENSION_GRAIN = [
    ("Which sectors concern you most?", "sector", 17),
    ("Which ratings concern you most?", "internal_grade", 10),
    ("Show rating distribution.", "internal_grade", 10),
    ("Show sector distribution.", "sector", 17),
    ("Show ECL by sector.", "sector", 17),
    ("Show exposure at default by rating.", "internal_grade", 10),
    ("Which sectors have the highest Stage 2 exposure at default?", "sector",
     17),
    ("Which rating grades saw the largest increase in exposure at default?",
     "internal_grade", 10),
    ("Which sectors deteriorated most this quarter?", "sector", 17),
    ("Which sectors have borrowers with rising 12-month PD?", "sector", 17),
]


class TestTheAnswerIsAtTheGrainTheQuestionAskedFor:
    @pytest.mark.parametrize("question,dimension,rows", AT_DIMENSION_GRAIN)
    def test_one_row_per_category_and_every_category(self, client,
                                                     question: str,
                                                     dimension: str,
                                                     rows: int):
        # What was REQUESTED, read from the sentence alone.
        assert dm.read(question).dimension == dimension

        body = ask(client, question)
        assert body["status"] == "succeeded", body.get("clarification")

        # What the answer is actually grouped by.
        assert scope_of(body).get("dimension") == dimension, (
            f"{question!r} was not grouped by {dimension}")

        found = rows_of(body)
        assert len(found) == rows, (
            f"{question!r} returned {len(found)} rows, not one per "
            f"{dimension}")
        # Every row identifies its category, and no category appears twice.
        values = [r.get(dimension) for r in found]
        assert all(v is not None for v in values)
        assert len(set(map(str, values))) == len(values)

    @pytest.mark.parametrize("question,dimension,_rows", AT_DIMENSION_GRAIN)
    def test_the_period_is_stated(self, client, question: str, dimension: str,
                                  _rows: int):
        scope = scope_of(ask(client, question))
        assert scope.get("to_period"), f"{question!r} states no period"


class TestABorrowerQuestionStaysAtBorrowerGrain:
    @pytest.mark.parametrize("question", [
        "Which borrowers concern you most?",
        "Which borrowers in Shipping concern you most?",
        "Show me the ten largest customers by exposure at default.",
    ])
    def test_the_rows_are_borrowers(self, client, question: str):
        body = ask(client, question)
        assert body["status"] == "succeeded", body.get("clarification")
        assert not scope_of(body).get("dimension")
        found = rows_of(body)
        assert found and all("customer_id" in r for r in found), (
            f"{question!r} did not return borrowers")

    def test_a_sector_filter_does_not_become_a_sector_grain(self, client):
        """"Borrowers IN Shipping" is a filter, not a breakdown."""
        body = ask(client, "Which borrowers in Shipping concern you most?")
        assert scope_of(body).get("filters", {}).get("sector") == "Shipping"
        assert not scope_of(body).get("dimension")


class TestTheDistributionContract:
    @pytest.mark.parametrize("question,dimension", [
        ("Show rating distribution.", "internal_grade"),
        ("Show sector distribution.", "sector"),
    ])
    def test_a_distribution_reports_every_category_with_a_share(
            self, client, question: str, dimension: str):
        found = rows_of(ask(client, question))
        assert len(found) > 1, "a distribution came back as a scalar"
        first = found[0]
        assert dimension in first
        assert "ead" in first, "the distribution reports no amount"
        assert "borrowers" in first, "the distribution reports no borrower count"
        assert any(k.endswith("_share_pct") for k in first), (
            "the distribution reports no share of the population")

    def test_the_shares_account_for_the_whole_population(self, client):
        found = rows_of(ask(client, "Show sector distribution."))
        total = sum(float(r.get("ead_share_pct") or 0) for r in found)
        assert total == pytest.approx(100.0, abs=0.5)

    def test_the_stage_distribution_names_every_stage(self, client):
        body = ask(client, "Show Stage distribution.")
        assert scope_of(body).get("dimension") == "ifrs9_stage", (
            "the answer is at stage grain but does not declare it")
        found = rows_of(body)
        assert len(found) == 3
        assert {str(r.get("ifrs9_stage")) for r in found} == {"1", "2", "3"}

    def test_the_default_measure_is_stated_rather_than_silent(self, client):
        """A default the reader cannot see is a substitution."""
        body = ask(client, "Show sector distribution.")
        caveats = (body.get("narrative") or {}).get("caveats") or []
        said = " ".join([answer_of(body), *caveats])
        assert "exposure at default" in said.lower()


class TestMeasureIsNotDimension:
    def test_the_grouping_concept_is_not_also_the_figure(self, client):
        """"Rating distribution" measured BY rating returned one scalar."""
        body = ask(client, "Show rating distribution.")
        assert len(rows_of(body)) == 10
        assert "10.00" not in answer_of(body)

    def test_a_measure_named_alongside_the_dimension_survives(self, client):
        body = ask(client, "Show ECL by sector.")
        assert "expected credit loss" in answer_of(body).lower()
        assert scope_of(body).get("dimension") == "sector"


class TestWhereTheGrainsDisagreeItAsks:
    def test_borrowers_grouped_by_sector_is_asked_about(self, client):
        body = ask(client,
                   "Show the five largest borrowers by exposure, "
                   "grouped by sector")
        assert body["status"] == "needs_clarification"
        asked = str((body.get("clarification") or {}).get("question") or "")
        assert "one row per borrower" in asked
        assert "one row per sector" in asked


class TestTheMeasureClarificationKeepsTheDimension:
    """The exposure gate is deliberate. The grain behind it must still hold.

    "Show exposure by rating" asks about a word with three governed meanings
    that differ by material amounts, and the product asks which. That is not a
    grain defect and is not weakened here — but the DIMENSION the sentence
    named has to survive the round trip, or answering the clarification starts
    from nothing.
    """

    @pytest.mark.parametrize("question,dimension", [
        ("Show exposure by rating.", "internal_grade"),
        ("Which rating grades saw the largest increase in exposure?",
         "internal_grade"),
    ])
    def test_the_dimension_is_read_even_where_the_measure_is_asked_about(
            self, client, question: str, dimension: str):
        assert dm.read(question).dimension == dimension
        body = ask(client, question)
        assert body["status"] == "needs_clarification"
        asked = str((body.get("clarification") or {}).get("question") or "")
        assert "exposure" in asked.lower()

    @pytest.mark.parametrize("question,dimension,rows", [
        ("Show exposure at default by rating.", "internal_grade", 10),
        ("Which sectors have the highest Stage 2 exposure at default?",
         "sector", 17),
        # "Stage 2 exposure" settles the measure on its own: "stage 2" is a
        # governed qualifier of the impairment book's exposure at default, so
        # the reader HAS said which of the three they mean and asking again
        # would be the amnesia this class exists to prevent. It used to sit
        # above, asserting a clarification the product deliberately stopped
        # needing when that qualifier was declared — a red test since before
        # this work began. It belongs here, where the claim is the one the
        # class is really about: the dimension survives.
        ("Which sectors have the highest Stage 2 exposure?", "sector", 17),
    ])
    def test_naming_the_measure_answers_at_that_dimension(
            self, client, question: str, dimension: str, rows: int):
        body = ask(client, question)
        assert body["status"] == "succeeded"
        assert scope_of(body).get("dimension") == dimension
        assert len(rows_of(body)) == rows


class TestTheConcernMethodologyAtSectorGrain:
    def test_the_evidence_is_read_per_borrower_and_aggregated(self, client):
        """A sector has no arrears. The signals are still borrower-level."""
        found = rows_of(ask(client, "Which sectors concern you most?"))
        first = found[0]
        assert first["sector"] == "Shipping"
        assert first["borrowers"] > 0
        assert 0 < first["borrowers_with_concern_evidence"] <= first["borrowers"]
        assert any(k.startswith("signal_") for k in first), (
            "the ranking cannot be decomposed into the signals behind it")

    def test_it_is_ordered_by_the_share_of_exposure_carrying_evidence(
            self, client):
        found = rows_of(ask(client, "Which sectors concern you most?"))
        shares = [float(r["concern_exposure_pct"]) for r in found]
        assert shares == sorted(shares, reverse=True)

    def test_the_answer_names_the_sector_and_its_evidence(self, client):
        said = answer_of(ask(client, "Which sectors concern you most?"))
        assert "Shipping" in said
        assert "sectors" in said
        assert "borrower" in said


class TestABreakdownTheBaseDatasetDoesNotCarry:
    """A governed dimension one hop away is joined in, not dropped.

    "Show IFRS 9 EAD by internal rating" anchors on the impairment run, which
    has the quarter the question asked for and no rating column. The grade is
    one governed hop away on the facility book. Dropping the breakdown returned
    a single row of portfolio totals under a heading promising one row per
    grade — and once the grain postcondition existed, it stopped returning
    anything at all and asked instead.

    The planner already deferred such a dimension and joined it. It could only
    do so where a CONCEPT match named the column; a dimension resolved from the
    sentence alone had nothing to hop on.
    """

    QUESTION = "Show IFRS 9 EAD by internal rating for the latest period."

    def test_it_answers_rather_than_asking(self, client):
        body = ask(client, self.QUESTION)
        assert body["status"] == "succeeded", (
            (body.get("clarification") or {}).get("question"))

    def test_there_is_one_row_per_internal_grade(self, client):
        rows = rows_of(ask(client, self.QUESTION))
        assert len(rows) == 10
        column = next(c for c in rows[0] if c.endswith("internal_grade"))
        assert len({r[column] for r in rows}) == 10

    def test_the_grades_still_sum_to_the_whole_book(self, client):
        rows = rows_of(ask(client, self.QUESTION))
        assert sum(float(r["ead"]) for r in rows) == pytest.approx(
            125454.51, rel=1e-4)

