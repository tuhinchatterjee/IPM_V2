"""Regulatory Intelligence. §29-§38.

The suite is mostly about refusals, because most of the value in this
subsystem is in what it declines to do. Two in particular are worth naming.

**Extraction may not dismiss a clause.** §31 forbids claiming a non-credit
clause is irrelevant without review where ambiguity exists, and the way that
is enforced is that `classify()` has no path to NOT_CREDIT_RELATED at all.
Only a reviewer's REJECT — NOT RELEVANT sets it.

**Supersession is not deletion.** §34 says do not ask which one to delete,
and the enforcement is that SUPERSEDES_FROM_DATE without a date is refused.
A restatement of a prior period still has to quote what applied then.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.regulatory import contradictions as cd
from backend.regulatory import pipeline as pl
from backend.regulatory import promotion as pm
from backend.regulatory import requirements as rq
from backend.regulatory import review as rv
from backend.regulatory import schema as sc

STAGE_2 = ("4.2 An exposure shall be classified as Stage 2 where the "
           "probability of default has increased significantly since "
           "initial recognition.")
ECL = ("5.1 The expected credit loss shall be calculated as PD multiplied "
       "by LGD multiplied by EAD.")
FIRE = "9.3 The premises shall be insured against fire and flood."


def _requirement(text: str = STAGE_2, **over) -> rq.Requirement:
    fields = {"document_id": "doc-1", "page": 12, "section_number": "4.2",
              "concepts": ("pd", "stage")}
    fields.update(over)
    return rq.propose(text, **fields)


# ============================================================== §30 schema


def test_the_fifteen_requirement_types_all_have_a_meaning():
    """A type nobody can describe gets applied to whatever the extractor
    could not classify."""
    assert len(rq.TYPES) == 15
    for kind in rq.TYPES:
        assert len(rq.TYPE_MEANS[kind]) > 30, kind


def test_only_a_calculation_threshold_or_classification_configures_a_method():
    """§36 offers CONFIGURE IN ANALYSIS STUDIO for a calculation. Offering it
    for a governance requirement produces a method that computes nothing."""
    assert rq.CONFIGURABLE == {rq.CALCULATION, rq.THRESHOLD,
                               rq.CLASSIFICATION}
    assert rq.GOVERNANCE not in rq.CONFIGURABLE


def test_a_clause_that_carries_its_own_numbering_is_cited_without_a_page():
    """"4.2 An exposure shall…" locates itself. An anchoring failure that
    lost the page has not lost the citation, and refusing this requirement
    would report a real defect where there is none."""
    numbered = _requirement(page=0, section_number="")

    assert numbered.paragraph == "4.2"
    assert numbered.cited is True
    assert rq.validate(numbered) == []


def test_a_requirement_with_no_citation_at_all_is_refused_at_validation():
    """§29: every extracted item retains page/section/paragraph citations.
    A requirement that cannot say where it came from cannot be defended to a
    regulator."""
    loose = rq.propose("An exposure shall be classified as Stage 2.",
                       document_id="doc-1")

    problems = rq.validate(loose)

    assert loose.cited is False
    assert any("no page, section or paragraph" in p for p in problems)


def test_the_type_is_determined_from_cue_words_or_admits_it_defaulted():
    """Defaulting every unrecognised clause to DEFINITION and reporting it as
    a determination fills the queue with confident mislabels."""
    kind, determined = rq.type_of(ECL)
    assert kind == rq.CALCULATION and determined is True

    kind, determined = rq.type_of("The quick brown fox.")
    assert kind == rq.DEFINITION and determined is False


# ========================================================== §31 relevance


def test_an_unmatched_clause_is_ambiguous_and_never_dismissed():
    """The safeguard. "We found no credit cue" and "this clause does not
    matter" are different statements, and only a person may make the
    second."""
    relevance, topics = rq.classify(FIRE)

    assert relevance == rq.AMBIGUOUS
    assert topics == ()
    assert relevance != rq.NOT_CREDIT_RELATED


def test_classification_never_returns_not_credit_related():
    """Enforced by there being no path to it, not by a convention."""
    for text in (FIRE, ECL, STAGE_2, "", "the board shall meet quarterly"):
        assert rq.classify(text)[0] != rq.NOT_CREDIT_RELATED


def test_only_a_reviewer_may_mark_a_clause_not_credit_related():
    requirement = _requirement(FIRE, section_number="9.3")
    assert requirement.relevance == rq.AMBIGUOUS

    rv.decide(requirement, rv.REJECT_NOT_RELEVANT, reviewer="alice",
              reason="a premises insurance clause, not a credit requirement")

    assert requirement.relevance == rq.NOT_CREDIT_RELATED
    assert requirement.reviewer == "alice"


def test_the_twenty_six_credit_topics_are_found_in_real_wording():
    found = rq.topics_in(STAGE_2)

    assert "stage_sicr" in found
    assert "pd_lgd_ead" in found
    assert len(rq.TOPIC_IDS) == 26


def test_a_short_token_cannot_match_inside_a_longer_word():
    """" pd " padded rather than "pd", or every mention of SPDR is a credit
    topic."""
    assert "pd_lgd_ead" not in rq.topics_in("The SPDR index fund")


# ========================================================= §30 confidence


def test_confidence_is_computed_from_evidence_and_says_what_was_missing():
    """A reviewer looking at 0.45 can see which four things were missing
    rather than being asked to trust a classifier's self-assessment."""
    strong = _requirement()
    weak = rq.propose("Something applies.", document_id="d", page=0)

    assert strong.interpretation_confidence > weak.interpretation_confidence
    assert any("missing" in why for why in weak.confidence_because)
    assert any("the page it came from is known"
               in why for why in strong.confidence_because)


