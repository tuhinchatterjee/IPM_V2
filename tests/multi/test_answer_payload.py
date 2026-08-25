"""
What the answer panel is handed.

The reading that reaches the answer comes from either planner, and the panel
renders one shape. A key present on the single-dataset reading and absent on the
multi-dataset one is how a panel that works for one question takes the whole
answer down for another — which is exactly what happened, and is what this file
exists to stop happening again.
"""

from __future__ import annotations

import time

import pytest

from backend.orchestration import dynamic
from backend.orchestration import executor as orch
from backend.orchestration.vocabulary import get_vocabulary
from tests.conftest import database_available

MULTI = ("Show Real Estate customers whose ECL increased more than 20%, "
         "rating deteriorated at least two notches, and EAD did not decline "
         "over the latest year.")

#: Every key the answer panel reads off a reading, whichever planner made it.
PANEL_KEYS = ("summary", "filters", "conditions")


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("needs the platform database")


@pytest.fixture(scope="module")
def multi_result():
    request = orch.multi_candidate(MULTI, get_vocabulary())
    assert request is not None
    investigation = orch.run_multi(MULTI, request, started=time.perf_counter())
    return investigation.steps[0].result


def test_both_readings_carry_the_keys_the_panel_renders(multi_result):
    single = dynamic.read_question(
        "Show customers whose ECL increased more than 20% and EAD did not "
        "decline over the latest year.",
        periods=get_vocabulary().periods,
        dimensions=get_vocabulary().dimensions).to_dict()
    for key in PANEL_KEYS:
        assert key in single, f"the single-dataset reading has no '{key}'"
        assert key in multi_result["reading"], (
            f"the multi-dataset reading has no '{key}'")


def test_a_list_the_panel_maps_over_is_never_missing(multi_result):
    reading = multi_result["reading"]
    assert isinstance(reading["filters"], list)
    assert isinstance(reading["conditions"], list)
    assert reading["conditions"], "the worked example has three conditions"


def test_every_condition_carries_what_the_panel_shows(multi_result):
    for condition in multi_result["reading"]["conditions"]:
        assert condition.get("description"), "the badge has nothing to render"
        assert condition.get("column"), "the badge has no React key"


def test_the_answer_carries_what_data_and_method_reads(multi_result):
    for key in ("datasets", "joins", "reconciliation", "join_plan",
                "fingerprint", "explanation"):
        assert key in multi_result, f"the answer has no '{key}'"
    assert multi_result["join_plan"]["paths"]
    for path in multi_result["join_plan"]["paths"]:
        assert isinstance(path["edges"], list) and path["edges"]
    for entry in multi_result["fingerprint"]["datasets"]:
        assert isinstance(entry["periods"], list)
