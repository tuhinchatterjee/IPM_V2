"""The Brain's lifecycle: ledger, quarantine, compatibility, conflicts, lift.

§13, §14, §16-§23, §29, §49. Between them these decide whether a Brain from
somewhere else may change how this installation answers - so every test here
is about a way that could go wrong quietly.
"""

from __future__ import annotations

import pytest

from backend.brain import compatibility as compat
from backend.brain import conflicts as cf
from backend.brain import ledger as led
from backend.brain import liftlab as lift
from backend.brain import pack
from backend.brain import quarantine as qn

# ================================================== §13/§14 Learning Ledger


def test_a_captured_entry_is_local_and_unreviewed_by_default():
    entry = led.capture(led.DATA_BUILDER_MAPPING, "mapped a field")
    assert entry.portability == led.NON_PORTABLE
    assert entry.review_status == led.CAPTURED
    assert not entry.exportable


def test_every_source_the_brief_names_is_a_source():
    for source in (led.ASK, led.FEEDBACK, led.BETTER_APPROACH,
                   led.STUDIO_METHOD, led.DATA_BUILDER_MAPPING,
                   led.REGULATORY_REVIEW, led.RISK_CASE, led.AGENTIC_REVIEW,
                   led.WORKFLOW_COMMENT, led.VISUALIZATION_CORRECTION,
                   led.EXPERIMENT, led.ADMIN_DECISION):
        assert source in led.SOURCES


def test_an_entry_with_no_summary_cannot_be_recorded():
    with pytest.raises(led.LedgerError, match="summary"):
        led.capture(led.ASK, "   ")


def test_an_approved_entry_must_name_a_reviewer():
    entry = led.Entry(source=led.FEEDBACK, summary="x",
                      review_status=led.APPROVED)
    assert any("reviewer" in p for p in led.validate(entry))


def test_a_missing_eligibility_check_counts_as_failed():
    """"Nobody looked" and "it passed" are different."""
    state, blockers = led.eligibility({})
    assert state == led.NON_PORTABLE
    assert len(blockers) == len(led.ELIGIBILITY)


def test_portability_needs_every_condition():
    passing = {name: True for name, _ in led.ELIGIBILITY}
    assert led.eligibility(passing)[0] == led.PORTABLE
    passing["single_tenant"] = False
    state, blockers = led.eligibility(passing)
    assert state != led.PORTABLE
    assert any("tenant" in b for b in blockers)


def test_approved_and_portable_are_both_needed_to_export():
    entry = led.Entry(source=led.FEEDBACK, summary="x",
                      review_status=led.APPROVED, reviewer="SME",
                      portability=led.NON_PORTABLE)
    assert entry.releasable and not entry.exportable
    entry.portability = led.PORTABLE
    assert entry.exportable


def test_correcting_an_entry_supersedes_rather_than_updates():
    """§13: never lose the observation."""
    first = led.capture(led.ASK, "the original observation")
    second = led.capture(led.ASK, "what it should have said")
    superseded = led.supersede(first, second, "the first reading was wrong")
    assert superseded.review_status == led.SUPERSEDED
    assert superseded.superseded_by == second.entry_id
    assert superseded.summary == first.summary, "the original is preserved"


def test_a_supersession_needs_a_reason():
    a = led.capture(led.ASK, "one")
    b = led.capture(led.ASK, "two")
    with pytest.raises(led.LedgerError):
        led.supersede(a, b, "  ")


def test_the_same_observation_twice_fingerprints_once():
    one = led.capture(led.DATA_BUILDER_MAPPING, "Mapped  rating_bucket",
                      object_kind="dataset", object_id="customer_ratings")
    two = led.capture(led.DATA_BUILDER_MAPPING, "mapped rating_bucket",
                      object_kind="dataset", object_id="customer_ratings")
    assert one.fingerprint == two.fingerprint
    assert one.entry_id != two.entry_id


def test_the_census_refuses_to_add_capture_to_approval():
    entries = [led.capture(led.ASK, f"observation {i}") for i in range(5)]
    census = led.census(entries)
    assert census["captured"] == 5
    assert census["approved"] == 0
    assert "More capture is not improvement" in census["note"]


# ================================================ §16 quarantine pipeline


@pytest.fixture
def candidate():
    return qn.Candidate(package_kind=pack.BRAIN_PACK, brain_id="b1",
                        brain_name="Riyadh", brain_version="1.0.0",
                        uploaded_by="admin")


def test_an_upload_is_quarantined_and_not_retrievable(candidate):
    """§16: uploading must never alter active production."""
    assert candidate.stage == qn.UPLOADED
    assert candidate.quarantined
    assert not candidate.retrievable


