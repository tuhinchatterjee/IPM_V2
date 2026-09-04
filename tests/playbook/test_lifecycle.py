"""The committee pack lifecycle, driven through the real service.

No mocks. These call the same functions the API calls, against a real
PostgreSQL and the real metric layer reading the real lake, because the
failures this product has to prevent — a pack approved with a broken figure, a
reviewer's approval surviving an edit, an agent publishing — are failures of
the interaction between those layers and not of any one of them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.playbook import access, generation, readiness, service
from backend.playbook import snapshots as snap

pytestmark = pytest.mark.usefixtures("session")


# ================================================================ the shape


def test_a_pack_is_laid_out_from_its_template(session, pack, actors):
    """Creating a pack from a template gives it the template's pages."""
    whole = service.pack(session, pack["id"], actors["owner"])
    titles = [s["title"] for s in whole["sections"]]
    assert titles == ["Portfolio performance", "Origination quality"]

    first = whole["sections"][0]
    assert [b["block_type"] for b in first["blocks"]] == ["KPI", "NARRATIVE"]
    assert first["blocks"][0]["config"]["metric_id"] == "retail.default_rate"
    # Laid out, not yet calculated. The two are separate operations because a
    # create that ran every query would make laying out a pack take minutes.
    assert first["blocks"][0]["figure"] is None


def test_a_pack_keeps_the_template_version_it_came_from(session, pack,
                                                        template, actors):
    """A template moving on does not reshape a pack already built from it."""
    whole = service.pack(session, pack["id"], actors["owner"])
    assert whole["template_id"] == template["id"]

    later = service.create_template(
        session, _steward(actors, session), name="Monthly Credit Pack",
        code=template["code"], committee_id=template["committee_id"],
        sections=[{"key": "only", "title": "A different shape"}])
    assert later["version"] == template["version"] + 1

    again = service.pack(session, pack["id"], actors["owner"])
    assert again["template_id"] == template["id"]
    assert [s["title"] for s in again["sections"]] == [
        "Portfolio performance", "Origination quality"]


def test_a_pack_links_itself_to_the_previous_approved_one(
        session, committee, template, actors):
    """"What changed since last time" is a stored relationship, not a guess."""
    first = _approve(session, committee, template, actors, period="2024-12")
    second = service.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period="2025-01")
    assert second["previous_pack_id"] == first["id"]


# ============================================================ calculation


def test_generating_freezes_a_governed_figure_into_every_calculated_block(
        session, pack, actors):
    """The number, and everything needed to defend it, land on the block."""
    outcome = generation.generate(session, pack["id"], actors["owner"])
    assert outcome.calculated == 2, outcome.summary

    whole = service.pack(session, pack["id"], actors["owner"])
    kpi = whole["sections"][0]["blocks"][0]
    figure = kpi["figure"]
    assert figure is not None
    assert figure["metric_id"] == "retail.default_rate"
    # The working travels with the value. A figure whose formula version and
    # period are not stored beside it cannot be defended six months later.
    assert figure["formula_hash"]
    assert figure["metric_version"]
    assert figure["period"]
    assert figure["dataset"]


def test_the_frozen_figure_is_the_one_the_metric_layer_computes(session, pack,
                                                               actors):
    """A pack does not have its own arithmetic — it stores the platform's."""
    generation.generate(session, pack["id"], actors["owner"])
    whole = service.pack(session, pack["id"], actors["owner"])
    figure = whole["sections"][0]["blocks"][0]["figure"]

    from backend.metrics import service as metrics

    live = metrics.value("retail.default_rate", period=figure["period"])
    if live["value"] is None:
        assert figure["value"] is None
    else:
        assert figure["value"] == pytest.approx(live["value"], rel=1e-12)


def test_a_pack_does_not_recalculate_when_it_is_opened(session, pack, actors):
    """Reading a pack shows what was calculated into it, not what is true now.

    The property the whole design rests on: two reads of the same pack version
    return the same numbers, whatever has happened to the lake in between.
    """
    generation.generate(session, pack["id"], actors["owner"])
    once = service.pack(session, pack["id"], actors["owner"])
    twice = service.pack(session, pack["id"], actors["owner"])
    assert (once["sections"][0]["blocks"][0]["figure"]["snapshot_id"]
            == twice["sections"][0]["blocks"][0]["figure"]["snapshot_id"])
    assert (once["sections"][0]["blocks"][0]["figure"]["value"]
            == twice["sections"][0]["blocks"][0]["figure"]["value"])


