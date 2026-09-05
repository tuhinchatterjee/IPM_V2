"""What the authorisation door refuses, and how it says so.

Two properties are asserted over and over here because both fail silently when
they fail at all:

  * an id in a URL is a guess until somebody checks it, and the check has to
    happen against the OBJECT'S OWN parent rather than against a pack id the
    same caller also sent
  * an assistant acting on somebody's behalf never exceeds them, and is capped
    below them at the operations that need a name against them

The not-found-versus-denied distinction gets its own test. A caller who can
tell "this pack does not exist" from "this pack exists and is not yours" can
walk the id space and learn which committees the bank runs and how often, from
403s alone, without ever reading a figure.
"""

from __future__ import annotations

import pytest

from backend.playbook import access, generation, service

pytestmark = pytest.mark.usefixtures("session")


# ==================================================== the boundary is the list


def test_somebody_not_on_the_committee_gets_not_found_rather_than_denied(
        session, pack, actors):
    with pytest.raises(access.PackNotFound):
        service.pack(session, pack["id"], actors["outsider"])


def test_an_id_that_does_not_exist_gives_the_same_answer(session, actors):
    """Identical exception AND an identical shape of message.

    If the two differ in any way a caller can observe, the enumeration works
    anyway and the distinction only looked like it had been closed.
    """
    with pytest.raises(access.PackNotFound) as missing:
        service.pack(session, 2_000_000_001, actors["outsider"])
    assert "No pack" in str(missing.value)


def test_an_outsider_sees_no_committees_at_all(session, committee, actors):
    assert service.committees(session, actors["outsider"]) == []
    assert service.packs(session, actors["outsider"]) == []


def test_a_member_of_one_committee_cannot_read_another(session, committee,
                                                       template, actors,
                                                       steward, people):
    """Membership is per committee, and reading is scoped by it."""
    other = service.create_committee(
        session, steward, name="Another Committee Entirely")
    service.add_member(session, other["id"], steward,
                       user_id=int(people["outsider"].id),
                       access_role="OWNER")
    theirs = service.create_pack(
        session, actors["outsider"], committee_id=other["id"], period="2025-01")

    with pytest.raises(access.PackNotFound):
        service.pack(session, theirs["id"], actors["owner"])
    with pytest.raises(access.PackNotFound):
        service.committee(session, other["id"], actors["owner"])

    from backend.models.playbook import PlaybookCommittee

    session.delete(session.get(PlaybookCommittee, int(other["id"])))
    session.flush()


# =========================================== children are checked by their own id


def test_a_section_of_another_pack_cannot_be_edited_by_sending_two_ids(
        session, committee, template, actors, steward, people):
    """The IDOR this shape of API invites, held shut.

    A caller who can read pack 4 must not be able to edit section 900 because
    they sent both. The service finds the section's OWN pack and authorises
    against that, so the pack id the caller sent is never load-bearing.
    """
    other = service.create_committee(
        session, steward, name="A Committee Somebody Else Runs")
    service.add_member(session, other["id"], steward,
                       user_id=int(people["outsider"].id),
                       access_role="OWNER")
    theirs = service.create_pack(
        session, actors["outsider"], committee_id=other["id"], period="2025-01")
    their_section = service.create_section(
        session, theirs["id"], actors["outsider"], title="Their private page")

    with pytest.raises(access.PackNotFound):
        service.update_section(session, their_section["id"], actors["owner"],
                               title="Mine now")
    with pytest.raises(access.PackNotFound):
        service.create_block(session, their_section["id"], actors["owner"],
                             block_type="NARRATIVE", body="Injected.")

    from backend.models.playbook import PlaybookCommittee

    session.delete(session.get(PlaybookCommittee, int(other["id"])))
    session.flush()


def test_reordering_refuses_ids_that_belong_to_another_pack(session, pack,
                                                            committee,
                                                            template, actors):
    """An order is a complete list, and every id in it has to be this pack's."""
    elsewhere = service.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period="2025-02")
    stranger = service.pack(session, elsewhere["id"],
                            actors["owner"])["sections"][0]
    mine = [s["id"] for s in
            service.pack(session, pack["id"], actors["owner"])["sections"]]

    with pytest.raises(access.PackNotFound) as e:
        service.reorder(session, pack["id"], actors["owner"],
                        section_ids=[*mine, stranger["id"]])
    assert "is not a section of this pack" in str(e.value)


def test_a_partial_order_is_refused_rather_than_half_applied(session, pack,
                                                             actors):
    whole = service.pack(session, pack["id"], actors["owner"])
    with pytest.raises(service.InvalidPlaybook) as e:
        service.reorder(session, pack["id"], actors["owner"],
                        section_ids=[whole["sections"][0]["id"]])
    assert "has to name every section" in str(e.value)


# ================================================================ what a role does


