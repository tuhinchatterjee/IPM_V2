"""Decisions, actions, the Planner bridge, the sweep and the comparison.

The half of the lifecycle that happens after a pack is read: what the committee
decided, who has to do something, where that work actually lives, who gets
chased, and what changed since last time.

Time is frozen everywhere it matters. `monitor.sweep` takes `now`, so these
tests put the clock at a given number of days before a meeting and assert what
gets sent — rather than seeding data at an offset from the real clock and
hoping the suite does not run across midnight.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.playbook import access, actions, compare, generation, monitor
from backend.playbook import service as pb

pytestmark = pytest.mark.usefixtures("session")


# =============================================================== decisions


def test_a_decision_request_has_to_say_what_is_being_decided(session, pack,
                                                             actors):
    with pytest.raises(pb.InvalidPlaybook) as e:
        actions.create_decision(session, pack["id"], actors["owner"],
                                title="Overlay", question="  ")
    assert "cannot decide a heading" in str(e.value)


def test_a_decision_is_drafted_and_decided_separately(session, pack, actors):
    made = actions.create_decision(
        session, pack["id"], actors["owner"],
        title="Release the retail overlay",
        question="Should the SAR 40m retail overlay be released in full?",
        recommendation="Release half and review in Q3.")
    assert made["status"] == "DRAFT"
    assert made["decided"] is False
    assert made["reference"].startswith(pack["code"])

    with pytest.raises(pb.InvalidPlaybook) as e:
        actions.update_decision(session, made["id"], actors["owner"],
                                status="APPROVED")
    assert "separate operation" in str(e.value)

    decided = actions.decide(session, made["id"], actors["approver"],
                             outcome="APPROVED",
                             decision_text="Released in full.")
    assert decided["decided"] is True
    assert decided["decided_by"] == actors["approver"].user_id
    assert decided["decided_at"]


def test_only_an_approver_records_what_the_committee_decided(session, pack,
                                                             actors):
    made = actions.create_decision(session, pack["id"], actors["owner"],
                                   title="A question", question="Well?")
    with pytest.raises(access.PackDenied) as e:
        actions.decide(session, made["id"], actors["author"],
                       outcome="APPROVED")
    assert "approver access" in str(e.value)


def test_an_assistant_cannot_record_a_decision(session, pack, actors):
    made = actions.create_decision(session, pack["id"], actors["owner"],
                                   title="A question", question="Well?")
    with pytest.raises(access.PackDenied) as e:
        actions.decide(session, made["id"], actors["approver"],
                       outcome="APPROVED", source="AI")
    assert "committee decides" in str(e.value)


def test_a_conditional_approval_has_to_state_its_conditions(session, pack,
                                                            actors):
    made = actions.create_decision(session, pack["id"], actors["owner"],
                                   title="A question", question="Well?")
    with pytest.raises(pb.InvalidPlaybook) as e:
        actions.decide(session, made["id"], actors["approver"],
                       outcome="CONDITIONALLY_APPROVED")
    assert "what the conditions are" in str(e.value)


def test_a_decided_decision_is_not_edited_afterwards(session, pack, actors):
    made = actions.create_decision(session, pack["id"], actors["owner"],
                                   title="A question", question="Well?")
    actions.decide(session, made["id"], actors["approver"], outcome="REJECTED")
    with pytest.raises(pb.InvalidPlaybook) as e:
        actions.update_decision(session, made["id"], actors["owner"],
                                title="Something else")
    assert "not edited afterwards" in str(e.value)


# ================================================================= actions


def test_an_assistant_drafts_an_action_and_cannot_open_it(session, pack,
                                                          actors):
    made = actions.create_action(
        session, pack["id"], actors["owner"],
        description="Re-run the vintage analysis for the 2024 cohorts.",
        source="AI")
    assert made["status"] == "DRAFT"

    with pytest.raises(access.PackDenied) as e:
        actions.create_action(session, pack["id"], actors["owner"],
                              description="Do it now.", status="OPEN",
                              source="AI")
    assert "somebody has agreed to do it" in str(e.value)


def test_closing_an_action_needs_evidence(session, pack, actors):
    made = actions.create_action(
        session, pack["id"], actors["owner"], description="Do the thing.",
        owner_id=actors["author"].user_id, status="OPEN")
    with pytest.raises(pb.InvalidPlaybook) as e:
        actions.close_action(session, made["id"], actors["author"],
                             evidence="  ")
    assert "take it on trust" in str(e.value)

    closed = actions.close_action(
        session, made["id"], actors["author"],
        evidence="Vintage analysis circulated to the committee on 14 March.")
    assert closed["status"] == "COMPLETED"
    assert closed["closed"] is True
    assert closed["closed_at"]


def test_an_assistant_cannot_close_an_action(session, pack, actors):
    made = actions.create_action(
        session, pack["id"], actors["owner"], description="Do the thing.",
        owner_id=actors["author"].user_id, status="OPEN")
    with pytest.raises(access.PackDenied) as e:
        actions.close_action(session, made["id"], actors["author"],
                             evidence="It looks done to me.", source="AI")
    assert "owner asserts that" in str(e.value)


def test_an_assistant_may_post_an_update_and_not_move_the_work(session, pack,
                                                               actors):
    made = actions.create_action(
        session, pack["id"], actors["owner"], description="Do the thing.",
        owner_id=actors["author"].user_id, status="OPEN")

    posted = actions.update_action(
        session, made["id"], actors["owner"],
        latest_update="The linked Planner task moved to in progress.",
        source="AI")
    assert posted["latest_update"].startswith("The linked Planner task")

    with pytest.raises(access.PackDenied) as e:
        actions.update_action(session, made["id"], actors["owner"],
                              owner_id=actors["reviewer"].user_id, source="AI")
    assert "person's decision" in str(e.value)


def test_an_action_belongs_to_its_owner_not_to_everyone(session, pack, actors):
    made = actions.create_action(
        session, pack["id"], actors["owner"], description="Do the thing.",
        owner_id=actors["author"].user_id, status="OPEN")
    # The author owns it, so they may update it even at contributor access.
    actions.update_action(session, made["id"], actors["author"],
                          latest_update="Started.")
    # The reviewer does not own it and is not an editor.
    with pytest.raises(access.PackDenied) as e:
        actions.update_action(session, made["id"], actors["reviewer"],
                              latest_update="I'll do it.")
    assert "belongs to somebody else" in str(e.value)


def test_open_actions_carry_forward_rather_than_being_copied(session, committee,
                                                             template, actors):
    """The action belongs to the committee and keeps its identity."""
    first = pb.create_pack(session, actors["owner"],
                           committee_id=committee["id"],
                           template_id=template["id"], period="2024-12")
    made = actions.create_action(
        session, first["id"], actors["owner"],
        description="Carry me into the next meeting.",
        owner_id=actors["author"].user_id, status="OPEN")

    second = pb.create_pack(session, actors["owner"],
                            committee_id=committee["id"],
                            template_id=template["id"], period="2025-01")
    carried = actions.carry_forward(session, second["id"], actors["owner"])
    references = [a["reference"] for a in carried]
    assert made["reference"] in references
    assert len(references) == len(set(references)), (
        "an action is not copied into the next pack; it keeps one identity")


# ========================================================= the Planner bridge


def test_an_action_sent_to_the_planner_reads_its_progress_from_there(
        session, pack, actors, people):
    """Playbook holds the governance record; the Planner holds the work."""
    from backend.planner import service as planner

    project = planner.create_project(
        session, actors["owner"], code=f"PBT{pack['id']}",
        name="A delivery project for one test",
        manager_id=actors["owner"].user_id)
    session.flush()

    made = actions.create_action(
        session, pack["id"], actors["owner"],
        description="Rebuild the behavioural scorecard monitoring pack.",
        owner_id=actors["author"].user_id, status="OPEN")
    linked = actions.link_to_planner(session, made["id"], actors["owner"],
                                     project_id=int(project.id))

    assert linked["planner_task_id"] is not None
    assert linked["planner"]["linked"] is True
    assert linked["planner"]["task_found"] is True
    assert linked["planner"]["percent_complete"] == 0.0

    # Move it in the PLANNER, and read it back through the committee action.
    from backend.models.planner import PlannerTask

    task = session.get(PlannerTask, int(linked["planner_task_id"]))
    task.status = "IN_PROGRESS"
    task.percent_complete = 40
    session.flush()

    again = actions.actions(session, actors["owner"], pack_id=pack["id"])
    mine = next(a for a in again if a["id"] == made["id"])
    assert mine["planner"]["percent_complete"] == 40.0
    assert mine["planner"]["status"] == "IN_PROGRESS"

    from backend.models.planner import PlannerProject

    session.delete(session.get(PlannerProject, int(project.id)))
    session.flush()


def test_an_action_is_linked_once(session, pack, actors):
    from backend.planner import service as planner

    project = planner.create_project(
        session, actors["owner"], code=f"PBT2{pack['id']}",
        name="Another delivery project",
        manager_id=actors["owner"].user_id)
    session.flush()
    made = actions.create_action(session, pack["id"], actors["owner"],
                                 description="Do it.", status="OPEN")
    actions.link_to_planner(session, made["id"], actors["owner"],
                            project_id=int(project.id))
    with pytest.raises(pb.InvalidPlaybook) as e:
        actions.link_to_planner(session, made["id"], actors["owner"],
                                project_id=int(project.id))
    assert "already linked" in str(e.value)

    from backend.models.planner import PlannerProject

    session.delete(session.get(PlannerProject, int(project.id)))
    session.flush()


def test_the_planner_refuses_a_project_the_caller_cannot_reach(session, pack,
                                                               actors):
    """The Planner's own access rules apply, and its refusal is passed on."""
    made = actions.create_action(session, pack["id"], actors["owner"],
                                 description="Do it.", status="OPEN")
    with pytest.raises(access.PackNotFound):
        actions.link_to_planner(session, made["id"], actors["owner"],
                                project_id=2_000_000_001)


