"""
§43-§46 — the frozen Teaching Release, its gate, and what a Trace may say.

The distinction the whole group rests on
-----------------------------------------
Everything else in this package answers "what may be retrieved right now". A
release answers "what was retrievable when this answer was produced". They come
apart the moment somebody approves a case, and the gap between them is where an
unexplainable answer lives: a Trace naming five teaching cases, two of which
have since been edited, and nothing that can reconstruct what the planner saw.
"""

from __future__ import annotations

import json

import pytest

from backend.orchestration import objectives as ob
from backend.orchestration import routing as rt
from backend.teaching import disclosure as dc
from backend.teaching import release as rl
from backend.teaching import retrieval as rv
from backend.teaching import schema as sc
from backend.teaching import status as st


def _case(case_id="tc-1", *, status=st.APPROVED, **over) -> sc.TeachingCase:
    base = dict(
        case_id=case_id, title="Total EAD by sector",
        family_id="SINGLE_DOMAIN_AGGREGATION",
        question="What is total exposure at default by sector?",
        objectives=[sc.Objective(id="o1", text="total EAD by sector")],
        analytical_plan_contract={"group_by": ["sector"]},
        concepts=["exposure at default"], ontology_version="2.0.0",
        cluster_id=f"cl-{case_id}",
    )
    base.update(over)
    case = sc.TeachingCase(**base)
    case.review_status = status
    return sc.sealed(case)


@pytest.fixture
def frozen(tmp_path):
    payload = rl.build([_case("a"), _case("b"), _case("c", status=st.DRAFT)],
                       git_sha="abc12345",
                       prompts={"planner": "PLAN", "critic": "FIX"},
                       routing_policy={"complex_at": 3},
                       model_roles=["router", "complex_planner"])
    return rl.freeze(payload, directory=tmp_path), tmp_path


# =========================================================== §43 the release


def test_a_release_contains_every_file_section_43_lists(frozen):
    path, _ = frozen
    assert {p.name for p in path.iterdir()} == set(rl.FILES)


def test_only_approved_cases_go_into_a_release(frozen):
    """§44: "Do not silently use unapproved draft cases." This filter is that
    sentence."""
    path, _ = frozen
    _, cases, missing = rl.load(path)
    assert missing == []
    assert {c.case_id for c in cases} == {"a", "b"}


def test_the_manifest_carries_what_section_43_names(frozen):
    path, _ = frozen
    manifest, _, _ = rl.load(path)
    assert manifest.release_id.startswith("tr-")
    assert manifest.git_sha == "abc12345"
    assert manifest.created_at
    assert manifest.case_counts_by_status[st.APPROVED] == 2
    assert manifest.case_counts_by_family["SINGLE_DOMAIN_AGGREGATION"] == 2
    assert set(manifest.prompt_versions) == {"planner", "critic"}
    assert manifest.routing_policy == {"complex_at": 3}
    assert manifest.model_role_names
    assert manifest.ontology_version == "2.0.0"
    assert manifest.certification_status == "DRAFT"


def test_a_release_cannot_be_overwritten(frozen):
    """A release that can be rewritten is not frozen, and every Trace naming it
    becomes unverifiable the moment it is."""
    path, directory = frozen
    payload = rl.build([_case("a")], git_sha="abc12345")
    payload["manifest.json"]["release_id"] = path.name
    with pytest.raises(FileExistsError):
        rl.freeze(payload, directory=directory)


def test_a_release_never_carries_holdout_content():
    """§41: the retrieval service cannot access holdout cases or labels. A
    release that carried them would hand them to everything downstream at
    once."""
    payload = rl.build([_case("a")], holdout_manifest={
        "case_count": 40, "families": ["AMBIGUITY"],
        "examples": ["what is the answer to case 12"],
        "gold": {"HB-1": 8563}})
    stored = payload["holdout_manifest.json"]
    assert set(stored) == {"case_count", "families"}
    assert "gold" not in json.dumps(stored)


def test_a_release_needs_named_reviewers_to_be_approved(frozen):
    path, _ = frozen
    with pytest.raises(ValueError):
        rl.approve(path, reviewers=[])
    with pytest.raises(ValueError):
        rl.approve(path, reviewers=["  "])

    manifest = rl.approve(path, reviewers=["Amal"], note="read the corpus")
    assert manifest.certification_status == rl.APPROVED
    assert manifest.reviewers == ["Amal"]


