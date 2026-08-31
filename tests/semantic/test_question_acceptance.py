"""Five hundred banking questions against the governed reader. §17.

Every case is checked against the reader's INTERMEDIATE reading — the cohorts
it found, the mentions it bound, whether it believes it needs a previous
result, and which words it took for borrower names. Not the HTTP status. The
question that started this ran fine and returned 200; it had simply decided
that `Explain` was a company.

Deterministic and offline. No provider is called, no credit is spent, and the
whole corpus runs in about a second because the governed vocabulary is
retrieved once and every reader below it is pure.
"""

from __future__ import annotations

import re

import pytest

from backend.orchestration import context as ctx_mod
from backend.orchestration import conversation as cv
from backend.orchestration import discourse, entities, referents
from tests.semantic import corpus

CASES = corpus.cases()


@pytest.fixture(scope="module")
def governed():
    """The governed vocabulary. Retrieved once; the dimensions are the same
    for every question, so 544 retrievals would measure the cache."""
    return ctx_mod.retrieve("What is total exposure by sector at Q2 2026?")


# ---------------------------------------------------------------------------
# The corpus is big enough to be worth asserting things about.
# ---------------------------------------------------------------------------


def test_the_corpus_is_at_least_five_hundred_distinct_questions():
    assert len(CASES) >= 500, f"only {len(CASES)} cases"
    questions = [c.question for c in CASES]
    assert len(set(questions)) == len(questions), (
        "the corpus contains a duplicate question, so its size overstates its "
        "coverage")


def test_the_corpus_covers_distinct_structures_not_distinct_nouns():
    """§17: 'Do not create 500 trivial string variants.'

    Sixty families would already be a lot; the floor is set well below what
    the corpus has so that a future edit deleting a family fails here rather
    than quietly reducing the suite to a vocabulary test.
    """
    assert len(corpus.families()) >= 60, (
        f"only {len(corpus.families())} structural families")
    # And no single family may dominate.
    counts: dict[str, int] = {}
    for case in CASES:
        counts[case.family] = counts.get(case.family, 0) + 1
    biggest = max(counts.values())
    assert biggest <= len(CASES) * 0.1, (
        f"one family supplies {biggest} of {len(CASES)} cases")


def test_every_class_section_seventeen_names_is_present():
    tags = {tag for case in CASES for tag in case.tags}
    for wanted in ("single-turn", "same-turn", "top-n", "bottom-n", "ranking",
                   "comparison", "trend", "yoy", "period", "multi-period",
                   "sector-filter", "borrower-filter", "group", "ifrs9",
                   "sicr", "ecl", "ratings", "covenant", "collateral",
                   "financials", "delinquency", "payments", "watchlist",
                   "profitability", "macro", "stress", "concentration",
                   "connected", "early-warning", "contradictory", "clarify",
                   "entity", "multi-clause", "attribution", "proportion",
                   "negation", "conditional"):
        assert wanted in tags, f"no case is tagged {wanted!r}"


def test_the_six_reported_questions_are_present_verbatim():
    """They are the acceptance evidence. Paraphrasing them loses it."""
    assert len(corpus.REPORTED) == 6
    for case in corpus.REPORTED:
        assert case.question in {c.question for c in CASES}
    joined = " ".join(c.question for c in corpus.REPORTED)
    for phrase in ("Identify the 10 borrowers",
                   "Explain the SICR evidence for every borrower",
                   "EBITDA margins have declined",
                   "hidden deterioration",
                   "Consider cash balances",
                   "a human credit officer could easily miss"):
        assert phrase in joined, f"{phrase!r} has been edited out"


# ---------------------------------------------------------------------------
# The three properties that must hold for every question.
# ---------------------------------------------------------------------------

#: Words that are instructions or analytical vocabulary. If the reader
#: reports one of these as a borrower nobody has heard of, it has mistaken a
#: verb for a company — the defect that produced a borrower called "Explain".
_NEVER_A_BORROWER = {
    "explain", "consider", "separate", "distinguish", "identify", "find",
    "show", "rank", "compare", "summarise", "list", "which", "what", "who",
    "where", "when", "why", "how", "do", "does", "decompose", "stage",
    "sicr", "ecl", "ead", "pd", "lgd", "ebitda", "sar", "if", "for", "has",
    "have", "whose", "the",
}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.family)
def test_no_instruction_verb_is_read_as_a_borrower(case, governed):
    """The `Explain`/`Consider` regression, on every question in the corpus."""
    unknown = entities.unresolved_names(case.question, governed)
    offenders = [name for name in unknown
                 if name.strip().lower() in _NEVER_A_BORROWER]
    assert not offenders, (
        f"read {offenders} as unknown borrower name(s) in: {case.question!r}")


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.self_contained is True],
    ids=lambda c: c.family)
def test_a_self_contained_question_is_never_refused_for_want_of_context(
        case, governed):
    """The `the 10 borrowers` regression, on every self-contained question.

    `referents.unresolved` returning text is the product asking which
    borrowers were meant. On a message that defines its own population that
    is not a clarification, it is a refusal to read the sentence in front of
    it.
    """
    del governed
    state = cv.ConversationState()
    asked = referents.unresolved(case.question, state)
    assert not asked, (
        f"refused a self-contained question: {case.question!r}\n"
        f"  asked: {asked}")
    assert discourse.resolves_locally(case.question), (
        f"did not resolve locally: {case.question!r}")


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.self_contained is False],
    ids=lambda c: c.question[:40])
