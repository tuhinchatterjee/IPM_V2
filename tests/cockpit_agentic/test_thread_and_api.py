"""Thread continuity and the API surface.
Specification sections 11, 12 and 17."""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import states as st
from backend.cockpit_agentic import thread
from backend.cockpit_agentic.contracts import Exchange, ThreadSummary
from backend.cockpit_agentic.ledger import DEEP_LIMITS, STANDARD_LIMITS
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider


def exchange(i: int, *, kind="answer", release="r1", domain="corporate_cockpit"):
    return Exchange(exchange_id=f"e{i}", question=f"question {i}",
                    answer=f"answer {i}", kind=kind, domain_id=domain,
                    dataset_release_id=release)


# ============================================== section 12: selection

def test_three_complete_pairs_by_default():
    history = [exchange(i) for i in range(20)]
    selection = thread.select(history, limits=STANDARD_LIMITS,
                              dataset_release_id="r1")
    assert selection.delivered_pairs == 3
    assert [e["exchange_id"] for e in selection.exchanges] == ["e17", "e18",
                                                               "e19"]
    assert selection.limited_by == "pairs"


def test_at_question_twenty_the_context_is_seventeen_through_nineteen():
    """The specification's own worked example."""
    history = [exchange(i) for i in range(1, 20)]
    selection = thread.select(history, limits=STANDARD_LIMITS,
                              dataset_release_id="r1")
    assert [e["exchange_id"] for e in selection.exchanges] == ["e17", "e18",
                                                               "e19"]


def test_five_can_be_selected_and_eight_is_the_hard_cap():
    history = [exchange(i) for i in range(20)]
    assert thread.select(history, limits=STANDARD_LIMITS,
                         dataset_release_id="r1", pairs=5).delivered_pairs == 5
    assert thread.select(history, limits=STANDARD_LIMITS,
                         dataset_release_id="r1", pairs=8).delivered_pairs == 8
    # Asking for more than eight gets eight, not more.
    assert thread.select(history, limits=STANDARD_LIMITS,
                         dataset_release_id="r1",
                         pairs=20).delivered_pairs == 8
    assert thread.HARD_CAP_PAIRS == 8


def test_the_history_token_cap_bites_before_the_pair_cap():
    fat = [Exchange(exchange_id=f"e{i}", question="q", answer="x" * 4000,
                    dataset_release_id="r1") for i in range(8)]
    selection = thread.select(fat, limits=STANDARD_LIMITS,
                              dataset_release_id="r1", pairs=8)
    assert selection.delivered_pairs < 8
    assert selection.limited_by == "tokens"
    assert selection.estimated_tokens <= STANDARD_LIMITS.recent_history_tokens


def test_deep_mode_carries_more_history_but_not_more_pairs():
    fat = [Exchange(exchange_id=f"e{i}", question="q", answer="x" * 3000,
                    dataset_release_id="r1") for i in range(8)]
    standard = thread.select(fat, limits=STANDARD_LIMITS,
                             dataset_release_id="r1", pairs=8)
    deep = thread.select(fat, limits=DEEP_LIMITS, dataset_release_id="r1",
                         pairs=8)
    assert deep.delivered_pairs > standard.delivered_pairs
    assert deep.delivered_pairs <= thread.HARD_CAP_PAIRS


def test_an_explicitly_referenced_older_exchange_displaces_a_recent_one():
    """Section 12: it replaces a less relevant recent pair WITHIN the same
    cap. It does not raise the cap."""
    history = [exchange(i) for i in range(20)]
    selection = thread.select(history, limits=STANDARD_LIMITS,
                              dataset_release_id="r1", pairs=3,
                              referenced_ids=["e2"])
    ids = [e["exchange_id"] for e in selection.exchanges]
    assert "e2" in ids
    assert len(ids) == 3, "the reference raised the cap"


# ============================================== the boundary applies to memory

