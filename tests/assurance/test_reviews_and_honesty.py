"""
§199-§203 and §207-§212, over the modules that read stored records.

What is different about this file
----------------------------------
tests/assurance/test_part_f.py tests the arithmetic: outcomes, gates, weights
and the verdict, all in memory. This file tests everything that happens
AFTER a record is stored — the views, the comparison, the trends, the access
policy and §212's seven impossibilities.

The distinction matters because the failures are different in kind. The
arithmetic fails by being wrong. Everything here fails by being plausible: a
comparison screen that says IMPROVED about two runs over different data, a
trend line drawn through four records, a review list that shows somebody
else's Investigation. Each of those looks correct.

No database is needed
----------------------
Every function under test takes records rather than fetching them, which is
why they can be tested exhaustively and quickly, and why the access policy
can be exercised against every combination of viewer and subject rather than
the two a fixture would produce.
"""

from __future__ import annotations

import pytest

from backend.assurance import access as ac
from backend.assurance import comparison as cmp
from backend.assurance import dimensions as dm
from backend.assurance import honesty as hn
from backend.assurance import record as rc
from backend.assurance import review as rv
from backend.assurance import reviews as rvs
from backend.assurance import store as st
from backend.assurance import trends as tr


def stored(**kwargs) -> st.StoredRecord:
    """A stored record with a plausible passing shape, overridable."""
    row = st.StoredRecord(
        assurance_record_id=kwargs.pop("id", "ar-1"),
        investigation_id=kwargs.pop("investigation_id", "inv-1"),
        user_id=kwargs.pop("user_id", 7),
        question=kwargs.pop("question", "what moved in Contracting?"),
        portfolio_scope=kwargs.pop("scope", "corporate"),
        created_at=kwargs.pop("created_at", "2026-08-01T09:00:00+00:00"),
        overall_status=kwargs.pop("status", rc.VALIDATED),
        operational_assurance=kwargs.pop("score", 88.0),
        coverage_pct=kwargs.pop("coverage", 91.0),
    )
    for key, value in kwargs.items():
        setattr(row, key, value)
    if not row.dimension_results:
        row.dimension_results = {
            name: {"dimension": name, "label": dm.LABELS[name],
                   "measured": True, "score": 90.0, "coverage_pct": 90.0,
                   "passed": 10, "warnings": 0, "failures": 0}
            for name in dm.DIMENSIONS}
    return row


def viewer(**kwargs) -> ac.Viewer:
    return ac.Viewer(
        user_id=kwargs.pop("user_id", 7),
        role=kwargs.pop("role", "ANALYST"),
        tenant_id=kwargs.pop("tenant_id", ""),
        project_ids=frozenset(kwargs.pop("projects", ())),
        shared_investigation_ids=frozenset(kwargs.pop("shared", ())),
        workflow_object_ids=frozenset(kwargs.pop("workflow", ())))


# ================================================== §207 who may read what


def test_a_tenant_mismatch_refuses_even_an_administrator():
    """The one rule no role widens. An administrator administers their own
    bank."""
    decision = ac.may_read(
        viewer(role="ADMIN", tenant_id="bank-a"),
        ac.Subject(investigation_id="inv-1", tenant_id="bank-b"))

    assert decision.allowed is False
    assert "different tenant" in decision.reason


def test_a_role_nobody_placed_reaches_nothing():
    """Fail-closed for the role somebody adds later and forgets to map."""
    decision = ac.may_read(viewer(role="AUDITOR"),
                           ac.Subject(investigation_id="inv-1",
                                      owner_user_id=7))

    assert decision.allowed is False
    assert "not placed" in decision.reason


def test_an_analyst_reads_their_own_investigation():
    decision = ac.may_read(viewer(user_id=7),
                           ac.Subject(investigation_id="inv-1",
                                      owner_user_id=7))

    assert decision.allowed is True
    assert decision.via == ac.OWN


def test_an_analyst_does_not_read_a_colleagues_investigation():
    decision = ac.may_read(viewer(user_id=7),
                           ac.Subject(investigation_id="inv-9",
                                      owner_user_id=9))

    assert decision.allowed is False


def test_a_record_with_no_owner_belongs_to_nobody():
    """It cannot be matched, so it is refused rather than shared."""
    assert ac.may_read(viewer(user_id=7),
                       ac.Subject(investigation_id="inv-9")).allowed is False