def test_a_genuinely_ambiguous_question_still_asks(case, governed):
    """So the test above cannot pass by resolving everything.

    A reader that never asks has not become better at reading; it has stopped
    checking. These five must still produce one useful question.
    """
    del governed
    state = cv.ConversationState()
    asked = referents.unresolved(case.question, state)
    assert asked, (
        f"resolved an ambiguous question instead of asking: {case.question!r}")
    assert not discourse.resolves_locally(case.question)


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.expect_unknown],
    ids=lambda c: c.expect_unknown)
def test_a_genuine_unknown_borrower_still_surfaces(case, governed):
    """And so the verb guard cannot pass by reporting nothing at all.

    The fix for "Explain" was a grammatical rule about sentence-initial
    capitals, not a blanket suppression. A name CreditProbe has never heard
    of, in the middle of a sentence, must still be reported — otherwise a
    question about a borrower who is not in the book is silently answered
    about the whole portfolio.
    """
    unknown = entities.unresolved_names(case.question, governed)
    assert case.expect_unknown in unknown, (
        f"{case.expect_unknown!r} was not reported as unknown in "
        f"{case.question!r}; got {unknown}")


# ---------------------------------------------------------------------------
# Named regressions from §17, each pinned on its own.
# ---------------------------------------------------------------------------


class TestTheNamedRegressions:
    """§17's explicit list, one test each."""

    def test_explain_is_never_a_borrower_after_a_question_mark(self, governed):
        question = ("Which borrowers are most likely to migrate from IFRS 9 "
                    "Stage 1 to Stage 2? Explain the SICR evidence for every "
                    "borrower and separate quantitative, qualitative and "
                    "forward-looking macroeconomic triggers.")
        assert "Explain" not in entities.unresolved_names(question, governed)

    def test_the_ten_borrowers_needs_no_previous_turn(self):
        question = ("Identify the 10 borrowers with the highest probability "
                    "of credit deterioration over the next 12 months.")
        assert discourse.resolves_locally(question)
        assert not referents.unresolved(question, cv.ConversationState())

    def test_for_each_borrower_refers_to_the_same_turn_population(self):
        question = ("Identify the 10 borrowers with the highest probability "
                    "of credit deterioration over the next 12 months. For "
                    "each borrower, explain the top five drivers.")
        read = discourse.read(question)
        assert read.cohorts, "no cohort was defined"
        assert not read.unresolved, (
            f"unresolved mentions: {[r.mention for r in read.unresolved]}")

    def test_these_borrowers_may_use_the_same_turn(self):
        question = ("Find borrowers whose leverage has increased over the "
                    "last four reporting periods. Which of these also have "
                    "covenant pressure?")
        assert discourse.resolves_locally(question)

    def test_ifrs9_terms_are_not_entity_lookups(self, governed):
        """Stage, SICR, ECL, PD, LGD and EAD are concepts, never obligors."""
        for question in (
            "Which borrowers moved from Stage 1 to Stage 2?",
            "Explain the SICR evidence for every borrower.",
            "Decompose the ECL movement into PD, LGD and EAD effects.",
            "What drove Stage 2 exposure higher?",
        ):
            unknown = {n.lower() for n in
                       entities.unresolved_names(question, governed)}
            for term in ("stage", "sicr", "ecl", "pd", "lgd", "ead",
                         "stage 1", "stage 2"):
                assert term not in unknown, (
                    f"{term!r} was read as a borrower in {question!r}")

    def test_a_number_in_a_population_is_a_count_not_an_identifier(self):
        """"the 10 borrowers" is ten of them, not borrower #10."""
        read = referents.read(
            "Identify the 10 borrowers with the highest ECL.")
        population = (read.population or "").lower()
        assert "borrower" in population or not population, (
            f"the population was read as {read.population!r}")

    def test_a_verb_that_is_also_a_measure_name_is_still_read_in_context(
            self, governed):
        """"Rank" is a verb here and a column name elsewhere."""
        assert "Rank" not in entities.unresolved_names(
            "Rank Contracting borrowers by EAD, largest first.", governed)


# ---------------------------------------------------------------------------
# The pass rate, reported rather than asserted per case.
# ---------------------------------------------------------------------------


def test_the_whole_corpus_reads_without_raising(governed):
    """Not one of 544 questions may break the reader.

    A crash here is worse than a wrong answer: a wrong answer is visible on
    the screen and a stack trace is a 500 the user cannot act on.
    """
    broken: list[str] = []
    for case in CASES:
        try:
            entities.unresolved_names(case.question, governed)
            discourse.read(case.question)
            referents.read(case.question)
            referents.unresolved(case.question, cv.ConversationState())
        except Exception as e:  # noqa: BLE001 - collecting, then failing
            broken.append(f"{case.question[:60]!r}: {type(e).__name__}: {e}")
    assert not broken, (
        f"{len(broken)} of {len(CASES)} questions broke the reader:\n"
        + "\n".join(broken[:10]))


def test_the_reader_finds_a_period_where_one_is_stated():
    """A stated period must reach the reading, or every answer is 'latest'."""
    stated = [c for c in CASES if re.search(r"Q[1-4] 20\d\d", c.question)]
    assert len(stated) >= 50, "too few cases state an explicit period"
    missed: list[str] = []
    for case in stated[:120]:
        found = discourse.read(case.question)
        text = " ".join(clause.text for clause in found.clauses)
        if not re.search(r"Q[1-4] 20\d\d", text):
            missed.append(case.question)
    assert not missed, (
        f"{len(missed)} question(s) stated a period the reading lost: "
        f"{missed[:3]}")
