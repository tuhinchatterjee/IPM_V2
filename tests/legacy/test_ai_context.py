"""
Per-screen Ask AI: scoping, briefs, and answer formatting.

Guards three properties: the assistant knows which screen it is on, the opening
brief is computed from the dataset (so it is exact rather than generated), and
assistant replies render as Markdown rather than raw text.
"""

import pytest
from dash import dcc

import app as A
import backend.ai_context as ax
import backend.data_loader as dl

SCREEN_KEYS = list(ax.SCREENS)


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def _page_keys(tree):
    return {n.id["page"] for n in _walk(A.html.Div(tree))
            if isinstance(getattr(n, "id", None), dict) and "page" in n.id}


def _text(tree):
    return " | ".join(c for c in (getattr(n, "children", None) for n in _walk(A.html.Div(tree)))
                      if isinstance(c, str))


# ------------------------------------------------------------------- routing

def test_data_hub_has_no_assistant():
    """The Data Hub is an upload screen — there is nothing for the assistant to
    be grounded in, so it is not offered there."""
    assert ax.has_assistant("/data") is False
    assert all(ax.has_assistant(spec["route"]) for spec in ax.SCREENS.values())


@pytest.mark.parametrize("route,screen", [(s["route"], k) for k, s in ax.SCREENS.items()])
def test_route_maps_to_its_screen(route, screen):
    assert ax.screen_for(route) == screen


def test_unknown_route_falls_back_to_cockpit():
    assert ax.screen_for("/nope") == ax.COCKPIT
    assert ax.screen_for(None) == ax.COCKPIT


# ------------------------------------------------------------------- prompts

@pytest.mark.parametrize("screen", SCREEN_KEYS)
def test_prompt_names_the_screen_and_demands_markdown(screen):
    prompt = ax.system_prompt(screen)
    assert "MARKDOWN" in prompt, "answers are rendered as Markdown; the model must be told"
    if screen != ax.B360:
        assert ax.spec(screen)["label"] in prompt
        assert "THIS screen" in prompt, "vague references must resolve to the current screen"


def test_borrower_prompt_is_bound_to_the_borrower():
    prompt = ax.system_prompt(ax.B360, dl.DEFAULT_CUSTOMER)
    assert dl.DEFAULT_CUSTOMER in prompt
    assert "MARKDOWN" in prompt


def test_each_screen_gets_a_distinct_prompt():
    prompts = {ax.system_prompt(s) for s in SCREEN_KEYS}
    assert len(prompts) == len(SCREEN_KEYS), "screens must not share a prompt"


@pytest.mark.parametrize("screen", SCREEN_KEYS)
def test_seed_history_is_a_single_system_turn(screen):
    seed = ax.seed_history(screen)
    assert len(seed) == 1 and seed[0]["role"] == "system"


# -------------------------------------------------------------------- briefs

@pytest.mark.parametrize("screen", SCREEN_KEYS)
def test_brief_is_grounded_and_complete(screen):
    brief = ax.screen_brief(screen)
    assert brief["label"] == ax.spec(screen)["label"]
    assert brief["as_of"]
    assert len(brief["portfolio"]) == 4, "the portfolio snapshot is on every screen"
    assert brief["lines"], f"{screen} brief has no screen-specific lines"
    for _label, value, tone in brief["portfolio"]:
        assert value and tone in {"ok", "warn", "bad", "neutral"}


def test_brief_portfolio_matches_the_dataset():
    """The snapshot is computed, not narrated — it must equal the same figures the
    cockpit KPI cards show."""
    k = dl.compute_kpis(dl.DEFAULT_QUARTER)
    values = dict((label, value) for label, value, _ in ax.screen_brief(ax.COCKPIT)["portfolio"])
    assert values["Total EAD"] == dl.fmt_bn(k["total_ead"], 1)
    assert values["NPL ratio"] == f"{k['npl_ratio']:.1f}%"
    assert values["Appetite breaches"] == str(k["breaches"])


def test_screen_lines_differ_between_screens():
    assert ax.screen_brief("stress")["lines"] != ax.screen_brief("watchlist")["lines"]


