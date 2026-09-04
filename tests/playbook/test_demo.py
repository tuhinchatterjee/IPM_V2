"""The seeded committees, and rolling them forward without losing anything.

The point of a demonstration seed is that it is still true tomorrow. These
tests are about the three properties that make it so: the dates move, the
move is idempotent, and a date a PERSON set is never overwritten by it.

The seed itself is exercised end to end in `test_demo_seed.py`; here the
concern is the re-anchor, which is the part that runs unattended.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.models.playbook import PlaybookCommittee, PlaybookPack
from backend.playbook import demo
from backend.playbook import service as pb

pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
def seeded(session, committee, template, actors):
    """A committee marked as seeded, anchored a fortnight ago.

    Built through the same fixtures as everything else and then MARKED,
    rather than run through the seed script: the marker is what `refresh`
    reads, and a test that ran the whole script would be testing the script
    rather than the property.
    """
    anchor = date(2026, 3, 1)
    row = session.get(PlaybookCommittee, int(committee["id"]))
    row.demo_origin = demo.PLAYBOOK_DEMO
    row.demo_anchor_date = anchor

    made = pb.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period="2025-01",
        comparison_period="2024-12",
        meeting_at=datetime(2026, 3, 15, 10, tzinfo=UTC))
    pack = session.get(PlaybookPack, int(made["id"]))
    pack.demo_origin = demo.PLAYBOOK_DEMO
    pack.data_freeze_at = datetime(2026, 3, 8, 10, tzinfo=UTC)
    session.flush()
    return {"committee": row, "pack": pack, "anchor": anchor}


# ================================================================ the marker


def test_only_committees_the_seed_built_are_candidates(session, seeded,
                                                       committee, actors,
                                                       steward):
    """A committee a person created is never touched.

    The marker is a stored column rather than a guess from the name, which is
    what makes this true even for somebody who names their own committee
    exactly what the seed names its own.
    """
    theirs = pb.create_committee(
        session, steward, name=seeded["committee"].name + " (theirs)",
        business_area="Retail Credit Risk", cadence="MONTHLY")
    session.flush()

    found = {int(c.id) for c in demo.seeded(session)}
    assert int(seeded["committee"].id) in found
    assert int(theirs["id"]) not in found


def test_a_committee_with_no_anchor_is_left_alone(session, seeded):
    """Seeded without an anchor is a fault, and guessing one would move every
    date by an arbitrary amount."""
    seeded["committee"].demo_anchor_date = None
    session.flush()

    out = demo.refresh(session, today=date(2026, 4, 1))
    entry = next(c for c in out.committees
                 if c.code == seeded["committee"].code)
    assert entry.shift_days == 0
    assert entry.moved == []


# ================================================================= the shift


def _mine(out, seeded):
    """This test's own committee out of the report.

    Scoped deliberately: the suite shares a database with the seeded
    demonstration, and a global count would pass or fail depending on whether
    somebody had run the seed script — which is not what any of these tests
    are about.
    """
    return next(c for c in out.committees
                if c.code == seeded["committee"].code)


def test_dates_move_by_the_days_since_the_anchor(session, seeded):
    before = seeded["pack"].meeting_at
    later = seeded["anchor"] + timedelta(days=17)

    out = demo.refresh(session, today=later)
    session.expire_all()

    pack = session.get(PlaybookPack, int(seeded["pack"].id))
    assert (pack.meeting_at - before).days == 17
    mine = _mine(out, seeded)
    assert len(mine.moved) == 2, "the meeting and the data freeze both moved"


def test_the_freeze_keeps_its_distance_from_the_meeting(session, seeded):
    """Both dates move by the same amount, so the week between them stands.

    Moving the meeting without the freeze would produce a pack whose data was
    due after the meeting it is for.
    """
    gap = seeded["pack"].meeting_at - seeded["pack"].data_freeze_at
    demo.refresh(session, today=seeded["anchor"] + timedelta(days=9))
    session.expire_all()

    pack = session.get(PlaybookPack, int(seeded["pack"].id))
    assert pack.meeting_at - pack.data_freeze_at == gap


def test_running_twice_on_one_day_changes_nothing(session, seeded):
    """What makes this safe to put in a start-up script."""
    later = seeded["anchor"] + timedelta(days=5)
    demo.refresh(session, today=later)
    session.expire_all()
    settled = session.get(PlaybookPack, int(seeded["pack"].id)).meeting_at

    again = demo.refresh(session, today=later)
    session.expire_all()
    assert _mine(again, seeded).moved == []
    assert session.get(PlaybookPack, int(seeded["pack"].id)).meeting_at == settled
    assert "already anchored" in again.summary


def test_a_dry_run_reports_and_writes_nothing(session, seeded):
    before = seeded["pack"].meeting_at
    anchor = seeded["committee"].demo_anchor_date

    out = demo.refresh(session, today=anchor + timedelta(days=11),
                       dry_run=True)
    session.expire_all()

    assert len(_mine(out, seeded).moved) == 2, "it says what it would do"
    assert out.dry_run is True
    assert "would move" in out.summary
    pack = session.get(PlaybookPack, int(seeded["pack"].id))
    assert pack.meeting_at == before, "and does none of it"
    assert session.get(
        PlaybookCommittee, int(seeded["committee"].id)
    ).demo_anchor_date == anchor, "the anchor does not move either"


# ================================================== somebody else's commitment


def test_a_meeting_date_a_person_moved_is_held_back(session, seeded, actors):
    """A committed meeting date is other people's diaries.

    The pack's history is append-only and records which field changed and
    through which door, so a human edit is findable — and is left exactly as
    the person set it.
    """
    chosen = datetime(2026, 5, 20, 14, tzinfo=UTC)
    pb.update_pack(session, int(seeded["pack"].id), actors["owner"],
                   meeting_at=chosen)
    session.flush()

    out = demo.refresh(session, today=seeded["anchor"] + timedelta(days=30))
    session.expire_all()

    entry = _mine(out, seeded)
    assert any("meeting_at" in held for held in entry.held)
    assert len(entry.held) == 1
    assert "held back because a person set" in out.summary

    pack = session.get(PlaybookPack, int(seeded["pack"].id))
    assert pack.meeting_at == chosen, "the person's date stands"
    # And the field they did NOT touch still moves, so a held date does not
    # freeze the whole committee.
    assert any("data_freeze_at" in moved for moved in entry.moved)


def test_forcing_overwrites_it_and_says_so(session, seeded, actors):
    """The only way past a human commitment, and it is reported."""
    chosen = datetime(2026, 5, 20, 14, tzinfo=UTC)
    pb.update_pack(session, int(seeded["pack"].id), actors["owner"],
                   meeting_at=chosen)
    session.flush()

    out = demo.refresh(session, today=seeded["anchor"] + timedelta(days=30),
                       force=True)
    session.expire_all()

    assert out.forced is True
    assert _mine(out, seeded).held == []
    pack = session.get(PlaybookPack, int(seeded["pack"].id))
    assert pack.meeting_at != chosen


def test_a_change_by_the_system_is_not_a_persons_commitment(session, seeded):
    """The seed's own writes must not look like somebody's decision.

    Otherwise the first refresh after a seed holds back every date it just
    set, and the demonstration never rolls forward at all.
    """
    pb.record(session, entity_type="pack", action="updated",
              pack=seeded["pack"], changes={"meeting_at": [None, "then"]},
              grant=None)
    session.flush()

    out = demo.refresh(session, today=seeded["anchor"] + timedelta(days=4),
                       dry_run=True)
    entry = next(c for c in out.committees
                 if c.code == seeded["committee"].code)
    assert entry.held == [], "a SYSTEM event is not a person moving a date"


# ================================================== what it will not touch


def test_content_and_status_are_never_moved(session, seeded, actors):
    """Only two fields, and everything else is somebody's work."""
    pack = seeded["pack"]
    before = (str(pack.status), str(pack.name), int(pack.version),
              str(pack.period))

    demo.refresh(session, today=seeded["anchor"] + timedelta(days=13))
    session.expire_all()

    now = session.get(PlaybookPack, int(pack.id))
    assert (str(now.status), str(now.name), int(now.version),
            str(now.period)) == before