def test_a_cross_domain_exchange_is_refused_however_it_got_there():
    """Section 6.4: a result created by another module does not become
    authorized by appearing in an old answer."""
    history = [exchange(1), exchange(2, domain="ews"), exchange(3)]
    selection = thread.select(history, limits=STANDARD_LIMITS,
                              dataset_release_id="r1")
    assert [e["exchange_id"] for e in selection.exchanges] == ["e1", "e3"]
    assert selection.dropped_out_of_domain == 1


def test_an_exchange_from_another_release_is_refused():
    history = [exchange(1), exchange(2, release="r2"), exchange(3)]
    selection = thread.select(history, limits=STANDARD_LIMITS,
                              dataset_release_id="r1")
    assert selection.dropped_out_of_domain == 1
    assert all(e["exchange_id"] != "e2" for e in selection.exchanges)


def test_a_referral_is_remembered_as_a_referral():
    """Section 12: a referral exchange must not read as a completed analysis,
    because the NEXT question is answered against this memory."""
    history = [exchange(1, kind="referral")]
    rendered = thread.select(history, limits=STANDARD_LIMITS,
                             dataset_release_id="r1").exchanges[0]
    assert rendered["kind"] == "referral"
    assert "REFERRED" in rendered["answer"]
    assert "was not answered here" in rendered["answer"]


def test_a_clarification_and_a_stop_are_remembered_as_what_they_were():
    for kind, marker in (("clarification", "still open"),
                         ("stop", "stopped without an answer")):
        rendered = thread.select([exchange(1, kind=kind)],
                                 limits=STANDARD_LIMITS,
                                 dataset_release_id="r1").exchanges[0]
        assert marker in rendered["answer"]


# ============================================== the summary

def test_a_stale_summary_cannot_overwrite_a_newer_one():
    """Section 7.9: version checks prevent a stale summary overwriting a newer
    one."""
    state = thread.ThreadState(thread_id="t", dataset_release_id="r1")
    state.apply_summary(ThreadSummary(thread_id="t",
                                      summary_through_exchange_id="e5",
                                      current_topic="newer", version=3))
    state.apply_summary(ThreadSummary(thread_id="t",
                                      summary_through_exchange_id="e2",
                                      current_topic="older", version=2))
    assert state.summary.current_topic == "newer"


def test_unsummarized_exchanges_are_flagged_for_inclusion_next_time():
    state = thread.ThreadState(thread_id="t", dataset_release_id="r1")
    state.apply_summary(ThreadSummary(
        thread_id="t", summary_through_exchange_id="e1",
        current_topic="x", version=1, unsummarized_exchange_ids=["e2"]))
    summary, _selection = state.context_for(limits=STANDARD_LIMITS)
    assert "not summarised" in summary["note"]


def test_a_failed_summary_call_keeps_the_previous_one(runtime_factory,
                                                      sonnet_answers):
    """Section 7.9: a failed summary does not erase a completed answer."""
    from backend.cockpit_agentic import service

    from backend.cockpit_agentic import sonnet as sonnet_mod
    from backend.cockpit_agentic.ledger import Ledger, Prices

    previous = ThreadSummary(thread_id="t", summary_through_exchange_id="e1",
                             current_topic="ECL history", version=4)
    broken = FakeProvider(raises=RuntimeError("the summariser is down"))
    kept = sonnet_mod.update_summary(
        previous, Exchange(exchange_id="e2", question="q", answer="a"),
        broken, Ledger(prices=Prices()))
    assert kept.current_topic == "ECL history"
    assert kept.version == 4
    assert "e2" in kept.unsummarized_exchange_ids


