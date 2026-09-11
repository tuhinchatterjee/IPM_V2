"""
The four ways a follow-up lost the conversation it was continuing.

§24 asks the same question twelve ways and checks that CONTEXT IS MODIFIED
CORRECTLY RATHER THAN DISCARDED. Four consecutive turns of one ordinary
Head-of-Retail-Risk conversation failed that, and each failed differently:

    1.  "For personal finance only, show expected credit loss by IFRS 9
         stage at August 2026."                              — answered
    2.  "How did that move since July 2026?"
    3.  "Only salary transfer customers."
    4.  "Now show all products."
    5.  "No, I meant gross carrying amount, not expected credit loss."

**Turn 2 — the measure was thrown away by the guardrail that carries it.**
The population guardrail stamps `scope_only` on a continuation, meaning "the
population came from the thread and the measure came from the sentence". It
stamped it unconditionally, including on a sentence with no measure in it, so
the planner inherited nothing and asked "Which figure should CreditProbe
measure?" — one turn after computing it. The clarification then became the
thread's pending question, turns 3 and 4 were read as answers to it, and the
conversation never recovered: three more turns of the same sentence.

**Turn 3 — a narrowing answered by the Metric Catalogue.** "Only salary
transfer customers." matched the published Salary-Transfer Share metric and
was answered with it: one number, 77.35%, in place of the measure, the
breakdown and the scope on the screen. A modification is a change to the
analysis in front of the reader, never a request for a different figure.

**Turn 4 — "all products" answered with one product.** The carried
`product_label = Personal Finance` survived into a breakdown BY product label,
so the answer was a single bar reading Personal Finance under a heading saying
BY PRODUCT. The guard for this existed and read the SENTENCE; nobody writes
"break it down by product" when they mean "now show all products".

**Turn 5 — a correction answered by addition.** The sentence names two
measures, one of them to reject, and both were computed: the rejected column
sat in the table next to the wanted one.

And one more, found isolating turn 2: `move` followed by `since` was not read
as a change at all, while `moved since` was. The same question, told apart by
its auxiliary.

Every figure below is reconciled against the Parquet book by
`tests/retail/conftest.py`'s oracle rather than against the product.
"""

from __future__ import annotations

import pytest

from backend.orchestration import conversation as cv
from backend.orchestration import memory as wm
from backend.orchestration import movement as mv
from backend.orchestration import orchestrator
from backend.orchestration import referents
from backend.orchestration.orchestrator import remember as advance
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

OPENING = ("For personal finance only, show expected credit loss by IFRS 9 "
           "stage at August 2026.")


class Thread:
    """One conversation, driven exactly as `backend/api/routers/ask.py` does."""

    def __init__(self) -> None:
        self.context: dict = {}

    def ask(self, question: str):
        state, memory = cv.load(self.context), wm.load(self.context)
        asked = question
        if state.pending and cv.answers_a_clarification(question):
            asked = f"{state.pending} {question.strip()}"
        answered = orchestrator.answer(asked, state=state, memory=memory)
        state = advance(state, answered, headline="", run_id=None)
        self.context = wm.save(cv.save(self.context, state),
                               wm.observe(wm.load(self.context), answered,
                                          None))
        return answered


def rows(answered) -> list[dict]:
    """The rows the reader is looking at, whichever route produced them.

    `runtime` is the composed analysis; `result` is what a handler — the
    Metric Catalogue among them — returned instead. Reading only one of them
    would make a gate pass because the wrong route answered.
    """
    runtime = getattr(answered, "runtime", None)
    if runtime is not None and getattr(runtime, "rows", None):
        return list(runtime.rows)
    result = getattr(answered, "result", None)
    return list(getattr(result, "rows", None) or [])


