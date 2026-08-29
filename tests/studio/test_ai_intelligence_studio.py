"""
Part C — the AI Intelligence Studio. §102-§120.

What is worth testing about a screen
-------------------------------------
Not that it renders. The Studio's whole reason to exist is that a Model Risk
reviewer, a Data Steward and a Product Owner can see what CreditProbe has been
configured with and decide whether to trust it — so what is worth testing is
the honesty of what it shows:

- every object answers §117's seven questions, and one that cannot is visibly
  incomplete rather than invisibly unexplained;
- no capability displays a percentage its sample does not support;
- readiness has five states and reaching the top one is hard;
- the sealed holdout gets a second wall, and a payload carrying a question
  raises rather than being quietly filtered;
- a permission nobody defined is refused rather than granted.

Offline throughout. Nothing in the Studio calls a provider, which is a design
property and not an accident of the test environment: a Studio that spent
credits to render a screen is a Studio nobody opens.
"""

from __future__ import annotations

import pytest

from backend.ai_studio import capabilities as cap
from backend.ai_studio import explain as ex
from backend.ai_studio import permissions as pm
from backend.ai_studio import tabs as tb
from backend.validation import intervals as me


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def admin() -> dict[str, str]:
    return {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}


def analyst() -> dict[str, str]:
    return {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "2"}


def steward() -> dict[str, str]:
    return {"X-IPM-Role": "DATA_STEWARD", "X-IPM-User-Id": "3"}


# ============================================== §117 the explanation contract


def test_every_studio_object_answers_seven_questions():
    assert len(ex.QUESTIONS) == 7
    assert ex.FIELDS == ("what", "why", "when", "validated", "performing",
                         "stale_or_failing", "release")
    for name in ex.FIELDS:
        assert ex.LABELS[name].endswith("?")


def test_an_object_that_cannot_explain_itself_is_visibly_incomplete():
    """Seven questions written in a design document get answered for the first
    three objects and skipped for the next forty, and the Studio becomes the
    admin card wall §117 says not to build."""
    partial = ex.Explanation(what="A materiality policy.", why="Because.")

    assert partial.complete is False
    assert "validated" in partial.missing
    assert partial.to_dict()["missing"]


def test_performing_may_honestly_be_not_measured():
    """The alternative — an object that must claim a score to be displayed —
    produces invented scores."""
    honest = ex.unmeasured(what="A blueprint.", why="Because.",
                           when="On broad questions.")

    assert honest.complete is True
    assert honest.performing == ex.NOT_MEASURED
    assert "no" in honest.release.lower() or "not" in honest.release.lower()


def test_a_drilldown_with_nothing_run_is_not_evaluated_rather_than_passed():
    """An unevaluated policy is not a working one."""
    fresh = ex.Drilldown()

    assert fresh.validation_status == ex.NOT_EVALUATED
    assert fresh.trustworthy is False
    assert fresh.rate is None
    assert "unknown rather than good" in fresh.sentence()


def test_a_pass_rate_of_zero_over_zero_is_none_not_zero():
    """Zero of zero displayed as 0% reads as a total failure and is the
    absence of a measurement."""
    assert ex.Drilldown(passed=0, failed=0).rate is None
    assert ex.Drilldown(passed=0, failed=4).rate == 0.0


def test_a_single_critical_failure_overrides_a_good_rate():
    scored = ex.Drilldown(validation_status=ex.PASSED, passed=98, failed=2,
                          critical_failures=["grounding on thread F"])

    assert scored.trustworthy is False
    assert "overrides the average" in scored.sentence()


def test_staleness_makes_an_object_untrustworthy_however_it_scored():
    scored = ex.Drilldown(validation_status=ex.PASSED, passed=100, failed=0,
                          staleness=["ontology"])

    assert scored.trustworthy is False
    assert "since changed" in scored.sentence()


