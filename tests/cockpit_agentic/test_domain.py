"""The twenty-quarter domain, its two time axes and its field dictionary.
Specification sections 3 and 4."""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import calendar as cal
from backend.cockpit_agentic import catalog as C
from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic.contracts import ContractError


@pytest.fixture()
def calendar() -> cal.Calendar:
    return cal.Calendar.ending("2026Q2", dataset_release_id="demo-20q-v1")


@pytest.fixture()
def catalog(calendar) -> C.Catalog:
    return C.build(dataset_release_id="demo-20q-v1", calendar=calendar)


# ---- section 3.1: exactly twenty reporting slots --------------------------

def test_a_release_has_exactly_twenty_reporting_slots(calendar):
    assert len(calendar) == 20
    assert calendar.first == "2021Q3" and calendar.last == "2026Q2"


def test_a_calendar_that_is_not_twenty_slots_is_refused():
    with pytest.raises(ValueError, match="exactly 20"):
        cal.Calendar(dataset_release_id="r", slots=("2026Q1", "2026Q2"))


def test_slots_must_be_consecutive_and_ordered():
    every_other = tuple(cal.Quarter.of(2020, 1).shift(i * 2).label
                        for i in range(20))
    with pytest.raises(ValueError, match="consecutive"):
        cal.Calendar(dataset_release_id="r", slots=every_other)
    backwards = tuple(reversed(cal.Calendar.ending(
        "2026Q2", dataset_release_id="r").slots))
    with pytest.raises(ValueError, match="ascending"):
        cal.Calendar(dataset_release_id="r", slots=backwards)


def test_the_twenty_first_quarter_is_not_reachable(calendar):
    with pytest.raises(cal.OutsideCalendar) as e:
        calendar.position("2021Q2")
    assert "not reachable from the Cockpit" in str(e.value)
    with pytest.raises(cal.OutsideCalendar):
        calendar.position("2026Q3")


def test_created_slots_are_not_observed_quarters():
    """Section 3.1: a release must never claim twenty observed quarters merely
    because twenty calendar slots were created."""
    partial = cal.Calendar.ending(
        "2026Q2", dataset_release_id="r",
        populated=("2025Q3", "2025Q4", "2026Q1", "2026Q2"))
    assert len(partial) == 20
    assert len(partial.populated) == 4
    assert len(partial.missing) == 16
    assert partial.fully_populated is False
    assert partial.to_dict()["missing_quarters"][0] == "2021Q3"


def test_previous_returns_none_at_the_start_rather_than_substituting(calendar):
    assert calendar.previous("2021Q3") is None
    assert calendar.previous("2021Q4") == "2021Q3"


# ---- section 3.1: the macro window is a SECOND axis ------------------------

def test_the_macro_window_is_twenty_offsets_from_minus_four_to_plus_fifteen():
    assert cal.MACRO_OFFSETS == tuple(range(-4, 16))
    assert len(cal.MACRO_OFFSETS) == 20


def test_the_macro_window_at_the_last_anchor_matches_the_worked_example(calendar):
    """Section 3.1: at the 2026Q2 anchor the macro window runs 2025Q2 through
    2030Q1."""
    window = calendar.macro_window("2026Q2")
    assert len(window) == 20
    assert window[0] == (-4, "2025Q2")
    assert window[4] == (0, "2026Q2")
    assert window[-1] == (15, "2030Q1")


def test_macro_targets_extend_past_the_calendar_without_extending_it(calendar):
    targets = calendar.macro_targets()
    assert len(targets) == 39, "twenty anchors x twenty offsets, deduplicated"
    assert targets[0] == "2020Q3" and targets[-1] == "2030Q1"
    # ...and none of the extra periods became a reporting quarter.
    assert len(calendar) == 20
    assert "2030Q1" not in calendar
    assert "2020Q3" not in calendar


def test_a_forward_macro_value_is_a_forecast_not_an_actual(calendar):
    assert calendar.is_forecast(anchor="2026Q2", target="2027Q1") is True
    assert calendar.is_forecast(anchor="2026Q2", target="2026Q2") is False
    assert calendar.is_forecast(anchor="2026Q2", target="2025Q4") is False


def test_point_in_time_availability(calendar):
    from datetime import date

    annual = cal.available_by(date(2025, 12, 31), audited=True)
    assert cal.knowable(annual, date(2026, 6, 30)) is True
    assert cal.knowable(annual, date(2026, 3, 31)) is False


# ---- section 4: the field dictionary --------------------------------------

def test_the_forty_ratios_are_all_declared():
    assert len(F.RATIO_DEFINITIONS) == 40
    assert len(set(F.RATIO_NAMES)) == 40
    numbers = [n for n, _f, _d, _u in F.RATIO_DEFINITIONS]
    assert numbers == list(range(1, 41))
    for name in ("dscr", "current_ratio", "cash_conversion_cycle_days",
                 "capex_to_operating_cash_flow"):
        assert name in F.RATIO_NAMES