def test_a_project_member_reads_the_projects_investigations():
    decision = ac.may_read(
        viewer(user_id=7, projects={"p-1"}),
        ac.Subject(investigation_id="inv-9", project_id="p-1",
                   owner_user_id=9))

    assert decision.via == ac.PROJECT
    # But only as a summary. The build-level detail is an administrative
    # surface, not part of reading a colleague's answer.
    assert decision.visibility == ac.SUMMARY


def test_only_a_reviewer_sees_inside_the_machine():
    ordinary = ac.may_read(viewer(user_id=7),
                           ac.Subject(investigation_id="inv-1",
                                      owner_user_id=7))
    reviewer = ac.may_read(viewer(role="ADMIN"),
                           ac.Subject(investigation_id="inv-1",
                                      owner_user_id=9))

    assert ordinary.full is False
    assert reviewer.full is True


def test_redaction_deletes_rather_than_blanks():
    """A key present with an empty value invites the reader to conclude the
    value was empty, which is a different and false statement."""
    payload = {"prompt_versions": {"planner": "v3"}, "question": "what?"}
    trimmed = ac.redact(payload, ac.Decision(ac.SUMMARY, "summary only"))

    assert "prompt_versions" not in trimmed
    assert trimmed["question"] == "what?"
    assert trimmed["detail_level"] == ac.SUMMARY


def test_the_full_reader_keeps_everything():
    payload = {"prompt_versions": {"planner": "v3"}}
    assert ac.redact(payload, ac.Decision(ac.FULL, "reviewer")) == payload


# ================================================ §186, §187 the review list


def test_the_list_removes_rows_rather_than_refusing_them():
    """A row that says "you may not see this" has already disclosed that the
    Investigation exists."""
    mine = stored(id="ar-1", user_id=7)
    theirs = stored(id="ar-2", user_id=9, investigation_id="inv-9")

    listing = rvs.build(viewer(user_id=7), records=[mine, theirs])

    assert [r["assurance_record_id"] for r in listing.rows] == ["ar-1"]
    assert listing.withheld == 1


def test_low_assurance_includes_the_records_nobody_scored():
    """"No number" is not better than a low number, and separating them would
    let the unscored ones hide."""
    low = stored(id="ar-1", score=42.0)
    unscored = stored(id="ar-2", status=rc.UNVERIFIED, score=None)
    fine = stored(id="ar-3", score=95.0)

    listing = rvs.build(viewer(role="ADMIN"), view=rvs.LOW_ASSURANCE,
                        records=[low, unscored, fine])

    assert {r["assurance_record_id"] for r in listing.rows} == {"ar-1", "ar-2"}


def test_an_unknown_view_falls_back_rather_than_raising():
    """The caller is a URL. A bookmark from a version with a different view
    should show something."""
    listing = rvs.build(viewer(role="ADMIN"), view="WHATEVER",
                        records=[stored()])

    assert listing.view == rvs.RECENT


def test_the_counts_come_from_the_same_predicates_as_the_lists():
    """A count that disagrees with its list is worse than no count."""
    rows = [stored(id="ar-1", status=rc.FAILED),
            stored(id="ar-2", status=rc.NEEDS_REVIEW),
            stored(id="ar-3", bad_feedback_count=2)]
    who = viewer(role="ADMIN")

    tally = rvs.counts(who, records=rows)

    for view in rvs.VIEWS:
        listed = rvs.build(who, view=view, records=rows)
        assert tally[view] == len(listed.rows), view


def test_a_row_carries_six_dimension_indicators_in_a_fixed_order():
    row = rvs.row_for(stored())

    assert [c["dimension"] for c in row["dimensions"]] == list(dm.DIMENSIONS)
    assert [c["short"] for c in row["dimensions"]] == [dm.SHORT[d]
                                                       for d in dm.DIMENSIONS]


def test_an_unmeasured_dimension_shows_as_unmeasured_rather_than_passed():
    """§183 compressed into a single character of screen."""
    row = stored()
    row.dimension_results[dm.AGENTIC] = {"measured": False}

    cells = {c["dimension"]: c["state"]
             for c in rvs.compact_dimensions(row)}

    assert cells[dm.AGENTIC] == "UNMEASURED"
    assert cells[dm.COMPUTATION] == "PASSED"


