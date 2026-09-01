"""
§210 and §204: a record for every answer, over the real store and routes.

    §210: "Assurance Record written for every answer."

Every answer, which includes the ones that are not analyses. A metadata
answer, a clarification, an unsupported response and a controlled failure all
get a record, and those are the turns where a missing record would matter
most: "CreditProbe declined to answer" is a claim about the product that
somebody will eventually dispute.

Why this file needs the database and the other two do not
-----------------------------------------------------------
The rules being tested here are about the ROUND TRIP. A verdict that is
correct in memory and wrong after a write and a read is a real defect and an
invisible one: the review screen would show a plausible number for a record
whose checks say something else. So these tests write, read back, and compare
— including the fingerprint, which is the thing that would silently stop
matching the first time a column changed shape.
"""

from __future__ import annotations

import pytest

from backend.assurance import access as ac
from backend.assurance import comparison as cmp
from backend.assurance import dimensions as dm
from backend.assurance import honesty as hn
from backend.assurance import record as rc
from backend.assurance import reviews as rvs
from backend.assurance import store as st
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")


@pytest.fixture
def clean():
    """Every test in this file owns the table.

    The records under test are compared by count and by view membership, and
    a leftover row from another test would make both meaningless.
    """
    from sqlalchemy import text

    from backend.db.engine import get_session

    def wipe() -> None:
        with get_session() as session:
            session.execute(text("DELETE FROM assurance_records"))
            session.commit()

    wipe()
    yield
    wipe()


def a_record(**kwargs) -> rc.Record:
    made = rc.Record(
        answer_id=kwargs.pop("answer_id", "a-1"),
        investigation_id=kwargs.pop("investigation_id", "inv-1"),
        user_id=kwargs.pop("user_id", None),
        project_id=kwargs.pop("project_id", ""),
        question=kwargs.pop("question", "what moved in Contracting?"),
        answer_type=kwargs.pop("answer_type", "succeeded"),
        portfolio_scope=kwargs.pop("scope", "corporate"),
        build_sha=kwargs.pop("build_sha", "sha-1"),
        intelligence_release_id=kwargs.pop("release", "ir-1"),
    )
    fails = set(kwargs.pop("fail", ()))
    skips = set(kwargs.pop("skip", ()))
    for name in dm.all_subcomponents():
        if name in fails:
            made.checks.append(rc.check(name, rc.FAIL,
                                        detail="deliberately failed"))
        elif name in skips:
            made.checks.append(rc.check(name, rc.SKIPPED))
        else:
            made.checks.append(rc.check(name, rc.PASS))
    for key, value in kwargs.items():
        setattr(made, key, value)
    return rc.seal(made)


# ============================================================ the round trip


@db
def test_a_record_survives_the_round_trip_with_its_verdict(clean):
    stored_id = st.write(a_record(), turn_index=0, model_route="ROUTINE")
    assert stored_id

    back = st.get(stored_id)

    assert back is not None
    assert back.overall_status == rc.HIGH_ASSURANCE
    assert back.operational_assurance == 100.0
    assert back.coverage_pct == 100.0
    assert back.model_route == "ROUTINE"
    assert len(back.checks) == len(dm.all_subcomponents())


@db
def test_the_fingerprint_still_matches_after_a_write_and_a_read(clean):
    """The check that would silently stop working the first time a column
    changed shape — and whose failure would look like tampering."""
    back = st.get(st.write(a_record()))

    assert st.verify(back)["intact"] is True


@db
def test_a_tampered_record_is_reported_rather_than_repaired(clean):
    from sqlalchemy import text

    from backend.db.engine import get_session

    stored_id = st.write(a_record())
    with get_session() as session:
        session.execute(
            text("UPDATE assurance_records SET question = :q "
                 "WHERE assurance_record_id = :id"),
            {"q": "a different question", "id": stored_id})
        session.commit()

    verdict = st.verify(st.get(stored_id))

    assert verdict["intact"] is False
    assert verdict["expected"] != verdict["stored"]


@db
def test_the_stored_verdict_is_not_recomputed_on_read(clean):
    """§208: "Do not rewrite historical scores." The status comes back as a
    value, not as a method somebody could call under today's weights."""
    back = st.get(st.write(a_record(fail={"business_invariants"})))

    assert back.overall_status == rc.FAILED
    assert back.operational_assurance is None
    assert back.critical_failure_count == 1
    assert not hasattr(back, "overall")


# ==================================== §210 a record for every kind of answer