def test_the_audit_names_every_object_that_cannot_explain_itself():
    """Run as a test rather than displayed: shipping an unexplained object
    should fail a build, not be discovered by a reader."""
    good = ex.Object(object_id="a", explanation=ex.unmeasured(
        what="x", why="y", when="z"))
    bad = ex.Object(object_id="b", explanation=ex.Explanation(what="only"))

    result = ex.audit([good, bad])

    assert result["complete"] is False
    assert result["incomplete"][0]["object_id"] == "b"
    assert ex.audit([good])["complete"] is True


# ================================================ §103 capability health


def test_the_eighteen_capabilities_section_103_names_all_have_a_meaning():
    assert len(cap.CAPABILITIES) == 18
    for capability in cap.CAPABILITIES:
        assert cap.MEANS[capability].strip(), capability


def test_a_capability_nobody_measured_appears_as_not_evaluated():
    """A capability missing from a health table reads as one that does not
    exist."""
    health = cap.health([])

    assert len(health["capabilities"]) == 18
    assert set(health["unmeasured"]) == set(cap.CAPABILITIES)
    for row in health["capabilities"]:
        assert row["status"] == cap.UNMEASURED


def test_no_capability_reports_a_percentage_its_sample_cannot_support():
    """§103's instruction. Eleven clean cases is not 100%; its lower bound is
    around 74%, which is what an honest row says."""
    small = cap.Capability(cap.INTENT, passed=11, total=11)

    assert small.rate.point == 100.0
    assert "too few observations" in small.sentence()
    assert "100" not in small.sentence().replace("100.0", "")
    assert small.status == cap.UNMEASURED


def test_a_reportable_capability_shows_its_interval():
    measured = cap.Capability(cap.INTENT, passed=95, total=100)

    assert "95% CI" in measured.sentence()
    assert measured.status in (cap.HEALTHY, cap.WATCH)


def test_a_critical_failure_is_failing_whatever_the_rate():
    """A green row over a grounding defect is the exact shape of a dashboard
    nobody should trust."""
    row = cap.Capability(cap.GROUNDING, passed=999, total=1000,
                         critical_failures=["thread F reported an uncited "
                                            "figure"])

    assert row.rate.lower > 98.0
    assert row.status == cap.FAILING
    assert "critical failure" in row.sentence()


def test_a_trend_needs_more_than_one_point():
    """A trend from one point is a line through one point, and drawing it is
    the most common way a dashboard lies."""
    first = cap.Capability(cap.PLAN, passed=90, total=100)
    assert first.trend == cap.NO_TREND

    improved = cap.Capability(cap.PLAN, passed=98, total=100,
                              previous_lower=80.0)
    assert improved.trend == cap.IMPROVING

    degraded = cap.Capability(cap.PLAN, passed=80, total=100,
                              previous_lower=95.0)
    assert degraded.trend == cap.DEGRADING


def test_a_small_move_is_steady_rather_than_a_trend():
    row = cap.Capability(cap.PLAN, passed=90, total=100, previous_lower=83.0)

    assert row.trend == cap.STEADY


def test_there_is_no_aggregate_capability_score():
    """Averaging eighteen dimensions of which one is a grounding defect
    produces a comfortable number and hides the only row that matters."""
    health = cap.health([cap.Capability(c, passed=95, total=100)
                         for c in cap.CAPABILITIES])

    assert health["no_aggregate_score"] is True
    assert "score" not in health
    assert "overall" not in health


# ============================================== §104 client-demo readiness


def test_readiness_has_the_five_states_section_104_names():
    assert len(cap.READINESS) == 5
    for state in cap.READINESS:
        assert cap.READINESS_MEANS[state].strip(), state


def test_a_stale_verification_is_stale_rather_than_a_lower_grade():
    """It is a statement about a product that no longer exists, and reading it
    as "mostly ready" is how a demo goes wrong in a way nobody predicted."""
    result = cap.readiness(cap.Signals(
        release_state="APPROVED", provider_state="CONNECTED",
        stale_axes=["ontology", "routing_policy"]))

    assert result.state == cap.READINESS_STALE
    assert "ontology" in result.sentence()
    assert result.to_improve


