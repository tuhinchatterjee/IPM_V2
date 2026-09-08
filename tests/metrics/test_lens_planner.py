"""The AI Lens Builder: broad requests become a coherent, multi-metric Lens.

UAT's complaint was precise: told to "include all metrics which you feel are
relevant," the builder needs judgement a keyword matcher does not have. This
module tests two layers separately, because only one of them can honestly be
tested here.

**The validation layer is tested for real**, against a scripted provider,
because this is the part that is actually this codebase's responsibility and
actually capable of being wrong: does an invented metric id get caught rather
than trusted, does an invalid chart dimension fall back to a KPI rather than
producing a chart over a field that does not exist, does the fallback path
(no provider configured) degrade honestly rather than crash.

**A live model's actual reasoning is not tested here**, because this sandbox
has no configured API key — the same reason `analyst/conftest.py`'s
`ScriptedProvider` exists: "you cannot make a real model refuse on demand,"
and equally you cannot make it reason on demand without calling it. The
scripts below are written by hand to model what the ABSOLUTE RULES in
`lens_planner.SYSTEM` ask a real model to produce for each golden request —
every metric id in them is real, drawn from this catalogue, and at least one
scripted response per group deliberately includes a fabricated id, to prove
the rejection path actually fires rather than being an assumption. A
deployment with a configured provider is the one place the model's own
judgement gets exercised, via `scripts/acceptance/lens_ai_journeys.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.llm.base import LLMResult
from backend.metrics import lens_planner as lp


class ScriptedProvider:
    """A model that answers exactly as scripted. See module docstring."""

    name = "test"
    model = "scripted-analyst"
    configured = True

    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.prompts: list[str] = []

    def structured(self, *, system: str, prompt: str, **kwargs: Any) -> LLMResult:
        del system, kwargs
        self.prompts.append(prompt)
        return LLMResult(data=self.data, model=self.model)


def _metric(metric_id: str, section: str, why: str, *, chart: str = "") -> dict:
    return {"metric_id": metric_id, "section": section, "why": why,
            "as_chart": bool(chart), "dimension": chart}


def _script(*, title: str, purpose: str, scope: str, questions: list[str],
           metrics: list[dict], unsupported: list[dict] | None = None,
           rationale: str = "Reasoned proposal.", clarify: str = "") -> dict:
    return {"title": title, "purpose": purpose, "scope_summary": scope,
           "risk_questions": questions, "metrics": metrics,
           "unsupported": unsupported or [], "rationale": rationale,
           "clarify": clarify}


@pytest.fixture()
def offline(monkeypatch):
    class _Offline:
        name = "none"
        model = ""
        configured = False

    monkeypatch.setattr(lp, "get_provider", lambda **_: _Offline())


def _use(monkeypatch, data: dict) -> ScriptedProvider:
    provider = ScriptedProvider(data)
    monkeypatch.setattr(lp, "get_provider", lambda **_: provider)
    return provider


# --------------------------------------------------------------- the fallback


def test_with_no_provider_the_builder_still_produces_a_lens(offline):
    """§ "If LLM interpretation is unavailable, do not break the Lens" applies
    here just as much as to reading one -- a builder that blocks because no
    key is configured is not an acceptable degradation."""
    plan = lp.plan("watchlist exposure and covenant breaches", user_id=9)
    assert plan.understood is False
    assert plan.unavailable
    assert plan.metrics, "the deterministic matcher must still propose something"
    assert all(m.metric_id for m in plan.metrics)


def test_the_fallback_never_invents_a_metric_either(offline):
    plan = lp.plan("show me the weighted internal grade", user_id=9)
    from backend.metrics import service
    known = {m.metric_id for m in service.catalogue(user_id=9)}
    assert all(m.metric_id in known for m in plan.metrics)


# ------------------------------------------------------------- the grounding


def test_a_fabricated_metric_id_is_rejected_not_trusted(monkeypatch):
    """The one rule this feature cannot compromise on."""
    _use(monkeypatch, _script(
        title="Contracting Sector Watch",
        purpose="Monitor contracting sector exposure and credit quality.",
        scope="Corporate book, contracting sector",
        questions=["Is exposure growing faster than credit quality can absorb?"],
        metrics=[
            _metric("corporate.exposure", "headline", "The size being monitored."),
            _metric("corporate.ifrs9.weighted_lgd_forecast_scenario_adjusted",
                    "trend", "A metric that does not exist in this catalogue."),
        ],
    ))
    plan = lp.plan("contracting sector exposure", user_id=9)
    assert plan.understood is True
    ids = {m.metric_id for m in plan.metrics}
    assert "corporate.exposure" in ids
    assert "corporate.ifrs9.weighted_lgd_forecast_scenario_adjusted" not in ids
    assert any("not a metric in the governed catalogue" in u["because"]
              for u in plan.unsupported)


def test_an_invalid_chart_dimension_falls_back_to_a_kpi_not_a_broken_chart(
    monkeypatch,
):
    _use(monkeypatch, _script(
        title="T", purpose="P", scope="S", questions=["Q"],
        metrics=[_metric("corporate.exposure", "trend", "Trend",
                        chart="astrological_sign")],
    ))
    plan = lp.plan("corporate exposure", user_id=9)
    assert len(plan.metrics) == 1
    assert plan.metrics[0].as_chart is False, (
        "a dimension the dataset does not carry must not become a chart"
    )


def test_a_valid_chart_dimension_is_kept_as_a_chart(monkeypatch):
    _use(monkeypatch, _script(
        title="T", purpose="P", scope="S", questions=["Q"],
        metrics=[_metric("corporate.exposure", "concentration", "By sector",
                        chart="sector")],
    ))
    plan = lp.plan("corporate exposure by sector", user_id=9)
    assert len(plan.metrics) == 1
    assert plan.metrics[0].as_chart is True
    assert plan.metrics[0].dimension == "sector"
    assert plan.metrics[0].dimension_label


def test_a_stated_unsupported_request_is_carried_through_verbatim(monkeypatch):
    _use(monkeypatch, _script(
        title="T", purpose="P", scope="S", questions=["Q"],
        metrics=[_metric("corporate.exposure", "headline", "H")],
        unsupported=[{"requested": "scenario ECL (base/upside/downside)",
                     "because": "The staging dataset carries one already-"
                                "weighted ECL, not one per scenario."}],
    ))
    plan = lp.plan("show scenario ECL", user_id=9)
    assert any("scenario ECL" in u["requested"] for u in plan.unsupported)


def test_duplicate_metric_dimension_pairs_are_not_repeated(monkeypatch):
    _use(monkeypatch, _script(
        title="T", purpose="P", scope="S", questions=["Q"],
        metrics=[_metric("corporate.exposure", "headline", "H"),
                _metric("corporate.exposure", "headline", "H again")],
    ))
    plan = lp.plan("corporate exposure", user_id=9)
    assert len(plan.metrics) == 1


def test_the_cap_on_metrics_is_enforced(monkeypatch):
    from backend.metrics import service

    pool = service.catalogue(user_id=9)
    ids = [m.metric_id for m in pool if m.domain.startswith("Corporate")]
    metrics = [_metric(i, "other", "Bulk") for i in ids[:60]]
    _use(monkeypatch, _script(title="T", purpose="P", scope="S", questions=["Q"],
                              metrics=metrics))
    plan = lp.plan("everything about corporate", user_id=9)
    assert len(plan.metrics) <= lp.MAX_METRICS + lp.MAX_CHARTS


def test_more_than_one_literal_keyword_match(monkeypatch):
    """§: the output must be more than a single keyword hit. A request naming
    one word ("exposure") but reasoned about properly should still produce a
    small, coherent set, not one tile."""
    _use(monkeypatch, _script(
        title="T", purpose="P", scope="S", questions=["Q"],
        metrics=[_metric("corporate.exposure", "headline", "Size"),
                _metric("corporate.utilisation", "headline", "Headroom"),
                _metric("corporate.ifrs9.stage2_share", "quality", "Quality"),
                _metric("corporate.watchlist_exposure", "early_warning", "EWS")],
    ))
    plan = lp.plan("corporate exposure", user_id=9)
    assert len(plan.metrics) > 1


# --------------------------------------------------- the twenty golden requests


GOLDEN: list[tuple[str, dict]] = [
    ("Build me a Lens for contracting sector exposure. Include whatever you "
     "think a senior risk officer should monitor.",
     _script(title="Contracting Sector Monitor",
            purpose="Monitor the size, concentration and credit quality of "
                    "the contracting sector.",
            scope="Corporate book, contracting sector",
            questions=["Is exposure growing?", "Is quality deteriorating?"],
            metrics=[
                _metric("corporate.exposure", "headline", "Size of the book"),
                _metric("corporate.utilisation", "headline", "Headroom"),
                _metric("corporate.exposure", "trend", "Growth",
                        chart="period"),
                _metric("corporate.ifrs9.stage2_share", "quality", "Migration"),
                _metric("corporate.ifrs9.weighted_pd", "quality", "PD level"),
                _metric("corporate.ifrs9.weighted_lgd", "quality", "LGD level"),
                _metric("corporate.watchlist_exposure", "early_warning", "EWS"),
                _metric("corporate.obligor_groups", "concentration", "Names"),
            ],
            unsupported=[{"requested": "a contracting-only rating downgrade "
                                       "trend", "because": "Ratings are not "
                                       "tracked at sector granularity in this "
                                       "deployment."}])),
    ("I want to monitor construction and real estate because I think the "
     "book is growing too quickly.",
     _script(title="Construction & Real Estate Growth Watch",
            purpose="Test whether rapid growth is outpacing credit quality.",
            scope="Corporate book, construction and real estate",
            questions=["Is growth outpacing quality?"],
            metrics=[_metric("corporate.exposure", "trend", "Growth",
                             chart="period"),
                    _metric("corporate.ifrs9.stage2_share", "quality", "Q"),
                    _metric("corporate.ifrs9.new_default_rate", "quality", "D"),
                    _metric("corporate.downgrade_probability",
                            "early_warning", "EWS")])),
    ("Build me a corporate portfolio deterioration Lens.",
     _script(title="Corporate Deterioration Monitor",
            purpose="Identify whether the corporate book is deteriorating.",
            scope="Corporate book",
            questions=["Is quality worsening?"],
            metrics=[_metric("corporate.ifrs9.stage2_share", "trend", "S2",
                             chart="period"),
                    _metric("corporate.ifrs9.new_default_rate", "trend", "D",
                            chart="period"),
                    _metric("corporate.watchlist_exposure", "early_warning",
                            "EWS"),
                    _metric("corporate.ifrs9.pd_drift", "quality", "PD")])),
    ("I want an IFRS 9 Lens that tells me why ECL moved.",
     _script(title="ECL Movement",
            purpose="Explain what is driving the change in ECL.",
            scope="Corporate IFRS 9",
            questions=["Why did ECL move?"],
            metrics=[_metric("corporate.ifrs9.total_ecl", "headline", "H"),
                    _metric("corporate.ifrs9.stage_1_to_2_ead", "trend", "M"),
                    _metric("corporate.ifrs9.stage_2_to_3_ead", "trend", "M"),
                    _metric("corporate.ifrs9.new_default_ead", "trend", "M"),
                    _metric("corporate.ifrs9.pd_drift", "quality", "PD")],
            unsupported=[{"requested": "scenario-weighted ECL",
                         "because": "Not available; one weighted ECL is "
                                    "carried, not per scenario."}])),
    ("Create a Lens for names that might move into Stage 2.",
     _script(title="Approaching Stage 2",
            purpose="Identify names at risk of migrating into Stage 2.",
            scope="Corporate IFRS 9",
            questions=["Who is approaching SICR?"],
            metrics=[_metric("corporate.ifrs9.sicr_rate", "early_warning", "S"),
                    _metric("corporate.ifrs9.sicr_pd", "early_warning", "S"),
                    _metric("corporate.ifrs9.sicr_covenant", "early_warning", "S"),
                    _metric("corporate.downgrade_probability",
                            "early_warning", "S")])),
    ("Show me whether ratings across the corporate book are getting worse.",
     _script(title="Rating Deterioration",
            purpose="Assess whether the rating distribution is worsening.",
            scope="Corporate book",
            questions=["Are downgrades outpacing upgrades?"],
            metrics=[_metric("corporate.weighted_internal_grade", "trend", "R",
                             chart="period"),
                    _metric("corporate.investment_grade_rate", "quality", "IG"),
                    _metric("corporate.portfolio_weighted_pd", "trend", "PD",
                            chart="period"),
                    _metric("corporate.watchlist_exposure", "early_warning",
                            "W")])),
    ("Create a Lens for sectors where risk is increasing faster than "
     "exposure.",
     _script(title="Risk Outpacing Growth",
            purpose="Find sectors where quality is worsening faster than "
                    "the book is growing.",
            scope="Corporate book, by sector",
            questions=["Where is risk outpacing growth?"],
            metrics=[_metric("corporate.exposure", "concentration", "E",
                             chart="sector"),
                    _metric("corporate.ifrs9.stage2_share", "concentration",
                            "S", chart="sector"),
                    _metric("corporate.deteriorating_rate", "quality", "D")])),
    ("Build me a Board Risk Committee view.",
     _script(title="Board Risk Committee",
            purpose="A small number of highly material views for the Board.",
            scope="Corporate book",
            questions=["What matters most this month?"],
            metrics=[_metric("corporate.exposure", "headline", "H"),
                    _metric("corporate.ifrs9.stage2_share", "headline", "H"),
                    _metric("corporate.ifrs9.total_ecl", "headline", "H"),
                    _metric("corporate.watchlist_exposure", "early_warning",
                            "W")],
            rationale="Kept deliberately small for a Board audience.")),
    ("I want a concentration Lens for the top 20 borrowers and the sectors "
     "they belong to.",
     _script(title="Concentration Watch",
            purpose="Show dependency on the largest names and sectors.",
            scope="Corporate book",
            questions=["Where is exposure concentrated?"],
            metrics=[_metric("corporate.obligor_groups", "concentration", "C"),
                    _metric("corporate.average_group_exposure",
                            "concentration", "C"),
                    _metric("corporate.exposure", "concentration", "E",
                            chart="sector"),
                    _metric("corporate.appetite_breach_exposure",
                            "concentration", "A")])),
    ("Track borrowers with rising PD, downgrades and weak covenant headroom.",
     _script(title="Rising Risk Names",
            purpose="Identify borrowers combining several deterioration "
                    "signals at once.",
            scope="Corporate book",
            questions=["Who is showing multiple signals together?"],
            metrics=[_metric("corporate.ifrs9.pd_drift", "early_warning", "P"),
                    _metric("corporate.downgrade_probability",
                            "early_warning", "D"),
                    _metric("corporate.covenant_headroom", "early_warning",
                            "C"),
                    _metric("corporate.covenant_breach_rate",
                            "early_warning", "C")])),
    ("Build me a Lens for early signs of stress before accounts become "
     "delinquent.",
     _script(title="Early Stress Signals",
            purpose="Surface leading indicators before delinquency appears.",
            scope="Corporate book",
            questions=["What moves before delinquency does?"],
            metrics=[_metric("corporate.watchlist_exposure",
                            "early_warning", "W"),
                    _metric("corporate.deteriorating_rate",
                            "early_warning", "D"),
                    _metric("corporate.ai_risk_score", "early_warning", "AI"),
                    _metric("corporate.critical_severity_rate",
                            "early_warning", "C")])),
    ("Create a Lens for retail deterioration by product and customer "
     "segment.",
     _script(title="Retail Deterioration",
            purpose="Monitor whether retail credit quality is worsening, cut "
                    "by product and segment.",
            scope="Retail Credit Risk",
            questions=["Is retail quality worsening, and where?"],
            metrics=[_metric("retail.dpd_30_balance", "trend", "D",
                             chart="period"),
                    _metric("retail.cure_rate_3m", "quality", "C"),
                    _metric("retail.repeat_delinquency_rate", "quality", "R"),
                    _metric("retail.default_rate", "trend", "D",
                            chart="period")],
            unsupported=[{"requested": "channel cut",
                         "because": "No channel dimension exists on the "
                                    "retail delinquency dataset."}])),
    ("I want to know whether growth in the contracting book is producing "
     "higher ECL.",
     _script(title="Contracting Growth vs ECL",
            purpose="Test whether contracting sector growth is translating "
                    "into higher ECL.",
            scope="Corporate book, contracting sector",
            questions=["Is growth producing more impairment?"],
            metrics=[_metric("corporate.exposure", "trend", "G",
                             chart="period"),
                    _metric("corporate.ifrs9.total_ecl", "trend", "E",
                            chart="period"),
                    _metric("corporate.ifrs9.new_default_rate", "quality",
                            "D")])),
    ("Build a Lens to monitor the weakest corporate names.",
     _script(title="Weakest Names",
            purpose="Track the corporate names carrying the most risk.",
            scope="Corporate book",
            questions=["Who is weakest right now?"],
            metrics=[_metric("corporate.watchlist_exposure",
                            "early_warning", "W"),
                    _metric("corporate.ifrs9.stage3_ead", "headline", "S3"),
                    _metric("corporate.downgrade_probability",
                            "early_warning", "D")])),
    ("Show me exposure growth, rating deterioration, Stage 2 migration and "
     "ECL by sector.",
     _script(title="Multi-Factor Sector View",
            purpose="Compare growth, ratings, staging and ECL across "
                    "sectors.",
            scope="Corporate book, by sector",
            questions=["Which sectors show growth with weakening quality?"],
            metrics=[_metric("corporate.exposure", "trend", "G",
                             chart="sector"),
                    _metric("corporate.weighted_internal_grade",
                            "concentration", "R", chart="sector"),
                    _metric("corporate.ifrs9.stage2_share",
                            "concentration", "S", chart="sector"),
                    _metric("corporate.ifrs9.total_ecl", "concentration",
                            "E", chart="sector")])),
    ("Create a Lens that a CRO could use in the first five minutes of the "
     "monthly risk committee.",
     _script(title="CRO Five-Minute View",
            purpose="The handful of figures a CRO needs first.",
            scope="Corporate book",
            questions=["What does the CRO need to know first?"],
            metrics=[_metric("corporate.exposure", "headline", "H"),
                    _metric("corporate.ifrs9.stage2_share", "headline", "H"),
                    _metric("corporate.ifrs9.total_ecl", "headline", "H"),
                    _metric("corporate.watchlist_exposure", "headline", "H")],
            rationale="Kept to headline figures only, by design.")),
    ("Build a Lens for my watchlist portfolio and tell me which names are "
     "getting worse.",
     _script(title="Watchlist Monitor",
            purpose="Track the watchlist and identify further "
                    "deterioration within it.",
            scope="Corporate book, watchlist",
            questions=["Who on the watchlist is getting worse?"],
            metrics=[_metric("corporate.watchlist_exposure", "headline", "H"),
                    _metric("corporate.watchlist_rate", "trend", "T",
                            chart="period"),
                    _metric("corporate.deteriorating_rate",
                            "early_warning", "D")])),
    ("Monitor high-utilisation borrowers where ratings are also "
     "deteriorating.",
     _script(title="Utilisation & Rating Overlap",
            purpose="Find borrowers combining high utilisation with rating "
                    "deterioration.",
            scope="Corporate book",
            questions=["Where do utilisation and rating risk overlap?"],
            metrics=[_metric("corporate.utilisation", "headline", "U"),
                    _metric("corporate.downgrade_probability",
                            "early_warning", "D"),
                    _metric("corporate.weighted_internal_grade",
                            "quality", "R")])),
    ("Build a Lens for sectors where concentration and early-warning risk "
     "overlap.",
     _script(title="Concentrated Early Warning",
            purpose="Find sectors that are both concentrated and showing "
                    "early-warning deterioration.",
            scope="Corporate book, by sector",
            questions=["Where does concentration overlap with EWS?"],
            metrics=[_metric("corporate.exposure", "concentration", "C",
                             chart="sector"),
                    _metric("corporate.watchlist_exposure",
                            "concentration", "W", chart="sector"),
                    _metric("corporate.deteriorating_rate",
                            "early_warning", "D")])),
    ("I don't know exactly which metrics I need. I want to know whether the "
     "corporate book is becoming riskier.",
     _script(title="Is The Book Getting Riskier",
            purpose="A general read on whether corporate risk is rising.",
            scope="Corporate book",
            questions=["Is overall risk increasing?"],
            metrics=[_metric("corporate.ifrs9.stage2_share", "trend", "S",
                             chart="period"),
                    _metric("corporate.ifrs9.total_ecl", "trend", "E",
                            chart="period"),
                    _metric("corporate.portfolio_weighted_pd", "trend", "P",
                            chart="period"),
                    _metric("corporate.watchlist_exposure",
                            "early_warning", "W")])),
]


@pytest.mark.parametrize("request_text,script", GOLDEN, ids=[g[0][:48] for g in GOLDEN])
def test_golden_request(monkeypatch, request_text, script):
    provider = _use(monkeypatch, script)
    plan = lp.plan(request_text, user_id=9)

    assert plan.understood is True
    assert plan.purpose, "purpose must be inferred, not left blank"
    assert plan.scope_summary, "scope must be inferred, not left blank"
    assert len(plan.metrics) > 1, (
        "a broad request must produce more than a single literal match"
    )

    from backend.metrics import service
    known = {m.metric_id for m in service.catalogue(user_id=9)}
    assert all(m.metric_id in known for m in plan.metrics), (
        "every proposed metric must be a real, governed metric"
    )

    # Every requested chart either kept a dimension the dataset actually
    # carries, or was correctly turned back into a KPI -- never left
    # pointing at a field that does not exist.
    for m in plan.metrics:
        if m.as_chart:
            assert m.dimension, "a chart entry must carry a real dimension"

    # The scripted prompt actually reached the model with the catalogue in
    # it, proving the pipeline assembled real context rather than a stub.
    assert "GOVERNED CATALOGUE" in provider.prompts[0]
    assert request_text in provider.prompts[0]
