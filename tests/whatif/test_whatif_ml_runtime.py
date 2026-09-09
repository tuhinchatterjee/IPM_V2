"""
Can the ML methodology run here, and which design does it serve?

Two failures found in manual acceptance, and they are the same failure twice:
the product asserted something about the model instead of checking it.

**It offered a methodology the machine could not run.** XGBoost is a wrapper
around a compiled library, and on macOS that library needs OpenMP, which Apple
does not ship. The import raised, and the screen showed the dynamic-linker
path. A credit officer read `Library not loaded: @rpath/libomp.dylib` where an
expected credit loss should have been.

**It served one design and reported another.** The training run fits a single
stage-aware model and one model per Stage, scores both, and records which won.
Nothing acted on the verdict, so when the rebuilt book changed the answer the
card said "one model per Stage" while the product scored every row on one
model. A study whose conclusion nothing obeys is decoration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.whatif.ml import ensemble as en
from backend.whatif.ml import registry as rg
from backend.whatif.ml import runtime as rt


class TestThePortabilityPreflight:
    def test_it_reports_whether_xgboost_loads_here(self) -> None:
        found = rt.check()
        assert isinstance(found.available, bool)
        assert found.platform_name

    def test_an_available_runtime_names_its_version(self) -> None:
        found = rt.check()
        if not found.available:
            pytest.skip("this installation cannot run XGBoost")
        assert found.version
        assert "available" in found.message()

    def test_every_platform_it_knows_has_a_remedy_and_a_command(self) -> None:
        for name, remedy in rt.REMEDY.items():
            assert remedy["cause"], name
            assert remedy["command"], name
            assert remedy["then"], name

    def test_a_failure_is_a_sentence_not_a_traceback(self) -> None:
        """Composed rather than caught, so the wording is asserted on every
        platform and not only on the one that happens to be broken."""
        failed = rt.Availability(
            available=False, platform_name="Darwin arm64",
            reason="XGBoost is installed but its compiled library will not load.",
            cause=rt.REMEDY["darwin"]["cause"],
            command=rt.REMEDY["darwin"]["command"],
            then=rt.REMEDY["darwin"]["then"],
            detail="dlopen(...): Library not loaded: @rpath/libomp.dylib")
        said = failed.message()
        assert "cannot run on this installation" in said
        assert "brew install libomp" in said
        assert "Delta Model" in said, (
            "a failure with no way to keep working is a dead end")
        assert "@rpath" not in said, "the linker path is for the log, not the screen"
        assert "Traceback" not in said

    def test_the_raw_error_is_kept_for_the_log(self) -> None:
        failed = rt.Availability(available=False, detail="dlopen failed")
        assert failed.detail
        assert failed.detail not in failed.message()

    def test_the_description_says_when_the_check_happens(self) -> None:
        body = rt.describe()
        assert body["preflight_version"]
        assert "before the methodology is offered" in body["statement"]

    def test_requiring_it_raises_the_readable_error(self, monkeypatch) -> None:
        monkeypatch.setattr(rt, "check", lambda: rt.Availability(
            available=False, cause="No OpenMP.", command="brew install libomp"))
        with pytest.raises(rt.MLUnavailable) as raised:
            rt.require()
        assert "brew install libomp" in str(raised.value)
        assert "Delta Model" in str(raised.value)


class _Constant:
    """A stand-in booster. The ensemble's job is routing, not arithmetic."""

    def __init__(self, value: float):
        self.value = value

    def predict(self, X):
        return np.full(len(X), self.value, dtype=float)


class TestTheEnsembleRoutes:
    @pytest.fixture
    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"stage": [1, 2, 3, 2, 1], "pd_12m": [1.0] * 5})

    def test_a_single_design_scores_every_row_on_one_model(self, frame) -> None:
        one = en.StageEnsemble(fallback=_Constant(0.5), design=en.SINGLE)
        assert not one.routes
        assert list(one.predict(frame)) == [0.5] * 5

    def test_a_per_stage_design_scores_each_row_on_its_own_stage(self, frame) -> None:
        many = en.StageEnsemble(
            fallback=_Constant(0.0),
            members={1: _Constant(0.1), 2: _Constant(0.2), 3: _Constant(0.3)},
            design=en.PER_STAGE)
        assert many.routes
        assert list(many.predict(frame)) == [0.1, 0.2, 0.3, 0.2, 0.1]

    def test_a_stage_with_no_model_of_its_own_falls_back(self, frame) -> None:
        """A Stage too thin to support a model is scored by the all-book one,
        which is why the fallback is always fitted and always stored."""
        partial = en.StageEnsemble(
            fallback=_Constant(0.9),
            members={1: _Constant(0.1), 2: _Constant(0.2)},
            design=en.PER_STAGE)
        assert list(partial.predict(frame)) == [0.1, 0.2, 0.9, 0.2, 0.1]

    def test_the_order_of_the_answer_is_the_order_of_the_question(self) -> None:
        """A prediction returned in a different order than the frame it was
        asked about attributes one borrower's provision to another."""
        frame = pd.DataFrame({"stage": [3, 1, 2, 1, 3, 2]})
        many = en.StageEnsemble(
            fallback=_Constant(0.0),
            members={1: _Constant(1.0), 2: _Constant(2.0), 3: _Constant(3.0)},
            design=en.PER_STAGE)
        assert list(many.predict(frame)) == [3.0, 1.0, 2.0, 1.0, 3.0, 2.0]

    def test_an_ensemble_with_no_members_is_the_single_design(self) -> None:
        assert en.StageEnsemble(fallback=_Constant(1.0),
                                design=en.PER_STAGE).design == en.SINGLE

    def test_it_refuses_a_design_it_does_not_have(self) -> None:
        with pytest.raises(en.EnsembleError):
            en.StageEnsemble(fallback=_Constant(1.0), design="whatever")

    def test_it_refuses_an_ensemble_with_no_fallback(self) -> None:
        with pytest.raises(en.EnsembleError):
            en.StageEnsemble(fallback=None)

    def test_it_refuses_an_artifact_that_is_not_json(self) -> None:
        with pytest.raises(en.EnsembleError) as raised:
            en.load(b"\\x80\\x04\\x95 a pickle")
        assert "a pickle is a program" in str(raised.value)


class TestTheStoredModel:
    def test_the_artifact_is_json(self) -> None:
        card = rg.active()
        if card is None:
            pytest.skip("no model has been trained in this installation")
        path = rg.root() / card.version / rg.ARTIFACT
        assert path.read_bytes().lstrip().startswith(b"{")

    def test_it_reads_back_and_predicts_the_same_way(self) -> None:
        from backend.whatif.ml import features as ft
        from backend.whatif.ml import train as tr

        card = rg.active()
        if card is None:
            pytest.skip("no model has been trained in this installation")
        served = rg.load_booster(card.version)
        split = tr.Split.from_dict(card.split)
        frame = tr.load(split.out_of_time[-1:])
        if frame.empty:
            pytest.skip("the lake has not been built")
        X = ft.build(frame, encoding=ft.Encoding.from_dict(card.encoding)).X
        first = served.predict(X)
        second = rg.load_booster(card.version).predict(X)
        assert np.allclose(first, second)

    def test_the_card_says_which_design_it_serves(self) -> None:
        card = rg.active()
        if card is None:
            pytest.skip("no model has been trained in this installation")
        assert card.design in en.DESIGNS
        assert rg.load_booster(card.version).design == card.design
