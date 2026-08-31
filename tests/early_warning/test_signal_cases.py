"""
§26, §27 — from a governed early-warning standing to a Risk Case.

Two things are being proved here and they are different.

The first is a *rule*: which standings deserve a case at all. That is
arithmetic over the taxonomy and it is tested without a database, on standings
built by hand, so a change to the rule shows up as a failure here rather than
as a queue that quietly doubles in size.

The second is a *review*: what happens when the rule is applied to the whole
book and the findings are written down. That needs PostgreSQL, because the
properties worth asserting - a replay updates rather than duplicates, an agent
cannot close a case, human state survives a refresh - are properties of the
database and of `agentic.cases`, not of anything this module could fake.
"""

from __future__ import annotations

import pytest

from backend.agentic import cases as rc
from backend.agentic import severity as sv
from backend.early_warning import cases as ec
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

# ------------------------------------------------------------ building blocks


def _obs(signal: str, family: str, *, severity: str = tx.CONCERN,
         lifecycle: str = sg.NEW, movement: float | None = None,
         booked: bool = False, means: str = "") -> sg.Observation:
    return sg.Observation(
        signal=signal, family=family, label=signal.replace("_", " ").title(),
        fired=True, lifecycle=lifecycle, severity=severity,
        movement=movement, booked_accounting=booked,
        means=means or f"{signal} means something a reader can check.",
        period="Q2 2026", previous_period="Q1 2026",
        dataset="corporate_borrower_360", field_name=signal, test=tx.ABOVE,
        threshold=1.0)


def _standing(*fired: sg.Observation, cured: tuple = (),
              untested: tuple = (), borrower: str = "CB-0001") -> sg.Standing:
    return sg.Standing(borrower_id=borrower, period="Q2 2026",
                       fired=list(fired), cured=list(cured),
                       untested=list(untested))


# ==================================================== §26 the materiality rule


class TestWhatDeservesACase:
    """A queue everybody works, not a queue everybody ignores."""

    def test_no_signal_is_not_a_case(self):
        reason = ec.worth_a_case(_standing())
        assert reason.raise_it is False
        assert reason.rule == "no_signal"

    def test_one_new_watch_condition_is_monitoring_not_a_finding(self):
        """The specific thing that makes a watchlist unusable.

        A single first-time WATCH condition on one borrower is visible on the
        Early Warning screen and does not open a case. If this ever starts
        raising cases, the queue grows by roughly the size of the book.
        """
        standing = _standing(_obs("rating_stale", tx.RATING,
                                  severity=tx.WATCH))
        reason = ec.worth_a_case(standing)
        assert reason.raise_it is False
        assert reason.rule == "single_watch"
        assert "monitoring, not a finding" in reason.sentence

    def test_one_severe_condition_is_enough(self):
        standing = _standing(_obs("stage_3", tx.IFRS9, severity=tx.SEVERE))
        reason = ec.worth_a_case(standing)
        assert reason.raise_it is True
        assert reason.rule == "severe"

    def test_two_independent_families_agreeing_is_enough(self):
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("utilisation_rose", tx.LIQUIDITY))
        reason = ec.worth_a_case(standing)
        assert reason.raise_it is True
        assert reason.rule == "breadth"

    def test_two_conditions_in_one_family_is_not_breadth(self):
        """The whole argument for counting families rather than signals.

        Five liquidity conditions off one utilisation number is one fact told
        five ways. Counting it as five is exactly the inflation a weighted
        score also produces, and the rule must not reintroduce it.
        """
        standing = _standing(_obs("utilisation_high", tx.LIQUIDITY),
                             _obs("utilisation_rose", tx.LIQUIDITY),
                             _obs("undrawn_thin", tx.LIQUIDITY))
        reason = ec.worth_a_case(standing)
        assert reason.raise_it is False
        assert reason.rule == "single_watch"

    def test_a_condition_still_firing_from_last_period_is_enough(self):
        standing = _standing(_obs("in_arrears", tx.BEHAVIOURAL,
                                  lifecycle=sg.PERSISTING))
        reason = ec.worth_a_case(standing)
        assert reason.raise_it is True
        assert reason.rule == "persistence"

    def test_a_booked_stage_position_is_enough(self):
        standing = _standing(_obs("stage_2", tx.IFRS9, booked=True))
        reason = ec.worth_a_case(standing)
        assert reason.raise_it is True
        assert reason.rule == "booked_stage"

    def test_the_rules_are_tried_in_the_order_a_credit_officer_would(self):
        """Severe beats breadth beats persistence beats a booked stage.

        Not cosmetic: the rule that fired is written onto the case and is what
        a reviewer sees as the reason it exists.
        """
        standing = _standing(
            _obs("stage_3", tx.IFRS9, severity=tx.SEVERE, booked=True),
            _obs("revenue_fell", tx.FINANCIAL, lifecycle=sg.PERSISTING))
        assert ec.worth_a_case(standing).rule == "severe"

    def test_every_reason_says_why_in_a_sentence(self):
        for standing in (_standing(),
                         _standing(_obs("rating_stale", tx.RATING,
                                        severity=tx.WATCH)),
                         _standing(_obs("stage_3", tx.IFRS9,
                                        severity=tx.SEVERE)),
                         _standing(_obs("revenue_fell", tx.FINANCIAL),
                                   _obs("cash_thin", tx.LIQUIDITY))):
            reason = ec.worth_a_case(standing)
            assert reason.sentence.endswith(".")
            assert len(reason.sentence) > 20


