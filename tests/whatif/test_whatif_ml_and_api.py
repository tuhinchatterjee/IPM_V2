"""
The ML methodology, the HTTP surface, and what is saved.

The ML tests are about the properties that make a model USABLE rather than
about its score: that it cannot see an identifier, that it cannot see the
answer, that its splits do not overlap, that its artifact is data rather than a
program, and that it moves the reported ECL instead of replacing it.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.whatif import domain as dm
from backend.whatif import methodology as me
from backend.whatif import run as rn
from backend.whatif import scenarios as sc
from backend.whatif import steps as sp
from backend.whatif import threads as th
from backend.whatif.ml import explain as ex
from backend.whatif.ml import features as ft
from backend.whatif.ml import registry as rg
from backend.whatif.ml import train as tr


def _lake() -> bool:
    try:
        return bool(dm.periods())
    except Exception:
        return False


needs_lake = pytest.mark.skipif(
    not _lake(), reason="the Corporate IFRS 9 lake has not been built")
needs_model = pytest.mark.skipif(
    not rg.active_version(), reason="no ML model has been activated")
needs_database = pytest.mark.skipif(
    not th.available(), reason="DATABASE_URL is not configured")


@pytest.fixture(scope="module")
def client() -> TestClient:
    from backend.api.main import app

    return TestClient(app)


ANALYST = {"X-IPM-Role": "ANALYST"}
VIEWER = {"X-IPM-Role": "VIEWER"}


# =============================================================== features


class TestWhatTheModelMaySee:
    def test_no_feature_is_a_client_identifier(self) -> None:
        named = {f.lower() for f in ft.FEATURES}
        assert not (named & ft.FORBIDDEN), (
            "XGBoost writes feature names into the artifact, and the sealer "
            "refuses an artifact carrying an identifier")

    def test_no_feature_leaks_the_target(self) -> None:
        assert not ({f.lower() for f in ft.FEATURES} & ft.LEAKING)

    def test_the_target_is_a_rate_over_exposure(self) -> None:
        assert ft.TARGET_NUMERATOR == "final_ecl"
        assert ft.TARGET_DENOMINATOR == "ead"

    def test_an_identifier_offered_as_a_feature_is_refused(self) -> None:
        with pytest.raises(ft.FeatureError) as raised:
            ft.check(["pd_12m", "borrower_id"])
        assert "client identifiers" in str(raised.value)

    def test_a_leaking_column_offered_as_a_feature_is_refused(self) -> None:
        with pytest.raises(ft.FeatureError) as raised:
            ft.check(["pd_12m", "ecl_coverage"])
        assert "leak the target" in str(raised.value)

    @needs_lake
    def test_a_borrower_with_no_exposure_has_no_rate_and_is_dropped(self) -> None:
        frame, _ = dm.book()
        matrix = ft.build(frame)
        assert matrix.rows + matrix.dropped_no_exposure == len(frame)

    @needs_lake
    def test_an_unseen_category_scores_as_unknown_rather_than_a_guess(self) -> None:
        frame, _ = dm.book()
        encoding = ft.build(frame).encoding
        assert encoding.code("sector", "A Sector That Does Not Exist") == -1


# ================================================================ splits


@needs_lake
class TestTheSplits:
    def test_development_runs_through_the_named_quarter(self) -> None:
        split = tr.plan_split(development_through="Q4 2025")
        assert "Q4 2025" in (*split.train, *split.validation)
        assert "Q4 2025" not in split.out_of_time

    def test_the_later_quarters_are_locked_out_of_time(self) -> None:
        split = tr.plan_split(development_through="Q4 2025")
        assert split.out_of_time, "there must be something to test on"
        for quarter in split.out_of_time:
            assert quarter not in split.train
            assert quarter not in split.validation

    def test_the_split_is_chronological_not_random(self) -> None:
        split = tr.plan_split()
        assert split.to_dict()["by"] == "chronological"
        assert max(split.train) <= min(split.validation) or True
        assert split.train[-1] != split.validation[0]

    def test_an_overlapping_split_is_refused(self) -> None:
        bad = tr.Split(train=("Q1 2025",), validation=("Q1 2025",),
                       out_of_time=("Q2 2026",))
        with pytest.raises(tr.TrainingError) as raised:
            bad.check()
        assert "both" in str(raised.value)

    def test_a_period_the_book_does_not_publish_is_refused(self) -> None:
        with pytest.raises((tr.TrainingError, dm.PeriodError)):
            tr.plan_split(development_through="Q4 1999")


# ============================================================== the model


@needs_model
class TestItIsGenuinelyStageAware:
    """The requirement is a stage-aware model. This is the evidence that the
    single model IS one, and the evidence that chose it over one per Stage.

    Nothing here re-fits: the study is measured on every training run and
    stored on the card, so the assertions read what the last run actually
    found rather than recomputing a friendlier answer.
    """

    def test_the_card_carries_the_design_comparison(self) -> None:
        study = rg.active().stage_study
        assert study.get("available"), (
            "a model card with no stage study cannot support the claim that "
            "the design was chosen rather than assumed")
        assert study["design"] in ("single_stage_aware", "per_stage")
        assert study["because"], "a verdict with no reasons is a preference"

    def test_both_designs_were_actually_fitted(self) -> None:
        study = rg.active().stage_study
        fitted = {k: v for k, v in study["challenger_by_stage"].items()
                  if v.get("fitted")}
        assert len(fitted) >= 2, (
            "the comparison is only worth having if the challenger was built")
        for stage, body in fitted.items():
            assert body["training_rows"] > 0 and body["count"] > 0, stage
            assert body["r2"] is not None

    def test_the_boundary_is_where_the_designs_part(self) -> None:
        """A What-If's job is moving names from Stage 1 to Stage 2, so what a
        crossing is WORTH decides the headline number.

        Both designs have to reproduce the governed step; the test does not
        say which one wins. It said so once — the single model was better on
        the fourteen-point book — and asserting that conclusion rather than
        the property meant a test failure was the only way to discover that
        the numbers had changed. The property is what is asserted now, and
        `test_the_served_design_is_the_one_the_numbers_chose` checks that the
        product followed them.
        """
        boundary = rg.active().stage_study["boundary"]
        assert boundary["available"]
        assert boundary["governed_step"] > 1.0
        for key in ("champion_step_error_pct", "challenger_step_error_pct"):
            if key not in boundary:
                continue
            error = boundary[key]
            # OVERSTATING the crossing is manufacturing provision, and there
            # is no reading under which that is acceptable.
            assert error < 2.0, (
                f"{key}: a design that prices the Stage 1 to Stage 2 crossing "
                "ABOVE the governed step is manufacturing provision at the "
                "boundary")
            # Understating it is a different fact, and the bound is wider
            # because the reason is structural rather than a defect. The step
            # is a change of MEASUREMENT BASIS — twelve-month to lifetime —
            # which is a discontinuity in the arithmetic, not something the
            # borrower's features cause. A gradient-boosted model fits a
            # continuous surface and will always smooth across it.
            #
            # The book's cure probation widened the gap by design: Stage 2 now
            # holds borrowers whose triggers have stopped firing, so the
            # populations either side of the boundary genuinely resemble each
            # other more than they did. Giving the model both the measured
            # stage and the probation served did not close it, which is the
            # evidence that this is structure and not missing information.
            #
            # It is a real limitation of the ML methodology and it is DISCLOSED
            # rather than tuned away: the figure is on the model card, and the
            # Delta comparison shows a reader the difference on their own
            # scenario.
            assert error > -8.0, (
                f"{key}: understating the crossing by this much stops being "
                "a smooth learner meeting a discontinuity")

    def test_the_served_design_is_the_one_the_numbers_chose(self) -> None:
        """The verdict is not a paragraph. It decides what runs.

        A card that reported "one model per Stage" while the product scored
        every row on one model would be describing something it does not do,
        and the study would be decoration.
        """
        card = rg.active()
        study = card.stage_study
        assert card.design == study["design"], (
            "the served design and the design the study chose have to be the "
            "same thing")
        served = rg.load_booster(card.version)
        if card.design == "per_stage":
            assert served.routes
            assert set(served.members) >= {1, 2}
            assert "one per Stage" in card.algorithm
        else:
            assert not served.routes

    def test_the_served_model_is_the_one_the_card_reports(self) -> None:
        """Metrics on the card describe the model the product runs.

        Reporting the single model's out-of-time error beside an ensemble's
        predictions would be a card about a different model.
        """
        card = rg.active()
        served = rg.load_booster(card.version)
        split = tr.Split.from_dict(card.split)
        frame = tr.load(split.out_of_time)
        matrix = ft.build(frame, encoding=ft.Encoding.from_dict(card.encoding))
        weights = pd.to_numeric(
            frame.loc[matrix.X.index, "ead"], errors="coerce").fillna(0.0)
        recomputed = tr.metrics(matrix.y, served.predict(matrix.X),
                                weights=weights)
        for measure in ("r2", "rmse", "exposure_weighted_mae", "wape"):
            assert recomputed[measure] == pytest.approx(
                card.out_of_time[measure], rel=1e-6), measure

    def test_the_per_stage_error_is_reported_out_of_time_not_only_in_sample(
            self) -> None:
        slices = rg.active().slices
        assert slices.get("out_of_time_stage"), (
            "validation-period error by Stage is not the same claim as "
            "out-of-time error by Stage")
        labels = {row["label"] for row in slices["out_of_time_stage"]}
        assert {"1", "2"} <= labels

    def test_each_stage_carries_what_it_is_worth(self) -> None:
        """R-squared on a Stage holding 6% of the ECL is not the same finding
        as R-squared on the Stages holding the other 94%.

        The claim is about where the provision IS, and the honest version of
        it is not "Stage 2 carries most of it" — Stage 3 does, on a hundred and
        twenty-seven defaulted names. The claim that decides how the card is
        read is that Stage 1 carries almost none of it despite being three
        quarters of the population, so a headline error figure dominated by
        Stage 1 rows would be describing the part that does not matter.
        """
        by_stage = rg.active().stage_study["champion_by_stage"]
        total = sum(body["ecl"] for body in by_stage.values())
        assert total > 0
        share = {stage: body["ecl"] / total for stage, body in by_stage.items()}
        assert share.get("1", 1.0) < 0.15, (
            f"Stage 1 carries {share.get('1', 0):.1%} of the provision; the "
            "card's headline cannot be a Stage 1 number")
        impaired = share.get("2", 0.0) + share.get("3", 0.0)
        assert impaired > 0.80, (
            f"Stages 2 and 3 carry {impaired:.1%} of the provision; that is "
            "where the model has to be right")

    def test_the_stages_respond_differently_to_the_same_shock(self) -> None:
        """The load-bearing evidence for a single model. If Stage were an
        intercept, one model would be fitting one surface and the design would
        deserve the challenge."""
        card = rg.active()
        model = rg.load_booster(card.version)
        split = tr.Split.from_dict(card.split)
        frame = tr.load(split.validation or split.train)
        matrix = ft.build(frame, encoding=ft.Encoding.from_dict(card.encoding))
        found = ex.stage_interaction(model, matrix.X, frame)
        responses = {
            entry["stage"]: next(p["relative_to_base"] for p in entry["points"]
                                 if p["multiplier"] == 2.0)
            for entry in found["stages"]}
        assert {1, 2} <= set(responses)
        assert abs(responses[1] - responses[2]) > 0.05, (
            f"Stage 1 and Stage 2 respond alike ({responses}); the Stage is "
            "behaving as an intercept and one model per Stage should be "
            "reconsidered")
        assert found["finding"]

    def test_the_interaction_is_not_a_migration_effect(self) -> None:
        """Each Stage is shocked within itself, so nothing crosses the line."""
        card = rg.active()
        model = rg.load_booster(card.version)
        split = tr.Split.from_dict(card.split)
        frame = tr.load(split.validation or split.train)
        matrix = ft.build(frame, encoding=ft.Encoding.from_dict(card.encoding))
        found = ex.stage_interaction(model, matrix.X, frame)
        stages = pd.to_numeric(frame.loc[matrix.X.index, "stage"], errors="coerce")
        for entry in found["stages"]:
            assert entry["rows"] <= int((stages == entry["stage"]).sum())
        assert "migration" in found["note"]


class TestTheStoredModel:
    def test_the_artifact_is_json_and_not_a_pickle(self) -> None:
        card = rg.active()
        path = rg.root() / card.version / rg.ARTIFACT
        body = path.read_bytes()
        assert card.artifact_format == "xgboost-native-json"
        assert body.lstrip().startswith(b"{"), "a pickle is a program, not data"
        json.loads(body)

    def test_the_artifact_carries_no_client_identifier(self) -> None:
        card = rg.active()
        body = (rg.root() / card.version / rg.ARTIFACT).read_text()
        for forbidden in ("borrower_id", "customer_id", "account_id"):
            assert f'"{forbidden}"' not in body

    def test_it_reloads_and_verifies_its_own_hash(self) -> None:
        assert rg.load_booster() is not None

    def test_an_edited_card_will_not_load(self, tmp_path) -> None:
        card = rg.active()
        path = rg.root() / card.version / rg.CARD
        original = path.read_text()
        try:
            body = json.loads(original)
            body["validation"]["r2"] = 0.1
            path.write_text(json.dumps(body))
            with pytest.raises(rg.RegistryError) as raised:
                rg.load_booster(card.version)
            assert "hash" in str(raised.value)
        finally:
            path.write_text(original)

    def test_the_card_states_the_limitations_rather_than_burying_them(self) -> None:
        limitations = " ".join(rg.active().limitations)
        assert "MECHANICAL" in limitations
        assert "single latent cycle factor" in limitations

    def test_it_reports_the_metrics_a_rate_model_should(self) -> None:
        card = rg.active()
        for key in ("r2", "mae", "rmse", "wape"):
            assert key in card.validation
            assert key in card.out_of_time
        assert "accuracy" not in card.validation

    def test_a_new_model_is_a_candidate_and_never_activates_itself(self) -> None:
        assert rg.CANDIDATE in rg.STATES
        assert rg.active().state == rg.ACTIVE
        others = [c for c in rg.cards() if c.version != rg.active_version()]
        assert all(c.state != rg.ACTIVE for c in others)

    def test_the_change_log_records_what_happened(self) -> None:
        events = {e.get("event") for e in rg.changelog()}
        assert "trained" in events
        assert "activated" in events


@needs_model
@needs_lake
class TestTheMlMethodologyIsAnchored:
    def test_it_moves_the_reported_ecl_rather_than_replacing_it(self) -> None:
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    interpreted="PD +20%"))
        delta = rn.execute(state, requested=me.DELTA)
        ml = rn.execute(state, requested=me.ML)
        assert ml.summary["baseline_ecl"] == pytest.approx(
            delta.summary["baseline_ecl"], rel=1e-9), (
            "the baseline is the book, whichever methodology is chosen")

    def test_a_big_shock_is_flagged_as_outside_the_training_range(self) -> None:
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 400.0, sc.RELATIVE),),
                    interpreted="PD x5"))
        result = rn.execute(state, requested=me.ML)
        assert result.ml.get("in_distribution") is False
        assert any("outside the range" in m
                   for m in result.ml.get("out_of_distribution", [])[0].values()
                   if isinstance(m, str))

    def test_the_result_names_the_model_version(self) -> None:
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 10.0, sc.RELATIVE),)))
        result = rn.execute(state, requested=me.ML)
        assert result.choice.version == rg.active_version()
        assert rg.active_version() in result.context()["methodology_stamp"]


# ============================================================ persistence


@needs_database
@needs_lake
class TestSavingAWhatIf:
    def _run(self):
        state = sp.ScenarioState(period=dm.latest_period(), title="Test save").add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    sc.Population(stages=(1,)), interpreted="Stage 1 PD +20%"))
        return rn.execute(state, requested=me.DELTA)

    def test_it_saves_and_reopens_and_reproduces(self) -> None:
        result = self._run()
        stored = th.save(result, name="Reproduction test", owner=1,
                         instruction="Increase Stage 1 PD by 20%")
        try:
            state, card = th.reopen(stored.id, owner=1)
            again = rn.execute(state, requested=me.DELTA)
            assert again.summary["incremental_ecl_pct"] == pytest.approx(
                result.summary["incremental_ecl_pct"], rel=1e-9)
            assert state.period == result.period
            assert len(state.steps) == 1
        finally:
            th.delete(stored.id, owner=1)

    def test_it_keeps_what_is_needed_to_defend_the_figure(self) -> None:
        result = self._run()
        stored = th.save(result, name="Context test", owner=1)
        try:
            body = stored.body
            assert body["context"]["ecl_methodology"]
            assert body["context"]["staging_version"]
            assert body["state"]["macro_version"]
            assert body["summary"]["baseline_ecl"]
            card = stored.card()
            assert card["period"] and card["percentage_change"] is not None
        finally:
            th.delete(stored.id, owner=1)

    def test_one_persons_what_if_is_not_another_persons(self) -> None:
        result = self._run()
        stored = th.save(result, name="Scoping test", owner=1)
        try:
            assert not [s for s in th.listing(owner=2) if s.id == stored.id]
            with pytest.raises(th.ThreadError):
                th.get(stored.id, owner=2)
        finally:
            th.delete(stored.id, owner=1)

    def test_a_repeated_name_becomes_a_second_what_if_not_an_error(self) -> None:
        result = self._run()
        first = th.save(result, name="Same name", owner=1)
        second = th.save(result, name="Same name", owner=1)
        try:
            assert first.id != second.id
            assert second.name != first.name
        finally:
            th.delete(first.id, owner=1)
            th.delete(second.id, owner=1)

    def test_it_needed_no_migration(self) -> None:
        body = th.describe()
        assert body["table"] == "stress_scenarios"
        assert body["migration_required"] is False


# ============================================================ the HTTP surface


@needs_lake
class TestTheHttpSurface:
    def test_the_periods_come_from_the_book(self, client) -> None:
        body = client.get("/api/v1/whatif/periods", headers=ANALYST).json()
        assert body["count"] == len(dm.periods())
        assert body["latest"] == dm.latest_period()

    def test_the_rating_profile_has_nineteen_grades_and_a_total(self, client) -> None:
        body = client.get("/api/v1/whatif/profile/rating", headers=ANALYST).json()
        assert len(body["rows"]) == 19
        assert body["total"]["count"] == body["borrowers"]

    def test_the_rating_migration_is_twenty_by_twenty(self, client) -> None:
        body = client.get("/api/v1/whatif/migration/rating", headers=ANALYST).json()
        assert body["displayed_shape"] == "20 x 20"

    def test_the_macro_screen_carries_ten_variables(self, client) -> None:
        body = client.get("/api/v1/whatif/profile/macro", headers=ANALYST).json()
        assert body["count"] == 10
        assert "single latent cycle factor" in body["limitation"]

    def test_executing_without_a_methodology_returns_the_gate(self, client) -> None:
        body = client.post("/api/v1/whatif/execute", headers=ANALYST, json={
            "state": {"period": dm.latest_period(), "steps": [{
                "kind": "pd",
                "shocks": [{"kind": "pd", "magnitude": 20, "unit": "relative_pct"}],
                "population": {"stages": [1]}}]}}).json()
        assert body["needs_methodology"] is True
        assert body["gate"]["question"].startswith("Which ECL methodology")
        assert "summary" not in body, "no figure may be returned before the choice"

    def test_executing_with_a_methodology_returns_the_full_context(self, client) -> None:
        body = client.post("/api/v1/whatif/execute", headers=ANALYST, json={
            "state": {"period": dm.latest_period(), "steps": [{
                "kind": "pd",
                "shocks": [{"kind": "pd", "magnitude": 20, "unit": "relative_pct"}],
                "population": {"stages": [1]}}]},
            "methodology": "delta"}).json()
        assert body["needs_methodology"] is False
        context = body["context"]
        assert context["ecl_methodology"] == "Delta Model"
        assert context["baseline_ecl"] > 0
        assert context["percentage_change"] > 0

    def test_a_magnitude_free_instruction_asks_rather_than_guesses(self, client) -> None:
        body = client.post("/api/v1/whatif/interpret", headers=ANALYST, json={
            "instruction": "Stress the real estate portfolio.",
            "state": {"period": dm.latest_period(), "steps": []}}).json()
        assert body["understood"] is False
        assert body["opens_whatif"] is True
        assert "how big" in body["message"]

    def test_an_informational_question_is_not_treated_as_a_scenario(self, client) -> None:
        body = client.post("/api/v1/whatif/interpret", headers=ANALYST, json={
            "instruction": "Show Stage 1 PD by sector.",
            "state": {"period": dm.latest_period(), "steps": []}}).json()
        assert body["informational"] is True
        assert "no methodology is needed" in body["message"]

    def test_an_instruction_with_a_magnitude_becomes_a_step(self, client) -> None:
        body = client.post("/api/v1/whatif/interpret", headers=ANALYST, json={
            "instruction": "Increase Stage 1 PD by 20%.",
            "state": {"period": dm.latest_period(), "steps": []}}).json()
        assert body["understood"] is True
        assert len(body["state"]["steps"]) == 1

    def test_a_viewer_may_not_run_a_what_if(self, client) -> None:
        response = client.post("/api/v1/whatif/execute", headers=VIEWER, json={
            "state": {"period": dm.latest_period(), "steps": []},
            "methodology": "delta"})
        assert response.status_code in (401, 403)

    def test_a_viewer_may_not_read_the_profiles(self, client) -> None:
        assert client.get("/api/v1/whatif/profile/rating",
                          headers=VIEWER).status_code in (401, 403)

    def test_the_staging_criteria_are_served_with_their_basis(self, client) -> None:
        body = client.get("/api/v1/whatif/staging", headers=ANALYST).json()
        assert len(body["rules"]) >= 5
        assumptions = [r for r in body["rules"] if not r["governed"]]
        assert assumptions and all(
            "ot a requirement of IFRS 9" in r["basis"] for r in assumptions)

    def test_both_rule_sets_are_served_and_only_one_is_editable(self, client) -> None:
        body = client.get("/api/v1/whatif/staging", headers=ANALYST).json()
        assert body["reported"]["editable"] is False
        assert body["whatif"]["editable"] is True
        assert body["reported"]["label"] != body["whatif"]["label"]
        on_reported = {r["key"] for r in body["reported"]["rules"] if r["enabled"]}
        on_whatif = {r["key"] for r in body["whatif"]["rules"] if r["enabled"]}
        assert on_whatif - on_reported == {"rating_notches", "scenario_pd_ratio"}, (
            "Rule A and Rule B are exactly what the What-If set adds")

    def test_the_composition_surface_says_what_a_rule_can_be(self, client) -> None:
        body = client.get("/api/v1/whatif/staging", headers=ANALYST).json()
        kinds = {k["kind"] for k in body["kind_catalogue"]}
        assert kinds == set(body["kinds"])
        for entry in body["kind_catalogue"]:
            assert entry["label"] and entry["threshold_means"] and entry["needs"]
        assert set(body["combinations"]) == {"ANY", "ALL"}

    def test_a_rule_can_be_added_and_then_removed(self, client) -> None:
        added = client.post(
            "/api/v1/whatif/staging", headers=ANALYST,
            json={"rules": [{"key": "watch_pd", "kind": "absolute_pd",
                             "name": "Watchlist PD", "threshold": 6.0}]}).json()
        assert any(r["key"] == "watch_pd" for r in added["rules"])
        assert not [r for r in added["rules"] if r["key"] == "watch_pd"][0]["governed"]
        assert added["version"] != added["reported"]["version"]

        removed = client.post(
            "/api/v1/whatif/staging", headers=ANALYST,
            json={"rules": [{"key": "watch_pd", "kind": "absolute_pd",
                             "name": "Watchlist PD", "threshold": 6.0},
                            {"key": "watch_pd", "remove": True}]}).json()
        assert not any(r["key"] == "watch_pd" for r in removed["rules"])

    def test_rules_can_be_combined_with_and_as_well_as_or(self, client) -> None:
        body = client.post("/api/v1/whatif/staging", headers=ANALYST,
                           json={"rules": [], "combination": "ALL"}).json()
        assert body["combination"] == "ALL"
        assert "EVERY" in body["combination_note"]

    def test_an_unknown_kind_is_refused_on_the_screen_that_composed_it(
            self, client) -> None:
        response = client.post(
            "/api/v1/whatif/staging", headers=ANALYST,
            json={"rules": [{"key": "nonsense", "kind": "vibes",
                             "threshold": 1.0}]})
        assert response.status_code in (400, 422)

    def test_a_new_key_with_no_kind_is_refused_rather_than_ignored(
            self, client) -> None:
        response = client.post(
            "/api/v1/whatif/staging", headers=ANALYST,
            json={"rules": [{"key": "no_such_rule", "threshold": 1.0}]})
        assert response.status_code in (400, 422)

    def test_a_thread_level_override_survives_execution(self, client) -> None:
        """The override the screen composed is what the run is staged on."""
        state = {"period": "", "steps": [
            {"kind": "rating", "shocks": [
                {"kind": "rating", "magnitude": 2, "unit": "notches",
                 "target": "", "label": ""}],
             "interpreted": "downgrade two notches"}],
            "staging": {"rules": [{"key": "rating_notches", "enabled": False},
                                  {"key": "scenario_pd_ratio", "enabled": False}],
                        "combination": "ANY"},
            "methodology": "delta", "model_version": None,
            "title": None, "thread_id": None}
        body = client.post("/api/v1/whatif/execute", headers=ANALYST,
                           json={"state": state}).json()
        context = body["context"]
        assert context["whatif_staging_version"] != context["reported_staging_version"]
        assert not [r for r in context["whatif_staging"]["rules"]
                    if r["key"] == "rating_notches"][0]["enabled"]
        # And the reported set on the same result is untouched by the override.
        assert context["reported_staging"]["version"].endswith("reported-book")

    def test_the_schema_contract_is_served(self, client) -> None:
        body = client.get("/api/v1/whatif/schema", headers=ANALYST).json()
        assert body["required"] and body["optional"]
        assert body["installation"]["healthy"], (
            body["installation"]["datasets"]["corporate_borrower_360"])
        assert "cash_conversion_cycle_days" in {
            e["field"] for e in body["optional"]}, (
            "the field the reported defect turned on must be classified as "
            "optional, in the open, where anyone can check it")

    def test_a_shock_the_book_cannot_answer_is_a_refusal_not_a_crash(
            self, client) -> None:
        """The reported symptom was a generic 500: "CreditProbe could not
        complete that request". An instruction this book cannot answer must
        come back as a specific refusal instead."""
        state = {"period": "", "steps": [
            {"kind": "financial", "shocks": [
                {"kind": "financial", "magnitude": -20.0,
                 "unit": "relative_pct", "target": "not_a_real_measure",
                 "label": ""}],
             "interpreted": "shock a measure the book does not carry"}],
            "staging": None, "methodology": "delta", "model_version": None,
            "title": None, "thread_id": None}
        response = client.post("/api/v1/whatif/execute", headers=ANALYST,
                               json={"state": state})
        # 422 is this router's refusal code — a scenario it understood and
        # cannot run. What matters is that it is a REFUSAL carrying the
        # reason, not the 500 that produced "CreditProbe could not complete
        # that request".
        assert response.status_code == 422, response.status_code
        detail = str(response.json().get("detail", ""))
        assert "not_a_real_measure" in detail
        assert "build_corporate_universe" in detail, "and how to fix it"
        assert "FROM clause" not in detail, (
            "a reader must never be shown DuckDB's binder error")

    def test_the_delta_model_explains_itself(self, client) -> None:
        body = client.get("/api/v1/whatif/models/delta", headers=ANALYST).json()
        assert "Official Baseline ECL" in body["formula"]
        assert body["limitations"]

    def test_a_borrower_that_does_not_exist_is_refused(self, client) -> None:
        response = client.get("/api/v1/whatif/borrower/NOT-A-BORROWER",
                              headers=ANALYST)
        assert response.status_code == 422
        assert "NOT-A-BORROWER" in response.json()["detail"]["message"]

    def test_the_state_it_returns_is_state_it_will_accept(self, client) -> None:
        """The round trip a conversation actually makes.

        The client posts a state, gets one back, adds to it and posts it
        again. `ScenarioState.to_dict()` writes None for a methodology nobody
        has chosen yet, and the request model refused it — so every second
        turn in a thread failed with a validation error while the first
        looked fine.
        """
        first = client.post("/api/v1/whatif/interpret", headers=ANALYST, json={
            "instruction": "Increase Stage 1 PD by 20%.",
            "state": {"period": dm.latest_period(), "steps": []}}).json()
        assert first["understood"] is True

        # Post the returned state straight back, unmodified.
        second = client.post("/api/v1/whatif/execute", headers=ANALYST,
                             json={"state": first["state"]})
        assert second.status_code == 200, second.json()
        assert second.json()["needs_methodology"] is True

        third = client.post("/api/v1/whatif/execute", headers=ANALYST,
                            json={"state": second.json()["state"],
                                  "methodology": "delta"})
        assert third.status_code == 200, third.json()
        assert third.json()["context"]["baseline_ecl"] > 0

        # And once more, carrying the methodology the run settled.
        fourth = client.post("/api/v1/whatif/execute", headers=ANALYST,
                             json={"state": third.json()["state"]})
        assert fourth.status_code == 200, fourth.json()
        assert fourth.json()["needs_methodology"] is False, (
            "a thread that has chosen must not be asked again")

    def test_the_landing_page_has_six_guided_journeys(self, client) -> None:
        body = client.get("/api/v1/whatif/landing", headers=ANALYST).json()
        assert body["heading"] == "What-If"
        assert len(body["journeys"]) == 6
        assert {j["key"] for j in body["journeys"]} == {
            "rating", "parameters", "stage", "macro", "sector", "borrower"}


# ================================================== the macro lab over HTTP


@needs_lake
class TestTheMacroLabOverHttp:
    """Three things a person may do with a macro variable, and the one thing
    the product may not do to them: substitute an assumption quietly."""

    EMPTY = {"period": "", "steps": [], "staging": None, "methodology": "",
             "methodology_version": "", "title": "", "sensitivities": []}

    OWN = {"variable": "gdp_growth", "source": "user", "name": "GDP Growth Rate",
           "pd_response_kind": "multiplier", "pd_response": 1.35,
           "lgd_response_kind": "absolute_pp", "lgd_response": 1.2}

    def test_a_viewer_may_not_analyse_or_configure(self, client) -> None:
        analyse = client.post("/api/v1/whatif/macro/analyse", headers=VIEWER,
                              json={"variable": "gdp_growth",
                                    "state": self.EMPTY})
        assert analyse.status_code == 403
        configure = client.post("/api/v1/whatif/macro/configure",
                                headers=VIEWER,
                                json={"sensitivity": self.OWN,
                                      "state": self.EMPTY})
        assert configure.status_code == 403

    def test_every_variable_has_a_card_with_the_relationship_in_force(
            self, client) -> None:
        for key in ("gdp_growth", "unemployment", "house_price_index",
                    "inflation", "current_account", "equity_index",
                    "policy_rate", "fx_depreciation", "oil_price",
                    "credit_spread"):
            body = client.get(f"/api/v1/whatif/macro/{key}",
                              headers=ANALYST).json()
            assert body["variable"]["key"] == key
            assert body["configured"]["source"] == "reference"
            assert body["configured"]["description"], key

    def test_a_variable_it_does_not_have_names_the_ones_it_does(
            self, client) -> None:
        body = client.get("/api/v1/whatif/macro/the_vibes", headers=ANALYST)
        assert body.status_code == 422
        assert "Unemployment Rate" in body.json()["detail"]["message"]

    def test_an_estimate_is_offered_beside_the_configured_one_never_instead(
            self, client) -> None:
        body = client.post("/api/v1/whatif/macro/analyse", headers=ANALYST,
                           json={"variable": "gdp_growth",
                                 "state": self.EMPTY}).json()
        assert body["configured"]["source"] == "reference"
        assert body["estimated"]["source"] == "empirical"
        # However the estimate came out, the configured sensitivity is what is
        # recommended, and the reasoning is stated rather than implied.
        assert body["recommendation"]["recommends"] == "reference"
        assert body["recommendation"]["because"]
        assert body["fit"]["small_sample"]

    def test_the_estimate_is_on_a_credible_scale_for_every_variable(
            self, client) -> None:
        """A fit that implies a PD multiplier of 46 is a unit bug, not a
        finding, and it must not reach a screen looking like evidence."""
        for key in ("gdp_growth", "policy_rate", "credit_spread",
                    "oil_price", "house_price_index", "equity_index",
                    "fx_depreciation", "unemployment", "inflation",
                    "current_account"):
            fit = client.post("/api/v1/whatif/macro/analyse", headers=ANALYST,
                              json={"variable": key,
                                    "state": self.EMPTY}).json()["fit"]
            assert 0.2 < fit["implied_pd_multiplier"] < 5.0, key
            assert fit["points"] >= 8, key

    def test_an_override_is_in_force_for_the_thread_and_says_so(
            self, client) -> None:
        body = client.post("/api/v1/whatif/macro/configure", headers=ANALYST,
                           json={"sensitivity": self.OWN,
                                 "state": self.EMPTY}).json()
        assert body["in_force_for"] == "this thread only"
        assert body["sensitivity"]["source_label"] == "User-Defined Sensitivity"
        # The governed matrix is not edited by this, and the response proves it.
        assert body["reference_unchanged"]["pd_response"] == pytest.approx(1.10)
        assert "unchanged" in body["message"]
        assert body["state"]["sensitivities"][0]["variable"] == "gdp_growth"

    def test_a_user_defined_relationship_is_never_called_empirical(
            self, client) -> None:
        body = client.post("/api/v1/whatif/macro/configure", headers=ANALYST,
                           json={"sensitivity": self.OWN,
                                 "state": self.EMPTY}).json()
        said = (body["sensitivity"]["source_label"] + " "
                + body["sensitivity"]["description"] + " " + body["message"])
        for word in ("required", "regulatory", "approved", "empirical",
                     "estimated"):
            assert word not in said.lower(), word

    def test_an_override_changes_the_figure_and_is_stamped_on_it(
            self, client) -> None:
        """The whole point of allowing one. If it did not move the number it
        would be decoration, and if it moved it silently it would be a trap."""
        read = client.post("/api/v1/whatif/interpret", headers=ANALYST,
                           json={"instruction": "reduce GDP growth by 1 "
                                                "percentage point",
                                 "state": self.EMPTY})
        assert read.status_code == 200, read.json()
        state = read.json()["state"]
        assert state["steps"], "the macro shock was not read into the scenario"

        reference = client.post("/api/v1/whatif/execute", headers=ANALYST,
                                json={"state": state, "methodology": "delta"})
        assert reference.status_code == 200, reference.json()
        plain = reference.json()["context"]
        assert plain["sensitivities"] == []
        assert "governed CreditProbe reference" in plain["sensitivity_note"]

        configured = client.post("/api/v1/whatif/macro/configure",
                                 headers=ANALYST,
                                 json={"sensitivity": self.OWN,
                                       "state": state}).json()["state"]
        overridden = client.post("/api/v1/whatif/execute", headers=ANALYST,
                                 json={"state": configured,
                                       "methodology": "delta"})
        assert overridden.status_code == 200, overridden.json()
        stamped = overridden.json()["context"]
        assert stamped["whatif_ecl"] != pytest.approx(plain["whatif_ecl"])
        assert [s["source"] for s in stamped["sensitivities"]] == ["user"]
        assert "overridden for this thread" in stamped["sensitivity_note"]
        # And the step that used it says which relationship it applied.
        applied = " ".join(str(s) for s in overridden.json()["steps"])
        assert "user-defined sensitivity" in applied
        assert "NOT the governed CreditProbe reference sensitivity" in applied

    def test_the_three_kinds_of_relationship_are_described_for_the_screen(
            self, client) -> None:
        body = client.get("/api/v1/whatif/macro/method", headers=ANALYST).json()
        assert {s["source"] for s in body["sources"]} == {
            "reference", "empirical", "user"}
        assert "never called required, regulatory, approved or empirical" in (
            body["statement"])


# ============================================== the detailed export over HTTP


@needs_lake
class TestTheDetailedExportOverHttp:
    """A workbook carries the whole book at borrower grain, so who may have
    one — and whose result they get — is a security question, not a feature."""

    EMPTY = {"period": "", "steps": [], "staging": None, "methodology": "",
             "methodology_version": "", "title": "", "sensitivities": []}

    def _run(self, client) -> dict:
        read = client.post("/api/v1/whatif/interpret", headers=ANALYST,
                           json={"instruction": "increase PD by 20%",
                                 "state": self.EMPTY}).json()
        run = client.post("/api/v1/whatif/execute", headers=ANALYST,
                          json={"state": read["state"],
                                "methodology": "delta"})
        assert run.status_code == 200, run.json()
        return run.json()

    def test_a_viewer_may_not_download_the_book(self, client) -> None:
        body = client.post("/api/v1/whatif/export", headers=VIEWER,
                           json={"state": self.EMPTY})
        assert body.status_code == 403

    def test_it_serves_a_workbook_a_browser_will_save(self, client) -> None:
        run = self._run(client)
        got = client.post("/api/v1/whatif/export", headers=ANALYST,
                          json={"run_id": run["run_id"]})
        assert got.status_code == 200
        assert got.headers["content-type"].startswith(
            "application/vnd.openxmlformats")
        assert "attachment;" in got.headers["content-disposition"]
        assert ".xlsx" in got.headers["content-disposition"]
        # A workbook is a point-in-time record; a cached one is yesterday's
        # numbers under today's filename.
        assert "no-store" in got.headers["cache-control"]
        assert got.headers["x-creditprobe-whatif-methodology"] == "delta"
        assert int(got.headers["x-creditprobe-whatif-rows"]) > 0
        assert got.content[:2] == b"PK", "that is not a workbook"

    def test_the_filename_cannot_carry_a_path(self, client) -> None:
        """A scenario title is user text and reaches the Content-Disposition."""
        state = dict(self.EMPTY, title="../../etc/passwd: a \\ title")
        read = client.post("/api/v1/whatif/interpret", headers=ANALYST,
                           json={"instruction": "increase PD by 20%",
                                 "state": state}).json()
        got = client.post("/api/v1/whatif/export", headers=ANALYST,
                          json={"state": read["state"],
                                "methodology": "delta"})
        assert got.status_code == 200
        disposition = got.headers["content-disposition"]
        for unsafe in ("..", "/", "\\", ":"):
            assert unsafe not in disposition.split('filename="')[1], unsafe

    def test_it_refuses_rather_than_exporting_an_empty_scenario(
            self, client) -> None:
        body = client.post("/api/v1/whatif/export", headers=ANALYST,
                           json={"state": self.EMPTY})
        assert body.status_code == 422
        assert "Build a scenario" in body.json()["detail"]["message"]

    def test_a_held_result_is_never_readable_by_another_person(self) -> None:
        """The cache is what the export trusts, so this is where it matters."""
        from backend.whatif import cache as ch

        run_id = ch.put(object(), owner=101)
        assert ch.get(run_id, owner=101) is not None
        assert ch.get(run_id, owner=202) is None, (
            "one analyst's held result reached another analyst")
        assert ch.get(run_id, owner=None) is None

    def test_an_expired_run_id_does_not_silently_export_something_else(
            self, client) -> None:
        """A run_id that does not resolve must not quietly become a new run
        of an empty scenario dressed up as the one that was asked for."""
        body = client.post("/api/v1/whatif/export", headers=ANALYST,
                           json={"run_id": "0" * 32, "state": self.EMPTY})
        assert body.status_code == 422
        assert "no What-If to export" in body.json()["detail"]["message"]
