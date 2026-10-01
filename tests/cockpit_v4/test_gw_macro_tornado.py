"""MAC07 — macro-sensitivity tornado in the governed What-If experience.

Every bar is the Scenario Library's own governed translation of a published
slope; signs are as fitted; PD and LGD are separate rows; the collateral
sign-review rule (RET-07 / CORP-03) is carried, never corrected; diagnostic-
only estimates are listed and not drawn. The accepted Cockpit chat path keeps
its "tornado substitute" exactly as before.
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.workspace import macro_sensitivity as ms
from backend.workspace import scenario_library as sl
from tests.cockpit_v4.test_gw_whatif import CONSTRUCTION, P, _book, client, flags, svc  # noqa: F401 (fixtures)


@pytest.fixture
def corp(svc):
    return ms.tornado(_book(), top=60)


def test_bars_are_the_governed_translation_exactly(svc, corp):
    book = _book()
    pop = sl._pop(book, __import__("backend.workspace.grid",
                                   fromlist=["view"]).view(book), "1=1", [])
    checked = 0
    for r in corp["rows"][:10]:
        up = sl.translate_macro(book, r["factor_id"], r["shock_operation"],
                                r["shock_size"], baseline=pop)
        down = sl.translate_macro(book, r["factor_id"], r["shock_operation"],
                                  -r["shock_size"], baseline=pop)
        u = next(d for d in up["derived"] if d["field"] == r["parameter"])
        d = next(d for d in down["derived"] if d["field"] == r["parameter"])
        assert r["up_pp"] == float(u["value"])
        assert r["down_pp"] == float(d["value"])
        assert r["native_derivative"] == u["native_derivative"]
        checked += 1
    assert checked == 10 and corp["model_calls"] == 0


def test_rows_are_ranked_by_swing_and_capped(corp, svc):
    swings = [r["swing_pp"] for r in corp["rows"]]
    assert swings == sorted(swings, reverse=True)
    assert len(ms.tornado(_book(), top=5)["rows"]) == 5
    assert corp["material_rows"] >= len(corp["rows"])


def test_pd_and_lgd_are_explicit_and_filterable(corp, svc):
    params = {r["parameter"] for r in corp["rows"]}
    assert {"lgd_pct"} <= params and params & {"pd_pit_12m", "pd_lifetime"}
    for r in corp["rows"]:
        assert r["parameter_label"] == ms.PARAMETER_LABEL[r["parameter"]]
        assert r["family"] == ("lgd" if r["parameter"] == "lgd_pct" else "pd")
    only_lgd = ms.tornado(_book(), parameter="lgd", top=60)["rows"]
    assert only_lgd and {r["parameter"] for r in only_lgd} == {"lgd_pct"}
    only_pd = ms.tornado(_book(), parameter="pd", top=60)["rows"]
    assert only_pd and all(r["family"] == "pd" for r in only_pd)


def test_signs_are_preserved_as_fitted(corp):
    for r in corp["rows"]:
        coef = r["coefficient"]
        assert r["sign"] == ("+" if coef >= 0 else "-")
        # An up shock moves the parameter in the coefficient's direction.
        assert (r["up_pp"] > 0) == (coef > 0), r["factor_name"]
        assert r["down_pp"] == pytest.approx(-r["up_pp"])


def test_collateral_sign_review_is_carried_not_corrected(svc, corp):
    reviewed = {(r["factor_id"], r["parameter"]): r for r in corp["rows"]
                if r["sign_review"]}
    assert ("MEV10", "lgd_pct") in reviewed
    r = reviewed[("MEV10", "lgd_pct")]
    assert r["down_pp"] < 0 and r["up_pp"] > 0  # drawn as fitted
    assert r["sign_review"].startswith("SIGN_REVIEW")
    assert "shown, not corrected" in r["sign_review"]
    # Only the governed collateral factors on LGD are reviewed.
    assert all(f in ms.COLLATERAL_FACTORS and p == "lgd_pct"
               for f, p in reviewed)
    # RET-07 on the retail book: the residential property index on LGD.
    retail = ms.tornado(_book("retail"), parameter="lgd", top=60)
    assert any(x["factor_id"] == "MEV09" and x["sign_review"]
               for x in retail["rows"])


def test_diagnostic_only_estimates_are_listed_not_drawn(corp):
    assert corp["excluded"]
    drawn = {(r["factor_id"], r["parameter"]) for r in corp["rows"]}
    for x in corp["excluded"]:
        assert x["readiness"] != "SUPPORTED_ESTIMATE"
        assert (x["factor_id"], x["parameter"]) not in drawn
    assert all(r["readiness"] == "SUPPORTED_ESTIMATE" for r in corp["rows"])


def test_hover_fields_are_all_present(corp):
    for r in corp["rows"]:
        for k in ("factor_name", "series_id", "shock_label", "coefficient",
                  "parameter_label", "up_pp", "down_pp", "sign", "readiness",
                  "method", "lag", "train_start", "train_end"):
            assert r[k] is not None, (k, r["factor_id"])


def test_the_population_follows_the_filter(svc):
    t = ms.tornado(_book(), filters=CONSTRUCTION["filters"], top=8)
    assert t["population"]["entities"] == 248
    with pytest.raises(HTTPException):
        ms.tornado(_book(), filters=[{"column": "sector", "op": "in",
                                      "values": ["No such sector"]}])
    for bad in ({"parameter": "ccf"}, {"scale": 0}, {"scale": 9}):
        with pytest.raises(HTTPException):
            ms.tornado(_book(), **bad)


def test_http_route(client):
    r = client.post(f"{P}/whatif/sensitivity/tornado", json={
        "domain": "retail", "parameter": "all", "top": 12})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["rows"]) == 12 and body["model_calls"] == 0
    assert client.post(f"{P}/whatif/sensitivity/tornado", json={
        "domain": "retail", "parameter": "x"}).status_code == 422


def test_the_accepted_chat_path_keeps_its_tornado_substitute():
    """Flags-off / accepted behaviour: the Cockpit chat's result spec still
    answers a tornado request with the labelled waterfall substitute."""
    from backend.cockpit_v4.scenario import results as rs
    assert hasattr(rs, "tornado_substitute")
    import inspect
    assert "TORNADO_UNAVAILABLE" in inspect.getsource(rs.tornado_substitute)
    assert "not available in this application" in rs.TORNADO_UNAVAILABLE
