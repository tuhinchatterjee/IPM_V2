"""The graph fields on the Borrower 360, and which kind of absent they say.

Twenty fields used to read ``NOT COMPUTED`` on every row. The point of this
suite is not that they now hold values - it is that where they DON'T hold a
value, they say which of four different things is true:

    NOT COMPUTED          the derivation did not run for this quarter
    NOT_AVAILABLE         it ran, and this borrower is not in that graph
    NOT_APPLICABLE        the measure does not apply to this borrower
    DATA_QUALITY_BLOCKED  the input was rejected, so it did not run

Collapsing any two of those into one - or into zero - is the failure this
suite exists to catch.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.corporate import graphquality as gq
from backend.corporate import graphsummary as gs
from backend.corporate import lineage as lineage_mod
from backend.corporate import network as net
from backend.corporate import snapshot as snapshot_mod

SENTINELS = {gs.NOT_AVAILABLE, gs.NOT_APPLICABLE, gs.DATA_QUALITY_BLOCKED}

GRAPH_FIELDS = [f.name for f in lineage_mod.FIELDS
                if f.group in snapshot_mod.GRAPH_GROUPS
                or f.name in snapshot_mod.GRAPH_DEPENDENT_FIELDS]


@pytest.fixture(scope="module")
def groups(graph_frames):
    return graph_frames[gs.GROUPS_DATASET]


@pytest.fixture(scope="module")
def issues(graph_frames):
    return graph_frames[gs.DQ_DATASET]


class TestTheDerivedDatasets:
    def test_both_declared_datasets_are_produced(self, graph_frames):
        """The lineage table has pointed at these two names since B5. Until
        now nothing produced them, so every VIEW SOURCE click led nowhere."""
        assert set(graph_frames) == {gs.GROUPS_DATASET, gs.DQ_DATASET}
        assert not graph_frames[gs.GROUPS_DATASET].empty
        assert not graph_frames[gs.DQ_DATASET].empty

    def test_the_group_dataset_is_one_row_per_borrower_quarter(self, groups):
        assert not groups.duplicated(subset=["borrower_id", "period"]).any()

    def test_the_issue_register_has_one_row_per_check_per_quarter(self, issues):
        assert not issues.duplicated(subset=["issue_id"]).any()
        assert len(issues) == len(gq.CHECKS) + len(gq.DATED_CHECKS)

    def test_every_row_is_marked_synthetic(self, groups, issues):
        assert (groups["origin"] == "SYNTHETIC_DEMO").all()
        assert (issues["origin"] == "SYNTHETIC_DEMO").all()

    def test_every_row_carries_its_method_and_policy_version(self, groups):
        assert (groups["method_version"] == net.NETWORK_VERSION).all()
        assert (groups["policy_version"] == net.POLICY_VERSION).all()
        assert (groups["summary_version"] == gs.SUMMARY_VERSION).all()

    def test_the_score_carries_its_banner_on_every_row(self, groups):
        assert (groups["network_risk_score_label"] == net.NRS_LABEL).all()

    def test_the_derivation_is_reproducible(self, universe, graph_period):
        first = gs.build(universe, periods=[graph_period])[gs.GROUPS_DATASET]
        second = gs.build(universe, periods=[graph_period])[gs.GROUPS_DATASET]
        pd.testing.assert_frame_equal(first, second)


class TestWhichKindOfAbsent:
    def test_every_numeric_measure_stays_numeric(self, groups):
        """The sentinel does NOT go in the measure column.

        "NOT_AVAILABLE" sitting alongside 2,480 floats makes the whole column
        VARCHAR, and a measure that cannot be averaged, ranked or charted is
        not a measure - it is a caption.
        """
        for column in gs.MEASURE_STATUS:
            assert groups[column].dtype.kind == "f", column
        available = groups[groups["network_risk_score_status"] == gs.AVAILABLE]
        assert available["network_risk_score"].mean() > 0

    def test_every_measure_has_a_status_column_beside_it(self, groups):
        for column, status in gs.MEASURE_STATUS.items():
            assert column in groups.columns
            assert status in groups.columns
            absent = groups[column].isna()
            assert (groups.loc[absent, status] != gs.AVAILABLE).all(), column
            assert (groups.loc[~absent, status] == gs.AVAILABLE).all(), column

    def test_a_borrower_outside_the_exposure_graph_is_not_available(
            self, groups):
        """Not zero. A borrower with no financial claims does not have a
        DebtRank impact of zero; it does not have one."""
        outside = groups[groups["debtrank_status"] == gs.NOT_AVAILABLE]
        assert len(outside) > 0
        assert outside["debtrank_impact"].isna().all()
        assert (outside["exposure_network_links"] == 0).all()

    def test_a_borrower_in_no_group_says_not_applicable_not_missing(
            self, groups):
        alone = groups[groups["connected_group_id"].astype(str)
                       == gs.NOT_APPLICABLE]
        assert len(alone) > 0
        assert (alone["connected_group_size"] == 1).all()
        assert (alone["group_status"] == gs.NOT_APPLICABLE).all()
        assert alone["group_utilisation_pct"].isna().all()

    def test_a_rejected_input_blocks_rather_than_returning_a_number(
            self, groups):
        """The planted defective registers. Their effective ownership is not
        available at any precision, and zero is not the answer."""
        blocked = groups[groups["ownership_status"] == gs.DATA_QUALITY_BLOCKED]
        assert len(blocked) > 0
        assert (blocked["effective_ownership_group_id"].astype(str)
                == gs.DATA_QUALITY_BLOCKED).all()
        assert blocked["ubo_count"].isna().all()
        assert (blocked["graph_dq_status"] == gs.DQ_INSUFFICIENT).all()
        assert (blocked["snapshot_validation_status"] == "FAILED").all()

    def test_a_count_that_came_back_empty_is_zero_not_a_sentinel(self, groups):
        """Zero is reserved for exactly this: the graph was searched and
        there is nothing there. That IS a measurement."""
        for column in ("director_count", "supplier_count", "customer_count",
                       "guarantee_links", "exposure_network_links"):
            values = groups[column]
            assert values.dtype.kind in "iu"
            assert (values >= 0).all()
            assert (values == 0).any()

    def test_the_three_sentinels_are_never_confused_with_each_other(
            self, groups):
        used = set()
        for column in groups.columns:
            used |= set(groups[column].astype(str)) & SENTINELS
        assert used == SENTINELS, (
            "all three sentinels must appear; if one never does, the "
            "distinction it draws is not being made")


class TestTheGroupFields:
    def test_group_roles_are_from_the_declared_set(self, groups):
        assert set(groups["group_role"]) <= {
            gs.ROLE_PARENT, gs.ROLE_SUBSIDIARY, gs.ROLE_AFFILIATE,
            gs.ROLE_STANDALONE}

    def test_not_every_borrower_is_a_subsidiary(self, groups):
        """Reading "controlled by someone" as SUBSIDIARY made 3,020 of 3,253
        borrowers subsidiaries, because almost every company here has a
        majority shareholder. A company owned by its founder is standalone."""
        counts = groups["group_role"].value_counts()
        assert counts.get(gs.ROLE_SUBSIDIARY, 0) < len(groups) * 0.6
        assert counts.get(gs.ROLE_STANDALONE, 0) > 0

    def test_the_snapshot_folds_the_number_and_its_status_back_together(
            self, graph_snapshot, graph_period):
        """A screen must never show a blank where a number would go."""
        block = graph_snapshot[graph_snapshot["period"] == graph_period]
        rendered = set(block["debtrank_impact"].astype(str))
        assert gs.NOT_AVAILABLE in rendered
        assert any(value not in SENTINELS and value != "NOT COMPUTED"
                   for value in rendered)
        assert not block["debtrank_impact"].isna().any()

    def test_a_group_is_named_after_a_member(self, groups):
        named = groups[groups["group_name"].astype(str) != gs.NOT_APPLICABLE]
        assert len(named) > 0
        assert named["group_name"].str.endswith(" Group").all()

    def test_every_member_of_one_group_shares_its_name_and_size(self, groups):
        real = groups[groups["connected_group_id"].astype(str)
                      != gs.NOT_APPLICABLE]
        per_group = real.groupby("connected_group_id").agg(
            names=("group_name", "nunique"),
            sizes=("connected_group_size", "nunique"))
        assert (per_group["names"] == 1).all()
        assert (per_group["sizes"] == 1).all()

    def test_group_utilisation_is_at_least_the_single_name_utilisation(
            self, groups, universe, graph_period):
        """A group contains the borrower, so its exposure cannot be less."""
        limits = universe["corporate_limits"]
        block = limits[limits["period"] == graph_period].set_index(
            "borrower_id")["single_name_utilisation_pct"]
        real = groups[groups["group_utilisation_pct"].notna()]
        for row in real.itertuples():
            single = block.get(row.borrower_id)
            if single is None or pd.isna(single):
                continue
            assert float(row.group_utilisation_pct) >= float(single) - 1e-6

    def test_the_group_limit_threshold_is_declared_unverified(self, groups):
        assert (groups["parameter_caveat"]
                .str.contains("UNVERIFIED REGULATORY PARAMETER")).all()


class TestConfidence:
    def test_the_weakest_and_the_mean_are_both_reported(self, groups):
        """They answer different questions. Showing only the mean is how one
        relationship manager's note hides behind five registry filings."""
        both = groups[groups["confidence_status"] == gs.AVAILABLE]
        assert len(both) > 0
        assert (both["graph_confidence"]
                <= both["relationship_confidence"] + 1e-9).all()
        assert (both["graph_confidence"]
                < both["relationship_confidence"]).any()

    def test_confidence_stays_within_zero_and_one(self, groups):
        for column in ("graph_confidence", "relationship_confidence"):
            values = pd.to_numeric(groups[column], errors="coerce").dropna()
            assert (values >= 0).all()
            assert (values <= 1).all()

    def test_weak_evidence_degrades_this_borrower_and_not_the_book(
            self, groups):
        """A status that reads the same for all 3,253 rows tells a reviewer
        nothing. Portfolio-wide flags stay in the DQ register."""
        statuses = groups["graph_dq_status"].value_counts()
        assert set(statuses.index) <= {gs.DQ_OK, gs.DQ_DEGRADED,
                                       gs.DQ_INSUFFICIENT}
        assert statuses.get(gs.DQ_OK, 0) > 0
        assert statuses.get(gs.DQ_DEGRADED, 0) > 0
        assert statuses.max() < len(groups)


