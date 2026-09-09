"""The functionality registry and the context packet.
Specification sections 6.1, 7.4 and 9.1."""

from __future__ import annotations

import dataclasses

import pytest

from backend.cockpit_agentic import catalog as C
from backend.cockpit_agentic import context as X
from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic import generate as G
from backend.cockpit_agentic import ledger as L
from backend.cockpit_agentic import profile as P
from backend.cockpit_agentic import registry as R
from backend.cockpit_agentic import scope as S
from backend.cockpit_agentic import sql, store
from backend.cockpit_agentic.contracts import CleanedQuestion, NormalizedQuestion

RELEASE = "test-ctx-20q"


class Principal:
    tenant_id = G.TENANT


# ============================================================ the registry

def test_all_six_functionalities_are_registered():
    assert R.FUNCTIONALITY_IDS == ("cockpit", "ews", "credit_scoring",
                                   "scorecard_validation", "what_if", "lenses")
    assert len(R.ENTRIES) == 6


def test_every_enabled_route_exists_in_the_application():
    """A referral with a dead link is worse than a referral with none."""
    verification = R.verify_routes()
    assert verification["verified"] is True, verification
    for functionality_id, result in verification["results"].items():
        if result["enabled"]:
            assert result["route_exists"] is True, functionality_id
            assert result["label_matches"] is True, (
                f"{functionality_id}: the registry calls it "
                f"{result['registry_label']!r} but the application calls it "
                f"{result['declared_label']!r}")


def test_what_if_is_registered_under_the_label_users_actually_see():
    """Referring someone to 'What-if Analysis' would send them looking for a
    menu item that is not there."""
    entry = R.entry(R.WHAT_IF)
    assert entry.ui_label == "Stress Testing"
    assert entry.route == "/stress"


def test_credit_scoring_is_excluded_and_honestly_unavailable():
    """Section 6.1: keep the ownership exclusion and state that the correct
    workflow is unavailable, rather than silently routing score generation to a
    validation-only screen."""
    entry = R.entry(R.CREDIT_SCORING)
    assert entry.enabled is False
    assert entry.route == ""
    assert "no credit-scoring workflow" in entry.unavailable_reason
    assert "reads stored ratings only" in entry.unavailable_reason
    validation = R.entry(R.SCORECARD_VALIDATION)
    assert any("does not run them for a borrower" in x
               for x in validation.excludes)


def test_the_registry_separates_the_action_from_the_noun():
    """'Show the stored rating' and 'calculate a new rating' name the same noun
    and belong to different functionalities."""
    cockpit = R.entry(R.COCKPIT)
    assert any("stored rating history" in e for e in cockpit.examples)
    assert any("new credit score" in e for e in cockpit.counterexamples)
    scoring = R.entry(R.CREDIT_SCORING)
    assert any("stored rating" in c for c in scoring.counterexamples)


def test_the_registry_payload_carries_descriptions_and_no_data():
    payload = R.compact()
    blob = str(payload).lower()
    # Section 6.1: other modules contribute DESCRIPTIONS ONLY -- no rows, no
    # fields, no search results, no tools from their domains.
    for leak in ("select ", "parquet", "borrower_id", "facility_id",
                 "ews_alert", "scorecard_run", "watchlist_register",
                 "reporting_quarter", "tenant_id"):
        assert leak not in blob, f"the registry payload leaked {leak!r}"
    assert "unique highest scorer" in payload["rule"]
    assert "executes no SQL" in payload["referral_rule"]
    assert "data-coverage limitation" in payload["coverage_rule"]


def test_the_registry_forbids_renaming_an_excluded_task():
    assert "risk index" in R.compact()["referral_rule"]


def test_a_coverage_gap_is_not_a_reason_to_refer_elsewhere():
    assert "Do NOT refer" in R.compact()["coverage_rule"]


# ============================================================ the packet

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from backend import config

    base = tmp_path_factory.mktemp("ctxlake")
    original = config.settings
    config.settings = dataclasses.replace(
        original, cockpit_agentic_v3=True, analytics_dir=base / "analytics")
    release = G.build_release(dataset_release_id=RELEASE, borrowers=25,
                              facilities=50)
    G.conform(release)
    store.write(release, overwrite=True)
    coverage = P.profile_release(release)
    scope = S.for_principal(Principal(), dataset_release_id=RELEASE)
    catalog = C.build(dataset_release_id=RELEASE, calendar=release.calendar)
    session = sql.open_session(scope=scope, catalog=catalog, reuse=False)
    yield {"release": release, "coverage": coverage, "scope": scope,
           "catalog": catalog, "session": session, "settings": config.settings}
    config.settings = original


