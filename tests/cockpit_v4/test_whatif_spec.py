"""A confirmation is bound to a hash, so an old approval cannot run.

UNIT. No database, no model, no provider call.

Section 6.2: *"Bind confirmation to a hash of the normalized scenario, book,
source versions, cohort hash, methods, mappings/models, custom assumptions and
material warnings. Any change invalidates confirmation and requires a new
preview. Do not execute an old approval after a source refresh, book switch,
cohort edit, model replacement or ambiguity repair."*

Five ways to invalidate an approval are named there, and each one has a test
below. They are worth testing separately because none of them involves anyone
acting in bad faith -- a source refresh does it on its own, and a mechanism
that only works when everybody remembers is not a mechanism.

Test C15 of section 16.3 is the same requirement from the conversation's side.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import ScenarioError


def source(**over) -> sp.SourceRef:
    body = {"domain_id": "corporate",
            "release_id": "v4-saudi-corporate-20q-v4",
            "release_fingerprint": "e37236d0f6d4e494",
            "reporting_period": "2026Q2"}
    body.update(over)
    return sp.SourceRef(**body)


def cohort(**over) -> sp.CohortRef:
    body = {"cohort_id": "coh-1", "membership_hash": "a" * 64,
            "grain": "facility", "entity_count": 412,
            "baseline_ead": "18000.5", "baseline_ecl": "640.25"}
    body.update(over)
    return sp.CohortRef(**body)


def pd_up(pct: str = "20", **over) -> sp.Shock:
    body = {"field_id": "pd_pit_12m",
            "amount": un.parse(pct, un.RELATIVE, raw=f"raise PD by {pct}%"),
            "origin": f"raise PD by {pct}%"}
    body.update(over)
    return sp.Shock(**body)


def draft(**over) -> sp.ScenarioSpec:
    body = {"scenario_id": "sc-1", "version": 1, "source": source(),
            "cohort": cohort(), "shocks": (pd_up(),)}
    body.update(over)
    return sp.ScenarioSpec(**body)


def confirmed(**over) -> sp.ScenarioSpec:
    return draft(state=sp.PREVIEW_READY, **over).confirm()


# ---- the hash ----------------------------------------------------------

def test_the_digest_is_stable_across_identical_specs() -> None:
    assert draft().digest() == draft().digest()


def test_the_digest_ignores_what_cannot_change_a_number() -> None:
    """Renaming a scenario must not expire its approval.

    An approval that died because somebody fixed a typo in a label would
    train people to click through the preview, which is the opposite of what
    the gate is for.
    """
    plain = draft()
    renamed = draft(name="Downside A", original_clauses=("raise PD 20%",))
    assert plain.digest() == renamed.digest()


def test_shock_order_does_not_change_the_hash_but_ordering_is_in_it() -> None:
    """Two readers who typed the same two rules the other way round get the
    same scenario -- but the APPLICATION order is a fact in its own right,
    because section 5.2 says an alternative ordering is a new revision."""
    lgd = sp.Shock(field_id="lgd_pct", amount=un.parse("10", un.RELATIVE))
    one = draft(shocks=(pd_up(), lgd))
    other = draft(shocks=(lgd, pd_up()))
    assert one.canonical()["shocks"] == other.canonical()["shocks"]
    assert one.ordering() != other.ordering()
    assert one.digest() != other.digest()


@pytest.mark.parametrize("field_name,changed", [
    ("source", source(release_id="v4-saudi-corporate-20q-v5")),
    ("source", source(release_fingerprint="0" * 16)),
    ("source", source(domain_id="retail")),
    ("cohort", cohort(membership_hash="b" * 64)),
    ("cohort", cohort(entity_count=411)),
    ("methods", (sp.DELTA, sp.USER_DEFINED)),
    ("delta_submode", sp.STRUCTURAL_EAD),
    ("stage_policy", "migrate"),
    ("overlay_policy", "scaled"),
    ("fx_policy", "stressed"),
    ("warnings", ("Stage 3 rows are ineligible for a PD shock",)),
    ("artifact_versions", {"rating_to_pd": "2.0.0"}),
    ("user_assumption", {"kind": "relative", "value": "15"}),
])
def test_anything_that_changes_the_answer_changes_the_hash(
        field_name, changed) -> None:
    assert draft().digest() != draft(**{field_name: changed}).digest()


def test_a_different_shock_value_changes_the_hash() -> None:
    assert draft().digest() != draft(shocks=(pd_up("25"),)).digest()


def test_the_same_number_under_a_different_unit_changes_the_hash() -> None:
    """+20% and +20pp are different scenarios that share their digits."""
    relative = draft(shocks=(pd_up("20"),))
    points = draft(shocks=(sp.Shock(
        field_id="pd_pit_12m", amount=un.parse("20", un.ABSOLUTE_PP)),))
    assert relative.digest() != points.digest()


# ---- confirmation ------------------------------------------------------

def test_an_unconfirmed_scenario_will_not_run() -> None:
    with pytest.raises(ScenarioError, match="has not been confirmed") as e:
        draft().require_confirmed()
    assert e.value.code == "CONFIRMATION_STALE"


def test_a_confirmed_scenario_runs() -> None:
    confirmed().require_confirmed()


def test_confirmation_only_comes_from_a_preview() -> None:
    """Section 6.2: reading the sensitivities or saying "use ML" before a
    complete preview is not confirmation of an unseen calculation."""
    with pytest.raises(ScenarioError, match="PREVIEW_READY"):
        draft(state=sp.SCENARIO_RESOLVED).confirm()


@pytest.mark.parametrize("what,change", [
    ("a source refresh", {"source": source(release_id="v4-saudi-corporate-20q-v5")}),
    ("a book switch", {"source": source(domain_id="retail")}),
    ("a cohort edit", {"cohort": cohort(membership_hash="c" * 64)}),
    ("a model replacement", {"artifact_versions": {"emulator": "2"}}),
    ("an ambiguity repair", {"shocks": (pd_up("25"),)}),
])
def test_the_five_named_invalidations(what, change) -> None:
    """Section 6.2 names exactly these five. None needs bad faith."""
    was = confirmed()
    assert was.is_confirmed()
    from dataclasses import replace
    now = replace(was, **change)
    assert not now.is_confirmed(), what
    with pytest.raises(ScenarioError, match="different version"):
        now.require_confirmed()


def test_the_stale_message_carries_both_hashes() -> None:
    """So a reader can see that something moved, not just be told it did."""
    from dataclasses import replace
    was = confirmed()
    now = replace(was, shocks=(pd_up("25"),))
    with pytest.raises(ScenarioError) as caught:
        now.require_confirmed()
    assert caught.value.detail["confirmed"] == was.confirmed_digest
    assert caught.value.detail["now"] == now.digest()
    assert caught.value.detail["confirmed"] != caught.value.detail["now"]


# ---- versioning --------------------------------------------------------

def test_revise_makes_a_new_version_with_the_old_one_as_parent() -> None:
    first = draft()
    second = first.revise(shocks=(pd_up("30"),))
    assert (second.version, second.parent_version) == (2, 1)
    assert first.version == 1, "the original is untouched"
    assert first.shocks[0].amount.value == Decimal("20")


def test_revising_drops_the_confirmation_without_being_asked() -> None:
    """A revised scenario is by definition not the one that was approved."""
    revised = confirmed().revise(shocks=(pd_up("30"),))
    assert revised.confirmed_digest == ""
    assert not revised.is_confirmed()


def test_a_spec_cannot_be_mutated() -> None:
    """Frozen, so section 5.2's "an overlay, never a compounding edit" is a
    fact about the type rather than a convention people remember."""
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        draft().version = 9  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        draft().shocks[0].amount = un.parse("99", un.RELATIVE)  # type: ignore[misc]


# ---- the lifecycle -----------------------------------------------------

def test_the_happy_path_walks_the_specified_states() -> None:
    at = draft()
    for step in (sp.SCENARIO_RESOLVED, sp.METHOD_SELECTION, sp.PREVIEW_READY):
        at = at.advance(step)
    at = at.confirm().advance(sp.RUNNING).advance(sp.COMPLETED)
    assert at.state == sp.COMPLETED


def test_a_preview_cannot_jump_straight_to_running() -> None:
    """There is no edge that skips CONFIRMED."""
    with pytest.raises(ScenarioError, match="can go to"):
        draft(state=sp.PREVIEW_READY).advance(sp.RUNNING)


def test_leaving_confirmed_for_anything_but_running_drops_the_approval() -> None:
    back = confirmed().advance(sp.DRAFT)
    assert back.confirmed_digest == ""


def test_a_finished_scenario_goes_nowhere() -> None:
    for terminal in sorted(sp.TERMINAL):
        assert sp.TRANSITIONS[terminal] == frozenset(), terminal


def test_cancellation_is_reachable_from_every_live_state() -> None:
    for state in sp.STATES:
        if state in sp.TERMINAL:
            continue
        assert sp.CANCELLED in sp.TRANSITIONS[state], state


def test_every_state_has_a_transition_entry() -> None:
    assert set(sp.TRANSITIONS) == set(sp.STATES)


# ---- conflicts ---------------------------------------------------------

def test_two_rules_on_one_field_over_the_whole_cohort_conflict() -> None:
    """Section 5.2's worked example: "all customers PD +10%, and construction
    PD +20%" must ask, not assume "more specific wins"."""
    everyone = pd_up("10", origin="all customers PD +10%")
    sector = pd_up("20", where={"sector": "Construction"},
                   origin="construction PD +20%")
    with pytest.raises(ScenarioError, match="Which applies") as caught:
        draft(shocks=(everyone, sector)).require_no_conflicts()
    assert caught.value.code == "RULE_CONFLICT"
    assert "pd_pit_12m" in str(caught.value)


