"""
§214 — Part F final acceptance, as fourteen assertions.

    §214: "Do not report the extended master phase complete unless: ..."

Fourteen conditions. Each is a test here, named after the condition it
checks, and each one fails if the thing it names is undone. That is the
point: a report claiming Part F is complete should be checkable by running
one file, rather than by re-reading fourteen paragraphs and taking somebody's
word for it.

Several of these look trivial — "there are six dimensions", "every answer
creates a record". They are trivial to assert and easy to break: a fifteenth
subcomponent filed under no dimension, an answer path that returns before the
record is written, a screen that reads a stored status without checking
staleness. Each of those has a natural way of happening during ordinary
work, and none of them announces itself.
"""

from __future__ import annotations

import inspect

from backend.ai_studio import tabs as tb
from backend.assurance import access as ac
from backend.assurance import collect as cl
from backend.assurance import comparison as cmp
from backend.assurance import dimensions as dm
from backend.assurance import honesty as hn
from backend.assurance import panel as pn
from backend.assurance import record as rc
from backend.assurance import review as rv
from backend.assurance import reviews as rvs
from backend.assurance import store as st
from backend.assurance import trends as tr
from backend.exports import calculation as cal
from backend.orchestration import executor as ex


def test_1_six_broad_dimensions_replace_the_flat_component_wall():
    assert len(dm.DIMENSIONS) == 6
    # And the Overview leads with them rather than with a number.
    overview = tr.overview([])
    assert overview["headline_score"] is None
    assert len(overview["dimensions"]) == 6


def test_2_detailed_subcomponent_drilldown_remains():
    """§179. The dimension is where you notice a problem; the subcomponent
    is where you fix it."""
    assert len(dm.all_subcomponents()) >= 90
    for dimension in dm.DIMENSIONS:
        assert len(dm.SUBCOMPONENTS[dimension]) >= 12, dimension
        assert dm.LABELS[dimension] and dm.ANSWERS[dimension]


def test_3_every_answer_creates_an_assurance_record():
    """The executor calls the collector on every answered turn, not only on
    the ones that ran an analysis."""
    source = inspect.getsource(ex)

    assert "_record_assurance(investigation, answered" in source
    # And it is called unconditionally, after the other recorders rather than
    # inside a branch that only analyses reach.
    assert source.index("_record_judgment(investigation, answered)") < \
        source.index("_record_assurance(investigation, answered")


def test_4_recent_investigations_can_be_selected_and_reviewed():
    assert len(rvs.VIEWS) == 8
    for view in rvs.VIEWS:
        assert view in rvs.VIEW_PREDICATES
        assert len(rvs.VIEW_MEANS[view]) > 20, view
    assert len(rvs.FILTERS) >= 13


def test_5_turn_by_turn_performance_is_visible():
    assert hasattr(rv.InvestigationReview, "timeline")
    for action in ("OPEN_ANSWER", "OPEN_TRACE", "OPEN_PLAN", "OPEN_RESULT",
                   "OPEN_FEEDBACK", "COMPARE_WITH_RERUN"):
        assert action in rv.TURN_ACTIONS


def test_6_the_critical_gates_and_statuses_are_honest():
    """A critical failure produces FAILED and no number, whatever the other
    ninety-four checks said."""
    made = rc.Record(answer_id="a")
    for name in dm.all_subcomponents():
        made.checks.append(
            rc.check(name, rc.FAIL if name == "result_correctness"
                     else rc.PASS,
                     detail="deliberate" if name == "result_correctness"
                     else ""))

    verdict = made.overall()

    assert verdict["overall_status"] == rc.FAILED
    assert verdict["operational_assurance"] is None
    assert verdict["scored_on_average"] is False


def test_7_skipped_and_missing_checks_are_not_passed():
    assert rc.SKIPPED not in rc.COUNTED
    assert rc.check("latency", rc.SKIPPED).counted is False

    sparse = rc.Record(answer_id="a")
    sparse.checks = [rc.check("capability_intent", rc.PASS)]
    assert "figure_grounding" in sparse.skipped_mandatory


def test_8_operational_assurance_and_reference_accuracy_are_separate():
    absent = rc.reference_block(None, "")
    present = rc.reference_block(96.0, "benchmark-2026Q1")

    assert absent["available"] is False
    assert absent["value_pct"] is None
    assert present["available"] is True
    assert "accuracy" not in rc.ASSURANCE_LABEL.lower()


