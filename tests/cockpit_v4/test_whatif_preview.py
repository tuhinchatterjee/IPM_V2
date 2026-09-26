"""A preview shows everything, calculates no ECL, and is what gets confirmed.

REAL DATABASE for the cohort · UNIT for the rest · NO MODEL. The frozen
cohort comes from the published parquet; everything else is arithmetic. No
provider in this module, not even a scripted one.

Section 6.2 lists fifteen things the preview must show and draws one line
twice: *"Preview calculations may resolve transformed parameters, mapping
readiness and workload checks; do not run and present final ECL results before
confirmation."*

Also covers the one protected-core change this pass makes —
`context.scenario_blocks()` — and the property that justifies it: with both
book flags off it returns nothing and the assembled payload is the baseline's.

Covers C12, C13, C14 and C15 of section 16.3, and A04.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import context as ctx
from backend.cockpit_v4 import domain_resolver as resolver
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario import preview as pv
from backend.cockpit_v4.scenario import rules as ru
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import ScenarioError


@pytest.fixture(scope="module", autouse=True)
def _lake_present():
    if not pathlib.Path("data/cockpit_v4_lake").exists():
        pytest.skip("the published lake is not present in this worktree")
    arun.reset()
    yield
    arun.reset()


@pytest.fixture(scope="module")
def frozen():
    book = arun.for_domain(dom.CORPORATE)
    scope = resolver.scope_for(dom.CORPORATE, tenant_id=lake.DEFAULT_TENANT)
    return ch.freeze(session=book.session, scope=scope,
                     predicate="sector = 'Construction' AND stage = 2",
                     described_as="Stage 2 construction facilities")


def pd_up(pct="20", **over):
    body = {"field_id": "pd_pit_12m",
            "amount": un.parse(pct, un.RELATIVE, raw=f"raise PD {pct}%"),
            "origin": f"raise PD by {pct}%"}
    body.update(over)
    return sp.Shock(**body)


def spec_for(frozen, **over) -> sp.ScenarioSpec:
    body = {
        "scenario_id": "sc-1", "version": 1, "name": "Construction stress",
        "source": sp.SourceRef(
            domain_id=frozen.domain_id, release_id=frozen.release_id,
            release_fingerprint=frozen.release_fingerprint,
            reporting_period=frozen.period),
        "cohort": frozen.ref, "shocks": (pd_up(),),
    }
    body.update(over)
    return sp.ScenarioSpec(**body)


def build(frozen, **over) -> pv.Preview:
    spec = spec_for(frozen, **over)
    return pv.build(spec=spec, frozen=frozen,
                    readiness=pv.readiness(spec))


# ---- what it shows -----------------------------------------------------

def test_every_required_section_is_present(frozen) -> None:
    body = build(frozen).body
    missing = [s for s in pv.REQUIRED_SECTIONS if s not in body]
    assert missing == [], missing


def test_it_names_the_book_the_release_and_the_period(frozen) -> None:
    body = build(frozen).body
    assert body["book"]["domain_id"] == dom.CORPORATE
    assert body["book"]["release_id"].startswith("v4-saudi-corporate")
    assert len(body["book"]["release_fingerprint"]) == 64
    assert body["period"] == frozen.period


def test_it_shows_the_cohort_with_its_counts_and_hash(frozen) -> None:
    cohort = build(frozen).body["cohort"]
    assert cohort["entity_count"] == frozen.ref.entity_count > 0
    assert cohort["owner_count"] == frozen.owner_count
    assert cohort["membership_hash"] == frozen.ref.membership_hash
    assert "facilities" in cohort["described"]


def test_it_names_the_denominator(frozen) -> None:
    """Section 0: never switch between EAD, outstanding balance and gross
    carrying amount without disclosure. Naming it is the disclosure."""
    baseline = build(frozen).body["baseline"]
    assert "EAD" in baseline["denominator"]
    assert "ead_sar_mn" in baseline["denominator"]
    assert Decimal(baseline["ead"]) > 0
    assert Decimal(baseline["coverage_pct"]) > 0


def test_it_shows_each_input_with_its_operation_and_unit(frozen) -> None:
    inputs = build(frozen).body["inputs"]
    assert len(inputs) == 1
    assert inputs[0]["field"] == "pd_pit_12m"
    assert inputs[0]["operation"] == "20% relative to baseline"
    assert inputs[0]["storage"] == un.FRACTION
    assert inputs[0]["origin"] == "raise PD by 20%"


def test_it_says_what_is_left_alone(frozen) -> None:
    """Section 13.1: unaffected rows must show exactly zero change."""
    said = build(frozen).body["unaffected"]
    assert "keeps its recorded ECL exactly" in said
    assert "plus the unchanged remainder" in said


def test_it_says_the_book_is_not_written(frozen) -> None:
    body = build(frozen).body
    assert body["source_is_not_changed"] == pv.SOURCE_UNTOUCHED
    assert "never written" in body["source_is_not_changed"]
    assert pv.SOURCE_UNTOUCHED in build(frozen).narrative()


def test_it_discloses_that_the_overlay_is_not_separated(frozen) -> None:
    """Section 9.1: when the source does not distinguish modelled ECL from
    overlay, disclose it rather than invent a decomposition."""
    note = build(frozen).body["stage_and_horizon"]["overlay_note"]
    assert "does not separate" in note
    assert "disclosed rather than decomposed" in note


def test_it_says_stages_are_frozen_and_why(frozen) -> None:
    said = build(frozen).body["stage_and_horizon"]
    assert said["stage_policy"] == "frozen"
    assert "held as recorded" in said["note"]
    assert "horizon conversion" in said["note"]


def test_an_ineligible_population_becomes_a_warning(frozen) -> None:
    """A PD shock cannot move Stage 3, and the reader is told before
    confirming rather than after."""
    warnings = build(frozen).body["warnings"]
    assert any("already one" in w for w in warnings), warnings


def test_a_derived_field_is_flagged_as_derived(frozen) -> None:
    """Section 3.3: a derivation may not be passed off as a source fact."""
    ccf = sp.Shock(field_id="ccf", amount=un.parse("20", un.RELATIVE))
    body = build(frozen, shocks=(ccf,)).body
    assert body["inputs"][0]["availability"] == "derived"
    assert "derivation" in body["inputs"][0]
    assert any("derived from published columns" in w
               for w in body["warnings"])


# ---- C12, C13: methods and their readiness ------------------------------

def test_c12_the_question_names_the_selected_methods(frozen) -> None:
    asked = build(frozen, methods=(sp.DELTA, sp.USER_DEFINED)).question()
    assert asked.startswith("Shall I execute this scenario using")
    assert "Delta" in asked and "your own impact assumption" in asked


def test_c13_any_subset_of_methods_is_accepted(frozen) -> None:
    for chosen in ((sp.DELTA,), (sp.USER_DEFINED,),
                   (sp.DELTA, sp.USER_DEFINED),
                   (sp.DELTA, sp.ML, sp.USER_DEFINED)):
        listed = build(frozen, methods=chosen).body["methods"]
        assert [m["method"] for m in listed] == list(chosen)


def test_the_ml_method_says_it_is_not_ready_rather_than_vanishing(
        frozen) -> None:
    """Section 11.5: a failed model gate cannot be declared a completed ML
    capability -- and neither can one that was never built.

    The status now carries the REASON, because section 12 asks for
    `ML NOT READY - <specific validation reason>` rather than a bare label. A
    reader told only "not ready" cannot tell a missing artifact from a failed
    gate from a model fitted on another release, and those three call for
    three different actions.
    """
    listed = build(frozen, methods=(sp.DELTA, sp.ML)).body["methods"]
    statuses = {m["method"]: m["status"] for m in listed}
    assert statuses[sp.ML].startswith("MODEL_NOT_READY")
    assert statuses[sp.ML] != "MODEL_NOT_READY", (
        "the status has to say WHY. A bare label is what this used to be, "
        "when the answer was a constant rather than the model's own gates.")
    assert statuses[sp.DELTA] == "READY"


def test_c13_all_three_without_a_custom_rule_asks_for_that_rule(
        frozen) -> None:
    """Section 6.2: *"If 'compare all' was requested without a custom
    assumption, ask only for that missing assumption."*"""
    listed = build(frozen, methods=(sp.DELTA, sp.ML, sp.USER_DEFINED)
                   ).body["methods"]
    statuses = {m["method"]: m["status"] for m in listed}
    assert statuses[sp.USER_DEFINED] == "NEEDS_ASSUMPTION"
    supplied = build(frozen, methods=(sp.USER_DEFINED,),
                     user_assumption={"kind": "relative", "value": "15"})
    assert supplied.body["methods"][0]["status"] == "READY"


