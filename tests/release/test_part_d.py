"""
Part D — §125's integration, §127's references, §128's gate, §130's safe mode,
§131's quality gates.

The four instructions these enforce
------------------------------------
    §125: "Do not duplicate existing runtime services."
    §127: "Any relevant change makes the release STALE."
    §128: "Do not promote on average score alone."
    §130: "no best-effort incomplete answer"

Each is a place where the convenient behaviour and the correct one differ, and
each has a cheap wrong version that looks identical from outside: a second
pipeline that agrees with the first until it doesn't, a staleness check that
skips the axis nobody remembered, a promotion decided by an aggregate, and an
answer that is 80% right and looks 100% right.
"""

from __future__ import annotations

import pytest

from backend.orchestration import judgment_bridge as jb
from backend.release import demo_safe as ds
from backend.release import promotion as pr
from backend.release import references as rf

# ===================================================== §125 the integration


def test_the_bridge_states_what_it_adds_and_what_it_leaves_alone():
    """§125's instruction is not to duplicate, and a module that cannot say
    what it does not do will duplicate something."""
    assert "the P0.8 presentability gate" in jb.RUNTIME_OWNS
    assert "the visualization selector" in jb.RUNTIME_OWNS
    assert "the Evidence Fact Graph" in jb.BRIDGE_ADDS
    assert set(jb.RUNTIME_OWNS) & set(jb.BRIDGE_ADDS) == set()


def test_a_fact_without_its_run_is_refused():
    """A statement whose provenance is "the system" cannot be checked by
    anybody, which is why source_run_id is mandatory on a Fact."""
    graph = jb.facts_from(None, None, "")

    assert len(graph.facts) == 0


def test_the_bridge_never_raises():
    """A judgment layer that could turn a correct answer into a five hundred
    is one that gets removed, and then none of it runs."""

    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("everything is on fire")

    block = jb.assess(Broken(), Broken())

    assert "unavailable" in block or "rubric" in block
    if "unavailable" in block:
        assert block["note"]


def test_an_unassessable_answer_says_so_rather_than_passing():
    class Empty:
        narrative = None
        graph = None
        question = "q"
        analysis_run_id = ""

    block = jb.assess(Empty(), Empty())

    assert "runtime_owns" in block
    # Either it assessed, or it said it could not. Never silence.
    assert "rubric" in block or "unavailable" in block


# ================================================ §127 the release references


def test_the_fourteen_references_section_127_names_all_have_a_reason():
    assert len(rf.REFERENCES) == 14
    for reference in rf.REFERENCES:
        assert len(rf.BECAUSE[reference]) > 25, reference


def test_the_current_versions_are_read_from_the_modules_themselves():
    """A version bumped in code should be noticed without anybody remembering
    to record it somewhere else — which is the failure this whole mechanism
    exists to prevent."""
    from backend.judgment import blueprints as bp
    from backend.judgment import contradictions as cd
    from backend.judgment import visual_grammar as vg

    now = rf.current()

    assert now[rf.BLUEPRINTS] == bp.BLUEPRINT_VERSION
    assert now[rf.CONTRADICTION_TAXONOMY] == cd.CONTRADICTION_VERSION
    assert now[rf.VISUALIZATION_GRAMMAR] == vg.GRAMMAR_VERSION


def test_a_reference_the_release_never_recorded_is_stale_not_agreed():
    """A blank is not evidence of agreement."""
    moved = rf.stale(rf.Manifest(versions={}))

    assert moved
    for entry in moved:
        assert entry["was"] == rf.UNVERSIONED
        assert entry["because"]


def test_a_reference_that_moved_is_named_with_what_it_was_and_is():
    manifest = rf.build("rel-1")
    manifest.versions[rf.VISUALIZATION_GRAMMAR] = "0.0.1"

    moved = rf.stale(manifest)

    entry = next(m for m in moved
                 if m["reference"] == rf.VISUALIZATION_GRAMMAR)
    assert entry["was"] == "0.0.1"
    assert entry["now"] != "0.0.1"


def test_a_release_cut_now_is_not_stale_against_now():
    manifest = rf.build("rel-1")

    assert rf.stale(manifest) == []