def test_the_question_names_the_three_readings() -> None:
    everyone = pd_up("10")
    sector = pd_up("20", where={"sector": "Construction"})
    with pytest.raises(ScenarioError) as caught:
        draft(shocks=(everyone, sector)).require_no_conflicts()
    said = str(caught.value)
    assert "replace" in said and "compose" in said and "did not cover" in said


def test_disjoint_scopes_do_not_conflict() -> None:
    draft(shocks=(pd_up("10", where={"sector": "Construction"}),
                  pd_up("20", where={"sector": "Real Estate"}))
          ).require_no_conflicts()


def test_different_fields_do_not_conflict() -> None:
    draft(shocks=(pd_up(),
                  sp.Shock(field_id="lgd_pct",
                           amount=un.parse("10", un.RELATIVE)))
          ).require_no_conflicts()


def test_a_derived_shock_does_not_conflict_with_its_own_parent() -> None:
    """A macro move that induced a PD move is one intervention, not two
    competing rules. Section 13.2 depends on this: showing the parent and its
    induced child as separate additive bars is the error it forbids."""
    direct = sp.Shock(field_id="unemployment_rate",
                      amount=un.parse("1", un.ABSOLUTE_PP))
    induced = sp.Shock(field_id="pd_pit_12m",
                       amount=un.parse("0.2", un.ABSOLUTE_PP),
                       derived_from="unemployment_rate",
                       mapping_version="sens-1.0.0")
    draft(shocks=(direct, induced)).require_no_conflicts()


