"""
§4, §5, §68, §69 — which officer is working, and why.

The cases in `test_the_five_representative_questions` are §69's own list. They
are the acceptance test for the whole selection design: if a metadata question
gets a Chief Orchestrator or a broad multi-domain investigation gets a Credit
Analyst, the title on the screen is decoration.
"""

from __future__ import annotations

from backend.agentic import officers, registry
from backend.orchestration import routing as rt

from .conftest import FakeReading


def _select(question: str, reading: FakeReading, *, proactive: bool = False,
            demo_safe: bool = False) -> officers.Selection:
    decision = rt.decide(question, reading=reading, demo_safe=demo_safe)
    agents = registry.agents_for(reading.concepts)
    return officers.select(
        question, decision=decision, reading=reading, agents=len(agents),
        tasks=len(agents) + 1, proactive=proactive, demo_safe=demo_safe)


# ---------------------------------------------------------------- §69 cases


def test_the_five_representative_questions():
    """§69's list, with the officer each one must produce."""
    cases = [
        # "What ratings data do you have?" — a catalogue question.
        ("What ratings data do you have?",
         FakeReading(datasets=("customer_ratings",), concepts=("rating",)),
         officers.CREDIT_ANALYST),
        # "Show EAD by sector." — one measure, one grouping.
        ("Show EAD by sector.",
         FakeReading(datasets=("facilities",), concepts=("ead",),
                     grain="facility"),
         officers.CREDIT_ANALYST),
        # Two domains, two periods, borrower grain.
        ("Which customers had a downgrade and ECL increase over the latest "
         "year?",
         FakeReading(datasets=("customer_ratings", "ifrs9_staging"),
                     concepts=("rating", "ecl"),
                     periods=("Q2 2025", "Q2 2026"),
                     period_requirement="two_period"),
         officers.SENIOR_CREDIT_OFFICER),
        # Open-ended, several domains, a named segment.
        ("Something seems wrong with Contracting. Investigate it.",
         FakeReading(datasets=("facilities", "ifrs9_staging",
                               "customer_ratings"),
                     concepts=("ead", "ecl", "stage", "rating"),
                     grain="sector"),
         officers.CHIEF_ORCHESTRATOR),
        # The proactive review.
        ("Review the latest portfolio period and tell me what requires "
         "attention.",
         FakeReading(datasets=("facilities", "ifrs9_staging",
                               "customer_ratings", "delinquency"),
                     concepts=("ead", "ecl", "stage", "rating", "dpd"),
                     grain="portfolio"),
         officers.CHIEF_ORCHESTRATOR),
    ]
    for question, reading, expected in cases:
        chosen = _select(question, reading)
        assert chosen.level == expected, (
            f"{question!r} produced {chosen.title} "
            f"(score {chosen.score}) instead of "
            f"{officers.title_for(expected)}: {chosen.selection_reason}")


def test_a_segment_question_reaches_the_portfolio_risk_lead():
    """The level §69 does not name but §4 defines: segment-level work."""
    chosen = _select(
        "Which sectors had the largest Stage 2 increase this quarter?",
        FakeReading(datasets=("facilities", "ifrs9_staging"),
                    concepts=("stage", "ead"),
                    periods=("Q1 2026", "Q2 2026"),
                    period_requirement="two_period", grain="sector"))
    assert chosen.level == officers.PORTFOLIO_RISK_LEAD


# ------------------------------------------------------- no phrase rules §5


def test_the_level_is_not_a_property_of_one_word():
    """§5 forbids phrase-specific rules.

    "Look at Contracting" and "investigate Contracting" are the same work, and
    the second must not become Chief Orchestrator work purely because of the
    verb — the STRUCTURE has to carry it. Here the structure is identical and
    thin, so neither reaches level 4.
    """
    thin = FakeReading(datasets=("facilities",), concepts=("ead",))
    plain = _select("Show me Contracting exposure.", thin)
    loaded = _select("Investigate Contracting exposure.", thin)
    assert plain.level == officers.CREDIT_ANALYST
    assert loaded.level < officers.CHIEF_ORCHESTRATOR