def test_every_ratio_has_a_status_and_a_source_value_companion():
    names = F.all_column_names(F.RATING_RATIO)
    for ratio in F.RATIO_NAMES:
        assert f"{ratio}_status" in names
        assert f"{ratio}_source_value" in names


def test_nineteen_grades_ranked_aaa_to_c_with_default_kept_separate():
    assert len(F.RATING_SCALE) == 19
    assert F.RATING_SCALE[0] == "AAA" and F.RATING_SCALE[-1] == "C"
    assert F.RATING_RANK["AAA"] == 1 and F.RATING_RANK["C"] == 19
    assert F.RATING_RANK["BBB"] < F.RATING_RANK["BB"], "larger rank is weaker"
    for absent in ("CCC+", "CCC-", "D"):
        assert absent not in F.RATING_SCALE
    assert F.find(F.FACILITY_QUARTER, "default_flag") is not None


def test_exactly_twenty_qualitative_questions_with_stable_ids():
    assert len(F.QUALITATIVE_QUESTIONS) == 20
    assert F.QUALITATIVE_IDS[0] == "Q01" and F.QUALITATIVE_IDS[-1] == "Q20"
    assert len(set(F.QUALITATIVE_IDS)) == 20
    for _qid, field_name, question in F.QUALITATIVE_QUESTIONS:
        assert field_name.endswith("_answer") and question.endswith("?")


def test_twelve_collateral_types_expand_to_one_hundred_and_eight_columns():
    """Section 4.9: the catalog must expand these into ALL actual column names
    and never send an unresolved placeholder."""
    assert len(F.COLLATERAL_TYPES) == 12
    assert len(F.COLLATERAL_SUMMARY_SUFFIXES) == 9
    assert len(F.COLLATERAL_SUMMARY_FIELDS) == 108
    names = F.all_column_names(F.FACILITY_QUARTER)
    for kind in F.COLLATERAL_TYPES:
        for suffix, *_ in F.COLLATERAL_SUMMARY_SUFFIXES:
            assert f"{kind}_{suffix}" in names


def test_no_unexpanded_placeholder_exists_anywhere():
    assert F.summary()["unexpanded_placeholders"] == 0
    for spec in F.ALL_FIELDS:
        assert "{" not in spec.name and "}" not in spec.name


def test_a_placeholder_field_cannot_be_constructed_at_all():
    from backend.cockpit_agentic.contracts import CockpitFieldSpec

    with pytest.raises(ContractError):
        CockpitFieldSpec(name="{type}_net_value_rcy", relation="r", label="l",
                         definition="d", dtype="float")


def test_ten_macro_factors_yield_two_hundred_pivot_cells_not_two_hundred_factors():
    assert len(F.MACRO_FACTORS) == 10
    assert len(F.MACRO_PIVOT_FIELDS) == 200
    assert len(set(F.MACRO_FACTOR_IDS)) == 10
    suffixes = set(F.MACRO_OFFSET_SUFFIXES)
    assert suffixes == ({f"lag{i}" for i in range(1, 5)} | {"current"}
                        | {f"lead{i}" for i in range(1, 16)})


def test_the_four_pd_fields_are_all_present_and_distinct():
    """Section 4.2: twelve-month and lifetime PD are different concepts, and
    PIT is not a substitute for TTC."""
    for name in ("pd_pit_12m", "pd_pit_lifetime", "pd_ttc_12m",
                 "pd_ttc_lifetime"):
        spec = F.find(F.FACILITY_QUARTER, name)
        assert spec is not None and spec.unit == "probability_0_1"
    lifetime = F.find(F.FACILITY_QUARTER, "pd_pit_lifetime")
    assert "CUMULATIVE" in lifetime.definition
    ttc = F.find(F.FACILITY_QUARTER, "pd_ttc_lifetime")
    assert "relabelled annual PD" in ttc.definition


def test_the_lifetime_horizon_is_not_the_reporting_calendar():
    spec = F.find(F.FACILITY_QUARTER, "pd_lifetime_horizon_months")
    assert "not automatically twenty quarters" in spec.definition.lower()


def test_null_is_not_zero():
    reason = next(k for k in F.COMMON_KEYS if k.name == "missing_reason")
    assert "not zero" in reason.definition
    assert "not_applicable" in reason.enumeration


# ---- section 3.3: several grains in one domain ----------------------------

def test_every_relation_declares_its_grain():
    for relation in F.RELATIONS:
        assert F.GRAIN[relation], f"{relation} has no declared grain"


