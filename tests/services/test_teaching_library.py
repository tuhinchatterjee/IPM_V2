"""
Part A §4-§6 — the teaching library, against the real database.

The three things worth proving here cannot be proved without one, because they
are all about what happens to a case *over time*: an edit does not rewrite an
approval, an approval leaves a record naming who made it, and a case whose
world moves underneath it stops being retrievable without anybody remembering
to look.
"""

from __future__ import annotations

import pytest

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")

if database_available():
    from sqlalchemy import text  # noqa: E402

    from backend.db.engine import SessionLocal  # noqa: E402
    from backend.services import teaching_library as tl  # noqa: E402


@pytest.fixture
def session():
    s = SessionLocal()
    s.execute(text("DELETE FROM teaching_case_events"))
    s.execute(text("DELETE FROM teaching_cases"))
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        s.execute(text("DELETE FROM teaching_case_events"))
        s.execute(text("DELETE FROM teaching_cases"))
        s.commit()
        s.close()


def _case(case_id="tc-1", **over) -> sc.TeachingCase:
    base = dict(
        case_id=case_id, title="Total EAD by sector",
        family_id="SINGLE_DOMAIN_AGGREGATION",
        question="What is total EAD by sector in the latest quarter?",
        objectives=[sc.Objective(id="o1", text="total EAD by sector")],
        analytical_plan_contract={"group_by": ["sector"]},
        concepts=["exposure at default"], operations=["SUM"],
        ontology_version="2.0.0",
    )
    base.update(over)
    return sc.TeachingCase(**base)


# ------------------------------------------------------------------ storing


@db
def test_a_stored_case_lands_validated_but_never_approved(session):
    """§5's line, at the point it is easiest to cross: the code path that
    stores a clean case is exactly where somebody would be tempted to mark it
    approved."""
    row = tl.save(session, _case(), actor="Amal")
    assert row.review_status == st.AUTO_VALIDATED
    assert row.case_version == 1
    assert row.reviewer == ""
    assert row.approved_at is None


@db
def test_the_fingerprint_and_the_denormalised_columns_are_written(session):
    row = tl.save(session, _case())
    assert row.fingerprint == sc.fingerprint(_case())
    assert row.concepts == ["exposure at default"]
    assert row.operations == ["SUM"]
    assert row.body["analytical_plan_contract"] == {"group_by": ["sector"]}


@db
def test_an_invalid_case_is_kept_as_a_draft_with_its_problems_recorded(session):
    """Losing half-written work to an exception teaches authors to stop using
    the tool. The problems go on the event so the author can see them."""
    row = tl.save(session, _case(family_id="MADE_UP"), actor="Amal")
    assert row.review_status == st.DRAFT

    events = tl.history(session, "tc-1")
    assert events and any("family_id" in p
                          for p in events[-1].detail["problems"])


@db
def test_editing_writes_a_new_version_rather_than_changing_the_reviewed_one(
        session):
    """An approved case whose content can change underneath its approval is an
    approval that means nothing."""
    tl.save(session, _case())
    tl.approve(session, "tc-1", reviewer="Amal", note="reads correctly")

    tl.save(session, _case(title="Total EAD by sector, restated"))

    first = tl.version(session, "tc-1", 1)
    second = tl.version(session, "tc-1", 2)
    assert first.review_status == st.APPROVED
    assert first.title == "Total EAD by sector"
    assert second.case_version == 2
    assert second.review_status == st.AUTO_VALIDATED


# ------------------------------------------------------------------ review


@db
def test_an_approval_records_who_made_it_and_why(session):
    tl.save(session, _case())
    row = tl.approve(session, "tc-1", reviewer="Amal", note="checked the plan "
                                                            "against the "
                                                            "ontology")
    assert row.review_status == st.APPROVED
    assert row.reviewer == "Amal"
    assert row.approved_at is not None

    event = tl.history(session, "tc-1")[-1]
    assert event.to_status == st.APPROVED
    assert event.actor == "Amal"
    assert "ontology" in event.note


@db
def test_an_approval_without_a_reason_is_refused(session):
    """An approval with no reasoning is a click, and every case retrieved on
    the strength of it inherits the click."""
    tl.save(session, _case())
    with pytest.raises(tl.LibraryError, match="reason"):
        tl.approve(session, "tc-1", reviewer="Amal", note="  ")


@db
def test_a_machine_cannot_sign_for_a_case(session):
    """§5: do not label LLM-generated cases human reviewed."""
    tl.save(session, _case(authoring_method=st.LLM_GENERATED))
    with pytest.raises(tl.LibraryError, match="human"):
        tl.approve(session, "tc-1", reviewer="validator",
                   reviewer_is_human=False, note="passed every check")


