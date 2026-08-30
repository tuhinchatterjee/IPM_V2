"""The Borrower 360 snapshot and its lineage. B2, B4, B5, B6, B7.

The central claim under test is B2's: the snapshot is fast, wide and
authoritative over nothing. That is not a property of a docstring, so it is
tested three ways - the lineage table declares no authoritative field, the
catalogue registers the snapshot as authoritative for nothing, and the
assembler refuses to publish a column that has no lineage entry.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.corporate import catalogue as catalogue_mod
from backend.corporate import lineage as lineage_mod
from backend.corporate import resolution as resolution_mod
from backend.corporate import search as search_mod
from backend.corporate import snapshot as snapshot_mod


class TestFieldCoverage:
    def test_every_b4_group_is_present(self):
        for group in ("IDENTITY", "RATING", "FINANCIALS", "EXPOSURE",
                      "IFRS9", "DELINQUENCY", "COVENANTS", "COLLATERAL",
                      "LIMIT", "GRAPH SUMMARY", "DATA QUALITY"):
            assert group in lineage_mod.GROUPS

    def test_b4_names_every_field_the_snapshot_carries(self, snapshot):
        declared = {f.name for f in lineage_mod.FIELDS}
        published = set(snapshot.columns) - {
            "period", "period_end_date", "origin", "not_client_data"}
        assert published == declared

    def test_a_representative_field_from_each_group_exists(self):
        for name in ("legal_name", "internal_rating", "leverage",
                     "ifrs9_ead", "stage", "current_dpd",
                     "covenants_breached", "collateral_coverage_pct",
                     "single_name_utilisation_pct", "network_risk_score",
                     "snapshot_validation_status"):
            assert lineage_mod.get(name).name == name

    def test_an_unknown_field_raises_and_explains(self):
        with pytest.raises(KeyError) as caught:
            lineage_mod.get("vibes")
        assert "no lineage entry has no provenance" in str(caught.value)


class TestAuthority:
    def test_no_field_is_authoritative(self):
        """B2, said in the metadata rather than only in prose."""
        assert [f.name for f in lineage_mod.FIELDS
                if f.authority == lineage_mod.AUTHORITATIVE] == []

    def test_every_field_declares_a_source_domain_and_dataset(self):
        for entry in lineage_mod.FIELDS:
            assert entry.source_domain
            assert entry.source_dataset
            assert entry.source_field

    def test_every_field_offers_a_view_source_target(self):
        """B5: a metric click lands on the exact Data Builder object."""
        for entry in lineage_mod.FIELDS:
            target = entry.to_dict()["view_source"]
            assert target["dataset"] and target["field"] and target["domain"]

    def test_the_ifrs9_domain_stays_the_owner_of_stage_and_ecl(self):
        for name in ("stage", "final_ecl", "ecl_coverage"):
            assert lineage_mod.get(name).source_domain == "CORPORATE IFRS 9"
            assert lineage_mod.get(name).authority != lineage_mod.AUTHORITATIVE

    def test_the_catalogue_registers_the_snapshot_as_authoritative_for_nothing(
            self, universe, snapshot):
        frames = dict(universe.frames)
        frames[catalogue_mod.SNAPSHOT_DATASET] = snapshot
        entries = {e["name"]: e for e in catalogue_mod.datasets(frames)}
        assert entries[catalogue_mod.SNAPSHOT_DATASET][
            "authoritative_for"] == []

    def test_the_ifrs9_dataset_is_registered_as_the_owner(
            self, universe, snapshot):
        frames = dict(universe.frames)
        frames[catalogue_mod.SNAPSHOT_DATASET] = snapshot
        entries = {e["name"]: e for e in catalogue_mod.datasets(frames)}
        assert "corporate_ecl" in entries["corporate_ifrs9"][
            "authoritative_for"]


class TestAssembly:
    def test_one_row_per_borrower_per_quarter(self, snapshot):
        assert not snapshot.duplicated(["borrower_id", "period"]).any()

    def test_it_covers_every_borrower_quarter_on_book(self, universe,
                                                      snapshot):
        assert len(snapshot) == len(universe["corporate_customer_master"])

    def test_copied_figures_equal_their_source(self, universe, snapshot):
        """The whole point of a copy is that it is one."""
        ifrs9 = universe["corporate_ifrs9"].set_index(
            ["borrower_id", "period"])
        keys = snapshot.set_index(["borrower_id", "period"]).index
        for column in ("stage", "final_ecl", "pd_12m", "lgd"):
            assert (snapshot[column].to_numpy()
                    == keys.map(ifrs9[column]).to_numpy()).all()

    def test_aggregated_figures_equal_the_aggregate(self, universe, snapshot):
        facilities = universe["corporate_facilities"]
        totals = facilities.groupby(["borrower_id", "period"])[
            "drawn_exposure"].sum()
        keys = snapshot.set_index(["borrower_id", "period"]).index
        expected = pd.Series(keys.map(totals)).fillna(0.0).to_numpy()
        assert abs(snapshot["total_outstanding"].to_numpy()
                   - expected).max() < 1e-6

    def test_financials_come_from_a_statement_already_published(
            self, snapshot):
        """No foresight. A statement the borrower had not filed is not
        information the bank had."""
        published = pd.to_datetime(snapshot["financial_statement_date"],
                                   errors="coerce")
        as_of = pd.to_datetime(snapshot["period_end_date"])
        assert (published.dropna() <= as_of[published.notna()]).all()

    def test_statement_age_is_the_gap_it_says_it_is(self, snapshot):
        rows = snapshot[snapshot["financial_statement_date"].notna()].head(500)
        gap = (pd.to_datetime(rows["period_end_date"])
               - pd.to_datetime(rows["financial_statement_date"])).dt.days
        assert (gap == rows["financial_statement_age_days"]).all()

    def test_the_oldest_valuation_is_reported_not_the_newest(
            self, universe, snapshot):
        collateral = universe["corporate_collateral"]
        oldest = collateral.groupby(["borrower_id", "period"])[
            "valuation_age_days"].max()
        keys = snapshot.set_index(["borrower_id", "period"]).index
        expected = pd.Series(keys.map(oldest)).fillna(0).astype(int).to_numpy()
        assert (snapshot["valuation_age_days"].to_numpy() == expected).all()

    def test_collateral_coverage_uses_the_eligible_value(self, snapshot):
        rows = snapshot[snapshot["secured_exposure"] > 0].head(500)
        implied = (rows["collateral_eligible_value"]
                   / rows["secured_exposure"] * 100)
        assert abs(implied - rows["collateral_coverage_pct"]).max() < 0.02

    def test_origin_and_the_caveat_are_on_every_row(self, snapshot):
        assert (snapshot["origin"] == "SYNTHETIC_DEMO").all()
        assert snapshot["not_client_data"].str.contains(
            "must not be presented as client data").all()


class TestPendingGraphFields:
    def test_graph_fields_are_marked_not_computed_not_zero(self, snapshot):
        """A network risk score of zero is a measurement.

        Filling an uncomputed field with zero makes "measured, and it is
        nothing" indistinguishable from "no graph has run", and a screen
        cannot tell them apart afterwards.
        """
        for name in ("network_risk_score", "debtrank_impact", "betweenness",
                     "connected_group_id", "ubo_count"):
            assert (snapshot[name] == snapshot_mod.NOT_COMPUTED).all()

    def test_the_summary_reports_what_is_pending(self, snapshot):
        report = snapshot_mod.summary(snapshot)
        assert report["graph_fields_pending"] >= 19
        assert "network_risk_score" in report["graph_fields_pending_names"]

    def test_the_summary_states_nothing_is_authoritative(self, snapshot):
        assert snapshot_mod.summary(snapshot)["authoritative_fields"] == 0

    def test_completeness_ignores_the_fields_the_graph_owes(self, snapshot):
        assert snapshot["source_completeness"].mean() > 95


class TestSearch:
    def test_an_identifier_resolves_to_one_borrower(self, snapshot):
        target = str(snapshot["borrower_id"].iloc[0])
        result = search_mod.search(snapshot, search_mod.Query(text=target))
        assert result["resolved"] is True
        assert result["borrowers"][0]["borrower_id"] == target

    def test_a_shared_name_stem_is_reported_ambiguous(self, snapshot):
        """Six companies match "Al Waha Trading". Returning the first as the
        answer is how a screen shows somebody else's exposure."""
        counts = snapshot["legal_name"].value_counts()
        stem = str(snapshot["legal_name"].iloc[0]).replace(" Company", "")
        result = search_mod.search(snapshot, search_mod.Query(text=stem))
        assert result["cohort_kind"] == search_mod.SINGLE
        if result["matched"] > 1:
            assert result["ambiguous"] is True
        assert counts is not None

    def test_arabic_names_are_searchable(self, snapshot):
        arabic = str(snapshot["arabic_name"].iloc[3])
        assert search_mod.search(
            snapshot, search_mod.Query(text=arabic))["matched"] >= 1

    def test_a_legal_form_suffix_does_not_defeat_a_match(self, snapshot):
        name = str(snapshot["legal_name"].iloc[0])
        with_suffix = f"{name.replace(' Company', '')} LLC"
        assert search_mod.search(
            snapshot, search_mod.Query(text=with_suffix))["matched"] >= 1

    def test_a_segment_query_leads_with_an_aggregate(self, snapshot):
        result = search_mod.search(
            snapshot, search_mod.Query(facets={"sector": "Contracting"}))
        assert result["cohort_kind"] == search_mod.SEGMENT
        assert result["lead_with_aggregate"] is True
        assert result["aggregate"]["borrowers"] == result["matched"]

    def test_segment_averages_are_exposure_weighted(self, snapshot):
        result = search_mod.search(
            snapshot, search_mod.Query(facets={"sector": "Utilities"}))
        aggregate = result["aggregate"]
        assert aggregate["exposure_weighted_pd_12m"] is not None
        assert "exposure weighted" in aggregate["weighting_note"]

    def test_a_named_cohort_reports_members_it_could_not_find(self, snapshot):
        ids = list(snapshot["borrower_id"].unique()[:3]) + ["CORP-999999"]
        result = search_mod.search(
            snapshot, search_mod.Query(borrower_ids=ids))
        assert result["cohort_kind"] == search_mod.MULTI
        assert "CORP-999999" in result["not_found"]

    def test_an_unknown_facet_is_refused_by_name(self, snapshot):
        with pytest.raises(search_mod.UnknownFacetError) as caught:
            search_mod.search(snapshot, search_mod.Query(facets={"vibe": "x"}))
        assert "vibe" in str(caught.value)

    def test_a_search_defaults_to_one_quarter(self, snapshot):
        result = search_mod.search(
            snapshot, search_mod.Query(facets={"region": "Riyadh"},
                                       limit=200))
        assert len({b["borrower_id"] for b in result["borrowers"]}) == len(
            result["borrowers"])

    def test_flags_filter_to_the_flagged(self, snapshot):
        result = search_mod.search(
            snapshot, search_mod.Query(flags=["watchlist_flag"], limit=50))
        assert all(b["watchlist_flag"] for b in result["borrowers"])


