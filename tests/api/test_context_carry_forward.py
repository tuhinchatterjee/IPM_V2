"""The four acceptance threads, through the endpoints the browser calls.

Why this file exists
--------------------
The multi-turn context work can be — and is — tested against `referents` and
`nth` directly. Those tests prove the reading. They cannot prove the product,
because the browser does not call `referents`: it calls `POST /investigations`
and `POST /investigations/{id}/messages`, and everything in between has to
carry the state for a reference to resolve at all. The release blocker was
exactly that gap: readers that worked, wired to a path that did not use them.

So these drive the surface, turn by turn, and assert on the identities that
come back — not on HTTP 200.

Thread A     the five turns the release was called for
Thread B     twenty by PD → Stage 2 → narrow → three → the second one
Thread C     a clarification answered, then continued
Thread D     a scope deliberately widened back out

What it leaves behind
---------------------
Nothing. Every Investigation this file opens is captured and deleted, children
first, in the module teardown. A test that accumulates rows in a shared
database makes the next person's `residue()` report a mess it did not cause.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available

HEADERS = {"X-IPM-Role": "ANALYST"}

#: Everything that points at an Investigation, in the order it has to go.
CHILDREN = ("investigation_messages", "investigation_versions",
            "saved_analyses", "risk_cases", "agent_runs",
            "analysis_runs")

_OPENED: list[int] = []


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
        pytest.skip("Threads need a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


@pytest.fixture(scope="module", autouse=True)
def leave_nothing_behind(require_everything):
    yield
    if not _OPENED:
        return
    from sqlalchemy import text

    from backend.db.engine import get_session

    with get_session() as session:
        for table in CHILDREN:
            session.execute(
                text(f"DELETE FROM {table} WHERE investigation_id = ANY(:ids)"),
                {"ids": _OPENED})
        session.execute(
            text("DELETE FROM investigations WHERE id = ANY(:ids)"),
            {"ids": _OPENED})
        session.commit()
    _OPENED.clear()


# ------------------------------------------------------------------ driving


def thread(client, questions: list[str]) -> list[dict]:
    """Ask a whole thread the way the browser does, and return each turn."""
    started = client.post("/api/v1/investigations",
                          json={"question": questions[0], "ask": True},
                          headers=HEADERS)
    assert started.status_code in (200, 201), started.text
    body = started.json()
    _OPENED.append(int(body["thread"]["id"]))

    out = [body]
    for question in questions[1:]:
        response = client.post(
            f"/api/v1/investigations/{body['thread']['id']}/messages",
            json={"question": question}, headers=HEADERS)
        assert response.status_code == 200, response.text
        out.append(response.json())
    return out


def run_of(turn: dict) -> dict:
    return turn.get("run") or {}


def continuation_of(turn: dict) -> dict:
    conversation = run_of(turn).get("conversation") or {}
    return dict(conversation.get("continuation") or {})


def rows_of(turn: dict) -> list[dict]:
    rows: list[dict] = []
    for step in run_of(turn).get("steps") or []:
        found = (step.get("result") or {}).get("rows") or []
        if found:
            rows = found
    return rows


def ids_of(turn: dict) -> list[str]:
    return [str(r.get("customer_id")) for r in rows_of(turn)
            if isinstance(r, dict) and r.get("customer_id")]


def answer_of(turn: dict) -> str:
    return str((run_of(turn).get("narrative") or {}).get("direct_answer") or "")


def filters_of(turn: dict) -> dict:
    return dict(((run_of(turn).get("plan") or {}).get("scope")
                 or {}).get("filters") or {})


# ------------------------------------------------------------------ threads


@pytest.fixture(scope="module")
def thread_a(client) -> list[dict]:
    return thread(client, [
        "Which sectors concern you most?",
        "Why Shipping?",
        "Which borrowers are the real issues?",
        "Which of those have rising 12-month PD?",
        "Why does the second one worry you?",
    ])


class TestThreadA:
    """The release blocker, turn by turn."""

    def test_every_turn_answers(self, thread_a):
        for index, turn in enumerate(thread_a, start=1):
            assert run_of(turn)["status"] == "succeeded", (
                f"turn {index} did not answer: "
                f"{run_of(turn).get('clarification')}")

    def test_turn_two_narrows_to_shipping_rather_than_asking_for_a_measure(
            self, thread_a):
        turn = thread_a[1]
        assert continuation_of(turn)["action"] == "NARROW_SCOPE"
        assert filters_of(turn).get("sector") == "Shipping"
        assert "Shipping" in answer_of(turn), (
            "the answer does not say which book it is about")

    def test_turn_three_stays_inside_shipping(self, thread_a):
        assert filters_of(thread_a[2]).get("sector") == "Shipping"

    def test_turn_four_resolves_those_to_turn_threes_rows(self, thread_a):
        """The release-blocking invariant: turn 3 named a set."""
        carried = continuation_of(thread_a[3])
        assert carried["action"] == "CONTINUE"
        assert carried["referent"], "no referent was recorded for 'of those'"
        assert set(ids_of(thread_a[3])) <= set(ids_of(thread_a[2])), (
            "turn 4 returned borrowers turn 3 never named")
        assert ids_of(thread_a[3]), "turn 4 lost the population entirely"

    def test_turn_five_binds_to_exactly_the_second_row_of_turn_four(
            self, thread_a):
        ordinal = continuation_of(thread_a[4]).get("ordinal") or {}
        assert ordinal.get("resolved") is True, ordinal
        assert ordinal["entity_id"] == ids_of(thread_a[3])[1], (
            "'the second one' did not bind to the second row of turn 4")
        assert ids_of(thread_a[4]) == [ordinal["entity_id"]], (
            "turn 5 answered about more than the one row it was asked about")
        assert ordinal["label"] in answer_of(thread_a[4]), (
            "the answer does not name the borrower it is about")


class TestThreadB:
    def test_a_ranking_narrowed_three_times_still_resolves_an_ordinal(
            self, client):
        turns = thread(client, [
            "Show me the 20 borrowers with the highest 12-month PD.",
            "Which of those are in Stage 2?",
            "Which three have the largest exposure at default?",
            "Why the second one?",
        ])
        for index, turn in enumerate(turns, start=1):
            assert run_of(turn)["status"] == "succeeded", (
                f"turn {index}: {run_of(turn).get('clarification')}")

        assert len(ids_of(turns[0])) == 20
        assert set(ids_of(turns[1])) <= set(ids_of(turns[0]))
        assert len(ids_of(turns[2])) == 3
        assert set(ids_of(turns[2])) <= set(ids_of(turns[1]))

        ordinal = continuation_of(turns[3]).get("ordinal") or {}
        assert ordinal.get("resolved") is True, ordinal
        assert ordinal["entity_id"] == ids_of(turns[2])[1]
        assert ids_of(turns[3]) == [ordinal["entity_id"]]


class TestThreadC:
    def test_a_clarification_is_answered_and_the_thread_continues(self, client):
        turns = thread(client, [
            "How has it changed?",
            "Expected credit loss.",
            "Which borrowers drove that?",
            "And the first one?",
        ])

        assert run_of(turns[0])["status"] == "needs_clarification", (
            "the opening question named no measure and should have been asked "
            "about")

        # The reply is merged with the question that provoked it, so the
        # answer is the MOVEMENT that was asked for and not a level.
        resumed = answer_of(turns[1]).lower()
        assert run_of(turns[1])["status"] == "succeeded"
        assert "expected credit loss" in resumed
        assert any(word in resumed for word in ("fell", "rose", "change")), (
            f"the pending question was lost: {resumed!r}")

        # And the measure it settled carries into a question that names none.
        assert run_of(turns[2])["status"] == "succeeded", (
            run_of(turns[2]).get("clarification"))
        assert "expected credit loss" in answer_of(turns[2]).lower()
        assert ids_of(turns[2]), "the third turn named no borrowers"

        ordinal = continuation_of(turns[3]).get("ordinal") or {}
        assert ordinal.get("resolved") is True, ordinal
        assert ordinal["entity_id"] == ids_of(turns[2])[0]


class TestThreadD:
    def test_a_scope_widened_back_out_carries_nothing(self, client):
        turns = thread(client, [
            "Show the ten largest Real Estate borrowers by exposure at "
            "default.",
            "Which of those are in Stage 2?",
            "Now across the whole portfolio, what is total exposure at "
            "default?",
        ])

        assert filters_of(turns[0]).get("sector") == "Real Estate"
        assert continuation_of(turns[2])["action"] == "RESET_SCOPE"
        assert not continuation_of(turns[2]).get("entity_ids")
        assert not filters_of(turns[2]), (
            "the portfolio total was still restricted to Real Estate")
        assert run_of(turns[2])["status"] == "succeeded"


class TestTheAskRouteCarriesTheSameContext:
    """`/ask` with an investigation_id continues THAT investigation. §13.

    The field always existed and only decided where the answer was FILED. A
    caller that named the thread still had its question planned as though
    nothing had been asked before it, so the two entry points into the same
    investigation behaved differently — which is two mechanisms, and the one
    the tests drove was not the one the product used.
    """

    def test_a_follow_up_through_ask_resolves_the_previous_population(
            self, client):
        started = client.post(
            "/api/v1/investigations",
            json={"question": "Show the ten largest Shipping borrowers by "
                              "exposure at default.", "ask": True},
            headers=HEADERS)
        assert started.status_code in (200, 201), started.text
        opened = started.json()
        _OPENED.append(int(opened["thread"]["id"]))
        first = [str(r["customer_id"]) for r in rows_of(opened)
                 if r.get("customer_id")]
        assert len(first) == 10

        response = client.post(
            "/api/v1/ask",
            json={"question": "Which of those are in Stage 2?",
                  "investigation_id": opened["thread"]["id"]},
            headers=HEADERS)
        assert response.status_code == 200, response.text
        body = response.json()

        carried = dict((body.get("conversation") or {}).get("continuation")
                       or {})
        assert carried.get("action") == "CONTINUE", carried
        assert carried.get("entity_count") == 10, (
            "/ask did not carry the investigation's population")

        rows = rows_of({"run": body})
        got = {str(r["customer_id"]) for r in rows if r.get("customer_id")}
        assert got <= set(first), "/ask answered outside the carried population"


class TestWhatIsNotInherited:
    def test_a_catalogue_question_mid_thread_is_not_narrowed(self, client):
        """A dataset's schema does not vary by sector."""
        turns = thread(client, [
            "Show total exposure at default for Real Estate.",
            "What fields are available in the ratings data?",
        ])
        assert run_of(turns[1])["status"] == "succeeded"
        assert len(rows_of(turns[1])) > 10, (
            "the field list was narrowed by the sector the reader was in")

    def test_an_ordinal_with_nothing_behind_it_is_asked_about(self, client):
        turns = thread(client, [
            "How many borrowers are in the book?",
            "Why does the second one worry you?",
        ])
        answer = run_of(turns[1])
        assert answer["status"] == "needs_clarification", (
            "an unresolvable ordinal was answered rather than asked about")
        assert "which row" in str(
            (answer.get("clarification") or {}).get("question") or "").lower()