def test_a_deleted_planner_task_is_reported_rather_than_shown_as_unlinked(
        session, pack, actors):
    from backend.models.planner import PlannerProject, PlannerTask
    from backend.planner import service as planner

    project = planner.create_project(
        session, actors["owner"], code=f"PBT3{pack['id']}",
        name="A third project", manager_id=actors["owner"].user_id)
    session.flush()
    made = actions.create_action(session, pack["id"], actors["owner"],
                                 description="Do it.", status="OPEN")
    linked = actions.link_to_planner(session, made["id"], actors["owner"],
                                     project_id=int(project.id))
    session.delete(session.get(PlannerTask, int(linked["planner_task_id"])))
    session.flush()

    # The foreign key is ON DELETE SET NULL, so the column empties. What must
    # not happen is the action quietly reading as though it had never been
    # sent anywhere — `linked_at` survives the delete and is what makes the
    # difference reportable.
    session.expire_all()
    again = actions.actions(session, actors["owner"], pack_id=pack["id"])
    mine = next(a for a in again if a["id"] == made["id"])
    assert mine["planner"]["linked"] is False
    assert mine["planner"]["was_linked"] is True
    assert "has been deleted" in mine["planner"]["note"]
    assert mine["linked_at"], "when it was sent is still on the record"

    session.delete(session.get(PlannerProject, int(project.id)))
    session.flush()


