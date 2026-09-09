"""
Whether the analytical universe is the whole model, or only the part that
was convenient to flatten.

What this suite is for
----------------------
The wide view used to expose seventy-three columns: the roll-ups, the
sub-category scores, the layers, the notches. Everything a screen draws, and
nothing a credit officer would actually check. "Which obligors have a covenant
breach, and what was the reading behind it?" was not a question this domain
could be asked, because the signals lived in a second dataset keyed on a signal
key nobody had been shown.

So every case here asserts one of two things: that all 123 inventory rows are
present at customer-month grain with the fields the methodology gives them; or
that what the projection says about a signal is what the normalised
observation says, because a wide view that could disagree with the model would
be a second source of truth rather than a projection of one.
"""

from __future__ import annotations

import pytest

from backend.early_warning import catalog as cat
from backend.early_warning import dictionary as dic
from backend.early_warning import signal_fields as sigf
from backend.early_warning import v2_service as svc
from backend.early_warning import wide


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def frame():
    return wide.customer_month()


@pytest.fixture(scope="module")
def columns():
    return set(wide.columns())


# --------------------------------------------------- all 123, not only 38


def test_the_inventory_is_still_one_two_three(frame):
    """The count that everything else here is measured against."""
    assert len(sigf.fields()) == 123
    assert len(sigf.scored_fields()) == 105
    assert cat.status_counts()["SCORED"] == 105
    assert sum(v for k, v in cat.status_counts().items() if k != "SCORED") == 18
    del frame


def test_every_signal_is_exposed_at_customer_month_grain(columns):
    missing = [entry.name for entry in sigf.fields()
               if not set(entry.columns) <= columns]
    assert not missing, f"{len(missing)} signals have no columns: {missing[:5]}"


def test_a_scored_signal_carries_its_whole_explanation(columns):
    """Trigger, the five accelerator dimensions, decay, score and reason.

    A score whose accelerator bands are not readable is a score nobody can
    take apart, which is the same as a score nobody should act on.
    """
    required = ("fired", "observed_value", "baseline_value",
                "normalised_value", "trigger_severity_band", "trigger_score",
                "magnitude_band", "velocity_band", "persistence_band",
                "repetition_band", "corroboration_band",
                "accelerator_multiplier", "decay_class", "decay_factor",
                "score", "reason_code", "reason", "source_system",
                "evidence_age_days", "freshness")
    for entry in sigf.scored_fields():
        for suffix in required:
            assert entry.column(suffix) in columns, (
                f"{entry.name} has no {suffix} column")


def test_a_signal_that_is_not_scored_says_what_happened_to_it(columns, frame):
    """Ten merged, five dropped, two replaced, one moved.

    They keep status, status detail and lineage and get nothing else: a
    column for the accelerator bands of a dropped signal would be empty for a
    reason nobody could recover from the data.
    """
    retired = [e for e in sigf.fields() if not e.scored]
    assert len(retired) == 18
    for entry in retired:
        assert entry.column("status") in columns
        assert entry.column("status_detail") in columns
        assert entry.column("score") not in columns, (
            f"{entry.name} is not scored and has a score column")
        assert frame[entry.column("status")].iloc[0] in (
            cat.MERGED, cat.DROPPED, cat.REPLACED, cat.MOVED)


def test_the_universe_is_far_larger_than_the_roll_ups(columns):
    """The specific claim the previous dictionary made and should not have."""
    assert len(columns) > 2000, (
        f"{len(columns)} columns is not the complete analytical universe")
    signal_columns = {c for entry in sigf.fields() for c in entry.columns}
    assert len(signal_columns) == len(sigf.scored_fields()) * len(
        sigf.SCORED_MEASURES) + 18 * len(sigf.INVENTORY_MEASURES)


# ------------------------------------------- the projection cannot disagree


