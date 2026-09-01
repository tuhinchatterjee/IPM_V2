"""
§21, §30-§33 — the four domain readers.

Every one of these tests is about a way a reading can be true and still
mislead: an absence read as reassurance, a market value read as coverage, a
stale test read as a current one, a booked classification read as a forecast,
somebody's prose read as a measurement.

The readers run against the real synthetic book, so they are also a check that
the fields they claim to read actually exist. A reader bound to a column the
catalogue does not publish is a reader that never fires, and a watchlist that
never fires looks exactly like a quiet book.
"""

from __future__ import annotations

import pytest

from backend import intelligence as base
from backend.corporate import service as corporate
from backend.intelligence import collateral, covenant, external, ifrs9
from backend.intelligence import reader as rd

READERS = (ifrs9, covenant, collateral, external)


@pytest.fixture(scope="module")
def period() -> str:
    return corporate.latest_period()


def _someone(dataset: str, period: str, key: str = "borrower_id",
             **where: object) -> str:
    frame = corporate._load(dataset)
    found = frame[frame["period"] == period]
    for column, value in where.items():
        found = found[found[column] == value]
    if found.empty:
        pytest.skip(f"no {dataset} row matches {where} at {period}")
    return str(found[key].iloc[0])


# ============================================================ the shared shape


class TestOneContractAcrossFourDomains:
    """A caller that can read one reading can read all four."""

    @pytest.mark.parametrize("module", READERS,
                             ids=[m.__name__.rsplit(".", 1)[-1]
                                  for m in READERS])
    def test_every_reader_answers_for_a_borrower_that_does_not_exist(
            self, module):
        reading = module.read("NOT-A-BORROWER")
        assert reading.findings == []
        assert reading.missing, "an absence must be reported, not implied"
        assert reading.sentence().endswith(".")

    @pytest.mark.parametrize("module", READERS,
                             ids=[m.__name__.rsplit(".", 1)[-1]
                                  for m in READERS])
    def test_an_unknown_period_is_refused_not_silently_replaced(self, module):
        """The worst failure available to a reader.

        Answering about the latest quarter when the caller asked about a
        different one produces figures that are all correct and all about the
        wrong date, which is the hardest kind of wrong to notice.
        """
        reading = module.read("CORP-100000", "Q9 1999")
        assert reading.findings == []
        assert any("not a reporting date" in m.why for m in reading.missing)

    @pytest.mark.parametrize("module", READERS,
                             ids=[m.__name__.rsplit(".", 1)[-1]
                                  for m in READERS])
    def test_no_reading_carries_a_score(self, module, period):
        who = _someone(module.DATASET, period,
                       key="customer_id" if module is external
                       else "borrower_id")
        body = module.read(who, period).to_dict()
        assert "score" not in body
        assert body["version"] == base.INTELLIGENCE_VERSION
        assert body["owner"] == base.OWNER

    @pytest.mark.parametrize("module", READERS,
                             ids=[m.__name__.rsplit(".", 1)[-1]
                                  for m in READERS])
    def test_every_finding_says_where_it_came_from(self, module, period):
        who = _someone(module.DATASET, period,
                       key="customer_id" if module is external
                       else "borrower_id")
        for finding in module.read(who, period).findings:
            assert finding.dataset == module.DATASET
            assert finding.field_name, f"{finding.key} names no field"
            assert finding.test, f"{finding.key} names no rule"
            assert finding.means.endswith("."), f"{finding.key} is not a sentence"
            assert finding.severity in base.SEVERITIES

    @pytest.mark.parametrize("module", READERS,
                             ids=[m.__name__.rsplit(".", 1)[-1]
                                  for m in READERS])
    def test_the_sentence_is_composed_from_the_findings(self, module, period):
        """The summary and the evidence under it cannot drift apart.

        A summary written alongside the evidence rather than out of it is one
        that can disagree with it, and by the time anybody notices, the number
        in the sentence is the one people quote.
        """
        who = _someone(module.DATASET, period,
                       key="customer_id" if module is external
                       else "borrower_id")
        reading = module.read(who, period)
        said = reading.sentence()
        for finding in reading.findings:
            assert finding.label in said

    @pytest.mark.parametrize("module", READERS,
                             ids=[m.__name__.rsplit(".", 1)[-1]
                                  for m in READERS])
    def test_it_reports_what_it_measured_whether_or_not_it_found_anything(
            self, module, period):
        who = _someone(module.DATASET, period,
                       key="customer_id" if module is external
                       else "borrower_id")
        reading = module.read(who, period)
        assert reading.measured, "a reading showing only faults has no context"
        assert "means" in reading.measured

    @pytest.mark.parametrize("module", READERS,
                             ids=[m.__name__.rsplit(".", 1)[-1]
                                  for m in READERS])
    def test_reading_the_same_borrower_twice_says_the_same_thing(
            self, module, period):
        who = _someone(module.DATASET, period,
                       key="customer_id" if module is external
                       else "borrower_id")
        assert module.read(who, period).to_dict() == \
               module.read(who, period).to_dict()


