"""
Shared fixtures for the export suite.

Every test here runs against an analysis this session created. That is the
point, and §58 asks for it explicitly: an earlier suite asserted against run ids
that happened to exist in a shared development database, so it passed for months
and then failed the day somebody regenerated the data — not because the product
had changed but because the records had. A test that depends on rows it did not
create is testing the database's history, not the code.

So the fixture asks a real question through the real API, offline, and hands its
run id to the tests. If the analytical lake is not built, the suite skips rather
than asserting against nothing.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.helpers import FACILITY
from tests.conftest import database_available

#: §33's mandatory example. Written with the measure explicitly resolved, so
#: the product answers it rather than stopping to ask which exposure was meant.
RATING_QUESTION = "Show IFRS 9 EAD by internal rating for the latest period."


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built — run `python scripts/build_data_lake.py`")
    if not database_available():
        pytest.skip("Exports read a persisted run; PostgreSQL is not reachable")


def ask(client, question: str, *, role: str = "ADMIN") -> int:
    """Ask a question and return the id of the run it produced."""
    response = client.post("/api/v1/ask", json={"question": question},
                           headers={"X-IPM-Role": role})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded", (
        f"{question!r} did not produce a result: {body['status']} — "
        f"{(body.get('narrative') or {}).get('summary')}"
    )
    run_id = body.get("analysis_run_id")
    assert run_id, "A succeeded answer must persist an analysis run to be exportable"
    return int(run_id)


@pytest.fixture(scope="module")
def rating_run(client) -> int:
    """§33: IFRS 9 EAD by internal rating, run fresh for this suite."""
    return ask(client, RATING_QUESTION)


@pytest.fixture(scope="module")
def rating_pack(rating_run):
    from backend.exports.gather import pack_for

    return pack_for(rating_run, user_name="Test Runner")