# =========================================================== §26 the case body


class TestTheCaseSaysWhereEveryFigureCameFrom:

    def test_every_metric_carries_its_dataset_field_and_threshold(self):
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("cash_thin", tx.LIQUIDITY))
        for metric in ec.metrics_of(standing):
            assert metric["dataset"] == "corporate_borrower_360"
            assert metric["field"]
            assert metric["threshold"] is not None
            assert metric["threshold_version"] == tx.TAXONOMY_VERSION
            assert metric["threshold_owner"] == tx.THRESHOLD_OWNER

    def test_the_conclusion_is_composed_not_written(self):
        """The sentence and the evidence beneath it cannot disagree.

        Both come from the same `Standing`, so there is no path by which a
        conclusion says three families and the metrics list two.
        """
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("cash_thin", tx.LIQUIDITY))
        reason = ec.worth_a_case(standing)
        conclusion = ec.conclusion_of(standing, reason)
        assert standing.sentence() in conclusion
        assert reason.sentence in conclusion
        assert "2 governed signals across 2 families" in conclusion

    def test_untested_conditions_are_named_in_the_case_not_omitted(self):
        untested = sg.Observation(signal="inventory_build",
                                  family=tx.FINANCIAL, label="Inventory build",
                                  unavailable="This book carries no inventory "
                                              "column.")
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("cash_thin", tx.LIQUIDITY),
                             untested=(untested,))
        why = ec.why_of(standing)
        assert "could not be tested" in why

    def test_a_booked_stage_is_never_described_as_a_prediction(self):
        """§20, on a surface where the wording matters most.

        A case is what somebody acts on, and 'this borrower will migrate to
        stage 2' is a different claim from 'this borrower is in stage 2'.
        """
        standing = _standing(_obs("stage_2", tx.IFRS9, booked=True),
                             _obs("cash_thin", tx.LIQUIDITY))
        why = ec.why_of(standing)
        assert "BOOKED accounting position" in why
        assert "not a prediction" in why

    def test_evidence_pointing_the_other_way_reaches_the_case(self):
        cured = _obs("revenue_fell", tx.FINANCIAL, lifecycle=sg.CURED)
        standing = _standing(_obs("cash_thin", tx.LIQUIDITY),
                             _obs("leverage_rose", tx.LEVERAGE),
                             cured=(cured,))
        assert "points the other way" in ec.why_of(standing)

    def test_the_draft_carries_the_whole_standing_as_evidence(self):
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("cash_thin", tx.LIQUIDITY))
        draft = ec.draft_for(standing, name="Acme Trading",
                             exposure=400.0, portfolio_exposure=10_000.0)
        assert draft.evidence["standing"]["breadth"] == 2
        assert draft.evidence["taxonomy_version"] == tx.TAXONOMY_VERSION
        assert draft.evidence["rule"] == "breadth"
        assert draft.level == rc.BORROWER
        assert draft.entity == "Acme Trading"
        assert draft.entity_id == "CB-0001"
        assert draft.about == ec.ABOUT

    def test_the_standing_still_carries_no_score(self):
        """§25 survives the trip through a module whose job is to score.

        The CASE has a severity band, computed by the platform's published
        formula. The STANDING it was computed from does not, and must not
        acquire one by being passed through here.
        """
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("cash_thin", tx.LIQUIDITY))
        draft = ec.draft_for(standing, exposure=400.0)
        assert "score" not in draft.evidence["standing"]
        assert draft.score is not None
        assert draft.score.version == sv.VERSION