def packet(built, *, mode="standard", exchanges=None, **kw):
    """Build the packet for the fixture's release."""
    return X.build(
        request_id="req-test",
        cleaned=CleanedQuestion(original_text="ECL kitna badha hai?",
                                detected_language="hi",
                                english_text="How much has ECL increased?"),
        normalized=NormalizedQuestion(
            business_question="How much has reported ECL increased?",
            subquestions=["the change in reported ECL"],
            explicit_scope={"sector_name": "Construction"},
            inherited_scope={"sector_name": "Real Estate",
                             "reporting_quarter": "2026Q2"}),
        scope=built["scope"], catalog=built["catalog"],
        coverage=built["coverage"],
        ledger=L.Ledger(mode=mode, prices=L.Prices()),
        session=built["session"], recent_exchanges=exchanges or [], **kw)


def with_cap(built, tokens: int):
    """Set the input cap and clear every other override.

    Explicit rather than incremental, because the runtime tests configure a
    raised deployment in a session-scoped fixture and a leaked override would
    make these assertions accidentally true.
    """
    from backend import config

    config.settings = dataclasses.replace(
        built["settings"],
        cockpit_agentic_v3_standard_input_tokens=tokens,
        cockpit_agentic_v3_deep_input_tokens=tokens,
        cockpit_agentic_v3_standard_total_tokens=0,
        cockpit_agentic_v3_deep_total_tokens=0,
        cockpit_agentic_v3_standard_deadline_seconds=0.0,
        cockpit_agentic_v3_deep_deadline_seconds=0.0,
        cockpit_agentic_v3_standard_model_requests=0,
        cockpit_agentic_v3_deep_model_requests=0)


def test_the_uat_configuration_holds_the_whole_packet(built):
    """The owner's decision: 64,000 Standard, 96,000 Deep. The measured floor
    is about 28,000, so the packet now fits with room for the conversation."""
    with_cap(built, 0)
    result = packet(built, mode="standard")
    assert L.limits_for("standard").max_input_tokens_per_call == 64_000
    assert result.estimated_tokens < 64_000
    assert result.reductions_applied == [], (
        "nothing had to be reduced at the configured cap")


def test_an_oversized_packet_is_still_refused_rather_than_abridged(built):
    """The rule did not change with the number. If the core does not fit, the
    schema is not halved to make it."""
    with_cap(built, 0)
    floor = measured_floor(built)
    import dataclasses as dc

    from backend import config

    config.settings = dc.replace(built["settings"],
                                 cockpit_agentic_v3_standard_input_tokens=0)
    # Simulate a deployment whose cap is below this domain's floor by asking
    # the builder to honour a cap it cannot meet.
    with pytest.raises(X.ContextTooLarge) as e:
        X.build(request_id="r", cleaned=CleanedQuestion(
                    original_text="q", detected_language="en",
                    english_text="q"),
                normalized=NormalizedQuestion(business_question="q"),
                scope=built["scope"], catalog=built["catalog"],
                coverage=built["coverage"],
                ledger=L.Ledger(mode="standard", prices=L.Prices(),
                                store=None),
                session=built["session"],
                _cap_override=floor - 1_000)
    message = str(e.value)
    assert "not abridged" in message
    assert "silently hidden" in message
    assert "CONTEXT_SIZING.md" in message


def test_the_invariants_have_no_override_at_all(built):
    """Sections 1.7 and 9.2 state these as invariants, not starting values.

    Every other numeric limit is a configurable starting value an administrator
    may raise with measured evidence (section 9.6). These two are not: there is
    no setting for them, and applying every override that does exist leaves
    them untouched.
    """
    import dataclasses as dc

    from backend import config

    assert set(L.INVARIANT) == {"execution_submissions", "analysis_rounds",
                                "deadline_seconds", "total_provider_requests",
                                "spend_ceiling_usd"}
    assert not (set(L.INVARIANT) & set(L.OVERRIDABLE))

    # Set every override that exists, generously, and check what moved.
    config.settings = dc.replace(
        built["settings"],
        cockpit_agentic_v3_standard_input_tokens=199_000,
        cockpit_agentic_v3_standard_total_tokens=999_000,
        cockpit_agentic_v3_standard_deadline_seconds=9_999.0,
        cockpit_agentic_v3_standard_model_requests=999)
    limits = L.limits_for("standard")
    assert limits.execution_submissions == 5
    assert limits.analysis_rounds == 3
    assert limits.deadline_seconds == 60.0, "the deadline is not configurable"
    assert limits.total_provider_requests == 12
    assert limits.spend_ceiling_usd == 1.00, (
        "the spending ceiling stays put so live usage can be measured "
        "against it")
    assert limits.max_input_tokens_per_call == 199_000
    assert limits.total_tokens == 999_000
    with_cap(built, 0)