def test_a_candidate_cannot_skip_a_pipeline_stage(candidate):
    with pytest.raises(qn.QuarantineError, match="pipeline order"):
        qn.advance(candidate, qn.APPROVED)


def test_the_pipeline_evaluates_before_it_approves():
    """Approving before evaluating is approving a claim."""
    assert qn.PIPELINE.index(qn.EVALUATED) < qn.PIPELINE.index(qn.APPROVED)
    assert qn.PIPELINE.index(qn.COMPATIBILITY_CHECKED) < \
        qn.PIPELINE.index(qn.EVALUATED)
    assert qn.PIPELINE.index(qn.FORMAT_CHECKED) < \
        qn.PIPELINE.index(qn.SIGNATURE_CHECKED)


def _walk(candidate, upto):
    for stage in qn.PIPELINE[1:qn.PIPELINE.index(upto) + 1]:
        qn.advance(candidate, stage, by="admin")
    return candidate


def test_nothing_is_retrievable_until_active(candidate):
    _walk(candidate, qn.STAGED)
    assert not candidate.retrievable
    candidate.approvals.append({"by": "admin"})
    candidate.evaluation = {"critical_regressions": 0, "verdict": "IMPROVEMENT"}
    candidate.inspection = {"signature_state": "TRUSTED"}
    qn.activate(candidate, by="admin")
    assert candidate.retrievable


def test_an_unsigned_package_needs_high_trust_to_activate(candidate):
    _walk(candidate, qn.STAGED)
    candidate.approvals.append({"by": "admin"})
    candidate.evaluation = {"critical_regressions": 0}
    candidate.inspection = {"signature_state": "UNSIGNED"}
    allowed, why = qn.may_activate(candidate)
    assert not allowed and "high-trust" in why
    allowed, _ = qn.may_activate(candidate, high_trust_approval=True)
    assert allowed


def test_a_critical_regression_stops_activation(candidate):
    _walk(candidate, qn.STAGED)
    candidate.approvals.append({"by": "admin"})
    candidate.inspection = {"signature_state": "TRUSTED"}
    candidate.evaluation = {"critical_regressions": 1}
    allowed, why = qn.may_activate(candidate)
    assert not allowed
    assert "does not offset" in why


def test_activation_without_an_evaluation_is_refused(candidate):
    _walk(candidate, qn.STAGED)
    candidate.approvals.append({"by": "admin"})
    candidate.inspection = {"signature_state": "TRUSTED"}
    allowed, why = qn.may_activate(candidate)
    assert not allowed
    assert "activating a claim" in why


def test_a_candidate_may_be_deleted_before_activation(candidate):
    qn.delete(candidate, by="admin", why="wrong file")
    assert candidate.stage == qn.DELETED


def test_an_activated_brain_may_not_be_deleted(candidate):
    _walk(candidate, qn.STAGED)
    candidate.approvals.append({"by": "admin"})
    candidate.evaluation = {"critical_regressions": 0}
    candidate.inspection = {"signature_state": "TRUSTED"}
    qn.activate(candidate, by="admin")
    with pytest.raises(qn.QuarantineError, match="installation record"):
        qn.delete(candidate, by="admin", why="tidying")


def test_a_purge_keeps_the_record(candidate):
    """§23: never silently hard-delete historical evidence."""
    qn.purge_payload(candidate, by="admin", why="retention policy")
    assert candidate.diff["purged"] is True
    assert any(s.stage == "PAYLOAD_PURGED" for s in candidate.history)
    assert candidate.history[0].stage == qn.UPLOADED


def test_a_rollback_needs_a_reason(candidate):
    _walk(candidate, qn.STAGED)
    candidate.approvals.append({"by": "admin"})
    candidate.evaluation = {"critical_regressions": 0}
    candidate.inspection = {"signature_state": "TRUSTED"}
    qn.activate(candidate, by="admin")
    with pytest.raises(qn.QuarantineError):
        qn.roll_back(candidate, to="previous", by="admin", why="")


# ================================================== §17 compatibility


@pytest.fixture
def receiver():
    return compat.Receiver(
        app_version="0.3.0", modules=frozenset({"ask", "studio"}),
        datasets=frozenset({"portfolio_facility"}),
        agents=frozenset({"credit_analyst"}),
        visualizations=frozenset({"bar"}),
        languages=frozenset({"en"}), scopes=frozenset({"CORPORATE"}),
        ontology_version="2.0.0", package_schema_version="1.0.0")