def test_confidence_never_exceeds_one_however_much_evidence_there_is():
    requirement = _requirement()
    score, _ = rq.confidence_from_evidence(requirement, type_determined=True)
    assert 0.0 <= score <= 1.0


def test_a_truncated_excerpt_says_so():
    """A clause cut mid-sentence reads as though the regulator stopped
    talking."""
    long_clause = "The bank shall do the following. " * 200
    requirement = rq.propose(long_clause, document_id="d", page=1)

    assert requirement.excerpt_truncated is True
    assert len(requirement.excerpt) <= rq.MAX_EXCERPT + 8


# ============================================================ §28 metadata


def test_a_consultation_paper_is_never_in_force_whatever_its_dates_say():
    """A requirement extracted from a proposal that reached retrieval would
    have the bank complying with a rule that does not exist."""
    proposal = sc.Circular(circular_id="c", document_type=sc.CONSULTATION,
                           effective=date(2020, 1, 1))
    real = sc.Circular(circular_id="d", document_type=sc.CIRCULAR,
                       effective=date(2020, 1, 1))

    assert proposal.in_force_on(date(2026, 1, 1)) is False
    assert real.in_force_on(date(2026, 1, 1)) is True


def test_an_unclassified_document_still_retrieves():
    """Every document uploaded before §28 existed carries UNCLASSIFIED.
    Treating it as not-in-force would empty the corpus and read as data
    loss rather than caution."""
    legacy = sc.Circular(circular_id="c", effective=date(2020, 1, 1))

    assert legacy.document_type == sc.UNCLASSIFIED
    assert legacy.in_force_on(date(2026, 1, 1)) is True
    assert sc.UNCLASSIFIED in sc.NEEDS_TYPE_CONFIRMATION


# ============================================================ §29 pipeline


def test_the_pipeline_refuses_a_skipped_stage():
    progress = pl.Progress(document_id="d")

    with pytest.raises(pl.PipelineError) as caught:
        pl.advance(progress, pl.RELEASED)

    assert "would skip" in str(caught.value)


def test_the_optional_configuration_stage_may_be_skipped():
    """§29 marks it optional, and a governance requirement configures
    nothing in Analysis Studio."""
    progress = pl.Progress(document_id="d")
    for stage in pl.STAGES[1:pl.STAGES.index(pl.RELEASED) + 1]:
        pl.advance(progress, stage, by="t")

    pl.advance(progress, pl.COMPLETE, by="t")

    assert progress.stage == pl.COMPLETE


