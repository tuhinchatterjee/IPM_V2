"""
§21, §22, §72 — autonomy and human approval.

The principle these tests exist to hold:

    HUMANS MUST APPROVE MATERIAL SIDE EFFECTS.

Two halves, and both matter. The autonomy half is pure and runs anywhere: no
agent's level grants a Level 4 action, and no tool in the registry performs one
— a missing function cannot be called, which is a stronger guarantee than a
permission that could be widened. The approval half needs the database, because
"a gate cannot be decided twice" is a property of a stored record.
"""

from __future__ import annotations

import pytest

from backend.agentic import autonomy, registry, tools

# ---------------------------------------------------------------------------
# §21 — what autonomy grants, and what it never does
# ---------------------------------------------------------------------------


def test_no_agent_is_shipped_above_draft():
    """§21 Level 3 exists so an administrator CAN pre-approve something, not so
    the product arrives already permitted to act."""
    assert all(agent.autonomy_level <= autonomy.DRAFT
               for agent in registry.AGENTS)


@pytest.mark.parametrize(
    "action_id",
    [a.action_id for a in autonomy.ACTIONS if a.level >= autonomy.MATERIAL])
def test_no_agent_may_perform_a_material_action(action_id):
    """§21: 'Level 4 requires explicit human approval.' Checked against every
    agent and every material action rather than a sampled pair, because one
    agent quietly defined at level 4 is the whole guarantee gone."""
    for agent in registry.AGENTS:
        verdict = autonomy.may(agent, action_id)
        assert verdict.allowed is False
        assert verdict.needs_approval is True
        assert verdict.approver_role


@pytest.mark.parametrize(
    "action_id",
    [a.action_id for a in autonomy.ACTIONS if a.level >= autonomy.MATERIAL])
def test_no_tool_exists_that_performs_a_material_action(action_id):
    """The stronger half of the guarantee. A permission can be widened by
    somebody editing a policy; a function that was never written cannot be
    called by anybody."""
    assert action_id in tools.NO_TOOL_EXISTS
    assert tools.tool(action_id) is None


def test_the_generally_dangerous_capabilities_have_no_tool_either():
    """§14: no arbitrary SQL, no arbitrary Python, no unrestricted network, no
    filesystem outside governed services."""
    for name in ("execute_sql", "execute_python", "fetch_url", "read_file"):
        assert name in tools.NO_TOOL_EXISTS
        assert tools.tool(name) is None


def test_an_undefined_action_is_treated_as_material():
    """The safe direction to fail. An action nobody defined is one nobody
    reviewed, so it is refused and escalated rather than waved through."""
    verdict = autonomy.may(registry.CHIEF_ORCHESTRATOR, "wire_the_money")
    assert verdict.allowed is False
    assert verdict.needs_approval is True
    assert verdict.level == autonomy.MATERIAL


class _AtLevelThree:
    """A stand-in, because no SHIPPED agent operates at Level 3 — which is the
    point of the test above. The rule being checked here is the policy rule,
    and it has to hold for the agent an administrator promotes tomorrow."""

    agent_id = "hypothetical"
    business_name = "A promoted specialist"
    autonomy_level = autonomy.EXECUTE_PREAPPROVED
    human_approval_requirements: tuple[str, ...] = ()


def test_pre_approved_without_a_policy_is_approved_by_nobody():
    """§21 Level 3. The product ships with an empty pre-approved list, and an
    empty list must mean 'ask', not 'go ahead'."""
    agent = _AtLevelThree()
    without = autonomy.may(agent, "refresh_attention",
                           policy=autonomy.policy_defaults())
    assert without.allowed is False
    assert without.needs_approval is True

    with_policy = autonomy.may(
        agent, "refresh_attention",
        policy={"pre_approved": ["refresh_attention"]})
    assert with_policy.allowed is True


def test_nothing_is_pre_approved_as_shipped():
    assert autonomy.policy_defaults()["pre_approved"] == []


def test_an_agents_own_definition_can_narrow_its_autonomy_further():
    """An agent that names an action in `human_approval_requirements` must be
    refused it even where its level would otherwise allow it."""
    agent = next((a for a in registry.AGENTS
                  if a.human_approval_requirements), None)
    assert agent is not None, "no agent names a human approval requirement"
    named = agent.human_approval_requirements[0]
    assert autonomy.may(agent, named).allowed is False


def test_a_drafting_action_is_within_a_specialists_autonomy():
    """The gate must not be so wide that nothing works: proposing a case is
    exactly what a specialist is for."""
    agent = next(a for a in registry.AGENTS
                 if a.autonomy_level >= autonomy.DRAFT)
    assert autonomy.may(agent, "draft_risk_case").allowed is True


# ---------------------------------------------------------------------------
# §22 — the gate an approver sees
# ---------------------------------------------------------------------------


def _gate():
    return autonomy.gate_for(
        registry.CHIEF_ORCHESTRATOR, "send_workflow",
        title="Ask the Contracting relationship team to review 4 borrowers",
        reason="Four borrowers contributed 61% of the sector's ECL increase.",
        scope="Contracting · Q2 2026",
        proposal={"items": 4, "due_days": 5},
        evidence={"analysis_run_id": 901, "cases": [11, 12, 13, 14]},
        objects=[{"type": "risk_case", "id": 11, "label": "Al Rajhi Contracting"}])


