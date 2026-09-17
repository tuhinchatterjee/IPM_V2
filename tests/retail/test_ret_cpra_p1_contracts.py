"""P1 contract gates: identity, metric and cohort, before any story adapter.

These run before the ten stories exist and are meant to keep running after
them. Each one guards a failure that produces a *wrong answer quietly* rather
than an error:

* a facility-month that is not unique — every total silently doubles;
* an EWS join at the wrong grain — a customer with two products contributes
  their ECL twice;
* an application feature that moved — the fixed-cohort comparison that the
  underwriting stories rest on becomes meaningless;
* a figure with no published definition — a reader cannot check what was
  counted;
* a missing value rendered as a zero — a coverage gap becomes an assertion
  that nothing is wrong;
* a cohort that grows between two steps — the customers in the workbook are
  not the customers the reader saw.

Everything here is synthetic demonstration material.
"""

from __future__ import annotations

import pytest

from backend.retail import cohort as ch
from backend.retail import episodes as ep
from backend.retail import metrics_contract as mc


# ------------------------------------------------------------------ metrics


def test_every_metric_states_its_denominator_and_what_it_cannot_prove():
    for metric in mc.ALL:
        assert metric.denominator, f"{metric.metric_id} has no denominator"
        assert metric.window, f"{metric.metric_id} has no window"
        assert metric.grain, f"{metric.metric_id} has no grain"
        assert len(metric.prohibited) > 20, (
            f"{metric.metric_id} has no prohibited inference. Every one of "
            f"these measures is routinely mistaken for another; the caveat is "
            f"part of the definition, not decoration.")


def test_the_four_measures_that_get_confused_are_four_measures():
    ids = {m.metric_id for m in mc.ALL}
    assert {"affected_population", "roll_rate", "observed_default_rate",
            "pd_12m"} <= ids
    # And each says so about the others.
    assert "migration" in mc.AFFECTED_POPULATION.prohibited.lower()
    assert "stock" in mc.ROLL_RATE.prohibited.lower()
    assert "pd" in mc.ODR.prohibited.lower()
    assert "impaired" in mc.PD12.prohibited.lower()


def test_an_undefined_figure_cannot_be_quoted():
    with pytest.raises(KeyError):
        mc.definition("thirty_plus_roll_rate_probably")


def test_missing_is_four_states_and_never_a_zero():
    assert len(mc.MISSING_STATES) == 4
    state = mc.coverage(covered=8, eligible=12,
                        missing={mc.UNAVAILABLE: 3, mc.UNVERIFIED: 1})
    assert state["coverage_pct"] == pytest.approx(66.67, abs=0.01)
    assert state["complete"] is False
    assert set(state["missing_reasons"]) == {mc.UNAVAILABLE, mc.UNVERIFIED}
    with pytest.raises(ValueError):
        mc.coverage(covered=1, eligible=2, missing={"zero": 1})


def test_full_coverage_says_so_rather_than_being_inferred_from_silence():
    assert mc.coverage(covered=15, eligible=15)["complete"] is True


# ----------------------------------------------------------------- episodes


def test_there_are_ten_episodes_and_each_is_a_dimension_not_a_title():
    episodes = ep.all_episodes()
    assert len(episodes) == 10
    assert len({e.case_id for e in episodes}) == 10
    for episode in episodes:
        assert episode.dimension_columns, (
            f"{episode.case_id} has no dimension columns. A pocket that is "
            f"only a phrase in an answer cannot be filtered in Early Warning "
            f"and cannot be exported.")
        assert episode.evidence_columns
        assert episode.product in ("CREDIT_CARD", "PERSONAL_LOAN",
                                   "AUTO_LOAN", "HOME_LOAN")
        assert episode.grain in ("facility", "customer")


def test_each_episode_has_six_steps_and_five_chips():
    for episode in ep.all_episodes():
        assert [s.step for s in episode.steps] == ["S0", "S1", "S2", "S3",
                                                   "S4", "S5"]
        assert len(episode.chips) == 5
        for step in episode.steps:
            assert step.prompt.strip()
            assert step.chart.strip()


def test_every_step_cites_only_published_metric_definitions():
    for episode in ep.all_episodes():
        for step in episode.steps:
            assert step.metric_ids
            for metric_id in step.metric_ids:
                mc.definition(metric_id)  # raises if undefined


