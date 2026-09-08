"""
A conversation, rather than a series of unrelated questions.

What continuity actually has to carry
--------------------------------------
    "How is Contracting doing?"
    "Which names drive it?"
    "Open the weakest one."
    "Why did its score move?"
    "Show the evidence."
    "What should I do?"
    "Escalate it."

Not one of those after the first is a complete question. "it", "its", "the
weakest one", "the evidence" — each resolves only against what came before,
and a product that answers them from zero either guesses or refuses. Both are
worse than remembering.

Two stores, on purpose
----------------------
The rolling summary carries the ANALYTICAL context — which population, which
month, which obligor, what was established. The UI state carries the
NAVIGATION context — the filters, the selection, the URL. They are separate
because rebuilding a screen from a prose summary is guesswork, and the URL
already knows exactly where the reader is.

These tests drive the thread the way a reader would, feeding each turn's
summary into the next, and assert that the references resolve.
"""

from __future__ import annotations

import pytest

from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import summary as summary_mod


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def a_real_group() -> str:
    """A group value the book actually contains."""
    from backend.early_warning import v2_service as svc

    frame = svc.borrower_month()
    counts = frame["sector"].value_counts()
    return str(counts.index[0])


def _thread(questions: list[str], *, ui_state=None):
    """Run a thread, carrying the summary forward the way the app does."""
    turns = []
    summary: dict | None = None
    state = dict(ui_state or {})
    for question in questions:
        turn = pipe.answer(question, thread_id="t-1",
                           ui_state=state, rolling_summary=summary)
        summary = turn.rolling_summary.to_dict() if turn.rolling_summary else None
        # The screen follows the answer, exactly as the UI does.
        if turn.packet is not None:
            for key in ("customer_id", "customer_name"):
                value = turn.packet.figures.get(key)
                if value:
                    state[key] = str(value)
        turns.append(turn)
    return turns, summary


def test_the_summary_carries_the_obligor_forward(a_real_group):
    """"Escalate it" three turns later still knows what "it" is."""
    from backend.early_warning import v2_service as svc

    frame = svc.borrower_month()
    worst = str(frame.sort_values("ews_score", ascending=False)
                .iloc[0]["customer_name"])

    turns, summary = _thread([
        f"How is {a_real_group} doing?",
        f"Why is {worst} flagged?",
        "What should I do?",
        "Escalate it.",
    ])
    assert summary is not None
    assert summary["customer_name"] == worst, (
        f"the thread lost the obligor: {summary['customer_name']!r}")
    # And the later turns answered ABOUT that obligor rather than about the
    # book they started from.
    assert worst in turns[-2].answer.get("direct", "") + \
        turns[-2].answer.get("interpretation", "")


def test_a_pronoun_with_nothing_behind_it_is_asked_about_not_guessed():
    """A first turn that says only "it" has no referent and must say so."""
    from backend.early_warning.conversation import normalise as norm

    request = norm.read(norm.clean("Why did its score move?"))
    assert request.clarification_needed, (
        "a pronoun with no thread and no screen was resolved anyway")
    assert request.ambiguities


def test_the_screen_resolves_a_pronoun_the_sentence_cannot():
    from backend.early_warning.conversation import normalise as norm
    from backend.early_warning import v2_service as svc

    frame = svc.borrower_month()
    row = frame.sort_values("ews_score", ascending=False).iloc[0]
    request = norm.read(
        norm.clean("Why did its score move?"),
        ui_state={"customer_id": str(row["customer_id"]),
                  "customer_name": str(row["customer_name"])})
    assert not request.clarification_needed
    assert request.inherited_context["customer_id"] == str(row["customer_id"])


def test_a_named_obligor_outranks_the_one_on_screen():
    """A reader who typed a name is asking about that name."""
    from backend.early_warning.conversation import normalise as norm
    from backend.early_warning import v2_service as svc

    frame = svc.borrower_month().sort_values("ews_score", ascending=False)
    on_screen, typed = frame.iloc[0], frame.iloc[1]
    request = norm.read(
        norm.clean(f"Why is {typed['customer_name']} flagged?"),
        ui_state={"customer_id": str(on_screen["customer_id"]),
                  "customer_name": str(on_screen["customer_name"])})
    assert request.inherited_context["customer_id"] == str(typed["customer_id"])


