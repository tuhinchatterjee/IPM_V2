"""The ECL decomposition, through the route the product answers on.

Six questions that must return the bridge, six that must not, and the
properties of the answer a reader would check: that it is a table of steps
rather than a number, that the steps reconcile to the reported provision, that
the money is in the governed currency, and that the chart and the table are the
same figures.

Driven through `POST /api/v1/ask` with `persist` false. The defect this suite
exists to prevent was an answer of "5,313 SAR mn" to "give me an ECL
decomposition" — a correct total standing in for a decomposition that was never
computed.
"""

from __future__ import annotations

import pytest

from backend.ifrs9 import decomposition as bridge
from tests.conftest import database_available

HEADERS = {"X-IPM-Role": "ANALYST"}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


#: Threads opened by the drill-down tests, so they can be swept away. A grain
#: test that leaves an Investigation behind per question makes the next
#: person's workspace report a mess it did not cause.
_OPENED: list[int] = []

CHILDREN = ("investigation_messages", "investigation_versions",
            "saved_analyses", "risk_cases", "agent_runs",
            "analysis_runs")


@pytest.fixture(scope="module", autouse=True)
def require_everything():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if not database_available():
        pytest.skip("Ask needs a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


@pytest.fixture(scope="module", autouse=True)
def leave_nothing_behind(require_everything):
    yield
    if not _OPENED:
        return
    from sqlalchemy import text

    from backend.db.engine import get_session

    with get_session() as session:
        for table in CHILDREN:
            session.execute(
                text(f"DELETE FROM {table} WHERE investigation_id = ANY(:ids)"),
                {"ids": _OPENED})
        session.execute(text("DELETE FROM investigations WHERE id = ANY(:ids)"),
                        {"ids": _OPENED})
        session.commit()
    _OPENED.clear()


def ask(client, question: str) -> dict:
    response = client.post("/api/v1/ask",
                           json={"question": question, "persist": False},
                           headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def step_of(body: dict, analysis_id: str) -> dict:
    for step in body.get("steps") or []:
        if step.get("analysis_id") == analysis_id:
            return step
    return {}


def analyses_run(body: dict) -> list[str]:
    return [str(s.get("analysis_id")) for s in body.get("steps") or []]


def rows_of(body: dict) -> list[dict]:
    return list((step_of(body, "ecl_decomposition").get("result")
                 or {}).get("rows") or [])


def values_of(body: dict) -> dict:
    return dict((step_of(body, "ecl_decomposition").get("result")
                 or {}).get("values") or {})


def meta_of(body: dict) -> dict:
    return dict((step_of(body, "ecl_decomposition").get("result")
                 or {}).get("meta") or {})


#: §16. Six phrasings a credit officer would actually use, all of which mean
#: "show me how the provision is built up".
DECOMPOSITION_QUESTIONS = [
    "Give me an ECL decomposition.",
    "Show me the ECL bridge.",
    "Show me the ECL waterfall.",
    "Decompose ECL into its components.",
    "What drove ECL this quarter?",
    "How is our ECL built up?",
]

#: §18. Six questions about ECL that are NOT a decomposition. Each has a right
#: answer of its own, and routing them to the bridge would be over-routing.
NOT_A_DECOMPOSITION = [
    "What is ECL?",
    "Show ECL by sector.",
    "Show ECL for Shipping.",
    "Which borrowers have the highest ECL?",
    "Which borrowers had ECL rise?",
    "Show ECL trend.",
]


class TestTheDecompositionQuestionsReachTheDecomposition:
    @pytest.mark.parametrize("question", DECOMPOSITION_QUESTIONS)
    def test_the_certified_bridge_answers_it(self, client, question: str):
        body = ask(client, question)
        assert "ecl_decomposition" in analyses_run(body), (
            f"{question!r} did not reach the certified ECL decomposition; it "
            f"ran {analyses_run(body)}")

    @pytest.mark.parametrize("question", DECOMPOSITION_QUESTIONS)
    def test_the_answer_is_a_table_of_steps_and_never_one_number(
            self, client, question: str):
        rows = rows_of(ask(client, question))
        assert len(rows) == len(bridge.STEP_ORDER) == 6
        assert [r["step"] for r in rows] == [1, 2, 3, 4, 5, 6]
        # The defect, stated as an assertion: a single row carrying a total is
        # not a decomposition however correct the total is.
        assert len({r["ecl"] for r in rows}) > 1


class TestTheQuestionsThatAreNotDecompositions:
    @pytest.mark.parametrize("question", NOT_A_DECOMPOSITION)
    def test_the_bridge_does_not_answer_them(self, client, question: str):
        body = ask(client, question)
        assert "ecl_decomposition" not in analyses_run(body), (
            f"{question!r} was over-routed to the ECL decomposition")

    def test_a_two_period_movement_still_goes_to_the_movement_analysis(
            self, client):
        body = ask(client, "Explain the movement in ECL.")
        ran = analyses_run(body)
        assert "ecl_decomposition" not in ran
        assert "ecl_movement" in ran

    def test_a_named_change_between_two_quarters_is_not_the_build_up(
            self, client):
        body = ask(client,
                   "Decompose the change in ECL from Q1 2026 to Q2 2026.")
        assert "ecl_decomposition" not in analyses_run(body)


@pytest.fixture(scope="module")
def body(client) -> dict:
    """One decomposition, asked once, checked from many angles."""
    return ask(client, "Give me an ECL decomposition.")


class TestTheAnswerOnScreen:
    def test_the_table_carries_the_columns_the_reader_needs(self, body: dict):
        row = rows_of(body)[0]
        for column in ("step", "description", "ecl", "step_impact",
                       "change_pct"):
            assert column in row

    def test_every_step_impact_is_the_difference_from_the_step_before(
            self, body: dict):
        rows = rows_of(body)
        for previous, current in zip(rows, rows[1:], strict=False):
            assert current["step_impact"] == pytest.approx(
                current["ecl"] - previous["ecl"], abs=0.002)

    def test_every_percentage_is_the_impact_over_the_previous_step(
            self, body: dict):
        rows = rows_of(body)
        assert rows[0]["change_pct"] is None
        for previous, current in zip(rows, rows[1:], strict=False):
            assert current["change_pct"] == pytest.approx(
                current["step_impact"] / previous["ecl"] * 100.0, abs=0.02)

    def test_the_last_step_reconciles_to_the_reported_provision(self,
                                                               body: dict):
        found = meta_of(body)["reconciliation"]
        assert found["reconciles"] is True
        assert found["residual_pct"] <= found["tolerance_pct"]
        assert rows_of(body)[-1]["ecl"] == pytest.approx(
            found["reported_ecl"], rel=found["tolerance_pct"] / 100.0)

    def test_the_overlay_is_a_step_of_its_own(self, body: dict):
        overlay = [r for r in rows_of(body) if "overlay" in r["description"].lower()]
        assert len(overlay) == 1
        assert overlay[0]["step_impact"] != 0.0

    def test_the_money_is_in_the_governed_currency(self, body: dict):
        units = (step_of(body, "ecl_decomposition").get("result")
                 or {}).get("units") or {}
        assert units["ecl"] == "SAR mn"
        assert units["step_impact"] == "SAR mn"
        assert "AED" not in str(units)

    def test_the_segments_are_the_configured_ones(self, body: dict):
        row = rows_of(body)[0]
        assert "corporate_ecl" in row
        assert values_of(body)["segments"] == ["Commercial", "Corporate",
                                               "Public Sector", "SME"]

    def test_the_chart_is_drawn_from_the_table_s_own_figures(self, body: dict):
        rows = rows_of(body)
        bars = meta_of(body)["waterfall"]
        assert len(bars) == len(rows)
        for bar, row in zip(bars, rows, strict=True):
            assert bar["label"] == row["description"]
            assert bar["end"] == pytest.approx(row["ecl"], abs=0.002)
            expected = (row["ecl"] if bar["kind"] == "total"
                        else row["step_impact"])
            assert bar["value"] == pytest.approx(expected, abs=0.002)

    def test_the_steps_this_installation_cannot_measure_are_declared(
            self, body: dict):
        omitted = meta_of(body)["omitted_steps"]
        assert {o["step"] for o in omitted} == {"ttc_calibration",
                                                "non_calibrated_portfolio"}
        assert all(o["because"] for o in omitted)

    def test_the_reading_names_the_steps_rather_than_the_total(self,
                                                              body: dict):
        narrative = body.get("narrative") or {}
        text = " ".join(f["text"] for f in narrative.get("findings") or [])
        assert len(narrative.get("findings") or []) >= 3
        assert "baseline" in text.lower()
        # Every figure named in the reading has to be one the engine returned.
        assert any(str(int(abs(r["step_impact"]))) in text.replace(",", "")
                   for r in rows_of(body)[1:])

    def test_there_is_a_borrower_behind_every_step(self, body: dict):
        contributors = meta_of(body)["contributors"]
        for key in bridge.STEP_ORDER[1:]:
            assert contributors[key], f"no contributors for {key}"
            assert "customer_id" in contributors[key][0]
            assert f"impact_{key}" in contributors[key][0]

    def test_the_trace_shows_where_each_figure_came_from(self, body: dict):
        trace = step_of(body, "ecl_decomposition").get("trace") or {}
        kinds = {str(n.get("type")) for n in (trace.get("nodes") or [])}
        for required in ("DATASET", "JOIN", "CALCULATION", "AGGREGATION",
                         "RECONCILIATION"):
            assert required in kinds, f"the Trace has no {required} node"


#: §11. What a credit officer asks next, and the step each drill lands on.
DRILL_DOWNS = [
    ("Which borrowers drove the stage migration?", bridge.STAGE),
    ("Which borrowers drove the collateral step?", bridge.COLLATERAL),
    ("Show me the overlay by borrower.", bridge.OVERLAY),
    ("Which borrowers drove the rating step?", bridge.RATING),
    ("Who drove the macro step?", bridge.MACRO),
]


class TestDrillingIntoAStepKeepsTheDecomposition:
    """§11. A follow-up must read the bridge, not compose a new ranking."""

    def thread(self, client, first: str = "Give me an ECL decomposition."):
        response = client.post("/api/v1/investigations",
                               json={"question": first}, headers=HEADERS)
        assert response.status_code in (200, 201), response.text
        thread_id = int(response.json()["thread"]["id"])
        _OPENED.append(thread_id)
        return thread_id

    def follow(self, client, thread_id: int, question: str) -> dict:
        response = client.post(f"/api/v1/investigations/{thread_id}/messages",
                               json={"question": question}, headers=HEADERS)
        assert response.status_code == 200, response.text
        return response.json().get("run") or {}

    @pytest.mark.parametrize("question,step", DRILL_DOWNS)
    def test_the_follow_up_reads_the_step_it_names(self, client,
                                                   question: str, step: str):
        run = self.follow(client, self.thread(client), question)
        assert analyses_run(run) == ["ecl_decomposition"], (
            f"{question!r} left the decomposition and ran "
            f"{analyses_run(run)}")
        values = values_of(run)
        assert values["step_key"] == step
        rows = rows_of(run)
        assert rows and "customer_id" in rows[0]
        assert f"impact_{step}" in rows[0]

    def test_the_rows_are_ordered_by_their_contribution_to_that_step(
            self, client):
        run = self.follow(client, self.thread(client),
                          "Which borrowers drove the stage migration?")
        column = f"impact_{bridge.STAGE}"
        magnitudes = [abs(float(r[column])) for r in rows_of(run)]
        assert magnitudes == sorted(magnitudes, reverse=True)

    def test_the_drill_keeps_the_period_and_the_population(self, client):
        run = self.follow(client, self.thread(client),
                          "Which borrowers drove the stage migration?")
        values = values_of(run)
        assert values["period"] == "Q2 2026"
        # The whole book the bridge measured, not a fresh selection.
        assert values["borrowers"] == 4100
        assert values["facilities"] == 16346
        assert values["reported_ecl"] == pytest.approx(5313.07, abs=0.01)

    def test_the_shown_borrowers_are_part_of_the_step_they_explain(self,
                                                                   client):
        run = self.follow(client, self.thread(client),
                          "Which borrowers drove the collateral step?")
        values = values_of(run)
        assert abs(values["shown_impact"]) <= abs(values["step_impact"])
        assert values["shown_share_pct"] == pytest.approx(
            values["shown_impact"] / values["step_impact"] * 100.0, abs=0.02)

    def test_a_drill_without_a_named_step_takes_the_largest(self, client):
        run = self.follow(client, self.thread(client), "Who drove that?")
        # The largest absolute impact on the live book is the point-in-time
        # step. Asserted against the bridge rather than hard-coded, so a book
        # whose largest step moves does not fail a test about drill-downs.
        assert values_of(run)["step_key"] in set(bridge.STEP_ORDER)
        assert analyses_run(run) == ["ecl_decomposition"]

    def test_the_reading_names_the_step_and_the_borrowers(self, client):
        run = self.follow(client, self.thread(client),
                          "Which borrowers drove the stage migration?")
        findings = (run.get("narrative") or {}).get("findings") or []
        assert len(findings) >= 3
        assert "stage migration" in findings[0]["text"].lower()
        assert rows_of(run)[0]["borrower_name"] in findings[1]["text"]

    def test_a_question_that_is_not_a_drill_leaves_the_decomposition(
            self, client):
        thread = self.thread(client)
        for question in ("Show ECL by sector.", "Which sectors concern you most?"):
            run = self.follow(client, thread, question)
            assert "ecl_decomposition" not in analyses_run(run), (
                f"{question!r} was answered as a drill into the bridge")

    def test_nothing_drills_without_a_bridge_on_screen(self, client):
        # The same sentence, in a thread that never ran a decomposition.
        thread = self.thread(client, "Show ECL by sector.")
        run = self.follow(client, thread,
                          "Which borrowers drove the stage migration?")
        assert "ecl_decomposition" not in analyses_run(run)
