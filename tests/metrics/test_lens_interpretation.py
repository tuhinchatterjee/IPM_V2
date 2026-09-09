"""Every Lens should say what it means, not only what it shows.

UAT: the CRO Lens "opens directly into metric cards... there is no AI
interpretation explaining what the user should conclude." This tests the
service that closes that gap, against a scripted provider for the reasons
`test_lens_planner.py`'s module docstring already gives — this sandbox has no
live model, so what is tested is the part that actually is this codebase's
responsibility: grounding (a number the Lens does not show must never survive
into the written reading), the graceful failure mode (no provider, no
tiles, a call that raises — none of them may ever look like a broken Lens),
and caching (the same rendered data must not cost a second call, and
different data must never be served from the first one's cache).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.llm.base import LLMResult
from backend.metrics import lens_interpretation as li


class ScriptedProvider:
    name = "test"
    model = "scripted-analyst"
    configured = True

    def __init__(self, data: dict[str, Any] | None = None, raises: Exception | None = None):
        self.data = data
        self.raises = raises
        self.calls = 0

    def structured(self, **kwargs: Any) -> LLMResult:
        del kwargs
        self.calls += 1
        if self.raises:
            raise self.raises
        return LLMResult(data=self.data, model=self.model)


LENS = {"name": "Corporate IFRS 9", "audience": "IFRS 9 Committee",
       "description": "Where the book sits across the three stages."}


def _rendered(*, stage2=11.8, ecl_value=None) -> dict[str, Any]:
    panels = [
        {"kind": "metric", "metric_id": "corporate.ifrs9.stage2_share",
         "title": "Stage 2 Ratio", "status": "succeeded", "value": stage2 / 100,
         "unit": "percent", "decimals": 1,
         "metric": {"definition": "Exposure in Stage 2 over total exposure."}},
        {"kind": "metric", "metric_id": "corporate.exposure",
         "title": "Corporate Exposure", "status": "succeeded", "value": 74_000,
         "unit": "currency", "decimals": 0, "metric": {"definition": "Total exposure."}},
    ]
    if ecl_value is not None:
        panels.append({"kind": "metric", "metric_id": "corporate.ifrs9.total_ecl",
                       "title": "Total ECL", "status": "succeeded",
                       "value": ecl_value, "unit": "currency", "decimals": 0,
                       "metric": {"definition": "Total ECL."}})
    return {"panels": panels, "scope": {"default_period": "Q2 2026"}}


def _use(monkeypatch, provider: ScriptedProvider) -> None:
    monkeypatch.setattr(li, "get_provider", lambda **_: provider)


@pytest.fixture(autouse=True)
def _clear_cache():
    li._cache.reset()
    yield
    li._cache.reset()


# ----------------------------------------------------------- graceful failure


def test_no_provider_configured_returns_unavailable(monkeypatch):
    class Offline:
        name = "none"
        model = ""
        configured = False

    monkeypatch.setattr(li, "get_provider", lambda **_: Offline())
    result = li.interpret(LENS, _rendered(), None)
    assert result.live is False
    assert "temporarily unavailable" in result.unavailable
    assert result.headline == ""


def test_a_provider_that_raises_degrades_gracefully(monkeypatch):
    _use(monkeypatch, ScriptedProvider(raises=RuntimeError("provider offline")))
    result = li.interpret(LENS, _rendered(), None)
    assert result.live is False
    assert "temporarily unavailable" in result.unavailable


def test_a_lens_with_no_succeeding_tiles_is_not_sent_to_the_model(monkeypatch):
    provider = ScriptedProvider(data={"headline": "H", "narrative": "N",
                                      "observations": []})
    _use(monkeypatch, provider)
    empty = {"panels": [{"kind": "metric", "metric_id": "x", "status": "failed"}],
            "scope": {}}
    result = li.interpret(LENS, empty, None)
    assert result.live is False
    assert provider.calls == 0


# ------------------------------------------------------------------ grounding


def test_a_grounded_reading_is_kept(monkeypatch):
    _use(monkeypatch, ScriptedProvider(data={
        "headline": "Stage 2 has risen to 11.8%.",
        "narrative": "Exposure stands at 74,000 while Stage 2 sits at 11.8%.",
        "observations": [{"text": "Stage 2 Ratio is 11.8%.",
                          "metric_names": ["Stage 2 Ratio"]}],
    }))
    result = li.interpret(LENS, _rendered(), None)
    assert result.live is True
    assert result.ungrounded == []
    assert "11.8%" in result.headline


def test_a_fabricated_figure_discards_the_whole_reading(monkeypatch):
    """The defect that matters: a number nobody can check, stated as fact."""
    _use(monkeypatch, ScriptedProvider(data={
        "headline": "Stage 2 has risen sharply to 47.3%.",
        "narrative": "This is a real concern.",
        "observations": [],
    }))
    result = li.interpret(LENS, _rendered(), None)
    assert result.live is False
    assert any("47.3" in u for u in result.ungrounded)
    assert "temporarily unavailable" in result.unavailable


def test_a_delta_figure_is_grounded_when_a_prior_period_is_given(monkeypatch):
    _use(monkeypatch, ScriptedProvider(data={
        "headline": "Stage 2 rose by 2.3%.",
        "narrative": "N",
        "observations": [],
    }))
    result = li.interpret(LENS, _rendered(stage2=11.8), _rendered(stage2=9.5))
    assert result.live is True, result.ungrounded


def test_an_observation_naming_an_unknown_tile_is_stripped_not_discarded(monkeypatch):
    """Referencing a tile that is not actually on this Lens is a smaller
    problem than a fabricated number, so only the reference is dropped."""
    _use(monkeypatch, ScriptedProvider(data={
        "headline": "H", "narrative": "N",
        "observations": [{"text": "Something moved.",
                          "metric_names": ["Stage 2 Ratio", "A Made-Up Tile"]}],
    }))
    result = li.interpret(LENS, _rendered(), None)
    assert result.live is True
    assert result.observations[0].metric_names == ["Stage 2 Ratio"]


# --------------------------------------------------------------------- caching


def test_identical_data_is_served_from_cache_not_a_second_call(monkeypatch):
    provider = ScriptedProvider(data={"headline": "H", "narrative": "N",
                                      "observations": []})
    _use(monkeypatch, provider)
    rendered = _rendered()
    first = li.interpret(LENS, rendered, None)
    second = li.interpret(LENS, rendered, None)
    assert provider.calls == 1
    assert first.cached is False
    assert second.cached is True
    assert second.headline == first.headline


def test_a_changed_figure_is_not_served_from_the_old_cache(monkeypatch):
    provider = ScriptedProvider(data={"headline": "H", "narrative": "N",
                                      "observations": []})
    _use(monkeypatch, provider)
    li.interpret(LENS, _rendered(stage2=11.8), None)
    li.interpret(LENS, _rendered(stage2=15.0), None)
    assert provider.calls == 2


def test_a_different_period_is_not_served_from_the_old_cache(monkeypatch):
    provider = ScriptedProvider(data={"headline": "H", "narrative": "N",
                                      "observations": []})
    _use(monkeypatch, provider)
    rendered_q2 = _rendered()
    rendered_q2["scope"] = {"default_period": "Q2 2026"}
    rendered_q3 = _rendered()
    rendered_q3["scope"] = {"default_period": "Q3 2026"}
    li.interpret(LENS, rendered_q2, None)
    li.interpret(LENS, rendered_q3, None)
    assert provider.calls == 2
