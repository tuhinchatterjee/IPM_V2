"""P13 grid gaps: GRID07 filter kinds, GRID11 null/boolean filters, GRID13
server-side sort through pagination, paging limits, and the filter / cohort
definition carried by every export.

The grid runs on the server against the active release; the browser only
asks (GW-P13 journeys drive the same paths through the UI).
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.workspace import cohorts, grid, service
from tests.cockpit_v4.test_gw_whatif import (  # noqa: F401 (fixtures)
    CONSTRUCTION,
    WHO,
    P,
    _book,
    client,
    converse_preview,
    flags,
    svc,
)

#: The filter kinds the grid UI has an editor for (data-grid.tsx FilterEditor).
EDITORS = {"text", "category", "range", "boolean"}


@pytest.mark.parametrize("domain", ["corporate", "retail"])
def test_grid07_every_visible_column_declares_a_filter_the_ui_can_edit(
        svc, domain):
    schema = grid.schema(_book(domain))
    visible = [c for c in schema["columns"] if c["visible"]]
    assert len(visible) >= 30
    for c in visible:
        assert c["filter"] in EDITORS, (c["key"], c["filter"])
        # The kind fits the type: flags are boolean, numbers are ranges.
        if c["type"] == "flag":
            assert c["filter"] == "boolean", c["key"]
        if c["type"] in ("number",) and c["unit"] not in ("",):
            assert c["filter"] in ("range", "category"), c["key"]


def _total(book, filters):
    return grid.query(book, filters=filters, limit=1)["total"]


@pytest.mark.parametrize("domain,flag,nullable", [
    ("corporate", "watchlist_flag", "prior_stage"),
    ("retail", "secured_flag", "prior_stage")])
def test_grid11_boolean_and_null_filters_partition_the_book(svc, domain, flag,
                                                            nullable):
    book = _book(domain)
    whole = _total(book, [])
    yes = _total(book, [{"column": flag, "op": "eq", "value": 1}])
    no = _total(book, [{"column": flag, "op": "eq", "value": 0}])
    unset = _total(book, [{"column": flag, "op": "is_null"}])
    assert yes > 0 and no > 0
    assert yes + no + unset == whole
    empty = _total(book, [{"column": nullable, "op": "is_null"}])
    filled = _total(book, [{"column": nullable, "op": "not_null"}])
    assert empty + filled == whole and filled > 0
    rows = grid.query(book, filters=[{"column": flag, "op": "eq",
                                      "value": 1}], limit=200)["rows"]
    assert rows and all(int(r[flag]) == 1 for r in rows)
    rows = grid.query(book, filters=[{"column": nullable, "op": "is_null"}],
                      limit=200)["rows"]
    assert all(r[nullable] is None for r in rows)


def test_grid11_through_http(client):
    r = client.post(f"{P}/grid/query", json={
        "domain": "corporate", "filters": [
            {"column": "sicr_flag", "op": "eq", "value": 1},
            {"column": "prior_stage", "op": "not_null"}], "limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] > 0
    assert all(row["sicr_flag"] == 1 for row in body["rows"])


@pytest.mark.parametrize("sort,desc", [("ead_sar_mn", True),
                                       ("ead_sar_mn", False),
                                       ("rating_current", True),
                                       ("stage", False)])
def test_grid13_server_sort_is_deterministic_across_pages(svc, sort, desc):
    book = _book()
    key = grid.view(book).key
    whole = grid.query(book, sort=sort, desc=desc, limit=150)["rows"]
    paged = []
    for offset in (0, 50, 100):
        page = grid.query(book, sort=sort, desc=desc, offset=offset,
                          limit=50)
        assert page["sort"] == sort and page["desc"] == desc
        paged += page["rows"]
    assert [r[key] for r in paged] == [r[key] for r in whole]
    values = [r[sort] for r in whole if r[sort] is not None]
    assert values == sorted(values, reverse=desc)
    # Ties are broken by the key: the same request gives the same order.
    again = grid.query(book, sort=sort, desc=desc, limit=150)["rows"]
    assert [r[key] for r in again] == [r[key] for r in whole]


def test_grid13_an_unknown_sort_column_falls_back_and_says_so(svc):
    page = grid.query(_book(), sort="ead_sar_mn; DROP TABLE x", limit=3)
    assert page["sort"] == "ecl_sar_mn"


def test_paging_is_server_side_and_capped(svc):
    book = _book()
    first = grid.query(book, limit=25)
    assert len(first["rows"]) == 25 and first["total"] == 2996
    last = grid.query(book, offset=2990, limit=25)
    assert len(last["rows"]) == 6
    big = grid.query(book, limit=10_000)
    assert len(big["rows"]) == grid.PAGE_MAX
    assert grid.query(book, offset=-5, limit=0)["offset"] == 0


def test_grid_export_carries_the_filter_definition(client):
    r = client.post(f"{P}/grid/export", json={
        "domain": "corporate", "filters": CONSTRUCTION["filters"]})
    assert r.status_code == 200
    head = [line for line in r.text.splitlines() if line.startswith("#")]
    text = "\n".join(head)
    assert "# filters:" in text and "Construction" in text
    assert "# filter_definition:" in text and "'op': 'in'" in text
    assert "# rows: 248" in text and "# fingerprint:" in text


def test_cohort_export_carries_the_cohort_definition(client, svc):
    saved = client.post(f"{P}/whatif/selection/cohort", json={
        "domain": "corporate", "selection": CONSTRUCTION,
        "name": "Construction book"}).json()
    r = client.get(f"{P}/cohorts/{saved['object_id']}/export")
    assert r.status_code == 200
    head = "\n".join(x for x in r.text.splitlines() if x.startswith("#"))
    for k in ("# cohort_id:", "# cohort_name: Construction book",
              "# cohort_definition:", "# membership_hash:",
              "# filter_definition:", "# rows: 248"):
        assert k in head, k


def test_a_conversation_cohort_exports_exactly_its_members(client, svc):
    """Regression: a cohort frozen in a conversation has no grid filters;
    its export must be its members, never the whole book."""
    _produced, stored = converse_preview(
        "retail", {"filters": [{"column": "product", "operator": "=",
                                "value": "Personal Finance"}]})
    book = _book("retail")
    adopted = cohorts.adopt(
        book, svc, service.principal(WHO), name="From conversation",
        predicate=stored["cohort_predicate"],
        selection=stored["cohort_selection"],
        period=stored["reporting_period"],
        described_as=stored["cohort_described_as"],
        expected_hash=stored["canonical"]["cohort"]["membership_hash"],
        source={"kind": "conversation", "thread_id": "th-x"})
    r = client.get(f"{P}/cohorts/{adopted['object_id']}/export")
    assert r.status_code == 200, r.text
    rows = [x for x in r.text.splitlines() if x and not x.startswith("#")]
    n = adopted["body"]["counts"]["entities"]
    assert len(rows) - 1 == n < 6702
    assert f"# members_exported: {n}" in r.text
    assert "# cohort_source: conversation" in r.text


def test_query_refuses_unknown_filter_columns(svc):
    with pytest.raises(HTTPException):
        grid.query(_book(), filters=[{"column": "nope", "op": "is_null"}])