def test_a_contributor_writes_their_own_section_and_not_somebody_elses(
        session, pack, actors):
    whole = service.pack(session, pack["id"], actors["owner"])
    mine, theirs = whole["sections"][0], whole["sections"][1]
    service.update_section(session, mine["id"], actors["owner"],
                           owner_id=actors["author"].user_id)

    service.update_section(session, mine["id"], actors["author"],
                           purpose="I own this one.")

    with pytest.raises(access.PackDenied) as e:
        service.update_section(session, theirs["id"], actors["author"],
                               purpose="And this one too.")
    assert "belongs to somebody else" in str(e.value)


def test_a_contributor_cannot_decide_who_reviews_their_own_work(session, pack,
                                                                actors):
    whole = service.pack(session, pack["id"], actors["owner"])
    section = whole["sections"][0]
    service.update_section(session, section["id"], actors["owner"],
                           owner_id=actors["author"].user_id)
    with pytest.raises(access.PackDenied) as e:
        service.update_section(session, section["id"], actors["author"],
                               reviewer_id=actors["author"].user_id)
    assert "editor access" in str(e.value)


def test_a_reviewer_cannot_edit_the_pack_they_are_reviewing(session, pack,
                                                            actors):
    whole = service.pack(session, pack["id"], actors["owner"])
    with pytest.raises(access.PackDenied):
        service.update_pack(session, pack["id"], actors["reviewer"],
                            name="Rewritten by the reviewer")
    # A reviewer outranks a contributor in ACCESS_RANK, so what stops them
    # here is not the level — it is that the section is not theirs.
    with pytest.raises(access.PackDenied) as e:
        service.update_section(session, whole["sections"][0]["id"],
                               actors["reviewer"], purpose="Rewritten.")
    assert "belongs to somebody else" in str(e.value)


def test_the_last_owner_cannot_be_removed(session, committee, actors):
    """A committee with no owner is one nobody can administer.

    Driven by a platform administrator rather than by one of the owners,
    because an owner removing themselves loses their own access partway
    through and would hit not-found before reaching the rule under test.
    """
    from sqlalchemy import select

    from backend.api.permissions import Principal, Role
    from backend.models.playbook import PlaybookMember

    admin = Principal(user_id=None, role=Role.ADMIN)
    owners = session.execute(select(PlaybookMember).where(
        PlaybookMember.committee_id == committee["id"],
        PlaybookMember.access_role == "OWNER",
        PlaybookMember.active.is_(True))).scalars().all()
    assert len(owners) >= 2, "the fixture seeds a creator and a named owner"

    for row in owners[:-1]:
        service.update_member(session, int(row.id), admin, active=False)

    with pytest.raises(service.InvalidPlaybook) as e:
        service.update_member(session, int(owners[-1].id), admin, active=False)
    assert "only owner" in str(e.value)

    with pytest.raises(service.InvalidPlaybook):
        service.update_member(session, int(owners[-1].id), admin,
                              access_role="VIEWER")


# ================================================================= the AI ceiling


def _as_ai(actor):
    return actor


def test_an_assistant_never_exceeds_editor_however_senior_the_person(
        session, committee, actors):
    """The cap is applied once, on the way out of the grant.

    The owner holds OWNER access. An AI-sourced call on their behalf holds
    EDITOR and no more, so nothing downstream has to remember the rule.
    """
    human = access.committee_grant(session, committee["id"], actors["owner"])
    assert human.access == access.OWNER

    machine = access.committee_grant(session, committee["id"], actors["owner"],
                                     source="AI")
    assert machine.access == access.AI_CEILING == access.EDITOR
    assert machine.by_ai is True
    assert not machine.at_least(access.APPROVER)
    assert not machine.at_least(access.OWNER)

    # And the thing the rank cap does NOT do, said out loud so nobody later
    # mistakes it for the whole mechanism. REVIEWER sits below EDITOR in
    # ACCESS_RANK, so the cap alone satisfies at_least(REVIEWER); what
    # actually refuses an agent a review is the explicit by_ai check in
    # `may_review_section`, exercised by its own test below.
    assert machine.at_least(access.REVIEWER)
    assert access.AI_FORBIDDEN["record_review"]


def test_a_platform_administrator_is_capped_the_same_way(session, committee,
                                                         steward):
    """The exception for administrators is a HUMAN exception."""
    from backend.api.permissions import Principal, Role

    admin = Principal(user_id=None, role=Role.ADMIN)
    assert access.committee_grant(
        session, committee["id"], admin).access == access.OWNER
    assert access.committee_grant(
        session, committee["id"], admin, source="AI").access == access.EDITOR


def test_an_assistant_cannot_approve_a_pack(session, committee, template,
                                            actors):
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(service.create_pack(
        session, actors["approver"], committee_id=committee["id"],
        template_id=template["id"], period="2025-01")["id"]))
    row.status = "READY_FOR_APPROVAL"
    session.flush()

    with pytest.raises(access.PackDenied) as e:
        service.set_pack_status(session, int(row.id), actors["approver"],
                                status="APPROVED", source="AI")
    said = str(e.value)
    assert "putting their name to it" in said
    assert "not going to be one" in said