def _manifest(**kwargs):
    base = dict(brain_id="b", brain_name="Incoming", brain_version="1.0.0",
                ontology_version="2.0.0", minimum_app_version="0.1.0")
    base.update(kwargs)
    return pack.Manifest(**base)


def test_a_compatible_package_reports_nothing(receiver):
    report = compat.check(_manifest(), receiver)
    assert report.compatible
    assert report.findings == []


def test_an_older_app_is_reported_with_a_named_reason(receiver):
    report = compat.check(_manifest(minimum_app_version="9.0.0"), receiver)
    assert any(f.reason == compat.APP_TOO_OLD for f in report.findings)


def test_every_unsupported_component_gets_a_named_reason(receiver):
    report = compat.check(
        _manifest(required_modules=("quantum",),
                  supported_languages=("ar",)),
        receiver,
        declared={"agents": ["unknown_agent"],
                  "datasets": ["missing_table"],
                  "visualizations": ["hologram"],
                  "relationships": ["a->b"]})
    reasons = {f.reason for f in report.findings}
    assert compat.MISSING_MODULE in reasons
    assert compat.UNKNOWN_LANGUAGE in reasons
    assert compat.UNKNOWN_AGENT in reasons
    assert compat.MISSING_DATA_CONTRACT in reasons
    assert compat.UNKNOWN_VISUALIZATION in reasons
    assert compat.MISSING_RELATIONSHIP in reasons
    assert all(f.reason in compat.REASONS for f in report.findings)


def test_a_fixable_finding_says_it_would_activate(receiver):
    report = compat.check(_manifest(required_modules=("quantum",)),
                          receiver)
    dormant = report.dormant
    assert dormant
    assert dormant[0].to_dict()["would_activate_if_fixed"] is True


def test_a_newer_ontology_is_reported_and_not_fixable(receiver):
    report = compat.check(_manifest(ontology_version="9.0.0"), receiver)
    finding = next(f for f in report.findings
                   if f.reason == compat.NEWER_POLICY_VERSION)
    assert not finding.fixable


def test_the_real_receiver_reads_its_own_registries():
    here = compat.Receiver.here()
    assert here.datasets
    assert "credit_analyst" in here.agents
    assert here.ontology_version


# ==================================================== §20/§21 conflicts


def test_the_twelve_conflict_classes_are_all_declared():
    assert len(cf.CLASSES) == 12
    assert len(set(cf.CLASS_IDS)) == 12


def test_there_is_no_newer_wins_resolution():
    """§21: no automatic winner merely because incoming is newer."""
    assert not any("NEWER" in r for r in cf.RESOLUTIONS)
    assert cf.KEEP_LOCAL in cf.RESOLUTIONS
    assert cf.ACCEPT_INCOMING in cf.RESOLUTIONS


def test_identical_items_are_not_a_conflict():
    same = {"thresholds": {"t": {"value": 30}}}
    assert cf.detect(same, same) == []


def test_an_addition_is_not_a_conflict():
    found = cf.detect({}, {"thresholds": {"new": {"value": 1}}})
    assert found == []


def test_a_differing_threshold_is_detected_and_scoped():
    found = cf.detect(
        {"thresholds": {"sicr": {"value": 30, "scope": "CORPORATE"}}},
        {"thresholds": {"sicr": {"value": 60, "scope": "RETAIL"}}})
    assert len(found) == 1
    assert found[0].conflict_class == cf.THRESHOLD_SCOPE
    assert found[0].recommended == cf.SCOPE_SPLIT
    assert "both can be true" in found[0].recommendation_reason


def test_the_same_method_version_with_different_content_is_a_conflict():
    found = cf.detect(
        {"methods": {"ecl": {"value": "a", "version": "1.0.0"}}},
        {"methods": {"ecl": {"value": "b", "version": "1.0.0"}}})
    assert found[0].conflict_class == cf.METHOD_VERSION_CONTENT
    assert found[0].risk == "high"


def test_a_resolution_requires_a_reason_and_a_person():
    found = cf.detect({"terms": {"t": {"value": "a"}}},
                      {"terms": {"t": {"value": "b"}}})
    with pytest.raises(cf.ConflictError, match="reason"):
        cf.resolve(found[0], cf.ACCEPT_INCOMING, by="admin", why="")
    with pytest.raises(cf.ConflictError, match="signed"):
        cf.resolve(found[0], cf.ACCEPT_INCOMING, by="", why="fine")