def test_an_override_is_reported_never_silent(built):
    """Section 9.6: report the measured coverage and the configuration change.
    A result obtained under a raised limit must not read as if it were obtained
    under the specification's own."""
    with_cap(built, 0)
    assert L.overrides_in_force("standard") == {}
    assert L.input_cap_is_overridden("standard") is False

    with_cap(built, 120_000)
    reported = L.overrides_in_force("standard")
    assert reported["max_input_tokens_per_call"] == {
        "specification": 64_000, "configured": 120_000}
    assert L.input_cap_is_overridden("standard") is True
    with_cap(built, 0)


def test_an_override_can_only_raise_a_limit_never_lower_it(built):
    with_cap(built, 500)
    assert L.limits_for("standard").max_input_tokens_per_call == 64_000
    with_cap(built, 0)


def test_with_an_explicitly_configured_cap_the_packet_assembles(built):
    with_cap(built, 0)
    result = packet(built, mode="standard")
    assert result.estimated_tokens <= 36_000
    assert result.payload["D_E_catalogue"]["relations"]
    assert result.required_core_tokens > 0


def test_the_complete_dictionary_is_in_the_packet_never_the_top_ten(built):
    """Section 7.4-D: never replace the entire dictionary with only ten
    important fields."""
    with_cap(built, 0)
    result = packet(built, mode="standard")
    catalogue = result.payload["D_E_catalogue"]
    named: set[tuple[str, str]] = set()
    for relation, block in catalogue["relations"].items():
        for entry in block.get("fields", []):
            named.add((relation, entry["n"]))
        for family in block.get("column_families", []):
            for name in family["names"]:
                named.add((relation, name))
    for key in catalogue["common_keys"]["fields"]:
        for relation in F.RELATIONS:
            named.add((relation, key["n"]))
    missing = [(s.relation, s.name) for s in F.ALL_FIELDS
               if s.relation in F.RELATIONS and (s.relation, s.name) not in named]
    assert missing == []
    # ...and the eight-column preview is labelled as a preview, not as the
    # available fields.
    samples = result.payload["G_samples"]
    if samples["samples"]:
        assert "do not treat these eight columns as the available fields" in \
            samples["preview_note"]


def measured_floor(built) -> int:
    """The smallest packet this domain can produce, measured not guessed.

    Every rung of the ladder is spent to reach it. Measured through
    `context.floor`, which runs the ladder to exhaustion, rather than by
    passing an impossibly small cap -- an override that only raises would
    ignore one, and a measurement that depends on a configuration quirk is not
    a measurement.
    """
    return X.floor(
        request_id="floor",
        cleaned=CleanedQuestion(original_text="q", detected_language="en",
                                english_text="q"),
        normalized=NormalizedQuestion(business_question="q"),
        scope=built["scope"], catalog=built["catalog"],
        coverage=built["coverage"],
        ledger=L.Ledger(mode="standard", prices=L.Prices()),
        session=built["session"])["tokens"]


def test_optional_detail_is_reduced_before_anything_else(built):
    """Section 7.4: reduce preview rows and non-essential history FIRST."""
    floor = measured_floor(built)
    with_cap(built, 0)
    built["cap_override"] = floor + 200
    exchanges = [{"question": f"q{i}", "answer": "a" * 400} for i in range(8)]
    result = packet(built, mode="standard", exchanges=exchanges,
                    _cap_override=floor + 200)
    assert result.reductions_applied, "nothing was reduced despite a tight cap"
    # The rungs are used in the mandated order: samples and history before
    # anything else, and never the schema.
    expected = [name for name, _why in X.LADDER]
    assert result.reductions_applied == expected[:len(result.reductions_applied)]
    assert result.reductions_applied[0] == "samples_10_to_5"
    assert len(result.reductions_applied) >= 6
    # The dictionary survived every one of them.
    assert result.payload["D_E_catalogue"]["relations"][
        F.FACILITY_QUARTER]["fields"]
    assert result.payload["B_scope"]["effective_scope"]


def test_the_ladder_never_touches_the_schema_or_the_scope(built):
    floor = measured_floor(built)
    with_cap(built, 0)
    tight = packet(built, mode="standard", _cap_override=floor + 200)
    loose = packet(built, mode="standard")
    assert tight.reductions_applied and not loose.reductions_applied
    assert (tight.payload["D_E_catalogue"]
            == loose.payload["D_E_catalogue"]), "the dictionary was trimmed"
    assert tight.payload["B_scope"] == loose.payload["B_scope"]
    assert tight.payload["A_request"] == loose.payload["A_request"]


