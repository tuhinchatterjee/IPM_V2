"""
Scenario Lab: named presets and the question memory.

The two behaviours that make the lab interactive rather than a blank prompt box:
a preset SETS a fully specified shock, and every question asked is remembered and
offered back on the next visit.
"""

import pytest
from dash import dcc

import app as A
import backend.data_loader as dl
import backend.stress_lab as sl


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def _ids(tree, of_type):
    return [n.id for n in _walk(A.html.Div(tree))
            if isinstance(getattr(n, "id", None), dict) and n.id.get("type") == of_type]


# ------------------------------------------------------------------- presets

def test_every_preset_is_fully_specified():
    assert len(sl.PRESETS) >= 5
    for p in sl.PRESETS:
        assert p["id"] and p["label"] and p["detail"] and p["rationale"]
        assert isinstance(p["rate_shock_bps"], (int, float))
        assert isinstance(p["cre_price_shock_pct"], (int, float))
        assert p["tone"] in {"neutral", "amber", "red"}


def test_preset_ids_are_unique():
    ids = [p["id"] for p in sl.PRESETS]
    assert len(ids) == len(set(ids))


def test_preset_sets_rather_than_accumulates():
    """Picking 'Severe adverse' must mean severe adverse — not severe adverse on
    top of whatever the previous turns had already stacked up."""
    existing = {"rate_shock_bps": 250, "cre_price_shock_pct": 10}
    applied = sl.apply_preset("severe", existing)
    spec = sl.preset("severe")
    assert applied["rate_shock_bps"] == spec["rate_shock_bps"]
    assert applied["cre_price_shock_pct"] == spec["cre_price_shock_pct"]


def test_reset_preset_clears_the_shock():
    applied = sl.apply_preset("base", {"rate_shock_bps": 400, "cre_price_shock_pct": 30})
    assert applied["rate_shock_bps"] == 0 and applied["cre_price_shock_pct"] == 0


def test_unknown_preset_leaves_params_untouched():
    existing = {"rate_shock_bps": 100, "cre_price_shock_pct": 5}
    assert sl.apply_preset("nope", existing) == existing


@pytest.mark.parametrize("preset_id", [p["id"] for p in sl.PRESETS])
def test_every_preset_runs_through_the_engine(preset_id):
    params = sl.apply_preset(preset_id)
    result = dl.compute_stress_scenario(dl.DEFAULT_QUARTER, params["rate_shock_bps"],
                                        params["cre_price_shock_pct"])
    assert result["stressed_ecl"] > 0
    assert sl.preset_reply(sl.preset(preset_id), result)


def test_severity_ordering_is_monotone():
    """A harsher preset must not produce a smaller loss — otherwise the labels
    mislead about which scenario is worse."""
    def ecl(pid):
        p = sl.apply_preset(pid)
        return dl.compute_stress_scenario(dl.DEFAULT_QUARTER, p["rate_shock_bps"],
                                          p["cre_price_shock_pct"])["stressed_ecl"]

    assert ecl("base") < ecl("rates_100") < ecl("rates_300") < ecl("severe")


def test_describe_params_states_the_active_shock():
    assert "No shock" in sl.describe_params({})
    text = sl.describe_params({"rate_shock_bps": 300, "cre_price_shock_pct": 20})
    assert "300" in text and "20" in text


# ----------------------------------------------------------- question memory

def test_record_puts_the_newest_question_first():
    recent = sl.record_question(["older"], "newest")
    assert recent[0] == "newest"


def test_record_deduplicates_case_insensitively():
    recent = sl.record_question(["What if rates rise?"], "what if rates rise?")
    assert len(recent) == 1


def test_record_is_capped():
    recent = []
    for i in range(sl.MAX_REMEMBERED + 5):
        recent = sl.record_question(recent, f"question {i}")
    assert len(recent) == sl.MAX_REMEMBERED


def test_record_ignores_blank_input():
    assert sl.record_question(["a"], "   ") == ["a"]


def test_recall_puts_the_analysts_own_questions_first():
    recalled = sl.recall_questions(["my own question"])
    assert recalled[0] == "my own question"
    # Topped up from the starters, never padded beyond what actually exists.
    assert len(recalled) == min(sl.RECALL_LIMIT, 1 + len(sl.STARTER_QUESTIONS))