@db
@pytest.mark.parametrize("answer_type", [
    "succeeded", "partial", "needs_clarification", "rejected", "failed",
])
def test_every_kind_of_answer_gets_a_record(clean, answer_type):
    """Including the ones that are not analyses. A turn where CreditProbe
    declined is a turn somebody will dispute."""
    stored_id = st.write(a_record(answer_id=f"a-{answer_type}",
                                  answer_type=answer_type))

    back = st.get(stored_id)

    assert back is not None
    assert back.answer_type == answer_type


@db
def test_a_thread_returns_its_turns_in_order(clean):
    for index in range(3):
        st.write(a_record(answer_id=f"a-{index}", question=f"turn {index}"),
                 turn_index=index)

    turns = st.for_investigation("inv-1")

    assert [t.turn_index for t in turns] == [0, 1, 2]
    assert [t.question for t in turns] == ["turn 0", "turn 1", "turn 2"]


# ================================================== §199 the feedback linkage


@db
def test_feedback_increments_a_counter_and_moves_no_score(clean):
    stored_id = st.write(a_record(answer_id="a-fb"))
    before = st.get(stored_id)

    assert st.note_feedback("a-fb", bad=1) is True
    after = st.get(stored_id)

    assert after.bad_feedback_count == 1
    # Every scoring field is untouched. This is §199 as a property of the
    # data rather than as a promise.
    assert after.overall_status == before.overall_status
    assert after.operational_assurance == before.operational_assurance
    assert after.coverage_pct == before.coverage_pct
    assert after.checks == before.checks
    assert after.fingerprint == before.fingerprint


@db
def test_feedback_on_an_answer_with_no_record_is_a_quiet_no(clean):
    assert st.note_feedback("a-nothing", bad=1) is False


# ====================================================== §200 the rerun link


@db
def test_a_rerun_links_to_its_original_without_editing_it(clean):
    versions = {"facilities": "v1"}
    original = st.write(a_record(answer_id="a-1", fail={"figure_grounding"},
                                 data_versions=versions))
    rerun = st.write(a_record(answer_id="a-2", data_versions=versions),
                     turn_index=1)

    assert st.mark_superseded(original, rerun) is True
    before, after = st.get(original), st.get(rerun)

    assert before.superseded_by == rerun
    assert after.rerun_of == original
    # The original keeps its failure. A "fix" that improved a record by
    # rewriting it would show improvement in every case.
    assert before.overall_status == rc.FAILED

    verdict = cmp.compare(before, after)
    assert verdict.verdict == cmp.IMPROVED


@db
def test_the_review_list_reads_what_was_written(clean):
    st.write(a_record(answer_id="a-1", user_id=None,
                      fail={"business_invariants"}))
    st.write(a_record(answer_id="a-2", investigation_id="inv-2"),
             turn_index=0)

    rows = st.recent(limit=50)
    listing = rvs.build(ac.Viewer(role="ADMIN"), view=rvs.FAILED,
                        records=rows)

    assert len(rows) == 2
    assert len(listing.rows) == 1
    assert listing.rows[0]["critical_failures"] == 1
    assert hn.honest(listing.rows[0]), hn.check_payload(listing.rows[0])


# =============================================================== §204 the API


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def admin() -> dict[str, str]:
    return {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}


def analyst() -> dict[str, str]:
    return {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "2"}


def test_the_dimension_catalogue_is_open_to_every_signed_in_role(client):
    """What CreditProbe measures about itself is not privileged. A user shown
    a score is entitled to know what it is a score OF."""
    body = client.get("/api/v1/intelligence/dimensions",
                      headers=analyst()).json()

    assert len(body["dimensions"]) == 6
    assert body["subcomponent_count"] >= 90
    assert body["operational_assurance_label"] == rc.ASSURANCE_LABEL
    assert "accuracy" not in body["operational_assurance_label"].lower()


def test_an_unknown_investigation_is_a_404_not_a_403(client):
    """A caller who could tell "not yours" from "does not exist" could
    enumerate the estate's Investigation ids."""
    assert client.get("/api/v1/investigations/nope/assurance",
                      headers=admin()).status_code == 404


@db
def test_an_analyst_may_not_read_another_users_investigation(client, clean):
    st.write(a_record(answer_id="a-1", user_id=1))

    refused = client.get("/api/v1/investigations/inv-1/assurance",
                         headers=analyst())

    assert refused.status_code == 404