def test_a_gate_states_what_a_person_is_agreeing_to():
    """§22: the consequence in the approver's own terms, not the action id."""
    shown = _gate().to_dict()
    assert shown["consequence"]
    assert shown["title"]
    assert shown["reason"]
    assert shown["risk"]
    assert shown["reversibility"]
    assert shown["objects_affected"]


def test_a_gate_offers_exactly_the_five_actions():
    """§22 names them. A sixth invented by the UI, or a missing OPEN TRACE,
    would be a different decision to the one the brief describes."""
    assert _gate().to_dict()["actions"] == [
        "APPROVE", "REJECT", "REQUEST CHANGE", "OPEN EVIDENCE", "OPEN TRACE"]


def test_a_gate_carries_the_evidence_it_was_raised_on():
    """OPEN EVIDENCE has to open something. A gate whose evidence is empty is
    one an approver can only accept on trust."""
    shown = _gate().to_dict()
    assert shown["evidence"]["analysis_run_id"] == 901


def test_an_unknown_action_produces_the_most_cautious_gate():
    gate = autonomy.gate_for(registry.CHIEF_ORCHESTRATOR, "wire_the_money",
                             title="x", reason="y")
    assert gate.risk == "high"
    assert gate.reversibility == "irreversible"
    assert gate.approver_role == "ADMIN"


# ---------------------------------------------------------------------------
# The stored decision. §22, §72.
# ---------------------------------------------------------------------------

from tests.conftest import database_available  # noqa: E402

db = pytest.mark.skipif(not database_available(),
                        reason="PostgreSQL is not reachable")

if database_available():
    from sqlalchemy import text  # noqa: E402

    from backend.agentic import approvals  # noqa: E402
    from backend.db.engine import SessionLocal  # noqa: E402


@pytest.fixture
def session():
    s = SessionLocal()
    s.execute(text("DELETE FROM agent_approvals"))
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        s.execute(text("DELETE FROM agent_approvals"))
        s.commit()
        s.close()


@db
def test_an_action_waits_in_the_queue_until_somebody_decides(session):
    row = approvals.open_gate(session, _gate())
    session.commit()
    assert row.status == approvals.PENDING
    assert approvals.approved(row) is False
    assert row.id in [r.id for r in approvals.pending(session)]


@db
def test_the_queue_shows_a_role_only_what_it_can_actually_decide(session):
    """A queue full of items somebody cannot act on trains them to ignore the
    queue."""
    approvals.open_gate(session, autonomy.gate_for(
        registry.CHIEF_ORCHESTRATOR, "certify_method", title="Certify",
        reason="r"))          # ADMIN
    approvals.open_gate(session, _gate())   # ANALYST
    session.commit()
    assert len(approvals.pending(session, role="ADMIN")) == 2
    assert len(approvals.pending(session, role="ANALYST")) == 1


@db
def test_a_role_below_the_gate_cannot_decide_it(session):
    row = approvals.open_gate(session, autonomy.gate_for(
        registry.CHIEF_ORCHESTRATOR, "certify_method",
        title="Certify the ECL attribution method", reason="r"))
    session.commit()
    with pytest.raises(approvals.NotAuthorised):
        approvals.decide(session, row, decision=approvals.APPROVED,
                         user_id=1, role="ANALYST")
    assert row.status == approvals.PENDING


@db
def test_approving_records_who_decided_and_when(session):
    row = approvals.open_gate(session, _gate())
    approvals.decide(session, row, decision=approvals.APPROVED, user_id=7,
                     role="ADMIN", note="Agreed, send it.")
    session.commit()
    assert approvals.approved(row) is True
    assert row.decided_by == 7
    assert row.decided_at is not None
    assert row.decision_note == "Agreed, send it."


@db
def test_a_gate_cannot_be_decided_twice(session):
    """An approval that could be flipped afterwards is a record of an opinion,
    not of a decision — and the trail would not show which one the action was
    taken under."""
    row = approvals.open_gate(session, _gate())
    approvals.decide(session, row, decision=approvals.REJECTED, user_id=7,
                     role="ADMIN")
    session.commit()
    with pytest.raises(approvals.AlreadyDecided):
        approvals.decide(session, row, decision=approvals.APPROVED,
                         user_id=7, role="ADMIN")
    assert row.status == approvals.REJECTED


@db
def test_a_rejected_or_changed_gate_does_not_permit_the_action(session):
    for decision in (approvals.REJECTED, approvals.CHANGES_REQUESTED):
        row = approvals.open_gate(session, _gate())
        approvals.decide(session, row, decision=decision, user_id=7,
                         role="ADMIN")
        session.commit()
        assert approvals.approved(row) is False


@db
def test_a_gate_that_was_never_opened_permits_nothing(session):
    """`approved(None)` is the case that matters: code that forgets to open a
    gate must not thereby be allowed to act."""
    assert approvals.approved(None) is False


@db
def test_an_invalid_decision_is_refused(session):
    row = approvals.open_gate(session, _gate())
    with pytest.raises(ValueError):
        approvals.decide(session, row, decision="maybe", user_id=7,
                         role="ADMIN")


@db
def test_the_approver_view_says_what_the_agent_wanted_and_why(session):
    row = approvals.open_gate(session, _gate(), run_id=None)
    session.commit()
    shown = approvals.view(row)
    assert shown["consequence"]
    assert shown["reason"]
    assert shown["evidence"]["analysis_run_id"] == 901
    assert shown["status"] == approvals.PENDING
