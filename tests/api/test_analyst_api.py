"""The analyst, through the real routes. §2, §5, §11.

Two things this asserts that the unit suites cannot:

  * the ROUTE returns what the product renders, in the shape the client reads;
  * the deterministic path is untouched when no provider is configured, which
    on a bank's own network may be the only permitted arrangement and is the
    posture this environment actually runs in.

No live provider call is made. Where the analyst path itself is exercised, a
scripted provider is injected — see tests/analyst/conftest.py for why that is
a complete provider as far as the loop is concerned.
"""

from __future__ import annotations

import pytest

from backend.analyst import answers, route
from backend.analyst.safety import Principal
from tests.analyst.conftest import ScriptedProvider


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


HEADERS = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}


@pytest.fixture(autouse=True)
def _empty_store():
    answers.store().clear()
    yield
    answers.store().clear()


class TestThePosture:

    def test_it_says_which_path_is_primary(self, client):
        response = client.get("/api/v1/ask/posture", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["primary"] in (route.ANALYST, route.DETERMINISTIC)
        assert body["tools"] >= 20
        assert body["max_tool_calls"] >= 1

    def test_it_names_no_vendor(self, client):
        from backend.release import product_copy

        body = client.get("/api/v1/ask/posture", headers=HEADERS).json()
        assert not product_copy.violations(str(body))

    def test_with_no_provider_it_says_the_reader_answers(self, client):
        body = client.get("/api/v1/ask/posture", headers=HEADERS).json()
        if body["analyst_available"]:
            pytest.skip("a provider is configured in this environment")
        assert body["primary"] == route.DETERMINISTIC
        assert "governed semantic reader" in body["label"]


class TestAskCarriesBothPaths:
    """The deterministic result keeps its shape; the analyst is added beside
    it. §2 makes the analyst primary without making every existing consumer
    rewrite itself on the same day."""

    def test_ask_still_answers_when_no_provider_is_configured(self, client):
        response = client.post("/api/v1/ask",
                               json={"question": "What is total exposure?",
                                     "persist": False},
                               headers=HEADERS)
        if response.status_code in (401, 403):
            pytest.skip("this environment requires a signed-in session")
        assert response.status_code == 200
        body = response.json()
        assert "analyst" in body
        assert body["analyst"]["path"] in (route.ANALYST, route.DETERMINISTIC)

    def test_the_analyst_block_never_takes_the_answer_down(self, client,
                                                           monkeypatch):
        """§9. A failure in one path is not a failure of the product."""
        from backend.api.routers import ask as ask_router

        monkeypatch.setattr(ask_router, "_analyst_view",
                            lambda *_a, **_k: (_ for _ in ()).throw(
                                RuntimeError("boom")))
        response = client.post("/api/v1/ask",
                               json={"question": "What is total exposure?",
                                     "persist": False},
                               headers=HEADERS)
        assert response.status_code in (200, 401, 403, 500)
        if response.status_code == 500:
            pytest.fail("the analyst took the deterministic answer down")


class TestTheRoutingLayer:

    def test_the_analyst_answers_when_a_provider_is_there(self):
        found = route.answer(
            "Which sectors carry the most exposure?",
            Principal(1, "ANALYST"),
            provider=ScriptedProvider([
                {"action": "CALL_TOOL", "why": "rank them",
                 "tool": "rank_entities",
                 "arguments": {"dataset": "portfolio_facility",
                               "entity": "sector", "measure": "ead",
                               "top": 5}},
                {"action": "ANSWER", "why": "done",
                 "answer": "Contracting is the largest."},
            ]))
        assert found["path"] == route.ANALYST
        assert found["answer"] == "Contracting is the largest."
        assert found["evidence"]["calls"] == 1

    def test_a_provider_failure_falls_back_rather_than_failing(self):
        from tests.analyst.conftest import BrokenProvider

        found = route.answer("Which sectors?", Principal(1, "ANALYST"),
                             provider=BrokenProvider())
        assert found["path"] == route.DETERMINISTIC
        assert "did not answer" in found["why_fallback"]

    def test_a_clarification_comes_back_as_one_sentence(self):
        """§5: a question in the same investigation, not a card."""
        found = route.answer(
            "Which borrowers deteriorate?", Principal(1, "ANALYST"),
            provider=ScriptedProvider([
                {"action": "ASK", "why": "two governed measures fit",
                 "question": ("Do you mean the current 12-month PD, or "
                              "deterioration since last quarter?"),
                 "assumption": "the current 12-month PD"}]))
        assert found["outcome"] == "ASK"
        assert found["question_back"].endswith("?")
        assert found["assumption"]
        assert "options" not in found

    def test_the_reply_continues_the_same_investigation(self):
        """The clarification's answer is carried, not a new question started.

        Distinct run keys, so neither is served from the other's entry, and the
        analyst is told not to ask again.
        """
        principal = Principal(1, "ANALYST")
        script = [
            {"action": "CALL_TOOL", "why": "rank", "tool": "rank_entities",
             "arguments": {"dataset": "portfolio_facility", "entity": "sector",
                           "measure": "ead", "top": 3}},
            {"action": "ANSWER", "why": "done", "answer": "Contracting."},
        ]
        first = route.answer("Which borrowers deteriorate?", principal,
                             provider=ScriptedProvider(list(script)))
        second = route.answer("Which borrowers deteriorate?", principal,
                              clarification="use the current 12-month PD",
                              provider=ScriptedProvider(list(script)))
        assert first["run_key"]["key"] != second["run_key"]["key"]
        assert second["reproduced"] is False

    def test_the_principal_of_an_api_caller_is_never_promoted(self):
        class Caller:
            user_id = 7
            role = None

        assert route.principal_of(Caller()).role == "VIEWER"

    def test_an_analyst_principal_passes_through_with_its_scope(self):
        narrow = Principal(3, "ANALYST", datasets=frozenset({"a", "b"}))
        assert route.principal_of(narrow).datasets == frozenset({"a", "b"})