def test_regenerating_writes_new_rows_rather_than_editing_the_old_ones(
        session, pack, actors):
    """Snapshots are append-only, which is what makes an old version readable."""
    from sqlalchemy import func, select

    from backend.models.playbook import PlaybookSnapshot

    def how_many() -> int:
        return int(session.execute(
            select(func.count()).select_from(PlaybookSnapshot)
            .where(PlaybookSnapshot.pack_id == pack["id"])).scalar_one())

    generation.generate(session, pack["id"], actors["owner"])
    after_one = how_many()
    generation.generate(session, pack["id"], actors["owner"])
    assert how_many() > after_one

    versions = {int(v) for v in session.execute(
        select(PlaybookSnapshot.pack_version)
        .where(PlaybookSnapshot.pack_id == pack["id"])).scalars()}
    assert len(versions) == 2, (
        "each generation writes its snapshots at one pack version, so the "
        "figures at a version are a coherent set")


def test_one_metric_on_three_blocks_is_read_once(session, pack, actors):
    """Three tiles over one metric must not produce three disagreeing reads."""
    whole = service.pack(session, pack["id"], actors["owner"])
    section = whole["sections"][0]
    for _ in range(2):
        service.create_block(
            session, section["id"], actors["owner"], block_type="KPI",
            title="The same rate again",
            config={"metric_id": "retail.default_rate"})

    outcome = generation.generate(session, pack["id"], actors["owner"])
    assert outcome.calculated == 2, (
        "four calculated blocks over two distinct metrics is two reads")

    again = service.pack(session, pack["id"], actors["owner"])
    shown = [b["figure"]["snapshot_id"] for b in again["sections"][0]["blocks"]
             if b["figure"] is not None]
    assert len(set(shown)) == 1, "all three point at the one calculation"


# ============================================================== the honest no


def test_an_immature_period_reports_not_matured_rather_than_zero(session, pack,
                                                                 actors):
    """The defect this product exists to prevent, held shut at pack level."""
    service.update_pack(session, pack["id"], actors["owner"], period="2025-07")
    generation.generate(session, pack["id"], actors["owner"])

    whole = service.pack(session, pack["id"], actors["owner"])
    figure = whole["sections"][0]["blocks"][0]["figure"]
    if figure["availability"] == snap.OK:
        pytest.skip("this lake has matured rows in 2025-07")

    assert figure["value"] is None
    assert figure["display_value"] == "—"
    assert figure["availability"] == snap.NOT_MATURED
    assert "has not happened" in figure["unavailable_reason"]


def test_an_immature_figure_does_not_block_the_pack(session, pack, actors):
    """A fact about the calendar is worth saying and is not worth waiting for."""
    service.update_pack(session, pack["id"], actors["owner"], period="2025-07")
    generation.generate(session, pack["id"], actors["owner"])

    from backend.models.playbook import PlaybookPack

    row = session.get(PlaybookPack, int(pack["id"]))
    state = readiness.assess(session, row)
    data = next(c for c in state.checks if c.key == "data")
    assert not any(r.blocking for r in data.reasons), (
        "an outcome that has not matured is a fact about the book, and a pack "
        "that states it plainly is better than one that waits for it")


def test_a_period_the_lake_does_not_hold_says_so(session, pack, actors):
    """Four ways of having no number, and this is not the same as the others."""
    service.update_pack(session, pack["id"], actors["owner"], period="2099-01")
    generation.generate(session, pack["id"], actors["owner"])

    whole = service.pack(session, pack["id"], actors["owner"])
    figure = whole["sections"][0]["blocks"][0]["figure"]
    assert figure["availability"] == snap.PERIOD_MISSING
    assert "2099-01" in figure["unavailable_reason"]


# ================================================================= findings