class Oracle:
    """The figures, read straight off the Parquet book.

    Independent of the product on purpose: a gate that reconciles the answer
    against the code that produced it reconciles nothing.
    """

    def __init__(self, book) -> None:
        self.frame = book.month("2026-08")

    def _scoped(self, **conditions):
        frame = self.frame
        for column, value in conditions.items():
            frame = frame[frame[column] == value]
        return frame

    def ecl_by_stage(self, **conditions) -> dict[int, float]:
        grouped = self._scoped(**conditions).groupby(
            "ifrs9_stage").ecl_final_sar.sum()
        return {int(k): round(float(v), 2) for k, v in grouped.items()}

    def gca_by_stage(self, **conditions) -> dict[int, float]:
        grouped = self._scoped(**conditions).groupby(
            "ifrs9_stage").gross_carrying_amount_sar.sum()
        return {int(k): round(float(v), 2) for k, v in grouped.items()}

    def book_ecl(self) -> float:
        return round(float(self.frame.ecl_final_sar.sum()), 2)


@pytest.fixture(scope="module")
def retail_oracle(retail_book) -> Oracle:
    return Oracle(retail_book)


def settled(answered) -> dict:
    """What this turn established, read the way the next turn will read it."""
    return advance(cv.load({}), answered, headline="", run_id=None).to_dict()


@pytest.fixture(scope="module")
def opened() -> Thread:
    thread = Thread()
    answered = thread.ask(OPENING)
    assert not answered.clarification, "the opening question must answer"
    return thread


def continued(opened: Thread, question: str):
    """The opening turn, then one follow-up, on a thread of their own."""
    thread = Thread()
    thread.context = dict(opened.context)
    return thread.ask(question)


# --------------------------------------------------------------- turn 2


class TestAFollowUpInheritsTheMeasureItPointsAt:
    def test_the_pronoun_follow_up_is_answered_not_queried(self, opened):
        answered = continued(opened, "How did that move since July 2026?")
        assert not answered.clarification, (
            "the thread had just computed expected credit loss; asking which "
            "figure to measure asks the reader to repeat themselves")

    def test_it_keeps_the_measure_the_dimension_and_the_scope(self, opened):
        state = settled(continued(opened,
                                  "How did that move since July 2026?"))
        assert state["metrics"] == ["expected credit loss"]
        assert state["dimensions"] == ["ifrs9_stage"]
        assert state["filters"] == [{"kind": "product_label",
                                     "value": "Personal Finance"}]

    def test_since_july_opens_the_window_rather_than_closing_it(self, opened):
        state = settled(continued(opened,
                                  "How did that move since July 2026?"))
        assert state["periods"] == ["2026-07", "2026-08"]

    @pytest.mark.parametrize("question", [
        "How did that move since July 2026?",
        "How has that moved since July 2026?",
        "What did that look like in July 2026?",
    ])
    def test_every_phrasing_of_the_same_follow_up_is_answered(
            self, opened, question):
        assert not continued(opened, question).clarification

    def test_the_marker_is_stamped_only_when_the_sentence_names_a_measure(self):
        assert referents.names_a_measure(
            "No, I meant gross carrying amount, not expected credit loss.")
        assert not referents.names_a_measure("How did that move since July?")


class TestMoveSinceIsAChange:
    @pytest.mark.parametrize("question", [
        "How did that move since July 2026?",
        "How did that move since 2026-07?",
        "How did that move since Q2 2025?",
        "How did that move since last quarter?",
        "How has that moved since July 2026?",
    ])
    def test_read_as_a_change(self, question):
        assert mv.asks_for_change(question)

    @pytest.mark.parametrize("sentence", [
        "move this to the project",
        "Please move since we are done",
        "Show a 12-month moving average",
    ])
    def test_the_imperative_and_the_conjunction_are_not(self, sentence):
        assert not mv.asks_for_change(sentence)


# --------------------------------------------------------------- turn 3


class TestANarrowingChangesTheAnalysisRatherThanReplacingIt:
    def test_it_is_not_answered_from_the_metric_catalogue(self, opened):
        answered = continued(opened, "Only salary transfer customers.")
        assert "Salary-Transfer Share" not in str(
            [r.get("metric") for r in rows(answered)]), (
            "a narrowing turn was answered with a published metric, which "
            "discards the measure, the breakdown and the scope on screen")

    def test_it_keeps_the_measure_the_dimension_and_the_scope(self, opened):
        state = settled(continued(opened, "Only salary transfer customers."))
        assert state["metrics"] == ["expected credit loss"]
        assert state["dimensions"] == ["ifrs9_stage"]
        assert {f["kind"] for f in state["filters"]} == {
            "product_label", "salary_transfer_flag"}

    def test_the_figures_are_the_book_s(self, opened, retail_oracle):
        answered = continued(opened, "Only salary transfer customers.")
        got = {int(r["ifrs9_stage"]): round(float(r["ecl_final_sar"]), 2)
               for r in rows(answered) if "ifrs9_stage" in r}
        want = retail_oracle.ecl_by_stage(product_label="Personal Finance",
                                          salary_transfer_flag=True)
        assert got == want