class TestTheSnapshot:
    def test_every_graph_field_is_populated_for_a_derived_quarter(
            self, graph_snapshot, graph_period):
        block = graph_snapshot[graph_snapshot["period"] == graph_period]
        still_pending = [name for name in GRAPH_FIELDS
                         if (block[name].astype(str)
                             == snapshot_mod.NOT_COMPUTED).any()]
        assert still_pending == []

    def test_an_underived_quarter_keeps_its_sentinel(
            self, graph_snapshot, universe):
        """Never forward-filled. A borrower's group is a fact about a date,
        and carrying a later quarter's structure backwards is the same class
        of error as reading a statement before it was filed."""
        block = graph_snapshot[graph_snapshot["period"] == universe.quarters[0]]
        for name in GRAPH_FIELDS:
            assert (block[name].astype(str)
                    == snapshot_mod.NOT_COMPUTED).all(), name

    def test_the_snapshot_without_a_graph_is_unchanged(self, universe):
        """The graph argument is optional and its absence is not an error."""
        plain = snapshot_mod.assemble(universe)
        for name in GRAPH_FIELDS:
            assert (plain[name].astype(str)
                    == snapshot_mod.NOT_COMPUTED).all(), name

    def test_the_lineage_contract_still_holds_with_the_graph_joined(
            self, graph_snapshot):
        declared = [f.name for f in lineage_mod.FIELDS]
        # period, period_end_date, then the declared fields in lineage order.
        assert list(graph_snapshot.columns)[2:2 + len(declared)] == declared

    def test_group_id_comes_from_the_connected_group(
            self, graph_snapshot, groups, graph_period):
        block = graph_snapshot[graph_snapshot["period"] == graph_period]
        joined = block.set_index("borrower_id")["group_id"]
        source = groups.set_index("borrower_id")["connected_group_id"]
        assert (joined.astype(str) == source.astype(str)).all()


