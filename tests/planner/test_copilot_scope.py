"""The Copilot's boundary, tested where it is enforced rather than prompted.

Two claims are under test and they fail in different ways.

The TOOL boundary fails loudly: a model asks for a capability the Copilot does
not have and the registry refuses it. These tests call the gate directly with
tool ids from the rest of the platform, because a boundary that only holds for
the ids somebody remembered to think about is not a boundary.

The TOPIC boundary fails quietly, and in the more dangerous direction. A
classifier that refuses too much would refuse the demo project by its own
name, and nobody would file that as a security bug — they would file it as
"the assistant is useless". Half of these tests are about not refusing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from tests.conftest import database_available


@dataclass
class Principal:
    user_id: int
    role: str = "ANALYST"


# ------------------------------------------------------------ the tool gate


def test_the_copilot_may_call_only_planner_tools():
    from backend.agentic import tools as reg
    from backend.planner import copilot

    for tool_id in copilot.ALLOWED_TOOLS:
        assert reg.tool(tool_id) is not None, f"{tool_id} is not registered"
        assert tool_id.startswith("planner_")

    foreign = [t.tool_id for t in reg.TOOLS
               if not t.tool_id.startswith("planner_")]
    assert foreign, "the platform has non-planner tools to be refused"
    for tool_id in foreign:
        assert not copilot.agent().may_use(tool_id)


@pytest.mark.parametrize("tool_id", [
    "run_analysis", "plan_analysis", "catalogue_lookup", "source_profile",
    "run_scenario", "numerical_kernel", "run_certified_method",
    "draft_investigation", "evidence_package", "pre_screen",
])
def test_a_platform_tool_is_refused_with_a_reason(tool_id):
    from backend.agentic import tools as reg
    from backend.planner import copilot

    call = reg.check(copilot.agent(), tool_id, {})
    assert not call.allowed
    assert "not permitted" in call.reason
    # The refusal is a recorded Call, not an exception nobody can review.
    assert call.agent_id == copilot.AGENT_ID


def test_an_invented_tool_is_refused():
    from backend.agentic import tools as reg
    from backend.planner import copilot

    call = reg.check(copilot.agent(), "planner_delete_everything", {})
    assert not call.allowed
    assert "not a registered CreditProbe tool" in call.reason


def test_the_copilot_reads_no_governed_data_domain():
    from backend.planner import copilot

    assert copilot.ALLOWED_DOMAINS == ()
    for domain in ("retail", "corporate", "ifrs9", "scorecard", "collateral"):
        assert not copilot.agent().may_read(domain)


def test_the_forbidden_planner_actions_still_have_no_tool():
    """§4's prohibition is enforced by absence, and stays that way.

    The Copilot is a new caller with a wider job than the old assistant. If
    building it had added a tool that completes a task or moves a date, this
    test is where that shows up.
    """
    from backend.agentic import tools as reg
    from backend.planner import copilot

    for forbidden in ("complete_task", "change_due_date", "assign_owner",
                      "close_risk", "sign_off_milestone"):
        assert reg.tool(forbidden) is None
        assert not copilot.agent().may_use(forbidden)
    assert "assign_owner" in reg.NO_TOOL_EXISTS


def test_every_allowed_tool_is_actually_wired():
    """A capability advertised and not wired fails when somebody uses it."""
    if not database_available():
        pytest.skip("handlers close over a real session")
    from backend.db.engine import get_session
    from backend.planner import copilot

    with get_session() as session:
        wired = copilot.handlers(session)
    assert sorted(wired) == sorted(copilot.ALLOWED_TOOLS)


def test_the_catalogue_describes_tools_once():
    from backend.agentic import tools as reg
    from backend.planner import copilot

    shown = copilot.catalogue()
    assert len(shown["tools"]) == len(copilot.ALLOWED_TOOLS)
    for entry in shown["tools"]:
        assert entry["purpose"] == reg.require(entry["tool_id"]).purpose


# ---------------------------------------------------------- the topic gate


@pytest.mark.parametrize("question,area", [
    ("What is the ECL for stage 2 retail?", "ifrs9"),
    ("Show me the IFRS 9 staging movement since December.", "ifrs9"),
    ("What is the gini of the application scorecard?", "scorecard"),
    ("Run a PSI on the score bands.", "scorecard"),
    ("Which borrowers are on the watchlist?", "early_warning"),
    ("Has anyone breached a covenant this quarter?", "early_warning"),
    ("Show me the ownership structure of the group.", "borrower360"),
    ("Publish a dataset to the data catalogue.", "data_builder"),
    ("Open the CRO lens.", "lenses"),
    ("Generate the committee pack.", "playbook"),
    ("What is our NPL ratio?", "portfolio"),
    ("Should we approve this facility?", "corporate"),
])
def test_another_module_s_question_is_refused_and_redirected(question, area):
    from backend.planner import scope

    found = scope.classify(question, names=[])
    assert not found.in_scope
    assert found.area == area
    # The refusal says where the answer lives and what this assistant is for.
    assert found.label.lower() in found.message.lower()
    assert "project delivery" in found.message


@pytest.mark.parametrize("question", [
    "What is the status of the Retail Application Scorecard Redevelopment?",
    "Is the scorecard redevelopment project on track?",
    "Who owns the model build milestone?",
    "What is overdue this week?",
    "Move the data extraction task to next Friday.",
    "Add a milestone called Independent Validation.",
    "Which tasks are on the critical path?",
    "Who has not given me an update?",
])
def test_a_delivery_question_is_answered(question):
    from backend.planner import scope

    names = ["Retail Application Scorecard Redevelopment", "Model build",
             "Data extraction", "Independent Validation"]
    assert scope.classify(question, names=names).in_scope


def test_a_project_named_after_another_module_is_still_a_project():
    """The trap the demo project sets, on purpose.

    "Retail Application Scorecard Redevelopment" contains three words that
    each belong to another part of the bank. A classifier that matched words
    would refuse to discuss the one project the Copilot demo is built on.
    """
    from backend.planner import scope

    names = ["Retail Application Scorecard Redevelopment"]
    delivery = scope.classify(
        "How is the scorecard redevelopment going?", names=names)
    assert delivery.in_scope
    assert delivery.anchors == names

    # The same project in reach, asking the other module's question. Naming a
    # project does not licence a metric question about it: `PSI` sits outside
    # the name, so it is still the Scorecard Validation module's question.
    analysis = scope.classify(
        "What is the PSI of the retail application scorecard?", names=names)
    assert not analysis.in_scope
    assert analysis.area == "scorecard"
    assert analysis.anchors == names  # the project was recognised anyway


def test_naming_a_project_does_not_licence_another_module_s_question():
    """Every foreign phrase is checked, not just the first one.

    A project called "IFRS 9 Model Redevelopment" makes "IFRS 9" its name. It
    does not make "what is the ECL" a delivery question, and a classifier that
    stopped at the first match per area would have decided it was.
    """
    from backend.planner import scope

    names = ["IFRS 9 Model Redevelopment"]
    assert scope.classify("Is the IFRS 9 Model Redevelopment on track?",
                          names=names).in_scope
    refused = scope.classify(
        "What is the ECL under the IFRS 9 Model Redevelopment?", names=names)
    assert not refused.in_scope
    assert refused.matched == "ecl"


def test_an_empty_message_is_not_refused():
    from backend.planner import scope

    assert scope.classify("", names=[]).in_scope


def test_a_name_nobody_can_see_does_not_anchor():
    """Anchoring must not become a way to confirm a project exists.

    The names come from `names_in_reach`, which reads through the participant
    list. Somebody who cannot see the project gets an empty list, so their
    question is classified as though it did not exist — which is the same
    answer they get everywhere else in the planner.
    """
    from backend.planner import scope

    hidden = "Retail Application Scorecard Redevelopment"
    assert scope.classify(f"How is {hidden} going?", names=[hidden]).in_scope
    assert not scope.classify(f"What is the gini on {hidden}?",
                              names=[]).in_scope


def test_scope_reads_names_through_the_participant_list():
    if not database_available():
        pytest.skip("needs a real database")
    from backend.db.engine import get_session
    from backend.db.models import User
    from backend.planner import draft, scope

    tag = uuid.uuid4().hex[:8]
    with get_session() as session:
        rows = {}
        for name in ("insider", "outsider"):
            row = User(username=f"scope-{name}-{tag}", password_hash="x",
                       role="ANALYST", first_name=name.title(),
                       last_name="Test",
                       email=f"{name}-{tag}@example.invalid")
            session.add(row)
            session.flush()
            rows[name] = int(row.id)
        session.commit()

        mine = Principal(rows["insider"])
        plan = draft.empty()
        plan["overview"] = {"name": f"Scorecard Redevelopment {tag}",
                            "code": f"SCR{tag[:5].upper()}",
                            "description": "x", "objective": "y"}
        plan["governance"] = {
            "sponsor_id": rows["insider"], "manager_id": rows["insider"],
            "owner_id": rows["insider"], "escalation_id": rows["insider"],
            "priority": "MEDIUM", "status": "ACTIVE",
            "start_date": "2026-01-01", "target_end_date": "2026-12-31",
            "reporting_cadence": "WEEKLY"}
        plan["milestones"] = [{"code": "M01", "name": "Discovery",
                               "owner_id": rows["insider"],
                               "start_date": "2026-01-01",
                               "target_date": "2026-03-01"}]
        plan["tasks"] = [{"code": "M01-T01", "milestone_code": "M01",
                          "title": "Extract data", "description": "d",
                          "owner_id": rows["insider"],
                          "due_date": "2026-02-01"}]
        row = draft.create(session, mine, plan=plan)
        session.commit()
        draft.publish(session, mine, row.key)
        session.commit()

        seen = scope.names_in_reach(session, mine)
        assert any(f"Scorecard Redevelopment {tag}" == n for n in seen)
        assert scope.names_in_reach(
            session, Principal(rows["outsider"])) == []


# ------------------------------------------------------- publish is an act


def test_there_is_no_tool_that_publishes_a_project():
    """§21 Level 4: creating a project is a person's act, so no tool does it.

    The Copilot builds the plan and shows it in full. Making it real happens
    on a route somebody calls. Enforced by the capability not existing rather
    than by a permission check being written correctly — the same way the
    planner's other prohibitions are enforced.
    """
    from backend.agentic import tools as reg
    from backend.planner import copilot

    for tool in reg.TOOLS:
        assert "publish" not in tool.tool_id or not tool.writes
    assert reg.tool("planner_draft_publish") is None
    assert "publish_project" in reg.NO_TOOL_EXISTS
    assert not any("publish" in t for t in copilot.ALLOWED_TOOLS)


def test_publishing_needs_the_person_to_say_yes():
    if not database_available():
        pytest.skip("needs a real database")
    from backend.db.engine import get_session
    from backend.planner import copilot

    with get_session() as session:
        with pytest.raises(copilot.NotConfirmed):
            copilot.confirm_publish(session, Principal(1), "anything",
                                    confirm=False)
        # Nor does a model's paraphrase of agreement count.
        for looks_like_yes in ("maybe", "go on then", "", None):
            with pytest.raises(copilot.NotConfirmed):
                copilot.confirm_publish(session, Principal(1), "anything",
                                        confirm=looks_like_yes)


def test_everything_the_copilot_writes_is_marked_as_chat():
    """§41: a change somebody typed and a change they asked for are different
    events forever, and the audit row is where that distinction lives."""
    from backend.models.planner import SOURCE_AI_CHAT, SOURCES
    from backend.planner import copilot

    assert copilot._source() == SOURCE_AI_CHAT
    assert SOURCE_AI_CHAT in SOURCES


# ------------------------------- a task named after the thing it produces


def test_a_task_named_after_a_metric_does_not_licence_asking_for_it():
    """The hole that containment opens, and the shape that closes it.

    Containment forgives a foreign phrase sitting inside something the plan
    is called — that is what lets somebody discuss a programme called "Retail
    Application Scorecard Redevelopment" without being sent elsewhere. But
    real programmes name their tasks after the metrics they produce, and a
    task called "Population stability index review" would then make "what is
    the population stability index?" a delivery question: one the planner
    cannot answer, asked of the one part of the product with no data to
    answer it with.

    A phrase used as a NAME is forgiven. A phrase being asked FOR is not.
    """
    from backend.planner import scope

    names = ["Population stability index review",
             "Retail Application Scorecard Redevelopment"]

    # Talking about the work by its name: still the Copilot's question.
    for asked in ("How is the Population stability index review going?",
                  "Who owns the Population stability index review?",
                  "Move the Population stability index review to Friday.",
                  "How is the scorecard redevelopment going?"):
        assert scope.classify(asked, names=names).in_scope, asked

    # Asking for the number itself: not the Copilot's question, however the
    # plan happens to have named its work.
    for asked in ("What is the population stability index?",
                  "What is the PSI of the application scorecard?",
                  "Show me the population stability index.",
                  "Calculate the population stability index for me."):
        refused = scope.classify(asked, names=names)
        assert not refused.in_scope, asked
        assert "Scorecard Validation" in refused.message, asked


def test_the_value_cue_does_not_refuse_ordinary_delivery_questions():
    """"What is overdue?" asks for a value too, and it is ours.

    The cue only ever promotes a phrase that already belongs to another
    module. A sentence with nothing foreign in it is never refused by it.
    """
    from backend.planner import scope

    for asked in ("What is overdue here?",
                  "What is on the critical path?",
                  "How many tasks are late?",
                  "Show me the milestones that are at risk.",
                  "What is still missing from this plan?"):
        assert scope.classify(asked, names=[]).in_scope, asked
