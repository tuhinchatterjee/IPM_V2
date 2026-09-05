"""A committee, its people and a pack — built for one test and then removed.

Every fixture here creates its own users and its own committee, so two tests
running against the same database cannot see each other's rows. The teardown
goes through the ORM's cascades rather than a truncate, because a truncate in a
test suite that shares a database with a demonstration is how somebody's demo
disappears an hour before they present it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL not reachable")


def _principal(user_id: int | None, role: str = "ANALYST"):
    from backend.api.permissions import Principal, Role

    return Principal(user_id=user_id, role=Role(role))


@pytest.fixture
def session():
    from backend.db.engine import get_session

    with get_session() as handle:
        yield handle
        handle.rollback()


@pytest.fixture
def people(session):
    """Five accounts with the roles a committee needs, removed afterwards.

    Named by what they DO on the committee rather than by a person's name, so
    a failing assertion reads as "the approver could not approve" rather than
    as a name nobody recognises.
    """
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    made = {}
    for key, role in (("owner", "ANALYST"), ("author", "ANALYST"),
                      ("reviewer", "ANALYST"), ("approver", "ANALYST"),
                      ("outsider", "ANALYST"), ("steward", "DATA_STEWARD")):
        user = User(username=f"pb.{key}.{tag}", email=f"pb.{key}.{tag}@test",
                    first_name=key.title(), last_name="Tester", role=role,
                    is_active=True)
        user.password_hash = "x"
        session.add(user)
        session.flush()
        made[key] = user
    ids = [int(u.id) for u in made.values()]
    yield made

    # Cleaned in a SEPARATE, COMMITTED session, after this test's own work is
    # rolled back. Most tests here never commit, so a delete on `session`
    # would be discarded along with everything else — harmless. But the tests
    # that go through the API commit deliberately, because the API opens its
    # own connection and cannot see an uncommitted row, and those users then
    # survive the rollback and outlive the test.
    #
    # They are not inert once they do. A later test that looks a person up by
    # what they ARE rather than by which fixture made them finds the oldest
    # leftover instead of its own, and fails for a reason that has nothing to
    # do with the change under test. That has happened here once already.
    from sqlalchemy import delete

    from backend.db.engine import get_session
    from backend.db.models import User
    from backend.models.collaboration import CollaborationAudit
    from backend.models.platform import ExportRecord

    session.rollback()
    with get_session() as cleanup:
        # The Planner writes a collaboration_audit row when a project is
        # created, and that table references `users` without a cascade.
        cleanup.execute(delete(CollaborationAudit).where(
            CollaborationAudit.actor_id.in_(ids)))
        # `export_records` is append-only and outlives the object it
        # describes, so it references `users` without a cascade — correctly,
        # since the point of the table is that a download history survives
        # what was downloaded.
        cleanup.execute(delete(ExportRecord).where(
            ExportRecord.user_id.in_(ids)))
        cleanup.execute(delete(User).where(User.id.in_(ids)))
        cleanup.commit()


@pytest.fixture
def steward(people):
    return _principal(int(people["steward"].id), "DATA_STEWARD")


@pytest.fixture
def committee(session, people, steward):
    """A committee with an owner, an author, a reviewer and an approver."""
    from backend.playbook import service

    made = service.create_committee(
        session, steward, name=f"Test Credit Committee {uuid.uuid4().hex[:6]}",
        business_area="Retail Credit Risk", cadence="MONTHLY",
        meeting_weekday=2, purpose="A committee that exists for one test.")

    for key, business, level in (
            ("owner", "PACK_OWNER", "OWNER"),
            ("author", "MEMBER", "CONTRIBUTOR"),
            ("reviewer", "MEMBER", "REVIEWER"),
            ("approver", "CHAIR", "APPROVER")):
        service.add_member(
            session, made["id"], steward, user_id=int(people[key].id),
            business_role=business, access_role=level,
            title=f"{key.title()} of things")
    session.flush()
    yield made

    from backend.models.playbook import PlaybookCommittee

    row = session.get(PlaybookCommittee, int(made["id"]))
    if row is not None:
        session.delete(row)
    session.flush()


@pytest.fixture
def actors(people):
    """The principals, ready to be passed to any service function."""
    return {key: _principal(int(user.id)) for key, user in people.items()}


@pytest.fixture
def template(session, committee, steward):
    """A two-section shape carrying two governed retail metrics.

    Uses real metric ids from the shipped catalogue rather than invented ones,
    so a generation in these tests reads the real lake and a real failure in
    the metric layer shows up here rather than being mocked away.
    """
    from backend.playbook import service

    return service.create_template(
        session, steward, name="Monthly Credit Pack",
        committee_id=committee["id"], status="PUBLISHED",
        sections=[
            {"key": "portfolio", "title": "Portfolio performance",
             "purpose": "How the book performed this period.",
             "required": True, "order": 0,
             "narrative_instructions": "Two sentences on direction and cause.",
             "blocks": [
                 {"type": "KPI", "title": "Retail default rate",
                  "config": {"metric_id": "retail.default_rate"}},
                 {"type": "NARRATIVE", "title": "Commentary"},
             ]},
            {"key": "origination", "title": "Origination quality",
             "purpose": "What we have been writing.",
             "required": True, "order": 1,
             "blocks": [
                 {"type": "KPI", "title": "Application bad rate",
                  "config": {"metric_id": "retail.application_bad_rate"}},
             ]},
        ],
        materiality_rules=[
            {"key": "default_rate.level", "metric_id": "retail.default_rate",
             "comparison": "above", "threshold": 5.0, "severity": "HIGH",
             "finding_type": "THRESHOLD_BREACH",
             "basis": "Retail credit risk appetite statement, §4.2"},
            {"key": "bad_rate.level", "metric_id": "retail.application_bad_rate",
             "comparison": "above", "threshold": 99.0, "severity": "MEDIUM",
             "finding_type": "THRESHOLD_BREACH"},
        ])


@pytest.fixture
def pack(session, committee, template, actors):
    """An open pack for next month's meeting, laid out from the template."""
    from backend.playbook import service

    return service.create_pack(
        session, actors["owner"], committee_id=committee["id"],
        template_id=template["id"], period="2025-01",
        comparison_period="2024-12",
        meeting_at=datetime.now(UTC) + timedelta(days=10),
        owner_id=actors["owner"].user_id)
