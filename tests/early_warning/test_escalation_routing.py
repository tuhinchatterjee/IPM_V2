"""
Does an escalation go where the matrix says, or where the caller says?

The matrix already decided the rung, the urgency and the parallel
notifications, and the endpoint applied all three — and then still refused
the request unless the CALLER named a recipient, because nothing could turn
"Head of Credit Risk" into somebody's inbox. So an escalation either carried
a hard-coded demo user, which is not a control, or could not be sent.

A rung now addresses a team named for it, derived from the matrix's own role
names so the two cannot drift. A deployment fills the team; what it cannot
choose is which rungs exist.
"""

from __future__ import annotations

import pytest

from backend.early_warning import escalation as esc


def test_every_rung_and_route_has_a_team_name():
    required = esc.required_teams()
    assert len(required) == len(esc.LADDER) + len(esc.SPECIALIST_ROUTES)
    for entry in required:
        assert entry["team"].startswith("ews_")
        assert entry["role"]
        assert " " not in entry["team"]


def test_the_team_name_comes_from_the_role_not_a_literal():
    assert esc.team_slug("L3") == "ews_head_of_credit_risk"
    assert esc.team_slug("S4") == "ews_legal"
    assert esc.team_slug("S1") == "ews_compliance_financial_crime"


def test_a_code_nobody_defines_still_yields_a_name():
    """A rung added to the matrix and not here must not crash a routing."""
    assert esc.team_slug("L9") == "ews_l9"
    assert esc.role_of("L9") == "L9"


def test_the_role_behind_a_code_is_the_matrix_s_own():
    assert esc.role_of("L3") == "Head of Credit Risk"
    assert esc.role_of("S2") == "Special Assets / Remedial"


def test_team_names_are_unique():
    names = [entry["team"] for entry in esc.required_teams()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("band,exposure", [
    ("VERY_HIGH", 3675.0), ("VERY_HIGH", 20.0),
    ("HIGH", 500.0), ("HIGH", 10.0), ("MEDIUM", 200.0), ("LOW", 5.0),
])
def test_every_route_the_matrix_can_produce_names_a_team(band, exposure):
    route = esc.route_for(band, exposure)
    for code in list(route.get("escalated_to") or []) + list(
            route.get("notified") or []):
        assert esc.team_slug(code), code
        assert esc.role_of(code) != "", code


def test_seeding_the_teams_is_idempotent():
    from backend.config import settings

    if not settings.has_database:
        pytest.skip("No database configured.")
    from backend.db.engine import get_session
    from backend.early_warning import case_bridge

    with get_session() as session:
        first = case_bridge.ensure_escalation_teams(session)
        session.commit()
    with get_session() as session:
        second = case_bridge.ensure_escalation_teams(session)
        session.commit()
    assert first == second
    assert len(first) == len(esc.required_teams())
