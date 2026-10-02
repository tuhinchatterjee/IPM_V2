"""Independent ECL reconciliation (EVIDENCE LABEL: INDEPENDENT ORACLE; NO
MODEL -- no provider is called): every published Delta figure, for every
scope a What-If run can take, recomputed from the source rows by this test's
own arithmetic -- not through the engine's plan, SQL compiler or the UI.

The oracle states the governed Delta rule in Python over the book's rows:
ECL is linear in PD and LGD, a 12-month PD shock reaches Stage 1 only (Stage 2
carries the lifetime PD), a probability is capped at 1 and an LGD at 100%, a
Stage 3 row is not moved by a PD shock, and every row outside the selection
keeps its baseline. Agreement is to 1e-6 SAR mn.

EVIDENCE LABEL: no model call.
"""

# ruff: noqa: F811

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from backend.cockpit_v4.scenario import cohort as ch
from backend.workspace import access, grid, scenarios, service
from backend.workspace.store import WorkspaceStore
from tests.cockpit_v4.test_gw_runs import (  # noqa: F401 (fixtures)
    WHO,
    P,
    client,
    full_run,
    svc,
    uat_scenario,
    who,
)

TOL = Decimal("1e-6")


def D(x):
    return Decimal(str(x if x is not None else 0))


def oracle(book, where: str, *, pd: str = "1", lgd: str = "1"
           ) -> tuple[Decimal, Decimal, int]:
    """(baseline, scenario, rows) over the rows `where` selects."""
    g = ch.GRAIN[book.domain_id]
    rows = book.rows(
        f"SELECT stage, pd_pit_12m, lgd_pct, ecl_sar_mn FROM "
        f"{g['relation']} WHERE {g['period']} = ? AND ({where})",
        [book.latest_period])
    pd_m, lgd_m = D(pd), D(lgd)
    base = scen = Decimal(0)
    for r in rows:
        e, p, lg = D(r["ecl_sar_mn"]), D(r["pd_pit_12m"]), D(r["lgd_pct"])
        base += e
        if r["stage"] == 3 and pd_m != 1:
            scen += e
            continue
        f = Decimal(1)
        if r["stage"] == 1 and p:
            f *= min(p * pd_m, Decimal(1)) / p
        if lg:
            f *= min(lg * lgd_m, Decimal(100)) / lg
        scen += e * f
    return base, scen, len(rows)


def check(result, book, where: str, **shock) -> dict[str, Decimal]:
    b = result["body"]
    s = b["decomposition"]["delta"]["scopes"]
    base, scen, n = oracle(book, where, **shock)
    book_base, _, _ = oracle(book, "TRUE")
    assert b["cohort"]["entity_count"] == n
    assert abs(D(s["selected"]["opening"]) - base) <= TOL
    assert abs(D(s["selected"]["closing"]) - scen) <= TOL
    assert abs(D(s["selected"]["change"]) - (scen - base)) <= TOL
    # The whole book: the same change, on the whole book's opening.
    assert abs(D(s["total"]["opening"]) - book_base) <= TOL
    assert abs(D(s["total"]["closing"]) - (book_base - base + scen)) <= TOL
    assert abs(D(s["total"]["change"]) - (scen - base)) <= TOL
    # The method summary row carries the same figures.
    delta = b["results"]["delta"]
    assert abs(D(delta["baseline"]) - base) <= TOL
    assert abs(D(delta["scenario"]) - scen) <= TOL
    # Rest of the book does not move.
    assert abs(D(b["decomposition"]["delta"]["cross_scope"]
                 ["rest_of_book_delta"])) <= TOL
    return {"opening": base, "closing": scen}


def _ids(book, n):
    v = grid.view(book)
    return [str(r[v.key]) for r in book.rows(
        f"SELECT {v.key} FROM ({v.sql}) g ORDER BY {v.key} LIMIT {n}")]