@db
def test_the_owner_reads_their_own_review(client, clean):
    st.write(a_record(answer_id="a-1", user_id=2))

    body = client.get("/api/v1/investigations/inv-1/assurance",
                      headers=analyst()).json()

    assert body["header"]["investigation_id"] == "inv-1"
    assert len(body["dimensions"]) == 6
    assert body["thread"]["averaged"] is False
    # An analyst gets the summary, not the build-level detail.
    assert body["detail_level"] == ac.SUMMARY
    assert "prompt_versions" not in body


@db
def test_a_reviewer_sees_inside_the_machine(client, clean):
    st.write(a_record(answer_id="a-1", user_id=2,
                      prompt_versions={"planner": "v3"}))

    body = client.get("/api/v1/investigations/inv-1/assurance",
                      headers=admin()).json()

    assert body["prompt_versions"] == {"planner": "v3"}
    assert "detail_level" not in body


@db
def test_the_turn_timeline_route_returns_the_thread(client, clean):
    for index in range(2):
        st.write(a_record(answer_id=f"a-{index}", user_id=1,
                          question=f"turn {index}"), turn_index=index)

    body = client.get("/api/v1/investigations/inv-1/assurance/turns",
                      headers=admin()).json()

    assert [t["turn"] for t in body["turns"]] == [1, 2]
    assert "COMPARE_WITH_RERUN" in body["actions"]


@db
def test_a_rerun_needs_its_cost_confirmed(client, clean):
    """§204: "cost-confirmed where live calls are required". A route that
    quietly spent a bank's tokens because somebody clicked "compare" is what
    this prevents."""
    stored_id = st.write(a_record(answer_id="a-1", user_id=1))

    refused = client.post("/api/v1/investigations/inv-1/assurance/rerun",
                          json={"assurance_record_id": stored_id},
                          headers=admin())
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "cost_not_confirmed"

    accepted = client.post("/api/v1/investigations/inv-1/assurance/rerun",
                           json={"assurance_record_id": stored_id,
                                 "cost_confirmed": True},
                           headers=admin())
    assert accepted.status_code == 200
    assert accepted.json()["original"] == stored_id


@db
def test_a_rerun_is_administrator_only(client, clean):
    stored_id = st.write(a_record(answer_id="a-1", user_id=2))

    refused = client.post("/api/v1/investigations/inv-1/assurance/rerun",
                          json={"assurance_record_id": stored_id,
                                "cost_confirmed": True},
                          headers=analyst())

    assert refused.status_code == 403


@db
def test_the_comparison_route_guards_both_records(client, clean):
    versions = {"facilities": "v1"}
    mine = st.write(a_record(answer_id="a-1", user_id=2,
                             data_versions=versions))
    theirs = st.write(a_record(answer_id="a-2", user_id=1,
                               investigation_id="inv-1",
                               data_versions=versions), turn_index=1)

    refused = client.get(
        f"/api/v1/investigations/inv-1/assurance/compare"
        f"?before={mine}&after={theirs}", headers=analyst())

    assert refused.status_code == 404


@db
def test_the_studio_review_list_is_a_table_of_what_the_caller_may_see(client,
                                                                     clean):
    st.write(a_record(answer_id="a-1", user_id=1))

    body = client.get("/api/v1/intelligence/investigation-reviews",
                      headers=admin()).json()

    assert body["presentation"] == "table"
    assert len(body["views"]) == len(rvs.VIEWS)
    assert body["count"] == 1
    assert set(body["counts"]) == set(rvs.VIEWS)


@db
def test_the_dimension_contribution_route_reports_roles(client, clean):
    stored_id = st.write(a_record(answer_id="a-1", user_id=1,
                                  fail={"business_invariants"}))

    body = client.get(f"/api/v1/intelligence/dimension-contribution/"
                      f"{stored_id}", headers=admin()).json()

    assert body["decided_by_gate"] is True
    assert body["equal_contribution"] is False
    assert body["overall_status"] == rc.FAILED


@db
def test_every_route_payload_passes_section_212(client, clean):
    """The rules run against the actual HTTP responses, not against a
    hand-built dictionary that happens to be honest."""
    st.write(a_record(answer_id="a-1", user_id=1,
                      fail={"business_invariants"}))

    review = client.get("/api/v1/investigations/inv-1/assurance",
                        headers=admin()).json()
    listing = client.get("/api/v1/intelligence/investigation-reviews",
                         headers=admin()).json()

    header = dict(review["header"])
    header["thread"] = review["thread"]
    header["feedback"] = review["feedback"]
    assert hn.honest(header), hn.check_payload(header)

    for row in listing["rows"]:
        assert hn.honest(row), hn.check_payload(row)