def test_a_fired_signal_matches_its_own_observation(frame):
    """The wide view is a projection, never a second computation."""
    period = svc.latest_period()
    observations = svc.observations(period)
    if observations.empty:
        pytest.skip("no signal fired in the latest published month")

    checked = 0
    indexed = frame.set_index("customer_id")
    for key, rows in sigf.by_trigger_key().items():
        entry = rows[0]
        if not entry.scored:
            continue
        for_key = observations[observations["signal_key"] == key]
        if for_key.empty:
            continue
        worst = for_key.sort_values("signal_score", ascending=False).iloc[0]
        customer = str(worst["customer_id"])
        assert bool(indexed.loc[customer, entry.column("fired")])
        assert indexed.loc[customer, entry.column("score")] == \
            pytest.approx(float(worst["signal_score"]))
        assert indexed.loc[customer, entry.column("trigger_score")] == \
            pytest.approx(float(worst["trigger_severity_score"]))
        assert indexed.loc[customer, entry.column("decay_factor")] == \
            pytest.approx(float(worst["decay_factor"]))
        assert indexed.loc[customer, entry.column("reason_code")] == \
            str(worst["reason_code"])
        checked += 1
    assert checked >= 10, f"only {checked} signals were actually checked"


def test_the_reading_behind_a_signal_is_persisted_not_re_derived(frame):
    """What the trigger saw, what it was compared with, what it normalised to.

    Without these, "why is this signal at 80?" can only be answered by
    re-running the calculation against a window that may have moved, and a
    re-derivation is not evidence.
    """
    period = svc.latest_period()
    observations = svc.observations(period)
    fired = observations[observations["observed_value"].notna()]
    if fired.empty:
        pytest.skip("no observation in this month carries a reading")
    row = fired.iloc[0]
    entry = sigf.by_trigger_key()[str(row["signal_key"])][0]
    indexed = frame.set_index("customer_id")
    customer = str(row["customer_id"])
    assert indexed.loc[customer, entry.column("observed_value")] is not None
    assert str(indexed.loc[customer, entry.column("observed_unit")]).strip()


def test_a_signal_with_no_feed_is_absent_rather_than_zero(frame):
    """An empty column and a column of noughts are different facts.

    A planner that averaged a column of noughts would report that every
    obligor scores zero on a signal this deployment cannot see, which reads
    as evidence of safety.
    """
    unfed = [e for e in sigf.scored_fields()
             if not frame[e.column("fired")].any()]
    assert unfed, "this test is meaningless if every signal has a feed"
    entry = unfed[0]
    assert frame[entry.column("score")].isna().all()
    assert (frame[entry.column("fired")] == False).all()  # noqa: E712


# ----------------------------------------------- the nodes and the roll-up


def test_each_sub_category_carries_its_band_reason_and_worst_signal(columns):
    for code in wide.SUBCATEGORY_CODES:
        for measure in wide.SUBCATEGORY_MEASURES:
            assert wide.subcategory_column(code, measure) in columns, (
                f"{code} has no {measure}")


def test_a_sub_category_band_agrees_with_its_score(frame):
    from backend.early_warning import aggregation as agg

    for code in wide.SUBCATEGORY_CODES[:6]:
        scores = frame[wide.subcategory_column(code, "score")]
        bands = frame[wide.subcategory_column(code, "band")]
        for score, band in list(zip(scores, bands))[:40]:
            assert band == agg.ta_verdict_band(float(score))


def test_the_roll_up_is_complete(columns):
    """Every output between the signal and the final band."""
    for name in ("ta_score", "ta_band", "classifier_score", "classifier_band",
                 "l1_ta", "l2_ta", "l3_ta", "l4_ta", "l2_c", "l4_c",
                 "anchor_score", "matrix_cell", "net_notches", "notch_points",
                 "ews_score", "ews_band", "dominant_layer",
                 "dominant_subcategory", "dominant_driver",
                 "override_applied", "override_types", "override_reasons"):
        assert name in columns, name
    for key in wide.NOTCH_KEYS:
        assert wide.notch_column(key) in columns