def test_a_deterministic_request_is_always_a_credit_analyst():
    """No model call means nothing to escalate to."""
    chosen = officers.select(
        "Investigate the whole portfolio across every domain.",
        deterministic=True)
    assert chosen.level == officers.CREDIT_ANALYST
    assert "Governed services" in chosen.selection_reason


# ------------------------------------------------------------ two scores §5


def test_risk_can_reach_a_level_complexity_would_not():
    """A cheap question about something that matters gets a senior officer."""
    thin = FakeReading(datasets=("ifrs9_staging",), concepts=("ecl",))
    ordinary = _select("What is total ECL?", thin)
    material = _select(
        "What is total ECL for the provision we certify to the board?", thin)
    assert material.risk_score > ordinary.risk_score
    assert material.level > ordinary.level


def test_demo_safe_mode_raises_the_risk_score():
    thin = FakeReading(datasets=("facilities",), concepts=("ead",))
    assert (_select("Show EAD.", thin, demo_safe=True).risk_score
            > _select("Show EAD.", thin).risk_score)


def test_a_proactive_run_is_scored_as_risk_not_complexity():
    """CreditProbe acting on its own initiative is a reason for seniority even
    before anything has been counted."""
    chosen = _select("Portfolio review.",
                     FakeReading(concepts=("ead",)), proactive=True)
    assert any(r.id == "proactive" and r.kind == "risk" for r in chosen.reasons)


# ------------------------------------------------------------ coordination


def test_three_specialists_means_a_chief_orchestrator_whatever_it_scored():
    chosen = officers.select("Anything.", agents=3, tasks=4)
    assert chosen.level == officers.CHIEF_ORCHESTRATOR
    assert chosen.coordinated


def test_two_specialists_is_not_coordinated_work():
    chosen = officers.select("Anything.", agents=2, tasks=3)
    assert not chosen.coordinated


# ------------------------------------------------------------ escalation §9


def test_escalation_records_where_it_came_from():
    first = officers.select("Show EAD.", agents=1)
    later = officers.escalate(first, to=officers.PORTFOLIO_RISK_LEAD,
                              why="The plan needed a third governed domain.")
    assert later.level == officers.PORTFOLIO_RISK_LEAD
    assert later.escalated_from == first.level
    assert later.escalation_line() == "Escalating to Portfolio Risk Lead"
    assert any("third governed domain" in r.detail for r in later.reasons)


def test_escalation_never_demotes():
    """§9 shows escalation only upward. Discovering half-way through that the
    work was simpler does not take the title back off the screen."""
    senior = officers.select("Anything.", agents=3)
    same = officers.escalate(senior, to=officers.CREDIT_ANALYST, why="simpler")
    assert same.level == senior.level
    assert same.escalated_from == 0


# ---------------------------------------------------------------- contract


def test_everything_section_five_asks_to_persist_is_present():
    chosen = _select("Show EAD by sector.",
                     FakeReading(datasets=("facilities",), concepts=("ead",)))
    stored = chosen.to_dict()
    for key in ("officer_level", "officer_title", "selection_reason",
                "complexity_score", "risk_score", "agent_count",
                "planned_task_count"):
        assert key in stored, key
    assert stored["officer_title"] == officers.TITLES[stored["officer_level"]]


def test_the_status_line_is_the_one_section_four_specifies():
    for level, title in officers.TITLES.items():
        chosen = officers.Selection(level=level, title=title)
        assert chosen.status_line == f"{title} is working"


def test_the_reason_is_structured_not_prose():
    """§5: Trace must expose the structured selection reason. Every reason
    carries an id and a weight so the Trace can show the arithmetic rather than
    a sentence somebody has to trust."""
    chosen = _select(
        "Something seems wrong with Contracting. Investigate it.",
        FakeReading(datasets=("facilities", "ifrs9_staging"),
                    concepts=("ead", "ecl"), grain="sector"))
    assert chosen.reasons
    for reason in chosen.reasons:
        assert reason.id
        assert reason.kind in {"complexity", "risk"}
        assert reason.detail


def test_every_level_has_a_remit():
    for level in officers.LEVELS:
        assert officers.REMIT[level]
        assert officers.TITLES[level]