class TestSeverityIsArithmeticNotAnOpinion:

    def test_more_families_scores_higher_than_fewer(self):
        thin = ec.score_for(_standing(_obs("revenue_fell", tx.FINANCIAL)),
                            exposure=400.0, portfolio_exposure=10_000.0)
        broad = ec.score_for(
            _standing(_obs("revenue_fell", tx.FINANCIAL),
                      _obs("cash_thin", tx.LIQUIDITY),
                      _obs("leverage_rose", tx.LEVERAGE),
                      _obs("in_arrears", tx.BEHAVIOURAL)),
            exposure=400.0, portfolio_exposure=10_000.0)
        assert broad.score > thin.score

    def test_persistence_scores_higher_than_a_first_appearance(self):
        fresh = ec.score_for(
            _standing(_obs("revenue_fell", tx.FINANCIAL),
                      _obs("cash_thin", tx.LIQUIDITY)),
            exposure=400.0, portfolio_exposure=10_000.0)
        standing = _standing(
            _obs("revenue_fell", tx.FINANCIAL, lifecycle=sg.PERSISTING),
            _obs("cash_thin", tx.LIQUIDITY, lifecycle=sg.WORSENING))
        stuck = ec.score_for(standing, exposure=400.0,
                             portfolio_exposure=10_000.0)
        assert stuck.score > fresh.score

    def test_larger_exposure_scores_higher_than_smaller(self):
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("cash_thin", tx.LIQUIDITY))
        small = ec.score_for(standing, exposure=5.0,
                             portfolio_exposure=10_000.0)
        large = ec.score_for(standing, exposure=2_000.0,
                             portfolio_exposure=10_000.0)
        assert large.score > small.score

    def test_a_thin_case_never_outranks_the_same_case_fully_evidenced(self):
        """The direction `agentic.severity` argues for, checked here.

        That module inverted this once - poor data RAISED severity, on the
        argument that a case nobody can see properly is itself worrying - and
        its evaluation corpus caught what that costs: an officer sent to the
        least established finding first. So a thin case scores at or below the
        same case fully evidenced, never above it, and the thinness is
        reported as coverage rather than smuggled into the risk.
        """
        untested = tuple(
            sg.Observation(signal=f"missing_{i}", family=tx.FINANCIAL,
                           label=f"Missing {i}", unavailable="No column.")
            for i in range(6))
        fired = (_obs("revenue_fell", tx.FINANCIAL),
                 _obs("cash_thin", tx.LIQUIDITY))
        whole = ec.draft_for(_standing(*fired), exposure=400.0)
        thin = ec.draft_for(_standing(*fired, untested=untested),
                            exposure=400.0)
        assert thin.evidence_coverage < whole.evidence_coverage
        assert thin.score.score <= whole.score.score
        assert sv.ORDER[thin.score.band] <= sv.ORDER[whole.score.band]

    def test_missing_columns_are_counted_once_not_twice(self):
        """One fact, one component.

        Thin evidence is carried by the evidence component. Feeding the same
        fact into data confidence as well drops a borrower two bands for one
        reason, and the reason a reader is shown accounts for only half of it.
        """
        untested = tuple(
            sg.Observation(signal=f"missing_{i}", family=tx.FINANCIAL,
                           label=f"Missing {i}", unavailable="No column.")
            for i in range(6))
        fired = (_obs("revenue_fell", tx.FINANCIAL),
                 _obs("cash_thin", tx.LIQUIDITY))
        thin = ec.score_for(_standing(*fired, untested=untested),
                            exposure=400.0, portfolio_exposure=10_000.0)
        confidence = thin.component(sv.DATA_CONFIDENCE)
        assert confidence is not None
        assert confidence.observed == 1.0

    def test_the_score_explains_itself(self):
        standing = _standing(_obs("revenue_fell", tx.FINANCIAL),
                             _obs("cash_thin", tx.LIQUIDITY))
        score = ec.score_for(standing, exposure=900.0,
                             portfolio_exposure=10_000.0)
        assert score.explain()
        assert score.components