def test_a_threshold_breach_raises_a_finding_that_names_its_rule(session, pack,
                                                                 actors):
    """A committee has to be able to argue with the threshold."""
    from sqlalchemy import select

    from backend.models.playbook import PlaybookFinding

    generation.generate(session, pack["id"], actors["owner"])
    findings = session.execute(
        select(PlaybookFinding)
        .where(PlaybookFinding.pack_id == pack["id"])).scalars().all()
    breach = [f for f in findings if f.rule_key == "default_rate.level"]
    if not breach:
        pytest.skip("the retail default rate is below 5% in this lake")

    found = breach[0]
    assert found.severity == "HIGH"
    assert found.rule_detail["rule"]["threshold"] == 5.0
    assert found.rule_detail["basis"].startswith("Retail credit risk appetite")
    assert "threshold" in found.factual_basis


def test_regenerating_does_not_raise_the_same_finding_twice(session, pack,
                                                            actors):
    """A finding somebody answered must not come back as a new one."""
    from sqlalchemy import select

    from backend.models.playbook import PlaybookFinding

    first = generation.generate(session, pack["id"], actors["owner"])
    if not first.findings_raised:
        pytest.skip("nothing was above its threshold in this lake")

    second = generation.generate(session, pack["id"], actors["owner"])
    assert second.findings_raised == 0
    assert second.findings_refreshed == first.findings_raised

    prints = [str(f.fingerprint) for f in session.execute(
        select(PlaybookFinding)
        .where(PlaybookFinding.pack_id == pack["id"])).scalars()]
    assert len(prints) == len(set(prints))


def test_a_dismissed_finding_is_left_alone_by_a_regeneration(session, pack,
                                                             actors):
    """Dismissing is management accepting a risk, and it sticks."""
    from sqlalchemy import select

    from backend.models.playbook import PlaybookFinding

    if not generation.generate(session, pack["id"], actors["owner"]).findings_raised:
        pytest.skip("nothing was above its threshold in this lake")

    found = session.execute(
        select(PlaybookFinding)
        .where(PlaybookFinding.pack_id == pack["id"])).scalars().first()
    found.status = "DISMISSED"
    found.dismissed_reason = "Known and accepted; see the appetite paper."
    session.flush()

    generation.generate(session, pack["id"], actors["owner"])
    session.refresh(found)
    assert found.status == "DISMISSED"
    assert found.dismissed_reason.startswith("Known and accepted")


# ============================================================== concurrency


def test_two_editors_do_not_silently_overwrite_one_another(session, pack,
                                                           actors):
    """The refusal names who moved it, so nobody has to ask around the floor."""
    whole = service.pack(session, pack["id"], actors["owner"])
    stale_version = whole["version"]

    service.update_pack(session, pack["id"], actors["owner"],
                        expected_version=stale_version, name="Their edit")

    with pytest.raises(service.StaleWrite) as e:
        service.update_pack(session, pack["id"], actors["owner"],
                            expected_version=stale_version, name="My edit")
    said = str(e.value)
    assert f"version {stale_version}" in said
    assert "Owner Tester" in said, "the refusal says who moved it"


# ============================================================ review gating


def test_a_review_is_recorded_against_the_version_that_was_read(session, pack,
                                                                actors):
    section = service.pack(session, pack["id"],
                           actors["owner"])["sections"][0]
    service.update_section(session, section["id"], actors["owner"],
                           owner_id=actors["author"].user_id,
                           reviewer_id=actors["reviewer"].user_id)
    from backend.models.playbook import PlaybookPack

    at = int(session.get(PlaybookPack, int(pack["id"])).version)
    outcome = service.review_section(session, section["id"], actors["reviewer"],
                                     decision="APPROVED", note="Read it.")
    assert outcome["review"]["at_version"] == at
    assert outcome["status"] == "APPROVED"


def test_an_approval_does_not_survive_an_edit_to_the_pack(session, pack,
                                                          actors):
    """A reviewer who approved version 4 has not approved version 5."""
    from backend.models.playbook import PlaybookPack

    whole = service.pack(session, pack["id"], actors["owner"])
    for section in whole["sections"]:
        service.update_section(session, section["id"], actors["owner"],
                               owner_id=actors["author"].user_id,
                               reviewer_id=actors["reviewer"].user_id)
    for section in whole["sections"]:
        service.review_section(session, section["id"], actors["reviewer"],
                               decision="APPROVED")

    row = session.get(PlaybookPack, int(pack["id"]))
    before = readiness.assess(session, row)
    assert not [r for r in before.blocking if r.check == "review"]

    service.update_block(
        session, whole["sections"][0]["blocks"][1]["id"], actors["owner"],
        body="A paragraph nobody has reviewed.")

    session.refresh(row)
    after = readiness.assess(session, row)
    stale = [r for r in after.blocking if r.check == "review"]
    assert stale, "an edit after approval puts the review back on the list"
    assert "has to be looked at again" in stale[0].text