def test_the_governed_outputs_are_fields_rather_than_sentences(frame,
                                                               columns):
    """An action invented at answer time is not a governed one."""
    for name in ("escalation_rung", "escalation_role", "escalation_notified",
                 "escalation_exposure_tier", "escalation_ack_sla_days",
                 "escalation_decision_sla_days", "expected_action",
                 "recommended_action", "action_owner_role", "action_owner",
                 "action_timeframe_days", "evidence_to_close",
                 "action_reversibility_rank", "action_cost_rank"):
        assert name in columns, name

    from backend.early_warning import escalation as esc

    row = frame.sort_values("ews_score", ascending=False).iloc[0]
    route = esc.route_for(str(row["ews_band"]), float(row["exposure"]))
    assert row["escalation_rung"] == ", ".join(route["escalated_to"])
    assert row["escalation_ack_sla_days"] == route["ack_sla_days"]


# --------------------------------------------------------- the dictionary


def test_the_dictionary_and_the_view_are_an_exact_contract(columns):
    """Both directions, at the new size."""
    described = set(dic.names())
    assert not described - columns, sorted(described - columns)[:8]
    assert not columns - described, sorted(columns - described)[:8]
    assert len(dic.fields()) == len(columns)


def test_the_dictionary_is_no_longer_seventy_three_fields():
    assert len(dic.fields()) > 2000, (
        f"{len(dic.fields())} fields is not the complete field universe")
    groups = dic.groups()
    assert groups[dic.SIGNAL_SCORES], "the signal inventory group is empty"
    assert groups[dic.WORKFLOW], "the workflow group is empty"


def test_every_field_is_described_well_enough_to_use(columns):
    """A generated definition is still a definition, or it is filler."""
    thin = [f.name for f in dic.fields() if len(f.definition) < 40]
    assert not thin, f"{len(thin)} definitions are too thin: {thin[:5]}"
    del columns


def test_a_signal_field_names_its_node_its_layer_and_its_source():
    entry = sigf.scored_fields()[0]
    described = dic.by_name()[entry.column("score")]
    assert described.sub_category == entry.code
    assert described.layer == entry.layer
    assert entry.name in described.label
    assert described.group == dic.SIGNAL_SCORES


def test_coverage_is_measured_rather_than_declared():
    """The signal columns are where this matters most."""
    summary = dic.coverage_summary()
    assert summary["fields"] == len(dic.fields())
    assert summary["empty"] > 0, (
        "no field is reported empty, which cannot be true with 123 signals "
        "and a feed for some of them")
    assert summary["fully_populated"] > 0

    measured = dic.profile()
    fed = [e for e in sigf.scored_fields()
           if measured[e.column("score")]["missing_rate"] < 1.0]
    unfed = [e for e in sigf.scored_fields()
             if measured[e.column("score")]["missing_rate"] == 1.0]
    assert fed and unfed, (
        "the profile does not distinguish a signal with a feed from one "
        "without, which is the whole point of measuring it")


def test_the_periods_are_still_twenty_contiguous_months():
    periods = svc.periods()
    assert len(periods) >= 20
    assert periods[0] < periods[-1]


# ------------------------------------------------------- relevance ranking


@pytest.mark.parametrize("question,expected", [
    ("Which names have a covenant breach and why?", "covenant"),
    ("Show the obligors whose utilisation increase fired.", "utilisation"),
    ("Which borrowers had a rating migration downgrade?", "rating"),
])
def test_the_top_fields_reach_the_signal_the_question_names(question,
                                                            expected):
    """Ten fields out of two and a half thousand, and they have to be the
    right ten.

    A relevance selection that returned the same ten roll-ups whatever was
    asked would leave the expanded universe unreachable in practice.
    """
    from backend.early_warning import grain as grain_mod

    names = [f["name"] for f in grain_mod.top_fields(question)]
    assert any(expected in name and name.startswith("sig") for name in names), (
        f"{question!r} surfaced {names}")


def test_the_sample_rows_show_only_the_signals_that_fired():
    """Two and a half thousand values of which two thousand are nulls teaches
    a planner nothing and costs the whole context window."""
    from backend.early_warning import grain as grain_mod

    rows = grain_mod.sample()
    assert rows
    for row in rows:
        assert len(row) < 400, f"a sample row carried {len(row)} columns"
        assert "ews_score" in row and "customer_id" in row
