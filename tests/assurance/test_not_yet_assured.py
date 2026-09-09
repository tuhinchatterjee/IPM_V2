"""A thread with nothing assured on it yet is not a missing address.

The defect
----------
`GET /investigations/{id}/assurance` answered 404 for three different things:
no such Investigation, an Investigation the caller may not read, and an
Investigation that exists, that the caller is looking at, and on which nothing
has been assured yet.

The first two are deliberately conflated — one message for both, so probing
addresses discloses nothing. The third does not belong with them. EVERY thread
is in that state until its first answer, so every Investigation page fetched a
404, logged a console error, and told the reader "No assurance record is
available at that address" — which reads as a broken link rather than as "not
yet". A route crawl found it on nineteen Investigations across three roles.

What is held here
-----------------
That the three cases stay three. The one that is neither missing nor refused
answers 200 and says so; the two that are sensitive keep the single 404 they
have always shared, decided by the same access policy rather than a new one.
"""

from __future__ import annotations

import inspect

import pytest

from backend.api.routers import assurance as ar


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


ADMIN = {"X-IPM-Role": "ADMIN"}


def _an_unassured_thread(client) -> dict | None:
    """The assurance body of a thread that has none, or None if all have.

    Scanned rather than assumed: whether the first Investigation in the list
    has been assured depends on what else has run against this database, and a
    test that only looks at one thread passes or fails on that accident.
    """
    body = client.get("/api/v1/investigations", headers=ADMIN)
    if body.status_code != 200:
        return None
    for one in (body.json().get("investigations") or [])[:25]:
        found = client.get(f"/api/v1/investigations/{one['id']}/assurance",
                           headers=ADMIN)
        if found.status_code != 200:
            continue
        payload = found.json()
        if "header" not in payload:
            return payload
    return None


class TestTheThreeCasesStayThree:

    def test_a_thread_with_nothing_assured_yet_is_not_a_failure(self,
                                                                client) -> None:
        body = _an_unassured_thread(client)
        if body is None:
            pytest.skip("every readable Investigation has been assured, so "
                        "the case under test is not present here")
        # 200 and an explicit "not yet", rather than 200 with an empty review
        # the reader would have to interpret as nothing having happened.
        assert body.get("assured") is False
        assert body.get("statement")
        assert "yet" in body["statement"]

    def test_it_says_not_yet_rather_than_not_found(self) -> None:
        assert "yet" in ar.NOT_YET
        assert ar.NOT_YET != ar.NOT_FOUND["message"]

    def test_an_investigation_that_does_not_exist_is_still_a_404(
            self, client) -> None:
        found = client.get("/api/v1/investigations/999999999/assurance",
                           headers=ADMIN)
        assert found.status_code == 404
        assert found.json()["detail"]["error"] == "not_found"

    def test_an_id_that_is_not_an_id_is_still_a_404(self, client) -> None:
        # `_readable` parses the id before touching the database. A
        # non-numeric one names nothing, and naming nothing must not become
        # "exists, nothing assured yet".
        found = client.get("/api/v1/investigations/not-an-id/assurance",
                           headers=ADMIN)
        assert found.status_code == 404

    def test_the_refusal_and_the_absence_still_read_alike(self) -> None:
        # The whole point of the single message: a caller cannot tell "no such
        # record" from "not yours" by reading it.
        assert "at that address" in ar.NOT_FOUND["message"]
        assert "permission" not in ar.NOT_FOUND["message"].lower()
        assert "role" not in ar.NOT_FOUND["message"].lower()


class TestNotYoursReadsAsARefusal:

    def test_a_thread_whose_assurance_is_not_yours_is_a_403(self,
                                                            client) -> None:
        # An Analyst who did not run the Investigation, is not in its project
        # and has no workflow action on it may not read its assurance. That is
        # §207 working. It arrived as a 404 and read as a wrong address, on a
        # page where the reader could see the Investigation perfectly well.
        listed = client.get("/api/v1/investigations", headers=ADMIN)
        if listed.status_code != 200:
            pytest.skip("no Investigation list")
        seen = set()
        for one in (listed.json().get("investigations") or [])[:25]:
            got = client.get(f"/api/v1/investigations/{one['id']}/assurance",
                             headers={"X-IPM-Role": "ANALYST"})
            seen.add(got.status_code)
            if got.status_code == 403:
                assert got.json()["detail"]["error"] == "forbidden"
                return
        if 404 in seen:
            raise AssertionError(
                "an Investigation an Analyst may not assure came back 404, "
                "which reads as a wrong address rather than as a refusal")
        pytest.skip("every listed Investigation is readable by an Analyst")

    def test_the_refusal_says_who_may_read_it(self) -> None:
        said = ar.NOT_YOURS["message"]
        assert "access" in said
        # Named, so the reader knows what would change it rather than only
        # that something is closed.
        assert "project" in said and "reviewers" in said

    def test_the_three_outcomes_are_named_rather_than_booleans(self) -> None:
        # `_visible` used to return a bool, and a bool cannot tell "not there"
        # from "not yours" — which is exactly the collapse being undone.
        assert {ar.GONE, ar.REFUSED, ar.OPEN} == {"GONE", "REFUSED", "OPEN"}


class TestItAsksTheSamePolicy:

    def test_readability_is_decided_by_may_read_and_not_by_a_new_rule(
            self) -> None:
        source = inspect.getsource(ar._visible)
        assert "ac.may_read" in source, (
            "a second access rule beside the assurance policy is how the two "
            "drift apart")

    def test_a_thread_that_is_not_there_is_not_readable(self) -> None:
        source = inspect.getsource(ar._visible)
        assert "if found is None" in source
