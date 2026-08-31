"""
§30-§33 — the four domain readings through the real routes.

What only a route can prove: that the four domains present one contract rather
than four, that reading is separated from writing by permission, and that an
unknown domain is refused with a sentence rather than a stack trace.
"""

from __future__ import annotations

import pytest

from backend import intelligence as base
from backend.corporate import service as corporate


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


ANALYST = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}
DOMAINS = ("ifrs9", "covenant", "collateral")


@pytest.fixture(scope="module")
def borrower() -> str:
    period = corporate.latest_period()
    frame = corporate._load("corporate_ifrs9")
    return str(frame[frame["period"] == period]["borrower_id"].iloc[0])


class TestTheContractIsPublished:

    def test_the_overview_names_every_reader_and_its_dataset(self, client):
        body = client.get("/api/v1/domain-intelligence").json()
        assert body["version"] == base.INTELLIGENCE_VERSION
        assert {d["id"] for d in body["domains"]} == {
            "ifrs9", "covenant", "collateral", "external"}
        for domain in body["domains"]:
            assert domain["dataset"]
            assert domain["label"]

    def test_it_says_there_is_no_score(self, client):
        """Published rather than merely true.

        A screen that has to guess whether a reading carries a score is a
        screen that will guess once and hard-code around it.
        """
        body = client.get("/api/v1/domain-intelligence").json()
        assert "no score" in body["shape"]["score"]

    def test_it_says_an_absence_is_never_a_reassurance(self, client):
        body = client.get("/api/v1/domain-intelligence").json()
        assert "never reported as an absence of risk" in body["shape"]["missing"]


class TestOneShapeAcrossFourDomains:

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_a_reading_comes_back_in_the_common_shape(self, client, domain,
                                                      borrower):
        body = client.get(f"/api/v1/domain-intelligence/{domain}/{borrower}",
                          headers=ANALYST).json()
        assert set(body) >= {"version", "owner", "domain", "domain_label",
                             "borrower_id", "period", "sentence", "severity",
                             "findings", "booked_accounting", "missing",
                             "measured"}
        assert "score" not in body
        assert body["sentence"].endswith(".")

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_every_finding_names_its_dataset_field_and_rule(self, client,
                                                            domain, borrower):
        body = client.get(f"/api/v1/domain-intelligence/{domain}/{borrower}",
                          headers=ANALYST).json()
        for finding in body["findings"]:
            assert finding["dataset"]
            assert finding["field"]
            assert finding["test"]
            assert finding["owner"] == base.OWNER

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_a_borrower_not_on_file_gets_a_reason_not_an_error(self, client,
                                                               domain):
        response = client.get(f"/api/v1/domain-intelligence/{domain}/NOT-A-BORROWER",
                              headers=ANALYST)
        assert response.status_code == 200
        body = response.json()
        assert body["findings"] == []
        assert body["missing"], "an absence must be reported, not implied"

    def test_an_unknown_domain_is_refused_with_a_sentence(self, client):
        response = client.get("/api/v1/domain-intelligence/astrology/CORP-100000",
                              headers=ANALYST)
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error"] == "unknown_domain"
        assert "collateral" in detail["message"]

    def test_a_viewer_may_not_read_a_borrower_level_reading(self, client,
                                                            borrower):
        response = client.get(f"/api/v1/domain-intelligence/ifrs9/{borrower}",
                              headers={"X-IPM-Role": "VIEWER",
                                       "X-IPM-User-Id": "2"})
        assert response.status_code == 403


class TestMemosAreQuotedNotSummarised:

    def test_the_extract_comes_back_verbatim_and_labelled(self, client):
        period = corporate.latest_period()
        frame = corporate._load("credit_memo_signals")
        rows = frame[frame["period"] == period]
        if rows.empty:
            pytest.skip("this book carries no memos at the latest period")
        who = str(rows["customer_id"].iloc[0])
        body = client.get(f"/api/v1/domain-intelligence/external/{who}/memos",
                          headers=ANALYST).json()
        assert body["memos"]
        assert "Nothing here is paraphrased or generated" in body["note"]
        for memo in body["memos"]:
            assert memo["quoted_verbatim"] is True
            assert memo["extract"] in str(
                rows[rows["customer_id"] == who]["extract"].tolist())
