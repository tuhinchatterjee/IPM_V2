"""
Does the configured model actually answer?

Why this exists
---------------
A release went out where 1,334 tests passed and the product was broken for
everybody who had configured a key. The suite had pinned itself offline, so the
live path — the one the product ships in — had never executed once.

Why it is now a thin file
--------------------------
The eight checks used to be defined here, and `verify-live-ai.ps1 -Quick`
exercised them by shelling out to pytest **inside the production backend
container** — which ships neither `tests/` nor pytest, on purpose. The
subprocess died in 45ms without reaching an assertion and the verifier recorded
that as the model failing, so a perfectly healthy provider reported FAILED.

The definitions therefore moved into production code, at
`backend/validation/live_smoke.py`, where the running application can reach
them. This file drives the same functions. Neither copy can drift from the
other because there is only one copy: what pytest asserts here and what the
production verifier reports are the same eight outcomes.

These are skipped where no key is configured, which is CI, and they run for a
developer or a deployment that has one. Nothing here asserts what the model
*said*; it asserts that a real structured response came back, that the
telemetry recorded it, and that the state the product reports is earned rather
than assumed.
"""

from __future__ import annotations

import pytest

from backend.validation import live_smoke

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def _require_a_key():
    from backend.llm import get_provider

    if not get_provider(refresh=True).configured:
        pytest.skip("no AI provider key is configured")


def _assert(outcome: live_smoke.Outcome) -> None:
    """One outcome, as a pytest failure that says what went wrong.

    The check already carries a sanitised detail and an error category, so the
    assertion message is built from them rather than re-derived — a developer
    reading a red test and an operator reading a stored report should be
    looking at the same sentence.
    """
    assert outcome.passed, (
        f"{outcome.check}: {outcome.detail or 'failed'}"
        + (f" [{outcome.error_category}]" if outcome.error_category else ""))


# ------------------------------------------------------------------- routing


@pytest.mark.parametrize("routing", live_smoke.ROUTING,
                         ids=lambda r: r.id)
def test_a_real_structured_response_comes_back(routing):
    """Five requests, five different routing decisions."""
    outcome = live_smoke.routing_check(routing)
    _assert(outcome)
    assert outcome.calls >= 1, "no model call was recorded"
    assert outcome.model, "the response did not report which model answered"


# ------------------------------------------------------------------ the rest


def test_the_provider_reports_connected_only_after_a_real_response():
    """The whole point of the telemetry: CONNECTED has to be earned."""
    _assert(live_smoke.provider_connected())


def test_no_recorded_call_carries_anything_key_shaped():
    """Safe metadata only — asserted rather than trusted."""
    _assert(live_smoke.telemetry_secret_safety())


def test_an_answer_end_to_end_is_computed_by_the_runtime_not_the_model():
    """The live path still runs every figure through the governed runtime."""
    outcome = live_smoke.runtime_computes_result()
    _assert(outcome)
    assert outcome.calls >= 1, "the live path was not exercised"