def test_asking_for_changes_without_saying_what_is_refused(session, pack,
                                                           actors):
    section = service.pack(session, pack["id"],
                           actors["owner"])["sections"][0]
    service.update_section(session, section["id"], actors["owner"],
                           reviewer_id=actors["reviewer"].user_id)
    with pytest.raises(service.InvalidPlaybook) as e:
        service.review_section(session, section["id"], actors["reviewer"],
                               decision="CHANGES_REQUESTED")
    assert "guessing" in str(e.value)


# ================================================================ approval


def test_a_pack_cannot_reach_approval_while_something_blocks_it(session, pack,
                                                                actors):
    service.set_pack_status(session, pack["id"], actors["owner"],
                            status="CONTRIBUTOR_REVIEW")
    service.set_pack_status(session, pack["id"], actors["owner"],
                            status="REVIEW")
    with pytest.raises(service.InvalidPlaybook) as e:
        service.set_pack_status(session, pack["id"], actors["owner"],
                                status="READY_FOR_APPROVAL")
    said = str(e.value)
    assert "not ready to go to committee" in said
    assert "•" in said, "the refusal lists what is blocking it"


def test_a_pack_cannot_jump_a_status(session, pack, actors):
    with pytest.raises(service.InvalidPlaybook) as e:
        service.set_pack_status(session, pack["id"], actors["approver"],
                                status="APPROVED")
    assert "cannot go straight to" in str(e.value)


def test_the_pack_owner_cannot_approve_their_own_pack(session, committee,
                                                      template, actors):
    """Sign-off means a second pair of eyes, and it is enforced not requested."""
    from sqlalchemy import select

    from backend.models.playbook import PlaybookMember

    # Give the owner approver access as well, so the only thing left refusing
    # them is the rule this test is about.
    row = session.execute(select(PlaybookMember).where(
        PlaybookMember.committee_id == committee["id"],
        PlaybookMember.user_id == actors["owner"].user_id)).scalar_one()
    row.access_role = "APPROVER"
    session.flush()

    ready = _ready_pack(session, committee, template, actors)
    with pytest.raises(access.PackDenied) as e:
        service.set_pack_status(session, ready["id"], actors["owner"],
                                status="APPROVED")
    assert "cannot also be the person who approves it" in str(e.value)


def test_approval_locks_the_pack_and_records_the_version(session, committee,
                                                         template, actors):
    approved = _approve(session, committee, template, actors)
    assert approved["status"] == "APPROVED"
    assert approved["approved_version"] == approved["version"]
    assert approved["approved_by"] == actors["approver"].user_id

    whole = service.pack(session, approved["id"], actors["owner"])
    assert whole["locked"] is True
    assert all(s["status"] == "LOCKED" for s in whole["sections"])

    with pytest.raises(access.PackLocked) as e:
        service.update_pack(session, approved["id"], actors["owner"],
                            name="Changed after the fact")
    assert "raise an amendment" in str(e.value)


def test_an_approved_pack_cannot_be_regenerated(session, committee, template,
                                                actors):
    """The tabled pack shows the same numbers next quarter. That is the point."""
    approved = _approve(session, committee, template, actors)
    with pytest.raises(access.PackLocked):
        generation.generate(session, approved["id"], actors["owner"])


# =============================================================== amendment


def test_an_amendment_supersedes_rather_than_rewrites(session, committee,
                                                      template, actors):
    approved = _approve(session, committee, template, actors)
    fresh = generation.amend(
        session, approved["id"], actors["owner"],
        reason="The coverage figure was read from the wrong period.")

    from backend.models.playbook import PlaybookPack

    original = session.get(PlaybookPack, int(approved["id"]))
    assert original.status == "SUPERSEDED"
    assert original.approved_at is not None, (
        "what the committee actually saw is still readable")

    assert fresh["status"] == "DRAFT"
    assert fresh["amends_pack_id"] == approved["id"]
    assert fresh["amendment_reason"].startswith("The coverage figure")

    carried = service.pack(session, fresh["id"], actors["owner"])
    assert [s["title"] for s in carried["sections"]] == [
        "Portfolio performance", "Origination quality"]
    # The carried blocks lose their figures on purpose: sharing snapshot rows
    # with the superseded pack would make refreshing one appear to change the
    # other.
    assert all(b["figure"] is None for s in carried["sections"]
               for b in s["blocks"])