def test_a_scope_split_must_name_its_axis():
    found = cf.detect({"terms": {"t": {"value": "a"}}},
                      {"terms": {"t": {"value": "b"}}})
    with pytest.raises(cf.ConflictError, match="axis"):
        cf.resolve(found[0], cf.SCOPE_SPLIT, by="a", why="b")
    resolved = cf.resolve(found[0], cf.SCOPE_SPLIT, by="a", why="b",
                          split_axis="jurisdiction")
    assert resolved.split_axis == "jurisdiction"


def test_a_deferred_high_risk_conflict_still_blocks():
    """Deferring is an answer to "which is right", not to "may this run"."""
    found = cf.detect({"methods": {"m": {"value": "a", "version": "1"}}},
                      {"methods": {"m": {"value": "b", "version": "1"}}})
    cf.resolve(found[0], cf.DEFER, by="admin", why="needs the SME")
    assert found[0].status == "DEFERRED"
    assert cf.blocking(found)


# ======================================================= §18/§19 Lift Lab


def _scores(value, cases=200, critical=0):
    return {d: lift.Score(d, value, cases, critical) for d in lift.DIMENSIONS}


def test_the_six_dimensions_are_the_six():
    assert len(lift.DIMENSIONS) == 6
    assert lift.UNDERSTANDING in lift.DIMENSIONS
    assert lift.RELIABILITY in lift.DIMENSIONS


def test_the_briefs_worked_example_reproduces():
    """§61: 82.0% to 88.5% is +6.5 pp, +7.9% relative, 36.1% error cut."""
    delta = lift.Delta(lift.DESIGN, lift.Score(lift.DESIGN, 0.82, 200),
                       lift.Score(lift.DESIGN, 0.885, 200))
    assert delta.points == 6.5
    assert delta.relative == pytest.approx(7.93, abs=0.05)
    assert delta.error_reduction == pytest.approx(36.11, abs=0.05)


def test_a_critical_regression_overrides_a_positive_average():
    report = lift.compare(_scores(0.82, critical=3),
                          _scores(0.95, critical=9))
    assert report.verdict == lift.REGRESSION
    assert "whatever the averages say" in report.headline()


def test_a_trivial_sample_is_insufficient_evidence_not_a_small_win():
    """§18: "Do not claim lift from trivial sample sizes."."""
    report = lift.compare(_scores(0.80, cases=8), _scores(0.90, cases=8))
    assert report.verdict == lift.INSUFFICIENT_EVIDENCE
    assert "not a small improvement" in report.headline()


def test_the_senders_holdout_invalidates_the_whole_evaluation():
    report = lift.compare(_scores(0.5), _scores(0.99),
                          sender_holdout_used=True)
    assert report.verdict == lift.INSUFFICIENT_EVIDENCE
    assert "measures nothing" in report.headline()


def test_a_relative_change_on_a_zero_baseline_is_not_a_number():
    delta = lift.Delta(lift.DESIGN, lift.Score(lift.DESIGN, 0.0, 200),
                       lift.Score(lift.DESIGN, 0.5, 200))
    assert delta.relative is None


def test_every_dimension_appears_even_with_no_cases():
    """A dimension omitted for lack of evidence reads as one that did not
    change."""
    report = lift.compare({}, {})
    assert len(report.deltas) == len(lift.DIMENSIONS)
    assert report.verdict == lift.INSUFFICIENT_EVIDENCE


def test_the_sentence_leads_with_percentage_points():
    delta = lift.Delta(lift.DESIGN, lift.Score(lift.DESIGN, 0.82, 200),
                       lift.Score(lift.DESIGN, 0.885, 200))
    said = delta.sentence()
    assert said.index("pp") < said.index("relative")


def test_the_impact_report_carries_every_section_the_brief_names():
    report = lift.compare(_scores(0.82), _scores(0.885))
    body = lift.impact_report(report, compatibility={"dormant": []},
                              conflicts={"blocking": 0}, diff={})
    for key in ("executive_summary", "compatibility", "components_added",
                "components_changed", "components_removed",
                "six_dimension_lift", "subcomponent_lift", "critical_fixes",
                "critical_regressions", "new_coverage", "lost_coverage",
                "latency_and_cost", "conflicts",
                "missing_receiver_capabilities",
                "privacy_and_provenance", "recommended_decision",
                "known_limitations"):
        assert key in body, key


def test_a_blocking_conflict_stops_the_recommendation():
    report = lift.compare(_scores(0.82), _scores(0.95))
    body = lift.impact_report(report, compatibility={},
                              conflicts={"blocking": 2}, diff={})
    assert body["recommended_decision"] == "RESOLVE CONFLICTS FIRST"
    assert "contradictory rules" in body["recommendation_reason"]
