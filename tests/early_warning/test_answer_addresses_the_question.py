"""
Does the answer address the question that was asked?

Every test here comes from a pre-UAT run in which the product produced a
confident, correctly-grounded, arithmetically sound answer to a DIFFERENT
question than the one typed. That failure mode is the worst one this product
has, because nothing on screen looks wrong: the figures reconcile, the prose
reads well, and only somebody who remembers what they asked can tell.

Six of them were found in one sitting, and they shared a shape — a constraint
in the question reaching the planner and then being dropped by the layer below
it. So each test below pins the constraint, not the sentence.
"""

from __future__ import annotations

import json
import sys

import pytest

sys.path.insert(0, "/home/user/IPM_V2")

from backend.early_warning import executable as ex  # noqa: E402
from backend.early_warning import v2_service as svc  # noqa: E402
from backend.early_warning.conversation import budget as budget_mod  # noqa: E402
from backend.early_warning.conversation import normalise as norm  # noqa: E402
from backend.early_warning.conversation import pipeline as pipe  # noqa: E402
from backend.early_warning.conversation import select as sel  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def current() -> str:
    return svc.latest_period()


def _read(question: str):
    ledger = budget_mod.open_ledger()
    return norm.read(norm.clean(question, ledger=ledger), ledger=ledger)


def _band(value) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


def _rows(turn) -> list[dict]:
    return list(turn.packet.rows or []) if turn.packet else []


# ---------------------------------------------- the headline follows intent


def test_a_ranking_question_is_answered_with_the_names():
    """"Which obligors are High or Very High?" is not a portfolio question.

    The plan reads the population first as context and then ranks it. The
    packet took its headline from whichever pack came first, so the answer was
    the portfolio's average score — every time, for every ranking question,
    with the names sitting unused in the packet.
    """
    turn = pipe.answer("Which obligors are currently High or Very High?")
    assert turn.packet.intent == "ranking", turn.packet.intent
    assert turn.answer["scope"] == "ranking", turn.answer["scope"]

    rows = _rows(turn)
    assert rows, "a ranking answered with no names"
    written = " ".join(turn.answer.get("points") or [])
    assert any(str(r.get("customer_name") or "") in written for r in rows)


def test_a_movement_question_is_answered_about_the_movement():
    turn = pipe.answer("Show the 10 obligors whose Early Warning score has "
                       "risen the most over the last 12 months.")
    assert turn.packet.intent == "movement", turn.packet.intent
    assert turn.answer["scope"] == "movement", turn.answer["scope"]


def test_the_population_step_does_not_claim_the_headline_it_only_supports():
    """The population is context for these plans, and says so in its own
    rationale. A plan that also ranked, moved or diagnosed is not a
    population answer."""
    for question in ("Which obligors are currently High or Very High?",
                     "Show the 10 obligors whose Early Warning score has "
                     "risen the most over the last 12 months."):
        turn = pipe.answer(question)
        ran = [s["analysis"] for s in turn.packet.steps]
        assert "population" in ran, ran
        assert turn.packet.intent != "population", (
            f"{question!r} reported itself as a population question")


def test_a_plan_that_only_reads_the_population_still_says_so():
    """The fallback has to keep working: no over-correction."""
    turn = pipe.answer("How is the book doing?")
    assert turn.packet.intent == "population"
    assert turn.answer["scope"] in ("portfolio", "group"), turn.answer["scope"]


# ------------------------------------------------- filters are not dropped


def test_a_band_named_in_the_question_filters_the_population(current):
    """"...for obligors at High or Very High" is a filter, not decoration.

    It was read off the screen and never out of the question, so the answer
    described every obligor in every sector — right arithmetic, wider
    population, and nothing on screen to say the filter had been dropped.
    """
    request = _read("Show exposure by sector for obligors at High or Very High.")
    inherited = dict(getattr(request, "inherited_context", {}) or {})
    assert inherited.get("band") == "high_plus", inherited


def test_the_band_filter_reaches_the_rows(current):
    turn = pipe.answer("Show exposure by sector for obligors at High or Very High.")
    rows = _rows(turn)
    assert rows, "the grouping returned nothing"

    frame = svc.borrower_month(current)
    high = frame[frame["ews_band"].map(_band).isin(("HIGH", "VERY_HIGH"))]
    expected = {str(s): int(n) for s, n in high.groupby("sector").size().items()}
    got = {str(r["sector"]): int(r["obligors"]) for r in rows}
    assert got == expected, (
        "the grouping counted obligors the band filter should have excluded")


@pytest.mark.parametrize("question,want", [
    ("Which obligors are at Very High?", "VERY_HIGH"),
    ("Show me the Low risk names.", "LOW"),
])
def test_a_single_band_named_in_the_question_is_also_a_filter(question, want):
    """Asserted on the EFFECTIVE filter, not on which key carried it.

    A single band is resolved by the group resolver against the domain's own
    values and lands under its canonical column; the compound lands under
    `band`. What matters downstream is the filter the plan applies, so that
    is what this checks.
    """
    from backend.early_warning.conversation import plan as plan_mod

    inherited = dict(getattr(_read(question), "inherited_context", {}) or {})
    applied = plan_mod._population_filters(inherited, "portfolio")
    assert applied.get("ews_band") == want or applied.get("high_plus"), (
        f"{question!r} -> inherited {inherited}, applied {applied}")


