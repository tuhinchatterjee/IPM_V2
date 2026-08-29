"""
§16-§18 — teaching-case governance, and the pack that does not fake approval.

    §16: "AUTO_VALIDATED cases must remain unavailable to production
          retrieval by default."
    §18: "Do not mark it approved."

All 2,453 cases in the library are AUTO_VALIDATED. That means production
retrieves nothing from it, and the single most tempting change in this whole
phase is the one line that would make the number look better. These tests
exist to make that line fail.
"""

from __future__ import annotations

import pytest

from backend.teaching import review_pack as rp
from backend.teaching import status as st
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")


# ==================================================== §16 the status model


def test_the_statuses_section_16_names_all_exist():
    for name in ("DRAFT", "AUTO_VALIDATED", "REJECTED", "RETIRED"):
        assert getattr(st, name) in st.STATUSES

    assert st.HUMAN_REVIEWED in st.STATUSES
    assert st.HUMAN_APPROVED in st.STATUSES
    assert st.SYSTEM_REFERENCE_VALIDATED in st.STATUSES


def test_human_approved_is_the_status_approval_already_meant():
    """Aliased rather than renamed: `may_approve` has always refused an
    approval without a named human, and renaming the stored value would
    rewrite 2,453 rows and every audit event referencing them."""
    assert st.HUMAN_APPROVED == st.APPROVED
    assert st.SYSTEM_REFERENCE_VALIDATED == st.SYSTEM_VALIDATED


def test_every_status_says_what_it_means():
    """One gloss, defined once. Otherwise the Studio, the API and the review
    workbench each invent their own."""
    for status in st.STATUSES:
        assert len(st.STATUS_MEANS[status]) > 30, status


def test_auto_validated_is_not_retrievable():
    """The rule that keeps the library honest, and the line somebody will
    eventually be tempted to change.

    All 2,453 cases are in this state. Making it retrievable would light up
    every retrieval metric in the product and would mean production is being
    taught by 2,453 examples no person has read.
    """
    assert st.AUTO_VALIDATED not in st.RETRIEVABLE
    assert st.retrievable(st.AUTO_VALIDATED).ok is False


def test_reviewed_is_not_approved():
    """§16's new state exists precisely to keep these apart."""
    assert st.HUMAN_REVIEWED not in st.RETRIEVABLE
    assert st.retrievable(st.HUMAN_REVIEWED).ok is False


def test_only_a_named_human_approval_is_retrievable_by_default():
    assert st.retrievable(st.HUMAN_APPROVED).ok is True
    for status in st.STATUSES:
        if status in (st.APPROVED, st.SYSTEM_VALIDATED):
            continue
        assert st.retrievable(status).ok is False, status


def test_system_reference_validated_needs_an_explicit_policy():
    """§16: "Optionally allow SYSTEM_REFERENCE_VALIDATED only under an
    explicit Administrator policy and visible label"."""
    off = st.retrievable(st.SYSTEM_REFERENCE_VALIDATED)
    on = st.retrievable(st.SYSTEM_REFERENCE_VALIDATED,
                        system_validated_enabled=True)

    assert off.ok is False
    assert "not governed on" in off.reason
    assert on.ok is True


def test_client_data_is_never_retrievable_whatever_the_status():
    for status in st.STATUSES:
        assert st.retrievable(status, system_validated_enabled=True,
                              sensitivity=st.CLIENT).ok is False, status


def test_a_reviewed_case_can_still_be_approved_or_refused():
    """A reviewer who read a case must be able to act on it."""
    for target in (st.APPROVED, st.REJECTED, st.SME_REVIEW_REQUIRED,
                   st.RETIRED):
        assert st.may_transition(st.HUMAN_REVIEWED, target).ok, target


def test_nothing_reaches_production_from_reviewed_except_approval():
    """The only edge out of HUMAN_REVIEWED into a retrievable state is the
    one that needs a name on it."""
    onward = st.TRANSITIONS[st.HUMAN_REVIEWED]

    assert onward & st.RETRIEVABLE == {st.APPROVED}


# ================================================= §18 the review pack


def _case(**kwargs):
    class Case:
        pass

    made = Case()
    made.case_id = kwargs.get("case_id", "c-1")
    made.title = kwargs.get("title", "a case")
    made.question = kwargs.get("question", "what moved?")
    made.family_id = kwargs.get("family_id", "SINGLE_DOMAIN_AGGREGATION")
    made.review_status = kwargs.get("review_status", st.AUTO_VALIDATED)
    made.authoring_method = kwargs.get("authoring_method", st.BLUEPRINT)
    made.provenance = kwargs.get("provenance", "blueprint")
    made.tags = kwargs.get("tags", ())
    made.expected_failure_categories = kwargs.get("checks", ())
    return made