def test_the_dimension_filter_selects_where_that_dimension_was_the_problem():
    troubled = stored(id="ar-1")
    troubled.dimension_results[dm.COMPUTATION]["failures"] = 1
    fine = stored(id="ar-2")

    listing = rvs.build(viewer(role="ADMIN"),
                        filters=rvs.Filters(dimension=dm.COMPUTATION),
                        records=[troubled, fine])

    assert [r["assurance_record_id"] for r in listing.rows] == ["ar-1"]


def test_an_unrecognised_filter_is_ignored_rather_than_rejected():
    """A stale bookmark should show a list, not an error."""
    filters = rvs.Filters.from_query({"user_id": "7", "nonsense": "x",
                                      "officer_level": "not a number"})

    assert filters.user_id == 7
    assert filters.officer_level is None


def test_every_filter_section_186_names_exists():
    named = {"date", "user", "team", "project", "portfolio scope", "language",
             "officer level", "model route", "Teaching Release", "status",
             "dimension", "feedback", "case family"}
    labels = {label.lower() for _, label in rvs.FILTERS}

    for wanted in named:
        assert any(wanted.lower() in label or label in wanted.lower()
                   for label in labels), wanted


# ======================================================= §189-§199 the review


def test_the_review_always_shows_six_dimensions():
    """A dimension dropped for having no data is a dimension the reader
    concludes was fine."""
    row = stored()
    row.dimension_results = {}

    review = rv.InvestigationReview(record=row)

    assert [d["dimension"] for d in review.dimensions()] == list(dm.DIMENSIONS)


def test_a_mandatory_check_absent_from_the_record_appears_as_skipped():
    """§183's other half, at the surface a reviewer reads."""
    row = stored()
    row.checks = [{"subcomponent": "capability_intent", "outcome": rc.PASS}]

    section = rv.dimension_section(row, dm.COMPUTATION)

    assert "figure_grounding" in section["skipped"]


def test_agentic_work_that_never_happened_is_not_applicable_with_a_reason():
    """§195's exception, and the one place NOT_APPLICABLE is the right
    answer — because an absent run id establishes it deterministically."""
    section = rv.dimension_section(stored(), dm.AGENTIC)

    assert section["applicability"]["applicable"] is False
    assert "No agentic run is recorded" in section["applicability"]["reason"]


def test_an_agentic_run_makes_the_dimension_applicable_whatever_it_found():
    row = stored(agentic_run_id="run-9")

    section = rv.dimension_section(row, dm.AGENTIC)

    assert section["applicability"]["applicable"] is True


def test_the_review_never_offers_hidden_reasoning():
    """§191: "Do not expose hidden chain-of-thought.\""""
    section = rv.dimension_section(stored(), dm.UNDERSTANDING)

    assert "hidden chain of thought" in section["never_shown"]


def test_a_failed_turn_is_retained_in_the_thread_even_after_a_rerun():
    """§210: "failed earlier turn retained"."""
    bad = stored(id="ar-1", status=rc.FAILED, turn_index=0,
                 superseded_by="ar-2")
    good = stored(id="ar-2", status=rc.VALIDATED, turn_index=1,
                  rerun_of="ar-1")

    thread = rv.InvestigationReview(record=good,
                                    thread=[bad, good]).thread_status()

    assert thread["status"] == rc.FAILED
    assert thread["failed_turns"] == ["ar-1"]
    assert thread["averaged"] is False


def test_the_feedback_section_keeps_raw_and_adjudicated_apart():
    """§199. Merging them turns an opinion into a finding."""
    section = rv.feedback_section(stored(good_feedback_count=3,
                                         bad_feedback_count=1))

    assert section["raw_user_feedback"]["bad"] == 1
    assert section["raw_user_feedback"]["changes_score"] is False
    assert section["adjudicated_findings"] == []


def test_a_recommendation_names_the_actual_failure():
    """"Improve grounding" is advice nobody can act on."""
    row = stored()
    row.checks = [{"subcomponent": "relationship_join_path",
                   "outcome": rc.FAIL,
                   "detail": "no join path from facilities to collateral"}]

    steps = rv.improvements(row)

    assert steps[0]["subcomponent"] == "relationship_join_path"
    assert "join path" in steps[0]["because"]


# ============================================================ §200 comparison


def test_two_runs_of_different_questions_are_not_comparable():
    before = stored(id="ar-1", question="what moved in Contracting?")
    after = stored(id="ar-2", question="what moved in Retail?")

    result = cmp.compare(before, after)

    assert result.verdict == cmp.NOT_COMPARABLE
    assert "the question asked differs" in result.reasons[0]