def test_anything_a_client_would_see_failing_is_not_ready():
    for signals in (
            cap.Signals(grounding_failures=["thread F"]),
            cap.Signals(numerical_failures=["ECL decomposition"]),
            cap.Signals(trace_failures=["agentic trace"]),
            cap.Signals(objective_coverage_failures=["three-part question"]),
            cap.Signals(critical_suite_failures=["sealed certification"]),
            cap.Signals(unavailable_roles=["complex_planner"])):
        assert cap.readiness(signals).state == cap.NOT_READY


def test_everything_measured_passing_is_a_controlled_demo_not_verified():
    """The honest answer far more often than either extreme."""
    result = cap.readiness(cap.Signals(
        provider_state="CONNECTED",
        accepted_precision=me.rate("accepted_precision", 95, 100),
        unmeasured_capabilities=["visualization", "agent_selection"]))

    assert result.state == cap.CONTROLLED_DEMO
    assert "not been evaluated" in result.sentence()
    assert result.to_improve


def test_verified_is_hard_to_reach():
    """A product that reached its top readiness state easily would have a top
    state that meant nothing."""
    almost = cap.Signals(
        release_state="APPROVED", provider_state="CONNECTED",
        live_verified_at="2026-08-28",
        accepted_precision=me.rate("accepted_precision", 20, 20))
    assert cap.readiness(almost).state == cap.CONTROLLED_DEMO

    demonstrated = cap.Signals(
        release_state="APPROVED", provider_state="CONNECTED",
        live_verified_at="2026-08-28",
        accepted_precision=me.rate("accepted_precision", 400, 400))
    assert cap.readiness(demonstrated).state == cap.VERIFIED


def test_an_offline_provider_is_limited_rather_than_not_ready():
    """It works; the live path cannot be shown. Those are different things to
    tell somebody about to walk into a meeting."""
    result = cap.readiness(cap.Signals(provider_state="OFFLINE"))

    assert result.state == cap.LIMITED
    assert "provider" in result.sentence()


def test_a_readiness_state_always_says_how_to_improve_or_why_it_is_top():
    for signals in (cap.Signals(provider_state="OFFLINE"),
                    cap.Signals(grounding_failures=["x"]),
                    cap.Signals(stale_axes=["ontology"]),
                    cap.Signals(provider_state="CONNECTED")):
        result = cap.readiness(signals)
        assert result.to_improve or result.state == cap.VERIFIED


# ==================================================== §102 the fifteen tabs


def test_the_fifteen_tabs_section_102_names_are_all_present():
    assert len(tb.TABS) == 15
    expected = ["OVERVIEW", "KNOWLEDGE", "TEACHING_CASES",
                "INVESTIGATION_BLUEPRINTS", "ANALYTICAL_JUDGMENT",
                "VISUALIZATION_GRAMMAR", "MODEL_ROUTING",
                "PROMPTS_AND_TEACHING_PACKS", "EVALUATIONS",
                "INVESTIGATION_REVIEWS", "FEEDBACK_AND_LEARNING",
                "AGENTIC_HEALTH", "RELEASES", "LIVE_AI_HEALTH", "SETTINGS"]
    assert list(tb.TABS) == expected


def test_every_tab_says_what_it_is_for():
    """A reader who cannot say what a tab is for will not open it, and the
    Studio becomes the Overview and fourteen unopened tabs."""
    for tab in tb.TABS:
        assert tb.LABELS[tab].strip(), tab
        assert len(tb.PURPOSE[tab]) > 40, tab
        assert tb.NEEDS[tab] in pm.PERMISSIONS, tab


def test_an_ordinary_analyst_opens_no_studio_tab():
    """§119: an Analyst sees only a compact assurance badge in the Trace."""
    assert tb.visible("ANALYST") == []
    assert tb.visible("VIEWER") == []
    assert len(tb.visible("ADMIN")) == 15


def test_a_steward_sees_the_read_tabs_and_not_the_authoring_ones():
    seen = tb.visible("DATA_STEWARD")

    assert tb.KNOWLEDGE in seen
    assert tb.SETTINGS not in seen
    assert tb.PROMPTS not in seen
    assert tb.EVALUATIONS not in seen