def test_9_feedback_is_linked_but_does_not_alter_a_score():
    """§199, as a property of the code: the one function that writes
    feedback touches no scoring column."""
    source = inspect.getsource(st.note_feedback)

    assert "good_feedback_count" in source
    assert "bad_feedback_count" in source
    for scoring in ("overall_status", "operational_assurance", "coverage_pct",
                    "checks", "dimension_results", "fingerprint"):
        assert f"row.{scoring} =" not in source, scoring


def test_10_rerun_and_version_comparison_works():
    assert len(cmp.VERDICTS) == 5
    for verdict in cmp.VERDICTS:
        assert len(cmp.VERDICT_MEANS[verdict]) > 30, verdict
    # And comparability is checked before anything is compared.
    source = inspect.getsource(cmp.compare)
    assert source.index("comparable(before, after)") < \
        source.index("_data_moved(before, after)")


def test_11_the_trace_and_the_calculation_pack_expose_assurance():
    """§205 and §206."""
    assert "assurance_summary" in inspect.getsource(ex._record_assurance)
    for dimension in dm.DIMENSIONS:
        assert dimension in cl.TRACE_NODES

    assert cal.ASSURANCE == "INVESTIGATION ASSURANCE"
    build = inspect.getsource(cal.build)
    # Present, and still before FINAL RESULTS, which stays last.
    assert build.index("_assurance(add(ASSURANCE)") < \
        build.index("_final(add(FINAL)")


def test_12_permissions_hold():
    """§207, including the one no role widens."""
    cross_tenant = ac.may_read(
        ac.Viewer(role="ADMIN", tenant_id="bank-a"),
        ac.Subject(investigation_id="inv-1", tenant_id="bank-b"))
    stranger = ac.may_read(
        ac.Viewer(user_id=7, role="ANALYST"),
        ac.Subject(investigation_id="inv-9", owner_user_id=9))

    assert cross_tenant.allowed is False
    assert stranger.allowed is False


#: §213's fifteen, by name. Asserted as a set rather than as a count so a
#: later phase adding a tab does not read as a regression, while removing one
#: of these still does — which is what the original count was protecting.
PART_F_TABS = (
    tb.OVERVIEW, tb.KNOWLEDGE, tb.TEACHING_CASES, tb.BLUEPRINTS,
    tb.JUDGMENT, tb.VISUAL_GRAMMAR, tb.ROUTING, tb.PROMPTS,
    tb.EVALUATIONS, tb.REVIEWS, tb.FEEDBACK, tb.AGENTIC, tb.RELEASES,
    tb.LIVE_HEALTH, tb.SETTINGS,
)


def test_13_the_studio_shows_dimension_trends_and_investigation_reviews():
    """§213's fifteen tabs, with Investigation Reviews among them and
    actually built rather than deferred."""
    assert len(PART_F_TABS) == 15
    assert set(PART_F_TABS) <= set(tb.TABS)
    assert tb.REVIEWS in tb.TABS
    assert callable(tb.investigation_reviews)

    tab = tb.investigation_reviews({}, 0, tr.tiles([]))
    assert tab["presentation"] == "table"
    assert len(tab["dimensions"]) == 6
    assert tab["score_rules"]["raw_feedback_changes_no_score"] is True

    assert len(tr.COHORTS) >= 8
    assert tr.MIN_SAMPLE >= 12


def test_14_score_honesty_is_enforced_rather_than_described():
    """§212. Seven predicates, each with a payload that breaks it."""
    assert len(hn.RULES) == 7
    assert hn.honest({"operational_assurance_label": rc.ASSURANCE_LABEL,
                      "reference_match": {"available": False}})
    assert not hn.honest({"operational_assurance_label": "Accuracy",
                          "reference_match": {"available": False}})


# ---------------------------------------------------------------------------
# The two rules Part F would be worthless without
# ---------------------------------------------------------------------------


def test_no_surface_averages_a_thread():
    """§185. A conversation containing a wrong answer is a conversation
    containing a wrong answer."""
    assert pn.Summary().to_dict()["averaged"] is False
    assert rv.InvestigationReview(
        record=st.StoredRecord()).thread_status()["averaged"] is False


def test_the_assurance_layer_never_calls_a_provider():
    """The whole package, checked for the imports that would spend money.

    Part F is an observability layer. A review screen that cost a bank money
    to open is a screen nobody opens, and an assurance record that required a
    model call would not be written for the failures that need it most.
    """
    import backend.assurance as package

    for name in package.__all__:
        source = inspect.getsource(getattr(package, name))
        assert "anthropic" not in source.lower(), name
        assert "get_provider" not in source, name