class TestPeriodsSortChronologicallyNotAlphabetically:
    """The defect that makes every figure right and about the wrong date."""

    def test_q4_of_one_year_sorts_before_q2_of_the_next(self):
        ordered = sorted(["Q4 2025", "Q2 2026", "Q1 2026"], key=rd.period_key)
        assert ordered == ["Q4 2025", "Q1 2026", "Q2 2026"]
        # The failure it prevents: a plain string sort.
        assert sorted(["Q4 2025", "Q2 2026"]) != ordered[:2]

    def test_the_prior_period_is_the_one_immediately_before(self, period):
        frame = corporate._load(ifrs9.DATASET)
        chosen, prior = rd.resolve(frame, period)
        assert chosen == period
        periods = rd.periods_of(frame)
        assert prior == periods[periods.index(chosen) - 1]

    def test_the_earliest_period_has_no_prior_rather_than_a_wrong_one(self):
        frame = corporate._load(ifrs9.DATASET)
        first = rd.periods_of(frame)[0]
        assert rd.resolve(frame, first) == (first, "")


# ==================================================================== §30 IFRS 9


class TestIFRS9IsTheBookedPositionNotAForecast:

    def test_every_stage_finding_is_flagged_as_booked(self, period):
        who = _someone(ifrs9.DATASET, period, stage=2)
        reading = ifrs9.read(who, period)
        staged = [f for f in reading.findings if f.key.startswith("stage")]
        assert staged
        assert all(f.booked_accounting for f in staged)

    def test_the_wording_says_booked_and_not_predicted(self, period):
        who = _someone(ifrs9.DATASET, period, stage=2)
        reading = ifrs9.read(who, period)
        said = " ".join(f.means for f in reading.findings).lower()
        assert "not a prediction" in said or "has happened" in said
        assert "will move" not in said
        assert "likely to migrate" not in said

    def test_a_sicr_flag_is_reported_with_the_trigger_that_set_it(self,
                                                                  period):
        """A conclusion with the argument removed is not an explanation.

        The three triggers lead to three different conversations: a PD
        trigger is a model view, days past due is a fact about payments, and
        a watchlist trigger is somebody's judgement.
        """
        who = _someone(ifrs9.DATASET, period, sicr_flag=True,
                       sicr_trigger_dpd=True)
        keys = {f.key for f in ifrs9.read(who, period).findings}
        assert keys & {"sicr_trigger_pd", "sicr_trigger_dpd",
                       "sicr_trigger_watchlist", "sicr_unexplained"}

    def test_an_improvement_is_named_as_well_as_a_deterioration(self, period):
        frame = corporate._load(ifrs9.DATASET)
        now = frame[(frame["period"] == period) & (frame["stage"] == 1)
                    & (frame["prior_stage"] > 1)]
        if now.empty:
            pytest.skip("no borrower improved into stage 1 at this period")
        who = str(now["borrower_id"].iloc[0])
        keys = {f.key for f in ifrs9.read(who, period).findings}
        assert "stage_improved" in keys

    def test_any_management_overlay_is_named(self, period):
        """How much of a number is modelled and how much is decided.

        Named at any size, because that is the question, and escalated when
        it is material.
        """
        frame = corporate._load(ifrs9.DATASET)
        now = frame[(frame["period"] == period)
                    & (frame["management_overlay"] > 0)
                    & (frame["final_ecl"] > 0)]
        assert not now.empty, "this book carries overlays; the reader must see them"
        who = str(now["borrower_id"].iloc[0])
        found = [f for f in ifrs9.read(who, period).findings
                 if f.key.startswith("overlay_")]
        assert found
        assert "judgement" in found[0].means

    def test_the_overlay_threshold_is_one_this_book_can_reach(self, period):
        """A rule that can never fire reads exactly like a clean book.

        The threshold was originally set at a fifth of final ECL; this
        generator caps overlays just under that, so it never fired once
        across three thousand borrowers. The assertion is on the DATA rather
        than on the constant, so moving the constant back would fail here.
        """
        frame = corporate._load(ifrs9.DATASET)
        now = frame[(frame["period"] == period)
                    & (frame["management_overlay"] > 0)
                    & (frame["final_ecl"] > 0)]
        shares = now["management_overlay"] / now["final_ecl"]
        assert (shares >= ifrs9.MATERIAL_OVERLAY_SHARE).any(), (
            "no borrower on this book can reach the materiality threshold, "
            "so the finding can never fire")

    def test_the_measured_figures_name_which_is_booked(self, period):
        who = _someone(ifrs9.DATASET, period, stage=1)
        measured = ifrs9.read(who, period).measured
        assert "BOOKED" in measured["means"]["stage"]
        assert "Not a forecast" in measured["means"]["stage"]