def test_an_assistant_cannot_record_a_review(session, pack, actors):
    section = service.pack(session, pack["id"],
                           actors["owner"])["sections"][0]
    service.update_section(session, section["id"], actors["owner"],
                           reviewer_id=actors["reviewer"].user_id)
    with pytest.raises(access.PackDenied) as e:
        service.review_section(session, section["id"], actors["reviewer"],
                               decision="APPROVED", source="AI_CHAT")
    assert "unreliable" in str(e.value)


def test_an_assistant_cannot_submit_a_section_for_somebody(session, pack,
                                                           actors):
    section = service.pack(session, pack["id"],
                           actors["owner"])["sections"][0]
    with pytest.raises(access.PackDenied) as e:
        service.submit_section(session, section["id"], actors["owner"],
                               source="AI")
    assert "have finished with it" in str(e.value)


def test_an_assistant_cannot_edit_an_approved_pack(session, committee,
                                                   template, actors):
    from sqlalchemy import select

    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(service.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period="2025-01")["id"]))
    row.status = "APPROVED"
    session.flush()

    with pytest.raises(access.PackDenied) as e:
        generation.amend(session, int(row.id), actors["owner"],
                         reason="A machine decided to correct it.",
                         source="AI")
    assert "historical record" in str(e.value)
    assert session.execute(select(PlaybookPack.status).where(
        PlaybookPack.id == row.id)).scalar_one() == "APPROVED"


def test_an_assistant_cannot_accept_its_own_draft(session, pack, actors):
    """Accepting is a person saying the words are theirs now."""
    section = service.pack(session, pack["id"],
                           actors["owner"])["sections"][0]
    drafted = service.create_block(
        session, section["id"], actors["owner"], block_type="AI_NARRATIVE",
        body="The default rate rose.", statement_kind="FACT", source="AI")
    assert drafted["ai_accepted"] is False, (
        "a block an assistant wrote is a draft until a person accepts it")

    with pytest.raises(access.PackDenied) as e:
        service.update_block(session, drafted["id"], actors["owner"],
                             ai_accepted=True, source="AI")
    assert "cannot accept its own writing" in str(e.value)


def test_a_person_editing_an_ai_draft_accepts_it(session, pack, actors):
    section = service.pack(session, pack["id"],
                           actors["owner"])["sections"][0]
    drafted = service.create_block(
        session, section["id"], actors["owner"], block_type="AI_NARRATIVE",
        body="The default rate rose.", source="AI")
    edited = service.update_block(
        session, drafted["id"], actors["owner"],
        body="The default rate rose by 64 basis points, driven by the 2024 "
             "vintages.")
    assert edited["ai_accepted"] is True
    assert edited["stale"] is False


def test_an_assistant_cannot_stand_up_a_committee(session, steward):
    with pytest.raises(access.PackDenied) as e:
        service.create_committee(session, steward, name="Machine Committee",
                                 source="AI")
    assert "how the bank runs" in str(e.value)


def test_an_unrecognised_source_is_refused_rather_than_treated_as_a_person(
        session, committee, actors):
    """A typo must not launder an AI write into a human one.

    An unknown source silently defaulting to UI is the failure: an agent
    sending "AI " or "assistant" would be recorded as a person, and every
    later check that asks `by_ai` would answer no.
    """
    for typo in ("HUMAN", "assistant", "ai-chat", " AI", "AI_"):
        with pytest.raises(ValueError) as e:
            access.committee_grant(session, committee["id"], actors["owner"],
                                   source=typo)
        assert "not a recorded source" in str(e.value), typo

    # None and "" are the exception, and deliberately so: at a Python call
    # boundary they cannot be told apart from the argument being omitted. What
    # makes that safe is that the source is decided by the code path — the
    # router passes UI, the agent tool passes AI — and is never read from a
    # request body, so no caller is in a position to send either.
    assert access.normalise_source(None) == "UI"
    assert access.normalise_source("") == "UI"


def test_lower_case_sources_are_accepted_and_normalised(session, committee,
                                                        actors):
    grant = access.committee_grant(session, committee["id"], actors["owner"],
                                   source="ai")
    assert grant.source == "AI" and grant.by_ai is True


# ============================================================ locked means locked


def test_no_role_can_edit_an_approved_pack(session, committee, template,
                                           actors, steward):
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(service.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period="2025-01")["id"]))
    row.status = "APPROVED"
    session.flush()

    for who in (actors["owner"], actors["approver"], steward):
        with pytest.raises(access.PackLocked):
            service.update_pack(session, int(row.id), who, name="Edited")


def test_a_locked_pack_says_how_to_correct_it(session, committee, template,
                                              actors):
    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(service.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period="2025-01")["id"]))
    row.status = "PUBLISHED"
    session.flush()
    with pytest.raises(access.PackLocked) as e:
        service.create_section(session, int(row.id), actors["owner"],
                               title="Added after the meeting")
    said = str(e.value)
    assert "historical record" in said
    assert "raise an amendment" in said, (
        "a refusal with no next step is how somebody edits the database "
        "directly")