def test_the_pack_names_every_risk_class_section_18_lists():
    named = {"permission_tenant_safety", "prompt_injection",
             "business_invariants", "critical_failure", "cross_domain_join",
             "period_logic", "agentic_cockpit", "agentic_project",
             "officer_selection", "agent_selection", "proactive_review",
             "risk_cases", "workflow_approval", "unsupported", "ambiguity"}

    assert named <= set(rp.CLASS_IDS)
    for name in rp.CLASS_IDS:
        assert len(rp.CLASS_WHY[name]) > 30, name


def test_building_a_pack_approves_nothing():
    """§18, stated as a property. The pack is a selection, and selecting is
    not signing."""
    pack = rp.build([_case(case_id=f"c-{i}") for i in range(40)])

    assert pack["approved"] is False
    assert pack["label"] == "REVIEW REQUIRED"
    for row in pack["rows"]:
        assert row["approved"] is False
        assert row["label"] == "REVIEW REQUIRED"


def test_the_pack_excludes_cases_that_are_already_decided():
    """A pack containing approved cases wastes the scarce thing it exists to
    respect."""
    cases = [_case(case_id="a", review_status=st.APPROVED),
             _case(case_id="b", review_status=st.REJECTED),
             _case(case_id="c", review_status=st.RETIRED),
             _case(case_id="d", review_status=st.AUTO_VALIDATED)]

    pack = rp.build(cases)

    assert pack["eligible_cases"] == 1
    assert [r["case_id"] for r in pack["rows"]] == ["d"]


def test_every_row_says_why_it_is_there():
    """A reviewer shown forty cases with no reason reviews them in the order
    they appear."""
    pack = rp.build([_case(case_id=f"c-{i}") for i in range(8)])

    for row in pack["rows"]:
        assert len(row["why"]) > 40, row


def test_a_generated_case_says_that_nobody_has_read_the_words():
    pack = rp.build([_case(authoring_method=st.LLM_GENERATED)])

    assert "generated rather than written" in pack["rows"][0]["why"]


def test_classification_is_from_the_recorded_fields_not_the_prose():
    """A classifier reading the question would put "show me exposure" and
    "show me another client's exposure" in the same class."""
    assert rp.classify(_case(tags=("permission",))) \
        == "permission_tenant_safety"
    assert rp.classify(_case(tags=("injection",))) == "prompt_injection"
    assert rp.classify(_case(family_id="AMBIGUITY_GATE")) == "ambiguity"
    assert rp.classify(_case(family_id="MULTI_DOMAIN_JOIN")) \
        == "cross_domain_join"


def test_the_pack_reports_the_classes_it_could_not_fill():
    """The finding, not a failure of the pack.

    The library today has no cases at all for permission safety, prompt
    injection, officer selection, agent selection, proactive review, Risk
    Cases or workflow approval — nine of §18's fifteen classes. A pack that
    quietly returned six classes would hide that; reporting the empty ones
    is how it becomes a work list.
    """
    pack = rp.build([_case(case_id=f"c-{i}") for i in range(20)])

    assert "classes_empty" in pack
    assert pack["classes_covered"] + len(pack["classes_empty"]) \
        == len(rp.CLASSES)


def test_the_pack_states_what_production_may_retrieve():
    pack = rp.build([_case()])
    policy = pack["production_retrieval"]

    assert policy["default"] == st.HUMAN_APPROVED
    assert st.AUTO_VALIDATED in policy["never"]
    assert st.HUMAN_REVIEWED in policy["never"]


def test_the_pack_lists_what_a_reviewer_must_be_shown():
    """§17's list. A decision made without the actual plan and the actual
    outcome is a decision about a title."""
    pack = rp.build([_case()])

    for wanted in ("actual plan", "actual outcome", "task DAG",
                   "selected datasets", "assurance", "version history"):
        assert wanted in pack["reviewer_sees"], wanted
    for action in ("APPROVE", "REJECT", "REQUEST_CHANGE", "MARK_RETIRED"):
        assert action in pack["actions"]


# ================================================= over the real library


@db
def test_the_live_library_has_no_approved_cases():
    """Reported rather than fixed. §1: "Do not label AUTO_VALIDATED material
    as HUMAN_APPROVED"."""
    from backend.db.engine import get_session
    from backend.services import teaching_library as tl

    with get_session() as session:
        governance = tl.governance(session)

    assert governance["human_reviewed"] == 0
    assert governance["retrievable_now"] == 0


@db
def test_the_live_pack_builds_and_approves_nothing():
    from backend.db.engine import get_session
    from backend.services import teaching_library as tl

    with get_session() as session:
        pack = tl.review_pack(session)

    assert pack["approved"] is False
    assert pack["rows"]
    assert pack["eligible_cases"] > 0


@db
def test_marking_reviewed_needs_a_name_and_an_assessment():
    """"Somebody looked, no comment" is the state HUMAN_REVIEWED exists to
    distinguish FROM."""
    from backend.db.engine import get_session
    from backend.services import teaching_library as tl

    with get_session() as session:
        with pytest.raises(tl.LibraryError):
            tl.mark_reviewed(session, "anything", reviewer="", note="looked")
        with pytest.raises(tl.LibraryError):
            tl.mark_reviewed(session, "anything", reviewer="Amal", note="")