def test_two_runs_over_different_scopes_are_not_comparable():
    before = stored(id="ar-1", scope="corporate")
    after = stored(id="ar-2", scope="retail")

    assert cmp.compare(before, after).verdict == cmp.NOT_COMPARABLE


def test_moved_data_is_reported_rather_than_scored():
    """A difference in the answer is not evidence about the change made."""
    before = stored(id="ar-1", score=70.0,
                    context={"data_versions": {"facilities": "v1"}})
    after = stored(id="ar-2", score=95.0,
                   context={"data_versions": {"facilities": "v2"}})

    result = cmp.compare(before, after)

    assert result.verdict == cmp.CHANGED_DUE_TO_DATA


def test_unrecorded_data_versions_are_not_treated_as_unchanged():
    """Unknown is not "the same". §200 says not to compare without stating
    the difference, and an unstated data version is exactly that."""
    before = stored(id="ar-1", score=70.0, context={})
    after = stored(id="ar-2", score=95.0, context={})

    result = cmp.compare(before, after)

    assert result.verdict == cmp.CHANGED_DUE_TO_DATA
    assert "Neither run recorded" in result.reasons[0]


def test_a_new_critical_failure_outranks_a_higher_score():
    """The gate is not something the score is allowed to average away."""
    versions = {"data_versions": {"facilities": "v1"}}
    before = stored(id="ar-1", score=60.0, critical_failure_count=0,
                    context=dict(versions))
    after = stored(id="ar-2", score=99.0, critical_failure_count=1,
                   context=dict(versions))

    result = cmp.compare(before, after)

    assert result.verdict == cmp.REGRESSED
    assert "Critical failures rose" in result.reasons[0]


def test_a_small_move_is_unchanged_rather_than_improved():
    versions = {"data_versions": {"facilities": "v1"}}
    before = stored(id="ar-1", score=88.0, context=dict(versions))
    after = stored(id="ar-2", score=88.4, context=dict(versions))

    assert cmp.compare(before, after).verdict == cmp.UNCHANGED


def test_a_real_move_is_reported_with_its_size():
    versions = {"data_versions": {"facilities": "v1"}}
    before = stored(id="ar-1", score=70.0, context=dict(versions))
    after = stored(id="ar-2", score=85.0, context=dict(versions))

    result = cmp.compare(before, after)

    assert result.verdict == cmp.IMPROVED
    assert "+15.0" in result.reasons[0]


def test_a_dimension_that_stopped_being_measured_is_flagged():
    """It has not improved by going quiet."""
    before = stored(id="ar-1")
    after = stored(id="ar-2")
    after.dimension_results[dm.JUDGMENT] = {"measured": False}

    rows = {r["dimension"]: r for r in cmp.dimension_diff(before, after)}

    assert rows[dm.JUDGMENT]["lost_coverage"] is True
    assert rows[dm.COMPUTATION]["lost_coverage"] is False


# ==================================================== §201-§203 the six tiles


def test_the_overview_has_no_headline_score():
    """§201. The first thing on the screen must not be the number that hides
    the dimension that failed."""
    body = tr.overview([stored()])

    assert body["headline_score"] is None
    assert len(body["dimensions"]) == 6


def test_a_tile_below_the_sample_floor_reports_no_score():
    """A dimension at 94% over four Investigations is a picture of
    nothing."""
    tiles = {t["dimension"]: t for t in tr.tiles([stored() for _ in range(4)])}

    assert tiles[dm.COMPUTATION]["underpowered"] is True
    assert tiles[dm.COMPUTATION]["score"] is None
    assert tiles[dm.COMPUTATION]["sample"] == 4


def test_a_tile_above_the_floor_reports_one():
    rows = [stored(id=f"ar-{i}") for i in range(tr.MIN_SAMPLE)]

    tiles = {t["dimension"]: t for t in tr.tiles(rows)}

    assert tiles[dm.COMPUTATION]["underpowered"] is False
    assert tiles[dm.COMPUTATION]["score"] == 90.0


def test_a_tile_names_the_subcomponents_that_actually_failed():
    row = stored()
    row.checks = [{"subcomponent": "figure_grounding", "outcome": rc.FAIL,
                   "critical": True, "detail": "17.4% traces to no fact"}]

    tiles = {t["dimension"]: t for t in tr.tiles([row])}
    worst = tiles[dm.COMPUTATION]["worst_subcomponents"]

    assert worst[0]["subcomponent"] == "figure_grounding"
    assert tiles[dm.COMPUTATION]["critical_failures"] == 1