# ==================================================================== sweep


def _at(pack_row, days_before: int) -> datetime:
    """A moment exactly `days_before` days before the meeting."""
    meeting = pack_row.meeting_at
    if meeting.tzinfo is None:
        meeting = meeting.replace(tzinfo=UTC)
    return meeting - timedelta(days=days_before)


def test_nobody_is_chased_before_the_committee_says_to(session, pack, actors,
                                                       committee):
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    whole = pb.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        pb.update_section(session, section["id"], actors["owner"],
                          owner_id=actors["author"].user_id)

    # The default `inputs` offset is 10 days. At 20 days out nothing is late.
    early = monitor.sweep(session, now=_at(row, 20),
                          committee_id=committee["id"], dry_run=True)
    assert [m for m in early.messages if m.trigger == "input"] == []


def test_section_owners_are_chased_from_the_committees_own_offset(
        session, pack, actors, committee):
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    whole = pb.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        pb.update_section(session, section["id"], actors["owner"],
                          owner_id=actors["author"].user_id)

    late = monitor.sweep(session, now=_at(row, 8),
                         committee_id=committee["id"], dry_run=True)
    inputs = [m for m in late.messages if m.trigger == "input"]
    assert inputs, "at eight days out, unwritten sections are chased"
    assert all(m.user_id == actors["author"].user_id for m in inputs)
    assert "sits in" in inputs[0].body


def test_a_committee_can_set_its_own_timing(session, pack, actors, committee,
                                            steward):
    """An annual forum and a monthly one do not chase on the same rhythm."""
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    whole = pb.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        pb.update_section(session, section["id"], actors["owner"],
                          owner_id=actors["author"].user_id)

    assert not [m for m in monitor.sweep(
        session, now=_at(row, 20), committee_id=committee["id"],
        dry_run=True).messages if m.trigger == "input"]

    pb.update_committee(session, committee["id"], steward,
                        workflow_offsets={"inputs": 25})
    assert [m for m in monitor.sweep(
        session, now=_at(row, 20), committee_id=committee["id"],
        dry_run=True).messages if m.trigger == "input"], (
        "with a 25-day input offset, 20 days out is late")