def test_a_reference_nobody_can_version_today_is_skipped_not_reported():
    """Reporting "changed" from ignorance would make the whole check noise."""
    manifest = rf.build("rel-1")

    moved = rf.stale(manifest, now={rf.BLUEPRINTS: "",
                                    rf.ONTOLOGY: ""})

    assert moved == []


# ===================================================== §128 the promotion gate


def _all(outcome: str = pr.PASS) -> dict[str, str]:
    return {c: outcome for c in pr.CONDITIONS}


def test_the_thirteen_conditions_section_128_names_all_ask_something():
    assert len(pr.CONDITIONS) == 13
    for condition in pr.CONDITIONS:
        assert pr.ASKS[condition].endswith("?"), condition


def test_a_release_meeting_all_thirteen_may_be_promoted():
    gate = pr.gate("rel-1", _all())

    assert gate.may_promote is True
    assert gate.blocking == []


def test_a_release_is_not_promoted_on_an_average():
    """A release with a 96% aggregate and one grounding failure will be
    promoted by any process that looks at the aggregate first, and the
    grounding failure is the whole reason not to."""
    gate = pr.gate("rel-1", {**_all(), pr.GROUNDING: pr.FAIL})

    assert gate.rate > 0.9
    assert gate.may_promote is False
    assert gate.to_dict()["promoted_on_average"] is False


def test_an_unchecked_condition_blocks_as_hard_as_a_failed_one():
    """A promotion process that treats an unrun check as satisfied gets
    faster the fewer checks you run."""
    gate = pr.gate("rel-1", {**_all(), pr.TRACE: pr.UNCHECKED})

    assert gate.may_promote is False
    assert pr.TRACE in gate.blocking[0].condition


def test_a_gate_with_nothing_supplied_refuses():
    gate = pr.gate("rel-1", {})

    assert gate.may_promote is False
    assert len(gate.blocking) == 13


def test_the_two_exact_conditions_admit_no_exceptions():
    """The deterministic reference is independently computed and the
    grounding check is mechanical, so 99% means somebody looked at a specific
    failure and shipped anyway."""
    assert pr.NUMERICAL in pr.EXACT
    assert pr.GROUNDING in pr.EXACT

    gate = pr.from_rates("rel-1", {pr.NUMERICAL: (999, 1000)},
                         reviewers=["a"], configuration_matches=True)

    assert gate.get(pr.NUMERICAL).outcome == pr.FAIL
    assert "admits no exceptions" in gate.get(pr.NUMERICAL).detail


def test_a_condition_with_no_cases_is_unchecked_rather_than_passed():
    gate = pr.from_rates("rel-1", {pr.SAME_TURN: (0, 0)},
                         reviewers=["a"], configuration_matches=True)

    assert gate.get(pr.SAME_TURN).outcome == pr.UNCHECKED
    assert "no cases were run" in gate.get(pr.SAME_TURN).detail


def test_a_release_with_no_named_reviewer_is_not_promoted():
    gate = pr.from_rates("rel-1", {c: (10, 10) for c in pr.CONDITIONS
                                   if c not in (pr.REVIEWERS,
                                                pr.CONFIGURATION, pr.COST)},
                         reviewers=[], configuration_matches=True,
                         within_budget=True)

    assert gate.get(pr.REVIEWERS).outcome == pr.FAIL
    assert gate.may_promote is False


def test_a_release_certified_against_a_different_build_is_not_promoted():
    gate = pr.from_rates("rel-1", {c: (10, 10) for c in pr.CONDITIONS
                                   if c not in (pr.REVIEWERS,
                                                pr.CONFIGURATION, pr.COST)},
                         reviewers=["model risk"],
                         configuration_matches=False, within_budget=True)

    assert gate.get(pr.CONFIGURATION).outcome == pr.FAIL
    assert "different SHA" in gate.get(pr.CONFIGURATION).detail


def test_an_unknown_condition_is_refused():
    with pytest.raises(KeyError):
        pr.from_rates("rel-1", {"feels_right": (10, 10)})
    with pytest.raises(ValueError):
        pr.gate("rel-1", {pr.TRACE: "PROBABLY"})


# ==================================================== §130 Demo Safe Mode