def test_an_amendment_needs_a_reason(session, committee, template, actors):
    approved = _approve(session, committee, template, actors)
    with pytest.raises(service.InvalidPlaybook) as e:
        generation.amend(session, approved["id"], actors["owner"], reason="  ")
    assert "why it was needed" in str(e.value)


# ================================================================== history


def test_every_change_leaves_a_line_saying_who_and_through_which_door(
        session, pack, actors):
    from sqlalchemy import select

    from backend.models.playbook import PlaybookEvent

    service.update_pack(session, pack["id"], actors["owner"],
                        name="A better name")
    generation.generate(session, pack["id"], actors["owner"])

    events = session.execute(
        select(PlaybookEvent).where(PlaybookEvent.pack_id == pack["id"])
        .order_by(PlaybookEvent.id)).scalars().all()
    actions = [e.action for e in events]
    assert "created" in actions and "updated" in actions
    assert "generated" in actions

    updated = next(e for e in events if e.action == "updated")
    assert updated.author_id == actors["owner"].user_id
    assert updated.source == "UI"
    assert updated.changes["name"][1] == "A better name"
    assert updated.at_version is not None


# ---------------------------------------------------------------- helpers


def _steward(actors, session):
    from sqlalchemy import select

    from backend.api.permissions import Principal, Role
    from backend.db.models import User

    row = session.execute(select(User).where(
        User.role == "DATA_STEWARD",
        User.username.like("pb.steward.%"))).scalars().first()
    return Principal(user_id=int(row.id), role=Role.DATA_STEWARD)


def _ready_pack(session, committee, template, actors, period: str = "2025-01"):
    """A pack with nothing blocking it, short of the approval itself."""
    made = service.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period=period,
        comparison_period="2024-12",
        meeting_at=datetime.now(UTC) + timedelta(days=7),
        owner_id=actors["owner"].user_id)
    generation.generate(session, made["id"], actors["owner"])

    # Every content edit FIRST, then every review. The other order fails, and
    # correctly: editing section two bumps the pack version, which invalidates
    # the approval already given on section one. That is the rule this product
    # exists to enforce, and a helper that worked around it would be testing a
    # pack no reviewer had actually read.
    whole = service.pack(session, made["id"], actors["owner"])
    for section in whole["sections"]:
        for block in section["blocks"]:
            if block["block_type"] == "NARRATIVE" and not block["body"]:
                service.update_block(session, block["id"], actors["owner"],
                                     body="Written by a person.")
        service.update_section(session, section["id"], actors["owner"],
                               owner_id=actors["author"].user_id,
                               reviewer_id=actors["reviewer"].user_id)
    _answer_findings(session, made["id"])
    for section in whole["sections"]:
        service.review_section(session, section["id"], actors["reviewer"],
                               decision="APPROVED")
    service.set_pack_status(session, made["id"], actors["owner"],
                            status="CONTRIBUTOR_REVIEW")
    service.set_pack_status(session, made["id"], actors["owner"],
                            status="REVIEW")
    return service.set_pack_status(session, made["id"], actors["owner"],
                                   status="READY_FOR_APPROVAL")


def _answer_findings(session, pack_id: int) -> None:
    """Acknowledge whatever the thresholds raised, so approval is not blocked.

    Written as the committee answering its findings rather than as the test
    deleting them, because a test that removes the finding is not testing the
    same pack a person would be approving.
    """
    from sqlalchemy import select

    from backend.models.playbook import PlaybookFinding

    for found in session.execute(
            select(PlaybookFinding)
            .where(PlaybookFinding.pack_id == int(pack_id))).scalars():
        if found.status == "OPEN":
            found.status = "ACKNOWLEDGED"
            found.response = "Noted by the committee."
    session.flush()


def _approve(session, committee, template, actors, period: str = "2025-01"):
    ready = _ready_pack(session, committee, template, actors, period)
    return service.set_pack_status(session, ready["id"], actors["approver"],
                                   status="APPROVED")
