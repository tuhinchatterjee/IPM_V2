"""P11: the server-side aggregates behind the product-wide chart contract.

Heatmaps and stage-migration flows are drawn from `grid.grouped2`: two
governed dimensions, aggregated on the server, capped, and returned with the
totals so every chart proves it reconciles to the filtered book. The
portfolio never reaches the browser; these tests pin that by size and shape.
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from backend.workspace import grid, whatif
from tests.cockpit_v4.test_gw_whatif import CONSTRUCTION, WHO, P, _book, client, flags, svc  # noqa: F401 (fixtures)


def _sum(cells, key):
    return sum(c[key] or 0 for c in cells)


def test_stage_flow_reconciles_to_the_whole_book(svc):
    out = grid.grouped2(_book(), x="prior_stage", y="stage")
    assert out["total"]["n"] == 2996 and not out["truncated"]
    assert _sum(out["cells"], "n") == out["total"]["n"]
    assert _sum(out["cells"], "ead_sar_mn") == pytest.approx(
        out["total"]["ead_sar_mn"], rel=1e-9)
    assert {c["y"] for c in out["cells"]} <= {1, 2, 3}
    # Every flow is a distinct (prior, current) pair.
    pairs = [(c["x"], c["y"]) for c in out["cells"]]
    assert len(pairs) == len(set(pairs))


def test_heatmap_under_a_filter_matches_the_selection_summary(svc):
    book = _book()
    out = grid.grouped2(book, x="sector", y="rating_current",
                        filters=CONSTRUCTION["filters"])
    summary = whatif.summary(book, CONSTRUCTION)
    assert {c["x"] for c in out["cells"]} == {"Construction"}
    assert _sum(out["cells"], "n") == summary["entities"] == 248
    assert _sum(out["cells"], "ecl_sar_mn") == pytest.approx(summary["ecl"])


def test_retail_matrix_is_product_by_score_band(svc):
    out = grid.grouped2(_book("retail"), x="product", y="score_band")
    assert _sum(out["cells"], "n") == out["total"]["n"] == 6702
    assert set(out["cells"][0]) == {"x", "y", "n", "ead_sar_mn",
                                    "ecl_sar_mn"}


def test_an_unknown_or_injected_dimension_is_refused(svc):
    book = _book()
    for bad in ("sector; DROP TABLE x", "no_such_column", "1"):
        with pytest.raises(HTTPException) as err:
            grid.grouped2(book, x=bad, y="stage")
        assert err.value.status_code == 422
    with pytest.raises(HTTPException):
        grid.grouped2(book, x="sector", y="stage", filters=[
            {"column": "sector') OR 1=1 --", "op": "eq", "value": "x"}])


def test_the_cell_cap_truncates_and_says_so(svc, monkeypatch):
    monkeypatch.setattr(grid, "CELLS_MAX", 5)
    out = grid.grouped2(_book(), x="sector", y="rating_current")
    assert out["truncated"] and len(out["cells"]) == 5
    # The total stays the book's, so a truncated chart cannot claim to
    # reconcile.
    assert _sum(out["cells"], "n") < out["total"]["n"] == 2996


def test_http_aggregate_is_small_and_row_free(client):
    r = client.post(f"{P}/grid/group2", json={
        "domain": "corporate", "x": "sector", "y": "rating_current"})
    assert r.status_code == 200
    body = r.json()
    raw = json.dumps(body)
    # 2,996 facilities, but the payload carries cells, never rows.
    assert len(body["cells"]) <= grid.CELLS_MAX
    assert len(raw) < 40_000, len(raw)
    assert "facility_id" not in raw and "borrower_id" not in raw
    assert body["release_id"] and body["fingerprint"] and body["period"]
    assert client.post(f"{P}/grid/group2", json={
        "domain": "corporate", "x": "nope", "y": "stage"}).status_code == 422


# ---- Early Warning: a warning reason cross-filters the page ----------------------

def test_a_warning_reason_cross_filters_bands_segments_and_the_cohort(client):
    whole = client.get(f"{P}/early-warning", params={"domain": "retail"}).json()
    reason = whole["reasons"][0]["reason"]
    tripped = whole["reasons"][0]["n"]
    one = client.get(f"{P}/early-warning", params={
        "domain": "retail", "reason": reason}).json()
    assert one["reason"] == reason
    assert one["filters"][0]["column"] == "ews_reasons"
    assert one["filters"][0]["value"] in reason
    # Every exposure tripping the rule is warned, so the bands hold exactly
    # the reason chart's count; segments partition it.
    assert sum(b["n"] for b in one["bands"]) == tripped
    assert sum(b["n"] for s in one["by_segment"] for b in s["bands"]) == tripped
    assert sum(b["n"] for b in one["bands"]) < sum(
        b["n"] for b in whole["bands"])
    # The reasons chart ignores its own filter: every rule stays selectable.
    assert one["reasons"] == whole["reasons"]
    assert all(reason in r["ews_reasons"] for r in one["top"])
    # The cohort, investigation and What-If handoffs carry the same filter.
    cohort = client.post(f"{P}/early-warning/cohort", json={
        "domain": "retail", "reason": reason,
        "bands": ["critical", "high", "moderate", "low"]}).json()
    assert cohort["body"]["counts"]["entities"] == tripped
    assert reason in cohort["body"]["name"]
    severe = client.post(f"{P}/early-warning/cohort", json={
        "domain": "retail", "reason": reason}).json()
    assert severe["body"]["counts"]["entities"] == sum(
        b["n"] for b in one["bands"] if b["value"] in ("critical", "high"))
    inv = client.post(f"{P}/early-warning/investigate", json={
        "domain": "retail", "reason": reason})
    assert inv.status_code == 201


def test_an_unknown_warning_reason_is_refused(client):
    for bad in ("x' OR 1=1 --", "Watch", "on watchlist"):
        r = client.get(f"{P}/early-warning", params={"domain": "corporate",
                                                     "reason": bad})
        assert r.status_code == 422, bad
        assert client.post(f"{P}/early-warning/cohort", json={
            "domain": "corporate", "reason": bad}).status_code == 422


def test_every_rule_of_both_books_filters_exactly(client):
    """Labels carry characters the predicate layer refuses (`<`, `>=`,
    `%`); each still filters to exactly the exposures tripping it."""
    from backend.workspace import ews

    for domain in ("corporate", "retail"):
        whole = client.get(f"{P}/early-warning", params={
            "domain": domain}).json()
        counts = {r["reason"]: r["n"] for r in whole["reasons"]}
        assert {r["label"] for r in ews.describe(domain)} >= set(counts)
        for reason, n in counts.items():
            one = client.get(f"{P}/early-warning", params={
                "domain": domain, "reason": reason})
            assert one.status_code == 200, (reason, one.text)
            assert sum(b["n"] for b in one.json()["bands"]) == n, reason


def test_a_reason_whose_token_names_two_rules_is_refused(svc, monkeypatch):
    """Fail closed rather than over-match: if a rule's safe token were also
    inside another rule's label, the filter would catch both."""
    from backend.workspace import ews, issues_api

    monkeypatch.setattr(ews, "describe", lambda domain: [
        {"id": "A", "label": "Past due (DPD > 0)"},
        {"id": "B", "label": "Past due (DPD > 30)"},
        {"id": "C", "label": "Watch"}])
    with pytest.raises(HTTPException) as err:
        issues_api._reason_filter(_book(), "Past due (DPD > 0)")
    assert err.value.detail["error_code"] == "AMBIGUOUS_EWS_REASON"
    assert issues_api._reason_filter(_book(), "Watch") == [
        {"column": "ews_reasons", "op": "contains", "value": "Watch"}]