@db
def test_a_case_carrying_client_data_cannot_be_approved(session):
    """§47. The status is not the thing that redeems it."""
    tl.save(session, _case(data_sensitivity=st.CLIENT))
    with pytest.raises(tl.LibraryError, match="client"):
        tl.approve(session, "tc-1", reviewer="Amal", note="looks fine")


@db
def test_a_case_in_a_gated_family_cannot_be_approved_yet(session):
    """ARABIC_QUERY waits on Arabic. Approving into it would put a case in
    front of the model for a capability the product does not have."""
    tl.save(session, _case(family_id="ARABIC_QUERY"))
    with pytest.raises(tl.LibraryError, match="Arabic"):
        tl.approve(session, "tc-1", reviewer="Amal", note="reads well")


@db
def test_a_rejection_is_kept_rather_than_deleted(session):
    """A rejected case records a reading somebody decided was wrong, which is
    worth as much as one they accepted."""
    tl.save(session, _case())
    row = tl.reject(session, "tc-1", reviewer="Bilal",
                    note="the ranking is not what was asked for")
    assert row.review_status == st.REJECTED
    assert tl.latest(session, "tc-1") is not None


@db
def test_an_impossible_transition_is_refused_with_its_reason(session):
    tl.save(session, _case())
    tl.retire(session, "tc-1", actor="Amal", note="superseded")
    with pytest.raises(tl.LibraryError, match="cannot become"):
        tl.approve(session, "tc-1", reviewer="Amal", note="changed my mind")


# --------------------------------------------------------- system validation


@db
def test_a_contract_derived_case_can_be_system_validated(session):
    tl.save(session, _case(authoring_method=st.DERIVED))
    row = tl.system_validate(session, "tc-1", source=st.CERTIFIED_METHOD,
                             provenance="method:sector_concentration@1.4",
                             deterministic_validation_passed=True)
    assert row.review_status == st.SYSTEM_VALIDATED
    assert row.system_source == st.CERTIFIED_METHOD
    assert row.source_provenance.endswith("@1.4")


@db
def test_system_validation_refuses_a_holdout_source(session):
    tl.save(session, _case(authoring_method=st.DERIVED))
    with pytest.raises(tl.LibraryError, match="holdout"):
        tl.system_validate(session, "tc-1", source=st.REVIEWED_TEST,
                           provenance="benchmark", from_holdout=True,
                           deterministic_validation_passed=True)


# --------------------------------------------------------------- retrieval


@db
def test_only_approved_cases_reach_a_live_prompt(session):
    tl.save(session, _case("tc-approved"))
    tl.approve(session, "tc-approved", reviewer="Amal", note="checked")
    tl.save(session, _case("tc-draft"))
    tl.save(session, _case("tc-rejected"))
    tl.reject(session, "tc-rejected", reviewer="Amal", note="wrong grain")

    ids = [r.case_id for r in tl.retrievable(session)]
    assert ids == ["tc-approved"]


@db
def test_system_validated_cases_appear_only_when_governed_on(session):
    tl.save(session, _case("tc-sys", authoring_method=st.DERIVED))
    tl.system_validate(session, "tc-sys", source=st.ENGINE_CONTRACT,
                       provenance="engine:ecl@2",
                       deterministic_validation_passed=True)

    assert tl.retrievable(session) == []
    assert [r.case_id for r in
            tl.retrievable(session, system_validated_enabled=True)] == \
        ["tc-sys"]


@db
def test_retrieval_reads_the_latest_version_only(session):
    """A superseded version that was approved before an edit is history, not
    curriculum. Retrieving both would show the model two answers to the same
    question."""
    tl.save(session, _case())
    tl.approve(session, "tc-1", reviewer="Amal", note="checked")
    tl.save(session, _case(title="restated"))
    tl.approve(session, "tc-1", reviewer="Amal", note="checked again")

    rows = tl.retrievable(session)
    assert len(rows) == 1
    assert rows[0].case_version == 2


@db
def test_retrieval_can_be_narrowed_by_family_and_scope(session):
    tl.save(session, _case("tc-corp", family_id="CORPORATE_SCOPE",
                           portfolio_scope=fam.CORPORATE))
    tl.approve(session, "tc-corp", reviewer="Amal", note="checked")
    tl.save(session, _case("tc-plain"))
    tl.approve(session, "tc-plain", reviewer="Amal", note="checked")

    assert [r.case_id for r in
            tl.retrievable(session, portfolio_scope=fam.CORPORATE)] == \
        ["tc-corp"]
    assert [r.case_id for r in
            tl.retrievable(session, family_id="SINGLE_DOMAIN_AGGREGATION")] == \
        ["tc-plain"]