def test_the_borrower_grain_warns_about_repetition_across_facilities():
    join = next(j for j in F.JOINS
                if j["right"] == F.BORROWER_FINANCIAL)
    assert join["cardinality"] == "many_to_one"
    assert "once per facility" in join["warning"]


def test_a_shared_collateral_asset_is_counted_once():
    join = next(j for j in F.JOINS if j["right"] == F.COLLATERAL)
    assert "triples it" in join["warning"]
    whole = F.find(F.COLLATERAL, "gross_market_value_rcy")
    assert whole.aggregation == "not_additive"
    allocated = F.find(F.COLLATERAL_ALLOCATION, "allocated_net_value_rcy")
    assert allocated.aggregation == "additive"


def test_scenario_ecl_is_not_additive_across_scenarios():
    spec = F.find(F.IFRS9_DETAIL, "scenario_ecl")
    assert "weight them" in spec.definition


def test_a_borrower_wide_covenant_is_not_counted_once_per_facility():
    scope = F.find(F.COVENANT, "binding_scope")
    assert scope.enumeration == ("borrower", "facility")
    assert "once per facility" in scope.definition


def test_untested_is_never_reported_as_compliant():
    status = F.find(F.COVENANT, "test_status")
    assert "never reported as compliant" in status.definition
    assert "not_tested" in status.enumeration


# ---- the catalog ----------------------------------------------------------

def test_the_compact_catalog_contains_every_business_field(catalog):
    compact = catalog.compact()
    named: set[tuple[str, str]] = set()
    for relation, block in compact["relations"].items():
        for field in block.get("fields", []):
            named.add((relation, field["n"]))
        for family in block.get("column_families", []):
            for name in family["names"]:
                named.add((relation, name))
    for key in compact["common_keys"]["fields"]:
        for relation in F.RELATIONS:
            named.add((relation, key["n"]))
    missing = [(s.relation, s.name) for s in F.ALL_FIELDS
               if s.relation in F.RELATIONS and (s.relation, s.name) not in named]
    assert missing == [], (
        "section 7.4-D: the COMPLETE dictionary goes to Opus. Never replace it "
        "with only the important fields.")


def test_every_field_the_compact_catalog_names_actually_resolves(catalog):
    compact = catalog.compact()
    for relation, block in compact["relations"].items():
        for family in block.get("column_families", []):
            for name in family["names"]:
                assert catalog.resolve(relation, name) is not None


def test_the_macro_pivot_is_described_by_an_exact_reversible_rule(catalog):
    pivot = catalog.compact()["relations"][C.MACRO_PIVOT]
    rule = pivot["column_rule"]
    assert len(rule["factor_ids"]) == 10
    assert len(rule["offset_suffixes"]) == 20
    # The rule is exact: every column it implies resolves.
    for factor in rule["factor_ids"]:
        for suffix in rule["offset_suffixes"]:
            catalog.resolve(C.MACRO_PIVOT, f"{factor}_{suffix}")
    assert "not two hundred factors" in rule["meaning"]


def test_the_common_keys_are_serialized_once_not_ten_times(catalog):
    compact = catalog.compact()
    assert len(compact["common_keys"]["fields"]) == len(F.COMMON_KEYS)
    facility = compact["relations"][F.FACILITY_QUARTER]["fields"]
    assert not any(f["n"] == "tenant_id" for f in facility)
    assert F.FACILITY_QUARTER in compact["common_keys"]["applies_to"]


def test_the_worked_missing_column_example_from_section_eight(catalog):
    """`pd_12_month` does not exist; `pd_pit_12m` and `pd_ttc_12m` do."""
    with pytest.raises(C.UnknownField):
        catalog.resolve(F.FACILITY_QUARTER, "pd_12_month")
    alternatives = catalog.alternatives(F.FACILITY_QUARTER, "pd_12_month")
    names = [a.field_name for a in alternatives]
    assert names[:2] == ["pd_pit_12m", "pd_ttc_12m"]
    assert all(a.unit == "probability_0_1" for a in alternatives[:2])


def test_a_refusal_does_not_map_the_rest_of_the_application(catalog):
    with pytest.raises(C.UnknownRelation) as e:
        catalog.require_relation("ews_alerts")
    message = str(e.value)
    assert "ews" not in message.replace("ews_alerts", "")
    for leak in ("scorecard", "lens", "stress", "early_warning"):
        assert leak not in message.lower()


def test_the_catalog_states_the_reporting_currency_convention(catalog):
    compact = catalog.compact()
    assert "_rcy" in compact["rcy_note"]
    assert compact["reporting_currency"] == "INR"


def test_the_ratio_definitions_are_labelled_semantics_not_a_template(catalog):
    note = catalog.compact()["ratio_note"]
    assert "not an analysis you are required to perform" in note
    assert "not a template to imitate" in note