def test_the_measured_floor_is_recorded_in_the_sizing_document(built):
    """The number in docs/cockpit_agentic_v3/CONTEXT_SIZING.md is a
    measurement, and a measurement that drifts from the code is a claim."""
    from pathlib import Path

    floor = measured_floor(built)
    document = (Path(__file__).resolve().parents[2]
                / "docs/cockpit_agentic_v3/CONTEXT_SIZING.md").read_text()
    # The document records the measurement and the decision that followed.
    assert "28,105" in document or str(floor) in document, (
        "the sizing document does not record the measured floor")
    assert "no override at any level" in document
    assert "spend is now the binding constraint" in document.lower(), (
        "the document must record which guardrail binds first under the new "
        "configuration")
    # The configured cap must actually clear the measured floor.
    configured = L.limits_for("standard").max_input_tokens_per_call
    assert configured == 64_000
    assert configured > floor, (
        f"the configured cap is {configured} and the measured floor is "
        f"{floor}")
    assert "64,000" in document or "64000" in document


# ---- the packet's contents ------------------------------------------------

def test_all_ten_sections_are_present(built):
    with_cap(built, 0)
    payload = packet(built).payload
    for key in ("A_request", "B_scope", "C_thread", "D_E_catalogue",
                "F_coverage", "G_samples", "H_functionalities", "I_execution",
                "J_budget"):
        assert key in payload and payload[key]


def test_the_packet_carries_all_three_forms_of_the_question(built):
    with_cap(built, 0)
    request = packet(built).payload["A_request"]
    assert request["original_question"] == "ECL kitna badha hai?"
    assert request["detected_language"] == "hi"
    assert request["english_translation"] == "How much has ECL increased?"
    assert request["business_request"].startswith("How much has reported ECL")
    assert "do not resolve it by guessing" in request["note"]


def test_explicit_scope_overrides_inherited_scope_in_the_packet(built):
    with_cap(built, 0)
    scope_block = packet(built).payload["B_scope"]
    assert scope_block["effective_scope"]["sector_name"] == "Construction"
    assert scope_block["effective_scope"]["reporting_quarter"] == "2026Q2"
    assert "does not merge with it" in scope_block["precedence_note"]


def test_coverage_comes_from_the_profiler_not_the_samples(built):
    with_cap(built, 0)
    coverage = packet(built).payload["F_coverage"]
    assert coverage["computed_from"] == (
        "the full authorized release, not the sample rows")
    assert coverage["row_counts"][F.FACILITY_QUARTER] > 100


def test_samples_are_labelled_as_shape_not_as_evidence(built):
    with_cap(built, 0)
    samples = packet(built).payload["G_samples"]
    assert "do not establish a total" in samples["note"]
    for sample in samples["samples"]:
        assert len(sample["rows"]) <= 10
        assert sample["ordering"]


def test_the_packet_states_what_can_actually_be_executed(built):
    with_cap(built, 0)
    execution = packet(built).payload["I_execution"]
    assert execution["sql"]["available"] is True
    assert "no ATTACH" in execution["sql"]["statement_rule"]
    assert "cannot widen what you see" in execution["sql"]["tenant_rule"]
    # Section 10.2: state the capability as it actually is on this host, and
    # never downgrade a missing one. Both branches are asserted because both
    # are real deployments -- the sandbox needs namespace privileges that a
    # locked-down container may not grant.
    from backend.cockpit_agentic import pysandbox as py_mod
    python = execution["python"]
    detected = py_mod.probe()
    assert python["available"] is detected.available
    if detected.available:
        assert python["packages"] == ["numpy", "pandas", "the standard library"]
        assert "not present" in python["package_rule"]
        assert "no database connection" in python["input_rule"].lower()
        assert "repair is yours" in python["failure_rule"]
    else:
        assert "downgraded to in-process execution" in python["reason"]
        assert "no in-process substitute" in python["consequence"]


def test_the_packet_carries_the_remaining_budget(built):
    with_cap(built, 0)
    budget = packet(built).payload["J_budget"]
    assert budget["submissions_remaining"] == 5
    assert budget["analysis_rounds_remaining"] == 3
    assert budget["cost_enforced"] is False
    assert budget["spend_usd"] == "UNKNOWN"


def test_the_packet_carries_no_other_module_s_data(built):
    with_cap(built, 0)
    blob = packet(built).serialize().lower()
    for leak in ("ews_alert", "watchlist_register", "scorecard_run",
                 "retail_application_scorecard", "lens_tile"):
        assert leak not in blob


def test_the_untrusted_data_note_travels_with_the_packet(built):
    with_cap(built, 0)
    payload = packet(built).payload
    assert "never an instruction" in payload["untrusted_data_note"].lower() or \
           "data, not instruction" in payload["untrusted_data_note"].lower()


def test_the_token_estimate_is_conservative_and_says_so(built):
    with_cap(built, 0)
    result = packet(built)
    assert "conservative" in result.token_method
    assert X.CHARS_PER_TOKEN <= 4.0, (
        "under-counting is the failure that matters: it would let an oversized "
        "packet through")
