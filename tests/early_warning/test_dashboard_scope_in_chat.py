"""A question asked from a filtered screen is about what is on the screen.

The gap this closes
-------------------
A reader narrows the dashboard to obligors at High or above in Contracting,
looks at the fifty-two that match, and types "how many of these are
deteriorating?" -- and is answered about three hundred. Nothing on the screen
says the filter was dropped, so the number reads as an answer to the question
asked.

So the dashboard's filter travels with the question, as the SAME governed
FilterSpec the dashboard and the export use. Structured, not described: a
scope reconstructed from a sentence is a scope that can be read back wrong,
and this one is already exact.

Two rules hold it in place, and they pull in opposite directions on purpose:

  * The scope is SNAPSHOTTED at thread start (§42). A thread whose scope
    followed a live filter would make its own history unreadable -- the
    answer three turns up was about the population of three turns ago. The
    client owns that snapshot; these tests hold the server's half.

  * An explicit question OVERRIDES it. The filter says what the reader is
    looking at; the sentence says what they are asking about, and when the
    two differ the sentence is the request.
"""

from __future__ import annotations

import pytest

from backend.early_warning import filterspec as fsp
from backend.early_warning.conversation import normalise as norm


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


def screen_state(**payload):
    """What the router builds from an ask body carrying a dashboard scope."""
    from backend.api.routers.early_warning_v2 import AskRequest, _screen_state

    return _screen_state(AskRequest(question="anything", **payload))


def read(question: str, **ui):
    """The deterministic floor, which is where the screen is inherited."""
    cleaned = norm.clean(question)
    return norm._read_deterministic(cleaned, ui_state=ui)


# ------------------------------------------------- the scope reaches the turn


def test_a_scope_travels_as_the_governed_spec_not_as_prose():
    state = screen_state(dashboard_scope={
        "filters": {"ews_band": ["HIGH", "VERY_HIGH"],
                    "segment": ["Large Corporate"]}})
    assert state["dashboard_scope"]["filters"]["ews_band"] == [
        "HIGH", "VERY_HIGH"]
    # A sentence as well, for the reader and the trace -- alongside the
    # structure, never instead of it.
    assert "High" in state["dashboard_scope_sentence"]


def test_one_band_reaches_the_request_reader_as_a_band():
    state = screen_state(dashboard_scope={"filters": {"ews_band": ["HIGH"]}})
    assert state["band"] == "HIGH"


def test_two_bands_do_not_become_the_first_one():
    # "High and Very High" collapsed to "High" is an answer about a narrower
    # population presented as the one that was asked for.
    state = screen_state(dashboard_scope={
        "filters": {"ews_band": ["HIGH", "VERY_HIGH"]}})
    assert "band" not in state
    assert state["dashboard_scope"]["filters"]["ews_band"] == [
        "HIGH", "VERY_HIGH"]


def test_the_scopes_month_becomes_the_turns_month():
    state = screen_state(dashboard_scope={"period": "2026-03", "filters": {}})
    assert state["period"] == "2026-03"


def test_no_scope_leaves_the_screen_state_alone():
    state = screen_state(ui_state={"level": "segment"})
    assert state == {"level": "segment"}


def test_a_scope_the_dashboard_could_not_have_produced_is_refused():
    """The chat is not a second door into the filtering.

    An ungoverned filter written into a request body by hand must not reach
    the planner just because it arrived through `/ask` rather than
    `/dashboard`.
    """
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        screen_state(dashboard_scope={"filters": {"made_up": ["x"]}})
    assert raised.value.status_code == 422
    assert raised.value.detail["error"] == "invalid_filter"


def test_a_band_that_is_not_a_band_cannot_enter_through_the_chat():
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        screen_state(dashboard_scope={"filters": {"ews_band": ["EXTREME"]}})


# ------------------------------------------ the sentence outranks the screen


def band_of(request) -> str:
    """The band the plan will actually filter on.

    Two keys reach the same filter: the screen writes `band`, and a band
    named in the question resolves to `ews_band`. `plan._population_filters` folds both
    into one, so the question a test should ask is which band SURVIVES, not
    which key it happens to be under.
    """
    from backend.early_warning.conversation import plan as plan_mod

    return str(plan_mod._population_filters(request.inherited_context, "")
                       .get("ews_band")
                   or "")


def test_a_question_naming_its_own_band_beats_the_screens_band():
    """§42. The filter is what the reader is LOOKING at."""
    request = read("which obligors are at very high risk?", band="HIGH")
    assert band_of(request) == "VERY_HIGH"


def test_a_question_naming_its_own_segment_beats_the_screens_segment():
    from backend.early_warning import v2_service as svc

    book = svc.borrower_month()
    segments = sorted({str(s) for s in book["segment"].dropna().unique()})
    if len(segments) < 2:
        pytest.skip("Only one segment in the book.")
    looking_at, asking_about = segments[0], segments[1]

    request = read(f"how is the {asking_about} segment doing?",
                   segment=looking_at)
    assert request.inherited_context.get("segment") == asking_about


def test_a_question_that_names_nothing_keeps_the_screens_scope():
    # The other half of the rule, and the one that makes the feature work at
    # all: "how many of these are deteriorating?" is about these.
    request = read("how many are deteriorating?", band="HIGH")
    assert band_of(request) == "HIGH"


def test_one_band_in_a_question_is_one_band_and_not_a_comparison():
    """"Very high" contains "high", and a resolver that read both out of it
    turned a question about one band into a comparison of two."""
    request = read("which obligors are at very high risk?")
    assert "comparison_pair" not in request.inherited_context
    assert band_of(request) == "VERY_HIGH"


def test_the_obligor_on_screen_still_reaches_a_question_about_it():
    request = read("why is it flagged?", customer_id="CORP-100721")
    assert request.inherited_context.get("customer_id") == "CORP-100721"