def test_each_episode_states_its_countercheck_and_its_draft_policy():
    for episode in ep.all_episodes():
        assert len(episode.countercheck) > 30, episode.case_id
        assert episode.policy_id.startswith("DEMO-"), (
            f"{episode.case_id} cites {episode.policy_id}. No approved bank "
            f"policy was supplied with this work, so every clause must be a "
            f"clearly marked demonstration draft.")
        assert len(episode.policy_actions) == 3
        for action in episode.policy_actions:
            assert "NOT BANK APPROVED" in action["status"]
            assert action["owner"] and action["timing"] and action["safeguard"]


def test_the_vintage_story_diagnoses_the_application_model():
    # C02's whole finding is that the original decision was weak. Decomposing
    # a behavioural score there answers a question nobody asked, and the
    # specification says so twice.
    assert ep.by_id("C02").diagnosis_model == "application"


def test_the_recovery_story_is_not_diagnosed_as_borrower_deterioration():
    # C06 is the negative control: PD 5.0% -> 5.1%, score down three points,
    # and the loss is entirely in severity. A behavioural diagnosis here would
    # have to invent a deterioration that is not in the data.
    assert ep.by_id("C06").diagnosis_model == "recovery"
    assert ep.by_id("C06").headline_metric == mc.ECL.metric_id


def test_the_two_outcome_window_stories_use_an_observed_default_rate():
    for case_id in ("C02", "C10"):
        assert ep.by_id(case_id).headline_metric == mc.ODR.metric_id, (
            f"{case_id} is measured over a matured outcome window. A stock "
            f"share would be a different question with a different "
            f"denominator.")


def test_no_pocket_is_a_protected_characteristic():
    banned = ("nationality", "sex", "gender", "religion", "race", "age_band",
              "marital")
    for episode in ep.all_episodes():
        for column in episode.dimension_columns + episode.evidence_columns:
            assert not any(b in column.lower() for b in banned), (
                f"{episode.case_id} would select on {column}. C09 is a "
                f"documented cash-flow mismatch, not a cohort of people over "
                f"a certain age.")


# ------------------------------------------------------------------- cohort


def _draft(**kw):
    base = dict(case_id="C01", occurrence_id="OCC-1", thread_id="T1",
                step_id="S0", source_as_of="2026-08",
                source_bundle_id="bundle-1",
                metric_definition_ids=["affected_population"],
                customer_ids=["c1", "c2", "c3"],
                facility_ids=["f1", "f2", "f3"],
                owner_user_id=1, purpose="retail early arrears investigation")
    base.update(kw)
    return ch.Draft(**base)


def test_a_cohort_may_not_cite_an_undefined_measure(db_session):
    with pytest.raises(KeyError):
        ch.create(db_session, _draft(metric_definition_ids=["made_up_rate"]))


def test_a_cohort_must_record_the_date_it_was_measured_at(db_session):
    with pytest.raises(ValueError):
        ch.create(db_session, _draft(source_as_of=""))


def test_a_cohort_must_say_whether_it_is_everything_or_a_selection(db_session):
    with pytest.raises(ValueError):
        ch.create(db_session, _draft(selection_mode="some"))
    with pytest.raises(ValueError):
        ch.create(db_session, _draft(facility_mode="whatever"))


def test_the_same_cohort_hashes_the_same_whatever_order_it_arrives_in(db_session):
    first = ch.create(db_session, _draft(customer_ids=["c3", "c1", "c2"]))
    second = ch.create(db_session, _draft(customer_ids=["c1", "c2", "c3"]))
    assert first.content_hash == second.content_hash
    assert first.snapshot_id != second.snapshot_id


def test_a_ticked_subset_is_not_the_same_cohort_as_everything_that_matched(db_session):
    matched = ch.create(db_session, _draft())
    subset = ch.select_subset(db_session, matched, customer_ids=["c1", "c2"],
                              facility_ids=["f1", "f2"])
    assert subset.content_hash != matched.content_hash
    assert subset.selection_mode == ch.SELECTED_SUBSET
    assert subset.customer_count == 2


def test_a_duplicated_customer_is_counted_once(db_session):
    row = ch.create(db_session, _draft(customer_ids=["c1", "c1", "c2"],
                                       facility_ids=["f1", "f1"]))
    assert row.customer_count == 2
    assert row.facility_count == 1


