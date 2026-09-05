"""Answering what the pack raised — and the one answer that needs a name.

A finding is the product's memory of something material. The tests here are
about what a person can do with one, and about the two doors that stay shut:
an assistant cannot dismiss one, and a dismissal without a written reason is
refused however senior the person is.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models.playbook import SOURCE_AI, PlaybookEvent, PlaybookFinding
from backend.playbook import access, generation, readiness
from backend.playbook import findings as find
from backend.playbook import service as pb

pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
def raised(session, pack, actors):
    """A pack carrying at least one finding, raised by a real rule.

    The template's materiality rules fire against the real lake, so if the
    figures happen not to move this fixture plants one directly — with a
    real rule_key and factual basis, so what is answered below is the same
    shape as what generation produces.
    """
    generation.generate(session, pack["id"], actors["owner"])
    rows = list(session.execute(
        select(PlaybookFinding)
        .where(PlaybookFinding.pack_id == int(pack["id"]))).scalars())
    if not rows:
        planted = PlaybookFinding(
            pack_id=int(pack["id"]), finding_type="DETERIORATION",
            severity="HIGH", title="Retail default rate above its band",
            description="The observed rate sits above the agreed band.",
            factual_basis="Observed 6.88% against a band ceiling of 6.50%.",
            metric_id="retail.default_rate", period="2025-01",
            rule_key="default_rate_band", status="OPEN",
            rule_detail={"comparison": "above", "threshold": 6.5,
                         "observed": 6.88},
            fingerprint="planted-for-the-findings-tests")
        session.add(planted)
        session.flush()
        rows = [planted]
    return rows[0]


# ============================================================== reading them


def test_findings_come_back_most_serious_first(session, pack, actors, raised):
    session.add(PlaybookFinding(
        pack_id=int(pack["id"]), finding_type="DATA_QUALITY", severity="LOW",
        title="A minor gap", factual_basis="One row was missing.",
        fingerprint="ordering-low", status="OPEN"))
    session.add(PlaybookFinding(
        pack_id=int(pack["id"]), finding_type="THRESHOLD_BREACH",
        severity="CRITICAL", title="A serious breach",
        factual_basis="Well outside the band.", fingerprint="ordering-crit",
        status="OPEN"))
    session.flush()

    listed = find.findings(session, actors["owner"], pack_id=pack["id"])
    severities = [f["severity"] for f in listed]
    assert severities[0] == "CRITICAL", severities
    assert severities[-1] == "LOW", severities


def test_a_finding_carries_the_rule_that_raised_it(session, pack, actors,
                                                   raised):
    """Without the rule and its inputs, a finding is an assertion."""
    one = find.finding(session, int(raised.id), actors["owner"])
    assert one["rule_key"], "which rule fired"
    assert one["factual_basis"], "on what numbers"
    assert one["answered"] is False


def test_somebody_outside_the_committee_sees_no_findings(session, pack, actors,
                                                          raised):
    """Asking about a specific pack is not-found, not an empty list.

    An empty list would confirm the pack exists and say the caller may see it
    but there is nothing to see. Not-found says neither.
    """
    with pytest.raises(access.PackNotFound):
        find.findings(session, actors["outsider"], pack_id=pack["id"])

    # And the unscoped list, which is a legitimate question anybody may ask,
    # simply contains none of this committee's findings.
    everything = find.findings(session, actors["outsider"])
    assert int(raised.id) not in [f["id"] for f in everything]


def test_a_finding_cannot_be_read_by_its_id_from_outside(session, actors,
                                                          raised):
    """The IDOR shape: a finding id is not a capability."""
    with pytest.raises(access.PackNotFound):
        find.finding(session, int(raised.id), actors["outsider"])


def test_open_only_hides_what_has_been_answered(session, pack, actors, raised):
    find.respond(session, int(raised.id), actors["owner"],
                 status="ACKNOWLEDGED")
    still = find.findings(session, actors["owner"], pack_id=pack["id"],
                          open_only=True)
    assert int(raised.id) not in [f["id"] for f in still]


# ============================================================= answering them


def test_acknowledging_a_finding_records_who_and_through_which_door(
        session, pack, actors, raised):
    find.respond(session, int(raised.id), actors["owner"],
                 status="ACKNOWLEDGED")
    event = session.execute(
        select(PlaybookEvent).where(
            PlaybookEvent.pack_id == int(pack["id"]),
            PlaybookEvent.entity_type == "finding")
        .order_by(PlaybookEvent.id.desc())).scalars().first()
    assert event is not None
    assert event.author_id == actors["owner"].user_id
    assert event.source == "UI"


def test_calling_it_explained_without_the_explanation_is_refused(session,
                                                                 actors,
                                                                 raised):
    with pytest.raises(pb.InvalidPlaybook) as e:
        find.respond(session, int(raised.id), actors["owner"],
                     status="EXPLAINED")
    assert "does not say how" in str(e.value)


def test_an_explanation_lands_on_the_finding(session, actors, raised):
    answered = find.respond(
        session, int(raised.id), actors["owner"], status="EXPLAINED",
        response="Driven by the two 2024 vintages, which are being reworked.")
    assert answered["status"] == "EXPLAINED"
    assert "2024 vintages" in answered["response"]
    assert answered["answered"] is True


def test_answering_findings_moves_the_readiness_check(session, pack, actors,
                                                      raised):
    before = readiness.assess(session, _row(session, pack)).check("findings")
    find.respond(session, int(raised.id), actors["owner"],
                 status="ACKNOWLEDGED")
    after = readiness.assess(session, _row(session, pack)).check("findings")
    assert after.progress >= before.progress
    assert not [r for r in after.reasons
                if str(raised.title) in r.message]


def _row(session, pack):
    from backend.models.playbook import PlaybookPack

    return session.get(PlaybookPack, int(pack["id"]))


def test_a_contributor_may_answer_but_not_dismiss(session, actors, raised):
    find.respond(session, int(raised.id), actors["author"],
                 status="ACKNOWLEDGED")
    with pytest.raises(access.PackDenied) as e:
        find.respond(session, int(raised.id), actors["author"],
                     status="DISMISSED", reason="Not material.")
    assert "reviewer access" in str(e.value)


# ============================================================ the dismissal


def test_dismissing_without_a_reason_is_refused(session, actors, raised):
    with pytest.raises(pb.InvalidPlaybook) as e:
        find.respond(session, int(raised.id), actors["reviewer"],
                     status="DISMISSED")
    assert "needs a reason" in str(e.value)


def test_a_dismissal_records_the_reason_the_name_and_the_time(session, actors,
                                                              raised):
    out = find.respond(
        session, int(raised.id), actors["reviewer"], status="DISMISSED",
        reason="The band was recalibrated last quarter and this rule has not "
               "been updated yet.")
    assert out["status"] == "DISMISSED"
    assert "recalibrated" in out["dismissed_reason"]
    assert out["dismissed_by"] == actors["reviewer"].user_id
    assert out["dismissed_at"] is not None


def test_an_assistant_cannot_dismiss_a_finding_even_holding_owner_access(
        session, actors, raised):
    """The ceiling is not what stops this. The operation is.

    `actors["owner"]` holds OWNER on the committee, which is the most access
    there is. Arriving through the AI door, the same person's grant is capped
    at EDITOR — still above the REVIEWER this operation needs. What refuses it
    is the explicit check on the operation itself.
    """
    with pytest.raises(access.PackDenied) as e:
        find.respond(session, int(raised.id), actors["owner"],
                     status="DISMISSED", reason="It is fine.",
                     source=SOURCE_AI)
    assert "It needs a name against it" in str(e.value)

    session.expire_all()
    assert str(session.get(PlaybookFinding, int(raised.id)).status) == "OPEN"


def test_an_assistant_may_still_acknowledge_one(session, actors, raised):
    """The refusal is narrow. An agent noting that it has seen something is
    not the same as an agent deciding it does not matter."""
    out = find.respond(session, int(raised.id), actors["owner"],
                       status="ACKNOWLEDGED", source=SOURCE_AI)
    assert out["status"] == "ACKNOWLEDGED"


# =============================================================== reopening


def test_a_dismissed_finding_can_be_reopened_and_keeps_its_reason(session,
                                                                  actors,
                                                                  raised):
    find.respond(session, int(raised.id), actors["reviewer"],
                 status="DISMISSED", reason="Judged immaterial at the time.")
    back = find.reopen(session, int(raised.id), actors["approver"],
                       why="The committee asked for this to be looked at "
                           "again.")
    assert back["status"] == "OPEN"
    assert "immaterial at the time" in back["dismissed_reason"], (
        "the earlier judgement stays visible; both are part of the record")


def test_reopening_needs_a_reason(session, actors, raised):
    find.respond(session, int(raised.id), actors["owner"],
                 status="ACKNOWLEDGED")
    with pytest.raises(pb.InvalidPlaybook):
        find.reopen(session, int(raised.id), actors["owner"], why="  ")


def test_reopening_something_already_open_says_so(session, actors, raised):
    with pytest.raises(pb.InvalidPlaybook) as e:
        find.reopen(session, int(raised.id), actors["reviewer"],
                    why="Looking again.")
    assert "already open" in str(e.value)


# ========================================== the two lists that must agree


def test_answered_means_the_same_thing_to_findings_and_to_readiness():
    """One of these decides what a screen shows; the other decides whether a
    pack may go for approval. If they disagreed, a pack could read as fully
    answered and still be blocked, with nothing on screen saying why."""
    assert find.ANSWERED == readiness.FINDING_ANSWERED