def _selection(client, name, ids):
    r = client.post(f"{P}/whatif/selection/cohort", json={
        "name": name, "selection": {"mode": "rows", "ids": ids}})
    assert r.status_code < 300, r.text
    return r.json()["object_id"]


@pytest.mark.parametrize("scope", ["single", "multi", "sub_portfolio",
                                   "whole_book"])
def test_corporate_delta_reconciles_to_an_independent_oracle(client, svc,
                                                             scope):
    obj, cohort = uat_scenario(svc)
    book = access.book(WHO, "corporate")
    ids = _ids(book, 5)
    quoted = ",".join(f"'{i}'" for i in ids)
    cid, where = {
        "single": (lambda: (_selection(client, "one", ids[:1]),
                            f"facility_id = '{ids[0]}'")),
        "multi": (lambda: (_selection(client, "five", ids),
                           f"facility_id IN ({quoted})")),
        "sub_portfolio": (lambda: (cohort["object_id"],
                                   "sector = 'Construction'")),
        "whole_book": (lambda: ("", "TRUE")),
    }[scope]()
    kw = {"cohort_id": cid} if cid else {}
    _run, result = full_run(client, obj["object_id"], session_id=scope, **kw)
    check(result, book, where, pd="1.20", lgd="1.10")


def test_retail_pd_shock_reconciles_to_an_independent_oracle(client, svc):
    obj = scenarios.create(svc, WHO, {
        "name": "Retail PD x1.20 LGD x1.05", "domain_id": "retail",
        "description": "validation", "risk_thesis": "oracle",
        "scope": {"type": "whole_book", "label": "Whole active book"},
        "components": [{"kind": "parameter", "field": "pd_pit_12m",
                        "operation": "multiply", "value": "1.20",
                        "label": "PD x1.20"},
                       {"kind": "parameter", "field": "lgd_pct",
                        "operation": "multiply", "value": "1.05",
                        "label": "LGD x1.05"}],
        "stage_policy": "frozen", "severity": "moderate", "tags": ["val"]})
    _run, result = full_run(client, obj["object_id"], session_id="r")
    check(result, access.book(WHO, "retail"), "TRUE", pd="1.20", lgd="1.05")


def test_a_reopened_result_and_a_comparison_carry_the_same_figures(
        client, svc):
    obj, cohort = uat_scenario(svc)
    book = access.book(WHO, "corporate")
    _r1, sector = full_run(client, obj["object_id"],
                           cohort_id=cohort["object_id"], session_id="a")
    _r2, whole = full_run(client, obj["object_id"], session_id="b")
    want = {"sector": check(sector, book, "sector = 'Construction'",
                            pd="1.20", lgd="1.10"),
            "whole": check(whole, book, "TRUE", pd="1.20", lgd="1.10")}
    # Reopen: a fresh store over the same file.
    path = svc.store.path
    service.use_store(None)
    service.use_store(WorkspaceStore(path))
    for name, res in (("sector", sector), ("whole", whole)):
        again = client.get(f"{P}/objects/{res['object_id']}").json()
        s = again["body"]["decomposition"]["delta"]["scopes"]["selected"]
        assert abs(D(s["opening"]) - want[name]["opening"]) <= TOL
        assert abs(D(s["closing"]) - want[name]["closing"]) <= TOL
    cmp_ = client.post(f"{P}/whatif/compare", json={
        "result_ids": [sector["object_id"], whole["object_id"]]})
    assert cmp_.status_code == 201, cmp_.text
    kpis = {k["result_id"]: k for k in cmp_.json()["body"]["kpis"]}
    for name, res in (("sector", sector), ("whole", whole)):
        k = kpis[res["object_id"]]
        assert abs(D(k["selected_opening"]) - want[name]["opening"]) <= TOL
        assert abs(D(k["selected_closing"]) - want[name]["closing"]) <= TOL
    assert json.dumps(cmp_.json()["body"]).count("recomputed") == 1