def test_the_tab_index_tells_a_caller_what_exists_and_what_they_may_open():
    """A front end that cannot ask what exists cannot explain to a reader why
    they are seeing an empty page."""
    index = tb.index("ANALYST")

    assert len(index["tabs"]) == 15
    assert index["visible"] == []
    assert all(t["purpose"] for t in index["tabs"])


# ================================================== §105-§109 the tab content


def test_the_knowledge_tab_links_to_the_editors_rather_than_reproducing_them():
    """Two editors for one object is two sets of validation, and the one that
    runs will be whichever screen the user happened to open."""
    knowledge = tb.knowledge()

    sections = {s["id"]: s for s in knowledge["sections"]}
    assert set(sections) == {"ontology", "methods", "data_semantics", "agents"}
    for section in sections.values():
        assert section["edit_in"].startswith("/"), section["id"]
        assert section["explanation"]["complete"] is True, section["id"]


def test_every_blueprint_explains_itself_completely():
    payload = tb.blueprints()

    assert payload["count"] >= 15
    assert payload["explanation_audit"]["complete"] is True
    for obj in payload["objects"]:
        assert obj["explanation"]["complete"] is True
        assert obj["mandatory_objectives"]
        assert "may_be_omitted" in obj


def test_the_judgment_tab_shows_the_rules_rather_than_describing_them():
    """"Materiality is assessed against a weighted model" tells a Model Risk
    reviewer nothing they can challenge. The weights tell them everything."""
    payload = tb.judgment()

    assert list(payload["policies"]) == list(tb.JUDGMENT_SUBTABS)
    materiality = payload["policies"]["MATERIALITY"]
    assert materiality["rules"]["weights"]
    assert materiality["rules"]["bands"]
    assert materiality["explanation"]["complete"] is True

    contradictions = payload["policies"]["CONTRADICTIONS"]
    assert len(contradictions["rules"]["checks"]) == 15
    assert len(contradictions["rules"]["taxonomy"]) == 13


def test_the_visual_grammar_tab_shows_all_fifteen_roles_and_the_mapping():
    payload = tb.visual_grammar()

    assert len(payload["roles"]) == 15
    assert len(payload["mapping"]) == 15
    assert len(payload["critic"]) == 12
    assert payload["precision_contract"]["max_decimals"] == 2
    assert payload["interactions"]


def test_the_result_shape_lab_needs_no_portfolio_data():
    """"No live portfolio data required" is the instruction, and a lab that
    accepted rows would be a lab somebody pasted a client extract into."""
    from backend.judgment import visual_grammar as vg

    result = tb.result_shape_lab(
        vg.CATEGORY_RANKING,
        {"category": vg.CATEGORY, "value": vg.MEASURE},
        categories=60, longest_label=12, measures=1, cardinality=60)

    assert result["used_live_data"] is False
    assert result["chosen"] == vg.TREEMAP
    # Every candidate, with its score and its rejection.
    assert len(result["candidates"]) >= 3
    refused = [c for c in result["candidates"] if not c["accepted"]]
    assert refused and all(c["rejections"] for c in refused)


def test_the_shape_lab_refuses_a_shape_the_grammar_does_not_know():
    result = tb.result_shape_lab("interpretive_dance", {})

    assert result["error"] == "unknown_shape"
    assert len(result["shapes"]) == 15


# ================================================== §119 permissions


def test_the_eight_permissions_section_119_names_all_have_a_meaning():
    assert len(pm.PERMISSIONS) == 8
    for permission in pm.PERMISSIONS:
        assert len(pm.MEANS[permission]) > 20, permission


def test_an_unknown_permission_is_refused_rather_than_granted():
    """The permissive version turns a typo in a route decorator into an open
    door."""
    assert pm.holds("ADMIN", "AI_SOMETHING_NEW") is False
    assert pm.holds("NOT_A_ROLE", pm.VIEW) is False