def test_the_summary_only_cites_results_that_exist(runtime_factory):
    from backend.cockpit_agentic import sonnet as sonnet_mod
    from backend.cockpit_agentic.ledger import Ledger, Prices

    provider = FakeProvider(structured_script=[{
        "current_topic": "ECL",
        "authorized_references": ["art-real", "art-invented"]}])
    updated = sonnet_mod.update_summary(
        None, Exchange(exchange_id="e1", question="q", answer="a",
                       fact_ids=["art-real"]),
        provider, Ledger(prices=Prices()))
    assert updated.authorized_references == ["art-real"]


# ============================================== the API

@pytest.fixture()
def api(lake, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.main import app
    from backend.cockpit_agentic import service

    monkeypatch.setattr(service, "DEFAULT_RELEASE", "test-runtime-20q")
    return TestClient(app)


HEADERS = {"X-IPM-User-Id": "1", "X-IPM-Role": "ANALYST"}
API = "/api/v1/cockpit"


def test_the_diagnostics_say_what_this_build_is(api):
    body = api.get(f"{API}/diagnostics", headers=HEADERS).json()
    assert body["cockpit_agentic_v3"] is True
    assert body["domain_id"] == "corporate_cockpit"
    assert body["functionality_routes"]["verified"] is True
    # Whether the isolated sandbox is available depends on what namespaces the
    # host grants, so the diagnostics must report what was MEASURED -- and an
    # operator reading this badge must be able to see which it was.
    from backend.cockpit_agentic import pysandbox as py_mod
    python = body["python_execution"]
    assert python["available"] is py_mod.probe().available
    if python["available"]:
        assert python["strategy"]
        assert python["guarantees"]["network_denied"]
        assert python["guarantees"]["privileges_dropped"]
    else:
        assert python["reason"]


def test_the_diagnostics_report_which_guardrails_are_raised(api):
    """A demonstration run under raised limits must not read as if it were run
    under the specification's own."""
    body = api.get(f"{API}/diagnostics", headers=HEADERS).json()
    assert "no override at any level" in body["guardrails_note"]
    assert body["standard_limits"]["execution_submissions"] == 5
    assert body["standard_limits"]["analysis_rounds"] == 3


def test_the_diagnostics_say_the_cost_ceiling_is_not_a_control(api):
    body = api.get(f"{API}/diagnostics", headers=HEADERS).json()
    assert body["cost_enforced"] is False
    assert "not a control" in body["cost_note"]


def test_the_catalogue_endpoint_is_scoped(api):
    body = api.get(f"{API}/catalogue",
                   params={"dataset_release_id": "test-runtime-20q"},
                   headers=HEADERS).json()
    assert body["domain_id"] == "corporate_cockpit"
    assert "cockpit_facility_quarter" in body["relations"]
    for foreign in ("ews_alerts", "scorecard_runs", "stress_scenarios"):
        assert foreign not in body["relations"]
    assert body["summary"]["ratios"] == 40


def test_an_unknown_mode_is_refused_rather_than_defaulted(api):
    response = api.post(f"{API}/ask",
                        json={"question": "x", "mode": "turbo"},
                        headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unknown_mode"


def test_deep_mode_is_never_selected_silently(api):
    """Section 9.6: no automatic Deep upgrade."""
    from backend.cockpit_agentic import default_mode

    assert default_mode() == "standard"


def test_without_a_credential_the_api_says_so_and_substitutes_nothing(api):
    """Sections 17 and 18, through the real endpoint."""
    body = api.post(f"{API}/ask",
                    json={"question": "How much did ECL change?",
                          "dataset_release_id": "test-runtime-20q"},
                    headers=HEADERS).json()
    assert body["status"] == st.PROVIDER_ERROR
    assert body["answer"]["kind"] == "stop"
    assert "no deterministic stand-in" in body["answer"]["narrative"]
    assert body["results"] == []
    assert body["answer"]["tables"] == [] and body["answer"]["charts"] == []


def test_cancel_does_not_claim_to_reverse_charges(api):
    body = api.post(f"{API}/cancel/req-anything", headers=HEADERS).json()
    assert body["cancelled"] is True
    assert "not reversed" in body["note"]
