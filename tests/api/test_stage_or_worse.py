"""«Stage 2 or worse» means stage >= 2, everywhere the answer is decided.

The defect
----------
The plan compiled the widening correctly — `ifrs9_stage >= 2`, stage 3
borrowers included — and then the post-result invariant, which built its
promise from the filter PAIRS alone, demanded `= 2` of every row and withheld
the answer for "contradicting" a question that had asked for exactly what it
returned. A correct answer refused by the layer that exists to catch wrong
ones.

The fix is one reading, recorded once. `ordinal.read` runs where the predicate
is compiled, the qualifier is stored on the build, and the invariant and the
narrative both read it from there. Three modules re-reading the sentence is
three chances to disagree; one record cannot.
"""

from __future__ import annotations

import pytest

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


def rows_of(body: dict) -> list[dict]:
    rows: list[dict] = []
    for step in body.get("steps") or []:
        found = (step.get("result") or {}).get("rows") or []
        if found:
            rows = found
    return rows


def answer_of(body: dict) -> str:
    return str((body.get("narrative") or {}).get("direct_answer") or "")


WIDENED = "Show exposure at default for Stage 2 or worse borrowers."
NARROW = "Show exposure at default for Stage 2 borrowers."
WORST = "Show exposure at default for Stage 3 borrowers."


class TestTheWidenedPopulationIsShown:
    def test_it_is_not_withheld(self, client):
        body = ask(client, WIDENED)
        assert body["status"] == "succeeded", answer_of(body)

    def test_stage_three_borrowers_are_in_it(self, client):
        stages = {r["ifrs9_stage"] for r in rows_of(ask(client, WIDENED))
                  if "ifrs9_stage" in r}
        assert stages, "the answer does not carry the stage it filtered on"
        assert 3 in stages, (
            f"'stage 2 or worse' returned only {sorted(stages)}; the stage 3 "
            "borrowers the question was reaching for are still excluded")

    def test_no_row_is_below_the_stage_asked_for(self, client):
        for row in rows_of(ask(client, WIDENED)):
            if "ifrs9_stage" in row:
                assert float(row["ifrs9_stage"]) >= 2


class TestPlainStageSemanticsAreUnchanged:
    """A qualifier that was not there must not be invented."""

    def test_stage_two_alone_stays_at_two(self, client):
        stages = {r["ifrs9_stage"] for r in rows_of(ask(client, NARROW))
                  if "ifrs9_stage" in r}
        assert stages == {2}, f"'Stage 2' returned {sorted(stages)}"

    def test_stage_three_alone_stays_at_three(self, client):
        stages = {r["ifrs9_stage"] for r in rows_of(ask(client, WORST))
                  if "ifrs9_stage" in r}
        assert stages == {3}, f"'Stage 3' returned {sorted(stages)}"


class TestTheAnswerSaysWhichPopulationItShowed:
    """A heading that says "stage 2" over stage 3 rows has misdescribed itself."""

    def test_the_widened_answer_says_or_worse(self, client):
        said = answer_of(ask(client, WIDENED)).lower()
        assert "or worse" in said, said

    def test_the_narrow_answer_does_not(self, client):
        said = answer_of(ask(client, NARROW)).lower()
        assert "or worse" not in said, said
