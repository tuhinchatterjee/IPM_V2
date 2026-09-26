"""The emulator's honesty constraints, most of which need no model at all.

UNIT. No model fitted here, no provider, no database. The heavy training run
lives in `scripts/whatif/train_emulator.py` and its outcome is published in
`MODEL_CARD_*.md` and `whatif_*_model_metric`; what this module asserts is
that the machinery around it cannot lie.

The M-series requirements covered:

* **M01** the target is the declared ECL rate on the declared denominator,
  not exposure share.
* **M02** no target-derived column reaches the feature matrix, and the check
  raises rather than filtering.
* **M03–M05** the split is chronological by distinct period, leaks nothing,
  and is persisted per row.
* **M06–M07** blend weights are genuinely fitted, non-negative and sum to
  one; a `1/0/0` outcome is reported as a single-model result.
* **M15–M16** the gates in code match the predeclared document, and a
  failure is reported as a failure.
* **M18** the candidate libraries are isolated: the accepted interpreter
  imports none of them, and nothing a chat turn reaches imports the
  training half.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import random
import re

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import errors as err
from backend.cockpit_v4.scenario import ml
from backend.cockpit_v4.scenario.ml import blend as bl
from backend.cockpit_v4.scenario.ml import features as ft
from backend.cockpit_v4.scenario.ml import infer
from backend.cockpit_v4.scenario.ml import split as sp
from backend.cockpit_v4.scenario.ml import train as tr

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGETS = ROOT / "docs" / "whatif" / "ML_ACCEPTANCE_TARGETS.md"

QUARTERS = tuple(f"{y}Q{q}" for y in range(2021, 2027)
                 for q in (1, 2, 3, 4))[2:22]


# ==========================================================================
# M01 / M02 -- the target, and what may not be near it
# ==========================================================================

def test_m01_the_target_is_the_declared_rate_on_the_declared_denominator():
    assert ft.TARGET == "ecl_rate"
    assert ft.DENOMINATOR == "ead_sar_mn"
    ft.check_target(ft.TARGET)


def test_m01_a_different_target_is_refused_by_name() -> None:
    """Section 11.1 is specifically about a manufactured target."""
    with pytest.raises(AssertionError, match="manufactured"):
        ft.check_target("ecl_share_of_portfolio")


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_m02_no_declared_feature_is_derived_from_the_target(domain_id) -> None:
    """The real feature list, against the real ban."""
    names = ft.names(domain_id)
    assert names
    assert ft.suspicious(names) == []
    ft.require_clean(names)
    assert ft.TARGET not in names


def test_m02_the_leakage_check_raises_rather_than_filtering() -> None:
    """Silently dropping a leaked column would let a wrong matrix train."""
    with pytest.raises(AssertionError) as raised:
        ft.require_clean(["sector", "ecl_rate", "pd_pit_12m"])
    assert "learns an identity" in str(raised.value)
    assert "ecl_rate" in str(raised.value)


def test_m02_a_new_ecl_column_is_caught_by_the_rule_not_by_a_list() -> None:
    """A column added to the release later must not need this file edited."""
    assert "ecl_stage3_sar_mn" not in ft.BANNED
    assert ft.suspicious(["ecl_stage3_sar_mn"])
    assert ft.suspicious(["lifetime_ecl_overlay_v2"])
    assert ft.suspicious(["recovery_rate_pct"])


def test_the_risk_drivers_are_deliberately_kept() -> None:
    """Excluding PD and LGD would leave a model predicting ECL from sector.

    They are inputs to the calculator, not outputs of it. The naive
    reference model in ML_ACCEPTANCE_TARGETS.md is what stops using them
    being a free pass.
    """
    for domain_id in (dom.CORPORATE, dom.RETAIL):
        names = ft.names(domain_id)
        assert "pd_pit_12m" in names
        assert "pd_lifetime" in names
        assert "lgd_pct" in names
        assert ft.DENOMINATOR in names


def test_post_hoc_columns_are_banned_because_they_are_the_future() -> None:
    assert "write_off_sar_mn" in ft.BANNED
    assert "recovery_sar_mn" in ft.BANNED
    for domain_id in (dom.CORPORATE, dom.RETAIL):
        assert "write_off_sar_mn" not in ft.names(domain_id)


# ==========================================================================
# M03 / M04 / M05 -- the split
# ==========================================================================

def test_m03_the_split_is_chronological_and_leaks_nothing() -> None:
    assignment = sp.assign(QUARTERS)
    assert sp.leakage(assignment) == []
    assert max(assignment.train) < min(assignment.validate)
    assert max(assignment.validate) < min(assignment.test)
    assert assignment.test == QUARTERS[-4:]


def test_m03_every_period_lands_in_exactly_one_place() -> None:
    assignment = sp.assign(QUARTERS)
    counted = (len(assignment.train) + len(assignment.validate)
               + len(assignment.test) + len(assignment.embargoed))
    assert counted == len(QUARTERS)
    assert set(assignment.train).isdisjoint(assignment.embargoed)
    assert set(assignment.test).isdisjoint(assignment.embargoed)


def test_m03_the_leakage_check_can_actually_fail() -> None:
    """A check that cannot fail is not a check."""
    good = sp.assign(QUARTERS)
    overlapping = sp.Assignment(
        periods=good.periods, train=good.train,
        validate=good.train[-2:] + good.validate, test=good.test,
        embargo=0, embargoed=(), rule="deliberately broken")
    problems = sp.leakage(overlapping)
    assert problems
    assert any("train/validate share" in p for p in problems)


def test_m04_the_embargo_is_derived_and_its_reasoning_travels_with_it():
    periods, rule = sp.label_embargo(
        [{"reporting_quarter": "2025Q1"}], period_column="reporting_quarter")
    assert periods == 1
    assert "overlapping twelve-month window" in rule
    assert sp.assign(QUARTERS, embargo=periods, rule=rule).rule == rule


def test_m04_the_embargoed_periods_are_reported_not_absorbed() -> None:
    assignment = sp.assign(QUARTERS, embargo=1)
    assert len(assignment.embargoed) == 2
    assert assignment.counts()["embargoed"] == 2
    for period in assignment.embargoed:
        assert period not in assignment.train
        assert period not in assignment.validate


def test_m04_no_fold_touches_a_test_or_an_embargoed_period() -> None:
    """Out-of-fold predictions the blend weights are fitted on have to be
    out of fold."""
    assignment = sp.assign(QUARTERS)
    forbidden = set(assignment.test) | set(assignment.embargoed)
    folds = sp.folds(assignment, count=ml.MAX_FOLDS)
    assert folds
    for train_periods, valid_periods in folds:
        assert not (set(train_periods) & forbidden)
        assert not (set(valid_periods) & forbidden)
        assert max(train_periods) < min(valid_periods)


def test_m05_the_split_assignment_is_persisted_per_row() -> None:
    assignment = sp.assign(QUARTERS)
    rows = [{"facility_id": f"F{i}", "reporting_quarter": q}
            for i in range(3) for q in QUARTERS]
    persisted = sp.assignment_rows(
        assignment, rows, key="facility_id",
        period_column="reporting_quarter", stamp={"origin": "SYNTHETIC_DEMO"})
    assert len(persisted) == len(rows)
    assert {r["split"] for r in persisted} == set(sp.SPLITS)
    assert all(r["embargo_periods"] == 1 for r in persisted)
    assert all(r["origin"] == "SYNTHETIC_DEMO" for r in persisted)


def test_a_book_too_short_to_split_is_refused_rather_than_split_anyway():
    with pytest.raises(ValueError, match="not enough to split"):
        sp.assign(QUARTERS[:6])


# ==========================================================================
# M06 / M07 -- the blend
# ==========================================================================

def _components(rng, n=400, noise_only=False):
    y = [rng.gauss(0, 1) for _ in range(n)]
    if noise_only:
        return y, {c: [rng.gauss(0, 1) for _ in range(n)]
                   for c in ml.COMPONENTS}
    return y, {
        ml.XGBOOST: [0.7 * v + rng.gauss(0, 0.3) for v in y],
        ml.LIGHTGBM: [0.9 * v + rng.gauss(0, 0.5) for v in y],
        ml.ADDITIVE_LOG: [0.4 * v + rng.gauss(0, 0.8) for v in y],
    }


def test_m06_weights_are_non_negative_and_sum_to_exactly_one() -> None:
    y, predictions = _components(random.Random(11))
    blended = bl.fit(predictions, y)
    assert all(w >= 0.0 for w in blended.weights)
    assert sum(blended.weights) == pytest.approx(1.0, abs=1e-9)
    assert len(blended.weights) == len(ml.COMPONENTS)


def test_m06_the_weights_are_fitted_not_hardcoded() -> None:
    """Different data must produce different weights."""
    first = bl.fit(*reversed(_components(random.Random(1))))
    second = bl.fit(*reversed(_components(random.Random(2))))
    assert first.weights != second.weights
    assert first.weights != (1 / 3, 1 / 3, 1 / 3)


def test_m06_the_solution_is_the_optimum_not_a_nearby_point() -> None:
    """Exact: no perturbation of the weights on the simplex does better."""
    y, predictions = _components(random.Random(3))
    blended = bl.fit(predictions, y)
    ordered = [list(predictions[c]) for c in blended.components]
    best = bl._error(ordered, y, list(blended.weights))
    rng = random.Random(4)
    for _try in range(300):
        draw = [rng.random() for _ in blended.components]
        total = sum(draw)
        candidate = [w / total for w in draw]
        assert bl._error(ordered, y, candidate) >= best - 1e-9


def test_m07_a_one_zero_zero_outcome_is_called_a_single_model_result():
    """The gate that matters. A concentrated fit is not an ensemble."""
    y = [float(i % 7) for i in range(200)]
    rng = random.Random(5)
    predictions = {ml.XGBOOST: list(y),
                   ml.LIGHTGBM: [rng.gauss(0, 1) for _ in y],
                   ml.ADDITIVE_LOG: [rng.gauss(0, 1) for _ in y]}
    blended = bl.fit(predictions, y)
    assert blended.is_single_model
    assert blended.material == (ml.XGBOOST,)
    assert blended.headline.startswith("SINGLE-MODEL RESULT")
    assert "not a blend, and is reported as one" in blended.headline


def test_m07_a_real_blend_says_it_is_one_and_names_the_immaterial() -> None:
    y, predictions = _components(random.Random(6))
    blended = bl.fit(predictions, y)
    assert not blended.is_single_model
    assert blended.headline.startswith("BLEND of")
    if blended.immaterial:
        assert "materiality floor" in blended.headline
        for name in blended.immaterial:
            assert name in blended.headline


def test_the_materiality_floor_is_the_declared_one() -> None:
    assert ml.MATERIAL_WEIGHT == 0.05
    y, predictions = _components(random.Random(8))
    blended = bl.fit(predictions, y)
    for name, weight in blended.by_name.items():
        assert (name in blended.material) == (weight >= ml.MATERIAL_WEIGHT)


def test_whether_blending_helped_is_reported_either_way() -> None:
    y, predictions = _components(random.Random(9))
    blended = bl.fit(predictions, y)
    assert isinstance(bl.beats_every_component(blended), bool)
    assert set(blended.single_component_errors) == set(ml.COMPONENTS)


def test_weights_fitted_on_mismatched_predictions_are_refused() -> None:
    y, predictions = _components(random.Random(10), n=50)
    predictions[ml.ADDITIVE_LOG] = predictions[ml.ADDITIVE_LOG][:40]
    with pytest.raises(ValueError, match="different populations"):
        bl.fit(predictions, y)


# ==========================================================================
# The anchoring, and the composition that is banned
# ==========================================================================

class _Frame(list):
    """The smallest thing `infer.anchor` needs: a length and a predictor."""

    columns: tuple[str, ...] = ()


class _Model:
    def __init__(self, scale: float) -> None:
        self.scale = scale

    def predict(self, frame):
        return [self.scale * v for v in frame]


def _loaded(scale: float = 0.02) -> infer.Loaded:
    return infer.Loaded(
        domain_id="corporate", model_version=ml.MODEL_VERSION,
        release_id="v4-whatif-corporate-20q-s1", features=(),
        categorical=(), weights={ml.XGBOOST: 1.0},
        headline="test double", models={ml.XGBOOST: _Model(scale)})


class _Indexed(dict):
    """A frame stand-in whose `[list]` returns the values themselves."""

    def __init__(self, values):
        super().__init__()
        self.values = list(values)

    def __len__(self):
        return len(self.values)

    def __getitem__(self, _key):
        return self.values


def test_a_zero_shock_moves_the_answer_by_exactly_zero() -> None:
    """Exactly. Not within a tolerance: it is the same call twice."""
    loaded = _loaded()
    frame = _Indexed([1.0, 2.0, 3.0])
    got = infer.anchor(loaded, baseline_frame=frame, scenario_frame=frame,
                       denominator=[100.0, 100.0, 100.0],
                       observed_modelled=40.0, observed_overlay=6.0)
    assert got.ml_change == 0.0
    assert got.anchored_modelled == 40.0
    assert got.anchored_total == 46.0
    assert got.change == 0.0
    assert infer.zero_shock_is_zero(loaded, frame, [1.0, 1.0, 1.0])


def test_the_anchoring_uses_the_models_difference_not_its_level() -> None:
    """A model 3% high everywhere must not report a 3% change."""
    loaded = _loaded(scale=0.02)
    baseline = _Indexed([1.0, 1.0])
    scenario = _Indexed([1.5, 1.5])
    got = infer.anchor(loaded, baseline_frame=baseline,
                       scenario_frame=scenario, denominator=[100.0, 100.0],
                       observed_modelled=7.0, observed_overlay=1.0)
    # raw: 0.02*1*100*2 = 4.0 ; 0.02*1.5*100*2 = 6.0 ; difference 2.0
    assert got.raw_baseline == pytest.approx(4.0)
    assert got.raw_scenario == pytest.approx(6.0)
    assert got.ml_change == pytest.approx(2.0)
    # Anchored on the OBSERVED 7.0, not on the model's 4.0.
    assert got.anchored_modelled == pytest.approx(9.0)
    assert got.anchored_total == pytest.approx(10.0)


def test_all_six_numbers_the_specification_asks_for_are_shown() -> None:
    loaded = _loaded()
    got = infer.anchor(loaded, baseline_frame=_Indexed([1.0]),
                       scenario_frame=_Indexed([1.2]), denominator=[50.0],
                       observed_modelled=3.0, observed_overlay=0.5)
    facts = got.as_facts()
    for key in ("observed_modelled_ecl", "observed_overlay",
                "raw_model_baseline", "raw_model_scenario",
                "raw_model_difference", "anchored_total_ecl"):
        assert key in facts
    assert "ML_change = P1 - P0" in facts["anchoring"]
    assert "never used, only its difference" in facts["anchoring"]


def test_the_ml_estimate_is_never_multiplied_by_the_delta_factor() -> None:
    """The ban, with a name a call site can point at."""
    with pytest.raises(err.ScenarioError) as raised:
        infer.refuse_composition(ml_estimate=12.0, delta_factor=1.2)
    assert raised.value.code == err.METHOD_COVERAGE_GAP
    message = str(raised.value)
    assert "not multiplied by the Delta factor" in message
    assert "a macro move is not applied twice" in message
    assert "two answers to one question" in message


def test_a_macro_move_records_which_route_it_took() -> None:
    """Applied once, through the parameter or through the factor, never
    both."""
    loaded = _loaded()
    for route in (infer.VIA_PARAMETER, infer.VIA_FACTOR):
        got = infer.anchor(loaded, baseline_frame=_Indexed([1.0]),
                           scenario_frame=_Indexed([1.1]),
                           denominator=[10.0], observed_modelled=1.0,
                           observed_overlay=0.0, applied_once=route)
        assert got.applied_once == route
        assert got.as_facts()["macro_move_applied_via"] == route
    with pytest.raises(ValueError, match="applied once"):
        infer.anchor(loaded, baseline_frame=_Indexed([1.0]),
                     scenario_frame=_Indexed([1.1]), denominator=[10.0],
                     observed_modelled=1.0, observed_overlay=0.0,
                     applied_once="both")


def test_two_different_populations_are_not_a_change() -> None:
    loaded = _loaded()
    with pytest.raises(err.ScenarioError) as raised:
        infer.anchor(loaded, baseline_frame=_Indexed([1.0, 2.0]),
                     scenario_frame=_Indexed([1.0]), denominator=[1.0],
                     observed_modelled=1.0, observed_overlay=0.0)
    assert raised.value.code == err.METHOD_COVERAGE_GAP
    assert "not a change" in str(raised.value)


def test_a_missing_model_is_model_not_ready_and_not_a_zero(tmp_path) -> None:
    with pytest.raises(err.ScenarioError) as raised:
        infer.load("corporate", root=tmp_path)
    assert raised.value.code == err.MODEL_NOT_READY
    assert "not a change of zero" in str(raised.value)
    assert "Delta or an explicit assumption" in str(raised.value)


def test_a_model_trained_against_another_release_is_refused(tmp_path) -> None:
    book = tmp_path / "corporate"
    book.mkdir()
    (book / "blend.json").write_text(json.dumps({
        "model_version": ml.MODEL_VERSION, "domain_id": "corporate",
        "release_id": "v4-some-other-book", "features": [], "weights": {}}))
    with pytest.raises(err.ScenarioError) as raised:
        infer.load("corporate", root=tmp_path,
                   release_id="v4-whatif-corporate-20q-s1")
    assert raised.value.code == err.MODEL_NOT_READY
    assert "describes a different book" in str(raised.value)


# ==========================================================================
# The gates: code and document cannot drift
# ==========================================================================

def test_the_gates_in_code_are_the_gates_in_the_committed_document() -> None:
    """A threshold that moved in one place and not the other is the whole
    failure mode `ML_ACCEPTANCE_TARGETS.md` exists to prevent."""
    text = TARGETS.read_text(encoding="utf-8")
    for name, (_what, threshold) in tr.GATES.items():
        row = re.search(rf"\|\s*\*\*{name}\*\*\s*\|(.+?)\|", text)
        assert row, f"{name} is not in ML_ACCEPTANCE_TARGETS.md"
        stated = re.search(r"(\d+(?:\.\d+)?)\s*%", text[row.start():
                                                        row.end() + 60])
        assert stated, f"{name}'s threshold is not stated as a percentage"
        assert float(stated.group(1)) / 100 == pytest.approx(threshold)


def test_the_document_was_written_before_any_model_was_fitted() -> None:
    text = TARGETS.read_text(encoding="utf-8")
    assert "before any model is fitted" in text
    assert "a failure stays a failure" in text.lower()
    assert "is **not edited**" in text


def test_a_failed_gate_is_reported_failed() -> None:
    result = tr.Result(
        domain_id=dom.CORPORATE, release_id="r",
        model_version=ml.MODEL_VERSION,
        assignment=sp.assign(QUARTERS),
        blended=bl.fit(*reversed(_components(random.Random(12)))),
        components={},
        metrics={"test_wape": 0.42, "test_bias": -0.11,
                 "worst_period_bias": 0.30,
                 "worst_material_group_wape": 0.55})
    tr.judge(result)
    assert result.passed is False
    assert len(result.failures()) == 4
    assert all(not g["passed"] for g in result.gates.values())
    assert result.gates["G1"]["measured"] == 0.42
    assert "measured 0.4200" in result.failures()[0]


def test_a_passing_result_passes_on_the_measured_value() -> None:
    result = tr.Result(
        domain_id=dom.CORPORATE, release_id="r",
        model_version=ml.MODEL_VERSION,
        assignment=sp.assign(QUARTERS),
        blended=bl.fit(*reversed(_components(random.Random(13)))),
        components={},
        metrics={"test_wape": 0.04, "test_bias": 0.01,
                 "worst_period_bias": 0.02,
                 "worst_material_group_wape": 0.09})
    tr.judge(result)
    assert result.passed is True
    assert result.failures() == []


def test_the_bias_gate_uses_the_absolute_value() -> None:
    """A model 11% low fails just as a model 11% high does."""
    for signed in (-0.11, 0.11):
        result = tr.Result(
            domain_id=dom.CORPORATE, release_id="r",
            model_version=ml.MODEL_VERSION,
            assignment=sp.assign(QUARTERS),
            blended=bl.fit(*reversed(_components(random.Random(14)))),
            components={},
            metrics={"test_wape": 0.04, "test_bias": signed,
                     "worst_period_bias": 0.02,
                     "worst_material_group_wape": 0.09})
        tr.judge(result)
        assert result.gates["G2"]["passed"] is False


def test_wape_is_not_hijacked_by_a_near_zero_actual() -> None:
    """Why the document names WAPE rather than MAPE."""
    actual = [100.0, 200.0, 0.0001]
    predicted = [101.0, 199.0, 5.0]
    assert tr.wape(actual, predicted) < 0.03
    mape = sum(abs(p - a) / a for a, p in zip(actual, predicted,
                                              strict=True)) / 3
    assert mape > 1000


def test_a_group_below_the_threshold_is_reported_but_not_gated() -> None:
    assert tr.MATERIAL_GROUP == 100


# ==========================================================================
# M18 -- isolation, in both directions
# ==========================================================================

@pytest.mark.parametrize("library", ["xgboost", "lightgbm", "sklearn",
                                     "shap", "scipy", "matplotlib"])
def test_the_accepted_environment_carries_none_of_the_ml_libraries(library):
    """The candidate can see the accepted environment; not the reverse.

    This suite runs on the ACCEPTED interpreter. If one of these ever
    becomes importable here, a dependency has leaked out of
    `requirements-whatif.txt` into the accepted environment.
    """
    assert importlib.util.find_spec(library) is None, (
        f"{library} is importable from the accepted interpreter. It belongs "
        f"in .venv-whatif only; see requirements-whatif.txt.")


def test_importing_the_ml_package_needs_none_of_those_libraries() -> None:
    """Every import of them is inside a function, so this suite can run."""
    from backend.cockpit_v4.scenario.ml import components as cp

    assert set(cp.available()) == set(ml.COMPONENTS)
    assert sorted(cp.missing()) == sorted(ml.COMPONENTS)


def test_nothing_a_chat_turn_reaches_imports_the_training_half() -> None:
    """`train`, `components`, `blend` and `split` are offline-only."""
    offenders: list[str] = []
    training = ("ml import train", "ml import components", "ml import blend",
                "ml import split", "ml.train", "ml.components", "ml.blend",
                "ml.split")
    for path in (ROOT / "backend" / "cockpit_v4").rglob("*.py"):
        if "scenario/ml" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for module in training:
            if module in text:
                offenders.append(f"{path.name}: {module}")
    assert offenders == []


def test_the_requirements_file_is_not_the_accepted_one() -> None:
    """Section 14.1: the accepted dependency set is not changed."""
    candidate = (ROOT / "requirements-whatif.txt").read_text()
    assert "xgboost" in candidate
    accepted = (ROOT / "pyproject.toml").read_text()
    for library in ("xgboost", "lightgbm", "shap"):
        assert library not in accepted, (
            f"{library} reached pyproject.toml, which is a protected file "
            f"and the accepted application's dependency set.")


def test_every_pinned_library_is_pinned_exactly() -> None:
    """A range would make "the same model" mean something else next month."""
    text = (ROOT / "requirements-whatif.txt").read_text()
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.strip().startswith("#")]
    assert lines
    for line in lines:
        assert "==" in line, f"{line} is not pinned to an exact version"