def test_nothing_is_retrievable_before_release():
    progress = pl.Progress(document_id="d")
    for stage in pl.STAGES[1:pl.STAGES.index(pl.RELEASED)]:
        assert progress.retrievable is False, progress.stage
        pl.advance(progress, stage, by="t")
    assert progress.retrievable is False

    pl.advance(progress, pl.RELEASED, by="t")
    assert progress.retrievable is True


def test_a_release_needs_two_pairs_of_eyes():
    progress = pl.Progress(document_id="d")
    for stage in pl.STAGES[1:pl.STAGES.index(pl.VALIDATED) + 1]:
        pl.advance(progress, stage, by="t")

    ok, why = pl.may_release(progress, requirements_adjudicated=True,
                             validation_passed=True, approver="alice",
                             reviewer="alice")
    assert ok is False
    assert "two hats" in why

    ok, _ = pl.may_release(progress, requirements_adjudicated=True,
                           validation_passed=True, approver="bob",
                           reviewer="alice")
    assert ok is True


def test_every_stage_says_what_it_establishes():
    assert len(pl.STAGES) == 16
    for stage in pl.STAGES:
        assert len(pl.MEANS[stage]) > 30, stage


# ============================================================== §32 review


def test_the_review_panel_puts_the_source_before_our_reading():
    """A reviewer shown the machine's interpretation before the regulator's
    sentence is reviewing the interpretation."""
    panel = rv.panel(_requirement())

    assert list(panel) == ["requirement_id", "source", "understanding",
                           "conflicts", "actions"]
    assert panel["source"]["excerpt"]
    assert "not" in panel["understanding"]["this_is_our_reading"]


def test_every_decision_needs_a_reason_including_approval():
    """"Approved" with no assessment is indistinguishable from nobody
    having looked."""
    with pytest.raises(rv.ReviewError) as caught:
        rv.decide(_requirement(), rv.APPROVE, reviewer="alice", reason="  ")

    assert "reason" in str(caught.value)


def test_the_seven_actions_are_section_32s_seven():
    assert len(rv.ACTIONS) == 7
    assert rv.REJECT_NOT_RELEVANT in rv.ACTIONS
    for action in rv.ACTIONS:
        assert len(rv.ACTION_MEANS[action]) > 30, action


def test_a_correction_needs_the_corrected_reading_not_just_a_complaint():
    with pytest.raises(rv.ReviewError):
        rv.decide(_requirement(), rv.CORRECT_INTERPRETATION,
                  reviewer="alice", reason="wrong", target="")


def test_a_decided_requirement_is_not_silently_re_decided():
    requirement = _requirement()
    rv.decide(requirement, rv.APPROVE, reviewer="alice", reason="correct")

    with pytest.raises(rv.ReviewError) as caught:
        rv.decide(requirement, rv.REJECT_NOT_RELEVANT, reviewer="bob",
                  reason="changed my mind")

    assert "already APPROVED" in str(caught.value)


def test_deferrals_do_not_count_as_progress():
    """A queue that counted them would report itself finished with every
    difficult requirement still open."""
    a, b = _requirement(), _requirement(ECL, section_number="5.1")
    rv.decide(a, rv.APPROVE, reviewer="alice", reason="fine")
    rv.decide(b, rv.DEFER, reviewer="alice", reason="need legal input")

    progress = rv.queue_progress([a, b])

    assert progress["reviewed"] == 1
    assert progress["parked"] == 1
    assert progress["complete"] is False


def test_the_implications_say_nothing_rather_than_listing_empty_categories():
    bare = rq.propose("A clause.", document_id="d", page=1)

    lines = rv.panel(bare)["understanding"]["implications"]

    assert len(lines) == 1
    assert "look harder" in lines[0]


# =========================================================== §33 correction


def test_a_correction_keeps_both_readings():
    """A year from now somebody asks whether CreditProbe read it right the
    first time, and an edit in place makes that unanswerable."""
    requirement = _requirement()

    record = rv.record_correction(
        requirement, correction="It applies only to retail exposures.",
        reason="corporate is covered by section 6", user_id="u1",
        user_role="SME")

    assert record.original_interpretation == requirement.summary
    assert record.correction == "It applies only to retail exposures."
    assert record.authoritative is False


