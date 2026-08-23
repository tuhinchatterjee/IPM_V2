"""
The global Ask AI drawer.

Guards the two properties the refactor is for: the AI panel is mounted exactly
once (in the drawer, not embedded in page bodies), and it is reachable from every
route with the chat context that matches the page.
"""

import app as A
import backend.ai_context as ai_context


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def _ids(tree):
    found = set()
    for node in _walk(tree):
        node_id = getattr(node, "id", None)
        if node_id is None:
            continue
        found.add(node_id if isinstance(node_id, str) else repr(sorted(node_id.items())))
    return found


def _class_names(tree):
    return [c for c in (getattr(n, "className", None) for n in _walk(tree)) if isinstance(c, str)]


# /data is excluded: the Data Hub page queries the dataset-version tables, and
# this suite is deliberately DB-free (see conftest). Every other route renders
# from the bundled workbook already in data_loader's module globals.
ROUTES = ["/", "/esg", "/macro", "/raroc", "/brf", "/watchlist", "/stress",
          "/reports", "/borrowers"]


def _render(pathname, search=""):
    """render_page reads every screen's chat store through a pattern-matching
    ALL state, so the fixture has to supply one history and one id per screen."""
    ids = [{"type": "chat-history", "page": screen} for screen in ai_context.SCREENS]
    histories = [ai_context.seed_history(i["page"]) for i in ids]
    models = [A.DEFAULT_MODEL] * len(ids)
    return A.render_page(pathname, search, histories, ids, models, A.dl.DEFAULT_CUSTOMER)


# ------------------------------------------------- the panel is not embedded

def test_cockpit_page_has_no_embedded_ai_panel():
    assert not any("ai-chat-panel" in c for c in _class_names(A.build_cockpit_page()))


def test_borrower_page_has_no_embedded_ai_panel():
    assert not any("ai-chat-panel" in c for c in _class_names(A.build_borrowers_page()))


def test_overview_spans_full_width():
    """The right rail is gone, so Overview must no longer be a two-column grid —
    that grid is what pushed the chat header into the model dropdown."""
    assert not any("dashboard-grid" in c for c in _class_names(A.build_cockpit_page()))


# ------------------------------------------------------------ the launcher

def test_launcher_is_in_the_app_shell():
    ids = _ids(A.serve_layout())
    for component in ("ai-fab", "ai-drawer", "ai-drawer-body", "ai-drawer-scrim", "ai-drawer-open"):
        assert component in ids, f"{component} missing from the app shell"


def test_every_route_fills_the_drawer():
    for route in ROUTES:
        page, drawer, style = _render(route)[:3]
        assert page, f"{route}: no page content"
        assert drawer, f"{route}: drawer body empty"
        assert style == A.VISIBLE, f"{route}: launcher should be visible"
        assert "ai-drawer-close" in _ids(A.html.Div(drawer)), f"{route}: no close button"


def test_data_hub_hides_the_launcher_entirely(monkeypatch):
    """The Data Hub is upload/administration — the assistant has nothing to be
    grounded in there, so it is not offered rather than offered and unhelpful.

    The page itself queries the dataset-version tables, so it is stubbed: what is
    under test is the launcher decision, not the Data Hub's own rendering."""
    monkeypatch.setattr(A.data_hub, "build_data_hub_page", lambda: A.html.Div("stub"))
    style = _render("/data")[2]
    assert style == A.HIDDEN


def test_drawer_context_follows_the_route():
    """Every screen gets its OWN chat context, so a question asked on Limits is
    answered about Limits and does not land in the Watchlist thread. Losing this
    would silently un-ground the assistant."""
    def page_keys(drawer):
        return {
            node_id["page"]
            for node_id in (getattr(n, "id", None) for n in _walk(A.html.Div(drawer)))
            if isinstance(node_id, dict) and "page" in node_id
        }

    for route, screen in [("/borrowers", "b360"), ("/", "cockpit"), ("/esg", "esg"),
                          ("/watchlist", "watchlist"), ("/macro", "macro")]:
        assert page_keys(_render(route)[1]) == {screen}, route


# --------------------------------------------------------------- toggling

def _toggle(trigger, is_open):
    ctx_stub = type("Ctx", (), {"triggered_id": trigger, "triggered": [{"value": 1}]})
    original = A.ctx
    try:
        A.ctx = ctx_stub
        return A.toggle_ai_drawer(1, 1, 1, is_open)
    finally:
        A.ctx = original


def test_fab_toggles_both_ways():
    assert _toggle("ai-fab", False)[0] is True
    assert _toggle("ai-fab", True)[0] is False


def test_close_and_scrim_always_close():
    for trigger in ("ai-drawer-close", "ai-drawer-scrim"):
        assert _toggle(trigger, True)[0] is False
        assert _toggle(trigger, False)[0] is False


def test_open_state_drives_every_class():
    open_state, drawer_cls, scrim_cls, fab_cls = _toggle("ai-fab", False)
    assert open_state is True
    assert "is-open" in drawer_cls and "is-open" in scrim_cls
    assert "is-hidden" in fab_cls, "the FAB must hide behind the open drawer"

    open_state, drawer_cls, scrim_cls, fab_cls = _toggle("ai-fab", True)
    assert open_state is False
    assert "is-open" not in drawer_cls and "is-open" not in scrim_cls
    assert "is-hidden" not in fab_cls
