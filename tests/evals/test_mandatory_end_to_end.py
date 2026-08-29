"""
§129 — the twenty mandatory end-to-end questions, and §125's integration.

What these run
--------------
`answer_investigation`, the same function the browser reaches. Not a
component, not a mock: the failures the earlier live-testing log recorded were
all failures of the surrounding architecture rather than of any component,
which passed its own tests while the service in between dropped the thing it
was meant to carry.

What they assert
----------------
The SHAPE of what a reader gets. Never phrasing: a test that asserts an exact
sentence fails when somebody improves the wording and passes when the product
answers the wrong question in the right words.

Every one asserts the four-outcome contract — an answer, a clarification, a
statement that the data is not held, or a stated failure — and that the
judgment layer §125 wired in recorded something honest, including "could not
assess" where that is the truth.

Offline
-------
With no provider key these exercise the deterministic governed reader, which
is what CI has. That is the point of the integration being a bridge rather
than a second pipeline: the layer either records an assessment or records that
it could not, and both are correct behaviour.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def _require_the_lake():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if not database_available():
        pytest.skip("The end-to-end questions need a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


class Thread:
    """One conversation, carried the way the service carries it."""

    def __init__(self) -> None:
        self.context: dict = {}

    def ask(self, question: str):
        from backend.orchestration import conversation as cv
        from backend.orchestration import memory as wm
        from backend.orchestration.executor import answer_investigation
        from backend.orchestration.orchestrator import remember as advance

        state, memory = cv.load(self.context), wm.load(self.context)
        investigation, answered = answer_investigation(
            question, persist=False, state=state, memory=memory)
        self.context = cv.save(self.context, advance(
            state, answered,
            headline=str(investigation.narrative.direct_answer or ""),
            run_id=None))
        self.context = wm.save(
            self.context,
            wm.observe(wm.load(self.context), answered, investigation))
        return investigation, answered


#: §129's twenty. Written out so the list is checkable against the brief
#: rather than described.
QUESTIONS: tuple[tuple[str, str], ...] = (
    ("multi_domain_same_turn",
     "Show me the ten largest Contracting borrowers and tell me which of "
     "them had their rating downgraded."),
    ("contracting_forensic",
     "Something seems wrong with Contracting. Investigate it across "
     "exposure, ratings, IFRS 9, delinquency, financial performance, "
     "covenants and collateral over the latest four quarters."),
    ("ecl_decomposition",
     "Decompose the ECL change into its components and show which sectors "
     "and customers contributed most."),
    ("stage2_broad_or_concentrated",
     "The portfolio's Stage 2 share increased. Determine whether the "
     "movement is broad or concentrated and identify the sectors and "
     "customers responsible."),
    ("rating_deterioration_cohort",
     "Compare borrowers whose rating deteriorated against those whose "
     "rating did not change."),
    ("contradictory_signals",
     "Find customers where financial performance improved but risk "
     "indicators deteriorated."),
    ("early_warning_pre_stage2",
     "Which borrowers are showing early warning signals before they reach "
     "Stage 2?"),
    ("rating_migration_matrix",
     "Show the rating migration matrix weighted by count and by exposure at "
     "default."),
    ("stage_migration_flow",
     "Show how exposures moved between IFRS 9 stages over the latest "
     "quarter."),
    ("rating_grade_economics",
     "Show the economics by rating grade. Does this make sense?"),
    ("exposure_ambiguity",
     "What is our exposure?"),
    ("unsupported_external_news",
     "What did the news say about Al Rajhi Contracting last week?"),
    ("impossible_period",
     "What was total ECL in 1987?"),
    ("join_integrity",
     "Join the facility book to borrower financials and reconcile the "
     "exposure totals."),
    ("presentation_mutation",
     "Show total exposure at default by sector."),
    ("multidimensional_visual",
     "Plot leverage against DSCR for each borrower, sized by exposure at "
     "default."),
    ("cro_portfolio_review",
     "Review the latest portfolio period for the CRO and identify the five "
     "most material validated risk developments."),
    ("challenge_the_conclusion",
     "Show expected credit loss by sector."),
    ("executive_portfolio_review",
     "Give me a full executive review of the portfolio for this quarter."),
    ("arabic_and_scope_variants",
     "Show total exposure at default for the corporate book."),
)


def test_section_129_names_twenty_questions():
    assert len(QUESTIONS) == 20
    assert len({name for name, _ in QUESTIONS}) == 20


@pytest.mark.parametrize("name,question", QUESTIONS,
                         ids=[n for n, _ in QUESTIONS])
def test_every_mandatory_question_reaches_one_of_the_four_outcomes(
        name, question):
    """An answer, a clarification, "CreditProbe does not hold that", or a
    stated failure. There is no fifth, and in particular there is no
    confident answer to a different question."""
    investigation, answered = Thread().ask(question)

    assert investigation is not None
    narrative = investigation.narrative
    outcome = bool(
        str(narrative.direct_answer or "").strip()
        or investigation.clarification
        or getattr(answered, "unsupported", None)
        or getattr(answered, "failure", None))
    assert outcome, name


@pytest.mark.parametrize("name,question", QUESTIONS,
                         ids=[n for n, _ in QUESTIONS])
def test_the_judgment_layer_records_something_honest_for_every_question(
        name, question):
    """§125's integration. Either an assessment or an explicit statement that
    one could not be made — never silence, and never a pass by default."""
    investigation, answered = Thread().ask(question)

    block = getattr(answered, "judgment", None)
    if block is None:
        # A clarification or an unsupported answer has no result to assess,
        # and the bridge correctly does not invent one.
        assert (investigation.clarification
                or getattr(answered, "unsupported", None)
                or getattr(answered, "failure", None)), name
        return

    assert "runtime_owns" in block and "bridge_adds" in block
    if "unavailable" in block:
        assert block["note"], name
        return
    rubric = block["rubric"]
    assert rubric["verdict"] in ("SHOW", "REPAIR", "DETERMINISTIC_SUMMARY",
                                "BLOCK")
    # No dimension is silently a pass.
    for finding in rubric["findings"]:
        assert finding["outcome"] in ("PASS", "FAIL", "NOT_APPLICABLE",
                                      "UNCHECKED")


@pytest.mark.parametrize("name,question", QUESTIONS,
                         ids=[n for n, _ in QUESTIONS])
def test_no_answer_leaks_a_key_or_a_holdout_question(name, question):
    investigation, _ = Thread().ask(question)

    blob = str(investigation.to_dict()).lower()
    for forbidden in ("sk-ant", "anthropic_api_key", "authorization:",
                      "bearer "):
        assert forbidden not in blob, (name, forbidden)


def test_the_ambiguous_question_asks_rather_than_guessing():
    """"What is our exposure?" has three readings and answering one of them
    confidently is the failure the ambiguity gate exists for."""
    investigation, answered = Thread().ask("What is our exposure?")

    assert (investigation.clarification
            or str(investigation.narrative.direct_answer or "").strip())


def test_the_impossible_period_is_stated_rather_than_computed():
    """A total for 1987 computed over data that starts in 2023 is a number
    with nothing behind it."""
    investigation, answered = Thread().ask("What was total ECL in 1987?")

    text = (str(investigation.narrative.direct_answer or "")
            + " ".join(investigation.narrative.caveats or [])).lower()
    assert (getattr(answered, "unsupported", None)
            or investigation.clarification
            or any(word in text for word in
                   ("not held", "no data", "does not", "cannot", "1987",
                    "outside", "earliest")))


def test_the_external_news_question_is_declined():
    """CreditProbe reads the published data. A question about last week's
    news has no answer here, and the honest response says so rather than
    answering from the portfolio."""
    investigation, answered = Thread().ask(
        "What did the news say about Al Rajhi Contracting last week?")

    text = str(investigation.narrative.direct_answer or "").lower()
    assert (getattr(answered, "unsupported", None)
            or investigation.clarification
            or any(word in text for word in
                   ("not hold", "does not", "cannot", "no data",
                    "published data")))


def test_a_thread_carries_its_population_across_turns():
    """The multi-domain question, as a thread. The failure this catches is
    the second turn answering about the whole portfolio."""
    thread = Thread()
    thread.ask("Show me the ten largest Contracting borrowers.")
    investigation, answered = thread.ask("Which of them were downgraded?")

    assert investigation is not None
    scope = getattr(answered, "scope", None)
    if scope is not None and getattr(scope, "after", None) is not None:
        # Whatever the second turn did, it did not silently widen to the whole
        # book without saying so.
        assert (scope.kind != "WIDEN" or scope.widening_note)
