"""
"Does this trend make sense?" must be answered from the result, not from a
second execution of the analysis that produced it.

Why these tests count things
-----------------------------
Every other test in this suite asserts on what came back. These assert on what
did NOT happen, because that is the whole property: the old behaviour produced
a correct-looking assessment and was wrong anyway, since it described a second
result computed a moment after the one the user was looking at.

"No governed data was rescanned for this follow-up" is a sentence the product
prints on screen. A sentence like that has to be checkable, so these tests
count calls to the three places governed data can be reached — the runtime's
single execution entry point, DuckDB itself, and the data access layer — and
require the count not to move.

They drive the endpoints the browser calls, not the orchestrator, because the
last time conversation memory was tested against internal functions it worked
in every test and failed for every user.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.conftest import database_available

HEADERS = {"X-IPM-Role": "ANALYST"}

#: The mandatory thread from §20 of the remediation brief.
GROUPED = ("For each rating grade, show average ECL coverage, average leverage "
           "and average DSCR in the latest period.")
ASSESS = "Does this trend make sense?"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_everything():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if not database_available():
        pytest.skip("Reuse threads need a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


class Counter:
    """How many times governed data was actually reached.

    Patches the three chokepoints rather than a convenience wrapper around
    them: `runtime.executor.execute` is the single entry point every analytical
    plan comes through, `DuckDBSource._run` is the single place a statement is
    executed, and `fetch`/`aggregate` are the data access layer's only reads.
    A new caller cannot get past these without being counted.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {"execute": 0, "duckdb": 0,
                                       "fetch": 0, "aggregate": 0}
        self._restore: list[tuple[Any, str, Any]] = []

    def start(self) -> None:
        from backend.data_access.duckdb_source import DuckDBSource
        from backend.runtime import executor as runtime_executor

        targets = (("execute", runtime_executor, "execute"),
                   ("duckdb", DuckDBSource, "_run"),
                   ("fetch", DuckDBSource, "fetch"),
                   ("aggregate", DuckDBSource, "aggregate"))
        for name, holder, attribute in targets:
            original = getattr(holder, attribute)
            self._restore.append((holder, attribute, original))
            setattr(holder, attribute, self._wrap(name, original))

    def _wrap(self, name: str, original: Any) -> Any:
        def counted(*args: Any, **kwargs: Any) -> Any:
            self.counts[name] += 1
            return original(*args, **kwargs)

        return counted

    def stop(self) -> None:
        for holder, attribute, original in reversed(self._restore):
            setattr(holder, attribute, original)
        self._restore.clear()

    def snapshot(self) -> dict[str, int]:
        return dict(self.counts)

    def since(self, before: dict[str, int]) -> dict[str, int]:
        return {k: self.counts[k] - before[k] for k in self.counts}


@pytest.fixture
def counter() -> Iterator[Counter]:
    found = Counter()
    found.start()
    try:
        yield found
    finally:
        found.stop()