def test_the_same_reminder_is_not_sent_twice_in_one_day(session, pack, actors,
                                                        committee):
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    whole = pb.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        pb.update_section(session, section["id"], actors["owner"],
                          owner_id=actors["author"].user_id)

    when = _at(row, 8)
    first = monitor.sweep(session, now=when, committee_id=committee["id"])
    assert first.sent > 0
    second = monitor.sweep(session, now=when, committee_id=committee["id"])
    assert second.sent == 0
    assert second.suppressed >= first.sent


def test_the_same_reminder_is_sent_again_the_next_day(session, pack, actors,
                                                      committee):
    """Still outstanding tomorrow means still worth saying tomorrow."""
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    whole = pb.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        pb.update_section(session, section["id"], actors["owner"],
                          owner_id=actors["author"].user_id)

    monitor.sweep(session, now=_at(row, 8), committee_id=committee["id"])
    tomorrow = monitor.sweep(session, now=_at(row, 7),
                             committee_id=committee["id"])
    assert tomorrow.sent > 0


def test_a_dry_run_writes_nothing(session, pack, actors, committee):
    from sqlalchemy import func, select

    from backend.models.playbook import PlaybookPack, PlaybookReminder

    row = session.get(PlaybookPack, int(pack["id"]))
    before = int(session.execute(
        select(func.count()).select_from(PlaybookReminder)).scalar_one())
    result = monitor.sweep(session, now=_at(row, 1),
                           committee_id=committee["id"], dry_run=True)
    after = int(session.execute(
        select(func.count()).select_from(PlaybookReminder)).scalar_one())
    assert after == before
    assert "nothing was written" in " ".join(result.notes)


def test_a_reminder_writes_a_real_notification(session, pack, actors,
                                               committee):
    from sqlalchemy import select

    from backend.models.platform import Notification
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    whole = pb.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        pb.update_section(session, section["id"], actors["owner"],
                          owner_id=actors["author"].user_id)

    result = monitor.sweep(session, now=_at(row, 8),
                           committee_id=committee["id"])
    assert result.sent > 0
    notes = session.execute(select(Notification).where(
        Notification.user_id == actors["author"].user_id,
        Notification.kind == "playbook")).scalars().all()
    assert notes, "the reminder lands in the platform's own notification table"
    assert notes[0].object_type == "playbook_pack"


def test_an_overdue_action_chases_its_owner_on_its_own_date(session, pack,
                                                            actors, committee):
    made = actions.create_action(
        session, pack["id"], actors["owner"],
        description="This was due last week.",
        owner_id=actors["author"].user_id,
        due_date=date.today() - timedelta(days=7), status="OPEN")

    result = monitor.sweep(session, now=datetime.now(UTC),
                           committee_id=committee["id"], dry_run=True)
    chased = [m for m in result.messages if m.trigger == "action"]
    assert chased, "an overdue action is chased"
    assert any(made["reference"] in m.title for m in chased)
    assert any("overdue" in m.title for m in chased)


def test_somebody_who_has_turned_notifications_off_is_not_chased(
        session, pack, actors, committee, steward):
    from sqlalchemy import select

    from backend.models.playbook import PlaybookMember, PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    whole = pb.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        pb.update_section(session, section["id"], actors["owner"],
                          owner_id=actors["author"].user_id)

    member = session.execute(select(PlaybookMember).where(
        PlaybookMember.committee_id == committee["id"],
        PlaybookMember.user_id == actors["author"].user_id)).scalar_one()
    pb.update_member(session, int(member.id), steward, notify=False)

    result = monitor.sweep(session, now=_at(row, 8),
                           committee_id=committee["id"], dry_run=True)
    assert not [m for m in result.messages
                if m.user_id == actors["author"].user_id]


# =============================================================== comparison


def test_the_first_pack_says_there_is_nothing_to_compare(session, pack, actors):
    generation.generate(session, pack["id"], actors["owner"])
    outcome = compare.against_previous(session, pack["id"], actors["owner"])
    assert outcome["previous_pack_id"] is None
    assert "first pack" in outcome["summary"]


def test_a_metric_the_new_pack_dropped_is_reported(session, committee,
                                                   template, actors):
    """A reader who saw it last time has not been told it is gone."""
    from backend.models.playbook import PlaybookPack

    first = pb.create_pack(session, actors["owner"],
                           committee_id=committee["id"],
                           template_id=template["id"], period="2025-01")
    generation.generate(session, first["id"], actors["owner"])
    row = session.get(PlaybookPack, int(first["id"]))
    row.status = "APPROVED"
    row.approved_version = int(row.version)
    session.flush()

    second = pb.create_pack(session, actors["owner"],
                            committee_id=committee["id"],
                            template_id=template["id"], period="2025-02")
    whole = pb.pack(session, second["id"], actors["owner"])
    dropped = whole["sections"][1]["blocks"][0]
    pb.delete_block(session, dropped["id"], actors["owner"])
    generation.generate(session, second["id"], actors["owner"])

    outcome = compare.against_previous(session, second["id"], actors["owner"])
    removed = [d for d in outcome["differences"] if d["kind"] == compare.REMOVED]
    assert removed, outcome["summary"]
    assert removed[0]["metric_id"] == "retail.application_bad_rate"
    assert "has not been told it is gone" in removed[0]["caveat"]