def test_an_unknown_cohort_is_reported_rather_than_guessed():
    body = tr.trend([stored()], "phase of the moon")

    assert body["known"] is False
    assert body["buckets"] == []


def test_a_trend_bucket_carries_its_own_sample_size():
    """§202's "confidence/sample evidence"."""
    rows = [stored(id=f"ar-{i}", intelligence_release_id="ir-1")
            for i in range(3)]

    buckets = tr.trend(rows, "release")["buckets"]

    assert buckets[0]["records"] == 3
    assert buckets[0]["sample_sufficient"] is False
    assert buckets[0]["score"] is None


def test_contribution_reports_roles_rather_than_six_percentages():
    """§203: "Do not imply equal contribution where gates/weights differ.\""""
    body = tr.contribution(stored())

    assert body["equal_contribution"] is False
    roles = {line["dimension"]: line["role"] for line in body["lines"]}
    assert roles[dm.COMPUTATION] == tr.GATE


def test_a_gated_record_shows_no_weights_because_they_never_ran():
    row = stored(status=rc.FAILED, critical_failure_count=1, score=None)
    row.dimension_results[dm.COMPUTATION]["failures"] = 1

    body = tr.contribution(row)
    lines = {line["dimension"]: line for line in body["lines"]}

    assert body["decided_by_gate"] is True
    assert "the gate" in body["how"]
    assert lines[dm.JUDGMENT]["weight_applied"] is None
    assert "failed, and that decided it" in lines[dm.COMPUTATION]["effect"]


def test_an_unmeasured_dimension_is_not_a_pass_in_the_contribution():
    row = stored()
    row.dimension_results[dm.AGENTIC] = {"measured": False}

    lines = {line["dimension"]: line for line in tr.contribution(row)["lines"]}

    assert lines[dm.AGENTIC]["role"] == tr.UNMEASURED
    assert "not a pass" in lines[dm.AGENTIC]["role_means"]


# ========================================================== §208 staleness


def test_a_moved_release_makes_a_record_stale():
    moved = st.staleness({"intelligence_release_id": "ir-1"},
                         {"intelligence_release_id": "ir-2"})

    assert moved == ["a newer Intelligence Release is in force"]


def test_an_axis_the_record_never_captured_is_stale():
    """A blank is not evidence of agreement."""
    moved = st.staleness({}, {"build_sha": "abc"})

    assert "this record recorded none" in moved[0]


def test_an_axis_the_runtime_cannot_report_is_skipped_not_assumed_equal():
    """Reporting a record as current because the comparison could not be
    made is the failure this avoids."""
    assert st.staleness({"build_sha": "abc"}, {}) == []


def test_a_stale_record_keeps_its_verdict_and_reports_a_current_status():
    row = stored(status=rc.HIGH_ASSURANCE)
    row.stale_reasons = ["the application build has changed"]

    assert row.overall_status == rc.HIGH_ASSURANCE
    assert row.status_now == rc.STALE


# ========================================================= §212 score honesty


def test_every_one_of_section_212s_seven_rules_exists():
    assert len(hn.RULES) == 7
    for rule in hn.RULE_IDS:
        assert len(hn.MEANS[rule]) > 30, rule


def test_a_clean_payload_is_honest():
    assert hn.honest({
        "overall_status": rc.VALIDATED,
        "operational_assurance": 88.0,
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "coverage_pct": 91.0,
        "reference_match": {"available": False},
        "critical_failures": 0,
        "skipped_mandatory": [],
        "stale": False,
    })


def test_full_marks_with_a_skipped_mandatory_check_is_refused():
    broken = hn.check_payload({
        "operational_assurance": 100.0, "coverage_pct": 100.0,
        "skipped_mandatory": ["figure_grounding"],
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
    })

    assert {v.rule for v in broken} == {
        "no_full_marks_with_skipped_mandatory"}


def test_calling_the_figure_accuracy_without_a_reference_is_refused():
    broken = hn.check_payload({
        "operational_assurance": 96.0,
        "operational_assurance_label": "Accuracy",
        "reference_match": {"available": False},
    })

    assert broken[0].rule == "no_accuracy_without_a_reference"