# ================================================= §27 the review over the book


class TestTheReviewLooksAtEveryBorrower:
    """Reads the real synthetic book. No database needed for these."""

    def test_it_stands_up_the_whole_book_not_a_page_of_it(self):
        book = ec.standings_for()
        assert len(book["standings"]) > 1_000
        assert book["period"]
        assert book["previous_period"]
        assert book["portfolio_exposure"] > 0

    def test_a_lifecycle_needs_two_periods_and_it_has_them(self):
        book = ec.standings_for()
        assert book["previous_period"] != book["period"]
        lifecycles = {o.lifecycle for s in book["standings"] for o in s.fired}
        assert sg.PERSISTING in lifecycles or sg.WORSENING in lifecycles

    def test_the_ranking_is_total_and_stable(self):
        book = ec.standings_for()
        qualified = [s for s in book["standings"]
                     if ec.worth_a_case(s).raise_it]
        first = [s.borrower_id for s in sg.rank(qualified)]
        second = [s.borrower_id for s in sg.rank(list(reversed(qualified)))]
        assert first == second
        assert len(set(first)) == len(first)

    def test_an_unknown_period_returns_nothing_rather_than_the_latest(self):
        """Silently answering about a different quarter is the worst failure
        available here: every figure is right and every one is about the
        wrong date."""
        book = ec.standings_for("Q9 1999")
        assert book["standings"] == []

    def test_the_case_rule_leaves_a_real_share_of_the_book_uncased(self):
        """A rule that flags everything has not triaged anything.

        The assertion is deliberately loose - this is a property of the rule
        meeting a generated book, and pinning it tightly would make it a test
        of the data generator. What it must never be is 'everything'.
        """
        book = ec.standings_for()
        qualified = sum(1 for s in book["standings"]
                        if ec.worth_a_case(s).raise_it)
        assert 0 < qualified < len(book["standings"])


# --------------------------------------------------------- against a database

from tests.conftest import database_available  # noqa: E402

pg = pytest.mark.skipif(not database_available(),
                        reason="PostgreSQL is not reachable")