def test_a_correction_from_one_user_is_not_automatically_authoritative():
    """§33's closing line, as a field rather than a convention."""
    record = rv.record_correction(
        _requirement(), correction="x means y", reason="because",
        user_id="u1", user_role="CRO")

    assert record.authoritative is False
    assert record.to_dict()["activates_nothing"] is True


def test_a_correction_that_only_says_we_are_wrong_is_refused():
    with pytest.raises(rv.ReviewError):
        rv.record_correction(_requirement(), correction="  ", reason="wrong",
                             user_id="u1", user_role="SME")


# ======================================================= §34 contradictions


def _positions() -> tuple[cd.Position, cd.Position]:
    new = cd.Position(kind="requirement", label="new SICR trigger",
                      source="C-2026-01", regulator="SAMA", value=30,
                      unit="days", effective_from=date(2026, 1, 1))
    old = cd.Position(kind="requirement", label="prior SICR trigger",
                      source="C-2024-07", regulator="SAMA", value=60,
                      unit="days", effective_from=date(2024, 7, 1))
    return new, old


def test_the_twelve_classes_and_ten_resolutions_are_complete():
    assert len(cd.CLASSES) == 12
    assert len(cd.RESOLUTIONS) == 10
    for _, means in cd.CLASSES:
        assert len(means) > 40
    for _, means in cd.RESOLUTIONS:
        assert len(means) > 40


def test_there_is_no_resolution_that_simply_deletes_the_other_one():
    """§34: do not ask simply which one to delete."""
    ids = " ".join(cd.RESOLUTION_IDS).lower()

    assert "delete" not in ids
    assert "discard" not in ids
    assert "newer_wins" not in ids


def test_supersession_without_a_date_is_refused():
    new, old = _positions()
    conflict = cd.detect(new, [old])[0]

    with pytest.raises(cd.ContradictionError) as caught:
        cd.resolve(conflict, cd.SUPERSEDES_FROM_DATE,
                   reason="the 2026 circular restates it", by="alice")

    assert "delete the old rule" in str(caught.value)


def test_a_scope_split_without_an_axis_is_refused():
    conflict = cd.Contradiction(conflict_class=cd.SCOPE_OR_PRODUCT_CONFLICT)

    with pytest.raises(cd.ContradictionError):
        cd.resolve(conflict, cd.MORE_SPECIFIC_SCOPE, reason="both apply",
                   by="alice")


def test_keeping_a_conflict_pending_is_not_resolving_it():
    """A queue that counted it as resolved could be emptied without settling
    anything."""
    new, old = _positions()
    conflict = cd.detect(new, [old])[0]
    cd.resolve(conflict, cd.KEEP_LOCAL_PENDING_REVIEW,
               reason="waiting on legal", by="alice")

    assert conflict.resolved is False
    assert conflict.blocking is True
    assert cd.summary([conflict])["unresolved"] == 1


def test_a_conflict_with_a_certified_method_is_critical():
    """Numbers have been produced and shown under that method."""
    new, _ = _positions()
    method = cd.Position(kind="studio_method", label="ecl-staging-v3")

    conflict = cd.detect(new, [method])[0]

    assert conflict.conflict_class == cd.STUDIO_METHOD_CONFLICT
    assert conflict.severity == cd.CRITICAL
    assert conflict.to_dict()["in_production"] is True


def test_the_options_always_include_keeping_both():
    """A reviewer under time pressure is never left with only destructive
    options."""
    new, old = _positions()

    for conflict in cd.detect(new, [old]):
        assert cd.BOTH_APPLY in conflict.available
        assert cd.KEEP_LOCAL_PENDING_REVIEW in conflict.available


def test_two_positions_that_never_overlap_are_not_a_conflict():
    a = cd.Position(kind="requirement", source="A", value=30, unit="d",
                    effective_from=date(2020, 1, 1),
                    effective_to=date(2021, 1, 1))
    b = cd.Position(kind="requirement", source="B", value=60, unit="d",
                    effective_from=date(2024, 1, 1))

    assert cd.detect(a, [b]) == []


# ========================================================= §35/§36 promotion


