"""
Limits: quarter-on-quarter utilisation movement, and the Borrower 360 entry
point that replaced the standalone Limits section.
"""

import pytest

import app as A
import backend.data_loader as dl

Q = dl.DEFAULT_QUARTER


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def _classes(tree):
    return [c for c in (getattr(n, "className", None) for n in _walk(A.html.Div(tree)))
            if isinstance(c, str)]


def _text(tree):
    return " | ".join(c for c in (getattr(n, "children", None) for n in _walk(A.html.Div(tree)))
                      if isinstance(c, str))


# --------------------------------------------------- quarter-on-quarter change

def test_every_line_carries_a_qoq_field():
    data = dl.compute_limits_dashboard(Q)
    assert data["has_comparison"], "the latest quarter should have a prior to compare against"
    for r in data["rows"]:
        for key in ("prev_pct", "delta_pct", "prev_used", "delta_used",
                    "newly_breached", "newly_cured"):
            assert key in r, f"{r['label']} missing {key}"


def test_delta_equals_current_minus_prior():
    for r in dl.compute_limits_dashboard(Q)["rows"]:
        if r["delta_pct"] is not None:
            assert r["delta_pct"] == pytest.approx(r["pct"] - r["prev_pct"])
            assert r["delta_used"] == pytest.approx(r["used"] - r["prev_used"])


def test_qoq_reproduces_the_prior_quarters_own_figures():
    """The comparison must be like-for-like: the prior figures have to equal what
    the dashboard reported for that quarter, not a re-derived approximation."""
    pq = dl.prev_quarter(Q)
    prior = {r["label"]: r["pct"] for r in dl.compute_limits_dashboard(pq)["rows"]}
    for r in dl.compute_limits_dashboard(Q)["rows"]:
        if r["prev_pct"] is not None:
            assert r["prev_pct"] == pytest.approx(prior[r["label"]])


def test_no_prior_quarter_leaves_deltas_none():
    """The first quarter has nothing to compare against — it must say so rather
    than fabricate a zero change."""
    data = dl.compute_limits_dashboard(dl.QUARTER_SHEETS[0])
    assert data["has_comparison"] is False
    assert all(r["delta_pct"] is None for r in data["rows"])


def test_breach_transitions_are_consistent_with_the_levels():
    for r in dl.compute_limits_dashboard(Q)["rows"]:
        if r["newly_breached"]:
            assert r["prev_pct"] < 100 <= r["pct"]
        if r["newly_cured"]:
            assert r["pct"] < 100 <= r["prev_pct"]
        assert not (r["newly_breached"] and r["newly_cured"])


def test_transition_counts_match_the_rows():
    data = dl.compute_limits_dashboard(Q)
    assert data["newly_breached"] == sum(1 for r in data["rows"] if r["newly_breached"])
    assert data["newly_cured"] == sum(1 for r in data["rows"] if r["newly_cured"])
    assert data["rising"] == sum(1 for r in data["rows"] if (r["delta_pct"] or 0) > 0)


# ------------------------------------------------------------------ rendering

def test_utilisation_view_shows_the_delta_column():
    body = A.build_limits_body(Q, view="Utilisation")
    assert any("util-delta" in c for c in _classes(body))
    assert "vs " in _text(body), "the header should name the comparison quarter"


def test_other_views_do_not_show_the_delta_column():
    """Appetite and Breaches are level views; only Utilisation is about movement."""
    for view in ("Appetite", "Breaches"):
        assert not any("util-delta" in c for c in _classes(A.build_limits_body(Q, view=view)))


def test_delta_cell_direction_is_keyed_to_the_cap():
    """Rising toward a cap is bad and falling away from it is good — getting this
    backwards would colour a deteriorating line green."""
    assert "is-bad" in A.build_qoq_delta_cell({"delta_pct": 5.0, "pct": 80, "prev_pct": 75}).className
    assert "is-good" in A.build_qoq_delta_cell({"delta_pct": -5.0, "pct": 70, "prev_pct": 75}).className
    assert "is-flat" in A.build_qoq_delta_cell({"delta_pct": 0.0, "pct": 75, "prev_pct": 75}).className
    assert "is-none" in A.build_qoq_delta_cell({"delta_pct": None, "pct": 75}).className


# ------------------------------------------- the section is gone from the nav

def test_limits_is_no_longer_a_top_level_section():
    assert "Limits" not in A.TOP_NAV_ITEMS
    assert "/limits" not in A.SECTION_ROUTES.values()
    assert "limits" not in A.SECTION_TABS
    assert "limits" not in A.ROUTE_TO_SECTION.values()


def test_removed_route_falls_back_rather_than_erroring():
    assert A.ROUTE_TO_SECTION.get("limits") is None


# ------------------------------------------------- borrower 360 entry point

def test_borrower_page_offers_the_limits_button():
    ids = [getattr(n, "id", None) for n in _walk(A.html.Div(A.build_borrowers_page()))]
    assert "b360-limits-btn" in ids


def test_limits_modal_defaults_to_the_utilisation_view():
    """Utilisation is the movement view, which is the one worth opening on."""
    body = A.build_b360_limits_modal_body(dl.DEFAULT_CUSTOMER, Q)
    assert any("util-delta" in c for c in _classes(body))


def test_modal_offers_every_limits_view():
    body = A.build_b360_limits_modal_body(dl.DEFAULT_CUSTOMER, Q)
    views = {n.id["view"] for n in _walk(A.html.Div(body))
             if isinstance(getattr(n, "id", None), dict) and n.id.get("type") == "b360-limits-tab"}
    assert views == set(A.LIMITS_VIEWS)


def test_borrower_limit_labels_pick_the_lines_they_sit_in():
    profile = dl.get_borrower_profile(dl.DEFAULT_CUSTOMER, Q)
    labels = A.borrower_limit_labels(dl.DEFAULT_CUSTOMER, Q)
    assert f"{profile['sector']} (sector)" in labels
    assert f"{profile['region']} (geography)" in labels


def test_borrower_lines_are_highlighted_in_the_modal():
    body = A.build_b360_limits_modal_body(dl.DEFAULT_CUSTOMER, Q)
    assert any("is-highlighted" in c for c in _classes(body))
    assert "THIS BORROWER" in _text(body)


def test_unknown_borrower_yields_no_highlight_rather_than_raising():
    assert A.borrower_limit_labels("NOT_A_CUSTOMER", Q) == set()


def test_limits_body_still_renders_without_highlights():
    """The views are still portfolio-level and must work with no borrower context."""
    assert A.build_limits_body(Q, view="Utilisation", highlight_labels=None)
