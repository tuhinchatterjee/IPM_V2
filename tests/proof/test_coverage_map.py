"""
The Coverage Map, and the rules that stop it flattering the product. §19-§21.

Why the map needs tests at all
--------------------------------
A coverage map is a document, and documents drift. Two things here are
checked rather than asserted in prose:

    the map and the dimension catalogue describe the same ninety-five
    subcomponents;

    every entry claiming WIRED is one the collector can actually emit.

Without the second, the map becomes a wish list that reports 100% coverage
while the collector emits a quarter of it — which is the exact failure this
phase exists to prevent, dressed as its solution.
"""

from __future__ import annotations

import pytest

from backend.assurance import dimensions as dm
from backend.assurance import record as rc
from backend.proof import coverage as cv
from backend.proof import flows as fl

# ============================================================ the map itself


def test_every_subcomponent_has_an_entry():
    """A subcomponent nobody described is one nobody owns."""
    assert cv.unmapped() == []


def test_no_entry_names_a_subcomponent_that_does_not_exist():
    assert cv.orphans() == []


def test_every_entry_names_a_source_and_a_rule():
    """§19's fields. An entry with no source cannot be wired by anybody, and
    an entry with no PASS rule cannot be judged."""
    for name, entry in cv.MAP.items():
        assert entry.source_system, name
        assert entry.source_field, name
        assert entry.passes_when, name
        assert entry.fails_when, name
        assert entry.applicability, name
        assert entry.state in cv.STATES, name


def test_an_unwired_entry_reports_not_available_rather_than_pass_or_skipped():
    """The rule the whole map rests on.

    SKIPPED would be a lie about a decision nobody made: it says execution
    chose not to run this check, when in fact no execution could.
    """
    for name in cv.planned() | cv.out_of_band():
        assert cv.MAP[name].outcome_when_unwired == rc.NOT_AVAILABLE, name
        assert cv.MAP[name].outcome_when_unwired != rc.PASS
        assert cv.MAP[name].outcome_when_unwired != rc.SKIPPED


def test_the_summary_counts_agree_with_the_map():
    summary = cv.summary()

    assert summary["mapped"] == len(cv.MAP)
    assert summary["wired"] == len(cv.wired())
    assert (summary["wired"] + summary["planned"] + summary["out_of_band"]
            == summary["mapped"])


def test_the_work_list_puts_critical_gaps_first():
    """A work list ordered alphabetically is a work list nobody works
    through in a useful order."""
    work = cv.work_list()
    if not work:
        pytest.skip("nothing left to instrument")

    criticals = [i for i, item in enumerate(work) if item["critical"]]
    non_critical = [i for i, item in enumerate(work) if not item["critical"]]
    if criticals and non_critical:
        assert max(criticals) < min(non_critical)


def test_the_work_list_excludes_out_of_band_entries():
    """"Wire the drivers engine" and "check contrast in a browser" have
    different owners; a list mixing them is ignored by both."""
    names = {item["subcomponent"] for item in cv.work_list()}

    assert not (names & cv.out_of_band())


# ================================================== §21 the flow classes


def test_there_are_flow_classes_for_every_shape_section_21_names():
    for flow in (fl.METADATA, fl.SIMPLE, fl.MULTI_DOMAIN, fl.COORDINATED,
                 fl.PROACTIVE, fl.PROJECT):
        assert flow in fl.FLOWS
        assert fl.LABELS[flow]
        assert len(fl.MEANS[flow]) > 40, flow


def test_every_flow_declares_what_applies_to_it():
    for flow in fl.FLOWS:
        applies = fl.applicable(flow)
        assert applies, flow
        # And every name in it is a real subcomponent.
        assert not (applies - set(dm.all_subcomponents())), flow


def test_a_richer_flow_carries_at_least_what_a_simpler_one_does():
    """Coordinated work does everything a simple analysis does, and more.

    Stated as a property because the alternative — six hand-maintained sets
    — drifts the first time a subcomponent is added to one and not the
    others, and the symptom is a coordinated review reporting better
    coverage than the simple analysis inside it.
    """
    assert fl.applicable(fl.SIMPLE) <= fl.applicable(fl.MULTI_DOMAIN)
    assert fl.applicable(fl.MULTI_DOMAIN) <= fl.applicable(fl.COORDINATED)


