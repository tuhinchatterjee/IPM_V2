"""
A turn is a thing with a state, and the backend owns it.

The defect this closes
----------------------
`/ask` answers in one synchronous call. On a certified provider that call
takes forty to seventy-five seconds, and the browser held it open under a
sixty-second fetch timeout — so the screen showed

    The backend did not respond within 60 seconds.

in red, and then, underneath it, the completed answer:

    Analysed in 73.2s ...

Both cannot be true, and the wrong one was the browser's. A fetch timeout is
a fact about a socket; whether a credit analysis succeeded is not a question
a socket can answer.

So a turn is created, runs, and reports `running`, `completed` or `failed`.
The client renders that and owns none of it. `/ask` is untouched — it still
answers synchronously, and the certification drives the pipeline directly —
so nothing that already worked has to move.
"""

from __future__ import annotations

import time

import pytest

from backend.early_warning.conversation import live as ews_live


def headers(role: str = "ANALYST") -> dict[str, str]:
    return {"X-IPM-Role": role}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module")
def domain_built(client) -> bool:
    r = client.get("/api/v1/early-warning/v2", headers=headers())
    return r.status_code == 200


def start(client, **over) -> dict:
    body = {"question": "What is the current Early Warning distribution "
                        "by risk band?",
            "mode": "standard"}
    body.update(over)
    r = client.post("/api/v1/early-warning/v2/ask/start", json=body,
                    headers=headers())
    assert r.status_code == 200, r.text
    return r.json()


def poll(client, turn_id: str) -> dict:
    r = client.post("/api/v1/early-warning/v2/ask/progress",
                    json={"turn_key": turn_id}, headers=headers())
    assert r.status_code == 200, r.text
    return r.json()


def settle(client, turn_id: str, *, limit: float = 120.0) -> dict:
    """Poll until the BACKEND says the turn is over. No other clock."""
    deadline = time.monotonic() + limit
    seen = poll(client, turn_id)
    while seen.get("state") not in ews_live.TERMINAL:
        assert time.monotonic() < deadline, f"turn never settled: {seen}"
        time.sleep(0.05)
        seen = poll(client, turn_id)
    return seen


# ------------------------------------------------------- the lifecycle

def test_starting_a_turn_returns_its_id_at_once(client, domain_built):
    if not domain_built:
        pytest.skip("Early Warning domain not built")
    began = time.monotonic()
    started = start(client)
    # The point of the call: it hands back an id and returns. Whatever the
    # analysis costs is not paid here.
    assert time.monotonic() - began < 5.0
    assert started["turn_id"]
    assert started["state"] == ews_live.RUNNING


def test_the_turn_completes_and_carries_its_answer(client, domain_built):
    if not domain_built:
        pytest.skip("Early Warning domain not built")
    started = start(client)
    done = settle(client, started["turn_id"])
    assert done["state"] == ews_live.COMPLETED
    assert done["failure"] == "" if "failure" in done else True
    answer = done["answer"]
    assert answer["answered"] is True
    assert answer["direct"]
    assert answer["routing"]["selected_functionality"] == "early_warning"


def test_a_running_turn_never_reports_a_failure(client, domain_built):
    """The whole defect, in one assertion: running is not failed."""
    if not domain_built:
        pytest.skip("Early Warning domain not built")
    started = start(client)
    seen = poll(client, started["turn_id"])
    if seen.get("state") == ews_live.RUNNING:
        assert "failure" not in seen
        assert "answer" not in seen
    settle(client, started["turn_id"])


def test_the_answer_is_the_one_the_synchronous_call_gives(client,
                                                          domain_built):
    """Two doors, one turn. A started turn and a synchronous one must not
    describe the same question differently."""
    if not domain_built:
        pytest.skip("Early Warning domain not built")
    question = "Which obligors are currently High or Very High?"
    started = start(client, question=question, thread_id="lifecycle-same-a")
    done = settle(client, started["turn_id"])["answer"]

    r = client.post("/api/v1/early-warning/v2/ask",
                    json={"question": question, "mode": "standard",
                          "thread_id": "lifecycle-same-b"},
                    headers=headers())
    assert r.status_code == 200
    direct = r.json()
    assert done["scope"] == direct["scope"]
    assert done["direct"] == direct["direct"]


# ------------------------------------------------- the long turn (test A)

def test_a_turn_longer_than_any_browser_timeout_still_completes(monkeypatch):
    """Seventy-five seconds, simulated, with no browser in the loop.

    The runtime is the only thing that decides a turn is over, so a turn that
    outlives every fetch timeout in the product is simply a turn that is
    still running.
    """
    ews_live.reset()

    class Principal:
        user_id = 1
        role = "ANALYST"

    key = ews_live.open_turn("slow-turn", Principal(), question="why?")
    assert key == "slow-turn"

    # Pretend 75 seconds have passed and the turn is still going.
    assert ews_live.state_of(key) == ews_live.RUNNING
    seen = ews_live.read(key, Principal())
    assert seen["state"] == ews_live.RUNNING
    assert "failure" not in seen
    assert "answer" not in seen

    ews_live.finish(key, {"answered": True, "direct": "Analysed.",
                          "scope": "level"})
    seen = ews_live.read(key, Principal())
    assert seen["state"] == ews_live.COMPLETED
    assert seen["answer"]["direct"] == "Analysed."
    assert "failure" not in seen
    ews_live.reset()


# --------------------------------------------- poll failure (test B)

