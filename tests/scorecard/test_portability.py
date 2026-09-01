"""
Portable scorecard intelligence, and what may not travel with it. §A8, §A9.

The interesting tests here are the exclusions. A Brain Pack that carried
fitted coefficients, raw rows or sealed holdout gold would look exactly like
one that did not — the archive is the same shape, the import succeeds, and
the score it later produces is flattering rather than wrong. So the audit
walks the built payload rather than trusting the builders, and these tests
walk it too.
"""

from __future__ import annotations

import pytest

from backend.brain import compatibility as compat
from backend.brain.pack import Manifest
from backend.scorecard import build as build_mod
from backend.scorecard import holdout as hold
from backend.scorecard import portable
from intelligence_factory.teaching import scorecard as dev


@pytest.fixture(scope="module")
def payload():
    return portable.package()


# ------------------------------------------------------------- what travels


def test_the_package_carries_everything_the_brief_lists(payload):
    """§A8's thirteen items."""
    for key in ("ontology", "metric_semantics", "teaching_families",
                "report_structure", "agent_and_tool_policy",
                "visual_grammar", "maturity_rules", "validation_policy",
                "validation_methods", "critical_cases", "model_shapes",
                "registry_governance"):
        assert key in payload, key
    assert payload["report_structure"]["coverage"]


def test_the_ontology_carries_the_distinctions_that_get_merged(payload):
    """PSI and CSI merged in an inherited ontology means a receiver answers
    a CSI question with a PSI figure and looks right doing it."""
    distinctions = " ".join(payload["ontology"]["distinctions"])
    assert "PSI is the score" in distinctions
    assert "one variable" in distinctions
    assert "not the model's Gini" in distinctions
    assert "latest matured" in distinctions


def test_the_maturity_rule_travels(payload):
    """The control the module is built around."""
    rules = payload["maturity_rules"]
    assert "never calculate actual against predicted" in rules["rule"]
    assert rules["default_horizon_months"] > 0
    assert "zero" in rules["never"]


def test_every_teaching_family_travels_as_an_obligation(payload):
    """A receiver inherits what to teach, not this installation's
    phrasing."""
    families = payload["teaching_families"]["families"]
    assert len(families) == 23
    for family in families:
        assert family["teaches"]
        assert family["scope"] == "RETAIL"


def test_the_critical_catalogue_travels(payload):
    """A receiver inherits the checks, not just the conclusions."""
    checks = payload["critical_cases"]["checks"]
    assert len(checks) >= 22
    assert payload["critical_cases"]["requirement"] == "zero failures"


def test_the_registry_governance_rules_travel(payload):
    rules = " ".join(payload["registry_governance"]["rules"])
    assert "candidate never overwrites" in rules
    assert "only from APPROVED" in rules


# ------------------------------------------------------- what may not travel


def test_the_audit_finds_nothing_to_exclude(payload):
    assert portable.audit(payload) == []


def test_no_fitted_coefficient_travels(payload):
    """§A8. Ours are synthetic, and a rule that only holds for synthetic
    data is not a rule."""
    equation = build_mod.load_equation(build_mod.APP, "INCUMBENT")
    rendered = repr(payload)
    for term in equation.terms:
        assert f"{term.coefficient:.6f}" not in rendered, term.variable
        assert f"{term.coefficient}" not in rendered, term.variable
    assert f"{equation.intercept}" not in rendered
    shapes = payload["model_shapes"][build_mod.APP]
    assert "coefficient" not in shapes
    assert shapes["variables"]
    assert shapes["coefficients_excluded_because"]


def test_no_measured_value_travels(payload):
    """A bare float in an intelligence payload is almost always a
    measurement that should have stayed behind."""
    def floats(node, path="package"):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from floats(value, f"{path}.{key}")
        elif isinstance(node, list | tuple):
            for index, value in enumerate(node):
                yield from floats(value, f"{path}[{index}]")
        elif isinstance(node, float):
            yield path

    assert list(floats(payload)) == []