def test_an_unapproved_requirement_may_not_be_promoted():
    with pytest.raises(pm.PromotionError) as caught:
        pm.promote(_requirement(), by="alice")

    assert "PROPOSED" in str(caught.value)


def test_an_uncited_requirement_may_not_be_promoted():
    """A change to the bank's rules whose justification cannot be located is
    a change nobody can defend."""
    loose = rq.propose("A clause requiring something.", document_id="d")
    rv.decide(loose, rv.APPROVE, reviewer="alice", reason="fine")

    with pytest.raises(pm.PromotionError) as caught:
        pm.promote(loose, by="alice")

    assert "no page, section or paragraph" in str(caught.value)


def test_promotion_produces_drafts_and_changes_nothing():
    """§35: no direct mutation from extraction."""
    requirement = _requirement(ECL, section_number="5.1",
                               concepts=("pd", "lgd", "ead"))
    rv.decide(requirement, rv.APPROVE, reviewer="alice",
              reason="the standard ECL identity")

    drafts = pm.promote(requirement, by="alice")

    assert drafts
    for draft in drafts:
        assert draft.status == pm.DRAFT
        assert draft.applied is False
        assert draft.to_dict()["nothing_changed_yet"] is True
        assert draft.target in rv.PROMOTION_TARGETS


def test_all_five_gates_are_outstanding_on_a_fresh_draft():
    requirement = _requirement(ECL, section_number="5.1")
    rv.decide(requirement, rv.APPROVE, reviewer="alice", reason="fine")
    draft = pm.promote(requirement, by="alice")[0]

    ok, outstanding = pm.may_release(draft)

    assert ok is False
    assert len(outstanding) == 5


def test_a_draft_may_release_only_when_every_gate_is_cleared():
    requirement = _requirement(ECL, section_number="5.1")
    rv.decide(requirement, rv.APPROVE, reviewer="alice", reason="fine")
    draft = pm.promote(requirement, by="alice")[0]

    for gate, _ in pm.GATES[:-1]:
        pm.pass_gate(draft, gate, by="alice")
    assert pm.may_release(draft)[0] is False

    pm.pass_gate(draft, pm.GATES[-1][0], by="alice")
    assert pm.may_release(draft)[0] is True


def test_the_eighteen_promotion_targets_are_a_closed_set():
    assert len(rv.PROMOTION_TARGETS) == 18

    requirement = _requirement(ECL, section_number="5.1")
    rv.decide(requirement, rv.APPROVE, reviewer="alice", reason="fine")

    with pytest.raises(pm.PromotionError) as caught:
        pm.promote(requirement, targets=("whatever I like",), by="alice")

    assert "eighteen promotion targets" in str(caught.value)


def test_a_draft_method_carries_all_fifteen_parts_and_is_not_certified():
    """§36: do not auto-certify."""
    requirement = _requirement(ECL, section_number="5.1",
                               concepts=("pd", "lgd", "ead"))
    rv.decide(requirement, rv.APPROVE, reviewer="alice", reason="fine")

    method = pm.draft_method(requirement, by="alice")

    assert set(method["parts"]) == set(pm.METHOD_PARTS)
    assert len(pm.METHOD_PARTS) == 15
    assert method["status"] == pm.DRAFT
    assert method["certification"]["certified"] is False
    assert method["certification"]["auto_certified"] is False


def test_an_empty_method_part_says_why_it_is_empty():
    """A blank formula alone reads as a method somebody forgot to finish."""
    requirement = _requirement(ECL, section_number="5.1")
    rv.decide(requirement, rv.APPROVE, reviewer="alice", reason="fine")

    method = pm.draft_method(requirement, by="alice")

    assert "without specifying" in method["established"]["formula"]
    assert "cannot be certified" in method["established"]["validation_cases"]


def test_a_governance_requirement_does_not_configure_a_method():
    governance = rq.propose(
        "The board shall approve the provisioning policy annually.",
        document_id="d", page=3, section_number="2.1")
    rv.decide(governance, rv.APPROVE, reviewer="alice", reason="fine")

    with pytest.raises(pm.PromotionError) as caught:
        pm.draft_method(governance, by="alice")

    assert "computes nothing" in str(caught.value)
