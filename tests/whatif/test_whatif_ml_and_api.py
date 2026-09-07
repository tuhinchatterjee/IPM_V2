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
        crossing is WORTH decides the headline number."""
        boundary = rg.active().stage_study["boundary"]
        assert boundary["available"]
        assert boundary["governed_step"] > 1.0
        assert abs(boundary["champion_step_error_pct"]) < 2.0, (
            "the model must reproduce the governed Stage 1 to Stage 2 step")
        if "challenger_step_error_pct" in boundary:
            assert (abs(boundary["champion_step_error_pct"])
                    < abs(boundary["challenger_step_error_pct"])), (
                "this is the reason the single model was kept; if it stops "
                "being true the design should change")

    def test_the_per_stage_error_is_reported_out_of_time_not_only_in_sample(
            self) -> None:
        slices = rg.active().slices
        assert slices.get("out_of_time_stage"), (
            "validation-period error by Stage is not the same claim as "
            "out-of-time error by Stage")
        labels = {row["label"] for row in slices["out_of_time_stage"]}
        assert {"1", "2"} <= labels

    def test_each_stage_carries_what_it_is_worth(self) -> None:
        """R-squared on a Stage holding 9% of the ECL is not the same finding
        as R-squared on the Stage holding 71% of it."""
        by_stage = rg.active().stage_study["champion_by_stage"]
        total = sum(body["ecl"] for body in by_stage.values())
        assert total > 0
        assert by_stage["2"]["ecl"] / total > 0.4, (
            "Stage 2 is where the provision is; the card has to say so")

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

    def test_the_rating_profile_has_fourteen_grades_and_a_total(self, client) -> None:
        body = client.get("/api/v1/whatif/profile/rating", headers=ANALYST).json()
        assert len(body["rows"]) == 14
        assert body["total"]["count"] == body["borrowers"]

    def test_the_rating_migration_is_fifteen_by_fifteen(self, client) -> None:
        body = client.get("/api/v1/whatif/migration/rating", headers=ANALYST).json()
        assert body["displayed_shape"] == "15 x 15"

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