def test_the_delta_submode_is_shown(frozen) -> None:
    """Oracle O05 turns on the two submodes giving different answers, so a
    reader confirming one is entitled to see which."""
    listed = build(frozen, delta_submode=sp.STRUCTURAL_EAD).body["methods"]
    assert listed[0]["submode"] == sp.STRUCTURAL_EAD


# ---- C14, C15: what confirmation is ------------------------------------

def test_c14_the_preview_calculates_no_ecl(frozen) -> None:
    """The line section 6.2 draws twice. A preview that had run the numbers
    would be presenting results nobody approved."""
    body = build(frozen).body
    blob = str(body)
    assert "scenario_ecl" not in blob
    assert "ecl_change" not in blob
    # The BASELINE is shown -- that is a fact about the book, not a result.
    assert Decimal(body["baseline"]["ecl"]) > 0


def test_c14_a_preview_is_not_itself_a_confirmation(frozen) -> None:
    preview = build(frozen)
    assert not preview.spec.is_confirmed()
    with pytest.raises(ScenarioError, match="has not been confirmed"):
        preview.spec.require_confirmed()


@pytest.mark.parametrize("reply", ["yes", "Yes", "yes, run it", "go ahead",
                                   "confirm", "Proceed", "do it"])
def test_an_affirmative_reply_binds_the_approval(frozen, reply) -> None:
    confirmed = pv.confirm(build(frozen), reply)
    assert confirmed.is_confirmed()
    assert confirmed.state == sp.CONFIRMED
    confirmed.require_confirmed()