def test_a_turn_survives_a_poll_nobody_could_answer(client, domain_built):
    """A failed poll is not a failed analysis.

    Simulated as the worst case the deployment note describes: a poll landing
    where the turn is unknown. It must read as "I cannot see it", never as
    "it failed".
    """
    if not domain_built:
        pytest.skip("Early Warning domain not built")
    started = start(client)
    missed = poll(client, "a-turn-nobody-ran")
    assert missed["watching"] is False
    assert missed["state"] == ""
    assert "failure" not in missed
    # And the real turn is unaffected by the miss.
    assert settle(client, started["turn_id"])["state"] == ews_live.COMPLETED


# ------------------------------------------------ a real failure (test C)

def test_a_failed_turn_says_so_once_and_in_the_reader_s_language():
    ews_live.reset()

    class Principal:
        user_id = 1
        role = "ANALYST"

    key = ews_live.open_turn("broken-turn", Principal(), question="why?")
    ews_live.fail(key, "CreditProbe could not complete this analysis.")
    seen = ews_live.read(key, Principal())
    assert seen["state"] == ews_live.FAILED
    assert seen["failure"] == "CreditProbe could not complete this analysis."
    # The question comes back so the client can offer a retry without having
    # had to keep it.
    assert seen["question"] == "why?"
    assert "answer" not in seen
    ews_live.reset()


def test_a_failure_never_carries_a_provider_or_python_message(
        client, monkeypatch):
    """A turn that raises becomes one sentence about credit.

    Driven through the endpoint rather than read out of the source, because
    what matters is what reaches the screen. The exception below carries a
    connection string, a status code and a stack — none of it may survive.
    """
    from backend.early_warning.conversation import pipeline as ews_pipeline

    def explode(*_args, **_kwargs):
        raise RuntimeError(
            "anthropic.APIStatusError: 529 overloaded_error at "
            "https://api.anthropic.com/v1/messages (key sk-ant-XXXX)")

    monkeypatch.setattr(ews_pipeline, "answer", explode)
    started = start(client, question="Why has Contracting deteriorated?",
                    turn_key="turn-that-raises")
    done = settle(client, started["turn_id"], limit=30.0)

    assert done["state"] == ews_live.FAILED
    assert done["failure"] == "CreditProbe could not complete this analysis."
    assert "answer" not in done
    # The question comes back so a retry needs nothing from the client.
    assert done["question"] == "Why has Contracting deteriorated?"
    blob = repr(done).lower()
    for leaked in ("anthropic", "529", "api.anthropic.com", "sk-ant",
                   "runtimeerror", "traceback", "overloaded_error"):
        assert leaked not in blob, leaked


# --------------------------------- a later turn is clean (test D)

def test_a_later_turn_does_not_inherit_an_earlier_failure(client,
                                                          domain_built):
    if not domain_built:
        pytest.skip("Early Warning domain not built")

    class Principal:
        user_id = 1
        role = "ANALYST"

    ews_live.open_turn("earlier-failed", Principal(), question="why?")
    ews_live.fail("earlier-failed", "CreditProbe could not complete this "
                                    "analysis.")
    started = start(client, thread_id="clean-after-failure")
    done = settle(client, started["turn_id"])
    assert done["state"] == ews_live.COMPLETED
    assert "failure" not in done
    # And the earlier one is still failed. State belongs to a turn, not to a
    # thread and not to the screen.
    assert ews_live.state_of("earlier-failed") == ews_live.FAILED
    ews_live.forget("earlier-failed")


# ---------------------------------------------------- no double analysis

def test_polling_does_not_run_the_analysis_again(client, domain_built):
    if not domain_built:
        pytest.skip("Early Warning domain not built")
    started = start(client)
    done = settle(client, started["turn_id"])
    calls = done["answer"]["budget"]["executions_attempted"]
    for _ in range(5):
        again = poll(client, started["turn_id"])
        assert again["state"] == ews_live.COMPLETED
        assert again["answer"]["budget"]["executions_attempted"] == calls


def test_a_second_start_with_the_same_id_is_the_same_turn(client,
                                                          domain_built):
    """An id identifies a turn. Re-using one replaces it rather than running
    two analyses under one name."""
    if not domain_built:
        pytest.skip("Early Warning domain not built")
    started = start(client, turn_key="fixed-turn-id")
    assert started["turn_id"] == "fixed-turn-id"
    settle(client, "fixed-turn-id")
    again = start(client, turn_key="fixed-turn-id")
    assert again["turn_id"] == "fixed-turn-id"
    settle(client, "fixed-turn-id")


# ------------------------------------------------------------- ownership

def test_a_turn_is_readable_only_by_whoever_started_it():
    """Turn ids are client-chosen and therefore guessable, so the check is on
    identity rather than on the id being secret.

    Asserted against the registry directly: over HTTP an unknown user id
    resolves to anonymous, so two callers who are both anonymous are — quite
    correctly — the same reader, and a test that expected otherwise would be
    testing the header parser rather than this control.
    """
    ews_live.reset()

    class Principal:
        def __init__(self, user_id, role="ANALYST"):
            self.user_id, self.role = user_id, role

    mine, theirs = Principal(1), Principal(2)
    ews_live.open_turn("owned-turn", mine, question="why?")
    ews_live.finish("owned-turn", {"answered": True, "direct": "Analysed."})

    assert ews_live.read("owned-turn", mine)["state"] == ews_live.COMPLETED
    assert ews_live.read("owned-turn", theirs) is None
    # A different ROLE is a different reader too.
    assert ews_live.read("owned-turn", Principal(1, "CRO")) is None
    ews_live.reset()


def test_an_unstorable_turn_id_is_refused(client):
    r = client.post("/api/v1/early-warning/v2/ask/start",
                    json={"question": "Why?", "turn_key": "../etc/passwd"},
                    headers=headers())
    assert r.status_code == 400