def test_no_holdout_question_travels(payload):
    rendered = repr(payload)
    for case in hold.build()[:60]:
        assert case.question not in rendered, case.case_id


def test_no_development_question_travels(payload):
    """The families travel; the phrasing does not."""
    rendered = repr(payload)
    for case in dev.cases()[:60]:
        assert case.question not in rendered, case.case_id


def test_the_audit_can_actually_fail():
    """A check that never fails is a check nobody has tested."""
    problems = portable.audit({"model": {"coefficients": {"x": 1}}})
    assert problems
    assert "may not carry coefficients" in problems[0]


def test_a_measured_value_is_caught_by_the_audit():
    problems = portable.audit({"metrics": {"auc": 0.7104}})
    assert problems
    assert "no measured value" in problems[0]


def test_the_exclusions_each_say_why(payload):
    """An exclusion with no reason gets relaxed the first time it is
    inconvenient."""
    assert len(payload["excluded"]) == len(portable.NEVER_EXPORTED)
    for entry in payload["excluded"]:
        assert len(entry["why"]) > 25, entry["what"]


# ------------------------------------------------------------ compatibility


def test_the_module_is_registered_with_the_receiver():
    assert portable.receiver_has_module(compat.Receiver.here())


def test_a_package_that_needs_the_module_is_clean_where_it_exists():
    manifest = Manifest(brain_id="b", brain_name="n", brain_version="1.0.0",
                        required_modules=portable.requires(),
                        minimum_app_version="0.0.0")
    report = portable.compatibility(manifest, compat.Receiver.here())
    modules = [f for f in report.findings if f.kind == "module"]
    assert modules == []


def test_a_receiver_without_the_module_is_told(payload):
    """§A8. A Brain carrying scorecard intelligence that lands somewhere
    without the module has to say so rather than half-installing."""
    here = compat.Receiver.here()
    without = compat.Receiver(
        app_version=here.app_version,
        modules=here.modules - {portable.MODULE},
        package_schema_version=here.package_schema_version)
    manifest = Manifest(brain_id="b", brain_name="n", brain_version="1.0.0",
                        required_modules=portable.requires(),
                        minimum_app_version="0.0.0")
    report = portable.compatibility(manifest, without)
    findings = [f for f in report.findings if f.name == portable.MODULE]
    assert findings, "a missing Retail Scorecard module was not reported"
    assert findings[0].kind == "module"


# -------------------------------------------------------------------- lift


def test_lift_is_measured_on_the_receivers_own_set():
    """§A9 and §18 agree: a lift measured on the sender's cases measures how
    well the sender described its own cases."""
    cases = dev.cases()
    report = portable.lift(cases[:150], cases, candidate_id="c",
                           brain_name="n", brain_version="1.0.0")
    assert report.sender_holdout_used is False
    assert "receiver" in report.sets_used[0]


def test_more_cases_alone_is_not_reported_as_lift():
    """§A9's rule. The candidate here has three times the cases and the same
    settle rate."""
    cases = dev.cases()
    report = portable.lift(cases[:150], cases, candidate_id="c",
                           brain_name="n", brain_version="1.0.0")
    payload = report.to_dict()
    assert payload["verdict"] != "IMPROVEMENT", (
        "a larger case count with an unchanged rate was reported as lift")


def test_the_lift_report_names_the_scorecard_subcomponents():
    """§A9: scorecard-specific subcomponent deltas, so a receiver can see
    WHERE imported intelligence helped."""
    cases = dev.cases()
    report = portable.lift(cases[:150], cases)
    notes = " ".join(report.notes)
    for name in portable.LIFT_SUBCOMPONENTS:
        assert name in notes, name


def test_the_lift_report_covers_all_six_dimensions():
    cases = dev.cases()
    report = portable.lift(cases[:150], cases)
    assert len(report.deltas) == 6