def test_authoring_and_approving_are_separated():
    """A person who writes a case and approves their own has produced a case
    with an approval record and no review."""
    assert (pm.TEACHING_AUTHOR, pm.TEACHING_REVIEW) in pm.SEPARATED
    assert pm.matrix()["separated_duties"]


def test_permissions_are_enforced_backend_side():
    """A Studio tab hidden in the front end is a tab reachable with curl."""
    assert pm.matrix()["enforced"] == "backend"


def test_the_analyst_badge_carries_no_score_and_no_case_count():
    """An analyst who could read which cases production retrieves would be
    most of the way to knowing how to phrase a question to get a chosen
    answer."""
    shown = pm.badge("rel-1", "APPROVED", cap.CONTROLLED_DEMO)

    assert set(shown) == {"release_id", "state", "readiness"}


# ================================================== §120 holdout safety


def test_only_section_120s_whitelist_reaches_a_screen():
    view = pm.holdout_view({
        "version": "2.0.0", "case_count": 90, "families": ["ECL"],
        "critical_count": 32, "evaluation_result": "PASS",
        "fingerprint": "ab12cd34"})

    assert view["case_count"] == 90
    assert set(pm.HOLDOUT_SHOWN) <= set(view)
    for forbidden in pm.HOLDOUT_NEVER:
        assert forbidden not in view


def test_a_holdout_payload_carrying_content_raises_rather_than_filtering():
    """A payload silently stripped would let the caller go on building them,
    and the next one would be assembled somewhere this function does not
    run."""
    for leaky in ({"questions": ["what is total ECL?"]},
                  {"gold_results": [{"ecl": 1}]},
                  {"answers": ["4.1%"]},
                  {"labels": ["correct"]}):
        with pytest.raises(pm.HoldoutLeak):
            pm.holdout_view({"version": "2.0.0", **leaky})


def test_the_holdout_view_says_what_it_is_withholding():
    view = pm.holdout_view({"version": "2.0.0"})

    assert view["withheld"]
    assert "production planner cannot reach them" in view["note"]


# ======================================================= over HTTP


def test_the_studio_routes_answer_for_an_administrator(client):
    for path in ("tabs", "readiness", "capabilities", "knowledge",
                 "blueprints", "judgment", "visual-grammar", "permissions",
                 "holdout", "badge"):
        response = client.get(f"/api/v1/intelligence/studio/{path}",
                              headers=admin())
        assert response.status_code == 200, (path, response.text[:200])


def test_the_settings_tab_is_administrator_only(client):
    for path in ("permissions", "holdout"):
        refused = client.get(f"/api/v1/intelligence/studio/{path}",
                             headers=analyst())
        assert refused.status_code == 403, path


def test_an_analyst_gets_the_badge_and_an_empty_tab_list(client):
    tabs = client.get("/api/v1/intelligence/studio/tabs",
                      headers=analyst()).json()
    assert tabs["visible"] == []
    assert len(tabs["tabs"]) == 15

    badge = client.get("/api/v1/intelligence/studio/badge",
                       headers=analyst()).json()
    assert set(badge) == {"release_id", "state", "readiness"}


def test_the_shape_lab_route_returns_every_candidate(client):
    response = client.post(
        "/api/v1/intelligence/studio/shape-lab", headers=admin(),
        json={"shape": "change_decomposition",
              "roles": {"category": "ENTITY",
                        "value": "DECOMPOSITION_COMPONENT"},
              "categories": 9, "measures": 1, "cardinality": 9})

    body = response.json()
    assert response.status_code == 200
    assert body["chosen"] == "waterfall"
    assert body["used_live_data"] is False
    assert body["candidates"]


def test_the_readiness_route_never_claims_more_than_it_can_show(client):
    body = client.get("/api/v1/intelligence/studio/readiness",
                      headers=admin()).json()

    assert body["state"] in cap.READINESS
    assert body["state"] != cap.VERIFIED
    assert "99.99" not in body["sentence"]