# --------------------------------------------------------------- staleness


@db
def test_the_sweep_takes_a_case_out_of_retrieval_when_its_world_moves(session):
    """The point of the sweep: nobody has to remember to look. An ontology
    release makes the cases that depended on the old one stop being served."""
    tl.save(session, _case())
    tl.approve(session, "tc-1", reviewer="Amal", note="checked")
    assert len(tl.retrievable(session)) == 1

    moved = tl.sweep_stale(session, {st.ONTOLOGY: "3.0.0"})
    assert [r.case_id for r in moved] == ["tc-1"]
    assert tl.latest(session, "tc-1").review_status == st.STALE
    assert tl.latest(session, "tc-1").stale_axes == "ontology"
    assert tl.retrievable(session) == []


@db
def test_the_sweep_leaves_a_case_whose_versions_still_match(session):
    tl.save(session, _case())
    tl.approve(session, "tc-1", reviewer="Amal", note="checked")
    assert tl.sweep_stale(session, {st.ONTOLOGY: "2.0.0"}) == []
    assert len(tl.retrievable(session)) == 1


@db
def test_the_sweep_leaves_drafts_alone(session):
    """Marking drafts stale buries the cases where staleness costs something —
    the ones retrieval is drawing from right now."""
    tl.save(session, _case())
    assert tl.sweep_stale(session, {st.ONTOLOGY: "3.0.0"}) == []
    assert tl.latest(session, "tc-1").review_status == st.AUTO_VALIDATED


@db
def test_revalidation_does_not_restore_an_approval(session):
    """The case was approved against a world that has since changed. A person
    decides whether the approval survives that, not the sweep that noticed."""
    tl.save(session, _case())
    tl.approve(session, "tc-1", reviewer="Amal", note="checked")
    tl.sweep_stale(session, {st.ONTOLOGY: "3.0.0"})

    row = tl.revalidate(session, "tc-1", current={st.ONTOLOGY: "3.0.0"})
    assert row.review_status == st.AUTO_VALIDATED
    assert row.stale_axes == ""
    assert row.ontology_version == "3.0.0"
    assert tl.retrievable(session) == []


# ------------------------------------------------------- duplicates and counts


@db
def test_a_duplicate_is_found_by_what_it_teaches_not_by_its_words(session):
    """§15. Two authors writing the same lesson under different ids is the
    ordinary case, not the adversarial one."""
    tl.save(session, _case("tc-first"))
    assert [r.case_id for r in tl.duplicates(session, _case("tc-second"))] == \
        ["tc-first"]


@db
def test_coverage_reports_every_family_including_the_empty_ones(session):
    """§13 asks for quality by family. A total hides the empty families behind
    the crowded ones."""
    tl.save(session, _case())
    tl.approve(session, "tc-1", reviewer="Amal", note="checked")

    rows = {c["family_id"]: c for c in tl.coverage(session)}
    assert len(rows) == len(fam.FAMILIES)
    assert rows["SINGLE_DOMAIN_AGGREGATION"]["approved"] == 1
    assert rows["SINGLE_DOMAIN_AGGREGATION"]["gap"] is False
    assert rows["ECL_MOVEMENT"]["gap"] is True
    # A gated family is deferred, not a gap.
    assert rows["ARABIC_QUERY"]["gap"] is False
    assert rows["ARABIC_QUERY"]["gated_on"]


@db
def test_the_summary_counts_what_section_13_asks_to_be_counted(session):
    tl.save(session, _case("tc-expert", difficulty=sc.EXPERT))
    tl.save(session, _case("tc-thread", family_id="MULTI_TURN_REFERENTS",
                           question="Show the five largest.",
                           conversation_turns=[
                               sc.Turn(turn_index=0,
                                       user_message="Show the five largest."),
                               sc.Turn(turn_index=1,
                                       user_message="Only Contracting.",
                                       conversation_action="MODIFY_PREVIOUS")]))

    found = tl.summary(session)
    assert found["total"] == 2
    assert found["expert_or_adversarial"] == 1
    assert found["multi_turn"] == 1
    assert found["families_available"] == len(fam.AVAILABLE)
    assert "ECL_MOVEMENT" in found["gaps"]


@db
def test_the_factory_reads_plain_data_rather_than_importing_the_backend(
        session):
    """Same rule as the review queue: plain data crosses the line between the
    factory and the product; imports do not."""
    tl.save(session, _case())
    specs = tl.specifications(tl.retrievable(session, limit=10)
                             or [tl.latest(session, "tc-1")])
    assert specs and isinstance(specs[0], dict)
    assert specs[0]["question"].startswith("What is total EAD")