def test_a_derived_shock_still_conflicts_with_an_unrelated_direct_one() -> None:
    """Section 5.2: "A direct PD shock plus a macro-derived PD shock needs an
    explicit composition decision when both apply.\""""
    induced = sp.Shock(field_id="pd_pit_12m",
                       amount=un.parse("0.2", un.ABSOLUTE_PP),
                       derived_from="unemployment_rate")
    with pytest.raises(ScenarioError, match="RULE|Which applies"):
        draft(shocks=(induced, pd_up("20"))).require_no_conflicts()


def test_direct_and_derived_are_told_apart() -> None:
    induced = sp.Shock(field_id="lgd_pct",
                       amount=un.parse("5", un.RELATIVE),
                       derived_from="unemployment_rate")
    at = draft(shocks=(pd_up(), induced))
    assert [s.field_id for s in at.direct_shocks()] == ["pd_pit_12m"]
    assert [s.field_id for s in at.derived_shocks()] == ["lgd_pct"]


# ---- what the type refuses ---------------------------------------------

def test_an_unknown_method_is_refused() -> None:
    with pytest.raises(ScenarioError, match="not methods"):
        draft(methods=("delta", "vibes"))


def test_an_unknown_submode_is_refused() -> None:
    with pytest.raises(ScenarioError, match="not a Delta submode"):
        draft(delta_submode="approximate")


def test_a_submode_is_not_a_fourth_method() -> None:
    """Section 10.2 says so twice, and oracle O05 turns on the two giving
    different answers."""
    assert sp.STRUCTURAL_EAD not in sp.METHODS
    assert sp.PROPORTIONAL not in sp.METHODS
    assert set(sp.DELTA_SUBMODES) == {sp.PROPORTIONAL, sp.STRUCTURAL_EAD}


def test_the_defaults_are_the_conservative_ones() -> None:
    """Stages frozen, overlay fixed, FX constant, membership fixed,
    proportional Delta -- each is what the specification asks for when the
    reader has not said otherwise."""
    at = draft()
    assert at.stage_policy == "frozen"
    assert at.overlay_policy == "fixed"
    assert at.fx_policy == "constant"
    assert at.cohort.fixed is True
    assert at.delta_submode == sp.PROPORTIONAL
    assert at.methods == (sp.DELTA,)