@pytest.mark.parametrize("reply", ["use ML", "what are the sensitivities?",
                                   "change a method", "no", "not yet",
                                   "", "maybe"])
def test_anything_that_is_not_a_yes_leaves_it_unconfirmed(frozen,
                                                          reply) -> None:
    """Section 6.2: *"Reading sensitivities or saying 'use ML' before a
    complete preview is not confirmation of an unseen calculation."*"""
    assert not pv.confirm(build(frozen), reply).is_confirmed()


def test_c15_the_approval_is_bound_to_this_preview_and_no_other(
        frozen) -> None:
    """C15: a yes approves the preview the reader read, not the next one.

    `revise()` drops the approval outright rather than carrying it forward
    to be tested against a moved hash, so a revision is simply unconfirmed
    and goes back through preview and confirm like any other scenario. The
    hash-moved branch is reachable another way -- a spec changed without
    going through `revise()` -- and
    `test_whatif_spec.py::test_the_five_named_invalidations` pins that one.
    """
    confirmed = pv.confirm(build(frozen), "yes")
    moved = confirmed.revise(shocks=(pd_up("30"),))
    assert not moved.is_confirmed()
    assert moved.confirmed_digest == ""
    assert moved.digest() != confirmed.digest()
    with pytest.raises(ScenarioError, match="has not been confirmed"):
        moved.require_confirmed()


def test_the_options_let_a_reader_change_their_mind(frozen) -> None:
    """A preview whose only options are yes and no invites a reader who
    wanted one number different to click yes and fix it afterwards."""
    options = build(frozen).options()
    assert any(o.startswith("Yes,") for o in options)
    assert any("Change an assumption" in o for o in options)
    assert any("Cancel" in o for o in options)