def test_the_approval_is_recorded_separately_from_the_manifest(frozen):
    path, _ = frozen
    rl.approve(path, reviewers=["Amal"], note="read the corpus")
    record = json.loads((path / "approval_record.json").read_text())
    assert record["status"] == rl.APPROVED
    assert record["reviewers"] == ["Amal"]
    assert record["approved_at"]
    assert record["note"] == "read the corpus"


# ============================================================== §44 the gate


def test_an_unapproved_release_is_not_usable(frozen):
    _, directory = frozen
    verdict = rl.gate(require_release=True, directory=directory)
    assert verdict.state == rl.UNAVAILABLE
    assert not verdict.usable
    assert "not been approved" in verdict.reason


def test_an_approved_release_is_usable(frozen):
    path, directory = frozen
    rl.approve(path, reviewers=["Amal"])
    verdict = rl.gate(require_release=True, directory=directory)
    assert verdict.state == rl.APPROVED
    assert verdict.usable
    assert verdict.release_id == path.name


def test_no_release_at_all_is_named_rather_than_fallen_back_from(tmp_path):
    """"The approved cases" and "whatever happens to be approved" are
    different things, and only one of them was reviewed."""
    verdict = rl.gate(require_release=True, directory=tmp_path)
    assert verdict.state == rl.UNAVAILABLE
    assert not verdict.usable


def test_an_incomplete_release_is_unavailable(frozen):
    path, directory = frozen
    rl.approve(path, reviewers=["Amal"])
    (path / "thresholds.json").unlink()
    verdict = rl.gate(require_release=True, directory=directory)
    assert verdict.state == rl.UNAVAILABLE
    assert "incomplete" in verdict.reason


@pytest.mark.parametrize("axis,value", [
    ("git_sha", "0" * 8),
    ("ontology", "9.9.9"),
    ("routing_policy", "different"),
])
def test_a_release_goes_stale_when_the_world_moves_under_it(frozen, axis,
                                                            value):
    path, directory = frozen
    rl.approve(path, reviewers=["Amal"])
    verdict = rl.gate(require_release=True, directory=directory,
                      current={axis: value})
    assert verdict.state == rl.STALE
    assert axis in verdict.moved
    assert not verdict.usable


def test_a_stale_release_is_worse_than_no_release(frozen):
    """It is describing a product that no longer exists, and it looks like a
    release while doing it."""
    path, directory = frozen
    rl.approve(path, reviewers=["Amal"])
    stale = rl.gate(require_release=True, directory=directory,
                    current={"git_sha": "moved"})
    assert not stale.usable


def test_an_axis_nobody_versions_does_not_make_a_release_stale(frozen):
    path, directory = frozen
    rl.approve(path, reviewers=["Amal"])
    assert rl.gate(require_release=True, directory=directory,
                   current={}).state == rl.APPROVED


def test_development_runs_off_the_live_library_and_says_so():
    """§44 allows it explicitly. What makes it acceptable is the label."""
    verdict = rl.gate(require_release=False)
    assert verdict.state == rl.UNRELEASED
    assert verdict.usable
    assert "live teaching library" in verdict.reason


def test_the_four_states_are_the_ones_section_44_names():
    assert set(rl.STATES) == {rl.APPROVED, rl.STALE, rl.UNAVAILABLE,
                              rl.UNRELEASED}


# =============================================== §45 and §46 the disclosure


def _panel(**over):
    cases = [_case("a"), _case("b", cluster_id="cl-b")]
    result = rv.retrieve(cases, rv.Need(
        question="What is total exposure at default by sector?",
        capability="ANALYSIS", concepts=("exposure at default",)))
    decision = rt.decide("Decompose the change in ECL in Contracting.")
    cascade = rt.Cascade()
    cascade.attempt(rt.COMPLEX, why="direct route")
    coverage = ob.coverage(ob.read("What is total EAD by sector, and which "
                                   "sectors grew fastest?"))
    coverage.objectives[0].settle(ob.COMPLETE)
    base = dict(gate=rl.Gate(rl.UNRELEASED), retrieval=result,
                decision=decision, cascade=cascade, coverage=coverage,
                plan_validation={"status": "PASS"},
                result_validation={"status": "PASS", "failed": []},
                rubric={"status": "PASS"})
    base.update(over)
    return dc.panel(**base)


