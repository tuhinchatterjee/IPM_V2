"""MODEL MOCK · REAL DATABASE · BOTH BOOKS · EVERY SURFACE.

§37/§38. One figure is written one way, and one period is named one way.

The live failures
-----------------
A monthly Corporate answer offered "2026Q2" as its period, and amounts
appeared with decimal places on some surfaces and not on others. Both are the
same class of defect: a reader comparing two places in one answer found two
different renderings of one fact, and had no way to know which was the real
one.

So this drives a real run in EACH book and inspects every visible surface of
the published answer -- the prose, the figure list, the table, the chart
labels, the same `display` map the tooltip reads, and the markdown export --
against two rules:

    an amount shows NO decimal places, anywhere;
    a period is written `2026-08` or `Aug 2026`, never `2026Q3`.
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import ScriptedResult, final, intent, tool_call
from test_domain_execution import drive_domain, execute_call  # noqa: F401
from test_domain_execution import make_domain_run  # noqa: F401

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4 import states as st

#: `SAR 7,013.42 million` -- an amount that reached a reader with decimals.
MONEY_WITH_DECIMALS = re.compile(r"\bSAR\s[\d,]+\.\d+\b")
#: Any amount at all, so the test can prove it was actually looking at money.
ANY_MONEY = re.compile(r"\bSAR\s[\d,]+(?:\.\d+)?\s?(?:million|billion)?\b")
#: A quarter label, in any of the spellings a book might produce.
QUARTER = re.compile(r"\b20\d\d\s?[Qq][1-4]\b|\b[Qq][1-4]\s?20\d\d\b")
#: The two period forms this build publishes.
MONTH_ISO = re.compile(r"\b20\d\d-(?:0[1-9]|1[0-2])\b")
MONTH_WORD = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s20\d\d\b")

BOOKS = {
    dom.CORPORATE: ("corp_facility_month", "sector", "corporate"),
    dom.RETAIL: ("retail_account_month", "product", "retail"),
}


@pytest.fixture(scope="module", autouse=True)
def _published():
    for domain_id in dom.DOMAIN_IDS:
        if not lake.exists(dom.DEFAULT_RELEASES[domain_id]):
            pytest.skip("run scripts/cockpit_v4/seed_domains.py")
    arun.reset()
    yield
    arun.reset()


def latest_month(domain_id: str) -> str:
    runtime = arun.for_domain(domain_id)
    populated = list(getattr(runtime.catalog.calendar, "populated", ()) or ())
    return str(populated[-1])


def _answer(messages, dimension: str):
    """One claim on the largest cell, a table and a chart on the same rows."""
    payload = json.loads(messages[-1]["content"][0]["content"])
    step = payload["steps"][0]
    row = step["preview"][0]
    column = next(c for c in step["columns"] if c != dimension)
    return ScriptedResult(tool_calls=[tool_call(
        "finalize_response",
        final(intent=intent("DATA_ANALYSIS", "COCKPIT"),
              narrative="The largest exposure is {{claim.top}}.",
              numeric_claims=[{
                  "claim_id": "top", "unit": "SAR million",
                  "evidence": {"artifact_id": step["artifact_id"],
                               "row_key": f"{dimension}={row[dimension]}",
                               "column_id": column}}],
              tables=[{"title": "EAD by segment",
                       "artifact_id": step["artifact_id"],
                       "columns": [dimension, column]}],
              charts=[{"kind": "bar", "artifact_id": step["artifact_id"],
                       "title": "EAD by segment", "x_column": dimension,
                       "y_columns": [column]}]))])


@pytest.fixture
def published(drive_domain):  # noqa: F811
    """A real published answer in one book, with money on every surface."""
    def _published(domain_id: str):
        relation, dimension, _label = BOOKS[domain_id]
        month = latest_month(domain_id)
        sql = (f"SELECT {dimension}, SUM(ead_sar_mn) AS ead_sar_mn "
               f"FROM {relation} WHERE reporting_month = '{month}' "
               f"GROUP BY 1 ORDER BY 2 DESC")
        outcome, _provider, record = drive_domain(
            domain_id, "What is exposure at default by segment this month?",
            [ScriptedResult(tool_calls=[execute_call(
                sql, purpose="EAD by segment", grain=dimension,
                units="SAR million", subquestions=["EAD by segment"],
                fields=[f"{relation}.ead_sar_mn", f"{relation}.{dimension}"],
                month=month)]),
             lambda messages: _answer(messages, dimension)])
        assert outcome.state == st.COMPLETED, outcome.message
        return outcome.response, record, month
    return _published


def surfaces(body: dict) -> dict[str, list[str]]:
    """Every visible string of a published answer.

    The chart's `display` map is the same map the tooltip reads -- see
    `visuals.tsx` -- so checking it checks the tooltip.
    """
    return {
        "prose": [body["narrative"]],
        "figure list": [c.get("display_value", "")
                        for c in body["numeric_claims"]],
        "table": [str(shown)
                  for table in body["tables"] for row in table.get("rows", [])
                  for shown in row["display"].values()],
        "chart label": [str(point.get("label", ""))
                        for chart in body["charts"]
                        for point in chart.get("points", [])],
        "tooltip": [str(shown)
                    for chart in body["charts"]
                    for point in chart.get("points", [])
                    for shown in point["display"].values()],
    }


# ---- §37: an amount shows no decimals, anywhere -------------------------

@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_no_surface_of_an_answer_shows_an_amount_with_decimals(
        published, domain_id):
    body, _record, _month = published(domain_id)
    seen = 0
    for where, values in surfaces(body).items():
        for shown in values:
            assert not MONEY_WITH_DECIMALS.search(shown), (where, shown)
            seen += len(ANY_MONEY.findall(shown))
    assert seen >= 4, (
        "this test found no amounts at all, so it proved nothing")


def exported(store_db, runtime, run_id: str) -> str:
    """The analysis document the export route actually serves."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.cockpit_v4 import routes

    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: {
                       "id": "u1", "tenant": lake.DEFAULT_TENANT},
                   startup_sha="testsha")
    app.include_router(routes.router)
    response = TestClient(app).get(
        f"/api/v1/cockpit-v4/runs/{run_id}/export")
    assert response.status_code == 200, response.text
    return response.text


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_export_shows_the_same_amounts_the_screen_does(
        published, domain_id, store_db, runtime):
    """§37. The export is a surface like any other, and it is the one a
    reader keeps."""
    body, record, _month = published(domain_id)
    document = exported(store_db, runtime, record.run_id)
    assert ANY_MONEY.search(document), "the export carried no amounts"
    assert not MONEY_WITH_DECIMALS.search(document), (
        MONEY_WITH_DECIMALS.search(document).group(0))
    # The figure in the prose is the figure in the document.
    assert body["numeric_claims"][0]["display_value"] in document


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_export_names_a_month_and_never_a_quarter(
        published, domain_id, store_db, runtime):
    """§38. Including the lineage footer, which is what a reader checks
    months later when they are no longer sure what they are looking at."""
    _body, record, month = published(domain_id)
    document = exported(store_db, runtime, record.run_id)
    assert not QUARTER.search(document), QUARTER.search(document).group(0)
    assert month in document, (
        f"the export does not say which month {month!r} it is")


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_export_names_the_release_it_was_taken_from(
        published, domain_id, store_db, runtime):
    """A fingerprint that hashes nothing identifies nothing. Both books were
    stamping SHA-256 of the empty string, which matched every other book."""
    import hashlib

    _body, record, _month = published(domain_id)
    document = exported(store_db, runtime, record.run_id)
    assert dom.DEFAULT_RELEASES[domain_id] in document
    empty = hashlib.sha256(b"").hexdigest()
    assert empty[:16] not in document, (
        "the export carries the fingerprint of nothing")
    assert lake.fingerprint(dom.DEFAULT_RELEASES[domain_id])[:16] in document


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_figure_in_the_prose_is_the_figure_in_the_table(
        published, domain_id):
    body, _record, _month = published(domain_id)
    shown = body["numeric_claims"][0]["display_value"]
    assert shown in body["narrative"]
    assert shown in surfaces(body)["table"], (
        f"the prose says {shown!r} and no table cell does")


