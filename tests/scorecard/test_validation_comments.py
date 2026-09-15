"""§15: a comment a validator can sign, and the report that carries it.

The sentence this module protects is §15's last one: an analyst must be able
to comment on a finding, generate a report, open it in Word, find that exact
comment and reconcile its accompanying metric to the UI.

The failures it is written against are the two ways a comment on a
validation result goes wrong. It attaches to the wrong thing — written about
one run and read as though it were about the next — or it quietly becomes
the result, with somebody's opinion of a severity sitting where the measured
one should be.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL not reachable")

API = "/api/v1/scorecard-validation"
ANALYST = {"X-IPM-User-Id": "1", "X-IPM-Role": "ANALYST"}
VIEWER = {"X-IPM-User-Id": "2", "X-IPM-Role": "VIEWER"}

MODEL = "retail_beh_credit_card"


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


@pytest.fixture(scope="module")
def recorded() -> str:
    """One recorded calibration run to hang comments on.

    Module-scoped: the run is the expensive part and every test below reads
    the same one, which is also closer to how the screen behaves — one run,
    several comments.
    """
    from fastapi.testclient import TestClient

    from backend.api.main import app

    got = TestClient(app).post(
        f"{API}/models/{MODEL}/categories/calibration", headers=ANALYST)
    assert got.status_code == 200, got.text
    key = got.json().get("run_key")
    assert key, "the run was not recorded, so there is nothing to comment on"
    return key


def _post(client, recorded, **fields):
    body = {"target": "scv_result", "test_id": "CAL-OE",
            "run_key": recorded, "kind": "ANALYST",
            "body": f"note {uuid.uuid4().hex[:8]}"}
    body.update(fields)
    got = client.post(f"{API}/models/{MODEL}/comments", json=body,
                      headers=ANALYST)
    assert got.status_code == 201, got.text
    return got.json()


# ------------------------------------------------- what it is attached to


def test_a_comment_carries_the_exact_model_run_test_and_data_version(
        client, recorded) -> None:
    made = _post(client, recorded)
    context = made["context"]
    assert context["model_id"] == MODEL
    assert context["model_version"]
    assert context["run_key"] == recorded
    assert context["test_id"] == "CAL-OE"
    assert context["category"] == "calibration"
    # The data version, so a reader can tell whether the comment is about
    # the book as it stands.
    assert context["dataset"]
    assert context["dataset_as_of"]
    assert context["dataset_version"]
    assert context["calculation_version"]


def test_the_author_is_the_principal_not_the_body(client, recorded) -> None:
    """A caller that could name its own author could sign for somebody else."""
    got = client.post(
        f"{API}/models/{MODEL}/comments",
        json={"target": "scv_result", "test_id": "CAL-OE",
              "run_key": recorded, "body": "mine",
              "author": "somebody else", "author_id": 99},
        headers=ANALYST)
    assert got.status_code == 201, got.text
    assert got.json()["author_id"] == 1


def test_a_run_belonging_to_another_model_is_refused(
        client, recorded) -> None:
    got = client.post(
        f"{API}/models/retail_beh_home_loan/comments",
        json={"target": "scv_result", "test_id": "CAL-OE",
              "run_key": recorded, "body": "wrong model"},
        headers=ANALYST)
    assert got.status_code in (400, 409, 422), got.text
    assert "not of" in got.text or "another model" in got.text


def test_an_empty_comment_is_refused(client, recorded) -> None:
    got = client.post(
        f"{API}/models/{MODEL}/comments",
        json={"target": "scv_result", "test_id": "CAL-OE",
              "run_key": recorded, "body": "   "},
        headers=ANALYST)
    assert got.status_code in (400, 409, 422)


def test_a_viewer_cannot_comment_on_a_validation(client, recorded) -> None:
    """A comment here is a governance statement, not a reaction."""
    got = client.post(
        f"{API}/models/{MODEL}/comments",
        json={"target": "scv_result", "test_id": "CAL-OE",
              "run_key": recorded, "body": "looks fine"},
        headers=VIEWER)
    assert got.status_code in (401, 403)


# --------------------------------------------- it does not become the result


def test_an_authors_severity_is_labelled_as_theirs(
        client, recorded) -> None:
    """§15: a user may disagree and may not silently change a metric."""
    made = _post(client, recorded, severity="CRITICAL",
                 assessment="DISAGREED")
    assert made["severity"] == "CRITICAL"
    assert made["severity_is_the_authors"] is True
    # And the result it is attached to is untouched.
    from fastapi.testclient import TestClient

    from backend.api.main import app

    run = TestClient(app).get(f"{API}/runs/{recorded}", headers=ANALYST)
    assert run.status_code == 200
    oe = next(r for r in run.json()["results"] if r["test_id"] == "CAL-OE")
    assert oe["state"] != "CRITICAL"
    assert oe["value"] is not None


def test_a_comment_cannot_invent_an_assessment(client, recorded) -> None:
    got = client.post(
        f"{API}/models/{MODEL}/comments",
        json={"target": "scv_result", "test_id": "CAL-OE",
              "run_key": recorded, "body": "x", "assessment": "PASSED"},
        headers=ANALYST)
    assert got.status_code in (400, 409, 422)
    assert "assessment" in got.text.lower()


def test_a_comment_cannot_invent_a_kind(client, recorded) -> None:
    """The three kinds §15 separates are a closed vocabulary.

    A free-text kind is a kind that eventually reads "APPROVED", and a
    report grouping by it would print an approval nobody gave.
    """
    got = client.post(
        f"{API}/models/{MODEL}/comments",
        json={"target": "scv_result", "test_id": "CAL-OE",
              "run_key": recorded, "body": "x", "kind": "SIGNED_OFF"},
        headers=ANALYST)
    assert got.status_code in (400, 409, 422)


# ------------------------------------------------------- editing and history


def test_an_edit_keeps_what_it_said_before(client, recorded) -> None:
    first = _post(client, recorded, body="The O/E is drift.",
                  assessment="DISAGREED")
    second = client.patch(
        f"{API}/comments/{first['id']}",
        json={"body": "Revised: the gap predates this book.",
              "assessment": "ACCEPTED_WITH_ACTION"},
        headers=ANALYST)
    assert second.status_code == 200, second.text
    made = second.json()
    assert made["id"] != first["id"]
    assert made["supersedes_id"] == first["id"]

    chain = client.get(f"{API}/comments/{made['id']}/history",
                       headers=ANALYST).json()
    assert chain["edits"] == 1
    bodies = [one["body"] for one in chain["versions"]]
    assert bodies[0] == "The O/E is drift."
    assert bodies[-1].startswith("Revised")
    assert chain["versions"][0]["assessment"] == "DISAGREED"


def test_a_superseded_comment_is_not_listed_twice(
        client, recorded) -> None:
    first = _post(client, recorded, body="before")
    client.patch(f"{API}/comments/{first['id']}", json={"body": "after"},
                 headers=ANALYST)
    live = client.get(f"{API}/models/{MODEL}/comments?run_key={recorded}",
                      headers=ANALYST).json()["comments"]
    ids = [one["id"] for one in live]
    assert first["id"] not in ids
    assert any(one["body"] == "after" for one in live)


def test_editing_a_superseded_comment_is_refused(client, recorded) -> None:
    """An edit chain that forks has no current version."""
    first = _post(client, recorded, body="original")
    client.patch(f"{API}/comments/{first['id']}", json={"body": "second"},
                 headers=ANALYST)
    again = client.patch(f"{API}/comments/{first['id']}",
                         json={"body": "third"}, headers=ANALYST)
    assert again.status_code in (400, 409, 422)


def test_resolving_and_reopening(client, recorded) -> None:
    made = _post(client, recorded)
    done = client.post(f"{API}/comments/{made['id']}/resolve",
                       headers=ANALYST).json()
    assert done["resolved"] is True
    back = client.post(f"{API}/comments/{made['id']}/resolve?resolved=false",
                       headers=ANALYST).json()
    assert back["resolved"] is False


# ------------------------------------------------------- it survives, marked


def test_a_comment_from_another_run_is_shown_and_marked(
        client, recorded) -> None:
    """§15's exact requirement, and its mirror image.

    A comment must not be silently attached to a later run. Hiding it would
    be the same mistake the other way round — a reader would never learn
    that somebody had already looked at this test.
    """
    _post(client, recorded, body="about the recorded run")
    other = client.get(
        f"{API}/models/{MODEL}/comments?run_key=SCVR-some-other-run",
        headers=ANALYST).json()
    theirs = [one for one in other["comments"]
              if one["run_key"] == recorded]
    assert theirs, "the earlier comment vanished when the run changed"
    for one in theirs:
        assert one["made_against_this_run"] is False
        assert "not the run on screen" in one["run_note"]


def test_the_same_comment_is_there_after_a_reload(
        client, recorded) -> None:
    """Survives a refresh, a category switch and a restart.

    The process is not restarted here — what is checked is that nothing is
    held in memory: the row is read back through a second client with no
    shared state, which is what a refresh and a restart both reduce to.
    """
    from fastapi.testclient import TestClient

    from backend.api.main import app

    made = _post(client, recorded, body="survives")
    fresh = TestClient(app).get(
        f"{API}/models/{MODEL}/comments?run_key={recorded}",
        headers=ANALYST).json()["comments"]
    assert made["id"] in [one["id"] for one in fresh]


def test_the_run_view_carries_only_this_runs_comments(
        client, recorded) -> None:
    _post(client, recorded, body="on this run")
    got = client.get(f"{API}/runs/{recorded}/comments",
                     headers=ANALYST).json()
    assert got["comments"]
    for one in got["comments"]:
        assert one["run_key"] == recorded


# ------------------------------------------------------------- the report


def test_a_comment_reaches_the_word_document(client, recorded) -> None:
    """§15's last sentence, end to end.

    Comment on a finding, generate the report, open it in Word, find that
    exact comment.
    """
    mark = f"MARKER-{uuid.uuid4().hex[:10].upper()}"
    _post(client, recorded, target="scv_finding", test_id="",
          finding_id="F-CAL-OE", kind="APPROVER",
          assessment="ACCEPTED_WITH_ACTION", severity="HIGH",
          body=f"{mark}: continued use with a dated recalibration.")

    draft = client.post(f"{API}/runs/{recorded}/report", headers=ANALYST)
    assert draft.status_code == 200, draft.text
    key = draft.json()["report"]["report_key"]
    blob = client.get(f"{API}/reports/{key}.docx", headers=ANALYST)
    assert blob.status_code == 200, blob.text
    xml = zipfile.ZipFile(io.BytesIO(blob.content)).read(
        "word/document.xml").decode("utf-8")
    assert mark in xml, "the comment did not reach the document"
    assert "Analyst and reviewer comments" in xml