def test_a_bare_band_resolves_to_the_band_the_product_headlines():
    """"HIGH" is a value of three band columns.

    The longest-token rule cannot separate them, so the winner used to be
    whichever column the level registry listed first — the classifier band —
    and "the High risk names" filtered on a band the reader had not asked
    about. A reader who names a band without qualifying it means the Early
    Warning band.
    """
    from backend.early_warning import ask as ask_mod

    found = ask_mod.resolve_group("Show me the High risk names.")
    assert found is not None
    assert found[0] == "ews_band", found


def test_a_qualified_band_still_wins_on_its_own_field():
    """No over-correction: naming the classifier band still selects it."""
    from backend.early_warning import ask as ask_mod
    from backend.early_warning import facts as ff
    from backend.early_warning import v2_service as svc

    frame = ff._with_derived(svc.borrower_month())
    only_classifier = (set(frame["classifier_band"].astype(str))
                       - set(frame["ews_band"].astype(str)))
    if not only_classifier:
        pytest.skip("no band value is unique to the classifier band here")
    value = sorted(only_classifier)[0]
    found = ask_mod.resolve_group(f"Show me the {value.title()} names.")
    assert found is not None and found[0] == "classifier_band", found


def test_the_compound_filter_wins_over_the_half_of_it_that_resolved():
    """"High or Very High" must not narrow to Very High.

    The group resolver matches "Very High" out of the phrase and records it
    as though the reader had asked for that band alone. Applying both filters
    answered for one band when two were asked for.
    """
    from backend.early_warning.conversation import plan as plan_mod

    inherited = dict(getattr(
        _read("Show exposure by sector for obligors at High or Very High."),
        "inherited_context", {}) or {})
    applied = plan_mod._population_filters(inherited, "portfolio")
    assert applied.get("high_plus") is True, applied
    assert "ews_band" not in applied, applied


# --------------------------------------------- the grouping is the grouping


@pytest.mark.parametrize("question,expected", [
    ("Show exposure by sector for obligors at High or Very High.", "sector"),
    ("Group the portfolio by internal rating.", "internal rating"),
    ("Group the portfolio by internal grade.", "internal grade"),
    ("Show the book by stage.", "stage"),
    ("What is the current Early Warning distribution by risk band?", "risk band"),
])
def test_the_grouping_phrase_stops_at_the_field(question, expected):
    """The capture ran two words and took the next one with it.

    "by sector for obligors" became the grouping "sector for", which resolves
    to nothing, so the grouping was dropped and the whole book was described.
    Two words are genuinely needed — "internal rating", "risk band" — so the
    fix is the governed registry arbitrating, not a shorter regex.
    """
    assert _read(question).requested_grouping == expected


def test_a_grouping_that_is_not_a_field_resolves_to_nothing():
    """No over-correction: an invented partition still finds no field."""
    assert _read("Break the book down by moon phase.").requested_grouping == ""


@pytest.mark.parametrize("phrase,canonical", [
    ("risk band", "ews_band"),
    ("severity band", "ews_band"),
    ("band", "ews_band"),
    ("internal grade", "internal_rating"),
    ("stage", "ifrs9_stage"),
])
def test_the_reader_s_words_for_a_grouping_resolve(phrase, canonical):
    assert ex.normalise(phrase, role=ex.GROUP_BY) == canonical
    assert ex.supports(canonical, role=ex.GROUP_BY)


def test_the_band_distribution_is_the_published_distribution(current):
    """The first question anybody asks this product."""
    turn = pipe.answer("What is the current Early Warning distribution by risk band?")
    rows = _rows(turn)
    assert rows, "no distribution was returned"

    frame = svc.borrower_month(current)
    expected = {str(b): int(n) for b, n
                in frame["ews_band"].map(_band).value_counts().items()}
    got = {_band(r["ews_band"]): int(r["obligors"]) for r in rows}
    assert got == expected, (got, expected)
    assert sum(got.values()) == len(frame)


# ------------------------------------------------------- ownership, again


@pytest.mark.parametrize("question,owner", [
    # The band names are Early Warning's own output. No other product in
    # CreditProbe assigns an obligor to a severity band, so a question that
    # filters on one is asking this product for its population.
    ("Show exposure by sector for obligors at High or Very High.", "early_warning"),
    ("Which obligors are currently High or Very High?", "early_warning"),
    # ...and a generic portfolio measure with no Early Warning vocabulary in
    # it still belongs to the Cockpit. The fix must not have swallowed that.
    ("What is Stage 2 exposure by sector?", "cockpit"),
    ("What is total exposure by sector?", "cockpit"),
    ("Show me the portfolio composition and performance.", "cockpit"),
    ("What happens to ECL if oil falls 30%?", "what_if"),
    ("What is the Gini and PSI of the corporate scorecard?", "scorecard_validation"),
])
def test_ownership_is_decided_on_the_vocabulary_that_distinguishes(question, owner):
    decided = sel.decide(question, ledger=budget_mod.open_ledger())
    assert decided.selected == owner, (
        f"{question!r} -> {decided.selected} (confidence {decided.confidence})")


def test_a_what_if_question_still_runs_no_early_warning_analysis():
    turn = pipe.answer("What happens to ECL if oil falls 30%?")
    assert turn.budget["spent"]["executions"] == 0
    assert not (set(turn.stages) & pipe.ANALYTICAL_STAGES)


# ------------------------------------------------------------ no repetition


def test_the_names_are_not_printed_twice():
    """The bolt-on sentence predates the ranking composer.

    Keeping both printed the obligors as a sentence and then again as a list.
    """
    turn = pipe.answer("Which obligors are currently High or Very High?")
    points = turn.answer.get("points") or []
    assert not any("largest exposure first" in p for p in points), points