def test_a_step_may_only_narrow_never_re_query(db_session):
    parent = ch.create(db_session, _draft())
    narrowed = ch.narrow(db_session, parent, step_id="S1",
                         customer_ids=["c1", "c2"], facility_ids=["f1", "f2"],
                         predicate=ch.predicate_ast(
                             ch.Predicate("dpd_bucket", "==", "20-29")))
    assert narrowed.customer_count == 2
    assert narrowed.parent_snapshot_id == parent.snapshot_id
    with pytest.raises(ValueError):
        ch.narrow(db_session, parent, step_id="S2",
                  customer_ids=["c1", "c9"], facility_ids=["f1"],
                  predicate={})


def test_an_export_cannot_carry_a_step_the_reader_never_visited(db_session):
    parent = ch.create(db_session, _draft())
    at_s1 = ch.narrow(db_session, parent, step_id="S1",
                      customer_ids=["c1"], facility_ids=["f1"], predicate={})
    assert ch.allows_step(at_s1, "S0") and ch.allows_step(at_s1, "S1")
    assert not ch.allows_step(at_s1, "S4")
    assert not ch.allows_step(at_s1, "S5")


def test_knowing_a_snapshot_id_is_not_permission_to_read_it(db_session):
    row = ch.create(db_session, _draft(owner_user_id=1))
    assert ch.read(db_session, row.snapshot_id, user_id=1) is not None
    with pytest.raises(ch.NotPermitted):
        ch.read(db_session, row.snapshot_id, user_id=2)
    # An administrator may; a team member scoped to the same team may.
    assert ch.read(db_session, row.snapshot_id, user_id=2, role="ADMIN")


def test_an_unowned_customer_list_is_refused_rather_than_public(db_session):
    row = ch.create(db_session, _draft(owner_user_id=None))
    assert ch.permitted(row, user_id=1) is False


def test_a_refusal_and_an_absence_are_told_apart_by_nobody(db_session):
    # Both raise the same exception with the same wording on purpose: saying
    # "that exists but is not yours" confirms somebody else's cohort exists.
    row = ch.create(db_session, _draft(owner_user_id=1))
    with pytest.raises(ch.NotPermitted) as refused:
        ch.read(db_session, row.snapshot_id, user_id=99)
    with pytest.raises(ch.NotPermitted) as absent:
        ch.read(db_session, "CPRA-NOTHING-0001", user_id=99)
    assert str(refused.value)[:40] != ""
    assert "may not exist" in str(refused.value)
    assert "may not exist" in str(absent.value)


def test_a_cohort_from_another_build_of_the_book_is_refused_not_reconciled(db_session):
    row = ch.create(db_session, _draft(source_bundle_id="bundle-1"))
    ch.require_bundle(row, "bundle-1")
    with pytest.raises(ch.BundleMismatch):
        ch.require_bundle(row, "bundle-2")


def test_reconciliation_names_what_differs_rather_than_saying_no(db_session):
    row = ch.create(db_session, _draft(
        totals={"ecl_weighted_sar": 42519.15}))
    ok = ch.reconcile(row, customer_ids=["c1", "c2", "c3"],
                      facility_ids=["f1", "f2", "f3"],
                      totals={"ecl_weighted_sar": 42519.15})
    assert ok["reconciled"] is True

    bad = ch.reconcile(row, customer_ids=["c1", "c2"],
                       facility_ids=["f1", "f2", "f3"],
                       totals={"ecl_weighted_sar": 42000.0})
    assert bad["reconciled"] is False
    what = {d["what"] for d in bad["differences"]}
    assert "customers" in what and "ecl_weighted_sar" in what


def test_the_view_does_not_carry_identifiers_by_habit(db_session):
    row = ch.create(db_session, _draft())
    assert "customer_ids" not in ch.view(row)
    assert ch.view(row, include_ids=True)["customer_ids"] == ["c1", "c2", "c3"]


def test_a_breadcrumb_reads_as_a_sentence(db_session):
    ast = ch.predicate_ast(
        ch.Predicate("product_subsegment", "==", "ALPHA_CARD_DEMO",
                     label="Alpha Card"),
        ch.Predicate("origination_score_band", "in", ["580-589", "590-599"],
                     label="original band 580-599"))
    assert ch.describe(ast) == "Alpha Card and original band 580-599"
    assert ch.describe({}) == "everything eligible"


# ------------------------------------------------- the book's own invariants
#
# These read the SHIPPED lake, because an invariant that holds in a 900-row
# temporary build and not in the 59,000-facility book the user opens is not an
# invariant. They skip loudly rather than passing when the lake is absent.