def test_recall_is_capped_at_the_limit():
    many = [f"question {i}" for i in range(sl.MAX_REMEMBERED)]
    assert len(sl.recall_questions(many)) == sl.RECALL_LIMIT


def test_recall_falls_back_to_starters_when_empty():
    """A first visit must still offer something to click."""
    assert sl.recall_questions([]) == sl.STARTER_QUESTIONS[:sl.RECALL_LIMIT]


def test_recall_never_repeats_a_question():
    recalled = sl.recall_questions([sl.STARTER_QUESTIONS[0], "mine"])
    assert len(recalled) == len({q.lower() for q in recalled})


# ------------------------------------------------------------ app integration

def test_lab_renders_presets_and_recall_chips():
    body = A.build_scenario_lab_body(dl.DEFAULT_QUARTER, {}, ["my earlier question"])
    presets = _ids(body, "scenario-preset")
    recalls = _ids(body, "scenario-recall")
    assert {p["preset"] for p in presets} == {p["id"] for p in sl.PRESETS}
    assert recalls[0]["text"] == "my earlier question"


def test_lab_marks_the_active_preset():
    body = A.build_scenario_lab_body(dl.DEFAULT_QUARTER, sl.apply_preset("severe"), [])
    actives = [n for n in _walk(A.html.Div(body))
               if "is-active" in (getattr(n, "className", "") or "")]
    assert len(actives) == 1


def test_question_memory_is_browser_persistent():
    """The point of the feature is that it survives leaving the page, so the store
    must be local storage rather than in-memory."""
    store = next(n for n in _walk(A.serve_layout())
                 if getattr(n, "id", None) == "scenario-recent-q")
    assert store.storage_type == "local"


def test_sending_a_question_records_it():
    class _Ctx:
        triggered_id = "scenario-send"
        triggered = [{"value": 1}]

    original = A.ctx
    try:
        A.ctx = _Ctx
        _hist, _params, cleared, recent = A.send_scenario_message(
            1, 0, [], "What happens at +300bps?", [], {}, [])
    finally:
        A.ctx = original
    assert recent[0] == "What happens at +300bps?"
    assert cleared == ""


def test_clicking_a_remembered_question_re_asks_it():
    question = "Model a 25% fall in real estate"

    class _Ctx:
        triggered_id = {"type": "scenario-recall", "text": question}
        triggered = [{"value": 1}]

    original = A.ctx
    try:
        A.ctx = _Ctx
        history, params, _cleared, recent = A.send_scenario_message(
            0, 0, [1], "", [], {}, [])
    finally:
        A.ctx = original
    assert history[0] == {"role": "user", "text": question}
    assert params["cre_price_shock_pct"] == 25
    assert recent[0] == question


def test_preset_click_replaces_the_shock_and_logs_it():
    class _Ctx:
        triggered_id = {"type": "scenario-preset", "preset": "stagflation"}
        triggered = [{"value": 1}]

    original = A.ctx
    try:
        A.ctx = _Ctx
        history, params = A.apply_scenario_preset([1], [{"role": "user", "text": "earlier"}])
    finally:
        A.ctx = original
    spec = sl.preset("stagflation")
    assert params["rate_shock_bps"] == spec["rate_shock_bps"]
    assert params["preset_id"] == "stagflation"
    assert history[-2]["text"].endswith(spec["label"])


def test_free_text_shock_clears_the_preset_badge():
    """Once the user types their own shock it is no longer a named scenario."""
    class _Ctx:
        triggered_id = "scenario-send"
        triggered = [{"value": 1}]

    original = A.ctx
    try:
        A.ctx = _Ctx
        _h, params, _c, _r = A.send_scenario_message(
            1, 0, [], "another +200bps", [], sl.apply_preset("severe"), [])
    finally:
        A.ctx = original
    assert "preset_id" not in params


def test_lab_replies_render_as_markdown():
    bubble = A.build_scenario_bubble("ai", "**Loaded** something", confidence=0.9)
    assert isinstance(bubble.children[0], dcc.Markdown)
    user_bubble = A.build_scenario_bubble("user", "plain question")
    assert user_bubble.children[0] == "plain question"