def test_the_sentence_explaining_the_absence_is_not_itself_a_violation():
    """"no accuracy figure can be given" is the sentence that makes the
    absence legible. A rule that caught it would delete its own
    explanation."""
    assert hn.honest({
        "operational_assurance": None,
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {
            "available": False,
            "why": "no accuracy figure can be given for a live "
                   "Investigation"},
        "overall_status": rc.UNVERIFIED,
    })


def test_a_real_reference_may_be_called_what_it_is():
    assert hn.honest({
        "operational_assurance": 88.0,
        "operational_assurance_label": "Accuracy against the approved answer",
        "reference_match": {"available": True, "value_pct": 96.0,
                            "source": "benchmark-2026Q1"},
        "overall_status": rc.VALIDATED,
    })


def test_high_assurance_after_a_critical_failure_is_refused():
    broken = hn.check_payload({
        "overall_status": rc.HIGH_ASSURANCE,
        "critical_failures": ["business_invariants"],
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
    })

    assert broken[0].rule == "no_high_assurance_after_a_critical_failure"


def test_validated_with_no_computation_is_refused():
    broken = hn.check_payload({
        "overall_status": rc.VALIDATED,
        "execution_produced_result": False,
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
    })

    assert broken[0].rule == "no_validated_without_a_computation"


def test_a_clean_thread_over_a_failed_turn_is_refused():
    broken = hn.check_payload({
        "overall_status": rc.VALIDATED,
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
        "thread": {"status": rc.VALIDATED, "failed_turns": ["ar-1"],
                   "averaged": False},
    })

    assert broken[0].rule == "no_clean_thread_hiding_a_failed_turn"


def test_an_averaged_thread_is_refused_even_when_nothing_failed():
    broken = hn.check_payload({
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
        "thread": {"status": rc.VALIDATED, "failed_turns": [],
                   "averaged": True},
    })

    assert broken[0].rule == "no_clean_thread_hiding_a_failed_turn"


def test_a_score_that_moves_on_a_thumb_is_refused():
    broken = hn.check_payload({
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
        "feedback": {"raw_user_feedback": {"good": 3, "bad": 0,
                                           "changes_score": True}},
    })

    assert broken[0].rule == "no_score_moved_by_a_thumb"


def test_a_stale_record_presenting_as_current_is_refused():
    broken = hn.check_payload({
        "overall_status": rc.HIGH_ASSURANCE,
        "status_now": rc.HIGH_ASSURANCE,
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
        "stale": True,
    })

    assert broken[0].rule == "no_current_validation_on_a_stale_record"


def test_a_stale_record_with_no_current_status_field_is_also_refused():
    """A reader who sees only the historical verdict is a reader who thinks
    it is current."""
    broken = hn.check_payload({
        "overall_status": rc.VALIDATED,
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "reference_match": {"available": False},
        "stale": True,
    })

    assert broken[0].rule == "no_current_validation_on_a_stale_record"


# ---------------------------------------------------------------------------
# The surfaces, run against §212 rather than only described by it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,score,criticals", [
    (rc.VALIDATED, 88.0, 0),
    (rc.FAILED, None, 2),
    (rc.NEEDS_REVIEW, None, 0),
    (rc.UNVERIFIED, None, 0),
])
def test_every_review_row_the_list_produces_is_honest(status, score,
                                                      criticals):
    """The rule that matters is not that `record.py` is careful — it is that
    every surface built ON it stays honest, including ones written later."""
    row = rvs.row_for(stored(status=status, score=score,
                             critical_failure_count=criticals))

    assert hn.honest(row), hn.check_payload(row)


def test_a_stale_review_row_is_honest():
    row = stored(status=rc.HIGH_ASSURANCE, score=96.0)
    row.stale_reasons = ["a newer Teaching Release is in force"]

    payload = rvs.row_for(row)

    assert payload["status_now"] == rc.STALE
    assert hn.honest(payload), hn.check_payload(payload)


def test_the_review_header_is_honest():
    header = rv.InvestigationReview(record=stored()).header()

    assert hn.honest(header), hn.check_payload(header)


def test_a_review_of_a_failed_thread_is_honest():
    bad = stored(id="ar-1", status=rc.FAILED, score=None,
                 critical_failure_count=1, turn_index=0)
    good = stored(id="ar-2", turn_index=1)
    review = rv.InvestigationReview(record=good, thread=[bad, good])

    payload = review.to_dict()
    payload.update(review.header())

    assert hn.honest(payload), hn.check_payload(payload)
    assert payload["thread"]["status"] == rc.FAILED
