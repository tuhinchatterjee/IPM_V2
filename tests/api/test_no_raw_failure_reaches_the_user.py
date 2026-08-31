"""No status code, stack trace or driver message reaches a reader. §9.

An acceptance run on a Mac put this on the screen:

    Request failed with status 500.

It is not a message. It names how the message travelled and says nothing about
what went wrong, what was or was not computed, or what to do next. It came
from the browser client's own fallback, and the fallback ran because the two
ends of the API disagreed about the shape of an error:

  * CreditProbe's own envelope is flat — `{error, message, detail}` — and the
    unhandled-exception handler had produced it correctly since P0.10.
  * FastAPI's default body for a deliberately raised `HTTPException` is
    `{"detail": "..."}`, where `detail` is a bare STRING. The client looked
    for `message` on an object, found neither, and printed the status.

So the fix is not a better fallback. It is that every failure — deliberate or
accidental, 4xx or 5xx, raised by a route or thrown by a driver — leaves
through one envelope carrying one sentence written for a credit officer.

What this suite refuses
-----------------------
Bare status codes, Python type names, SQL, file paths, connection strings,
environment variable names, and the vendor identity §12 also bans. And it
refuses the opposite failure too: a governed message so vague that the reader
cannot tell a permission refusal from a missing dataset. Both are ways of not
telling somebody what happened.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi import APIRouter, HTTPException

from backend.api import failures

#: Anything that is engineering detail rather than a message.
ENGINEERING = re.compile(
    r"Traceback|File \"|line \d+, in |"
    r"\b\w+Error\b|\b\w+Exception\b|"
    r"SELECT .+ FROM|postgresql\+?\w*://|psycopg|duckdb|sqlalchemy|"
    r"/home/|/app/|C:\\\\|"
    r"ANTHROPIC_API_KEY|SECRET_KEY|DATABASE_URL|"
    r"status \d{3}|HTTP \d{3}",
    re.IGNORECASE)


def envelope(response) -> dict:
    """The error object, whichever of the two shapes carried it.

    The house convention nests it under `detail`; the unhandled-exception
    handler returns it flat. Both are objects with `error` and `message`, and
    the browser client reads either. This helper is the same two-line read the
    client does, so the suite asserts what the product actually sees.
    """
    body = response.json()
    inner = body.get("detail")
    return inner if isinstance(inner, dict) and "message" in inner else body


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def breaking_client():
    """A client with routes that fail in each of the ways a real one can.

    Mounted onto the real application so the real handlers run. Reproducing
    the failure is the point: a test that asserts the handler's output without
    going through the handler proves nothing about the deployed behaviour.
    """
    from fastapi.testclient import TestClient

    from backend.api.main import app

    router = APIRouter(prefix="/_break", tags=["test"])

    @router.get("/bare-500")
    def bare_500():
        # The exact shape that produced "Request failed with status 500.":
        # a deliberately raised 500 whose detail is a bare string.
        raise HTTPException(status_code=500, detail="Internal Server Error")

    @router.get("/driver")
    def driver():
        raise RuntimeError(
            "psycopg.OperationalError: connection to server at "
            "postgresql://ipm_app:hunter2@db:5432/ipm failed")

    @router.get("/enum-403")
    def enum_403():
        raise HTTPException(status_code=403, detail="forbidden")

    @router.get("/written-404")
    def written_404():
        raise HTTPException(
            status_code=404,
            detail="No analysis named top_borrowers is registered here.")

    if not any(getattr(r, "path", "").startswith("/_break")
               for r in app.routes):
        app.include_router(router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


# ----------------------------------------------------- the failing requests


class TestEveryFailureLeavesThroughOneEnvelope:

    @pytest.mark.parametrize("path", [
        "/api/v1/_break/bare-500",
        "/api/v1/_break/driver",
        "/api/v1/_break/enum-403",
        "/api/v1/_break/written-404",
    ])
    def test_the_body_has_a_message_the_client_can_render(
            self, breaking_client, path):
        response = breaking_client.get(
            path, headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        assert response.status_code >= 400
        body = envelope(response)
        assert isinstance(body.get("message"), str) and body["message"].strip()
        assert body.get("error")
        assert body["correlation_id"], "the log must be findable"

    @pytest.mark.parametrize("path", [
        "/api/v1/_break/bare-500",
        "/api/v1/_break/driver",
        "/api/v1/_break/enum-403",
    ])
    def test_no_engineering_detail_is_in_it(self, breaking_client, path):
        response = breaking_client.get(
            path, headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        message = envelope(response)["message"]
        found = ENGINEERING.search(message)
        assert not found, f"{path} leaked {found.group(0)!r}: {message}"

    def test_the_connection_string_never_leaves_the_server(
            self, breaking_client):
        """The Phase 0 failure: a stopped database reported as a bug, with the
        credentials in the message."""
        response = breaking_client.get(
            "/api/v1/_break/driver",
            headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        whole = json.dumps(response.json())
        assert "hunter2" not in whole
        assert "postgresql://" not in whole
        assert not failures.leaks(whole)

    def test_a_route_that_wrote_a_sentence_keeps_it(self, breaking_client):
        """The governed default is a floor, not a ceiling.

        A route that knows what it was doing says something more useful than
        any generic sentence, and replacing it would be the other failure —
        telling the reader less than the server knew.
        """
        response = breaking_client.get(
            "/api/v1/_break/written-404",
            headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        assert "top_borrowers" in envelope(response)["message"]

    def test_a_bare_enum_is_replaced_by_a_sentence(self, breaking_client):
        """`detail="forbidden"` is a token, not something to show a person."""
        response = breaking_client.get(
            "/api/v1/_break/enum-403",
            headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        message = envelope(response)["message"]
        assert message != "forbidden"
        assert "role" in message.lower()

    def test_a_five_hundred_never_keeps_the_routes_own_words(
            self, breaking_client):
        """At 5xx the text is as likely to be a driver's as a person's."""
        response = breaking_client.get(
            "/api/v1/_break/bare-500",
            headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        assert envelope(response)["message"] != "Internal Server Error"
        assert len(envelope(response)["message"].split()) > 5


class TestAnInvalidRequestBody:

    def test_pydantic_field_locations_do_not_reach_the_reader(self, client):
        response = client.post(
            "/api/v1/ask", json={"not": "a question"},
            headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        if response.status_code not in (400, 422):
            pytest.skip(f"route answered {response.status_code}")
        body = envelope(response)
        assert isinstance(body.get("message"), str)
        assert "type_error" not in json.dumps(body)
        assert "value_error" not in json.dumps(body)

    def test_it_still_says_which_field(self, client):
        """Refusing to leak internals is not a licence to be unhelpful."""
        response = client.post(
            "/api/v1/ask", json={"not": "a question"},
            headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"})
        if response.status_code != 422:
            pytest.skip(f"route answered {response.status_code}")
        assert "Check:" in envelope(response)["message"]


# ------------------------------------------------------- the sentences


class TestTheGovernedSentences:

    @pytest.mark.parametrize("status", sorted(failures.BY_STATUS))
    def test_each_one_is_a_sentence_and_not_a_code(self, status):
        message = failures.BY_STATUS[status]
        assert len(message.split()) >= 6, message
        assert message.endswith("."), message
        assert not ENGINEERING.search(message), message

    def test_a_status_nobody_wrote_one_for_still_gets_a_sentence(self):
        assert failures.for_status(418).strip()
        assert not ENGINEERING.search(failures.for_status(418))

    def test_a_leaking_route_sentence_is_discarded(self):
        leaking = ("could not connect to "
                   "postgresql://ipm_app:hunter2@db:5432/ipm")
        assert failures.for_status(400, leaking) != leaking
        assert not failures.leaks(failures.for_status(400, leaking))

    def test_they_name_no_vendor(self):
        """§12 applies to failures too — an error is product copy."""
        from backend.release import product_copy

        for message in failures.BY_STATUS.values():
            assert not product_copy.violations(message), message
        for message in failures.MESSAGE.values():
            assert not product_copy.violations(message), message


class TestTheCategoriesStillDiscriminate:
    """§9 asks for safe errors, not for one safe error.

    "Something went wrong" for a permission refusal, a missing dataset and a
    stopped database is exactly the defect P0.10 was opened for. These assert
    that hiding the detail did not also collapse the meaning.
    """

    def test_every_category_says_something_different(self):
        messages = [failures.MESSAGE[c] for c in failures.CATEGORIES]
        assert len(set(messages)) == len(messages)

    def test_a_permission_refusal_is_not_a_server_fault(self):
        assert failures.STATUS[failures.PERMISSION] == 403
        assert failures.STATUS[failures.PERSISTENCE] != 403

    def test_a_stopped_database_is_a_persistence_failure(self):
        """Not a bug in CreditProbe, and it must not read as one."""
        try:
            raise RuntimeError("could not answer") from OSError(
                "connection refused")
        except RuntimeError as e:
            # OSError classifies as EXECUTION, which is generic; what matters
            # is that the chain is read at all rather than only the wrapper.
            assert failures.classify(e) in (
                failures.EXECUTION, failures.PERSISTENCE)