# ================================================================ §32 covenants


class TestCovenantsAreReadOneAtATime:

    def test_each_covenant_is_named_rather_than_collapsed(self, period):
        who = _someone(covenant.DATASET, period, breach_flag=True)
        reading = covenant.read(who, period)
        assert reading.measured["covenants_on_file"] >= 1
        assert reading.measured["names"]
        # A borrower's covenant position is not one number.
        assert "minimum_headroom_pct" in reading.measured
        assert "average_headroom_pct" in reading.measured

    def test_the_minimum_is_explained_as_not_being_an_average(self, period):
        who = _someone(covenant.DATASET, period, breach_flag=True)
        means = covenant.read(who, period).measured["means"]
        assert "not an average" in means["minimum_headroom_pct"]

    def test_a_breach_is_severe_and_a_waived_breach_is_not_hidden(self,
                                                                  period):
        who = _someone(covenant.DATASET, period, breach_flag=True)
        breaches = [f for f in covenant.read(who, period).findings
                    if f.key.startswith("breach_")]
        assert breaches
        for finding in breaches:
            assert finding.severity in (base.SEVERE, base.CONCERN)
            if "waived" in finding.label:
                assert "removes the consequence, not the fact" in finding.means

    def test_headroom_measured_on_stale_statements_is_flagged(self, period):
        frame = corporate._load(covenant.DATASET)
        now = frame[(frame["period"] == period)
                    & (frame["statement_age_days"] > 365)]
        if now.empty:
            pytest.skip("no covenant is tested on statements over a year old")
        who = str(now["borrower_id"].iloc[0])
        found = [f for f in covenant.read(who, period).findings
                 if f.key == "tested_on_old_statements"]
        assert found, "comfortable headroom on stale accounts is not headroom"
        assert "historical" in found[0].means

    def test_no_covenant_on_file_is_not_reported_as_compliance(self):
        reading = covenant.read("NOT-A-BORROWER")
        assert reading.findings == []
        why = " ".join(m.why for m in reading.missing)
        assert "not that every promise is being kept" in why


# =============================================================== §33 collateral