def test_a_formula_change_is_reported_as_a_redefinition_not_a_movement(
        session, committee, template, actors):
    """The most misleading line a comparison can produce, held shut.

    The previous pack's snapshot is edited to carry a different formula hash,
    which is exactly what a governed formula revision between two meetings
    produces. The comparison must refuse to call the difference a movement.
    """
    from sqlalchemy import select

    from backend.models.playbook import PlaybookPack, PlaybookSnapshot

    first = pb.create_pack(session, actors["owner"],
                           committee_id=committee["id"],
                           template_id=template["id"], period="2025-01")
    generation.generate(session, first["id"], actors["owner"])
    row = session.get(PlaybookPack, int(first["id"]))
    row.status = "APPROVED"
    row.approved_version = int(row.version)
    session.flush()

    was = session.execute(select(PlaybookSnapshot).where(
        PlaybookSnapshot.pack_id == first["id"],
        PlaybookSnapshot.metric_id == "retail.default_rate")).scalars().first()
    was.formula_hash = "a-different-arithmetic-entirely"
    was.metric_version = "0.9.0"
    session.flush()

    second = pb.create_pack(session, actors["owner"],
                            committee_id=committee["id"],
                            template_id=template["id"], period="2025-01")
    generation.generate(session, second["id"], actors["owner"])

    outcome = compare.against_previous(session, second["id"], actors["owner"])
    found = next(d for d in outcome["differences"]
                 if d["metric_id"] == "retail.default_rate")
    assert found["kind"] == compare.REDEFINED
    assert "not calculated the same way" in found["caveat"]
    assert "should not be read as a movement" in found["caveat"]
    assert outcome["material"][0]["kind"] == compare.REDEFINED, (
        "a redefinition sorts first, because it changes what every other "
        "line means")


# ============================================ a move nobody can see on screen


def _figure(**over):
    from backend.playbook import snapshots as snap

    base = {
        "metric_id": "retail.average_debt_burden",
        "metric_name": "Average debt burden ratio",
        "metric_version": "1.0.0",
        "formula_hash": "a" * 64,
        "period": "2025-01",
        "comparison_period": "2024-12",
        "value": 0.31349361339628923,
        "comparison_value": 0.305581953071401,
        "unit": "percent",
        "decimals": 1,
        "higher_is_better": False,
        "availability": snap.OK,
    }
    base.update(over)
    return snap.Figure(**base)


def test_a_move_below_the_reported_precision_is_marked_not_visible():
    """0.3134% against 0.3056% both read "0.3%" at one decimal.

    `decimals` is a governance statement about how precisely the metric is
    meaningful. A movement that does not survive it becomes, on screen, an
    arrow between two identical numbers — which a committee reads as an
    error — and quoting the extra digits to justify the arrow would be a
    precision the metric definition does not claim.
    """
    from backend.playbook import snapshots as snap

    moved = snap.movement(_figure())
    assert moved["available"] is True
    assert moved["direction"] == "up", (
        "the arithmetic must still say which way it went")
    assert moved["visible"] is False


def test_a_move_that_survives_the_precision_is_visible():
    from backend.playbook import snapshots as snap

    moved = snap.movement(_figure(value=0.42, comparison_value=0.31))
    assert moved["direction"] == "up"
    assert moved["visible"] is True


def test_the_document_says_so_rather_than_drawing_an_arrow():
    from backend.playbook import export

    said = export._movement_cell(_figure())
    assert "▲" not in said and "▼" not in said, said
    assert "precision" in said, said


def test_materiality_still_reads_the_real_numbers():
    """Presentation was told the truth. The arithmetic was not touched.

    A rule with a threshold below the reported precision must still fire:
    materiality is about the book, not about how many decimals a pack prints.
    """
    from backend.playbook import materiality

    figure = _figure()
    rule = materiality.Rule(
        key="debt_burden_move", metric_id=figure.metric_id,
        comparison="absolute_change", threshold=0.005,
        severity="MEDIUM", title="Debt burden moved")
    found = materiality._movement(rule, figure)
    assert found is not None, (
        "a real move must still be observable even when it is too small to "
        "print at the metric's own precision")