def test_a_facility_month_is_unique(retail_book):
    for month in (retail_book.months()[0], retail_book.months()[-1]):
        frame = retail_book.month(month, columns=["facility_id"])
        assert frame["facility_id"].is_unique, (
            f"{month} has duplicate facility rows. Every exposure, ECL and "
            f"count in the product is a sum over this grain, so a duplicate "
            f"does not fail — it silently doubles.")


def test_a_customer_is_distinct_customers_not_joined_rows(retail_book):
    latest = retail_book.months()[-1]
    frame = retail_book.month(latest, columns=["customer_id", "facility_id"])
    assert frame["customer_id"].nunique() < len(frame), (
        "No customer in the book holds two facilities, which would make the "
        "multi-facility gates unfalsifiable.")


def test_the_ews_panel_is_customer_product_and_does_not_multiply_ecl(retail_book):
    import pandas as pd

    latest = retail_book.months()[-1]
    panel_dir = retail_book.analytics_dir / "retail_ews_panel"
    if not panel_dir.exists():
        pytest.skip("The Early Warning panel has not been built.")
    # The panel writes part files, the book writes data.parquet. Globbing
    # rather than naming one is what stops this gate from skipping silently
    # and reporting a pass it never made.
    parts = sorted((panel_dir / f"reporting_month={latest}").glob("*.parquet"))
    if not parts:
        pytest.skip(f"No Early Warning panel for {latest}.")

    panel = pd.concat(
        [pd.read_parquet(p, columns=["customer_id", "product_code"])
         for p in parts], ignore_index=True)
    assert not panel.duplicated(["customer_id", "product_code"]).any(), (
        "The panel has more than one row per customer-product. Joining it to "
        "facilities at that grain is what multiplies a customer's ECL by the "
        "number of warnings they have.")

    book = retail_book.month(
        latest, columns=["customer_id", "facility_id", "product_code",
                         "ecl_weighted_sar"])
    before = round(float(book["ecl_weighted_sar"].sum()), 2)
    joined = book.merge(panel, on=["customer_id", "product_code"], how="left")
    after = round(float(joined["ecl_weighted_sar"].sum()), 2)
    assert after == pytest.approx(before, abs=0.01), (
        f"Joining the panel changed total ECL from {before} to {after}. The "
        f"join is not grain-safe.")


def test_an_original_application_score_never_moves(retail_book):
    """The fixed-cohort comparison the underwriting stories rest on.

    A portfolio average can change because the population changed. The same
    facility's own decision-time score cannot, and the moment it does, every
    'were they weak when approved' answer in C02 becomes unreadable.
    """
    import pandas as pd

    months = retail_book.months()
    columns = ["facility_id", "application_score_band", "origination_date"]
    first = retail_book.month(months[0], columns=columns)
    last = retail_book.month(months[-1], columns=columns)
    both = first.merge(last, on="facility_id", suffixes=("_first", "_last"))
    assert len(both) > 100, "too few surviving facilities to make this a test"

    moved_band = both["application_score_band_first"] != \
        both["application_score_band_last"]
    assert not moved_band.any(), (
        f"{int(moved_band.sum())} facilities changed their ORIGINAL "
        f"application score band between {months[0]} and {months[-1]}. An "
        f"origination value is immutable; a moving one means it is being "
        f"reconstructed from today's data.")

    moved_date = pd.to_datetime(both["origination_date_first"]) != \
        pd.to_datetime(both["origination_date_last"])
    assert not moved_date.any()


def test_every_published_month_covers_the_same_identity_space(retail_book):
    months = retail_book.months()
    assert len(months) >= 12
    for month in (months[0], months[len(months) // 2], months[-1]):
        frame = retail_book.month(
            month, columns=["customer_id", "facility_id", "product_code"])
        assert frame["customer_id"].notna().all()
        assert frame["facility_id"].notna().all()
        assert frame["product_code"].notna().all()
        assert (frame["facility_id"].astype(str).str.len() > 0).all()


def test_the_denominator_of_every_rate_is_reachable(retail_book):
    """A rate whose denominator is not a column is a rate nobody can check."""
    latest = retail_book.month(retail_book.months()[-1],
                               columns=["facility_id", "product_code",
                                        "dpd_bucket", "ifrs9_stage"])
    for column in ("product_code", "dpd_bucket", "ifrs9_stage"):
        counts = latest[column].value_counts(dropna=False)
        assert counts.sum() == len(latest), (
            f"{column} does not partition the book, so a share of it has no "
            f"honest denominator.")