def test_a_conversational_turn_does_not_carry_the_result_checks():
    """A clarification has no result to reconcile. Counting result checks
    against it would report every clarification as a broken analysis."""
    applies = fl.applicable(fl.CONVERSATIONAL)

    assert "result_correctness" not in applies
    assert "business_invariants" not in applies
    # But it still carries the ones about the turn itself.
    assert "capability_intent" in applies
    assert "permission_enforcement" in applies
    assert "privacy_tenant_safety" in applies


def test_an_unknown_flow_gets_the_widest_applicable_set():
    """Coverage should be harder to claim for something nobody classified,
    not easier."""
    unknown = fl.applicable("SOMETHING_NEW")

    for flow in fl.FLOWS:
        assert fl.applicable(flow) <= unknown


@pytest.mark.parametrize("kwargs,expected", [
    ({"executed": False, "answer_type": "needs_clarification"},
     fl.CONVERSATIONAL),
    ({"executed": False, "answer_type": "succeeded", "datasets": 1},
     fl.METADATA),
    ({"executed": True, "datasets": 1}, fl.SIMPLE),
    ({"executed": True, "datasets": 3}, fl.MULTI_DOMAIN),
    ({"executed": True, "datasets": 3, "agentic_run": True,
      "specialists": 3}, fl.COORDINATED),
    ({"executed": True, "datasets": 3, "project_id": "p-1"}, fl.PROJECT),
    ({"executed": True, "proactive": True}, fl.PROACTIVE),
])
def test_classification_is_deterministic_and_from_the_record(kwargs, expected):
    """Never from the question's wording: a classifier that read the prose
    would put "review the portfolio" and "review the portfolio's spelling"
    in the same class."""
    assert fl.classify(**kwargs) == expected


def test_a_proactive_review_inside_a_project_is_judged_as_proactive():
    """Its idempotency and deduplication checks are the ones most likely to
    be the reason it went wrong."""
    assert fl.classify(executed=True, proactive=True,
                       project_id="p-1") == fl.PROACTIVE


# ================================================== §21 the coverage targets


def test_the_critical_gate_cannot_be_lowered():
    """"Do not lower thresholds merely to pass" has to be enforced
    somewhere."""
    with pytest.raises(ValueError):
        fl.Target(flow=fl.SIMPLE, critical_pct=95.0)
    with pytest.raises(ValueError):
        fl.Target(flow=fl.SIMPLE, overall_pct=80.0)


def test_a_flow_may_not_permit_a_critical_not_available():
    with pytest.raises(ValueError):
        fl.Target(flow=fl.SIMPLE, allow_critical_not_available=True)
    with pytest.raises(ValueError):
        fl.Target(flow=fl.SIMPLE, allow_mandatory_skipped=True)


def test_every_flow_has_a_target():
    for flow in fl.FLOWS:
        assert fl.TARGETS[flow].critical_pct == 100.0
        assert fl.TARGETS[flow].overall_pct >= 90.0


def test_a_flow_missing_a_critical_subcomponent_does_not_meet_its_gate():
    found = fl.FlowCoverage(flow=fl.SIMPLE)
    found.instrumented = set(fl.applicable(fl.SIMPLE))
    assert found.meets_gate

    missing = next(iter(fl.critical_for(fl.SIMPLE)))
    found.instrumented.discard(missing)

    assert not found.meets_gate
    assert any("critical" in reason for reason in found.blocking)


def test_a_critical_not_available_blocks_the_flow():
    found = fl.FlowCoverage(flow=fl.SIMPLE)
    found.instrumented = set(fl.applicable(fl.SIMPLE))
    blocked = next(iter(fl.critical_for(fl.SIMPLE)))
    found.not_available = {blocked}

    assert not found.meets_gate
    assert any("NOT_AVAILABLE" in reason for reason in found.blocking)