def test_brief_survives_a_broken_builder(monkeypatch):
    """A brief must never take the assistant down with it."""
    monkeypatch.setitem(ax._LINE_BUILDERS, "stress",
                        lambda _q: (_ for _ in ()).throw(RuntimeError("boom")))
    brief = ax.screen_brief("stress")
    assert brief["lines"], "should fall back to a description, not an empty brief"


@pytest.mark.parametrize("screen", SCREEN_KEYS)
def test_suggestions_are_screen_specific(screen):
    assert len(ax.suggestions(screen)) >= 3


# ------------------------------------------------------------ app integration

def test_chat_stores_exist_for_every_screen():
    assert set(SCREEN_KEYS) <= _page_keys(A.serve_layout())


@pytest.mark.parametrize("screen", SCREEN_KEYS)
def test_panel_carries_its_screen_key_and_brief(screen):
    panel = A.build_chat_panel(screen, ax.seed_history(screen), A.DEFAULT_MODEL)
    assert _page_keys(panel) == {screen}
    text = _text(panel)
    assert "ON THIS SCREEN" in text and ax.spec(screen)["label"] in text


# --------------------------------------------------------------- formatting

def test_assistant_turns_render_as_markdown():
    """Raw text in a div is what made answers read as an undifferentiated wall."""
    bubbles = A.render_chat_bubbles([
        {"role": "user", "content": "which limits are breached?"},
        {"role": "assistant", "content": "**Three.**\n\n| a | b |\n|---|---|\n| 1 | 2 |"},
    ])
    assert len(bubbles) == 2
    assert isinstance(bubbles[0].children, str), "user turns stay plain text"
    assert isinstance(bubbles[1].children, dcc.Markdown), "assistant turns are Markdown"


def test_markdown_does_not_allow_raw_html():
    """The reply is model output; rendering it as HTML would be an injection path."""
    md = A.render_chat_bubbles([{"role": "assistant", "content": "hi"}])[0].children
    assert md.dangerously_allow_html is False


def test_empty_history_shows_a_prompt_hint():
    bubbles = A.render_chat_bubbles([])
    assert len(bubbles) == 1
    assert "Ask a question" in bubbles[0].children


def test_suggestion_chips_carry_their_text_and_screen():
    """The chip's own id carries the question — echo_user_message reads it from
    there rather than from the input box, so a malformed id silently does
    nothing when clicked."""
    panel = A.build_chat_panel("stress", ax.seed_history("stress"), A.DEFAULT_MODEL)
    chips = [n.id for n in _walk(A.html.Div(panel))
             if isinstance(getattr(n, "id", None), dict) and n.id.get("type") == "chat-chip"]
    assert len(chips) == len(ax.suggestions("stress"))
    assert {c["text"] for c in chips} == set(ax.suggestions("stress"))
    assert all(c["page"] == "stress" for c in chips)


def test_clicking_a_chip_sends_its_text():
    """Regression: the chips are inside a popup that is only interactive while the
    input has focus. A CSS change that lets the input blur on mousedown cancels
    the click before it lands, and the chip appears to do nothing."""
    history = ax.seed_history("stress")
    trigger = {"type": "chat-chip", "page": "stress", "text": "What breaks first under +300bps?"}

    class _Ctx:
        triggered_id = trigger
        triggered = [{"value": 1}]

    original = A.ctx
    try:
        A.ctx = _Ctx
        _bubbles, new_history, cleared, pending = A.echo_user_message(None, None, [1], "", history)
    finally:
        A.ctx = original

    assert new_history[-1] == {"role": "user", "content": trigger["text"]}
    assert pending["text"] == trigger["text"]
    assert cleared == ""


def test_chip_guard_script_ships_with_the_assets():
    """The chips only work because a mousedown guard keeps the input focused;
    without the script the popup hides itself mid-click."""
    from pathlib import Path
    script = Path(A.__file__).parent / "assets" / "chat_suggestions.js"
    assert script.exists(), "assets/chat_suggestions.js is required for chip clicks"
    body = script.read_text(encoding="utf-8")
    assert "chat-suggestions-popup" in body and "preventDefault" in body


def test_tool_and_system_turns_are_never_shown():
    bubbles = A.render_chat_bubbles([
        {"role": "system", "content": "secret prompt"},
        {"role": "tool", "content": "raw tool payload"},
    ])
    assert len(bubbles) == 1 and "Ask a question" in bubbles[0].children