def test_no_studio_route_leaks_a_key_or_a_holdout_question(client):
    """The two things §120 and the security policy both forbid, checked on
    every payload the Studio serves rather than on the two that seem most
    likely."""
    for path in ("tabs", "readiness", "capabilities", "knowledge",
                 "blueprints", "judgment", "visual-grammar", "permissions",
                 "holdout", "badge"):
        text = client.get(f"/api/v1/intelligence/studio/{path}",
                          headers=admin()).text.lower()
        for forbidden in ("sk-ant", "authorization:", "api_key",
                          "anthropic_api_key", "bearer "):
            assert forbidden not in text, (path, forbidden)


# =========================================== §106, §110-§116 the other tabs


def test_the_routing_tab_names_roles_and_never_a_model_id():
    """§110: do not hard-code model IDs. The role is named; what serves it is
    configuration, and a Studio that named one would be wrong the week after
    the next model ships."""
    payload = tb.routing()

    assert payload["roles"]
    for role in payload["roles"]:
        assert "claude" not in role["name"].lower()
        assert "opus" not in role["name"].lower()
    assert set(payload["why"]) == {"routine", "complex", "critic", "none"}
    for why in payload["why"].values():
        assert len(why) > 40


def test_the_route_simulator_makes_no_call():
    """An administrator who can try twenty phrasings for nothing will, and one
    who spends a call per try will try none — which is how a routing policy
    goes unexamined."""
    result = tb.route_simulator("what is total ECL by sector?")

    assert result["called_a_provider"] is False
    assert "nothing was spent" in result["note"]


def test_the_prompts_tab_shows_the_pack_policy_and_not_prompt_text():
    """§111: do not expose secrets or client content. A prompt is the artefact
    most likely to have accumulated a hard-coded example from a real
    portfolio."""
    payload = tb.prompts()

    assert payload["pack_policy"]["included"]
    assert payload["pack_policy"]["excluded"]
    assert payload["promotion"]["requires"]
    text = str(payload).lower()
    for forbidden in ("sk-ant", "api_key", "authorization"):
        assert forbidden not in text


def test_the_evaluations_tab_keeps_the_seven_suites_apart():
    payload = tb.evaluations()

    assert len(payload["subtabs"]) == 7
    assert payload["reporting_rules"]["no_combined_score"] is True
    assert payload["cost_control"]["confirmation_required"] is True


def test_a_live_evaluation_cannot_start_by_accident():
    """An evaluation that can start by accident is one somebody starts by
    accident."""
    assert tb.evaluations()["cost_control"]["confirmation_required"] is True


def test_the_live_health_tab_gives_commands_and_never_a_key():
    payload = tb.live_health({"state": "OFFLINE"}, {"roles": []})

    assert len(payload["commands"]) >= 3
    for command in payload["commands"]:
        assert command["windows"] and command["unix"]
        assert "sk-ant" not in command["windows"]
        assert "Authorization" not in command["unix"]
    assert "API keys" in payload["never_shown"]


def test_the_releases_tab_says_the_holdout_is_never_packaged():
    payload = tb.releases({"state": "UNRELEASED"}, {}, ["manifest.json"], [])

    assert "sealed holdout" in payload["never"]
    assert any(a["id"] == "promote" for a in payload["actions"])
    for action in payload["actions"]:
        assert action["needs"] in pm.PERMISSIONS


def test_the_failures_tab_says_there_is_no_automatic_learning():
    """§114's last line, and the whole shape of the tab."""
    payload = tb.failures([])

    assert payload["no_automatic_learning"] is True
    assert "Unreviewed feedback never changes production" in payload["note"]
    assert len(payload["categories"]) == 24


def test_the_teaching_cases_tab_leads_with_the_governance_sentence():
    """The answer to the question a Model Risk reviewer actually has: how
    many of these has a person read?"""
    payload = tb.teaching_cases(
        {"total": 2453},
        {"sentence": "2453 teaching cases. 0 carry a named human approval."},
        [])

    performing = [a for a in payload["explanation"]["answers"]
                  if a["id"] == "performing"][0]
    assert "0 carry a named human approval" in performing["answer"]
    assert "Sealed-holdout content is never shown" in payload["never_shown"]