# ---- §38: a period is a month, never a quarter --------------------------

@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_no_surface_of_an_answer_names_a_quarter(published, domain_id):
    body, _record, _month = published(domain_id)
    blob = json.dumps(body, default=str)
    assert not QUARTER.search(blob), QUARTER.search(blob).group(0)


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_release_header_names_the_book_in_months(published, domain_id):
    body, _record, month = published(domain_id)
    header = body.get("release") or {}
    blob = json.dumps(header, default=str)
    assert not QUARTER.search(blob), blob
    assert str(header.get("reporting_frequency", "")).lower() == "monthly", (
        header)


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_attention_feed_names_months_and_shows_whole_amounts(
        domain_id, store_db, runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.cockpit_v4 import attention_v2 as att
    from backend.cockpit_v4 import routes

    att.clear_cache()
    arun.reset()
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: {
                       "id": "u1", "tenant": lake.DEFAULT_TENANT},
                   startup_sha="testsha")
    app.include_router(routes.router)
    client = TestClient(app)

    feed = client.get("/api/v1/cockpit-v4/attention",
                      params={"domain": domain_id}).json()
    cards = feed["segments_requiring_attention"] + feed["ecl_highlights"]
    assert cards
    for card in cards:
        blob = json.dumps(card, default=str)
        assert not QUARTER.search(blob), (card["item_id"],
                                          QUARTER.search(blob).group(0))
        assert MONTH_ISO.fullmatch(str(card["reporting_month"])), card
        for shown in [n["display"] for n in card["key_numbers"]]:
            assert not MONEY_WITH_DECIMALS.search(str(shown)), shown
    # And the feed really did carry amounts.
    assert any(ANY_MONEY.search(str(n["display"]))
               for card in cards for n in card["key_numbers"])


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_period_the_book_offers_is_a_month_this_release_holds(domain_id):
    from backend.cockpit_v4 import semantics as sem

    runtime = arun.for_domain(domain_id)
    vocabulary = sem.vocabulary(runtime.catalog)
    assert vocabulary["PERIOD"] == "month", vocabulary
    assert vocabulary["FREQUENCY"] == "monthly", vocabulary
    assert MONTH_ISO.fullmatch(vocabulary["LATEST_PERIOD"]), vocabulary
    for value in vocabulary.values():
        assert not QUARTER.search(str(value)), value


def test_both_period_spellings_are_the_same_month():
    """§38 allows `2026-08` and `Aug 2026`. They must be one month written
    two ways, not two months."""
    assert MONTH_ISO.fullmatch("2026-08")
    assert MONTH_WORD.fullmatch("Aug 2026")
    assert not MONTH_ISO.fullmatch("2026-13")
    assert not MONTH_ISO.fullmatch("2026Q3")
    assert QUARTER.search("the latest quarter 2026Q2 against 2026Q1")
