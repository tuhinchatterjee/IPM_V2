"""
The Retail Scorecard Model Registry. §12, §13, §35, §94.

Most of what follows tests refusals, and that is deliberate. A registry that
records things correctly is easy; a registry that cannot be talked into
recording the wrong thing under deadline pressure is the one worth having.
The operations tested here are the ones somebody genuinely wants at 5pm on a
release day: edit the active model's coefficients, activate a candidate
nobody approved, record a breach without saying whose limit it broke.

The transitions test is not a test of a state machine. It is a test that
approval and activation are separate acts.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.scorecard import build as build_mod
from backend.scorecard import equation as equation_mod
from backend.scorecard import policy as policy_mod
from backend.scorecard import registry as reg
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")

TENANT = "test-registry"

#: Tables this suite owns, children first.
_OWNED = ("scorecard_report_evidence", "scorecard_reports",
          "scorecard_dashboard_pins", "scorecard_model_approvals",
          "scorecard_findings", "scorecard_validation_runs",
          "scorecard_policy_limits", "scorecard_binning_specs",
          "scorecard_model_variables", "scorecard_models")


if database_available():
    from backend.db.engine import SessionLocal  # noqa: E402


def _clean(session) -> None:
    for table in _OWNED:
        session.execute(text(f"DELETE FROM {table} WHERE tenant = :t"),
                        {"t": TENANT})
    session.commit()


@pytest.fixture
def session():
    s = SessionLocal()
    _clean(s)
    try:
        yield s
    finally:
        s.rollback()
        _clean(s)
        s.close()


@pytest.fixture
def seeded(session):
    reg.seed(session, tenant=TENANT, created_by="test")
    session.commit()
    return session


def _equation(name: str = "Probe") -> equation_mod.Equation:
    return equation_mod.Equation(
        model_name=name, scorecard_type=build_mod.APP, intercept=-2.5,
        terms=[equation_mod.Term("bureau_score", -0.8),
               equation_mod.Term("debt_burden_ratio", -0.6)],
        binning_spec_version="application-woe-1.0.0",
        score_mapping=equation_mod.ScoreMapping(
            base_score=600, pdo=20, base_odds=50,
            score_direction=equation_mod.HIGHER_SCORE_IS_BETTER))


# ---------------------------------------------------------------- the shape


def test_every_status_has_a_transition_entry():
    """A status missing from TRANSITIONS is a model that can never move.

    Not a hypothetical: adding a status and forgetting the map is exactly
    how a registry acquires a version nobody can retire.
    """
    assert set(reg.TRANSITIONS) == set(reg.STATUSES)
    for status, allowed in reg.TRANSITIONS.items():
        for target in allowed:
            assert target in reg.STATUSES, f"{status} -> {target}"


def test_activation_is_only_reachable_through_approval():
    """§35's real content, as a property of the graph.

    ACTIVE has exactly one predecessor, and it is APPROVED. If a second
    route to ACTIVE ever appears, the narrower approval permission stops
    being a control and becomes a formality somebody can route around.
    """
    into_active = [s for s, allowed in reg.TRANSITIONS.items()
                   if reg.ACTIVE in allowed]
    assert into_active == [reg.APPROVED]


def test_retired_is_terminal():
    assert reg.TRANSITIONS[reg.RETIRED] == ()


# ------------------------------------------------------------- registration


@db
def test_seeding_registers_both_scorecards_with_one_active_each(seeded):
    """Three models per scorecard, and exactly one of each type live."""
    rows = reg.models(seeded, tenant=TENANT)
    assert len(rows) == 6
    for kind in (build_mod.APP, build_mod.BEH):
        live = [r for r in rows
                if r.scorecard_type == kind and r.status == reg.ACTIVE]
        assert len(live) == 1, f"{kind} has {len(live)} active models"
        assert live[0].model_id.endswith("incumbent")


@db
def test_every_registered_row_is_marked_synthetic(seeded):
    """§2. The marker travels with the row, not with a caption."""
    for row in reg.models(seeded, tenant=TENANT):
        assert row.origin == reg.SYNTHETIC_DEMO


@db
def test_a_registered_model_records_its_sign_convention(seeded):
    """§13. Never blank: every discrimination statistic depends on it."""
    for row in reg.models(seeded, tenant=TENANT):
        assert row.score_direction in equation_mod.SCORE_DIRECTIONS


@db
def test_a_model_with_no_score_mapping_is_refused(session):
    """A model registered without a mapping leaves the convention unstated,
    which is the one thing §13 says the registry has to settle."""
    eq = _equation()
    eq.score_mapping = None
    with pytest.raises(reg.RegistryError, match="sign convention"):
        reg.register(session, equation=eq, model_id="probe",
                     model_version="1.0.0", status=reg.DEVELOPMENT,
                     scorecard_type=build_mod.APP, tenant=TENANT)


@db
def test_an_unknown_status_is_refused(session):
    with pytest.raises(reg.RegistryError, match="not a registry status"):
        reg.register(session, equation=_equation(), model_id="probe",
                     model_version="1.0.0", status="LIVE-ISH",
                     scorecard_type=build_mod.APP, tenant=TENANT)


@db
def test_an_active_models_equation_cannot_be_edited(session):
    """The operation everybody wants under deadline, refused.

    Re-registering an ACTIVE version with the same equation is fine — that
    is a reseed. Re-registering it with a different one is not an update, it
    is a different model wearing the approved version's number.
    """
    eq = _equation()
    reg.register(session, equation=eq, model_id="probe",
                 model_version="1.0.0", status=reg.ACTIVE,
                 scorecard_type=build_mod.APP, tenant=TENANT)
    session.flush()

    # Same equation: idempotent.
    reg.register(session, equation=_equation(), model_id="probe",
                 model_version="1.0.0", status=reg.ACTIVE,
                 scorecard_type=build_mod.APP, tenant=TENANT)

    changed = _equation()
    changed.intercept = -3.1
    with pytest.raises(reg.RegistryError, match="not editable"):
        reg.register(session, equation=changed, model_id="probe",
                     model_version="1.0.0", status=reg.ACTIVE,
                     scorecard_type=build_mod.APP, tenant=TENANT)


@db
def test_a_variable_the_dictionary_does_not_define_is_refused(session):
    """A hidden predictor gets into a registry exactly once — the first time
    an unknown name is recorded with blank metadata."""
    eq = _equation()
    eq.terms.append(equation_mod.Term("uncle_works_at_the_bank", 0.4))
    with pytest.raises(Exception, match="not a candidate variable"):
        reg.register(session, equation=eq, model_id="probe",
                     model_version="1.0.0", status=reg.DEVELOPMENT,
                     scorecard_type=build_mod.APP, tenant=TENANT)


@db
def test_the_registry_records_variables_considered_and_not_used(seeded):
    """"Which variables were rejected?" is a standard validation question."""
    rows = reg.variables_for(seeded, "application-incumbent", "1.0.0",
                             tenant=TENANT)
    active = [v.variable for v in rows if v.role == reg.ACTIVE_VARIABLE]
    considered = [v.variable for v in rows if v.role == reg.CANDIDATE_VARIABLE]
    assert active, "the incumbent has terms"
    assert considered, "and the development weighed more than it used"
    assert not set(active) & set(considered)


@db
def test_information_value_comes_from_the_binning(seeded):
    """IV is a property of the approved bins, not of the fit: the same
    variable has a different IV under a different specification."""
    rows = reg.variables_for(seeded, "application-incumbent", "1.0.0",
                             tenant=TENANT)
    spec = build_mod.load_spec(build_mod.APP).to_dict()["variables"]
    for row in rows:
        if row.information_value is None:
            continue
        assert row.information_value == pytest.approx(
            spec[row.variable]["information_value"])


@db
def test_the_stored_equation_round_trips(seeded):
    """A score reproduced from the registry has to match the built one."""
    stored = reg.equation_for(seeded, "application-incumbent", tenant=TENANT)
    built = build_mod.load_equation(build_mod.APP, "INCUMBENT")
    assert stored.intercept == pytest.approx(built.intercept)
    assert [t.variable for t in stored.terms] == [t.variable
                                                  for t in built.terms]
    for a, b in zip(stored.terms, built.terms, strict=True):
        assert a.coefficient == pytest.approx(b.coefficient)
    assert (stored.score_mapping.score_direction
            == built.score_mapping.score_direction)
    assert stored.score(-2.0) == pytest.approx(built.score(-2.0))


# ------------------------------------------------------ candidates (§35)


@db
def test_a_candidate_leaves_the_active_model_untouched(seeded):
    """§35. The point of the whole flow."""
    incumbent = reg.get(seeded, "application-incumbent", tenant=TENANT)
    before = dict(incumbent.equation)

    proposed = _equation("Application Scorecard v1.1 proposal")
    reg.propose_candidate(seeded, equation=proposed, based_on=incumbent,
                          model_version="1.1.0", created_by="test",
                          tenant=TENANT)
    seeded.flush()

    after = reg.get(seeded, "application-incumbent", model_version="1.0.0",
                    tenant=TENANT)
    assert after.status == reg.ACTIVE
    assert after.equation == before

    candidate = reg.get(seeded, "application-incumbent",
                        model_version="1.1.0", tenant=TENANT)
    assert candidate.status == reg.CANDIDATE
    assert candidate.based_on_model_id == "application-incumbent:1.0.0"


@db
def test_a_candidate_may_not_reuse_the_version_it_modifies(seeded):
    incumbent = reg.get(seeded, "application-incumbent", tenant=TENANT)
    with pytest.raises(reg.RegistryError, match="same version"):
        reg.propose_candidate(seeded, equation=_equation(),
                              based_on=incumbent, model_version="1.0.0",
                              tenant=TENANT)


@db
def test_a_candidate_cannot_be_activated_without_approval(seeded):
    """The refusal that makes the narrower permission mean something."""
    incumbent = reg.get(seeded, "application-incumbent", tenant=TENANT)
    reg.propose_candidate(seeded, equation=_equation("proposal"),
                          based_on=incumbent, model_version="1.1.0",
                          tenant=TENANT)
    seeded.flush()
    with pytest.raises(reg.RegistryError, match="cannot move to ACTIVE"):
        reg.transition(seeded, model_id="application-incumbent",
                       model_version="1.1.0", to_status=reg.ACTIVE,
                       decided_by="test", tenant=TENANT)


@db
def test_activating_a_model_retires_the_live_one_of_that_type(seeded):
    """Two live scorecards deciding the same applications is not a state
    anybody means to be in; it is what happens when activation forgets."""
    for target in (reg.APPROVED, reg.ACTIVE):
        reg.transition(seeded, model_id="application-challenger",
                       model_version="1.0.0", to_status=target,
                       decided_by="test", tenant=TENANT)
    seeded.flush()

    live = [r for r in reg.models(seeded, scorecard_type=build_mod.APP,
                                  tenant=TENANT) if r.status == reg.ACTIVE]
    assert [r.model_id for r in live] == ["application-challenger"]

    superseded = reg.get(seeded, "application-incumbent", tenant=TENANT)
    assert superseded.status == reg.RETIRED

    # And the behavioural side is untouched: different population, different
    # point in the account lifecycle, both live is normal.
    behavioral = [r for r in reg.models(seeded, scorecard_type=build_mod.BEH,
                                        tenant=TENANT)
                  if r.status == reg.ACTIVE]
    assert len(behavioral) == 1


@db
def test_a_retirement_is_recorded_not_silent(seeded):
    """"When did 1.0.0 stop being live?" is an audit question."""
    for target in (reg.APPROVED, reg.ACTIVE):
        reg.transition(seeded, model_id="application-challenger",
                       model_version="1.0.0", to_status=target,
                       decided_by="ADMIN#1", tenant=TENANT)
    seeded.flush()
    trail = reg.approvals_for(seeded, "application-incumbent", tenant=TENANT)
    assert [a.to_status for a in trail] == [reg.RETIRED]
    assert trail[0].decision == "SUPERSEDED"
    assert "application-challenger" in trail[0].rationale


@db
def test_the_approval_trail_survives_the_status_column(seeded):
    """The model row says where it is. The trail says how it got there."""
    reg.transition(seeded, model_id="application-challenger",
                   model_version="1.0.0", to_status=reg.APPROVED,
                   rationale="Model committee, minute 4.",
                   committee="Model Risk Committee", decided_by="ADMIN#1",
                   tenant=TENANT)
    reg.transition(seeded, model_id="application-challenger",
                   model_version="1.0.0", to_status=reg.RETIRED,
                   decision="WITHDRAWN", decided_by="ADMIN#1", tenant=TENANT)
    seeded.flush()
    trail = reg.approvals_for(seeded, "application-challenger", tenant=TENANT)
    assert [a.to_status for a in trail] == [reg.APPROVED, reg.RETIRED]
    assert trail[0].committee == "Model Risk Committee"


# ------------------------------------------------------------------ limits


@db
def test_every_seeded_limit_says_it_is_demonstration_policy(seeded):
    """§26/§80. A conventional PSI cut-off recorded without its provenance
    becomes a regulatory requirement the third time somebody reads it."""
    rows = reg.limits(seeded, tenant=TENANT)
    assert rows
    for row in rows:
        assert row.source == policy_mod.DEMO_POLICY


@db
def test_a_limit_with_an_unnameable_source_is_refused(session):
    bad = policy_mod.Limit("auc", "AUC", policy_mod.AT_LEAST, 0.6,
                           provenance="SOMEBODY SAID SO")
    with pytest.raises(reg.RegistryError, match="not one of the five"):
        reg.register_limits(session, (bad,), tenant=TENANT)


# ---------------------------------------------------------------- findings


def _finding(**overrides) -> policy_mod.Finding:
    payload = {
        "finding_id": "F-TEST-1", "model_id": "application-incumbent",
        "model_version": "1.0.0", "period": "2024-06",
        "category": next(iter(policy_mod.CATEGORIES)),
        "title": "Score PSI above the demonstration limit",
        "description": "PSI of 0.31 against a 0.25 limit.",
        "severity": policy_mod.HIGH, "metric": "score_psi",
        "observed": 0.31, "limit_value": 0.25,
        "limit_source": policy_mod.DEMO_POLICY, "breach": True,
        "status": policy_mod.OPEN,
        # Required by Finding itself for HIGH and MEDIUM: §48 says a finding
        # that cannot point at a number is an opinion the model owner has no
        # way to answer.
        "evidence": [{"metric": "score_psi", "value": 0.31,
                      "run_id": "RUN-1"}],
        "analysis_run_ids": ["RUN-1"],
    }
    payload.update(overrides)
    return policy_mod.Finding(**payload)


@db
def test_a_recorded_finding_keeps_its_limit_source(seeded):
    row = reg.record_finding(seeded, _finding(), tenant=TENANT)
    assert row.limit_source == policy_mod.DEMO_POLICY
    assert row.breach is True


@db
def test_a_breach_with_no_limit_source_is_refused(seeded):
    """A breach of an unattributed limit cannot be defended in a report."""
    with pytest.raises(reg.RegistryError, match="no limit source"):
        reg.record_finding(seeded, _finding(limit_source=""), tenant=TENANT)


@db
def test_a_finding_moves_through_its_lifecycle(seeded):
    reg.record_finding(seeded, _finding(), tenant=TENANT)
    row = reg.set_finding_status(seeded, "F-TEST-1", policy_mod.CLOSED,
                                 tenant=TENANT)
    assert row.status == policy_mod.CLOSED
    assert row.closed_at is not None
    with pytest.raises(reg.RegistryError, match="not a finding status"):
        reg.set_finding_status(seeded, "F-TEST-1", "SORTED", tenant=TENANT)


# ------------------------------------------------------- runs and reports


@db
def test_a_run_records_whether_the_window_had_closed(seeded):
    """§7. Without it, an immature run and a mature one are the same row
    six months later, when nobody remembers which it was."""
    row = reg.record_run(
        seeded, run_id="RUN-1", model_id="application-incumbent",
        model_version="1.0.0", scorecard_type=build_mod.APP,
        period="2025-11", matured=False,
        performance_window_closes="2026-11",
        metrics={"gini": 0.42}, tenant=TENANT)
    assert row.matured is False
    assert row.performance_window_closes == "2026-11"
    assert reg.runs_for(seeded, "application-incumbent", tenant=TENANT)


@db
def test_a_report_cannot_be_recorded_without_its_disclaimer(seeded):
    """§0. CreditProbe does not certify anything, and a report record that
    cannot show it said so is not evidence of anything."""
    with pytest.raises(reg.RegistryError, match="disclaimer"):
        reg.record_report(
            seeded, report_id="R-1", model_id="application-incumbent",
            model_version="1.0.0", scorecard_type=build_mod.APP,
            period="2024-06", title="Validation report",
            structure_version="cbuae-aligned-1.0.0", disclaimer="   ",
            tenant=TENANT)


@db
def test_report_evidence_links_every_figure_to_its_run(seeded):
    """§55. "Where does 0.7104 come from?" needs an answer that is not
    somebody's memory."""
    reg.record_report(
        seeded, report_id="R-1", model_id="application-incumbent",
        model_version="1.0.0", scorecard_type=build_mod.APP,
        period="2024-06", title="Validation report",
        structure_version="cbuae-aligned-1.0.0",
        disclaimer="This is not a regulatory certification.",
        tenant=TENANT)
    reg.add_evidence(seeded, "R-1", [
        {"section": "Discrimination", "label": "AUC", "metric": "auc",
         "value": 0.7104, "validation_run_id": "RUN-1",
         "workbook_sheet": "DISCRIMINATION", "workbook_cell": "B7"},
    ], tenant=TENANT)
    rows = reg.evidence_for(seeded, "R-1", tenant=TENANT)
    assert len(rows) == 1
    assert rows[0].validation_run_id == "RUN-1"
    assert rows[0].workbook_cell == "B7"


# -------------------------------------------------------------------- pins


@db
def test_a_pin_belongs_to_a_person_not_to_the_scorecard(session):
    reg.pin(session, user_id=1, scorecard_type=build_mod.APP, kind="metric",
            reference="score_psi", label="Score PSI", tenant=TENANT)
    reg.pin(session, user_id=2, scorecard_type=build_mod.APP, kind="metric",
            reference="gini", tenant=TENANT)
    assert len(reg.pins_for(session, user_id=1, tenant=TENANT)) == 1
    assert len(reg.pins_for(session, user_id=2, tenant=TENANT)) == 1
    assert reg.unpin(session, user_id=1, scorecard_type=build_mod.APP,
                     kind="metric", reference="score_psi", tenant=TENANT)
    assert reg.pins_for(session, user_id=1, tenant=TENANT) == []