@pytest.fixture
def session():
    """A session that cleans up after itself and nothing else.

    Emptying `risk_cases` wholesale is the obvious thing to write here and it
    is wrong: the bootstrap leaves the Q2 2026 portfolio review's cases in
    this database, the readiness gate checks they are there, and a test that
    truncates the table breaks a different suite two files away with a failure
    that reads like a product defect. So the fixture takes the ids that
    existed before, and afterwards removes exactly the rows that did not.
    Events and links go with them by cascade.
    """
    from sqlalchemy import text

    from backend.db.engine import SessionLocal

    s = SessionLocal()
    before = {row[0] for row in
              s.execute(text("SELECT id FROM risk_cases")).all()}

    def drop_mine():
        s.rollback()
        if before:
            s.execute(text("DELETE FROM risk_cases WHERE id <> ALL(:keep)"),
                      {"keep": list(before)})
        else:
            s.execute(text("DELETE FROM risk_cases"))
        s.commit()

    drop_mine()
    try:
        yield s
    finally:
        drop_mine()
        s.close()


@pg
class TestTheReviewWritesFindings:

    def test_it_opens_cases_and_reports_what_it_did(self, session):
        outcome = ec.run(session, budget=10)
        assert outcome.evaluated > 1_000
        assert outcome.opened == 10
        assert outcome.refreshed == 0
        assert outcome.qualified > 10
        assert outcome.not_opened == outcome.qualified - 10
        assert outcome.sentence().endswith(".")

    def test_the_number_it_did_not_open_is_reported_not_hidden(self, session):
        """The classic reporting lie, refused.

        A 'top ten' assembled from the first ten rows loaded is indefensible.
        This review evaluates every borrower, ranks them all, opens the top
        ten and says how many qualified below the line.
        """
        outcome = ec.run(session, budget=10)
        assert outcome.not_opened > 0
        body = outcome.to_dict()
        assert body["not_opened"] == outcome.not_opened
        assert "below the 10-case limit" in body["sentence"]

    def test_a_replay_refreshes_and_never_duplicates(self, session):
        first = ec.run(session, budget=8)
        session.commit()
        second = ec.run(session, budget=8)
        assert second.opened == 0
        assert second.refreshed == 8
        assert sorted(second.case_ids) == sorted(first.case_ids)

    def test_a_replay_produces_the_same_cases_in_the_same_order(self, session):
        first = ec.run(session, budget=12)
        session.commit()
        second = ec.run(session, budget=12)
        assert second.case_ids == first.case_ids
        assert second.rules == first.rules
        assert second.qualified == first.qualified

    def test_a_refresh_never_undoes_a_person(self, session):
        """The specific way a proactive system becomes something people
        switch off: a review that resets what somebody triaged."""
        outcome = ec.run(session, budget=3)
        session.commit()
        case = rc.load(session, outcome.case_ids[0])
        rc.assign(session, case, owner_id=1, user_id=1, note="Mine.")
        rc.transition(session, case, rc.UNDER_REVIEW, user_id=1)
        session.commit()

        ec.run(session, budget=3)
        again = rc.load(session, outcome.case_ids[0])
        assert again.status == rc.UNDER_REVIEW
        assert again.owner_id == 1

    def test_every_case_carries_the_rule_that_raised_it(self, session):
        outcome = ec.run(session, budget=6)
        for case_id in outcome.case_ids:
            case = rc.load(session, case_id)
            assert case.evidence["rule"] in {
                "severe", "breadth", "persistence", "booked_stage"}
            assert case.evidence["rule_sentence"]
            assert case.evidence["taxonomy_version"] == tx.TAXONOMY_VERSION

    def test_every_case_is_scored_by_the_published_formula(self, session):
        outcome = ec.run(session, budget=6)
        for case_id in outcome.case_ids:
            case = rc.load(session, case_id)
            assert case.severity in {sv.CRITICAL, sv.HIGH, sv.MEDIUM, sv.LOW}
            assert case.severity_version == sv.VERSION
            assert case.severity_detail["components"]
            assert case.severity == sv.band_for(case.severity_score)

    def test_every_case_metric_points_at_a_governed_field(self, session):
        outcome = ec.run(session, budget=6)
        fields = {s.field for s in tx.SIGNALS}
        for case_id in outcome.case_ids:
            case = rc.load(session, case_id)
            assert case.metrics
            for metric in case.metrics:
                assert metric["field"] in fields
                assert metric["dataset"] == "corporate_borrower_360"

    def test_the_cases_it_opens_are_the_top_of_the_ranking(self, session):
        book = ec.standings_for()
        qualified = [s for s in book["standings"]
                     if ec.worth_a_case(s).raise_it]
        expected = [s.borrower_id for s in sg.rank(qualified)][:7]
        outcome = ec.run(session, budget=7)
        got = [rc.load(session, i).entity_id for i in outcome.case_ids]
        assert got == expected

    def test_the_review_cannot_close_a_case(self, session):
        """§38, checked at the seam rather than assumed.

        `agentic.cases.transition` refuses RESOLVED and DISMISSED to an actor
        with no user id. This asserts the early-warning review is subject to
        that refusal like anything else.
        """
        outcome = ec.run(session, budget=2)
        case = rc.load(session, outcome.case_ids[0])
        with pytest.raises(rc.NotPermitted):
            rc.transition(session, case, rc.RESOLVED,
                          actor_agent=ec.REVIEWER)
        with pytest.raises(rc.NotPermitted):
            rc.transition(session, case, rc.DISMISSED,
                          actor_agent=ec.REVIEWER)

    def test_a_cured_borrower_moves_to_monitoring_not_to_resolved(self,
                                                                  session):
        """The honest thing the review CAN say about a cured case.

        The conditions it raised the case on no longer fire. Whether the
        credit recovered is a judgement, and stays with a person.
        """
        book = ec.standings_for()
        clean = next(s for s in book["standings"] if not s.fired)
        row = book["rows"][clean.borrower_id]
        planted = _standing(_obs("revenue_fell", tx.FINANCIAL),
                            _obs("cash_thin", tx.LIQUIDITY),
                            borrower=clean.borrower_id)
        planted.period = book["period"]
        draft = ec.draft_for(planted, name=str(row.get("display_name") or ""),
                             exposure=100.0)
        case = rc.upsert(session, draft, actor_agent=ec.REVIEWER)
        session.commit()
        assert case.status == rc.NEW

        outcome = ec.run(session, budget=2)
        assert outcome.moved_to_monitoring >= 1
        again = rc.load(session, case.id)
        assert again.status == rc.MONITORING
        note = [e for e in rc.events_of(session, case.id)
                if e.to_status == rc.MONITORING][-1]
        assert "no longer" in note.body
        assert "person's decision" in note.body

    def test_the_review_does_not_touch_cases_it_did_not_raise(self, session):
        other = rc.upsert(session, rc.Draft(
            level=rc.BORROWER, title="Raised by somebody else",
            period=ec.standings_for()["period"], entity="Someone",
            entity_id="CB-NOT-OURS", about="manual",
            conclusion="A person opened this."), actor_agent="a-person")
        session.commit()
        ec.run(session, budget=2)
        again = rc.load(session, other.id)
        assert again.status == rc.NEW
        assert again.title == "Raised by somebody else"

    def test_a_case_is_reachable_by_its_borrower_and_period(self, session):
        outcome = ec.run(session, budget=4)
        case = rc.load(session, outcome.case_ids[0])
        key = rc.dedupe_key(level=rc.BORROWER, entity_id=case.entity_id,
                            period=case.period, about=ec.ABOUT)
        assert case.dedupe_key == key

    def test_the_outcome_serialises_with_its_versions(self, session):
        body = ec.run(session, budget=3).to_dict()
        assert body["review_version"] == ec.REVIEW_VERSION
        assert body["taxonomy_version"] == tx.TAXONOMY_VERSION
        assert body["signals_version"] == sg.SIGNALS_VERSION
        assert set(body["rules"]) <= {"severe", "breadth", "persistence",
                                      "booked_stage", "single_watch",
                                      "no_signal"}
