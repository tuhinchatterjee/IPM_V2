"""A validation run, after the screen that produced it has gone.

The module this covers exists for one sentence: opening last quarter's
validation shows last quarter's numbers. Everything below is an attempt to
break that sentence — by reading a run after the code moved, by re-running and
watching whether the earlier row followed, by finalising a report twice, by
asking for one model's run through another model's URL.

The proof that a historical read does not recalculate is deliberately brutal
rather than statistical. `test_reading_a_run_cannot_reach_the_runner` replaces
the calculation engine with something that raises, and then reads a stored run
successfully. A test that merely compared two numbers would pass just as well
against an implementation that recomputed and happened to agree, which is the
implementation this whole module exists to rule out.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL not reachable")

API = "/api/v1/scorecard-validation"

ANALYST = {"X-IPM-User-Id": "1", "X-IPM-Role": "ANALYST"}
ADMIN = {"X-IPM-User-Id": "1", "X-IPM-Role": "ADMIN"}
#: VIEWER is outside SCORECARD_VIEW entirely, so it is the role that proves
#: the module is gated at all rather than merely gated for writes.
VIEWER = {"X-IPM-User-Id": "2", "X-IPM-Role": "VIEWER"}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture()
def session():
    from backend.db.engine import get_session

    with get_session() as handle:
        yield handle


def _sweep(keys: list[str]) -> None:
    """Remove the runs a test made, reports first for the RESTRICT.

    Not a truncate. This suite shares a database with a seeded demonstration,
    and a truncate in a test file is how somebody's demo disappears an hour
    before they present it.
    """
    from sqlalchemy import delete, select

    from backend.db.engine import get_session
    from backend.models.scorecard_validation import ScvReport, ScvRun

    if not keys:
        return
    with get_session() as handle:
        ids = list(handle.execute(
            select(ScvRun.id).where(ScvRun.run_key.in_(keys))).scalars().all())
        if ids:
            handle.execute(delete(ScvReport).where(ScvReport.run_id.in_(ids)))
            handle.execute(delete(ScvRun).where(ScvRun.id.in_(ids)))
        handle.commit()


@pytest.fixture()
def made(client):
    """One recorded discrimination run on the SME champion, then removed."""
    keys: list[str] = []

    def run(model_id: str = "sme_champion",
            category: str = "discrimination", **params):
        response = client.post(f"{API}/models/{model_id}/categories/{category}",
                               params=params, headers=ANALYST)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded"] is True, body["recorded_note"]
        keys.append(body["run_key"])
        return body

    yield run
    _sweep(keys)


# ============================================================ SCV-RUN-001/005


class TestTheRunIsWrittenDown:

    def test_running_tests_returns_a_run_key(self, made):
        body = made()
        assert body["run_key"].startswith("SCVR-sme_champion-")
        assert "will not change" in body["recorded_note"]

    def test_the_run_records_what_it_tested_and_against_what(
            self, client, made):
        key = made()["run_key"]
        head = client.get(f"{API}/runs/{key}", headers=ANALYST).json()

        # The model, at the version it was then.
        assert head["model_id"] == "sme_champion"
        assert head["model_version"]
        assert head["model_kind"] == "CHAMPION"

        # The data, identified rather than described.
        assert head["dataset"]
        assert head["dataset_as_of"]
        assert head["dataset_version"]

        # The scope somebody asked for.
        assert head["scope"] == "CATEGORY"
        assert head["requested_categories"] == ["discrimination"]

        # The code that produced it — five versions, not one, because these
        # move independently and a comparison has to name which one moved.
        for field in ("registry_version", "threshold_profile_version",
                      "calculation_version", "states_version",
                      "findings_version"):
            assert head[field], f"{field} was not recorded"

        # Who, when, and how.
        assert head["source"] == "UI"
        assert head["status"] == "COMPLETE"
        assert head["started_at"] and head["finished_at"]

    def test_a_result_carries_its_whole_context(self, client, made):
        key = made()["run_key"]
        body = client.get(f"{API}/runs/{key}", headers=ANALYST).json()
        auc = next(r for r in body["results"] if r["test_id"] == "DISC-AUC")

        assert auc["value"] is not None
        assert auc["limit"] is not None
        assert auc["limit_source"]
        assert auc["observations"] > 0
        assert auc["excluded"] > 0, (
            "the rows outside the tested cohort are part of the evidence")
        assert auc["score_direction"] in ("HIGHER_SCORE_IS_BETTER",
                                          "LOWER_SCORE_IS_BETTER")
        assert auc["chart"]["kind"] == "roc"
        assert auc["chart"]["roc"], "the chart is stored, not re-derived"
        assert auc["period"]
        assert auc["method"]

    def test_a_refused_test_stores_its_reason_and_no_number(
            self, client, made):
        """The whole point of a nullable value column, from the outside.

        A run that stored 0.0 for a test that could not run would come back out
        of the database as a measurement, and nothing downstream could tell the
        difference between "the default rate is zero" and "we did not look".
        """
        key = made(category="implementation")["run_key"]
        body = client.get(f"{API}/runs/{key}", headers=ANALYST).json()
        refused = [r for r in body["results"] if not r["measured"]]
        assert refused, (
            "the implementation category refuses on this data — a run where "
            "nothing refused is not evidence for what this test asserts")
        for row in refused:
            assert row["value"] is None, (
                f"{row['test_id']} refused but stored {row['value']}")
            assert row["detail"], f"{row['test_id']} refused without saying why"


# ================================================================ SCV-RUN-002


class TestAStoredRunDoesNotMove:

    def test_reading_a_run_cannot_reach_the_runner(
            self, client, made, monkeypatch):
        """Read a stored run with the calculation engine sabotaged.

        If the read path recomputed anything at all this raises. It passing is
        the evidence that a historical run is assembled from rows.
        """
        key = made()["run_key"]
        before = client.get(f"{API}/runs/{key}", headers=ANALYST).json()

        from backend.scorecard.validation import runner

        def refuse(*args, **kwargs):
            raise AssertionError(
                "reading a stored run recalculated something")

        monkeypatch.setattr(runner, "run", refuse)
        monkeypatch.setattr(runner, "run_category", refuse)
        monkeypatch.setattr(runner, "population", refuse)

        after = client.get(f"{API}/runs/{key}", headers=ANALYST).json()
        assert after["results"] == before["results"]
        assert after["findings"] == before["findings"]

    def test_two_reads_of_one_run_are_identical(self, client, made):
        key = made()["run_key"]
        first = client.get(f"{API}/runs/{key}", headers=ANALYST).json()
        second = client.get(f"{API}/runs/{key}", headers=ANALYST).json()
        assert first == second

    def test_the_run_says_out_loud_that_it_is_historical(self, client, made):
        key = made()["run_key"]
        body = client.get(f"{API}/runs/{key}", headers=ANALYST).json()
        assert "read back unchanged" in body["historical"]
        assert "not a recalculation" in body["historical"]


# ============================================================ SCV-RUN-003/004


class TestRunningAgainMakesANewRun:

    def test_a_second_run_leaves_the_first_alone(self, client, made):
        first = made()["run_key"]
        before = client.get(f"{API}/runs/{first}", headers=ANALYST).json()
        second = made()["run_key"]
        assert second != first
        after = client.get(f"{API}/runs/{first}", headers=ANALYST).json()
        assert after == before

    def test_duplicate_returns_the_question_not_the_answer(self, client, made):
        key = made()["run_key"]
        body = client.get(f"{API}/runs/{key}/duplicate",
                          headers=ANALYST).json()
        config = body["configuration"]
        assert config["model_id"] == "sme_champion"
        assert config["scope"] == "CATEGORY"
        assert config["categories"] == ["discrimination"]
        assert config["duplicated_from_key"] == key
        assert "results" not in config
        assert "NEW run" in body["means"]

    def test_a_re_run_records_what_it_repeats(self, client):
        """`duplicate_of` builds the chain without touching the earlier run."""
        keys: list[str] = []
        try:
            first = client.post(
                f"{API}/models/retail_application_champion/categories/"
                "discrimination", headers=ANALYST).json()
            keys.append(first["run_key"])
            before = client.get(f"{API}/runs/{first['run_key']}",
                                headers=ANALYST).json()

            again = client.post(
                f"{API}/models/retail_application_champion/run",
                params={"duplicate_of": first["run_key"]},
                headers=ANALYST).json()
            keys.append(again["run_key"])

            assert again["run_key"] != first["run_key"]
            after = client.get(f"{API}/runs/{first['run_key']}",
                               headers=ANALYST).json()
            assert after == before
        finally:
            _sweep(keys)

    def test_naming_a_predecessor_that_does_not_exist_is_refused(
            self, client):
        """A broken lineage nobody was told about is worse than no lineage."""
        response = client.post(
            f"{API}/models/sme_champion/categories/discrimination",
            headers=ANALYST)
        assert response.status_code == 200
        _sweep([response.json()["run_key"]])

        missing = client.post(
            f"{API}/models/sme_champion/run",
            params={"duplicate_of": f"SCVR-sme_champion-{uuid.uuid4().hex[:12]}"},
            headers=ANALYST)
        assert missing.status_code == 404


# ============================================================ SCV-RUN-007/008


class TestTheHistoryAndTheComparison:

    def test_history_lists_what_a_list_screen_needs(self, client, made):
        key = made()["run_key"]
        body = client.get(f"{API}/runs", params={"model_id": "sme_champion"},
                          headers=ANALYST).json()
        assert body["total"] >= 1
        row = next(r for r in body["runs"] if r["run_key"] == key)
        for field in ("model_name", "model_version", "started_at", "dataset",
                      "dataset_as_of", "scope", "initiated_by", "status",
                      "findings_summary", "measured", "returned"):
            assert field in row, f"the history row has no {field}"
        assert "results" not in row, (
            "a history row carrying forty-eight results is a page of megabytes")

    def test_history_filters_to_one_model(self, client, made):
        made()
        body = client.get(f"{API}/runs", params={"model_id": "sme_champion"},
                          headers=ANALYST).json()
        assert {r["model_id"] for r in body["runs"]} == {"sme_champion"}

    def test_history_refuses_a_model_outside_the_three(self, client):
        assert client.get(f"{API}/runs", params={"model_id": "ifrs9_ecl"},
                          headers=ANALYST).status_code in (403, 404)

    def test_two_runs_compare_without_recalculating_either(
            self, client, made, monkeypatch):
        older = made()["run_key"]
        newer = made()["run_key"]

        from backend.scorecard.validation import runner

        def refuse(*args, **kwargs):
            raise AssertionError("a comparison recalculated a run")

        monkeypatch.setattr(runner, "run_category", refuse)
        monkeypatch.setattr(runner, "population", refuse)

        body = client.get(f"{API}/runs/{older}/compare/{newer}",
                          headers=ANALYST).json()
        assert body["before"]["run_key"] == older
        assert body["after"]["run_key"] == newer
        assert body["comparable"] is True
        assert body["data_moved"] is False
        assert body["tests"], "a comparison with no rows compared nothing"

    def test_a_run_cannot_be_compared_with_itself(self, client, made):
        key = made()["run_key"]
        response = client.get(f"{API}/runs/{key}/compare/{key}",
                              headers=ANALYST)
        assert response.status_code == 422

    def test_two_models_are_not_a_change_over_time(self, client, made):
        sme = made()["run_key"]
        retail = made(model_id="retail_application_champion")["run_key"]
        response = client.get(f"{API}/runs/{sme}/compare/{retail}",
                              headers=ANALYST)
        assert response.status_code == 422
        assert "different scorecards" in response.json()["detail"]["message"]

    def test_an_unknown_run_is_a_404_not_an_empty_page(self, client):
        response = client.get(f"{API}/runs/SCVR-sme_champion-000000000000",
                              headers=ANALYST)
        assert response.status_code == 404


# ================================================================ SCV-RUN-006


class TestWhoMayDoWhat:

    def test_a_viewer_cannot_reach_the_module_at_all(self, client):
        for path in ("/runs", "/runs/SCVR-x-1", "/overview"):
            assert client.get(f"{API}{path}",
                              headers=VIEWER).status_code == 403

    def test_reading_a_run_is_not_restricted_to_its_author(
            self, client, made):
        """A run is institutional evidence, not a private working note.

        A committee, a second-line reviewer and an auditor all have to read a
        validation somebody else performed.
        """
        key = made()["run_key"]
        other = {"X-IPM-User-Id": "9", "X-IPM-Role": "ANALYST"}
        assert client.get(f"{API}/runs/{key}",
                          headers=other).status_code == 200

    def test_the_run_is_attributed_to_the_principal_not_the_body(
            self, client, made):
        key = made()["run_key"]
        head = client.get(f"{API}/runs/{key}", headers=ANALYST).json()
        assert head["initiated_by"] or head["initiated_by_role"], (
            "a run with no author is a run nobody can be asked about")


# ============================================================ SCV-RUN-009/010


@pytest.fixture(scope="module")
def full_run():
    """One whole-model run on the SME champion, shared by the report tests.

    Module-scoped because a full run is forty-eight tests over every period —
    a minute of bootstrap resampling — and running it once per test would make
    this file the slowest in the suite for no additional evidence.
    """
    from fastapi.testclient import TestClient

    from backend.api.main import app

    with TestClient(app) as handle:
        body = handle.post(f"{API}/models/sme_champion/run",
                           headers=ANALYST).json()
        assert body["recorded"] is True, body["recorded_note"]
        yield body["run_key"]
    _sweep([body["run_key"]])


class TestAReportIsBoundToItsRun:

    def test_a_draft_names_the_run_it_was_built_from(self, client, full_run):
        body = client.post(f"{API}/runs/{full_run}/report",
                           headers=ANALYST).json()
        head = body["report"]
        assert head["run_key"] == full_run
        assert head["source_run_keys"] == [full_run]
        assert head["status"] == "DRAFT"
        assert head["opinion"]
        assert full_run in body["bound_to"]

    def test_the_stored_hash_is_the_report_s_own(self, client, full_run):
        """One hash, not two under one name.

        `Report.content_hash` excludes the document-control section so it
        answers "has the assessment changed?". A second hash over the whole
        dict would answer "was this generated twice?" and disagree on every
        regeneration — and the column would be the one a reader trusted.
        """
        key = client.post(f"{API}/runs/{full_run}/report",
                          headers=ANALYST).json()["report"]["report_key"]
        stored = client.get(f"{API}/reports/{key}", headers=ANALYST).json()
        assert stored["content_hash"] == stored["document"]["content_hash"]

    def test_a_stored_report_regenerates_to_the_same_document(
            self, client, full_run, monkeypatch):
        """SCV-RUN-010, and the strict form of it.

        The .docx is rendered from the stored content with the calculation
        engine sabotaged, so a renderer that reached back for a fresh number
        would raise rather than quietly produce a different document.
        """
        key = client.post(f"{API}/runs/{full_run}/report",
                          headers=ANALYST).json()["report"]["report_key"]
        stored = client.get(f"{API}/reports/{key}", headers=ANALYST).json()

        from backend.scorecard.validation import runner

        def refuse(*args, **kwargs):
            raise AssertionError("rendering a stored report recalculated")

        monkeypatch.setattr(runner, "run", refuse)
        monkeypatch.setattr(runner, "run_category", refuse)
        monkeypatch.setattr(runner, "population", refuse)

        first = client.get(f"{API}/reports/{key}.docx", headers=ANALYST)
        assert first.status_code == 200
        assert first.headers["x-report-content-hash"] == stored["content_hash"]
        assert first.headers["x-validation-run"] == full_run

        import io
        import zipfile

        book = zipfile.ZipFile(io.BytesIO(first.content))
        assert "word/document.xml" in book.namelist()

    def test_the_download_name_cannot_escape_its_header(
            self, client, full_run):
        key = client.post(f"{API}/runs/{full_run}/report",
                          headers=ANALYST).json()["report"]["report_key"]
        disposition = client.get(f"{API}/reports/{key}.docx",
                                 headers=ANALYST).headers["content-disposition"]
        name = disposition.split('filename="')[1].rstrip('"')
        for forbidden in ('"', ";", "/", "\\", "\n", "\r", ".."):
            assert forbidden not in name, (
                f"{forbidden!r} in a Content-Disposition filename")

    def test_finalising_is_one_way(self, client, full_run):
        key = client.post(f"{API}/runs/{full_run}/report",
                          headers=ANALYST).json()["report"]["report_key"]
        signed = client.post(f"{API}/reports/{key}/finalise", headers=ANALYST)
        assert signed.status_code == 200
        assert signed.json()["report"]["status"] == "FINAL"

        again = client.post(f"{API}/reports/{key}/finalise", headers=ANALYST)
        assert again.status_code == 409
        assert "new report against a new run" in \
            again.json()["detail"]["message"]

    def test_a_new_draft_does_not_disturb_a_signed_one(
            self, client, full_run):
        first = client.post(f"{API}/runs/{full_run}/report",
                            headers=ANALYST).json()["report"]["report_key"]
        client.post(f"{API}/reports/{first}/finalise", headers=ANALYST)
        before = client.get(f"{API}/reports/{first}", headers=ANALYST).json()

        second = client.post(f"{API}/runs/{full_run}/report",
                             headers=ANALYST).json()["report"]
        assert second["report_key"] != first
        assert second["status"] == "DRAFT"

        after = client.get(f"{API}/reports/{first}", headers=ANALYST).json()
        assert after == before

    def test_a_signed_report_keeps_its_run_alive(self, client, full_run):
        """The database refuses, not a service that remembered to.

        ON DELETE RESTRICT on `scv_reports.run_id`: a run cannot be removed
        from underneath a document that is evidence of what it said.
        """
        from sqlalchemy import delete
        from sqlalchemy.exc import IntegrityError

        from backend.db.engine import get_session
        from backend.models.scorecard_validation import ScvRun

        client.post(f"{API}/runs/{full_run}/report", headers=ANALYST)
        with get_session() as handle:
            with pytest.raises(IntegrityError):
                handle.execute(
                    delete(ScvRun).where(ScvRun.run_key == full_run))
                handle.flush()
            handle.rollback()

    def test_the_signature_is_the_principal_not_a_field(
            self, client, full_run):
        key = client.post(f"{API}/runs/{full_run}/report",
                          headers=ANALYST).json()["report"]["report_key"]
        signed = client.post(f"{API}/reports/{key}/finalise",
                             json={"finalised_by": "Somebody Else"},
                             headers=ADMIN).json()["report"]
        assert signed["finalised_by"] != "Somebody Else"

    def test_drafting_a_report_needs_more_than_looking(self, client,
                                                       full_run):
        assert client.post(f"{API}/runs/{full_run}/report",
                           headers=VIEWER).status_code == 403
