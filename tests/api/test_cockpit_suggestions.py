"""The Cockpit offers exactly three questions, and every one of them answers.

A suggestion is a PROMISE. The reader did not choose it — the product offered
it — so an offered question that comes back as "which figure should CreditProbe
measure?" is worse than no suggestion at all: the user did exactly what they
were told and the product asked them what they meant.

Three of the five were doing precisely that before this suite existed. Two
returned a clarification or an unsupported notice, and one was withheld with a
plan-validator message on the screen where the answer belonged.
"""

from __future__ import annotations

import datetime as dt

import pytest

from backend.orchestration import conversation as cv
from backend.orchestration import memory as wm
from backend.orchestration import suggestions as sg
from backend.orchestration.context import retrieve
from backend.orchestration.executor import answer_investigation

APPROVED = [question for question, _ in sg.COCKPIT]


@pytest.fixture(scope="module")
def governed():
    return retrieve("")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


class TestExactlyThree:

    def test_the_approved_set_has_five(self):
        assert len(sg.COCKPIT) == 5

    def test_the_cockpit_shows_three(self, governed):
        assert len(sg.opening(governed)) == sg.COCKPIT_AT_ONCE == 3

    def test_every_offered_question_is_approved(self, governed):
        for day in range(40):
            on = dt.date(2026, 1, 1) + dt.timedelta(days=day)
            for question in sg.opening(governed, on=on):
                assert question in APPROVED

    def test_no_question_is_offered_twice_at_once(self, governed):
        for day in range(40):
            on = dt.date(2026, 1, 1) + dt.timedelta(days=day)
            offered = sg.opening(governed, on=on)
            assert len(set(offered)) == len(offered)


class TestTheRotation:
    """Rotated by the day: stable while it is read, different tomorrow."""

    def test_the_same_day_gives_the_same_three(self, governed):
        on = dt.date(2026, 5, 14)
        assert sg.opening(governed, on=on) == sg.opening(governed, on=on)

    def test_the_next_day_gives_a_different_three(self, governed):
        first = sg.opening(governed, on=dt.date(2026, 5, 14))
        second = sg.opening(governed, on=dt.date(2026, 5, 15))
        assert first != second

    def test_every_approved_question_comes_round(self, governed):
        seen: set[str] = set()
        for day in range(len(sg.COCKPIT) + 2):
            on = dt.date(2026, 5, 14) + dt.timedelta(days=day)
            seen.update(sg.opening(governed, on=on))
        assert seen == set(APPROVED)


class TestItNeverAdvertisesWhatIsNotInstalled:

    class _Dataset:
        def __init__(self, name):
            self.name = name
            self.business_name = name

    def test_a_question_needing_a_missing_dataset_is_not_offered(self):
        class Context:
            datasets = [TestItNeverAdvertisesWhatIsNotInstalled._Dataset(
                "portfolio_facility")]

        offered = sg.opening(Context())
        # Everything but the one that needs IFRS 9 staging as well.
        assert "What is driving Stage 2 and ECL growth?" not in offered
        assert offered
        for question in offered:
            assert question in APPROVED

    def test_an_empty_catalogue_offers_nothing(self):
        class Context:
            datasets = []

        assert sg.opening(Context()) == []


class TestTheEndpointServesTheApprovedThree:

    def test_it_returns_three(self, client):
        got = client.get("/api/v1/ask/suggestions").json()
        assert len(got["questions"]) == 3

    def test_every_one_is_approved(self, client):
        got = client.get("/api/v1/ask/suggestions").json()
        for entry in got["questions"]:
            assert entry["question"] in APPROVED


@pytest.mark.parametrize("question", APPROVED)
class TestEveryApprovedQuestionAnswers:
    """The gate. Each one, through the real orchestration path, on real data.

    Not a smoke test: an answer that is a clarification, an abstention or a
    withheld runtime failure is exactly the thing this suite exists to catch,
    and each is asserted separately so a failure names which one happened.
    """

    @staticmethod
    def _ask(question):
        return answer_investigation(question, persist=False,
                                    state=cv.load({}), memory=wm.load({}))

    def test_it_does_not_ask_the_reader_what_they_meant(self, question):
        _, answered = self._ask(question)
        assert not answered.clarification, (
            f"{question!r} was offered by the Cockpit and came back asking "
            f"the reader to rephrase: {answered.clarification}")

    def test_it_is_not_refused_as_unsupported(self, question):
        _, answered = self._ask(question)
        assert not answered.unsupported, (
            f"{question!r} was offered by the Cockpit and came back saying "
            f"the governed universe holds nothing about it.")

    def test_it_is_not_withheld(self, question):
        _, answered = self._ask(question)
        assert not answered.failure, (
            f"{question!r} was offered by the Cockpit and was withheld: "
            f"{answered.failure}")

    def test_it_returns_rows(self, question):
        investigation, _ = self._ask(question)
        step = investigation.steps[0] if investigation.steps else None
        result = (step.result if isinstance(step.result, dict) else {}) if step else {}
        assert result.get("rows"), f"{question!r} produced no rows."

    def test_it_leads_with_an_answer(self, question):
        investigation, _ = self._ask(question)
        direct = str(investigation.narrative.direct_answer or "")
        assert direct.strip(), f"{question!r} produced no direct answer."
        assert "CreditProbe withheld" not in direct
        assert "no governed data" not in direct

    def test_it_says_nothing_a_reader_should_not_see(self, question):
        investigation, _ = self._ask(question)
        shown = " ".join([
            str(investigation.narrative.direct_answer or ""),
            *[str(c) for c in (investigation.narrative.caveats or [])],
        ])
        for leak in ("Traceback", "SELECT ", "PlanRejected", "is not a column",
                     "op=", "anthropic", "claude"):
            assert leak.lower() not in shown.lower(), (
                f"{question!r} showed {leak!r} to the reader.")