def test_a_mandatory_skip_blocks_the_flow():
    found = fl.FlowCoverage(flow=fl.SIMPLE)
    found.instrumented = set(fl.applicable(fl.SIMPLE))
    skipped = next(iter(fl.mandatory_for(fl.SIMPLE)))
    found.skipped = {skipped}

    assert not found.meets_gate
    assert any("did not run" in reason for reason in found.blocking)


def test_a_deterministically_inapplicable_check_leaves_both_denominators():
    found = fl.FlowCoverage(flow=fl.MULTI_DOMAIN)
    without = len(found.applicable_set)
    found.not_applicable = {"join_reconciliation"}

    assert len(found.applicable_set) == without - 1
    assert "join_reconciliation" not in found.critical_set


# ============================== the map and the collector must agree


def test_the_map_and_the_readers_describe_the_same_set():
    """The property that stops the Coverage Map becoming a wish list.

    Before this phase the map claimed 71.6% wired while the probes observed
    9.5% actual coverage — it was describing an intention. A map that
    overstates instrumentation is worse than no map, because it reports the
    problem as solved.

    Asserted both ways on purpose: the map may not claim a signal no reader
    reads, and a reader may not exist that nobody mapped (an unmapped reader
    has no owner, no source and no stated rules).
    """
    from backend.assurance import signals as sg

    assert cv.wired() - set(sg.READERS) == set(), (
        "the Coverage Map claims these are wired and no reader reads them")
    assert set(sg.READERS) - cv.wired() == set(), (
        "these readers exist and the Coverage Map does not list them as "
        "wired")


def test_every_reader_returns_a_signal_or_nothing():
    """A reader that returned a bare string or a bool would be silently
    mis-scored by the collector."""
    from backend.assurance import record as arc
    from backend.assurance import signals as sg

    ctx = sg.Ctx.of(None, None)
    for name in sg.READERS:
        signal = sg.read(name, ctx)
        if signal is None:
            continue
        assert isinstance(signal, sg.Signal), name
        assert signal.outcome in arc.OUTCOMES, (name, signal.outcome)


def test_a_reader_that_raises_is_recorded_rather_than_losing_the_record():
    """Losing ninety-four good checks because one reader misbehaved would be
    a far worse trade than recording that it misbehaved."""
    from backend.assurance import record as arc
    from backend.assurance import signals as sg

    def explode(ctx):
        raise RuntimeError("deliberate")

    original = sg.READERS.get("latency")
    sg.READERS["latency"] = explode
    try:
        signal = sg.read("latency", sg.Ctx.of(None, None))
    finally:
        if original is not None:
            sg.READERS["latency"] = original

    assert signal is not None
    assert signal.outcome == arc.SKIPPED
    assert "RuntimeError" in signal.detail


def test_an_unreasoned_not_applicable_from_a_reader_becomes_skipped():
    """§183 refuses an unreasoned NOT_APPLICABLE. A reader that returned one
    is a bug in the reader, and letting it through would remove a check from
    the denominator on no evidence."""
    from backend.assurance import collect as ac
    from backend.assurance import record as arc
    from backend.assurance import signals as sg

    def sloppy(ctx):
        return sg.Signal(arc.NOT_APPLICABLE)

    original = sg.READERS.get("latency")
    sg.READERS["latency"] = sloppy
    try:
        check = ac._check_for("latency", sg.Ctx.of(None, None))
    finally:
        if original is not None:
            sg.READERS["latency"] = original

    assert check.outcome == arc.SKIPPED
    assert "no reason" in check.detail


def test_an_unwired_subcomponent_names_the_system_that_owes_the_signal():
    """"No signal exists" is unactionable. "The judgment drivers engine does
    not emit drivers.decomposition" is a ticket."""
    from backend.assurance import collect as ac

    detail = ac._no_signal_detail("drivers_contributions")

    assert "judgment drivers engine" in detail
    assert "drivers.decomposition" in detail
    assert "Owner" in detail