# ==================================== §121-§123 export, notifications, audit


def test_the_report_has_all_thirteen_sheets_even_when_empty():
    """A report whose contents depend on what was available produces two
    documents with the same title and different meanings."""
    from backend.ai_studio import report as rp

    built = rp.build()

    assert len(built["sheets"]) == 13
    assert [s["name"] for s in built["sheets"]] == list(rp.SHEETS)
    for sheet in built["sheets"]:
        assert sheet["contents"], sheet["name"]
        assert sheet["note"], sheet["name"]


def test_the_report_refuses_to_carry_a_secret_or_a_holdout_answer():
    """An export is the one artefact that leaves the building. Everything
    else here can be wrong and corrected; an export that left with a holdout
    question in it cannot be recalled."""
    from backend.ai_studio import report as rp

    for leaky in ({"Overview": [{"note": "sk-ant-api03-xxx"}]},
                  {"Critical Failures": [{"detail": "gold_answer: 4.1%"}]},
                  {"Model Routing": [{"header": "Authorization: Bearer x"}]}):
        with pytest.raises(rp.WouldLeak):
            rp.build(leaky)


def test_the_ten_notification_events_section_122_names_all_route_somewhere():
    from backend.ai_studio import report as rp

    assert len(rp.EVENTS) == 10
    for event in rp.EVENTS:
        assert rp.NOTIFY[event] in pm.PERMISSIONS, event
        assert len(rp.SAYS[event]) > 30, event


def test_an_unknown_notification_is_refused_rather_than_sent_to_everybody():
    """A notification with no defined audience is one the whole administrator
    group learns to ignore."""
    from backend.ai_studio import report as rp

    with pytest.raises(KeyError):
        rp.notification("something_happened")


def test_an_audit_entry_needs_a_named_actor_and_a_reason():
    """"system changed a routing policy" is not an audit trail, and a change
    with no reason cannot be reviewed — only reverted, by somebody who does
    not know why it was made."""
    from backend.ai_studio import report as rp

    with pytest.raises(ValueError):
        rp.record("policy_changed", user="", object_id="materiality",
                  reason="raised the floor")
    with pytest.raises(ValueError):
        rp.record("policy_changed", user="admin#1",
                  object_id="materiality", reason="   ")
    with pytest.raises(KeyError):
        rp.record("did_a_thing", user="admin#1", object_id="x", reason="y")

    entry = rp.record("policy_changed", user="admin#1",
                      object_id="materiality",
                      reason="raised the appetite floor after the Q2 review",
                      old_version="1.0.0", new_version="1.1.0",
                      affected_release="rel-7")
    assert set(entry.to_dict()) == set(rp.AUDIT_FIELDS)
    assert entry.at


def test_the_twelve_audited_actions_section_123_names_are_all_covered():
    from backend.ai_studio import report as rp

    assert len(rp.AUDITED) == 12
    for action in ("case_approved", "prompt_changed", "routing_changed",
                   "policy_changed", "release_promoted",
                   "release_rolled_back", "live_verification",
                   "fine_tuning_export"):
        assert action in rp.AUDITED


def test_the_remaining_studio_routes_answer_for_an_administrator(client):
    for path in ("routing-tab", "prompts", "evaluations", "releases-tab",
                 "live-health", "failures", "report", "audit-actions"):
        response = client.get(f"/api/v1/intelligence/studio/{path}",
                              headers=admin())
        assert response.status_code == 200, (path, response.text[:200])


def test_the_route_simulator_route_spends_nothing(client):
    response = client.post("/api/v1/intelligence/studio/route-simulator",
                           headers=admin(),
                           json={"question": "what moved in Contracting?"})

    assert response.status_code == 200
    assert response.json()["called_a_provider"] is False


def test_an_analyst_may_not_open_the_authoring_tabs(client):
    for path in ("teaching-cases", "prompts", "evaluations", "failures",
                 "report", "audit-actions", "live-health"):
        refused = client.get(f"/api/v1/intelligence/studio/{path}",
                             headers=analyst())
        assert refused.status_code == 403, path