class TestTheLimitsFrame:
    def test_the_group_limit_is_filled_where_the_graph_ran(
            self, universe, groups, graph_period):
        """`build_limits` has written NOT YET COMPUTED since B3, because the
        group is a derived answer and the derivation did not exist."""
        updated = gs.apply_group_limits(universe.frames, groups)
        block = updated[updated["period"] == graph_period]
        assert not (block["group_utilisation_status"]
                    == "NOT YET COMPUTED").any()
        assert block["group_utilisation_pct"].notna().any()

    def test_an_underived_quarter_is_not_backfilled(self, universe, groups):
        updated = gs.apply_group_limits(universe.frames, groups)
        block = updated[updated["period"] == universe.quarters[0]]
        assert (block["group_utilisation_status"] == "NOT YET COMPUTED").all()

    def test_the_original_frame_is_not_mutated(self, universe, groups):
        before = universe["corporate_limits"][
            "group_utilisation_status"].value_counts().to_dict()
        gs.apply_group_limits(universe.frames, groups)
        after = universe["corporate_limits"][
            "group_utilisation_status"].value_counts().to_dict()
        assert before == after


class TestProvenance:
    def test_the_derivation_records_what_it_ran_and_how_long(self, groups):
        provenance = groups.attrs["provenance"]
        assert len(provenance) == 1
        entry = provenance[0]
        assert entry["quality"]["checks_run"] >= 14
        assert entry["effective_ownership"]["pipeline_version"]
        assert entry["control_closure"]["semantics"]
        assert entry["connected_groups"]["caveat"]
        assert entry["timings_seconds"]

    def test_the_caveats_travel_with_the_provenance(self, groups):
        entry = groups.attrs["provenance"][0]
        assert "NOT an expected credit loss" in entry["network"][
            "debtrank_caveat"]
        assert "NOT A PROBABILITY" in entry["network"]["label"]
        assert "not regulatory connectedness" in entry["connected_groups"][
            "caveat"]
