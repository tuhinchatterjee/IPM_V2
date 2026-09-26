"""P9b -- the ML prediction explanation, and the line it must not cross.

Section 13.2 names two quantities that share the word "contribution":

* **Scenario-impact attribution** -- why ECL moved from baseline to scenario.
  Measured by re-running the calculation over coalitions of the scenario's own
  interventions, and it reconciles to the ECL change because it IS a
  measurement of it. `attribution.never_add` refuses to sum its two views.
* **ML prediction explanation** -- why the fitted emulator returned its
  number. A statement about a function's response to its own inputs, which
  reconciles to nothing about the scenario.

  > *"Never present feature importance as a decomposition of the scenario ECL
  > movement."*

These tests are the guard rather than the caption: they fail if a feature
ranking is ever published with a currency column, if a feature name appears as
an attribution driver, or if the offline document is built against anything but
the development window.

Measured on GENERATED books. Nothing here is bank output, an accounting figure,
or a bank-validated model.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import attribution as at
from backend.cockpit_v4.scenario.ml import explain as ex

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "whatif"
BOOKS = (dom.CORPORATE, dom.RETAIL)


def built(domain_id: str) -> dict:
    path = ARTIFACTS / domain_id / ex.DOCUMENT
    if not path.exists():
        pytest.skip(f"{path} has not been built in this checkout")
    return json.loads(path.read_text(encoding="utf-8"))


def builder():
    path = ROOT / "scripts" / "whatif" / "build_explanations.py"
    spec = importlib.util.spec_from_file_location("build_explanations", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- 1. the guard ------------------------------------------------------

@pytest.mark.parametrize("column",
                         ["change_sar_mn", "baseline_sar_mn",
                          "scenario_sar_mn"])
def test_a_feature_ranking_carrying_a_currency_column_is_refused(column):
    """The specific error section 13.2 names, caught rather than described."""
    rows = [{"item": "pd_pit_12m", "kind": "feature contribution",
             column: "12.3456"}]
    with pytest.raises(ValueError) as caught:
        ex.never_a_decomposition(rows)
    assert column in str(caught.value)
    assert "not a share of the scenario" in str(caught.value)


def test_a_ranking_in_the_models_own_space_passes_the_guard() -> None:
    ex.never_a_decomposition([
        {"item": "pd_pit_12m", "kind": "feature contribution",
         "unit": "mean |SHAP|, model rate space", "note": "0.0031"},
        {"item": "stage", "kind": "gain importance",
         "unit": "share of split gain", "note": "0.37"},
    ])


def test_the_guard_and_never_add_are_two_different_refusals() -> None:
    """`never_add` stops the two SCENARIO views being summed;
    `never_a_decomposition` stops a PREDICTION explanation being published as
    a scenario decomposition. One is not a substitute for the other, and both
    only ever raise."""
    assert callable(at.never_add)
    assert callable(ex.never_a_decomposition)
    with pytest.raises(ValueError):
        ex.never_a_decomposition([{"item": "stage",
                                   "change_sar_mn": "1.0"}])


# ---- 2. the published document ----------------------------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_the_document_is_built_on_the_development_window_only(domain_id):
    body = built(domain_id)
    assert body["built_on"] == "the DEVELOPMENT window only"
    held = set(body["held_back_and_not_read"])
    development = set(body["development_periods"])
    assert held, "a document that holds nothing back read the test split"
    assert not (held & development), (
        "a period cannot be both developed on and held back; overlap here "
        "means the curves were measured against the untouched split")


#: The result artifact's currency columns. A feature may legitimately be CALLED
#: `balance_sar_mn` -- that is the book's own column name and it is an input to
#: the model, not a scenario measurement. What must never appear is one of
#: these as a KEY or a UNIT, which is the shape a reader or a chart would add
#: to an attribution row.
CURRENCY_KEYS = ("change_sar_mn", "baseline_sar_mn", "scenario_sar_mn",
                 "change_pct")


@pytest.mark.parametrize("domain_id", BOOKS)
def test_the_document_carries_no_currency_column_anywhere(domain_id) -> None:
    """A response curve is a mean prediction in rate space and an importance is
    a share. Neither is money, and a currency KEY here is how a reader starts
    adding one to an ECL movement. A feature NAMED after a money column is
    still just a feature name."""
    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in CURRENCY_KEYS, (
                    f"{path}.{key} is a scenario currency column")
                if key in ("unit", "units"):
                    assert "SAR" not in str(value), (
                        f"{path}.{key} is denominated in riyals: "
                        f"{value!r}. Nothing in a prediction explanation is "
                        f"money.")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(built(domain_id))


@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_importance_is_a_dimensionless_share(domain_id) -> None:
    body = built(domain_id)
    assert body["importance"], "no feature was ranked"
    for row in body["importance"]:
        assert row["unit"] == "share of split gain"
        assert 0.0 < float(row["value"]) <= 1.0
    total = sum(float(r["value"]) for r in body["importance"])
    assert total <= 1.0 + 1e-9, (
        "the shares are weighted by the blend's own weights, so the ranked "
        "subset cannot exceed one")


@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_response_says_it_is_association_not_causation(domain_id):
    body = built(domain_id)
    assert body["responses"], "no response relationship was published"
    for row in body["responses"]:
        assert row["unit"] == "mean prediction, model rate space"
        assert "not causation" in row["shape"]
        assert len(row["curve"]) >= 2, (
            "a relationship needs at least two points to be a relationship")
    assert "NOT a decomposition" in body["not_a_decomposition"]


@pytest.mark.parametrize("domain_id", BOOKS)
def test_a_component_with_no_splits_is_named_rather_than_scored_zero(
        domain_id) -> None:
    """An additive model has no split gain. Treating that as "importance zero
    for every feature" would understate it; saying which components the
    ranking is combined over, and which gave no gain, states it."""
    body = built(domain_id)
    for row in body["importance"]:
        assert row["combined_over"], "a ranking must say what it is over"
    noted = {r["no_gain_from"] for r in body["importance"]}
    assert noted, "the components that contribute no gain are not named"


@pytest.mark.parametrize("domain_id", BOOKS)
def test_the_document_describes_the_model_that_is_published(domain_id) -> None:
    body = built(domain_id)
    manifest = json.loads(
        (ARTIFACTS / domain_id / "blend.json").read_text(encoding="utf-8"))
    assert body["model_version"] == manifest["model_version"]
    assert body["release_id"] == manifest["release_id"]
    assert sorted(body["held_back_and_not_read"]) == \
        sorted(str(p) for p in manifest["test_periods"]), (
            "a document built against a different split than the model "
            "describes a different model")


# ---- 3. absence, and reproducibility ----------------------------------

def test_an_unbuilt_document_is_absence_rather_than_a_failure(tmp_path):
    assert ex.document(dom.CORPORATE, root=tmp_path) == {}


def test_a_corrupt_document_is_absence_rather_than_a_crash(tmp_path) -> None:
    home = tmp_path / dom.CORPORATE
    home.mkdir(parents=True)
    (home / ex.DOCUMENT).write_text("{not json", encoding="utf-8")
    assert ex.document(dom.CORPORATE, root=tmp_path) == {}


def test_the_builder_declares_its_seed_and_its_sample(tmp_path) -> None:
    """The document is part of the model's documentation, so two builds of one
    model must produce one file. That needs a declared seed and a declared
    sample size, not whatever the row order happened to be."""
    module = builder()
    assert isinstance(module.SEED, int)
    assert module.SAMPLE_ROWS > 0
    assert module.GRID_POINTS >= 3
    for domain_id in BOOKS:
        body = built(domain_id)
        assert body["seed"] == module.SEED
        assert body["grid_points"] == module.GRID_POINTS
        assert body["rows_sampled_for_curves"] <= body["rows"]


@pytest.mark.parametrize("domain_id", BOOKS)
def test_the_document_names_no_more_features_than_it_may(domain_id) -> None:
    body = built(domain_id)
    assert len(body["importance"]) <= ex.TOP_FEATURES
    assert len(body["responses"]) <= ex.TOP_FEATURES
