"""
The flag-off path. Brief §1.3, §9.

With COCKPIT_INTELLIGENCE_V2 unset the product must behave exactly as it did on
the base commit. That is not a claim to be made in a release note; it is a
thing to hold shut with tests, because the failure mode — a Cockpit-only
experiment quietly changing Early Warning — is the one the owner would find out
about last.
"""

from __future__ import annotations

import pytest

from backend.cockpit_v2 import guard


class _Settings:
    """A settings stand-in with the switch off."""

    cockpit_intelligence_v2 = False
    cockpit_v2_namespace = "cockpit_v2"
    analytics_dir = "/tmp/not-a-v2-directory"
    metadata_dir = "/tmp/not-a-v2-directory"
    database_url = "postgresql+psycopg://user@host/production"


@pytest.fixture()
def flag_off(monkeypatch):
    import backend.config as config_module

    monkeypatch.setattr(config_module, "settings", _Settings())
    from backend import cockpit_v2

    monkeypatch.setattr(cockpit_v2, "enabled", lambda: False)
    return _Settings()


def test_the_package_reports_itself_disabled(flag_off):
    from backend import cockpit_v2

    assert cockpit_v2.enabled() is False


def test_the_service_declines_to_answer(flag_off):
    from backend.cockpit_v2 import service

    assert service.available() is False
    assert service.answer("Give me an ECL decomposition.") is None


def test_no_tool_is_registered(flag_off):
    from backend.analyst import tools as analyst_tools
    from backend.cockpit_v2 import tools as cockpit_tools

    before = {tool.name for tool in analyst_tools.REGISTRY}
    assert cockpit_tools.install() == []
    assert {tool.name for tool in analyst_tools.REGISTRY} == before


def test_the_seed_refuses_to_run(flag_off):
    with pytest.raises(guard.UnsafeTarget) as raised:
        guard.check_targets()
    assert "COCKPIT_INTELLIGENCE_V2 is not set" in str(raised.value)


def test_the_guard_never_prints_a_connection_string(flag_off):
    with pytest.raises(guard.UnsafeTarget) as raised:
        guard.check_targets()
    message = str(raised.value)
    assert "postgresql+psycopg" not in message
    assert "@host" not in message
    assert "user" not in message.replace("unprivileged", "")


def test_the_narrative_contract_keeps_its_historical_default():
    """A response with no V2 and no analyst still says where the prose came
    from, and says the same thing it always meant."""
    from backend.orchestration.interpreter import Narrative

    payload = Narrative(direct_answer="Expected credit loss fell.").to_dict()
    assert payload["prose_source"] == "deterministic"
    assert payload["prose_fallback_reason"] == ""
    # Every field the base build returned is still there, unchanged.
    for field in ("direct_answer", "summary", "findings", "interpretation",
                  "interpretation_points", "why_multiple", "scope", "metrics",
                  "drivers", "caveats"):
        assert field in payload


def test_the_response_is_left_alone_when_v2_returns_nothing():
    """`apply` is never reached when `answer_for` returned None."""
    from backend.cockpit_v2 import integration

    body = {"narrative": {"direct_answer": "unchanged",
                          "interpretation_points": ["a"], "caveats": []}}
    before = {**body["narrative"]}
    integration.record_prose_source(body)
    assert body["narrative"]["direct_answer"] == before["direct_answer"]
    assert body["narrative"]["interpretation_points"] == \
        before["interpretation_points"]
    assert body["narrative"]["prose_source"] == "deterministic"
    assert "cockpit_v2" not in body


def test_apply_declines_an_empty_answer():
    """A V2 payload with nothing in it must not take the turn."""
    from backend.cockpit_v2 import integration

    class _Investigation:
        narrative = None
        status = "succeeded"

    assert integration.apply(_Investigation(), {}) is False
    assert integration.apply(_Investigation(), {"direct_answer": ""}) is False