class Thread:
    """A conversation, driven the way the browser drives one."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.id: int | None = None

    def ask(self, question: str) -> dict[str, Any]:
        if self.id is None:
            response = self.client.post(
                "/api/v1/investigations",
                json={"question": question, "ask": True}, headers=HEADERS)
            assert response.status_code in (200, 201), response.text
            body = response.json()
            self.id = body["thread"]["id"]
            return body["run"] or {}
        response = self.client.post(
            f"/api/v1/investigations/{self.id}/messages",
            json={"question": question}, headers=HEADERS)
        assert response.status_code == 200, response.text
        return response.json()["run"] or {}


def rows_of(run: dict[str, Any]) -> list[dict[str, Any]]:
    steps = run.get("steps") or []
    return ((steps[0].get("result") or {}).get("rows") or []) if steps else []


def action_of(run: dict[str, Any]) -> str:
    conversation = run.get("conversation") or {}
    return str((conversation.get("continuation") or {}).get("action") or "")


def reuse_of(run: dict[str, Any]) -> dict[str, Any]:
    return dict((run.get("mode") or {}).get("reuse") or {})


def node_types(run: dict[str, Any]) -> list[str]:
    return [str(n.get("type")) for n in (run.get("trace") or {}).get("nodes", [])]


# ---------------------------------------------------------------- the thread


def test_the_mandatory_thread_reuses_and_rescans_nothing(client, counter):
    """§20: the exact thread the brief requires, with the counts asserted."""
    thread = Thread(client)

    first = thread.ask(GROUPED)
    assert first["status"] == "succeeded", first.get("clarification")
    grouped_rows = rows_of(first)
    assert len(grouped_rows) >= 5, "the first turn must produce grouped rows"

    ran_once = counter.snapshot()
    assert ran_once["execute"] == 1, (
        "the first turn must execute the analysis exactly once")

    before = counter.snapshot()
    second = thread.ask(ASSESS)
    delta = counter.since(before)

    assert second["status"] == "succeeded", second.get("clarification")
    assert delta == {"execute": 0, "duckdb": 0, "fetch": 0, "aggregate": 0}, (
        "a question about the previous result must not reach governed data")

    assert action_of(second) == "ASSESS_PREVIOUS_RESULT"
    assert len(rows_of(second)) == len(grouped_rows), (
        "the assessment must be about the rows that were already on the table")


def test_the_assessment_is_evidence_grounded(client):
    thread = Thread(client)
    thread.ask(GROUPED)
    second = thread.ask(ASSESS)

    narrative = second["narrative"]
    said = narrative["direct_answer"]
    assert said and said != "Yes.", said
    # A conclusion, not a verdict: it names the shape, the subject and a
    # coefficient rather than answering the question with a mood.
    assert "Spearman" in said or "association" in said.lower(), said

    evidence = " ".join(narrative.get("interpretation_points") or [])
    assert "groups" in evidence, "the sample size must be stated"

    assessment = ((second["steps"][0]["result"].get("detail") or {})
                  .get("assessment") or {})
    assert assessment["conclusion"]
    assert assessment["evidence"]
    assert assessment["limitations"]
    assert assessment["next_analysis"]
    assert assessment["caveat"], "the causation caveat is not optional"
    assert "does not establish that one causes the other" in assessment["caveat"]


def test_the_assessment_does_not_claim_a_cause(client):
    thread = Thread(client)
    thread.ask(GROUPED)
    second = thread.ask(ASSESS)

    prose = " ".join([
        second["narrative"]["direct_answer"],
        second["narrative"].get("interpretation") or "",
        *(second["narrative"].get("interpretation_points") or []),
    ]).lower()
    for forbidden in (" causes ", " caused by ", " because of the ",
                      " proves that "):
        assert forbidden not in prose, f"causal overclaim: {forbidden!r}"


# ------------------------------------------------------------- the provenance


def test_the_reuse_is_recorded_with_its_source_run(client):
    thread = Thread(client)
    first = thread.ask(GROUPED)
    second = thread.ask(ASSESS)

    provenance = reuse_of(second)
    assert provenance["reused_result"] is True
    assert provenance["data_rescan"] is False
    assert provenance["derived_from_run_id"] == first["analysis_run_id"]
    assert provenance["derived_from_result_fingerprint"], (
        "a reused result must name the execution it came from")
    assert provenance["original_question"] == GROUPED
    assert provenance["original_periods"], "the assessed window must be recorded"
    assert provenance["rows_reused"] == len(rows_of(first))
    assert provenance["original_run_sha"], (
        "the build that produced the reused result must be recorded")


def test_the_population_period_and_filters_are_the_previous_turns(client):
    """A narrowed result stays narrowed when it is assessed."""
    thread = Thread(client)
    first = thread.ask(
        "For each rating grade in Contracting, show average ECL coverage and "
        "average DSCR in the latest period.")
    if first["status"] != "succeeded":
        pytest.skip("The sector-restricted grouping did not run here.")
    second = thread.ask(ASSESS)
    if second["status"] != "succeeded":
        pytest.skip(second.get("clarification"))

    previous = ((second["steps"][0]["result"].get("detail") or {})
                .get("previous") or {})
    assert previous["row_count"] == len(rows_of(first))
    assert previous["periods"] == (first["plan"]["scope"].get("to_period")
                                   and previous["periods"]), previous
    scope = second["narrative"]["scope"].lower()
    assert "contracting" in scope or any(
        "contracting" in str(f.get("value", "")).lower()
        for f in previous.get("filters") or []), (
        "an assessment must say it covers the restricted population")


def test_only_approved_kernels_run(client):
    from backend.orchestration import kernels

    thread = Thread(client)
    thread.ask(GROUPED)
    second = thread.ask(ASSESS)

    ran = reuse_of(second)["kernels"]
    assert ran, "an assessment computes something"
    assert set(ran) <= set(kernels.KERNELS), (
        f"unapproved kernels ran: {sorted(set(ran) - set(kernels.KERNELS))}")


def test_an_unapproved_kernel_cannot_run():
    """The allowlist is a boundary, not a suggestion."""
    from backend.orchestration import kernels

    with pytest.raises(kernels.NotApproved):
        kernels.run("exec", [1, 2, 3])
    with pytest.raises(kernels.NotApproved):
        kernels.run("linear_regression_with_controls", [1], [2])


# ------------------------------------------------------------------ the Trace


def test_the_trace_says_nothing_was_rescanned(client):
    thread = Thread(client)
    thread.ask(GROUPED)
    second = thread.ask(ASSESS)

    types = node_types(second)
    for required in ("PREVIOUS_RESULT", "REUSED_RESULT", "KERNEL", "RESULT"):
        assert required in types, f"{required} missing from {types}"

    nodes = {str(n.get("id")): n for n in second["trace"]["nodes"]}
    reused = nodes["reused_result"]
    assert reused["status"] == "cached", (
        "a reused step must not be shown as though it executed")
    assert "No governed data was rescanned" in str(reused["config"])

    previous = nodes["previous_result"]
    assert previous["config"]["original_question"] == GROUPED
    assert previous["config"]["result_fingerprint"]

    statistic = nodes["derived_statistic"]
    assert statistic["config"]["kernels"], "the kernels that ran are listed"
    assert statistic["config"]["approved"], "the allowlist is shown beside them"

    evidence = nodes["evidence"]
    assert evidence["config"]["causal_claim"] is False

    # No dataset, join or SQL node: none of those ran, and drawing one so the
    # picture looks full would make every genuine Trace less believable.
    for absent in ("DATASET", "JOIN", "SQL_QUERY", "MATHEMATICAL_QUERY"):
        assert absent not in types, f"{absent} on a Trace that read no data"


# ------------------------------------------------------- when it is not enough


def test_a_one_row_result_is_not_assessed(client, counter):
    """§18: say what is missing; never widen the scope to make it answerable."""
    thread = Thread(client)
    first = thread.ask("What is the total EAD in the latest quarter?")
    assert first["status"] == "succeeded", first.get("clarification")

    before = counter.snapshot()
    second = thread.ask(ASSESS)
    delta = counter.since(before)

    assert second["status"] == "needs_clarification", second["narrative"]
    assert delta == {"execute": 0, "duckdb": 0, "fetch": 0, "aggregate": 0}, (
        "an insufficient result must not be silently re-run wider")

    said = str((second.get("clarification") or {}).get("question") or "")
    assert "one aggregate row" in said, said
    assert "cannot establish an association" in said, said
    assert "expand" in said.lower(), "the analysis that WOULD answer is offered"


def test_an_explicit_expansion_does_run_a_new_analysis(client, counter):
    thread = Thread(client)
    thread.ask(GROUPED)

    before = counter.snapshot()
    widened = thread.ask("Expand the analysis to customer level.")
    delta = counter.since(before)

    assert widened["status"] in ("succeeded", "needs_clarification")
    assert delta["execute"] >= 1, (
        "an explicit request for more data must execute a new analysis")
    assert action_of(widened) != "ASSESS_PREVIOUS_RESULT"


def test_an_assessment_with_no_previous_result_asks(client, counter):
    thread = Thread(client)
    before = counter.snapshot()
    opened = thread.ask(ASSESS)
    delta = counter.since(before)

    assert opened["status"] == "needs_clarification", opened["narrative"]
    assert delta["execute"] == 0, (
        "there is nothing to assess, so nothing should have run")
    said = str((opened.get("clarification") or {}).get("question") or "")
    assert "no previous result" in said.lower(), said


# -------------------------------------------------------- presentation only


def test_a_presentation_change_computes_nothing(client, counter):
    thread = Thread(client)
    first = thread.ask("What is total EAD by sector in the latest quarter?")
    assert first["status"] == "succeeded"

    before = counter.snapshot()
    redrawn = thread.ask("Show it as a graph.")
    delta = counter.since(before)

    assert redrawn["status"] == "succeeded"
    assert delta == {"execute": 0, "duckdb": 0, "fetch": 0, "aggregate": 0}, (
        "changing how a result is shown must not recompute it")
    assert action_of(redrawn) == "MODIFY_PRESENTATION"
    assert len(rows_of(redrawn)) == len(rows_of(first))

    visual = (redrawn["steps"][0]["result"] or {}).get("visual") or {}
    assert visual.get("chart") != "table", "a graph was asked for"
    assert "table" in (visual.get("toggle") or []), (
        "the figures behind a chart are never taken away")


# ------------------------------------------------- the whole family of asks


@pytest.mark.parametrize("question", [
    "Does this trend make sense?",
    "Is that relationship consistent?",
    "What explains this pattern?",
    "Are there exceptions?",
    "Is this monotonic?",
    "How strong is the relationship?",
    "Is that conclusion supported?",
    "What should I take from this?",
])
def test_every_question_about_the_result_reuses_it(client, counter, question):
    """§14: the whole family, not just the one sentence in the brief."""
    thread = Thread(client)
    thread.ask(GROUPED)

    before = counter.snapshot()
    answered = thread.ask(question)
    delta = counter.since(before)

    assert delta["execute"] == 0, (
        f"{question!r} was answered by re-running the analysis")
    assert answered["status"] == "succeeded", answered.get("clarification")
    assert action_of(answered) == "ASSESS_PREVIOUS_RESULT"


def test_the_reuse_contract_is_the_same_whatever_read_the_question():
    """§20: the live and deterministic paths share one reuse contract.

    The route a question takes to the action differs — a live model may return
    the conversation action, and the deterministic reader derives it from the
    sentence. What happens AFTER the action is decided must not: both go
    through `orchestrator._assess_previous`, which is the only caller of
    `reuse.cached_result` and of `assessment.assess`.

    Asserted structurally rather than by running both, because this
    environment has no provider key and a test that silently skipped would be
    the exact dishonesty §36 forbids.
    """
    import inspect

    from backend.orchestration import conversation as cv
    from backend.orchestration import orchestrator, referents

    source = inspect.getsource(orchestrator.answer)
    assert "_assess_previous" in source
    # Reached from the sentence, before the model's action is consulted, so a
    # provider that reads it as a fresh ANALYSIS cannot route around reuse.
    assert source.index("_assess_previous") < source.index("_analyse(answered")

    assert cv.ASSESS_PREVIOUS_RESULT in referents._READER_OWNS, (
        "a model reading must not be able to override the reuse action")
    assert cv.ASSESS_PREVIOUS_RESULT in cv.NON_ANALYTICAL
    assert cv.ASSESS_PREVIOUS_RESULT in cv.REUSES_RESULT