class TestCollateralNeverConfusesTheTwoValues:

    def test_both_values_are_reported_and_named(self, period):
        who = _someone(collateral.DATASET, period)
        measured = collateral.read(who, period).measured
        assert measured["market_value"] >= measured["eligible_value"]
        assert "NOT what they are worth" in measured["means"]["market_value"]
        assert "covers exposure" in measured["means"]["eligible_value"]
        assert measured["haircut_removed"] == pytest.approx(
            measured["market_value"] - measured["eligible_value"], abs=0.01)

    def test_an_overdue_valuation_is_measured_against_its_own_policy(self,
                                                                     period):
        who = _someone(collateral.DATASET, period, valuation_overdue=True)
        found = [f for f in collateral.read(who, period).findings
                 if f.key == "valuations_overdue"]
        assert found
        assert "its own revaluation policy" in found[0].means
        assert "not one global rule" in found[0].means

    def test_a_stale_value_is_said_not_to_be_a_value(self, period):
        who = _someone(collateral.DATASET, period, valuation_overdue=True)
        said = " ".join(f.means for f in collateral.read(who, period).findings)
        assert "stale value is not a value" in said

    def test_no_collateral_on_file_is_not_reported_as_unsecured(self):
        """Two different facts that a screen showing only findings conflates.

        The dataset cannot tell an unsecured exposure from one whose security
        was never loaded, so the reading says so rather than picking.
        """
        why = " ".join(m.why for m in collateral.read("NOT-A-BORROWER").missing)
        assert "may be unsecured, or the security may simply not be on file" \
               in why

    def test_security_concentrated_in_one_asset_type_is_named(self, period):
        frame = corporate._load(collateral.DATASET)
        now = frame[frame["period"] == period]
        counts = now.groupby("borrower_id")["collateral_type"].nunique()
        single = counts[counts == 1].index
        rows = now[now["borrower_id"].isin(single)]
        many = rows.groupby("borrower_id").size()
        many = many[many >= 2]
        if many.empty:
            pytest.skip("no borrower holds two charges over one asset type")
        who = str(many.index[0])
        found = [f for f in collateral.read(who, period).findings
                 if f.key == "collateral_concentrated"]
        assert found
        assert "one bet, not several" in found[0].means


# ==================================================== §21/§31 external evidence


class TestExternalIntelligenceIsEvidenceNotAConclusion:

    def test_each_concern_is_named_rather_than_summed(self, period):
        who = _someone(external.DATASET, period, key="customer_id",
                       sentiment="negative")
        keys = {f.key for f in external.read(who, period).findings}
        assert keys & {name for name, _, _, _ in external.CONCERNS}

    def test_going_concern_is_the_most_serious_and_is_never_inferred(self,
                                                                     period):
        who = _someone(external.DATASET, period, key="customer_id",
                       going_concern_mentioned=True)
        found = [f for f in external.read(who, period).findings
                 if f.key == "going_concern_mentioned"]
        assert found
        assert found[0].severity == base.SEVERE
        assert "never inferred" in found[0].means

    def test_sentiment_is_reported_as_something_written_not_measured(self,
                                                                     period):
        who = _someone(external.DATASET, period, key="customer_id",
                       sentiment="negative")
        found = [f for f in external.read(who, period).findings
                 if f.key == "adverse_sentiment"]
        assert found
        assert "not a measurement of the borrower" in found[0].means

    def test_no_memo_is_not_read_as_a_quiet_borrower(self):
        why = " ".join(m.why for m in external.read("NOT-A-BORROWER").missing)
        assert "Nothing follows from that" in why
        assert "unattended" in why

    def test_the_text_is_quoted_and_labelled_as_quoted(self, period):
        who = _someone(external.DATASET, period, key="customer_id",
                       sentiment="negative")
        found = external.extracts(who, period)
        assert found
        for memo in found:
            assert memo["quoted_verbatim"] is True
            assert memo["extract"]
            assert memo["author_role"]

    def test_extracts_are_not_findings(self, period):
        """A finding is a claim this product makes; an extract is one somebody
        else made. Mixing them is how a paraphrase gets attributed."""
        who = _someone(external.DATASET, period, key="customer_id",
                       sentiment="negative")
        reading = external.read(who, period)
        text = " ".join(external.extracts(who, period)[0]["extract"]
                        .split())
        for finding in reading.findings:
            assert finding.means not in text

    def test_a_memo_breach_and_a_covenant_breach_are_kept_separate(self,
                                                                   period):
        """Two sources disagreeing is itself worth knowing."""
        who = _someone(external.DATASET, period, key="customer_id",
                       covenant_breach_mentioned=True)
        found = [f for f in external.read(who, period).findings
                 if f.key == "covenant_breach_mentioned"]
        assert found
        assert "separate question" in found[0].means
