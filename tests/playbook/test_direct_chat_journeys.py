"""
The Direct Chat journeys, through the real application.

Every case here posts to `POST /api/v1/playbook/workspaces/{id}/messages` — the
entry point a browser uses — against the real router, the real service, the
real worker dispatch and the real database. The provider is scripted; nothing
else is. A test that called `assistant.converse` directly would prove the loop
works and say nothing about whether a user can reach it, which is the whole
question this milestone had to answer.

Mapping to the acceptance matrix: DC-01, DC-02, DC-04, DC-15, DC-21, DC-22,
DC-24, DC-27 and the interruption half of DC-31.
"""

from __future__ import annotations

import io

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="the Direct Chat journeys need the platform database")

REPORT_MD = """# Auto Loan Development Report

## 1. Scope

The model covers the auto-loan book. Weighted ECL was SAR 22.77 million.

## 2. Data

The development sample runs to 1,050 accounts.
"""


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"})
        yield c


@pytest.fixture(autouse=True)
def _clean_rows():
    """Delete only what these journeys create; never the demonstration."""
    from sqlalchemy import text

    from backend.db.engine import get_session

    tables = ("playbook_workspaces",)
    with get_session() as session:
        before = {t: session.execute(
            text(f"SELECT COALESCE(MAX(id), 0) FROM {t}")).scalar_one()
            for t in tables}
    yield
    with get_session() as session:
        for table, mark in before.items():
            session.execute(text(f"DELETE FROM {table} WHERE id > :i"),
                            {"i": mark})
        session.commit()