def test_the_twelve_conditions_section_130_names_all_ask_something():
    assert len(ds.CONDITIONS) == 12
    for condition in ds.CONDITIONS:
        assert ds.ASKS[condition].endswith("?"), condition


def test_every_condition_is_required_in_demo_safe_mode():
    """§130 lists twelve and does not rank them."""
    for condition in ds.CONDITIONS:
        met = {c: True for c in ds.CONDITIONS if c != condition}
        assert ds.check(met, active=True).may_show is False, condition


def test_all_twelve_met_may_be_shown():
    assert ds.check({c: True for c in ds.CONDITIONS},
                    active=True).outcome == ds.SHOW


def test_a_condition_a_question_could_fix_asks_rather_than_failing():
    """A question is obviously a question. A caveated answer still reads as
    an answer."""
    met = {c: True for c in ds.CONDITIONS if c != ds.BLUEPRINT_COVERAGE}

    assert ds.check(met, active=True).outcome == ds.CLARIFY


def test_a_stale_release_is_a_controlled_failure_not_a_clarification():
    """No rephrasing fixes a stale release."""
    met = {c: True for c in ds.CONDITIONS if c != ds.NOT_STALE}

    assert ds.check(met, active=True).outcome == ds.CONTROLLED_FAILURE


def test_nothing_supplied_is_not_safe():
    """The permissive default would make an answer safe for a client
    demonstration by virtue of nobody having checked it."""
    assert ds.check({}, active=True).may_show is False


def test_the_mode_is_off_by_default():
    """A mode that refuses answers should be turned on deliberately, and one
    that defaults on would be turned off by the first person it
    inconvenienced."""
    import os

    was = os.environ.pop(ds.ENV, None)
    try:
        assert ds.enabled() is False
    finally:
        if was is not None:
            os.environ[ds.ENV] = was


def test_with_the_mode_off_the_verdict_still_says_what_would_have_failed():
    """So somebody can see what turning it on would change."""
    verdict = ds.check({}, active=False)

    assert verdict.may_show is True
    assert len(verdict.unmet) == 12
    # "Demo Safe Mode" was the old name. The posture is unchanged -- refuse to
    # show an answer that cannot be fully validated -- but §13 bans the word,
    # and the posture is one a bank may want on its own book, which is exactly
    # why its name should never have said "demo". The stronger assertion: the
    # sentence names the mode AND still says what turning it on would change.
    assert "Client Safe Mode is off" in verdict.sentence()
    assert "ordinary rules" in verdict.sentence()
    from backend.release import product_copy

    assert not product_copy.violations(verdict.sentence())


def test_the_verdict_explains_itself_in_a_sentence_a_person_can_act_on():
    verdict = ds.check({c: True for c in ds.CONDITIONS
                        if c != ds.GROUNDING}, active=True)

    assert "part that worked" in verdict.sentence()
    assert ds.GROUNDING in verdict.unmet


# ================================================== §131 the quality gates


def test_the_gates_run_in_section_131s_order():
    from scripts import quality_gates as qg

    names = [g.name for g in qg.GATES]
    assert names[0] == "ruff"
    assert names[1] == "pytest"
    assert "holdout-isolation" in names
    assert "release-manifest" in names
    for gate in qg.GATES:
        assert gate.checks.strip(), gate.name
        assert gate.command


def test_no_gate_spends_a_credit():
    """§131's last line. A gate that spends credits is one nobody runs before
    pushing."""
    from scripts import quality_gates as qg

    for gate in qg.GATES:
        blob = " ".join(gate.command).lower()
        for forbidden in ("certify", "verify-live", "--confirm", "live"):
            assert forbidden not in blob, (gate.name, forbidden)


def test_the_gates_that_are_not_run_here_are_named():
    """Their absence from a green run should be visible rather than
    assumed."""
    from scripts import quality_gates as qg

    named = {name for name, _ in qg.DEFERRED}
    assert "live smoke test" in named
    assert "sealed certification" in named
    for _, why in qg.DEFERRED:
        assert len(why) > 20


def test_a_gate_that_cannot_run_here_is_skipped_not_passed():
    """The whole point of the list is that a green run means something."""
    from scripts import quality_gates as qg

    docker = next(g for g in qg.GATES if g.needs == "docker")
    ok, why = docker.available()
    if not ok:
        assert why