def test_the_summary_records_what_was_established_not_every_word():
    turns, summary = _thread(["Why has portfolio EWS deteriorated?"])
    assert summary["confirmed"], "nothing was carried forward as established"
    # Bounded: a summary that grew with the thread would make every turn pay
    # for every turn before it.
    assert len(summary["confirmed"]) <= summary_mod.RECENT_TURNS


def test_the_summary_carries_the_next_drills():
    turns, summary = _thread(["Why has portfolio EWS deteriorated?"])
    assert summary["next_drills"], (
        "the thread carries no next drill, so a follow-up starts from zero")


def test_navigation_state_is_not_rebuilt_from_prose():
    """The two stores stay separate.

    The summary is the analytical context. The filters and the selection are
    navigation, and they travel as structured UI state — a screen rebuilt by
    reading a paragraph is a screen that is sometimes wrong.
    """
    turns, summary = _thread(
        ["Why has portfolio EWS deteriorated?"],
        ui_state={"band": "HIGH", "level": "internal_rating"})
    assert "band" not in summary or summary.get("band") in ("", "HIGH")
    # The summary does not claim to hold the URL.
    assert "level" not in summary


def test_a_redirect_does_not_lose_the_thread():
    """The reader asked something else mid-thread. The context survives it."""
    from backend.early_warning import v2_service as svc

    worst = str(svc.borrower_month().sort_values("ews_score", ascending=False)
                .iloc[0]["customer_name"])
    turns, summary = _thread([
        f"Why is {worst} flagged?",
        "What happens to ECL if oil falls 30%?",
        "What should I do?",
    ])
    assert turns[1].answer.get("redirected") is True
    assert summary["customer_name"] == worst, (
        "a redirect wiped the obligor the thread was about")


def test_sufficiency_notices_an_unanswered_half():
    """"Why has it deteriorated and is it systemic?" is two questions.

    Run the trend, get a number, write a paragraph, and the answer LOOKS
    complete while the second half was never measured. The review has to
    catch that before the prose is written.
    """
    from backend.early_warning import grain as grain_mod
    from backend.early_warning.conversation import normalise as norm
    from backend.early_warning.conversation import packet as packet_mod
    from backend.early_warning.conversation import plan as plan_mod
    from backend.early_warning.conversation import sufficiency as suff

    package = grain_mod.build("x")
    request = norm.read(norm.clean(
        "Why has Contracting deteriorated and is it systemic?"))
    assert {"diagnosis", "concentration"} <= set(request.requested_analyses)

    # A first execution that produced only the trend.
    thin = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.MOVEMENT, period=package.current_period)])
    empty = packet_mod.build("q", request, thin, [], package=package)
    reviewed = suff.review(request, thin, empty)
    assert not reviewed.complete
    assert "diagnosis" in reviewed.uncovered or \
        "concentration" in reviewed.uncovered
    assert reviewed.next_step is not None, (
        "an incomplete answer proposed no further analysis")


def test_a_multipart_question_runs_a_step_for_each_part():
    turn = pipe.answer("Why has portfolio EWS deteriorated and is it systemic?")
    ran = {s["analysis"] for s in (turn.packet.steps if turn.packet else [])}
    assert "concentration" in ran, (
        f"the 'is it systemic' half was never measured; ran {sorted(ran)}")
    assert "diagnosis" in ran, (
        f"the 'why' half was never established; ran {sorted(ran)}")


def test_a_partial_answer_says_that_it_is_partial():
    """The failure the whole review exists to prevent."""
    from backend.early_warning import grain as grain_mod
    from backend.early_warning.conversation import normalise as norm
    from backend.early_warning.conversation import packet as packet_mod
    from backend.early_warning.conversation import plan as plan_mod
    from backend.early_warning.conversation import sufficiency as suff

    package = grain_mod.build("x")
    request = norm.read(norm.clean(
        "Why has Contracting deteriorated and is it systemic?"))
    thin = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.MOVEMENT, period=package.current_period)])
    empty = packet_mod.build("q", request, thin, [], package=package)
    # No revision affordable: the honest outcome is a partial answer that
    # names what it could not cover.
    reviewed = suff.review(request, thin, empty, can_revise=False)
    assert reviewed.recommend_partial
    assert reviewed.uncovered
