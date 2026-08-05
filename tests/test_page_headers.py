"""
One page header per page.

The page header carries the LIVE SYSTEM VIEW badge and the refresh clock. Sub-tab
bodies that called build_page_header rendered a second badge and a second,
differently-timed clock directly beneath the first — visible on Covenants, and on
six other tabs with the same shape.
"""

import pytest

import app as A


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def _count(tree, class_name):
    return sum(1 for n in _walk(A.html.Div(tree))
               if class_name in (getattr(n, "className", "") or "").split())


def _page(tree):
    """A full page = its own header plus the body of its first tab."""
    return A.html.Div(tree)


COCKPIT_TABS = [t for t in A.SUBNAV_TABS if t not in ("Overview", "Health Index")]
B360_TABS = ["Borrower List", "Covenants"]


@pytest.mark.parametrize("tab", COCKPIT_TABS)
def test_cockpit_tab_bodies_add_no_second_page_header(tab):
    body = {
        "Signals": A.build_signals_dashboard,
        "Concentration": A.build_concentration_dashboard,
        "Migration": A.build_migration_dashboard,
        "EAD": A.build_ead_dashboard,
        "IFRS 9": A.build_ifrs9_dashboard,
    }[tab]()
    assert _count(body, "page-header-row") == 0, f"{tab} renders its own page header"
    assert _count(body, "live-badge") == 0, f"{tab} renders a second LIVE badge"


@pytest.mark.parametrize("tab", B360_TABS)
def test_b360_tab_bodies_add_no_second_page_header(tab):
    body = {
        "Borrower List": A.build_borrower_list_dashboard,
        "Covenants": A.build_covenants_dashboard,
    }[tab]()
    assert _count(body, "page-header-row") == 0, f"{tab} renders its own page header"
    assert _count(body, "live-badge") == 0, f"{tab} renders a second LIVE badge"


def test_a_page_still_has_exactly_one_header():
    for page in (A.build_cockpit_page(), A.build_borrowers_page(),
                 A.build_section_page("watchlist")):
        assert _count(page, "page-header-row") == 1
        assert _count(page, "live-badge") == 1


def test_covenants_keeps_a_visible_heading():
    """Removing the duplicate must not leave the tab unlabelled."""
    body = A.build_covenants_dashboard()
    assert _count(body, "subsection-header") == 1
    text = " ".join(c for c in (getattr(n, "children", None) for n in _walk(A.html.Div(body)))
                    if isinstance(c, str))
    assert "Covenant" in text


@pytest.mark.parametrize("section", sorted(A.SECTION_TABS))
def test_breadcrumb_is_addressable_so_it_can_follow_the_sub_tab(section):
    """The breadcrumb used to keep naming whichever tab you arrived on, because
    only the sub-nav and the body were re-rendered on a tab switch."""
    page = A.build_section_page(section)
    crumbs = [n for n in _walk(page)
              if isinstance(getattr(n, "id", None), dict)
              and n.id.get("type") == "sec-crumb"]
    assert len(crumbs) == 1, f"{section}: expected one addressable breadcrumb"
    assert crumbs[0].id["section"] == section
    assert crumbs[0].children == A.SECTION_TABS[section][0]


def test_switching_sub_tab_returns_the_new_crumb_text():
    """Drive the real callback through a faked Dash callback context. Dash derives
    ctx.triggered_id by parsing prop_id, so the id has to be encoded into it."""
    import json

    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    ids = [{"type": "sec-subnav", "section": "reports", "tab": tab}
           for tab in A.SECTION_TABS["reports"]]
    prop_id = json.dumps(ids[1], sort_keys=True, separators=(",", ":")) + ".n_clicks"
    context_value.set(AttributeDict(
        triggered_inputs=[{"prop_id": prop_id, "value": 1}]))

    classnames, _body, crumb = A.switch_section_subnav([0, 1, 0], ids, None, None, None)
    assert crumb == "Schedules"
    assert classnames == ["subnav-item", "subnav-item active", "subnav-item"]


def test_watchlist_board_has_no_copilot_rail():
    """The AI Watch Copilot duplicated the Actions tab; Ask AI covers it with real
    grounding."""
    board = A.build_watchlist_tab_board()
    classes = " ".join(getattr(n, "className", "") or "" for n in _walk(A.html.Div(board)))
    assert "copilot" not in classes
    assert not hasattr(A, "build_ai_copilot_panel")