def test_the_only_fields_that_move_are_the_declared_ones():
    """A list that grows silently is how a demonstration tool starts editing
    content. Asserted so adding to it is a deliberate act."""
    assert demo.FIELDS == ("meeting_at", "data_freeze_at")


# ================================================== the committees themselves


def test_three_committees_are_defined_and_they_are_different():
    assert len(demo.COMMITTEES) == 3
    codes = {c.code for c in demo.COMMITTEES}
    assert len(codes) == 3

    # Different cadences and different period grains, which is the point of
    # having three: a monthly-measured book and a quarterly-measured one are
    # different products to run.
    assert {c.cadence for c in demo.COMMITTEES} >= {"MONTHLY", "QUARTERLY"}
    assert {c.period_kind for c in demo.COMMITTEES} == {"month", "quarter"}

    # And they sit at different points in the cycle on the day of a
    # demonstration, so the three of them together show the whole lifecycle
    # rather than three copies of one state.
    assert len({c.current_status for c in demo.COMMITTEES}) >= 2


def test_every_seeded_metric_is_one_the_catalogue_actually_has():
    """A template naming a metric that does not exist produces a pack of
    blanks, and the failure would only show up when somebody generated it."""
    from backend.metrics import service as metrics

    for spec in demo.COMMITTEES:
        for section in spec.template["sections"]:
            for block in section.get("blocks") or []:
                metric_id = str(
                    (block.get("config") or {}).get("metric_id") or "")
                if not metric_id:
                    continue
                metrics.resolve(metric_id)  # raises if it is not there


def test_every_materiality_rule_is_one_the_engine_can_evaluate():
    """A rule the engine refuses is a threshold nobody is being held to."""
    from backend.playbook import materiality

    for spec in demo.COMMITTEES:
        rules = materiality.parse(spec.template["materiality"])
        assert len(rules) == len(spec.template["materiality"]), spec.code
        for rule in rules:
            assert rule.key
            assert rule.severity in (
                "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


def test_every_rule_names_a_metric_the_same_template_puts_on_a_pack():
    """A threshold on a metric the pack does not show is a finding a reader
    cannot check against anything in front of them."""
    for spec in demo.COMMITTEES:
        shown = {
            str((block.get("config") or {}).get("metric_id") or "")
            for section in spec.template["sections"]
            for block in section.get("blocks") or []
        } - {""}
        for rule in spec.template["materiality"]:
            metric_id = str(rule.get("metric_id") or "")
            if metric_id:
                assert metric_id in shown, f"{spec.code}: {rule['key']}"