@pytest.fixture
def workspace(client) -> int:
    response = client.post("/api/v1/playbook/workspaces",
                           json={"title": "Auto Loan Development Report"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client, workspace: int, text: str, *, key: str, **extra) -> dict:
    response = client.post(
        f"/api/v1/playbook/workspaces/{workspace}/messages",
        json={"text": text, "idempotency_key": f"ws{workspace}:{key}", **extra})
    assert response.status_code in (200, 201), response.text
    return response.json()


def thread(client, workspace: int) -> dict:
    response = client.get(f"/api/v1/playbook/workspaces/{workspace}")
    assert response.status_code == 200, response.text
    return response.json()


# ==========================================================================


class TestAnOrdinaryQuestionStaysOrdinary:
    """DC-01. The behaviour the product could not previously express."""

    def test_a_question_is_answered_and_no_file_is_made(
            self, client, workspace, scripted_author):
        scripted_author(
            "", makes_document=False,
            chat_text="A development report explains how a model was built; a "
                      "validation report challenges it independently.")

        result = send(client, workspace, "What is the difference between a "
                                         "development and a validation report?",
                      key="q1")

        assert result["files"] == [], "no file was requested, so none was made"
        assert result["artifact_id"] is None
        assert result["version"] == 0

        body = thread(client, workspace)
        answer = body["messages"][-1]
        assert "development report explains" in answer["content"]["text"]
        assert answer["content"]["tools"] == [], (
            "the assistant reached for no tool, because none was called for")
        assert body["artifacts"] == [], "and the workspace still has no document"

    def test_the_answer_is_the_assistants_own_words(
            self, client, workspace, scripted_author):
        scripted_author("", makes_document=False,
                        chat_text="Two paragraphs, plainly put.")
        send(client, workspace, "Explain it.", key="q2")

        said = thread(client, workspace)["messages"][-1]["content"]["text"]
        assert "Two paragraphs, plainly put." in said
        assert "#" not in said, "not a document rendered into the thread"


class TestAnAttachmentDoesNotForceAFile:
    """DC-04 with DC-01: reading a source is not a reason to write a report."""

    def test_a_question_about_an_upload_is_answered_in_the_thread(
            self, client, workspace, scripted_author, committee_report_docx):
        upload = client.post(
            f"/api/v1/playbook/workspaces/{workspace}/sources",
            files={"file": ("prior.docx", io.BytesIO(committee_report_docx),
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document")},
            data={"source_role": "previous_report"})
        assert upload.status_code == 201, upload.text
        source_id = upload.json()["id"]

        scripted_author("", makes_document=False,
                        chat_text="It covers staging, coverage and overlays.")
        result = send(client, workspace, "What does this paper cover?",
                      key="a1", source_ids=[source_id])

        assert result["files"] == []
        assert thread(client, workspace)["artifacts"] == []


class TestAskingForAReportProducesRealFiles:
    """DC-15 and DC-21."""

    def test_word_and_pdf_are_written_and_downloadable(
            self, client, workspace, scripted_author):
        scripted_author(REPORT_MD, chat_text="The report is ready.",
                        chat_formats=["docx", "pdf"])

        result = send(client, workspace,
                      "Write the Auto Loan development report in Word and PDF.",
                      key="r1")

        [produced] = result["files"]
        assert sorted(produced["delivered"]) == ["docx", "pdf"]
        assert produced["failed"] == {}
        assert produced["version"] == 1

        body = thread(client, workspace)
        [artifact] = body["artifacts"]
        [version] = artifact["versions"]
        assert {f["format"] for f in version["files"]} == {"docx", "pdf"}

        # Real bytes, through the real download route.
        for file in version["files"]:
            got = client.get(
                f"/api/v1/playbook/artifact-files/{file['id']}/download")
            assert got.status_code == 200, got.text
            assert len(got.content) > 500, "a stub is not a document"
            assert got.content[:2] in (b"PK", b"%P"), (
                f"{file['format']} did not begin like one")

    def test_the_answer_and_the_document_are_different_things(
            self, client, workspace, scripted_author):
        scripted_author(REPORT_MD, chat_text="Drafted; two sections.")
        send(client, workspace, "Write it.", key="r2")

        said = thread(client, workspace)["messages"][-1]["content"]["text"]
        assert "Drafted; two sections." in said
        assert "22.77" not in said, (
            "the document's prose belongs in the file, not the message")


class TestOneFormatFailingKeepsTheOther:
    """DC-22 and chapter 16's recovery example."""

    def test_word_survives_a_pdf_that_will_not_open(
            self, client, workspace, scripted_author, monkeypatch):
        from backend.playbook import validate

        real = validate.validate

        def pdf_is_corrupt(content, fmt, doc):
            if fmt == "pdf":
                v = validate.Validation(format="pdf")
                v.fail("the generated file could not be reopened: simulated",
                       integrity=True)
                return v
            return real(content, fmt, doc)

        monkeypatch.setattr(validate, "validate", pdf_is_corrupt)
        monkeypatch.setattr("backend.playbook.service.validate.validate",
                            pdf_is_corrupt)

        scripted_author(REPORT_MD, chat_formats=["docx", "pdf"],
                        chat_text="The Word draft is ready; the PDF failed.")
        result = send(client, workspace, "Write it in Word and PDF.", key="p1")

        [produced] = result["files"]
        assert produced["delivered"] == ["docx"], "the good format survived"
        assert "pdf" in produced["failed"]
        assert "could not be reopened" in produced["failed"]["pdf"]

        body = thread(client, workspace)
        [version] = body["artifacts"][0]["versions"]
        assert {f["format"] for f in version["files"]} == {"docx"}, (
            "no download is offered for a file that was never sound")

    def test_a_content_finding_does_not_withdraw_the_file(
            self, client, workspace, scripted_author, monkeypatch):
        """The distinction the delivery rule turns on, end to end.

        A PDF that will not open is withheld. A PDF that opens but whose table
        count differs from the document is delivered with the finding against
        it — chapter 16: review findings "do not erase an otherwise safe
        draft". Without this case the two rules are indistinguishable, because
        a corrupt file fails both.
        """
        from backend.playbook import validate

        real = validate.validate

        def pdf_has_a_finding(content, fmt, doc):
            result = real(content, fmt, doc)
            if fmt == "pdf":
                result.fail("2 table(s) were expected and 1 is present.")
            return result

        monkeypatch.setattr(validate, "validate", pdf_has_a_finding)
        monkeypatch.setattr("backend.playbook.service.validate.validate",
                            pdf_has_a_finding)

        scripted_author(REPORT_MD, chat_formats=["docx", "pdf"],
                        chat_text="Both are ready; the PDF has a note.")
        result = send(client, workspace, "Write it in Word and PDF.", key="n1")

        [produced] = result["files"]
        assert sorted(produced["delivered"]) == ["docx", "pdf"], (
            "a content finding is not a reason to withhold the file")
        assert produced["failed"] == {}
        assert any("worth review" in n for n in result["notes"]), (
            "and the finding is surfaced rather than discarded")

        [version] = thread(client, workspace)["artifacts"][0]["versions"]
        assert {f["format"] for f in version["files"]} == {"docx", "pdf"}

    def test_the_retry_reuses_the_saved_document(
            self, client, workspace, scripted_author, monkeypatch):
        """Chapter 17: a conversion retry must not author the report again."""
        from backend.playbook import provider

        scripted_author(REPORT_MD, chat_formats=["docx"],
                        chat_text="Word is ready.")
        send(client, workspace, "Write it in Word.", key="c1")

        calls = {"authored": 0}
        real_author = provider.author

        def counted(**kw):
            calls["authored"] += 1
            return real_author(**kw)

        monkeypatch.setattr(provider, "author", counted)
        monkeypatch.setattr("backend.playbook.service.provider.author", counted)

        # A second turn whose scripted assistant converts rather than creates.
        state = scripted_author.state
        state["makes_document"] = False
        state["chat_text"] = "Converted."
        from backend.playbook import chat as chat_module

        seen = {}
        real_convert = chat_module._Documents.convert

        def convert(self, args):
            seen["ran"] = True
            return real_convert(self, {"formats": ["pdf"]})

        monkeypatch.setattr(chat_module._Documents, "convert", convert)

        # Drive the convert tool directly through the real turn machinery by
        # scripting the assistant to call it.
        def call_convert(client_, *, model, system, messages, tools, container,
                         purpose, role, on_delta=None, is_cancelled=None,
                         deadline=None, with_tools=False, tool_choice=None):
            used = any(
                isinstance(m.get("content"), list)
                and any(isinstance(b, dict) and b.get("type") == "tool_result"
                        for b in m["content"]) for m in messages)

            class _B:
                def __init__(self, **kw):
                    self.__dict__.update(kw)

            class _R:
                def __init__(self, content, stop):
                    self.content, self.stop_reason = content, stop
                    self.model, self._request_id = "scripted-author", "req_x"
                    self.usage = type("U", (), {"input_tokens": 0,
                                                "output_tokens": 0})()

            if not used:
                return _R([_B(type="tool_use", name="convert_document",
                              id="tu_c", input={"formats": ["pdf"]})],
                          "tool_use")
            return _R([_B(type="text", text="The PDF is ready now.")],
                      "end_turn")

        monkeypatch.setattr(provider, "_call", call_convert)
        send(client, workspace, "Now make the PDF.", key="c2")

        assert seen.get("ran") is True
        assert calls["authored"] == 0, (
            "converting an existing version must make no authoring call")

        body = thread(client, workspace)
        [version] = body["artifacts"][0]["versions"]
        assert {f["format"] for f in version["files"]} == {"docx", "pdf"}, (
            "the PDF joined the version it was converted from")
        assert version["version"] == 1, "and no second version was invented"


class TestAToolFailureIsExplainedNotHidden:

    def test_the_turn_keeps_its_answer_and_claims_no_file(
            self, client, workspace, scripted_author):
        scripted_author("", chat_text="I could not produce that document.")

        result = send(client, workspace, "Write the report.", key="f1")

        assert result["files"] == []
        answer = thread(client, workspace)["messages"][-1]["content"]
        assert "could not produce" in answer["text"]
        [tool] = answer["tools"]
        assert tool["ok"] is False
        assert thread(client, workspace)["artifacts"] == [], (
            "and nothing was written that could be mistaken for success")


class TestTheDashboardCannotStopDelivery:
    """DC-27 — the architectural acceptance test, through the real route."""

    def test_a_broken_projection_still_delivers_the_files(
            self, client, workspace, scripted_author, monkeypatch):
        from backend.playbook.intelligence import adopt

        def down(*_a, **_kw):
            raise RuntimeError("the status indexer is down")

        monkeypatch.setattr(adopt, "adopt", down)

        scripted_author(REPORT_MD, chat_text="Done.")
        result = send(client, workspace, "Write it.", key="d1")

        assert result["dashboard"]["ok"] is False, "the projection did fail"
        [produced] = result["files"]
        assert sorted(produced["delivered"]) == ["docx", "pdf"]

        body = thread(client, workspace)
        [version] = body["artifacts"][0]["versions"]
        files = version["files"]
        assert len(files) == 2
        for file in files:
            got = client.get(
                f"/api/v1/playbook/artifact-files/{file['id']}/download")
            assert got.status_code == 200, "and the download still works"

    def test_the_conversation_still_answers_with_the_dashboard_down(
            self, client, workspace, scripted_author, monkeypatch):
        from backend.playbook.intelligence import adopt

        monkeypatch.setattr(adopt, "adopt", lambda *a, **k: 1 / 0)
        scripted_author("", makes_document=False, chat_text="Still answering.")

        send(client, workspace, "A question.", key="d2")
        assert "Still answering." in (
            thread(client, workspace)["messages"][-1]["content"]["text"])


class TestReopeningKeepsEverything:
    """DC-02 and the reopen half of DC-31."""

    def test_the_thread_and_its_files_come_back(
            self, client, workspace, scripted_author):
        scripted_author(REPORT_MD, chat_text="Drafted.")
        send(client, workspace, "Write it.", key="o1")

        reopened = thread(client, workspace)
        assert [m["role"] for m in reopened["messages"]] == ["user", "assistant"]
        assert reopened["messages"][0]["content"]["text"] == "Write it."
        [version] = reopened["artifacts"][0]["versions"]
        assert len(version["files"]) == 2

    def test_a_follow_up_works_from_the_document_already_there(
            self, client, workspace, scripted_author):
        scripted_author(REPORT_MD, chat_text="Drafted.")
        send(client, workspace, "Write it.", key="o2")

        # The second turn is told what the document is; the scripted assistant
        # answers about it without making anything new.
        state = scripted_author.state
        state["makes_document"] = False
        state["chat_text"] = "It has two sections: Scope and Data."
        send(client, workspace, "What sections does it have?", key="o3")

        messages = thread(client, workspace)["messages"]
        assert "two sections" in messages[-1]["content"]["text"]
        assert len(thread(client, workspace)["artifacts"][0]["versions"]) == 1, (
            "a question about the document did not write a new version")

        # And the turn genuinely saw the document rather than guessing.
        sent = scripted_author.state["chat_calls"][-1]["messages"][-1]["content"]
        assert "Auto Loan Development Report" in sent
        assert "the document as it stands" in sent


class TestAnInterruptedAnswerIsLabelled:
    """Chapter 07: partial text is never presented as finished."""

    def test_a_truncated_reply_is_marked_and_not_called_complete(
            self, client, workspace, scripted_author, monkeypatch):
        from backend.playbook import provider

        def truncated(client_, *, model, system, messages, tools, container,
                      purpose, role, on_delta=None, is_cancelled=None,
                      deadline=None, with_tools=False, tool_choice=None):
            if on_delta:
                on_delta("The coverage ratio moved because")

            class _B:
                type = "text"
                text = "The coverage ratio moved because"

            class _R:
                content = [_B()]
                stop_reason = "max_tokens"
                model = "scripted-author"
                _request_id = "req_trunc"
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

            return _R()

        monkeypatch.setattr(provider, "_call", truncated)
        result = send(client, workspace, "Explain the movement.", key="i1")

        assert result["interrupted"] is True
        answer = thread(client, workspace)["messages"][-1]["content"]
        assert answer["interrupted"] is True
        assert answer["text"] == "The coverage ratio moved because"
        assert result["files"] == [], "and nothing was claimed to be produced"