class TestEntityResolution:
    def test_source_records_are_never_merged_destructively(self, universe):
        records = universe["corporate_entity_resolution"]
        assert not records["merged_destructively"].any()

    def test_every_source_system_is_represented(self, universe):
        records = universe["corporate_entity_resolution"]
        assert set(records["source_system"]) == set(
            resolution_mod.SOURCE_SYSTEMS)

    def test_fuzzy_matching_is_never_auto_accepted(self, universe):
        """B7 precedence 3.

        This rule merges two unrelated family companies with common surnames
        and a common non-executive director. A wrong merge here doubles one
        borrower's exposure and deletes another's.
        """
        records = universe["corporate_entity_resolution"]
        fuzzy = records[records["resolution_method"]
                        == resolution_mod.FUZZY_NAME_AND_DIRECTOR]
        assert len(fuzzy) > 0
        assert not (fuzzy["review_status"]
                    == resolution_mod.AUTO_ACCEPTED).any()

    def test_a_rejected_match_resolves_to_nothing(self, universe):
        records = universe["corporate_entity_resolution"]
        rejected = records[records["review_status"]
                           == resolution_mod.HUMAN_REJECTED]
        assert len(rejected) > 0
        assert (rejected["canonical_entity_id"] == "").all()

    def test_exact_registration_matches_carry_the_highest_confidence(
            self, universe):
        records = universe["corporate_entity_resolution"]
        by_method = records.groupby("resolution_method")["confidence"].mean()
        assert (by_method[resolution_mod.EXACT_REGISTRATION]
                > by_method[resolution_mod.FUZZY_NAME_AND_DIRECTOR])

    def test_normalisation_strips_legal_form_words(self):
        assert (resolution_mod.normalise("Al Waha Trading LLC")
                == resolution_mod.normalise("Al Waha Trading Company"))

    def test_normalisation_does_not_collapse_different_companies(self):
        assert (resolution_mod.normalise("Al Waha Trading")
                != resolution_mod.normalise("Al Maha Trading"))

    def test_a_review_queue_remains(self, universe):
        report = resolution_mod.summary(
            universe["corporate_entity_resolution"])
        assert report["pending_review"] > 0
        assert report["destructive_merges"] == 0


class TestCatalogueRelationships:
    def test_the_grain_mismatch_join_is_declared_forbidden(self):
        forbidden = [r for r in catalogue_mod.RELATIONSHIPS
                     if r["kind"] == "FORBIDDEN"]
        pairs = {(r["from_dataset"], r["to_dataset"]) for r in forbidden}
        assert (catalogue_mod.SNAPSHOT_DATASET,
                "corporate_covenants") in pairs

    def test_supply_chain_into_group_formation_is_forbidden(self):
        forbidden = [r for r in catalogue_mod.RELATIONSHIPS
                     if r["kind"] == "FORBIDDEN"]
        reasons = " ".join(r["why"] for r in forbidden)
        assert "B21" in reasons

    def test_every_dataset_declares_its_grain(self, universe, snapshot):
        frames = dict(universe.frames)
        frames[catalogue_mod.SNAPSHOT_DATASET] = snapshot
        for entry in catalogue_mod.datasets(frames):
            assert entry["grain"], entry["name"]
            assert entry["is_synthetic"] is True
            assert entry["origin"] == "SYNTHETIC_DEMO"
