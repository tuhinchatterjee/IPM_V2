"""
Does the configured model actually answer?

Why this exists
---------------
A release went out where 1,334 tests passed and the product was broken for
everybody who had configured a key. The suite had pinned itself offline, so the
live path — the one the product ships in — had never executed once.

These tests exercise it. They are skipped where no key is configured, which is
CI, and they run for a developer or a deployment that has one. Nothing here
asserts what the model *said*; it asserts that a real structured response came
back, that the telemetry recorded it, and that the state the product reports is
earned rather than assumed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def _require_a_key():
    from backend.llm import get_provider

    if not get_provider(refresh=True).configured:
        pytest.skip("no AI provider key is configured")


#: Five requests, chosen to exercise five different routing decisions rather
#: than five phrasings of the same one.
REQUESTS = [
    ("What data do you have about borrower ratings?", "DATA_DISCOVERY"),
    ("What fields are available in the ratings data?", "DATA_DICTIONARY"),
    ("How is the ratings data connected to IFRS 9 data?", "DATA_RELATIONSHIP"),
    ("What is total EAD by sector in the latest quarter?", "ANALYSIS"),
    ("Show me the five largest Real Estate customers by EAD.", "ANALYSIS"),
]


@pytest.mark.parametrize(("question", "expected"), REQUESTS,
                         ids=lambda v: str(v)[:34])
def test_a_real_structured_response_comes_back(question, expected):
    from backend.orchestration.context import retrieve
    from backend.orchestration.router import read

    result = read(question, context=retrieve(question))
    assert not result.degraded_reason, (
        f"the live path failed: {result.degraded_reason}")
    assert result.calls >= 1, "no model call was made"
    assert result.reading.source in ("llm", "guardrail")
    assert result.reading.model, "the response did not report which model answered"
    assert result.reading.intent == expected, (
        f"{question!r} was read as {result.reading.intent}, not {expected}")


def test_the_provider_reports_connected_only_after_a_real_response():
    """The whole point of the telemetry: CONNECTED has to be earned."""
    from backend.llm import health, telemetry
    from backend.orchestration.context import retrieve
    from backend.orchestration.router import read

    telemetry.ledger().reset()
    assert health()["state"] == telemetry.CONFIGURED, (
        "a key with no calls behind it must not report CONNECTED")

    read("What data do you have about arrears?", context=retrieve("arrears"))

    observed = health()
    assert observed["state"] == telemetry.CONNECTED
    assert observed["counts"]["succeeded"] >= 1
    assert observed["last_success"]["latency_ms"] > 0
    assert observed["last_success"]["model"]


def test_no_recorded_call_carries_anything_key_shaped():
    """Safe metadata only — asserted rather than trusted."""
    from backend.config import settings
    from backend.llm import health

    key = (settings.anthropic_api_key or "").strip()
    blob = repr(health())
    assert key, "this test is meaningless without a key"
    assert key not in blob
    assert key[:12] not in blob


def test_an_answer_end_to_end_is_computed_by_the_runtime_not_the_model():
    """The live path still runs every figure through the governed runtime."""
    from backend.orchestration.executor import answer_investigation

    investigation, answered = answer_investigation(
        "What is total EAD by sector in the latest quarter?", persist=False)
    assert investigation.status == "succeeded", investigation.rejected
    assert answered.runtime is not None
    assert investigation.steps[0].result["rows"], "no rows were computed"
    assert (investigation.conversation or {}).get("model_calls", 0) >= 1