def test_the_preview_travels_as_an_ordinary_clarification(frozen) -> None:
    """No new disposition, no new route: the existing round trip carries it,
    and `context.build` already projects the reply back."""
    payload = build(frozen).as_clarification()
    assert payload["disposition"] == "clarification"
    assert payload["clarification_question"].startswith("Shall I execute")
    assert len(payload["clarification_options"]) == 4
    assert payload["whatif_digest"] == build(frozen).digest()
    assert payload["narrative"]


def test_the_narrative_reads_in_the_order_a_reader_needs(frozen) -> None:
    said = build(frozen).narrative()
    assert said.index("Cohort.") < said.index("What changes.")
    assert said.index("What changes.") < said.index("Unaffected.")
    assert said.index("Unaffected.") < said.index("simulation")


# ---- overlaps in the preview -------------------------------------------

def test_an_overlap_is_shown_with_its_size_and_its_options(frozen) -> None:
    """Section 5.2: *"Show overlap counts and amounts."*"""
    everyone = pd_up("10", origin="all facilities PD +10%")
    sector = pd_up("20", where={"sector": "Construction"},
                   origin="construction PD +20%")
    spec = spec_for(frozen, shocks=(everyone, sector))
    found = ru.overlaps(spec, counts={"pd_pit_12m": (412, "18500.25")})
    body = pv.build(spec=spec, frozen=frozen,
                    overlaps=found).body
    assert len(body["overlaps"]) == 1
    shown = body["overlaps"][0]
    assert "412" in shown["question"] and "18500.25" in shown["question"]
    assert len(shown["options"]) == 3
    assert shown["composition"] == "", "undeclared until the reader chooses"
    assert any("412" in line for line in build(frozen).narrative().split("\n")
               ) is False  # the plain preview has no overlap section


# ---- the one protected-core change -------------------------------------

def test_a04_scenario_blocks_are_empty_when_the_flags_are_off(
        monkeypatch) -> None:
    from backend.cockpit_v4.scenario import flags as fl

    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    assert ctx.scenario_blocks(domain_id=dom.CORPORATE) == []
    assert ctx.scenario_blocks(domain_id=dom.RETAIL) == []
    assert ctx.scenario_blocks(domain_id="") == []


def test_the_block_is_per_book(monkeypatch) -> None:
    from backend.cockpit_v4.scenario import flags as fl

    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(fl.VARIABLES[dom.CORPORATE], "1")
    assert len(ctx.scenario_blocks(domain_id=dom.CORPORATE)) == 1
    assert ctx.scenario_blocks(domain_id=dom.RETAIL) == []


def test_the_block_teaches_the_four_readings_of_twenty(monkeypatch) -> None:
    """The one thing the catalogue cannot say."""
    from backend.cockpit_v4.scenario import flags as fl

    monkeypatch.setenv(fl.VARIABLES[dom.CORPORATE], "1")
    said = ctx.scenario_blocks(domain_id=dom.CORPORATE)[0]["text"]
    for reading in ("1.20", "0.20", "0.0020", "replaces it"):
        assert reading in said, reading
    assert "factor of ten" in said


def test_the_block_does_not_teach_arithmetic(monkeypatch) -> None:
    """It says what a sentence MEANS, not how to compute a stressed ECL.
    A block that taught the sums would invite the analyst to do them."""
    from backend.cockpit_v4.scenario import flags as fl

    monkeypatch.setenv(fl.VARIABLES[dom.CORPORATE], "1")
    said = ctx.scenario_blocks(domain_id=dom.CORPORATE)[0]["text"].lower()
    for forbidden in ("ead * pd", "ead x pd", "select ", "sum(",
                      "elasticity"):
        assert forbidden not in said, forbidden


def test_the_import_of_the_candidate_package_is_guarded() -> None:
    """A module-level import would make the accepted runtime depend on the
    candidate package existing, which is the thing this block avoids."""
    import inspect

    source = inspect.getsource(ctx.scenario_blocks)
    assert "from backend.cockpit_v4.scenario import" in source
    assert "try:" in source and "ImportError" in source