# --------------------------------------------------------------- turn 4


class TestABreakdownIsNeverPinnedToOneOfItsOwnGroups:
    def test_all_products_returns_every_product(self, opened):
        answered = continued(opened, "Now show all products.")
        products = {r.get("product_label") for r in rows(answered)}
        assert products == {"Personal Finance", "Credit Card",
                            "Home Finance", "Auto Finance"}

    def test_the_carried_restriction_is_dropped_not_intersected(self, opened):
        state = settled(continued(opened, "Now show all products."))
        assert state["filters"] == []
        assert state["dimensions"] == ["product_label"]

    def test_the_total_is_the_whole_book(self, opened, retail_oracle):
        answered = continued(opened, "Now show all products.")
        total = sum(float(r["ecl_final_sar"]) for r in rows(answered))
        assert round(total, 2) == retail_oracle.book_ecl()

    def test_the_wording_the_reader_used_is_irrelevant(self, opened):
        """The planner's own dimension settles it, not the sentence."""
        for phrasing in ("Now show all products.",
                         "Break that down by product.",
                         "Show it per product."):
            answered = continued(opened, phrasing)
            assert len({r.get("product_label") for r in rows(answered)}) == 4, (
                f"{phrasing!r} returned a breakdown of one group")


# --------------------------------------------------------------- turn 5


class TestACorrectionReplacesTheMeasureRatherThanAddingIt:
    def test_the_rejected_figure_is_not_computed(self, opened):
        answered = continued(
            opened,
            "No, I meant gross carrying amount, not expected credit loss.")
        columns = {k for r in rows(answered) for k in r}
        assert "gross_carrying_amount_sar" in columns
        assert "ecl_final_sar" not in columns, (
            "the correction was answered by adding the figure it corrected")

    def test_the_figures_are_the_book_s(self, opened, retail_oracle):
        answered = continued(
            opened,
            "No, I meant gross carrying amount, not expected credit loss.")
        got = {int(r["ifrs9_stage"]):
               round(float(r["gross_carrying_amount_sar"]), 2)
               for r in rows(answered) if "ifrs9_stage" in r}
        want = retail_oracle.gca_by_stage(product_label="Personal Finance")
        assert got == want

    @pytest.mark.parametrize("sentence,kept,dropped", [
        ("Show gross carrying amount instead of expected credit loss.",
         "gross_carrying_amount_sar", "ecl_final_sar"),
        ("Gross carrying amount rather than expected credit loss, please.",
         "gross_carrying_amount_sar", "ecl_final_sar"),
    ])
    def test_every_form_of_the_correction(self, opened, sentence, kept,
                                          dropped):
        answered = continued(opened, sentence)
        columns = {k for r in rows(answered) for k in r}
        assert kept in columns
        assert dropped not in columns

    def test_a_negated_STATE_is_a_restriction_not_a_rejection(self):
        """A bare "not" needs the comma that makes it a correction.

        "which facilities are not in default" restricts the population. Read
        as a rejected measure it would drop the restriction the reader asked
        for — a wider answer under the same heading, which is the class of
        defect this whole file is about.
        """
        from backend.orchestration import analysis_planner as ap
        from backend.orchestration import concepts as cx
        from backend.orchestration import context as governed_context
        from backend.data_access import get_catalog

        text = ("Which facilities are not in default with expected credit "
                "loss above 10,000?")
        known = {d.name: {f["name"] for f in d.fields}
                 for d in governed_context.all_datasets()}
        matches = list(cx.read_concepts(text, known=known,
                                        catalogue=get_catalog()).matches)
        assert matches, "the sentence names a governed measure"
        assert ap._rejected_measures(text, matches) == []