def test_the_panel_has_every_section_section_45_names():
    built = _panel()
    assert set(dc.SECTIONS) <= set(built)


def test_an_absent_section_is_empty_rather_than_missing():
    """A Trace that omits "critic_repair" when no critic ran reads as a Trace
    that forgot to record it."""
    built = _panel()
    assert built["critic_repair"] == {}
    assert "critic_repair" in built


def test_retrieval_reports_ids_and_relevance_and_never_case_content():
    """The worked example went to the planner. Putting it in a Trace an
    ordinary user reads puts a governed teaching case in front of an audience
    it was never reviewed for."""
    retrieval = _panel()["teaching_retrieval"]
    assert retrieval["cases"]
    for entry in retrieval["cases"]:
        assert set(entry) == {"case_id", "case_version", "relevance",
                              "matched_features", "why", "cluster", "tokens",
                              "status", "ontology_version"}
    assert "group_by" not in json.dumps(retrieval)


def test_routing_shows_the_initial_and_final_route_and_the_escalation():
    routing = _panel()["model_routing"]
    assert routing["initial_route"]
    assert routing["final_route"]
    assert routing["model_role"]
    assert "cascade" in routing
    assert routing["route_reasons"]


def test_objective_coverage_is_shown_with_its_statuses():
    coverage = _panel()["objective_coverage"]
    assert coverage["total"] == 2
    assert coverage["complete"] == 1
    assert coverage["by_status"][ob.COMPLETE] == 1
    assert coverage["presentable"] is False


def test_a_prompt_is_withheld_from_an_ordinary_user_rather_than_omitted():
    """An absent row reads as "there was no prompt", which is a different and
    untrue statement."""
    built = _panel(prompts={"planner": "THE CONFIDENTIAL PROMPT"})
    assert built["prompts"] == {"planner": dc.WITHHELD}
    assert "CONFIDENTIAL" not in json.dumps(built)


def test_an_administrator_sees_the_prompt():
    built = _panel(prompts={"planner": "THE CONFIDENTIAL PROMPT"},
                   viewer_role="ADMIN")
    assert built["prompts"]["planner"] == "THE CONFIDENTIAL PROMPT"


@pytest.mark.parametrize("payload", [
    {"gold_answer": 5},
    {"nested": {"holdout_case": "HB-1"}},
    {"chain_of_thought": "first I thought"},
    {"cases": [{"sealed_result": 1}]},
])
def test_anything_that_looks_like_an_answer_key_is_refused(payload):
    """Raised rather than filtered: a silent filter means the caller never
    finds out, and the next surface that forgets to filter shows it."""
    with pytest.raises(dc.Leak):
        dc.panel(plan_validation=payload)


def test_a_value_that_merely_looks_like_gold_is_not_refused():
    """Matched on the key, not the value. A value that happens to equal the
    gold answer is the product being right; a KEY called "gold" is the seal
    being broken."""
    built = dc.panel(plan_validation={"status": "PASS", "note": "the gold "
                                                                "standard"})
    assert built["plan_validation"]["note"]


# ------------------------------------------------------------- §46 the rows


def test_the_pack_rows_cover_section_46s_list():
    labels = {label for label, _ in dc.sheet_rows(_panel())}
    assert {"Teaching Release", "Teaching cases retrieved", "Prompt versions",
            "Final route", "Escalated from", "Objective coverage",
            "Plan validation", "Critic result", "Interpretation rubric"} \
        <= labels


def test_the_pack_rows_are_a_rendering_of_the_same_panel():
    """Written twice they drift, and the way they drift is that one of them
    starts showing something the other redacts."""
    built = _panel(prompts={"planner": "SECRET"})
    rendered = dict(dc.sheet_rows(built))
    assert rendered["Final route"] == built["model_routing"]["final_route"]
    assert "SECRET" not in json.dumps(rendered)


def test_an_empty_value_renders_as_a_dash_rather_than_a_blank():
    """A blank cell in a governed pack is indistinguishable from a bug."""
    rows = dc.sheet_rows(dc.panel())
    assert all(value for _, value in rows)


def test_the_summary_says_the_two_things_a_reader_wants_first():
    said = dc.summary(_panel())
    assert "complex_planner" in said
    assert "1 of 2 objectives" in said
